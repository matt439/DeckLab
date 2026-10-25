"""Built decks reserving their token cards: the Token cards line (lib/decks/tokencards.py), how it's
shared out over a space's rows (lib/tokens/reserve.py), what other decks then see (deck_tokens'
held, row_uses' in_use, shared_rows), the deck page's Packed part and POST /api/deck/token-cards,
and taking a deck apart dropping the line; and the Tokens page's plan of every built deck's line
(lib/tokens/optimise.py, GET/POST /api/tokens/plan)."""
import unittest
from unittest import mock

from decklab.lib import cards, decks, inventory, tokens
from decklab.lib.api import deck_page, token_cards, token_plan
from decklab.lib.api.common import ApiError
from decklab.lib.decks import assembled
from decklab.lib.decks.decklist import DeckFileError
from decklab.tests.test_api_tokens import FIXTURES, TokensApiTestCase
from decklab.tests.test_tokens import deck_md

Line = decks.TokenCardLine


def built(title, deck="1 Army of the Damned\n", packed=None):
    text = deck_md(title, status="built", deck=deck)
    if packed is not None:
        text = text.replace("- **Status:** built", f"- **Status:** built\n- **Token cards:** {packed}")
    return text


class LineTests(unittest.TestCase):
    def test_parse_and_format(self):
        lines = decks.parse_token_cards("2 Treasure (TFDN) 12; 1 Beast // Dog;  1 The Monarch ;")
        self.assertEqual(lines, [Line(2, "Treasure", "", "tfdn", "12"), Line(1, "Beast", "Dog"),
                                 Line(1, "The Monarch")])
        self.assertEqual(decks.format_token_cards(lines), "2 Treasure (TFDN) 12; 1 Beast // Dog; 1 The Monarch")
        self.assertEqual(decks.parse_token_cards(""), [])

    def test_bad_parts_are_refused(self):
        for value in ("Treasure", "0 Treasure", "2 Treasure // Dog // Cat", "2 // Dog"):
            with self.subTest(value=value), self.assertRaises(DeckFileError):
                decks.parse_token_cards(value)

    def test_set_keeps_the_rest_and_taking_apart_drops_it(self):
        deck = decks.parse_deck(built("Zed").encode(), "zed", "casual")
        decks.set_token_cards(deck, [Line(1, "Zombie", "Zombie Knight")])
        text = decks.render_deck_file(deck)
        self.assertIn("- **Token cards:** 1 Zombie // Zombie Knight\n", text)
        self.assertEqual(text.replace("- **Token cards:** 1 Zombie // Zombie Knight\n", ""), built("Zed"))
        again = decks.parse_deck(text.encode(), "zed", "casual")
        self.assertEqual(decks.token_cards(again), [Line(1, "Zombie", "Zombie Knight")])
        decks.set_status(again, "building")
        self.assertFalse(decks.has_token_cards(again))
        self.assertNotIn("Token cards", decks.render_deck_file(again))

    def test_an_empty_line_says_none_are_packed(self):
        deck = decks.parse_deck(built("Zed").encode(), "zed", "casual")
        decks.set_token_cards(deck, [])
        self.assertTrue(decks.has_token_cards(deck))
        self.assertEqual(decks.token_cards(deck), [])
        assembled.clear(deck)
        self.assertFalse(decks.has_token_cards(deck))


