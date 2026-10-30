"""Forge matchups (lib/forge/, imported when first needed: the server loads it
at start-up for its warm pool): the runner FORGE_JOBS, GET /api/matchups and
/api/matchup, POST /api/matchup/run and /api/matchup/stop, deck_view's
matchups part, and stop_jobs, which stops both runners when the server stops.

FORGE_JOBS and STOP_WAIT live here only: the server reads
api.forge_runs.FORGE_JOBS, and tests patch both here. (It isn't called
matchups.py because the package's matchups() would hide it.)

Simulation wave 3 (forge-trial/sim-wave3-contract.md section 1) adds COORD_JOBS,
the runner of the coordinators that play many matchups for one question (a
field run, api/field_page.py; a variant test, api/variant_page.py), so one that
plays for an hour never holds one of FORGE_JOBS's slots. It lives here only too,
and stop_jobs() stops it.
"""
import importlib
import sys
import traceback

from decklab.lib import config, decks, jobs, live_ranges, permissions

from . import common, practice
from .common import MAX_BODY, _SHA_RE, ApiError, _keys, _parse_body, _public
from .library import _deck_sections, _half_title, is_half, viewer_decks_revision
from . import guard
from .activity import SOMEONE
from .settings import _config_profiles, _current_settings, _require_profile, _writer, own_settings_id

# What a failed run says on the page when the reason isn't one of Forge's own
# plain sentences (forge.ForgeError); the Python error and its traceback go
# to the server log.
MATCHUP_FAILED = ("Something went wrong on the PC while Forge was playing the games. Try again; if it keeps "
                  "happening, the server window says why.")
MATCHUP_BUSY = "10 matchups are already waiting to be played. Try again when one of them has finished."
MATCHUP_STOPPING = "Deck Lab is stopping on the PC, so no new matchup can start."
MATCHUP_WAITING = (jobs.QUEUED, jobs.RUNNING)   # the statuses the server answers with HTTP 202
STOP_WAIT = 10          # seconds stop_matchup() waits for a stopped run to save the games it finished
# A key that isn't 64 hex digits, or one with nothing saved or playing (#/matchup?key=...).
MATCHUP_BAD_KEY = "That link isn't a matchup's address."
MATCHUP_NO_KEY = "There's no saved matchup at that link."
# A run of a deck the viewer may not see, as an admin sees it in the running list (E10-S30).
HIDDEN_RUN = "A run of a deck you can't see"
NAME_KEYS = ("by", "stopped_by", "cancelled_by")


