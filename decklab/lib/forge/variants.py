"""Paired variant tests (simulation wave 3's R15, forge-trial/sim-wave3-contract.md section 11):
a changed version of a list (same size) played on its base list's games. The variant's .dck is
written aligned to the base's (aligned_dck), and with Deck Lab's game patch deck-order-1 Forge
builds each library in .dck line order before the shuffle, so both versions see the same
shuffles and only games where the change mattered differ. The variant plays the base result's
game numbers with its seeds (runner.run's numbers=, seeds=, kind="paired"), and seqstats'
paired functions judge the difference.

    NO_DECK_ORDER           the refusal when the engine lacks deck-order-1
    aligned_dck(base_entry, variant_cards)
                            (the aligned .dck text, {"remove": [[qty, name]], "add": [[qty, name]]})
    variant_entry(base_entry, variant_cards)
                            the variant's entry (section 11.2)
    paired_flip(base_flip, base_side, variant_side)
                            f_P = (f_B + β + ν) mod 2 (section 11.3)
    paired_key(base_key, base_side, card_sha, dck_sha)
                            a paired result's key (section 14.2)
    test_id(base_entry, variant, against, mode, limited=None)
                            a test's id (section 14.3)
    run_test(base_entry, variant_cards, against, mode="ahead", *, by, progress=None,
             results_dir=None, pool=None, local=False, log_dir=None, log_every=1, opponents=None,
             extend=None)
                            the test (section 11.4); returns its summary (section 14.3)
    load_summary(test_id, results_dir=None)
                            a test's saved summary, or None
    view(test_id, results_dir=None)
                            a test's view (section 15), or None when there's no such test
    tests_for(deck_id, version, results_dir=None)
                            the tests of a deck's list, newest first
    verdict_words(summary, titles=None)
                            the verdict sentence the page and the command line show

How a test plays (section 11.4). Per opponent and per stage (a target of games a deck): the
base result (the current-engine matchup result of the base list and the opponent, an ordinary
result saved with the matchups) is topped up to the target when it holds fewer games, then the
variant plays the target's first game numbers of the base result that its paired result
(<results>/paired/<key>.json) doesn't hold yet, on the base result's seed base and stream, with
the flip that puts the variant in the base's seat in every game. Up to config
forge_field_inflight pair runs play at once, across opponents. The first run of a pair fixes its
base key; another key later stops the test (ENGINE_CHANGED). A look happens once every remaining
opponent has finished the stage: seqstats.paired_diff per opponent, seqstats.paired_field over
the field, judged by seqstats.paired_look with config forge_variant_margin (the field) or
forge_variant_margin_one (one opponent). An opponent whose run fails (a ForgeError) is dropped,
named in the summary, and left out of every look's recomputation.

Modes: "quick" (one look at 200 games a deck), an int N (one look at N), or "ahead" (looks at
seqstats.PAIRED_LOOKS against one opponent, FIELD_PAIRED_LOOKS against the field, until a
verdict or the last look). "Play more" (extend=<test id>) turns any test into "ahead": the looks
already made count as interim looks, and it plays to the next look, then goes on as "ahead".
The summary (section 14.3) is written to <results>/paired/tests/<test id>.json after each stage.
"""
import contextlib
import hashlib
import json
import re
import threading
import time

from decklab.lib import decks

from . import common, deck_identity, engine, field, lifecycle, lists, runner, saved, seqstats, views
from . import pool as pools
from .common import STOPS, ForgeError, forge_name

NO_DECK_ORDER = ("Tests of changes need Deck Lab's deck-order patch, which doesn't fit this Forge version yet.")
SIZE_CHANGED = "A tested change must keep the deck's size: {out} cards out, {into} in"
ENGINE_CHANGED = "The engine changed during this run: play it again."
ENGINE_CHANGED_MORE = ("The engine has changed since this test was played, so it can't play more: "
                       "start the test again.")
MODES = ("ahead", "quick")
DECK_ORDER = "deck-order-1"     # the game patch a test needs (simjar's id)

NO_CHANGE = "The changed list plays the same cards as the saved one, so there's no change to test."
SIDEBOARD_ONLY = "Sideboard changes aren't tested (games are best of one)"
FIELD_NOT_BUILT = "Tests against the field need the field view, which isn't built on this PC yet."
NO_OPPONENTS = "There's no deck in the field to test this change against."
BUSY = "This test is already being played."
NO_MORE = "This test has already played as many games as a test plays: it can't play more."
LIST_CHANGED = "The deck's list has changed since this test was played, so it can't play more: start a new test."
NOT_A_TEST = "There's no test of a change with that id."

QUICK_GAMES = 200               # a quick look's games a deck
PAIRED_VERSION = 1              # a paired result's "paired_version"
TEST_VERSION = 2                # space-scoped API field tests; paired keys are unchanged
SUMMARY_VERSION = 1             # a summary's "version"
TESTS_DIR = "tests"             # <results>/paired/tests/<test id>.json
TEST_ID_RE = re.compile(r"[0-9a-f]{64}")
INFLIGHT_DEFAULT = 4            # config forge_field_inflight's default
BUSY_WAITS_S = (5, 20, 60)      # a pair whose base matchup another job is playing: tried again after these
OUTCOMES = (*seqstats.PAIRED_VERDICTS, "stopped", "error")


# ============================================================ the aligned .dck (section 11.2)

def _canonical_sections(cards, kind):
    """{"Commander": [(qty, forge name)], "Main": [...]}, merged and sorted by name as lists._list_text
    writes them (a Constructed list plays its Commander section in Main)."""
    commander = [(int(q), forge_name(n)) for q, n in (cards or {}).get("Commander", [])]
    main = [(int(q), forge_name(n)) for q, n in (cards or {}).get("Main", [])]
    if kind != "commander":
        main, commander = commander + main, []
    return {"Commander": lists._merge_lines(commander, False), "Main": lists._merge_lines(main, False)}


