"""Adaptive matchup runs (simulation wave 3's R12, forge-trial/sim-wave3-contract.md section 9):
a run that plays in stages and looks at its games after each (seqstats.py), stopping when the
question is answered.

    "fixed"     a set number of games, as before (runner.run; not played here)
    "assess"    "How well does this deck do here?": a 400-game pilot (or what the result already
                has), then the planned rest in one stage, then at most one top-up, stopping at a
                half-width of ±3 points or at max_games (seqstats.assess_next, section 7.2)
    "ahead"     "Which deck wins?": looks at 400, 800, 1,600 and 3,200 games (up to max_games),
                stopping at a Haybittle-Peto boundary or when the decks are about even
                (seqstats.ahead_next and look, section 7.3)

A stage is one runner.run of the games up to the next look, so a look happens only once every
game of its stage has finished (a look never sees a subset biased toward short games). The
first stage's key is the run's key: a later stage that returns another key (a git pull, an
override or pilot change mid-run) stops the run with ENGINE_CHANGED, so a look never mixes
engines.

At the end the run appends a summary to its result's "adaptive" list (section 14.1, through
runner.update_result once wave 3's R has built it, else _update_result here, which takes the
matchup's lock the same way). A Stop (finished games are kept, as for any run) makes one more
look on the games played, judged as a look between planned checks (seqstats.look's
stopped=True: "ahead" only at |z| ≥ 3.0), recorded as the outcome "stopped" with the
anytime-valid range (seqstats.anytime_range); the Stop is then raised again. An error records
"error" and is raised again. A run that played no game records nothing, except an "ahead" run
whose result was already on a check and whose look there decided (a summary with no stages).

While the last summary applies (the result still has that run's games_after games:
last_summary), the page's lead word is the summary's decision (lead_from_summary, wired into
views.view by the base commit), so a stopped run never shows the plain 95 % verdict at a
stopping time chosen while watching the bar.

    MODES                   ("fixed", "assess", "ahead")
    ADAPTIVE                ("assess", "ahead"): the modes run_adaptive plays
    run_adaptive(entry_a, entry_b, mode, *, by, progress=None, results_dir=None, pool=None,
                 local=False, seed_base=None, max_games=3200, log_dir=None, log_every=1)
                            the run (section 9.2); returns the saved result. progress(done,
                            total, detail): done and total are this run's new games and its
                            current plan's (total grows at each stage); detail is runner.run's
                            plus "plan" {"mode", "stage", "next_look", "max", "planned",
                            "games_before"}, "range" (the anytime-valid range of the result's
                            games so far, [stored side 0's, side 1's], each {"value", "low",
                            "high"} or None) and "looks" (the looks made so far, as summaries
                            store them)
    last_summary(result)    the result's last adaptive summary while it applies, else None
    lead_from_summary(summary)
                            the summary's decision in views._lead's shape, {"verdict", "side",
                            "basis": "adaptive"} (side: the stored side ahead), or None (an
                            "assess" run's: the plain lead stands)
"""
import inspect
import json
import time

from . import common, lifecycle, runner, saved, seqstats, views
from .common import STOPS, ForgeError
from .lists import matchup_key

MODES = ("fixed", "assess", "ahead")
ADAPTIVE = ("assess", "ahead")
ENGINE_CHANGED = "The engine changed during this run: play it again."
TOO_MANY_STAGES = "The run couldn't reach its next check: too many of its games failed."
MAX_STAGES = 16             # an adaptive run plays at most 6 stages; more means games keep failing
TOPUP_SLACK = 0.002         # an "assess" top-up only when the half-width is over h + this (section 7.2)
UPDATE_WAIT = 30            # seconds _update_result waits for the matchup's lock (runner.update_result's)

# assess_next's reasons for stopping, as summaries store them (section 14.1).
ASSESS_OUTCOMES = {"precise": "precise", "capped": "capped", "capped at plan": "capped_at_plan"}
# The decisions a summary's lead can show (lead_from_summary), and the verdict each is.
LEAD_DECISIONS = {"ahead": "ahead", "slightly_ahead": "slightly_ahead", "about_even": "about_even",
                  "not_settled": "not_settled", "not_settled_stopped": "not_settled"}


# ============================================================ the summary the page reads

def _counted(result):
    return sum(len(b.get("games") or []) for b in result.get("batches") or [])


