"""Public provider responses enter the same guarded, read-only deck import review."""
import io
import json
import unittest
from urllib.error import HTTPError
from unittest import mock

from decklab.lib import api, deck_link_import as links, decks, inventory
from decklab.lib.api import editor_imports, guard
from decklab.lib.api.common import ApiError
from decklab.tests import test_collection_edit as fixture
from decklab.tests.test_api import _write
from decklab.tests.test_deck_categories import DECK


MOXFIELD = "https://moxfield.com/decks/SortByRamp_a"
ARCHIDEKT = "https://www.archidekt.com/decks/12345/fixture-deck"


def moxfield():
    def row(name, set_code, number, quantity=1, **extra):
        return {"quantity": quantity, "card": {"name": name, "set": set_code, "cn": number}, **extra}

    return {
        "visibility": "public",
        "boards": {
            "commanders": {"cards": {"commander": row("Aerie Mystics", "con", "99")}},
            "mainboard": {"cards": {"split": row("Llanowar Elves", "fdn", "227", 3, printingData=[
                {"quantity": 2, "set": "fdn", "cn": "227", "finish": "nonFoil"},
                {"quantity": 1, "set": "cmm", "cn": "294", "finish": "foil"},
            ])}},
            "sideboard": {"cards": {"negate": row("Negate", "fdn", "47")}},
            "maybeboard": {"cards": {"skip": row("Forest", "fdn", "291")}},
        },
        "authorTags": {"split": ["Ramp", "Mana"]},
    }


def archidekt():
    def row(name, set_code, number, categories, modifier="Normal", companion=False):
        return {"quantity": 1, "categories": categories, "modifier": modifier, "companion": companion, "card": {
            "oracleCard": {"name": name}, "edition": {"editioncode": set_code}, "collectorNumber": number,
        }}

    return {
        "private": False, "unlisted": False,
        "categories": [{"name": "Command zone", "isPremier": True, "includedInDeck": True},
                       {"name": "Ramp", "isPremier": False, "includedInDeck": True},
                       {"name": "Answers", "isPremier": False, "includedInDeck": True},
                       {"name": "Sideboard", "isPremier": False, "includedInDeck": False},
                       {"name": "Considering", "isPremier": False, "includedInDeck": False}],
        "cards": [
            row("Aerie Mystics", "con", "99", ["Ramp", "Command zone"]),
            row("Llanowar Elves", "fdn", "227", ["Ramp", "Considering"]),
            row("Elvish Mystic", "cmm", "648", ["Answers", "Sideboard"], "Etched Foil"),
            row("Lurrus of the Dream-Den", "iko", "226", ["Answers", "Sideboard"], companion=True),
            row("Forest", "fdn", "291", ["Considering", "Ramp"]),
        ],
    }


