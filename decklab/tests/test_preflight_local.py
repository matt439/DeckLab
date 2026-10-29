"""Core preflight adapters use disposable files and fake drivers, never configured hosts."""
from contextlib import contextmanager
import gzip
import hashlib
import json
from pathlib import Path
import site
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.request

from decklab.db import conn as db
from decklab.lib import card_index, config, preflight_local as local
from decklab.lib.card_index import ROLE_TAGS


class FakeConnection:
    def __init__(self, checksum):
        self.version = 160004
        self.exists = True
        self.rows = [(1, checksum)]
        self.initialized = (True, True)
        self.calls = []
        self.active = False
        self.closed = 0
        self.error = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @contextmanager
    def transaction(self):
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def execute(self, sql, params=None):
        if not self.active:
            raise AssertionError("No metadata may be read outside the read-only transaction")
        if not self.calls and sql != local.READ_ONLY:
            raise AssertionError("Read-only must precede every query")
        self.calls.append((sql, params))
        if self.error is not None:
            raise self.error
        if sql == local.READ_ONLY:
            return SimpleNamespace()
        if sql == local.VERSION_SQL:
            return SimpleNamespace(fetchone=lambda: (self.version,))
        if sql == local.LEDGER_EXISTS:
            return SimpleNamespace(fetchone=lambda: (self.exists,))
        if sql == local.LEDGER_SQL:
            return SimpleNamespace(fetchall=lambda: self.rows)
        if sql == local.INITIALIZED:
            return SimpleNamespace(fetchone=lambda: self.initialized)
        raise AssertionError("Unexpected query")

    def close(self):
        self.closed += 1


class LocalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="decklab-preflight-local-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = {"profiles": [{"id": "user1", "name": "User1", "space": "home", "plays_as": "user",
                                 "role": "admin", "emails": ["user1@example.com"]}]}
        self.write_config()
        self.sql = b"select 1;\n"
        self.write("decklab/db/migrations/0001_foundation.sql", self.sql)
        self.checksum = hashlib.sha256(self.sql).hexdigest()
        self.connection = FakeConnection(self.checksum)
        self.connector = mock.Mock(return_value=self.connection)
        self.driver = SimpleNamespace(connect=self.connector)
        self.finder = mock.Mock(return_value=SimpleNamespace())
        self.importer = mock.Mock(return_value=self.driver)
        self.base = str(self.root / "python" / "python.exe")
        card = {"name": "Fixture Card", "oracle_id": "fixture-oracle", "paper": True,
                "roles": [], "printings": [["set", "1"]], "game_changer": False, "layout": "normal",
                "mana_cost": "{1}", "cmc": 1, "type_line": "Creature", "oracle_text": "",
                "colors": [], "color_identity": [], "keywords": [], "produced_mana": [],
                "commander_legality": "legal", "power": "1", "toughness": "1",
                "loyalty": None, "defense": None}
        printing = {"name": "Fixture Card", "oracle_id": "fixture-oracle", "finishes": ["nonfoil"],
                    "games": ["paper"], "digital": False, "oversized": False, "set_type": "core",
                    "usd": None, "usd_foil": None, "usd_etched": None}
        self.card_data = {"version": 4, "built_at": "2026-10-28T00:00:00+00:00", "bulk": {},
                          "cards": {"Fixture Card": card}, "printings": {"set": {"1": printing}},
                          "variants": {}, "tokens": {},
                          "roles": {role: {"tag": tag, "oracle_cards": 0} for role, tag in ROLE_TAGS.items()}}
        self.write_cards()
        # Fail safely even if an adapter accidentally invokes an established application
        # loader or ignores an injected driver. These never forward to real dependencies.
        for owner, name in ((db, "connect"), (db, "settings"), (db, "_psycopg"), (db, "log"),
                            (config, "load"), (site, "addsitedir"), (socket, "socket"),
                            (socket, "create_connection"), (urllib.request, "urlopen"),
                            (local, "_import_driver")):
            self.enterContext(mock.patch.object(owner, name, side_effect=AssertionError("Forbidden real dependency")))
        self.original_open = Path.open
        self.original_stat = Path.stat
        self.original_iterdir = Path.iterdir
        self.original_gzip = gzip.open

        def inside(path):
            if not Path(path).absolute().is_relative_to(self.root.absolute()):
                raise AssertionError("No file outside the disposable root may be probed")

        def opened(path, *args, **kwargs):
            inside(path)
            return self.original_open(path, *args, **kwargs)

        def stat(path, *args, **kwargs):
            inside(path)
            return self.original_stat(path, *args, **kwargs)

        def iterdir(path):
            inside(path)
            return self.original_iterdir(path)

        def gzipped(path, *args, **kwargs):
            inside(path)
            return self.original_gzip(path, *args, **kwargs)

        self.enterContext(mock.patch.object(Path, "open", opened))
        self.enterContext(mock.patch.object(Path, "stat", stat))
        self.enterContext(mock.patch.object(Path, "iterdir", iterdir))
        self.enterContext(mock.patch.object(gzip, "open", gzipped))

    def write(self, path, raw):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def write_config(self):
        return self.write("decklab/config.json", json.dumps(self.raw).encode())

    def write_cards(self):
        return self.write("decklab/data/scryfall/index.json.gz", gzip.compress(json.dumps(self.card_data).encode()))

    def adapter(self, **kwargs):
        options = {"root": self.root, "version": (3, 14), "platform": "win32", "environ": {},
                   "find_driver": self.finder, "import_driver": self.importer,
                   "base_executable": self.base, "search_path": ["fixture-packages"]}
        options.update(kwargs)
        return local.Local(**options)

    def venv(self, *, version="3.14.1", home=None, platform="win32"):
        home = str(Path(self.base).parent) if home is None else home
        self.write(".venv/pyvenv.cfg", f"home = {home}\nversion = {version}\n".encode())
        packages = ".venv/Lib/site-packages" if platform == "win32" else ".venv/lib/python3.14/site-packages"
        (self.root / packages).mkdir(parents=True, exist_ok=True)
        return self.root / packages

    def test_construction_and_settings_getter_do_no_work(self):
        read = mock.Mock(side_effect=AssertionError("Read during construction"))
        adapter = self.adapter(read_file=read)
        self.assertIsNone(adapter.settings)
        read.assert_not_called()
        self.finder.assert_not_called()
        self.connector.assert_not_called()

    def test_supported_runtime_and_unsupported_runtime_do_not_read_files(self):
        read = mock.Mock(side_effect=AssertionError("Runtime reads files"))
        for platform in ("win32", "linux", "darwin"):
            self.assertEqual(self.adapter(platform=platform, read_file=read).probe("runtime"), "runtime_ready")
        for version, platform in (((3, 13), "win32"), ((3, 15), "linux"), ((3, 14), "unknown")):
            self.assertEqual(self.adapter(version=version, platform=platform).probe("runtime"), "runtime_unsupported")

    def test_unknown_probe_is_refused_without_reads(self):
        with self.assertRaises(ValueError):
            self.adapter().probe("private-value")
        self.connector.assert_not_called()

    def test_valid_config_is_captured_once_without_private_values_in_result(self):
        self.raw["database"] = {"host": "fixture.invalid", "port": 5433, "name": "fixture_database"}
        self.write_config()
        adapter = self.adapter(environ={"DECKLAB_DB_NAME": "fixture_override"})
        self.assertEqual(adapter.probe("config"), "config_ready")
        self.assertEqual(adapter.settings["database"], {"host": "fixture.invalid", "port": 5433, "name": "fixture_override"})
        self.write("decklab/config.json", b"damaged later")
        self.assertEqual(adapter.probe("config"), "config_ready")

    def test_missing_unreadable_oversized_and_malformed_config_fail_closed(self):
        for error, code in ((FileNotFoundError(), "config_missing"), (OSError("SECRET"), "config_unavailable"),
                            (local.TooLarge(), "config_invalid")):
            read = mock.Mock(side_effect=error)
            adapter = self.adapter(read_file=read)
            self.assertEqual(adapter.probe("config"), code)
            self.assertIsNone(adapter.settings)
        for raw in (b"[]", b"{", b'{"profiles":[],"profiles":[]}', b'{"profiles":NaN}', b"\xff"):
            self.write("decklab/config.json", raw)
            self.assertEqual(self.adapter().probe("config"), "config_invalid")

    def test_pending_publication_and_overlay_refuse_before_config_read(self):
        read = mock.Mock(side_effect=AssertionError("Config read despite gate"))
        self.assertEqual(self.adapter(read_file=read, environ={"DECKLAB_CONFIG_EXTRA": "SECRET"}).probe("config"),
                         "config_override_active")
        self.write("decklab/data/profile-config/pending.json", b"NOT READ")
        self.assertEqual(self.adapter(read_file=read).probe("config"), "config_profile_pending")
        read.assert_not_called()

    def test_invalid_profiles_and_missing_home_profile_are_distinct(self):
        self.raw["profiles"].append(dict(self.raw["profiles"][0]))
        self.write_config()
        self.assertEqual(self.adapter().probe("config"), "config_profiles_invalid")
        self.raw["profiles"] = [{"id": "user2", "name": "User2", "space": "user2", "role": "member"}]
        self.write_config()
        self.assertEqual(self.adapter().probe("config"), "config_no_home_profile")

    def test_invalid_ports_database_and_access_values_are_not_echoed(self):
        for changed in ({"port": True}, {"host": "bad\nSECRET"}, {"database": []},
                        {"database": {"port": "bad"}}, {"database": {"host": ""}},
                        {"database": {"name": "SECRET\n"}}, {"access": {"team": "SECRET"}}):
            original = dict(self.raw)
            self.raw.update(changed)
            self.write_config()
            adapter = self.adapter()
            self.assertEqual(adapter.probe("config"), "config_invalid")
            self.assertIsNone(adapter.settings)
            self.raw = original

    def test_allowed_host_shapes_are_checked_without_resolving_them(self):
        for value in (42, True, [42], ["bad\nSECRET"]):
            self.raw["allowed_hosts"] = value
            self.write_config()
            self.assertEqual(self.adapter().probe("config"), "config_invalid")
        self.raw["allowed_hosts"] = ["fixture.invalid"]
        self.write_config()
        self.assertEqual(self.adapter().probe("config"), "config_ready")

    def test_numeric_string_database_port_preserves_existing_connector_normalization(self):
        self.raw["database"] = {"port": "5433"}
        self.write_config()
        adapter = self.adapter()
        self.assertEqual(adapter.probe("database"), "database_ready")
        self.assertEqual(self.connector.call_args.kwargs["port"], 5433)

    def test_driver_missing_never_imports_or_connects(self):
        self.finder.return_value = None
        self.assertEqual(self.adapter().probe("driver"), "driver_missing")
        self.importer.assert_not_called()
        self.connector.assert_not_called()

    def test_runtime_failure_prevents_driver_discovery(self):
        self.assertEqual(self.adapter(version=(3, 13)).probe("driver"), "driver_unusable")
        self.finder.assert_not_called()

    def test_driver_venv_mismatch_is_not_hidden_by_another_install(self):
        self.venv(version="3.13.9")
        self.assertEqual(self.adapter().probe("driver"), "driver_venv_mismatch")
        self.finder.assert_not_called()
        self.venv(home=str(self.root / "other-python"))
        self.assertEqual(self.adapter().probe("driver"), "driver_venv_mismatch")

    def test_matching_venv_import_uses_direct_path_without_pth_or_bytecode(self):
        packages = self.venv()
        marker = self.root / "pth-ran"
        self.write(".venv/Lib/site-packages/canary.pth", b"import this_must_not_execute\n")
        before = list(sys.path)
        bytecode = sys.dont_write_bytecode
        def importing():
            self.assertEqual(sys.path[0], str(packages))
            self.assertTrue(sys.dont_write_bytecode)
            self.assertFalse(marker.exists())
            return self.driver
        self.assertEqual(self.adapter(import_driver=importing).probe("driver"), "driver_ready")
        self.assertEqual(sys.path, before)
        self.assertEqual(sys.dont_write_bytecode, bytecode)
        self.finder.assert_called_once_with("psycopg", [str(packages), "fixture-packages"])

    def test_linux_venv_path_is_used_without_native_discovery(self):
        packages = self.venv(platform="linux")
        self.assertEqual(self.adapter(platform="linux").probe("driver"), "driver_ready")
        self.assertEqual(self.finder.call_args.args[1][0], str(packages))

    def test_bad_driver_import_is_sanitized_and_restores_interpreter_state(self):
        before, bytecode = list(sys.path), sys.dont_write_bytecode
        self.importer.side_effect = RuntimeError("password=SECRET C:/private/path")
        self.assertEqual(self.adapter().probe("driver"), "driver_unusable")
        self.assertEqual(sys.path, before)
        self.assertEqual(sys.dont_write_bytecode, bytecode)
        self.importer.side_effect = None
        self.importer.return_value = SimpleNamespace()
        self.assertEqual(self.adapter().probe("driver"), "driver_unusable")

    def test_previously_loaded_driver_from_a_different_package_is_not_claimed_ready(self):
        self.finder.return_value = SimpleNamespace(origin=str(self.root / "preferred/psycopg/__init__.py"))
        self.driver.__spec__ = SimpleNamespace(origin=str(self.root / "other/psycopg/__init__.py"))
        self.assertEqual(self.adapter().probe("driver"), "driver_unusable")
        self.connector.assert_not_called()

    def test_previously_loaded_driver_without_discovered_origin_is_not_claimed_ready(self):
        self.finder.return_value = SimpleNamespace(origin=str(self.root / "preferred/psycopg/__init__.py"))
        for specification in (None, SimpleNamespace(origin=None), SimpleNamespace()):
            self.driver.__spec__ = specification
            self.assertEqual(self.adapter().probe("driver"), "driver_unusable")
        self.connector.assert_not_called()

    def test_database_ready_uses_only_captured_config_one_readonly_app_connection(self):
        adapter = self.adapter()
        self.assertEqual(adapter.probe("database"), "database_ready")
        self.connector.assert_called_once_with(host="localhost", hostaddr="127.0.0.1", port=5432,
                                              dbname="decklab", user="decklab_app", autocommit=False,
                                              connect_timeout=2, application_name="decklab.preflight", options=local.OPTIONS)
        self.assertEqual(self.connection.calls, [(local.READ_ONLY, None), (local.VERSION_SQL, None),
                                                (local.LEDGER_EXISTS, None), (local.LEDGER_SQL, (2,)),
                                                (local.INITIALIZED, None)])
        self.assertFalse(self.connection.active)
        self.assertEqual(self.connection.closed, 1)
        self.assertIn("default_transaction_read_only=on", local.OPTIONS)
        self.assertIn("statement_timeout=5000", local.OPTIONS)
        self.assertIn("lock_timeout=2000", local.OPTIONS)

    def test_config_failure_prevents_driver_and_connection(self):
        self.write("decklab/config.json", b"not json")
        self.assertEqual(self.adapter().probe("database"), "database_unavailable")
        self.finder.assert_not_called()
        self.connector.assert_not_called()

    def test_database_uses_remote_host_without_inventing_a_host_address(self):
        self.raw["database"] = {"host": "fixture.invalid", "name": "fixture"}
        self.write_config()
        self.assertEqual(self.adapter().probe("database"), "database_ready")
        self.assertNotIn("hostaddr", self.connector.call_args.kwargs)

    def test_multihost_configuration_is_valid_but_not_contacted_by_preflight(self):
        for host in ("first.invalid,second.invalid", "localhost,", ",localhost"):
            self.raw["database"] = {"host": host}
            self.write_config()
            adapter = self.adapter()
            self.assertEqual(adapter.probe("config"), "config_ready")
            self.assertEqual(adapter.probe("database"), "database_host_unsupported")
        self.connector.assert_not_called()

    def test_captured_config_is_not_loaded_again_for_database(self):
        adapter = self.adapter()
        self.assertEqual(adapter.probe("config"), "config_ready")
        self.write("decklab/config.json", b"changed")
        self.assertEqual(adapter.probe("database"), "database_ready")

    def test_empty_misnamed_duplicate_or_oversized_catalog_never_connects(self):
        catalog = self.root / "decklab/db/migrations"
        (catalog / "0001_foundation.sql").unlink()
        self.assertEqual(self.adapter().probe("database"), "database_catalog_invalid")
        for paths in (("BAD.sql",), ("0001_one.sql", "0001_two.sql")):
            for path in paths:
                self.write("decklab/db/migrations/" + path, b"select 1")
            self.assertEqual(self.adapter().probe("database"), "database_catalog_invalid")
            self.connector.assert_not_called()
            for path in catalog.iterdir():
                path.unlink()
        self.write("decklab/db/migrations/0001_one.sql", b"x" * 10)
        with mock.patch.object(local, "MAX_MIGRATION", 4):
            self.assertEqual(self.adapter().probe("database"), "database_catalog_invalid")
        self.connector.assert_not_called()

    def test_catalog_bounds_outer_entries_and_normalizes_windows_bytes(self):
        with mock.patch.object(local, "MAX_CATALOG_ENTRIES", 0):
            self.assertEqual(self.adapter().probe("database"), "database_catalog_invalid")
        self.write("decklab/db/migrations/0001_foundation.sql", b"\xef\xbb\xbfselect 1;\r\n")
        self.assertEqual(self.adapter().probe("database"), "database_ready")

    def test_connect_failure_is_generic_and_never_parses_raw_auth_details(self):
        self.connector.side_effect = RuntimeError("password authentication failed for SECRET at private.invalid")
        self.assertEqual(self.adapter().probe("database"), "database_unavailable")
        self.assertEqual(self.connection.calls, [])

    def test_unsupported_database_version_does_not_read_schema(self):
        self.connection.version = 150007
        self.assertEqual(self.adapter().probe("database"), "database_version_unsupported")
        self.assertEqual(len(self.connection.calls), 2)
        self.assertEqual(self.connection.closed, 1)

    def test_missing_ledger_and_pending_migrations_do_not_read_initialization(self):
        self.connection.exists = False
        self.assertEqual(self.adapter().probe("database"), "database_schema_missing")
        self.connection.exists = True
        self.connection.rows = []
        self.assertEqual(self.adapter().probe("database"), "database_migrations_pending")
        self.assertNotIn((local.INITIALIZED, None), self.connection.calls)

    def test_mismatched_extra_and_duplicate_ledger_rows_are_bounded(self):
        for rows in ([(1, "bad")], [(2, self.checksum)], [(1, self.checksum), (2, "bad")],
                     [(1, self.checksum), (1, self.checksum)]):
            self.connection.rows = rows
            self.assertEqual(self.adapter().probe("database"), "database_migrations_mismatch")
        self.assertIn("left(checksum, 65)", local.LEDGER_SQL)
        self.assertNotIn("name", local.LEDGER_SQL)

    def test_initialization_sentinels_do_not_count_or_read_private_rows(self):
        for initialized in ((False, True), (True, False), (False, False)):
            self.connection.initialized = initialized
            self.assertEqual(self.adapter().probe("database"), "database_uninitialized")
        self.assertNotIn("count", local.INITIALIZED)
        self.assertNotIn("profile", local.INITIALIZED)
        self.assertNotIn("collection_card", local.INITIALIZED)

    def test_query_timeout_privilege_and_malformed_results_close_without_raw_details(self):
        for state in ("57014", "42501", "42P01"):
            error = RuntimeError("SECRET emails@example.com /private/path")
            error.sqlstate = state
            self.connection.error = error
            self.assertEqual(self.adapter().probe("database"), "database_schema_unavailable")
        self.assertEqual(self.connection.closed, 3)
        self.assertFalse(self.connection.active)
        self.connection.error = None
        self.connection.initialized = (1, 1)
        self.assertEqual(self.adapter().probe("database"), "database_schema_unavailable")

    def test_connection_entry_failure_still_closes(self):
        class BrokenConnection(FakeConnection):
            def __enter__(self):
                raise RuntimeError("SECRET")
        broken = BrokenConnection(self.checksum)
        self.connector.return_value = broken
        self.assertEqual(self.adapter().probe("database"), "database_schema_unavailable")
        self.assertEqual(broken.closed, 1)

    def test_cancellation_propagates_and_connection_closes(self):
        self.connection.error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.adapter().probe("database")
        self.assertEqual(self.connection.closed, 1)
        with self.assertRaises(SystemExit):
            self.adapter(read_file=mock.Mock(side_effect=SystemExit(7))).probe("config")

    def test_cache_ready_checks_existing_bytes_without_loading_global_index(self):
        self.assertEqual(self.adapter().probe("cards"), "cards_ready")
        self.connector.assert_not_called()
        self.importer.assert_not_called()

    def test_generated_tiny_index_accepts_cards_variants_tokens_and_nullable_noncard_fields(self):
        base = {"name": "Fixture Card", "oracle_id": "fixture-card", "layout": "normal", "set": "set",
                "collector_number": "1", "set_type": None, "type_line": "Creature", "power": "1",
                "toughness": "1", "cmc": 1, "finishes": ["nonfoil"], "games": ["paper"]}
        objects = [base, dict(base, oracle_id="fixture-variant", collector_number="2"),
                   {"name": "Fixture Token", "oracle_id": "fixture-token", "layout": "token", "set": "set",
                    "collector_number": "3", "set_type": "token", "type_line": "Token Creature", "power": "1",
                    "toughness": "1", "finishes": ["nonfoil"], "games": ["paper"]},
                   {"name": "Fixture Art", "layout": "art_series", "set": "set", "collector_number": "4",
                    "set_type": None}]
        source = self.write("bulk/cards.jsonl", "".join(json.dumps(obj) + "\n" for obj in objects).encode())
        tags = self.write("bulk/tags.jsonl", "".join(json.dumps({"id": str(number), "slug": tag,
                          "taggings": []}) + "\n" for number, tag in enumerate(ROLE_TAGS.values())).encode())
        self.card_data = card_index.build_index(source, tags, {"default_cards": "2026-10-28"}, log=lambda _: None)
        self.write_cards()
        self.assertEqual(len(self.card_data["variants"]), 1)
        self.assertEqual(len(self.card_data["tokens"]), 1)
        self.assertEqual(self.adapter().probe("cards"), "cards_ready")
        self.connector.assert_not_called()

    def test_missing_corrupt_old_or_invalid_cache_have_fixed_codes(self):
        path = self.root / "decklab/data/scryfall/index.json.gz"
        path.unlink()
        self.assertEqual(self.adapter().probe("cards"), "cards_missing")
        path.write_bytes(b"not gzip SECRET")
        self.assertEqual(self.adapter().probe("cards"), "cards_invalid")
        self.card_data["version"] = 3
        self.write_cards()
        self.assertEqual(self.adapter().probe("cards"), "cards_invalid")
        self.card_data["version"] = True
        self.write_cards()
        self.assertEqual(self.adapter().probe("cards"), "cards_invalid")

    def test_cache_empty_maps_missing_entry_fields_or_bad_tokens_are_invalid(self):
        for key, value in (("cards", {}), ("printings", []), ("tokens", {"id": {}}),
                           ("cards", {"Fixture": {"paper": "yes"}}), ("printings", {"set": []}),
                           ("printings", {"set": {"1": []}})):
            original = self.card_data[key]
            self.card_data[key] = value
            self.write_cards()
            self.assertEqual(self.adapter().probe("cards"), "cards_invalid")
            self.card_data[key] = original

    def test_nested_printing_variant_metadata_and_card_reader_fields_are_required(self):
        mutations = [lambda: self.card_data.pop("built_at"),
                     lambda: self.card_data.update(bulk={"default_cards": None}),
                     lambda: self.card_data.update(variants={"id": {}}),
                     lambda: self.card_data["printings"]["set"].update({"1": {}}),
                     lambda: self.card_data["cards"]["Fixture Card"].pop("printings"),
                     lambda: self.card_data["cards"]["Fixture Card"].pop("oracle_id"),
                     lambda: self.card_data["cards"]["Fixture Card"].pop("roles"),
                     lambda: self.card_data["cards"]["Fixture Card"].pop("power"),
                     lambda: self.card_data["printings"]["set"]["1"].update(oracle_id=[]),
                     lambda: self.card_data.update(tokens={"id": {"name": "Token", "face_names": ["Token"],
                                                                 "printings": []}})]
        original = json.dumps(self.card_data)
        for mutate in mutations:
            self.card_data = json.loads(original)
            mutate()
            self.write_cards()
            self.assertEqual(self.adapter().probe("cards"), "cards_invalid")

    def test_token_fields_and_noncard_printing_nullable_oracle_id_match_builder(self):
        self.card_data["printings"]["set"]["2"] = dict(self.card_data["printings"]["set"]["1"],
                                                        name="Fixture Art", oracle_id=None)
        token = {"name": "Fixture Token", "kind": "token", "layout": "token", "type_line": "Token Creature",
                 "text": "", "power": "1", "toughness": "1", "colors": [], "keywords": [], "faces": [],
                 "face_names": ["Fixture Token"], "printings": [["set", "1"]], "image": ["set", "1"]}
        self.card_data["tokens"] = {"token-id": token}
        self.write_cards()
        self.assertEqual(self.adapter().probe("cards"), "cards_ready")
        token["faces"] = [{"name": "Fixture Token", "type_line": "Token Creature", "text": "",
                           "power": "1", "toughness": "1", "colors": []}]
        self.write_cards()
        self.assertEqual(self.adapter().probe("cards"), "cards_ready")
        token["faces"][0].pop("colors")
        self.write_cards()
        self.assertEqual(self.adapter().probe("cards"), "cards_invalid")

    def test_compressed_and_expanded_cache_work_is_capped(self):
        with mock.patch.object(local, "MAX_COMPRESSED", 1):
            self.assertEqual(self.adapter().probe("cards"), "cards_oversized")
        with mock.patch.object(local, "MAX_INDEX", 1):
            self.assertEqual(self.adapter().probe("cards"), "cards_oversized")

    def test_unreadable_cache_is_unavailable_and_error_text_is_not_output(self):
        read = mock.Mock(side_effect=OSError("password=SECRET"))
        self.assertEqual(self.adapter(read_file=read).probe("cards"), "cards_unavailable")

    def test_core_probe_codes_remain_static_and_omit_contents(self):
        adapter = self.adapter()
        self.assertEqual([adapter.probe(check) for check in ("runtime", "config", "driver", "database", "cards")],
                         ["runtime_ready", "config_ready", "driver_ready", "database_ready", "cards_ready"])
        self.connector.assert_called_once()

    def test_each_new_adapter_rechecks_instead_of_reusing_a_previous_ready_result(self):
        self.assertEqual(self.adapter().probe("config"), "config_ready")
        self.write("decklab/config.json", b"broken")
        self.assertEqual(self.adapter().probe("config"), "config_invalid")

    def test_driver_cancellation_restores_paths_and_does_not_become_an_error_code(self):
        before, bytecode = list(sys.path), sys.dont_write_bytecode
        self.importer.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.adapter().probe("driver")
        self.assertEqual(sys.path, before)
        self.assertEqual(sys.dont_write_bytecode, bytecode)
