"""Tests for the database's folder settings off Windows (lib/pathsetting.py, conn.path_setting,
conn.pg_bin's Linux folders) and the backups' guards against an unmounted NAS share
(backup.same_device_problem, copy_to's leaf-only folder), plus setup's next steps for a
pg_hba.conf that won't take a password and a cluster locale that can't hold UTF8.

Nothing here needs PostgreSQL, psycopg, a NAS or Linux: the platform is passed in or patched
(pathsetting.on_posix, conn._on_windows), and stat, dump and record are fakes, so every test
runs the same on Windows and Linux CI.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_db_paths
"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from decklab.db import backup, conn as db, export, setup
from decklab.lib import config, pathsetting, venv

UNC = "\\\\NAS\\Backups\\DeckLab"
HAS_PSYCOPG = importlib.util.find_spec("psycopg") is not None


def _temp(test):
    tmp = Path(tempfile.mkdtemp(prefix="decklab-paths-test-"))
    test.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


class NormaliseTests(unittest.TestCase):

    def test_unset_and_blank_values_are_none(self):
        for posix in (True, False):
            for value in (None, "", "   "):
                self.assertIsNone(pathsetting.normalise("database.backup_dir", value, posix=posix))

    def test_windows_keeps_its_values(self):
        self.assertEqual(pathsetting.normalise("database.backup_dir", UNC, posix=False), UNC)
        self.assertEqual(pathsetting.normalise("database.staging_dir", "D:\\Backups", posix=False), "D:\\Backups")

    def test_off_windows_a_network_path_is_refused_naming_the_setting(self):
        with self.assertRaises(pathsetting.PathSettingError) as caught:
            pathsetting.normalise("database.backup_dir", UNC, posix=True)
        text = str(caught.exception)
        self.assertIn("database.backup_dir", text)
        self.assertIn("Windows network path", text)
        self.assertIn("Mount the share", text)
        self.assertIn("/mnt/nas/DeckLab", text)
        self.assertIsInstance(caught.exception, ValueError)

    def test_off_windows_drive_letters_backslashes_and_relative_paths_are_refused(self):
        for value in ("D:\\Backups\\DeckLab", "C:/Backups", "C:", "backups\\deck", "backups", "./backups",
                      "../DeckLabData"):
            with self.subTest(value=value), self.assertRaises(pathsetting.PathSettingError) as caught:
                pathsetting.normalise("database.export_repo", value, posix=True)
            self.assertIn("database.export_repo", str(caught.exception))

    def test_off_windows_absolute_and_home_paths_are_used(self):
        self.assertEqual(pathsetting.normalise("database.backup_dir", " /mnt/nas/DeckLab ", posix=True),
                         "/mnt/nas/DeckLab")
        with mock.patch.dict(os.environ, {"HOME": "/home/deck"}):
            self.assertEqual(pathsetting.normalise("records_repo", "~/TradingCardCollection", posix=True),
                             "/home/deck/TradingCardCollection")

    def test_a_value_that_is_not_text_is_refused(self):
        for posix in (True, False):
            with self.assertRaisesRegex(pathsetting.PathSettingError, "database.pg_bin"):
                pathsetting.normalise("database.pg_bin", 18, posix=posix)

    def test_path_setting_reads_the_database_block(self):
        with mock.patch.object(pathsetting, "on_posix", return_value=True):
            self.assertEqual(db.path_setting("backup_dir", {"backup_dir": "/mnt/nas"}), "/mnt/nas")
            self.assertIsNone(db.path_setting("backup_dir", {"backup_dir": None}))
            with self.assertRaisesRegex(ValueError, "database.staging_dir"):
                db.path_setting("staging_dir", {"staging_dir": "data\\backups"})


class PgBinTests(unittest.TestCase):

    def setUp(self):
        self.tmp = _temp(self)
        self.settings = {"pg_bin": None}
        for patcher in (mock.patch.object(db, "settings", lambda: dict(self.settings)),):
            patcher.start()
            self.addCleanup(patcher.stop)

    def program(self, *parts):
        path = self.tmp.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        return path

    def posix(self, roots=None):
        roots = roots if roots is not None else ((self.tmp / "lib" / "postgresql", "*/bin"), (self.tmp, "pgsql-*/bin"))
        return [mock.patch.object(db, "_on_windows", return_value=False),
                mock.patch.object(pathsetting, "on_posix", return_value=True),
                mock.patch.object(db, "POSIX_PG_ROOTS", roots)]

    def run_with(self, patches, func):
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return func()

    def test_linux_takes_the_newest_version_folder_debian_or_rhel(self):
        self.program("lib", "postgresql", "16", "bin", "pg_dump")
        newest = self.program("lib", "postgresql", "18", "bin", "pg_dump")
        self.program("pgsql-17", "bin", "pg_dump")
        with mock.patch("shutil.which", side_effect=AssertionError("PATH looked at")):
            self.assertEqual(self.run_with(self.posix(), lambda: db.pg_bin("pg_dump")), newest)

    def test_linux_finds_rhel_folders_off_the_path(self):
        rhel = self.program("pgsql-18", "bin", "pg_restore")
        self.program("lib", "postgresql", "9.6", "bin", "pg_restore")
        self.assertEqual(self.run_with(self.posix(), lambda: db.pg_bin("pg_restore")), rhel)

    def test_linux_falls_back_to_the_path_and_says_where_it_looked(self):
        self.run_with(self.posix(), lambda: None)
        with mock.patch("shutil.which", return_value="/usr/bin/pg_dump"):
            self.assertEqual(db.pg_bin("pg_dump"), Path("/usr/bin/pg_dump"))
        with mock.patch("shutil.which", return_value=None), self.assertRaises(FileNotFoundError) as caught:
            db.pg_bin("pg_dump")
        text = str(caught.exception)
        self.assertIn("pgsql-*/bin", text)
        self.assertNotIn("Program Files", text)
        self.assertNotIn(".exe", text)

    def test_linux_refuses_a_windows_pg_bin_setting(self):
        self.settings["pg_bin"] = "C:\\Program Files\\PostgreSQL\\18\\bin"
        self.run_with(self.posix(), lambda: None)
        with self.assertRaisesRegex(FileNotFoundError, "database.pg_bin"):
            db.pg_bin("pg_dump")

    def test_windows_looks_in_program_files_never_the_linux_folders(self):
        self.program("lib", "postgresql", "19", "bin", "pg_dump.exe")
        wanted = self.program("Programs", "PostgreSQL", "17", "bin", "pg_dump.exe")
        self.run_with([mock.patch.object(db, "_on_windows", return_value=True),
                       mock.patch.object(pathsetting, "on_posix", return_value=False),
                       mock.patch.object(db, "PG_BIN_DEFAULT", str(self.tmp / "absent")),
                       mock.patch.object(db, "POSIX_PG_ROOTS", ((self.tmp / "lib" / "postgresql", "*/bin"),)),
                       mock.patch.dict(os.environ, {"ProgramFiles": str(self.tmp / "Programs")})], lambda: None)
        self.assertEqual(db.pg_bin("pg_dump"), wanted)

    def test_version_folders_sort_by_number(self):
        names = ["9.6", "pgsql-16", "10", "18", "17.2"]
        self.assertEqual(sorted(names, key=db._version_key), ["9.6", "10", "pgsql-16", "17.2", "18"])


class PsycopgHintTests(unittest.TestCase):

    def test_each_system_gets_its_own_venv_command(self):
        self.assertEqual(venv.pip_hint(windows=True),
                         ".venv\\Scripts\\python -m pip install -r decklab/requirements.txt")
        self.assertEqual(venv.pip_hint(windows=False), ".venv/bin/python -m pip install -r decklab/requirements.txt")

    def test_a_missing_psycopg_names_this_systems_command(self):
        with mock.patch.dict(sys.modules, {"psycopg": None}), self.assertRaises(db.DbUnavailable) as caught:
            db._psycopg()
        self.assertIn(venv.pip_hint(), str(caught.exception))


class RecordedNameTests(unittest.TestCase):

    def test_a_path_written_on_windows_matches_on_any_system(self):
        name = "decklab-2026-10-31-033000.dump"
        for path in (UNC + "\\" + name, "C:\\Projects\\DeckLab\\decklab\\data\\backups\\" + name,
                     "/mnt/nas/DeckLab/" + name, name):
            with self.subTest(path=path):
                self.assertEqual(backup.dump_basename(path), name)

    def test_recorded_finds_a_windows_row_without_a_database(self):
        name = "decklab-2026-10-31-033000.dump"
        rows = [(UNC + "\\" + name, backup.dump_detail({"public.deck": 3}), {"public.deck": "x"})]
        conn = mock.MagicMock()
        conn.__enter__.return_value.execute.return_value.fetchall.return_value = rows
        with mock.patch.object(db, "connect", return_value=conn):
            self.assertEqual(backup.recorded(name), ({"public.deck": 3}, {"public.deck": "x"}))


def _stat(devices):
    """A fake os.stat: devices maps a Path to its st_dev; anything else isn't there."""
    def stat(path):
        try:
            return SimpleNamespace(st_dev=devices[Path(path)])
        except KeyError:
            raise FileNotFoundError(path) from None
    return stat