class _Seen:
    """One viewer's Forge reads and run controls (E10-S31).

    Saved sides use visible historical aliases or identical current lists; results need
    two visible sides. Jobs require visible original decks and named opponents. Deleted
    deck references remain with their former space. Starter/stopper names are shown only
    when unambiguously from the viewer's space. An admin sees other jobs as anonymous
    system items with Stop. A script naming nobody sees everything, names included.
    """

    def __init__(self, profile=False):
        if profile is False:
            try:
                profile = guard.viewer()
            except ApiError:
                profile = None
        is_script = guard.script()
        self.deck = guard.deck_reader(profile)
        self.profile = profile
        self.admin = permissions.is_admin(profile, script=is_script)
        self.everything = not profile and is_script
        self.space = (profile.get("space") or permissions.HOME) if profile else None
        self._names = None
        self._lists = None
        self._current_ids = None

    def historical(self, deck_id):
        """A current visible deck, or a deleted deck only in its former owner's space."""
        if not self.deck(deck_id):
            return False
        if self.everything or permissions._deck_space(deck_id) == self.space:
            return True
        if self._current_ids is None:
            self._current_ids = {_TodaysLists._id(s["id"])
                                 for s in [*decks.list_decks(), *decks.beginner_box_pairings()]
                                 if self.deck(s["id"])}
        return _TodaysLists._id(deck_id) in self._current_ids

    def lists(self, forge):
        """This answer's visible saved aliases and matching current lists (E10-S31)."""
        if self._lists is None:
            from decklab.lib.simulation_visibility import VisibleLists
            self._lists = VisibleLists(self.deck, forge.card_sha, self.historical, self.space)
        return self._lists

    def result(self, forge, stored):
        return self.lists(forge).result(stored)

    def item(self, forge, item, today, first_sha=None, prefer=None):
        """A saved item with visible side names and current links, or None."""
        if first_sha is not None and item["sides"][0].get("card_sha") != first_sha:
            stored = forge.load(item["key"])
            if stored is not None:
                item = forge.list_item(stored, first_sha)
        item = self.lists(forge).item(item, forge.load(item["key"]), prefer)
        return None if item is None else self.mask(dict(item, sides=[today.side(side) for side in item["sides"]]))

    def sides(self, sides):
        """True when the viewer sees the deck of every one of these sides ({"id", ...})."""
        sides = list(sides or ())
        return bool(sides) and all(isinstance(side, dict) and self.historical(side.get("id")) for side in sides)

    def coordinator(self, job):
        """True when the viewer sees a COORD_JOBS job: its deck, and a test's one opponent."""
        fn = job.fn
        deck = getattr(fn, "entry", None) or getattr(fn, "base", None)
        if not isinstance(deck, dict):          # else the deck its progress reports
            detail = COORD_JOBS.snapshot(job)["detail"]
            deck = detail.get("deck") if isinstance(detail, dict) else None
        if not isinstance(deck, dict) or not self.historical(deck.get("id")):
            return False
        against = getattr(fn, "against", None)
        if isinstance(against, dict) and not self.historical(against.get("id")):
            return False
        detail = COORD_JOBS.snapshot(job)["detail"]
        pairs = detail.get("pairs") if isinstance(detail, dict) else None
        return not isinstance(pairs, dict) or all(
            self.historical((pair.get("opponent") or {}).get("id")) for pair in pairs.values() if isinstance(pair, dict))

    def stop_target(self, job, visible):
        """The pure run.stop target: original decks and starter, never a displayed alias."""
        fn = job.fn
        sides = list(getattr(fn, "sides", None) or [])
        for key in ("entry", "base", "against"):
            value = getattr(fn, key, None)
            if isinstance(value, dict):
                sides.append(value)
        return {"visible": visible, "by_id": getattr(fn, "by_id", None),
                "spaces": [permissions._deck_space(side.get("id")) for side in sides]}

    def can_stop(self, job, visible=True):
        return permissions.can(self.profile, "run.stop", self.stop_target(job, visible), script=self.everything)

    def require_stop(self, job, visible, missing):
        if not visible and not self.admin:
            raise ApiError(404, missing)
        guard.require(self.profile, "run.stop", self.stop_target(job, visible))

    def hidden_title(self, job):
        """An admin's anonymous system label names only the owning space."""
        spaces = self.stop_target(job, False)["spaces"]
        hidden = next((space for space in spaces if space and space != self.space), None)
        if hidden == permissions.HOME:
            return "A run of one of the home decks"
        if hidden:
            try:
                owner = next((p.get("name") for p in _config_profiles() if p.get("space") == hidden), None)
            except ApiError:
                owner = None
            if owner:
                return f"A run of one of {owner}'s decks"
        return HIDDEN_RUN

    def name(self, value):
        """A starter's or stopper's name as this viewer is told it (the class docstring)."""
        if self.everything or not isinstance(value, str):
            return value
        if self._names is None:
            try:
                self._names = {}
                for profile in _config_profiles():
                    self._names.setdefault(profile["name"], set()).add(profile.get("space") or permissions.HOME)
            except ApiError:
                self._names = {}
        if value in (SOMEONE, "Claude", "System"):
            return value
        return value if self._names.get(value) == {self.space} else SOMEONE

    def mask(self, value):
        """value (an answer, or part of one) with every by, stopped_by and cancelled_by told as name()."""
        if self.everything:
            return value
        if isinstance(value, dict):
            return {key: self.name(item) if key in NAME_KEYS else self.mask(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.mask(item) for item in value]
        return value


def _matchup_error(error):
    """A failed run's error for the page (FORGE_JOBS's describe): STOPPED
    for a run that was stopped (forge.run raises again the jobs.Stopped its
    progress raised), a ForgeError's own plain sentence, and MATCHUP_FAILED
    for anything else (the runner logs its traceback)."""
    forge = sys.modules.get("decklab.lib.forge")
    if isinstance(error, jobs.Stopped):
        return jobs.STOPPED
    if isinstance(error, getattr(forge, "ForgeError", ())):
        return _public(error)
    return MATCHUP_FAILED


MATCHUPS_AT_ONCE = 4    # matchups playing at once: they share the warm pool's queue (forge/pool.py)


def _forge_runner():
    """The background runner for matchups: up to MATCHUPS_AT_ONCE at once, all
    playing in the server's warm pool, whose one queue gives each its share of
    config "forge_workers" workers (the oldest first, so a run started earlier
    finishes first), at most 10 waiting, and apart from JOBS, so practice hands
    never wait behind a matchup."""
    return jobs.Runner(max_running=MATCHUPS_AT_ONCE, max_queued=10, log=lambda text: common._log(text),
                       describe=_matchup_error, name="matchup")


FORGE_JOBS = _forge_runner()

COORDINATORS_AT_ONCE = 2        # field runs and variant tests playing at once (wave 3)
COORDINATORS_QUEUED = 4         # ... and waiting


def _coord_runner():
    """The background runner for wave 3's coordinators (field runs, keys "field:...", and
    variant tests, "variant:..."): up to COORDINATORS_AT_ONCE at once and COORDINATORS_QUEUED
    waiting. A coordinator's pair runs are threads inside its job that play in the server's warm
    pool with every other run, so it never takes one of FORGE_JOBS's slots."""
    return jobs.Runner(max_running=COORDINATORS_AT_ONCE, max_queued=COORDINATORS_QUEUED,
                       log=lambda text: common._log(text), describe=_matchup_error, name="coordinator")


COORD_JOBS = _coord_runner()


def stop_jobs():
    """The server is stopping: both runners start nothing more (jobs.Runner.stop).
    A matchup that's playing stops within about a second and saves every game
    that finished: in the warm pool, its chunks' readers close at once and its
    workers are told to cancel (forge/pool.py); with cold batches, it kills its
    Forge processes (a batch cut short is kept as a partial batch).
    FORGE_JOBS.join() waits for them; the server stops its warm pool after.
    Wave 3's coordinators (COORD_JOBS) stop the same way: their pair runs stop
    and save, then the coordinator; COORD_JOBS.join() waits for them."""
    practice.JOBS.stop()
    FORGE_JOBS.stop()
    COORD_JOBS.stop()


def _forge_module():
    """decklab.lib.forge, or ApiError 500 (the traceback goes to the log)."""
    try:
        return importlib.import_module("decklab.lib.forge")
    except Exception:
        common._log("Forge matchups can't be loaded:\n" + traceback.format_exc())
        raise ApiError(500, "Forge matchups aren't available (the server log says why)") from None


# How a matchup run plays (wave 3's R12, forge-trial/sim-wave3-contract.md section 9): a set
# number of games, or an adaptive run (forge.adaptive.run_adaptive) that plays until the win rate
# is known to within ±3 points ("assess") or one deck is clearly ahead or they're about even
# ("ahead"). The profile setting matchup_mode is the default.
RUN_MODES = ("fixed", "assess", "ahead")
ADAPTIVE_MODES = ("assess", "ahead")


class _MatchupRun:
    """What a matchup job runs in FORGE_JOBS's thread (forge.run, or for an
    adaptive mode forge.adaptive.run_adaptive), and what the answers need to
    know about it while it waits or plays: the two lists as they were asked
    for, a first (entries; sides, as the page gets them; lists, each
    (sections, kind) for forge.ai_limits), the games asked for (None for an
    adaptive run), its mode, and the name of whoever started it. (Whoever
    pressed Stop is the job's cancelled_by, and forge.run saves it with the
    run.)"""

    def __init__(self, forge, entries, sides, lists, games, by, mode="fixed", by_id=None):
        self.forge, self.entries, self.sides, self.lists = forge, entries, sides, lists
        self.games, self.by, self.mode = games, by, mode
        self.by_id = by_id

    def __call__(self, progress):
        if self.mode in ADAPTIVE_MODES:
            saved = self.forge.adaptive.run_adaptive(self.entries[0], self.entries[1], self.mode, by=self.by,
                                                     progress=progress)
        else:
            saved = self.forge.run(self.entries[0], self.entries[1], self.games, by=self.by, progress=progress)
        # The answers read the saved result from disk, so the job keeps only its key.
        return {"key": saved.get("key") if isinstance(saved, dict) else None}


def _matchup_games(profile_id):
    """The games a profile's matchup page offers first: its "matchup_games"
    setting, as a number (ApiError 404 for an unknown profile; the default
    when the database can't be read: settings._current_settings)."""
    _require_profile(profile_id)
    return int(_current_settings(profile_id)["matchup_games"])


def _matchup_mode(profile_id):
    """How a profile's new matchup run plays by default: its "matchup_mode"
    setting ("assess" when it has none, it isn't one of RUN_MODES or the
    database can't be read)."""
    _require_profile(profile_id)
    mode = _current_settings(profile_id).get("matchup_mode")
    return mode if mode in RUN_MODES else "assess"


def _mode(value):
    """The run mode asked for: one of RUN_MODES; ApiError 400 otherwise."""
    if value not in RUN_MODES:
        raise ApiError(400, f"mode must be one of: {', '.join(RUN_MODES)}")
    return value


def _games(value, choices):
    """The games asked for: one of choices (a number, or the same written as
    digits); ApiError 400 otherwise."""
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value not in choices:
        raise ApiError(400, f"games must be one of: {', '.join(str(n) for n in choices)}")
    return value


def _matchup_key(value):
    if not (isinstance(value, str) and _SHA_RE.fullmatch(value)):
        raise ApiError(400, MATCHUP_BAD_KEY)
    return value


def _matchup_lists(forge, asked):
    """[(summary, version, sections, entry)] for the two [(deck id, version)]
    of a matchup, as the lists are today (version None means target).
    ApiError as deck_view for an id or version, and 400 for a Beginner Box
    half or a Commander deck against one that isn't."""
    lists = []
    for deck_id, version in asked:
        version = "target" if version is None else version
        summary, sections = _deck_sections(deck_id, version)
        if is_half(summary):
            raise ApiError(400, f"{_half_title(summary)} is half of a Beginner Box deck, which is only played "
                                f"shuffled together with another half: pick a pairing of two halves.")
        lists.append((summary, version, sections))
    commander = [summary["title"] for summary, _, _ in lists if decks.engine_kind(summary) == "commander"]
    if len(commander) == 1:
        other = next(summary["title"] for summary, _, _ in lists if decks.engine_kind(summary) != "commander")
        raise ApiError(400, f"{commander[0]} is a Commander deck and {other} isn't: a Commander deck only "
                            f"plays another Commander deck.")
    out = []
    for summary, version, sections in lists:
        try:
            entry = forge.entry(summary["id"], version, summary["title"], decks.engine_kind(summary), sections)
        except forge.ForgeError as e:
            raise ApiError(400, _public(e)) from None
        out.append((summary, version, sections, entry))
    return out


def _asked(forge, lists):
    """(key, entries, sides, ai_lists) for _matchup_lists' answer: the
    matchup's key, forge's entries, each side for the page (without "ai")
    and each list's (sections, kind), a first."""
    entries = [entry for *_, entry in lists]
    try:
        key = forge.matchup_key(*entries)
    except forge.ForgeError as e:
        raise ApiError(400, _public(e)) from None
    sides = [{"id": summary["id"], "version": version, "title": summary["title"],
              "kind": forge.page_kind(summary["id"]), "card_sha": entry["card_sha"],
              "card_count": entry["card_count"], "current": True}
             for summary, version, _, entry in lists]
    return key, entries, sides, [(sections, decks.engine_kind(summary)) for summary, _, sections, _ in lists]


class _TodaysLists:
    """The library as it is today, read once per answer, for the sides of
    saved results: the card_sha of each deck id and version's list (for
    "current"; None when the deck or version is gone or can't be read).
    A pairing's two names (its halves in either order) are one deck."""

    def __init__(self, forge):
        self.forge = forge
        self._summaries = None
        self._shas = {}

    @staticmethod
    def _id(deck_id):
        """Current deck id, or a pairing's id with its halves in one order."""
        from decklab.lib import inventory
        if isinstance(deck_id, str) and deck_id.startswith("pairing/"):
            return "pairing/" + "+".join(sorted(deck_id[8:].split("+")))
        try:
            return inventory.resolve_deck_id(deck_id)
        except (inventory.StateError, OSError, ValueError, RuntimeError):
            return deck_id

    def summary(self, deck_id):
        if self._summaries is None:
            self._summaries = {self._id(s["id"]): s for s in [*decks.list_decks(), *decks.beginner_box_pairings()]}
        return self._summaries.get(self._id(deck_id)) if isinstance(deck_id, str) else None

    def remember(self, deck_id, version, card_sha):
        self._shas[(self._id(deck_id), version)] = card_sha

    def same(self, side, deck_id, version):
        """True when a saved result's side was last played as deck_id's version."""
        return (isinstance(side.get("id"), str) and self._id(side["id"]) == self._id(deck_id)
                and side.get("version") == version)

    def sha(self, deck_id, version):
        key = (self._id(deck_id), version)
        if key not in self._shas:
            summary, sha = self.summary(deck_id), None
            if summary is not None and not summary.get("error") and version in summary["versions"]:
                try:
                    sha = self.forge.card_sha(decks.load_deck(summary["id"], version), decks.engine_kind(summary))
                except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError, self.forge.ForgeError):
                    sha = None          # a list that can't be read today isn't current
            self._shas[key] = sha
        return self._shas[key]

    def side(self, side):
        """A side of a saved result (forge.list_item's) for the page, with
        "current": whether it's still that deck id and version's list today,
        and "title": the deck's title today (a renamed deck's results show its
        new name, UI review MU-15), else the title it was last played as. A
        pairing keeps its saved title (its halves in the order played)."""
        out = {key: value for key, value in side.items() if key != "ai"}
        today = self.sha(side.get("id"), side.get("version"))
        out["current"] = today is not None and today == side.get("card_sha")
        summary = self.summary(side.get("id"))
        if summary is not None and not str(side.get("id")).startswith("pairing/"):
            out["id"] = summary["id"]
        if summary is not None and summary.get("title") and not str(side.get("id")).startswith("pairing/"):
            out["title"] = summary["title"]
        return out


