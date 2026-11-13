"""Which updates a git checkout follows, and how many are waiting (E11-S84).

Two channels (Matt's decision of 2026-11-13):

- "main" (the default, which the household's server follows): `python -m decklab.update`
  fast-forwards to the branch's upstream, every commit merged into main.
- "release": it moves only to the newest stable version tag on the upstream (vX.Y.Z, as
  .github/workflows/release.yml publishes them, E11-S49), never to a commit between tags, never
  to a pre-release tag (v1.3.0-rc1), and never back to an older release than the checkout holds.

config.json's {"update": {"channel": "main" | "release"}} picks one; update's --channel overrides
it. The checkout stays on its branch either way: the release channel fast-forwards the branch to
the tag's commit, so switching back to "main" is a plain fast-forward again.

view() is Settings' "N updates available" line for a git checkout. It reads only what git already
has (the last fetch's refs and tags, and FETCH_HEAD's time): it never fetches, so opening Settings
makes no network request. Each git call here is given its runner, so update.py passes its own and
the tests pass a fake.
"""
import os
import re
from datetime import datetime, timezone
from pathlib import Path

CHANNELS = ("main", "release")
DEFAULT = "main"
_STABLE = re.compile(r"v([0-9]+)\.([0-9]+)\.([0-9]+)\Z")


class ChannelError(ValueError):
    """config.json's update channel isn't one Deck Lab knows."""


def configured(settings):
    """config.json's update channel: "main" when it names none. ChannelError when it's malformed."""
    block = (settings or {}).get("update")
    if block is None:
        return DEFAULT
    if not isinstance(block, dict):
        raise ChannelError('config.json\'s "update" must be an object, such as {"channel": "release"}')
    channel = block.get("channel", DEFAULT)
    if channel not in CHANNELS:
        raise ChannelError(f'config.json\'s "update": {{"channel": ...}} must be "main" or "release", not {channel!r}')
    return channel


def choose(flag, settings):
    """The channel an update follows: --channel when given, else config.json's."""
    if flag is not None:
        if flag not in CHANNELS:
            raise ChannelError(f"--channel must be main or release, not {flag!r}")
        return flag
    return configured(settings)


def stable_key(tag):
    """(major, minor, patch) of a stable version tag such as v1.2.0, or None for any other name."""
    found = _STABLE.fullmatch(tag.strip()) if isinstance(tag, str) else None
    return tuple(int(part) for part in found.groups()) if found else None


def _stable(names):
    """The stable version tags among git's tag listing, newest first."""
    tags = {name.strip() for name in names.splitlines() if stable_key(name)}
    return sorted(tags, key=stable_key, reverse=True)


def released_tags(git, ref):
    """The stable version tags ref holds (reachable from it), newest first."""
    return _stable(git("tag", "--list", "v*", "--merged", ref))


def _is_ancestor(git, older, newer):
    return git("merge-base", older, newer) == git("rev-parse", older)


def plan_release(git, upstream):
    """Where the release channel moves this checkout: {"tag", "target", "move", "note"}.

    tag is the newest stable version tag on upstream (None when there's none yet), target its
    commit, move whether HEAD fast-forwards to it. note says why nothing moves. Raises ValueError
    when the tag's commit is neither ahead of HEAD nor behind it (never moved: no merge, no reset)."""
    head = git("rev-parse", "HEAD")
    on_main = released_tags(git, upstream)
    if not on_main:
        return {"tag": None, "target": head, "move": False,
                "note": f"There's no release on {upstream} yet (a vX.Y.Z tag), so nothing was moved: the release "
                        "channel never moves to a commit between releases."}
    newest = on_main[0]
    target = git("rev-parse", f"{newest}^{{commit}}")
    held = released_tags(git, "HEAD")
    current = held[0] if held else None
    if target == head:
        return {"tag": newest, "target": target, "move": False, "note": f"Already at the newest release, {newest}."}
    if current and stable_key(current) >= stable_key(newest):
        return {"tag": newest, "target": head, "move": False,
                "note": f"This checkout already holds {current}, the newest release, and is past it: the release "
                        "channel never goes back to an older commit, so nothing was moved; it moves again at the "
                        "next release."}
    if _is_ancestor(git, head, target):
        return {"tag": newest, "target": target, "move": True, "note": None}
    raise ValueError(f"{newest} isn't ahead of this checkout or behind it, so nothing was moved")


def _fetched_on(git, root, settings=None):
    """The date (YYYY-MM-DD) of the last git fetch here, from FETCH_HEAD's time, or None. Dated as
    the household's dates are (lib/hometime.py: config.json's "timezone", else this PC's own zone),
    so a fetch early in the household's morning isn't shown as the day before."""
    try:
        path = Path(git("rev-parse", "--git-path", "FETCH_HEAD"))
        if not path.is_absolute():
            path = Path(root) / path
        moment = os.stat(path).st_mtime
    except Exception:       # noqa: BLE001 - never fetched, or git can't say: no date
        return None
    from decklab.lib import hometime
    return hometime.household_today(settings or {}, now=datetime.fromtimestamp(moment, timezone.utc))


def waiting(git, root, settings):
    """{"channel", "count", "newest", "upstream", "fetched_on", "problem"} for a git checkout, from
    git's refs as last fetched (no fetch). count is commits (main) or newer stable releases
    (release) not yet here; None with problem (fixed words) when it can't be told."""
    out = {"channel": None, "count": None, "newest": None, "upstream": None, "fetched_on": None, "problem": None}
    try:
        out["channel"] = configured(settings)
    except ChannelError:
        out["problem"] = "config.json's update channel isn't main or release."
        return out
    try:
        upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    except Exception:       # noqa: BLE001 - a detached HEAD or no upstream: said in fixed words
        upstream = ""
    if not upstream:
        out["problem"] = "This checkout's branch has no upstream to compare with."
        return out
    out["upstream"] = upstream
    out["fetched_on"] = _fetched_on(git, root, settings)
    try:
        if out["channel"] == "main":
            out["count"] = int(git("rev-list", "--count", "HEAD..@{upstream}"))
        else:
            held = released_tags(git, "HEAD")
            floor = stable_key(held[0]) if held else (-1, -1, -1)
            newer = [tag for tag in _stable(git("tag", "--list", "v*", "--merged", "@{upstream}",
                                                "--no-merged", "HEAD")) if stable_key(tag) > floor]
            out["count"], out["newest"] = len(newer), (newer[0] if newer else None)
    except Exception:       # noqa: BLE001 - git's own words never reach the page
        out["count"], out["newest"] = None, None
        out["problem"] = "Git couldn't count the updates waiting."
    return out


def view(root=None):
    """Settings' answer: None for a release install (release_check says what's newer there), else waiting()."""
    from decklab.lib import build, config
    root = Path(root or build._root or build._DEFAULT_ROOT)
    if build.is_release(root) or not (root / ".git").exists():
        return None

    def git(*args):
        return build._git(root, *args).strip()

    try:
        settings = config.load()
    except Exception:       # noqa: BLE001 - an unreadable config: the channel is unknown, said in fixed words
        return {"channel": None, "count": None, "newest": None, "upstream": None, "fetched_on": None,
                "problem": "config.json can't be read, so the update channel is unknown."}
    return waiting(git, root, settings)
