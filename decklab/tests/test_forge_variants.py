"""Tests for paired variant tests (decklab/lib/forge/variants.py, simulation wave 3's R15,
forge-trial/sim-wave3-contract.md section 11): the aligned .dck writer (in place, a name already
in the deck, land swaps, Commander, sizes), the variant entry, the flip formula across side orders,
keys and test ids, and the coordinator (base top-ups, paired numbers, filling holes after a stop,
"Play more" making earlier looks interim, the margins, a dropped opponent, a key change, the
refusal without deck-order-1) with a stand-in for runner.run that saves results as wave 3's R
does. The stand-in decides each game by its seat and seed, so the variant's games pair with the
base's only when the flip is right (no starter mismatch).

Tests that play the fake Forge through runner.run's wave 3 keywords skip until package R has
built them (runner.RUN_FEATURES); those that need seqstats' paired functions skip until package
S has built them.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_forge_variants
"""
import hashlib
import io
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import forge
from decklab.lib.forge import common, engine, runner, seeds, seqstats, variants
from decklab.tests import test_forge
from decklab.tests.test_forge import GISA, GREEN, RED, entry, sections

ORDER = {"game_patches": ["attack-requirements-in-order-1", "deck-order-1"]}


def seqstats_built():
    try:
        seqstats.paired_verdict(-0.1, 0.1, 0.03)
    except NotImplementedError:
        return False
    return True


def cards_of(text, kind="constructed"):
    return forge.lists._section_cards(sections(text))


def changed(text, remove=(), add=()):
    """The cards of text with (qty, name) removed from and added to Main."""
    cards = cards_of(text)
    main = {}
    for q, n in cards["Main"]:
        main[n] = main.get(n, 0) + q
    for q, n in remove:
        main[n] -= q
    for q, n in add:
        main[n] = main.get(n, 0) + q
    cards["Main"] = [[q, n] for n, q in main.items() if q > 0]
    return cards


def dck_lines(text):
    return [line for line in text.splitlines() if line and not line.startswith("[") and "=" not in line]


def expand(text, section="[Main]"):
    """The .dck's section expanded copy by copy, in line order (as DeckOrder reads it)."""
    out, on = [], False
    for line in text.splitlines():
        if line.startswith("["):
            on = line == section
            continue
        if on and line:
            qty, name = line.split(" ", 1)
            out += [name] * int(qty)
    return out


