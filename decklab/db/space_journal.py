"""Durable, hash-checked quarantine for member removal, under lifecycle maintenance.

The immutable pending journal precedes the first move. Presence of the audited
DB change decides recovery: absent restores, present finishes. This module
never guesses that outcome and never overwrites an unexpected file.

The recovery contract covers application/process crashes. fsync and atomic or
write-through moves reduce filesystem risk; they do not promise a hardware- or
power-loss transaction spanning PostgreSQL and the filesystem.
"""
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

from decklab.db import space_export


def _operation(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A canonical removal operation UUID is required") from None
    return value


def _ordinary(path):
    """Refuse linked paths anywhere along a path that could be read or moved."""
    path = Path(path)
    for part in [path, *path.parents]:
        if part.is_symlink() or part.is_junction():
            raise ValueError("Removal recovery refuses linked paths")
    return path


def _control(claim):
    root, control = Path(claim.root), Path(claim.control_dir)
    _ordinary(root)
    _ordinary(control)
    if root.resolve() != root or control.resolve() != root.parent / f".{root.name}-lifecycle":
        raise ValueError("Removal recovery has an unexpected lifecycle directory")
    return root, control


def _sync_dir(path):
    if os.name == "nt":
        return                  # _move uses MoveFileExW WRITE_THROUGH on Windows
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _move(source, target, *, replace=False):
    _ordinary(source)
    _ordinary(target)
    if not replace and target.exists():
        raise ValueError("Removal recovery would overwrite an existing file")
    if os.name == "nt":
        import ctypes
        fn = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        fn.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
        fn.restype = ctypes.c_int
        if not fn(str(source), str(target), 0x8 | (0x1 if replace else 0)):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        if replace:
            os.replace(source, target)
        else:
            _no_replace(source, target)
        _sync_dir(source.parent)
        if target.parent != source.parent:
            _sync_dir(target.parent)


def _no_replace(source, target):
    """Atomic destination creation for same-volume regular files on POSIX.

    A process crash between link and unlink leaves two names for the same
    inode, which recovery recognises and resolves without copying/overwriting.
    """
    os.link(source, target, follow_symlinks=False)
    _sync_dir(target.parent)
    os.unlink(source)


def _write(path, value):
    _ordinary(path)
    _mkdir(path.parent)
    data = space_export._json(value)
    fd, name = tempfile.mkstemp(prefix=".journal-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _move(temporary, path, replace=True)
    finally:
        temporary.unlink(missing_ok=True)


def _mkdir(path):
    """Persist new directory entries before a journal can authorize moves."""
    path = _ordinary(Path(path))
    if path.exists():
        if not path.is_dir():
            raise ValueError("Removal journal expected a directory")
        return
    _mkdir(path.parent)
    if os.name == "nt":
        temporary = Path(tempfile.mkdtemp(prefix=".journal-dir-", dir=path.parent))
        try:
            _move(temporary, path)    # native directory rename, WRITE_THROUGH
        finally:
            if temporary.exists():
                temporary.rmdir()
    else:
        path.mkdir()
        _sync_dir(path)
        _sync_dir(path.parent)


def _entry_paths(claim, journal, entry):
    root, control = _control(claim)
    rel = space_export._relative(entry["path"])
    original = _ordinary(root.joinpath(*rel.parts))
    staged = _ordinary(control / "quarantine" / journal["operation"] / Path(*rel.parts))
    if not original.resolve().is_relative_to(root) or not staged.resolve().is_relative_to(control / "quarantine"):
        raise ValueError("Removal journal contains an escaping path")
    return original, staged


def _matches(path, entry):
    _ordinary(path)
    if not path.is_file() or path.stat().st_size != entry["bytes"]:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == entry["sha256"]


def _validate(claim, journal, operation):
    root, _ = _control(claim)
    if not isinstance(journal, dict) or type(journal.get("version")) is not int or journal["version"] != 1 \
            or journal.get("operation") != operation \
            or journal.get("root") != str(root) or journal.get("state") not in ("prepared", "committed", "rolled_back"):
        raise ValueError("The removal journal does not match this results root")
    space_export.member_space(journal.get("space"))
    if type(journal.get("change_set_id")) is not int or journal["change_set_id"] < 1 \
            or not isinstance(journal.get("actor"), str) or not journal["actor"].strip():
        raise ValueError("The removal journal has no valid audited change identity")
    for key in ("message_sha256", "snapshot_sha256"):
        if not isinstance(journal.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", journal[key]):
            raise ValueError("The removal journal has an invalid fingerprint")
    database = journal.get("database")
    if not isinstance(database, dict) or set(database) != {"host", "port", "name"} \
            or not all(isinstance(database[k], str) and database[k] for k in ("host", "name")) \
            or type(database["port"]) is not int or not 1 <= database["port"] <= 65535:
        raise ValueError("The removal journal has an invalid database identity")
    entries = journal.get("entries")
    if not isinstance(entries, list):
        raise ValueError("The removal journal has no file plan")
    paths = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"} \
                or type(entry["bytes"]) is not int or entry["bytes"] < 0 \
                or not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("The removal journal has an invalid file plan")
        _entry_paths(claim, journal, entry)
        if entry["path"].casefold() in paths:
            raise ValueError("The removal journal has colliding file paths")
        paths.add(entry["path"].casefold())
    return journal


def pending(claim):
    _, control = _control(claim)
    folder = _ordinary(control / "pending")
    return [_operation(path.stem) for path in sorted(folder.glob("*.json"))]


def load(claim, operation):
    operation = _operation(operation)
    _, control = _control(claim)
    path = _ordinary(control / "pending" / f"{operation}.json")
    if not path.exists():
        path = _ordinary(control / "completed" / f"{operation}.json")
    try:
        journal = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ValueError("The pending removal journal cannot be read") from exc
    return _validate(claim, journal, operation)


def prepare(claim, operation, space, database, change_set_id, actor, message_sha256, snapshot_sha256, entries):
    operation = _operation(operation)
    root, control = _control(claim)
    journal = _validate(claim, {"version": 1, "operation": operation, "space": space, "root": str(root),
                        "database": database, "change_set_id": change_set_id, "actor": actor,
                        "message_sha256": message_sha256, "snapshot_sha256": snapshot_sha256,
                        "entries": entries, "state": "prepared"}, operation)
    path = control / "pending" / f"{operation}.json"
    if path.exists() or (control / "completed" / path.name).exists():
        raise ValueError("That removal operation already has a journal")
    for entry in entries:
        original, staged = _entry_paths(claim, journal, entry)
        if not _matches(original, entry) or staged.exists():
            raise ValueError("A Forge file changed before quarantine; export it again")
    quarantine = _ordinary(control / "quarantine" / operation)
    if quarantine.exists():
        raise ValueError("That removal operation already has quarantine data")
    _mkdir(quarantine)
    _write(path, journal)           # durable before the first original is moved
    return journal


def stage(claim, journal, fault=None):
    _validate(claim, journal, _operation(journal["operation"]))
    for index, entry in enumerate(journal["entries"]):
        original, staged = _entry_paths(claim, journal, entry)
        if not _matches(original, entry) or staged.exists():
            raise ValueError("A Forge file changed before quarantine; export it again")
        _mkdir(staged.parent)
        _move(original, staged)
        if not _matches(staged, entry):
            raise ValueError("A Forge file changed while entering quarantine; recovery is required")
        if fault:
            fault("staged", index)


def _archive(claim, journal, state):
    _, control = _control(claim)
    quarantine = _ordinary(control / "quarantine" / journal["operation"])
    if quarantine.exists():
        for directory in sorted((p for p in quarantine.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            _ordinary(directory)
            if not any(directory.iterdir()):
                directory.rmdir()
                _sync_dir(directory.parent)
        if any(quarantine.iterdir()):
            raise ValueError("Removal quarantine holds unexpected files; recovery is required")
        quarantine.rmdir()
        _sync_dir(quarantine.parent)
    path = control / "pending" / f"{journal['operation']}.json"
    archived = dict(journal, state=state)
    completed = control / "completed" / path.name
    if completed.exists():
        if json.loads(_ordinary(completed).read_bytes()) != archived:
            raise ValueError("Removal completion record differs; recovery refused")
        if path.exists():
            if not os.path.samefile(path, completed):
                raise ValueError("A different pending journal appeared beside its completion record")
            path.unlink()           # interrupted POSIX link/unlink archive
            _sync_dir(path.parent)
        return
    _write(path, archived)
    _mkdir(completed.parent)
    _move(path, completed)


def restore(claim, journal, fault=None):
    _validate(claim, journal, _operation(journal["operation"]))
    for index, entry in enumerate(journal["entries"]):
        original, staged = _entry_paths(claim, journal, entry)
        if original.exists():
            if not _matches(original, entry):
                raise ValueError("Recovery would overwrite an existing Forge file; nothing was overwritten")
            if staged.exists():
                if not _matches(staged, entry) or not os.path.samefile(original, staged):
                    raise ValueError("Recovery would overwrite an existing Forge file; nothing was overwritten")
                staged.unlink()    # interrupted POSIX link/unlink stage or restore
                _sync_dir(staged.parent)
        elif _matches(staged, entry):
            _mkdir(original.parent)
            _move(staged, original)
        else:
            raise ValueError("A quarantined Forge file is missing or changed; recovery refused")
        if fault:
            fault("restored", index)
    _archive(claim, journal, "rolled_back")


def finish(claim, journal, fault=None):
    _validate(claim, journal, _operation(journal["operation"]))
    _, control = _control(claim)
    marker = _ordinary(control / "departed.json")
    try:
        departed = json.loads(marker.read_bytes()) if marker.exists() else {"version": 1, "spaces": []}
    except (OSError, ValueError) as exc:
        raise ValueError("The departed-space marker cannot be read; recovery refused") from exc
    if not isinstance(departed, dict) or type(departed.get("version")) is not int or departed["version"] != 1 \
            or not isinstance(departed.get("spaces"), list):
        raise ValueError("The departed-space marker is invalid; recovery refused")
    for space in departed["spaces"]:
        space_export.member_space(space)
    _write(marker, {"version": 1, "spaces": sorted(set(departed["spaces"]) | {journal["space"]})})
    if fault:
        fault("departed", None)
    for index, entry in enumerate(journal["entries"]):
        original, staged = _entry_paths(claim, journal, entry)
        if original.exists():
            raise ValueError("A Forge file reappeared after removal; recovery refused without overwriting it")
        if staged.exists():
            if not _matches(staged, entry):
                raise ValueError("A quarantined Forge file changed; recovery refused")
            staged.unlink()
            _sync_dir(staged.parent)
        if fault:
            fault("cleaned", index)
    _archive(claim, journal, "committed")
