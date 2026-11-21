"""The guide checks current Commander lists against cached precons and known on-hand copies."""
import json
from collections import Counter
from unittest import mock

from decklab.lib import cards, decks, inventory, pool, stats
from decklab.lib.api import comparison_lists, guard, precon_upgrades
from decklab.lib.stats import commander
from decklab.tests import test_precons as fixtures
from decklab.tests.test_api import FIXTURES, _write
from decklab.tests.test_swaps_api import deck_text

ID = "commander/upgrade-fixture"
FILE = "UpgradeDinos_TST"
ANSWER = "Pick Your Poison"
MAIN = "Commander\n1 Ghalta, Primal Hunger (RIX) 130\n\nDeck\n1 Rampant Growth (8ED) 274 #Ramp\n98 Forest"


class PreconUpgradeTests(fixtures.PreconTestCase):
    def setUp(self):
        super().setUp()
        src = self.box.root / "upgrade-cards.jsonl"
        src.write_text("\n".join((FIXTURES / name).read_text(encoding="utf-8") for name in
                                 ("default_cards.jsonl", "stats_cards.jsonl")), encoding="utf-8")
        idx = self.box.root / "upgrade-index.json.gz"
        cards.write_index(cards.build_index(src, FIXTURES / "oracle_tags.jsonl", {}, log=lambda *a: None), idx)
        self.addCleanup(setattr, cards, "_index", cards._index)
        cards.load(idx)
        self.box.stats.side_effect = stats.deck_stats
        self.box.stack.enter_context(mock.patch.object(commander, "TAG_FILE", FIXTURES / "stats_tags.jsonl"))
        self.path = self.box.magic / "decks/commander/upgrade-fixture.md"
        self.write_deck()
        self.listed(FILE, {"data": {**fixtures.DINOS["data"], "name": "Upgrade Dinos", "mainBoard": [
            fixtures.card("Rampant Growth", "8ED", "274"), fixtures.card("Forest", "FDN", "280", 98)]}})
        self.pool = pool.Pool(Counter({ANSWER: 2}), {}, [])
        self.loader = self.box.stack.enter_context(mock.patch.object(precon_upgrades, "_space_pool", return_value=self.pool))

    def write_deck(self, text=MAIN):
        _write(self.path, deck_text(text, title="Upgrade fixture", fmt="Commander").replace(
            "- **Status:** building", "- **Status:** building\n- **Target bracket:** 2"))

    def suggest(self, profile="matt", **changes):
        payload = {"id": ID, "file": FILE, "goal": "early-interaction", **changes}
        return self.call(precon_upgrades.suggest_upgrades, profile, **payload)

    def test_pairs_current_stock_cut_with_legal_free_answer_without_writing(self):
        original = self.path.read_bytes()
        with self.as_("matt"), mock.patch.object(inventory, "apply", side_effect=AssertionError("no writes")):
            result = self.suggest()
        [proposal] = result["proposals"]
        self.assertEqual((proposal["cut"]["name"], proposal["cut"]["category"], proposal["add"]["name"]),
                         ("Rampant Growth", "Ramp", ANSWER))
        self.assertEqual((proposal["free"], proposal["stock_cut"], proposal["add"]["qty"]), (2, True, 1))
        self.assertIn("removal", proposal["reason"])
        self.assertIn("situational answer", proposal["trade_off"])
        self.assertEqual((result["target_bracket"], result["before_minimum"], proposal["after_minimum"]), (2, 1, 1))
        self.assertEqual(result["sha256"], decks.read_deck_file(self.path).sha256)
        self.assertEqual(self.path.read_bytes(), original)

    def test_incoming_copies_and_holds_do_not_become_upgrade_ideas(self):
        self.pool.on_the_way = {ANSWER: [("Private order", 1)]}
        self.pool.in_use = [pool.InUse(ID, "Own Play-now hold", "built", Counter({ANSWER: 1}))]
        with self.as_("matt"):
            value = self.suggest()
            self.assertEqual(value["proposals"], [])
            self.assertNotIn("Private order", json.dumps(value))
            self.assertNotIn("Own Play-now hold", json.dumps(value))
            self.pool.in_use = [pool.InUse("product/test", "Private product", "intact product", Counter({ANSWER: 1}))]
            value = self.suggest()
            self.assertEqual(value["proposals"], [])
            self.assertNotIn("Private product", json.dumps(value))

    def test_already_modified_list_and_unknown_bracket_are_handled(self):
        self.write_deck(MAIN.replace("98 Forest", "97 Forest\n1 Pick Your Poison (MKM) 170"))
        with self.as_("matt"):
            self.assertEqual(self.suggest()["proposals"], [])
            self.write_deck()
            with mock.patch.object(commander, "TAG_FILE", self.box.root / "tags-missing.jsonl"):
                result = self.suggest()
        [proposal] = result["proposals"]
        self.assertIsNone(result["before_minimum"])
        self.assertIsNone(proposal["after_minimum"])

    def test_only_the_current_lists_editors_see_the_action_or_pool_counts(self):
        with self.as_("matt"):
            self.assertTrue(comparison_lists.current_view(ID)["may_upgrade_precon"])
            self.assertApiError(400, self.suggest, file="ElfTheme_TST")
            self.assertApiError(400, self.suggest, goal="too broad")
        with self.as_("user1"):
            self.assertNotIn("may_upgrade_precon", comparison_lists.current_view(ID))
            self.assertApiError(403, self.suggest, "user1")
        with self.as_("user2"):
            self.assertApiError(404, self.suggest, "user2", file="invalid")
            with mock.patch.object(guard, "public_deck_spaces", return_value={"home"}), \
                    mock.patch.object(guard, "sees_inventory", return_value=True):
                self.assertNotIn("may_upgrade_precon", comparison_lists.current_view(ID))
                self.assertApiError(403, self.suggest, "user2")
        self.loader.assert_not_called()
