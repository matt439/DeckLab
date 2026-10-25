"""Removal-journal recovery uses temporary Forge files only; no DB or service."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

from decklab.db import space_journal


OPERATION = "11111111-1111-4111-8111-111111111111"
CHANGE_SET = 7
LOCAL_TEMP = (Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp"
              if os.name == "nt" else Path(tempfile.gettempdir()))


class InjectedCrash(RuntimeError):
    pass


class RemovalJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="decklab-journal-", dir=LOCAL_TEMP)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "forge"
        self.root.mkdir()
        self.control = self.root.parent / f".{self.root.name}-lifecycle"
        self.control.mkdir()
        self.claim = SimpleNamespace(root=self.root, control_dir=self.control)
        self.contents = {"jobs/first/output.txt": b"first output\n",
                         "results/second.json": b'{"second":true}\n'}
        self.entries = []
        for relative, raw in self.contents.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.entries.append({"path": relative, "bytes": len(raw),
                                 "sha256": hashlib.sha256(raw).hexdigest()})

    def prepare(self, **overrides):
        args = {"operation": OPERATION, "space": "sample",
                "database": {"host": "127.0.0.1", "port": 5432, "name": "decklab_test_journal"},
                "change_set_id": CHANGE_SET, "actor": "test", "message_sha256": "a" * 64,
                "snapshot_sha256": "b" * 64, "entries": copy.deepcopy(self.entries)}
        args.update(overrides)
        return space_journal.prepare(self.claim, **args)

    def staged(self, relative):
        return self.control / "quarantine" / OPERATION / relative

    def assert_originals(self):
        for relative, raw in self.contents.items():
            self.assertEqual((self.root / relative).read_bytes(), raw)
            self.assertFalse(self.staged(relative).exists())

    def assert_archived(self, state):
        self.assertEqual(space_journal.pending(self.claim), [])
        documents = [json.loads(path.read_text(encoding="utf-8"))
                     for path in self.control.rglob("*.json")]
        self.assertTrue(any(document.get("operation") == OPERATION
                            and document.get("state") == state for document in documents))

    def crash_after(self, label, check=None):
        def fault(event, index):
            if event == label:
                if check:
                    check(index)
                raise InjectedCrash(label)
        return fault

    def test_prepare_is_durable_before_any_original_is_moved(self):
        journal = self.prepare()
        self.assertEqual(space_journal.pending(self.claim), [OPERATION])
        self.assertEqual(space_journal.load(self.claim, OPERATION), journal)
        self.assert_originals()

    def test_restore_without_any_staging_archives_rollback_and_keeps_originals(self):
        journal = self.prepare()
        space_journal.restore(self.claim, journal)
        self.assert_originals()
        self.assert_archived("rolled_back")

    def test_crash_after_first_move_can_restore_staged_and_unmoved_files(self):
        journal = self.prepare()
        with self.assertRaises(InjectedCrash):
            space_journal.stage(self.claim, journal, fault=self.crash_after("staged"))
        self.assertEqual(sum(self.staged(relative).exists() for relative in self.contents), 1)
        self.assertEqual(sum((self.root / relative).exists() for relative in self.contents), 1)
        self.assertEqual(space_journal.pending(self.claim), [OPERATION])
        space_journal.restore(self.claim, space_journal.load(self.claim, OPERATION))
        self.assert_originals()
        self.assert_archived("rolled_back")

    def test_restore_after_all_moves_recovers_exact_original_bytes(self):
        journal = self.prepare()
        space_journal.stage(self.claim, journal)
        for relative, raw in self.contents.items():
            self.assertFalse((self.root / relative).exists())
            self.assertEqual(self.staged(relative).read_bytes(), raw)
        space_journal.restore(self.claim, space_journal.load(self.claim, OPERATION))
        self.assert_originals()
        self.assert_archived("rolled_back")

    def test_committed_cleanup_retry_is_idempotent_after_partial_deletion(self):
        journal = self.prepare()
        space_journal.stage(self.claim, journal)
        with self.assertRaises(InjectedCrash):
            space_journal.finish(self.claim, journal, fault=self.crash_after("cleaned"))
        self.assertEqual(sum(self.staged(relative).exists() for relative in self.contents), 1)
        self.assertEqual(space_journal.pending(self.claim), [OPERATION])
        space_journal.finish(self.claim, space_journal.load(self.claim, OPERATION))
        for relative in self.contents:
            self.assertFalse(self.staged(relative).exists())
            self.assertFalse((self.root / relative).exists())
        self.assert_archived("committed")

    def test_departed_marker_is_durable_before_first_cleanup(self):
        journal = self.prepare()
        space_journal.stage(self.claim, journal)

        def marker_is_written(_index):
            marker = json.loads((self.control / "departed.json").read_text(encoding="utf-8"))
            self.assertEqual(marker, {"version": 1, "spaces": ["sample"]})

        with self.assertRaises(InjectedCrash):
            space_journal.finish(self.claim, journal,
                                 fault=self.crash_after("departed", marker_is_written))
        for relative in self.contents:
            self.assertEqual(self.staged(relative).read_bytes(), self.contents[relative])
        self.assertEqual(space_journal.pending(self.claim), [OPERATION])

    def test_departed_marker_preserves_existing_spaces_and_sorts_them(self):
        (self.control / "departed.json").write_text(
            json.dumps({"version": 1, "spaces": ["zebra", "aardvark"]}), encoding="utf-8")
        journal = self.prepare()
        space_journal.stage(self.claim, journal)
        space_journal.finish(self.claim, journal)
        self.assertEqual(json.loads((self.control / "departed.json").read_text(encoding="utf-8")),
                         {"version": 1, "spaces": ["aardvark", "sample", "zebra"]})
        self.assert_archived("committed")

    def test_rollback_retry_is_idempotent_after_partial_restore(self):
        journal = self.prepare()
        space_journal.stage(self.claim, journal)
        with self.assertRaises(InjectedCrash):
            space_journal.restore(self.claim, journal, fault=self.crash_after("restored"))
        self.assertEqual(sum((self.root / relative).exists() for relative in self.contents), 1)
        self.assertEqual(space_journal.pending(self.claim), [OPERATION])
        space_journal.restore(self.claim, space_journal.load(self.claim, OPERATION))
        self.assert_originals()
        self.assert_archived("rolled_back")

    def test_changed_original_refuses_stage_and_keeps_pending_journal(self):
        journal = self.prepare()
        first = self.entries[0]["path"]
        (self.root / first).write_bytes(b"intervening output")
        with self.assertRaises(ValueError):
            space_journal.stage(self.claim, journal)
        self.assertEqual((self.root / first).read_bytes(), b"intervening output")
        self.assertEqual(space_journal.pending(self.claim), [OPERATION])

    def test_changed_quarantine_refuses_restore_without_overwriting_it(self):
        journal = self.prepare()
        space_journal.stage(self.claim, journal)
        first = self.entries[0]["path"]
        self.staged(first).write_bytes(b"changed quarantine")
        with self.assertRaises(ValueError):
            space_journal.restore(self.claim, journal)
        self.assertEqual(self.staged(first).read_bytes(), b"changed quarantine")
        self.assertFalse((self.root / first).exists())
        self.assertEqual(space_journal.pending(self.claim), [OPERATION])

    def test_changed_quarantine_refuses_cleanup_without_deleting_it(self):
        journal = self.prepare()
        space_journal.stage(self.claim, journal)
        first = self.entries[0]["path"]
        self.staged(first).write_bytes(b"changed quarantine")
        with self.assertRaises(ValueError):
            space_journal.finish(self.claim, journal)
        self.assertEqual(self.staged(first).read_bytes(), b"changed quarantine")
        self.assertEqual(space_journal.pending(self.claim), [OPERATION])

    def test_restore_conflict_preserves_both_intervening_and_staged_bytes(self):
        journal = self.prepare()
        space_journal.stage(self.claim, journal)
        first = self.entries[0]["path"]
        original = self.root / first
        original.write_bytes(b"new output at original path")
        with self.assertRaises(ValueError):
            space_journal.restore(self.claim, journal)
        self.assertEqual(original.read_bytes(), b"new output at original path")
        self.assertEqual(self.staged(first).read_bytes(), self.contents[first])
        self.assertEqual(space_journal.pending(self.claim), [OPERATION])

    def test_atomic_no_replace_preserves_an_intervening_destination(self):
        source = self.root / self.entries[0]["path"]
        target = Path(self.tmp.name) / "intervening.txt"
        target.write_bytes(b"unrelated target")
        with self.assertRaises(FileExistsError):
            space_journal._no_replace(source, target)
        self.assertEqual(source.read_bytes(), self.contents[self.entries[0]["path"]])
        self.assertEqual(target.read_bytes(), b"unrelated target")

    @unittest.skipUnless(os.name == "posix", "POSIX link/unlink crash boundary; Windows uses atomic native moves")
    def test_link_unlink_stage_crash_duplicate_inode_is_restored_safely(self):
        journal = self.prepare()
        first = self.entries[0]["path"]
        space_journal._mkdir(self.staged(first).parent)
        os.link(self.root / first, self.staged(first))
        space_journal.restore(self.claim, journal)
        self.assert_originals()
        self.assert_archived("rolled_back")

    @unittest.skipUnless(os.name == "posix", "POSIX link/unlink crash boundary; Windows uses atomic native moves")
    def test_link_unlink_archive_crash_removes_only_its_duplicate_pending_name(self):
        journal = self.prepare()
        pending = self.control / "pending" / f"{OPERATION}.json"
        completed = self.control / "completed" / pending.name
        space_journal._mkdir(completed.parent)
        space_journal._write(pending, dict(journal, state="rolled_back"))
        os.link(pending, completed)
        space_journal.restore(self.claim, space_journal.load(self.claim, OPERATION))
        self.assert_originals()
        self.assert_archived("rolled_back")

    def test_stage_refuses_original_symlink_and_preserves_its_target(self):
        journal = self.prepare()
        first = self.entries[0]["path"]
        original = self.root / first
        target = Path(self.tmp.name) / "target.txt"
        target.write_bytes(self.contents[first])
        original.unlink()
        try:
            original.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"Symbolic links unavailable: {exc}")
        with self.assertRaises(ValueError):
            space_journal.stage(self.claim, journal)
        self.assertTrue(original.is_symlink())
        self.assertEqual(target.read_bytes(), self.contents[first])
        self.assertEqual(space_journal.pending(self.claim), [OPERATION])

    def test_prepare_refuses_unsafe_or_duplicate_entries_without_moving_files(self):
        bad_paths = ("../outside", "/absolute", "jobs/../outside", "jobs\\outside",
                     ".lifecycle/lock", "jobs/a:stream", "jobs/NUL", "jobs//file")
        for path in bad_paths:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.prepare(entries=[{**self.entries[0], "path": path}])
        with self.assertRaises(ValueError):
            self.prepare(entries=[self.entries[0], self.entries[0]])
        self.assertEqual(space_journal.pending(self.claim), [])
        self.assert_originals()

    def test_load_rejects_tampered_path_and_preserves_journal_and_originals(self):
        journal = self.prepare()
        paths = [path for path in self.control.rglob("*.json")
                 if json.loads(path.read_text(encoding="utf-8")) == journal]
        self.assertEqual(len(paths), 1)
        journal["entries"][0]["path"] = "../outside"
        paths[0].write_text(json.dumps(journal), encoding="utf-8")
        with self.assertRaises(ValueError):
            space_journal.load(self.claim, OPERATION)
        self.assertTrue(paths[0].exists())
        self.assert_originals()


if __name__ == "__main__":
    unittest.main()