def _item_json(forge, item, lists, first_sha=None):
    """A saved result's ListItem for the page (forge.list_item), its sides
    as _TodaysLists.side makes them; with first_sha, from that list's point
    of view (it's sides[0]: forge.results() puts the list the last run was
    asked for first, so the other way round it's listed again)."""
    if first_sha is not None and item["sides"][0].get("card_sha") != first_sha:
        stored = forge.load(item["key"])
        if stored is not None:
            item = forge.list_item(stored, first_sha)
    return dict(item, sides=[lists.side(side) for side in item["sides"]])


def _live_range(wins, other):
    """The same anytime-valid range as adaptive runs, from the live score.

    Each side's draws/errors are non-wins, so the two ranges need not be
    complements. The range covers exactly the supplied score: fixed-run games,
    or a coordinator's cumulative games (including saved variant base games).
    """
    found = live_ranges.anytime_counts(wins[0], sum(wins) + other)
    if found is None:
        return None
    return dict(zip(("value", "low", "high"), (round(n, 4) for n in found)))


def _job_json(job, snap, flip, key=None, sides=None):
    """The "job" of a matchup answer: a run's progress as the page shows it.
    forge reports the wins in card_sha order; flip puts them in the page's.
    waiting is forge's sentence while none of the run's games can play
    because other runs on the PC hold every slot (slots.WAITING), or other
    matchups' games hold the warm pool's workers (pool.QUEUED), else None;
    fallback the sentence saying the warm workers couldn't start, so its
    games play one process at a time (pool.FALLBACK), else None.

    Wave 3 (forge-trial/sim-wave3-contract.md sections 9.3 and 10.5): "mode"
    is the run's ("fixed", "assess" or "ahead"); an adaptive run's "plan"
    ({"mode", "stage", "next_look", "max", "planned", "games_before"}) and
    "range" (the anytime-valid range of the result's games so far, from the
    page's first side: {"value", "low", "high"}). Fixed runs show the same
    kind of range over this run's games, or None before any finish. For a coordinator
    job (COORD_JOBS: a field run or a variant test) playing key, the answer is
    that pair's record from the job's "pairs" (_pair_json), with "via" saying
    which job it is; sides are then the page's two sides, which tell whose
    wins come first."""
    if key is not None and _coord_kind(job) is not None:
        return _pair_json(job, snap, key, sides)
    run = job.fn
    detail = snap["detail"] if isinstance(snap["detail"], dict) else {}
    wins = list(detail.get("wins") or (0, 0))
    if flip:
        wins.reverse()
    total = snap["progress"]["total"]
    ranges = detail.get("range")
    shown = ranges[1 if flip else 0] if isinstance(ranges, list) and len(ranges) == 2 else None
    return {"status": snap["status"], "ahead": snap["ahead"], "done": snap["progress"]["done"],
            "total": (run.games or 0) if total is None else total, "wins": wins, "other": detail.get("other", 0),
            "games_per_min": detail.get("games_per_min"), "eta_s": detail.get("eta_s"), "by": run.by,
            "seconds": snap["seconds"], "waiting": detail.get("waiting"), "fallback": detail.get("fallback"),
            "mode": getattr(run, "mode", "fixed"),
            "plan": detail.get("plan") if isinstance(detail.get("plan"), dict) else None,
            "range": shown if isinstance(shown, dict) else _live_range(wins, detail.get("other", 0))}