class WriterTests(unittest.TestCase):

    def test_a_swap_in_place(self):
        base = entry(GREEN, "casual/green")
        text, changes = variants.aligned_dck(base, changed(GREEN, [(1, "Fiery Annihilation")], [(1, "Shock")]))
        self.assertEqual(changes, {"remove": [[1, "Fiery Annihilation"]], "add": [[1, "Shock"]]})
        before, after = expand(base["dck"]), expand(text)
        self.assertEqual(len(before), len(after))
        # Every card but the changed one keeps its place in the library before the shuffle.
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual([before[i] for i in diffs], ["Fiery Annihilation"])
        self.assertEqual([after[i] for i in diffs], ["Shock"])
        lines = dck_lines(text)
        base_lines = dck_lines(base["dck"])
        at = base_lines.index("1 Fiery Annihilation")     # its line went, and Shock's took its place
        self.assertEqual(lines[at], "1 Shock")
        self.assertEqual(lines[:at], base_lines[:at])
        # Name= is the variant's canonical card_sha.
        variant = variants.variant_entry(base, changed(GREEN, [(1, "Fiery Annihilation")], [(1, "Shock")]))
        self.assertIn(f"Name={variant['card_sha'][:12]}\n", text)
        self.assertEqual(variant["card_sha"], forge.lists._list_text(variant["cards"], "constructed")[1])

    def test_a_name_already_in_the_deck_gets_its_own_line(self):
        base = entry(GREEN, "casual/green")
        text, changes = variants.aligned_dck(base, changed(GREEN, [(1, "Fiery Annihilation")], [(1, "Overrun")]))
        self.assertEqual(changes["add"], [[1, "Overrun"]])
        lines = dck_lines(text)
        self.assertEqual(lines.count("2 Overrun") + lines.count("1 Overrun"), 2)
        before, after = expand(base["dck"]), expand(text)
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(len(diffs), 1)

    def test_copies_come_off_a_lines_end_and_added_ones_sort_by_name(self):
        base = entry(GREEN, "casual/green")
        cards = changed(GREEN, [(3, "Grizzly Bears")], [(2, "Shock"), (1, "Ambush Viper")])
        text, changes = variants.aligned_dck(base, cards)
        self.assertEqual(changes, {"remove": [[3, "Grizzly Bears"]], "add": [[1, "Ambush Viper"], [2, "Shock"]]})
        lines = dck_lines(text)
        at = lines.index("1 Grizzly Bears")
        self.assertEqual(lines[at + 1:at + 3], ["1 Ambush Viper", "2 Shock"])
        before, after = expand(base["dck"]), expand(text)
        start = before.index("Grizzly Bears")
        self.assertEqual(after[start:start + 4], ["Grizzly Bears", "Ambush Viper", "Shock", "Shock"])
        self.assertEqual(before[:start], after[:start])
        self.assertEqual(before[start + 4:], after[start + 4:])

    def test_land_swaps(self):
        base = entry(RED, "casual/red")
        text, changes = variants.aligned_dck(base, changed(RED, [(2, "Mountain")], [(2, "Swamp")]))
        self.assertEqual(changes, {"remove": [[2, "Mountain"]], "add": [[2, "Swamp"]]})
        before, after = expand(base["dck"]), expand(text)
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual([before[i] for i in diffs], ["Mountain", "Mountain"])
        self.assertEqual(dck_lines(text).count("2 Swamp"), 1)      # its own line after the Mountains

    def test_commander(self):
        base = entry(GISA, "commander/gisa", "commander")
        cards = forge.lists._section_cards(sections(GISA))
        cards["Main"] = [[3, "Murderous Rider // Swift End"], [11, "Swamp"]]
        text, changes = variants.aligned_dck(base, cards)
        self.assertTrue(text.split("\n")[2] == "[Commander]")
        self.assertEqual(expand(text, "[Commander]"), ["Ghoulcaller Gisa"])
        self.assertEqual(changes, {"remove": [[1, "Murderous Rider"]], "add": [[1, "Swamp"]]})
        # The commander's own count must stay: moving a card into the Commander section is refused.
        cards = forge.lists._section_cards(sections(GISA))
        cards["Commander"].append([1, "Swamp"])
        cards["Main"] = [[4, "Murderous Rider // Swift End"], [9, "Swamp"]]
        with self.assertRaises(ValueError):
            variants.aligned_dck(base, cards)

    def test_sizes_and_no_change_are_refused(self):
        base = entry(GREEN, "casual/green")
        with self.assertRaises(ValueError) as caught:
            variants.aligned_dck(base, changed(GREEN, [(1, "Fiery Annihilation")]))
        self.assertEqual(str(caught.exception), variants.SIZE_CHANGED.format(out=1, into=0))
        with self.assertRaises(ValueError) as caught:
            variants.aligned_dck(base, cards_of(GREEN))
        self.assertEqual(str(caught.exception), variants.NO_CHANGE)

    def test_the_variant_entry(self):
        base = dict(entry(GREEN, "casual/green", title="Green"), pilot={"profile": "Default", "switches": []})
        cards = changed(GREEN, [(1, "Fiery Annihilation")], [(1, "Shock")])
        found = variants.variant_entry(base, cards)
        self.assertEqual((found["id"], found["version"], found["title"], found["kind"]),
                         ("variant:casual/green", "target", "Green (your change)", "constructed"))
        self.assertEqual(found["dck_file"], hashlib.sha256(found["dck"].encode()).hexdigest() + ".dck")
        self.assertEqual(found["aligned_to"], base["card_sha"])
        self.assertEqual(found["pilot"], base["pilot"])
        self.assertEqual(found["card_count"], base["card_count"])
        self.assertIsNone(found["source"])
        # The aligned text isn't the variant's sorted .dck (so it never overwrites it), but plays the same cards.
        self.assertNotEqual(found["dck"], forge.lists._dck(forge.lists._list_text(cards, "constructed")[0],
                                                           found["card_sha"]))
        self.assertEqual(sorted(expand(found["dck"])),
                         sorted(expand(forge.lists._dck(forge.lists._list_text(cards, "constructed")[0], "x"))))


class FlipTests(unittest.TestCase):

    def test_the_variant_takes_the_base_seat_in_every_game(self):
        for f_b in (0, 1):
            for beta in (0, 1):
                for nu in (0, 1):
                    f_p = variants.paired_flip(f_b, beta, nu)
                    for g in range(0, 200, 7):
                        base_deck1 = seeds.deck1_side(g, f_b) == beta
                        variant_deck1 = seeds.deck1_side(g, f_p) == nu
                        self.assertEqual(base_deck1, variant_deck1, (f_b, beta, nu, g))

    def test_keys(self):
        k = variants.paired_key("a" * 64, 1, "b" * 64, "c" * 64)
        self.assertEqual(k, engine._sha({"paired_version": 1, "base_key": "a" * 64, "base_side": 1,
                                         "variant": ["b" * 64, "c" * 64]}))
        self.assertNotEqual(k, variants.paired_key("a" * 64, 0, "b" * 64, "c" * 64))
        base = entry(GREEN, "casual/green")
        variant = variants.variant_entry(base, changed(GREEN, [(1, "Fiery Annihilation")], [(1, "Shock")]))
        red = entry(RED, "casual/red")
        ids = {variants.test_id(base, variant, "field", "ahead"), variants.test_id(base, variant, "field", "quick"),
               variants.test_id(base, variant, red, "ahead"), variants.test_id(base, variant, "field", 400),
               variants.test_id(base, variant, "field", "ahead", ["casual/red"])}
        self.assertEqual(len(ids), 5)
        with self.assertRaises(ValueError):
            variants.test_id(base, variant, "field", "slow")


