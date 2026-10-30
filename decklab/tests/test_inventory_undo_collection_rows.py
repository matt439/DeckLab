"""The transaction-local proof of a collection-row batch Undo, over isolated audit fixtures.

confirm() gets the audit rows and reason a PostgreSQL transaction would read; here they are
built from the reviewed source, then tampered with one fact at a time. No database, real
household data, network or process is used.
"""
import copy
import unittest
from unittest import mock

from decklab.lib import cards, inventory
from decklab.lib.inventory import Summary, rules, undo, undo_collection_rows as proof
from decklab.tests import test_activity_undo_api as fixture
from decklab.tests import test_inventory_undo_batch_delete as delete_fixture
from decklab.tests import test_inventory_undo_batch_insert as insert_fixture

REASON = insert_fixture.REASON


def _audit(source, op, *, location=None):
    """The audit rows the inverse of source writes: DELETE of each added row, INSERT of each deleted one."""
    rows = []
    for index, record in enumerate(source):
        image = copy.deepcopy(record["after"] if op == "DELETE" else record["before"])
        if location is not None:
            image["location"] = location
        rows.append({"id": 900 + index, "table": undo.COLLECTION, "op": op, "key": copy.deepcopy(record["key"]),
                     "before": image if op == "DELETE" else None, "after": None if op == "DELETE" else image})
    return rows


class _Case:
    fixture_class = None
    op = None
    reason = None

    def setUp(self):
        self.case = self.fixture_class()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.before = self.case.store.snapshot
        self.after, self.summary = self.case.apply()
        self.actual = _audit(self.case.source(), self.op)

    def confirm(self, actual=None, saved=None, reason="default", summary=None):
        return proof.confirm(self.before, self.after if saved is None else saved, summary or self.summary,
                             self.actual if actual is None else actual, self.reason if reason == "default" else reason)

    def refused(self, **kwargs):
        with self.assertRaises(undo.UndoConflict) as caught:
            self.confirm(**kwargs)
        self.assertEqual(str(caught.exception), proof.UNCONFIRMED)
        return caught.exception

    def test_the_reviewed_effect_is_confirmed_and_the_proof_dropped(self):
        self.assertTrue(proof.restoring(self.summary))
        confirmed = self.confirm()
        self.assertNotIn(proof.PROOF, confirmed.extra)
        self.assertEqual(confirmed.extra, {k: v for k, v in self.summary.extra.items() if k != proof.PROOF})
        self.assertEqual((confirmed.text, confirmed.counts, confirmed.changed),
                         (self.summary.text, self.summary.counts, self.summary.changed))
        self.assertIn(proof.PROOF, self.summary.extra)  # the summary itself isn't changed

    def test_audit_rows_must_be_exactly_the_reviewed_ones(self):
        extra = copy.deepcopy(self.actual[0])
        extra["id"] = 999
        cases = {"one more": [*self.actual, extra], "one fewer": self.actual[:1], "none": [],
                 "repeated": [self.actual[0], self.actual[0]], "not a list": None}
        for name, actual in cases.items():
            with self.subTest(name):
                self.refused(actual=actual if actual is not None else "rows")

    def test_each_audit_row_must_be_this_space_and_tables_op_and_recorded_facts(self):
        def changed(edit):
            rows = copy.deepcopy(self.actual)
            edit(rows[1])
            return rows
        image = "before" if self.op == "DELETE" else "after"
        other = "INSERT" if self.op == "DELETE" else "DELETE"
        edits = {
            "other table": lambda row: row.update(table=undo.TOKENS),
            "other op": lambda row: row.update(op=other),
            "update": lambda row: row.update(op="UPDATE", before=row[image], after=row[image]),
            "other space": lambda row: row[image].update(space_id="user2"),
            "key differs": lambda row: row["key"].update(collector_number="1"),
            "quantity": lambda row: row[image].update(quantity=row[image]["quantity"] + 1),
            "notes": lambda row: row[image].update(notes="changed"),
            "condition": lambda row: row[image].update(condition="HP"),
            "extra column": lambda row: row[image].update(id=7),
            "missing image": lambda row: row.update({image: None}),
        }
        for name, edit in edits.items():
            with self.subTest(name):
                self.refused(actual=changed(edit))

    def test_the_saved_collection_and_every_other_part_must_be_as_reviewed(self):
        home = [row.as_dict() for row in self.after.collection("home").rows]
        stray = {**fixture.CARD, "collector_number": "777", "quantity": 1}
        cases = {
            "another home row": self.after.with_collection("home", [*home, stray]),
            "another space": self.after.with_collection("user2", [stray]),
            "token cards": self.after.with_tokens("home", [{**fixture.TOKEN}]),
            "decks revision": self.after.replace(decks_revision=self.after.decks_revision + "x"),
        }
        for name, saved in cases.items():
            with self.subTest(name):
                self.refused(saved=saved)

    def test_an_unavailable_database_is_not_reported_as_unconfirmed(self):
        with mock.patch.object(proof, "_remaining_collection", side_effect=inventory.Unavailable("gone")),                 self.assertRaises(inventory.Unavailable):
            self.confirm()

    def test_other_summaries_are_not_this_proofs(self):
        extra = {k: v for k, v in self.summary.extra.items() if k != proof.PROOF}
        for summary in (Summary("x"), Summary("x", {}, {}, extra),
                        Summary("x", {}, {}, {**self.summary.extra, "action": "batch_update"}),
                        Summary("x", {}, {}, {**self.summary.extra, "kind": "tokens"})):
            with self.subTest(summary.extra):
                self.assertFalse(proof.restoring(summary))