def _coord_kind(job):
    """"field" or "variant" for a COORD_JOBS job (its key's prefix), else None."""
    prefix = str(getattr(job, "key", "")).split(":", 1)[0]
    return prefix if prefix in ("field", "variant") else None


def _coord_title(job, detail):
    """A coordinator job's title: "Field run of <deck>" or "Test of a change to <deck>"."""
    deck = detail.get("deck") if isinstance(detail.get("deck"), dict) else {}
    title = deck.get("title") or "a deck"
    return f"Field run of {title}" if _coord_kind(job) == "field" else f"Test of a change to {title}"


def _coord_link(job, detail):
    """Where a coordinator job's page is: the deck page's field section, or the test's page."""
    if _coord_kind(job) == "variant":
        return "#/variant?test=" + job.key.split(":", 1)[1]
    deck = detail.get("deck") if isinstance(detail.get("deck"), dict) else {}
    if not deck.get("id"):
        return None
    return f"#/deck/{deck['id']}?version={deck.get('version') or 'target'}#field"


def _coord_by(job, detail):
    return getattr(job.fn, "by", None) or detail.get("by")


def _via_json(job, detail):
    """The "via" of a matchup a coordinator job is playing (section 10.5)."""
    return {"kind": _coord_kind(job), "job": job.key, "title": _coord_title(job, detail),
            "link": _coord_link(job, detail), "by": _coord_by(job, detail)}


def _pair_json(job, snap, key, sides=None):
    """The "job" of a matchup answer for a key a coordinator job is playing:
    the pair's record from its progress detail ({"done", "total", "wins",
    "other", "playing"}, wins and other from the assessed deck D's side) as
    _job_json's shape, wins in the page's order (D's first unless the page's
    first side is another deck id or version than D's), and "via"."""
    detail = snap["detail"] if isinstance(snap["detail"], dict) else {}
    pairs = detail.get("pairs") if isinstance(detail.get("pairs"), dict) else {}
    pair = pairs.get(key) if isinstance(pairs.get(key), dict) else {}
    done, other = int(pair.get("done") or 0), int(pair.get("other") or 0)
    d_wins = int(pair.get("wins") or 0)
    wins = [d_wins, max(0, done - d_wins - other)]
    deck = detail.get("deck") if isinstance(detail.get("deck"), dict) else {}
    if sides and deck.get("id") is not None and (
            _TodaysLists._id(sides[0].get("id")) != _TodaysLists._id(deck.get("id")) or
            (sides[0].get("version") or "target") != (deck.get("version") or "target")):
        wins.reverse()
    return {"status": snap["status"], "ahead": snap["ahead"], "done": done, "total": int(pair.get("total") or 0),
            "wins": wins, "other": other, "games_per_min": None, "eta_s": None, "by": _coord_by(job, detail),
            "seconds": snap["seconds"], "waiting": None, "fallback": None, "mode": "fixed", "plan": None,
            "range": _live_range(wins, other), "via": _via_json(job, detail)}


def _running_json(job, first_sha=None):
    """A Running item for a run waiting or playing (None once it's over):
    its sides and wins with the deck listed first when it was asked for
    first, or with first_sha's list first (the deck page), and waiting and
    fallback as _job_json gives them. Wave 3 (section 10.5): every item has "kind"
    ("matchup", "field" or "variant"), "title" and "link"; a matchup run's
    also its "mode", "plan" and "eta_s" (forge's estimate of the seconds
    left, for the run activity's details, or None); a coordinator job (COORD_JOBS) is
    {"key", "kind", "title", "by", "done", "total", "link", "status",
    "ahead", "sides": None}."""
    if _coord_kind(job) is not None:
        snap = COORD_JOBS.snapshot(job)
        if snap["status"] not in MATCHUP_WAITING:
            return None
        detail = snap["detail"] if isinstance(snap["detail"], dict) else {}
        return {"key": job.key, "kind": _coord_kind(job), "title": _coord_title(job, detail),
                "by": _coord_by(job, detail), "done": snap["progress"]["done"],
                "total": snap["progress"]["total"], "link": _coord_link(job, detail), "status": snap["status"],
                "ahead": snap["ahead"], "sides": None}
    snap = FORGE_JOBS.snapshot(job)
    if snap["status"] not in MATCHUP_WAITING:
        return None
    sides = [dict(side) for side in job.fn.sides]
    progress = _job_json(job, snap, flip=sides[0]["card_sha"] > sides[1]["card_sha"])
    if first_sha is not None and sides[0]["card_sha"] != first_sha:
        sides.reverse()
        progress["wins"].reverse()
    titles = " v ".join(side.get("title") or "?" for side in sides)
    return {"key": job.key, "sides": sides, "status": snap["status"], "ahead": snap["ahead"],
            "done": progress["done"], "total": progress["total"], "wins": progress["wins"], "by": job.fn.by,
            "waiting": progress["waiting"], "fallback": progress["fallback"], "kind": "matchup", "title": titles,
            "link": f"#/matchup?key={job.key}",
            "mode": progress["mode"], "plan": progress["plan"], "eta_s": progress["eta_s"]}


def _hidden_run(item, title=HIDDEN_RUN):
    """A Running item of a run the viewer may not see, as an admin is shown it (_Seen): its key,
    kind, status and progress, nothing of its decks or who started it."""
    return {"key": item["key"], "kind": item["kind"], "title": title, "by": SOMEONE,
            "done": item["done"], "total": item["total"], "link": None, "status": item["status"],
            "ahead": item["ahead"], "sides": None, "hidden": True, "may_stop": True}


def _running_items(card_sha=None, deck=None, seen=None):
    """The Running items of both runners (matchup runs, then coordinator jobs), each as
    _running_json makes it, those seen (a _Seen, this request's when None) only, and its names
    masked; an admin also gets the others, anonymous (_hidden_run), in the full list. With
    card_sha (the deck page), only that list's matchup runs (it first) and the coordinator jobs
    of deck ((deck id, version): a field run or a test of it)."""
    seen = _Seen() if seen is None else seen
    out = []
    for job in FORGE_JOBS.active():
        if card_sha is not None and card_sha not in (side["card_sha"] for side in job.fn.sides):
            continue
        visible = seen.sides(job.fn.sides)
        if not visible and (card_sha is not None or not seen.admin):
            continue
        item = _running_json(job, card_sha)
        if item is not None:
            out.append(seen.mask(dict(item, may_stop=seen.can_stop(job))) if visible
                       else _hidden_run(item, seen.hidden_title(job)))
    for job in COORD_JOBS.active():
        if card_sha is not None:
            detail = COORD_JOBS.snapshot(job)["detail"]
            mine = detail.get("deck") if isinstance(detail, dict) and isinstance(detail.get("deck"), dict) else {}
            if deck is None or (_TodaysLists._id(mine.get("id")), mine.get("version") or "target") != (
                    _TodaysLists._id(deck[0]), deck[1]):
                continue
        visible = seen.coordinator(job)
        if not visible and (card_sha is not None or not seen.admin):
            continue
        item = _running_json(job)
        if item is not None:
            out.append(seen.mask(dict(item, may_stop=seen.can_stop(job))) if visible
                       else _hidden_run(item, seen.hidden_title(job)))
    return out


