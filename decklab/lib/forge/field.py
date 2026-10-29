"""The field view (simulation wave 3's R13, forge-trial/sim-wave3-contract.md section 10): how a
list does against the current decks of its format. A field run is a set of ordinary matchup
runs (each pair under its own key, stream and base), a floor of games against each opponent
then APT allocation (seqstats.apt_pick); the view adds the equal-weight field average, a
Bradley-Terry rating with a starter term, and residual flags.

Per-card numbers from field runs: a field run's games are ordinary matchup results, so
cardstats.list_cards pools them with Mantel-Haenszel weights, which lean toward close opponents
(APT gives them more games); valid per stratum, but not the field average's equal-weight
estimand. Equal-weight per-card pooling over field opponents isn't built (section 7.7).

    BUDGETS                 ("quick", "standard", "thorough"); "fixed:N" and an int are the
                            command line's and the harness's
    field_lists(fmt)        the field's lists of a format (section 10.1): [entry]
    field_notes(fmt)        why lists that would be in the field aren't (deck files with
                            errors, bad simulation.json names), as sentences
    opponents(entry, opponents=None)
                            the field minus every list with entry's deck id, limited to the
                            "<deck id>[@version]" names in opponents when given
    plan(entry, budget, results_dir=None, opponents=None)
                            what a field run would play now: the per-opponent target and
                            each opponent's new games (the floor's, and APT's spread evenly)
    run_field(entry, budget="standard", *, by, progress=None, results_dir=None, pool=None,
              local=False, seed_base=None, log_dir=None, log_every=1, inflight=None, opponents=None)
                            the field run (section 10.3); returns its note (section 10.3)
    view(entry, results_dir=None)
                            the field view (sections 10.4 and 15)
    averages(fmt, results_dir=None)
                            every field list's field average and when it was tested (the
                            library's Forge line)
    last_note(entry, results_dir=None)
                            the last field run's note of this list, or None

The optional space/public/visible arguments select a member's field: its own
space plus spaces accepted by public(space_id), then visible(deck_id) filters
the viewer's opponents and their notes. keep(result) filters saved numbers and
ratings. product_notes=False hides home product diagnostics from outsiders.
Callers on the page supply all these checks; command-line defaults retain home's
field even when the entry is a member's deck. No filtered field is cached.

The field is worked out again for every call (decks.list_decks() and products/status.csv): it's
cheap, and a deck file edited a moment ago counts at once. decklab/simulation.json's "field"
section ({"Constructed": {"add": [...], "remove": [...]}, "Commander": {...}}, each name
"<deck id>[@version]") adds lists the rules leave out (a Beginner Box pairing, a product whose
"intact" is still blank) and takes lists out (a house deck built from a precon that's also kept
whole). HOME's saved field choices (E3-S23, field_policy_overlay.py) are laid over those
edits for current house decks; without any (or before migration 0017) the field is as above.
"""
import json
import threading
import time
import traceback

from decklab.lib import decks, spaces
from decklab.lib import pool as card_pool          # products/status.csv (read_status)

from . import (common, deck_identity, engine, field_exclusions, field_policy_overlay, lifecycle, lists, runner,
               saved, seqstats, views)
from .common import ForgeError

BUDGETS = ("quick", "standard", "thorough")
BUDGET_GAMES = {"quick": None, "standard": 400, "thorough": 800}   # APT's games per opponent (None: the floor only)
ENGINE_CHANGED = "The engine changed during this run: play it again."
NO_OPPONENTS = "There's no other deck in the {fmt} field for it to play."
BUSY_TWICE = "it was being played elsewhere twice, so the field run left it out"
FAILED = "an error in Deck Lab ({name})"
NOTES_DIR = "field"             # <card_sha>-<format>-<space>.json; legacy files belong to home
NOTE_WAIT = 30                  # seconds a note waits for another process writing the same file
LOOP_S = 0.2                    # how often the coordinator looks at its pair runs (and reports)
FIELD_STATUSES = ("owned", "preordered", "ordered")     # products/status.csv statuses whose intact decks count
_notes_lock = threading.Lock()


# ============================================================ the field

def _simulation_edits(fmt, *, trace=None, exclusions=None):
    """(add, remove) of decklab/simulation.json's field section for fmt: lists of "<deck
    id>[@version]" names; ([], []) when the file or the section is missing, and when it can't be
    read (logged)."""
    from . import pilots            # pilots names the file; it comes before this part
    try:
        with open(pilots.SIMULATION_FILE, encoding="utf-8") as f:
            found = json.load(f)
    except FileNotFoundError:
        field_exclusions.notify(exclusions, "configuration", [])
        return [], []
    except (OSError, ValueError) as e:
        common._log(f"decklab/simulation.json can't be read, so the field has no edits: {e}")
        if trace is not None:
            trace.unavailable()
        field_exclusions.notify(exclusions, "unavailable")
        return [], []
    configuration_ok = True
    if exclusions is not None and (not isinstance(found, dict) or
                                   (found.get("field") is not None and not isinstance(found["field"], dict))):
        configuration_ok = False
        field_exclusions.notify(exclusions, "unavailable")
    if exclusions is not None and isinstance(found, dict) and isinstance(found.get("field"), dict):
        raw_section = found["field"].get(fmt)
        if raw_section is not None and not isinstance(raw_section, dict):
            configuration_ok = False
            field_exclusions.notify(exclusions, "unavailable")
    if trace is not None and (not isinstance(found, dict) or
                             (found.get("field") is not None and not isinstance(found["field"], dict))):
        trace.unavailable()
        return [], []
    section = ((found.get("field") if isinstance(found, dict) else None) or {}).get(fmt) or {}
    if not isinstance(section, dict):
        if trace is not None:
            trace.unavailable()
        field_exclusions.notify(exclusions, "unavailable")
        return [], []
    if exclusions is not None and any(not isinstance(section.get(part, []), list) or
                                      any(not isinstance(name, str) for name in section.get(part, []))
                                      for part in ("add", "remove")):
        configuration_ok = False
        field_exclusions.notify(exclusions, "unavailable")
    if trace is not None and any(not isinstance(section.get(part, []), list) or
                                 any(not isinstance(name, str) for name in section.get(part, []))
                                 for part in ("add", "remove")):
        trace.unavailable()
        return [], []
    names = [[name for name in (section.get(part) or []) if isinstance(name, str) and name.strip()]
             for part in ("add", "remove")]
    add, remove = [name.strip() for name in names[0]], [name.strip() for name in names[1]]
    field_exclusions.notify(exclusions, "configuration", remove, configuration_ok)
    return add, remove