class SameDeviceTests(unittest.TestCase):
    staging = Path("/home/deck/DeckLab/decklab/data/backups")
    share = Path("/mnt/nas/DeckLab")

    def problem(self, devices, s=None, posix=True, folder=None):
        return backup.same_device_problem(folder or self.share, self.staging, s or {}, stat=_stat(devices),
                                          posix=posix)

    def test_an_unmounted_share_is_refused(self):
        # The share isn't mounted: /mnt/nas is a bare folder on the local disk, DeckLab isn't there.
        text = self.problem({self.share.parent: 1, self.staging: 1})
        self.assertIn("is the NAS share mounted?", text)
        self.assertIn(backup.SAME_DEVICE_OK, text)
        # The mount point itself as backup_dir, empty and local.
        self.assertIsNotNone(self.problem({self.share: 1, self.staging: 1}))

    def test_a_mounted_share_is_fine(self):
        self.assertIsNone(self.problem({self.share: 7, self.share.parent: 1, self.staging: 1}))
        self.assertIsNone(self.problem({self.share.parent: 7, self.staging: 1}))

    def test_staging_not_made_yet_compares_with_the_data_folder(self):
        self.assertIsNotNone(self.problem({self.share.parent: 1, config.DATA: 1}))
        self.assertIsNone(self.problem({self.share.parent: 1}))

    def test_the_opt_out_and_windows_never_refuse(self):
        devices = {self.share.parent: 1, self.staging: 1}
        self.assertIsNone(self.problem(devices, s={backup.SAME_DEVICE_OK: True}))
        self.assertIsNotNone(self.problem(devices, s={backup.SAME_DEVICE_OK: "yes"}))     # only true opts out
        self.assertIsNone(self.problem(devices, posix=False))

    def test_a_place_that_cant_be_read_is_left_to_the_copy(self):
        def denied(path):
            raise PermissionError(path)
        self.assertIsNone(backup.same_device_problem(self.share, self.staging, {}, stat=denied, posix=True))