def _matchup_notice(job, snap, full, seen=None):
    """The notice of a matchup answer, about the last run (view()'s run
    records): who stopped it (told as seen.name tells it) and after how many
    games, or how many of its batches failed and why (the first one's reason)."""
    name = seen.name if seen is not None else (lambda value: value)
    stopped = snap is not None and snap["error"] == jobs.STOPPED
    if stopped and snap["seconds"] is None:
        by = f" by {name(job.cancelled_by)}" if job.cancelled_by else ""
        return f"Stopped{by} before it started."
    runs = (full or {}).get("runs") or []
    if not runs:
        return None
    last = runs[-1]
    if last.get("stopped"):
        who = name(last.get("stopped_by") or (job.cancelled_by if stopped else None))
        by = f" by {who}" if who else ""
        if not last.get("played"):
            return f"Stopped{by} before any game finished."
        return f"Stopped{by} after {last['played']:,} of {last.get('asked') or 0:,} games."
    failed, batches, reason = last.get("failed"), last.get("batches"), last.get("failure")
    if isinstance(failed, int) and failed > 0 and last.get("played"):
        because = f": {reason.rstrip('.')}" if isinstance(reason, str) and reason else ""
        return f"{failed} of {batches} batches failed{because}. Their games aren't counted."
    return None


def _batching():
    """{"workers", "batch_games"}: config.json's forge_workers, which the
    page's rough time of a run follows (as forge.plan splits it), and
    forge_batch_games. batch_games is no longer used by the page (forge.plan
    no longer reads it); it's kept for older clients. Each is None when
    config.json can't be read or doesn't give a whole number of 1 or more
    there, and the page then uses the usual 16 workers."""
    try:
        settings = config.load()
    except Exception:
        settings = {}
    numbers = {}
    for field, name in (("workers", "forge_workers"), ("batch_games", "forge_batch_games")):
        try:
            value = int(settings.get(name))
        except (TypeError, ValueError, OverflowError):
            value = None
        numbers[field] = value if value is not None and value >= 1 else None
    return numbers


def _earlier(forge, key, fmt, sha_a, sha_b, seen=None):
    """The keys of the saved results of these two lists (either order) and format played
    with another engine than today's (their ListItem's engine "current" isn't True), key
    left out, newest first: the page of two lists today's engine hasn't played links to
    them. [] when the saved results can't be read (logged)."""
    pair = sorted([sha_a, sha_b])
    try:
        seen = _Seen() if seen is None else seen
        today = _TodaysLists(forge)
        return [item["key"] for item in forge.results_for(sha_a)
                if item["key"] != key and item["format"] == fmt
                and sorted(side["card_sha"] for side in item["sides"]) == pair
                and (item.get("engine") or {}).get("current") is not True
                and seen.item(forge, item, today) is not None]
    except Exception:
        common._log(f"The earlier results of a matchup can't be looked up:\n{traceback.format_exc()}")
        return []


COORD_PLAYING = "This matchup is playing as part of {title}: stop it there."


def _job_for_key(key):
    """The coordinator job (COORD_JOBS: a field run or a variant test) whose pair run is playing
    the matchup key now, as {"job", "snap", "pair": the pair's record in the job's progress
    detail (forge.field's section 10.3 shape: opponent, done, total, wins, other, playing),
    "deck_sha": the card_sha of the list the pair's wins are counted for (the coordinator's
    entry), "via": {"kind", "job", "title", "link", "by"}}, or None. Only a pair that is
    playing counts: between its runs the matchup is free."""
    for job in COORD_JOBS.active():
        snap = COORD_JOBS.snapshot(job)
        detail = snap["detail"] if isinstance(snap["detail"], dict) else {}
        pairs = detail.get("pairs") if isinstance(detail.get("pairs"), dict) else {}
        pair = pairs.get(key)
        if snap["status"] != jobs.RUNNING or not isinstance(pair, dict) or not pair.get("playing"):
            continue
        fn = job.fn
        via = dict(getattr(fn, "via", None) or {})
        kind = via.get("kind") or job.key.split(":", 1)[0]
        deck = getattr(fn, "entry", None) or getattr(fn, "base", None) or {}
        return {"job": job, "snap": snap, "pair": pair, "deck_sha": deck.get("card_sha"),
                "via": {"kind": kind, "job": job.key,
                        "title": via.get("title") or getattr(fn, "title", None) or f"a {kind} run",
                        "link": via.get("link") or getattr(fn, "link", None), "by": getattr(fn, "by", None)}}
    return None


def _coord_progress(found, first_sha, shown=True):
    """A matchup answer's "job" while a coordinator's pair run plays it (_job_for_key's found):
    the pair's done, total, wins (in the page's order: first_sha's list first) and other, who
    started the coordinator, and "via", so the page's bar moves and its Stop becomes a link.
    shown False (a coordinator the viewer may not see, _Seen.coordinator: a field run or test of
    another space's deck with the same lists) leaves out what names it: its via has no job, title
    or link, and by is "someone" (E10-S30)."""
    pair, snap = found["pair"], found["snap"]
    done, wins, other = pair.get("done") or 0, pair.get("wins") or 0, pair.get("other") or 0
    pair_wins = [wins, max(0, done - wins - other)]
    if found["deck_sha"] is not None and first_sha != found["deck_sha"]:
        pair_wins.reverse()
    out = {"status": jobs.RUNNING, "ahead": 0, "done": done, "total": pair.get("total") or done,
            "wins": pair_wins, "other": other, "games_per_min": None, "eta_s": None, "by": found["via"]["by"],
            "seconds": snap["seconds"], "waiting": None, "fallback": None,
            "range": _live_range(pair_wins, other), "via": found["via"]}
    if not shown:
        out.update(by=SOMEONE, via={"kind": None, "job": None, "title": None, "link": None, "by": SOMEONE})
    return out