def _split_name(name):
    """("<deck id>", version or None) of a "<deck id>[@version]" name."""
    deck_id, _, version = name.partition("@")
    return deck_id.strip(), (version.strip() or None)


def _same_id(a, b):
    """True for current/former deck ids and a pairing's halves in either order."""
    return deck_identity.same(a, b)


def _fmt_of(summary):
    return lists.fmt_for(decks.engine_kind(summary))


def _house_version(summary):
    """The list of a deck file the field plays: its Built version when the deck is built and has
    that line, else the target list."""
    built = summary.get("built_version")
    if summary.get("status") == "built" and built in summary.get("versions", []):
        return built
    return "target"


def _entry(summary, version):
    sections = decks.load_deck(summary["id"], version)
    return lists.entry(summary["id"], version, summary["title"], decks.engine_kind(summary), sections)


def _product_file(deck_id):
    return deck_id.split("/")[1] + ".csv"


def _field(fmt, *, space="home", public=None, visible=None, product_notes=True, trace=None, exclusions=None):
    """([entry], [note]) of the field of fmt (section 10.1), sorted by title, from one inventory
    snapshot (the request's or command's, else one pinned for this call: decklab/lib/inventory).
    An optional membership trace records decisions after visibility checks; legacy callers
    retain the same entries, notes and defaults."""
    from decklab.lib import inventory
    if not inventory.is_pinned():
        with inventory.pinned():
            return _field(fmt, space=space, public=public, visible=visible, product_notes=product_notes,
                          trace=trace, exclusions=exclusions)
    field_exclusions.notify(exclusions, "begin")
    chosen, notes = [], []
    status_unavailable = False
    try:
        statuses = card_pool.read_status()
    except (OSError, UnicodeDecodeError, ValueError) as e:
        statuses = {}
        status_unavailable = True
        field_exclusions.notify(exclusions, "unavailable")
        if product_notes:
            notes.append(f"The products' status list can't be read, so no product deck is in the field ({e}).")
    summaries = decks.list_decks()
    for summary in summaries:
        deck_id = summary["id"]
        owner = summary.get("space") or spaces.space_of(deck_id)
        if (space == "home" and owner != "home") or \
                (space != "home" and owner != space and not (public and public(owner))) or \
                (visible is not None and not visible(deck_id)):
            continue
        house = spaces.split_deck_id(deck_id)[1] in decks.KINDS
        if house:
            if summary.get("error"):
                if (spaces.split_deck_id(deck_id)[1] == "commander" and fmt == "Commander") or \
                        (spaces.split_deck_id(deck_id)[1] == "casual" and fmt == "Constructed"):
                    notes.append(f"{summary.get('title') or deck_id} isn't in the field: its file can't be read "
                                 f"({summary['error']}).")
                    if trace is not None:
                        trace.candidate(summary, None, "unreadable")
                    field_exclusions.notify(exclusions, "unavailable")
                continue
            if _fmt_of(summary) == fmt:
                chosen.append((summary, _house_version(summary)))
                if trace is not None:
                    trace.candidate(summary, _house_version(summary), "default")
            continue
        if not deck_id.startswith("product/") or summary.get("error") or deck_id.startswith(
                f"product/{decks.BEGINNER_BOX}/"):
            if summary.get("error"):
                field_exclusions.notify(exclusions, "unavailable")
            if trace is not None and _fmt_of(summary) == fmt:
                trace.candidate(summary, None, "unreadable" if summary.get("error") else "beginner_half")
            continue
        status = statuses.get(_product_file(deck_id))
        if status is not None and status.status in FIELD_STATUSES and status.intact and _fmt_of(summary) == fmt:
            chosen.append((summary, "target"))
            if trace is not None:
                trace.candidate(summary, "target", "default")
        elif trace is not None and _fmt_of(summary) == fmt:
            if status_unavailable:
                trace.unavailable()
            trace.product(summary, status)
    if trace is not None:
        trace.pairings(fmt, space, public, visible)
    edit_options = {}
    if trace is not None:
        edit_options["trace"] = trace
    if exclusions is not None:
        edit_options["exclusions"] = exclusions
    add, remove = _simulation_edits(fmt, **edit_options)
    # HOME's saved choices mask their decks' legacy directives first (E3-S23).
    policy = field_policy_overlay.prepare(fmt, space, chosen, notes, trace=trace, exclusions=exclusions)
    add, remove = policy.directives(add, remove, exclusions)
    for name in add:
        deck_id, version = _split_name(name)
        owner = spaces.space_of(deck_id)
        if (visible is not None and not visible(deck_id)) or \
                (owner != space and not (space == "home" and public is None) and not (public and public(owner))):
            notes.append("A simulation.json field addition isn't visible and was skipped.")
            continue
        summary = decks.find_summary(deck_id) if deck_id else None
        if summary is not None and visible is not None and not visible(summary["id"]):
            notes.append("A simulation.json field addition isn't visible and was skipped.")
            continue
        if not product_notes and deck_id.startswith(("product/", "pairing/")):
            add_note = lambda sentence: None
        else:
            add_note = notes.append
        if summary is None or summary.get("error"):
            if summary is not None:
                field_exclusions.notify(exclusions, "unavailable")
            add_note(f"simulation.json adds {name} to the {fmt} field, but there's no such deck that can be read.")
            continue
        if _fmt_of(summary) != fmt:
            add_note(f"simulation.json adds {name} to the {fmt} field, but it isn't a {fmt} deck.")
            continue
        version = version or _house_version(summary)
        if version not in summary["versions"]:
            add_note(f"simulation.json adds {name} to the {fmt} field, but that deck has no {version} list.")
            continue
        chosen = [(s, v) for s, v in chosen if not _same_id(s["id"], summary["id"])] + [(summary, version)]
        if trace is not None:
            trace.candidate(summary, version, "configured_add")
    for name in remove:
        deck_id, version = _split_name(name)
        if trace is not None:
            # Gate trace-only alias resolution/emission. The authoritative removal
            # below still runs unchanged, including legacy aliases hidden to this viewer.
            if visible is None or visible(deck_id):
                canonical = deck_identity.canonical(deck_id)
                if visible is None or visible(canonical):
                    for summary, selected in chosen:
                        if _same_id(summary["id"], deck_id) and version in (None, selected):
                            trace.removed(summary, selected)
        remaining = []
        for summary, selected in chosen:
            if _same_id(summary["id"], deck_id) and version in (None, selected):
                field_exclusions.notify(exclusions, "removed", summary, selected, deck_id, visible)
            else:
                remaining.append((summary, selected))
        chosen = remaining
    chosen = policy.apply(chosen, notes, trace=trace, exclusions=exclusions, visible=visible)
    entries = []
    for summary, version in chosen:
        try:
            entries.append(_entry(summary, version))
        except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError, ForgeError) as e:
            if trace is not None:
                trace.failed(summary, version)
            field_exclusions.notify(exclusions, "unavailable")
            if product_notes or not summary["id"].startswith(("product/", "pairing/")):
                notes.append(f"{summary['title']} isn't in the field: its {version} list can't be read ({e}).")
    entries.sort(key=lambda e: (e["title"].casefold(), e["id"], e["version"]))
    field_exclusions.notify(exclusions, "finish")
    return entries, notes


