"""The gauntlet's fixing (lib/gauntlet/fixing.py): an average deck made exactly 100 singleton
cards, its bracket and re-tiering, unknown names, and Forge AI screening against a fake script
table. Synthetic cards only (gauntlet_sources_support); no network."""
import unittest

from decklab.lib.gauntlet import catalogue, fixing
from decklab.tests.gauntlet_sources_support import GauntletCase, fake_limits

YSHTOLA = "Y'shtola, Night's Blessed"


def total(listed):
    return sum(q for q, _ in listed["Commander"] + listed["Main"])


def count(listed, name):
    return sum(q for q, n in listed["Main"] if n == name)


class FixToHundred(GauntletCase):
    def test_under_100_adds_basics_by_pips(self):
        # Pips: Counterspell UU, Swords W, Vindicate WB, Baleful Strix UB -> W2 U3 B2.
        main = [[1, "Counterspell"], [1, "Swords to Plowshares"], [1, "Vindicate"], [1, "Baleful Strix"]]
        fixed = fixing.fix_commander([YSHTOLA], main)
        self.assertTrue(fixed["playable"])
        self.assertEqual(total(fixed["cards"]), 100)
        added = {n: count(fixed["cards"], n) for n in ("Plains", "Island", "Swamp")}
        self.assertEqual(sum(added.values()), 95)
        self.assertGreater(added["Island"], added["Plains"])
        self.assertEqual(added["Plains"], added["Swamp"])
        self.assertTrue(any(f.startswith("Added") and "Island" in f for f in fixed["fixes"]))

    def test_under_100_merges_into_existing_basics(self):
        fixed = fixing.fix_commander([YSHTOLA], [[1, "Counterspell"], [6, "Island"]])
        self.assertEqual(count(fixed["cards"], "Island"), 98)       # only blue pips
        self.assertEqual([n for _, n in fixed["cards"]["Main"]].count("Island"), 1)

    def test_colourless_identity_gets_wastes(self):
        fixed = fixing.fix_commander(["Kozilek, the Great Distortion"], [[1, "Sol Ring"]])
        self.assertEqual(count(fixed["cards"], "Wastes"), 98)
        self.assertEqual(total(fixed["cards"]), 100)

    def test_over_100_removes_basics_to_the_floor_then_nonlands_from_the_end(self):
        fillers = [[1, f"Filler Blue {i}"] for i in range(1, 41)]
        main = [[20, "Island"], [20, "Plains"], [3, "Command Tower"]] + fillers   # 1 + 43 + 40 = 84
        main += [[1, "Counterspell"], [1, "Baleful Strix"], [20, "Swamp"]]        # 106
        fixed = fixing.fix_commander([YSHTOLA], main)
        self.assertEqual(total(fixed["cards"]), 100)
        lands = sum(q for q, n in fixed["cards"]["Main"] if n in ("Island", "Plains", "Swamp", "Command Tower"))
        self.assertGreaterEqual(lands, fixing.LAND_FLOOR)
        self.assertEqual(count(fixed["cards"], "Command Tower"), 1)       # a duplicate non-basic
        self.assertIn("Counterspell", [n for _, n in fixed["cards"]["Main"]])
        self.assertTrue(any(f.startswith("Removed") for f in fixed["fixes"]))

    def test_over_100_with_lands_at_the_floor_cuts_nonlands_from_the_end(self):
        fillers = [[1, f"Filler Blue {i}"] for i in range(1, 41)]
        main = [[33, "Island"]] + fillers + [[1, "Counterspell"]] + [[1, "Sol Ring"], [1, "Arcane Signet"]]
        main += [[1, n] for n in ("Baleful Strix", "Swords to Plowshares", "Vindicate", "Rhystic Study",
                                  "Cyclonic Rift", "Smothering Tithe")]
        main += [[25, "Relentless Rats"]]                                       # 1 + 33 + 49 + 25 = 108
        fixed = fixing.fix_commander([YSHTOLA], main)
        self.assertEqual(total(fixed["cards"]), 100)
        self.assertEqual(count(fixed["cards"], "Island"), 33)
        self.assertEqual(count(fixed["cards"], "Relentless Rats"), 17)        # cut from the end
        self.assertTrue(any(f.startswith("Cut") for f in fixed["fixes"]))

    def test_duplicates_reduced_unless_text_allows_more(self):
        fixed = fixing.fix_commander([YSHTOLA], [[2, "Counterspell"], [1, "Counterspell"], [5, "Relentless Rats"]])
        self.assertEqual(count(fixed["cards"], "Counterspell"), 1)
        self.assertEqual(count(fixed["cards"], "Relentless Rats"), 5)
        self.assertIn("Counterspell: 3 copies reduced to 1.", fixed["fixes"])

    def test_off_identity_and_illegal_cards_dropped(self):
        fixed = fixing.fix_commander([YSHTOLA], [[1, "Lightning Bolt"], [1, "Black Lotus"], [1, "Counterspell"]])
        names = [n for _, n in fixed["cards"]["Main"]]
        self.assertNotIn("Lightning Bolt", names)
        self.assertNotIn("Black Lotus", names)
        self.assertIn("Dropped 1 Lightning Bolt: outside the commander's colour identity.", fixed["fixes"])
        self.assertIn("Dropped 1 Black Lotus: banned in Commander.", fixed["fixes"])
        self.assertEqual(total(fixed["cards"]), 100)

    def test_commander_in_the_99_is_moved_out(self):
        fixed = fixing.fix_commander([YSHTOLA], [[1, YSHTOLA], [1, "Counterspell"]])
        self.assertEqual(fixed["cards"]["Commander"], [[1, YSHTOLA]])
        self.assertNotIn(YSHTOLA, [n for _, n in fixed["cards"]["Main"]])

    def test_unknown_names(self):
        found, unknown = fixing.resolve([[1, "counterspell"], [1, "No Such Card"]])
        self.assertEqual(found, [[1, "Counterspell"]])
        self.assertEqual(unknown, ["No Such Card"])


