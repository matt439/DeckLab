"""Local doctor adapters. Results are public codes; supplied settings stay internal.

Construction is inert. Only probe() performs reads; it never repairs, fetches or starts
anything. Dependency seams let fixture tests use disposable roots and fake drivers.
The database check establishes a bounded migration-ledger/initialization result, not
complete schema, grant, data or operational integrity.
"""
import gzip
import hashlib
import importlib
from importlib.machinery import PathFinder
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import zlib
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
MAX_CONFIG = 4 * 1024 * 1024
MAX_VENV = 16 * 1024
MAX_MIGRATIONS = 128
MAX_CATALOG_ENTRIES = 256
MAX_MIGRATION = 1024 * 1024
MAX_CATALOG = 8 * 1024 * 1024
MAX_COMPRESSED = 128 * 1024 * 1024
MAX_INDEX = 512 * 1024 * 1024
MAX_ENTRIES = 2_000_000
OPTIONS = "-c default_transaction_read_only=on -c lock_timeout=2000 -c statement_timeout=5000"
READ_ONLY = "set transaction isolation level repeatable read, read only"
VERSION_SQL = "select current_setting('server_version_num')::integer"
LEDGER_EXISTS = "select to_regclass('public.schema_migration') is not null"
LEDGER_SQL = "select version, left(checksum, 65) from public.schema_migration order by version limit %s"
INITIALIZED = (
    "select exists (select 1 from public.inventory_revision where id is true and revision >= 1), "
    "exists (select 1 from public.decks_revision where id is true and revision >= 1)"
)
MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class TooLarge(ValueError):
    """An optional preflight input exceeds its fixed work bound."""


def _read_file(path, limit):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise TooLarge
    return raw


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _json(raw):
    def invalid(_):
        raise ValueError
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=invalid)


def _text(value, limit=255):
    return isinstance(value, str) and 0 < len(value) <= limit and value == value.strip() \
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)


def _port(value):
    return type(value) is int and 1 <= value <= 65535


def _import_driver():
    return importlib.import_module("psycopg")


def _strings(value):
    return isinstance(value, list) and len(value) <= MAX_ENTRIES and \
        all(isinstance(item, str) for item in value)


def _links(value, printings):
    if not isinstance(value, list) or len(value) > MAX_ENTRIES:
        return False
    return all(isinstance(pair, list) and len(pair) == 2 and all(isinstance(part, str) for part in pair)
               and pair[0] in printings and pair[1] in printings[pair[0]] for pair in value)


def _nullable_texts(entry, keys):
    return all(key in entry and (entry[key] is None or isinstance(entry[key], str)) for key in keys)


def _card_entry(entry, printings):
    if not isinstance(entry, dict) or not _text(entry.get("name"), 512) or \
            not _text(entry.get("oracle_id"), 128) or type(entry.get("paper")) is not bool or \
            type(entry.get("game_changer")) is not bool or not _strings(entry.get("roles")) or \
            not _links(entry.get("printings"), printings):
        return False
    if any(not isinstance(entry.get(key), str) for key in
           ("layout", "mana_cost", "type_line", "oracle_text", "commander_legality")) or \
            any(not _strings(entry.get(key)) for key in
                ("colors", "color_identity", "keywords", "produced_mana")):
        return False
    if not _nullable_texts(entry, ("power", "toughness", "loyalty", "defense")):
        return False
    cmc = entry.get("cmc")
    if type(cmc) not in (int, float) or not math.isfinite(cmc):
        return False
    if "faces" in entry and (not isinstance(entry["faces"], list) or any(
            not isinstance(face, dict) or not _text(face.get("name"), 512) for face in entry["faces"])):
        return False
    return all(_strings(entry[key]) for key in ("tokens", "token_names") if key in entry)