class CopyToTests(unittest.TestCase):

    def setUp(self):
        self.tmp = _temp(self)
        self.dump = self.tmp / "decklab-2026-10-31-033000.dump"
        self.dump.write_bytes(b"dump")

    def test_only_the_leaf_folder_is_made(self):
        copy = backup.copy_to(self.dump, self.tmp / "DeckLab")
        self.assertEqual(copy.read_bytes(), b"dump")
        with self.assertRaises(OSError):
            backup.copy_to(self.dump, self.tmp / "share" / "DeckLab")
        self.assertFalse((self.tmp / "share").exists())

    def test_a_same_device_problem_stops_the_copy_before_any_folder(self):
        with mock.patch.object(pathsetting, "on_posix", return_value=True), \
                self.assertRaisesRegex(OSError, "NAS share mounted"):
            backup.copy_to(self.dump, self.tmp / "DeckLab", staging=self.tmp, s={})
        self.assertFalse((self.tmp / "DeckLab").exists())


class _Commands(unittest.TestCase):
    """run_backup, run_prune, run_export and run_restore_check with fake settings, dump and
    record: no database. Folder settings pass through path_setting's own normaliser, with this
    system's checks unless a test patches pathsetting.on_posix."""

    def setUp(self):
        self.tmp = _temp(self)
        self.settings = {"name": "decklab", "backup_dir": None, "staging_dir": str(self.tmp / "staging"),
                         "export_repo": str(self.tmp / "export"), "keep_daily": 14, "keep_weekly": 8}
        self.records, self.said = [], []
        for p in (mock.patch.object(db, "settings", lambda: dict(self.settings)),
                  mock.patch.object(db, "pg_bin", return_value=Path("pg_dump")),
                  mock.patch.object(backup, "dump", self.fake_dump),
                  mock.patch.object(backup, "record", self.fake_record)):
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def fake_dump(target, s=None):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(b"dump")
        return True, {"public.deck": 1}, {"public.deck": "d"}, ""

    def fake_record(self, kind, started, ok, path=None, size=None, detail=None, dbname=None, digests=None):
        self.records.append((kind, ok, path, detail))
        return len(self.records)

    def posix_paths(self):
        """Off-Windows checks with this system's real temporary folders: the Windows-path test
        is applied only to values the test chose, as a Linux PC would see them."""
        real = pathsetting.normalise

        def normalise(key, value, posix=None):
            if isinstance(value, str) and value.startswith(str(self.tmp)):
                return real(key, value, posix=False)
            return real(key, value, posix=True)
        for p in (mock.patch.object(pathsetting, "on_posix", return_value=True),
                  mock.patch.object(pathsetting, "normalise", normalise)):
            p.start()
            self.addCleanup(p.stop)


