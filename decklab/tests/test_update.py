"""The server PC's updater (decklab/update.py) and the database move's digest comparison
(decklab/db/move.py): their pure parts. Pulling, migrating, restoring and downloading need
the real repo, PostgreSQL and the network, so they aren't run here."""
import hashlib
import json
import os
import stat
import tempfile
import types
import unittest
import zipfile
from unittest import mock
from pathlib import Path

from decklab import update
from decklab.db import move


class ForgeConfigTests(unittest.TestCase):
    def test_expected_release(self):
        text = 'import x\n\nV = "2.0.15-decklab-52387e83f"\nRELEASE = V\n'
        self.assertEqual(update.expected_release(text), "2.0.15-decklab-52387e83f")
        self.assertIsNone(update.expected_release("RELEASE = 'x'\n"))

    def test_set_forge_dir_replaces_in_place(self):
        text = '{\n  "port": 8642,\n  "forge_dir": "C:\\\\Tools\\\\forge-old",\n  "profiles": []\n}\n'
        out = update.set_forge_dir(text, r"C:\Tools\forge-2.0.16-decklab-abc")
        self.assertEqual(json.loads(out)["forge_dir"], r"C:\Tools\forge-2.0.16-decklab-abc")
        self.assertEqual(out.splitlines()[1], '  "port": 8642,')       # the layout is kept
        self.assertEqual(out.splitlines()[3], '  "profiles": []')

    def test_set_forge_dir_adds_the_key(self):
        out = update.set_forge_dir('{"profiles": []}', "/srv/forge-new")
        self.assertEqual(json.loads(out), {"forge_dir": "/srv/forge-new", "profiles": []})

    def test_set_forge_dir_refuses_what_it_cant_place(self):
        with self.assertRaises(ValueError):
            update.set_forge_dir("[]", "/x")
        nested = '{"forge_dir": "/a", "extra": {"forge_dir": "/b"}}'
        with self.assertRaises(ValueError):
            update.set_forge_dir(nested, "/x")


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)

    def archive(self, names):
        path = self.dir / "a.zip"
        with zipfile.ZipFile(path, "w") as z:
            for name in names:
                z.writestr(name, "x")
        return path

    def test_one_folder_is_unzipped(self):
        target = self.dir / "out"
        target.mkdir()
        top = update.safe_extract(self.archive(["forge-1/a.jar", "forge-1/res/b.txt"]), target)
        self.assertEqual(top, target.resolve() / "forge-1")
        self.assertTrue((top / "res" / "b.txt").is_file())

    def test_escaping_and_loose_files_are_refused(self):
        for names in (["forge-1/a.jar", "../evil.txt"], ["forge-1/a.jar", "loose.txt"]):
            target = self.dir / f"out{len(names)}{names[-1][0]}"
            target.mkdir()
            with self.assertRaises(update.Failed):
                update.safe_extract(self.archive(names), target)
            self.assertFalse((self.dir / "evil.txt").exists())

    def test_each_files_unix_mode_is_kept(self):
        path = self.dir / "modes.zip"
        modes = {"forge-1/forge.sh": 0o100755, "forge-1/res/data.txt": 0o100644, "forge-1/jre/bin/java": 0o104755,
                 "forge-1/plain.txt": None}           # made on Windows: only the DOS archive bit
        with zipfile.ZipFile(path, "w") as z:
            for name, mode in modes.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = 0x20 if mode is None else mode << 16
                z.writestr(info, "x")
        target = self.dir / "modes"
        with zipfile.ZipFile(path) as z, mock.patch.object(update.os, "chmod") as chmod:
            update._keep_modes(z.infolist(), target)
        self.assertEqual(sorted((Path(c.args[0]).relative_to(target).as_posix(), c.args[1])
                                for c in chmod.call_args_list),
                         [("forge-1/forge.sh", 0o755), ("forge-1/jre/bin/java", 0o755),     # never setuid
                          ("forge-1/res/data.txt", 0o644)])
        if os.name != "nt":             # and for real, where files have Unix modes
            target.mkdir()
            top = update.safe_extract(path, target)
            self.assertEqual(stat.S_IMODE((top / "forge.sh").stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((top / "jre" / "bin" / "java").stat().st_mode), 0o755)

    def test_the_download_is_hashed_in_blocks(self):
        path = self.dir / "big.bin"
        data = bytes(range(256)) * 9000          # over a MiB
        path.write_bytes(data)
        self.assertEqual(update.file_sha256(path), hashlib.sha256(data).hexdigest())


class StopBeforeBackupTests(unittest.TestCase):
    """E11-S70: with migrations pending, the running server is stopped before the backup, on
    every system, and started again afterwards; a failure says it is stopped."""
    STOP, BACKUP, MIGRATE = "Stop Deck Lab before the backup", "Back up before migrating", "Migrate"
    RESTART = "Restart the background server"
    PENDING = ({"name": "0021_x"},)

    def run_update(self, pending=PENDING, running=True, needs_stop=False, files=(), no_restart=False, fail=None,
                   done=None):
        """(the steps run, the done set, the Failed raised or None) of _after_pull with everything
        outside it stubbed; fail names the step that exits non-zero."""
        steps, done = [], set() if done is None else done

        def step(argv, what, timeout=None):
            what = what.split(" (")[0]
            steps.append(what)
            if what == fail:
                raise update.Failed(f"{what} failed (exit 1)")

        args = types.SimpleNamespace(no_forge=True, no_restart=no_restart, no_smoke=True)
        raised = None
        with mock.patch.object(update, "PIP_NEEDS_STOP", needs_stop), \
                mock.patch.object(update, "changed_files", return_value=list(files)), \
                mock.patch.object(update, "git", return_value="abc"), \
                mock.patch.object(update, "server_answers", return_value=running), \
                mock.patch.object(update, "psycopg_mismatch", return_value=False), \
                mock.patch.object(update, "server_restart_required", return_value=False), \
                mock.patch.object(update, "venv_python", return_value=Path("/srv/.venv/bin/python")), \
                mock.patch.object(update, "step", side_effect=step), \
                mock.patch("decklab.lib.venv.activate", return_value=None), \
                mock.patch("decklab.db.migrate.pending", return_value=list(pending)), \
                mock.patch.object(update, "say"):
            try:
                update._after_pull(args, "abc", done)
            except update.Failed as e:
                raised = e
        return steps, done, raised

    def test_the_server_is_stopped_before_the_backup_on_linux_as_on_windows(self):
        for needs_stop in (False, True):            # Linux and macOS, then Windows
            with self.subTest(pip_needs_stop=needs_stop):
                steps, done, raised = self.run_update(needs_stop=needs_stop)
                self.assertIsNone(raised)
                self.assertEqual(steps, [self.STOP, self.BACKUP, self.MIGRATE, self.RESTART])
                self.assertNotIn("server-stopped", done)        # started again by the restart

    def test_with_none_pending_it_isnt_stopped_early(self):
        steps, done, _ = self.run_update(pending=(), done={"pulled"})
        self.assertEqual(steps, [self.RESTART])
        self.assertNotIn("stopped-for-migration", done)

    def test_a_server_that_isnt_running_is_neither_stopped_nor_started(self):
        steps, done, _ = self.run_update(running=False)
        self.assertEqual(steps, [self.BACKUP, self.MIGRATE])
        self.assertNotIn("server-stopped", done)

    def test_a_server_already_stopped_for_psycopg_is_stopped_once(self):
        steps, _, _ = self.run_update(needs_stop=True, files=[update.REQUIREMENTS])
        self.assertEqual(steps, ["Stop Deck Lab to replace psycopg", "Reinstall psycopg", self.BACKUP, self.MIGRATE,
                                 self.RESTART])
        steps, _, _ = self.run_update(needs_stop=False, files=[update.REQUIREMENTS])      # Linux: pip never stops it
        self.assertEqual(steps, ["Reinstall psycopg", self.STOP, self.BACKUP, self.MIGRATE, self.RESTART])

    def test_no_restart_still_starts_a_server_stopped_for_the_migration(self):
        steps, done, _ = self.run_update(no_restart=True)
        self.assertEqual(steps, [self.STOP, self.BACKUP, self.MIGRATE, "Start Deck Lab again"])
        self.assertNotIn("server-stopped", done)
        steps, _, _ = self.run_update(no_restart=True, pending=())       # nothing stopped: left alone
        self.assertEqual(steps, [])

    def test_a_failed_backup_says_the_server_is_stopped_and_how_to_start_it(self):
        steps, done, raised = self.run_update(fail=self.BACKUP, done={"pulled"})
        self.assertIsNotNone(raised)
        self.assertEqual(steps, [self.STOP, self.BACKUP])               # nothing migrated, nothing restarted
        self.assertLessEqual({"server-stopped", "stopped-for-migration", "backup-failed"}, done)
        self.assertNotIn("migrated", done)
        text = update.way_back("0123456789abcdef", done)
        self.assertIn("Nothing was migrated.", text)
        self.assertIn("Deck Lab is stopped: it was stopped before the backup", text)
        self.assertIn("python -m decklab.lib.homenet start", text)
        self.assertNotIn("decklab.db restore", text)                    # there's nothing to restore
        self.assertNotIn("replace psycopg", text)

    def test_a_failed_migration_says_so_too_and_when_the_code_alone_may_go_back(self):
        steps, done, raised = self.run_update(fail=self.MIGRATE, done={"pulled"})
        self.assertIsNotNone(raised)
        self.assertEqual(steps, [self.STOP, self.BACKUP, self.MIGRATE])
        text = update.way_back("0123456789abcdef", done)
        self.assertIn("Deck Lab is stopped: it was stopped before the backup", text)
        self.assertIn("python -m decklab.lib.homenet start (it then runs the pulled code).", text)
        self.assertIn("git reset --hard 0123456789ab", text)
        self.assertIn("python -m decklab.db restore", text)
        self.assertIn("Going back to the code alone, without the restore, is fine when the migrations that were "
                      "applied only added things", text)
        self.assertIn("the database is newer than the code", text)

    def test_a_failed_stop_backs_up_nothing(self):
        steps, done, raised = self.run_update(fail=self.STOP)
        self.assertIsNotNone(raised)
        self.assertEqual(steps, [self.STOP])
        self.assertEqual(done & {"server-stopped", "migrated", "backup-failed"}, set())

    def test_the_psycopg_stop_keeps_its_own_way_back(self):
        text = update.way_back("0123456789abcdef", {"server-stopped"})
        self.assertEqual(text, "Deck Lab was stopped to replace psycopg: python -m decklab.lib.homenet start.")

    def test_the_documents_state_the_early_stop_and_the_rule(self):
        root = Path(update.__file__).resolve().parents[1]
        hosting = (root / "SELF-HOSTING.md").read_text(encoding="utf-8")
        self.assertIn("with migrations pending, stops the running server", hosting)
        self.assertIn("add in one release, remove in a later one", hosting)
        from decklab.db import migrate
        self.assertIn("add in one release, remove in a later one", migrate.__doc__)
        readme = (root / "decklab" / "README.md").read_text(encoding="utf-8")
        database = readme[readme.index("\n## Database"):]
        self.assertIn("add in one release, remove in a later one", database)


def _digest(migration, counts, digests):
    return {"version": move.DIGEST_VERSION, "migration": migration, "counts": counts, "digests": digests}


class DigestCompareTests(unittest.TestCase):
    def test_the_same_data(self):
        d = _digest(20, {"public.deck": 3}, {"public.deck": "aa"})
        self.assertEqual(move.compare(d, dict(d)), [])

    def test_differences_are_named(self):
        there = _digest(20, {"public.deck": 3, "public.x": 1}, {"public.deck": "aa"})
        here = _digest(20, {"public.deck": 4, "public.y": 1}, {"public.deck": "bb"})
        self.assertEqual(move.compare(there, here), [
            "public.deck has 4 rows here, 3 in the digest file",
            "public.x is missing here",
            "public.y is here but not in the digest file",
            "public.deck's rows differ"])

    def test_newer_migrations_compare_counts_only(self):
        there = _digest(20, {"public.deck": 3}, {"public.deck": "aa"})
        here = _digest(21, {"public.deck": 3, "public.new_table": 0}, {"public.deck": "changed by 21"})
        self.assertEqual(move.compare(there, here), [])
        here["counts"]["public.deck"] = 2
        self.assertEqual(move.compare(there, here), ["public.deck has 2 rows here, 3 in the digest file"])

    def test_read_digest_checks_the_shape(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, folder, True)
        good, bad = folder / "good.json", folder / "bad.json"
        good.write_text(json.dumps(_digest(1, {}, {})), encoding="utf-8")
        bad.write_text('{"counts": {}}', encoding="utf-8")
        self.assertEqual(move.read_digest(good)["migration"], 1)
        with self.assertRaises(ValueError):
            move.read_digest(bad)
        with self.assertRaises(ValueError):
            move.read_digest(folder / "missing.json")

    def test_restoring_name(self):
        self.assertEqual(move._restoring_name("decklab"), "decklab_restoring")
        with self.assertRaises(ValueError):
            move._restoring_name("x" * 60)
        with self.assertRaises(ValueError):
            move._restoring_name("")


if __name__ == "__main__":
    unittest.main()
