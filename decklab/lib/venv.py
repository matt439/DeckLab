"""Makes the repo's .venv packages (psycopg, for the database) importable from the base Python.

The server, its scheduled task and every script run on the base Python, never the venv's own
python.exe: on Windows that's a launcher which starts the base interpreter as a child, so the
pid Deck Lab records, its /F kills, the Forge slots' pid checks and the program-scoped firewall
rule would all name the wrong process. Instead activate() puts .venv's site-packages on
sys.path, when the venv was made from this same interpreter (pyvenv.cfg's home is this Python's
folder and its version is this major.minor), so the pinned psycopg wins over anything else.

It's called first thing by decklab/server.py, python -m decklab.db and the test package.
Only the standard library is used here, and nothing is imported from the venv.
"""
import os
import site
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VENV = REPO / ".venv"

_state = {"result": "not activated yet"}


def _site_packages():
    if os.name == "nt":
        return VENV / "Lib" / "site-packages"
    return VENV / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "site-packages"


def _config(path):
    """pyvenv.cfg's "key = value" lines, as a dict with lowercase keys."""
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip().lower()] = value.strip()
    return out


def _base_folder():
    return os.path.normcase(os.path.dirname(getattr(sys, "_base_executable", None) or sys.executable))


def _insert_at(path=None):
    """Where the venv's entries go: just before the first base site-packages folder on sys.path
    (or path; the user's or the installation's), so '' and the standard library still come
    first."""
    path = sys.path if path is None else path
    for i, entry in enumerate(path):
        if entry and os.path.basename(os.path.normpath(entry)).lower() == "site-packages":
            return i
    return len(path)


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _activate():
    if sys.prefix != sys.base_prefix and _same(sys.prefix, VENV):
        return None                                 # already running inside the repo's venv
    cfg = VENV / "pyvenv.cfg"
    if not cfg.is_file():
        return "there's no .venv in the repo"
    values = _config(cfg)
    home = values.get("home")
    if not home or os.path.normcase(os.path.normpath(home)) != os.path.normcase(os.path.normpath(_base_folder())):
        return f".venv was made from another Python ({home or 'unknown'}), not this one ({sys.executable})"
    version = values.get("version") or values.get("version_info") or ""
    if version.split(".")[:2] != [str(sys.version_info[0]), str(sys.version_info[1])]:
        return f".venv is for Python {version or 'unknown'}, not {sys.version_info[0]}.{sys.version_info[1]}"
    packages = _site_packages()
    if not packages.is_dir():
        return f".venv has no {packages.relative_to(VENV).as_posix()} folder"
    present = [entry for entry in sys.path if entry and _same(entry, packages)]
    if present:
        # Done before (activate is idempotent), or put there some other way (PYTHONPATH): make
        # sure it's ahead of the base site-packages, or the base Python's packages would win.
        rest = [entry for entry in sys.path if entry not in present]
        if sys.path.index(present[0]) > _insert_at(rest):
            sys.path[:] = rest
            at = _insert_at()
            sys.path[at:at] = present[:1]
        return None
    before = list(sys.path)
    site.addsitedir(str(packages))                  # also runs its .pth files
    added = [entry for entry in sys.path if entry not in before]
    rest = [entry for entry in sys.path if entry in before]
    sys.path[:] = rest
    at = _insert_at()
    sys.path[at:at] = added
    return None


def activate():
    """Put .venv's site-packages on sys.path, ahead of the base Python's, when the venv was made
    from this interpreter. Returns None when it did (or there was no need: already done, or
    running inside the repo's venv itself), else a short reason in plain words why it didn't. Never raises."""
    try:
        result = _activate()
    except Exception as e:                          # a damaged pyvenv.cfg mustn't stop the server
        result = f".venv couldn't be used: {e}"
    _state["result"] = result
    return result


def reason():
    """What the last activate() returned: None when the venv's packages are importable (or
    there was nothing to do), else why not."""
    return _state["result"]