class BackupCommandTests(_Commands):

    def test_a_windows_backup_dir_still_dumps_and_fails_the_copy(self):
        self.posix_paths()
        self.settings["backup_dir"] = UNC
        cwd = os.getcwd()
        self.assertEqual(backup.run_backup(say=self.said.append), 1)
        (kind, ok, path, detail), = self.records
        self.assertFalse(ok)
        self.assertIn("database.backup_dir", detail)
        self.assertIn("Windows network path", detail)
        self.assertIn("The local copy is kept", self.said[-1])
        self.assertEqual(len(backup.dumps_in(self.tmp / "staging")), 1)
        self.assertFalse(Path(cwd, UNC).exists())

    def test_a_windows_staging_dir_fails_before_dumping(self):
        self.posix_paths()
        self.settings["staging_dir"] = "D:\\DeckLab\\backups"
        self.assertEqual(backup.run_backup(say=self.said.append), 1)
        (kind, ok, path, detail), = self.records
        self.assertFalse(ok)
        self.assertIn("database.staging_dir", detail)
        self.assertFalse((self.tmp / "staging").exists())

    def test_a_share_on_the_staging_disk_is_refused_off_windows(self):
        self.posix_paths()
        self.settings["backup_dir"] = str(self.tmp / "mnt" / "DeckLab")
        (self.tmp / "mnt").mkdir()
        self.assertEqual(backup.run_backup(say=self.said.append), 1)
        self.assertIn("NAS share mounted", self.records[-1][3])
        self.assertFalse((self.tmp / "mnt" / "DeckLab").exists())
        self.settings[backup.SAME_DEVICE_OK] = True
        self.assertEqual(backup.run_backup(say=self.said.append), 0, self.said)
        self.assertEqual(len(backup.dumps_in(self.tmp / "mnt" / "DeckLab")), 1)

    def test_a_missing_share_root_is_never_made(self):
        self.settings["backup_dir"] = str(self.tmp / "absent" / "DeckLab")
        self.assertEqual(backup.run_backup(say=self.said.append), 1)
        self.assertFalse((self.tmp / "absent").exists())
        self.assertIn("copy to", self.records[-1][3])

    def test_windows_copies_to_a_folder_on_the_same_disk_as_before(self):
        with mock.patch.object(pathsetting, "on_posix", return_value=False):
            self.settings["backup_dir"] = str(self.tmp / "DeckLab")
            self.assertEqual(backup.run_backup(say=self.said.append), 0, self.said)
        self.assertTrue(self.records[-1][1])

    def test_a_dest_given_by_hand_is_not_checked_for_its_disk(self):
        self.posix_paths()
        self.assertEqual(backup.run_backup(dest=self.tmp / "usb", say=self.said.append), 0, self.said)


