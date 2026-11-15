"""Actual inventory/audit batch integration; dedicated isolated PostgreSQL runner only."""
import copy
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from decklab.lib.state import Actor, Conflict, Invalid
from decklab.lib.state import pg_collection_batches as batches

CONNECT = None
RESTART = None
PREPARE = None
VALUE = {"label": "A physical pile", "rows": [{"name": "Llanowar Elves", "set": "fdn",
         "collector_number": "227", "finish": "nonfoil", "condition": "NM", "language": "en", "quantity": 3}],
         "unresolved": []}


class InventoryFixture:
    """Fresh migrated database and fixture card/config scope for dedicated proofs."""
    @classmethod
    def setUpClass(cls):
        if CONNECT is None:
            raise unittest.SkipTest("requires isolated batch inventory PostgreSQL runner")

    def setUp(self):
        from psycopg import sql

        from decklab.db import conn as db
        from decklab.lib.inventory import pg
        from decklab.tests.test_inventory_contract import fixture_world
        self.dbname = "batch_inventory_" + uuid.uuid4().hex[:10]
        with CONNECT("super", "postgres", autocommit=True) as c:
            c.execute(sql.SQL("create database {} owner decklab_owner").format(sql.Identifier(self.dbname)))
        self.addCleanup(self.drop)
        PREPARE(self.dbname)
        self.enterContext(mock.patch.object(db, "connect", side_effect=self.connection))
        self.enterContext(fixture_world())
        self.backend = pg.PgInventory(dbname=self.dbname)
        self.bid = str(uuid.uuid4())
        self.profile, self.space = "user1", "home"
        self.call(batches.create, VALUE)

    def drop(self):
        from psycopg import sql
        with CONNECT("super", "postgres", autocommit=True) as c:
            c.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(self.dbname)))

    def connection(self, role="app", dbname=None, **kwargs):
        if dbname not in (None, self.dbname):
            raise AssertionError("unexpected database target")
        return CONNECT(role, self.dbname, **kwargs)

    def call(self, fn, *args):
        with self.connection() as c, c.cursor() as cur:
            cur.execute("select 1")
            return fn(cur, self.profile, self.space, self.bid, *args)

    def complete(self, token, backend=None, actor=None):
        from decklab.lib.inventory.batch_import import BatchImport
        return (backend or self.backend).apply(BatchImport(self.space, self.bid, token),
                actor or Actor(self.profile, "Fixture user", "home"), "Add a reviewed collection batch")

    def counts(self):
        with self.connection("ro") as c:
            return tuple(c.execute(query).fetchone()[0] for query in (
                "select coalesce(sum(quantity),0) from collection_card",
                "select count(*) from collection_import", "select count(*) from collection_import_content",
                "select count(*) from audit.change_set", "select count(*) from audit.row_change"))



