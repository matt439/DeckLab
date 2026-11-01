"""Folder settings in config.json read the same way everywhere: database.backup_dir,
database.staging_dir, database.export_repo, database.pg_bin and records_repo.

A leading ~ is expanded to the user's home. On Linux and macOS a value must be an absolute
path and must not look like a Windows one (a drive letter, a \\\\server\\share network path or
any backslash): there such a value is just a folder name, relative to wherever the command
runs, so a config.json copied from a Windows PC would quietly back up into the repo's own
folder. normalise() refuses it instead, naming the setting, so the backup, the export and the
smoke test fail loudly with the fix. On Windows nothing is refused: values work as before.

Only the standard library is used, so lib/config.py can use it as well as decklab/db.
"""
import os
import posixpath
import re

# The settings this module reads, with an example of a good value off Windows for each.
EXAMPLES = {
    "database.backup_dir": "/mnt/nas/DeckLab",
    "database.staging_dir": "/home/<you>/decklab-backups",
    "database.export_repo": "/home/<you>/DeckLabData",
    "database.pg_bin": "/usr/lib/postgresql/18/bin",
    "records_repo": "/home/<you>/TradingCardCollection",
}
_DRIVE = re.compile(r"^[A-Za-z]:")


class PathSettingError(ValueError):
    """A folder setting this PC can't use. The message names the setting and says what to give."""


def on_posix():
    """True off Windows: where the checks apply (tests patch this)."""
    return os.name != "nt"


def windows_looking(text):
    """True when text looks like a Windows path: a drive letter (C: or C:\\...), a \\\\server
    network path, or any backslash."""
    return bool(_DRIVE.match(text)) or "\\" in text


def normalise(key, value, posix=None):
    """value (a setting's raw value from config.json) as a path string with ~ expanded, or None
    when it's unset or blank. key names the setting in messages ("database.backup_dir").
    posix: apply the Linux and macOS checks (default: on_posix()). Raises PathSettingError
    for a value that isn't a string, or, off Windows, one that isn't absolute or looks like
    Windows."""
    if value is None:
        return None
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise PathSettingError(f"{key} in config.json must be a folder path in quotes, not {value!r}")
    text = value.strip()
    if not text:
        return None
    posix = on_posix() if posix is None else posix
    example = EXAMPLES.get(key, "/home/<you>/folder")
    if posix:
        if windows_looking(text):
            kind = "a Windows network path" if text.startswith("\\\\") else "a Windows path"
            mount = (" Mount the share (for example at /mnt/nas) and give the folder there."
                     if text.startswith("\\\\") else "")
            raise PathSettingError(f"{key} in config.json is {text}, {kind}, which this PC can't use.{mount} "
                                   f"Give an absolute path such as {example}.")
        text = posixpath.expanduser(text)
        if not posixpath.isabs(text):
            raise PathSettingError(f"{key} in config.json is {text}, a relative path, which would depend on the "
                                   f"folder a command runs in. Give an absolute path such as {example}.")
        return text
    return os.path.expanduser(text)
