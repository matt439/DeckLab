"""Explicit paste previews share pool scope/redaction and never fetch a price or write."""
import json
from unittest import mock

from decklab.lib import api, cards, inventory
from decklab.lib.api import editor_imports, guard
from decklab.tests import test_collection_edit as fixture
from decklab.tests.test_api import _write
from decklab.tests.test_deck_categories import DECK


class EditorImportMarksTests(fixture.CollectionEditTestCase):
    def setUp(self):
        super().setUp()
        _write(self.box.magic / "decks/casual/import-target.md", DECK.replace("- **Status:** built", "- **Status:** idea"))
        member = DECK.replace("- **Played by:** user\n", "").replace("- **Status:** built", "- **Status:** idea")
        _write(self.box.magic / "people/user2/decks/casual/import-target.md", member)

    def parsed(self, who="matt", **context):
        with self.as_(who):
            return self.call(api.parse_list, who, text="1 Llanowar Elves (FDN) 227 #Ramp\n1 Elvish Mystic (CMM) 648\n", context=context)

    def test_explicit_review_returns_name_level_pool_marks_without_prices_writes_or_replacing_printings(self):
        before = inventory.current()
        with mock.patch.object(cards, "usd_to_aud", side_effect=AssertionError("No market lookup")):
            shown = self.parsed(id="casual/import-target")
        self.assertTrue(shown["marks"])
        self.assertEqual(shown["sections"]["Deck"][0]["category"], "Ramp")
        self.assertEqual((shown["sections"]["Deck"][0]["set"], shown["sections"]["Deck"][0]["number"]), ("fdn", "227"))
        self.assertEqual({row["name"] for row in shown["availability"]["rows"]}, {"Llanowar Elves", "Elvish Mystic"})
        self.assertTrue(all(row["aud_each"] is None for row in shown["availability"]["rows"]))
        self.assertEqual(inventory.current(), before)
        self.assertEqual(self.writes, [])

    def test_member_preview_uses_only_its_space_and_hidden_target_is_missing_before_pool_read(self):
        shown = self.parsed("user2", id="user2/casual/import-target")
        elves = next(row for row in shown["availability"]["rows"] if row["name"] == "Llanowar Elves")
        self.assertEqual(elves["owned"], 2)
        with mock.patch.object(editor_imports, "_load_pool", side_effect=AssertionError("Private pool read")):
            self.assertApiError(404, self.parsed, "user2", id="casual/import-target")

    def test_public_deck_without_inventory_has_no_marks_and_is_invariant_under_hidden_pool_changes(self):
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})), \
                mock.patch.object(editor_imports, "_load_pool", side_effect=AssertionError("Hidden pool read")):
            first = self.parsed("user2", id="casual/import-target")
            _write(self.box.magic / "collection.csv", fixture.HEADER + "Llanowar Elves,fdn,227,nonfoil,99,NM,en,\n")
            second = self.parsed("user2", id="casual/import-target")
        self.assertEqual(first, second)
        self.assertEqual((first["marks"], first["availability"]), (False, None))

    def test_legacy_parse_contract_and_denied_new_space_keep_existing_privacy_boundaries(self):
        with self.as_("user2"):
            old = self.call(api.parse_list, "user2", text="1 Llanowar Elves\n")
        self.assertEqual(set(old), {"sections", "unknown", "errors", "warnings", "count"})
        self.assertApiError(403, self.parsed, "user2", space="home")
        self.assertApiError(400, self.parsed, id="casual/import-target", space="home")

    def test_cached_stale_snapshot_withholds_availability_instead_of_claiming_free_copies(self):
        stale = inventory.current().replace(stale="Synthetic cached snapshot")
        with self.as_("matt"), mock.patch.object(inventory, "current", return_value=stale), \
                mock.patch.object(editor_imports, "_load_pool", side_effect=AssertionError("No current pool")):
            shown = editor_imports.availability({}, {"id": "casual/import-target"})
        self.assertEqual((shown["marks"], shown["availability"]), (False, None))
        self.assertIn("current collection snapshot", shown["availability_error"])

    def test_card_copy_exceptions_use_the_existing_commander_rule_without_inventory_or_network(self):
        from decklab.lib.api.card_lookup import _card_json
        fixture.ce._require_cards()
        base = cards.card("Llanowar Elves")
        for text, expected in (("A deck can have any number of cards named Fixture.", None),
                               ("A deck can have up to seven cards named Fixture.", 7)):
            shown = _card_json({**base, "oracle_text": text}, None)
            self.assertEqual(shown["commander_copies"], expected)
        self.assertNotIn("commander_copies", _card_json({**base, "oracle_text": ""}, None))