def last_summary(result):
    """The result's last adaptive summary (section 14.1) while its game count is still that
    run's games_after, else None (later games make the plain view the one that counts)."""
    items = (result or {}).get("adaptive")
    if not isinstance(items, list) or not items or not isinstance(items[-1], dict):
        return None
    last = items[-1]
    if type(last.get("games_after")) is not int or last["games_after"] != _counted(result):
        return None
    return last


def lead_from_summary(summary):
    """The lead word an adaptive summary shows, in views._lead's shape ({"verdict", "side",
    "basis": "adaptive"}), or None when the plain lead stands (an "assess" run's summary, or
    an error's). side is the result's stored side that is ahead (views._adaptive_view maps it
    to the page's point of view); a stopped run's "not settled: stopped between checks" is
    "not_settled"."""
    if not isinstance(summary, dict):
        return None
    verdict = LEAD_DECISIONS.get(summary.get("decision"))
    if verdict is None:
        return None
    side = summary.get("side")
    if verdict in ("ahead", "slightly_ahead"):
        if side not in (0, 1) or isinstance(side, bool):
            return None
    else:
        side = None
    return {"verdict": verdict, "side": side, "basis": "adaptive"}


def _games_words(n):
    return f"{n:,} game" + ("" if n == 1 else "s")


def words(summary, titles):
    """A summary's outcome in a sentence, as the page's "How these games were played" says it
    (matchups.js adaptiveWords): titles are the result's two sides' titles in stored order, so
    the side ahead (the summary's stored "side") is named. None for no summary."""
    if not isinstance(summary, dict):
        return None
    n = summary.get("games_after") or 0
    decision, outcome = summary.get("decision"), summary.get("outcome")
    lead = lead_from_summary(summary)
    leader = None
    if lead is not None and lead["side"] is not None:
        leader = titles[lead["side"]]
    if outcome == "stopped":
        found = summary.get("range") or {}
        span = ""
        if found.get("low") is not None:
            span = f" A range that allows for stopping at any time: {100 * found['low']:.0f}-{100 * found['high']:.0f} %."
        if decision in ("ahead", "slightly_ahead") and leader:
            verdict = f" {leader} is clearly ahead even so."
        elif decision == "about_even":
            verdict = " The decks are about even even so (within 5 points of win rate)."
        else:
            verdict = " Not settled."
        return f"Stopped early after {_games_words(n)}, between checks.{span}{verdict}"
    if outcome == "error":
        return f"This run stopped after {_games_words(n)} because of an error."
    head = f"This run stopped at a planned check after {_games_words(n)}"
    if outcome in ("ahead", "slightly_ahead") and leader:
        slightly = " slightly" if outcome == "slightly_ahead" else " clearly"
        return f"{head}: {leader} is{slightly} ahead."
    if outcome == "about_even":
        return f"{head}: the decks are about even (within 5 points of win rate)."
    if outcome == "not_settled":
        return f"{head}: it reached {_games_words(n)} without a clear leader."
    if outcome == "precise":
        width = summary.get("half_width")
        within = f"±{100 * width:.1f} points" if width is not None else "±3 points"
        return f"{head}: the win rate is known to within {within} of win rate."
    if outcome in ("capped", "capped_at_plan"):
        width = summary.get("half_width")
        within = f" (to within ±{100 * width:.1f} points of win rate)" if width is not None else ""
        return f"{head}: it played as many games as planned{within}."
    return None


# ============================================================ helpers

def _side_of(result, entry):
    """entry's stored side in result (0 or 1). A mirror (one list on both sides) is side 0,
    unless the sides' pilots tell them apart (wave 3's pilot mirror) and entry's is side 1's."""
    if result is None:
        return 0
    sides = result["sides"]
    mine = [i for i, side in enumerate(sides) if side.get("card_sha") == entry["card_sha"]]
    if len(mine) == 2 and entry.get("pilot") is not None:
        pilots = [side.get("pilot") for side in sides]
        if pilots[0] != pilots[1] and pilots[1] is not None and _same_pilot(pilots[1], entry["pilot"]):
            return 1
    return mine[0] if mine else 0


