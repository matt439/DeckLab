"""Revision/precon Compare sides use cached public card data and never inventory-derived views."""
import json
from unittest import mock

from decklab.lib import accessories, inventory, pool, tokens
from decklab.lib.api import comparison_lists, guard, history
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.tests import test_precons as fixtures
from decklab.tests.test_deck_history import install, revision


TEXT = """# Intrinsic fixture

- **Format:** Casual 60-card, 1v1
- **Played by:** user
- **Status:** building
- **Sleeves:** PRIVATE_KIT_VALUE
- **Deck box:** PRIVATE_BOX_VALUE

## Decklist

```
Deck
2 Llanowar Elves (FDN) 227
```

## Owned vs needed

| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |
|---|---|---|---|---|---|---|
| Llanowar Elves | 2 | 91 | 0 | | | INVENTORY_PRIVATE_MARKER |
"""


class ComparisonBaselineApiTests(fixtures.PreconTestCase):
    def setUp(self):
        super().setUp()
        self.deck_id = "casual/gruul-test"
        self.box.magic.joinpath("decks/casual/gruul-test.md").write_text(TEXT, encoding="utf-8")
        self.history = install(self.box, {self.deck_id: [revision(self.deck_id, 1, TEXT, message="PRIVATE_REVISION_MESSAGE")]})

    def assert_intrinsic(self, value):
        encoded = json.dumps(value)
        for marker in ("PRIVATE_KIT_VALUE", "PRIVATE_BOX_VALUE", "INVENTORY_PRIVATE_MARKER", "PRIVATE_REVISION_MESSAGE"):
            self.assertNotIn(marker, encoded)
        for key in ("owned", "missing", "kit", "fields", "current", "history", "matchups", "practice", "table"):
            self.assertNotIn(key, value)

    def test_current_and_revision_stats_are_intrinsic_even_for_an_outside_public_deck_reader(self):
        before = files.render(inventory.current(), decks=True)
        with self.as_("user2"), mock.patch.object(guard, "public_deck_spaces", return_value={"home"}), \
                mock.patch.object(pool, "load_pool", side_effect=AssertionError("No collection read")), \
                mock.patch.object(accessories, "read", side_effect=AssertionError("No kit read")), \
                mock.patch.object(tokens, "read", side_effect=AssertionError("No token read")), \
                mock.patch.object(history, "edit_view", side_effect=AssertionError("No editor/inventory projection")):
            current = comparison_lists.current_view(self.deck_id)
            old = history.deck_revision(self.deck_id, "1", stats="1")
        for value in (current, old):
            self.assert_intrinsic(value)
            self.assertFalse(value["stats_unknown"])
            self.assertIsNotNone(value["stats"])
        self.assertEqual(old["comparison"]["kind"], "revision")
        self.assertEqual(old["comparison"]["revision"], 1)
        self.assertIn("today", old["comparison"]["bracket_note"])
        self.assertEqual(files.render(inventory.current(), decks=True), before)

    def test_unknown_revision_card_is_explicitly_unknown_without_a_partial_zero_stat(self):
        self.history.revisions[self.deck_id] = [revision(self.deck_id, 1, TEXT.replace("Llanowar Elves", "Unindexed fixture spell"))]
        with self.as_("matt"):
            old = history.deck_revision(self.deck_id, "1", stats="1")
        self.assertTrue(old["stats_unknown"])
        self.assertIsNone(old["stats"])
        self.assertIn("unknown", old["stats_note"])
        self.assertEqual(old["sections"]["Deck"][0]["name"], "Unindexed fixture spell")
        self.assertIsNone(old["sections"]["Deck"][0]["card"])

    def test_hidden_deck_is_missing_before_revision_stats_or_version_validation(self):
        with self.as_("user2"), mock.patch.object(inventory, "deck_revision", side_effect=AssertionError("Hidden revision not read")):
            self.assertApiError(404, history.deck_revision, self.deck_id, "bad revision", version="bad", stats="bad")
            self.assertApiError(404, comparison_lists.current_view, self.deck_id, version="bad")

    def test_existing_revision_editor_payload_is_unchanged_without_opt_in(self):
        with self.as_("matt"):
            old = history.deck_revision(self.deck_id, "1")
        self.assertIn("current", old)
        self.assertIn("fields", old)
        self.assertNotIn("stats", old)

    def test_historical_and_current_available_versions_are_independent(self):
        old_text = TEXT.replace("## Owned vs needed", "### Owned-only version\n\n```\nDeck\n1 Llanowar Elves (FDN) 227\n```\n\n## Owned vs needed")
        self.history.revisions[self.deck_id] = [revision(self.deck_id, 1, old_text)]
        with self.as_("matt"):
            old = history.deck_revision(self.deck_id, "1", version="owned", stats="1")
            current = comparison_lists.current_view(self.deck_id)
            index = history.deck_history(self.deck_id)
        self.assertEqual(old["versions"], ["target", "owned"])
        self.assertEqual(current["versions"], ["target"])
        self.assertEqual(index["versions"], ["target"])

    def test_comparison_parse_failures_never_quote_hidden_table_or_kit_values(self):
        with self.as_("matt"), mock.patch.object(comparison_lists, "_deck_sections", side_effect=ApiError(500, "PRIVATE_TABLE_ERROR")):
            error = self.assertApiError(500, comparison_lists.current_view, self.deck_id)
        self.assertNotIn("PRIVATE_TABLE_ERROR", error.message)
        with self.as_("matt"), mock.patch.object(history, "_parse", side_effect=ApiError(500, "PRIVATE_TABLE_ERROR")):
            error = self.assertApiError(500, history.deck_revision, self.deck_id, "1", stats="1")
        self.assertNotIn("PRIVATE_TABLE_ERROR", error.message)

    def test_precon_reader_is_public_cached_and_preserves_published_printings_without_creating_a_deck(self):
        count = len(self.writes)
        with mock.patch.object(inventory, "current", side_effect=AssertionError("A public precon needs no inventory")), \
                mock.patch.object(inventory, "apply", side_effect=AssertionError("No trial or deck creation")):
            value = comparison_lists.precon_view("TestDinos_TST")
        self.assertEqual(value["comparison"]["file"], "TestDinos_TST")
        self.assertIsNone(value["summary"]["id"])
        self.assertEqual({key: value["sections"]["Commander"][0][key] for key in ("name", "set", "number", "finish")},
                         {"name": "Ghalta, Primal Hunger", "set": "rix", "number": "130", "finish": "foil"})
        self.assertEqual(sum(line["qty"] for rows in value["sections"].values() for line in rows), 25)
        self.assertNotIn("orix", json.dumps(value))
        self.assertEqual(len(self.writes), count)
        self.assert_intrinsic(value)

    def test_partial_published_sources_refuse_a_misleading_comparison_and_unknown_cards_stay_unknown(self):
        self.assertApiError(502, comparison_lists.precon_view, "Unfinished_TST")
        self.listed("UnknownBaseline_TST", {"data": {"name": "Unknown baseline", "mainBoard": [
            fixtures.card("Unindexed fixture spell", "TST", "999")] }}, kind="Theme Deck")
        value = comparison_lists.precon_view("UnknownBaseline_TST")
        self.assertTrue(value["stats_unknown"])
        self.assertIsNone(value["stats"])