def _matchup_json(forge, key, sides, ai_lists, default_games, stored, default_mode=None, seen=None):
    """The answer of GET /api/matchup (and of both POSTs) for key: sides
    [a, b] are the page's Sides without "ai", in the order it asked for
    them; ai_lists each side's (sections, kind), for its AI limits while
    nothing has been played (None: taken from stored); stored forge.load(key).
    Each side also gets "auto_profile" (from stored, as list items' sides
    have it: forge.engine.auto_profile_flag; None before any game), and the
    answer "earlier" (_earlier). default_mode is the profile's "matchup_mode"
    (_matchup_mode), None without a profile. Its names (by, stopped_by,
    cancelled_by and the notice's) are told as seen (a _Seen, this request's
    when None) tells them; the caller has checked that seen sees both sides."""
    seen = _Seen() if seen is None else seen
    sha_a, sha_b = sides[0]["card_sha"], sides[1]["card_sha"]
    a_side = 0 if sha_a <= sha_b else 1         # forge keeps the sides in card_sha order
    full = forge.view(stored, sha_a) if stored is not None else None
    result = full if full is not None and full.get("games") else None
    for position, side in enumerate(sides):
        if stored is not None:
            index = a_side if position == 0 else 1 - a_side
            side["ai"] = forge.side_ai(stored, index)
            side.setdefault("auto_profile", forge.engine.auto_profile_flag(stored["sides"][index]))
        else:
            side["ai"] = forge.ai_limits(*ai_lists[position]) if ai_lists else None
            side.setdefault("auto_profile", None)
    job = FORGE_JOBS.get(key)
    snap = FORGE_JOBS.snapshot(job) if job is not None else None
    progress = notice = error = None
    coord = _job_for_key(key) if snap is None or snap["status"] not in MATCHUP_WAITING else None
    if snap is not None and snap["status"] in MATCHUP_WAITING:
        status, progress = snap["status"], _job_json(job, snap, flip=a_side == 1)
        progress["may_stop"] = seen.can_stop(job, seen.sides(job.fn.sides))
    elif coord is not None:
        # A field run or variant test plays it; one of a deck the viewer may not see, anonymously.
        status, progress = jobs.RUNNING, _coord_progress(coord, sha_a, seen.coordinator(coord["job"]))
    else:
        if snap is not None and snap["status"] == jobs.ERROR and snap["error"] != jobs.STOPPED:
            error = snap["error"]
        elif full is not None and full.get("runs"):
            last = full["runs"][-1]
            if last.get("error") and not last.get("played") and not last.get("stopped"):
                error = last["error"]           # a run that played nothing, since the server restarted
        notice = _matchup_notice(job, snap, full, seen)
        status = "done" if result is not None else "error" if error else "none"
    fmt = full["format"] if full is not None else forge.fmt_for(ai_lists[0][1])
    if result is not None and isinstance(result.get("adaptive_last"), dict):
        result["adaptive_last"] = _adaptive_last(result["adaptive_last"], a_side)
    from . import play_comparison
    return {"key": key, "format": fmt, "sides": sides, "status": status, "job": seen.mask(progress),
            "result": seen.mask(result), "notice": notice, "error": error, "choices": list(forge.GAME_CHOICES),
            "real_games": play_comparison.summarize(sides, fmt, profile=seen.profile, script=seen.everything),
            "default_games": forge.DEFAULT_GAMES if default_games is None else default_games,
            "default_mode": default_mode,
            **_batching(), "forge": forge.status(), "earlier": _earlier(forge, key, fmt, sha_a, sha_b, seen),
            "estimates": _estimates(forge, sides, fmt, None if _starts_afresh(result) else stored, a_side)}


def _starts_afresh(result):
    """Whether more games of this result's lists start a new result rather than add to it: a result
    of an earlier engine (its "engine" current is False) is never added to, so the times the page
    shows for Play are a new result's, from no games (_estimates with nothing stored)."""
    return result is not None and (result.get("engine") or {}).get("current") is False


def _adaptive_last(last, a_side):
    """result.adaptive_last for the page (forge.adaptive's summary, section 14.1): its
    stopped run's anytime-valid range from the page's first side (the summary keeps one per
    stored side, "ranges")."""
    out = dict(last)
    ranges = last.get("ranges")
    if isinstance(ranges, list) and len(ranges) == 2:
        out["range"] = ranges[a_side]
    return out


def _estimates(forge, sides, fmt, stored, a_side):
    """The answer's "estimates" (section 9.3): {"fixed": {"200": [low, high], ...}, "assess":
    [low, high], "ahead": [low, high]} minutes from forge.estimate.matchup, for the games
    already saved; None when there's no estimator (the page then keeps its own rough times) or
    it fails (logged)."""
    estimate = getattr(forge, "estimate", None)
    if estimate is None or not hasattr(estimate, "matchup"):
        return None
    kind = "commander" if fmt == "Commander" else "constructed"
    entries = [{"card_sha": side["card_sha"], "kind": kind} for side in sides]
    try:
        games = forge.views._games(stored) if stored is not None else []
        return estimate.matchup(entries[0], entries[1], games, a_side if stored is not None else 0,
                                choices=list(forge.GAME_CHOICES))
    except Exception:
        common._log("A matchup's time estimates can't be worked out:\n" + traceback.format_exc())
        return None


def _matchup_by_key(forge, key, default_games, default_mode=None, seen=None):
    """The answer for a key alone: saved sides under visible aliases, in
    the order the last run asked for, or the active run's requested sides;
    ApiError 404 for neither, and the same 404 when seen (a _Seen, this
    request's when None) doesn't see every side (E10-S30)."""
    seen = _Seen() if seen is None else seen
    stored = forge.load(key)
    if stored is not None:
        item = forge.list_item(stored)
        lists = _TodaysLists(forge)
        item = seen.item(forge, item, lists)
        if item is None:
            raise ApiError(404, MATCHUP_NO_KEY)
        sides = item["sides"]
        return _matchup_json(forge, key, sides, None, default_games, stored, default_mode, seen)
    job = FORGE_JOBS.get(key)
    if job is None:
        coord = _job_for_key(key)
        fn = coord["job"].fn if coord is not None else None
        deck = getattr(fn, "entry", None) or getattr(fn, "base", None)
        opponent = coord["pair"].get("opponent") if coord is not None else None
        if not (isinstance(deck, dict) and isinstance(opponent, dict)) or not seen.sides([deck, opponent]):
            raise ApiError(404, MATCHUP_NO_KEY)
        # Nothing saved yet, and a field run's (or variant test's) pair run plays it: its two lists.
        asked_lists = [(deck["id"], deck["version"]), (opponent["id"], opponent["version"])]
        try:
            asked_key, _, sides, ai_lists = _asked(forge, _matchup_lists(forge, asked_lists))
        except ApiError as e:
            if e.status == 404:             # a deck gone or hidden since: as no matchup at that link
                raise ApiError(404, MATCHUP_NO_KEY) from None
            raise
        if asked_key != key:
            # A draft variant's paired key isn't the saved base deck's matchup.
            raise ApiError(404, MATCHUP_NO_KEY)
        return _matchup_json(forge, key, sides, ai_lists, default_games, None, default_mode, seen)
    if not seen.sides(job.fn.sides):
        raise ApiError(404, MATCHUP_NO_KEY)
    return _matchup_json(forge, key, [dict(side) for side in job.fn.sides], job.fn.lists, default_games, None,
                         default_mode, seen)