def _counts(lines):
    out = {}
    for qty, name in lines:
        out[name] = out.get(name, 0) + qty
    return out


def aligned_dck(base_entry, variant_cards):
    """The variant's .dck aligned to the base's lines (section 11.2): (text, changes). The base's
    canonical lines (merged, sorted by name, the Commander section first for a Commander deck) are
    written in order, each with the copies the variant keeps, and right after a line the cards that
    take its removed copies' places (added copies sorted by name, removed copies taken from each
    line's last), so DeckOrder puts every unchanged card where it is in the base's library. Name=
    is the variant's canonical card_sha[:12]. changes is {"remove": [[qty, name]], "add": [[qty,
    name]]} in Forge's names. ValueError (a plain sentence) when the change doesn't keep the size
    of the deck or of its Commander section (SIZE_CHANGED), or changes nothing (NO_CHANGE)."""
    kind = base_entry["kind"]
    base = _canonical_sections(base_entry["cards"], kind)
    variant = _canonical_sections(variant_cards, kind)
    _, card_sha, _ = lists._list_text(variant_cards, kind)
    if card_sha == base_entry["card_sha"]:
        raise ValueError(NO_CHANGE)
    total_out = total_in = 0
    sections, removed, added = {}, {}, {}
    for section in ("Commander", "Main"):
        b, v = _counts(base[section]), _counts(variant[section])
        total_out += sum(max(0, q - v.get(n, 0)) for n, q in b.items())
        total_in += sum(max(0, q - b.get(n, 0)) for n, q in v.items())
    if total_out != total_in:
        raise ValueError(SIZE_CHANGED.format(out=total_out, into=total_in))
    for section in ("Commander", "Main"):
        lines, gone, new = _section_lines(base[section], variant[section])
        sections[section] = lines
        for n, q in gone.items():
            removed[n] = removed.get(n, 0) + q
        for n, q in new.items():
            added[n] = added.get(n, 0) + q
    text_lines = []
    if sections["Commander"]:
        text_lines += ["[Commander]"] + [f"{q} {n}" for q, n in sections["Commander"]]
    text_lines += ["[Main]"] + [f"{q} {n}" for q, n in sections["Main"]]
    text = f"[metadata]\nName={card_sha[:12]}\n" + "\n".join(text_lines) + "\n"
    order = lambda item: (item[1].casefold(), item[1])      # noqa: E731
    changes = {"remove": sorted(([q, n] for n, q in removed.items()), key=order),
               "add": sorted(([q, n] for n, q in added.items()), key=order)}
    return text, changes


def _section_lines(base_lines, variant_lines):
    """One section's aligned lines (section 11.2 steps 3-4), with what it removes and adds."""
    before, after = _counts(base_lines), _counts(variant_lines)
    removed = {n: q - after.get(n, 0) for n, q in before.items() if q > after.get(n, 0)}
    added = {n: q - before.get(n, 0) for n, q in after.items() if q > before.get(n, 0)}
    if sum(removed.values()) != sum(added.values()):
        raise ValueError(SIZE_CHANGED.format(out=sum(removed.values()), into=sum(added.values())))
    incoming = [n for n in sorted(added, key=lambda n: (n.casefold(), n)) for _ in range(added[n])]
    lines, at = [], 0
    for qty, name in base_lines:
        gone = removed.get(name, 0)
        if qty - gone > 0:
            lines.append([qty - gone, name])
        run = []                    # this line's added lines: [qty, name], one per name, in order
        for n in incoming[at:at + gone]:
            if run and run[-1][1] == n:
                run[-1][0] += 1
            else:
                run.append([1, n])
        at += gone
        lines.extend(run)
    return [(q, n) for q, n in lines], removed, added


def variant_entry(base_entry, variant_cards):
    """The variant's entry (section 11.2): the base's id with "variant:" before it, its version
    and kind, its title with " (your change)", the variant's canonical card_sha, card count and
    cards, the aligned .dck text ("dck") under its own file name ("dck_file", its SHA-256, so it
    never overwrites the list's sorted .dck), the base's pilot, and "aligned_to" (the base's
    card_sha). Also "changes" (aligned_dck's). ValueError as aligned_dck."""
    text, changes = aligned_dck(base_entry, variant_cards)
    cards = {"Commander": [[int(q), n] for q, n in (variant_cards or {}).get("Commander", [])],
             "Main": [[int(q), n] for q, n in (variant_cards or {}).get("Main", [])]}
    _, card_sha, count = lists._list_text(cards, base_entry["kind"])
    dck_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"id": "variant:" + str(base_entry["id"]), "version": base_entry["version"],
            "title": f"{base_entry['title']} (your change)", "kind": base_entry["kind"], "card_sha": card_sha,
            "card_count": count, "cards": cards, "dck": text, "dck_file": f"{dck_sha}.dck",
            "dck_sha": dck_sha, "pilot": base_entry.get("pilot"), "aligned_to": base_entry["card_sha"],
            "source": None, "changes": changes}


def paired_flip(base_flip, base_side, variant_side):
    """The paired result's flip, so the variant takes the base's seat in every game (section 11.3):
    f_P = (f_B + β + ν) mod 2, β the base's side index in the base result and ν the variant's in
    the paired result."""
    return (int(base_flip) + int(base_side) + int(variant_side)) % 2


def paired_key(base_key, base_side, card_sha, dck_sha):
    """A paired result's key (section 14.2): sha256 of the canonical {"paired_version": 1,
    "base_key", "base_side", "variant": [card_sha, dck_sha]}."""
    return engine._sha({"paired_version": PAIRED_VERSION, "base_key": base_key, "base_side": int(base_side),
                        "variant": [card_sha, dck_sha]})


