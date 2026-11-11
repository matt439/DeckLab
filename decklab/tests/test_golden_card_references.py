"""Public-card URL compatibility never hides unrelated fields or unexpected outbound destinations."""
import copy
import unittest

from decklab.tests import golden_p4


class CardReferenceGoldenTests(unittest.TestCase):
    def card(self):
        return {"name": "Llanowar Elves", "mana_cost": "{G}", "cmc": 1, "type_line": "Creature",
                "colors": ["G"], "color_identity": ["G"], "roles": [], "img": "/img/fdn/227/normal",
                "img_small": None, "oracle_text": "{T}: Add {G}.",
                "scryfall_url": "https://scryfall.com/card/fdn/227", "edhrec_url": "https://edhrec.com/cards/llanowar-elves"}

    def test_only_exact_card_urls_are_ignored_without_mutation(self):
        value = {"cards": [self.card()]}
        untouched = copy.deepcopy(value)
        got = golden_p4.normalise(value)["cards"][0]
        self.assertEqual(set(got), set(self.card()) - {"scryfall_url", "edhrec_url"})
        self.assertEqual(value, untouched)

    def test_unexpected_urls_and_identical_keys_in_other_shapes_still_compare(self):
        value = {"cards": [self.card()], "notes": {"scryfall_url": self.card()["scryfall_url"]}}
        value["cards"][0]["scryfall_url"] = "https://example.com/unexpected"
        got = golden_p4.normalise(value)
        self.assertEqual(got["cards"][0]["scryfall_url"], "https://example.com/unexpected")
        self.assertEqual(got["notes"], value["notes"])
