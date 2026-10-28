"""Pod store round trips and CAS, in memory and through an explicit fake PG cursor.

The PG adapter exercises PgStore's record and membership-call path without
connecting, retrieving credentials or claiming database integration coverage.
"""
import copy
import sys
import types
import unittest
from contextlib import ExitStack, contextmanager
from unittest import mock

from decklab.lib import state
from decklab.lib.state import pg, rules
from decklab.lib.state.memory import MemoryStore
from decklab.tests.test_pod_model import full_record, pod, selection

ACTOR = state.Actor("test", "Test")


class PodStoreContract:
    def test_three_and_four_seat_records_round_trip_with_original_bytes_and_hash(self):
        for count in (3, 4):
            record = full_record(pod(count=count))
            record["id"] = str(count) * 32
            original = copy.deepcopy(record)
            saved = self.store.play_put("games", record, None, ACTOR, "Save fixture pod")
            record["seats"][1]["player"] = "Changed caller copy"
            loaded = self.store.play_get("games", original["id"])
            self.assertEqual(saved, original)
            self.assertEqual(loaded, original)
            self.assertEqual(rules.record_bytes(loaded), rules.record_bytes(original))
            self.assertEqual(rules.record_sha(loaded), rules.record_sha(original))

    def test_cas_allows_exact_revision_and_preserves_historical_snapshots(self):
        record = full_record()
        record["seats"][0]["deck"].update(title="Historical title", sections={"Deck": []})
        first = self.store.play_put("games", record, None, ACTOR, "Save fixture pod")
        changed = copy.deepcopy(first)
        changed.update(revision=2, result="s3", notes="Correction")
        for expected in (None, "0" * 64):
            with self.subTest(expected=expected), self.assertRaises(state.Conflict):
                self.store.play_put("games", changed, expected, ACTOR, "Reject stale correction")
            self.assertEqual(self.store.play_get("games", first["id"]), first)
        second = self.store.play_put("games", changed, rules.record_sha(first), ACTOR, "Correct fixture pod")
        self.assertEqual(second, changed)
        self.assertEqual(second["seats"][0]["deck"], first["seats"][0]["deck"])
        self.assertNotEqual(rules.record_sha(second), rules.record_sha(first))

    def test_new_record_cannot_reuse_another_record_concurrency_token(self):
        first = self.store.play_put("games", full_record(), None, ACTOR, "Save fixture pod")
        other = full_record()
        other["id"] = "c" * 32
        with self.assertRaises(state.Conflict):
            self.store.play_put("games", other, rules.record_sha(first), ACTOR, "Reject unrelated token")
        self.assertIsNone(self.store.play_get("games", other["id"]))

    def test_invalid_seats_never_replace_stored_record(self):
        first = self.store.play_put("games", full_record(), None, ACTOR, "Save fixture pod")
        changed = copy.deepcopy(first)
        changed.update(revision=2, result="s4")
        with self.assertRaises(state.Invalid):
            self.store.play_put("games", changed, rules.record_sha(first), ACTOR, "Reject invalid winner")
        self.assertEqual(self.store.play_get("games", first["id"]), first)

    def test_external_labels_are_not_indexed_as_deck_ids(self):
        record = full_record()
        record["seats"][1].update(player="user2/commander/private", commander="commander/other")
        self.store.play_put("games", record, None, ACTOR, "Save fixture pod")
        self.assertEqual(self.indexed_ids(record["id"]), ["commander/fixture"])

    def test_index_preserves_real_deck_order_and_mirrors(self):
        record = full_record(pod(count=4))
        record["seats"][1] = {"seat_id": "s2", "type": "deck", "player": "Another",
                                "deck": selection("commander/other")}
        record["seats"][3] = {"seat_id": "s4", "type": "deck", "player": "Mirror", "deck": selection()}
        self.store.play_put("games", record, None, ACTOR, "Save fixture pod")
        self.assertEqual(self.indexed_ids(record["id"]),
                         ["commander/fixture", "commander/other", "commander/fixture"])

    def test_unknown_or_partial_format_markers_are_rejected_before_mutation(self):
        for change in ({"mode": "pod", "game_version": True}, {"mode": "other"}):
            record = full_record()
            record.update(change)
            with self.subTest(change=change), self.assertRaises(state.Invalid):
                self.store.play_put("games", record, None, ACTOR, "Reject malformed pod")
            self.assertIsNone(self.store.play_get("games", record["id"]))

    def test_read_results_are_independent_copies(self):
        original = full_record()
        self.store.play_put("games", original, None, ACTOR, "Save fixture pod")
        loaded = self.store.play_list("games")
        loaded[0]["seats"][1]["commander"] = "Changed returned copy"
        self.assertEqual(self.store.play_get("games", original["id"]), original)