def field_lists(fmt, *, space="home", public=None, visible=None, product_notes=True):
    """The field of a format ("Constructed" or "Commander"): [entry] (section 10.1), sorted by
    title. Every deck file of the format with one list (its Built version when the deck is built
    and has that line, else its target list), and the product decks whose products/status.csv
    row is owned, preordered or ordered with intact "yes"; then simulation.json's field edits. A
    blank intact is "not decided yet", so such a product stays out until the owner sets it."""
    return _field(fmt, space=space, public=public, visible=visible, product_notes=product_notes)[0]


def field_notes(fmt, *, space="home", public=None, visible=None, product_notes=True):
    """Why lists that would be in fmt's field aren't (section 10.1), as sentences."""
    return _field(fmt, space=space, public=public, visible=visible, product_notes=product_notes)[1]


def _opponents(entry, names, field):
    """opponents() over a field already worked out."""
    out = [e for e in field if not _same_id(e["id"], entry["id"])]
    if names is None:
        return out
    wanted = [_split_name(name) for name in names if name and name.strip()]
    unknown = [name for name, (deck_id, version) in zip(names, wanted)
               if not any(_same_id(e["id"], deck_id) and version in (None, e["version"]) for e in out)]
    if unknown:
        raise ValueError(f"Not in the {lists.fmt_for(entry['kind'])} field as an opponent: {', '.join(unknown)}.")
    return [e for e in out if any(_same_id(e["id"], deck_id) and version in (None, e["version"])
                                  for deck_id, version in wanted)]


def opponents(entry, opponents=None, *, space="home", public=None, visible=None, product_notes=True):
    """entry's opponents in the field of its format (section 10.1): the field minus every list
    with entry's deck id, so entry can be any list (a field list, an owned-only list, a product
    deck). opponents, a list of "<deck id>[@version]" names, limits them to those (ValueError,
    with a sentence, for a name that isn't one of them)."""
    return _opponents(entry, opponents, field_lists(lists.fmt_for(entry["kind"]), space=space, public=public,
                                                   visible=visible, product_notes=product_notes))


# ============================================================ saved numbers

def _games(result):
    return views._games(result) if result is not None else []


def _run_counts(entry, result):
    """(games, entry's wins, games without a winner) that the run which saved result last added:
    the games of its run record, and the wins and others of the batches with that run's ordinal
    (a v2 result's batches carry it as "n"). Wins and others are None for a result whose batches
    don't say which run played them (one saved by the v1 runner). Never totals: the result may
    have games of another run (the page's, or ones saved under the key before this run)."""
    runs = result.get("runs") or []
    if not runs:
        return 0, None, None
    played = runs[-1].get("played") or 0
    if not isinstance(result.get("seeds"), dict):
        return played, None, None
    ordinal = len(runs) - 1
    games = [g for b in result.get("batches", []) if b.get("n") == ordinal for g in b.get("games", [])]
    p = views._perspective(result, entry["card_sha"])
    return played, sum(1 for g in games if g["w"] == p), sum(1 for g in games if g["w"] is None)


def _pair_state(entry, opponent, results_dir, *, keep=None):
    """What's saved of entry against opponent with today's engine: {"key", "n", "pi",
    "meaningful", "result"}."""
    key = lists.matchup_key(entry, opponent)
    result = saved.load(key, results_dir)
    if result is not None and keep is not None and not keep(result):
        result = None
    return _numbers({"key": key}, entry, result)


def _numbers(pair, entry, result):
    """pair with "n", "pi", "meaningful" and "result" from a saved result (None: nothing yet)."""
    games = _games(result)
    pi = None
    if games:
        p = views._perspective(result, entry["card_sha"])
        try:
            pi = seqstats.decided_share(games, p)["pi"]
        except NotImplementedError:
            pi = None
    pair.update(n=len(games), pi=pi, meaningful=result is None or not views._not_meaningful(result), result=result)
    return pair


# ============================================================ budgets and plans

def _budget(budget):
    """(floor, target, fixed) for a budget: floor the games every opponent is brought up to
    first, target APT's games per opponent (None: no APT), fixed True for "fixed:N" (every
    opponent topped up to N, no APT). ValueError for a budget that isn't one."""
    if isinstance(budget, str) and budget in BUDGETS:
        return seqstats.FIELD_FLOOR, BUDGET_GAMES[budget], False
    if isinstance(budget, str) and budget.startswith("fixed:") and budget[6:].isdigit() and int(budget[6:]) >= 1:
        return int(budget[6:]), None, True
    if isinstance(budget, str) and budget.isascii() and budget.isdigit():
        budget = int(budget)
    if isinstance(budget, int) and not isinstance(budget, bool) and budget >= 1:
        target = min(budget, seqstats.FIELD_CAP)
        return min(seqstats.FIELD_FLOOR, target), target, False
    raise ValueError(f"A field budget is one of {', '.join(BUDGETS)}, fixed:<games> or a number of games, "
                     f"not {budget!r}.")


def _per_opponent(budget):
    """The games per opponent a budget aims at (the page's "about 400 games a deck")."""
    floor, target, _ = _budget(budget)
    return target if target is not None else floor


def _alloc_left(pairs, floor, target):
    """APT games still to play: target per meaningful opponent less what they have (each counted
    up to FIELD_CAP, and at least the floor once it's played)."""
    if target is None:
        return 0
    counted = [p for p in pairs if p["meaningful"] and not p.get("dropped")]
    have = sum(min(max(p["n"], floor), seqstats.FIELD_CAP) for p in counted)
    return max(0, target * len(counted) - have)