# ============================================================ the coordinator, with a stand-in run

def _h(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


class FakeRuns:
    """runner.run as wave 3's R builds it, without Forge: game g's starting seat and its winning seat
    come from the result's stream and g (the same in both arms when the variant takes the base's
    seat), and a list holding WINNER wins a third of its games whatever happens (cardwins)."""

    WINNER = "Shock"

    def __init__(self, results):
        self.results = Path(results)
        self.calls = []
        self.stop_after = None          # stop (as the page's Stop) after this many games of the next run
        self.fail = {}                  # opponent card_sha -> a ForgeError's sentence
        self.keys = {}                  # (card_sha, card_sha) -> key, as today's engine gives

    def key(self, a, b):
        return self.keys.get(tuple(sorted((a["card_sha"], b["card_sha"])))) or engine._sha(
            sorted([a["card_sha"], b["card_sha"]]))

    def __call__(self, entry_a, entry_b, games, *, by, progress=None, results_dir=None, exact=False, numbers=None,
                 seeds=None, key=None, kind=None, extra=None, pool=None, local=False, **kwargs):
        self.calls.append({"a": entry_a["id"], "b": entry_b["id"], "games": games, "numbers": numbers,
                           "kind": kind, "seeds": seeds, "key": key, "pool": pool})
        for e in (entry_a, entry_b):
            if e["card_sha"] in self.fail:
                raise common.ForgeError(self.fail[e["card_sha"]])
        ordered = sorted([entry_a, entry_b], key=lambda e: e["card_sha"])
        key = key or self.key(entry_a, entry_b)
        folder = self.results / ("paired" if kind == "paired" else "")
        path = folder / f"{key}.json"
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            stream = forge.seeds.stream_hex(forge.seeds.stream_of(ordered[0]["card_sha"], ordered[1]["card_sha"]))
            record = seeds or {"base": 1, "stream": stream, "flip": 0}
            result = {"key": key, "format": "Constructed", "run_version": 2, "updated": "",
                      "engine": {"kind": "decklab", **ORDER},
                      "seeds": {"scheme": forge.seeds.SCHEME, "base": record["base"], "stream": record["stream"],
                                "seat_block": 25, "flip": record["flip"]},
                      "next_game": 0, "sides": [forge.runner._side(e) for e in ordered], "runs": [], "batches": [],
                      "failed": []}
            for side, e in zip(result["sides"], ordered):
                side["seen_as"] = [{"id": e["id"], "version": e["version"], "title": e["title"]}]
            if kind:
                result["kind"] = kind
            result.update(extra or {})
        if seeds is not None:
            assert {k: result["seeds"][k] for k in ("base", "stream", "flip")} == seeds
        held = {g["g"] for b in result["batches"] for g in b["games"]}
        if numbers is None:
            numbers = list(range(result["next_game"], result["next_game"] + games))
        else:
            assert kind in ("paired", "experiment") and len(numbers) == games and not held & set(numbers)
        flip = result["seeds"]["flip"]
        played, stopped = [], None
        wins = [0, 0]
        for i, g in enumerate(numbers):
            if self.stop_after is not None and i == self.stop_after:
                stopped = common.Stopped("stopped")
                self.stop_after = None
                break
            deck1 = forge.seeds.deck1_side(g, flip)
            first = deck1 if _h(result["seeds"]["stream"], g, "start") % 2 == 0 else 1 - deck1
            seat_w = _h(result["seeds"]["stream"], g, "win") % 2
            w = deck1 if seat_w == 0 else 1 - deck1
            holders = [s for s in (0, 1)
                       if any(n == self.WINNER for _, n in result["sides"][s]["cards"].get("Main", []))]
            if len(holders) == 1 and _h(g, "card") % 3 == 0:
                w = holders[0]
            played.append({"g": g, "w": w, "r": "win", "first": first, "rounds": 5, "turns": 10, "ms": 100})
            wins[w] += 1
            if progress is not None:
                try:
                    progress(i + 1, len(numbers), {"wins": list(wins), "other": 0})
                except BaseException as e:
                    stopped = e
                    break
        if played:
            result["batches"].append({"n": len(result["runs"]), "first": played[0]["g"], "games": played,
                                      "casts": [{}, {}], "lands": [{}, {}]})
        result["runs"].append({"played": len(played), "by": by})
        result["next_game"] = max(result["next_game"], max(numbers) + 1 if numbers else 0)
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result), encoding="utf-8")
        if stopped is not None:
            raise stopped
        return result


class CoordinatorCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.runs = FakeRuns(self.tmp)
        self.settings = {"forge_field_inflight": 2, "forge_variant_margin": 0.02, "forge_variant_margin_one": 0.03}
        for p in (mock.patch.object(runner, "run", self.runs),
                  mock.patch.object(engine, "today", return_value=dict(ORDER, complete=True)),
                  mock.patch.object(variants, "_base_key", lambda a, b: self.runs.key(a, b)),
                  mock.patch.object(common, "_settings", lambda: dict(self.settings))):
            p.start()
            self.addCleanup(p.stop)
        self.base = entry(GREEN, "casual/green", title="Green")
        self.red = entry(RED, "casual/red", title="Red")
        self.blue = entry(RED.replace("4 Lightning Bolt", "4 Shock"), "casual/blue", title="Blue")
        self.cards = changed(GREEN, [(1, "Fiery Annihilation")], [(1, "Shock")])

    def run_test(self, against=None, mode="quick", **kwargs):
        return variants.run_test(self.base, self.cards, against or self.red, mode, by="Matt",
                                 results_dir=self.tmp, **kwargs)


class RefusalTests(CoordinatorCase):

    def test_no_deck_order_patch(self):
        with mock.patch.object(engine, "today", return_value={"game_patches": ["attack-requirements-in-order-1"]}):
            with self.assertRaises(common.ForgeError) as caught:
                self.run_test()
        self.assertEqual(str(caught.exception), variants.NO_DECK_ORDER)
        self.assertEqual(self.runs.calls, [])

    def test_the_field_needs_f(self):
        with mock.patch.object(forge.field, "opponents", side_effect=NotImplementedError):
            with self.assertRaises(common.ForgeError) as caught:
                self.run_test("field")
        self.assertEqual(str(caught.exception), variants.FIELD_NOT_BUILT)


