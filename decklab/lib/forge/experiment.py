"""The experiment harness (simulation wave 3's R16, forge-trial/sim-wave3-contract.md section 12):
arms (override sets, pilots, seeds or config knobs) played on a control result's game numbers
and seeds, compared with the control per card and per pair, and a recommendation for each arm
(the owner adopts). Arm results have kind "experiment" and keys of their own, so they never mix
with matchups, and live only in experiment folders.

    load_spec(path)         an experiment spec (section 12.1), checked
    plan(spec, *, results_dir=None, control_dir=None, only=None, games=None)
                            per arm and pair, the games to play (the --dry-run)
    run(spec, *, by, progress=None, results_dir=None, logs_dir=None, control_dir=None,
        control_logs_dir=None, only=None, games=None, local=False, log_every=None)
                            play what's missing (section 12.2); returns the measures
    measures(spec, *, results_dir=None, logs_dir=None, control_dir=None, control_logs_dir=None)
                            the measures and recommendations (sections 12.3 and 12.4)
    report(found)           report.md's text

The spec (section 12.1). "pairs" are [deck a, deck b], each a deck id ("casual/gruul-ramp",
the target list) or "<deck id>@owned". "games" is each pair's games in every arm. An arm is any
of: "overrides" (set names, added to the adopted sets, or in their place with
"replace_adopted": true), "pilots" ({deck: {"profile", "switches"}}, with "sides": "a" or "b"
to change only that element of a pair: a mirror's side a), "seeds" ({"stream_from": [deck,
deck], "seat_of": deck}: the arm plays on another pair's stream, base and game numbers) and
"config" (knobs, {setting: value}: played in a child process, _play_knob_arm). An arm applies to the
pairs it changes: a pilot to the pairs holding its list, override sets to the pairs whose lists
hold a card the sets change, seeds to the pairs holding seat_of's list (not the stream_from pair
itself); the other pairs are listed as skipped.

The control of a pair is its matchup result with today's engine: the one in the control folder
(--control-dir, or the spec's control.results_dir) when it's current and holds the games, else
a result played into <results>/control/ (ordinary results, the log tee on every chunk). Its
first `games` game numbers, in order, are what every arm of the pair plays (runner.run's
numbers=), with the control's seeds: its base and stream, and a flip that keeps each list in
the seat it has in the control's game g (section 11.3's formula; _flip). An arm's result for a
pair is <results>/<arm>/<key>.json, key = sha256 of canonical({"experiment": name, "arm": arm,
"control_key": the control's key}), kind "experiment", with {"experiment": {"name", "arm",
"control_key"}} at its top level. Its logs are in <logs>/<arm>/<key>/ (the tee's layout), every
chunk for an experiment with named cards or the own_lost measure, else every 10th. The
control's logs are in the control logs folder (--control-logs-dir, the spec's
control.logs_dir) or <logs>/control/.

Order: one launch identity (user folder) at a time: first the controls with the arms that play
in the real user folder (pilots, seeds), then each override arm's folder; within one, at most
forge_field_inflight runs at once, in one pool.session. The key runner.run gives back for a pair
must be the one the experiment planned with (ENGINE_CHANGED otherwise). Run again, it plays
only what's missing; measures() reads what's saved, and run() writes experiment.json (the
measures) and report.md in the results folder.

Measures (section 12.3), per arm against the control, for each pair and pooled over the pairs:
- matchup: seqstats.paired_diff (the arm as the variant) from the point of view of the pair's
  changed list (its first element otherwise), pooled with seqstats.paired_field; a pair is
  "clearly negative" at z < -Phi^-1(1 - 0.025/k) (k pairs);
- per named card, from the logs of the games logged in both arms (LogReader's card log, a
  game at a time): the cast share of drawn copies (a ratio estimator with a cluster SE over
  games) and "cast at least once" when drawn in both arms (paired); the average turn of a
  copy's first cast; the win rate when in hand by turn 3 and when drawn (paired over the games
  where it holds in both arms, seqstats.paired_diff on those games); own permanents lost per
  cast (after each "Resolve Stack:" line naming the card, the caster's own permanents moving
  Battlefield -> Graveyard or Exile, up to the next "Resolve Stack:", "Turn:" or "Phase:" line);
- speed: the median Forge ms per game, and games a minute over the runs;
- AI timeouts and clock stops per 1,000 games, with COMBINED-RUN.md section 9.1 MG9's rate-ratio
  test (arm against control, per pair at 1 - 0.05/m and pooled at 0.95: flagged when the lower
  bound of the rate ratio is over 3, and per pair only with 3 or more arm games);
- errors: "unsupported card" lines and unexpected exceptions in the arm's logs that the
  control's don't have; only the unsupported cards and script errors (_blocking_error) count
  against an override set, the other exceptions are noted with their games.
Recommendations (section 12.4): an override arm and a pilot arm get "adopt", "don't adopt" or
"more games", with the reasons; other arms are evidence only.
"""
import json
import math
import re
import os
import subprocess
import sys
import threading
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import ExitStack
from pathlib import Path

from decklab.lib import decks

from . import common, engine, experiment_estimate, install, lifecycle, lists, overrides, pilots, pool, runner, saved, seeds, seqstats, simjar, views
from .common import ForgeError, forge_name, norm

# Keep the experiment entry points and helpers available at their original import path.
from .experiment_logs import (
    _Lost, _rows_copy, read_logs, _read_file, LOG_NAME,
)
from .experiment_analysis import (
    NONINFERIOR, CAST_RISE, OWN_LOST_RISE, PILOT_SLOWDOWN, HYBRID,
    HYBRID_SLOWDOWN, TIMEOUT_RATIO, TIMEOUT_MIN, SETTLE_CAP, _Z,
    _pair_words, _ratio, _difference, _bound, _binom_sf,
    _cp_lower, rate_ratio, _timeouts, _speed, _syn,
    _paired, _field, SCRIPT_ERROR, _blocking_error, _strata,
    DRAWN, COPIES, USED, ROUND_SUM, EARLY,
    _card_measures, _arm_measures, _timeout_test, _settle, recommend,
    _pairs_negative, _exception_notes, _common_checks, _recommend_override, _recommend_pilot,
    _verdict, WORDS, _pct, _pts, _range,
    report, _ms, _signed,
)

ENGINE_CHANGED = "The engine changed during this run: play it again."
PLAN_IDENTITY_UNKNOWN = ("The experiment's current engine identity could not be confirmed read-only, so its "
                         "remaining game count is unknown. No games were started.")
SEATS_CHANGED = ("The arm's result for {pair} doesn't put the lists in the seats of its control's games, so it "
                 "can't be compared: delete {path} and play it again.")
CONTROL_CHANGED = ("The control of {pair} isn't the one the arm's result {path} was played on (other seeds): delete "
                   "that file and play it again.")

MEASURES = ("cast", "turn", "win_early", "win_drawn", "own_lost", "matchup", "speed")
ARM_KEYS = ("overrides", "replace_adopted", "pilots", "sides", "seeds", "config")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
CONTROL = "control"                 # <results>/control/ and <logs>/control/: the controls the experiment played
EXPERIMENT_FILE = "experiment.json"
REPORT_FILE = "report.md"
SPEC_FILE = "spec.json"             # the spec as checked, kept with the results
LOGS = "logs"                       # <results>/logs/: the tee's default folder (_canonical_dirs)
RESERVED = (CONTROL, LOGS, SPEC_FILE, EXPERIMENT_FILE, REPORT_FILE)     # names an arm's folder can't take
LOG_EVERY_CARDS = 1                 # the log tee for an experiment with named cards or own_lost
LOG_EVERY_OTHER = 10