def plan(entry, budget, results_dir=None, opponents=None, *, space="home", public=None, visible=None,
         keep=None, product_notes=True):
    """What a field run of entry with budget would play now (nothing plays): {"budget",
    "per_opponent", "floor", "allocate" (APT's games, not yet given to opponents), "new_games",
    "pairs": [{"opponent": entry, "key", "have", "floor", "games"}]}, each pair's "games" its
    floor games plus an even share of APT's (for time estimates)."""
    floor, target, fixed = _budget(budget)
    opps = _opponents(entry, opponents, field_lists(lists.fmt_for(entry["kind"]), space=space, public=public,
                                                   visible=visible, product_notes=product_notes))
    pairs = [dict(_pair_state(entry, o, results_dir, keep=keep), opponent=o) for o in opps]
    for p in pairs:
        p["floor_games"] = max(0, floor - p["n"])
    allocate = _alloc_left(pairs, floor, None if fixed else target)
    counted = [p for p in pairs if p["meaningful"]] or pairs
    share = allocate / len(counted) if counted else 0
    out = []
    for p in pairs:
        games = p["floor_games"] + (round(share) if p in counted and allocate else 0)
        out.append({"opponent": p["opponent"], "key": p["key"], "have": p["n"], "floor": p["floor_games"],
                    "games": games})
    return {"budget": budget, "per_opponent": _per_opponent(budget), "floor": sum(p["floor_games"] for p in pairs),
            "allocate": allocate, "new_games": sum(p["floor_games"] for p in pairs) + allocate, "pairs": out}


# ============================================================ the field run

def _who(e):
    return {"id": e["id"], "version": e["version"], "title": e["title"]}


def _inflight_setting():
    try:
        value = int(common._settings().get("forge_field_inflight") or 4)
    except (TypeError, ValueError, OSError):
        value = 4
    return max(1, value)


def _notes_path(entry, results_dir, *, space="home", legacy=False):
    from decklab.lib.inventory.paths import _space
    _space(space)
    suffix = "" if legacy else f"-{space}"
    return common._results_dir(results_dir) / NOTES_DIR / f"{entry['card_sha']}-{lists.fmt_for(entry['kind'])}{suffix}.json"


@lifecycle.writing("entry", "note")
def _append_note(entry, results_dir, note, *, space="home"):
    """Append a field run's note to <results_dir>/field/<card_sha>-<format>-<space>.json as
    runner.update_result writes a result: under the file's lock (runner._claim, waiting up to
    NOTE_WAIT seconds for another process), read, add, written whole. A note that can't be
    written is logged."""
    path = _notes_path(entry, results_dir, space=space)
    deadline = time.monotonic() + NOTE_WAIT
    with _notes_lock:
        while True:
            try:
                lock = runner._claim(path.parent, path.stem)
                break
            except ForgeError as e:
                if str(e) != runner.BUSY or time.monotonic() > deadline:
                    common._log(f"A field run's note couldn't be saved in {path.parent}: {e}")
                    return
                time.sleep(0.2)
        try:
            try:
                found = json.loads(path.read_text(encoding="utf-8"))
                runs = found.get("runs") if isinstance(found, dict) and isinstance(found.get("runs"), list) else []
            except (OSError, ValueError):
                runs = []
            runs.append(note)
            common._write_atomic(path, json.dumps({"runs": runs}, ensure_ascii=False, separators=(",", ":")))
        except OSError as e:
            common._log(f"A field run's note couldn't be saved as {path}: {e}")
        finally:
            runner._release(lock, path.parent / f"{path.stem}.lock")


def last_note(entry, results_dir=None, *, space="home", visible=None, keep=None):
    """The last field run's note of entry's list in its format (section 10.3), or None."""
    path = _notes_path(entry, results_dir, space=space)
    if not path.exists() and space == "home":
        path = _notes_path(entry, results_dir, legacy=True)
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    runs = found.get("runs") if isinstance(found, dict) else None
    note = runs[-1] if isinstance(runs, list) and runs and isinstance(runs[-1], dict) else None
    if note is None or (visible is not None and not visible((note.get("deck") or {}).get("id", ""))):
        return None
    if keep is not None:
        kept = {key for key in (note.get("per_opponent") or {}) if
                (result := saved.load(key, results_dir)) is not None and keep(result)}
        old_counts = note.get("per_opponent") or {}
        note["per_opponent"] = {key: value for key, value in old_counts.items() if key in kept}
        note["dropped"] = {key: value for key, value in (note.get("dropped") or {}).items() if key in kept}
        if len(kept) != len(old_counts):
            # Totals, errors and timing also describe the now-hidden opponents.
            for key in ("planned", "played", "wall_s", "error"):
                note.pop(key, None)
    return note