class StageTests(CoordinatorCase):
    """The pool session, the engine check of every stage, and drops (no seqstats needed)."""

    def state(self, inflight=1, outer=None):
        stopping = threading.Event()
        return {"base": self.base, "variant": variants.variant_entry(self.base, self.cards),
                "progress": variants._Progress(outer, 0, "quick", stopping), "stopping": stopping,
                "inflight": inflight, "kw": {"by": "Matt", "results_dir": self.tmp, "pool": None, "local": False,
                                             "log_dir": None, "log_every": 1}}

    def summary(self, state):
        return variants._new_summary("f" * 64, self.base, state["variant"], "field", "quick", [self.blue, self.red],
                                     0.02, "Matt", None)

    def test_top_up_scores_include_the_saved_games_for_base_and_paired_runs(self):
        from decklab.lib import api
        state = self.state()
        record = self.summary(state)["opponents"][1]
        variants._play_pair(state, record, self.red, 20)
        seen = []

        def run(a, b, more, **kwargs):
            key = kwargs.get("key") or self.runs.key(a, b)
            stored = variants.load_paired(key, self.tmp) if kwargs.get("kind") == "paired" else forge.load(key, self.tmp)
            old = variants._games(stored)
            side = 0 if a["card_sha"] <= b["card_sha"] else 1
            before_wins = sum(g["w"] == side for g in old)
            before_other = sum(g["w"] is None for g in old)
            report = kwargs["progress"]

            def progress(done, total, counts):
                report(done, total, counts)
                pair = state["progress"].pairs[key]
                self.assertEqual(pair["done"], len(old) + done)
                self.assertEqual(pair["wins"], before_wins + counts["wins"][side])
                self.assertEqual(pair["other"], before_other + counts["other"])
                found = {"pair": pair, "snap": {"seconds": 1}, "deck_sha": a["card_sha"],
                         "via": {"by": "Matt", "kind": "variant"}}
                shown = api.forge_runs._coord_progress(found, a["card_sha"])
                self.assertEqual(shown["range"]["value"], round(pair["wins"] / pair["done"], 4))
                seen.append(kwargs.get("kind"))

            return self.runs(a, b, more, **dict(kwargs, progress=progress))

        with mock.patch.object(runner, "run", run):
            variants._play_pair(state, record, self.red, 40)
            state = self.state()  # a resumed coordinator also seeds its scores from saved results
            variants._play_pair(state, record, self.red, 60)
        self.assertEqual(set(seen), {None, "paired"})

    def test_every_run_of_a_test_shares_one_pool_session(self):
        with mock.patch.object(variants, "_run_test", return_value={}) as inner:
            self.run_test()
            self.assertIsInstance(inner.call_args.kwargs["pool"], forge.pool.Session)
            given = object()
            self.run_test(pool=given)
            self.assertIs(inner.call_args.kwargs["pool"], given)

    def test_the_pair_runs_get_the_session(self):
        state = self.state()
        session = object()
        state["kw"]["pool"] = session
        record = self.summary(state)["opponents"][1]
        variants._play_pair(state, record, self.red, 20)
        self.assertEqual([c["pool"] for c in self.runs.calls], [session, session])

    def test_an_engine_change_stops_a_stage_whose_base_has_its_games(self):
        state = self.state()
        record = self.summary(state)["opponents"][1]
        record["base_key"] = self.runs.key(self.base, self.red)       # the pair's first key
        self.runs.keys[tuple(sorted((self.base["card_sha"], self.red["card_sha"])))] = "e" * 64
        self.runs(self.base, self.red, 200, by="Matt")                  # today's base already holds the stage
        self.runs.calls.clear()
        with self.assertRaises(common.ForgeError) as caught:
            variants._play_pair(state, record, self.red, 200)
        self.assertEqual(str(caught.exception), variants.ENGINE_CHANGED)
        self.assertEqual(self.runs.calls, [])

    def play(self, state, summary, plays):
        """_stage with _play_pair answered by plays: {opponent id: [what each call does]} (the last
        one again once the others are used)."""
        calls = []

        def fake(state_, record, opponent, target):
            calls.append(opponent["id"])
            todo = plays[opponent["id"]]
            act = todo.pop(0) if len(todo) > 1 else todo[0]
            if act is not None:
                act()
        with mock.patch.object(variants, "_play_pair", fake):
            variants._stage(state, summary, [self.blue, self.red], 20)
        return calls

    @staticmethod
    def raises(error):
        def act():
            raise error
        return act

    @staticmethod
    def dropped(summary):
        return {r["id"]: r["dropped"] for r in summary["opponents"]}

    def test_a_failure_while_stopping_is_the_stop_not_a_drop(self):
        state = self.state()
        summary = self.summary(state)

        def dies():
            state["stopping"].set()             # Ctrl+C: the Java children die with the console
            raise common.ForgeError("No games could be played.")
        with self.assertRaises(common.ForgeError):
            self.play(state, summary, {"casual/blue": [dies], "casual/red": [None]})
        self.assertEqual(self.dropped(summary), {"casual/blue": None, "casual/red": None})

    def test_drops_in_a_stage_that_ends_the_test_are_undone(self):
        state = self.state()
        summary = self.summary(state)
        with self.assertRaises(common.Stopped):
            self.play(state, summary, {"casual/blue": [self.raises(common.ForgeError("Forge doesn't know X."))],
                                       "casual/red": [self.raises(common.Stopped("stopped"))]})
        self.assertEqual(self.dropped(summary), {"casual/blue": None, "casual/red": None})

    def test_a_drop_stands_when_the_stage_finishes(self):
        state = self.state()
        summary = self.summary(state)
        self.play(state, summary, {"casual/blue": [self.raises(common.ForgeError("Forge doesn't know X."))],
                                   "casual/red": [None]})
        found = self.dropped(summary)
        self.assertIsNone(found["casual/red"])
        self.assertEqual(found["casual/blue"], "couldn't be played: Forge doesn't know X.")

    def test_busy_is_tried_again_after_a_wait(self):
        busy = self.raises(common.ForgeError(runner.BUSY))
        with mock.patch.object(variants, "BUSY_WAITS_S", (0.01, 0.01, 0.01)):
            state = self.state(inflight=2)
            summary = self.summary(state)
            calls = self.play(state, summary, {"casual/blue": [busy, None], "casual/red": [None]})
            self.assertEqual(calls.count("casual/blue"), 2)
            self.assertIsNone(self.dropped(summary)["casual/blue"])
            state = self.state()
            summary = self.summary(state)
            calls = self.play(state, summary, {"casual/blue": [busy], "casual/red": [None]})
            self.assertEqual(calls.count("casual/blue"), 4)
            self.assertEqual(self.dropped(summary)["casual/blue"], f"couldn't be played: {runner.BUSY}")

    def test_a_stop_during_a_busy_wait_stops_the_test(self):
        def outer(done, total, detail):
            raise common.Stopped("stopped")
        state = self.state(outer=outer)
        summary = self.summary(state)
        with self.assertRaises(common.Stopped):
            self.play(state, summary, {"casual/blue": [self.raises(common.ForgeError(runner.BUSY))],
                                       "casual/red": [None]})
        self.assertIsNone(self.dropped(summary)["casual/blue"])

    def test_a_mirror_takes_the_runs_side_order(self):
        variant = variants.variant_entry(self.base, self.cards)
        mirror = dict(variant, id="casual/other")
        with mock.patch.object(runner, "_ordered", lambda a, b, eng: [b, a], create=True):
            self.assertEqual(variants._variant_index(variant, mirror), 1)
        with mock.patch.object(runner, "_ordered", lambda a, b, eng: [a, b], create=True):
            self.assertEqual(variants._variant_index(variant, mirror), 0)


