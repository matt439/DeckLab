"""Staged upgrade and real removal-journal gates; isolated cluster runner only.

All database/filesystem changes are disposable fixtures. Runtime probes are supplied
synthetic stopped-server/current-process answers; real admission and journal logic run.
No production migration is promoted by these tests.
"""
import copy
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from decklab.db import conn as db
from decklab.db import migrate, space_apply, space_export, space_journal, space_runtime
from decklab.lib.forge import lifecycle
from decklab.lib.state import Actor, Unavailable
from decklab.lib.state import pg_collection_batches as batches
from decklab.tests.test_collection_batch_inventory import VALUE, InventoryFixture
from decklab.tests.test_space_remove_preview import forge_result

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "decklab/design/resumable-batch-schema.sql"
ACTOR = Actor("claude", "Fixture runner", None, "cli")


class Crash(BaseException):
    """Deliberately bypass normal exception recovery, as abrupt process death does."""


class MigrationGateTests(InventoryFixture, unittest.TestCase):
    def candidates(self, suffix=""):
        tmp = self.enterContext(tempfile.TemporaryDirectory(prefix="decklab-batch-upgrade-"))
        folder = Path(tmp)
        current = migrate.available()
        for item in current:
            (folder / item["path"].name).write_bytes(item["path"].read_bytes())
        version = max(item["version"] for item in current) + 1
        candidate = folder / f"{version:04d}_collection_batches_candidate.sql"
        candidate.write_text(SCHEMA.read_text(encoding="utf-8") + suffix, encoding="utf-8")
        return folder, version, candidate

    def remove_staged_fixture(self):
        with self.connection("owner") as c:
            c.execute("drop table collection_batch")  # disposable fixture only, never a runtime down migration

    def test_candidate_is_not_a_production_migration_and_missing_schema_fails_closed(self):
        self.assertFalse(any("collection_batch" in item["sql"] for item in migrate.available()))
        self.remove_staged_fixture()
        self.assertEqual(migrate.apply(dbname=self.dbname), [])
        with self.assertRaises(Unavailable):
            self.call(batches.read)
        # Normal stock writes remain available before the optional schema exists.
        from decklab.lib.inventory import Op
        row = {**VALUE["rows"][0], "quantity": "1", "notes": ""}
        self.backend.apply(Op("collection.import", {"space": "home", "sources": [("fixture", [row])]}),
                           Actor("user1", "Fixture user", "home"), "Existing collection write")
        self.assertEqual(self.counts()[0], 1)

    def test_additive_upgrade_old_code_warning_and_disposable_down_reapply(self):
        self.remove_staged_fixture()
        before = self.counts()
        folder, version, candidate = self.candidates()
        self.assertEqual(migrate.apply(dbname=self.dbname, directory=folder), [candidate.name])
        self.assertEqual(migrate.apply(dbname=self.dbname, directory=folder), [])
        self.assertEqual(before, self.counts())
        self.call(batches.create, VALUE)  # app-role privileges inherited from actual foundation migration
        with self.assertRaises(migrate.DatabaseNewer):
            migrate.status(dbname=self.dbname)  # old code detects, never silently rewrites schema
        with self.connection("owner") as c:
            c.execute("drop table collection_batch")
            c.execute("delete from schema_migration where version=%s", (version,))
        self.assertEqual(migrate.status(dbname=self.dbname)["pending"], [])
        self.assertEqual(before, self.counts())
        self.assertEqual(migrate.apply(dbname=self.dbname, directory=folder), [candidate.name])
        self.call(batches.create, VALUE)

    def test_failed_candidate_upgrade_is_atomic_and_retryable(self):
        import psycopg
        self.remove_staged_fixture()
        before = self.counts()
        folder, version, candidate = self.candidates("\nselect 1 / 0;\n")
        with self.assertRaises(psycopg.errors.DivisionByZero):
            migrate.apply(dbname=self.dbname, directory=folder)
        with self.connection("ro") as c:
            self.assertIsNone(c.execute("select to_regclass('public.collection_batch')").fetchone()[0])
            self.assertEqual(c.execute("select count(*) from schema_migration where version=%s", (version,)).fetchone(), (0,))
        self.assertEqual(before, self.counts())
        candidate.write_text(SCHEMA.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(migrate.apply(dbname=self.dbname, directory=folder), [candidate.name])
        self.call(batches.create, VALUE)

    def test_readonly_role_cannot_change_scratch_or_receipts(self):
        import psycopg
        with self.connection("ro") as c, self.assertRaises(psycopg.errors.InsufficientPrivilege):
            c.execute("update collection_batch set content=null")
        self.assertEqual(self.call(batches.read)["status"], "draft")


class RemovalJournalGateTests(InventoryFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from decklab.db import export
        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="decklab-batch-journal-"))).resolve()
        self.assertTrue(self.temp.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.root = self.temp / "results"
        self.root.mkdir()
        self.dest = self.temp / "member-copy"
        self.enterContext(mock.patch.object(space_runtime, "_status", return_value=None))
        self.enterContext(mock.patch.object(space_runtime, "_processes", return_value={os.getpid(): 1}))
        with self.connection() as c:
            self.target = {"host": c.info.host, "port": c.info.port, "name": self.dbname}
        self.enterContext(mock.patch.object(db, "settings", return_value=self.target))
        self.profile = self.space = "user2"
        self.bid = str(uuid.uuid4())
        value = copy.deepcopy(VALUE)
        value["label"] = "PRIVATE-COMPLETED-BATCH-LABEL"
        self.call(batches.create, value)
        self.complete(self.call(batches.review, 1))
        self.committed_id = self.bid
        self.bid = str(uuid.uuid4())
        value["label"] = "PRIVATE-DRAFT-BATCH-LABEL"
        self.call(batches.create, value)
        self.own = self.root / ("a" * 64 + ".json")
        self.mixed = self.root / ("b" * 64 + ".json")
        self.own.write_text(json.dumps(forge_result("a" * 64, "user2/casual/one", "user2/casual/two")), encoding="utf-8")
        self.mixed.write_text(json.dumps(forge_result("b" * 64, "user2/casual/one", "casual/other")), encoding="utf-8")
        self.originals = {self.own: self.own.read_bytes(), self.mixed: self.mixed.read_bytes()}
        self.manifest = space_export.export_to("user2", self.dest, self.dbname, self.root)
        self.before = self.counts()
        self.batches_before = self.batch_rows()
        self.general = self.temp / "general-copy"
        export.write_tables(self.general, dbname=self.dbname)  # no git, push, or configured export location

    def batch_rows(self):
        with self.connection("ro") as c:
            return c.execute("select batch_id,status,content,review,receipt from collection_batch "
                             "where space_id='user2' order by batch_id").fetchall()

    def apply_removal(self, fault=None):
        return space_apply.apply("user2", self.dest, self.manifest["snapshot_sha256"], ACTOR,
                                 "Remove fixture member", "Fixture member requested removal",
                                 dbname=self.dbname, results_dir=self.root, fault=fault)

    def recover(self, operation, fault=None):
        return space_apply.recover(operation, dbname=self.dbname, results_dir=self.root, fault=fault)

    def pending(self):
        with lifecycle.maintenance(self.root) as claim:
            return space_journal.pending(claim)

    @staticmethod
    def crash_at(stage):
        def fail(label, index):
            if label == stage:
                raise Crash(stage)
        return fail

    def assert_restored(self):
        self.assertEqual(self.batch_rows(), self.batches_before)
        self.assertEqual(self.counts(), self.before)
        self.assertEqual(self.pending(), [])
        for path, raw in self.originals.items():
            self.assertEqual(path.read_bytes(), raw)

    def assert_removed(self):
        self.assertEqual(self.batch_rows(), [])
        self.assertEqual(self.counts()[:3], (0, 0, 0))
        self.assertEqual(self.counts()[3], self.before[3] + 1)
        self.assertFalse(self.own.exists())
        self.assertEqual(self.mixed.read_bytes(), self.originals[self.mixed])
        with self.connection("ro") as c:
            self.assertEqual(c.execute("select count(*) from collection_batch where space_id='home'").fetchone(), (1,))
        with self.assertRaises(lifecycle.LifecycleError), lifecycle.writer(self.root, deck_ids=["user2/casual/one"]):
            self.fail("departed member writer admitted")

    def test_private_scratch_is_absent_from_both_export_artifacts(self):
        for folder in (self.dest, self.general):
            for path in folder.rglob("*"):
                if path.is_file():
                    raw = path.read_bytes()
                    self.assertNotIn(b"PRIVATE-DRAFT-BATCH-LABEL", raw)
                    self.assertNotIn(b"PRIVATE-COMPLETED-BATCH-LABEL", raw)
                    self.assertNotIn("collection_batch", path.name)
        self.assertEqual(len(self.batch_rows()), 2)

    def test_normal_removal_deletes_batches_keeps_other_space_and_recovers_idempotently(self):
        result = self.apply_removal()
        self.assertEqual(result["state"], "committed")
        self.assert_removed()
        before = self.counts()
        self.assertEqual(self.recover(result["operation"])["state"], "committed")
        self.assertEqual(self.counts(), before)

    def test_precommit_crashes_restore_files_drafts_receipts_and_audit(self):
        for stage in ("prepared", "staged", "sql_done"):
            with self.subTest(stage=stage):
                with self.assertRaises(Crash):
                    self.apply_removal(self.crash_at(stage))
                operation, = self.pending()
                self.assertEqual(self.recover(operation)["state"], "rolled_back")
                self.assert_restored()

    def test_postcommit_and_cleanup_crashes_finish_without_second_change(self):
        with self.assertRaises(Crash):
            self.apply_removal(self.crash_at("committed"))
        operation, = self.pending()
        with self.assertRaises(Crash):
            self.recover(operation, self.crash_at("cleaned"))
        self.assertEqual(self.recover(operation)["state"], "committed")
        self.assertEqual(self.pending(), [])
        self.assert_removed()

    def test_lost_commit_ack_is_confirmed_by_existing_audit_identity(self):
        def lost(label, index):
            if label == "committed":
                raise RuntimeError("fixture lost acknowledgement")
        result = self.apply_removal(lost)
        self.assertTrue(result["recovered"])
        self.assert_removed()

    def test_stale_batch_fingerprint_refuses_removal_without_touching_files(self):
        value = copy.deepcopy(VALUE)
        value["label"] = "new private draft revision"
        self.call(batches.save, 1, value)
        before = self.counts()
        with self.assertRaises(ValueError):
            self.apply_removal()
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.pending(), [])
        self.assertEqual(self.call(batches.read)["revision"], 2)
        for path, raw in self.originals.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_tampered_export_refuses_before_quarantine(self):
        path = self.dest / "collection.csv"
        path.write_bytes(path.read_bytes() + b"tampered\n")
        with self.assertRaises(ValueError):
            self.apply_removal()
        self.assert_restored()

    def test_recovery_refuses_a_different_database_identity_then_recovers_original(self):
        with self.assertRaises(Crash):
            self.apply_removal(self.crash_at("staged"))
        operation, = self.pending()
        with mock.patch.object(db, "settings", return_value={**self.target, "port": self.target["port"] + 1}), self.assertRaises(ValueError):
            self.recover(operation)
        self.assertEqual(self.pending(), [operation])
        self.assertEqual(self.recover(operation)["state"], "rolled_back")
        self.assert_restored()
