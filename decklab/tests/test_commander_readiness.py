"""Commander disclosures use synthetic fixture decks and the loaded local index only."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from decklab.lib import cards, decks, official_lists, stats
from decklab.lib.stats import commander


FIXTURES = Path(__file__).parent / "fixtures"
TAGS = FIXTURES / "stats_tags.jsonl"
COMBOS = FIXTURES / "stats_combos.json"     # its list is of 2026-10-14
OFFICIAL = FIXTURES / "stats_official_lists.json"   # 2026-02-09's announcement, checked 2026-10-15
ANNOUNCED = {"date": "2026-02-09",
             "url": "https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-february-9-2026"}
# What the fixture's check says when nothing is out of date.
CURRENT = {"official_announcement": ANNOUNCED, "official_checked": "2026-10-15", "official_unknown": False,
           "rules_date": "2026-02-09", "cards_older_than_announcement": False,
           "rules_older_than_announcement": False}
FRESH = {"default_cards": "2026-10-14T21:05:39.249+00:00",
         "oracle_tags": "2026-10-13T21:00:42.364Z"}
CLEAN = "Commander\n1 Finneas, Ace Archer\n\nDeck\n99 Forest\n"


class FixtureStats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = cards.build_index(FIXTURES / "stats_cards.jsonl", TAGS, FRESH, log=lambda *a: None)

    def setUp(self):
        self.loaded = cards._prepare(copy.deepcopy(self.index))
        self.clock = mock.Mock(wraps=datetime)
        self.clock.now.return_value = datetime(2026, 10, 15, 23, 59, tzinfo=timezone.utc)
        for patch in (mock.patch.object(cards, "_index", self.loaded),
                      mock.patch.object(cards, "_tag_cache", {}),
                      mock.patch.object(commander, "TAG_FILE", TAGS),
                      mock.patch.object(commander, "COMBO_FILE", COMBOS),
                      mock.patch.object(commander, "OFFICIAL_FILE", OFFICIAL),
                      mock.patch.object(commander, "datetime", self.clock),
                      mock.patch.object(cards, "_open_url", side_effect=AssertionError("No network in stats")),
                      mock.patch.object(cards, "update", side_effect=AssertionError("No index rebuild in stats"))):
            patch.start()
            self.addCleanup(patch.stop)

    def bracket(self, text=CLEAN):
        return stats.deck_stats(decks.parse_decklist(text), "commander")["commander"]["bracket"]


class CommanderReadinessTests(FixtureStats):
    def test_source_dates_are_from_loaded_bulk_and_normalized(self):
        self.loaded.data["built_at"] = "2040-01-01T00:00:00+00:00"
        self.assertEqual(self.bracket()["data"], {
            "cards_date": "2026-10-14", "tags_date": "2026-10-13", "combos_date": "2026-10-14",
            "stale": False, "dates_stale": False, "max_age_days": 7, **CURRENT})
        self.clock.now.assert_called_once_with(timezone.utc)
        json.dumps(self.bracket(), allow_nan=False)

    def test_old_source_data_is_stale_even_when_the_other_source_is_fresh(self):
        for source in ("default_cards", "oracle_tags"):
            with self.subTest(source=source):
                self.loaded.data["bulk"] = {**FRESH, source: "2026-10-07"}
                self.assertTrue(self.bracket()["data"]["stale"])

    def test_exact_maximum_age_is_fresh_and_today_is_fresh(self):
        for value in ("2026-10-08", "2026-10-15"):
            with self.subTest(value=value):
                self.loaded.data["bulk"] = dict.fromkeys(FRESH, value)
                self.assertFalse(self.bracket()["data"]["stale"])

    def test_missing_and_invalid_source_dates_are_unknown_and_stale(self):
        for value in (None, "", "unknown", "2026-02-30", "2026-10-14broken", 123, {}):
            with self.subTest(value=value):
                self.loaded.data["bulk"] = {**FRESH, "default_cards": value}
                data = self.bracket()["data"]
                self.assertIsNone(data["cards_date"])
                self.assertEqual(data["tags_date"], "2026-10-13")
                self.assertTrue(data["stale"])
        self.loaded.data["bulk"] = {"default_cards": "2026-10-14"}
        self.assertIsNone(self.bracket()["data"]["tags_date"])
        self.assertTrue(self.bracket()["data"]["stale"])

    def test_future_source_dates_are_displayed_but_not_trusted_as_fresh(self):
        for source in FRESH:
            with self.subTest(source=source):
                self.loaded.data["bulk"] = {**FRESH, source: "2026-10-16"}
                data = self.bracket()["data"]
                key = "cards_date" if source == "default_cards" else "tags_date"
                self.assertEqual(data[key], "2026-10-16")
                self.assertTrue(data["stale"])

    def test_missing_or_damaged_index_metadata_does_not_break_stats(self):
        for bulk in (None, [], "unknown", {}):
            with self.subTest(bulk=bulk):
                self.loaded.data["bulk"] = bulk
                self.assertEqual(self.bracket()["data"], {
                    "cards_date": None, "tags_date": None, "combos_date": "2026-10-14",
                    "stale": True, "dates_stale": True, "max_age_days": 7, **CURRENT})
        del self.loaded.data["bulk"]
        self.assertTrue(self.bracket()["data"]["stale"])
        with mock.patch.object(cards, "info", side_effect=OSError("Index metadata unavailable")):
            self.assertTrue(self.bracket()["data"]["stale"])

    def test_missing_tags_never_claim_no_tagged_effects(self):
        with mock.patch.object(commander, "TAG_FILE", FIXTURES / "no-such-tags.jsonl"):
            bracket = self.bracket()
        self.assertIsNone(bracket["mass_land_denial"])
        self.assertIsNone(bracket["extra_turns"])
        self.assertIn("No Game Changers.", bracket["reasons"])
        self.assertTrue(any("weren't counted" in reason for reason in bracket["reasons"]))
        self.assertNotIn("No Game Changers, mass land denial or extra turns.", bracket["reasons"])

    def test_known_effects_keep_existing_lists_and_minimum(self):
        text = CLEAN.replace("99 Forest", "96 Forest\n1 Smothering Tithe\n1 Armageddon\n1 Time Warp")
        bracket = self.bracket(text)
        self.assertEqual(bracket["minimum"], 4)
        self.assertEqual(bracket["game_changers"], [{"name": "Smothering Tithe", "qty": 1}])
        self.assertEqual(bracket["mass_land_denial"], [{"name": "Armageddon", "qty": 1}])
        self.assertEqual(bracket["extra_turns"], [{"name": "Time Warp", "qty": 1}])

    def test_unknown_names_are_deduplicated_across_relevant_sections(self):
        text = ("Commander\n1 Unknown Commander\n1 Unknown Repeat\n\n"
                "Deck\n96 Forest\n1 Unknown Deck\n2 Unknown Repeat\n\n"
                "Companion\n1 Unknown Companion\n1 Unknown Repeat\n\n"
                "Sideboard\n1 Unknown Sideboard\n")
        self.assertEqual(self.bracket(text)["unknown_cards"],
                         ["Unknown Commander", "Unknown Companion", "Unknown Deck", "Unknown Repeat"])

    def test_sideboard_cards_do_not_raise_bracket_or_incomplete_card_check(self):
        text = CLEAN + "\nSideboard\n1 Smothering Tithe\n1 Armageddon\n1 Time Warp\n1 Unknown Sideboard\n"
        bracket = self.bracket(text)
        self.assertEqual(bracket["minimum"], 1)
        self.assertEqual(bracket["unknown_cards"], [])
        for field in ("game_changers", "mass_land_denial", "extra_turns"):
            self.assertEqual(bracket[field], [])
        self.assertIn("No Game Changers, mass land denial or extra turns.", bracket["reasons"])


class OfficialListTests(FixtureStats):
    """E9-S24: Wizards' latest Commander announcement against the card data and
    the bracket rules, read from the PC only."""

    def official(self, **changes):
        state = {**json.loads(OFFICIAL.read_text(encoding="utf-8")), **changes}
        path = self.tmp / "official_lists.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        return mock.patch.object(commander, "OFFICIAL_FILE", path)

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_an_announcement_after_the_card_data_warns_even_when_the_data_is_fresh(self):
        later = {"date": "2026-10-14", "url": "https://magic.wizards.com/en/news/announcements/x"}
        with self.official(announcement=later):
            data = self.bracket()["data"]
        self.assertFalse(data["dates_stale"])
        self.assertEqual((data["cards_date"], data["official_announcement"]), ("2026-10-14", later))
        self.assertTrue(data["cards_older_than_announcement"])     # the same day: may predate it
        self.assertTrue(data["rules_older_than_announcement"])
        self.assertTrue(data["stale"])

    def test_newer_card_data_still_warns_while_the_bracket_rules_are_older(self):
        later = {"date": "2026-10-12", "url": "https://magic.wizards.com/en/news/announcements/x"}
        with self.official(announcement=later):
            data = self.bracket()["data"]
        self.assertFalse(data["cards_older_than_announcement"])
        self.assertTrue(data["rules_older_than_announcement"])
        self.assertTrue(data["stale"])
        with self.official(announcement=later), mock.patch.object(commander, "BRACKET_RULES_DATE", "2026-10-12"):
            data = self.bracket()["data"]          # reviewed: the rules' date is the announcement's
        self.assertEqual(data["rules_date"], "2026-10-12")
        self.assertFalse(data["rules_older_than_announcement"])
        self.assertFalse(data["stale"])

    def test_no_good_check_in_a_week_is_unknown(self):
        cases = ({"last_success_at": "2026-10-08T00:00:00+00:00"},       # 7 days: still known
                 {"last_success_at": "2026-10-07T23:59:00+00:00"},
                 {"last_success_at": None}, {"last_success_at": "2026-10-16T00:00:00+00:00"},
                 {"announcement": None}, {"format": 2})
        for changes, unknown in zip(cases, (False, True, True, True, True, True)):
            with self.subTest(changes=changes), self.official(**changes):
                data = self.bracket()["data"]
                self.assertIs(data["official_unknown"], unknown)
                self.assertIs(data["stale"], unknown)
        with self.official(last_success_at="2026-10-01T00:00:00+00:00", error="OSError: offline"):
            data = self.bracket()["data"]
        self.assertEqual((data["official_checked"], data["official_announcement"]), ("2026-10-01", ANNOUNCED))
        with mock.patch.object(commander, "OFFICIAL_FILE", self.tmp / "never-checked.json"):
            data = self.bracket()["data"]
        self.assertEqual((data["official_unknown"], data["official_checked"], data["official_announcement"],
                          data["cards_older_than_announcement"], data["stale"]), (True, None, None, False, True))

    def test_reading_never_fetches(self):
        with mock.patch.object(official_lists, "update", side_effect=AssertionError("no check in stats")):
            self.assertFalse(self.bracket()["data"]["stale"])


class TwoCardComboTests(FixtureStats):
    """E9-S23: the fixture combo list (fixtures/stats_combos.json) pairs fixture cards."""

    def deck(self, commander="Finneas, Ace Archer", cards=(), sideboard=()):
        lines = "".join(f"1 {name}\n" for name in cards)
        text = f"Commander\n1 {commander}\n\nDeck\n{99 - len(cards)} Forest\n{lines}"
        if sideboard:
            text += "\nSideboard\n" + "".join(f"1 {name}\n" for name in sideboard)
        return self.bracket(text)

    def test_none_found_is_checked_with_the_lists_date(self):
        combos = self.bracket()["combos"]
        self.assertEqual(combos, {"checked": True, "list_date": "2026-10-14T03:14:00.560664+00:00",
                                  "version": "7.3.0", "matches": []})
        self.assertIn("commander-spellbook", self.bracket()["sources"])
        result = stats.deck_stats(decks.parse_decklist(CLEAN), "commander")
        self.assertEqual(result["sources"]["commander-spellbook"]["date"], "list of 2026-10-14, version 7.3.0")

    def test_a_standalone_infinite_combo_raises_the_floor_to_three(self):
        bracket = self.deck(cards=("Serra Angel", "Pelakka Wurm"))
        self.assertEqual((bracket["minimum"], bracket["cards_minimum"]), (3, 1))     # the combo's floor alone
        self.assertEqual(bracket["combos"]["matches"], [{
            "names": ["Serra Angel", "Pelakka Wurm"], "results": ["Infinite damage", "Infinite lifegain"],
            "class": "infinite", "standalone": True, "raises_floor": True, "floor": 3,
            "url": "https://commanderspellbook.com/combo/1-2/"}])
        self.assertIn("Holds both pieces of a two-card combo that goes infinite or ends the game "
                      "(none in Brackets 1-2): Serra Angel + Pelakka Wurm", bracket["reasons"])

    def test_a_commander_piece_counts_only_as_the_commander(self):
        in_the_99 = self.deck(cards=("Wilson, Refined Grizzly", "Grizzly Bears"))
        self.assertEqual((in_the_99["combos"]["matches"], in_the_99["minimum"]), ([], 1))
        commanding = self.deck("Wilson, Refined Grizzly", cards=("Grizzly Bears",))
        self.assertEqual([m["names"] for m in commanding["combos"]["matches"]],
                         [["Wilson, Refined Grizzly", "Grizzly Bears"]])
        self.assertEqual((commanding["combos"]["matches"][0]["class"], commanding["minimum"]), ("win", 3))

    def test_a_piece_only_in_the_sideboard_isnt_a_match(self):
        bracket = self.deck(cards=("Serra Angel",), sideboard=("Pelakka Wurm",))
        self.assertEqual((bracket["combos"]["matches"], bracket["minimum"]), ([], 1))

    def test_helpers_locks_and_draws_are_listed_but_raise_nothing(self):
        bracket = self.deck(cards=("Garruk's Companion", "Changeling Outcast", "Rampant Growth",
                                   "Myriad Landscape", "Opt", "Boon of the Wish-Giver"))
        found = {m["class"]: m for m in bracket["combos"]["matches"]}
        self.assertEqual(set(found), {"infinite", "lock", "draw"})
        self.assertFalse(found["infinite"]["standalone"])
        self.assertFalse(any(m["raises_floor"] for m in found.values()))
        self.assertEqual(bracket["minimum"], 1)
        self.assertFalse(any("Holds both pieces" in r for r in bracket["reasons"]))

    def test_a_standalone_land_destroying_combo_counts_as_mass_land_denial(self):
        bracket = self.deck(cards=("Fireball", "Shatterskull Smashing"))
        self.assertEqual(bracket["minimum"], 4)
        self.assertEqual(bracket["mass_land_denial"], [])      # the tagged cards stay as they are
        self.assertIn("Holds both pieces of a two-card combo that destroys lands (mass land denial, not allowed "
                      "in Brackets 1-3): Fireball + Shatterskull Smashing // Shatterskull, the Hammer Pass",
                      bracket["reasons"])

    def test_a_helper_only_land_destroying_combo_counts_as_mass_land_denial_too(self):
        # Spellbook marks "Mass Land Denial" a helper result in every combo (Stasis + Time Elemental).
        bracket = self.deck(cards=("Kitchen Finks", "Worldspine Wurm"))
        [match] = bracket["combos"]["matches"]
        self.assertEqual((match["class"], match["standalone"], match["floor"], match["raises_floor"]),
                         ("mass_land_denial", False, 4, True))
        self.assertEqual(bracket["minimum"], 4)
        self.assertIn("Holds both pieces of a two-card combo that destroys lands (mass land denial, not allowed "
                      "in Brackets 1-3): Kitchen Finks + Worldspine Wurm", bracket["reasons"])

    def test_an_unreadable_list_says_not_checked_never_none_found(self):
        for path in (FIXTURES / "no-such-combos.json", FIXTURES / "stats_tags.jsonl"):
            with self.subTest(path=path.name), mock.patch.object(commander, "COMBO_FILE", path):
                result = stats.deck_stats(decks.parse_decklist(CLEAN.replace(
                    "99 Forest", "97 Forest\n1 Serra Angel\n1 Pelakka Wurm")), "commander")
                bracket = result["commander"]["bracket"]
                self.assertFalse(bracket["combos"]["checked"])
                self.assertNotIn("matches", bracket["combos"])
                self.assertEqual(bracket["minimum"], 1)
                self.assertIsNone(bracket["data"]["combos_date"])
                self.assertTrue(bracket["data"]["stale"])
                self.assertIn("Two-card combos weren't checked (the combo list can't be read).", bracket["reasons"])
                self.assertTrue(any("two-card combos weren't checked" in w for w in result["warnings"]))
                self.assertEqual(result["sources"]["commander-spellbook"]["date"],
                                 "not downloaded yet or can't be read, so combos weren't checked")


if __name__ == "__main__":
    unittest.main()
