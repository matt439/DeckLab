"""Atomic editor promotion contracts, using the API's disposable files inventory only."""
from copy import deepcopy
from unittest import mock

from decklab.lib import api, decks
from decklab.lib.api import saving
from decklab.tests import test_editor as support


DECK_ID = "casual/table-test"


class EditorConsideringMoveTests(support.EditorTestCase):
    def setUp(self):
        super().setUp()
        self.seed([decks.DeckLine(2, "Aerie Mystics", "con", "1", "nonfoil", "Alternatives")])

    def seed(self, considering, text=None):
        block = "## Considering\n\n```\n" + "\n".join(decks.format_line(line) for line in considering) + "\n```\n\n"
        support._write(self.path(DECK_ID), (text or support.TABLE_DECK).replace("## Owned vs needed", block + "## Owned vs needed"))

    def parsed(self):
        return decks.parse_deck(self.text(DECK_ID).encode("utf-8"), "table-test", "casual")

    def proposal(self, section="Deck", indices=(0,)):
        view = api.edit_view(DECK_ID)
        lists = {"target": deepcopy(view["lists"]["target"]), "considering": deepcopy(view["lists"]["considering"])}
        moved = [lists["considering"][i] for i in indices]
        lists["considering"] = [line for i, line in enumerate(lists["considering"]) if i not in indices]
        lists["target"].setdefault(section, []).extend(moved)
        return view, lists

    def check(self, lists, sha=None):
        return api.check_draft(self.body(id=DECK_ID, sha256=sha or self.sha(DECK_ID), lists=lists))

    def test_deck_and_sideboard_promotions_check_without_writing_then_save_as_one_operation(self):
        source = decks.DeckLine(2, "Aerie Mystics", "con", "1", "nonfoil", "Alternatives")
        for section in ("Deck", "Sideboard"):
            with self.subTest(section=section):
                self.seed([source])
                original = self.path(DECK_ID).read_bytes()
                before = self.parsed()
                view, lists = self.proposal(section)
                with mock.patch.object(self.box.inventory, "apply", wraps=self.box.inventory.apply) as apply:
                    checked = self.check(lists, view["sha256"])
                    self.assertTrue(checked["ok"])
                    self.assertEqual(checked["changes"]["decklist"], True)
                    self.assertEqual(checked["changes"]["considering"], True)
                    self.assertEqual(self.path(DECK_ID).read_bytes(), original)
                    apply.assert_not_called()
                    saved = self.save(DECK_ID, lists, sha=view["sha256"])
                    apply.assert_called_once()
                    operation = apply.call_args.args[0]
                    self.assertEqual(operation.kind, "deck.save")
                    committed = decks.parse_deck(operation.params["text"].encode("utf-8"), "table-test", "casual")
                    self.assertEqual(committed.considering, [])
                    self.assertEqual(committed.target[section][-1], source)
                after = self.parsed()
                self.assertEqual(after.considering, [])
                self.assertEqual(after.target[section][-1], source)
                self.assertIsNone(after.owned)
                self.assertIsNone(saved["deck"]["lists"]["owned"])
                self.assertEqual(saved["marked"], support.TODAY)
                self.assertTrue(saved["table"]["rewritten"])
                self.assertEqual(after.get_field("Status"), before.get_field("Status"))
                self.assertIn("Keep this prose.", self.text(DECK_ID))

    def test_promotion_and_independent_play_now_edits_share_the_same_save(self):
        self.save(DECK_ID, {"owned": {"Deck": [{"qty": 2, "name": "Llanowar Elves", "set": "fdn", "number": "227"}]}})
        view, lists = self.proposal("Sideboard")
        lists["owned"] = deepcopy(view["lists"]["owned"])
        lists["owned"]["Deck"][0]["qty"] = 3
        with mock.patch.object(self.box.inventory, "apply", wraps=self.box.inventory.apply) as apply:
            self.assertTrue(self.check(lists)["ok"])
            self.save(DECK_ID, lists, sha=view["sha256"])
            apply.assert_called_once()
        after = self.parsed()
        self.assertEqual(after.considering, [])
        self.assertEqual(after.target["Sideboard"][0].quantity, 2)
        self.assertEqual(after.owned["Deck"][0].quantity, 3)

    def test_unknown_name_or_wrong_printing_refuses_the_complete_pair_before_any_write(self):
        sources = [decks.DeckLine(2, "Never Printed Card"),
                   decks.DeckLine(2, "Aerie Mystics", "fdn", "227"),
                   decks.DeckLine(2, "Aerie Mystics", "con", "1", "etched")]
        for source in sources:
            with self.subTest(source=source):
                self.seed([source])
                original = self.path(DECK_ID).read_bytes()
                _, lists = self.proposal()
                with mock.patch.object(self.box.inventory, "apply", wraps=self.box.inventory.apply) as apply:
                    checked = self.check(lists)
                    self.assertFalse(checked["ok"])
                    self.assertTrue(any(block["list"] == "target" for block in checked["blocks"]))
                    self.assertApiError(400, lambda: self.save(DECK_ID, lists))
                    apply.assert_not_called()
                self.assertEqual(self.path(DECK_ID).read_bytes(), original)
                self.assertEqual(self.parsed().considering, [source])

    def test_check_reports_category_loss_when_new_duplicate_printings_would_merge(self):
        self.seed([decks.DeckLine(2, "Aerie Mystics", "con", "1", "nonfoil", "Ramp"),
                   decks.DeckLine(3, "Aerie Mystics", "con", "1", "nonfoil", "Draw")])
        original = self.path(DECK_ID).read_bytes()
        _, lists = self.proposal(indices=(0, 1))
        checked = self.check(lists)
        self.assertTrue(checked["ok"])
        promoted = [line for line in checked["lists"]["target"]["Deck"] if line["name"] == "Aerie Mystics"]
        self.assertEqual([(line["qty"], line["category"]) for line in promoted], [(5, "Ramp")])
        self.assertEqual([(line["qty"], line["category"]) for line in lists["target"]["Deck"][-2:]],
                         [(2, "Ramp"), (3, "Draw")])
        # The client must detect this lossy proposal before removing the source from its draft.
        self.assertEqual(self.path(DECK_ID).read_bytes(), original)
        self.assertEqual(len(self.parsed().considering), 2)

    def test_check_exposes_default_printing_and_finish_changes_for_setless_sources(self):
        source = decks.DeckLine(2, "Aerie Mystics", finish="foil", category="Alternatives")
        self.seed([source])
        original = self.path(DECK_ID).read_bytes()
        _, lists = self.proposal()
        checked = self.check(lists)
        self.assertTrue(checked["ok"])
        promoted = checked["lists"]["target"]["Deck"][-1]
        self.assertEqual((promoted["qty"], promoted["set"], promoted["number"], promoted["finish"], promoted["category"]),
                         (2, "con", "1", "nonfoil", "Alternatives"))
        self.assertEqual((lists["target"]["Deck"][-1]["set"], lists["target"]["Deck"][-1]["finish"]), (None, "foil"))
        self.assertEqual(self.path(DECK_ID).read_bytes(), original)
        self.assertEqual(self.parsed().considering, [source])

    def test_explicit_foil_printing_and_category_survive_check_and_atomic_save(self):
        source = decks.DeckLine(2, "Aerie Mystics", "con", "1", "foil", "Draw")
        self.seed([source])
        _, lists = self.proposal("Sideboard")
        checked = self.check(lists)
        self.assertTrue(checked["ok"])
        self.assertEqual(checked["lists"]["target"]["Sideboard"][0]["finish"], "foil")
        self.save(DECK_ID, lists)
        self.assertEqual(self.parsed().target["Sideboard"], [source])
        self.assertEqual(self.parsed().considering, [])

    def test_new_duplicate_printing_overflow_refuses_both_lists_without_clamping(self):
        sources = [decks.DeckLine(99, "Aerie Mystics", "con", "1"), decks.DeckLine(1, "Aerie Mystics", "con", "1")]
        self.seed(sources)
        original = self.path(DECK_ID).read_bytes()
        _, lists = self.proposal(indices=(0, 1))
        with mock.patch.object(self.box.inventory, "apply", wraps=self.box.inventory.apply) as apply:
            checked = self.check(lists)
            self.assertFalse(checked["ok"])
            self.assertTrue(any("more than 99" in block["problem"] for block in checked["blocks"]))
            self.assertApiError(400, lambda: self.save(DECK_ID, lists))
            apply.assert_not_called()
        self.assertEqual(self.path(DECK_ID).read_bytes(), original)
        self.assertEqual(self.parsed().considering, sources)

    def test_known_printing_can_append_one_to_a_99_copy_row_preserving_both_categories(self):
        text = support.TABLE_DECK.replace("4 Llanowar Elves (FDN) 227", "99 Llanowar Elves (FDN) 227 #Ramp")
        source = decks.DeckLine(1, "Llanowar Elves", "fdn", "227", "nonfoil", "Draw")
        self.seed([source], text)
        _, lists = self.proposal()
        checked = self.check(lists)
        self.assertTrue(checked["ok"])
        same = [line for line in checked["lists"]["target"]["Deck"] if line["name"] == "Llanowar Elves"]
        self.assertEqual([(line["qty"], line["category"]) for line in same], [(99, "Ramp"), (1, "Draw")])
        self.save(DECK_ID, lists)
        same = [line for line in self.parsed().target["Deck"] if line.name == "Llanowar Elves"]
        self.assertEqual([(line.quantity, line.category) for line in same], [(99, "Ramp"), (1, "Draw")])
        self.assertEqual(self.parsed().considering, [])

    def test_stale_pair_is_reported_by_check_and_refused_before_any_write(self):
        view, lists = self.proposal()
        support._write(self.path(DECK_ID), self.text(DECK_ID) + "\nAn independent fixture edit.\n")
        latest = self.path(DECK_ID).read_bytes()
        with mock.patch.object(self.box.inventory, "apply", wraps=self.box.inventory.apply) as apply:
            self.assertTrue(self.check(lists, view["sha256"])["file_changed"])
            error = self.assertApiError(409, lambda: self.save(DECK_ID, lists, sha=view["sha256"]))
            self.assertEqual(error.extra["conflict"]["reason"], "changed")
            apply.assert_not_called()
        self.assertEqual(self.path(DECK_ID).read_bytes(), latest)
        self.assertEqual(len(self.parsed().considering), 1)

    def test_retry_after_success_cannot_apply_a_promotion_twice(self):
        view, lists = self.proposal()
        saved = self.save(DECK_ID, lists, sha=view["sha256"])
        committed = self.path(DECK_ID).read_bytes()
        with mock.patch.object(self.box.inventory, "apply", wraps=self.box.inventory.apply) as apply:
            self.assertApiError(409, lambda: self.save(DECK_ID, lists, sha=view["sha256"]))
            retry = self.save(DECK_ID, lists, sha=saved["sha256"])
            self.assertFalse(retry["changed"])
            apply.assert_not_called()
        self.assertEqual(self.path(DECK_ID).read_bytes(), committed)
        promoted = [line for line in self.parsed().target["Deck"] if line.name == "Aerie Mystics"]
        self.assertEqual([line.quantity for line in promoted], [2])
        self.assertEqual(self.parsed().considering, [])

    def test_change_after_check_is_refused_again_under_the_inventory_write(self):
        view, lists = self.proposal()
        self.assertTrue(self.check(lists, view["sha256"])["ok"])
        latest = self.text(DECK_ID) + "\nA fixture writer won the race.\n"
        apply = self.box.inventory.apply

        def competing_write(operation, *args, **kwargs):
            support._write(self.path(DECK_ID), latest)
            return apply(operation, *args, **kwargs)

        with mock.patch.object(self.box.inventory, "apply", side_effect=competing_write) as raced:
            self.assertApiError(409, lambda: self.save(DECK_ID, lists, sha=view["sha256"]))
            raced.assert_called_once()
        self.assertEqual(self.text(DECK_ID), latest)
        self.assertEqual(len(self.parsed().considering), 1)
        self.assertFalse(any(line.name == "Aerie Mystics" for line in self.parsed().target["Deck"]))