# ============================================================ the spec

def load_spec(path):
    """An experiment spec read from a JSON file and checked (section 12.1): the module
    docstring's shape, with every arm's keys filled in. ValueError with a sentence when it
    can't be read or doesn't fit."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"The experiment spec {path} can't be read ({common._os_reason(e)}).") from None
    except ValueError as e:
        raise ValueError(f"The experiment spec {path} isn't JSON ({e}).") from None
    return check_spec(data)


def check_spec(data):
    """A spec (a dict, as in the JSON file) checked and filled in: {"name", "games", "pairs",
    "control": {"results_dir", "logs_dir"}, "arms": {name: {"overrides": [sets] or None,
    "replace_adopted", "pilots": {deck: {"profile", "switches"}}, "sides": "a"/"b"/None,
    "seeds": {"stream_from", "seat_of"} or None, "config": {...} or None}}, "cards": {name:
    {"cast_target", "turn_target"}}, "measures": [...]}. ValueError with a sentence."""
    if not isinstance(data, dict):
        raise ValueError("An experiment spec is a JSON object.")
    unknown = sorted(set(data) - {"name", "games", "pairs", "control", "arms", "cards", "measures"})
    if unknown:
        raise ValueError(f"The experiment spec has keys it doesn't know: {', '.join(unknown)}.")
    name = data.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("The experiment's name must be letters, digits, '-', '_' or '.' (up to 64).")
    games = data.get("games")
    if type(games) is not int or games < 1:
        raise ValueError("The experiment's games must be a whole number of 1 or more.")
    pairs = data.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("The experiment needs pairs: a list of [deck, deck].")
    seen = set()
    for pair in pairs:
        if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(d, str) and d for d in pair)):
            raise ValueError(f"A pair is [deck, deck], not {pair!r}.")
        if tuple(sorted(pair)) in seen:         # either order is one control (_control_key) and one arm key
            raise ValueError(f"The pair {pair!r} is listed twice.")
        seen.add(tuple(sorted(pair)))
    control = data.get("control") or {}
    if not isinstance(control, dict) or set(control) - {"results_dir", "logs_dir"} \
            or not all(v is None or isinstance(v, str) for v in control.values()):
        raise ValueError("The control is {\"results_dir\": folder, \"logs_dir\": folder}.")
    arms = data.get("arms")
    if not isinstance(arms, dict) or not arms:
        raise ValueError("The experiment needs arms.")
    checked = {}
    for arm, how in arms.items():
        checked[arm] = _check_arm(arm, how)
    cards = data.get("cards") or {}
    if not isinstance(cards, dict):
        raise ValueError("The cards are {name: {\"cast_target\", \"turn_target\"}}.")
    named = {}
    for card, targets in cards.items():
        if not isinstance(card, str) or not card.strip() or not isinstance(targets, dict) \
                or set(targets) - {"cast_target", "turn_target"}:
            raise ValueError(f"The card {card!r} needs {{\"cast_target\", \"turn_target\"}}.")
        cast, turn = targets.get("cast_target"), targets.get("turn_target")
        if cast is not None and not (_number(cast) and 0 < cast <= 1):
            raise ValueError(f"{card}'s cast_target must be a share from 0 to 1.")
        if turn is not None and not (_number(turn) and turn > 0):
            raise ValueError(f"{card}'s turn_target must be a turn above 0.")
        named[card] = {"cast_target": cast, "turn_target": turn}
    measures = data.get("measures") or list(MEASURES)
    if not isinstance(measures, list) or set(measures) - set(MEASURES):
        raise ValueError(f"The measures are some of {', '.join(MEASURES)}.")
    return {"name": name, "games": games, "pairs": [list(p) for p in pairs],
            "control": {"results_dir": control.get("results_dir"), "logs_dir": control.get("logs_dir")},
            "arms": checked, "cards": named, "measures": [m for m in MEASURES if m in measures]}


def _number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _check_arm(arm, how):
    if not isinstance(arm, str) or not NAME_RE.fullmatch(arm) or arm in RESERVED:
        raise ValueError(f"An arm's name must be letters, digits, '-', '_' or '.', and not one of "
                         f"{', '.join(map(repr, RESERVED))} (the results folder's own): {arm!r}.")
    if not isinstance(how, dict):
        raise ValueError(f"The arm {arm!r} is a JSON object.")
    # A checked arm (check_spec's answer) reads as it was given: its empty keys left out.
    how = {k: v for k, v in how.items()
           if v is not None and not (k == "replace_adopted" and v is False) and not (k == "pilots" and v == {})}
    unknown = sorted(set(how) - set(ARM_KEYS))
    if unknown:
        raise ValueError(f"The arm {arm!r} has keys it doesn't know: {', '.join(unknown)}.")
    if not any(k in how for k in ("overrides", "pilots", "seeds", "config")):
        raise ValueError(f"The arm {arm!r} changes nothing: give it overrides, pilots, seeds or config.")
    out = {"overrides": None, "replace_adopted": bool(how.get("replace_adopted", False)), "pilots": {},
           "sides": how.get("sides"), "seeds": None, "config": None}
    if "overrides" in how:
        sets = how["overrides"]
        if not isinstance(sets, list) or not all(isinstance(s, str) for s in sets) or len(set(sets)) != len(sets):
            raise ValueError(f"In the arm {arm!r}, overrides are a list of set names.")
        known = _sets()
        missing = [s for s in sets if s not in known]
        if missing:
            raise ValueError(f"The arm {arm!r} names override sets sets.json doesn't have: {', '.join(missing)}.")
        out["overrides"] = list(sets)
    elif "replace_adopted" in how:
        raise ValueError(f"The arm {arm!r} has replace_adopted without overrides.")
    if "pilots" in how:
        given = how["pilots"]
        if not isinstance(given, dict) or not given:
            raise ValueError(f"In the arm {arm!r}, pilots are {{deck: {{\"profile\", \"switches\"}}}}.")
        for deck, pilot in given.items():
            out["pilots"][deck] = _check_pilot(arm, deck, pilot)
    if out["sides"] not in (None, "a", "b"):
        raise ValueError(f"In the arm {arm!r}, sides is \"a\" or \"b\".")
    if out["sides"] is not None and not out["pilots"]:
        raise ValueError(f"The arm {arm!r} has sides without pilots.")
    if "seeds" in how:
        given = how["seeds"]
        stream_from = given.get("stream_from") if isinstance(given, dict) else None
        seat_of = given.get("seat_of") if isinstance(given, dict) else None
        if not (isinstance(stream_from, list) and len(stream_from) == 2 and all(isinstance(d, str) for d in stream_from)
                and stream_from[0] != stream_from[1] and seat_of in stream_from) or set(given) - {"stream_from",
                                                                                                    "seat_of"}:
            raise ValueError(f"In the arm {arm!r}, seeds are {{\"stream_from\": [deck, deck], "
                             "\"seat_of\": one of them}.")
        out["seeds"] = {"stream_from": list(stream_from), "seat_of": seat_of}
    if "config" in how:
        if not isinstance(how["config"], dict) or not how["config"]:
            raise ValueError(f"In the arm {arm!r}, config is {{setting: value}}.")
        out["config"] = dict(how["config"])
    return out


def _check_pilot(arm, deck, pilot):
    if not isinstance(deck, str) or not deck or not isinstance(pilot, dict) or set(pilot) - {"profile", "switches"}:
        raise ValueError(f"In the arm {arm!r}, the pilot for {deck!r} is {{\"profile\", \"switches\"}}.")
    profile = pilot.get("profile", pilots.DEFAULT_PROFILE)
    switches = pilot.get("switches", [])
    if not isinstance(profile, str) or not profile or not isinstance(switches, list) \
            or not all(isinstance(s, str) and s for s in switches):
        raise ValueError(f"In the arm {arm!r}, the pilot for {deck!r} is {{\"profile\": a name, \"switches\": [ids]}}.")
    return {"profile": profile, "switches": sorted(set(switches))}


def _spec(spec):
    """A spec given as a path or a dict, checked."""
    return load_spec(spec) if isinstance(spec, (str, Path)) else check_spec(spec)


# ============================================================ override sets (sets.json)

def _sets():
    """sets.json's sets: {name: {"status", "files": {file: {"card", ...}}}}. overrides.load_sets
    (E3) when it's built, else the file as it is."""
    try:
        return overrides.load_sets()["sets"]
    except NotImplementedError:
        return json.loads(overrides.SETS_FILE.read_text(encoding="utf-8"))["sets"]


