"""Optional age CLI transport for off-PC copies; no Python cryptography or live setup.

Only native public recipients and unencrypted native identity files are accepted.
No passphrase, SSH agent, plugin, shell or secret command-line argument is used.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from decklab.lib import pathsetting

SUFFIX = ".age"
HEADER = b"age-encryption.org/v1\n"
TIMEOUT = 300
MAX_IDENTITY_BYTES = 64 * 1024
MAX_IDENTITIES = 16
BECH32 = "023456789acdefghjklmnpqrstuvwxyz"
RECIPIENT = re.compile(rf"(?:age1[{BECH32}]{{58}}|age1pq1[{BECH32}]{{64,4000}})\Z")
IDENTITY = re.compile(r"AGE-SECRET-KEY-(?:PQ-)?1[A-Z0-9]{20,4096}\Z")
_SPAWN = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


class CryptoError(OSError):
    """Fixed operator guidance, never the tool's stderr, key, or identity file contents."""


def recipient(settings):
    value = settings.get("backup_recipient")
    if value is None:
        return None
    if not isinstance(value, str) or not RECIPIENT.fullmatch(value):
        raise CryptoError("database.backup_recipient needs one native age public recipient, or null")
    return value


def program(settings):
    configured = settings.get("age_bin")
    if configured is not None:
        try:
            value = pathsetting.normalise("database.age_bin", configured)
        except (OSError, ValueError):
            raise CryptoError("database.age_bin needs an absolute path to the optional age command") from None
        try:
            if value and Path(value).is_absolute() and Path(value).is_file():
                return value
        except (OSError, ValueError):
            pass
    else:
        found = shutil.which("age")
        if found:
            return found
    raise CryptoError("Encrypted backups need the optional age command on PATH or at database.age_bin; nothing is installed automatically")


def identity_path(settings):
    value = settings.get("backup_identity")
    if not value:
        raise CryptoError("Encrypted backups need a local key file in database.backup_identity to restore")
    try:
        value = pathsetting.normalise("database.backup_identity", value)
        target = Path(value) if value else None
        ready = target is not None and target.is_absolute() and target.is_file()
    except (OSError, ValueError):
        ready = False
    if not ready:
        raise CryptoError("The encrypted-backup key file cannot be found; check database.backup_identity on this PC")
    return target


def warnings(settings, *, encrypted=False):
    """Passive existence/tool checks only; never open the identity or run a tool."""
    if settings.get("backup_recipient") is None and not encrypted:
        return []
    out = []
    for check in (recipient, identity_path, program):
        try:
            check(settings)
        except CryptoError as error:
            out.append(str(error))
    return out


def _identities(settings):
    target = identity_path(settings)
    try:
        with target.open("rb") as stream:
            raw = stream.read(MAX_IDENTITY_BYTES + 1)
        if len(raw) > MAX_IDENTITY_BYTES:
            raise ValueError
        lines = [line.strip() for line in raw.decode("ascii").splitlines() if line.strip() and not line.lstrip().startswith("#")]
        if not 1 <= len(lines) <= MAX_IDENTITIES or not all(IDENTITY.fullmatch(line) for line in lines):
            raise ValueError
    except (OSError, ValueError, UnicodeError):
        raise CryptoError("The restore key file must contain only unencrypted native age identities; it was not used") from None
    return ("\n".join(lines) + "\n").encode("ascii")


def _run(args, *, runner=None, identity=None):
    options = {"timeout": TIMEOUT, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, **_SPAWN}
    options.update({"stdin": subprocess.DEVNULL} if identity is None else {"input": identity})
    try:
        result = (runner or subprocess.run)([str(arg) for arg in args], **options)
    except (OSError, subprocess.SubprocessError):
        raise CryptoError("The age command could not finish; check its installation, recipient/key and file access") from None
    if result.returncode != 0:
        raise CryptoError("The age command refused the file or key; no plaintext copy was used as a fallback")


def encrypt_copy(source, folder, settings, *, runner=None):
    """Write ciphertext only at the destination, then rename atomically. Keep the local dump."""
    public = recipient(settings)
    if public is None:
        raise CryptoError("Encrypted backup copying needs database.backup_recipient")
    executable = program(settings)
    source, folder = Path(source), Path(folder)
    folder.mkdir(exist_ok=True)       # never create a missing NAS share's parents
    target = folder / (source.name + SUFFIX)
    partial = target.with_name(target.name + ".partial")
    try:
        _run([executable, "--encrypt", "--recipient", public, "--output", partial, source], runner=runner)
        with partial.open("rb") as stream:
            valid = stream.read(len(HEADER)) == HEADER
        if not valid or partial.stat().st_size <= len(HEADER):
            raise CryptoError("The age command did not produce an encrypted backup; no plaintext fallback was copied")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


@contextmanager
def readable_dump(source, settings, *, runner=None):
    """Plain dumps pass through. Ciphertext decrypts to an OS-private temporary folder, removed on every exit."""
    source = Path(source)
    if not source.name.endswith(SUFFIX):
        yield source
        return
    identities = _identities(settings)
    executable = program(settings)
    with tempfile.TemporaryDirectory(prefix="decklab-decrypted-") as folder:
        target = Path(folder) / "restore.dump"
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        _run([executable, "--decrypt", "--identity", "-", "--output", target, source], runner=runner, identity=identities)
        with target.open("rb") as stream:
            valid = stream.read(5) == b"PGDMP"
        if not valid:
            raise CryptoError("The decrypted file is not a PostgreSQL custom-format dump; nothing was restored")
        yield target
