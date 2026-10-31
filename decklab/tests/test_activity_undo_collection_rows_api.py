"""Activity's collection-row batch Undo through a store that proves the effect before commit.

The test store runs the same transaction-local proof PostgreSQL runs (undo_collection_rows),
over audit rows built from the reviewed source; a tampered proof leaves nothing saved. No
database, real household data, network or process is used.
"""
import copy
import json
import unittest

from decklab.lib.api import activity_undo
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import changes, undo_collection_rows as proof
from decklab.tests import test_activity_undo_api as original
from decklab.tests import test_inventory_undo_batch_delete as delete_fixture
from decklab.tests import test_inventory_undo_batch_insert as insert_fixture
from decklab.tests.test_inventory_undo_collection_rows import _audit


class _ProvingStore:
    """Wraps the fixture store's apply with the proof, rolling back (keeping the snapshot) on refusal."""

    def __init__(self, store, op, tamper=None):
        self.store, self.op, self.tamper, self.calls = store, op, tamper, []
        self.original = store.apply
        store.apply = self.apply

    def apply(self, op, actor, message, reason=None, expected_revision=None):
        before = self.store.snapshot
        after, summary = op.run(changes.detach(before))
        after = changes.prepare(before, after, revision=before.revision + "-undo")
        actual = _audit(self.store.audit[original.CHANGE_ID], self.op)
        if self.tamper:
            actual = self.tamper(actual)
        self.calls.append(proof.restoring(summary))
        summary = proof.confirm(before, after, summary, actual, reason)
        self.store.snapshot = after
        self.store.writes.append((op, actor, message, summary))
        return after, summary


class _Api:
    fixture_class = None
    op = None
    body = None

    def setUp(self):
        self.case = self.fixture_class()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.backend = self.case.store

    def save(self, tamper=None):
        store = _ProvingStore(self.backend, self.op, tamper)
        preview = activity_undo.undo_view(id=str(original.CHANGE_ID))
        return store, activity_undo.apply_undo(json.dumps({"profile": "matt", "id": original.CHANGE_ID,
                                                          "expect": preview["expect"], **self.body}).encode())

    def test_a_proved_save_answers_as_before_and_drops_the_proof(self):
        store, result = self.save()
        self.assertEqual(store.calls, [True])
        self.assertIs(result["saved"], True)
        self.assertEqual(result["row_count"], 2)
        self.assertNotIn(proof.PROOF, self.backend.writes[-1][3].extra)

    def test_a_tampered_proof_saves_nothing_and_names_no_card(self):
        snapshot, audit = self.backend.snapshot, copy.deepcopy(self.backend.audit)
        for name, tamper in {"one fewer": lambda rows: rows[:1],
                             "changed quantity": lambda rows: [rows[0], {**rows[1], self.image: {
                                 **rows[1][self.image], "quantity": rows[1][self.image]["quantity"] + 1}}]}.items():
            with self.subTest(name), self.assertRaises(ApiError) as caught:
                self.save(tamper)
            self.assertEqual(caught.exception.status, 409)
            self.assertNotIn("Llanowar", caught.exception.message)
            self.assertEqual(self.backend.writes, [])
            self.assertEqual(self.backend.snapshot, snapshot)
            self.assertEqual(self.backend.audit, audit)


class RestoreRowsApiTests(_Api, unittest.TestCase):
    fixture_class = delete_fixture.BatchDeleteUndoTests
    op, image = "INSERT", "after"
    body = {"confirm_owned": True}


class RemoveRowsApiTests(_Api, unittest.TestCase):
    fixture_class = insert_fixture.BatchInsertUndoTests
    op, image = "DELETE", "before"
    body = {"reason": insert_fixture.REASON}


if __name__ == "__main__":
    unittest.main()