class _FieldRun:
    """One field run's coordinator (run_field): its pairs, what's playing, and the progress
    detail of section 10.3. Pair runs are threads that call runner.run; everything they change
    is under self.lock."""

    def __init__(self, entry, opps, budget, by, progress, results_dir, session, seed_base, log_dir, log_every,
                 inflight, keep=None):
        self.entry, self.budget, self.by, self.progress = entry, budget, by, progress
        self.results_dir, self.session, self.seed_base = results_dir, session, seed_base
        self.log_dir, self.log_every, self.inflight = log_dir, log_every, inflight
        self.floor, self.target, self.fixed = _budget(budget)
        self.lock = threading.Lock()
        self.finished = []              # (pair, outcome, value) handed back by pair threads
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.threads = []
        self.pairs = []
        for o in opps:
            pair = dict(_pair_state(entry, o, results_dir, keep=keep), opponent=o, fixed_key=None, dropped=None,
                        busy=0, waiting=False, playing=False, done=0, total=0, wins=0, other=0, run_games=0,
                        run_done=0, run_wins=0, run_other=0)
            self.pairs.append(pair)
        for p in self.pairs:
            p["floor_need"] = max(0, self.floor - p["n"])
            p["total"] = p["floor_need"]
        self.phase = "floor"
        self.planned = sum(p["floor_need"] for p in self.pairs) + _alloc_left(
            self.pairs, self.floor, None if self.fixed else self.target)
        self.played = 0
        self.error = None
        self.stopped_by = None

    # ------------------------------------------------------------ progress

    def detail(self):
        with self.lock:
            pairs = {}
            for p in self.pairs:
                pairs[p["key"]] = {"opponent": _who(p["opponent"]), "done": p["done"] + p["run_done"],
                                   "total": max(p["total"], p["done"] + p["run_done"]),
                                   "wins": p["wins"] + p["run_wins"], "other": p["other"] + p["run_other"],
                                   "playing": p["playing"]}
                if p["dropped"]:
                    pairs[p["key"]]["dropped"] = p["dropped"]
            done = sum(p["done"] + p["run_done"] for p in self.pairs)
            return done, {"budget": self.budget, "phase": self.phase, "deck": _who(self.entry), "pairs": pairs}

    def report(self):
        done, detail = self.detail()
        total = max(self.planned, done)
        if self.progress is not None:
            self.progress(done, total, detail)

    # ------------------------------------------------------------ pair runs

    def _pair_progress(self, pair):
        mine = 0 if self.entry["card_sha"] <= pair["opponent"]["card_sha"] else 1

        def progress(done, total, detail):
            if self.stopping.is_set():
                raise common.Stopped("Stopped")
            wins = (detail or {}).get("wins") or [0, 0]
            with self.lock:
                pair["run_done"], pair["run_wins"] = done, wins[mine]
                pair["run_other"] = (detail or {}).get("other", 0)
        return progress

    def _play(self, pair, games):
        """A pair run's thread: runner.run, its outcome handed back to the coordinator."""
        kwargs = {}
        if self.log_dir is not None:
            kwargs = {"log_dir": self.log_dir, "log_every": self.log_every}
        try:
            result = runner.run(self.entry, pair["opponent"], games, by=self.by, progress=self._pair_progress(pair),
                                results_dir=self.results_dir, pool=self.session, exact=True,
                                seed_base=self.seed_base, **kwargs)
            outcome = ("done", result)
        except ForgeError as e:
            outcome = ("busy", None) if str(e) == runner.BUSY else ("forge", str(e))
        except common.STOPS as e:
            outcome = ("stopped", e)
        except Exception as e:      # a bug: logged, and the other opponents go on
            common._log(f"A field run's games of {self.entry['title']} against {pair['opponent']['title']} "
                        f"failed:\n{traceback.format_exc()}")
            outcome = ("bug", FAILED.format(name=type(e).__name__))
        with self.lock:
            self.finished.append((pair, games, *outcome))
        self.wake.set()

    def start(self, pair, games):
        with self.lock:
            pair["playing"] = True
            pair["run_games"], pair["run_done"], pair["run_wins"], pair["run_other"] = games, 0, 0, 0
            pair["total"] = max(pair["total"], pair["done"]) + (games if self.phase == "allocate" else 0)
        thread = threading.Thread(target=self._play, args=(pair, games), daemon=True,
                                  name=f"field-{pair['opponent']['id']}")
        self.threads.append(thread)
        thread.start()

    def _settle(self, pair, games, outcome, value):
        """A pair run has ended: count its games, check its key, and drop it or mark it waiting
        for its one retry (a BUSY pair, tried again once nothing else plays)."""
        with self.lock:
            pair["playing"] = False
            if outcome == "done":
                result = value
                pair["busy"] = 0
                if pair["fixed_key"] is None:
                    pair["fixed_key"] = result.get("key")
                    if result.get("key") != pair["key"]:
                        # Saved under another key than today's engine gave before the run (an engine
                        # that was still being worked out): the pair's games are that result's.
                        pair["key"] = result.get("key")
                elif result.get("key") != pair["fixed_key"]:
                    self.error = ENGINE_CHANGED
                if result.get("key") == pair["fixed_key"]:
                    _numbers(pair, self.entry, result)
                # This run's own games, never the result's totals: the result can hold games the
                # page added between two pair runs, or ones saved under the key before this run.
                new, wins, other = _run_counts(self.entry, result)
                if wins is None:
                    wins, other = pair["run_wins"], pair["run_other"]
                pair["done"] += new
                pair["wins"] += wins
                pair["other"] += other
                self.played += new
            elif outcome == "stopped":
                saved_games = getattr(value, "saved_games", None) or 0
                pair["done"] += saved_games
                pair["wins"] += pair["run_wins"] if saved_games else 0
                pair["other"] += pair["run_other"] if saved_games else 0
                self.played += saved_games
                by = getattr(value, "by", None)
                if by and self.stopped_by is None:
                    self.stopped_by = by
                self.stopping.set()
            elif outcome == "busy":
                pair["busy"] += 1
                if pair["busy"] > 1:
                    pair["dropped"] = f"couldn't be played: {BUSY_TWICE}"
                else:
                    pair["waiting"] = True
            else:
                pair["dropped"] = f"couldn't be played: {value}"
            pair["run_games"] = pair["run_done"] = pair["run_wins"] = pair["run_other"] = 0
            if pair["dropped"]:
                self.planned = max(self.played, self.planned - max(0, pair["total"] - pair["done"]))
                pair["total"] = pair["done"]

    # ------------------------------------------------------------ the loop

    def _running(self):
        return sum(1 for p in self.pairs if p["playing"])

    def _alloc_rows(self):
        """apt_pick's rows: every pair still in the run, except those waiting for their retry."""
        return [{"id": p["key"], "n": p["n"], "pi": p["pi"], "inflight": p["playing"],
                 "meaningful": p["meaningful"] and not p["dropped"]}
                for p in self.pairs if not p["dropped"] and not p["waiting"]]

    @staticmethod
    def _alloc_retry_games(pair):
        """The games a waiting pair's retry plays in the APT phase: one pick's."""
        return max(0, min(seqstats.FIELD_STEP, seqstats.FIELD_CAP - pair["n"])) if pair["meaningful"] else 0

    def _alloc_starts(self, free):
        """The APT picks to start now: [(pair, games)]. The games a waiting pair's retry will
        play are kept out of what's left for the others."""
        with self.lock:
            left = _alloc_left(self.pairs, self.floor, self.target) - sum(
                p["run_games"] for p in self.pairs if p["playing"]) - sum(
                self._alloc_retry_games(p) for p in self.pairs if p["waiting"] and not p["dropped"])
            if left <= 0 or free <= 0:
                return []
            picks = seqstats.apt_pick(self._alloc_rows(), free)
            by_key = {p["key"]: p for p in self.pairs}
            out = []
            for key in picks:
                pair = by_key.get(key)
                if pair is None or left <= 0:
                    continue
                games = min(seqstats.FIELD_STEP, seqstats.FIELD_CAP - pair["n"], left)
                if games > 0:
                    out.append((pair, games))
                    left -= games
            return out

    def _retry_waiting(self, games_for):
        """Start the retries of the pairs waiting after a BUSY (each is tried once more), as
        many as inflight allows; called once nothing else plays or is left to start. True while
        a retry started or is still waiting."""
        free = self.inflight - self._running()
        busy = False
        for pair in self.pairs:
            if not pair["waiting"]:
                continue
            if pair["dropped"]:
                pair["waiting"] = False
                continue
            if free <= 0:
                busy = True
                continue
            with self.lock:
                pair["waiting"] = False
                games = games_for(pair)
                if self.phase == "allocate":
                    games = min(games, _alloc_left(self.pairs, self.floor, self.target))
            if games > 0:
                self.start(pair, games)
                free -= 1
                busy = True
        return busy

    def run(self):
        """Play the floor, then APT rounds; returns when nothing is left to play or the run
        stops. A BUSY pair waits, left out of the floor queue and APT's picks, until nothing
        else plays or is left to start; then it's tried once more. Raises common.Stopped,
        jobs.Stopped or KeyboardInterrupt (the run's own) after every pair run has saved."""
        floor = [(p, p["floor_need"]) for p in self.pairs if p["floor_need"] > 0]
        interrupt = None
        while True:
            try:
                self.wake.wait(LOOP_S)
                self.wake.clear()
                with self.lock:
                    finished, self.finished = self.finished, []
                for pair, games, outcome, value in finished:
                    self._settle(pair, games, outcome, value)
                    if outcome == "stopped" and interrupt is None and not self.error:
                        interrupt = value       # a pair run stopped on its own (DECKLAB_STOP_FILE, say)
                if self.error:
                    self.stopping.set()
                if not self.stopping.is_set():
                    free = self.inflight - self._running()
                    while free > 0 and self.phase == "floor" and floor:
                        pair, games = floor.pop(0)
                        if games > 0 and not pair["dropped"] and not pair["playing"]:
                            self.start(pair, games)
                            free -= 1
                    if (self.phase == "floor" and not floor and not self._running()
                            and not self._retry_waiting(lambda p: max(0, self.floor - p["n"]))):
                        if self.fixed or self.target is None:
                            break
                        self.phase = "allocate"
                        with self.lock:
                            self.planned = self.played + _alloc_left(self.pairs, self.floor, self.target)
                    if self.phase == "allocate":
                        for pair, games in self._alloc_starts(self.inflight - self._running()):
                            self.start(pair, games)
                        if (not self._running() and not self._alloc_starts(1)
                                and not self._retry_waiting(self._alloc_retry_games)):
                            break
                elif not self._running():
                    break
                self.report()
            except common.STOPS as e:
                # The page's Stop (the job's progress raised), the server stopping, or Ctrl+C:
                # every pair run stops at its next progress call and saves its finished games.
                if interrupt is None:
                    interrupt = e
                    if getattr(e, "by", None) and self.stopped_by is None:
                        self.stopped_by = e.by
                self.stopping.set()
                with common._interrupts_held():
                    for thread in self.threads:
                        while thread.is_alive():
                            thread.join(0.2)
                    with self.lock:
                        finished, self.finished = self.finished, []
                    for pair, games, outcome, value in finished:
                        self._settle(pair, games, outcome, value)
                break
            except BaseException:
                # A bug here: stop the pair runs (each saves its games) before it goes on up.
                self.stopping.set()
                for thread in self.threads:
                    thread.join()
                raise
        for thread in self.threads:
            thread.join()
        with self.lock:
            finished, self.finished = self.finished, []
        for pair, games, outcome, value in finished:
            self._settle(pair, games, outcome, value)
        return interrupt