def matchups(running=False):
    """GET /api/matchups[?running=1]: every saved result (forge.results(), newest first,
    each a ListItem whose sides say whether they're still that deck's list,
    and whose "engine" says what played it and whether that's today's
    engine; forge leaves out results with no games counted), the runs waiting or
    playing (Running items, in the order they run), the game choices, the
    default number of games, config.json's forge_workers and
    forge_batch_games as "workers" and "batch_games" (_batching(); the page's
    rough time of a run uses workers only, batch_games is kept for older
    clients), forge.status() and decks_revision (the viewer's, as GET /api/decks') from the same inventory snapshot as
    current result links, so another device's rename can refresh the library. A result that can't be
    shown is left out (the log says why), so it can't hide the others. Only the results and runs
    whose every side the viewer may see are listed, with names from other spaces as "someone"
    (_Seen, E10-S30); an admin also sees the other runs, anonymous.

    With running (?running=1, the top bar's "Forge playing" pill, which asks on
    every page), only {"running", "forge"}: the runs waiting or playing, without
    reading a saved result, so asking often costs the PC next to nothing."""
    forge = _forge_module()
    seen = _Seen()
    if running:
        return {"running": _running_items(seen=seen), "forge": forge.status()}
    from decklab.lib import inventory
    if not inventory.is_pinned():
        with inventory.pinned():
            return matchups()
    with common.state_errors():
        decks_revision = viewer_decks_revision(guard.visible_decks(decks.list_decks()))    # as GET /api/decks
    lists = _TodaysLists(forge)
    results = []
    with forge.engine.held():           # today's engine, worked out once for every item
        for item in forge.results():
            try:
                item = seen.item(forge, item, lists)
                if item is not None:
                    results.append(item)
            except Exception:
                common._log(f"A matchup result can't be listed:\n{traceback.format_exc()}")
    running = _running_items(seen=seen)
    return {"results": results, "running": running, "choices": list(forge.GAME_CHOICES),
            "default_games": forge.DEFAULT_GAMES, **_batching(), "forge": forge.status(),
            "decks_revision": decks_revision}


def matchup(a=None, av=None, b=None, bv=None, key=None, profile=None):
    """GET /api/matchup?a=<id>&av=target|owned&b=<id>&bv=target|owned, or
    ?key=<64 hex>, either with &profile=<id>: one matchup.

    Returns {key, format, sides [a, b] (each a Side with "ai", what Forge's
    AI can't play in that list, and "auto_profile", whether Forge's AI
    played it as a slower, non-aggro deck in every game: None before any
    game or when the run didn't say), status, job, result, notice, error,
    choices, default_games, default_mode, workers, batch_games, forge, earlier,
    estimates}:
    - status "queued" or "running" while a run for the key waits or plays
      (job: its progress, from a's point of view; result: what was saved
      before it, or None), else "done" when a result is saved, "error" when
      the last run failed and nothing is saved, or "none".
    - result is forge.view() from a's point of view; None until a game has
      been counted.
    - notice says who stopped the last run and after how many games, or how
      many of its batches failed; error why the last run failed (a
      ForgeError's plain sentence, or MATCHUP_FAILED).
    - default_games is the profile's "matchup_games" setting, or
      forge.DEFAULT_GAMES without a profile; default_mode its
      "matchup_mode" setting (the page's first run mode), or None without a
      profile.
    - workers and batch_games are config.json's forge_workers and
      forge_batch_games (_batching()). The page's rough time of a run uses
      workers only; batch_games is no longer used and is kept for older
      clients.
    - earlier: the keys of these two lists' saved results played with
      another engine than today's (simulation wave 2: before it, plain
      Forge, another Forge version...), newest first, for a page today's
      engine hasn't played yet to link to (_earlier). A run of the two
      lists never adds to those: it starts or adds to today's (key).

    While a field run or a variant test (COORD_JOBS, wave 3) plays the
    key, status is "running" and job is that pair's record with "via"
    (_job_for_key, _coord_progress); asked for by key with nothing saved
    yet, the sides are its two lists.

    Asked for by key, the sides use the newest visible saved aliases, or
    identical current lists, in the order the last run asked for. ApiError 400 for a bad id,
    version or key, a Beginner Box half, a Commander deck against one that
    isn't, or both a key and decks; 404 for an unknown deck, version or
    profile, or a key with no saved result or run (and the same for a deck,
    or a key with a side, the viewer may not see: E10-S30); 503 until the card data
    is ready; 500 when the matchup code can't be loaded.

    The defaults are read only from the viewer's own settings (settings.own_settings_id,
    E10-S34): a ?profile= naming anyone else, or no one known, answers as without a profile."""
    profile = own_settings_id(profile) if profile is not None else None
    default_games = _matchup_games(profile) if profile is not None else None
    default_mode = _matchup_mode(profile) if profile is not None else None
    if key is not None:
        if any(value is not None for value in (a, av, b, bv)):
            raise ApiError(400, "Ask for a matchup by its key or by its two decks, not both")
        key = _matchup_key(key)
        return _matchup_by_key(_forge_module(), key, default_games, default_mode)
    if a is None or b is None:
        raise ApiError(400, "Say which two decks play: a and b (with av and bv, target or owned), or a key")
    forge = _forge_module()
    key, _, sides, ai_lists = _asked(forge, _matchup_lists(forge, [(a, av), (b, bv)]))
    return _matchup_json(forge, key, sides, ai_lists, default_games, forge.load(key), default_mode)


