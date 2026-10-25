"""Report the server's startup version and changes to application files.

Call start() before importing the application at server startup. The baseline
is immutable for this process: status() never silently captures a later checkout
as the running server. Commits that only change collection data, deck files,
documentation or tests do not require restarting the application.

Git supplies commit identity and whether application files differ from HEAD;
content hashes, including untracked files and deletions, detect edits after
startup. Web assets have a separate hash because the server reads them on each
request. A loaded page can compare its original hash with web_revision to know
when it needs refreshing. Unknown version information is never reported current.
"""

import hashlib
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

CACHE_SECONDS = 5.0
GIT_TIMEOUT = 2.0
_DEFAULT_ROOT = Path(__file__).resolve().parents[2]
_TEXT = {".py", ".java", ".json", ".js", ".css", ".html", ".svg", ".webmanifest"}
_WEB = _TEXT - {".py", ".java"} | {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2"}
_SHA = re.compile(r"[0-9a-f]{40,64}\Z")
_lock = threading.Lock()
_root = None
_running = None
_latest = None
_checked_at = 0.0
_started_at = None


class _Unavailable(Exception):
    pass


@dataclass(frozen=True)
class _Snapshot:
    commit: str | None = None
    dirty: bool | None = None
    runtime: str | None = None
    web: str | None = None
    error: str | None = None


def _kind(name):
    """Runtime and served-asset files, excluding documentation and test data."""
    path = PurePosixPath(name)
    parts = path.parts
    if len(parts) < 2 or parts[0] != "decklab":
        return None
    if any(part in {"__pycache__", "tests", "fixtures", "docs", "node_modules"} for part in parts[1:-1]):
        return None
    if len(parts) == 2 and (path.suffix == ".py" or parts[1] == "config.json"):
        return "runtime"
    if parts[1] == "lib" and path.suffix in {".py", ".java"}:
        return "runtime"
    # The database package's code runs in the server too (lib/state and lib/dbstatus use
    # it); its migrations are applied by hand, never by a restart, so they don't count.
    if parts[1] == "db" and path.suffix == ".py":
        return "runtime"
    if parts[1] == "web" and path.suffix.lower() in _WEB:
        return "web"
    return None


def _files(root, kind=None):
    """Walk only source directories, never the large card/image/result cache.

    os.walk's default ignores traversal errors; reporting current despite an
    unreadable source directory would be misleading, so let those errors out.
    """
    def unreadable(error):
        raise error

    paths = []
    decklab = root / "decklab"
    if kind != "web":
        for path in decklab.iterdir():
            if path.is_file() and _kind(path.relative_to(root).as_posix()) == "runtime":
                paths.append(path)
    for folder in (("web",) if kind == "web" else ("lib", "db", "web")):
        location = decklab / folder
        if not location.exists():
            continue
        for directory, dirs, names in os.walk(location, onerror=unreadable):
            dirs[:] = [name for name in dirs if name not in {"__pycache__", "tests", "fixtures", "docs", "node_modules"}]
            for name in names:
                path = Path(directory) / name
                category = _kind(path.relative_to(root).as_posix())
                if category and (kind is None or kind == category):
                    paths.append(path)
    return sorted(paths)


def _fingerprints(root, kind=None):
    paths = _files(root, kind)
    digests = {name: hashlib.sha256() for name in ("runtime", "web")}
    names = set()
    for path in paths:
        name = path.relative_to(root).as_posix()
        category = _kind(name)
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise _Unavailable("Application files changed while checking their version; try again.")
        # A CRLF checkout and its LF equivalent execute the same source.
        if path.suffix.lower() in _TEXT:
            data = data.replace(b"\r\n", b"\n")
        digests[category].update(name.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
        names.add(name)
    if paths != _files(root, kind):
        raise _Unavailable("Application files changed while checking their version; try again.")
    return {name: digest.hexdigest() for name, digest in digests.items()}, names


def _git(root, *args):
    # Discard inherited Git overrides: they must not redirect this read to some
    # other checkout or index. None of these commands needs a writable index.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
               GIT_CEILING_DIRECTORIES=str(root.parent))
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        done = subprocess.run(["git", *args], cwd=root, env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=GIT_TIMEOUT, **options)
    except FileNotFoundError:
        raise _Unavailable("Git is unavailable, so the application version cannot be checked.") from None
    except subprocess.TimeoutExpired:
        raise _Unavailable("Git took too long to check the application version; try again.") from None
    except OSError:
        raise _Unavailable("Git could not read the application checkout.") from None
    if done.returncode:
        raise _Unavailable("The application checkout or its latest commit could not be read.")
    return done.stdout.decode("utf-8", errors="surrogateescape")


def _snapshot(root):
    try:
        commit = _git(root, "rev-parse", "--verify", "HEAD").strip()
        if not _SHA.fullmatch(commit):
            raise _Unavailable("Git did not return a valid application commit.")
        fingerprints, names = _fingerprints(root)
        tracked = set(filter(None, _git(root, "ls-tree", "-r", "--name-only", "-z", commit,
                                       "--", "decklab").split("\0")))
        tracked = {name for name in tracked if _kind(name)}
        changed = set(filter(None, _git(root, "diff", "--name-only", "-z", "--no-renames",
                                       "--no-ext-diff", "--no-textconv", commit, "--", "decklab").split("\0")))
        # A gitignored file (a checkout's own config.json) is no uncommitted change; it still
        # counts in the fingerprints, so editing it asks for a restart.
        untracked = sorted(names - tracked)
        ignored = set(filter(None, _git(root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard",
                                        "--", *untracked).split("\0"))) if untracked else set()
        dirty = names - ignored != tracked or any(_kind(name) for name in changed)
        if _git(root, "rev-parse", "--verify", "HEAD").strip() != commit:
            raise _Unavailable("The latest commit changed while checking the version; try again.")
        return _Snapshot(commit, bool(dirty), fingerprints["runtime"], fingerprints["web"])
    except (_Unavailable, OSError, UnicodeError) as error:
        message = str(error) if isinstance(error, _Unavailable) else "Application files could not be read to check their version."
        return _Snapshot(error=message)


def start(repo=None):
    """Capture the process startup once, before importing application modules."""
    global _root, _running, _latest, _checked_at, _started_at
    with _lock:
        if _running is not None:
            return
        _root = Path(repo if repo is not None else _DEFAULT_ROOT).resolve()
        _started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _running = _latest = _snapshot(_root)
        _checked_at = time.monotonic()


def web_revision():
    """Fresh fingerprint for the HTML response's loaded-assets marker.

    This intentionally bypasses the status cache and Git so a newly loaded
    page's marker describes the files currently being served.
    """
    try:
        return _fingerprints(_root or _DEFAULT_ROOT, "web")[0]["web"]
    except (_Unavailable, OSError, UnicodeError):
        return None


def status():
    """JSON-ready status: cached Git/runtime information and fresh web assets.

    Dirty means uncommitted *application* files, not unsaved deck/collection
    work. code_changed covers runtime or web changes; only runtime changes
    require restarting the server. Git/runtime checks are shared for five
    seconds; the web hash is always fresh so a newly loaded page cannot be
    mistaken for stale just because the status cache predates its assets.
    Unknown comparisons are None, never False.
    """
    global _latest, _checked_at
    with _lock:
        if _running is None:
            running = latest = _Snapshot(error="The server version was not captured at startup.")
            current_web = None
        else:
            if time.monotonic() - _checked_at >= CACHE_SECONDS:
                _latest = _snapshot(_root)
                _checked_at = time.monotonic()
            running, latest = _running, _latest
            current_web = web_revision()
        known = not running.error and not latest.error
        restart = running.runtime != latest.runtime if known else None
        assets = running.web != current_web if known and current_web is not None else None
        changed = True if restart is True or assets is True else (None if None in (restart, assets) else False)
        return {
            "running_commit": running.commit,
            "latest_commit": latest.commit,
            "started_at": _started_at,
            "running_dirty": running.dirty,
            "latest_dirty": latest.dirty,
            "restart_required": restart,
            "assets_changed": assets,
            "code_changed": changed,
            "web_revision": current_web,
            "running_web_revision": running.web,
            "error": running.error or latest.error or (
                "Web assets could not be read to check their version." if current_web is None else None),
        }
