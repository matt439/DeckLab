"""Durable journal protocol over disposable synthetic requests and file leases; no Forge/services."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from decklab.lib.forge import run_journal as journal


class JournalTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="decklab-run-journal-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "journal"
        self.journal = journal.Journal(self.root)
        self.addCleanup(self.journal.close)
        self.request = {"profile": "user2", "id": "user2/casual/fixture", "version": "target", "budget": "standard"}
        self.manifest = {"base": {"id": "user2/casual/fixture", "card_sha": "a" * 64}, "engine": "b" * 64,
                         "participants": [{"id": "user2/casual/opponent", "card_sha": "c" * 64}]}

    def create(self, who="user2"):
        return self.journal.create(who, "field", {**self.request, "profile": who}, self.manifest)

    def test_request_is_persisted_before_returning_and_caller_mutation_cannot_rewrite_it(self):
        record = self.create()
        self.request["budget"] = "PRIVATE_CHANGED_REQUEST"
        self.manifest["engine"] = "PRIVATE_CHANGED_ENGINE"
        found = self.journal.get("user2", record["id"])
        self.assertEqual(found["request"]["budget"], "standard")
        self.assertEqual(found["manifest"]["engine"], "b" * 64)
        self.assertEqual(found["state"], "queued")
        self.assertFalse(self.journal.inactive(found))
        self.assertFalse(any(path.name.endswith(".tmp") for path in self.root.rglob("*")))

    def test_other_starters_files_are_not_read_or_disclosed_including_malformed_private_records(self):
        record = self.create()
        private = self.root / "user2" / (record["id"] + ".json")
        private.write_bytes(b"PRIVATE_CORRUPT_METADATA")
        self.assertEqual(self.journal.records("matt"), [])
        self.assertIsNone(self.journal.get("matt", record["id"]))
        with self.assertRaises(journal.JournalUnavailable) as refused:
            self.journal.records("user2")
        self.assertNotIn("PRIVATE", str(refused.exception))

    def test_live_other_session_is_not_interrupted_and_a_closed_lease_can_be_claimed_only_once(self):
        record = self.create()
        other = journal.Journal(self.root)
        self.addCleanup(other.close)
        self.assertFalse(other.inactive(record))
        with self.assertRaises(journal.JournalUnavailable):
            other.claim("user2", record["id"], self.manifest)
        self.journal.close()                         # models a restart/crash releasing the OS-held lease
        self.assertTrue(other.inactive(record))
        claimed = other.claim("user2", record["id"], self.manifest)
        self.assertNotEqual(claimed["session"], record["session"])
        self.assertFalse(other.inactive(claimed))
        with self.assertRaises(journal.JournalUnavailable):
            self.journal.claim("user2", record["id"], self.manifest)

    def test_stop_done_failure_and_dismiss_are_terminal_but_server_interruption_retains_exact_request(self):
        for event in ("done", "cancelled", "failed", "dismissed"):
            with self.subTest(event=event):
                record = self.create()
                self.journal.transition("user2", record["id"], "running")
                self.journal.transition("user2", record["id"], event)
                self.assertIsNone(self.journal.get("user2", record["id"]))
        record = self.create()
        self.journal.transition("user2", record["id"], "interrupted")
        interrupted = self.journal.get("user2", record["id"])
        self.assertTrue(self.journal.inactive(interrupted))
        self.assertEqual(interrupted["request"], record["request"])
        with self.assertRaisesRegex(ValueError, "changed"):
            self.journal.claim("user2", record["id"], {**self.manifest, "engine": "changed"})

    def test_bounds_invalid_paths_and_failed_atomic_write_never_return_an_accepted_record(self):
        for starter, key in (("../private", "a" * 32), ("user2", "../private")):
            with self.assertRaises(journal.JournalUnavailable):
                self.journal.get(starter, key)
        with mock.patch.object(journal, "MAX_RECORDS", 1):
            self.create()
            with self.assertRaises(journal.JournalUnavailable):
                self.create()
        with mock.patch.object(journal.os, "replace", side_effect=OSError("PRIVATE_PATH")):
            with self.assertRaises(journal.JournalUnavailable) as failed:
                self.journal.create("user3", "field", self.request, self.manifest)
        self.assertNotIn("PRIVATE", str(failed.exception))
        self.assertEqual(self.journal.records("user3"), [])
        with mock.patch.object(journal, "MAX_BYTES", 20):
            with self.assertRaises(journal.JournalUnavailable):
                self.journal.create("user3", "field", self.request, self.manifest)

    def test_missing_lease_or_malformed_identity_never_proves_a_run_is_safe_to_resume(self):
        record = self.create()
        bad = {**record, "session": "f" * 32}
        self.assertIsNone(self.journal.inactive(bad))
        self.assertIsNone(self.journal._session().inactive("../private"))
        record["starter"] = "user3"
        target = self.root / "user2" / (record["id"] + ".json")
        target.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(journal.JournalUnavailable):
            self.journal.get("user2", record["id"])