def _adopted():
    """The adopted sets, in sets.json's order."""
    try:
        return list(overrides.adopted())
    except NotImplementedError:
        return [name for name, s in _sets().items() if s.get("status") == "adopted"]


def _set_cards(names):
    """The cards (norm()'d Forge names) the sets' files are for."""
    found = _sets()
    return {norm(f["card"]) for name in names for f in (found.get(name) or {}).get("files", {}).values()
            if isinstance(f, dict) and f.get("card")}


def _arm_sets(how, adopted):
    """The sets an arm plays with (runner.run's override_sets), or None for the real folder's."""
    if how["overrides"] is None:
        return None
    if how["replace_adopted"]:
        return list(how["overrides"])
    return list(adopted) + [s for s in how["overrides"] if s not in adopted]


def _changed_cards(how, adopted):
    """The cards whose script the arm's sets change against the adopted ones."""
    sets = _arm_sets(how, adopted)
    if sets is None:
        return set()
    on, off = set(sets) - set(adopted), set(adopted) - set(sets)
    return _set_cards(on) | _set_cards(off)


def _set_targets(how, adopted):
    """{card: cast_target or None} of the files of the sets an arm changes against the adopted
    ones (sets.json's names and cast_target): the cards an override arm is judged on."""
    sets = _arm_sets(how, adopted)
    if sets is None:
        return {}
    changed = (set(sets) - set(adopted)) | (set(adopted) - set(sets))
    found = _sets()
    out = {}
    for name in [s for s in list(adopted) + list(sets) if s in changed]:
        for f in (found.get(name) or {}).get("files", {}).values():
            if isinstance(f, dict) and f.get("card"):
                target = f.get("cast_target")
                out[f["card"]] = target if _number(target) else out.get(f["card"])
    return out


def _arm_cards(spec, how, adopted):
    """(the cards an arm's numbers are given for, {card: {"cast_target", "turn_target"}}): an
    override arm's are its changed sets' cards (the spec's targets first, then sets.json's);
    any other arm's are the spec's cards."""
    if how["overrides"] is None:
        return sorted(spec["cards"]), {c: dict(t) for c, t in spec["cards"].items()}
    targets = {}
    for card, cast in _set_targets(how, adopted).items():
        given = spec["cards"].get(card) or {}
        targets[card] = {"cast_target": given.get("cast_target") if given.get("cast_target") is not None else cast,
                         "turn_target": given.get("turn_target")}
    return sorted(targets), targets


# ============================================================ lists, pilots and seats

def _entry(ref):
    """The entry (lists.entry, with its pilot) of a deck reference: "<deck id>" (its target
    list) or "<deck id>@owned" / "@target". ForgeError when there's no such list."""
    with lists.one_snapshot():
        return _entry_read(ref)


def _entry_read(ref):
    deck_id, _, version = ref.partition("@")
    version = version or "target"
    summary = decks.find_summary(deck_id)
    if summary is None or summary.get("error"):
        raise ForgeError(f"There's no deck {deck_id!r} (an experiment pair).")
    if version not in summary["versions"]:
        raise ForgeError(f"{deck_id} has no {version} list.")
    try:
        sections = decks.load_deck(summary["id"], version)
    except (decks.DeckNotFound, decks.DeckFileError) as e:
        raise ForgeError(f"{deck_id} can't be read: {e}") from None
    return lists.entry(summary["id"], version, summary["title"], decks.engine_kind(summary), sections)


def _list_cards(entry_):
    """The norm()'d Forge names of an entry's Main and Commander cards."""
    cards = entry_.get("cards") or {}
    return {norm(forge_name(name)) for section in ("Commander", "Main") for _, name in cards.get(section, [])}


def _pilot_of(entry_):
    found = entry_.get("pilot") or pilots.DEFAULT_PILOT
    return {"profile": found.get("profile") or pilots.DEFAULT_PROFILE, "switches": sorted(found.get("switches") or [])}


def _pilot_for(how, ref, index):
    """The arm's pilot for pair element index (ref), or None: a pilot named by the deck id, or
    by "<deck id>@<version>" (which wins); only element sides when the arm says so."""
    if not how["pilots"] or (how["sides"] is not None and "ab".index(how["sides"]) != index):
        return None
    deck_id = ref.partition("@")[0]
    version = ref.partition("@")[2] or "target"
    return how["pilots"].get(f"{deck_id}@{version}") or how["pilots"].get(ref) or how["pilots"].get(deck_id)


def _side_list(entry_, eng):
    """An entry's side list (section 4.1): engine.side_list when E3 has built it, else what R's
    runner._side_list stands in with: [card_sha, its pilot's profile, the profile's SHA-256], and
    the pilot's switches when it has any."""
    built = getattr(engine, "side_list", None)
    if built is not None:
        try:
            return built(entry_, eng)
        except NotImplementedError:
            pass
    pilot = _pilot_of(entry_)
    side = [entry_["card_sha"], pilot["profile"], ((eng or {}).get("ai_sha") or {}).get(pilot["profile"])]
    return side + [pilot["switches"]] if pilot["switches"] else side


def _arm_sides(entries, eng=None):
    """[side of entries[0], side of entries[1]] in the result runner.run saves for them: runner's
    own order (R's runner._ordered) when it has one, else Python's sort of the side lists with a
    None ai_sha as "" (R's sort key), so lists of two card_shas keep wave 2's card_sha order and a
    tie keeps the order given."""
    ordered = getattr(runner, "_ordered", None)
    if ordered is not None and eng is not None:
        first = ordered(entries[0], entries[1], eng)[0]
        return [0, 1] if first is entries[0] else [1, 0]
    keys = [["" if part is None else part for part in _side_list(e, eng)] for e in entries]
    return [0, 1] if keys[0] <= keys[1] else [1, 0]


