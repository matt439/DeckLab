"""A deck's Considering list (E2-S23, lib/decks/considering.py and api/considering.py): its "## Considering"
block is read and written apart from the Planned and Play-now lists, nothing that reads a deck's lists
counts its cards, and the deck page shows it with each card's free copies and saves a card moved into the
Planned list in one save.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import api, decks, pool
from decklab.lib.api import considering as considering_api
from decklab.lib.decks import DeckLine
from decklab.lib.inventory import pg_decks
from decklab.tests.test_decks import parse, read
from decklab.tests.test_editor import TABLE_DECK, EditorTestCase
from decklab.tests import test_pool as pool_fixture
from decklab.tests.test_pool import PoolTestCase, deck_md

setUpModule = pool_fixture.setUpModule
tearDownModule = pool_fixture.tearDownModule

BLOCK = "## Considering\n\n```\n2 Llanowar Elves (FDN) 227\n1 Wrath of God\n```\n"
# Table Test with a Considering section between its Decklist and its table.
CONSIDERING_DECK = TABLE_DECK.replace("## Owned vs needed", "## Considering\n\n```\n1 Black Lotus (LEA) 232\n"
                                      "2 Elvish Mystic (CMM) 648\n```\n\n## Owned vs needed", 1)


class ParseAndRenderTests(unittest.TestCase):
    """deckfile.parse_deck and render.render_deck_file."""

    def test_a_deck_without_one_has_none(self):
        deck = read("casual/gruul-ramp")
        self.assertIsNone(deck.considering)
        self.assertEqual(decks.render_deck_file(deck), deck.text)

    def test_the_block_is_read_apart_from_both_lists(self):
        text = "# T\n\n- **Status:** idea\n\n## Decklist\n\n```\nDeck\n4 Forest\n```\n\n" + BLOCK + "\n## Notes\n\nN\n"
        deck = parse(text)
        self.assertEqual(deck.considering, [DeckLine(2, "Llanowar Elves", "fdn", "227"), DeckLine(1, "Wrath of God")])
        self.assertEqual(deck.target, {"Deck": [DeckLine(4, "Forest")]})
        self.assertIsNone(deck.owned)
        self.assertEqual(decks.render_deck_file(deck), text)      # unchanged: byte for byte

    def test_a_new_one_goes_after_the_decklist(self):
        deck = read("casual/gruul-ramp")
        deck.considering = [DeckLine(2, "Llanowar Elves", "fdn", "227")]
        text = decks.render_deck_file(deck)
        self.assertIn("```\n\n## Considering\n\n```\n2 Llanowar Elves (FDN) 227\n```\n\n## Owned vs needed", text)
        again = decks.parse_deck(text.encode(), "gruul-ramp", "casual")
        self.assertEqual((again.target, again.owned, again.rows, again.total, again.considering),
                         (deck.target, deck.owned, deck.rows, deck.total, deck.considering))
        self.assertEqual(text.replace("## Considering\n\n```\n2 Llanowar Elves (FDN) 227\n```\n\n", ""), deck.text)

    def test_edits_rewrite_only_the_block(self):
        deck = parse("# T\n\n## Decklist\n\n```\n4 Forest\n```\n\n" + BLOCK)
        deck.considering = deck.considering[1:]
        self.assertEqual(decks.render_deck_file(deck),
                         "# T\n\n## Decklist\n\n```\n4 Forest\n```\n\n## Considering\n\n```\n1 Wrath of God\n```\n")
        deck.considering = []
        self.assertTrue(decks.render_deck_file(deck).endswith("## Considering\n\n```\n```\n"))
        bare = parse("# T\n\n## Decklist\n\n```\n4 Forest\n```\n\n## Considering\n\nIdeas.\n")
        self.assertIsNone(bare.considering)
        bare.considering = [DeckLine(1, "Opt")]
        self.assertEqual(parse(decks.render_deck_file(bare)).considering, [DeckLine(1, "Opt")])

    def test_section_headers_and_bad_lines_are_refused(self):
        for block in ("Sideboard\n1 Opt\n", "Deck\n1 Opt\n", "an idea\n"):
            with self.subTest(block=block), self.assertRaises(decks.DecklistError) as caught:
                parse(f"# T\n\n## Decklist\n\n```\n4 Forest\n```\n\n## Considering\n\n```\n{block}```\n")
            self.assertIn("Considering list", str(caught.exception))

    def test_only_a_level_two_heading_counts(self):
        deck = parse("# T\n\n## Decklist\n\n```\n4 Forest\n```\n\n## Notes\n\n### Considering\n\n```\nnot a list\n```\n")
        self.assertIsNone(deck.considering)

    def test_apply_edit_changes_it_without_marking_the_decklist(self):
        deck = parse("# T\n\n- **Status:** idea\n\n## Decklist\n\n```\n4 Forest\n```\n\n" + BLOCK)
        changes = decks.apply_edit(deck, considering=[DeckLine(1, "Opt")], date="2026-10-28")
        self.assertEqual(changes, {"decklist": False, "fields": [], "considering": True})
        self.assertIsNone(deck.changed_on)
        self.assertEqual(decks.apply_edit(deck, considering=[DeckLine(1, "Opt")])["considering"], False)



class NothingCountsItTests(PoolTestCase):
    """The pool, the table and the deck_line rows read only the lists."""

    def setUp(self):
        super().setUp()
        self.cards_csv("collection.csv", ("Sol Ring", "ecc", "57", "nonfoil", 2),
                       ("Wrath of God", "8ed", "58", "nonfoil", 1))
        self.deck("a", "A", "idea", "Deck\n2 Sol Ring\n")
        text = deck_md("Deck B", "built", "Deck\n1 Sol Ring\n") + "\n## Considering\n\n```\n4 Wrath of God\n1 Sol Ring\n```\n"
        self.write("decks/casual/b.md", text)

    def test_a_built_decks_considering_cards_arent_in_use(self):
        held = next(d for d in pool.load_pool().in_use if d.id == "casual/b")
        self.assertEqual(dict(held.cards), {"Sol Ring": 1})
        _, rows = self.check("casual/a")
        self.assertEqual(rows["Sol Ring"]["in_use_elsewhere"], [("Deck B", 1)])
        self.assertEqual(pool.free_copies(pool.load_pool())["Wrath of God"], 1)

    def test_its_own_table_and_lines_leave_them_out(self):
        result, rows = self.check("casual/b")
        self.assertEqual(set(rows), {"Sol Ring"})
        deck = decks.read_deck_file(self.magic / "decks" / "casual" / "b.md")
        self.assertEqual(len(deck.considering), 2)
        self.assertEqual([row[5] for row in pg_decks.lines("casual/b", deck)], ["Sol Ring"])


class ConsideringApiTests(EditorTestCase):
    """The deck page's part and POST /api/deck/considering, in the editor's sandbox."""

    def setUp(self):
        super().setUp()
        from decklab.tests.test_api import _write
        _write(self.box.magic / "decks" / "casual" / "table-test.md", CONSIDERING_DECK)

    def change(self, profile="matt", **data):
        body = {"id": "casual/table-test", "sha256": self.sha("casual/table-test"), **data}
        return considering_api.save_considering(self.body(profile, **body))

    def test_the_deck_page_shows_it_with_free_copies(self):
        view = api.deck_view("casual/table-test")
        part = view["considering"]
        self.assertEqual([(l["qty"], l["name"]) for l in part["lines"]], [(1, "Black Lotus"), (2, "Elvish Mystic")])
        self.assertEqual(part["sha256"], self.sha("casual/table-test"))
        self.assertNotIn("Black Lotus", {l["name"] for s in view["sections"].values() for l in s if l["qty"] > 1})
        self.assertNotIn("Considering", view["sections"])
        p = pool.load_pool()
        free = pool.free_copies(p, pool.self_ids("casual/table-test"))
        # Beyond what the Planned list needs (1 Black Lotus, 1 Elvish Mystic).
        self.assertEqual([l["free"] for l in part["lines"]],
                         [max(free.get("Black Lotus", 0) - 1, 0), max(free.get("Elvish Mystic", 0) - 1, 0)])
        self.assertTrue(all("on_the_way" in l for l in part["lines"]))

    def test_a_viewer_who_cant_see_the_collection_gets_no_free_counts(self):
        with mock.patch("decklab.lib.api.guard.sees_inventory", return_value=False):
            part = api.deck_view("casual/table-test")["considering"]
        self.assertEqual(len(part["lines"]), 2)
        self.assertFalse(any("free" in l or "on_the_way" in l for l in part["lines"]))

    def test_a_product_has_none(self):
        self.assertIsNone(api.deck_view("product/fdn-beginner-box/elves")["considering"])

    def test_moving_a_card_into_the_planned_list_is_one_save(self):
        answer = self.change(action="move", index=1, qty=1)
        self.assertTrue(answer["saved"] and answer["changed"])
        deck = decks.parse_deck(self.text("casual/table-test").encode(), "table-test", "casual")
        self.assertEqual(deck.considering, [DeckLine(1, "Black Lotus", "lea", "232"),
                                            DeckLine(1, "Elvish Mystic", "cmm", "648")])
        self.assertIn(DeckLine(2, "Elvish Mystic", "cmm", "648"), deck.target["Deck"])
        self.assertEqual(answer["marked"], "2026-10-05")        # a Planned list change, as any
        self.assertTrue(answer["table"]["rewritten"])
        # The rest of it, to the sideboard: the line leaves Considering.
        self.change(action="move", index=1, section="Sideboard")
        deck = decks.parse_deck(self.text("casual/table-test").encode(), "table-test", "casual")
        self.assertEqual(deck.considering, [DeckLine(1, "Black Lotus", "lea", "232")])
        self.assertEqual(deck.target["Sideboard"], [DeckLine(1, "Elvish Mystic", "cmm", "648")])

    def test_adding_and_removing_dont_touch_the_lists_or_table(self):
        before = decks.parse_deck(self.text("casual/table-test").encode(), "table-test", "casual")
        answer = self.change(action="add", line={"name": "llanowar elves", "qty": 2})
        self.assertEqual((answer["marked"], answer["table"]["rewritten"]), (None, False))
        deck = decks.parse_deck(self.text("casual/table-test").encode(), "table-test", "casual")
        self.assertEqual(deck.considering[-1].name, "Llanowar Elves")
        self.assertEqual(deck.considering[-1].quantity, 2)
        self.assertEqual((deck.target, deck.rows, deck.changed_on), (before.target, before.rows, None))
        self.change(action="add", line={"name": "Black Lotus", "qty": 1, "set": "lea", "number": "232"})
        deck = decks.parse_deck(self.text("casual/table-test").encode(), "table-test", "casual")
        self.assertEqual(deck.considering[0], DeckLine(2, "Black Lotus", "lea", "232"))
        self.change(action="remove", index=0)
        deck = decks.parse_deck(self.text("casual/table-test").encode(), "table-test", "casual")
        self.assertEqual([l.name for l in deck.considering], ["Elvish Mystic", "Llanowar Elves"])

    def test_refusals(self):
        before = self.text("casual/table-test")
        self.assertApiError(400, lambda: self.change(action="add", line={"name": "Not A Real Card", "qty": 1}))
        self.assertApiError(400, lambda: self.change(action="move", index=5))
        self.assertApiError(400, lambda: self.change(action="move", index=0, qty=3))
        self.assertApiError(400, lambda: self.change(action="move", index=0, section="Commander"))
        self.assertApiError(400, lambda: self.change(action="burn", index=0))
        self.assertApiError(409, lambda: self.change(action="remove", index=0, sha256="0" * 64))
        self.assertApiError(403, lambda: self.change("guest", action="remove", index=0))
        self.assertEqual(self.text("casual/table-test"), before)

    def test_the_editor_sends_it_too(self):
        view = api.edit_view("casual/table-test")
        self.assertEqual([l["name"] for l in view["lists"]["considering"]], ["Black Lotus", "Elvish Mystic"])
        saved = self.save("casual/table-test", {"considering": view["lists"]["considering"][:1]})
        self.assertEqual(saved["marked"], None)
        deck = decks.parse_deck(self.text("casual/table-test").encode(), "table-test", "casual")
        self.assertEqual(deck.considering, [DeckLine(1, "Black Lotus", "lea", "232")])
        self.assertApiError(400, lambda: self.save("casual/table-test", {"considering": {"Deck": []}}))
        check = api.check_draft(self.body(id="casual/table-test", sha256=self.sha("casual/table-test"),
                                          lists={"considering": [{"name": "Nope Nope", "qty": 1}]}))
        self.assertEqual(check["blocks"][0]["list"], "considering")

    def test_the_route_is_registered(self):
        from decklab.lib import feature_routes
        self.assertIn('("deck", "considering"): considering.save_considering',
                      Path(feature_routes.__file__).read_text(encoding="utf-8"))
        json.dumps(api.deck_view("casual/table-test")["considering"], allow_nan=False)