@lifecycle.writing("entry", "opponents")
def run_field(entry, budget="standard", *, by, progress=None, results_dir=None, pool=None, local=False,
              seed_base=None, log_dir=None, log_every=1, inflight=None, opponents=None, space="home",
              public=None, visible=None, keep=None, product_notes=True):
    """Play entry against the field of its format (section 10.3): a floor of games against each
    opponent (FIELD_FLOOR, or fewer for a smaller budget), then APT rounds (seqstats.apt_pick, each
    pick FIELD_STEP games) until the budget's games are played. Each pair is an ordinary matchup
    run (runner.run, exact=True) under its own key, stream and base, so its games stay that
    matchup's results; at most inflight pair runs at once (config forge_field_inflight), each on
    its own thread, all in one pool session (the server's pool in the server; pool and local as
    runner.run's). progress(done, total, detail) gets the new games, the plan's new games and
    section 10.3's detail.

    A pair whose run is already being played (runner.BUSY) is tried again once, after the
    others; a ForgeError drops that opponent ("couldn't be played: <sentence>"); a run that comes
    back under another key than the pair's first stops the field run (ENGINE_CHANGED, raised as a
    ForgeError once every pair run has saved). Stop (progress raising), common.Stopped or
    Ctrl+C stops every pair run (each saves its finished games), writes the note and is raised
    again, with "saved_games".

    Returns the note appended to <results_dir>/field/<card_sha>-<format>-<space>.json: {"when", "by",
    "budget", "planned", "played", "wall_s", "stopped", "per_opponent": {key: games played},
    "deck": {"id", "version", "title"}, "dropped": {key: sentence}, "error": sentence or None}.
    ValueError for a budget or opponent names that don't suit, ForgeError when the field has no
    opponent for it."""
    from . import pool as pools         # pool.py comes after lists; field comes after both
    _budget(budget)
    fmt = lists.fmt_for(entry["kind"])
    opps = _opponents(entry, opponents, field_lists(fmt, space=space, public=public, visible=visible,
                                                   product_notes=product_notes))
    if not opps:
        raise ForgeError(NO_OPPONENTS.format(fmt=fmt))
    inflight = int(inflight) if inflight is not None else _inflight_setting()
    if inflight < 1:
        raise ValueError("inflight must be at least 1")
    when, began = common._now(), time.monotonic()
    with pools.session(local=local) if pool is None else _given(pool) as session:
        coordinator = _FieldRun(entry, opps, budget, by, progress, results_dir, session, seed_base, log_dir,
                                log_every, inflight, keep=keep)
        coordinator.report()
        interrupt = coordinator.run()
        if interrupt is None:
            try:
                coordinator.report()        # the finished pairs, none playing
            except common.STOPS:
                pass                        # Stop pressed as the last games ended: they're all saved
    note = {"when": when, "by": by, "budget": budget, "planned": coordinator.planned, "played": coordinator.played,
            "wall_s": round(time.monotonic() - began, 1), "stopped": interrupt is not None,
            "per_opponent": {p["key"]: p["done"] for p in coordinator.pairs}, "deck": _who(entry),
            "dropped": {p["key"]: p["dropped"] for p in coordinator.pairs if p["dropped"]},
            "error": coordinator.error}
    if interrupt is not None and coordinator.stopped_by:
        note["stopped_by"] = coordinator.stopped_by
    _append_note(entry, results_dir, note, space=space)
    if interrupt is not None:
        try:
            interrupt.saved_games = coordinator.played
        except (AttributeError, TypeError):
            pass
        raise interrupt
    if coordinator.error:
        raise ForgeError(coordinator.error)
    return note