def _same_pilot(stored, pilot):
    """A stored side's pilot ({"profile", "switches", ...}) is entry's pilot."""
    if not isinstance(stored, dict) or not isinstance(pilot, dict):
        return False
    return (stored.get("profile") == pilot.get("profile")
            and sorted(stored.get("switches") or []) == sorted(pilot.get("switches") or []))


def _half_width(games, p):
    """The larger side of views.balanced's range of p's headline win rate (the half-width an
    "assess" run judges), or None without games in both strata."""
    play = [g for g in games if g.get("first") == p]
    draw = [g for g in games if g.get("first") == 1 - p]
    found = views.balanced(sum(g["w"] == p for g in play), len(play), sum(g["w"] == p for g in draw), len(draw))
    if found is None:
        return None
    value, low, high = found
    return max(value - low, high - value)


def _range(games, p):
    """seqstats.anytime_range of games for p as {"value", "low", "high"}, or None (no games, or
    it can't be worked out: a progress report never fails a run)."""
    try:
        found = seqstats.anytime_range(games, p) if games else None
    except Exception as e:
        said = f"{type(e).__name__}: {e}"
        if said not in _range_said:         # once per process: progress asks a few times a second
            _range_said.add(said)
            common._log(f"The live range of an adaptive run can't be worked out ({said}).")
        return None
    if found is None:
        return None
    value, low, high = found
    return {"value": round(value, 4), "low": round(low, 4), "high": round(high, 4)}


_range_said = set()         # _range's problems already logged


def _plan_done(planned):
    """assess_next's plan_done keyword (S's addition: whether the plan's stage has been played,
    which its other arguments can't tell for a result that started with more than the pilot's
    games), when its assess_next takes it."""
    try:
        takes = "plan_done" in inspect.signature(seqstats.assess_next).parameters
    except (TypeError, ValueError):
        takes = False
    return {"plan_done": planned} if takes else {}


def _look_record(found):
    """A seqstats.look() answer as summaries store it (section 14.1), with its "basis" (the range
    the decision was judged on: "decided", "comparison" or, for a stopped look, "decided_share")."""
    def num(x, places=4):
        return None if x is None else round(x, places)
    return {"games": found.get("look"), "z": num(found.get("z"), 3), "bound": found.get("bound"),
            "low": num(found.get("low")), "high": num(found.get("high")), "decision": found.get("decision"),
            "stopped": bool(found.get("stopped", False)), "basis": found.get("basis")}


def _stored_side(look_side, p):
    """look()'s side (0: p, 1: the other) as the result's stored side index, or None."""
    if look_side not in (0, 1):
        return None
    return p if look_side == 0 else 1 - p