class InventoryBatchTests(InventoryFixture, unittest.TestCase):
    def test_real_inventory_raw_source_and_audit_once_after_lost_response(self):
        token, before = self.call(batches.review, 1), self.counts()
        saved, summary = self.complete(token)
        first = self.counts()
        self.assertEqual(first[:3], (3, 1, 1))
        self.assertEqual(first[3], before[3] + 1)
        self.assertGreater(first[4], before[4])
        with self.connection("ro") as c:
            change_id = summary.extra["collection_batch"]["result"]["change_set"]
            audited = {row[0] for row in c.execute(
                "select table_name from audit.row_change where change_set_id=%s", (change_id,))}
            self.assertTrue({"collection_card", "collection_import"} <= audited)
            raw = bytes(c.execute("select content from collection_import_content").fetchone()[0]).decode()
            self.assertIn("Llanowar Elves", raw)
            self.assertIn("fdn,227,nonfoil,3", raw)
        RESTART()  # force WAL recovery with actual inventory/import/audit/receipt rows
        from decklab.lib.inventory.pg import PgInventory
        again, retry = self.complete(token, PgInventory(dbname=self.dbname))
        self.assertEqual(self.counts(), first)
        self.assertEqual(summary.extra["collection_batch"], retry.extra["collection_batch"])
        self.assertEqual(saved.revision, again.revision)
        self.assertEqual(retry.changed, {})

    def test_concurrent_completion_same_receipt_one_audit_change(self):
        from decklab.lib.inventory.pg import PgInventory
        token, before, barrier = self.call(batches.review, 1), self.counts(), threading.Barrier(2)
        def worker():
            backend = PgInventory(dbname=self.dbname)
            barrier.wait(timeout=5)
            return self.complete(token, backend)[1].extra["collection_batch"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(worker) for _ in range(2)]
            results = [j.result(timeout=15) for j in jobs]
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.counts()[:4], (3, 1, 1, before[3] + 1))

    def test_conflicting_retry_no_audit_or_inventory_changes(self):
        token = self.call(batches.review, 1)
        self.complete(token)
        before = self.counts()
        token["nonce"] = str(uuid.uuid4())
        with self.assertRaises(Conflict):
            self.complete(token)
        self.assertEqual(before, self.counts())

    def test_receipt_failure_rolls_back_real_inventory_import_audit(self):
        from decklab.lib.inventory import batch_import
        token, before = self.call(batches.review, 1), self.counts()
        with mock.patch.object(batch_import.batches, "finish", side_effect=Invalid("injected receipt failure")), self.assertRaises(Invalid):
            self.complete(token)
        self.assertEqual(before, self.counts())
        self.assertEqual(self.call(batches.read)["status"], "draft")
        # Same backend and token: no poisoned provisional cache may survive rollback.
        saved, _ = self.complete(token)
        self.assertEqual(self.counts()[:3], (3, 1, 1))
        self.assertEqual(int(saved.collection("home").rows[0].text("quantity")), 3)

    def test_failure_after_receipt_sql_rolls_back_receipt_too(self):
        from decklab.lib.inventory import batch_import
        token, before = self.call(batches.review, 1), self.counts()
        real = batch_import.finish
        def fail(*args):
            real(*args)
            raise Invalid("failure after receipt statement")
        with mock.patch.object(batch_import, "finish", side_effect=fail), self.assertRaises(Invalid):
            self.complete(token)
        self.assertEqual(before, self.counts())
        self.assertEqual(self.call(batches.read)["status"], "draft")
        self.complete(token)
        self.assertEqual(self.counts()[:3], (3, 1, 1))

    def test_fresh_review_after_unrelated_inventory_write(self):
        from decklab.lib.inventory import Op
        row = {**VALUE["rows"][0], "quantity": "1", "notes": ""}
        token = self.call(batches.review, 1)
        self.backend.apply(Op("collection.import", {"space": "home", "sources": [("fixture", [row])]}),
                           Actor("user1", "Fixture user", "home"), "Add another card")
        before = self.counts()
        with self.assertRaises(Conflict):
            self.complete(token)
        self.assertEqual(before, self.counts())
        self.complete(self.call(batches.review, 1))
        self.assertEqual(self.counts()[:3], (4, 1, 1))

    def test_invalid_printing_does_not_import(self):
        value = copy.deepcopy(VALUE)
        value["rows"][0]["collector_number"] = "999999"
        self.call(batches.save, 1, value)
        before = self.counts()
        with self.assertRaises(Invalid):
            self.complete(self.call(batches.review, 2))
        self.assertEqual(before, self.counts())

    def test_another_household_actor_cannot_complete(self):
        token, before = self.call(batches.review, 1), self.counts()
        with self.assertRaises(Invalid):
            self.complete(token, actor=Actor("matt", "Matt", "home"))
        self.assertEqual(before, self.counts())

    def test_member_fingerprint_privacy_removal_and_late_retry(self):
        from decklab.db import conn as db
        from decklab.db import space_apply, space_export, space_remove
        self.profile = self.space = "user2"
        self.bid = str(uuid.uuid4())
        with self.connection("owner") as c:
            original_files, original_sha = space_export.snapshot(c, "user2")
        self.call(batches.create, VALUE)
        token = self.call(batches.review, 1)
        with self.connection("owner") as c:
            files, sha, data = space_export.snapshot(c, "user2", details=True)
            personal, _ = space_export.snapshot(c, "user2", personal=True)
        self.assertEqual(files, original_files)
        self.assertNotEqual(sha, original_sha)
        self.assertIn("collection_batches", data)
        self.assertFalse(any(b"A physical pile" in value for value in personal.values()))
        rows, _ = space_remove.row_plan("user2", data)
        self.assertIn("collection_batch", {r["table"] for r in rows})
        with self.connection("owner", autocommit=True) as c, db.change(
                "system", "cli", "Fixture member removal", conn=c) as (cur, change_id):
            space_apply._locks(c)
            space_apply._mutate(cur, data, rows, "system", str(uuid.uuid4()), change_id)
        with self.connection("ro") as c:
            self.assertEqual(c.execute("select count(*) from collection_batch where space_id='user2'").fetchone(), (0,))
        before = self.counts()
        with self.assertRaises(Invalid):
            self.complete(token)
        self.assertEqual(before, self.counts())

    def test_queued_completion_cannot_cross_member_removal(self):
        from decklab.db import conn as db
        from decklab.db import space_apply, space_export, space_remove
        self.profile = self.space = "user2"
        self.bid = str(uuid.uuid4())
        self.call(batches.create, VALUE)
        token = self.call(batches.review, 1)
        # Commit once first so this also proves a queued receipt replay cannot survive removal.
        self.complete(token)
        started = threading.Event()
        def worker():
            started.set()
            with self.assertRaises(Invalid):
                self.complete(token)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.connection("owner", autocommit=True) as c, db.change(
                    "system", "cli", "Fixture member removal", conn=c) as (cur, change_id):
                space_apply._locks(c)
                _, _, data = space_export.snapshot(c, "user2", details=True)
                rows, _ = space_remove.row_plan("user2", data)
                job = pool.submit(worker)
                self.assertTrue(started.wait(5))
                space_apply._mutate(cur, data, rows, "system", str(uuid.uuid4()), change_id)
            job.result(timeout=10)
        self.assertEqual(self.counts()[:3], (0, 0, 0))
        with self.connection("ro") as c:
            self.assertEqual(c.execute("select count(*) from collection_batch where space_id='user2'").fetchone(), (0,))

    def test_claim_cannot_finalize_on_a_later_transaction(self):
        token = self.call(batches.review, 1)
        with self.connection(autocommit=True) as c:
            with c.transaction(), c.cursor() as cur:
                pending, _ = batches.claim(cur, self.profile, self.space, self.bid, token)
            with c.transaction(), c.cursor() as cur, self.assertRaises(Invalid):
                batches.finish(cur, pending, {"cards": 3})
        self.assertEqual(self.call(batches.read)["status"], "draft")

    def test_identical_new_physical_pile_adds_once_more(self):
        before = self.counts()
        self.complete(self.call(batches.review, 1))
        self.bid = str(uuid.uuid4())
        self.call(batches.create, VALUE)
        self.complete(self.call(batches.review, 1))
        self.assertEqual(self.counts()[:4], (6, 2, 2, before[3] + 2))

    def test_metadata_groups_preserve_raw_facts_and_existing_merge_under_concurrent_retry(self):
        import io

        from decklab.lib.inventory import rules
        from decklab.lib.inventory.pg import PgInventory
        value = copy.deepcopy(VALUE)
        base = value["rows"][0]
        value["rows"] = [{**base, "quantity": qty, "condition": condition, "language": language}
                         for qty, condition, language in ((2, "NM", "en"), (1, "LP", "ja"), (3, "", ""))]
        self.call(batches.save, 1, value)
        self.assertEqual(self.call(batches.read)["content"], value)
        duplicate = copy.deepcopy(value)
        duplicate["rows"].append(copy.deepcopy(value["rows"][-1]))
        with self.assertRaises(Invalid):
            self.call(batches.save, 2, duplicate)
        self.assertEqual(self.call(batches.read)["content"], value)
        token, before, barrier = self.call(batches.review, 2), self.counts(), threading.Barrier(2)
        def worker():
            barrier.wait(timeout=5)
            return self.complete(token, PgInventory(dbname=self.dbname))[1].extra["collection_batch"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(worker) for _ in range(2)]
            receipts = [job.result(timeout=15) for job in jobs]
        self.assertEqual(receipts[0], receipts[1])
        with self.connection("ro") as c:
            result = c.execute("select quantity, condition, language, notes from collection_card").fetchone()
            raw = bytes(c.execute("select content from collection_import_content").fetchone()[0]).decode()
        parsed = rules.parse_cards(io.StringIO(raw), "fixture scan source")
        self.assertEqual([(row["quantity"], row["condition"], row["language"]) for row in parsed],
                         [("2", "NM", "en"), ("1", "LP", "ja"), ("3", "", "")])
        expected, _ = rules.merge_rows([], [("existing scan/import transformation", parsed)])
        self.assertEqual(result, (6, expected[0]["condition"], expected[0]["language"], expected[0]["notes"]))
        self.assertEqual(result[1:3], ("", ""))
        self.assertIn("condition 2 NM, 1 LP, 3 not recorded", result[3])
        self.assertIn("language 2 en, 1 ja, 3 not recorded", result[3])
        completed = self.counts()
        self.assertEqual(completed[:4], (6, 1, 1, before[3] + 1))
        # A lost receipt can be fetched again by a fresh backend without second effects.
        self.assertEqual(self.complete(token, PgInventory(dbname=self.dbname))[1].extra["collection_batch"], receipts[0])
        self.assertEqual(self.counts(), completed)

    def test_v1_payload_token_and_initial_digest_need_no_rewrite(self):
        token = self.call(batches.review, 1)
        with self.connection("ro") as c:
            before = c.execute("select initial_digest, content, review from collection_batch").fetchone()
        self.assertEqual(self.call(batches.create, VALUE)["review"], token)
        with self.connection("ro") as c:
            self.assertEqual(c.execute("select initial_digest, content, review from collection_batch").fetchone(), before)
        self.complete(token)
        self.assertEqual(self.counts()[:3], (3, 1, 1))

    def test_metadata_edit_requires_fresh_review(self):
        token = self.call(batches.review, 1)
        value = copy.deepcopy(VALUE)
        value["rows"][0]["condition"] = ""
        value["rows"][0]["language"] = ""
        self.call(batches.save, 1, value)
        with self.assertRaises(Conflict):
            self.complete(token)
        self.complete(self.call(batches.review, 2))
        with self.connection("ro") as c:
            self.assertEqual(c.execute("select quantity, condition, language, notes from collection_card").fetchone(),
                             (3, "", "", ""))

    def test_scanner_evidence_resume_omission_guard_and_commit_once(self):
        from decklab.tests.test_collection_batch_evidence import value_with_evidence
        value = value_with_evidence()
        self.call(batches.save, 1, value)
        self.assertEqual(self.call(batches.read)["content"], value)
        with self.assertRaises(Invalid):
            self.call(batches.review, 2)
        with self.assertRaises(Invalid):
            self.call(batches.save, 2, VALUE)
        self.assertEqual(self.call(batches.read)["content"], value)
        resolved = copy.deepcopy(value)
        resolved["unresolved"] = []
        resolved["evidence"]["ambiguities"] = []
        self.call(batches.save, 2, resolved)
        self.assertEqual(self.call(batches.read)["content"]["evidence"]["next_scan_id"], 8)
        token = self.call(batches.review, 3)
        # Even evidence-only updates invalidate a reviewed snapshot.
        resolved["evidence"]["provenance"][0]["choices"][0]["how"] = "number"
        self.call(batches.save, 3, resolved)
        with self.assertRaises(Conflict):
            self.complete(token)
        token = self.call(batches.review, 4)
        receipt = self.complete(token)[1].extra["collection_batch"]
        before = self.counts()
        self.assertEqual(self.complete(token)[1].extra["collection_batch"], receipt)
        self.assertEqual(self.counts(), before)
        self.assertIsNone(self.call(batches.read)["content"])

    def test_evidence_is_private_fingerprinted_and_removed_with_member(self):
        from decklab.db import conn as db
        from decklab.db import space_apply, space_export, space_remove
        from decklab.tests.test_collection_batch_evidence import value_with_evidence
        self.profile = self.space = "user2"
        self.bid = str(uuid.uuid4())
        value = value_with_evidence()
        self.call(batches.create, value)
        with self.connection("owner") as c:
            files, before, _ = space_export.snapshot(c, self.space, details=True)
            personal, _ = space_export.snapshot(c, self.space, personal=True)
        self.assertFalse(any(b"Unresolved scan" in item for item in [*files.values(), *personal.values()]))
        value["evidence"]["ambiguities"][0]["proposals"][0]["how"] = "number"
        self.call(batches.save, 1, value)
        with self.connection("owner") as c:
            after_files, after, data = space_export.snapshot(c, self.space, details=True)
        self.assertEqual(files, after_files)
        self.assertNotEqual(before, after)
        rows, _ = space_remove.row_plan(self.space, data)
        with self.connection("owner", autocommit=True) as c, db.change(
                "system", "cli", "Fixture evidence member removal", conn=c) as (cur, change_id):
            space_apply._locks(c)
            space_apply._mutate(cur, data, rows, "system", str(uuid.uuid4()), change_id)
        with self.connection("ro") as c:
            self.assertEqual(c.execute("select count(*) from collection_batch where space_id='user2'").fetchone(), (0,))
