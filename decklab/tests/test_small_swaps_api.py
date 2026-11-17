"""Read-only E2-S33 API permissions, physical capacity and saved-list identity."""
import copy
import json
from collections import Counter
from unittest import mock

from decklab.lib import pool
from decklab.lib.api import guard, small_swaps
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import _as
from decklab.tests.test_swaps_api import SwapsTestCase, deck_text

DECK_ID = "casual/small-test"
MAIN = "Deck\n4 Ghalta, Primal Hunger (RIX) 130\n56 Forest"
CONSIDERING = "\n## Considering\n\n```\n2 Llanowar Elves (FDN) 227 #Draw\n```\n"


class SmallSwapTests(SwapsTestCase):
    def setUp(self):
        super().setUp()
        self.write("small-test", deck_text(MAIN, rest=CONSIDERING))
        self.p = pool.Pool(Counter({"Llanowar Elves": 4}), {}, [])
        self.loader = mock.patch.object(small_swaps, "_space_pool", return_value=self.p)
        self.loader.start()
        self.addCleanup(self.loader.stop)

    def suggest(self, **change):
        data = {"id": DECK_ID, "profile": "matt", "version": "target", "goal": "earlier", "protected": []}
        data.update(change)
        return small_swaps.suggest_small_swaps(json.dumps(data).encode())

    def test_saved_hash_one_copy_default_and_considering_printing_category_preserved(self):
        before = self.text(DECK_ID)
        answer = self.suggest()
        self.assertEqual((answer["deck_id"], answer["version"], answer["sha256"]),
                         (DECK_ID, "target", self.sha(DECK_ID)))
        [proposal] = answer["proposals"]
        self.assertEqual(proposal["cuts"], [{"name": "Ghalta, Primal Hunger", "qty": 1}])
        added = proposal["adds"][0]
        self.assertEqual((added["name"], added["qty"], added["set"], added["number"], added["finish"], added["category"]),
                         ("Llanowar Elves", 1, "fdn", "227", "nonfoil", "Draw"))
        self.assertEqual(proposal["max_qty"], 2)
        self.assertIsNone(answer["reason"])
        self.assertEqual(self.text(DECK_ID), before)

    def test_incoming_other_built_and_intact_holds_are_never_available(self):
        self.p.on_the_way = {"Llanowar Elves": [("private-order", 1)]}
        self.p.in_use = [pool.InUse("casual/holder", "Hidden holder", "built", Counter({"Llanowar Elves": 1})),
                         pool.InUse("product/box/one", "Hidden product", "intact product", Counter({"Llanowar Elves": 1}))]
        self.assertEqual(self.suggest()["proposals"][0]["max_qty"], 1)
        self.p.owned["Llanowar Elves"] = 3
        answer = self.suggest()
        self.assertEqual(answer["proposals"], [])
        self.assertNotIn("Hidden", json.dumps(answer))
        self.assertNotIn("private-order", json.dumps(answer))

    def test_selected_lists_sideboard_and_own_physical_standins_use_copies(self):
        self.write("small-test", deck_text(MAIN + "\n\nSideboard\n3 Llanowar Elves (FDN) 227", rest=CONSIDERING))
        self.assertEqual(self.suggest()["proposals"][0]["max_qty"], 1)
        self.p.in_use = [pool.InUse(DECK_ID, "Mine", "built", Counter({"Llanowar Elves": 4}))]
        self.assertEqual(self.suggest()["proposals"], [])

    def test_unreadable_or_unknown_inventory_fails_closed_with_generic_reason(self):
        for attr, value in (("warnings", ["Hidden holder cannot be read"]),
                            ("unresolved", {"Secret card": {"hidden-path"}})):
            with self.subTest(attr=attr):
                setattr(self.p, attr, value)
                answer = self.suggest()
                self.assertEqual(answer["proposals"], [])
                self.assertEqual(answer["reason"], small_swaps.INCOMPLETE)
                self.assertNotIn("Hidden", json.dumps(answer))
                setattr(self.p, attr, [] if attr == "warnings" else {})

    def test_unknown_list_card_and_bad_printing_are_not_promoted(self):
        self.write("small-test", deck_text(MAIN.replace("56 Forest", "55 Forest\n1 Unknown card"), rest=CONSIDERING))
        self.assertEqual(self.suggest()["proposals"], [])
        self.write("small-test", deck_text(MAIN, rest=CONSIDERING.replace("227", "9999")))
        self.assertEqual(self.suggest()["proposals"], [])

    def test_off_limits_and_no_considering_have_useful_empty_answers(self):
        answer = self.suggest(protected=["ghalta, primal hunger"])
        self.assertEqual(answer["proposals"], [])
        self.assertIn("off-limits", answer["reason"])
        self.write("small-test", deck_text(MAIN))
        self.assertIn("Add alternatives", self.suggest()["reason"])

    def test_whole_list_copy_limits_and_selected_version_are_checked(self):
        self.write("small-test", deck_text(MAIN.replace("4 Ghalta", "5 Ghalta").replace("56 Forest", "55 Forest"), rest=CONSIDERING))
        self.assertIn("copy limits", self.suggest()["reason"])
        self.write("small-test", deck_text(MAIN, rest=CONSIDERING +
            "\n## Substitutes\n\n### Substitute version (owned and incoming cards)\n\n```\n" + MAIN + "\n```\n"))
        self.assertEqual(self.suggest(version="owned")["version"], "owned")

    def test_invalid_inputs_do_not_get_heuristic_defaults(self):
        for change in ({"goal": None}, {"goal": "win more"}, {"version": "both"},
                       {"protected": "Ghalta, Primal Hunger"}, {"protected": ["Unknown"]},
                       {"protected": ["Forest"] * 61}):
            with self.subTest(change=change):
                self.assertApiError(400, lambda: self.suggest(**change))
        self.write("small-test", deck_text(MAIN.replace("56 Forest", "55 Forest"), rest=CONSIDERING))
        self.assertApiError(400, self.suggest)
        self.assertApiError(400, lambda: self.suggest(id="commander/elf-commander"))

    def test_visibility_inventory_and_forged_profile_are_guarded_before_pool_read(self):
        _write(self.box.root / "config.json", json.dumps(ROLES))
        with _as("user2"), mock.patch.object(small_swaps, "_space_pool", side_effect=AssertionError("private pool read")):
            self.assertApiError(404, lambda: self.suggest(profile="user2", goal=None))
            self.assertApiError(403, lambda: self.suggest(profile="matt"))
        with _as("matt"), mock.patch.object(guard, "sees_inventory", return_value=False), \
                mock.patch.object(small_swaps, "_space_pool", side_effect=AssertionError("private pool read")):
            self.assertApiError(403, self.suggest)

    def test_public_collection_outsider_cannot_infer_private_holds(self):
        _write(self.box.root / "config.json", json.dumps(ROLES))
        with _as("user2"), mock.patch.object(guard, "public_deck_spaces", return_value={"home"}), \
                mock.patch.object(guard, "public_spaces", return_value={"home"}), \
                mock.patch.object(small_swaps, "_space_pool", side_effect=AssertionError("private hold read")):
            error = self.assertApiError(403, lambda: self.suggest(profile="user2"))
        self.assertEqual(error.message, "That collection isn't public.")

    def test_pool_and_card_list_have_no_mutation(self):
        before = copy.deepcopy(self.p)
        self.suggest()
        self.assertEqual(self.p, before)

    def test_real_fixture_pool_keeps_the_beginner_box_hold_and_does_not_write(self):
        self.loader.stop()
        self.write("broken", deck_text("Deck\n60 Forest", title="Repaired fixture"))
        checked = pool.load_pool()
        self.assertEqual((checked.warnings, checked.unresolved), ([], {}))
        before = {str(p.relative_to(self.box.magic)): p.read_bytes()
                  for p in self.box.magic.rglob("*") if p.is_file()}
        answer = self.suggest()
        self.assertTrue(answer["proposals"], answer)
        self.assertEqual(answer["proposals"][0]["max_qty"], 2)  # five owned, two intact
        after = {str(p.relative_to(self.box.magic)): p.read_bytes()
                 for p in self.box.magic.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