@unittest.skipUnless(seqstats_built(), "needs seqstats' paired functions (package S)")
class CoordinatorTests(CoordinatorCase):

    def test_a_quick_test_tops_up_the_base_then_pairs_its_numbers(self):
        summary = self.run_test()
        base_call, paired_call = self.runs.calls
        self.assertEqual((base_call["kind"], base_call["games"], base_call["numbers"]), (None, 200, None))
        self.assertEqual(paired_call["kind"], "paired")
        self.assertEqual(paired_call["numbers"], list(range(200)))
        record = summary["opponents"][0]
        base = forge.load(record["base_key"], self.tmp)
        beta = [s["card_sha"] for s in base["sides"]].index(self.base["card_sha"])
        variant = variants.variant_entry(self.base, self.cards)
        nu = 0 if variant["card_sha"] < self.red["card_sha"] else 1
        self.assertEqual(paired_call["seeds"], {"base": base["seeds"]["base"], "stream": base["seeds"]["stream"],
                                                "flip": variants.paired_flip(base["seeds"]["flip"], beta, nu)})
        self.assertEqual(record["paired_key"], variants.paired_key(record["base_key"], beta, variant["card_sha"],
                                                                   variant["dck_sha"]))
        paired = variants.load_paired(record["paired_key"], self.tmp)
        self.assertEqual(paired["paired"]["base_key"], record["base_key"])
        self.assertEqual(paired["kind"], "paired")
        # The flip puts the variant in the base's seat: every game pairs, none with another starter.
        self.assertEqual(summary["starter_mismatch"]["games"], 0)
        self.assertEqual(len(summary["looks"]), 1)
        look = summary["looks"][0]
        self.assertEqual((look["games_per_opponent"], look["interim"], look["stopped"]), (200, False, False))
        self.assertIn(summary["outcome"], seqstats.PAIRED_VERDICTS)
        self.assertEqual(summary["margin"], 0.03)
        self.assertTrue((self.tmp / "paired" / "tests" / f"{summary['test']}.json").exists())
        # Shock wins a third of the variant's games: the change is better.
        self.assertGreater(look["delta"], 0)
        # Played again: nothing more to play.
        again = self.run_test()
        self.assertEqual(len(self.runs.calls), 2)
        self.assertEqual(again["test"], summary["test"])

    def test_existing_base_games_are_reused(self):
        self.runs(self.base, self.red, 300, by="Matt")
        self.runs.calls.clear()
        self.run_test()
        (paired_call,) = self.runs.calls
        self.assertEqual(paired_call["numbers"], list(range(200)))

    def test_a_stopped_test_fills_its_holes(self):
        self.runs(self.base, self.red, 200, by="Matt")
        self.runs.stop_after = 60
        with self.assertRaises(common.Stopped):
            self.run_test()
        summary = variants.load_summary(variants.test_id(self.base, variants.variant_entry(self.base, self.cards),
                                                         self.red, "quick"), self.tmp)
        self.assertEqual(summary["outcome"], "stopped")
        self.assertTrue(summary["looks"][-1]["stopped"])
        self.runs.calls.clear()
        summary = self.run_test()
        (paired_call,) = self.runs.calls
        self.assertEqual(paired_call["numbers"], list(range(60, 200)))
        self.assertIn(summary["outcome"], seqstats.PAIRED_VERDICTS)
        self.assertEqual(summary["looks"][-1]["games_per_opponent"], 200)

    def test_play_more_makes_earlier_looks_interim(self):
        summary = self.run_test()
        self.runs.calls.clear()
        more = variants.run_test(self.base, self.cards, self.red, "quick", by="User1", results_dir=self.tmp,
                                 extend=summary["test"])
        self.assertEqual(more["test"], summary["test"])
        self.assertEqual(more["mode"], "ahead")
        self.assertEqual(more["created_mode"], "quick")
        self.assertTrue(more["looks"][0]["interim"])
        self.assertEqual(more["looks"][0]["bound"], seqstats.HP_INTERIM)
        self.assertGreaterEqual(more["looks"][1]["games_per_opponent"], 400)
        self.assertEqual(self.runs.calls[0]["games"], 200)          # the base to 400
        self.assertEqual(self.runs.calls[1]["numbers"], list(range(200, 400)))

    def test_the_field_drops_an_opponent_that_cant_be_played(self):
        self.runs.fail[self.blue["card_sha"]] = "Forge doesn't know this card, so the matchup can't be played: X."
        with mock.patch.object(forge.field, "opponents", return_value=[self.red, self.blue]):
            summary = self.run_test("field")
        self.assertEqual(summary["against"], "field:Constructed")
        self.assertEqual(summary["margin"], 0.02)
        dropped = {r["id"]: r["dropped"] for r in summary["opponents"]}
        self.assertIsNone(dropped["casual/red"])
        self.assertTrue(dropped["casual/blue"].startswith("couldn't be played: Forge doesn't know"))
        view = variants.view(summary["test"], self.tmp)
        self.assertEqual(len(view["opponents"]), 2)
        self.assertIsNotNone(view["field"])
        self.assertTrue(view["words"])

    def test_a_key_change_stops_the_test(self):
        summary = self.run_test(mode=200)
        self.assertEqual(summary["looks"][-1]["games_per_opponent"], 200)
        self.runs.keys[tuple(sorted((self.base["card_sha"], self.red["card_sha"])))] = "e" * 64
        self.runs.calls.clear()
        with self.assertRaises(common.ForgeError) as caught:
            variants.run_test(self.base, self.cards, self.red, 200, by="Matt", results_dir=self.tmp,
                              extend=summary["test"])
        self.assertEqual(str(caught.exception), variants.ENGINE_CHANGED_MORE)
        self.assertEqual(self.runs.calls, [])       # refused before any game

    def test_the_list_changing_stops_play_more(self):
        summary = self.run_test()
        other = entry(GREEN.replace("2 Giant Growth", "1 Giant Growth\n1 Shock"), "casual/green", title="Green")
        with self.assertRaises(common.ForgeError) as caught:
            variants.run_test(other, self.cards, self.red, "quick", by="Matt", results_dir=self.tmp,
                              extend=summary["test"])
        self.assertEqual(str(caught.exception), variants.LIST_CHANGED)

    def test_progress_has_the_pairs(self):
        seen = []
        self.run_test(progress=lambda done, total, detail: seen.append((done, total, detail)))
        done, total, detail = seen[-1]
        self.assertEqual((done, total), (400, 400))
        self.assertEqual(detail["games_per_opponent"], 200)
        self.assertEqual(len(detail["pairs"]), 2)        # the base top-up's and the paired run's
        self.assertTrue(all(p["opponent"]["id"] == "casual/red" for p in detail["pairs"].values()))

    def test_tests_for_and_words(self):
        summary = self.run_test()
        listed = variants.tests_for("casual/green", "target", self.tmp)
        self.assertEqual([s["test"] for s in listed], [summary["test"]])
        self.assertEqual(variants.tests_for("casual/green", "owned", self.tmp), [])
        words = variants.verdict_words(summary)
        self.assertTrue(words.startswith(("Better against Red", "Not settled", "Makes little", "A little")), words)


