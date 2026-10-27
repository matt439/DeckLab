"""Token INSERT Undo preserves physical-card quantities, stable IDs and packed holders.

Every audit row, SQL layout and inventory snapshot is an explicit isolated test
double. No database, household records, process inspection or network is used.
"""
import copy
from dataclasses import replace
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import model, rules, undo
from decklab.lib.state import Invalid
from decklab.lib.tokens import ops as token_ops
from decklab.tests import test_activity_undo_api as fixture


REASON = "Correct an accidental token-card addition."
TARGET_ID = 7


def token(front="Angel", back="The Monarch", quantity=2, **extra):
    return {**{field: "" for field in rules.TOKEN_FIELDS}, "front": front, "back": back,
            "quantity": quantity, "notes": "Paired faces verified", **extra}


class TokenInsertUndoTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ActivityUndoApiTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store = self.case.backend
        self.products = self.store.snapshot.products
        self.store.snapshot = self.store.snapshot.replace(decks={}, products=(),
            status=model.Sheet("magic/products/status.csv", tuple(rules.STATUS_FIELDS), (), True))
        self.store.undo_token_positions = lambda space: copy.deepcopy(self.layout if space == self.space else [])
        self.seed()

    def seed(self, row=None, extra=(), positions=None, *, space="home"):
        self.space = space
        current = copy.deepcopy(token() if row is None else row)
        rows = [model.TokenRow.make(current, id=TARGET_ID), *extra]
        self.store.snapshot = self.store.snapshot.with_tokens(space, rows)
        self.layout = [{"id": stored.id, "position": (index + 1) * 100 if positions is None else positions[stored.id]}
                       for index, stored in enumerate(self.store.snapshot.token_set(space).rows)]
        position = next(row["position"] for row in self.layout if row["id"] == TARGET_ID)
        raw = {"set_code" if key == "set" else key: value for key, value in current.items()}
        raw.update(space_id=space, id=TARGET_ID, position=position)
        self.store.audit[fixture.CHANGE_ID] = [{"id": fixture.ROW_ID, "table": undo.TOKENS, "op": "INSERT",
            "key": {"id": TARGET_ID}, "before": None, "after": raw}]
        self.store.latest = fixture.ROW_ID
        return current

    def source(self):
        return self.store.audit[fixture.CHANGE_ID][0]

    def review(self):
        return inventory.undo_review(fixture.CHANGE_ID, self.space, self.store.snapshot)

    def apply(self, plan=None, **extra):
        plan = self.review() if plan is None else plan
        return inventory.Op("inventory.undo", {"change_id": fixture.CHANGE_ID, "space": self.space,
            "expect": plan["expect"], "reason": REASON, **extra}).run(self.store.snapshot)

    def built(self, slug="fixture", packed="", *, headers="", status="built"):
        line = "" if packed is None else "- **Token cards:** " + packed + "\n"
        text = "# Token holder fixture\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** " + status + "\n" \
            + line + headers + "\n## Decklist\n\n```\nDeck\n1 Llanowar Elves\n59 Forest\n```\n"
        self.store.snapshot = self.store.snapshot.with_deck(model.Deck("home", "casual", slug, text))

    def product(self, packed):
        product = next(item for item in self.products if item.file == "fdn-beginner-box.csv")
        row = model.StatusRow.make({"file": product.file, "status": "owned", "intact": "yes", "token_cards": packed})
        self.store.snapshot = self.store.snapshot.replace(products=(product,),
            status=model.Sheet("magic/products/status.csv", tuple(rules.STATUS_FIELDS), (row,), True))

    @staticmethod
    def stock(snapshot):
        return [(row.id, row.as_dict()) for row in snapshot.token_set("home").rows]

    def test_review_uses_the_exact_inserted_stable_id_and_full_row(self):
        original, snapshot = copy.deepcopy(self.store.audit), self.store.snapshot
        plan = self.review()
        self.assertEqual((plan["action"], plan["kind"], plan["token_row_id"]), ("remove", "tokens", TARGET_ID))
        self.assertTrue(plan["reason_required"])
        self.assertEqual(plan["current"], token())
        self.assertIsNone(plan["restore"])
        self.assertEqual(plan["key"], {"id": TARGET_ID})
        self.assertEqual(self.store.snapshot, snapshot)
        self.assertEqual(self.store.audit, original)

    def test_a_paired_physical_row_is_removed_once_and_other_ids_and_facts_survive(self):
        survivor = model.TokenRow.make(token("Zombie", "Zombie Knight", 3), id=8)
        self.seed(extra=(survivor,))
        before, original = self.store.snapshot, copy.deepcopy(self.store.audit)
        plan = self.review()
        after, summary = self.apply(plan)
        self.assertEqual(self.stock(after), [(8, survivor.as_dict())])
        self.assertEqual(summary.counts["cards"], 3)  # Remaining physical cards, not faces or removed quantity.
        self.assertEqual(sum(row.qty for row in before.token_set("home").rows)
                         - sum(row.qty for row in after.token_set("home").rows), 2)
        self.assertIsNone(undo.restored_row(after, plan))
        self.assertEqual(summary.counts["undo"], 1)
        self.assertEqual(self.store.audit, original)
        self.assertEqual(self.stock(self.store.snapshot), self.stock(before))

    def test_last_row_can_be_removed_with_an_explicit_zero_token_holder(self):
        self.built(packed="")
        plan = self.review()
        after, summary = self.apply(plan)
        self.assertEqual(after.token_set("home").rows, ())
        self.assertEqual(summary.counts["cards"], 0)
        self.assertIsNone(undo.restored_row(after, plan))

    def test_verified_single_sided_row_can_be_removed_without_inventing_a_reverse(self):
        row = self.seed(token("Treasure", "", 2, notes="single-sided verified; printing unconfirmed"))
        plan = self.review()
        self.assertEqual(plan["current"], row)
        after, _ = self.apply(plan)
        self.assertEqual(after.token_set("home").rows, ())

    def test_unknown_pairing_or_unverified_blank_reverse_is_outside_the_slice(self):
        for row in (token("Treasure", "", 2, notes="printing unconfirmed"),
                    token(notes="reverse face unconfirmed"), token(notes="pairing unknown")):
            self.seed(row)
            with self.subTest(notes=row["notes"]), self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                self.review()

    def test_index_shift_preserves_another_decks_exact_stable_id_hold(self):
        survivor = model.TokenRow.make(token("Zombie", "Zombie Knight", 3), id=8)
        self.seed(extra=(survivor,))
        self.built(packed="1 Zombie // Zombie Knight")
        plan = self.review()
        after, _ = self.apply(plan)
        self.assertEqual(self.stock(after), [(8, survivor.as_dict())])
        self.assertEqual(after.deck("casual/fixture"), self.store.snapshot.deck("casual/fixture"))

    def test_intact_product_hold_on_a_survivor_remains_unchanged_after_index_shift(self):
        survivor = model.TokenRow.make(token("Zombie", "Zombie Knight", 3), id=8)
        self.seed(extra=(survivor,))
        self.product("1 Zombie // Zombie Knight")
        plan = self.review()
        after, _ = self.apply(plan)
        self.assertEqual(self.stock(after), [(8, survivor.as_dict())])
        self.assertEqual(after.status, self.store.snapshot.status)

    def test_target_hold_cannot_be_reallocated_to_an_alternative_printing(self):
        alternative = model.TokenRow.make(token(set="tst", front_collector_number="9", finish="nonfoil", quantity=4), id=8)
        self.seed(extra=(alternative,))
        self.built(packed="1 Angel // The Monarch")
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_unknown_missing_duplicate_or_invalid_packed_lines_are_not_zero_holds(self):
        for packed, headers in ((None, ""), ("not a packing line", ""),
                                ("", "- **Token cards:** 1 Angel // The Monarch\n")):
            self.store.snapshot = self.store.snapshot.replace(decks={})
            self.built(packed=packed, headers=headers)
            with self.subTest(packed=packed), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_unknown_or_ambiguous_built_status_cannot_hide_a_participant(self):
        for status, headers in (("unknown", ""), ("built", "- **Status:** idea\n")):
            self.store.snapshot = self.store.snapshot.replace(decks={})
            self.built(status=status, headers=headers)
            with self.subTest(status=status), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_blank_intact_product_packing_remains_unknown(self):
        self.product("")
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_unmatched_or_overcommitted_other_holders_refuse_even_when_target_is_unheld(self):
        survivor = model.TokenRow.make(token("Zombie", "Zombie Knight", 1), id=8)
        self.seed(extra=(survivor,))
        for packed in ("1 Treasure", "2 Zombie // Zombie Knight"):
            self.store.snapshot = self.store.snapshot.replace(decks={})
            self.built(packed=packed)
            with self.subTest(packed=packed), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_duplicate_full_values_or_physical_identity_are_not_selected_by_first_match(self):
        for extra in (token(), token(quantity=3, notes="A separately recorded matching row")):
            self.seed(extra=(model.TokenRow.make(extra, id=8),))
            with self.subTest(extra=extra), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_layout_gaps_are_valid_but_duplicate_or_decreasing_positions_are_not(self):
        survivor = model.TokenRow.make(token("Zombie", "Zombie Knight", 3), id=8)
        self.seed(extra=(survivor,), positions={TARGET_ID: 100, 8: 90000})
        self.assertEqual(self.review()["token_row_id"], TARGET_ID)
        for positions in ((100, 100), (100, 50)):
            self.layout = [{"id": TARGET_ID, "position": positions[0]}, {"id": 8, "position": positions[1]}]
            with self.subTest(positions=positions), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_sql_layout_must_cover_unique_positive_current_ids_and_the_original_target_position(self):
        layouts = [[], [{"id": TARGET_ID, "position": 101}],
                   [{"id": TARGET_ID, "position": 100}, {"id": TARGET_ID, "position": 200}],
                   [{"id": 0, "position": 100}], [{"id": True, "position": 100}],
                   [{"id": TARGET_ID, "position": -1}], [{"id": TARGET_ID, "position": True}]]
        for layout in layouts:
            self.layout = layout
            with self.subTest(layout=layout), self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                self.review()

    def test_current_token_ids_cannot_be_zero_or_duplicated(self):
        for rows in ([model.TokenRow.make(token(), id=0)],
                     [model.TokenRow.make(token(), id=TARGET_ID),
                      model.TokenRow.make(token("Zombie", "Zombie Knight", 3), id=TARGET_ID)]):
            self.store.snapshot = self.store.snapshot.with_tokens("home", rows)
            with self.subTest(ids=[row.id for row in rows]), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_unsorted_stock_is_not_silently_reordered_during_undo(self):
        sheet = replace(self.store.snapshot.token_set("home"), sorted=False)
        self.store.snapshot = self.store.snapshot.replace(tokens={"home": sheet})
        with self.assertRaises(undo.UndoConflict):
            self.review()

    def test_reason_latest_audit_and_both_revision_guards_remain_required(self):
        plan = self.review()
        for reason in (None, "", "  ", 1, "x" * 201):
            with self.subTest(reason=repr(reason)), self.assertRaises(Invalid):
                self.apply(plan, reason=reason)
        self.store.latest += 1
        with self.assertRaises(undo.UndoConflict):
            self.apply(plan)
        self.store.latest = fixture.ROW_ID
        for field in ("revision", "decks_revision"):
            before = self.store.snapshot
            self.store.snapshot = before.replace(**{field: "later"})
            with self.subTest(field=field), self.assertRaises(undo.UndoConflict):
                self.apply(plan)
            self.store.snapshot = before

    def test_source_schema_stable_id_position_and_full_current_values_are_exact(self):
        for mode in ("extra-field", "bad-key", "bad-id", "bad-position", "changed-row"):
            self.seed()
            if mode == "extra-field":
                self.source()["after"]["future_field"] = "Unconfirmed"
            elif mode == "bad-key":
                self.source()["key"]["id"] = 8
            elif mode == "bad-id":
                self.source()["after"]["id"] = True
            elif mode == "bad-position":
                self.source()["after"]["position"] = True
            else:
                changed = model.TokenRow.make(token(notes="Changed after insertion"), id=TARGET_ID)
                self.store.snapshot = self.store.snapshot.with_tokens("home", [changed])
            with self.subTest(mode=mode), self.assertRaises((undo.UndoUnsupported, undo.UndoConflict)):
                self.review()

    def test_hidden_and_mixed_insert_sources_remain_generic_before_layout_inspection(self):
        for mode in ("hidden", "mixed"):
            self.seed()
            if mode == "hidden":
                self.source()["after"]["space_id"] = "user2"
            else:
                self.store.audit[fixture.CHANGE_ID].append({"table": "profile_email", "before": None,
                                                           "after": {"email": "hidden@example.com"}})
            with self.subTest(mode=mode), \
                    mock.patch.object(self.store, "undo_token_positions", side_effect=AssertionError("hidden layout read")), \
                    self.assertRaises(undo.UndoMissing) as caught:
                self.review()
            self.assertEqual(str(caught.exception), "That change is not available to undo.")

    def test_survivor_id_changes_cannot_hide_behind_dataclass_equality(self):
        survivor = model.TokenRow.make(token("Zombie", "Zombie Knight", 3), id=8)
        self.seed(extra=(survivor,))
        remove = token_ops.remove
        def changed(*args, **kwargs):
            after, summary = remove(*args, **kwargs)
            rows = [replace(row, id=999) for row in after.token_set("home").rows]
            return after.with_tokens("home", rows), summary
        with mock.patch.object(token_ops, "remove", side_effect=changed), self.assertRaises(undo.UndoConflict):
            self.review()