class MemoryPodStoreTests(PodStoreContract, unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()

    def indexed_ids(self, record_id):
        return self.store._play[("games", record_id)]["deck_ids"]

    def test_batch_rollback_restores_pod_and_audit_atomically(self):
        first = self.store.play_put("games", full_record(), None, ACTOR, "Save fixture pod")
        trail = self.store.changes()
        changed = dict(copy.deepcopy(first), revision=2, result="draw")
        with self.assertRaisesRegex(RuntimeError, "abort fixture batch"), self.store.batch(ACTOR, "Fixture batch"):
            self.store.play_put("games", changed, rules.record_sha(first), ACTOR, "Change fixture result")
            raise RuntimeError("abort fixture batch")
        self.assertEqual(self.store.play_get("games", first["id"]), first)
        self.assertEqual(self.store.changes(), trail)

    def test_one_saved_pod_has_one_audit_row(self):
        record = full_record()
        self.store.play_put("games", record, None, ACTOR, "Save fixture pod")
        changes = self.store.changes()
        self.assertEqual(len(changes), 1)
        self.assertEqual(len(changes[0]["rows"]), 1)
        self.assertEqual(changes[0]["rows"][0]["table"], "play_record")
        self.assertEqual(changes[0]["rows"][0]["after"]["content"]["seats"], record["seats"])


class FakePlayCursor:
    def __init__(self):
        self.rows = {}
        self.ids = {}
        self.events = []
        self.result = None
        self.fail_after_write = False

    def execute(self, sql, params=()):
        self.events.append(sql.split(" ", 1)[0])
        if sql.startswith("select pg_advisory_xact_lock"):
            self.result = None
        elif sql.startswith("select ") and "order by id" in sql:
            self.result = [copy.deepcopy(row) for (kind, _), row in sorted(self.rows.items()) if kind == params[0]]
        elif sql.startswith("select "):
            self.result = copy.deepcopy(self.rows.get(tuple(params)))
        elif sql.startswith(("insert into play_record", "update play_record")):
            revision, created, updated, by, ids, content, kind, record_id = params
            key = kind, record_id
            self.rows[key] = (record_id, revision, created, updated, by, copy.deepcopy(content))
            self.ids[key] = copy.deepcopy(ids)
            self.result = copy.deepcopy(self.rows[key])
            if self.fail_after_write:
                raise RuntimeError("fixture write failed")
        else:
            raise AssertionError(f"Unexpected fake-cursor SQL: {sql}")
        return self

    def fetchone(self):
        return copy.deepcopy(self.result)

    def fetchall(self):
        return copy.deepcopy(self.result)


class FakePgPodStoreTests(PodStoreContract, unittest.TestCase):
    def setUp(self):
        self.cursor = FakePlayCursor()
        self.store = pg.PgStore(dbname="fixture_never_connected", breaker=pg.Breaker())
        self.admitted = []
        self.allow_membership = True
        self.commits = 0
        stack = self.enterContext(ExitStack())
        stack.enter_context(mock.patch.object(self.store, "_call", side_effect=lambda work: work(self.cursor)))
        stack.enter_context(mock.patch.object(pg.db, "change", self.change))
        from decklab.db import space_members
        stack.enter_context(mock.patch.object(space_members, "admit", side_effect=self.admit))
        fake_json = types.ModuleType("psycopg.types.json")
        fake_json.Jsonb = lambda value: copy.deepcopy(value)
        stack.enter_context(mock.patch.dict(sys.modules, {"psycopg.types.json": fake_json}))

    @contextmanager
    def change(self, *args, **kwargs):
        before = copy.deepcopy((self.cursor.rows, self.cursor.ids))
        try:
            yield self.cursor, 1
        except BaseException:
            self.cursor.rows, self.cursor.ids = before
            raise
        else:
            self.commits += 1

    def admit(self, cur, **kwargs):
        self.assertIs(cur, self.cursor)
        self.admitted.append(copy.deepcopy(kwargs))
        self.cursor.events.append("admit")
        if not self.allow_membership:
            raise state.Invalid("fixture membership stopped")

    def indexed_ids(self, record_id):
        return self.cursor.ids[("games", record_id)]

    def test_membership_admission_receives_only_recording_space_before_any_write(self):
        record = full_record(pod(space="user2"))
        self.store.play_put("games", record, None, ACTOR, "Save fixture pod")
        self.assertEqual(self.admitted[0]["space_ids"], {"user2"})
        self.assertEqual(self.admitted[0]["profile_ids"], ())
        self.assertEqual(self.cursor.events[0], "admit")
        self.assertLess(self.cursor.events.index("admit"), self.cursor.events.index("insert"))

    def test_membership_refusal_never_writes(self):
        self.allow_membership = False
        record = full_record()
        with self.assertRaisesRegex(state.Invalid, "fixture membership stopped"):
            self.store.play_put("games", record, None, ACTOR, "Refuse fixture pod")
        self.assertEqual(self.cursor.rows, {})
        self.assertEqual(self.commits, 0)
        self.assertEqual(self.cursor.events, ["admit"])

    def test_mixed_space_record_is_rejected_before_membership_or_transaction(self):
        record = full_record()
        record["seats"][0]["deck"]["id"] = "user2/commander/fixture"
        with self.assertRaises(state.Invalid):
            self.store.play_put("games", record, None, ACTOR, "Refuse mixed pod")
        self.assertEqual(self.admitted, [])
        self.assertEqual(self.cursor.events, [])
        self.assertEqual(self.commits, 0)

    def test_failure_after_write_rolls_back_fake_transaction(self):
        first = self.store.play_put("games", full_record(), None, ACTOR, "Save fixture pod")
        self.cursor.fail_after_write = True
        changed = dict(copy.deepcopy(first), revision=2, result="draw")
        with self.assertRaisesRegex(RuntimeError, "fixture write failed"):
            self.store.play_put("games", changed, rules.record_sha(first), ACTOR, "Fail fixture correction")
        self.assertEqual(self.store.play_get("games", first["id"]), first)
        self.assertEqual(self.commits, 1)