class _given:
    """A pool the caller gave run_field, as a context manager that leaves it open."""

    def __init__(self, pool):
        self.pool = pool

    def __enter__(self):
        return self.pool

    def __exit__(self, *exc):
        return False


# ============================================================ the view

def _side_id(entry, eng):
    """entry's side id with eng (E3's engine.entry_side_id when built, else wave 2's
    engine.side_id of its triple)."""
    found = getattr(engine, "entry_side_id", None)
    if found is not None:
        try:
            return found(entry, lists.fmt_for(entry["kind"]), eng)
        except NotImplementedError:
            pass
    return engine.side_id(eng, lists.fmt_for(entry["kind"]), engine._triple(entry, eng))


def _bt_data(fmt, results_dir, *, current_engine=None, keep=None):
    """{(i, j, i_started): [i's wins, decided games]} over every saved result of fmt that today's
    engine would add to (engine.is_current True; None counts as not current), of the decklab kind,
    never a paired or experiment one, and not "not meaningful" (section 10.4). The players are
    the stored sides' side ids ("engine_id"); a mirror of one side id says nothing and is left out.
    current_engine supplies an already inspected identity for strictly read-only consumers,
    avoiding is_current()/today() and their setup/deployment/cache side effects. keep(result),
    when given, is False for a saved result to leave out (the rankings' viewer filter, E10-S30)."""
    if current_engine is not None and (not current_engine.get("complete") or
                                       current_engine.get("kind") != engine.KIND_DECKLAB):
        return {}
    data = {}
    with engine.held():
        for result in saved._stored(results_dir):
            if result.get("format") != fmt or result.get("kind") or engine.kind_of(result) != engine.KIND_DECKLAB:
                continue
            if keep is not None and not keep(result):
                continue
            ids = [side.get("engine_id") for side in result["sides"]]
            if not all(isinstance(i, str) for i in ids) or ids[0] == ids[1] or views._not_meaningful(result):
                continue
            try:
                current = (engine.is_current(result) if current_engine is None else
                           engine.stored_key(result, current_engine) == result["key"])
                if current is not True:
                    continue
            except Exception:
                continue
            for g in _games(result):
                if g.get("w") is None or g.get("first") not in (0, 1):
                    continue
                cell = data.setdefault((ids[0], ids[1], g["first"] == 0), [0, 0])
                cell[0] += g["w"] == 0
                cell[1] += 1
    return data


def _rating(entry, field, rows, results_dir, notes, *, keep=None):
    """(rating or None, {opponent key: (pred, residual)}) of section 10.4's Bradley-Terry fit."""
    fmt = lists.fmt_for(entry["kind"])
    try:
        eng = engine.today(engine.KIND_DECKLAB)
        player = _side_id(entry, eng)
        ids = {e["card_sha"] + "|" + e["id"] + "|" + e["version"]: _side_id(e, eng) for e in field}
        data = _bt_data(fmt, results_dir, **({"keep": keep} if keep is not None else {}))
        if keep is not None:
            allowed = {player, *ids.values()}
            data = {key: value for key, value in data.items() if key[0] in allowed and key[1] in allowed}
        component = seqstats.bt_component(data, player)
        if len(component) < 2:
            notes.append("Not rated: no games link this list to the field yet.")
            return None, {}
        fitted = {k: v for k, v in data.items() if k[0] in component and k[1] in component}
        fit = seqstats.bt_fit(fitted)
        field_ids = sorted({i for i in ids.values() if i in component})
        rating = seqstats.bt_rating(fit, player, field_ids) if field_ids else None
        per = {}
        observed = {}
        for row in rows:
            opp = ids.get(row["opponent"]["card_sha"] + "|" + row["opponent"]["id"] + "|" + row["opponent"]["version"])
            row["side_id"] = opp
            if opp in component and opp != player:
                per[row["key"]] = [seqstats.bt_predict(fit, player, opp), None]
                if row["numbers"] and row["numbers"].get("pi") is not None and row["numbers"].get("se") is not None:
                    observed[opp] = (row["numbers"]["pi"], row["numbers"]["se"])
        if observed:
            flags = {f["opponent"]: f for f in seqstats.residual_flags(fitted, fit, player, observed)}
            for row in rows:
                if row.get("side_id") in flags and row["key"] in per:
                    found = flags[row["side_id"]]
                    per[row["key"]][1] = {k: found.get(k) for k in ("r", "z", "p", "flag")}
        # A not-meaningful opponent is left out of the fit on purpose: its row says why.
        unlinked = [row["opponent"]["title"] for row in rows
                    if row.get("side_id") not in component and not row["not_meaningful"]]
        if unlinked:
            notes.append("Not rated against " + ", ".join(unlinked) + ": no games link them.")
        if rating is None:
            return None, per
        out = {k: rating.get(k) for k in ("value", "low", "high", "rank", "rank_low", "rank_high", "of", "h_points")}
        out.update(connected=len(component), dispersion=fit.get("phi"))
        return out, per
    except NotImplementedError:
        notes.append("The rating isn't worked out yet (the statistics part isn't built).")
        return None, {}
    except Exception as e:
        common._log(f"The field rating of {entry['title']} can't be worked out:\n{traceback.format_exc()}")
        notes.append(f"The rating can't be worked out ({type(e).__name__}).")
        return None, {}


def _r(x):
    return None if x is None else round(x, 4)


