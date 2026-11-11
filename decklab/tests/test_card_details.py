"""Public card addresses and inventory-private owned printing/location facts."""
import json
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from decklab.lib import cards, inventory
from decklab.lib.api import card_details, card_lookup, guard
from decklab.tests.test_api import _write
from decklab.tests.test_global_search import GlobalSearchTestCase


class CardDetailsTests(GlobalSearchTestCase):
    def test_public_lookup_needs_no_inventory_and_preserves_the_requested_printing(self):
        with self.at_home(None), mock.patch.object(inventory, "current", side_effect=AssertionError("No collection read")):
            card = card_details.card_view("Llanowar Elves", "fdn", "227")["card"]
        self.assertEqual(card["scryfall_url"], "https://scryfall.com/card/fdn/227")
        self.assertEqual(card["edhrec_url"], "https://edhrec.com/cards/llanowar-elves")
        self.assertNotIn("have", card)
        self.assertApiError(404, card_details.card_view, "Llanowar Elves", "lea", "232")
        self.assertApiError(400, card_details.card_view, "Llanowar Elves", "fdn")

    def test_missing_printing_uses_an_escaped_exact_name_search_and_edhrec_uses_front_face(self):
        name = 'A "quoted" \\ name'
        url = card_lookup.reference_url(name)
        self.assertEqual(urlsplit(url).hostname, "scryfall.com")
        self.assertEqual(parse_qs(urlsplit(url).query), {"q": ['!"A \\"quoted\\" \\\\ name"']})
        original = cards.card("Llanowar Elves")
        value = card_lookup._card_json({**original, "name": "Front // Back"}, None)
        self.assertEqual(value["edhrec_url"], "https://edhrec.com/cards/front")

    def test_copies_are_owned_rows_and_recorded_locations_without_notes_or_incoming(self):
        _write(self.box.magic / "locations.csv", "set,collector_number,finish,location\nfdn,227,nonfoil,Top row\n")
        with self.as_("matt"):
            answer = card_details.copies_view("llanowar elves")
        self.assertEqual(answer["printings"], [{"set": "fdn", "number": "227", "finish": "nonfoil", "quantity": 5, "location": "Top row"}])
        self.assertEqual(len(self.writes), 0)
        self.assertNotIn("on_the_way", json.dumps(answer))
        with self.as_("user2"):
            mine = card_details.copies_view("Llanowar Elves", "user2")
        self.assertNotIn("Top row", json.dumps(mine))
        self.assertTrue(all(set(row) == {"set", "number", "finish", "quantity", "location"} for row in mine["printings"]))

    def test_hidden_collection_is_refused_before_card_validation_or_inventory_reads(self):
        for profile, space in ((None, "home"), ("user2", "home"), ("matt", "user2"), ("user2", "missing")):
            with (self.at_home(None) if profile is None else self.as_(profile)), mock.patch.object(guard, "public_deck_spaces", return_value={"home", "user2"}), \
                    mock.patch.object(inventory, "current", side_effect=AssertionError("Private snapshot not read")):
                self.assertApiError(403, card_details.copies_view, None, space, contains="That collection isn't public.")