def _control_side(result, entry_, index):
    """The side of a pair's element index (entry_) in a control result: the side with its
    card_sha; in a mirror, side index (section 11.3: a variant of a mirror pairs with side 0)."""
    shas = [s["card_sha"] for s in result["sides"]]
    if shas[0] != shas[1]:
        return shas.index(entry_["card_sha"])
    return index


def _stored_side(result, entry_, index, guess):
    """The side of a pair's element index (entry_) in an arm's saved result: by card_sha, or in a
    mirror by the stored sides' pilots (guess when they don't tell)."""
    sides = result["sides"]
    shas = [s["card_sha"] for s in sides]
    if shas[0] != shas[1]:
        return shas.index(entry_["card_sha"])
    stored = [s.get("pilot") for s in sides]
    if all(isinstance(p, dict) for p in stored):
        mine = _pilot_of(entry_)
        matches = [i for i, p in enumerate(stored)
                   if p.get("profile") == mine["profile"] and sorted(p.get("switches") or []) == mine["switches"]]
        if len(matches) == 1:
            return matches[0]
    return guess


def _flip(control_flip, control_side, arm_side):
    """The arm's flip that gives the list on the control's control_side, which is the arm's
    arm_side, the same seat in every game g (section 11.3: f = (f_C + beta + nu) mod 2)."""
    return (int(control_flip) + control_side + arm_side) % 2


def _seat_side(arm_side, arm_flip, control_flip):
    """The control's side that holds the arm's arm_side's seat in every game."""
    return arm_side ^ int(arm_flip) ^ int(control_flip)


# ============================================================ the layout: controls and items

def _canonical_dirs(spec, results_dir, logs_dir, control_dir, control_logs_dir):
    results = Path(results_dir) if results_dir else common.DATA_DIR / "experiments" / spec["name"]
    logs = Path(logs_dir) if logs_dir else results / LOGS
    control = control_dir or spec["control"]["results_dir"]
    control_logs = control_logs_dir or spec["control"]["logs_dir"]
    return results, logs, (Path(control) if control else None), (Path(control_logs) if control_logs else None)


def _games(result):
    return views._games(result) if result else []


def _layout(spec, *, results_dir=None, logs_dir=None, control_dir=None, control_logs_dir=None, only=None,
            games=None, entries=None, eng=None, read_only=False):
    """Everything plan(), run() and measures() share: the folders, each pair's control (its key,
    where it is, its game numbers) and each (arm, pair) item (its entries, key, override sets,
    seed pair, point of view, or why it's skipped). eng is the engine the controls' keys are
    worked out with: the runs' (_run_engine) or, without one, the card log's engine of today
    (engine.today(KIND_DECKLAB): no Java, as replay's dry run plans). The plan opts into
    read_only: no deployment or persistent identity writes, and an unconfirmed engine
    cannot make claims about cached controls or remaining games."""
    results, logs, control, control_logs = _canonical_dirs(spec, results_dir, logs_dir, control_dir,
                                                           control_logs_dir)
    target = games or spec["games"]
    arms = spec["arms"]
    if only:
        unknown = [a for a in only if a not in arms]
        if unknown:
            raise ValueError(f"The experiment has no arm called {', '.join(unknown)}.")
        arms = {a: arms[a] for a in arms if a in only}
    entries = {} if entries is None else entries

    def entry_of(ref):
        if ref not in entries:
            entries[ref] = _entry(ref)
        return entries[ref]

    if not read_only:
        try:
            overrides.ensure_deployed(common._user_dir())       # keys are worked out from what workers load
        except NotImplementedError:
            pass
    adopted = _adopted()
    eng = eng or (engine.today(engine.KIND_DECKLAB, read_only=True) if read_only
                  else engine.today(engine.KIND_DECKLAB))
    if read_only and not eng.get("complete"):
        raise ForgeError(PLAN_IDENTITY_UNKNOWN)
    controls = {}
    given = _given_controls()

    def control_of(pair):
        pair = _control_key(pair)
        if pair not in controls:
            a, b = entry_of(pair[0]), entry_of(pair[1])
            if a["kind"] != b["kind"]:
                raise ForgeError(f"{pair[0]} and {pair[1]} are of different formats, so they can't be a pair.")
            key = engine.key(a, b, eng)
            found, source, folder, log_folder = None, CONTROL, results / CONTROL, logs / CONTROL
            if given is not None:
                mine = given.get("|".join(pair))
                if mine is None:
                    raise ForgeError(f"The experiment's parent gave no control for {_pair_words(pair)}.")
                key, folder = mine["key"], Path(mine["dir"])
                log_folder, source = (Path(mine["logs"]) if mine.get("logs") else None), mine["source"]
                found = saved.load(key, folder)
            elif control is not None:
                stored = saved.load(key, control)
                # A result saved under today's key of these lists is current by its key.
                if stored is not None and len(_games(stored)) >= target:
                    found, source, folder = stored, "control_dir", control
                    log_folder = control_logs
            if found is None:
                found = saved.load(key, folder)
            numbers = sorted(g["g"] for g in _games(found))[:target]
            controls[pair] = {"pair": list(pair), "entries": [a, b], "key": key, "result": found, "source": source,
                              "dir": folder, "logs": log_folder, "numbers": numbers,
                              "missing": max(0, target - len(numbers))}
        return controls[pair]

    items = []
    for pair in spec["pairs"]:
        control_of(pair)
    for arm, how in arms.items():
        changed_cards = _changed_cards(how, adopted)
        for pair in spec["pairs"]:
            base = control_of(pair)
            item = {"arm": arm, "pair": list(pair), "control": _control_key(pair), "seed_control": _control_key(pair),
                    "sets": _arm_sets(how, adopted), "config": how["config"], "entries": [entry_of(r) for r in pair],
                    "perspective": 0, "skipped": None, "seat_of": None,
                    "key": engine._sha({"experiment": spec["name"], "arm": arm, "control_key": base["key"]})}
            why = []
            for i, ref in enumerate(pair):
                pilot = _pilot_for(how, ref, i)
                if pilot is not None and pilot != _pilot_of(item["entries"][i]):
                    item["entries"][i] = dict(item["entries"][i], pilot=dict(pilot))
                    why.append(("pilot", i))
            if changed_cards:
                for i in (0, 1):
                    if changed_cards & _list_cards(item["entries"][i]):
                        why.append(("overrides", i))
            if how["seeds"] is not None:
                stream_from = how["seeds"]["stream_from"]
                if how["seeds"]["seat_of"] in pair and set(pair) != set(stream_from):
                    item["seed_control"] = _control_key(stream_from)
                    item["seat_of"] = how["seeds"]["seat_of"]
                    why.append(("seeds", pair.index(item["seat_of"])))
            if how["config"] is not None:
                why.append(("config", 0))
            if not why:
                item["skipped"] = "the arm changes nothing in this pair"
            else:
                item["perspective"] = why[0][1]
                item["changes"] = sorted({w for w, _ in why})
            items.append(item)
    for item in items:
        if not item["skipped"]:
            control_of(item["seed_control"])
    return {"spec": spec, "games": target, "results": results, "logs": logs, "control_dir": control,
            "control_logs": control_logs, "controls": controls, "items": items, "adopted": adopted, "eng": eng}


def _control_key(pair):
    """A pair's control in _layout's controls: either order of the two lists is the same result."""
    return tuple(sorted(pair))