def _rows(entry, opps, results_dir, keep):
    """view()'s row of each opponent: {"opponent", "key", "n", "numbers" (seqstats.field_row's) or None, "lead",
    "not_meaningful", "problem", "updated" (when its saved games were last added to, or None)}."""
    rows = []
    for o in opps:
        problem = None
        try:
            pair = _pair_state(entry, o, results_dir, keep=keep)
        except ForgeError as e:
            pair, problem = {"key": None, "n": 0, "pi": None, "meaningful": True, "result": None}, str(e)
        result, games = pair["result"], _games(pair["result"])
        numbers = lead = None
        if games:
            p = views._perspective(result, entry["card_sha"])
            rates = views._winrate(games, p)
            lead = views._lead(games, p, rates["winrate"], views._comparison(games, p))
            try:
                numbers = seqstats.field_row(games, p)
            except NotImplementedError:
                w = rates["winrate"]
                numbers = {"n": len(games), "value": w["value"] if w.get("balanced") else None,
                           "low": w["low"] if w.get("balanced") else None,
                           "high": w["high"] if w.get("balanced") else None, "pi": None, "se": None, "d": None}
        rows.append({"opponent": o, "key": pair["key"], "n": pair["n"], "numbers": numbers, "lead": lead,
                     "not_meaningful": not pair["meaningful"], "problem": problem,
                     "updated": result.get("updated") if games else None})
    return rows


def _average(rows):
    """The equal-weight field average over rows (_rows) with games that mean something: {"value", "low", "high",
    "counted", "of", "partial"}, or None."""
    counted = [r["numbers"] for r in rows if r["numbers"] and not r["not_meaningful"]]
    try:
        average = seqstats.field_average(counted, of=sum(1 for r in rows if not r["not_meaningful"]))
    except NotImplementedError:
        average = None
    return None if average is None else {k: average.get(k) for k in ("value", "low", "high", "counted", "of", "partial")}


def view(entry, results_dir=None, *, space="home", public=None, visible=None, keep=None, product_notes=True):
    """entry against the field of its format (sections 10.4 and 15): {"deck": {"id", "version",
    "title", "card_sha"}, "format", "opponents": [{"id", "version", "title", "kind", "card_sha",
    "key", "games", "rate" {value, low, high} or None, "lead" (views._lead from entry's side) or
    None, "pred" (the rating's prediction) or None, "residual" {r, z, p, flag} or None,
    "not_meaningful", "problem"}] sorted by win rate (those without games last), "average"
    {value, low, high, counted, of, partial} or None (the equal-weight field average over the
    meaningful opponents with games on the play and on the draw), "rating" {value, low, high,
    rank, rank_low, rank_high, of, h_points, connected, dispersion, manual_excluded} or None, "coverage"
    {"with_floor", "of"}, "last_run" (last_note), "notes" (sentences: lists left out of the
    field, opponents the rating can't reach, ...)}. It never plays a game."""
    fmt = lists.fmt_for(entry["kind"])
    exclusions = field_exclusions.observation(visible)
    field, notes = _field(fmt, space=space, public=public, visible=visible,
                          product_notes=product_notes, exclusions=exclusions)
    rows = _rows(entry, _opponents(entry, None, field), results_dir, keep)
    average = _average(rows)
    rating, per = _rating(entry, field, rows, results_dir, notes, keep=keep) if rows else (None, {})
    if isinstance(rating, dict):
        rating = {**rating, "manual_excluded": field_exclusions.count(exclusions)}
    opponents_out = []
    for row in rows:
        o, numbers = row["opponent"], row["numbers"]
        pred, residual = per.get(row["key"], (None, None))
        rate = None
        if numbers and numbers.get("value") is not None:
            rate = {"value": _r(numbers["value"]), "low": _r(numbers.get("low")), "high": _r(numbers.get("high"))}
        opponents_out.append({"id": o["id"], "version": o["version"], "title": o["title"],
                              "kind": views.page_kind(o["id"]), "card_sha": o["card_sha"], "key": row["key"],
                              "games": row["n"], "rate": rate, "lead": row["lead"], "pred": _r(pred),
                              "residual": residual, "not_meaningful": row["not_meaningful"],
                              "problem": row["problem"]})
    opponents_out.sort(key=lambda o: (o["rate"] is None, -(o["rate"] or {}).get("value", 0) if o["rate"] else 0,
                                      o["title"].casefold()))
    return {"deck": {"id": entry["id"], "version": entry["version"], "title": entry["title"],
                     "card_sha": entry["card_sha"]},
            "format": fmt, "opponents": opponents_out, "average": average, "rating": rating,
            "coverage": {"with_floor": sum(1 for r in rows if r["n"] >= seqstats.FIELD_FLOOR), "of": len(rows)},
            "last_run": last_note(entry, results_dir, space=space, visible=visible, keep=keep), "notes": notes}


def pair_rates(fmt, results_dir=None, *, space="home", public=None, visible=None, keep=None, product_notes=True):
    """Each pair of fmt's field lists with saved games that mean something, for tonight's pairs (E1-S28):
    {(deck id, opponent's deck id): {"value" (the first's win rate, or None while it can't be told), "games",
    "versions" (the two lists' versions, in the key's order)}}, in both orders, worked out as view()'s rows are.
    A field addition may put a deck's other list in the field, so a caller checks "versions" against the lists
    it means. The options are view()'s. It never plays a game."""
    field, _notes = _field(fmt, space=space, public=public, visible=visible, product_notes=product_notes)
    out = {}
    for entry in field:
        for row in _rows(entry, _opponents(entry, None, field), results_dir, keep):
            if row["n"] and not row["not_meaningful"]:
                opponent = row["opponent"]
                out[(entry["id"], opponent["id"])] = {"value": _r((row["numbers"] or {}).get("value")),
                                                      "games": row["n"],
                                                      "versions": (entry["version"], opponent["version"])}
    return out


def averages(fmt, results_dir=None, *, space="home", public=None, visible=None, keep=None, product_notes=True):
    """Every list of fmt's field against the rest of it, for the library's Forge line (E11-S30 slice 8):
    {deck id: {"version", "card_sha", "average" (as view's) or None, "games", "tested" (the newest saved game's
    "updated", or None)}}, worked out from one field as view() works out each list's, without the rating, the
    opponents' rows or the notes. The options are view()'s. It never plays a game."""
    field, _notes = _field(fmt, space=space, public=public, visible=visible, product_notes=product_notes)
    out = {}
    for entry in field:
        rows = _rows(entry, _opponents(entry, None, field), results_dir, keep)
        dates = [r["updated"] for r in rows if r["updated"]]
        out[entry["id"]] = {"version": entry["version"], "card_sha": entry["card_sha"], "average": _average(rows),
                            "games": sum(r["n"] for r in rows), "tested": max(dates) if dates else None}
    return out
