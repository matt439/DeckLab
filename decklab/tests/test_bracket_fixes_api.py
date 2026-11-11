"""Bracket fix projections stay intrinsic; checked replacement plans keep edit/inventory/CAS boundaries."""
import copy
import json
from unittest import mock

from decklab.lib import api, cards, inventory, stats as real_stats
from decklab.lib.stats import commander as stats_commander
from decklab.lib.api import bracket_fixes as fixes_api, guard, swaps
from decklab.tests.test_api import FIXTURES, _write
from decklab.tests.test_collection_edit import CollectionEditTestCase

TEXT = """# Bracket fixture

- **Format:** Commander
- **Played by:** user
- **Status:** building
- **Target bracket:** 2

## Decklist

```
Commander
1 Finneas, Ace Archer (BLB) 212
Deck
1 Smothering Tithe (CMM) 473
98 Forest
```
"""


class BracketFixApiTests(CollectionEditTestCase):
    def setUp(self):
        super().setUp()
        fixture_cards = self.box.root / "bracket-cards.jsonl"
        fixture_cards.write_text((FIXTURES / "default_cards.jsonl").read_text(encoding="utf-8") + "\n" +
                                 (FIXTURES / "stats_cards.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        index = cards.build_index(fixture_cards, FIXTURES / "oracle_tags.jsonl",
                                  {"default_cards": "2026-10-28", "oracle_tags": "2026-10-28"}, log=lambda *args: None)
        index_path = self.box.root / "bracket-index.json.gz"
        cards.write_index(index, index_path)
        previous = cards._index
        self.addCleanup(setattr, cards, "_index", previous)
        cards.load(index_path)
        self.path = self.box.magic / "decks/commander/bracket-fixture.md"
        _write(self.path, TEXT)
        self.box.stats.side_effect = real_stats.deck_stats
        self.box.stack.enter_context(mock.patch.object(stats_commander, "TAG_FILE", FIXTURES / "stats_tags.jsonl"))

    def page(self):
        return api.deck_view("commander/bracket-fixture", omit=("matchups",))

    def request(self):
        value = self.page()
        return {"id": value["summary"]["id"], "version": "target", "sha256": value["stats"]["commander"]["bracket"]["fixes"]["receipt"],
                "target": 2, "cuts": ["Smothering Tithe"], "card": "Smothering Tithe"}

    def test_target_plan_is_attached_without_private_receipts_for_public_readers(self):
        with self.as_("matt"):
            private = self.page()["stats"]["commander"]["bracket"]["fixes"]
        self.assertTrue(private["checked"])
        self.assertEqual(private["cuts"], 1)
        self.assertEqual(len(private["receipt"]), 64)
        with self.as_("user2"), mock.patch.object(guard, "public_deck_spaces", return_value={"home"}):
            before = self.page()["stats"]["commander"]["bracket"]["fixes"]
            self.assertIsNone(before["receipt"])
            _write(self.path, TEXT.replace("- **Status:**", "- **Sleeves:** PRIVATE_KIT_MARKER\n- **Status:**", 1))
            after = self.page()["stats"]["commander"]["bracket"]["fixes"]
        self.assertEqual(after, before)
        self.assertNotIn("PRIVATE_KIT_MARKER", json.dumps(after))

    def test_replacements_recheck_safe_unsafe_and_unknown_minima_without_writing(self):
        candidates = [{"name": name, "max_qty": 1} for name in ("Llanowar Elves", "Smothering Tithe", "Unknown fixture spell")]
        with self.as_("matt"):
            body = self.request()
            with mock.patch.object(swaps, "suggest_replacements", return_value={"candidates": copy.deepcopy(candidates)}), \
                    mock.patch.object(inventory, "apply", side_effect=AssertionError("No deck or inventory write")):
                answer = fixes_api.replacements(json.dumps(body))
        self.assertEqual([(row["name"], row["fit"], row["after_minimum"]) for row in answer["candidates"]],
                         [("Llanowar Elves", "safe", 1), ("Smothering Tithe", "unsafe", 3), ("Unknown fixture spell", "unknown", None)])
        self.assertTrue(answer["candidates"][0]["one_swap_legal"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), TEXT)

    def test_hidden_and_public_inventory_guards_precede_cut_validation(self):
        with self.as_("user2"):
            self.assertApiError(404, fixes_api.replacements, json.dumps({"id": "commander/bracket-fixture"}))
        with self.as_("user2"), mock.patch.object(guard, "public_deck_spaces", return_value={"home"}):
            self.assertApiError(403, fixes_api.replacements, json.dumps({"id": "commander/bracket-fixture"}), contains="That collection isn't public.")
        with self.as_("user2"), mock.patch.object(guard, "public_deck_spaces", return_value={"home"}), \
                mock.patch.object(swaps, "_require_cards", side_effect=AssertionError("Private inventory refuses before card-data validation")):
            self.assertApiError(403, fixes_api.replacements, json.dumps({"id": "commander/bracket-fixture"}))

    def test_stale_receipts_targets_and_nonminimal_cutsets_are_refused(self):
        with self.as_("matt"):
            body = self.request()
            for changed in ({**body, "sha256": "0" * 64}, {**body, "target": 3},
                            {**body, "cuts": ["Smothering Tithe", "Finneas, Ace Archer"]}):
                self.assertApiError(409, fixes_api.replacements, json.dumps(changed))

    def test_malformed_or_unavailable_counted_inputs_cannot_be_a_safe_replacement(self):
        for stats in (None, [], {"commander": []}, {"commander": {"bracket": {"minimum": 1}}}):
            self.assertIsNone(fixes_api._checked_minimum(stats))

    def test_missing_tag_data_is_an_explicit_unavailable_plan(self):
        with self.as_("matt"), mock.patch.object(stats_commander, "TAG_FILE", self.box.root / "missing-tags.jsonl"):
            answer = self.page()["stats"]["commander"]["bracket"]["fixes"]
        self.assertFalse(answer["checked"])
        self.assertNotIn("missing-tags", answer["reason"])

    def test_commander_replacement_is_explicit_and_cannot_bypass_identity_checks(self):
        source_text = TEXT.replace("1 Finneas, Ace Archer (BLB) 212", "1 Finneas, Ace Archer")
        _write(self.path, source_text)
        collection = self.box.magic / "collection.csv"
        _write(collection, collection.read_text(encoding="utf-8") + '"Wilson, Refined Grizzly",clb,522,nonfoil,1,NM,en,\n')
        real_card = cards.card

        def game_changer_commander(name):
            value = real_card(name)
            return {**value, "game_changer": True} if value and name == "Finneas, Ace Archer" else value

        with self.as_("matt"), mock.patch.object(cards, "card", side_effect=game_changer_commander):
            body = self.request()
            body.update(card="Finneas, Ace Archer", cuts=["Finneas, Ace Archer", "Smothering Tithe"])
            answer = fixes_api.replacements(json.dumps(body))
        wilson = next(row for row in answer["candidates"] if row["name"] == "Wilson, Refined Grizzly")
        self.assertEqual(wilson["section"], "Commander")
        self.assertEqual((wilson["fit"], wilson["after_minimum"]), ("safe", 1))
        # Only swapping the green/white leader leaves the white card outside Wilson's green identity.
        self.assertFalse(wilson["one_swap_legal"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), source_text)
