"""Pod Activity and member removal on synthetic rows, memory and fake cursors.

No configured database, server, card cache, Forge runtime or household records
are read. The fixture entry point installs protection before this module imports.
"""
import copy
import json
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.db import space_apply, space_export, space_remove
from decklab.lib import access, state
from decklab.lib.api import activity, activity_summaries, guard, settings
from decklab.lib.state import rules
from decklab.lib.state.memory import MemoryStore

PROFILES = [
    {"id": "matt", "name": "Matt", "role": "admin", "space": "home", "plays_as": "user"},
    {"id": "user1", "name": "User1", "role": "member", "space": "home", "plays_as": "wife"},
    {"id": "user2", "name": "User2", "role": "member", "space": "user2", "plays_as": None},
]
PRIVATE = "PRIVATE-EXTERNAL-LABEL"


def pod_record(space="user2", count=3):
    deck_id = ("" if space == "home" else space + "/") + "commander/fixture"
    payload = {"id": deck_id, "version": "target", "sections": {"Deck": [
        {"name": "Island", "qty": 99, "set": None, "number": None, "finish": "nonfoil"}]}}
    deck = {**payload, "title": "Fixture deck", "sha256": rules.record_sha(payload)}
    seats = [{"seat_id": "s1", "type": "deck", "player": PRIVATE + "-PLAYER", "deck": deck}]
    seats.extend({"seat_id": f"s{i}", "type": "external", "player": PRIVATE + f"-{i}",
                  "commander": PRIVATE + "-COMMANDER"} for i in range(2, count + 1))
    return {"version": 1, "id": "a" * 32, "kind": "games", "revision": 1,
            "created_on": "2026-10-28T01:02:03+00:00", "updated_on": "2026-10-28T01:02:03+00:00",
            "updated_by": "User2", "mode": "pod", "game_version": 2, "space": space,
            "date": "2026-10-28", "result": "s2", "notes": PRIVATE + "-NOTES", "seats": seats}


def database_row(record=None):
    header, content, deck_ids = rules.split_record("games", record or pod_record())
    return {**header, "content": content, "deck_ids": deck_ids}


def change(row, op="INSERT"):
    return {"id": 1, "at": "2026-10-28T01:02:03+00:00", "actor": "user2", "source": "web",
            "via": "tunnel", "message": "Save a pod game", "reason": None,
            "rows": [{"table": "play_record", "op": op, "key": {"kind": "games", "id": row["id"]},
                      "before": row if op == "DELETE" else None,
                      "after": None if op == "DELETE" else row}]}


class PodActivityTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(state.use(self.store))
        for patcher in (
            mock.patch.object(settings, "_config_profiles", return_value=copy.deepcopy(PROFILES)),
            mock.patch.object(activity, "row_cards", return_value={}),
            mock.patch.object(activity, "_load_orders", return_value={}),
            mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def view(self, profile=None):
        with access.viewing(profile):
            return activity.activity_view()

    def test_memory_save_is_one_private_activity_change_with_fixed_summary(self):
        record = pod_record()
        self.store.play_put("games", record, None, state.Actor("user2", "User2", "tunnel"), "Save a pod game")
        answer = self.view("user2")
        self.assertEqual(len(answer["changes"]), 1)
        shown = answer["changes"][0]
        self.assertEqual(shown["headline"], "User2 recorded a 3-player pod game")
        self.assertEqual(shown["rows"][0]["summary"], "Saved a 3-player pod game")
        self.assertNotIn(PRIVATE, json.dumps(answer))
        self.assertNotIn("Fixture deck", json.dumps(answer))
        self.assertEqual(self.view("matt")["changes"], [])
        self.assertEqual(self.view("user1")["changes"], [])

    def test_public_game_and_deck_switches_never_widen_activity(self):
        actor = state.Actor("user2", "User2", "tunnel")
        self.store.play_put("games", pod_record(), None, actor, "Save a pod game")
        self.store.visibility_set("user2", "games", True, actor, "Make games public")
        self.store.visibility_set("user2", "decks", True, actor, "Make decks public")
        for viewer in ("matt", "user1"):
            self.assertEqual(self.view(viewer)["changes"], [], viewer)
        self.assertEqual(len(self.view("user2")["changes"]), 3)

    def test_three_and_four_seat_summaries_never_name_external_labels(self):
        for count in (3, 4):
            for op, verb in (("INSERT", "Saved"), ("UPDATE", "Changed"), ("DELETE", "Removed")):
                with self.subTest(count=count, op=op):
                    row = database_row(pod_record(count=count))
                    summary = activity_summaries._play_summary(op, row)
                    self.assertEqual(summary, f"{verb} a {count}-player pod game")
                    self.assertNotIn(PRIVATE, summary)

    def test_other_record_kinds_do_not_opt_into_the_pod_summary(self):
        row = database_row()
        row["kind"] = "future"
        row["content"].pop("seats")
        self.assertEqual(activity_summaries._play_summary("INSERT", row), "Saved a game: a deck vs a deck")

    def test_pod_ownership_uses_only_validated_real_deck_ids(self):
        row = database_row()
        self.assertEqual(activity_summaries._play_owners(row), ["user2/commander/fixture"])
        mirror = copy.deepcopy(row)
        mirror["content"]["seats"][1] = {**mirror["content"]["seats"][0], "seat_id": "s2"}
        mirror["deck_ids"].append("user2/commander/fixture")
        self.assertEqual(activity_summaries._play_owners(mirror), mirror["deck_ids"])
        self.assertNotIn(PRIVATE, json.dumps(activity_summaries._play_owners(mirror)))

    def test_mismatched_metadata_never_grants_another_space_activity(self):
        for ids in ([], ["commander/fixture"], ["user2/commander/fixture", "commander/extra"], PRIVATE):
            with self.subTest(ids=ids):
                row = database_row()
                row["deck_ids"] = ids
                self.assertEqual(activity_summaries._play_owners(row), [])
                self.store._changes = [change(row)]
                for viewer in ("matt", "user1", "user2"):
                    self.assertEqual(self.view(viewer)["changes"], [], viewer)
                self.assertEqual(activity_summaries._play_summary("INSERT", row), "Saved a play record")

    def test_partial_unknown_or_mixed_space_pods_fail_closed_before_legacy_ownership(self):
        malformed = []
        for key in ("mode", "game_version"):
            row = database_row()
            row["content"].pop(key)
            malformed.append(row)
        for key, value in (("mode", "future"), ("game_version", True), ("game_version", 99)):
            row = database_row()
            row["content"][key] = value
            malformed.append(row)
        row = database_row()
        row["content"]["seats"][0]["deck"]["id"] = "commander/another-space"
        malformed.append(row)
        for row in malformed:
            with self.subTest(content=row["content"]):
                self.assertEqual(activity_summaries._play_owners(row), [])
                self.store._changes = [change(row)]
                self.assertEqual(self.view("user2")["changes"], [])
                self.assertEqual(activity_summaries._play_summary("INSERT", row), "Saved a play record")

    def test_noniterable_or_wrong_type_metadata_is_hidden_before_raw_activity_iteration(self):
        for ids in (7, True, {"user2/commander/fixture": True}, PRIVATE, [None], None):
            with self.subTest(ids=ids):
                row = database_row()
                row["deck_ids"] = ids
                self.store._changes = [change(row)]
                for viewer in ("matt", "user1", "user2", None):
                    self.assertEqual(self.view(viewer)["changes"], [], viewer)

    def test_damaged_after_hides_whole_update_even_when_before_is_valid_and_owned(self):
        for fault in ("partial-marker", "indexed-ids", "mixed-space"):
            good = database_row()
            bad = copy.deepcopy(good)
            if fault == "partial-marker":
                bad["content"].pop("mode")
            elif fault == "indexed-ids":
                bad["deck_ids"] = 1
            else:
                bad["content"]["seats"][0]["deck"]["id"] = "commander/foreign"
            packet = change(bad, "UPDATE")
            packet["rows"][0]["before"] = good
            packet["message"] = PRIVATE
            self.store._changes = [packet]
            for viewer in ("user2", "matt", None):
                with self.subTest(fault=fault, viewer=viewer):
                    self.assertEqual(self.view(viewer)["changes"], [])


class PodRemovalTests(unittest.TestCase):
    def test_removing_recorder_deletes_whole_three_or_four_seat_pod(self):
        for count in (3, 4):
            with self.subTest(count=count):
                row = database_row(pod_record(count=count))
                before = copy.deepcopy(row)
                self.assertIsNone(space_remove.transformed_record("user2", row))
                self.assertEqual(row, before)

    def test_unrelated_valid_pod_is_preserved_exactly_without_reassignment(self):
        row = database_row()
        before = copy.deepcopy(row)
        after = space_remove.transformed_record("user3", row)
        self.assertEqual(after, before)
        self.assertIsNot(after, row)
        self.assertIsNot(after["content"], row["content"])
        self.assertEqual(row, before)

    def test_home_pod_is_not_removed_when_a_member_has_an_external_label(self):
        row = database_row(pod_record(space="home"))
        row["content"]["seats"][1]["player"] = "user2"
        self.assertEqual(space_remove.transformed_record("user2", row), row)

    def test_stored_deck_index_must_match_actual_deck_seats(self):
        for ids in ([], ["commander/foreign"], ["user2/commander/fixture"] * 2, PRIVATE, None):
            row = database_row()
            row["deck_ids"] = ids
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, "pod game has damaged"):
                space_remove.transformed_record("user2", row)

    def test_mixed_space_pod_is_refused_instead_of_retaining_a_tombstone(self):
        row = database_row()
        deck = copy.deepcopy(row["content"]["seats"][0]["deck"])
        deck["id"] = "other/commander/foreign"
        row["content"]["seats"][1] = {"seat_id": "s2", "type": "deck", "player": "Other", "deck": deck}
        row["deck_ids"].append(deck["id"])
        with self.assertRaisesRegex(ValueError, "pod game has damaged"):
            space_remove.transformed_record("user2", row)
        self.assertNotIn(space_remove.REMOVED, row["content"]["seats"])

    def test_partial_or_unknown_markers_cannot_fall_through_to_two_side_redaction(self):
        for markers in ({"mode": "pod"}, {"game_version": 2}, {"mode": "pod", "game_version": 3},
                        {"mode": "future", "game_version": 2}, {"mode": "pod", "game_version": True}):
            row = database_row()
            row["content"].pop("mode")
            row["content"].pop("game_version")
            row["content"].update(markers)
            row["content"]["sides"] = [{"id": "user2/casual/old"}, {"id": "casual/other"}]
            with self.subTest(markers=markers), self.assertRaisesRegex(ValueError, "pod game has damaged"):
                space_remove.transformed_record("user2", row)

    def test_row_plan_schedules_one_delete_and_no_retained_external_snapshot(self):
        row = database_row(pod_record(count=4))
        rows, retained = space_remove.row_plan("user2", {"play_records": [row]})
        self.assertEqual(rows, [{"table": "play_record", "key": {"kind": "games", "id": row["id"]},
                                "action": "delete"}])
        self.assertEqual(retained, [])
        self.assertNotIn(PRIVATE, json.dumps(rows))

    def test_a_damaged_pod_aborts_planning_before_a_mutation_plan_is_returned(self):
        bad = database_row()
        bad["content"]["seats"][0]["deck"]["id"] = "commander/foreign"
        with self.assertRaisesRegex(ValueError, "pod game has damaged"):
            space_remove.row_plan("user2", {"play_records": [database_row(), bad]})

    def test_fake_postgres_removal_issues_only_one_bound_delete_for_owned_pod(self):
        row = database_row()
        cursor = mock.Mock()
        actor = state.Actor("claude", "Claude", None, "cli")
        with mock.patch.dict(sys.modules, {"psycopg.types.json": SimpleNamespace(Jsonb=lambda value: value)}):
            space_apply._write_records(cursor, {"space": [{"id": "user2"}], "play_records": [row]}, actor)
        cursor.execute.assert_called_once_with("delete from play_record where kind = %s and id = %s",
                                               ("games", row["id"]))
        self.assertNotIn(PRIVATE, str(cursor.mock_calls))

    def test_fake_postgres_writer_refuses_invalid_pod_before_any_sql(self):
        row = database_row()
        row["content"]["space"] = "other"
        cursor = mock.Mock()
        with mock.patch.dict(sys.modules, {"psycopg.types.json": SimpleNamespace(Jsonb=lambda value: value)}):
            with self.assertRaisesRegex(ValueError, "pod game has damaged"):
                space_apply._write_records(cursor, {"space": [{"id": "user2"}], "play_records": [row]},
                                           state.Actor("claude", "Claude", None, "cli"))
        cursor.execute.assert_not_called()


