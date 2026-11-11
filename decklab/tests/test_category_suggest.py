"""Role priority, saved-space privacy and lossless canonical category projection."""
import unittest
from unittest import mock

from decklab.db import migration_categories
from decklab.lib import cards, decks, inventory
from decklab.lib.api import category_suggestions as api
from decklab.lib.inventory import pg_decks
from decklab.lib.stats import category_suggest
from decklab.tests import test_collection_edit as fixture
from decklab.tests.test_api import _write
from decklab.tests.test_deck_categories import DECK


class CategoryRulesTests(unittest.TestCase):
    def test_specific_roles_have_one_fixed_priority_and_unknown_metadata_has_no_suggestion(self):
        for index, (role, label) in enumerate(category_suggest.PRIORITY):
            self.assertEqual(category_suggest.suggest({"roles": [role]}), label)
            self.assertEqual(category_suggest.suggest({"roles": [item[0] for item in category_suggest.PRIORITY[index:]]}), label)
        for card in (None, {}, {"roles": "ramp"}, {"roles": ["unknown"]}):
            self.assertIsNone(category_suggest.suggest(card))

    def test_backfill_proves_legacy_identity_before_projecting_only_categories(self):
        parsed = pg_decks.parsed("casual/cats", DECK)
        old = pg_decks.lines("casual/cats", parsed)
        new = pg_decks.lines("casual/cats", parsed, categories=True)
        self.assertEqual([row[:-1] for row in new], old)
        self.assertEqual(new[0][-1], "Ramp")
        self.assertIsNone(new[1][-1])
        self.assertEqual(migration_categories.projection([("casual/cats", DECK)], old), [("Ramp", "casual/cats", "target", "Deck", 0)])
        for texts, stored in (([("casual/cats", DECK)], old[:-1]), ([], old), ([("casual/cats", "broken")], old)):
            with self.subTest(texts=len(texts)), self.assertRaises(migration_categories.ProjectionError):
                migration_categories.projection(texts, stored)


class CategoryChoicesTests(fixture.CollectionEditTestCase):
    def setUp(self):
        super().setUp()
        fixture.ce._require_cards()
        for space, tag in (("home", "Home label"), ("user2", "Member label"), ("user3", "Hidden label")):
            path = self.box.magic / ("decks" if space == "home" else f"people/{space}/decks") / "casual/categories.md"
            text = DECK.replace("#Ramp", "#" + tag)
            if space != "home":
                text = text.replace("- **Played by:** user\n", "")
            _write(path, text)

    def test_choices_use_only_the_callers_actual_space_and_no_other_deck_titles_or_counts(self):
        for viewer, space, label in (("matt", "home", "Home label"), ("user1", "home", "Home label"), ("user2", "user2", "Member label")):
            with self.subTest(viewer=viewer), self.as_(viewer):
                answer = api.choices_view("Llanowar Elves", space)
                self.assertEqual(answer, {"name": "Llanowar Elves", "categories": [label], "more": False})
                excluded = api.choices_view("Llanowar Elves", space, "casual/categories" if space == "home" else space + "/casual/categories")
                self.assertEqual(excluded["categories"], [])

    def test_public_inventory_or_deck_does_not_grant_private_category_habits_and_guard_precedes_reads(self):
        for viewer, space in (("matt", "user2"), ("user2", "home"), ("user1", "user3")):
            with self.subTest(viewer=viewer), self.as_(viewer), \
                    mock.patch.object(api.guard, "sees_inventory", return_value=True), \
                    mock.patch.object(inventory, "current", side_effect=AssertionError("Private snapshot read")), \
                    mock.patch.object(api, "_require_cards", side_effect=AssertionError("Card data read")):
                self.assertApiError(403, api.choices_view, "Llanowar Elves", space)

    def test_intrinsic_card_json_offers_a_role_label_without_reading_any_deck(self):
        from decklab.lib.api.card_lookup import _card_json
        with mock.patch.object(inventory, "current", side_effect=AssertionError("Deck read")):
            result = _card_json({**cards.card("Llanowar Elves"), "roles": ["ramp", "draw"]}, None)
        self.assertEqual(result["category_suggestion"], "Draw")