def _against_value(against, fmt, space=None):
    """A summary's "against": "field:<format>", or {"id", "version", "card_sha"} of one list."""
    if against == "field":
        return f"field:{space}:{fmt}" if space is not None else f"field:{fmt}"
    return {"id": against["id"], "version": against["version"], "card_sha": against["card_sha"]}


def _mode_value(mode):
    if mode in MODES:
        return mode
    if isinstance(mode, bool) or not isinstance(mode, int) or mode < 1:
        raise ValueError("A test's mode is \"ahead\", \"quick\" or a whole number of games a deck (1 or more)")
    return mode


def test_id(base_entry, variant, against, mode, limited=None, *, field_space=None):
    """A test's id (section 14.3): sha256 of the canonical {"test_version": 2, "base": [id, version,
    card_sha], "variant": [card_sha, dck_sha], "against", "mode"}, with "limited" (the field's
    opponents a test was limited to, sorted) only when it was. variant is variant_entry()'s;
    against is "field" or an entry. API field_space scopes the field identity; the command
    line keeps its existing field selection when this argument is omitted."""
    fmt = lists.fmt_for(base_entry["kind"])
    payload = {"test_version": TEST_VERSION, "base": [base_entry["id"], base_entry["version"], base_entry["card_sha"]],
               "variant": [variant["card_sha"], variant["dck_sha"]],
               "against": _against_value(against, fmt, field_space),
               "mode": _mode_value(mode)}
    if limited:
        payload["limited"] = sorted(limited)
    return engine._sha(payload)


test_id.__test__ = False        # not a unittest name


# ============================================================ saved files

def _paired_dir(results_dir=None):
    return common._results_dir(results_dir) / "paired"


def _tests_dir(results_dir=None):
    return _paired_dir(results_dir) / TESTS_DIR


def load_paired(key, results_dir=None):
    """The paired result saved under key (<results>/paired/<key>.json), or None."""
    if not TEST_ID_RE.fullmatch(key or ""):
        return None
    found = saved._read_result(_paired_dir(results_dir) / f"{key}.json")
    return json.loads(json.dumps(found)) if found is not None else None


