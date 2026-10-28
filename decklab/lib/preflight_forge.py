"""Optional Forge/Java file facts, without importing or running Forge or Java.

Settings are captured lazily from the caller's validated configuration. File
providers can be replaced entirely by fixtures. Only static result codes leave
this adapter: filenames, configuration, release values and errors stay private.
Present files do not establish archive integrity, executable compatibility,
card-log qualification or a successful simulation.
"""
from collections.abc import Mapping
import os
from pathlib import Path
import re
import stat

MAX_ENTRIES = 128
MAX_PARTS = 64
MAX_RELEASE = 8192
JAR_NAME = re.compile(r"^forge-gui-desktop-(.{1,128})-jar-with-dependencies\.jar$")
JAVA_VERSION = re.compile(r'^JAVA_VERSION\s*=\s*"([^"\r\n]{1,80})"\s*$', re.M)
ZIP_PREFIXES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_UNREAD = object()


class _Unavailable(Exception):
    pass


def _names(path):
    with os.scandir(path) as entries:
        for entry in entries:
            yield entry.name


def _read(path, limit):
    with path.open("rb") as stream:
        return stream.read(limit)


class ForgeFiles:
    """probe('java'|'forge') returns one agreed static optional-check code.

    stat_path uses lstat semantics, list_names yields direct child names, and
    read_bytes accepts a byte limit. java_path, when supplied, returns an already
    selected runtime path; this adapter never searches PATH, JAVA_HOME or host
    installation folders. Symlink paths are left unverified rather than followed.
    """

    def __init__(self, settings, root=None, *, stat_path=None, list_names=None,
                 read_bytes=None, java_path=None, platform=None):
        self._settings = settings
        self._config = _UNREAD
        self.root = Path(root) if root is not None else Path(__file__).parents[2]
        self.stat_path = stat_path if stat_path is not None else lambda path: path.lstat()
        self.list_names = list_names if list_names is not None else _names
        self.read_bytes = read_bytes if read_bytes is not None else _read
        self.java_path = java_path
        self.windows = (platform if platform is not None else os.name) == "nt"

    def probe(self, check_id):
        if check_id not in ("java", "forge"):
            raise ValueError("Unknown optional preflight check")
        try:
            if self._config is _UNREAD:
                self._config = None  # a failed provider is not retried within this report
                supplied = self._settings()
                if isinstance(supplied, Mapping):
                    self._config = dict(supplied)
            if self._config is None:
                return check_id + "_unavailable"
            return self._java() if check_id == "java" else self._forge()
        except Exception:
            return check_id + "_unavailable"

    def _safe_text(self, value):
        if not isinstance(value, str) or not value or len(value) > 4096 or value != value.strip() or any(
                ord(char) < 32 or ord(char) == 127 for char in value):
            raise _Unavailable
        if value.startswith(("\\\\", "//")):
            raise _Unavailable
        drive = re.match(r"^[A-Za-z]:[\\/]", value)
        if ":" in (value[2:] if drive else value) or (drive and not self.windows):
            raise _Unavailable
        return value

    def _path(self, value):
        value = os.fspath(value)
        path = Path(self._safe_text(value))
        if not path.is_absolute() and not path.root:
            path = self.root / path
        self._safe_text(str(path))
        if ".." in path.parts or len(path.parts) > MAX_PARTS:
            raise _Unavailable
        if self.windows:
            devices = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
                       *(f"LPT{n}" for n in range(1, 10))}
            if any(part.rstrip(" .").split(".")[0].upper() in devices for part in path.parts):
                raise _Unavailable
        return path

    def _stat(self, path):
        # Check components without following links, including links in a configured
        # parent directory. Never turn an apparently local name into a network read.
        for parent in reversed(path.parents):
            info = self.stat_path(parent)
            if not stat.S_ISDIR(info.st_mode) or self._reparse(info):
                raise _Unavailable
        info = self.stat_path(path)
        if stat.S_ISLNK(info.st_mode) or self._reparse(info):
            raise _Unavailable
        return info

    @staticmethod
    def _reparse(info):
        return bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))

    def _file(self, path, archive=False):
        try:
            info = self._stat(path)
        except FileNotFoundError:
            return "missing"
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
            return "incomplete"
        if archive and self.read_bytes(path, 4) not in ZIP_PREFIXES:
            return "invalid"
        return "ready"

    def _java(self):
        chosen = self._config.get("forge_java")
        if not chosen and self.java_path is not None:
            chosen = self.java_path()
        if not chosen:
            return "java_unavailable"  # no automatic discovery or execution was performed
        runtime = self._path(chosen)
        found = self._file(runtime)
        if found != "ready":
            return "java_missing" if found == "missing" else "java_incomplete"
        # The JDK's bounded release metadata can identify its declared major version.
        # Compiler tools are not required for a prebuilt Forge distribution's file facts.
        release = self._path(runtime.parent.parent / "release")
        try:
            info = self._stat(release)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size < MAX_RELEASE:
                return "java_version_unknown"
            raw = self.read_bytes(release, MAX_RELEASE)
            if len(raw) != info.st_size or len(raw) >= MAX_RELEASE:
                return "java_version_unknown"
            declarations = JAVA_VERSION.findall(raw.decode("utf-8"))
            version = (re.match(r"^(?:1\.)?(\d{1,3})(?:[._+\-]|$)", declarations[0])
                       if len(declarations) == 1 else None)
            if version is None:
                return "java_version_unknown"
            return "java_files_ready" if int(version[1]) >= 21 else "java_version_unsupported"
        except (OSError, ValueError, UnicodeError, _Unavailable):
            return "java_version_unknown"

    def _forge(self):
        configured = self._config.get("forge_dir")
        if not configured:
            return "forge_missing"
        folder = self._path(configured)
        try:
            info = self._stat(folder)
        except FileNotFoundError:
            return "forge_missing"
        if not stat.S_ISDIR(info.st_mode):
            return "forge_incomplete"
        candidates = []
        for number, name in enumerate(self.list_names(folder)):
            if number >= MAX_ENTRIES:
                raise _Unavailable
            if not isinstance(name, str) or len(name) > 256 or any(char in name for char in ("/", "\\")):
                continue
            matched = JAR_NAME.fullmatch(name)
            if matched:
                version = tuple(int(part) if part.isdigit() else 0 for part in re.split(r"[.+_-]", matched[1]))
                candidates.append((version, matched[1], name))
        if not candidates:
            return "forge_missing"
        jar = self._path(folder / max(candidates)[2])
        for path in (jar, self._path(folder / "res" / "cardsfolder" / "cardsfolder.zip")):
            result = self._file(path, archive=True)
            if result != "ready":
                return "forge_invalid" if result == "invalid" else "forge_incomplete"
        return "forge_files_ready"
