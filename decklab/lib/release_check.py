"""Whether a newer Deck Lab release is out (E11-S49), for a home admin's Settings page.

Only a release install (build.is_release: an unzipped release, with no .git) ever asks; a git
checkout makes no request at all. It asks GitHub's API for the repository's latest published
release (GET /repos/OWNER/REPO/releases/latest: drafts and pre-releases aren't "latest"), at most
once a day, and keeps the answer in the gitignored decklab/data/release-check.json. Nothing is
downloaded: the page only says a newer one exists and links to its release page.

config.json's "release_check": true (the default) asks REPO, a string "owner/repo" asks that
repository instead (a fork's releases), false never asks.

Nothing waits on the network: view() answers from the saved answer and, when it's a day old (or
missing), starts one background thread to ask again; the page shows the new answer next time.
A failed check keeps the last good answer and its date, and says it couldn't check.
"""
import http.client
import json
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from decklab.lib import build, config

REPO = "matt439/DeckLab"            # .github/workflows/release.yml publishes here
INTERVAL = timedelta(days=1)
TIMEOUT = 5.0
USER_AGENT = "DeckLab-release-check"
MAX_ANSWER = 1 << 20                # bytes of GitHub's answer read at most
_REPO_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}\Z")
_SEMVER = re.compile(r"[vV]?([0-9]+)\.([0-9]+)\.([0-9]+)(?:-([0-9A-Za-z.-]{1,40}))?(?:\+[0-9A-Za-z.-]*)?\Z")
_lock = threading.Lock()
_thread = None


def cache_file():
    return config.DATA / "release-check.json"


def version_key(text):
    """A semantic version's sort key (a leading v ignored, build metadata too), or None when text isn't one.
    A pre-release sorts before its release; its parts compare numbers as numbers, below words."""
    found = _SEMVER.fullmatch(text.strip()) if isinstance(text, str) else None
    if not found:
        return None
    major, minor, patch, pre = found.groups()
    if pre is None:
        tail = (1,)
    else:
        parts = pre.split(".")
        if any(not part for part in parts):
            return None
        tail = (0, *((0, int(part), "") if part.isdigit() else (1, 0, part) for part in parts))
    return int(major), int(minor), int(patch), tail


def is_newer(latest, current):
    """True when latest is a later version than current; None when either can't be read as one."""
    a, b = version_key(latest), version_key(current)
    return None if a is None or b is None else a > b


def repository():
    """The repository asked, or None when config.json's release_check turns the check off."""
    setting = config.load().get("release_check", True)
    if setting is True or setting is None:
        return REPO
    if isinstance(setting, str) and _REPO_NAME.fullmatch(setting.strip()):
        return setting.strip()
    return None                     # false, or something that isn't owner/repo: never ask


def _now():
    return datetime.now(timezone.utc)


def _read():
    try:
        data = json.loads(cache_file().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _when(text):
    try:
        found = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return found if found.tzinfo else None


def _due(saved, repo):
    checked = _when(saved.get("checked_at"))
    now = _now()
    # A date in the future (a clock put back) counts as due, so a bad clock never stops the check for good.
    return saved.get("repo") != repo or checked is None or checked > now + timedelta(minutes=5) or now - checked >= INTERVAL


def fetch(repo):
    """GitHub's latest published release of repo: {"latest": tag or None, "url": its page or None}.
    No published release yet (404) is an answer, None. Anything else raises OSError, ValueError or
    http.client.HTTPException (a broken answer, such as one cut off part way)."""
    request = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest", headers={
        "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            data = json.loads(answer.read(MAX_ANSWER).decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {"latest": None, "url": None}
        raise
    tag, url = (data.get("tag_name"), data.get("html_url")) if isinstance(data, dict) else (None, None)
    if version_key(tag) is None:
        raise ValueError("GitHub's latest release has no version tag")
    if not isinstance(url, str) or not url.startswith(f"https://github.com/{repo}/releases/"):
        url = f"https://github.com/{repo}/releases"
    return {"latest": tag.strip(), "url": url}


def _write(data):
    path = cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def check(repo):
    """Ask now and save the answer (the background thread's work); returns what was saved."""
    saved = _read()
    if saved.get("repo") != repo:
        saved = {}
    now = _now().isoformat(timespec="seconds")
    try:
        found = fetch(repo)
    except (OSError, ValueError, UnicodeError, http.client.HTTPException):
        result = {**saved, "repo": repo, "checked_at": now, "ok": False}
    else:
        result = {"repo": repo, "checked_at": now, "ok": True, "good_at": now, **found}
    try:
        _write(result)
    except OSError:
        pass                        # asked again next time; nothing else depends on it
    return result


def _start(repo):
    """One background check at a time (a second asks while one runs start none)."""
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=check, args=(repo,), name="release-check", daemon=True)
            _thread.start()


def view():
    """The Settings page's answer: None for a git checkout (nothing asked), else
    {"enabled", "current", "latest", "url", "newer", "checked_on", "failed", "checking"}.
    checked_on is the date of the last good check (YYYY-MM-DD, UTC); failed says the latest attempt didn't get one."""
    if not build.is_release():
        return None
    current = build.status().get("version")
    repo = repository()
    if repo is None:
        return {"enabled": False, "current": current, "latest": None, "url": None, "newer": None,
                "checked_on": None, "failed": False, "checking": False}
    saved = _read()
    if saved.get("repo") != repo:
        saved = {}
    checking = _due(saved, repo)
    if checking:
        _start(repo)
    good = _when(saved.get("good_at"))
    latest = saved.get("latest") if good and version_key(saved.get("latest")) else None
    url = saved.get("url") if latest and isinstance(saved.get("url"), str) else None
    return {"enabled": True, "current": current, "latest": latest, "url": url,
            "newer": is_newer(latest, current) if latest else (False if good else None),
            "checked_on": good.date().isoformat() if good else None,
            "failed": saved.get("ok") is False, "checking": checking}
