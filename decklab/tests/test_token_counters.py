"""The counters and dice a deck's cards call for (E7-S24's read-only slice, lib/tokens/counters.py): the
kinds read from rules text, types and keywords, the words that aren't kinds, the deck's needs in
deck_tokens' "counters", the deck printout's lines, and that they go only where the deck's tokens go (a
viewer who may not see the space's inventory gets no token part at all).

The cards are test cards added to fixtures/tokens_cards.jsonl's real Scryfall objects (each a copy of
Prideful Parent with its own name, type, text and keywords, and no token link), so no card index is needed.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_token_counters
"""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import access, cards, tokens
from decklab.lib.api import deck_page, guard
from decklab.lib.decks.decklist import DeckLine
from decklab.lib.tokens import counters
from decklab.tests import household_config
from decklab.tests import test_api_tokens as token_fixture
from decklab.tests import test_tokens as fixture

CREATURE = "Creature — Snake"
# (name, type line, rules text, keywords): test cards, never real printings.
EXTRA = (
    ("Venom Drake", CREATURE, "Flying\nToxic 2 (Players dealt combat damage by this creature also get two poison "
                              "counters.)", ["Flying", "Toxic"]),
    ("Grim Return", CREATURE, "Undying", ["Undying"]),        # printed without its reminder text
    ("Siege of Tests", "Battle — Siege", "When this Siege enters, draw a card.", []),
    ("Tale of Tests", "Enchantment — Saga", "(As this Saga enters and after your draw step, add a lore counter.)\n"
                                            "I — Draw a card.\nII — Put a +1/+1 counter on target creature.", []),
    ("Lucky Roller", CREATURE, "When this creature enters, roll a d20. Then you get {E}{E}.\n"
                               "Whenever it attacks, roll two six-sided dice.", []),
    ("Plain Refusal", "Instant", "Counter target spell. Proliferate. (Choose any number of permanents and/or "
                                 "players, then give each another counter of each kind already there.)", ["Proliferate"]),
    ("Shield Bearer", CREATURE, "When this creature enters, put a shield counter and a +1/+1 counter on target "
                                "creature.", []),
)


def extended_index():
    """fixtures/tokens_cards.jsonl's index with EXTRA's cards added."""
    lines = (fixture.FIXTURES / "tokens_cards.jsonl").read_text(encoding="utf-8").splitlines()
    template = next(json.loads(line) for line in lines if json.loads(line)["name"] == "Prideful Parent")
    for i, (name, type_line, text, keywords) in enumerate(EXTRA):
        card = {**template, "name": name, "type_line": type_line, "oracle_text": text, "keywords": keywords,
                "id": f"00000000-0000-4000-8100-{i:012d}", "oracle_id": f"00000000-0000-4000-9100-{i:012d}",
                "collector_number": f"8{i}", "all_parts": []}
        lines.append(json.dumps(card))
    folder = Path(tempfile.mkdtemp())
    try:
        path = folder / "cards.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return cards._prepare(cards.build_index(path, fixture.FIXTURES / "oracle_tags.jsonl", {}, log=lambda *a: None))
    finally:
        shutil.rmtree(folder, True)


class TextTests(unittest.TestCase):
    def test_the_word_before_counter_is_the_kind(self):
        cases = {
            "Undying (When this creature dies, if it had no +1/+1 counters on it, return it with a +1/+1 counter "
            "on it.)": ["+1/+1"],
            "Put a shield counter and a first strike counter on target creature. Remove three time counters.":
                ["shield", "first strike", "time"],
            "Put a −1/−1 counter on each creature.": ["-1/-1"],     # Scryfall's minus sign
            "Put a -1/-1 counter and an oil counter on it.": ["-1/-1", "oil"],
            "When this enters, you get {E}{E}.": ["energy"],
            "Roll a d20. Then roll two six-sided dice. Target player rolls a d4.": ["d20", "d6", "d4"],
        }
        for text, kinds in cases.items():
            self.assertEqual(counters.text_kinds(text), kinds, text)

    def test_words_that_only_count_point_or_counter_a_spell_are_no_kind(self):
        for text in ("Counter target spell. You may counter target spell unless its controller pays {3}.",
                     "Proliferate. (Choose any number of permanents and/or players, then give each another counter "
                     "of each kind already there.)",
                     "Double the number of each kind of counter on target permanent.",
                     "If this spell was kicked, instead counter target spell.",
                     "Players can't get counters.",
                     "Put Zack Fair's counters on that creature.",
                     "Whenever a spell or ability you control counters a spell, draw a card.",
                     "Ward {2} (Whenever this becomes the target of a spell or ability an opponent controls, counter "
                     "it unless that player pays {2}.)",
                     "Roll the planar die.", ""):
            self.assertEqual(counters.text_kinds(text), [], text)

    def test_a_cards_types_and_keywords_add_kinds(self):
        self.assertEqual(counters.card_kinds({"type_line": "Legendary Planeswalker — Test", "oracle_text": "+1: Draw."}),
                         ["loyalty"])
        self.assertEqual(counters.card_kinds({"type_line": "Battle — Siege", "oracle_text": ""}), ["defense"])
        self.assertEqual(counters.card_kinds({"type_line": "Creature — Ooze", "oracle_text": "Infect",
                                              "keywords": ["Infect"]}), ["-1/-1", "poison"])
        # Each face's text and type: a creature that transforms into a planeswalker.
        card = {"type_line": "Legendary Creature — Human", "oracle_text": "Put a +1/+1 counter on it.\n//\n+2: Draw.",
                "faces": [{"type_line": "Legendary Creature — Human", "oracle_text": "Put a +1/+1 counter on it."},
                          {"type_line": "Legendary Planeswalker — Test", "oracle_text": "+2: Draw.", "loyalty": "3"}]}
        self.assertEqual(counters.card_kinds(card), ["+1/+1", "loyalty"])
        self.assertEqual(counters.card_kinds({"type_line": "Instant", "oracle_text": "Draw two cards."}), [])