def run_matchup(body):
    """POST /api/matchup/run {"profile", "a", "b", "av"?, "bv"?, "mode"?,
    "games"?}: play a matchup (or more games of one) in Forge.

    mode (wave 3's R12, forge-trial/sim-wave3-contract.md section 9.3) is
    "fixed", "assess" (until the win rate is known to within ±3 points) or
    "ahead" (until one deck is clearly ahead, or they're about even). Left
    out, it's "fixed" when games is given (as the page asked before wave 3),
    else the profile's "matchup_mode" setting. games is read only with
    "fixed": one of forge.GAME_CHOICES (the profile's "matchup_games"
    setting when it's left out). A run for the same two lists that's already
    waiting or playing is joined instead (its games and mode stand), and the
    answer's "joined" says so: {"mode", "by"} of the run joined (None when
    this request started the run). Returns what matchup() would, from a's
    point of view, with "joined"; the run goes to FORGE_JOBS, where it plays
    after any others waiting. ApiError as matchup() for the decks, 400 for a
    mode not in RUN_MODES or games not in the choices, 403 without a
    profile or while the simulations setting refuses (api/simulations.py), and 503 when Forge isn't ready (forge.status()'s problem), 10
    runs are already waiting (MATCHUP_BUSY), or the server is stopping
    (MATCHUP_STOPPING)."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    guard.require_start(profile)        # the simulations setting (api/simulations.py)
    _keys(data, ("profile", "a", "b"), ("av", "bv", "games", "mode"))
    forge = _forge_module()
    default_games = _matchup_games(profile["id"])
    if "mode" in data:
        mode = _mode(data["mode"])
    else:
        mode = "fixed" if "games" in data else _matchup_mode(profile["id"])
    games = None
    if mode == "fixed":
        games = _games(data["games"], forge.GAME_CHOICES) if "games" in data else default_games
    lists = _matchup_lists(forge, [(data["a"], data.get("av")), (data["b"], data.get("bv"))])
    key, entries, sides, ai_lists = _asked(forge, lists)
    state = forge.status()
    if not state.get("ready"):
        raise ApiError(503, state.get("problem") or "Forge isn't ready to play games on the PC.")
    run = _MatchupRun(forge, entries, [dict(side) for side in sides], ai_lists, games, profile["name"], mode,
                       by_id=profile["id"])
    try:
        job = FORGE_JOBS.submit(key, run, rerun=True)
    except jobs.Busy as e:
        raise ApiError(503, MATCHUP_STOPPING if e.stopping else MATCHUP_BUSY) from None
    joined, seen = None, _Seen(profile)
    if job.fn is not run:
        joined = seen.mask({"mode": getattr(job.fn, "mode", "fixed"), "by": getattr(job.fn, "by", None)})
    answer = _matchup_json(forge, key, sides, ai_lists, default_games, forge.load(key),
                           _matchup_mode(profile["id"]), seen)
    answer["joined"] = joined
    return answer


def stop_matchup(body):
    """POST /api/matchup/stop {"profile", "key", "a"?, "av"?, "b"?, "bv"?}: Stop.

    A run waiting for key is taken off the queue; a playing one stops within
    about a second and keeps every game that finished (this waits up to
    STOP_WAIT seconds for it to save them). The notice then names the
    profile that stopped it (the first, if two press Stop). Stopping a key
    with no run waiting or playing changes nothing. Returns what matchup()
    would: from a's point of view when the two decks are given too (both a
    and b; they must be the key's), else by key. ApiError 400 for a bad key,
    only one of the decks, or decks that aren't the key's, 403 without a
    profile, 404 for a key with no saved result or run, and 409 while a
    field run or variant test plays the key (COORD_PLAYING: it's stopped
    there). A visible run may be stopped by its starter (profile id), a profile of a deck's
    space, or an admin. A hidden run answers 404 except for an admin, whose response is
    only {"key", "stopped", "hidden": True}. Coordinator keys from the running list are
    accepted too, so an admin can stop an anonymous field run or variant test here."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    _keys(data, ("profile", "key"), ("a", "av", "b", "bv"))
    if isinstance(data["key"], str) and data["key"].startswith(("field:", "variant:")):
        seen = _Seen(profile)
        job = COORD_JOBS.get(data["key"])
        if job is None:
            raise ApiError(404, MATCHUP_NO_KEY)
        visible = seen.coordinator(job)
        seen.require_stop(job, visible, MATCHUP_NO_KEY)
        stopped = COORD_JOBS.cancel(data["key"], by=profile["name"])
        if stopped:
            job.wait(STOP_WAIT)
        return {"key": data["key"], "stopped": stopped, "hidden": not visible}
    key = _matchup_key(data["key"])
    forge = _forge_module()
    asked = None
    if any(data.get(name) is not None for name in ("a", "av", "b", "bv")):
        if data.get("a") is None or data.get("b") is None:
            raise ApiError(400, "Give both decks (a and b) with the key, or neither.")
        asked = _asked(forge, _matchup_lists(forge, [(data["a"], data.get("av")), (data["b"], data.get("bv"))]))
        if asked[0] != key:
            raise ApiError(400, "Those two decks aren't the ones playing that matchup (their lists may have "
                                "changed): reload the page.")
    seen = _Seen(profile)
    job = FORGE_JOBS.get(key)
    if job is not None:
        visible = seen.sides(job.fn.sides)
    else:
        stored = forge.load(key)
        visible = stored is not None and seen.result(forge, stored)
    if job is not None:
        seen.require_stop(job, visible, MATCHUP_NO_KEY)
    elif not visible and not seen.admin:
        raise ApiError(404, MATCHUP_NO_KEY)
    if job is None or FORGE_JOBS.snapshot(job)["status"] not in MATCHUP_WAITING:
        coord = _job_for_key(key)
        if coord is not None:
            seen.require_stop(coord["job"], seen.coordinator(coord["job"]), MATCHUP_NO_KEY)
            title = coord["via"]["title"] if seen.coordinator(coord["job"]) else "another run"
            raise ApiError(409, COORD_PLAYING.format(title=title))
    if job is None and not visible:
        raise ApiError(404, MATCHUP_NO_KEY)
    stopped = job is not None and FORGE_JOBS.cancel(key, by=profile["name"])
    if stopped:
        job.wait(STOP_WAIT)
    if not visible:
        return {"key": key, "stopped": stopped, "hidden": True}
    default_games, default_mode = _matchup_games(profile["id"]), _matchup_mode(profile["id"])
    if asked is not None:
        _, _, sides, ai_lists = asked
        return _matchup_json(forge, key, sides, ai_lists, default_games, forge.load(key), default_mode, seen)
    return _matchup_by_key(forge, key, default_games, default_mode, seen)


def _deck_matchups(summary, version, sections):
    """deck_view's "matchups" for one list: {"ai": forge.list_ai (what Forge's
    AI can't play in it, with the cards it never cast in all its saved games;
    "games" says how many games that's judged by), "results": its saved
    results (ListItems with this list first), then those of this
    deck and version's earlier lists (a side last played as this deck id
    and version, but not with today's list: that side comes first, with
    "current" false), each newest first; "running": runs of it waiting or
    playing (this list first), "forge": forge.status(), "cards":
    forge.list_cards (how each of its cards played, from the card log,
    pooled over every saved result of this list; None without card data,
    or when working it out fails: that's logged, and the rest stays)}.
    None for a Beginner Box half (it only plays in a pairing), and when the
    matchup code can't be loaded or fails: the deck page still shows, and
    the log says why. It never starts a run."""
    if is_half(summary):
        return None
    try:
        forge = _forge_module()
    except ApiError:
        return None                 # _forge_module logged why
    try:
        kind = decks.engine_kind(summary)
        sha = forge.card_sha(sections, kind)
        lists = _TodaysLists(forge)
        lists.remember(summary["id"], version, sha)
        results, earlier = [], []
        seen = _Seen()
        prefer = {"id": summary["id"], "version": version, "title": summary["title"], "card_sha": sha}
        with forge.engine.held():       # today's engine, worked out once for every item
            for item in forge.results():
                visible = seen.item(forge, item, lists, prefer=prefer)
                if visible is None:
                    continue
                if sha in (side.get("card_sha") for side in item["sides"]):
                    results.append(seen.item(forge, item, lists, sha, prefer))
                    continue
                older = next((side["card_sha"] for side in visible["sides"]
                              if lists.same(side, summary["id"], version)), None)
                if older is not None:
                    earlier.append(seen.item(forge, item, lists, older))
        results += earlier
        running = _running_items(sha, (summary["id"], version), seen)
        try:
            cards = forge.list_cards(sections, kind, keep=lambda result: seen.result(forge, result))
        except Exception:
            common._log(f"The card stats of {summary['id']} can't be worked out:\n" + traceback.format_exc())
            cards = None
        return {"ai": forge.list_ai(sections, kind, keep=lambda result: seen.result(forge, result)),
                "results": results, "running": running,
                "forge": forge.status(), "cards": cards}
    except Exception:
        common._log(f"The matchups of {summary['id']} can't be looked up:\n" + traceback.format_exc())
        return None
