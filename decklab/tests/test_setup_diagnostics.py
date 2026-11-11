"""First-run diagnostics use synthetic errors, metadata and disposable paths only."""
from contextlib import redirect_stderr
import io
import threading
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab import server
from decklab.db import conn as db, setup
from decklab.db import __main__ as db_cli
from decklab.lib import db_failures, dbstatus, inventory, preflight, server_http, server_run
from decklab.lib.api import carddata
from decklab.lib.inventory.pg import PgInventory
from decklab.lib.preflight_forge import ForgeFiles
from decklab.tests.test_doctor import Codes


class ConnectionClassificationTests(unittest.TestCase):
    def test_structured_and_recognized_causes_only_produce_fixed_categories(self):
        for value, state, expected in (
                ("SECRET", "28P01", "authentication"), ("SECRET", "28000", "authentication"),
                ("SECRET", "3D000", "setup"), ("connection refused SECRET", None, "network"),
                ("connection timeout expired SECRET", None, "network"),
                ("password authentication failed SECRET", None, "authentication"),
                ('role "SECRET" does not exist', None, "setup"), ("SECRET", "08006", "unknown")):
            error = RuntimeError(value)
            error.sqlstate = state
            with self.subTest(state=state, expected=expected):
                self.assertEqual(db_failures.connection_reason(error), expected)
        self.assertEqual(db_failures.connection_reason(ConnectionRefusedError()), "network")
        self.assertEqual(db_failures.connection_reason(TimeoutError()), "network")
        outer = RuntimeError("SECRET")
        outer.__cause__ = TimeoutError()
        self.assertEqual(db_failures.connection_reason(outer), "network")
        self.assertEqual(db.DbUnavailable("SECRET", reason="authentication").reason, "authentication")

    def test_connection_wrapper_keeps_cause_and_setup_guidance(self):
        class Error(Exception):
            sqlstate = "28P01"
        connector = mock.Mock(side_effect=Error("password authentication failed for SECRET"))
        driver = SimpleNamespace(OperationalError=Error, connect=connector)
        with mock.patch.object(db, "_psycopg", return_value=driver), mock.patch.object(db, "settings", return_value={
                "host": "localhost", "port": 5432, "name": "fixture"}):
            with self.assertRaises(db.DbUnavailable) as caught:
                db.connect()
        self.assertEqual(caught.exception.reason, "authentication")
        self.assertIn("PostgreSQL answered", str(caught.exception))
        self.assertIn("python -m decklab.db setup", str(caught.exception))

    def test_doctor_messages_never_quote_driver_details(self):
        for code in ("database_no_answer", "database_signin_failed", "database_setup_needed"):
            result = preflight.report(Codes({"database": code}))
            text = preflight.text(result)
            self.assertIn("python -m decklab.db", text)
            self.assertEqual(result["exit_code"], 1)
        result = preflight.report(Codes({"runtime": "runtime_unsupported"}), runtime_version=lambda: (3, 13))
        self.assertIn("Python 3.13", preflight.text(result))
        result = preflight.report(Codes({"runtime": "runtime_unsupported"}), runtime_version=lambda: ("SECRET", 13))
        self.assertNotIn("SECRET", preflight.text(result))

    def test_missing_driver_names_venv_creation_before_installation(self):
        with mock.patch.dict(sys.modules, {"psycopg": None}), \
                mock.patch.object(db.venv, "reason", return_value="there is no matching .venv"):
            with self.assertRaises(db.DbUnavailable) as caught:
                db._psycopg()
        self.assertEqual(caught.exception.reason, "driver")
        self.assertIn("python -m venv .venv", str(caught.exception))
        self.assertIn("SELF-HOSTING.md step 3", str(caught.exception))


