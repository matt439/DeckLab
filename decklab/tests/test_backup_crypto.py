"""No real crypto/tools/keys: a fake command protocol over disposable synthetic bytes."""
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab.db import backup, backup_crypto as crypto, move

PUBLIC = "age1" + "q" * 58
PRIVATE = "AGE-SECRET-KEY-1" + "A" * 59


class CryptoTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="decklab-crypto-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "decklab-2026-11-11-033000.dump"
        self.source.write_bytes(b"PGDMP_SYNTHETIC_PRIVATE_PAYLOAD")
        self.identity = self.root / "synthetic.key"
        self.identity.write_text("# synthetic identity only\n" + PRIVATE + "\n", encoding="ascii")
        self.settings = {"backup_recipient": PUBLIC, "backup_identity": str(self.identity)}
        self.enterContext(mock.patch.object(crypto.shutil, "which", return_value="fake-age"))
        self.calls = []

    def fake(self, args, **options):
        self.calls.append((args, options))
        output = Path(args[args.index("--output") + 1])
        if "--encrypt" in args:
            output.write_bytes(crypto.HEADER + b"SYNTHETIC_CIPHERTEXT")
        else:
            output.write_bytes(b"PGDMP_SYNTHETIC_PRIVATE_PAYLOAD")
        return SimpleNamespace(returncode=0)

    def test_encryption_needs_no_private_key_and_sends_only_ciphertext_to_the_destination(self):
        self.identity.unlink()
        encrypted = crypto.encrypt_copy(self.source, self.root / "nas", self.settings, runner=self.fake)
        self.assertEqual(encrypted.name, self.source.name + ".age")
        self.assertNotIn(b"PRIVATE_PAYLOAD", encrypted.read_bytes())
        self.assertEqual(self.source.read_bytes(), b"PGDMP_SYNTHETIC_PRIVATE_PAYLOAD")
        args, options = self.calls[0]
        self.assertIn(PUBLIC, args)
        self.assertNotIn("--identity", args)
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertFalse(any(path.name.endswith(".partial") for path in encrypted.parent.iterdir()))

    def test_decryption_supplies_native_identity_on_stdin_and_removes_plaintext_on_every_exit(self):
        encrypted = crypto.encrypt_copy(self.source, self.root / "nas", self.settings, runner=self.fake)
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with crypto.readable_dump(encrypted, self.settings, runner=self.fake) as temporary:
                self.assertEqual(temporary.read_bytes(), self.source.read_bytes())
                folder = temporary.parent
                self.assertNotEqual(folder, encrypted.parent)
                raise RuntimeError("synthetic consumer failure")
        self.assertFalse(folder.exists())
        args, options = self.calls[-1]
        self.assertNotIn(PRIVATE, " ".join(args))
        self.assertIn("--identity", args)
        self.assertEqual(options["input"], (PRIVATE + "\n").encode())

    def test_refused_or_broken_tool_never_falls_back_to_plaintext_or_keeps_partial_ciphertext(self):
        def refused(args, **options):
            Path(args[args.index("--output") + 1]).write_bytes(b"PRIVATE_PARTIAL")
            return SimpleNamespace(returncode=1)
        with self.assertRaises(crypto.CryptoError) as failed:
            crypto.encrypt_copy(self.source, self.root / "nas", self.settings, runner=refused)
        self.assertNotIn("PRIVATE", str(failed.exception))
        self.assertEqual(list((self.root / "nas").iterdir()), [])
        self.assertTrue(self.source.is_file())
        with self.assertRaises(crypto.CryptoError):
            crypto.encrypt_copy(self.source, self.root / "nas", self.settings,
                                runner=mock.Mock(side_effect=subprocess.TimeoutExpired("fake-age", 1)))

    def test_missing_or_interactive_keys_refuse_before_running_any_command_and_status_stays_passive(self):
        runner = mock.Mock()
        self.identity.write_text("ssh-rsa PRIVATE_NOT_SUPPORTED", encoding="ascii")
        with self.assertRaises(crypto.CryptoError):
            with crypto.readable_dump(self.source.with_suffix(".dump.age"), self.settings, runner=runner):
                self.fail("no decrypted input")
        runner.assert_not_called()
        self.identity.unlink()
        self.assertTrue(any("key file" in line for line in crypto.warnings(self.settings)))
        self.assertEqual(crypto.warnings({}), [])
        for value in ("-r injected", "ssh-ed25519 unknown", "AGE-SECRET-KEY-1PRIVATE", "age1plugin1invalid"):
            with self.assertRaises(crypto.CryptoError):
                crypto.recipient({"backup_recipient": value})

    def test_plain_input_passes_through_without_a_key_or_tool_and_empty_decryption_is_refused(self):
        with mock.patch.object(crypto, "program", side_effect=AssertionError("no tool needed")):
            with crypto.readable_dump(self.source, {}) as plain:
                self.assertEqual(plain, self.source)
        with self.assertRaises(crypto.CryptoError):
            with crypto.readable_dump(self.source.with_suffix(".dump.age"), self.settings,
                                      runner=lambda *args, **options: SimpleNamespace(returncode=0)):
                self.fail("empty output cannot be restored")

    def test_backup_command_never_copies_plaintext_when_encryption_is_opted_in_and_preserves_recorded_proof(self):
        settings = {**backup.db.DEFAULTS, **self.settings, "staging_dir": str(self.root / "staging"),
                    "backup_dir": str(self.root / "nas"), "backup_same_device_ok": True}
        counts, digests = {"public.collection_card": 1}, {"public.collection_card": "synthetic-digest"}
        def dump(target, s):
            target.parent.mkdir(parents=True)
            target.write_bytes(self.source.read_bytes())
            return True, counts, digests, ""
        with mock.patch.object(backup.db, "settings", return_value=settings), \
                mock.patch.object(backup.db, "pg_bin", return_value="fake-pg-dump"), \
                mock.patch.object(backup, "dump", side_effect=dump), mock.patch.object(backup, "record") as record, \
                mock.patch.object(crypto.subprocess, "run", side_effect=self.fake):
            self.assertEqual(backup.run_backup(say=lambda text: None), 0)
        files = list((self.root / "nas").iterdir())
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.endswith(".dump.age"))
        self.assertNotIn(b"PRIVATE_PAYLOAD", files[0].read_bytes())
        self.assertEqual(record.call_args.args[2:6], (True, files[0], files[0].stat().st_size, backup.dump_detail(counts)))
        self.assertEqual(record.call_args.kwargs["digests"], digests)

    def test_failed_encrypted_copy_is_a_failed_backup_with_a_kept_local_dump_and_no_remote_fallback(self):
        settings = {**backup.db.DEFAULTS, **self.settings, "staging_dir": str(self.root / "staging"),
                    "backup_dir": str(self.root / "nas"), "backup_same_device_ok": True}
        def dump(target, s):
            target.parent.mkdir(parents=True)
            target.write_bytes(self.source.read_bytes())
            return True, {"public.collection_card": 1}, {}, ""
        with mock.patch.object(backup.db, "settings", return_value=settings), \
                mock.patch.object(backup.db, "pg_bin", return_value="fake-pg-dump"), \
                mock.patch.object(backup, "dump", side_effect=dump), mock.patch.object(backup, "record") as record, \
                mock.patch.object(crypto.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            self.assertEqual(backup.run_backup(say=lambda text: None), 1)
        self.assertFalse(record.call_args.args[2])
        self.assertTrue(Path(record.call_args.args[3]).is_file())
        self.assertEqual(list((self.root / "nas").iterdir()), [])

    def test_restore_check_decrypts_before_scratch_writes_and_keeps_exact_row_and_digest_comparisons(self):
        encrypted = crypto.encrypt_copy(self.source, self.root / "nas", self.settings, runner=self.fake)
        settings = {**backup.db.DEFAULTS, **self.settings, "name": "fixture", "backup_same_device_ok": True}
        connection = mock.MagicMock()
        restored = []
        def tool(args):
            target = Path(args[-1])
            self.assertEqual(target.read_bytes(), self.source.read_bytes())
            restored.append(target)
            return True, ""
        counts, digests = {"public.collection_card": 1}, {"public.collection_card": "expected"}
        with mock.patch.object(backup.db, "settings", return_value=settings), \
                mock.patch.object(backup.db, "connect", return_value=connection), \
                mock.patch.object(backup.db, "pg_bin", return_value="fake-pg-restore"), \
                mock.patch.object(backup, "recorded", return_value=(counts, digests)) as recorded, \
                mock.patch.object(backup, "count_rows", return_value=counts), mock.patch.object(backup, "digest_rows", return_value=digests), \
                mock.patch.object(backup, "_scratch_drop"), mock.patch.object(backup, "record") as record, \
                mock.patch.object(backup, "_tool", side_effect=tool), mock.patch.object(crypto.subprocess, "run", side_effect=self.fake):
            self.assertEqual(backup.run_restore_check(source=encrypted.parent, say=lambda text: None), 0)
        recorded.assert_called_once_with(encrypted.name)
        self.assertFalse(restored[0].exists())
        self.assertEqual(record.call_args.args[2], True)
        self.assertEqual(record.call_args.args[3], encrypted)
        # Missing identity refuses before creating/dropping any scratch database.
        self.identity.unlink()
        with mock.patch.object(backup.db, "settings", return_value=settings), \
                mock.patch.object(backup.db, "connect") as connect, mock.patch.object(backup, "recorded", return_value=(counts, digests)), \
                mock.patch.object(backup, "record") as record:
            self.assertEqual(backup.run_restore_check(source=encrypted.parent, say=lambda text: None), 1)
        connect.assert_not_called()
        self.assertEqual(record.call_args.args[2], False)

    def test_restore_command_supplies_plaintext_to_the_existing_guarded_restore_and_key_failure_never_reaches_it(self):
        encrypted = crypto.encrypt_copy(self.source, self.root / "nas", self.settings, runner=self.fake)
        used = []
        def restore(path, **options):
            self.assertEqual(path.read_bytes(), self.source.read_bytes())
            self.assertEqual(options["expect"], "synthetic-digest.json")
            self.assertTrue(options["replace"])
            self.assertFalse(options["force"])
            used.append(path)
            return 0
        with mock.patch.object(move.db, "settings", return_value=self.settings), \
                mock.patch.object(move, "_run_restore_plain", side_effect=restore), \
                mock.patch.object(crypto.subprocess, "run", side_effect=self.fake):
            self.assertEqual(move.run_restore(encrypted, expect="synthetic-digest.json", replace=True), 0)
        self.assertFalse(used[0].exists())
        self.identity.unlink()
        with mock.patch.object(move.db, "settings", return_value=self.settings), \
                mock.patch.object(move, "_run_restore_plain") as restore:
            self.assertEqual(move.run_restore(encrypted, say=lambda text: None), 1)
        restore.assert_not_called()

    def test_encrypted_names_partials_and_recorded_proofs_work_with_existing_retention(self):
        encrypted = crypto.encrypt_copy(self.source, self.root / "nas", self.settings, runner=self.fake)
        self.assertEqual(backup.dump_date(encrypted.name), backup.dump_date(self.source.name))
        self.assertEqual(backup.newest_dump(encrypted.parent), encrypted)
        counts, digests = {"public.collection_card": 1}, {"public.collection_card": "expected"}
        connection = mock.MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchall.return_value = [
            (str(encrypted), backup.dump_detail(counts), digests)]
        with mock.patch.object(backup.db, "connect", return_value=connection):
            self.assertEqual(backup.recorded(self.source.name), (counts, digests))
        old = encrypted.with_name("decklab-2026-01-01-033000.dump.age.partial")
        old.write_bytes(b"ciphertext")
        self.assertEqual(backup.stale_partials(encrypted.parent, now=old.stat().st_mtime + backup.PARTIAL_MAX_AGE + 1), [old.name])

    def test_status_warns_for_a_missing_key_even_after_encryption_is_disabled_when_recent_receipts_are_encrypted(self):
        now = datetime.now(timezone.utc)
        kinds = ("dump", "export", "check", "restore_check")
        recent = dict.fromkeys(kinds)
        recent["dump"] = {"ok": True, "started_at": now, "finished_at": now,
                          "detail": "rows: {}", "path": "decklab-2026-11-11-033000.dump.age"}
        with mock.patch.object(backup.db, "settings", return_value=dict(backup.db.DEFAULTS)), \
                mock.patch.object(backup, "last_ok", return_value=dict.fromkeys(kinds, now)), \
                mock.patch.object(backup, "latest", return_value=recent):
            self.assertTrue(any("key file" in line for line in backup.status(now=now)))