class ReservationTests(TokensApiTestCase):
    """ROWS (Zombie // Zombie Knight ×8 among them) and the fixture card index; Army of the Damned
    makes Zombies."""

    loaded = None

    @classmethod
    def setUpClass(cls):
        cls.loaded = cards._prepare(cards.build_index(FIXTURES / "tokens_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                                                      {}, log=lambda *a: None))

    def index(self):
        return self.loaded

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(token_cards, "_writer",
                                    lambda data: {"id": data.get("profile"), "name": "Matt", "role": "admin"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def zombie(self, inv=None):
        inv = inv or tokens.read()
        return next(i for i, r in enumerate(inv.rows) if r["back"] == "Zombie Knight")

    def test_holds_share_rows_out_deck_by_deck(self):
        self.write("tokens.csv", self.csv_text() + "Zombie,Zombie Knight,,,,,1,2/2; black,,printing unconfirmed\n")
        inv = tokens.read()
        first, second = [i for i, r in enumerate(inv.rows) if r["back"] == "Zombie Knight"]
        self.write("decks/casual/a.md", built("A Deck", packed="8 Zombie // Zombie Knight"))
        self.write("decks/casual/b.md", built("B Deck", packed="2 Zombie // Zombie Knight; 1 Treasure"))
        holds = tokens.reserve.holds(inv)
        self.assertEqual(holds["casual/a"]["rows"], {first: 8})
        self.assertEqual(holds["casual/b"]["rows"], {second: 2})             # one left of the second row, one over
        self.assertEqual(holds["casual/b"]["unmatched"], ["1 Treasure"])
        self.assertEqual(tokens.reserve.held_elsewhere(holds, "casual/b"),
                         {first: [{"deck": "casual/a", "title": "A Deck", "quantity": 8}]})

    def test_other_decks_see_packed_cards_as_in_use(self):
        self.write("decks/casual/a.md", built("A Deck", packed="8 Zombie // Zombie Knight"))
        inv = tokens.read()
        zombie = self.zombie(inv)
        held = tokens.reserve.held_elsewhere(tokens.reserve.holds(inv), "casual/b")
        result = tokens.deck_tokens(decks.load_deck("casual/a"), inv, [], held)
        need = next(n for n in result["needs"] if n["name"] == "Zombie")
        self.assertEqual((need["state"], need["cards"]), ("none", []))
        self.assertEqual(need["in_use"], [{"row": zombie, "front": "Zombie", "back": "Zombie Knight", "side": "front",
                                           "quantity": 8, "decks": ["A Deck"]}])
        self.assertEqual(need["words"], "All yours are packed in A Deck")
        # Packing fewer leaves the rest free.
        self.write("decks/casual/a.md", built("A Deck", packed="3 Zombie // Zombie Knight"))
        held = tokens.reserve.held_elsewhere(tokens.reserve.holds(inv), "casual/b")
        need = next(n for n in tokens.deck_tokens(decks.load_deck("casual/a"), inv, [], held)["needs"]
                    if n["name"] == "Zombie")
        self.assertEqual((need["state"], need["cards"][0]["quantity"]), ("check", 5))
        self.assertTrue(need["words"].endswith(" · more packed in A Deck"))
        self.assertNotIn("in_use", need)

    def test_the_tokens_page_and_its_warning(self):
        self.write("decks/casual/a.md", built("A Deck", packed="8 Zombie // Zombie Knight"))
        self.write("decks/casual/b.md", built("B Deck"))
        row = self.row("Zombie", "Zombie Knight")
        self.assertEqual(row["packed"], [{"deck": "casual/a", "title": "A Deck", "link": "casual/a", "quantity": 8}])
        self.assertIn({"deck": "casual/b", "title": "B Deck", "link": "casual/b", "token": "Zombie",
                       "side": "front", "state": "in_use"}, row["uses"])
        self.assertEqual([(h["deck"], h["quantity"]) for h in row["shared"]], [("casual/a", 8), ("casual/b", 1)])
        notes, warnings = [], []
        tokens.check(notes=notes, warnings=warnings)
        self.assertIn("Only 8 cards, but built decks pack 9: A Deck ×8 and B Deck", "\n".join(warnings))
        # A line that packs none of the row: B Deck wants nothing of it.
        self.write("decks/casual/b.md", built("B Deck", packed=""))
        self.assertEqual(self.row("Zombie", "Zombie Knight")["shared"], [])

    def test_the_deck_page_and_its_save(self):
        self.write("decks/casual/a.md", built("A Deck"))
        view = deck_page.deck_view("casual/a")
        packed = view["tokens"]["packed"]
        self.assertEqual((packed["written"], packed["lines"]), (False, []))
        zombie = self.zombie()
        self.assertEqual([(c["row"], c["free"], c["packed"]) for c in packed["choices"]], [(zombie, 8, 0)])
        body = {"id": "casual/a", "expect": packed["expect"], "tokens_sha256": packed["tokens_sha256"],
                "cards": [{"row": zombie, "quantity": 2}]}
        answer = self.call(token_cards.save_token_cards, **body)
        self.assertEqual((answer["saved"], answer["token_cards"]), (True, "2 Zombie // Zombie Knight"))
        packed = deck_page.deck_view("casual/a")["tokens"]["packed"]
        self.assertEqual([line["text"] for line in packed["lines"]], ["2 Zombie // Zombie Knight"])
        self.assertEqual(packed["choices"][0]["packed"], 2)
        with self.assertRaises(ApiError) as caught:     # the old revision
            self.call(token_cards.save_token_cards, **body)
        self.assertEqual(caught.exception.status, 409)
        body["expect"] = packed["expect"]
        with self.assertRaises(ApiError) as caught:     # token cards changed meanwhile
            self.call(token_cards.save_token_cards, **{**body, "tokens_sha256": "0" * 64})
        self.assertEqual(caught.exception.status, 409)
        self.write("decks/casual/a.md", deck_md("A Deck", deck="1 Army of the Damned\n"))
        with self.assertRaises(ApiError) as caught:     # only built decks pack token cards
            self.call(token_cards.save_token_cards,
                      **{**body, "expect": inventory.current().deck("casual/a").sha256})
        self.assertEqual(caught.exception.status, 400)

    def test_finish_building_packs_one_free_card_per_token(self):
        from decklab.lib.api.assembly_completion import _TokenPacking
        self.write("tokens.csv", self.csv_text() + "Zombie,Zombie Knight,,,,,1,2/2; black,,printing unconfirmed\n")
        self.write("decks/casual/a.md", built("A Deck", packed="8 Zombie // Zombie Knight"))
        packing = _TokenPacking()
        b = decks.parse_deck(deck_md("B Deck", deck="1 Army of the Damned\n").encode(), "b", "casual")
        packing.fill(b, decks.load_deck("casual/a"))
        self.assertEqual(decks.token_cards(b), [Line(1, "Zombie", "Zombie Knight")])   # the second row's card
        c = decks.parse_deck(deck_md("C Deck", deck="1 Army of the Damned\n").encode(), "c", "casual")
        packing.fill(c, decks.load_deck("casual/a"))
        self.assertFalse(decks.has_token_cards(c))          # B, in the same save, took the last free card
        kept = decks.parse_deck(built("D Deck", packed="").encode(), "d", "casual")
        packing.fill(kept, decks.load_deck("casual/a"))
        self.assertEqual(kept.get_field("Token cards"), "")  # a line already there is kept



class PlanTests(ReservationTests):
    """The plan over ROWS: Angel // The Monarch ×1, Insect // Goblin ×1, Zombie // Zombie Knight ×8."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(token_plan, "_writer",
                                    lambda data: {"id": data.get("profile"), "name": "Matt", "role": "admin"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def plan(self):
        return {d["id"]: d for d in token_plan.plan_view()["decks"]}

    def test_one_each_then_the_spares_shared_out(self):
        self.write("decks/casual/a.md", built("A Deck"))
        self.write("decks/casual/b.md", built("B Deck", packed="8 Zombie // Zombie Knight"))
        self.write("decks/casual/c.md", built("C Deck", deck="1 Hornet Queen\n"))
        plan = self.plan()
        self.assertEqual(sorted(plan), ["casual/a", "casual/b", "casual/c"])     # the building Queen Deck isn't in it
        self.assertEqual((plan["casual/a"]["after"], plan["casual/a"]["spares"]), ("4 Zombie // Zombie Knight", 3))
        self.assertEqual((plan["casual/b"]["before"], plan["casual/b"]["after"]),
                         ("8 Zombie // Zombie Knight", "4 Zombie // Zombie Knight"))
        self.assertEqual(plan["casual/a"]["lines"], [{"text": "4 Zombie // Zombie Knight",
                                                      "sides": ["Zombie side only, can be sleeved"]}])
        self.assertEqual(plan["casual/a"]["packs"], [{"token": "Zombie", "card": "Zombie / Zombie Knight",
                                                      "side": "front", "verdict": "check"}])
        # Hornet Queen's Insect has deathtouch; the only Insect card says it hasn't: a stand-in.
        self.assertEqual(plan["casual/c"]["packs"][0]["verdict"], "differs")
        self.assertEqual(plan["casual/c"]["after"], "1 Insect // Goblin")

    def test_both_faces_and_shortfalls(self):
        self.write("tokens.csv", self.csv_text().replace("Angel,The Monarch,,,,,1,", "Angel,The Monarch,,,,,2,"))
        self.write("decks/casual/court.md", built("Court", deck="1 Court of Grace\n"))
        court = self.plan()["casual/court"]
        self.assertEqual(court["after"], "2 Angel // The Monarch")
        self.assertEqual(court["lines"][0]["sides"], ["both sides used"])
        self.assertEqual(court["short"], ["Spirit"])
        # Only one card: one of the two is short.
        self.write("tokens.csv", self.csv_text().replace("Angel,The Monarch,,,,,2,", "Angel,The Monarch,,,,,1,"))
        court = self.plan()["casual/court"]
        self.assertEqual((court["after"], len(court["short"])), ("1 Angel // The Monarch", 2))

    def test_single_sided_cards_go_first(self):
        self.write("tokens.csv", self.csv_text() + "Zombie,,,,,,1,,,single-sided verified\n")
        self.write("decks/casual/a.md", built("A Deck"))
        self.write("decks/casual/b.md", built("B Deck"))
        plan = self.plan()
        self.assertEqual([p["card"] for p in plan["casual/a"]["packs"]], ["Zombie"])
        self.assertEqual([p["card"] for p in plan["casual/b"]["packs"]], ["Zombie / Zombie Knight"])

    def test_apply_saves_every_line_once(self):
        self.write("decks/casual/a.md", built("A Deck"))
        self.write("decks/casual/b.md", built("B Deck"))
        view = token_plan.plan_view()
        self.assertEqual(view["changes"], 2)
        answer = self.call(token_plan.apply_plan, sha256=view["sha256"])
        self.assertEqual(answer, {"saved": 2, "decks": ["casual/a", "casual/b"]})
        saved = decks.parse_deck(inventory.current().deck("casual/a").text.encode(), "a", "casual")
        self.assertEqual(decks.token_cards(saved), [Line(4, "Zombie", "Zombie Knight")])
        with self.assertRaises(ApiError) as caught:             # the decks changed since that preview
            self.call(token_plan.apply_plan, sha256=view["sha256"])
        self.assertEqual(caught.exception.status, 409)
        again = token_plan.plan_view()
        self.assertEqual(again["changes"], 0)
        self.assertEqual(self.call(token_plan.apply_plan, sha256=again["sha256"]), {"saved": 0, "decks": []})
        with mock.patch.object(token_plan.guard, "allowed", lambda *a, **k: False):
            self.write("decks/casual/a.md", built("A Deck", packed=""))
            with self.assertRaises(ApiError) as caught:
                self.call(token_plan.apply_plan, sha256=token_plan.plan_view()["sha256"])
            self.assertEqual((caught.exception.status, str(caught.exception)),
                             (403, "You can't change A Deck's token cards."))


if __name__ == "__main__":
    unittest.main()
