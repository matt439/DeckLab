"""Tests for decklab.lib.decks.decklist (through decks): Arena/MTGO decklist
lines and blocks, and basic lands. The fixtures are in test_decks.py (see its
docstring).

Run from the repo root:
    python scripts/test_fixtures.py
"""
import re
import unittest

from decklab.lib import decks
from decklab.lib.decks import DeckLine
from decklab.tests.test_decks import EXPECTED_DECKS, FIXTURE_FILES


class DecklistLineTests(unittest.TestCase):

    def test_standard_line(self):
        self.assertEqual(decks.parse_line("4 Llanowar Elves (FDN) 227"),
                         DeckLine(4, "Llanowar Elves", "fdn", "227", "nonfoil"))

    def test_foil_and_etched(self):
        self.assertEqual(decks.parse_line("1 Pelakka Wurm (FDN) 720 *F*").finish, "foil")
        self.assertEqual(decks.parse_line("2 Borborygmos and Fblthp (WAR) 1 *E*").finish, "etched")

    def test_basic_without_set(self):
        self.assertEqual(decks.parse_line("9 Forest"), DeckLine(9, "Forest"))

    def test_set_without_number(self):
        self.assertEqual(decks.parse_line("1 Grim Lavamancer (SLD)"),
                         DeckLine(1, "Grim Lavamancer", "sld", None))

    def test_collector_numbers_with_letters_and_symbols(self):
        for number in ("ELD-97", "C14-146", "123a", "55★", "A-12"):
            line = decks.parse_line(f"1 Card Name (PLST) {number}")
            self.assertEqual((line.name, line.set, line.number), ("Card Name", "plst", number))

    def test_awkward_names(self):
        names = ["Ruby, Daring Tracker", "Garruk's Uprising", "Sakura-Tribe Elder",
                 "Murderous Rider // Swift End", "Jötun Grunt", "Erase (Not the Urza's Legacy One)",
                 "Pollen-Shield Hare // Hare Raising", "Bonders' Enclave", "Hazmat Suit (Used)"]
        for name in names:
            self.assertEqual(decks.parse_line(f"1 {name} (ABC) 1").name, name)
        self.assertEqual(decks.parse_line("1 Erase (Not the Urza's Legacy One)").name,
                         "Erase (Not the Urza's Legacy One)")

    def test_a_bracketed_word_at_the_end_is_part_of_the_name(self):
        # A set with no number after it has to be in capitals, as Arena writes it.
        self.assertEqual(decks.parse_line("1 Hazmat Suit (Used)"), DeckLine(1, "Hazmat Suit (Used)"))
        self.assertEqual(decks.parse_line("1 Llanowar Elves (foil)"), DeckLine(1, "Llanowar Elves (foil)"))
        self.assertEqual(decks.parse_line("1 Hazmat Suit (Used) (UST) 57"),
                         DeckLine(1, "Hazmat Suit (Used)", "ust", "57"))
        self.assertEqual(decks.parse_line("1 Hazmat Suit (Used) (UST)"),
                         DeckLine(1, "Hazmat Suit (Used)", "ust", None))
        for line in (DeckLine(1, "Hazmat Suit (Used)", "ust", "57"), DeckLine(1, "Hazmat Suit (Used)", "ust"),
                     DeckLine(1, "Hazmat Suit (Used)")):
            self.assertEqual(decks.parse_line(decks.format_line(line)), line)

    def test_format_is_the_inverse(self):
        for text in ["4 Llanowar Elves (FDN) 227", "1 Pelakka Wurm (FDN) 720 *F*",
                     "2 Borborygmos and Fblthp (WAR) 1 *E*", "9 Forest", "1 Grim Lavamancer (SLD)",
                     "2 Murderous Rider // Swift End (PLST) ELD-97", "1 Forest *F*",
                     "1 Hazmat Suit (Used) (UST) 57"]:
            self.assertEqual(decks.format_line(decks.parse_line(text)), text)

    def test_lenient_input_is_normalised(self):
        line = decks.parse_line("  4x  Llanowar Elves  (fdn)  227  *f* ")
        self.assertEqual(decks.format_line(line), "4 Llanowar Elves (FDN) 227 *F*")

    def test_set_and_finish_without_number(self):
        self.assertEqual(decks.parse_line("1 Grim Lavamancer (SLD) *F*"),
                         DeckLine(1, "Grim Lavamancer", "sld", None, "foil"))

    def test_bad_lines(self):
        for text in ["Forest", "0 Forest", "", "four Forest", "4", "-1 Forest",
                     "1 Card Name (FDN) 12 34", "2 Opt (FDN) 512 extra *F*", "1 Opt (fdn) 512 (FDN) 512"]:
            with self.assertRaises(decks.DecklistError, msg=text):
                decks.parse_line(text)

    def test_lines_that_would_not_read_back_are_refused(self):
        bad = [DeckLine(0, "Opt"), DeckLine(1, "Opt\n## Notes"), DeckLine(1, "Opt "),
               DeckLine(1, ""), DeckLine(1, "Opt", None, "512"), DeckLine(1, "Opt", "fdn", "5 12"),
               DeckLine(1, "Opt", "f d n", "512"), DeckLine(1, "Opt", "fdn", "512", "gold"),
               DeckLine(1, "Opt", "fdn", "(512)")]
        for line in bad:
            with self.subTest(line), self.assertRaises(ValueError):
                decks.format_line(line)