class DeckCountersTests(fixture.IndexTestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = extended_index()

    def counters(self, deck=(), sideboard=()):
        sections = {"Deck": [DeckLine(q, n) for q, n in deck], "Sideboard": [DeckLine(q, n) for q, n in sideboard]}
        return tokens.deck_tokens(sections, self.real(), [])

    def test_each_kind_with_the_cards_that_use_it_in_order(self):
        result = self.counters(deck=[(2, "Shield Bearer"), (1, "Tale of Tests"), (1, "Grim Return"),
                                     (1, "Elspeth, Sun's Champion"), (1, "Lucky Roller"), (1, "Siege of Tests"),
                                     (1, "Plain Refusal"), (4, "Forest"), (1, "Not A Real Card")],
                               sideboard=[(3, "Venom Drake"), (1, "Shield Bearer")])
        needs = result["counters"]["needs"]
        self.assertEqual([n["key"] for n in needs], ["+1/+1", "defense", "lore", "loyalty", "shield", "energy",
                                                     "poison", "d6", "d20"])
        plus = needs[0]
        self.assertEqual(plus["name"], "+1/+1 counters")
        self.assertEqual(plus["made_by"], [{"name": "Shield Bearer", "quantity": 2, "section": "Deck"},
                                           {"name": "Tale of Tests", "quantity": 1, "section": "Deck"},
                                           {"name": "Grim Return", "quantity": 1, "section": "Deck"},
                                           {"name": "Shield Bearer", "quantity": 1, "section": "Sideboard"}])
        self.assertFalse(plus["sideboard_only"])
        poison = next(n for n in needs if n["key"] == "poison")
        self.assertEqual((poison["group"], poison["name"], poison["sideboard_only"]),
                         ("player", "Poison counters", True))
        self.assertEqual(next(n for n in needs if n["key"] == "loyalty")["made_by"][0]["name"], "Elspeth, Sun's Champion")
        self.assertEqual({n["key"]: n["group"] for n in needs if n["group"] == "die"}, {"d6": "die", "d20": "die"})
        self.assertIn("approximate", result["counters"]["note"])

    def test_counters_change_nothing_else_and_a_list_without_them_has_none(self):
        with_counters = self.counters(deck=[(1, "Hornet Queen"), (1, "Shield Bearer")])
        without = self.counters(deck=[(1, "Hornet Queen")])
        self.assertEqual(without["counters"]["needs"], [])
        for key in ("needs", "counts", "copies", "unlisted", "note"):
            self.assertEqual(with_counters[key], without[key], key)

    def test_the_deck_printout_lists_them(self):
        self.real()
        self.deck("rollers", "Rollers", deck="1 Lucky Roller\n1 Hare Apparent\n", sideboard="1 Venom Drake\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tokens.main(["casual/rollers"]), 0)
        text = out.getvalue()
        self.assertIn("Counters and dice (approximate):", text)
        self.assertIn("  Energy counters: Lucky Roller", text)
        self.assertIn("  Poison counters [sideboard only]: Venom Drake (sideboard)", text)
        self.assertIn("  d20: Lucky Roller", text)


class DeckPageCountersTests(token_fixture.TokensApiTestCase):
    """The counters are part of the deck page's tokens, which only the space's own people get."""

    @classmethod
    def setUpClass(cls):
        cls.loaded = extended_index()

    def index(self):
        return self.loaded

    def setUp(self):
        household_config.use(self)
        super().setUp()
        self.write("decks/casual/drakes.md", token_fixture.deck_md("Drakes", deck="2 Venom Drake\n1 Hornet Queen\n"))

    def view(self, profile):
        with access.using({"profile": profile, "email": "", "remote": True}), access.answering(False), \
                mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})), \
                mock.patch.object(guard, "public_spaces", return_value=frozenset()), \
                mock.patch.object(guard, "public_owners", return_value=frozenset()), \
                mock.patch.object(deck_page, "_deck_stats", return_value=None), \
                mock.patch.object(deck_page, "_deck_practice", return_value=None), \
                mock.patch.object(deck_page, "usual_opponents", return_value=[]):
            return deck_page.deck_view("casual/drakes", omit=("matchups",))

    def test_home_sees_the_counters_and_a_member_of_another_space_gets_no_token_part(self):
        seen = self.view("matt")["tokens"]["counters"]
        self.assertEqual([(n["key"], n["made_by"][0]["quantity"]) for n in seen["needs"]], [("poison", 2)])
        answer = self.view("user2")          # the deck is public; home's inventory isn't
        self.assertNotIn("tokens", answer)
        serialized = json.dumps(answer)
        for private in ("Poison counters", counters.NOTE[:40], '"counters"'):
            self.assertNotIn(private, serialized)


if __name__ == "__main__":
    unittest.main()
