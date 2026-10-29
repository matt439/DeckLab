"""Deleted-token review uses authoritative fake audit rows and disposable stock only."""
import copy
from dataclasses import replace
import unittest
from unittest import mock

from decklab.lib import cards, inventory
from decklab.lib.inventory import model, rules, undo, undo_token_delete as deleted
from decklab.lib.tokens import names, ops
from decklab.tests import test_activity_undo_api as fixture

TARGET = 71


def token(front="Angel", back="The Monarch", quantity=2, **extra):
    return {**{field: "" for field in rules.TOKEN_FIELDS}, "front": front, "back": back,
            "set": "tst", "front_collector_number": "1", "back_collector_number": "2" if back else "",
            "finish": "nonfoil", "quantity": quantity, "notes": "Paired faces verified", **extra}


class TokenDeleteFixture(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ActivityUndoApiTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store = self.case.backend
        self.products = self.store.snapshot.products
        self.store.snapshot = self.store.snapshot.replace(decks={}, products=(), tokens={},
            status=model.Sheet("magic/products/status.csv", tuple(rules.STATUS_FIELDS), (), True))
        self.store.undo_token_latest = mock.Mock(side_effect=lambda space: self.latest)
        self.store.undo_token_positions = mock.Mock(side_effect=lambda space: copy.deepcopy(self.layout))
        self.enterContext(mock.patch.object(names, "check_names", side_effect=lambda row: (dict(row), [])))
        self.enterContext(mock.patch.object(cards, "printing", return_value={"digital": False, "games": ["paper"],
                                                                           "finishes": ["nonfoil", "foil"]}))
        self.enterContext(mock.patch.object(cards, "_get", side_effect=AssertionError("No real card cache")))
        for name in ("add", "edit", "remove"):
            self.enterContext(mock.patch.object(ops, name, side_effect=AssertionError("Read-only review cannot write")))
        self.seed()

    def seed(self, row=None, survivors=(), *, space="home"):
        self.space = space
        self.old = copy.deepcopy(token() if row is None else row)
        self.store.snapshot = self.store.snapshot.with_tokens(space, survivors)
        self.layout = [{"id": row.id, "position": (index + 1) * 1024}
                       for index, row in enumerate(self.store.snapshot.token_set(space).rows)]
        old = {"set_code" if key == "set" else key: value for key, value in self.old.items()}
        old.update(space_id=space, id=TARGET, position=500)
        self.store.audit[fixture.CHANGE_ID] = [{"id": fixture.ROW_ID, "table": "token_card", "op": "DELETE",
                                               "key": {"id": TARGET}, "before": old, "after": None}]
        self.store.latest = self.latest = fixture.ROW_ID

    def review(self):
        return inventory.undo_review(fixture.CHANGE_ID, self.space, self.store.snapshot)

    def source(self):
        return self.store.audit[fixture.CHANGE_ID][0]

    def built(self, packed="", *, space="home", headers="", status="built"):
        line = "" if packed is None else "- **Token cards:** " + packed + "\n"
        text = "# Fixture holder\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** " + status + "\n" \
            + line + headers + "\n## Decklist\n\n```\nDeck\n1 Llanowar Elves\n59 Forest\n```\n"
        self.store.snapshot = self.store.snapshot.with_deck(model.Deck(space, "casual", "fixture", text))

    def product(self, packed):
        product = next(item for item in self.products if item.file == "fdn-beginner-box.csv")
        row = model.StatusRow.make({"file": product.file, "status": "owned", "intact": "yes", "token_cards": packed})
        self.store.snapshot = self.store.snapshot.replace(products=(product,),
            status=model.Sheet("magic/products/status.csv", tuple(rules.STATUS_FIELDS), (row,), True))


class TokenDeleteTests(TokenDeleteFixture):
    def test_paired_record_is_reviewed_as_physical_cards_without_writing(self):
        before, audit, layout = self.store.snapshot, copy.deepcopy(self.store.audit), copy.deepcopy(self.layout)
        plan = self.review()
        self.assertEqual(plan["action"], deleted.ACTION)
        self.assertNotIn("read_only", plan)
        self.assertIsNone(plan["current"])
        self.assertEqual(plan["restore"], self.old)
        self.assertEqual(plan["restore"]["quantity"], 2)
        self.assertEqual(plan["identity_policy"], "fresh_id")
        self.assertIs(plan["physical_confirmation_required"], True)
        self.assertIs(plan["packing_restored"], False)
        self.assertRegex(plan["expect"], "^[a-f0-9]{64}$")
        self.assertEqual((self.store.snapshot, self.store.audit, self.layout), (before, audit, layout))
        self.assertEqual(self.store.writes, [])
        self.assertNotIn("token_row_id", plan)
        self.assertNotIn("position", plan["restore"])

    def test_verified_single_sided_card_and_last_row_removal_are_supported(self):
        self.seed(token("Treasure", "", notes="single-sided verified"))
        self.assertEqual(self.review()["restore"]["back"], "")
        self.assertEqual(self.store.snapshot.token_set("home").rows, ())

    def test_later_space_touch_and_original_id_aba_refuse(self):
        self.latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.review()
        self.latest = fixture.ROW_ID
        self.store.latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_fresh_id_restoration_or_later_removal_consumes_original_space_fence(self):
        self.latest += 2  # An INSERT at a fresh id and its later DELETE cannot revive eligibility.
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_missing_fence_is_not_assumed_latest(self):
        self.store.undo_token_latest = None
        with self.assertRaises(undo.UndoUnsupported):
            self.review()

    def test_complete_global_source_is_required_before_any_label_or_printing_lookup(self):
        self.store.audit[fixture.CHANGE_ID].append(copy.deepcopy(self.source()))
        self.store.audit[fixture.CHANGE_ID][1]["table"] = "collection_import"
        with mock.patch.object(deleted, "_verified_printing", side_effect=AssertionError("Not an owned single source")):
            with self.assertRaises(undo.UndoMissing):
                self.review()

    def test_hidden_scope_is_rejected_before_historical_fields_or_current_stock(self):
        self.source()["before"] = {"space_id": "user2", "notes": "Private source note"}
        with mock.patch.object(deleted, "_verified_printing", side_effect=AssertionError("Hidden source")):
            with self.assertRaises(undo.UndoMissing):
                self.review()
        self.store.undo_token_latest.assert_not_called()
        self.store.undo_token_positions.assert_not_called()

    def test_historical_schema_ids_position_and_exact_text_are_checked(self):
        original = copy.deepcopy(self.source())
        mutations = [lambda s: s.update(after={}), lambda s: s["before"].update(extra="secret"),
                     lambda s: s["key"].update(id=True), lambda s: s["before"].update(id=True),
                     lambda s: s["before"].update(position=True), lambda s: s["before"].update(position=-1),
                     lambda s: s["before"].update(position=2 ** 31), lambda s: s["before"].update(quantity=True),
                     lambda s: s["before"].update(notes="two\nlines"), lambda s: s["before"].update(notes="\ud800"),
                     lambda s: s["before"].update(front=" Angel"), lambda s: s["before"].update(front="A\0ngel")]
        for mutate in mutations:
            self.store.audit[fixture.CHANGE_ID] = [copy.deepcopy(original)]
            mutate(self.source())
            with self.subTest(source=self.source()), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported)):
                self.review()

    def test_unknown_pairing_printing_or_blank_reverse_refuses(self):
        for row in (token(notes="pairing unknown"), token(set=""), token(finish=""),
                    token(back="", back_collector_number="", notes="No recorded reverse verification")):
            self.seed(row)
            with self.subTest(row=row), self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_card_data_failure_changed_name_digital_or_unsupported_finish_refuses(self):
        for answer in ((dict(_cells(self.old)), ["Card cache unavailable"]),
                       ({**_cells(self.old), "front": "Different token"}, [])):
            with mock.patch.object(names, "check_names", return_value=answer), self.assertRaises(undo.UndoUnsupported):
                self.review()
        for printing in (None, {"digital": True, "games": ["paper"], "finishes": ["nonfoil"]},
                         {"digital": False, "games": ["arena"], "finishes": ["nonfoil"]},
                         {"digital": False, "games": ["paper"], "finishes": ["foil"]}):
            with mock.patch.object(cards, "printing", return_value=printing), self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_existing_id_duplicate_printing_reversed_pair_and_unknown_same_faces_refuse(self):
        candidates = [(TARGET, token(front="Other", back="", front_collector_number="9")), (80, token()),
                      (80, token("The Monarch", "Angel", front_collector_number="2", back_collector_number="1")),
                      (80, token(front_details="Different recorded traits")),
                      (80, token(set="", front_collector_number="", back_collector_number="", finish="")),
                      (80, token(back="", set="", front_collector_number="", back_collector_number="", finish="")),
                      (80, token(back="Different reverse", set="", front_collector_number="", back_collector_number="", finish=""))]
        for rid, row in candidates:
            self.seed(survivors=(model.TokenRow.make(row, id=rid),))
            with self.subTest(row=row), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_other_printing_and_unrelated_survivors_keep_ids_positions_and_allocations(self):
        survivor = model.TokenRow.make(token("Zombie", "Zombie Knight", quantity=3,
            front_collector_number="8", back_collector_number="9"), id=80)
        self.seed(survivors=(survivor,))
        self.built("1 Zombie // Zombie Knight")
        before, layout = self.store.snapshot, copy.deepcopy(self.layout)
        self.review()
        self.assertEqual(self.store.snapshot, before)
        self.assertEqual(self.layout, layout)
        self.assertEqual(self.store.snapshot.token_set("home").rows[0].id, 80)

    def test_current_layout_ambiguity_and_unreadable_or_unsorted_stock_refuse(self):
        survivor = model.TokenRow.make(token("Zombie", "Zombie Knight", front_collector_number="8",
                                              back_collector_number="9"), id=80)
        self.seed(survivors=(survivor,))
        for layout in ([], [{"id": True, "position": 1024}], [{"id": 80, "position": True}],
                       [{"id": 80, "position": -1}], [{"id": 80, "position": 2 ** 31}]):
            self.layout = layout
            with self.subTest(layout=layout), self.assertRaises(undo.UndoConflict):
                self.review()
        self.layout = [{"id": 80, "position": 1024}]
        sheet = replace(self.store.snapshot.token_set("home"), error="Private raw error")
        self.store.snapshot = self.store.snapshot.replace(tokens={"home": sheet})
        with self.assertRaises(undo.UndoConflict) as caught:
            self.review()
        self.assertNotIn("Private", str(caught.exception))

    def test_any_matching_packed_reference_refuses_without_moving_to_another_printing(self):
        survivor = model.TokenRow.make(token(front_collector_number="8", back_collector_number="9"), id=80)
        self.seed(survivors=(survivor,))
        self.built("1 Angel // The Monarch")
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_unknown_unmatched_and_duplicate_packing_is_not_zero(self):
        for packed, headers in ((None, ""), ("bad packing", ""), ("1 Angel // The Monarch", ""),
                                ("", "- **Token cards:** 1 Angel // The Monarch\n")):
            self.store.snapshot = self.store.snapshot.replace(decks={})
            self.built(packed, headers=headers)
            with self.subTest(packed=packed), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_unknown_or_matching_product_packing_refuses(self):
        for packed in ("", "1 Angel // The Monarch", "bad packing"):
            self.product(packed)
            with self.subTest(packed=packed), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_another_spaces_deck_is_not_parsed_or_named(self):
        self.built(None, space="user2", status="unknown")
        plan = self.review()
        self.assertNotIn("user2", json_text(plan))

    def test_stale_and_preview_snapshots_are_never_eligibility_evidence(self):
        original = self.store.snapshot
        for snapshot in (replace(original, stale="Old fixture"), replace(original, revision="old~preview"),
                         replace(original, revision=""), replace(original, decks_revision="")):
            self.store.snapshot = snapshot
            with self.assertRaises(undo.UndoConflict):
                self.review()

    def test_receipt_binds_facts_hash_layout_inventory_and_deck_revisions(self):
        original = self.review()["expect"]
        self.source()["before"]["notes"] = "Changed historical fixture note"
        self.assertNotEqual(self.review()["expect"], original)
        self.seed()
        self.store.snapshot = replace(self.store.snapshot, revision="other")
        self.assertNotEqual(self.review()["expect"], original)
        self.seed()
        self.store.snapshot = replace(self.store.snapshot, decks_revision="other")
        self.assertNotEqual(self.review()["expect"], original)

    def test_stock_and_holder_work_bounds_refuse_without_partial_review(self):
        survivor = model.TokenRow.make(token("Zombie", "Zombie Knight", front_collector_number="8",
                                              back_collector_number="9"), id=80)
        self.seed(survivors=(survivor,))
        with mock.patch.object(deleted, "MAX_STOCK", 0), self.assertRaises(undo.UndoConflict):
            self.review()
        self.built("")
        with mock.patch.object(deleted, "MAX_HOLDERS", 0), self.assertRaises(undo.UndoConflict):
            self.review()
        with mock.patch.object(deleted, "MAX_DECK_TEXT", 1), self.assertRaises(undo.UndoConflict):
            self.review()
        self.store.snapshot = self.store.snapshot.replace(decks={})
        self.built("1 Zombie // Zombie Knight")
        with mock.patch.object(deleted, "MAX_MATCHES", 0), self.assertRaises(undo.UndoConflict):
            self.review()

def _cells(row):
    return {**row, "quantity": str(row["quantity"])}


def json_text(value):
    import json
    return json.dumps(value, sort_keys=True)