class PublicDeckProviderTests(unittest.TestCase):
    def parse(self, link, data):
        with mock.patch.object(links, "_download", return_value=data) as download:
            text, notes = links.fetch(link)
        return decks.parse_decklist(text), notes, download.call_args.args[0]

    def test_moxfield_fixed_endpoint_boards_categories_and_split_printings(self):
        sections, notes, url = self.parse(MOXFIELD + "/primer?from=share#main", moxfield())
        self.assertEqual(url, "https://api2.moxfield.com/v3/decks/all/SortByRamp_a")
        self.assertEqual(list(sections), ["Commander", "Deck", "Sideboard"])
        self.assertEqual(sections["Commander"][0].name, "Aerie Mystics")
        self.assertEqual([(row.quantity, row.set, row.number, row.finish, row.category) for row in sections["Deck"]],
                         [(2, "fdn", "227", "nonfoil", "Ramp"), (1, "cmm", "294", "foil", "Ramp")])
        self.assertTrue(any("Extra boards" in note for note in notes))
        self.assertTrue(any("first supported category" in note for note in notes))

    def test_archidekt_recognizes_zone_after_an_ordinary_category_and_preserves_printing(self):
        sections, notes, url = self.parse(ARCHIDEKT, archidekt())
        self.assertEqual(url, "https://archidekt.com/api/decks/12345/")
        self.assertEqual(list(sections), ["Commander", "Companion", "Deck", "Sideboard"])
        self.assertEqual(sections["Commander"][0].name, "Aerie Mystics")
        self.assertEqual(sections["Commander"][0].category, "Ramp")
        self.assertEqual(sections["Companion"][0].name, "Lurrus of the Dream-Den")
        self.assertEqual(sections["Deck"][0].category, "Ramp")
        sideboard = sections["Sideboard"][0]
        self.assertEqual((sideboard.set, sideboard.number, sideboard.finish, sideboard.category),
                         ("cmm", "648", "etched", "Answers"))
        self.assertTrue(any("Extra boards" in note for note in notes))

    def test_non_public_decks_and_unsupported_links(self):
        with mock.patch.object(links, "_download") as network:
            for value in ("http://moxfield.com/decks/example", "https://example.com/decks/1",
                          "https://moxfield.com/decks/", "https://archidekt.com/collection/12345/"):
                with self.subTest(value=value), self.assertRaises(ApiError) as error:
                    links.fetch(value)
                self.assertEqual(error.exception.status, 400)
            network.assert_not_called()
        for link, data in ((MOXFIELD, {**moxfield(), "visibility": "private"}),
                           (ARCHIDEKT, {**archidekt(), "unlisted": True})):
            with self.subTest(link=link), self.assertRaises(ApiError) as error:
                self.parse(link, data)
            self.assertEqual(error.exception.status, 404)

    def test_failed_download_and_oversized_response(self):
        endpoint = "https://api2.moxfield.com/v3/decks/all/SortByRamp_a"
        with mock.patch.object(links, "build_opener") as make_opener:
            opener = make_opener.return_value
            opener.open.side_effect = HTTPError(endpoint, 404, "Fixture unavailable", {}, io.BytesIO())
            with self.assertRaises(ApiError) as error:
                links._download(endpoint)
            self.assertEqual(error.exception.status, 404)
            self.assertTrue(any(isinstance(handler, links._NoRedirects) for handler in make_opener.call_args.args))
            opener.open.side_effect = None
            response = opener.open.return_value.__enter__.return_value
            response.headers = {"Content-Length": str(links.MAX_RESPONSE + 1)}
            with self.assertRaises(ApiError) as error:
                links._download(endpoint)
            self.assertEqual(error.exception.status, 502)
            response.read.assert_not_called()
            response.headers = {}
            response.read.return_value = json.dumps(moxfield()).encode()
            self.assertEqual(links._download(endpoint)["visibility"], "public")
            response.read.assert_called_once_with(links.MAX_RESPONSE + 1)


class PublicDeckLinkReviewTests(fixture.CollectionEditTestCase):
    def setUp(self):
        super().setUp()
        _write(self.box.magic / "decks/casual/link-target.md", DECK.replace("- **Status:** built", "- **Status:** idea"))

    def review(self, who, target, link=ARCHIDEKT):
        with self.as_(who):
            return self.call(api.parse_list, who, link=link, context=target)

    def test_existing_editor_review_marks_the_members_own_inventory_and_keeps_categories(self):
        before = inventory.current()
        with mock.patch.object(links, "_download", return_value=archidekt()):
            result = self.review("user2", {"space": "user2"})
        elves = next(row for row in result["availability"]["rows"] if row["name"] == "Llanowar Elves")
        self.assertTrue(result["marks"])
        self.assertEqual(elves["owned"], 2)
        line = result["sections"]["Deck"][0]
        self.assertEqual((line["set"], line["number"], line["category"]), ("fdn", "227", "Ramp"))
        self.assertIn("1 Llanowar Elves (FDN) 227 #Ramp", result["source_text"])
        self.assertEqual(inventory.current(), before)
        self.assertEqual(self.writes, [])

    def test_denied_context_never_fetches_and_public_target_has_no_private_pool_marks(self):
        with mock.patch.object(links, "_download", return_value=archidekt()) as download:
            self.assertApiError(404, self.review, "user2", {"id": "casual/link-target"})
            self.assertApiError(403, self.review, "user2", {"space": "home"})
            download.assert_not_called()
            with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})), \
                    mock.patch.object(editor_imports, "_load_pool", side_effect=AssertionError("Private pool read")):
                shown = self.review("user2", {"id": "casual/link-target"})
        self.assertEqual((shown["marks"], shown["availability"]), (False, None))
