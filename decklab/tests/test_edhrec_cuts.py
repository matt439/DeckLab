"""Cut evidence is cached, intrinsic and optional; no evidence is an automatic edit."""
import copy
import json
from unittest import mock

from decklab.lib import access, cards, decks, edhrec, edhrec_cuts, inventory
from decklab.lib.api import deck_cuts, guard
from decklab.tests.test_edhrec import IdeasCase, PAGE

LIST = "Commander\n1 Ghalta, Primal Hunger\nDeck\n12 Llanowar Elves\n1 Elvish Mystic\n1 Pick Your Poison\n1 Sol Ring\n1 Black Lotus\n"


class CutEvidenceTests(IdeasCase):
    def setUp(self):
        super().setUp()
        self.source = edhrec.reduce_page(PAGE, "ghalta-primal-hunger", edhrec._now())
        self.source["lists"] = [{"header": "Fixture", "cards": [
            {"name": "Llanowar Elves", "decks": 800, "of": 1000}, {"name": "Elvish Mystic", "decks": 10, "of": 1000},
            {"name": "Pick Your Poison", "decks": 0, "of": 1000}, {"name": "Sol Ring", "decks": None, "of": None}]}]
        self.cache.joinpath("ghalta-primal-hunger.json").write_text(json.dumps(self.source), encoding="utf-8")
        self.get.side_effect = AssertionError("Cuts must never fetch EDHREC")
        self.sections = decks.parse_decklist(LIST)

    def project(self, **kwargs):
        with mock.patch.object(edhrec, "_write", side_effect=AssertionError("No cache write")):
            return edhrec_cuts.project(self.sections, ["Ghalta, Primal Hunger"], **kwargs)

    def test_known_inclusion_sorts_ascending_while_absent_and_unknown_are_separate(self):
        before = self.cache.joinpath("ghalta-primal-hunger.json").read_bytes()
        groups = {group["key"]: group["cards"] for group in self.project()["groups"]}
        self.assertEqual([(row["name"], row["inclusion"]) for row in groups["ranked"]],
                         [("Pick Your Poison", 0), ("Elvish Mystic", 1), ("Llanowar Elves", 80)])
        self.assertEqual([(row["name"], row["inclusion"]) for row in groups["unquantified"]], [("Sol Ring", None)])
        self.assertEqual([(row["name"], row["inclusion"]) for row in groups["absent"]], [("Black Lotus", None)])
        self.assertEqual(self.cache.joinpath("ghalta-primal-hunger.json").read_bytes(), before)
        self.get.assert_not_called()

    def test_missing_or_malformed_cache_never_claims_absence_or_zero_inclusion(self):
        for source in (None, {**self.source, "lists": "broken"}):
            with self.subTest(source=source), mock.patch.object(edhrec, "_read", return_value=source):
                answer = self.project()
            self.assertFalse(answer["source"]["available"])
            self.assertEqual([group["key"] for group in answer["groups"]], ["uncached"])
            self.assertTrue(all(row["inclusion"] is None for row in answer["groups"][0]["cards"]))

    def test_role_counts_and_settled_forge_thresholds_are_evidence_without_a_worst_card(self):
        stats = {"games": 800, "enough": True, "rows": [
            {"name": "Llanowar Elves", "land": False, "drawn_games": 30, "cast": 0, "other_casts": 0},
            {"name": "Elvish Mystic", "land": False, "drawn_games": 40, "cast": 10, "other_casts": 0,
             "copies_drawn": 20, "stuck_share": .2}]}
        answer = self.project(forge_stats=stats)
        rows = {row["name"]: row for group in answer["groups"] for row in group["cards"]}
        self.assertIn("role", [reason["kind"] for reason in rows["Llanowar Elves"]["reasons"]])
        self.assertIn("forge-never", [reason["kind"] for reason in rows["Llanowar Elves"]["reasons"]])
        self.assertIn("forge-stuck", [reason["kind"] for reason in rows["Elvish Mystic"]["reasons"]])
        self.assertNotIn("worst", json.dumps(answer))
        for changed in ({**stats, "games": 799}, {**stats, "enough": False}):
            early = self.project(forge_stats=changed)
            self.assertFalse(any(reason["kind"].startswith("forge") for group in early["groups"] for row in group["cards"] for reason in row["reasons"]))

    def test_commander_land_sideboard_and_unknown_card_are_not_ranked_as_cuts(self):
        self.sections["Deck"] += decks.parse_decklist("Deck\n1 Ghalta, Primal Hunger\n20 Forest\n1 Unindexed fixture\n")["Deck"]
        self.sections["Sideboard"] = decks.parse_decklist("Deck\n1 Wrath of God\n")["Deck"]
        real = cards.card
        with mock.patch.object(cards, "card", side_effect=lambda name: {"type_line": "Basic Land — Forest", "roles": []} if name == "Forest" else real(name)):
            answer = self.project()
        names = {row["name"] for group in answer["groups"] for row in group["cards"]}
        self.assertFalse(names.intersection({"Ghalta, Primal Hunger", "Forest", "Wrath of God", "Unindexed fixture"}))
        self.assertIn("Unindexed fixture", answer["unknown"])

    def test_api_public_deck_projection_has_no_inventory_counts_and_hidden404_is_first(self):
        with mock.patch.object(deck_cuts, "_forge_facts", return_value=None), \
                mock.patch.object(guard, "public_deck_spaces", return_value={"home"}), \
                mock.patch.object(guard, "viewer", return_value={"id": "user2", "space": "user2", "role": "member"}), \
                access.using({"profile": "user2", "remote": True}):
            answer = deck_cuts.cuts_view("commander/elf-commander")
        self.assertFalse(answer["may_edit"])
        self.assertNotIn("owned", json.dumps(answer))
        with access.using({"profile": "user2", "remote": True}), mock.patch.object(inventory, "current", side_effect=AssertionError("No hidden list read")):
            self.assertApiError(404, lambda: deck_cuts.preview_cuts(json.dumps({"id": "commander/elf-commander", "sections": "bad", "page": "bad/path"})))

    def test_draft_preview_uses_actual_planned_rows_without_a_write_or_old_forge_evidence(self):
        sections = {section: [{"name": line.name, "qty": line.quantity} for line in rows] for section, rows in self.sections.items()}
        before = copy.deepcopy(sections)
        with access.using({"profile": "matt", "remote": True}), mock.patch.object(deck_cuts, "_forge_facts", side_effect=AssertionError("Changed draft has no current-list games")), \
                mock.patch.object(inventory, "apply", side_effect=AssertionError("No deck write")):
            answer = deck_cuts.preview_cuts(json.dumps({"id": "commander/elf-commander", "sections": sections}))
        self.assertTrue(answer["draft"])
        self.assertEqual(answer["total"], 16)
        self.assertEqual(sections, before)

    def test_public_cut_projection_is_invariant_under_private_kit_and_table_only_changes(self):
        path = self.box.magic / "decks/commander/elf-commander.md"
        original = path.read_text(encoding="utf-8")
        with mock.patch.object(deck_cuts, "_forge_facts", return_value=None):
            with access.using({"profile": "matt", "remote": True}):
                editable_before = deck_cuts.cuts_view("commander/elf-commander")
            member = {"id": "user2", "space": "user2", "role": "member"}
            with access.using({"profile": "user2", "remote": True}), mock.patch.object(guard, "viewer", return_value=member), \
                    mock.patch.object(guard, "public_deck_spaces", return_value={"home"}):
                public_before = deck_cuts.cuts_view("commander/elf-commander")
                self.assertFalse(public_before["may_edit"])
                self.assertIsNone(public_before["sha256"])
                private_change = original.replace("- **Status:**", "- **Sleeves:** PRIVATE_KIT_MARKER\n- **Status:**", 1)
                private_change += ("\n## Owned vs needed\n\n"
                                   "| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |\n"
                                   "|---|---|---|---|---|---|---|\n"
                                   "| Llanowar Elves | 1 | 91 | 0 | | | PRIVATE_TABLE_MARKER |\n")
                path.write_text(private_change, encoding="utf-8")
                self.assertEqual(deck_cuts.cuts_view("commander/elf-commander"), public_before)
            with access.using({"profile": "matt", "remote": True}):
                editable_after = deck_cuts.cuts_view("commander/elf-commander")
            self.assertTrue(editable_after["may_edit"])
            self.assertNotEqual(editable_after["sha256"], editable_before["sha256"])