@unittest.skipUnless(seqstats_built(), "needs seqstats' paired functions (package S)")
class CommandLineTests(CoordinatorCase):

    def dck(self, name, text):
        path = self.tmp / f"{name}.dck"
        entry_ = entry(text, f"casual/{name}")
        path.write_text(entry_["dck"].replace(f"Name={entry_['card_sha'][:12]}", f"Name={name}"), encoding="utf-8")
        return str(path)

    def main(self, *argv):
        """(exit code, stdout, stderr) of the command line."""
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = forge.cli.main(list(argv))
            out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def test_remove_and_add_against_one_deck(self):
        green, red = self.dck("green", GREEN), self.dck("red", RED)
        code, out, err = self.main("variant", green, "--remove", "1 Fiery Annihilation", "--add", "1 Shock",
                                   "--against", red, "--games", "200", "--results-dir", str(self.tmp))
        self.assertEqual(code, 0, err)
        self.assertIn("Testing -1 Fiery Annihilation, +1 Shock in green", err)
        self.assertIn("paired games", out)
        self.assertRegex(out, r"test [0-9a-f]{64}")
        self.assertEqual([c["kind"] for c in self.runs.calls], [None, "paired"])

    def test_a_list_file_and_json(self):
        green, red = self.dck("green", GREEN), self.dck("red", RED)
        listed = self.tmp / "variant-1.txt"
        listed.write_text(GREEN.replace("1 Fiery Annihilation", "1 Shock"), encoding="utf-8")
        code, out, err = self.main("variant", green, "--list", str(listed), "--against", red, "--quick", "--json",
                                   "--results-dir", str(self.tmp))
        self.assertEqual(code, 0, err)
        found = json.loads(out)
        self.assertEqual(found["test"]["mode"], "quick")
        self.assertIn("rho", found["opponents"][0]["paired"])
        self.assertEqual(found["test"]["variant"]["changes"]["add"], [[1, "Shock"]])

    def test_mistakes(self):
        green, red = self.dck("green", GREEN), self.dck("red", RED)
        for argv, words in ((["variant", green, "--add", "1 Shock", "--against", red], "keep the deck's size"),
                            (["variant", green, "--remove", "1 Fiery Annihilation", "--add", "1 Shock"],
                             "Say what to test against"),
                            (["variant", green, "--remove", "5 Overrun", "--add", "5 Shock", "--against", red],
                             "can't come out"),
                            (["variant", green, "--remove", "1 Fiery Annihilation", "--add", "1 Shock", "--against",
                              red, "--quick", "--games", "200"], "Choose one of")):
            code, out, err = self.main(*argv)
            self.assertEqual(code, 1, (argv, out, err))
            self.assertIn(words, err)


