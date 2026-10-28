"""Process-local accident guards for fixture tests; not a malicious-code sandbox.

Install before test-package imports. Ordinary explicit integration workflows do not use
this runner. Guards do not change the application or its configured server.
"""
import builtins
import errno
import importlib
import importlib.abc
import importlib.machinery
import io
import os
from pathlib import Path
import site
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
DATABASE_DISABLED = "Database integration disabled by fixture runner; separate explicit qualification is required"
CONNECT_DISABLED = "PostgreSQL connections disabled by fixture runner"
RUNTIME_SKIPS = {
    "decklab.tests.test_homenet_gather.RealFactsTests":
        "Native network facts require separate qualification; the prior Windows probe was denied",
    "decklab.tests.test_overnight.CleanupTests":
        "Native process cleanup requires separate qualification; the prior Windows check was unavailable",
    "decklab.tests.test_server_lifecycle.BackgroundServerTests":
        "Native server children need separate qualification; process-local fixture guards do not cross pythonw launches",
    "decklab.tests.test_server_lifecycle.BackgroundServerTests.test_taskkill_without_f_stops_it_like_the_stop_option":
        "Native taskkill requires separate qualification; the prior Windows action was denied",
    "decklab.tests.test_inv_decks.FreshInterpreterTests.test_the_write_commands_register_their_operations":
        "Fresh command child needs separate qualification; its temporary inventory does not isolate private config",
    "decklab.tests.test_overnight.FakeRunTests":
        "Overnight controller children sample native processes even with --fake; the prior inventory action was denied",
    "decklab.tests.test_overnight_report_full.ControllerEndTests":
        "Overnight controller monitoring/cleanup needs native process inventory; the prior inventory action was denied",
}
_installed = False
_installing = False
_root = None
_protected = frozenset()
_audit_installed = False


def _lexical(path):
    """Normalize a path without resolving links or probing any protected file."""
    if isinstance(path, int):
        return None
    try:
        text = os.fsdecode(os.fspath(path))
        if os.name == "nt":
            text = text.replace("/", "\\")
            # Extended-length paths name the same files; normalize without resolving
            # links, reading a directory or touching the requested file.
            if text[:8].upper() == "\\\\?\\UNC\\":
                text = "\\\\" + text[8:]
            elif text.startswith("\\\\?\\"):
                text = text[4:]
        return os.path.normcase(os.path.abspath(text))
    except TypeError:
        return None


def _excluded(path):
    return _lexical(path) in _protected


def _refuse(path):
    raise FileNotFoundError(errno.ENOENT, "File excluded from fixture checks", os.fspath(path))


def _file_guards(root):
    global _protected
    known = [root / "decklab" / "config.json"]
    home = os.environ.get("USERPROFILE") if os.name == "nt" else os.environ.get("HOME")
    home = home or os.path.expanduser("~")
    known.extend([Path(home) / ".pgpass", Path(home) / ".pg_service.conf"])
    appdata = os.environ.get("APPDATA")
    if appdata:
        known.extend(Path(appdata) / "postgresql" / leaf for leaf in ("pgpass.conf", ".pg_service.conf"))
    for key in ("PGPASSFILE", "PGSERVICEFILE"):
        if os.environ.get(key):
            known.append(Path(os.environ[key]))
    _protected = frozenset(_lexical(path) for path in known)

    leaves = {Path(p).name for p in _protected}

    def check(path, dir_fd=None):
        if _excluded(path):
            _refuse(path)
        # A directory descriptor has no lexical path. Fail closed for a protected
        # leaf rather than resolving a descriptor through OS inspection.
        if dir_fd is not None and not isinstance(path, int):
            text = os.fsdecode(os.fspath(path))
            if not os.path.isabs(text) and os.path.normcase(os.path.basename(text)) in leaves:
                _refuse(path)

    def guarded_open(original):
        def open_file(path=None, *args, **kwargs):
            if path is None and "file" in kwargs:
                path = kwargs.pop("file")
            check(path, kwargs.get("dir_fd"))
            return original(path, *args, **kwargs)
        return open_file

    builtins.open = guarded_open(builtins.open)
    io.open = guarded_open(io.open)
    Path.open = guarded_open(Path.open)
    os.open = guarded_open(os.open)
    def absent(original):
        def exists(path, *args, **kwargs):
            return False if _excluded(path) else original(path, *args, **kwargs)
        return exists
    # pathlib may use platform-native fast paths instead of the Python os.stat binding.
    for name in ("exists", "is_file", "is_dir", "is_symlink"):
        setattr(Path, name, absent(getattr(Path, name)))
    Path.stat = guarded_open(Path.stat)
    for name in ("exists", "lexists", "isfile", "isdir", "islink"):
        setattr(os.path, name, absent(getattr(os.path, name)))
    for name in ("stat", "lstat", "unlink", "remove", "truncate", "chmod", "utime"):
        setattr(os, name, guarded_open(getattr(os, name)))
    for name in ("rename", "replace", "link"):
        original = getattr(os, name)

        def two_paths(source=None, destination=None, *args, _original=original, **kwargs):
            if source is None and "src" in kwargs:
                source = kwargs.pop("src")
            if destination is None and "dst" in kwargs:
                destination = kwargs.pop("dst")
            check(source, kwargs.get("src_dir_fd"))
            check(destination, kwargs.get("dst_dir_fd"))
            return _original(source, destination, *args, **kwargs)
        setattr(os, name, two_paths)


