"""Whose side of the table a deck's token lands on (E7-S23, lib/tokens/sides.py): the classifier over
rules-text sentences, the side, cards and words deck_tokens gives each need, the deck printout's line,
and that the side goes only where the deck's tokens go (a viewer who may not see the space's inventory
gets no token part at all).

The cards that give tokens away are test cards added to fixtures/tokens_cards.jsonl's real Scryfall
objects (each a copy of Prideful Parent with its own name, text and token link), so no card index is
needed.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_token_sides
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
from decklab.lib.tokens import sides
from decklab.tests import household_config
from decklab.tests import test_api_tokens as token_fixture
from decklab.tests import test_tokens as fixture

INSECT, SPIRIT_ID, TREASURE_ID = "1a9b06fb-4617-4e2d-9747-e12791565527", "21e580cb-6092-48b7-ba3e-d64ec28860da", \
    "d0ab4943-3943-4b83-8da3-90a1fb0988b3"
# (name, rules text, the token's Scryfall id): test cards, never real printings.
EXTRA = (
    ("Orchard Gift", "{T}: Add one mana of any color.\nWhenever you tap this land for mana, target opponent creates "
                     "a 1/1 white Spirit creature token with flying.", SPIRIT_ID),
    ("Swarm Within", "Destroy target permanent. Its controller creates a 1/1 green Insect creature token with "
                     "flying and deathtouch.", INSECT),
    ("Tribute Hoard", "When this creature enters, each opponent creates a Treasure token.", TREASURE_ID),
)


def extended_index():
    """fixtures/tokens_cards.jsonl's index with EXTRA's cards added."""
    lines = (fixture.FIXTURES / "tokens_cards.jsonl").read_text(encoding="utf-8").splitlines()
    template = next(json.loads(line) for line in lines if json.loads(line)["name"] == "Prideful Parent")
    for i, (name, text, token_id) in enumerate(EXTRA):
        card = {**template, "name": name, "oracle_text": text, "id": f"00000000-0000-4000-8000-{i:012d}",
                "oracle_id": f"00000000-0000-4000-9000-{i:012d}", "collector_number": f"9{i}",
                "all_parts": [{"object": "related_card", "id": token_id, "component": "token", "name": "x",
                               "type_line": "Token"}]}
        lines.append(json.dumps(card))
    folder = Path(tempfile.mkdtemp())
    try:
        path = folder / "cards.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return cards._prepare(cards.build_index(path, fixture.FIXTURES / "oracle_tags.jsonl", {}, log=lambda *a: None))
    finally:
        shutil.rmtree(folder, True)


class SentenceTests(unittest.TestCase):
    def side(self, text, names=("Spirit",)):
        return sides.card_side(text, names)

    def test_the_decks_own(self):
        for text in ("When this creature enters, create a 1/1 white Spirit creature token.",
                     "+1: Create three 1/1 white Spirit creature tokens.",
                     "For each opponent, create a 1/1 white Spirit creature token.",
                     "Whenever an opponent casts a spell, you create a 1/1 white Spirit creature token.",
                     "When this creature dies, create two Spirit tokens. They have \"When this token dies, "
                     "target opponent loses 1 life.\"",
                     # Only the subject after the last "and" creates: "you", not the player named before it.
                     "When enchanted creature dies, return this card to its owner's hand and you create a 1/3 "
                     "black Spirit creature token.",
                     "Exile target creature an opponent controls and you create a Spirit token.",
                     "Target opponent loses 2 life and you create a Spirit token.",
                     "Each opponent loses 1 life and you may create a Spirit token."):
            self.assertEqual(self.side(text), sides.OWN, text)

    def test_the_opponents(self):
        for text in ("Whenever you tap this land for mana, target opponent creates a 1/1 Spirit creature token.",
                     "Each opponent creates a 1/1 white Spirit creature token.",
                     "When this enters, an opponent creates a Spirit token.",
                     "Defending player creates a 1/1 Spirit creature token.",
                     "Then each other player creates a Spirit token.",
                     "Create a 1/1 Spirit creature token under target opponent's control.",
                     "You may have target opponent create a 1/1 Spirit creature token."):
            self.assertEqual(self.side(text), sides.OPPONENT, text)

    def test_either(self):
        for text in ("Destroy target permanent. Its controller creates a 3/3 green Spirit creature token.",
                     "Exile target creature. That creature's controller creates a Spirit token.",
                     "Target player creates a 1/1 Spirit creature token.",
                     "At the beginning of your upkeep, each player creates a Spirit token.",
                     "You and target opponent each create a Spirit token.",
                     "Target opponent and you each create a Spirit token.",
                     "Target player sacrifices a creature and creates a Spirit token.",
                     "Create a 1/1 Spirit token. Then that player creates a Spirit token."):
            self.assertEqual(self.side(text), sides.EITHER, text)

    def test_the_sentences_naming_the_token_count_first(self):
        text = ("When this creature enters, create a Treasure token.\n"
                "Whenever it attacks, defending player creates a 1/1 white Spirit creature token.")
        self.assertEqual(self.side(text, ("Spirit",)), sides.OPPONENT)
        self.assertEqual(self.side(text, ("Treasure",)), sides.OWN)
        # No sentence names it (a link Scryfall made from another word): every creating sentence counts.
        self.assertEqual(self.side(text, ("Clue",)), sides.EITHER)
        self.assertIsNone(self.side("Flying", ("Spirit",)))
        self.assertIsNone(self.side("", ("Spirit",)))

    def test_side_of_a_need_and_its_words(self):
        need = {"name": "Spirit", "face_names": ["Spirit"],
                "made_by": [{"name": "Gift", "quantity": 1, "section": "Deck"}]}
        texts = {"Gift": "Target opponent creates a Spirit token.", "Maker": "Create a Spirit token.",
                 "Hydras": "Its controller creates a Spirit token."}
        self.assertEqual(sides.side(need, texts), (
            sides.OPPONENT, ["Gift"], "For your opponent: Gift's text gives it to another player (approximate)"))
        need["made_by"].append({"name": "Maker", "quantity": 1, "section": "Deck"})
        self.assertEqual(sides.side(need, texts), (
            sides.EITHER, ["Gift"], "Maybe your opponent's: Gift's text can give it to another player (approximate)"))
        need["made_by"] = [{"name": "Hydras", "quantity": 1, "section": "Deck"},
                           {"name": "Gift", "quantity": 1, "section": "Sideboard"}]
        self.assertEqual(sides.side(need, texts)[2],
                         "Maybe your opponent's: Hydras and Gift's text can give it to another player (approximate)")
        need["made_by"] = [{"name": "Hydras", "quantity": 1, "section": "Deck"}]
        self.assertTrue(sides.side(need, texts)[2].startswith("Maybe your opponent's: Hydras' text"))
        need["made_by"] = [{"name": "Maker", "quantity": 1, "section": "Deck"},
                           {"name": "No text", "quantity": 1, "section": "Deck"}]
        self.assertEqual(sides.side(need, texts), (sides.OWN, [], None))


class DeckTokensSideTests(fixture.IndexTestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = extended_index()

    def by_name(self, result, name):
        found = [n for n in result["needs"] if n["name"] == name]
        self.assertEqual(len(found), 1, [n["name"] for n in result["needs"]])
        return found[0]

    def test_each_need_says_whose_side_it_lands_on(self):
        result = self.makes(["Hornet Queen", "Orchard Gift", "Tribute Hoard", "Hare Apparent"])
        rabbit = self.need(result, fixture.RABBIT)
        self.assertEqual((rabbit["side"], rabbit["side_from"], rabbit["side_words"]), ("own", [], None))
        self.assertEqual(self.need(result, fixture.INSECT)["side"], "own")
        spirit = self.by_name(result, "Spirit")
        self.assertEqual((spirit["side"], spirit["side_from"]), ("opponent", ["Orchard Gift"]))
        self.assertIn("approximate", spirit["side_words"])
        treasure = self.need(result, fixture.TREASURE)
        self.assertEqual((treasure["side"], treasure["side_from"]), ("opponent", ["Tribute Hoard"]))
        # The side changes nothing else: the state, words and counts are the same as without it.
        self.assertEqual(spirit["state"], "check")
        self.assertEqual(result["counts"]["kinds"], 4)

    def test_a_token_made_for_both_players_is_marked_as_maybe_the_opponents(self):
        result = self.makes(["Hornet Queen", "Swarm Within"], section="Deck")
        insect = self.need(result, fixture.INSECT)
        self.assertEqual((insect["side"], insect["side_from"]), ("either", ["Swarm Within"]))
        self.assertEqual(insect["side_words"],
                         "Maybe your opponent's: Swarm Within's text can give it to another player (approximate)")
        self.assertEqual(self.need(self.makes(["Swarm Within"]), fixture.INSECT)["side"], "either")

    def test_the_deck_printout_says_it(self):
        self.real()
        self.deck("gifts", "Gifts", deck="1 Orchard Gift\n1 Hare Apparent\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tokens.main(["casual/gifts"]), 0)
        text = out.getvalue()
        self.assertIn("For your opponent: Orchard Gift's text gives it to another player (approximate)", text)
        self.assertEqual(text.count("(approximate)"), 1)


class DeckPageSideTests(token_fixture.TokensApiTestCase):
    """The side is part of the deck page's tokens, which only the space's own people get."""

    @classmethod
    def setUpClass(cls):
        cls.loaded = extended_index()

    def index(self):
        return self.loaded

    def setUp(self):
        household_config.use(self)
        super().setUp()
        self.write("decks/casual/gifts.md", token_fixture.deck_md("Gifts", deck="1 Orchard Gift\n1 Hornet Queen\n"))

    def view(self, profile):
        with access.using({"profile": profile, "email": "", "remote": True}), access.answering(False), \
                mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})), \
                mock.patch.object(guard, "public_spaces", return_value=frozenset()), \
                mock.patch.object(guard, "public_owners", return_value=frozenset()), \
                mock.patch.object(deck_page, "_deck_stats", return_value=None), \
                mock.patch.object(deck_page, "_deck_practice", return_value=None), \
                mock.patch.object(deck_page, "usual_opponents", return_value=[]):
            return deck_page.deck_view("casual/gifts", omit=("matchups",))

    def test_home_sees_the_side_and_a_member_of_another_space_gets_no_token_part(self):
        sides_seen = {n["name"]: n["side"] for n in self.view("matt")["tokens"]["needs"]}
        self.assertEqual(sides_seen, {"Spirit": "opponent", "Insect": "own"})
        answer = self.view("user2")          # the deck is public; home's inventory isn't
        self.assertNotIn("tokens", answer)
        serialized = json.dumps(answer)
        for private in ("side_words", "For your opponent", "side_from"):
            self.assertNotIn(private, serialized)


if __name__ == "__main__":
    unittest.main()