def _token_entry(entry, printings):
    if not isinstance(entry, dict) or not _text(entry.get("name"), 512) or \
            entry.get("kind") not in ("token", "emblem", "reminder", "helper") or \
            any(not isinstance(entry.get(key), str) for key in ("layout", "type_line", "text")) or \
            not _nullable_texts(entry, ("power", "toughness")) or \
            any(not _strings(entry.get(key)) for key in ("colors", "keywords", "face_names")) or \
            not _links(entry.get("printings"), printings):
        return False
    faces = entry.get("faces")
    if not isinstance(faces, list) or len(faces) > MAX_ENTRIES:
        return False
    for face in faces:
        if not isinstance(face, dict) or any(not isinstance(face.get(key), str) for key in
                                            ("name", "type_line", "text")) or \
                not _nullable_texts(face, ("power", "toughness")) or not _strings(face.get("colors")):
            return False
    return "image" in entry and (entry["image"] is None or _links([entry["image"]], printings))


class Local:
    def __init__(self, root=None, *, version=None, platform=None, environ=None,
                 read_file=None, find_driver=None, import_driver=None, connect=None,
                 base_executable=None, search_path=None):
        self.root = Path(root) if root is not None else ROOT
        self.version = tuple(sys.version_info[:2] if version is None else version[:2])
        self.platform = sys.platform if platform is None else platform
        self.environ = os.environ if environ is None else environ
        self.read_file = _read_file if read_file is None else read_file
        self.find_driver = PathFinder.find_spec if find_driver is None else find_driver
        self.import_driver = _import_driver if import_driver is None else import_driver
        self.connect = connect
        self.base_executable = base_executable
        self.search_path = search_path
        self._settings = None
        self._loaded_driver = None
        self._results = {}

    @property
    def settings(self):
        """Already validated private settings, for the optional adapter; never reads."""
        return self._settings

    def probe(self, check_id):
        if check_id not in ("runtime", "config", "driver", "database", "cards"):
            raise ValueError("Unknown preflight check")
        if check_id not in self._results:
            self._results[check_id] = getattr(self, "_" + check_id)()
        return self._results[check_id]

    def _runtime(self):
        return "runtime_ready" if self.version == (3, 14) and self.platform in ("win32", "linux", "darwin") \
            else "runtime_unsupported"

    def _config(self):
        if self.environ.get("DECKLAB_CONFIG_EXTRA"):
            return "config_override_active"
        path = self.root / "decklab" / "config.json"
        try:
            if (path.parent / "data" / "profile-config" / "pending.json").exists():
                return "config_profile_pending"
            raw = self.read_file(path, MAX_CONFIG)
        except FileNotFoundError:
            return "config_missing"
        except TooLarge:
            return "config_invalid"
        except Exception:
            return "config_unavailable"
        try:
            settings = _json(raw)
            if not isinstance(settings, dict):
                return "config_invalid"
            from decklab.lib import access, config, profiles
            try:
                listed = profiles.read_checked(settings)
            except profiles.InvalidProfiles:
                return "config_profiles_invalid"
            if not any(profile["space"] == "home" for profile in listed):
                return "config_no_home_profile"
            settings = {**config.DEFAULTS, **settings}
            settings.setdefault("port", 8642)
            if not _port(settings["port"]) or not _text(settings.get("host", "0.0.0.0")):
                return "config_invalid"
            hosts = settings.get("allowed_hosts", [])
            if not isinstance(hosts, list) or any(not _text(host) for host in hosts):
                return "config_invalid"
            access.settings_of(settings)
            if settings.get("access") is not None and profiles.legacy(settings.get("profiles")):
                return "config_profiles_invalid"
            aliases = set()
            for profile in listed:
                for email in profile["emails"]:
                    if profiles.supported_email(email) is None or email in aliases:
                        return "config_profiles_invalid"
                    aliases.add(email)
            block = settings.get("database", {})
            if not isinstance(block, dict):
                return "config_invalid"
            database = {"host": "localhost", "port": 5432, "name": "decklab", **block}
            if isinstance(database["port"], str) and re.fullmatch(r"[0-9]{1,5}", database["port"]):
                database["port"] = int(database["port"])
            if self.environ.get("DECKLAB_DB_NAME"):
                database["name"] = self.environ["DECKLAB_DB_NAME"]
            if not _text(database["host"]) or not _port(database["port"]) or not _text(database["name"], 63):
                return "config_invalid"
            settings["database"] = database
        except Exception:
            return "config_invalid"
        self._settings = settings
        return "config_ready"

    def _driver(self):
        return self._load_driver()

    def _load_driver(self):
        if self.probe("runtime") != "runtime_ready":
            return "driver_unusable"
        try:
            folder = self.root / ".venv"
            paths = list(sys.path if self.search_path is None else self.search_path)
            if folder.exists():
                values = {}
                raw = self.read_file(folder / "pyvenv.cfg", MAX_VENV).decode("utf-8")
                for line in raw.splitlines():
                    key, sep, value = line.partition("=")
                    if sep:
                        values[key.strip().lower()] = value.strip()
                base = self.base_executable or getattr(sys, "_base_executable", None) or sys.executable
                home = values.get("home")
                same_home = isinstance(home, str) and os.path.normcase(os.path.abspath(home)) == \
                    os.path.normcase(os.path.abspath(os.path.dirname(base)))
                if not same_home or (values.get("version") or values.get("version_info") or "").split(".")[:2] \
                        != [str(value) for value in self.version]:
                    return "driver_venv_mismatch"
                packages = folder / "Lib" / "site-packages" if self.platform == "win32" else \
                    folder / "lib" / ("python" + ".".join(map(str, self.version))) / "site-packages"
                if not packages.is_dir():
                    return "driver_venv_mismatch"
                paths.insert(0, str(packages))
            specification = self.find_driver("psycopg", paths)
            if specification is None:
                return "driver_missing"
            before, bytecode = list(sys.path), sys.dont_write_bytecode
            try:
                # Only insert verified package paths. site.addsitedir would execute .pth.
                sys.path[:] = paths
                sys.dont_write_bytecode = True
                driver = self.import_driver()
            finally:
                sys.path[:] = before
                sys.dont_write_bytecode = bytecode
            if not callable(getattr(driver, "connect", None)):
                return "driver_unusable"
            expected = getattr(specification, "origin", None)
            actual = getattr(getattr(driver, "__spec__", None), "origin", None)
            if expected and (not actual or os.path.normcase(os.path.abspath(expected)) != \
                             os.path.normcase(os.path.abspath(actual))):
                return "driver_unusable"
            self._loaded_driver = driver
            return "driver_ready"
        except FileNotFoundError:
            return "driver_venv_mismatch"
        except Exception:
            return "driver_unusable"

    def _catalog(self):
        folder = self.root / "decklab" / "db" / "migrations"
        files, total = {}, 0
        for count, path in enumerate(folder.iterdir(), 1):
            if count > MAX_CATALOG_ENTRIES:
                raise TooLarge
            if path.suffix != ".sql":
                continue
            if len(files) >= MAX_MIGRATIONS:
                raise TooLarge
            match = MIGRATION_NAME.fullmatch(path.name)
            if match is None or int(match[1]) in files:
                raise ValueError
            raw = self.read_file(path, min(MAX_MIGRATION, MAX_CATALOG - total))
            total += len(raw)
            raw = raw.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")
            raw.decode("utf-8")
            files[int(match[1])] = hashlib.sha256(raw).hexdigest()
        if not files:
            raise ValueError
        return files

    def _database(self):
        if self.probe("config") != "config_ready" or self.probe("driver") != "driver_ready":
            return "database_unavailable"
        settings = self._settings["database"]
        # libpq applies connect_timeout to each address, not to the whole attempt.
        # Do not multiply that wait across an explicitly configured host list.
        # A single DNS name can still resolve to several addresses; this is no
        # promise of a hard wall-clock bound on DNS or connection establishment.
        if "," in settings["host"]:
            return "database_host_unsupported"
        try:
            catalog = self._catalog()
        except Exception:
            return "database_catalog_invalid"
        kwargs = {"host": settings["host"], "port": settings["port"], "dbname": settings["name"],
                  "user": "decklab_app", "autocommit": False, "connect_timeout": 2,
                  "application_name": "decklab.preflight", "options": OPTIONS}
        if settings["host"].lower() == "localhost":
            kwargs["hostaddr"] = "127.0.0.1"
        try:
            connect = self.connect or self._loaded_driver.connect
            connection = connect(**kwargs)
        except Exception:
            # Authentication and network failures are not safely distinguished by text.
            return "database_unavailable"
        try:
            with connection:
                with connection.transaction():
                    connection.execute(READ_ONLY)
                    version = connection.execute(VERSION_SQL).fetchone()[0]
                    if type(version) is not int or version < 160000:
                        return "database_version_unsupported"
                    exists = connection.execute(LEDGER_EXISTS).fetchone()[0]
                    if exists is False:
                        return "database_schema_missing"
                    if exists is not True:
                        return "database_schema_unavailable"
                    rows = connection.execute(LEDGER_SQL, (len(catalog) + 1,)).fetchall()
                    if len(rows) > len(catalog):
                        return "database_migrations_mismatch"
                    applied = {}
                    for row in rows:
                        version, checksum = row
                        if type(version) is not int or version in applied or catalog.get(version) != checksum:
                            return "database_migrations_mismatch"
                        applied[version] = checksum
                    if set(applied) != set(catalog):
                        return "database_migrations_pending"
                    initialized = connection.execute(INITIALIZED).fetchone()
                    if not isinstance(initialized, tuple) or len(initialized) != 2 or \
                            any(type(value) is not bool for value in initialized):
                        return "database_schema_unavailable"
                    if not all(initialized):
                        return "database_uninitialized"
        except Exception:
            return "database_schema_unavailable"
        finally:
            try:
                connection.close()
            except Exception:
                pass
        return "database_ready"

    def _cards(self):
        path = self.root / "decklab" / "data" / "scryfall" / "index.json.gz"
        try:
            compressed = self.read_file(path, MAX_COMPRESSED)
            with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
                raw = stream.read(MAX_INDEX + 1)
            if len(raw) > MAX_INDEX:
                return "cards_oversized"
        except FileNotFoundError:
            return "cards_missing"
        except TooLarge:
            return "cards_oversized"
        except (gzip.BadGzipFile, EOFError, zlib.error):
            return "cards_invalid"
        except Exception:
            return "cards_unavailable"
        try:
            from decklab.lib.card_index import INDEX_VERSION, ROLES
            data = _json(raw)
            if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != INDEX_VERSION:
                return "cards_invalid"
            for key in ("cards", "printings", "variants", "tokens", "roles"):
                if not isinstance(data.get(key), dict) or len(data[key]) > MAX_ENTRIES:
                    return "cards_invalid"
            if not data["cards"] or not data["printings"]:
                return "cards_invalid"
            if not isinstance(data.get("built_at"), str) or \
                    datetime.fromisoformat(data["built_at"]).utcoffset() is None or \
                    not isinstance(data.get("bulk"), dict) or \
                    any(not isinstance(value, str) for value in data["bulk"].values()) or \
                    set(data["roles"]) != set(ROLES):
                return "cards_invalid"
            for role in data["roles"].values():
                if not isinstance(role, dict) or not _text(role.get("tag")) or \
                        type(role.get("oracle_cards")) is not int or role["oracle_cards"] < 0:
                    return "cards_invalid"
            for numbers in data["printings"].values():
                if not isinstance(numbers, dict) or len(numbers) > MAX_ENTRIES or \
                        any(not isinstance(entry, dict) for entry in numbers.values()):
                    return "cards_invalid"
                for entry in numbers.values():
                    if not _text(entry.get("name"), 512) or "oracle_id" not in entry or \
                            (entry["oracle_id"] is not None and not _text(entry["oracle_id"], 128)) or \
                            not _strings(entry.get("finishes")) or not _strings(entry.get("games")) or \
                            type(entry.get("digital")) is not bool or type(entry.get("oversized")) is not bool or \
                            not _nullable_texts(entry, ("set_type",)):
                        return "cards_invalid"
                    for key in ("usd", "usd_foil", "usd_etched"):
                        if key not in entry or (entry[key] is not None and
                                               (type(entry[key]) not in (int, float) or not math.isfinite(entry[key])
                                                or entry[key] < 0)):
                            return "cards_invalid"
            for name, entry in data["cards"].items():
                if not _text(name, 512) or not _card_entry(entry, data["printings"]) or entry["name"] != name:
                    return "cards_invalid"
            for oracle_id, entry in data["variants"].items():
                if not _card_entry(entry, data["printings"]) or entry["oracle_id"] != oracle_id:
                    return "cards_invalid"
            for entry in data["tokens"].values():
                if not _token_entry(entry, data["printings"]):
                    return "cards_invalid"
        except Exception:
            return "cards_invalid"
        return "cards_ready"