class RestoredRowsProofTests(_Case, unittest.TestCase):
    """batch_add: a complete DELETE source restored as INSERTs."""
    fixture_class = delete_fixture.BatchDeleteUndoTests
    op = "INSERT"
    reason = None

    def test_a_restored_row_never_gains_a_location_and_no_reason_is_recorded(self):
        self.confirm(actual=_audit(self.case.source(), "INSERT", location=""))
        self.refused(actual=_audit(self.case.source(), "INSERT", location="Row 2, B"))
        self.refused(reason=REASON)

    def test_fifty_rows_confirm(self):
        self.case.seed(50)
        catalog = {(record["before"]["set_code"], record["before"]["collector_number"]):
                   {"name": record["before"]["name"], "digital": False, "games": ["paper"], "finishes": ["nonfoil"]}
                   for record in self.case.source()}
        with mock.patch.object(cards, "printing", side_effect=lambda s, n: catalog.get((s, n))), \
                mock.patch.object(cards, "printing_card", side_effect=lambda s, n: catalog.get((s, n))):
            self.before = self.case.store.snapshot
            self.after, self.summary = self.case.apply()
        self.assertEqual(self.summary.extra["row_count"], 50)
        self.confirm(actual=_audit(self.case.source(), "INSERT"))
        self.refused(actual=_audit(self.case.source(), "INSERT")[:49])


class RemovedRowsProofTests(_Case, unittest.TestCase):
    """batch_remove: a complete INSERT source removed again as DELETEs."""
    fixture_class = insert_fixture.BatchInsertUndoTests
    op = "DELETE"
    reason = REASON

    def test_the_reviewed_reason_must_be_the_recorded_one(self):
        for reason in (None, "", REASON + ".", "Another reason"):
            with self.subTest(reason=reason):
                self.refused(reason=reason)

    def test_survivors_keep_their_rows_and_storage_locations(self):
        extra = self.case.extra_stock()
        key = rules.ident(extra)
        self.before = self.case.store.snapshot.with_locations("home", {key: "Binder"})
        self.case.store.snapshot = self.before
        self.after, self.summary = self.case.apply()
        self.assertEqual(self.after.locations_of("home"), {key: "Binder"})
        self.confirm()
        # A removed row's recorded location goes with it; the audit image keeps the column.
        self.confirm(actual=_audit(self.case.source(), "DELETE", location="Row 1"))
        self.refused(saved=self.after.with_locations("home", {}))
        self.refused(saved=self.after.with_locations("home", {key: "Row 9"}))
        survivors = [row.as_dict() for row in self.after.collection("home").rows]
        self.refused(saved=self.after.with_collection("home", [{**survivors[0], "quantity": 99}]))


if __name__ == "__main__":
    unittest.main()
