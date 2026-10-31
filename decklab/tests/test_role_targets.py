"""Commander role targets on the Stats tab (E9-S26): the Command Zone template's figures (lib/stats/role_targets.py),
deck_stats' "role_targets", and GET /api/deck carrying them for a Commander deck only.

The API tests run in test_swaps_api's SwapsTestCase (test_api's Sandbox, its fixture card index built from
tests/fixtures' default_cards and oracle_tags: ramp holds Llanowar Elves, Elvish Mystic and Sol Ring; removal
Pick Your Poison, Wrath of God and Fire // Ice, with Wrath of God a sweeper too; draw Rhystic Study and
Fire // Ice; no fixture card is a counterspell) with the real deck_stats in place of the sandbox's stand-in.
Nothing here writes to a database or needs the PC's card data.
"""
import json
import unittest

from decklab.lib import api, cards
from decklab.lib import stats as real_stats
from decklab.lib.stats import role_targets
from decklab.lib.stats.cardtext import Entry
from decklab.lib.stats.constants import SOURCES
from decklab.tests import test_swaps_api as base
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import _as
from decklab.tests.test_role_cards import commander_text

TARGETS_DECK = ("Commander\n1 Ghalta, Primal Hunger (RIX) 130\n\nDeck\n1 Llanowar Elves (FDN) 227\n"
                "1 Elvish Mystic (CMM) 648\n1 Sol Ring (ECC) 57\n1 Pick Your Poison (MKM) 170\n"
                "1 Fire // Ice (APC) 128\n1 Wrath of God (8ED) 58\n1 Rhystic Study (WOT) 25\n92 Forest")


def entry(name, qty, *roles):
    return Entry(qty=qty, name=name, section="Deck", card={"roles": list(roles)})


class TemplateTests(unittest.TestCase):

    def test_the_figures_are_episode_658s(self):
        targets = {c["category"]: (c["target"], c["about"]) for c in role_targets.CATEGORIES}
        self.assertEqual(targets, {"lands": (38, False), "ramp": (10, False), "card advantage": (12, False),
                                   "targeted disruption": (12, False), "mass disruption": (6, False),
                                   "plan": (30, True)})
        self.assertEqual((role_targets.EPISODE, role_targets.EPISODE_DATE), (658, "2025-02-18"))
        self.assertRegex(role_targets.CHECKED, r"^\d{4}-\d\d-\d\d$")

    def test_the_source_is_cited_for_the_sources_panel(self):
        source = SOURCES[role_targets.SOURCE_ID]
        self.assertIn("episode 658", source["title"])
        self.assertTrue(source["url"].startswith("https://www.youtube.com/watch?v="))
        self.assertIn("2025-02-18", source["date"])
        self.assertIn(role_targets.CHECKED, source["date"])
        self.assertEqual(len(source["figures_from"]), 3)
        self.assertTrue(all(url.startswith("https://") for url in source["figures_from"]))

    def test_every_mapped_role_is_a_deck_lab_role_and_plan_has_none(self):
        for c in role_targets.CATEGORIES:
            with self.subTest(c["category"]):
                self.assertLessEqual(set(c["roles"]) | set(c["except"]), set(cards.ROLES))
                self.assertTrue(c["measure"])
                if c["role_bar"]:
                    self.assertEqual(c["roles"], (c["role_bar"],))     # a bar carries only a whole measure
        plan = next(c for c in role_targets.CATEGORIES if c["category"] == "plan")
        self.assertEqual((plan["roles"], plan["lands"]), ((), False))
        self.assertIn("No Deck Lab role", plan["measure"])

    def test_status(self):
        self.assertEqual([role_targets.status(n, 10) for n in (9, 10, 11)], ["below", "at", "above"])
        self.assertIsNone(role_targets.status(None, 30))

    def test_counting(self):
        main = [entry("Rock", 3, "ramp"), entry("Elf", 7, "ramp"), entry("Murder", 2, "removal"),
                entry("Counter", 1, "counterspell"), entry("Wrath", 2, "removal", "board wipe"),
                entry("Wipe", 1, "board wipe"), entry("Opt", 4, "draw"), entry("Bolt", 1, "removal", "burn")]
        result = role_targets.role_targets(main, 37)
        got = {c["category"]: (c["count"], c["status"]) for c in result["categories"]}
        self.assertEqual(got, {"lands": (37, "below"), "ramp": (10, "at"), "card advantage": (4, "below"),
                               "targeted disruption": (4, "below"),     # Murder 2, Counter 1, Bolt 1: no Wrath
                               "mass disruption": (3, "below"), "plan": (None, None)})
        self.assertEqual(result["by_role"], {"ramp": "ramp", "draw": "card advantage",
                                             "board wipe": "mass disruption"})
        self.assertEqual((result["source"], result["episode"]), (role_targets.SOURCE_ID, 658))
        more = role_targets.role_targets([entry("Wrath", 7, "removal", "board wipe")], 40)
        self.assertEqual({c["category"]: c["status"] for c in more["categories"]}["mass disruption"], "above")


class RoleTargetsApiTests(base.SwapsTestCase):

    def setUp(self):
        super().setUp()
        self.box.stats.side_effect = real_stats.deck_stats       # the real stats, on the fixture card index
        self.write("targets", commander_text(TARGETS_DECK, "Targets"), kind="commander")

    def test_a_commander_decks_stats_carry_the_targets(self):
        st = api.deck_view("commander/targets")["stats"]
        targets = st["role_targets"]
        got = {c["category"]: (c["count"], c["status"]) for c in targets["categories"]}
        lands = st["lands"]["lands"]
        self.assertEqual(got, {"lands": (lands, "above" if lands > 38 else "at" if lands == 38 else "below"),
                               "ramp": (3, "below"), "card advantage": (2, "below"),
                               "targeted disruption": (2, "below"),     # Pick Your Poison, Fire // Ice
                               "mass disruption": (1, "below"), "plan": (None, None)})
        # The role bars' own counts: Wrath of God is removal too, so the Removal bar isn't the targeted figure.
        roles = {r["role"]: r["count"] for r in st["roles"]}
        self.assertEqual((roles["removal"], roles["ramp"], roles["draw"], roles["board wipe"]), (3, 3, 2, 1))
        self.assertIn(targets["source"], st["sources"])
        self.assertEqual(st["sources"][targets["source"]]["url"], role_targets.SOURCE["url"])

    def test_a_casual_deck_has_none(self):
        self.assertIsNone(api.deck_view(base.SWAP_ID)["stats"]["role_targets"])

    def test_the_play_now_list_is_counted_on_its_own(self):
        owned = "Commander\n1 Ghalta, Primal Hunger (RIX) 130\n\nDeck\n1 Llanowar Elves (FDN) 227\n98 Forest"
        text = commander_text(TARGETS_DECK, "Two Lists").replace(
            "## Owned vs needed", f"### Substitute version (owned and incoming cards)\n\n```\n{owned}\n```\n\n"
                                  "## Owned vs needed", 1)
        self.write("two-lists", text, kind="commander")
        view = api.deck_view("commander/two-lists", "owned")
        if view["version"] != "owned":
            self.skipTest("the fixture deck text has no Play-now list")
        ramp = next(c for c in view["stats"]["role_targets"]["categories"] if c["category"] == "ramp")
        self.assertEqual(ramp["count"], 1)

    def test_a_hidden_deck_is_still_missing(self):
        _write(self.box.root / "config.json", json.dumps(ROLES))      # user2 a member with a space of their own
        with _as("user2"):
            self.assertApiError(404, api.deck_view, "commander/targets")


if __name__ == "__main__":
    unittest.main()