def _item_state(item, lay):
    """(saved result or None, the control's numbers it lacks, the games it still has to play):
    the last counts the games its control hasn't played yet too (the dry run's)."""
    seed = lay["controls"][item["seed_control"]]
    found = saved.load(item["key"], lay["results"] / item["arm"])
    have = {g["g"] for g in _games(found)}
    todo = [g for g in seed["numbers"] if g not in have]
    return found, todo, len(todo) + seed["missing"]


# ============================================================ plan (the dry run)

def _plan_timing_metadata():
    """Read optional timing metadata quietly; no pool, host or readiness inspection.

    Use the field estimator's class mapping and value rules. Unlike its page-facing
    rates() reader, a damaged optional file must not log paths or raw parse errors in
    this command. A missing file uses the same defaults; unknown workers stay unknown.
    """
    from . import estimate
    table = dict(estimate.DEFAULT_RATES)
    try:
        data = json.loads((common.DATA_DIR / estimate.RATES_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("Invalid optional timing metadata")
    table.update(estimate._workload_rates(data.get("warm_games_per_min")))
    named = data["rates"] if isinstance(data.get("rates"), dict) else data
    for name in table:
        value = experiment_estimate._positive(named.get(name))
        if value is not None:
            table[name] = value
    settings = common._settings()
    workers = settings.get("forge_workers") if isinstance(settings, dict) else None
    return table, experiment_estimate._worker_count(workers)


def _plan_estimate(found, sample_rows):
    """Best-effort timing from the very snapshots that supplied the game plan."""
    try:
        if found["totals"]["games"] == 0:
            return experiment_estimate.estimate_plan(found)
        rates, workers = _plan_timing_metadata()
        samples, ambiguous = {}, set()
        for key, result in sample_rows:
            if not isinstance(result, dict) or key in ambiguous:
                continue
            if key in samples and samples[key] is not result and samples[key] != result:
                # Two aliases may name one result key. Conflicting snapshots cannot
                # establish one observed rate, so leave that key to the fallback.
                samples.pop(key)
                ambiguous.add(key)
            else:
                samples[key] = result
        return experiment_estimate.estimate_plan(found, samples=samples, rates=rates, workers=workers)
    except Exception:
        return {"remaining_games": found["totals"]["games"], "minutes": None, "complete": False,
                "basis": "unavailable", "workers": None, "assumed_workers": None,
                "assumptions": [*experiment_estimate.BASE_ASSUMPTIONS, experiment_estimate.UNAVAILABLE],
                "controls": [], "arms": []}


def plan(spec, *, results_dir=None, control_dir=None, only=None, games=None, logs_dir=None, control_logs_dir=None):
    """Per arm and pair, the games to play, and the control games the control folder doesn't
    hold (section 12.5's --dry-run; the combined run's harness counts both):
    {"experiment", "results_dir", "games", "controls": [{"pair", "key", "source": "control_dir"
    or "control", "have", "missing", "card_shas"}], "arms": [{"arm", "pair", "key", "sets",
    "changes", "have", "missing", "skipped", "card_shas"}], "totals": {"control_games",
    "arm_games", "games"}, "estimate": experiment_estimate.estimate_plan's best-effort
    remaining-work estimate}. Nothing is played or written."""
    spec = _spec(spec)
    lay = _layout(spec, results_dir=results_dir, logs_dir=logs_dir, control_dir=control_dir,
                  control_logs_dir=control_logs_dir, only=only, games=games, read_only=True)
    controls = [{"pair": c["pair"], "key": c["key"], "source": c["source"], "have": len(c["numbers"]),
                 "missing": c["missing"], "card_shas": [e["card_sha"] for e in c["entries"]],
                 "kind": c["entries"][0]["kind"]}
                for c in lay["controls"].values()]
    arms = []
    sample_rows = [(control["key"], control["result"]) for control in lay["controls"].values()]
    for item in lay["items"]:
        row = {"arm": item["arm"], "pair": item["pair"], "key": item["key"], "sets": item["sets"],
               "changes": item.get("changes", []), "skipped": item["skipped"], "have": 0, "missing": 0,
               "card_shas": [e["card_sha"] for e in item["entries"]], "kind": item["entries"][0]["kind"],
               "config": item["config"]}
        if not item["skipped"]:
            found, _, missing = _item_state(item, lay)
            row["have"], row["missing"] = len(_games(found)), missing
            sample_rows.append((item["key"], found))
        arms.append(row)
    control_games = sum(c["missing"] for c in controls)
    arm_games = sum(a["missing"] for a in arms)
    found = {"experiment": spec["name"], "results_dir": str(lay["results"]), "logs_dir": str(lay["logs"]),
             "games": lay["games"], "controls": controls, "arms": arms,
             "totals": {"control_games": control_games, "arm_games": arm_games, "games": control_games + arm_games}}
    found["estimate"] = _plan_estimate(found, sample_rows)
    return found


# ============================================================ run

class _Tally:
    """The progress of a run's many runner.run calls as one (done, total, detail)."""

    def __init__(self, progress, total, stop):
        self.progress, self.total, self.stop = progress, total, stop
        self.done = {}
        self.lock = threading.Lock()

    def for_item(self, name):
        def report(done, total, detail):
            if self.stop.is_set():
                raise common.Stopped("Stopped: another run of this experiment stopped")
            with self.lock:
                self.done[name] = done
                count = sum(self.done.values())
            if self.progress is not None:
                self.progress(count, self.total, {"playing": name, "detail": detail})
        return report


def run(spec, *, by, progress=None, results_dir=None, logs_dir=None, control_dir=None, control_logs_dir=None,
        only=None, games=None, local=False, log_every=None):
    """Play the experiment's missing games (section 12.2): each pair's control when the control
    folder doesn't hold it, then every arm's games on its control's numbers and seeds; then
    work out the measures (measures()) and write experiment.json and report.md into the
    results folder. Returns the measures, with "played" (games played now) and "failed" ([{"arm",
    "pair", "error"}]: runs that couldn't play, the others went on). log_every: the tee's every
    k-th seat block for the arms (None: section 12.2's rule, _log_every); the controls the
    experiment plays tee every chunk. A stop (the page's, Ctrl+C, DECKLAB_STOP_FILE) stops every
    run at its next game boundary, keeps the games played and is raised again."""
    spec = _spec(spec)
    results, _, control, _ = _canonical_dirs(spec, results_dir, logs_dir, control_dir, control_logs_dir)
    roots = {results, results / CONTROL, *(results / arm for arm in spec["arms"])}
    if control is not None:
        roots.add(control)
    roots.update(Path(c["dir"]) for c in (_given_controls() or {}).values())
    with ExitStack() as claims:
        for root in sorted({lifecycle.root_path(root) for root in roots}, key=str):
            claims.enter_context(lifecycle.writer(root, deck_ids=lifecycle.references(spec["pairs"])))
        return _run_claimed(spec, by=by, progress=progress, results_dir=results_dir, logs_dir=logs_dir,
                            control_dir=control_dir, control_logs_dir=control_logs_dir, only=only,
                            games=games, local=local, log_every=log_every)


def _run_claimed(spec, *, by, progress, results_dir, logs_dir, control_dir, control_logs_dir,
                 only, games, local, log_every):
    entries = {}
    eng = _run_engine()
    lay = _layout(spec, results_dir=results_dir, logs_dir=logs_dir, control_dir=control_dir,
                  control_logs_dir=control_logs_dir, only=only, games=games, entries=entries, eng=eng)
    child = _given_controls() is not None
    for item in lay["items"]:
        if not item["skipped"]:
            for e in item["entries"]:
                try:
                    pilots.check_switches(eng, _pilot_of(e))
                except ValueError as err:
                    raise ForgeError(f"The arm {item['arm']!r} can't play: {err}") from None
    lay["results"].mkdir(parents=True, exist_ok=True)
    common._write_atomic(lay["results"] / SPEC_FILE, json.dumps(spec, indent=1, ensure_ascii=False))
    stop = threading.Event()
    failed, played = [], [0]
    inflight = _inflight()

    # 1. The controls the control folder doesn't hold, in the real user folder.
    total = sum(c["missing"] for c in lay["controls"].values())
    total += sum(_item_state(i, lay)[2] for i in lay["items"] if not i["skipped"])
    tally = _Tally(progress, total, stop)
    jobs_ = [("control", c) for c in lay["controls"].values() if c["missing"] and not child]
    _play_group(jobs_, lay, tally, stop, failed, played, by=by, local=local, inflight=inflight,
                log_every=log_every)
    # 2. The arms, one launch identity at a time: the real folder's first.
    lay = _layout(spec, results_dir=results_dir, logs_dir=logs_dir, control_dir=control_dir,
                  control_logs_dir=control_logs_dir, only=only, games=games, entries=entries, eng=eng)
    groups, knobs = {}, {}
    for item in lay["items"]:
        if item["skipped"] or (child and item["config"] is None):
            continue
        seed = lay["controls"][item["seed_control"]]
        if seed["result"] is None or seed["missing"]:
            failed.append({"arm": item["arm"], "pair": item["pair"],
                           "error": f"its control ({_pair_words(seed['pair'])}) wasn't played in full"})
            continue
        if item["config"] is not None and not child:
            knobs.setdefault(item["arm"], []).append(item)
            continue
        groups.setdefault(json.dumps(item["sets"]), []).append(("arm", item))
    for name in sorted(groups, key=lambda s: (s != "null", list(groups).index(s))):
        _play_group(groups[name], lay, tally, stop, failed, played, by=by, local=local, inflight=inflight,
                    log_every=log_every)
    for arm, items in knobs.items():
        _play_knob_arm(arm, items, lay, failed, by=by, local=local, log_every=log_every)
    if child:
        return {"experiment": spec["name"], "games": lay["games"], "results_dir": str(lay["results"]),
                "measures": spec["measures"], "arms": {}, "skipped": [], "played": played[0], "failed": failed}
    found = measures(spec, results_dir=lay["results"], logs_dir=lay["logs"], control_dir=lay["control_dir"],
                     control_logs_dir=lay["control_logs"], only=only, games=games, entries=entries, eng=eng)
    found["played"] = played[0]
    found["failed"] = failed
    common._write_atomic(lay["results"] / EXPERIMENT_FILE, json.dumps(found, indent=1, ensure_ascii=False))
    common._write_atomic(lay["results"] / REPORT_FILE, report(found))
    return found


# ============================================================ config knob arms (a child process)

CHILD_ENV = "DECKLAB_EXPERIMENT_CONTROLS"   # a child's controls.json: the parent's controls, by pair
CONFIG_ENV = "DECKLAB_CONFIG_EXTRA"         # config.load's extra file (R): the knob arm's settings
KNOB_FILE = "knobs.json"                    # in <results>/<arm>/: the arm's config, for CONFIG_ENV
CONTROLS_FILE = "controls.json"             # in <results>/<arm>/: the controls, for CHILD_ENV
_REPO = Path(__file__).resolve().parents[3]     # the repository: where "-m decklab.lib.forge" runs


def _given_controls():
    """In a knob arm's child process: {"<a>|<b>" (the pair sorted): {"key", "dir", "logs",
    "source"}}, the parent's controls (a knob can change the engine, so the child mustn't work
    out the controls' keys again); None in any other process."""
    path = os.environ.get(CHILD_ENV)
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))["controls"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ForgeError(f"The experiment's controls file {path} can't be read ({e}).") from None


def _play_knob_arm(arm, items, lay, failed, *, by, local, log_every):
    """A config arm (section 12.2): its runs play in a child process of this command with
    DECKLAB_CONFIG_EXTRA naming the arm's settings (config.load merges them; install._setup
    picks a knob user folder for PERFORMANCE_MODE), on this process's controls (CHILD_ENV). The
    child plays only that arm's missing games; this process measures them. A child that ends
    with an error fails the arm's runs (failed)."""
    folder = lay["results"] / arm
    folder.mkdir(parents=True, exist_ok=True)
    controls = {"|".join(pair): {"key": c["key"], "dir": str(c["dir"]), "logs": str(c["logs"]) if c["logs"] else None,
                                 "source": c["source"]}
                for pair, c in lay["controls"].items() if c["result"] is not None}
    common._write_atomic(folder / KNOB_FILE, json.dumps(lay["spec"]["arms"][arm]["config"], indent=1))
    common._write_atomic(folder / CONTROLS_FILE, json.dumps({"controls": controls}, indent=1))
    argv = [sys.executable, "-m", "decklab.lib.forge", "experiment", str(lay["results"] / SPEC_FILE), "--only", arm,
            "--results-dir", str(lay["results"]), "--logs-dir", str(lay["logs"]), "--games", str(lay["games"]),
            "--by", by] + (["--log-every", str(log_every)] if log_every else []) + (["--local"] if local else [])
    env = dict(os.environ, **{CONFIG_ENV: str(folder / KNOB_FILE), CHILD_ENV: str(folder / CONTROLS_FILE)})
    code = _child(argv, env)
    if code:
        for item in items:
            failed.append({"arm": arm, "pair": item["pair"],
                           "error": f"the config arm's process ended with exit code {code}"})


def _child(argv, env):
    """Run a knob arm's child process to its end (its output on this one's stderr) and give its
    exit code. Ctrl+C reaches it too: it stops as a run stops (its games saved), and this
    process waits for that before stopping."""
    proc = subprocess.Popen(argv, env=env, cwd=str(_REPO), stdout=subprocess.DEVNULL)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        with common._interrupts_held():
            proc.wait()
        raise


NEEDS_CARD_LOG = "Experiments need Deck Lab's card log (the v2 engine), and it can't be used on this PC now."


def _run_engine():
    """The engine the experiment's runs play (as runner.run works it out, after the real user
    folder's overrides are deployed): ForgeError when the card log can't be used, since arms play
    on their control's game numbers and seeds (the v2 engine's)."""
    try:
        overrides.ensure_deployed(common._user_dir())
    except NotImplementedError:
        pass
    setup = install._setup()
    log = simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], setup["version"])
    eng = engine.current(setup, log)
    if eng["kind"] != engine.KIND_DECKLAB:
        raise ForgeError(" ".join(filter(None, [NEEDS_CARD_LOG, (log or {}).get("problem")])))
    return eng