@lifecycle.writing()
def _update_result(key, results_dir, fn):
    """runner.update_result's rule until wave 3's R builds it: claim the matchup's lock
    (waiting up to UPDATE_WAIT seconds while another run holds it), load the result, apply fn,
    write it atomically and release the lock."""
    folder = common._results_dir(results_dir)
    end = time.monotonic() + UPDATE_WAIT
    while True:
        try:
            fd = runner._claim(folder, key)
            break
        except ForgeError as e:
            if str(e) != runner.BUSY or time.monotonic() >= end:
                raise
            time.sleep(0.25)
    try:
        path = folder / f"{key}.json"
        result = saved._read_result(path)
        if result is None:
            raise ForgeError(runner.UNREADABLE)
        result = json.loads(json.dumps(result))         # the read cache's copy is shared
        before = lifecycle.references(result)
        changed = fn(result)
        result = changed if isinstance(changed, dict) else result
        with lifecycle.writer(results_dir, deck_ids=lifecycle.references(result) - before):
            common._write_atomic(path, json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return result
    finally:
        runner._release(fd, folder / f"{key}.lock")


def _append_summary(key, results_dir, summary):
    """Append summary to the result's "adaptive" list (runner.update_result when R has built
    it). A failure is logged: the run's games are saved either way."""
    def add(result):
        items = result.get("adaptive")
        result["adaptive"] = (items if isinstance(items, list) else []) + [summary]
        return result

    update = getattr(runner, "update_result", None) or _update_result
    try:
        update(key, results_dir, add)
    except Exception as e:
        common._log(f"The adaptive run's summary couldn't be saved with the matchup result {key[:12]} "
                    f"({type(e).__name__}: {e}).")


# ============================================================ the run

@lifecycle.writing("entry_a", "entry_b")
def run_adaptive(entry_a, entry_b, mode, *, by, progress=None, results_dir=None, pool=None, local=False,
                 seed_base=None, max_games=3200, log_dir=None, log_every=1):
    """Play entry_a against entry_b in stages until mode's question is answered (section 9.2),
    and return the saved result (with this run's summary in its "adaptive" list). mode is
    "assess" or "ahead" (ValueError otherwise, and for max_games outside 400 to 3,200); side p
    of the statistics is entry_a's. pool and local are runner.run's: without a pool the stages
    share one pool.session(), so a pool of the run's own stays warm between them. ForgeError
    as runner.run, and ENGINE_CHANGED when a stage plays under another key than the first.
    A result already past every look ("ahead" with more games than its last check) plays
    nothing and is returned as it is. An "ahead" run whose result sits exactly on one of its checks (400,
    800, 1,600 or 3,200 games, up to max_games) makes that look first; when it decides, the run
    plays nothing and records a summary with no stages (games_before = games_after)."""
    if mode not in ADAPTIVE:
        raise ValueError(f"an adaptive run's mode is one of: {', '.join(ADAPTIVE)}")
    if isinstance(max_games, bool) or not isinstance(max_games, int) \
            or not seqstats.ASSESS_PILOT <= max_games <= seqstats.CAP:
        raise ValueError(f"max_games must be a whole number from {seqstats.ASSESS_PILOT} to {seqstats.CAP}")
    run = _Adaptive(entry_a, entry_b, mode, by=by, progress=progress, results_dir=results_dir, local=local,
                    seed_base=seed_base, max_games=max_games, log_dir=log_dir, log_every=log_every)
    if pool is not None:
        run.pool = pool
        return run.play()
    from . import pool as pools          # pool.py comes before this part, but keep the import light
    with pools.session(local=local) as session:
        run.pool = session
        return run.play()


class _Adaptive:
    """One adaptive run's state: its stages, looks and key, and this run's games so far."""

    def __init__(self, entry_a, entry_b, mode, *, by, progress, results_dir, local, seed_base, max_games,
                 log_dir, log_every):
        self.a, self.b, self.mode, self.by = entry_a, entry_b, mode, by
        self.progress, self.results_dir, self.local = progress, results_dir, local
        self.seed_base, self.max_games = seed_base, max_games
        self.log = {"log_dir": log_dir, "log_every": log_every} if log_dir is not None else {}
        self.pool = None
        self.key = None             # the first stage's key: the run's
        self.first_key = None       # matchup_key's, before any stage (where a Stop's games went)
        self.when = common._now()
        self.stages, self.looks = [], []
        self.played = 0             # this run's games, over its finished stages
        self.wins = [0, 0]          # ... their wins in stored side order, and the games without a winner
        self.other = 0
        self.games_before = 0
        self.stage_plan = None      # the current stage's plan (progress detail)
        self.pending = None         # the stage playing: {"runs_before", "reason"} (a Stop's or error's record)
        self.runs = 0               # the result's run records before the next stage

    # ---------------------------------------------------------------- progress

    def _report(self, base_games, p, done, detail):
        """progress() for this run: done is this stage's games so far, base_games the
        result's games before the stage."""
        if self.progress is None:
            return
        detail = dict(detail or {})
        wins = list(detail.get("wins") or (0, 0))
        other = detail.get("other") or 0
        detail["wins"] = [self.wins[0] + wins[0], self.wins[1] + wins[1]]
        detail["other"] = self.other + other
        live = (base_games + [{"w": 0, "first": None}] * wins[0] + [{"w": 1, "first": None}] * wins[1]
                + [{"w": None, "first": None}] * other)
        detail["range"] = [_range(live, 0), _range(live, 1)]
        detail["plan"] = dict(self.stage_plan)
        detail["looks"] = [dict(look) for look in self.looks]
        for name, value in (("failed_batches", 0), ("games_per_min", None), ("eta_s", None), ("waiting", None),
                            ("fallback", None)):
            detail.setdefault(name, value)
        total = max(self.stage_plan["planned"] - self.games_before, self.played + done)
        self.progress(self.played + done, total, detail)

    # ---------------------------------------------------------------- stages

    def _stage(self, more, reason, next_look, games, p):
        """Play one stage of more games; returns the saved result."""
        n = len(games)
        self.stage_plan = {"mode": self.mode, "stage": len(self.stages) + 1, "next_look": next_look,
                           "max": self.max_games, "planned": n + more, "games_before": self.games_before}
        self.pending = {"runs_before": self.runs, "reason": reason}
        self._report(games, p, 0, None)          # the new plan; a Stop pressed between stages lands here

        def progress(done, total, detail):
            self._report(games, p, done, detail)

        result = runner.run(self.a, self.b, more, by=self.by, progress=progress, results_dir=self.results_dir,
                            seed_base=self.seed_base, local=self.local, pool=self.pool, exact=True, **self.log)
        if self.key is None:
            self.key = result["key"]
        elif result["key"] != self.key:
            raise _EngineChanged()
        played = result["runs"][-1].get("played") or 0
        self.played += played
        self.stages.append({"run": len(result["runs"]) - 1, "games": played, "reason": reason})
        self.pending, self.runs = None, len(result["runs"])
        self._count(result, played)
        return result

    def _interrupted(self, result):
        """Record the stage a Stop or an error cut short (its run record, when it saved one)."""
        if self.pending is None or result is None:
            return
        runs = result.get("runs") or []
        if len(runs) > self.pending["runs_before"]:
            played = runs[-1].get("played") or 0
            self.stages.append({"run": len(runs) - 1, "games": played, "reason": self.pending["reason"]})
            self.played += played
        self.pending = None

    def _count(self, result, played):
        """Add the last run's games (its batch) to this run's wins."""
        if not played:
            return
        ordinal = len(result["runs"]) - 1
        batches = [b for b in result.get("batches") or [] if b.get("n") == ordinal]
        games = [g for b in batches for g in b["games"]] if batches else views._games(result)[-played:]
        for g in games:
            if g["w"] is None:
                self.other += 1
            else:
                self.wins[g["w"]] += 1

    def _look(self, games, p, stopped=False):
        found = seqstats.look(games, p, len(games), max_games=self.max_games, stopped=stopped)
        record = _look_record(dict(found, stopped=stopped))
        self.looks.append(record)
        return found

    # ---------------------------------------------------------------- the loop

    def play(self):
        self.first_key = matchup_key(self.a, self.b)
        result = saved.load(self.first_key, self.results_dir)
        games = views._games(result) if result is not None else []
        p = _side_of(result, self.a)
        self.games_before = len(games)
        self.runs = len(result["runs"]) if result is not None else 0
        topups, planned = 0, False
        outcome = decision = side = None
        try:
            if self.mode == "ahead" and self._on_a_check(len(games)):
                # A result already on a check makes that look first (section 7.3): ahead_next is
                # strictly greater-than, so the loop below would skip it.
                found = self._look(games, p)
                if found["decision"] != "continue":
                    outcome = decision = found["decision"]
                    side = _stored_side(found.get("side"), p)
                    return self._finish(games, outcome, decision=decision, side=side, p=p) or result
            for _ in range(MAX_STAGES):
                if self.mode == "assess":
                    more, reason = seqstats.assess_next(games, p, h=seqstats.ASSESS_HALF_WIDTH, cap=self.max_games,
                                                        topups_done=topups, **_plan_done(planned))
                    if more <= 0:
                        outcome = ASSESS_OUTCOMES.get(reason, "capped_at_plan")
                        break
                    if len(games) >= seqstats.ASSESS_PILOT:
                        if not planned:
                            reason = "plan"
                        elif reason == "plan":
                            # assess_next can't tell the planned stage from the one after it: past
                            # the plan, only a top-up is left (section 7.2).
                            width = _half_width(games, p)
                            if topups >= seqstats.ASSESS_TOPUPS or width is None \
                                    or width <= seqstats.ASSESS_HALF_WIDTH + TOPUP_SLACK:
                                outcome = "capped_at_plan"
                                break
                            reason = "top-up"
                        elif reason == "top-up" and topups >= seqstats.ASSESS_TOPUPS:
                            outcome = "capped_at_plan"
                            break
                    more = min(more, self.max_games - len(games))
                    if more <= 0:
                        outcome = "capped"
                        break
                    result = self._stage(more, reason, None, games, p)
                    if reason == "plan":
                        planned = True
                    elif reason == "top-up":
                        topups += 1
                else:
                    more, next_look = seqstats.ahead_next(games, p, max_games=self.max_games)
                    if more <= 0 or next_look is None:
                        if not self.stages:
                            return result           # no look left: the plain verdict stands
                        outcome = decision = "not_settled"
                        break
                    result = self._stage(more, "look", next_look, games, p)
                games = views._games(result)
                p = _side_of(result, self.a)
                if self.mode == "ahead" and len(games) >= self.stage_plan["next_look"]:
                    found = self._look(games, p)
                    if found["decision"] != "continue":
                        outcome = decision = found["decision"]
                        side = _stored_side(found.get("side"), p)
                        break
            else:
                raise ForgeError(TOO_MANY_STAGES)
        except STOPS as stop:
            self._guarded(self._stopped, p)
            raise stop
        except _EngineChanged:
            self._guarded(self._finish, None, "error")
            raise ForgeError(ENGINE_CHANGED) from None
        except BaseException:
            self._guarded(self._finish, None, "error")
            raise
        if self.played or self.looks:
            result = self._finish(games, outcome, decision=decision, side=side, p=p) or result
        return result

    def _on_a_check(self, n):
        """Whether a result of n games sits exactly on one of the run's checks (an entry of
        seqstats.HP_LOOKS up to max_games)."""
        return 0 < n <= self.max_games and n in seqstats.HP_LOOKS

    @staticmethod
    def _guarded(fn, *args):
        """fn(*args) while a Stop or an error is on its way out: a failure here is logged, so
        the Stop or error that ended the run is the one raised."""
        try:
            fn(*args)
        except Exception as e:
            common._log(f"The adaptive run's summary couldn't be recorded after it ended early "
                        f"({type(e).__name__}: {e}).")

    def _stopped(self, p):
        """A Stop: one more look at the games played, judged as a look between planned checks."""
        key = self.key or self.first_key
        result = saved.load(key, self.results_dir)
        self._interrupted(result)
        if result is None or not self.played and self._ran_nothing(result):
            return
        games = views._games(result)
        p = _side_of(result, self.a)
        found = None
        try:
            found = self._look(games, p, stopped=True) if games else None
        except Exception as e:
            common._log(f"The stopped adaptive run's last look can't be worked out ({type(e).__name__}: {e}).")
        decision = found["decision"] if found else None
        self.key = key
        self._finish(games, "stopped", decision=decision, side=_stored_side((found or {}).get("side"), p), p=p,
                     result=result)

    def _ran_nothing(self, result):
        """True when the stage a Stop interrupted saved no game either."""
        return _counted(result) <= self.games_before

    def _finish(self, games, outcome, decision=None, side=None, p=0, result=None):
        """Append this run's summary (section 14.1) to its result; returns the result as saved
        (None when nothing was recorded)."""
        key = self.key or self.first_key
        if result is None:
            result = saved.load(key, self.results_dir)
        if result is None:
            return None
        self._interrupted(result)
        if games is None:
            games = views._games(result)
            p = _side_of(result, self.a)
        if (len(games) <= self.games_before and not self.played
                and (outcome in ("error", "stopped") or not self.looks)):
            return None                 # this run played nothing (and decided nothing): nothing to say
        width = _half_width(games, p)
        summary = {"mode": self.mode, "key": key, "when": self.when, "by": self.by,
                   "games_before": self.games_before, "games_after": len(games), "max_games": self.max_games,
                   "stages": self.stages, "looks": self.looks, "outcome": outcome,
                   "decision": decision if outcome != "error" else None,
                   "side": side if outcome != "error" else None,
                   "half_width": None if width is None else round(width, 4),
                   "range": None}
        if outcome == "stopped":
            # p's range (the side that asked: the command line's A), and each stored side's for
            # the page, which shows it from either side (api.forge_runs._matchup_json).
            summary["ranges"] = [_range(games, 0), _range(games, 1)]
            summary["range"] = summary["ranges"][p]
        if self.mode == "assess" and outcome != "stopped":
            summary["decision"] = summary["side"] = None        # the plain lead stands (section 7.2)
        _append_summary(key, self.results_dir, summary)
        return saved.load(key, self.results_dir)


class _EngineChanged(Exception):
    """A stage played under another key than the run's first (ENGINE_CHANGED)."""
