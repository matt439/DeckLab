"""Whole-deck take-apart evidence and existing status saves, using disposable fixture data only."""
import copy
import json
from unittest import mock

from decklab.lib import access, decks, inventory, pool
from decklab.lib.api import assembly, assembly_takeapart, saving
from decklab.lib.api.common import ApiError
from decklab.lib.decks import assembled, standins
from decklab.lib.inventory import files, ops_decks
from decklab.tests import household_config
from decklab.tests.test_assembly_completion import TABLE
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


ELF = "Llanowar Elves"
MYSTIC = "Elvish Mystic"
POISON = "Pick Your Poison"
MAIN = f"Deck\n4 {ELF}\n20 Forest\n\nSideboard\n2 {MYSTIC}\n"
OWNED = f"Deck\n2 {MYSTIC}\n20 Forest\n\nSideboard\n1 {POISON}\n"


class AssemblyTakeApartTests(PreparationCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        active = access.using({"profile": "matt", "email": "matt@example.com", "remote": True})
        active.__enter__()
        self.addCleanup(active.__exit__, None, None, None)
        self.cards_csv("collection.csv", (ELF, "fdn", "227", "nonfoil", 8),
                       (MYSTIC, "cmm", "648", "nonfoil", 8), (POISON, "mkm", "170", "nonfoil", 2))
        self.deck("a", "A", "built", MAIN, owned=OWNED, built_version="target", table=TABLE)

    def record(self):
        return inventory.current().deck("casual/a")

    def parsed(self):
        return ops_decks.parsed_deck(self.record())

    def write_model(self, deck):
        self.write("decks/casual/a.md", decks.render_deck_file(deck))

    def checklist(self, version="target"):
        return self.preview(("a", version))["decks"][0]["take_apart"]

    def project(self, deck=None, kit=None):
        return assembly_takeapart.project(deck or self.parsed(), self.record(), kit)

    def rows(self, checklist):
        return [row for rows in checklist["sections"].values() for row in rows]

    def test_legacy_list_is_complete_and_independent_of_the_current_selected_version(self):
        before = files.render(inventory.current(), decks=True)
        with mock.patch.object(self.inventory, "apply", side_effect=AssertionError("Checklist reads never write")):
            result = self.checklist("owned")
        self.assertTrue(result["available"])
        self.assertTrue(result["can_take_apart"])
        self.assertEqual((result["source"], result["version"], result["sha256"]),
                         ("built-list", "target", self.record().sha256))
        self.assertEqual(result["card_count"], 26)
        self.assertEqual([(name, sum(row["quantity"] for row in rows))
                          for name, rows in result["sections"].items()], [("Deck", 24), ("Sideboard", 2)])
        self.assertEqual({row["name"] for row in self.rows(result)}, {ELF, MYSTIC, "Forest"})
        self.assertNotIn(POISON, {row["name"] for row in self.rows(result)})
        self.assertEqual((result["tokens_recorded"], result["tokens"], result["token_count"]), (False, [], 0))
        self.assertEqual(files.render(inventory.current(), decks=True), before)

    def test_saved_snapshot_remains_authoritative_after_intended_list_and_sideboard_changes(self):
        deck = self.parsed()
        old = decks.parse_decklist(f"Deck\n2 {MYSTIC}\n20 Forest\n\nSideboard\n1 {POISON}\n")
        assembled.install(deck, "owned", old)
        deck.owned = decks.parse_decklist(f"Deck\n4 {ELF}\n10 Forest\n")
        self.write_model(deck)
        result = self.checklist()
        self.assertEqual((result["source"], result["version"], result["card_count"]), ("assembled", "owned", 23))
        self.assertEqual({row["name"] for row in self.rows(result)}, {MYSTIC, POISON, "Forest"})
        self.assertNotIn(ELF, {row["name"] for row in self.rows(result)})
        self.assertEqual(assembled.sections(self.parsed()), old)
        self.deck("a", "A", "built", MAIN, table=TABLE)
        deck = self.parsed()
        assembled.install(deck, "owned", old)
        self.write_model(deck)
        removed_version = self.checklist()
        self.assertEqual(removed_version["sections"], result["sections"])
        self.assertEqual(removed_version["version"], "owned")

    def test_every_canonical_section_and_basics_is_present_without_printing_claims(self):
        deck = self.parsed()
        deck.kind = "commander"
        physical = decks.parse_decklist(f"Commander\n1 Aerie Mystics\n\nCompanion\n1 {POISON}\n"
                                       f"\nDeck\n1 {ELF} (FDN) 227 *F*\n1 {ELF} (M19) 314\n20 forest\n"
                                       f"\nSideboard\n1 {MYSTIC}\n")
        assembled.install(deck, "target", physical)
        result = self.project(deck)
        self.assertTrue(result["available"], result["reason"])
        self.assertEqual(list(result["sections"]), list(decks.SECTIONS))
        self.assertEqual(result["card_count"], 25)
        main = result["sections"]["Deck"]
        self.assertEqual(next(row["quantity"] for row in main if row["name"] == ELF), 2)
        self.assertTrue(next(row["basic"] for row in main if row["name"] == "Forest"))
        self.assertTrue(all("set" not in row and "finish" not in row for row in self.rows(result)))

    def test_installed_markers_replace_real_targets_once_across_sections_not_future_choices(self):
        deck = self.parsed()
        physical = decks.parse_decklist(f"Deck\n2 {ELF}\n20 Forest\n\nSideboard\n2 {ELF}\n")
        assembled.install(deck, "target", physical)
        standins.set_stand_ins(deck, {"target": [{"for": ELF, "using": POISON, "qty": 4}], "owned": [],
                                     "built": {"version": "target", "cards": [
                                         {"for": ELF, "using": MYSTIC, "qty": 1},
                                         {"for": ELF, "using": None, "qty": 2}]}})
        original = copy.deepcopy(deck.target), copy.deepcopy(standins.get_stand_ins(deck))
        result = self.project(deck)
        self.assertTrue(result["available"], result["reason"])
        self.assertEqual(result["card_count"], 24)
        rows = self.rows(result)
        self.assertEqual(sum(row["quantity"] for row in rows if row["name"] == ELF), 1)
        self.assertEqual(sum(row["quantity"] for row in rows if row["name"] == MYSTIC), 1)
        self.assertNotIn(POISON, [row["name"] for row in rows])
        anonymous = [row for row in rows if row["name"] is None]
        self.assertEqual(sum(row["quantity"] for row in anonymous), 2)
        self.assertTrue(all(row["kind"] == "marker" and row["basic"] is None and row["for"] == ELF for row in anonymous))
        self.assertEqual(sum(row["quantity"] for row in result["sections"]["Deck"]), 22)
        self.assertEqual(sum(row["quantity"] for row in result["sections"]["Sideboard"]), 2)
        self.assertEqual((deck.target, standins.get_stand_ins(deck)), original)

    def test_packed_token_card_pairs_count_physical_cards_and_absent_is_not_an_explicit_empty_record(self):
        deck = self.parsed()
        decks.set_token_cards(deck, [decks.TokenCardLine(2, "Dog", "Beast", "tfdn", "12"),
                                     decks.TokenCardLine(1, "The Monarch")])
        self.write_model(deck)
        result = self.checklist()
        self.assertTrue(result["tokens_recorded"])
        self.assertEqual(result["token_count"], 3)
        self.assertEqual(result["tokens"], [{"quantity": 2, "front": "Dog", "back": "Beast", "set": "tfdn", "number": "12"},
                                           {"quantity": 1, "front": "The Monarch", "back": "", "set": "", "number": ""}])
        decks.set_token_cards(deck, [])
        result = self.project(deck)
        self.assertEqual((result["tokens_recorded"], result["tokens"], result["token_count"]), (True, [], 0))

    def test_visible_kit_is_copied_and_raw_private_kit_headers_are_never_projected(self):
        deck = self.parsed()
        decks.set_sleeves(deck, "private-secret-sleeves")
        decks.set_deck_box(deck, "private-secret-box")
        hidden = self.project(deck)
        self.assertIsNone(hidden["kit"])
        self.assertTrue(hidden["kit_reason"])
        self.assertNotIn("private-secret", json.dumps(hidden))
        kit = {"sleeves": {"id": "shared-sleeves", "label": "Shared sleeve label", "state": "linked"},
               "deck_box": {"state": "text", "value": "older box", "label": "older box"}}
        visible = self.project(deck, kit)
        self.assertEqual(visible["kit"], kit)
        visible["kit"]["sleeves"]["label"] = "Changed output"
        self.assertEqual(kit["sleeves"]["label"], "Shared sleeve label")

    def test_home_reader_without_deck_edit_gets_guidance_with_a_read_only_reason(self):
        deck = self.parsed()
        decks.set_player(deck, "user")
        self.write_model(deck)
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            result = self.checklist()
        self.assertTrue(result["available"])
        self.assertFalse(result["can_take_apart"])
        self.assertTrue(result["why_not"])

    def test_nonbuilt_other_space_and_synthetic_participants_have_no_checklist(self):
        deck = self.parsed()
        for field, value in (("status", "building"), ("space", "user2"), ("kind", "product"), ("kind", "pairing")):
            with self.subTest(field=field, value=value):
                clone = copy.deepcopy(deck)
                if field == "status":
                    decks.set_status(clone, value)
                else:
                    setattr(clone, field, value)
                self.assertIsNone(self.project(clone))
        self.assertIsNone(assembly_takeapart.project(None, None, None))
        decks.set_status(deck, "building")
        self.write_model(deck)
        self.assertNotIn("take_apart", self.preview(("a", "target"))["decks"][0])
        self.product("fixture-precon.csv", ("deck", ELF, 2), ("deck", "Forest", 20), column="section")
        product_plan = assembly.assembly_preview(json.dumps({"profile": "matt", "decks": [
            {"id": "product/fixture-precon", "version": "target"}]}))
        self.assertNotIn("take_apart", product_plan["decks"][0])

    def test_legacy_without_built_version_uses_the_existing_play_now_fallback_explicitly(self):
        deck = self.parsed()
        decks.set_built_version(deck, None)
        result = self.project(deck)
        self.assertEqual((result["source"], result["version"], result["card_count"]), ("built-list", "owned", 23))
        self.assertIn(POISON, {row["name"] for row in self.rows(result)})

    def test_other_spaces_are_refused_before_the_physical_projection_runs(self):
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}), \
                mock.patch.object(assembly_takeapart, "project", side_effect=AssertionError("No physical build read")):
            with self.assertRaises(ApiError) as caught:
                self.checklist()
        self.assertEqual(caught.exception.status, 403)

    def test_bad_physical_snapshot_helper_is_unavailable_and_preview_keeps_existing_409(self):
        deck = self.parsed()
        deck.header.append(decks.HeaderField(assembled.FIELD, '{"bad":1}'))
        self.write_model(deck)
        result = self.project()
        self.assertFalse(result["available"])
        self.assertFalse(result["can_take_apart"])
        self.assertTrue(result["reason"])
        self.assertEqual((result["sections"], result["card_count"]), ({}, None))
        with self.assertRaises(ApiError) as caught:
            self.preview(("a", "target"))
        self.assertEqual(caught.exception.status, 409)

    def test_malformed_or_mismatched_installed_markers_and_unresolved_cards_never_guess_a_checklist(self):
        cases = [{"for": ELF, "using": MYSTIC, "qty": 5}, {"for": "Forest", "using": MYSTIC, "qty": 1},
                 {"for": ELF, "using": "Forest", "qty": 1}, {"for": ELF, "using": "Unknown fixture card", "qty": 1}]
        for mapping in cases:
            with self.subTest(mapping=mapping):
                deck = self.parsed()
                standins.set_stand_ins(deck, {"built": {"version": "target", "cards": [mapping]}})
                result = self.project(deck)
                self.assertFalse(result["available"])
                self.assertEqual(result["card_count"], None)
        deck = self.parsed()
        standins.set_stand_ins(deck, {"built": {"version": "owned", "cards": []}})
        self.assertFalse(self.project(deck)["available"])
        deck = self.parsed()
        decks.set_token_cards(deck, [])
        deck.header.append(decks.HeaderField("Token cards", "not a token-card line"))
        self.assertFalse(self.project(deck)["available"])

    def test_unreadable_token_evidence_is_explicit_in_an_otherwise_readable_api_plan(self):
        deck = self.parsed()
        deck.header.append(decks.HeaderField("Token cards", "not a token-card line"))
        self.write_model(deck)
        with mock.patch.object(assembly.common, "_log"):
            result = self.checklist()
        self.assertFalse(result["available"])
        self.assertFalse(result["can_take_apart"])
        self.assertTrue(result["reason"])
        self.assertEqual((result["sections"], result["card_count"], result["token_count"]), ({}, None, None))

    def test_existing_status_save_after_review_clears_only_physical_reservations_and_preserves_intent(self):
        deck = self.parsed()
        decks.set_player(deck, "user")
        decks.set_sleeves(deck, "older red sleeves")
        decks.set_deck_box(deck, "older blue box")
        assembled.install(deck, "target", deck.target)
        mapping = {"for": ELF, "using": POISON, "qty": 1}
        standins.set_stand_ins(deck, {"target": [mapping], "built": {"version": "target", "cards": [mapping]}})
        decks.set_token_cards(deck, [decks.TokenCardLine(1, "The Monarch")])
        self.write_model(deck)
        before = self.parsed()
        collection = inventory.current().collection()
        result = self.checklist()
        self.assertTrue(result["available"], result["reason"])
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            saved = saving.save_deck(json.dumps({"profile": "matt", "id": "casual/a", "sha256": result["sha256"],
                                                "fields": {"status": "building"}}))
        self.assertTrue(saved["saved"])
        self.assertEqual(apply.call_count, 1)
        after = self.parsed()
        self.assertEqual(after.status, "building")
        self.assertEqual((after.target, after.owned), (before.target, before.owned))
        self.assertEqual((after.sleeves, after.deck_box, after.built_version), (None, None, None))
        self.assertIsNone(assembled.get(after))
        self.assertEqual(assembled.generation(after), assembled.generation(before) + 1)
        self.assertIsNone(standins.installed_for(after))
        self.assertEqual(standins.choices_for(after, "target"), [mapping])
        self.assertFalse(decks.has_token_cards(after))
        self.assertEqual(inventory.current().collection(), collection)
        self.assertFalse(any(holder.id == "casual/a" for holder in pool.load_pool().in_use))

    def test_reviewed_sha_refuses_a_later_deck_edit_without_an_apply(self):
        result = self.checklist()
        self.write("decks/casual/a.md", self.record().text + "\n## Notes\n\nLater fixture edit.\n")
        before = files.render(inventory.current(), decks=True)
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            with self.assertRaises(ApiError) as caught:
                saving.save_deck(json.dumps({"profile": "matt", "id": "casual/a", "sha256": result["sha256"],
                                            "fields": {"status": "building"}}))
        self.assertEqual(caught.exception.status, 409)
        apply.assert_not_called()
        self.assertEqual(files.render(inventory.current(), decks=True), before)