class Brackets(GauntletCase):
    def test_game_changers_raise_the_bracket_and_retier_core(self):
        fixed = fixing.fix_commander([YSHTOLA], [[1, "Rhystic Study"], [1, "Cyclonic Rift"]])
        measured, reasons, _ = fixing.bracket(fixed["cards"])
        self.assertEqual(measured["minimum"], 3)
        self.assertEqual(measured["game_changers"], ["Cyclonic Rift", "Rhystic Study"])
        tier, why = fixing.retier("core", measured)
        self.assertEqual(tier, "upgraded")
        self.assertIn("minimum bracket is 3", why)
        self.assertEqual(fixing.retier("upgraded", measured), ("upgraded", None))

    def test_four_game_changers_are_bracket_4_still_upgraded(self):
        main = [[1, n] for n in ("Rhystic Study", "Cyclonic Rift", "Smothering Tithe")]
        fixed = fixing.fix_commander([YSHTOLA], main)
        self.assertEqual(fixing.bracket(fixed["cards"])[0]["minimum"], 3)
        self.patch_gc("Sol Ring")
        measured = fixing.bracket(fixing.fix_commander([YSHTOLA], main + [[1, "Sol Ring"]])["cards"])[0]
        self.assertEqual(measured["minimum"], 4)
        self.assertEqual(fixing.retier("precon", measured)[0], "upgraded")

    def patch_gc(self, name):
        from decklab.lib import cards
        cards._index.data["cards"][name]["game_changer"] = True

    def test_clean_core_stays(self):
        measured = fixing.bracket(fixing.fix_commander([YSHTOLA], [[1, "Counterspell"]])["cards"])[0]
        self.assertLessEqual(measured["minimum"], 2)
        self.assertEqual(fixing.retier("core", measured), ("core", None))