class SetupAndRuntimeTests(unittest.TestCase):
    def test_unsupported_server_version_is_refused_before_any_role_or_database_write(self):
        from decklab.lib import profiles
        for version in (150010, "SECRET", None):
            connection = mock.MagicMock()
            connection.__enter__.return_value = connection
            connection.execute.return_value.fetchone.return_value = (version,)
            with self.subTest(version=version), mock.patch.object(setup, "_superuser", return_value=connection), \
                    mock.patch.object(profiles, "read_checked", return_value=[]), \
                    mock.patch.object(db, "settings", return_value={"name": "fixture"}), \
                    mock.patch.object(setup, "ensure_roles") as roles, \
                    mock.patch.object(setup, "ensure_database") as database:
                with self.assertRaisesRegex(db.DbUnavailable, "PostgreSQL.*16 or later"):
                    setup._run(say=lambda text: None)
                roles.assert_not_called()
                database.assert_not_called()

    def test_wrong_python_is_named_before_startup_or_cli_work(self):
        problem = db_failures.runtime_problem((3, 13))
        self.assertIn("Python 3.13", problem)
        self.assertIsNone(db_failures.runtime_problem((3, 14)))
        with mock.patch.object(db_failures, "runtime_problem", return_value=problem), \
                mock.patch.object(server_run, "_serve") as serve, \
                mock.patch.object(server_http, "log") as log:
            self.assertEqual(server.main(["--no-update"]), 1)
        serve.assert_not_called()
        log.assert_called_once_with(problem)
        parsed = SimpleNamespace(func=mock.Mock(), command="status")
        with mock.patch.object(db_failures, "runtime_problem", return_value=problem), \
                mock.patch.object(db_cli, "parser", return_value=SimpleNamespace(parse_args=lambda args: parsed)), \
                redirect_stderr(io.StringIO()) as output:
            self.assertEqual(db_cli.main([]), 1)
        parsed.func.assert_not_called()
        self.assertIn("Python 3.13", output.getvalue())

    def test_never_configured_simulations_are_one_neutral_optional_finding(self):
        files = ForgeFiles(settings=lambda: {"_decklab_simulations_selected": False}, platform="nt")
        self.assertEqual(files.probe("java"), "simulations_not_set_up")
        self.assertEqual(files.probe("forge"), "simulations_not_set_up")
        result = preflight.report(Codes({"java": "simulations_not_set_up", "forge": "simulations_not_set_up"}))
        self.assertEqual(result["optional_files_status"], "not_configured")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(preflight.text(result).count("OPTIONAL Simulations not set up"), 1)


class RetainedSnapshotTests(unittest.TestCase):
    def test_status_never_loads_inventory_and_only_claims_a_real_retained_snapshot(self):
        fake = SimpleNamespace(cached_snapshot_available=lambda: False)
        with inventory.use(fake), mock.patch.object(inventory, "_database", side_effect=AssertionError("no startup")):
            result = dbstatus.inventory_view({"usable": False, "inventory": None})
            self.assertTrue(result["unavailable"])
            self.assertFalse(result["stale"])
            fake.cached_snapshot_available = lambda: True
            self.assertTrue(dbstatus.inventory_view({"usable": False, "inventory": None})["stale"])
        backend = SimpleNamespace(_lock=threading.Lock(), _cache=None, _decks=None, _migrated=False)
        self.assertFalse(PgInventory.cached_snapshot_available(backend))
        backend._cache = object()
        self.assertTrue(PgInventory.cached_snapshot_available(backend))
        backend._migrated = True
        self.assertFalse(PgInventory.cached_snapshot_available(backend))

    def test_first_index_download_is_worded_as_progress(self):
        with mock.patch.object(carddata.cards, "info", side_effect=FileNotFoundError("SECRET")), \
                mock.patch.object(carddata, "_last_index_error", [None]), \
                mock.patch.dict(carddata.UPDATE, running=True), mock.patch.object(carddata.common, "_log") as log:
            carddata._index_info()
        self.assertIn("being downloaded", log.call_args.args[0])
        self.assertNotIn("SECRET", log.call_args.args[0])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class SetupWordingUiTests(unittest.TestCase):
    def test_first_use_does_not_claim_a_cached_snapshot_or_tell_a_new_install_to_restore(self):
        from decklab.tests.test_web import _run_page
        messages = _run_page([
            "databaseMessages({ok:false,error:'no answer',inventory:{stale:false,unavailable:true}}).join(' ')",
            "databaseMessages({ok:false,error:'sign-in refused'}).join(' ')",
            "databaseMessages({ok:true,inventory:{not_imported:true}}).join(' ')",
            "databaseMessages({ok:false,inventory:{stale:true}}).join(' ')"], names=("version.js",))
        self.assertIn("Nothing answered", messages[0])
        self.assertNotIn("as they were", messages[0])
        self.assertNotIn("Try again in a minute", messages[0])
        self.assertIn("PostgreSQL answered", messages[1])
        self.assertIn("python -m decklab.db setup", messages[1])
        self.assertIn("On a new install", messages[2])
        self.assertIn("restore", messages[2])
        self.assertIn("as they were", messages[3])