class WordsTests(unittest.TestCase):

    def summary(self, decision, delta=0.024, low=0.006, high=0.042, against="field:Constructed", outcome=None):
        return {"against": against, "margin": 0.02, "outcome": outcome or decision,
                "looks": [{"games_per_opponent": 400, "delta": delta, "low": low, "high": high,
                           "decision": decision}]}

    def test_words(self):
        self.assertEqual(variants.verdict_words(self.summary("better")),
                         "Better against the field: +2.4 points of win rate (+0.6 to +4.2)")
        self.assertEqual(variants.verdict_words(self.summary("worse", -0.024, -0.042, -0.006)),
                         "Worse against the field: −2.4 points of win rate (−4.2 to −0.6)")
        self.assertEqual(variants.verdict_words(self.summary("little_difference")),
                         "Makes little difference: within 2 points of win rate")
        self.assertEqual(variants.verdict_words(self.summary("not_settled")), "Not settled yet after 400 games a deck")
        self.assertEqual(variants.verdict_words(self.summary("continue", outcome="stopped")),
                         "Stopped early: the result shows the games played so far")
        one = self.summary("better", against={"id": "casual/red", "version": "target", "card_sha": "r", "title": "Red"})
        self.assertTrue(variants.verdict_words(one).startswith("Better against Red:"))
        self.assertIsNone(variants.verdict_words({"against": "field:Constructed", "looks": [], "outcome": None}))


# ============================================================ with the fake Forge (needs R's hooks)

@unittest.skipUnless(runner.RUN_FEATURES >= {"numbers", "seeds", "kind"} and seqstats_built(),
                     "needs runner.run's wave 3 keywords (package R) and seqstats (package S)")
class FakeForgeTests(test_forge.ForgeCase):
    """A real paired run through runner.run and the fake Forge's v2 mode, with the card log said
    to be ready and deck-order-1 among its game patches: the fake builds each library in .dck line
    order, so an aligned variant draws the same cards until its changed slot."""

    @classmethod
    def setUpClass(cls):
        test_forge.setUpModule()

    @classmethod
    def tearDownClass(cls):
        test_forge.tearDownModule()

    def setUp(self):
        super().setUp()
        log = dict(test_forge.CARD_LOG, game_patches=["attack-requirements-in-order-1", "deck-order-1"])
        for p in (mock.patch.object(forge.simjar, "card_log", side_effect=lambda *a, **k: dict(log)),
                  mock.patch.object(forge.simjar, "readiness", return_value={"ready": True, "problem": None}),
                  mock.patch.object(forge.engine, "_jar_patches", return_value=list(log["game_patches"]))):
            p.start()
            self.addCleanup(p.stop)
        self.settings["forge_workers"] = 2

    def test_a_quick_test_with_cardwins(self):
        base = entry(GREEN, "casual/green", title="Green")
        red = entry(RED, "casual/red", title="Red")
        cards = changed(GREEN, [(1, "Fiery Annihilation")], [(1, "Overrun")])
        with mock.patch.dict("os.environ", {"FAKE_FORGE": "cardwins=Overrun"}):
            summary = variants.run_test(base, cards, red, 50, by="Matt", results_dir=self.results)
        record = summary["opponents"][0]
        self.assertIsNone(record["dropped"])
        paired = variants.load_paired(record["paired_key"], self.results)
        self.assertEqual(len(forge.views._games(paired)), 50)
        self.assertEqual(summary["starter_mismatch"]["games"], 0)
        view = variants.view(summary["test"], self.results)
        paired_numbers = view["opponents"][0]["paired"]
        # Aligned, the two versions draw the same cards until the changed slot: most games play out the
        # same, the arms are correlated, and the third Overrun (cardwins) only ever helps.
        self.assertGreaterEqual(paired_numbers["same"], 0.5)
        self.assertGreater(paired_numbers["rho"], 0.2)
        self.assertGreater(paired_numbers["delta"], 0)
        self.assertEqual(paired["kind"], "paired")
        self.assertEqual(paired["seeds"]["stream"], forge.load(record["base_key"], self.results)["seeds"]["stream"])


if __name__ == "__main__":
    unittest.main()