class PruneAndRestoreCommandTests(_Commands):

    def test_prune_fails_on_a_windows_backup_dir_but_prunes_staging(self):
        self.posix_paths()
        self.settings["backup_dir"] = UNC
        (self.tmp / "staging").mkdir()
        self.assertEqual(backup.run_prune(say=self.said.append), 1)
        self.assertIn("database.backup_dir", self.said[0])
        self.assertTrue(any("Prune (staging)" in line for line in self.said))

    def test_prune_refuses_an_empty_mount_point_on_the_staging_disk(self):
        self.posix_paths()
        (self.tmp / "staging").mkdir()
        (self.tmp / "nas").mkdir()
        self.settings["backup_dir"] = str(self.tmp / "nas")
        self.assertEqual(backup.run_prune(say=self.said.append), 1)
        self.assertIn("NAS share mounted", self.said[0])
        self.settings[backup.SAME_DEVICE_OK] = True
        self.said.clear()
        self.assertEqual(backup.run_prune(say=self.said.append), 0, self.said)

    def test_restore_check_records_an_unusable_backup_dir(self):
        self.posix_paths()
        for value, words in ((UNC, "database.backup_dir"), (str(self.tmp), "NAS share mounted")):
            with self.subTest(value=value):
                self.records.clear()
                self.settings["backup_dir"] = value
                (self.tmp / "staging").mkdir(exist_ok=True)
                self.assertEqual(backup.run_restore_check(say=self.said.append), 1)
                (kind, ok, path, detail), = self.records
                self.assertEqual((kind, ok), ("restore_check", False))
                self.assertIn(words, detail)

    def test_export_records_an_unusable_export_repo(self):
        self.posix_paths()
        self.settings["export_repo"] = "..\\DeckLabData"
        self.assertEqual(export.run_export(say=self.said.append), 1)
        (kind, ok, path, detail), = self.records
        self.assertEqual((kind, ok), ("export", False))
        self.assertIn("database.export_repo", detail)
        self.assertFalse(Path(os.getcwd(), "..\\DeckLabData").exists())


