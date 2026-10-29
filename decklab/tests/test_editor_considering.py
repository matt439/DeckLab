"""Considering normalization stays separate from playable editor lists and saved counts."""
from unittest import mock

from decklab.lib import api, decks
from decklab.lib.api import guard, saving
from decklab.tests import test_editor as support


DECK_ID = "casual/table-test"
CONSIDERING = "## Considering\n\n```\n1 Black Lotus (LEA) 232 #Power\n2 Aerie Mystics (CON) 1 #Alternatives\n```\n\n"


class EditorConsideringTests(support.EditorTestCase):
    def setUp(self):
        super().setUp()
        support._write(self.path(DECK_ID), support.TABLE_DECK.replace("## Owned vs needed", CONSIDERING + "## Owned vs needed"))

    def check(self, lists=None, **options):
        data = {"id": DECK_ID, "sha256": self.sha(DECK_ID), **options}
        if lists is not None:
            data["lists"] = lists
        return api.check_draft(self.body(**data))

    def parsed(self):
        return decks.parse_deck(self.text(DECK_ID).encode("utf-8"), "table-test", "casual")

    def facts(self, lines):
        return [(line["qty"], line["name"], line.get("set"), line.get("number"),
                 line.get("finish"), line.get("category")) for line in lines]

    def test_missing_or_null_considering_keeps_the_saved_flat_list_on_check_and_save(self):
        expected = self.facts(api.edit_view(DECK_ID)["lists"]["considering"])
        before = self.path(DECK_ID).read_bytes()
        for lists in (None, {}, {"considering": None}):
            with self.subTest(lists=lists):
                checked = self.check(lists)
                self.assertTrue(checked["ok"])
                self.assertEqual(self.facts(checked["lists"]["considering"]), expected)
                self.assertFalse(checked["changes"]["decklist"])
                self.assertFalse(checked["changes"].get("considering", False))
                self.assertFalse(self.save(DECK_ID, lists)["changed"])
                self.assertEqual(self.path(DECK_ID).read_bytes(), before)

    def test_explicit_empty_considering_clears_it_without_starting_play_now(self):
        checked = self.check({"considering": []})
        self.assertEqual(checked["lists"]["considering"], [])
        self.assertTrue(checked["changes"]["considering"])
        self.assertFalse(checked["changes"]["decklist"])
        before = self.parsed()
        with mock.patch.object(saving, "_rewrite_table", side_effect=AssertionError("Considering does not refresh the table")):
            saved = self.save(DECK_ID, {"considering": []})
        after = self.parsed()
        self.assertEqual(after.considering, [])
        self.assertIsNone(after.owned)
        self.assertIsNone(saved["deck"]["lists"]["owned"])
        self.assertEqual((saved["marked"], saved["table"]["rewritten"]), (None, False))
        self.assertEqual((after.target, after.rows, after.total, after.changed_on),
                         (before.target, before.rows, before.total, before.changed_on))

    def test_considering_only_changes_are_normalized_without_affecting_playable_counts(self):
        before = self.check()
        payload = {"considering": [{"qty": 3, "name": "llanowar elves", "category": "Alternatives"}]}
        checked = self.check(payload)
        [line] = checked["lists"]["considering"]
        self.assertEqual((line["qty"], line["name"], line["category"]), (3, "Llanowar Elves", "Alternatives"))
        self.assertTrue(line["set"] and line["number"])
        self.assertEqual(checked["counts"], before["counts"])
        self.assertEqual(checked["availability"], before["availability"])
        self.assertEqual(checked["bracket"], before["bracket"])
        self.assertEqual(set(checked["counts"]), {"target", "owned"})
        self.assertEqual(set(checked["availability"]), {"target", "owned"})
        self.assertIsNone(checked["lists"]["owned"])
        self.assertTrue(checked["changes"]["considering"])
        self.assertFalse(checked["changes"]["decklist"])
        original = self.parsed()
        saved = self.save(DECK_ID, {"considering": checked["lists"]["considering"]})
        after = self.parsed()
        self.assertEqual(len(after.considering), 1)
        self.assertEqual((after.target, after.owned, after.rows, after.changed_on),
                         (original.target, original.owned, original.rows, original.changed_on))
        self.assertEqual((saved["marked"], saved["table"]["rewritten"]), (None, False))

    def test_invalid_considering_marks_only_its_change_and_cannot_be_saved(self):
        payload = {"considering": [{"name": "Never Printed Card", "qty": 1}]}
        before = self.path(DECK_ID).read_bytes()
        checked = self.check(payload)
        self.assertFalse(checked["ok"])
        self.assertEqual({block["list"] for block in checked["blocks"]}, {"considering"})
        self.assertTrue(checked["changes"]["considering"])
        self.assertFalse(checked["changes"]["decklist"])
        self.assertApiError(400, lambda: self.save(DECK_ID, payload))
        self.assertEqual(self.path(DECK_ID).read_bytes(), before)

    def test_invalid_playable_lines_still_mark_a_playable_list_change(self):
        checked = self.check({"target": {"Deck": [{"name": "Never Printed Card", "qty": 1}]}})
        self.assertFalse(checked["ok"])
        self.assertTrue(checked["changes"]["decklist"])
        self.assertFalse(checked["changes"].get("considering", False))
        self.assertEqual({block["list"] for block in checked["blocks"]}, {"target"})

    def test_existing_unknown_considering_name_is_preserved_but_cannot_move_into_planned(self):
        text = self.text(DECK_ID).replace("2 Aerie Mystics (CON) 1 #Alternatives", "1 Never Printed Card")
        support._write(self.path(DECK_ID), text)
        view = api.edit_view(DECK_ID)
        kept = self.check({"considering": view["lists"]["considering"]})
        self.assertTrue(kept["ok"])
        self.assertEqual(kept["lists"]["considering"][-1]["name"], "Never Printed Card")
        self.assertFalse(kept["changes"]["decklist"])
        self.assertFalse(kept["changes"]["considering"])
        self.assertFalse(self.save(DECK_ID, {"considering": kept["lists"]["considering"]})["changed"])
        moved = {"target": view["lists"]["target"], "considering": view["lists"]["considering"][:-1]}
        moved["target"]["Deck"].append(view["lists"]["considering"][-1])
        checked = self.check(moved)
        self.assertFalse(checked["ok"])
        self.assertTrue(checked["changes"]["decklist"])
        self.assertTrue(checked["changes"]["considering"])
        self.assertEqual(checked["blocks"][0]["list"], "target")
        self.assertApiError(400, lambda: self.save(DECK_ID, moved))
        self.assertEqual(self.text(DECK_ID), text)

    def test_considering_only_save_keeps_an_existing_decklist_changed_marker(self):
        support._write(self.path(DECK_ID), self.text(DECK_ID).replace("Some prose about the deck.",
                      support.MARKER + "\n\nSome prose about the deck."))
        before = self.parsed().changed_on
        self.assertEqual(before, support.TODAY)
        self.save(DECK_ID, {"considering": []})
        self.assertEqual(self.parsed().changed_on, before)

    def test_normalized_considering_does_not_add_inventory_counts_for_public_readers(self):
        with mock.patch.object(guard, "sees_inventory", return_value=False):
            checked = self.check()
        self.assertEqual(len(checked["lists"]["considering"]), 2)
        self.assertIsNone(checked["owned"])
        self.assertEqual(checked["availability"], {"target": None, "owned": None})
        self.assertFalse(any("free" in line or "on_the_way" in line or "have" in line
                             for line in checked["lists"]["considering"]))

    def test_new_decks_keep_the_existing_playable_only_payload_contract(self):
        lists = {"target": {"Deck": [{"name": "Forest", "qty": 20}]}}
        checked = api.check_draft(self.body(kind="casual", lists=lists))
        self.assertNotIn("considering", checked["lists"])
        lists["considering"] = []
        self.assertApiError(400, api.check_draft, self.body(kind="casual", lists=lists), contains="Unknown list")
        self.assertApiError(400, api.create_deck, self.body(title="New Deck", kind="casual", lists=lists),
                            contains="Unknown list")