def _inflight():
    try:
        value = int(common._settings().get("forge_field_inflight", 4))
    except (TypeError, ValueError):
        value = 4
    return max(1, value)


def _play_group(jobs_, lay, tally, stop, failed, played, *, by, local, inflight, log_every):
    """Play one launch identity's runs, at most inflight at once in one pool.session. A
    ForgeError or ValueError (or a bug, logged) fails that run only (failed); a stop stops them
    all and is raised again once every run has saved its games."""
    if not jobs_ or stop.is_set():
        return
    stopped = []
    with pool.session(local=local) as session:
        with ThreadPoolExecutor(max_workers=min(inflight, len(jobs_)), thread_name_prefix="experiment") as ex:
            futures = {ex.submit(_play_job, kind, what, lay, tally, session, by, local, log_every): (kind, what)
                       for kind, what in jobs_}
            pending = set(futures)
            try:
                while pending:
                    done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                    for future in done:
                        kind, what = futures[future]
                        try:
                            played[0] += future.result()
                        except common.STOPS as e:
                            stop.set()
                            stopped.append(e)
                        except (ForgeError, ValueError) as e:
                            failed.append({"arm": what["arm"] if kind == "arm" else CONTROL, "pair": what["pair"],
                                           "error": str(e)})
                        except Exception as e:      # a bug: logged, and the other runs go on
                            common._log("An experiment run failed:\n" + traceback.format_exc())
                            failed.append({"arm": what["arm"] if kind == "arm" else CONTROL, "pair": what["pair"],
                                           "error": f"an error in Deck Lab ({type(e).__name__})"})
            except KeyboardInterrupt as e:
                stop.set()
                stopped.append(e)
                with common._interrupts_held():
                    wait(pending)
    if stopped:
        raise stopped[0]