def _raw_open_guard():
    """Catch C-level FileIO opens too, without replacing the FileIO class API."""
    global _audit_installed
    if _audit_installed:
        return
    seen = False
    marker = object()

    def audit(event, args):
        nonlocal seen
        if event == "decklab.fixture_guard.ready" and args == (marker,):
            seen = True
        elif event == "open" and args and _excluded(args[0]):
            _refuse(args[0])

    sys.addaudithook(audit)
    # An earlier audit hook may silently refuse registration. Fail closed before
    # imports rather than assume this hook was accepted.
    sys.audit("decklab.fixture_guard.ready", marker)
    if not seen:
        raise RuntimeError("Fixture raw-file guard could not be installed")
    _audit_installed = True


def _safe_activate():
    """Use the existing interpreter/version checks without executing venv .pth code."""
    from decklab.lib import venv
    original = site.addsitedir

    def path_only(path, known_paths=None):
        text = os.path.abspath(os.fspath(path))
        if text not in sys.path:
            sys.path.append(text)
        return known_paths
    site.addsitedir = path_only
    try:
        venv.activate()
    finally:
        site.addsitedir = original


def _block_driver():
    try:
        driver = importlib.import_module("psycopg")
    except ModuleNotFoundError as error:
        if error.name == "psycopg":
            return
        raise

    def prohibited(*args, **kwargs):
        raise driver.OperationalError(CONNECT_DISABLED)
    driver.connect = prohibited
    for name in ("Connection", "AsyncConnection"):
        connection = getattr(driver, name, None)
        if connection is not None:
            connection.connect = classmethod(prohibited)


def disabled_database():
    return DATABASE_DISABLED


class _SupportLoader:
    def __init__(self, loader):
        self.loader = loader

    def create_module(self, spec):
        create = getattr(self.loader, "create_module", None)
        return create(spec) if create else None

    def exec_module(self, module):
        self.loader.exec_module(module)
        module.unavailable = disabled_database


class _SupportFinder(importlib.abc.MetaPathFinder):
    """Patch db_support before any importing decorator can call unavailable()."""
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "decklab.tests.db_support":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Fixture database support could not be guarded")
        spec.loader = _SupportLoader(spec.loader)
        return spec


def install(root=ROOT):
    """Install once, before discovery, including saved-script __mp_main__ imports.

    Unexpected startup failures propagate: the caller must not continue discovery.
    Unit tests may temporarily replace guarded APIs with their explicit fakes.
    """
    global _installed, _installing, _root
    normalized = _lexical(root)
    if _installed:
        if normalized != _root:
            raise RuntimeError("Fixture guards already belong to another checkout")
        return
    if _installing:
        raise RuntimeError("Recursive fixture guard installation")
    _installing = True
    try:
        _file_guards(Path(root))
        _raw_open_guard()
        for key in ("DECKLAB_CONFIG_EXTRA", "DECKLAB_DECK_EXPORT", "PGPASSWORD", "PGPASSFILE", "PGSERVICE", "PGSERVICEFILE"):
            os.environ.pop(key, None)
        # Real Forge games remain a separate opt-in qualification; an inherited
        # request must never turn ordinary fixture discovery into real games.
        os.environ.pop("DECKLAB_FORGE_TESTS", None)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        _safe_activate()
        _block_driver()
        sys.meta_path.insert(0, _SupportFinder())
        from decklab.tests import db_support
        db_support.unavailable = disabled_database
        _root, _installed = normalized, True
    finally:
        _installing = False


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def protect_suite(suite):
    """Retain known runtime cases in discovery with explicit, honest skip results."""
    install()
    for test in cases(suite):
        name = test.id()
        for prefix, reason in RUNTIME_SKIPS.items():
            if name == prefix or name.startswith(prefix + "."):
                cls = type(test)
                if prefix == f"{cls.__module__}.{cls.__name__}":
                    cls.__unittest_skip__, cls.__unittest_skip_why__ = True, reason
                else:
                    method = getattr(cls, test._testMethodName)
                    method.__unittest_skip__, method.__unittest_skip_why__ = True, reason
    return suite