class Screening(GauntletCase):
    LISTED = {"Commander": [[1, YSHTOLA]], "Main": [[1, "Counterspell"], [4, "Doom Blade"], [94, "Island"]]}

    def test_commander_unplayable_excludes(self):
        reason, _ = fixing.screen(self.LISTED, "commander", fake_limits(commander={YSHTOLA}))
        self.assertIn("commander", reason)

    def test_unknown_card_excludes(self):
        reason, _ = fixing.screen(self.LISTED, "commander", fake_limits(unknown={"Counterspell"}))
        self.assertIn("Counterspell", reason)

    def test_more_than_three_unplayable_copies_excludes(self):
        reason, _ = fixing.screen(self.LISTED, "commander", fake_limits(cannot={"Doom Blade"}))
        self.assertIn("4 of its cards", reason)

    def test_a_few_unplayable_copies_only_a_problem(self):
        reason, problems = fixing.screen(self.LISTED, "commander", fake_limits(cannot={"Counterspell"}, poor=True))
        self.assertIsNone(reason)
        self.assertIn("Forge's AI can't play Counterspell.", problems)
        self.assertTrue(any("pilots it poorly" in p for p in problems))

    def test_a_screening_problem_alone_is_only_a_problem(self):
        reason, problems = fixing.screen(self.LISTED, "commander", fake_limits(problem="No oracle tags."))
        self.assertIsNone(reason)
        self.assertEqual(problems, ["AI screening: No oracle tags."])

    def test_forge_scripts_unread_excludes_as_not_screened(self):
        reason, problems = fixing.screen(self.LISTED, "commander",
                                         fake_limits(problem="Forge isn't installed.", screened=False))
        self.assertIn("Not screened", reason)
        self.assertEqual(problems, ["AI screening: Forge isn't installed."])


class ForgeLimits(GauntletCase):
    def test_no_card_scripts_means_not_screened(self):
        from unittest import mock
        from decklab.lib.forge import ai, install
        from decklab.lib.forge.common import ForgeError
        limits = {"cannot_play": [], "unknown": [], "commander_unplayable": False, "pilot": None,
                  "team_pump": None, "problem": "Forge isn't installed.", "games": 0}

        def missing():
            raise ForgeError("Forge isn't installed.")
        with mock.patch.object(ai, "ai_limits", lambda sections, kind: dict(limits)),                 mock.patch.object(install, "script_index", missing):
            reason, problems = fixing.screen(Screening.LISTED, "commander")
        self.assertIn("Not screened", reason)
        with mock.patch.object(ai, "ai_limits", lambda sections, kind: dict(limits, problem=None)),                 mock.patch.object(install, "script_index", lambda: {}):
            self.assertEqual(fixing.screen(Screening.LISTED, "commander"), (None, []))


class Entries(GauntletCase):
    def record(self, commanders, main, tier="core"):
        return {"id": "gauntlet:edhrec/test-core", "title": "Test", "kind": "commander", "tier": tier,
                "source": {"kind": "edhrec", "url": "https://edhrec.com/x", "fetched": None, "rank": 1, "decks": 10},
                "commanders": commanders, "cards": main, "themes": ["Control"], "problems": []}

    def test_unknown_name_makes_it_unplayable_and_keeps_it_whole(self):
        made = catalogue.entry(self.record([YSHTOLA], [[1, "Counterspell"], [1, "Not A Card"]]), fake_limits())
        self.assertFalse(made["playable"])
        self.assertIn("Not Scryfall cards: Not A Card.", made["problems"])
        self.assertEqual(made["cards"]["Main"], [[1, "Counterspell"], [1, "Not A Card"]])
        self.assertEqual(made["fixes"], [])

    def test_fixed_entry_is_re_tiered_and_screened(self):
        calls = []
        made = catalogue.entry(self.record([YSHTOLA], [[1, "Rhystic Study"], [1, "Cyclonic Rift"]]),
                               fake_limits(calls=calls))
        self.assertTrue(made["playable"])
        self.assertEqual(made["tier"], "upgraded")
        self.assertEqual(made["bracket"]["minimum"], 3)
        self.assertEqual(total(made["cards"]), 100)
        self.assertEqual(calls, ["commander"])
        self.assertEqual(made["identity"], "WUB")
        self.assertEqual(len(made["card_sha"]), 64)

    def test_ai_exclusion_makes_it_unplayable(self):
        made = catalogue.entry(self.record([YSHTOLA], [[1, "Counterspell"]]), fake_limits(commander={YSHTOLA}))
        self.assertFalse(made["playable"])
        self.assertIn("Forge's AI can't play its commander.", made["problems"])


if __name__ == "__main__":
    unittest.main()
