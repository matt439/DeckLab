"""S40: retained games/plans with exact removed-deck markers, never live removals."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, state
from decklab.lib.api import activity, play_records as play
from decklab.lib.state import rules
from decklab.lib.state.memory import MemoryStore
from decklab.lib.state.play import REMOVED_DECK, is_removed_deck, record_deck_ids
from decklab.tests.test_api import ApiTestCase
from decklab.tests.test_play_records import MixedFixture, encoded, selector
from decklab.tests.test_activity import ADMIN, BY_ID, _change, _row
from decklab.tests import db_support
from decklab.tests.test_state_contract import game, plan, ID_A, ID_B, MATT


class RemovedMarkerTests(unittest.TestCase):
    def test_only_the_exact_two_key_marker_is_recognised(self):
        self.assertTrue(is_removed_deck(copy.deepcopy(REMOVED_DECK)))
        for value in (None, {}, True, {"removed": 1, "title": "a removed deck"},
                      {"removed": True}, {"removed": True, "title": "Former person's deck"},
                      {**REMOVED_DECK, "id": "user2/casual/a"}, {**REMOVED_DECK, "player": "Private name"}):
            with self.subTest(value=value):
                self.assertFalse(is_removed_deck(value))

    def test_identity_contains_only_survivors_and_cannot_lose_the_owned_plan_deck(self):
        side = {"id": "casual/survivor"}
        self.assertEqual(record_deck_ids("games", {"sides": [REMOVED_DECK, side], "space": "", "notes": ""}),
                         ["casual/survivor"])
        self.assertEqual(record_deck_ids("sideboards", {"deck": side, "opponent": REMOVED_DECK}),
                         ["casual/survivor"])
        for kind, content in (("games", {"sides": [REMOVED_DECK, REMOVED_DECK]}),
                              ("games", {"sides": [REMOVED_DECK]}),
                              ("games", {"sides": [REMOVED_DECK, side], "space": "", "notes": "Private"}),
                              ("sideboards", {"deck": REMOVED_DECK, "opponent": side}),
                              ("games", {"sides": [{**REMOVED_DECK, "sha256": "private"}, side]})):
            with self.subTest(kind=kind, content=content), self.assertRaises(state.Invalid):
                record_deck_ids(kind, content)


class RemovedStoreContract:
    def test_removed_sides_keep_hash_and_only_surviving_audit_ids(self):
        records = [game(ID_A), plan(ID_B)]
        records[0]["sides"][0] = copy.deepcopy(REMOVED_DECK)
        records[0].update(space="", notes="")
        records[1]["opponent"] = copy.deepcopy(REMOVED_DECK)
        for record in records:
            saved = self.store.play_put(record["kind"], record, None, MATT, "Retain a mixed record")
            loaded = self.store.play_get(record["kind"], record["id"])
            self.assertEqual(saved, record)
            self.assertEqual(rules.record_bytes(loaded), rules.record_bytes(record))
            self.assertEqual(rules.record_sha(loaded), rules.record_sha(record))
        for change in self.store.activity()["changes"]:
            after = change["rows"][0]["after"]
            self.assertEqual(after["deck_ids"], record_deck_ids(after["kind"], after["content"]))
            self.assertEqual(len(after["deck_ids"]), 1)


class MemoryRemovedStoreTests(RemovedStoreContract, unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()


class PgRemovedStoreTests(RemovedStoreContract, db_support.DbTestCase):
    def setUp(self):
        from decklab.lib.state.pg import PgStore, Breaker
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        self.store = PgStore(dbname=self.dbname, breaker=Breaker())


class RemovedPlayTests(MixedFixture, ApiTestCase):
    def removed_game(self, *, recorder="home", removed_index=0):
        if not hasattr(self, "original_mixed"):
            self.original_mixed = copy.deepcopy(self.box.state.play_get("games", self.mixed))
        record = copy.deepcopy(self.original_mixed)
        record["sides"][removed_index] = copy.deepcopy(REMOVED_DECK)
        record["space"] = recorder
        record["notes"] = "" if not recorder else "Surviving recorder's note"
        record["updated_by"] = "someone"
        old = self.box.state.play_get("games", self.mixed)
        record["revision"] = old["revision"] + 1
        self.box.state.play_put("games", record, rules.record_sha(old), state.Actor("test", "a test"), "Seed retained game")
        return record

    def removed_plan(self):
        record = copy.deepcopy(self.box.state.play_get("sideboards", self.home_plan))
        old = copy.deepcopy(record)
        record["opponent"] = copy.deepcopy(REMOVED_DECK)
        record["revision"] += 1
        self.box.state.play_put("sideboards", record, rules.record_sha(old), state.Actor("test", "a test"), "Seed retained plan")
        return record

    def entry(self, kind, record_id):
        return next(item for item in play.play_overview()[kind] if item["record"]["id"] == record_id)

    def game_body(self, entry, profile="matt"):
        record = entry["record"]
        return {"profile": profile, "id": record["id"], "sha256": entry["sha256"], "preview": True,
                "date": record["date"], "result": record["result"], "notes": record["notes"],
                "sides": [copy.deepcopy(side) if is_removed_deck(side) else
                          {**selector(side), "player": side["player"], "mulligans": side["mulligans"],
                           **{key: side[key] for key in ("plan_id", "plan_sha256") if key in side}}
                          for side in record["sides"]]}

    def test_game_reads_in_both_seat_orders_and_retains_surviving_snapshot(self):
        for index, survivor in ((0, "matt"), (1, "user2")):
            record = self.removed_game(removed_index=index)
            expected = copy.deepcopy(record["sides"][1-index])
            with access.viewing(survivor):
                entry = self.entry("games", self.mixed)
            self.assertEqual(entry["record"]["sides"][index], REMOVED_DECK)
            self.assertEqual(entry["record"]["sides"][1-index], expected)
            self.assertEqual(entry["can"]["sides"], [index != 0, index != 1])
            self.assertEqual(play._readable_ids("games", record), [expected["id"]])
            self.assertEqual(play._checked("games", self.mixed, record), rules.record_sha(record))

    def test_removed_recorder_result_is_locked_and_surviving_side_can_be_corrected(self):
        record = self.removed_game(recorder="")
        removed_bytes = rules.record_bytes(record["sides"][0])
        with access.viewing("matt"):
            entry = self.entry("games", self.mixed)
            self.assertFalse(entry["can"]["result"])
            data = self.game_body(entry)
            data["sides"][1]["mulligans"] += 1
            preview = play.save_game(encoded(data))
            saved = play.save_game(encoded({**data, "preview": False, "review_sha256": preview["review_sha256"]}))
            stored = self.box.state.play_get("games", self.mixed)
            self.assertEqual(rules.record_bytes(stored["sides"][0]), removed_bytes)
            self.assertEqual((stored["space"], stored["notes"], stored["date"], stored["result"]),
                             ("", "", record["date"], record["result"]))
            self.assertEqual(saved["record"]["sides"][0], REMOVED_DECK)
            changed = self.game_body(self.entry("games", self.mixed))
            changed["result"] = "b" if stored["result"] == "a" else "a"
            self.assertApiError(403, lambda: play.save_game(encoded(changed)))

    def test_clients_cannot_replace_or_embellish_removed_sides(self):
        self.removed_game()
        with access.viewing("matt"):
            entry = self.entry("games", self.mixed)
            for replacement in ({"hidden": True}, {**REMOVED_DECK, "id": "casual/other"},
                                {"removed": 1, "title": "a removed deck"}, selector(play._snapshot("casual/other", "target"))):
                data = self.game_body(entry)
                data["sides"][0] = replacement
                with self.subTest(replacement=replacement):
                    self.assertApiError(403, lambda: play.save_game(encoded(data)))
            data = self.game()
            data["sides"][0] = copy.deepcopy(REMOVED_DECK)
            self.assertApiError(403, lambda: play.save_game(encoded(data)))

    def test_surviving_sideboarded_snapshot_keeps_its_historical_plan_on_correction(self):
        plan_id = self.stored_plan("casual/gruul-test", "user2/casual/r-elves")
        plan_record = self.box.state.play_get("sideboards", plan_id)
        record = self.removed_game(recorder="")
        side = record["sides"][1]
        side["base_sha256"] = side["sha256"]
        side["sections"] = copy.deepcopy(plan_record["after"])
        side["sha256"] = play._hash(play._bytes({key: side[key] for key in ("id", "version", "sections")}))
        side.update(plan_id=plan_id, plan_sha256=rules.record_sha(plan_record))
        before = self.box.state.play_get("games", self.mixed)
        record["revision"] += 1
        self.box.state.play_put("games", record, rules.record_sha(before), state.Actor("test", "a test"), "Seed played plan")
        expected = copy.deepcopy(side)
        expected["mulligans"] += 1
        with access.viewing("matt"), mock.patch.object(play, "_read", side_effect=AssertionError("re-read private plan")):
            entry = self.entry("games", self.mixed)
            data = self.game_body(entry)
            data["sides"][1]["mulligans"] += 1
            checked = play.save_game(encoded(data))
            play.save_game(encoded({**data, "preview": False, "review_sha256": checked["review_sha256"]}))
        stored = self.box.state.play_get("games", self.mixed)
        self.assertEqual(stored["sides"], [REMOVED_DECK, expected])

    def test_public_retained_game_is_read_only_without_the_surviving_private_list(self):
        self.removed_game(recorder="")
        self.box.state.visibility_set("home", "games", True, state.Actor("test", "a test"), "Publish fixture games")
        with access.viewing("user3"):
            entry = self.entry("games", self.mixed)
        self.assertEqual(entry["record"]["sides"][0], REMOVED_DECK)
        self.assertTrue(entry["record"]["sides"][1]["hidden"])
        self.assertNotIn("sections", entry["record"]["sides"][1])
        self.assertEqual(entry["can"], {"sides": [False, False], "result": False})

    def test_blank_recorder_cannot_be_claimed_by_a_real_space_named_removed(self):
        record = {"space": "", "sides": [REMOVED_DECK, {"id": "removed/casual/remaining"}]}
        profile = {"id": "removed", "space": "removed"}
        with mock.patch.object(play, "_writable_decks", return_value=[]), mock.patch.object(play.guard, "allowed", return_value=True):
            self.assertEqual(play._rights("games", record, profile), {"sides": [False, True], "result": False})
            self.assertTrue(play._rights("games", dict(record, space="removed"), profile)["result"])

    def test_plan_with_removed_opponent_round_trips_without_changing_its_deck(self):
        record = self.removed_plan()
        with access.viewing("matt"):
            entry = self.entry("sideboards", self.home_plan)
            self.assertTrue(entry["editable"])
            self.assertEqual(entry["record"]["opponent"], REMOVED_DECK)
            data = {"profile": "matt", "id": self.home_plan, "sha256": entry["sha256"], "preview": True,
                    "deck": selector(record["deck"]), "opponent": copy.deepcopy(REMOVED_DECK),
                    "out": record["out"], "in": record["in"], "notes": "Revised surviving plan"}
            checked = play.save_sideboard(encoded(data))
            play.save_sideboard(encoded({**data, "preview": False, "review_sha256": checked["review_sha256"]}))
            stored = self.box.state.play_get("sideboards", self.home_plan)
            self.assertEqual(stored["opponent"], REMOVED_DECK)
            self.assertEqual(stored["deck"], record["deck"])
            changed = dict(data, sha256=rules.record_sha(stored), opponent=selector(play._snapshot("casual/other", "target")))
            self.assertApiError(403, lambda: play.save_sideboard(encoded(changed)))
            new = self.plan()
            new["opponent"] = copy.deepcopy(REMOVED_DECK)
            self.assertApiError(403, lambda: play.save_sideboard(encoded(new)))

    def test_activity_names_removed_deck_without_recovering_its_old_identity(self):
        record = self.removed_game(recorder="")
        header, content, ids = rules.split_record("games", record)
        row = _row("play_record", "UPDATE", {"kind": "games", "id": self.mixed},
                   after={**header, "content": content, "deck_ids": ids})
        shown = activity.visible_change(_change([row], actor="matt", source="web", message="Retain game"), ADMIN, BY_ID)
        self.assertIn("a removed deck", shown["headline"])
        self.assertNotIn("User2", json.dumps(shown))


if __name__ == "__main__":
    unittest.main()