class RecordsRepoTests(unittest.TestCase):

    def test_off_windows_a_windows_records_repo_is_said_once_and_kept(self):
        value = "C:\\Projects\\TradingCardCollection"
        err = io.StringIO()
        with mock.patch.object(config, "load", return_value={"records_repo": value}), \
                mock.patch.object(config, "CHECKOUT", config.REPO), \
                mock.patch.object(pathsetting, "on_posix", return_value=True), \
                mock.patch.object(config, "_said", set()), redirect_stderr(err):
            self.assertEqual(config.records_dir(), Path(value))
            config.records_dir()
        self.assertEqual(err.getvalue().count("records_repo"), 1)

    def test_the_smoke_test_fails_on_a_windows_records_repo_off_windows(self):
        from decklab import smoke
        r = smoke.Result("records", "Records")
        with mock.patch.object(config, "load", return_value={"records_repo": "C:\\Records"}), \
                mock.patch.object(pathsetting, "on_posix", return_value=True):
            smoke.step_records(r, {"doctor": {"config": "ready"}})
        self.assertEqual(r.status, smoke.FAIL)
        self.assertIn("records_repo", r.lines[0][1])

    def test_a_home_records_repo_is_expanded(self):
        with mock.patch.object(config, "load", return_value={"records_repo": "~/Records"}), \
                mock.patch.object(config, "CHECKOUT", config.REPO), \
                mock.patch.object(pathsetting, "on_posix", return_value=True), \
                mock.patch.dict(os.environ, {"HOME": "/home/deck"}):
            self.assertEqual(config.records_dir(), Path("/home/deck/Records"))


class SuperuserMethodTests(unittest.TestCase):
    ident = db.DbUnavailable("can't reach PostgreSQL at localhost:5432 as postgres (database postgres): "
                             'FATAL:  Ident authentication failed for user "postgres"')
    wrong = db.DbUnavailable("can't reach PostgreSQL at localhost:5432 as postgres (database postgres): "
                             'FATAL:  password authentication failed for user "postgres"')
    empty = db.DbUnavailable("can't reach PostgreSQL ...: fe_sendauth: no password supplied")

    def test_an_ident_or_peer_login_says_how_to_allow_passwords(self):
        for posix in (True, False):
            with self.subTest(posix=posix), mock.patch.object(pathsetting, "on_posix", return_value=posix), \
                    mock.patch.object(db, "connect", side_effect=self.ident), \
                    self.assertRaises(db.DbUnavailable) as caught:
                setup._superuser(say=lambda _: None, ask=mock.Mock(side_effect=AssertionError("asked")),
                                 interactive=True)
            text = str(caught.exception)
            self.assertIn("pg_hba.conf", text)
            self.assertIn("scram-sha-256", text)
            self.assertIn("python -m decklab.db setup again", text)
            self.assertEqual("sudo -u postgres psql" in text, posix)

    def test_a_wrong_typed_password_says_how_to_set_one(self):
        with mock.patch.object(pathsetting, "on_posix", return_value=True), \
                mock.patch.object(db, "connect", side_effect=[self.empty, self.wrong]), \
                self.assertRaises(db.DbUnavailable) as caught:
            setup._superuser(say=lambda _: None, ask=lambda _: "typed-secret", interactive=True)
        text = str(caught.exception)
        self.assertIn('sudo -u postgres psql -c "\\password postgres"', text)
        self.assertNotIn("typed-secret", text)


class LocaleHintTests(unittest.TestCase):

    def test_only_a_locale_refusal_gets_the_hint(self):
        refused = 'encoding "UTF8" does not match locale "en_US"'
        self.assertIn("initdb --locale=C.UTF-8", db.locale_hint(Exception(refused)))
        self.assertIn("UTF-8", db.locale_hint(Exception('The chosen LC_CTYPE setting requires encoding "LATIN1".')))
        self.assertEqual(db.locale_hint(Exception("permission denied to create database")), "")

    @unittest.skipUnless(HAS_PSYCOPG, "psycopg isn't installed for this Python")
    def test_setup_explains_a_cluster_that_cant_hold_utf8(self):
        import psycopg
        c = mock.MagicMock()
        c.execute.side_effect = [mock.Mock(fetchone=lambda: None),
                                 psycopg.Error('encoding "UTF8" does not match locale "en_US"')]
        with self.assertRaisesRegex(db.DbUnavailable, "initdb --locale"):
            setup.ensure_database(c, "decklab", say=lambda _: None)


if __name__ == "__main__":
    unittest.main()