def _play_job(kind, what, lay, tally, session, by, local, log_every):
    """One runner.run: a control's missing games, or an arm's on its control's numbers.
    Returns the games it played."""
    if kind == "control":
        a, b = what["entries"]
        name = f"control {_pair_words(what['pair'])}"
        result = runner.run(a, b, what["missing"], by=by, progress=tally.for_item(name), results_dir=what["dir"],
                            pool=session, local=local, exact=True, log_dir=str(lay["logs"] / CONTROL), log_every=1)
        if result["key"] != what["key"]:
            raise ForgeError(ENGINE_CHANGED)
        return result["runs"][-1]["played"]
    item = what
    found, todo, _ = _item_state(item, lay)
    if not todo:
        return 0
    seed = lay["controls"][item["seed_control"]]
    cseeds = seed["result"]["seeds"]
    guess = _arm_sides(item["entries"], lay["eng"])
    index = _seed_index(item)
    a, b = item["entries"]
    # The arm's key is the experiment's, so it doesn't follow the engine: the key engine.key gives
    # its own entries (their pilots too) with the run's engine is kept in the result, and checked
    # before games are added (section 1: one engine). An override arm's folder is checked too.
    engine_key = engine.key(a, b, lay["eng"])
    if found is not None:
        if (found["seeds"]["base"], found["seeds"]["stream"]) != (cseeds["base"], cseeds["stream"]):
            raise ForgeError(CONTROL_CHANGED.format(pair=_pair_words(item["pair"]),
                                                    path=lay["results"] / item["arm"] / f"{item['key']}.json"))
        stored = (found.get("experiment") or {}).get("engine_key")
        if stored is not None and stored != engine_key:
            raise ForgeError(ARM_ENGINE_CHANGED.format(arm=item["arm"], pair=_pair_words(item["pair"]),
                                                       path=lay["results"] / item["arm"] / f"{item['key']}.json"))
        _check_arm_folder(item, found, lay)
        flip = found["seeds"]["flip"]
    else:
        beta = _control_side(seed["result"], item["entries"][index], _seed_position(item, index))
        flip = _flip(cseeds["flip"], beta, guess[index])
    result = runner.run(a, b, len(todo), by=by, progress=tally.for_item(f"{item['arm']} {_pair_words(item['pair'])}"),
                        results_dir=lay["results"] / item["arm"], pool=session, local=local, exact=True,
                        numbers=todo, seeds={"base": cseeds["base"], "stream": cseeds["stream"], "flip": flip},
                        key=item["key"], kind="experiment",
                        extra={"experiment": {"name": lay["spec"]["name"], "arm": item["arm"],
                                              "control_key": lay["controls"][item["control"]]["key"],
                                              "engine_key": engine_key}},
                        override_sets=item["sets"], log_dir=str(lay["logs"] / item["arm"]),
                        log_every=log_every or _log_every(lay["spec"], item["arm"], lay["adopted"]))
    if result["key"] != item["key"]:
        raise ForgeError(ENGINE_CHANGED)
    arm_side = _stored_side(result, item["entries"][index], index, guess[index])
    beta = _control_side(seed["result"], item["entries"][index], _seed_position(item, index))
    if _seat_side(arm_side, result["seeds"]["flip"], cseeds["flip"]) != beta:
        raise ForgeError(SEATS_CHANGED.format(pair=_pair_words(item["pair"]),
                                              path=lay["results"] / item["arm"] / f"{item['key']}.json"))
    return result["runs"][-1]["played"]


ARM_ENGINE_CHANGED = ("The engine of the arm {arm!r} (Forge, its pilots' profiles, ...) changed since its games against "
                      "{pair} were played, so more games wouldn't be the same engine: delete {path} to play it again.")
ARM_FILES_CHANGED = ("The override files of the arm {arm!r} changed since its games against {pair} were played, so "
                     "more games wouldn't be the same engine: delete {path} to play it again.")


def _check_arm_folder(item, found, lay):
    """An override arm's saved result keeps its key when its sets' files change (the key is the
    experiment's, section 12.2), so before adding games check the arm's user folder holds what
    the result was played with: the overrides hash its engine recorded (section 1: one engine)."""
    if item["sets"] is None:
        return
    stored = (found.get("engine") or {}).get("overrides")
    try:
        mode = common._settings().get("forge_performance_mode", True) is not False
        now = overrides.ensure_deployed(overrides.user_dir_for(item["sets"], performance_mode=mode))["hash"]
    except NotImplementedError:
        return
    if stored and now and stored != now:
        raise ForgeError(ARM_FILES_CHANGED.format(arm=item["arm"], pair=_pair_words(item["pair"]),
                                                  path=lay["results"] / item["arm"] / f"{item['key']}.json"))


def _log_every(spec, arm, adopted):
    """Section 12.2's tee for an arm: every chunk (LOG_EVERY_CARDS) when it has named cards (an
    override arm's changed cards, or the spec's) or the experiment measures own_lost, else every
    LOG_EVERY_OTHER-th."""
    named = _arm_cards(spec, spec["arms"][arm], adopted)[0]
    return LOG_EVERY_CARDS if named or "own_lost" in spec["measures"] else LOG_EVERY_OTHER


def _seed_index(item):
    """The pair element whose seat the arm keeps: the seat_of list for a seeds arm, else the
    point of view (any element keeps its seat when one does)."""
    if item["seat_of"] is not None:
        return item["pair"].index(item["seat_of"])
    return item["perspective"]


def _seed_position(item, index):
    """That element's position in the seed control's pair (its side in a mirror)."""
    if item["seat_of"] is not None:
        return list(item["seed_control"]).index(item["seat_of"])
    return index


# ============================================================ measures