class PodExportFingerprintTests(unittest.TestCase):
    def snapshot(self, row):
        class Cursor:
            def execute(self, query, params=()):
                if query == "select 1 from space where id = %s":
                    return SimpleNamespace(fetchone=lambda: (1,))
                if query == "select to_regclass('public.visibility') is not null":
                    return SimpleNamespace(fetchone=lambda: (True,))
                if query == space_export._QUERIES["space"]:
                    return [({"id": "user2"},)]
                if query == space_export._QUERIES["play_records"]:
                    self.play_params = params
                    return [(copy.deepcopy(row),)]
                return []
        cursor = Cursor()
        result = space_export.snapshot(cursor, "user2", details=True)
        self.assertEqual(cursor.play_params, ("user2", "user2"))
        return result

    def test_existing_scoped_export_fingerprints_seat_text_without_exporting_it(self):
        row = database_row()
        files, sha, data = self.snapshot(row)
        changed = copy.deepcopy(row)
        changed["content"]["seats"][1]["commander"] += "-CHANGED"
        other_files, other_sha, other_data = self.snapshot(changed)
        self.assertEqual(files, other_files)
        self.assertNotEqual(sha, other_sha)
        self.assertEqual(data["play_records"], [row])
        self.assertEqual(other_data["play_records"], [changed])
        self.assertNotIn(PRIVATE.encode(), b"".join(files.values()))