class DecklistBlockTests(unittest.TestCase):

    def test_every_block_in_the_deck_files_round_trips(self):
        """parse_decklist and format_decklist are exact inverses on every fenced
        block in the frozen deck files (found independently of read_deck_file)."""
        blocks = []
        for path in FIXTURE_FILES:
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            blocks += re.findall(r"^```[^\n]*\n(.*?)^```", text, re.M | re.S)
        self.assertEqual(len(blocks), 2 * len(EXPECTED_DECKS))
        for block in blocks:
            sections = decks.parse_decklist(block)
            self.assertEqual(decks.format_decklist(sections), block)
            self.assertEqual(decks.parse_decklist(decks.format_decklist(sections)), sections)
            self.assertEqual(decks.format_decklist(sections, "\r\n"), block.replace("\n", "\r\n"))

    def test_sections(self):
        text = "Commander\n1 Giada, Font of Hope (FDC) 4 *F*\n\nDeck\n1 Sol Ring (FDC) 286\n31 Plains\n"
        sections = decks.parse_decklist(text)
        self.assertEqual(list(sections), ["Commander", "Deck"])
        self.assertEqual(decks.card_count(sections), 33)
        self.assertEqual(decks.parse_decklist(text.replace("\n", "\r\n")), sections)

    def test_sections_are_written_in_canonical_order(self):
        text = "sideboard:\n1 Negate (FDN) 710\n\nDECK\n4 Opt (FDN) 512\n\nCompanion\n1 Lurrus of the Dream-Den\n"
        sections = decks.parse_decklist(text)
        self.assertEqual(list(sections), ["Companion", "Deck", "Sideboard"])
        self.assertEqual(decks.format_decklist(sections),
                         "Companion\n1 Lurrus of the Dream-Den\n\nDeck\n4 Opt (FDN) 512\n\n"
                         "Sideboard\n1 Negate (FDN) 710\n")

    def test_cards_before_a_header_go_in_the_deck(self):
        self.assertEqual(decks.parse_decklist("4 Opt (FDN) 512\n"), {"Deck": [DeckLine(4, "Opt", "fdn", "512")]})

    def test_empty_sections_are_dropped(self):
        self.assertEqual(decks.parse_decklist("Deck\n4 Opt\n\nSideboard\n"), {"Deck": [DeckLine(4, "Opt")]})
        self.assertEqual(decks.format_decklist({"Deck": [DeckLine(4, "Opt")], "Sideboard": []}), "Deck\n4 Opt\n")
        self.assertEqual(decks.format_decklist({}), "")

    def test_card_after_blank_line_without_header_is_an_error(self):
        with self.assertRaisesRegex(decks.DecklistError, "line 4"):
            decks.parse_decklist("Deck\n4 Opt\n\n2 Negate\n")

    def test_bad_line_reports_its_number(self):
        with self.assertRaisesRegex(decks.DecklistError, "line 3.*Maybeboard"):
            decks.parse_decklist("Deck\n4 Opt\nMaybeboard\n")

    def test_unknown_section_is_refused_when_writing(self):
        with self.assertRaises(ValueError):
            decks.format_decklist({"Maybeboard": [DeckLine(1, "Opt")]})


class BasicLandTests(unittest.TestCase):

    def test_is_basic_land(self):
        for name in ("Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
                     "Snow-Covered Plains", "Snow-Covered Forest", "Snow-Covered Wastes"):
            self.assertTrue(decks.is_basic_land(name), name)
        for name in ("Plains // Plains", "Forest Bear", "forest", "Snow-Covered", "Evolving Wilds", ""):
            self.assertFalse(decks.is_basic_land(name), name)


if __name__ == "__main__":
    unittest.main()