def load_summary(test, results_dir=None):
    """A test's summary (section 14.3), or None when there's none (or it can't be read)."""
    if not isinstance(test, str) or not TEST_ID_RE.fullmatch(test):
        return None
    try:
        data = json.loads((_tests_dir(results_dir) / f"{test}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("test") != test or not isinstance(data.get("opponents"), list):
        return None
    return data


@lifecycle.writing("summary")
def _write_summary(summary, results_dir):
    summary["updated"] = common._now()
    path = _tests_dir(results_dir) / f"{summary['test']}.json"
    try:
        common._write_atomic(path, json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    except OSError as e:
        common._log(f"A test's summary couldn't be saved as {path}: {e}")


def _games(result):
    return views._games(result) if result else []


def _first_numbers(result, target):
    """The first target game numbers a base result holds, sorted."""
    return sorted(g["g"] for g in _games(result))[:target]


# ============================================================ the test

def _margin(field_test):
    """The "makes little difference" margin: config forge_variant_margin against the field,
    forge_variant_margin_one against one deck (a bad value: the default)."""
    name, default = (("forge_variant_margin", seqstats.VARIANT_EQUIV_FIELD) if field_test
                     else ("forge_variant_margin_one", seqstats.VARIANT_EQUIV_ONE))
    try:
        value = common._settings().get(name, default)
    except Exception:
        value = default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 0.5:
        return default
    return float(value)


def _inflight():
    try:
        value = common._settings().get("forge_field_inflight", INFLIGHT_DEFAULT)
    except Exception:
        value = INFLIGHT_DEFAULT
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 16 else INFLIGHT_DEFAULT


def _looks(mode, field_test):
    """The looks of a mode (games a deck): quick (200,), an int (N,), ahead the paired looks."""
    if mode == "quick":
        return (QUICK_GAMES,)
    if mode == "ahead":
        return tuple(seqstats.FIELD_PAIRED_LOOKS if field_test else seqstats.PAIRED_LOOKS)
    return (int(mode),)


def _ahead_looks(field_test):
    return tuple(seqstats.FIELD_PAIRED_LOOKS if field_test else seqstats.PAIRED_LOOKS)


def _opponent_entries(base_entry, against, opponents, field_options=None):
    """The opponents' entries: [against], or the field minus the base's deck id (field.opponents),
    limited to opponents' names when given."""
    if against != "field":
        return [against]
    try:
        options = {k: v for k, v in (field_options or {}).items() if k in ("space", "public", "visible")}
        found = field.opponents(base_entry, opponents, **options)
    except NotImplementedError:
        raise ForgeError(FIELD_NOT_BUILT) from None
    found = [e for e in found if not deck_identity.same(e.get("id"), base_entry.get("id"))]
    if not found:
        raise ForgeError(NO_OPPONENTS)
    return found


def _index_of(result, card_sha):
    """The side index of card_sha in a result (0 for a mirror: one list on both sides)."""
    shas = [s["card_sha"] for s in result["sides"]]
    if card_sha not in shas:
        raise ForgeError("The base matchup's saved games aren't this list's, so the test can't be played.")
    return shas.index(card_sha)


def _variant_index(variant, opponent):
    """ν: the variant's side index in its paired result, as runner.run orders the sides (by card_sha
    for two different lists; runner._ordered's side-list sort, wave 3's R, when they're the same
    list, so a mirror differing only in its pilot gets the run's own order)."""
    if variant["card_sha"] != opponent["card_sha"]:
        return 0 if variant["card_sha"] < opponent["card_sha"] else 1
    ordered = getattr(runner, "_ordered", None)
    if ordered is None:
        return 0
    try:
        return 0 if ordered(variant, opponent, engine.today())[0] is variant else 1
    except Exception:
        return 0


def _base_key(base_entry, opponent):
    return engine.matchup_key(base_entry, opponent)


def _deck_order(eng):
    return DECK_ORDER in (eng or {}).get("game_patches", [])


class _Stop(Exception):
    """Inside a test: another pair's run stopped the test."""


class _Progress:
    """The test's progress for its job: games played across every pair run, against the plan's
    total (the worst case to the last look), with each pair's record (section 10.3's "pairs")."""

    def __init__(self, outer, total, mode, stopping):
        self.outer, self.total, self.mode = outer, total, mode
        self.done = 0
        self.pairs = {}
        self.extra = {"stage": 0, "next_look": None, "games_per_opponent": 0}
        self.lock = threading.Lock()
        self.stopping = stopping
        self.last = 0.0

    def pair(self, key, opponent, total, done=0, wins=0, other=0):
        with self.lock:
            record = self.pairs.setdefault(key, {"opponent": {"id": opponent.get("id"),
                                                              "version": opponent.get("version"),
                                                              "title": opponent.get("title")},
                                                 "done": done, "total": total, "wins": 0, "other": 0,
                                                 "playing": False})
            record["total"] = total
            record["done"] = done
            record["wins"] = wins
            record["other"] = other
        return record

    def detail(self):
        return {"mode": self.mode, **self.extra, "pairs": {k: dict(v) for k, v in self.pairs.items()}}

    def tick(self, final=False):
        if self.outer is None:
            return
        now = time.monotonic()
        if not final and now - self.last < 0.25:
            return
        self.last = now
        with self.lock:
            detail = self.detail()
            done = self.done
        self.outer(done, max(self.total, done), detail)

    def runner_progress(self, key, side):
        """A pair run's progress callback: its games (side: the tested deck's side in the run's
        card_sha order, for the pair's wins) added to the test's."""
        seen = {"done": 0}
        record = self.pairs[key]
        start = record["done"]
        start_wins, start_other = record["wins"], record["other"]

        def report(done, total, counts):
            if self.stopping.is_set():
                raise common.Stopped("the test was stopped")
            with self.lock:
                self.done += done - seen["done"]
                seen["done"] = done
                record["done"] = start + done
                wins = (counts or {}).get("wins") or [0, 0]
                record["wins"] = start_wins + wins[side]
                record["other"] = start_other + (counts or {}).get("other", 0)
                record["playing"] = True
            self.tick()
        return report


def _new_summary(tid, base_entry, variant, against, mode, opponents, margin, by, limited, field_space=None):
    fmt = lists.fmt_for(base_entry["kind"])
    against_value = _against_value(against, fmt, field_space)
    if isinstance(against_value, dict):
        against_value["title"] = against.get("title")
    return {"test": tid, "version": SUMMARY_VERSION,
            "base": {"id": base_entry["id"], "version": base_entry["version"], "card_sha": base_entry["card_sha"],
                     "title": base_entry["title"], "kind": base_entry["kind"]},
            "variant": {"card_sha": variant["card_sha"], "dck_sha": variant["dck_sha"], "changes": variant["changes"],
                        "cards": variant["cards"]},
            "against": against_value, "limited": sorted(limited) if limited else None,
            "format": fmt, "mode": mode, "created_mode": mode, "margin": margin,
            "opponents": [{"id": o["id"], "version": o["version"], "card_sha": o["card_sha"], "title": o.get("title"),
                           "base_key": None, "paired_key": None, "base_side": None, "variant_side": None,
                           "dropped": None} for o in opponents],
            "looks": [], "starter_mismatch": {"games": 0, "of": 0}, "outcome": None, "decision": None,
            "games_per_opponent": 0, "created": common._now(), "updated": None, "by": by}


def _games_per_opponent(summary):
    looks = summary.get("looks") or []
    return looks[-1]["games_per_opponent"] if looks else 0


def _final(summary):
    return summary.get("outcome") in seqstats.PAIRED_VERDICTS


def _check_key(record, name, key):
    """The first run of a pair fixes its key; another later means the engine changed (section 1)."""
    if record.get(name) is None:
        record[name] = key
    elif record[name] != key:
        raise ForgeError(ENGINE_CHANGED)


def _play_pair(state, record, opponent, target):
    """One opponent's stage: the base topped up to target, then the variant on the base's first
    target game numbers it doesn't hold yet. Today's engine's base key is checked against the
    pair's first one every time (ENGINE_CHANGED), even when the base already holds the target,
    so a paired result never gets games of two engines."""
    base_entry, variant, kw = state["base"], state["variant"], state["kw"]
    results_dir = kw["results_dir"]
    progress = state["progress"]
    base_key = _base_key(base_entry, opponent)
    _check_key(record, "base_key", base_key)
    base = saved.load(base_key, results_dir)
    have = len(_games(base))
    base_side_order = 0 if base_entry["card_sha"] <= opponent["card_sha"] else 1
    if have < target:
        games = _games(base)
        progress.pair(base_key, opponent, target, have,
                      sum(g["w"] == base_side_order for g in games), sum(g["w"] is None for g in games))
        result = runner.run(base_entry, opponent, target - have, by=kw["by"],
                            progress=progress.runner_progress(base_key, base_side_order), exact=True,
                            **_run_kw(kw))
        progress.pairs[base_key]["playing"] = False
        _check_key(record, "base_key", result["key"])
        base = result
    if base is None:
        return
    if not _deck_order(base.get("engine")):
        raise ForgeError(NO_DECK_ORDER)
    mirror = base["sides"][0]["card_sha"] == base["sides"][1]["card_sha"]
    beta = 0 if mirror else _index_of(base, base_entry["card_sha"])
    nu = _variant_index(variant, opponent)
    vkey = paired_key(record["base_key"], beta, variant["card_sha"], variant["dck_sha"])
    _check_key(record, "paired_key", vkey)
    record["base_side"], record["variant_side"] = beta, nu
    flip = paired_flip(base["seeds"]["flip"], beta, nu)
    paired = load_paired(vkey, results_dir)
    held = {g["g"] for g in _games(paired)}
    wanted = _first_numbers(base, target)
    numbers = [g for g in wanted if g not in held]
    wanted_set = set(wanted)
    held_games = [g for g in _games(paired) if g["g"] in wanted_set]
    wins, other = sum(g["w"] == nu for g in held_games), sum(g["w"] is None for g in held_games)
    if not numbers:
        progress.pair(vkey, opponent, len(wanted), len(wanted), wins, other)
        return
    progress.pair(vkey, opponent, len(wanted), len(wanted) - len(numbers), wins, other)
    extra = {"paired": {"base_key": record["base_key"], "base_side": beta, "variant_side": nu,
                        "variant": {"card_sha": variant["card_sha"], "dck_sha": variant["dck_sha"],
                                    "aligned_to": variant["aligned_to"], "changes": variant["changes"]}}}
    result = runner.run(variant, opponent, len(numbers), by=kw["by"],
                        progress=progress.runner_progress(vkey, nu), exact=True, numbers=numbers,
                        seeds={"base": base["seeds"]["base"], "stream": base["seeds"]["stream"], "flip": flip},
                        key=vkey, kind="paired", extra=extra, **_run_kw(kw))
    progress.pairs[vkey]["playing"] = False
    if result.get("key") not in (None, vkey):
        raise ForgeError(ENGINE_CHANGED)
    if not _deck_order(result.get("engine")):
        raise ForgeError(NO_DECK_ORDER)


def _run_kw(kw):
    """runner.run's keywords a test passes on (the log tee only when asked for, so a run without
    wave 3's R still takes them)."""
    out = {"results_dir": kw["results_dir"], "pool": kw["pool"], "local": kw["local"]}
    if kw.get("log_dir") is not None:
        out["log_dir"] = kw["log_dir"]
        out["log_every"] = kw["log_every"]
    return out


def _opponent_record(summary, opponent):
    """The original captured record of a current or renamed opponent, without rewriting it."""
    return next((record for record in summary["opponents"]
                 if record["card_sha"] == opponent["card_sha"] and
                 deck_identity.same(record["id"], opponent["id"])), None)


def _stage(state, summary, opponents, target):
    """Play every remaining opponent to target games a deck, up to inflight pair runs at once.
    A ForgeError drops that opponent (BUSY, its base matchup played by another job, is tried again
    after each of BUSY_WAITS_S, behind the others); a stop stops every pair run (each saves the
    games it finished), then raises again. A pair run failing while the test stops (a Ctrl+C's
    Java children dying with it) is the stop, not a drop, and drops made in a stage that ends
    the test are undone, so a resumed test plays those opponents again."""
    todo = [(o, record) for o in opponents if (record := _opponent_record(summary, o)) is not None
            and record.get("dropped") is None]
    queue_ = list(todo)
    tries = {}                  # record id -> BUSY answers so far
    dropped_now = []
    lock = threading.Lock()
    failure = []                # the first error that ends the test (a stop, an engine change, anything else)
    stopping = state["stopping"]

    def busy_wait(seconds):
        """Wait out a BUSY answer: True when the test stops meanwhile (the job's Stop raises
        from the progress tick)."""
        until = time.monotonic() + seconds
        while not stopping.wait(min(1.0, max(0.0, until - time.monotonic()))):
            if time.monotonic() >= until:
                return False
            state["progress"].tick()
        return True

    def work():
        while True:
            with lock:
                if failure or not queue_:
                    return
                opponent, record = queue_.pop(0)
            wait = None
            try:
                _play_pair(state, record, opponent, target)
            except ForgeError as e:
                text = str(e)
                if stopping.is_set() or text == ENGINE_CHANGED or text == NO_DECK_ORDER:
                    with lock:
                        failure.append(e)
                    stopping.set()
                    return
                with lock:
                    if text == runner.BUSY and tries.get(record["id"], 0) < len(BUSY_WAITS_S):
                        wait = BUSY_WAITS_S[tries.get(record["id"], 0)]
                        tries[record["id"]] = tries.get(record["id"], 0) + 1
                    else:
                        record["dropped"] = f"couldn't be played: {text}"
                        dropped_now.append(record)
            except BaseException as e:      # a stop, or anything else: the test ends
                with lock:
                    failure.append(e)
                stopping.set()
                return
            if wait is None:
                continue
            try:
                if busy_wait(wait):
                    return
            except BaseException as e:      # the job's Stop
                with lock:
                    failure.append(e)
                stopping.set()
                return
            with lock:
                queue_.append((opponent, record))

    threads = [threading.Thread(target=work, name=f"variant-{i}", daemon=True)
               for i in range(min(state["inflight"], len(todo)) or 1)]
    for t in threads:
        t.start()
    try:
        for t in threads:
            while t.is_alive():
                t.join(0.2)
    except KeyboardInterrupt as e:          # Ctrl+C on the command line: stop every pair run
        state["stopping"].set()
        for t in threads:
            t.join()
        failure.insert(0, e)
    if failure:
        for record in dropped_now:
            record["dropped"] = None
        raise failure[0]        # the cause: the other pair runs only stopped because of it


def _look_numbers(state, summary, opponents, target):
    """The paired differences at target games a deck: {card_sha|id: paired_diff()} of every
    remaining opponent, and the field's (paired_field) or None."""
    diffs = {}
    results_dir = state["kw"]["results_dir"]
    for o in opponents:
        record = _opponent_record(summary, o)
        if record.get("dropped") is not None or record.get("paired_key") is None:
            continue
        base = saved.load(record["base_key"], results_dir)
        paired = load_paired(record["paired_key"], results_dir)
        numbers = set(_first_numbers(base, target))
        base_games = [g for g in _games(base) if g["g"] in numbers]
        paired_games = [g for g in _games(paired) if g["g"] in numbers]
        diffs[record["card_sha"] + "|" + record["id"]] = seqstats.paired_diff(
            base_games, paired_games, record["base_side"], record["variant_side"])
    return diffs


def _judge(summary, diffs, target, looks, *, stopped=False, interim=False):
    """One look (seqstats.paired_look) at target games a deck, added to the summary."""
    field_test = summary["against"] if isinstance(summary["against"], str) else None
    margin = summary["margin"]
    if field_test:
        diff = seqstats.paired_field(list(diffs.values()))
    else:
        diff = next(iter(diffs.values()), None)
    if diff is None or diff.get("delta") is None:
        diff = {"delta": None, "low": None, "high": None, "z": None}
    found = seqstats.paired_look(diff, target, looks=looks, max_games=looks[-1], margin=margin,
                                 stopped=stopped, interim=interim)
    mismatch = [d.get("starter_mismatch") or {} for d in diffs.values()]
    summary["starter_mismatch"] = {"games": sum(m.get("games") or 0 for m in mismatch),
                                   "of": sum(m.get("of") or 0 for m in mismatch)}
    summary["looks"].append(found)
    summary["games_per_opponent"] = target
    summary["decision"] = found.get("decision")
    return found


def _keys_today(summary, base_entry, opponents):
    """True when every opponent's base key in the summary is the one today's engine gives."""
    for o in opponents:
        record = _opponent_record(summary, o)
        if record is None or record.get("dropped") is not None or record.get("base_key") is None:
            continue
        if record["base_key"] != _base_key(base_entry, o):
            return False
    return True


@lifecycle.writing("base_entry", "against", "opponents")
def run_test(base_entry, variant_cards, against, mode="ahead", *, by, progress=None, results_dir=None, pool=None,
             local=False, log_dir=None, log_every=1, opponents=None, extend=None, field_options=None):
    """Play a variant test (section 11.4) and return its summary (section 14.3).

    base_entry is the list as it is today (lists.entry), variant_cards the changed list's
    {"Commander": [[qty, name]], "Main": [...]}, against an entry or "field" (opponents: the
    field's "<deck id>[@version]" names to limit it to), mode "ahead", "quick" or an int (games a
    deck). extend=<test id> is "Play more": that test (its summary must be this one's) goes on as
    "ahead" to the next look. A test that's already been played (the same id) goes on from where
    it stopped, or returns its summary when it has a verdict; one whose engine has changed since
    starts again.

    ForgeError (a plain sentence) when it can't start: no deck-order-1 in today's engine
    (NO_DECK_ORDER), no opponent, nothing more to play, the list changed (LIST_CHANGED), the
    engine changed between stages (ENGINE_CHANGED), or the same test is playing elsewhere (BUSY).
    ValueError for a change that doesn't keep the deck's size or changes nothing. A stop (the
    job's Stop, Ctrl+C) saves the summary with outcome "stopped" and raises again."""
    if not _deck_order(engine.today()):
        raise ForgeError(NO_DECK_ORDER)
    variant = variant_entry(base_entry, variant_cards)
    field_test = against == "field"
    fmt = lists.fmt_for(base_entry["kind"])
    if not field_test and against.get("kind") != base_entry["kind"]:
        raise ForgeError(common.MIXED_KINDS)
    limited = sorted(opponents) if field_test and opponents else None
    mode = _mode_value(mode)
    if extend is not None:
        tid = extend
        summary = load_summary(extend, results_dir)
        if summary is None:
            raise ForgeError(NOT_A_TEST)
        tested = (summary["base"]["card_sha"], summary["variant"]["card_sha"])
        if tested != (base_entry["card_sha"], variant["card_sha"]):
            raise ForgeError(LIST_CHANGED)
        limited = summary.get("limited")
    else:
        tid = test_id(base_entry, variant, against, mode, limited,
                      field_space=(field_options or {}).get("space"))
        summary = load_summary(tid, results_dir)
    folder = _tests_dir(results_dir)
    try:
        lock = runner._claim(folder, tid)
    except ForgeError as e:
        raise ForgeError(BUSY if str(e) == runner.BUSY else str(e)) from None
    try:
        # Every run of the test (base top-ups and pair runs, up to inflight at once) plays in one
        # pool session, as the field's runs do: never a cold pool of each run's own.
        with pools.session(local=local) if pool is None else contextlib.nullcontext(pool) as session:
            return _run_test(tid, summary, base_entry, variant, against, field_test, fmt, mode, limited, extend,
                             by=by, progress=progress, results_dir=results_dir, pool=session, local=local,
                             log_dir=log_dir, log_every=log_every, field_options=field_options)
    finally:
        runner._release(lock, folder / f"{tid}.lock")


def _run_test(tid, summary, base_entry, variant, against, field_test, fmt, mode, limited, extend, *, by, progress,
              results_dir, pool, local, log_dir, log_every, field_options=None):
    opponent_entries = _opponent_entries(base_entry, against, limited, field_options)
    margin = _margin(field_test)
    if summary is not None and extend is None and not _keys_today(summary, base_entry, opponent_entries):
        summary = None          # played with an earlier engine: start again
    if summary is None:
        if extend is not None:
            raise ForgeError(NOT_A_TEST)
        summary = _new_summary(tid, base_entry, variant, against, mode, opponent_entries, margin, by, limited,
                               (field_options or {}).get("space"))
    else:
        opponent_entries = [o for o in opponent_entries if _opponent_record(summary, o) is not None]
        if not opponent_entries:
            raise ForgeError(NO_OPPONENTS)
        if extend is None and _final(summary):
            return summary      # already played to a verdict
        if extend is not None and not _keys_today(summary, base_entry, opponent_entries):
            raise ForgeError(ENGINE_CHANGED_MORE)
    if extend is not None:
        # "Play more": the looks already made count as interim looks (section 7.4), and the test
        # goes on as "ahead" from the next look.
        for found in summary["looks"]:
            found["interim"] = True
            found["bound"] = seqstats.HP_INTERIM
        summary["mode"] = "ahead"
        looks = _ahead_looks(field_test)
    else:
        looks = _looks(summary["mode"], field_test)
    # The next looks: after the last planned look made (a stopped look, made between planned looks,
    # doesn't count: the stage it stopped in plays on to its planned look).
    planned_done = max([found["games_per_opponent"] for found in summary["looks"] if not found.get("stopped")]
                       or [0])
    plan = [t for t in looks if t > planned_done]
    if not plan:
        if extend is not None:
            raise ForgeError(NO_MORE)
        return summary
    summary["by"] = summary.get("by") or by
    summary["outcome"] = None
    stopping = threading.Event()
    total = _planned(base_entry, variant, opponent_entries, summary, plan[-1], results_dir)
    tracker = _Progress(progress, total, summary["mode"], stopping)
    state = {"base": base_entry, "variant": variant, "progress": tracker, "stopping": stopping,
             "inflight": _inflight(),
             "kw": {"by": by, "results_dir": results_dir, "pool": pool, "local": local, "log_dir": log_dir,
                    "log_every": log_every}}
    _write_summary(summary, results_dir)
    for stage, target in enumerate(plan, 1):
        tracker.extra = {"stage": stage, "next_look": target, "games_per_opponent": target}
        try:
            tracker.tick(final=True)        # (the job's Stop raises here too)
            _stage(state, summary, opponent_entries, target)
        except STOPS:
            _stopped_look(state, summary, opponent_entries, looks)
            summary["outcome"] = "stopped"
            _write_summary(summary, results_dir)
            raise
        except BaseException:
            summary["outcome"] = "error"
            _write_summary(summary, results_dir)
            raise
        remaining = [o for o in opponent_entries if not _dropped(summary, o)]
        if not remaining:
            summary["outcome"] = "error"
            _write_summary(summary, results_dir)
            raise ForgeError("No opponent could be played: " + "; ".join(
                f"{r.get('title') or r['id']} {r['dropped']}" for r in summary["opponents"] if r.get("dropped")) + ".")
        diffs = _look_numbers(state, summary, remaining, target)
        found = _judge(summary, diffs, target, looks)
        _write_summary(summary, results_dir)
        if found.get("decision") != "continue":
            summary["outcome"] = found["decision"] if found["decision"] in seqstats.PAIRED_VERDICTS else "not_settled"
            break
    else:
        if summary.get("outcome") is None:
            summary["outcome"] = summary.get("decision") if summary.get("decision") in seqstats.PAIRED_VERDICTS \
                else "not_settled"
    _write_summary(summary, results_dir)
    try:
        tracker.tick(final=True)
    except STOPS:
        pass                # Stop pressed once the test was over: its verdict stands
    return summary


def _dropped(summary, opponent):
    record = _opponent_record(summary, opponent)
    return record is None or record.get("dropped") is not None


def _stopped_look(state, summary, opponents, looks):
    """A look at the games every remaining opponent's arms have in common when the test stopped
    between looks (judged at HP_INTERIM: "stopped")."""
    try:
        remaining = [o for o in opponents if not _dropped(summary, o)]
        counts = []
        for o in remaining:
            record = _opponent_record(summary, o)
            paired = load_paired(record["paired_key"], state["kw"]["results_dir"]) if record.get("paired_key") else None
            counts.append(len(_games(paired)))
        target = min(counts) if counts else 0
        if target <= _games_per_opponent(summary):
            return
        diffs = _look_numbers(state, summary, remaining, target)
        _judge(summary, diffs, target, looks, stopped=True)
    except Exception as e:      # the stop goes on up whatever happens here
        common._log(f"A stopped test's numbers couldn't be worked out ({type(e).__name__}: {e}).")


def _planned(base_entry, variant, opponents, summary, last, results_dir):
    """The new games of the plan to its last look (the worst case: base top-ups included)."""
    total = 0
    for o in opponents:
        if _dropped(summary, o):
            continue
        record = _opponent_record(summary, o)
        try:
            base = saved.load(record.get("base_key") or _base_key(base_entry, o), results_dir)
        except ForgeError:
            base = None
        base_n = len(_games(base))
        paired = load_paired(record["paired_key"], results_dir) if record.get("paired_key") else None
        wanted = set(_first_numbers(base, last))
        held = sum(1 for g in _games(paired) if g["g"] in wanted)
        total += max(0, last - base_n) + max(0, last - held)
    return total


# ============================================================ what the page and the command line show

def _pts(x, sign=True):
    """A difference in points of win rate: "+2.4", "−0.6"."""
    value = round(100 * x, 1)
    if value == 0:
        return "0.0"
    text = f"{abs(value):.1f}"
    return (("+" if value > 0 else "−") + text) if sign else text


def verdict_words(summary, titles=None):
    """The verdict sentence of a test (section 11.6), from its last look: "Better against the field:
    +2.4 points of win rate (+0.6 to +4.2)", "Makes little difference: within 2 points of win rate",
    "Worse ...", "Not settled yet after 400 games a deck" or "Stopped early: the result shows the
    games played so far"; None before any look. titles: {"against": the one opponent's title}."""
    outcome = summary.get("outcome")
    looks = summary.get("looks") or []
    if outcome == "stopped":
        return "Stopped early: the result shows the games played so far"
    if outcome == "error" and not looks:
        return None
    if not looks:
        return None
    last = looks[-1]
    decision = outcome if outcome in seqstats.PAIRED_VERDICTS else last.get("decision")
    against = "the field" if isinstance(summary.get("against"), str) else \
        ((titles or {}).get("against") or (summary.get("against") or {}).get("title") or "that deck")
    margin = round(100 * (summary.get("margin") or 0))
    games = last.get("games_per_opponent") or 0
    numbers = ""
    if last.get("delta") is not None and last.get("low") is not None:
        numbers = f": {_pts(last['delta'])} points of win rate ({_pts(last['low'])} to {_pts(last['high'])})"
    if decision == "better":
        return f"Better against {against}{numbers}"
    if decision == "worse":
        return f"Worse against {against}{numbers}"
    if decision == "slightly_better":
        return f"A little better against {against}{numbers}, within {margin} points"
    if decision == "slightly_worse":
        return f"A little worse against {against}{numbers}, within {margin} points"
    if decision == "little_difference":
        return f"Makes little difference: within {margin} points of win rate"
    if decision == "continue" and outcome is None:
        return f"Not settled yet after {games:,} games a deck"
    return f"Not settled yet after {games:,} games a deck"


def _paired_json(diff):
    if not diff:
        return None
    keys = ("delta", "low", "high", "n", "rho", "same", "starter_mismatch", "unpaired", "saved_share", "z")
    return {k: diff.get(k) for k in keys}


def visible_summary(summary, visible=None):
    """A response copy with visible opponents only; never retain hidden-field verdicts."""
    if visible is None:
        return summary
    rows = [row for row in summary.get("opponents") or [] if visible(row.get("id"))]
    if len(rows) == len(summary.get("opponents") or []):
        return summary
    limited = summary.get("limited")
    if limited is not None:
        limited = [name for name in limited if visible(field._split_name(name)[0])]
    return dict(summary, opponents=rows, limited=limited, looks=[], outcome=None, decision=None,
                games_per_opponent=0, starter_mismatch={"games": 0, "of": 0})


def view(test, results_dir=None, *, visible=None):
    """A test's view (sections 14.3 and 15), or None when there's no such test: {"test": the summary,
    "opponents": [{id, version, title, card_sha, base_key, paired_key, dropped, games, paired:
    paired_diff()'s numbers over every game both arms have, or None}], "field": {delta, low, high}
    over the field's opponents (None against one deck or without numbers), "margin", "verdict" (the
    outcome, or None), "words" (verdict_words)}."""
    summary = load_summary(test, results_dir)
    if summary is None:
        return None
    summary = visible_summary(summary, visible)
    rows, diffs = [], []
    for record in summary["opponents"]:
        paired = diff = None
        base = saved.load(record["base_key"], results_dir) if record.get("base_key") else None
        if record.get("paired_key"):
            paired = load_paired(record["paired_key"], results_dir)
        if base is not None and paired is not None and record.get("base_side") is not None:
            try:
                diff = seqstats.paired_diff(_games(base), _games(paired), record["base_side"], record["variant_side"])
            except NotImplementedError:
                diff = None
        if diff is not None and record.get("dropped") is None:
            diffs.append(diff)
        rows.append({**{k: record.get(k) for k in ("id", "version", "title", "card_sha", "base_key", "paired_key",
                                                    "dropped")},
                     "games": len(_games(paired)), "paired": _paired_json(diff)})
    field_numbers = None
    if isinstance(summary.get("against"), str) and diffs:
        try:
            found = seqstats.paired_field(diffs)
        except NotImplementedError:
            found = None
        if found:
            field_numbers = {"delta": found.get("delta"), "low": found.get("low"), "high": found.get("high")}
    outcome = summary.get("outcome")
    return {"test": summary, "opponents": rows, "field": field_numbers, "margin": summary.get("margin"),
            "verdict": outcome if outcome in OUTCOMES else None, "words": verdict_words(summary)}


def tests_for(deck_id, version, results_dir=None):
    """The summaries of a deck's list's tests (its id and version), newest first."""
    folder = _tests_dir(results_dir)
    try:
        paths = list(folder.glob("*.json"))
    except OSError:
        return []
    out = []
    for path in paths:
        summary = load_summary(path.stem, results_dir)
        if summary and deck_identity.same(summary["base"].get("id"), deck_id) and \
                summary["base"].get("version") == version:
            out.append(summary)
    return sorted(out, key=lambda s: s.get("created") or "", reverse=True)


# ============================================================ entries for the api and the command line

def base_entry(deck_id, version="target"):
    """A deck file's list as it is today (lists.entry). ForgeError for an unknown deck or version."""
    with lists.one_snapshot():
        return _base_entry(deck_id, version)


def _base_entry(deck_id, version):
    summary = decks.find_summary(deck_id)
    if summary is None or summary.get("error"):
        raise ForgeError(f"There's no deck called {deck_id}.")
    if version not in summary["versions"]:
        raise ForgeError(f"{summary['title']} has no {'owned-only' if version == 'owned' else version} list.")
    try:
        sections = decks.load_deck(summary["id"], version)
    except (decks.DeckNotFound, decks.DeckFileError) as e:
        raise ForgeError(f"{summary['title']} can't be read: {e}") from None
    return lists.entry(summary["id"], version, summary["title"], decks.engine_kind(summary), sections)


def config_margin(field_test):
    """The margin a new test judges with (config forge_variant_margin / _one)."""
    return _margin(field_test)


