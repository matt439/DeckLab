"""The Considering list (E2-S23): a deck text's "## Considering" block of cards that might go in the
deck. The parser reads it into DeckFile.considering and every save keeps it byte for byte; owned vs
needed, the table, the shared pool, the Forge list and the sleeve count never count it; the deck page
shows it with how many copies the pool has free.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import unittest

from decklab.lib import accessories, decks, pool
from decklab.lib.api import deck_page
from decklab.lib.decks import DeckLine, TableRow, TotalRow
from decklab.lib.forge import lists as forge_lists
from decklab.tests.test_pool import PoolTestCase, deck_md, setUpModule, tearDownModule  # noqa: F401

BLOCK = "## Considering\n\nA few cards to try.\n\n```\n2 Elvish Mystic\n1 Sol Ring (FDN) 1 *F*\n```\n"


def with_considering(text, block=BLOCK):
    """text with the Considering block straight after its decklist."""
    head, rule, rest = text.partition("```\n\n## ")
    if not rule:
        return text + "\n" + block
    return f"{head}```\n\n{block}\n## {rest}"


TEXT = with_considering(deck_md("A", "building", "Deck\n4 Llanowar Elves\n20 Forest\n",
                                table="| Llanowar Elves | 4 | 0 | 4 | | | |\n"))


def parse(text=TEXT):
    return decks.parse_deck(text.encode(), "a", "casual")


class ParsingTests(unittest.TestCase):

    def test_the_block_is_read_and_kept_out_of_both_lists(self):
        deck = parse()
        self.assertEqual(deck.considering, [DeckLine(2, "Elvish Mystic"), DeckLine(1, "Sol Ring", "fdn", "1", "foil")])
        self.assertEqual(decks.format_decklist(deck.target), "Deck\n4 Llanowar Elves\n20 Forest\n")
        self.assertIsNone(deck.owned)
        self.assertEqual([r.card for r in deck.rows], ["Llanowar Elves"])

    def test_a_deck_without_one_has_none_and_an_empty_one_is_empty(self):
        self.assertIsNone(parse(deck_md("A", "idea", "Deck\n1 Opt\n")).considering)
        self.assertEqual(parse(with_considering(deck_md("A", "idea", "Deck\n1 Opt\n"),
                                                "## Considering\n\n```\n```\n")).considering, [])

    def test_round_trip_is_byte_identical(self):
        self.assertEqual(decks.render_deck_file(parse()), TEXT)

    def test_a_save_of_the_lists_status_and_table_keeps_it_as_written(self):
        deck = parse()
        deck.target["Deck"][0].quantity = 3
        deck.target["Sideboard"] = [DeckLine(1, "Pick Your Poison")]
        decks.set_status(deck, "built")
        decks.set_table(deck, [TableRow("Llanowar Elves", 3, 0, 3), TableRow("Pick Your Poison", 1, 0, 1)],
                        TotalRow(4, ""))
        decks.mark_decklist_changed(deck, "2026-10-27")
        text = decks.render_deck_file(deck)
        self.assertIn(BLOCK, text)
        again = parse(text)
        self.assertEqual(again.considering, parse().considering)
        self.assertEqual(again.target, deck.target)
        self.assertEqual(again.status, "built")

    def test_a_new_play_now_list_goes_in_without_touching_it(self):
        deck = parse()
        deck.owned = {"Deck": [DeckLine(4, "Elvish Mystic")]}
        text = decks.render_deck_file(deck)
        self.assertIn(BLOCK, text)
        again = parse(text)
        self.assertEqual(again.owned, deck.owned)
        self.assertEqual(again.considering, parse().considering)

    def test_section_headers_and_bad_lines_are_refused(self):
        for body in ("Sideboard\n1 Opt\n", "Deck\n1 Opt\n\nSideboard\n1 Opt\n", "one Opt\n"):
            with self.subTest(body=body):
                with self.assertRaisesRegex(decks.DecklistError, "Considering list"):
                    parse(with_considering(deck_md("A", "idea", "Deck\n1 Opt\n"), f"## Considering\n\n```\n{body}```\n"))

    def test_only_a_level_two_heading_starts_it(self):
        text = deck_md("A", "idea", "Deck\n1 Opt\n") + "\n## Notes\n\n### Considering\n\n```\n1 Sol Ring\n```\n"
        self.assertIsNone(parse(text).considering)


class CountedNowhereTests(PoolTestCase):
    """A Considering list never counts as needed, missing or in use."""

    def setUp(self):
        super().setUp()
        self.cards_csv("collection.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 2),
                       ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.write("decks/casual/a.md", TEXT)

    def test_owned_vs_needed_and_the_table_skip_it(self):
        result, rows = self.check("casual/a")
        self.assertEqual(set(rows), {"Llanowar Elves"})
        self.assertEqual(result["totals"]["missing"], 0)
        deck = decks.read_deck_file(self.magic / "decks/casual/a.md")
        table, _, _ = pool.deck_table(deck, prices=False)
        self.assertEqual([r.card for r in table], ["Llanowar Elves"])

    def test_a_built_decks_considering_cards_stay_free_for_other_decks(self):
        self.write("decks/casual/a.md", TEXT.replace("**Status:** building", "**Status:** built"))
        self.deck("b", "B", "idea", "Deck\n2 Elvish Mystic\n")
        held = next(d for d in pool.load_pool().in_use if d.id == "casual/a")
        self.assertNotIn("Elvish Mystic", held.cards)
        _, rows = self.check("casual/b")
        self.assertEqual((rows["Elvish Mystic"]["missing"], rows["Elvish Mystic"]["in_use_elsewhere"]), (0, []))

    def test_the_forge_list_skips_it(self):
        sections = decks.load_deck("casual/a")
        played = forge_lists._section_cards(sections)
        self.assertEqual(played["Main"], [[4, "Llanowar Elves"], [20, "Forest"]])
        bare = decks.parse_deck(deck_md("A", "building", "Deck\n4 Llanowar Elves\n20 Forest\n").encode(), "a", "casual")
        self.assertEqual(forge_lists.card_sha(sections, "constructed"), forge_lists.card_sha(bare.target, "constructed"))

    def test_the_sleeve_count_skips_it(self):
        self.assertEqual(accessories.sleeve_need(decks.load_deck("casual/a")), 24)

    def test_the_deck_page_marks_copies_free_in_the_pool(self):
        self.deck("b", "B", "built", "Deck\n1 Elvish Mystic\n")
        deck = decks.read_deck_file(self.magic / "decks/casual/a.md")
        info = []
        lines = deck_page._view_considering(deck, "casual/a", deck.target, pool.load_pool(), info, [])
        self.assertEqual([(line["name"], line["qty"], line["free"]) for line in lines],
                         [("Elvish Mystic", 2, 1), ("Sol Ring", 1, 0)])
        self.assertEqual(lines[0]["card"]["name"], "Elvish Mystic")
        # A card the shown list already uses leaves only what's left over; no pool, no marks.
        deck.considering = [DeckLine(1, "Llanowar Elves")]
        self.assertEqual(deck_page._view_considering(deck, "casual/a", deck.target, pool.load_pool(), info, [])[0]["free"], 0)
        self.assertNotIn("free", deck_page._view_considering(deck, "casual/a", deck.target, None, info, [])[0])
        deck.considering = None
        self.assertIsNone(deck_page._view_considering(deck, "casual/a", deck.target, None, info, []))


if __name__ == "__main__":
    unittest.main()