def measures(spec, *, results_dir=None, logs_dir=None, control_dir=None, control_logs_dir=None, only=None, games=None,
             entries=None, eng=None):
    """The measures per arm against the control, and the recommendations (sections 12.3-12.4),
    from what's saved: {"experiment", "games", "results_dir", "arms": {arm: {"kind": "override",
    "pilot" or "other", "pairs": [{"pair", "key", "control_key", "perspective", "games": {"arm",
    "control", "paired", "logged"}, "matchup": paired_diff's answer (+ "clearly_negative"),
    "mirror": {"value", "low", "high"} or None, "speed", "timeouts", "errors"}], "pooled":
    {"matchup", "speed", "timeouts", "errors"}, "cards": {card: {...}}, "recommendation":
    "adopt" / "dont_adopt" / "more_games" / None, "why": [sentences], "games_per_pair"}},
    "skipped": [{"arm", "pair", "why"}]}."""
    spec = _spec(spec)
    lay = _layout(spec, results_dir=results_dir, logs_dir=logs_dir, control_dir=control_dir,
                  control_logs_dir=control_logs_dir, only=only, games=games, entries=entries, eng=eng)
    arms = {arm: how for arm, how in spec["arms"].items() if not only or arm in only}
    cards_of = {arm: _arm_cards(spec, how, lay["adopted"]) for arm, how in arms.items()}
    every_card = sorted({c for cards, _ in cards_of.values() for c in cards})    # one reading of each log
    log_cache = {}
    out = {"experiment": spec["name"], "games": lay["games"], "results_dir": str(lay["results"]),
           "measures": spec["measures"], "arms": {}, "skipped": []}
    for arm, how in arms.items():
        items = [i for i in lay["items"] if i["arm"] == arm]
        out["skipped"] += [{"arm": arm, "pair": i["pair"], "why": i["skipped"]} for i in items if i["skipped"]]
        cards, targets = cards_of[arm]
        needs_logs = bool(cards) or how["overrides"] is not None
        pairs = [_pair_measures(item, lay, cards, every_card, log_cache, needs_logs)
                 for item in items if not item["skipped"]]
        out["arms"][arm] = _arm_measures(how, pairs, cards, targets)
    return out


def _logs_for(folder, key, flip, names, cache, games):
    """read_logs of a result's logs (<folder>/<key>/) for the games numbered games[0] to games[1],
    read once a measures() call."""
    if folder is None or games is None:
        return {}
    path = Path(folder) / key
    found = cache.get((str(path), flip, games))
    if found is None:
        found = read_logs(path, flip, names, games)
        cache[(str(path), flip, games)] = found
    return found


def _pair_measures(item, lay, cards, names, cache, needs_logs=True):
    control = lay["controls"][item["control"]]
    found = saved.load(item["key"], lay["results"] / item["arm"])
    row = {"pair": item["pair"], "key": item["key"], "control_key": control["key"], "perspective": item["pair"][
        item["perspective"]], "changes": item.get("changes", []), "games": {"arm": 0, "control": 0, "paired": 0,
                                                                            "logged": 0},
           "matchup": None, "mirror": None, "speed": None, "timeouts": None, "errors": None, "cards": {}}
    if found is None or control["result"] is None:
        return row
    numbers = set(control["numbers"])
    cgames = {g["g"]: g for g in _games(control["result"]) if g["g"] in numbers}
    seed = lay["controls"][item["seed_control"]]
    seed_numbers = set(seed["numbers"])
    agames = {g["g"]: g for g in _games(found) if g["g"] in seed_numbers}
    row["games"]["arm"], row["games"]["control"] = len(agames), len(cgames)
    guess = _arm_sides(item["entries"], lay["eng"])
    p = item["perspective"]
    a_sides = [_stored_side(found, item["entries"][i], i, guess[i]) for i in (0, 1)]
    if item["entries"][0]["card_sha"] == item["entries"][1]["card_sha"]:
        c_sides = [_seat_side(a_sides[i], found["seeds"]["flip"], control["result"]["seeds"]["flip"]) for i in (0, 1)]
    else:
        c_sides = [_control_side(control["result"], item["entries"][i], i) for i in (0, 1)]
    common_g = sorted(set(cgames) & set(agames))
    row["games"]["paired"] = len(common_g)
    cg, ag = [cgames[g] for g in common_g], [agames[g] for g in common_g]
    diff = _paired(cg, ag, c_sides[p], a_sides[p])
    row["matchup"] = diff
    if found["sides"][0]["card_sha"] == found["sides"][1]["card_sha"] and "pilot" in item.get("changes", []):
        rate = views.balanced(*_strata(list(agames.values()), a_sides[p]))
        row["mirror"] = {"value": rate[0], "low": rate[1], "high": rate[2]} if rate else None
    row["speed"] = {"arm": _speed(found, list(agames.values())), "control": _speed(control["result"], cg)}
    row["timeouts"] = {"arm": _timeouts(list(agames.values())), "control": _timeouts(list(cgames.values()))}
    # The logs only matter for named cards and for an override arm's new errors (section 12.4).
    span = (min(control["numbers"]), max(control["numbers"])) if control["numbers"] and needs_logs else None
    alogs = _logs_for(lay["logs"] / item["arm"], item["key"], found["seeds"]["flip"], names, cache, span)
    clogs = _logs_for(control["logs"], control["key"], control["result"]["seeds"]["flip"], names, cache, span)
    if control["source"] == "control_dir" and not clogs:
        clogs = _logs_for(lay["logs"] / CONTROL, control["key"], control["result"]["seeds"]["flip"], names, cache,
                          span)
    aerr = sorted({e for g in agames if g in alogs for e in alogs[g]["errors"]})
    cerr = sorted({e for g in cgames if g in clogs for e in clogs[g]["errors"]})
    new = [e for e in aerr if e not in cerr]
    row["errors"] = {"arm": aerr, "control": cerr, "new": new,
                     "new_blocking": [e for e in new if _blocking_error(e, cards)],
                     "new_games": {e: sum(1 for g in agames if g in alogs and e in alogs[g]["errors"]) for e in new},
                     "arm_error_games": sum(1 for g in agames.values() if g.get("r") == "error"),
                     "control_error_games": sum(1 for g in cgames.values() if g.get("r") == "error")}
    logged = [g for g in common_g if g in alogs and g in clogs]
    row["games"]["logged"] = len(logged)
    row["cards"] = _card_numbers(item, cards, logged, alogs, clogs, cgames, agames, a_sides, c_sides)
    return row


def _card_numbers(item, cards, logged, alogs, clogs, cgames, agames, a_sides, c_sides):
    """Per named card, per element of the pair whose list holds it: the per-game numbers both
    arms' logs give, for _card_measures to pool."""
    out = {}
    for card in cards:
        key = norm(card)
        units = []
        for i in (0, 1):
            if key not in _list_cards(item["entries"][i]):
                continue
            unit = {"element": i, "games": []}
            for g in logged:
                a, c = alogs[g], clogs[g]
                if a["cards"] is None or c["cards"] is None:
                    continue
                arow = a["cards"][a_sides[i]].get(key) or [0] * 10
                crow = c["cards"][c_sides[i]].get(key) or [0] * 10
                unit["games"].append({"g": g, "arm": arow, "control": crow,
                                      "arm_lost": a["lost"][a_sides[i]].get(key) or [0, 0],
                                      "control_lost": c["lost"][c_sides[i]].get(key) or [0, 0],
                                      "arm_game": agames[g], "control_game": cgames[g]})
            unit["arm_side"], unit["control_side"] = a_sides[i], c_sides[i]
            units.append(unit)
        if units:
            out[card] = units
    return out
