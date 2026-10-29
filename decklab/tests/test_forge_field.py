"""Tests for the field view (simulation wave 3's R13, forge-trial/sim-wave3-contract.md section
10): decklab.lib.forge.field's membership rules, opponents, budgets and plans, the field run
(floor, APT order, the BUSY retry, a dropped opponent, a key change, Stop, the progress detail and
the note) and the view's numbers; and the command line's field --show and --dry-run.

They run on a small magic/ tree in a temp folder (decks.DECKS_DIR points at it, and its inventory is installed),
with runner.run, lists.matchup_key and saved.load replaced by a FakeField that keeps results in
memory, so no Forge process starts. Until package S's seqstats is built, the few statistics a
field run needs (decided_share, apt_pick, field_row, field_average) are stand-ins written from
section 7.5; once it is, the real ones run and the same expectations hold.

Run from the repo root: python scripts/test_fixtures.py
"""
import copy
import hashlib
import io
import json
import math
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import decks, inventory, jobs
from decklab.lib.inventory.files import FileInventory
from decklab.lib.forge import cli, common, engine, estimate, field, lists, pilots, runner, saved, seqstats, views

DECK = """# {title}
- **Format:** Casual 60-card, 1v1
- **Played by:** either
- **Status:** {status}
{extra}
## Decklist

```
Deck
{cards}
```
{owned}"""

OWNED = """
## Substitutes

### Owned-only version

```
Deck
4 Forest
4 {card}
```
"""

COMMANDER = """# {title}
- **Format:** Commander (100 cards)
- **Played by:** either
- **Status:** building

## Decklist

```
Commander
1 {commander}

Deck
1 Sol Ring
```
"""

PRODUCT = "section,name,set,collector_number,finish,quantity\n{rows}"
STATUS = ("file,status,intact,notes\n"
          "aggro.csv,owned,yes,kept whole\n"
          "blank.csv,preordered,,due soon\n"
          "broken-up.csv,owned,no,in the pool\n"
          "precon.csv,preordered,yes,\n"
          "fdn-beginner-box.csv,owned,yes,\n")
BOX = ("deck,section,name,set,collector_number,finish,quantity\n"
       "Cats,deck,Savannah Lions,fdn,1,nonfoil,2\n"
       "Elves,deck,Llanowar Elves,fdn,2,nonfoil,2\n")


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _built():
    """True once package S has built seqstats (the stand-ins are used until then)."""
    try:
        seqstats.apt_pick([], 1)
        return True
    except NotImplementedError:
        return False


# ------------------------------------------------------------ stand-ins for seqstats (section 7.5)

def _decided_share(games, p):
    a, b = [0, 0], [0, 0]
    for g in games:
        s = 0 if g["first"] == p else 1
        if g["w"] == p:
            a[s] += 1
        elif g["w"] is not None:
            b[s] += 1
    d = [a[0] + b[0], a[1] + b[1]]
    if not all(d):
        return {"pi": None, "se": None, "z": None, "a": a, "b": b, "d": d}
    pi = (a[0] / d[0] + a[1] / d[1]) / 2
    t = [(a[i] + 0.5) / (d[i] + 1) for i in (0, 1)]
    se = math.sqrt(sum(t[i] * (1 - t[i]) / d[i] for i in (0, 1))) / 2
    return {"pi": pi, "se": se, "z": (pi - 0.5) / se, "a": a, "b": b, "d": d}


def _apt_pick(rows, k):
    eligible = [r for r in rows if r["n"] < 1600 and not r["inflight"] and r["meaningful"]]
    score = lambda r: math.sqrt(r["n"]) * (abs((0.5 if r["pi"] is None else r["pi"]) - 0.5) + 0.05)
    return [r["id"] for r in sorted(eligible, key=lambda r: (score(r), r["n"], r["id"]))[:k]]


def _field_row(games, p):
    play = [g for g in games if g["first"] == p]
    draw = [g for g in games if g["first"] != p]
    found = views.balanced(sum(g["w"] == p for g in play), len(play), sum(g["w"] == p for g in draw), len(draw))
    share = _decided_share(games, p)
    value, low, high = found if found else (None, None, None)
    return {"n": len(games), "value": value, "low": low, "high": high, "pi": share["pi"], "se": share["se"],
            "d": sum(share["d"])}


def _field_average(rows, of=None):
    counted = [r for r in rows if r.get("value") is not None]
    if not counted:
        return None
    m = len(counted)
    value = sum(r["value"] for r in counted) / m
    return {"value": value, "low": value - math.sqrt(sum((r["value"] - r["low"]) ** 2 for r in counted)) / m,
            "high": value + math.sqrt(sum((r["high"] - r["value"]) ** 2 for r in counted)) / m, "counted": m,
            "of": of if of is not None else len(rows), "partial": m < (of if of is not None else len(rows)),
            "se_wald": None}


class FakeField:
    """runner.run, lists.matchup_key and saved.load over results kept in memory. Deck D (entry_a)
    wins its games against an opponent at the share self.rates[opponent id] (0.5 when not set),
    in a fixed pattern; the starter alternates. Results are saved as a v2 run saves them: each run
    adds a run record and a batch with that run's ordinal as "n". self.calls lists (opponent id,
    games, kwargs) in the order runs started, and self.starts (opponent id, runs then playing).
    self.busy[opponent id] runs raise runner.BUSY first; self.busy_at[id] is a set of that pair's
    call numbers (1 for its first) that raise it; self.fail[id] is a ForgeError sentence;
    self.rekey[id] is a key a later run of that pair is saved under, self.saved_as[id] a key every
    run of it is saved under; self.page[id] games are added (as the page's own run) before each of
    that pair's runs; self.delay[id] is seconds each quarter of that pair's runs takes."""

    def __init__(self):
        self.store, self.calls, self.starts, self.rates = {}, [], [], {}
        self.busy, self.busy_at, self.fail, self.rekey, self.saved_as, self.page = {}, {}, {}, {}, {}, {}
        self.delay = {}
        self.active = 0
        self.lock = threading.Lock()

    @staticmethod
    def key(a, b):
        return hashlib.sha256("|".join(sorted([a["card_sha"], b["card_sha"]])).encode()).hexdigest()

    def result(self, a, b, key=None):
        key = key or self.key(a, b)
        if key not in self.store:
            pair = sorted([a, b], key=lambda e: e["card_sha"])
            self.store[key] = {"key": key, "format": lists.fmt_for(a["kind"]),
                               "sides": [{"card_sha": e["card_sha"], "kind": e["kind"], "engine_id": "id-" + e["id"],
                                          "seen_as": [{"id": e["id"], "version": e["version"], "title": e["title"]}]}
                                         for e in pair],
                               "seeds": {"stream": "0" * 16}, "batches": [], "runs": []}
        return self.store[key]

    def new_run(self, stored):
        """A new run record of stored and its batch (empty)."""
        ordinal = len(stored["runs"])
        stored["runs"].append({"played": 0})
        batch = {"n": ordinal, "first": 0, "games": []}
        stored["batches"].append(batch)
        return batch

    def add_games(self, a, b, n, rate=None, key=None, batch=None):
        """n more games of a against b (a wins at rate), as a run would save them: in batch, or
        as a run of their own."""
        stored = self.result(a, b, key)
        if batch is None:
            batch = self.new_run(stored)
        p = 0 if stored["sides"][0]["card_sha"] == a["card_sha"] else 1
        rate = self.rates.get(b["id"], 0.5) if rate is None else rate
        for _ in range(n):
            g = sum(len(x["games"]) for x in stored["batches"])
            won = (g * 37 % 100) < rate * 100
            batch["games"].append({"g": g, "w": p if won else 1 - p, "first": g % 2, "r": "win"})
        stored["runs"][batch["n"]]["played"] += n
        return stored

    def run(self, entry_a, entry_b, games, *, by, progress=None, results_dir=None, pool=None, exact=False,
            seed_base=None, **kwargs):
        with self.lock:
            self.calls.append((entry_b["id"], games, dict(exact=exact, seed_base=seed_base, by=by, **kwargs)))
            self.starts.append((entry_b["id"], self.active))
            ran = sum(1 for c in self.calls if c[0] == entry_b["id"])
            if self.busy.get(entry_b["id"]) or ran in self.busy_at.get(entry_b["id"], ()):
                if self.busy.get(entry_b["id"]):
                    self.busy[entry_b["id"]] -= 1
                raise common.ForgeError(runner.BUSY)
            if entry_b["id"] in self.fail:
                raise common.ForgeError(self.fail[entry_b["id"]])
            key = self.saved_as.get(entry_b["id"]) or (self.rekey.get(entry_b["id"]) if ran > 1 else None)
            if self.page.get(entry_b["id"]):
                self.add_games(entry_a, entry_b, self.page[entry_b["id"]], key=key)
            batch = self.new_run(self.result(entry_a, entry_b, key))
            self.active += 1
        step = max(1, games // 4)
        done = 0
        try:
            while done < games:
                n = min(step, games - done)
                if self.delay.get(entry_b["id"]):
                    time.sleep(self.delay[entry_b["id"]])
                with self.lock:
                    self.add_games(entry_a, entry_b, n, key=key, batch=batch)
                done += n
                if progress is not None:
                    progress(done, games, {"wins": [done // 2, done - done // 2], "other": 0})
        except common.STOPS as e:
            e.saved_games = done
            raise
        finally:
            with self.lock:
                self.active -= 1
        with self.lock:
            return copy.deepcopy(self.result(entry_a, entry_b, key))

    def load(self, key, results_dir=None):
        with self.lock:
            found = self.store.get(key)
            return copy.deepcopy(found) if found is not None else None

    def stored(self, results_dir=None):
        with self.lock:
            return [copy.deepcopy(r) for r in self.store.values()]


class FieldTestCase(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        magic = self.root / "magic"
        _write(magic / "decks" / "casual" / "alpha.md", DECK.format(
            title="Alpha", status="building", extra="", cards="4 Savannah Lions\n20 Plains", owned=""))
        _write(magic / "decks" / "casual" / "beta.md", DECK.format(
            title="Beta", status="built", extra="- **Built version:** owned-only",
            cards="4 Llanowar Elves\n20 Forest", owned=OWNED.format(card="Elvish Mystic")))
        _write(magic / "decks" / "casual" / "gamma.md", DECK.format(
            title="Gamma", status="built", extra="", cards="4 Opt\n20 Island", owned=OWNED.format(card="Opt")))
        _write(magic / "decks" / "casual" / "broken.md", "# Broken\n\nNo decklist here.\n")
        _write(magic / "decks" / "commander" / "cmdr.md", COMMANDER.format(title="Cmdr", commander="Giada, Font of Hope"))
        products = magic / "products"
        _write(products / "aggro.csv", PRODUCT.format(rows="deck,Lightning Bolt,fdn,1,nonfoil,4\ndeck,Mountain,fdn,2,nonfoil,20\n"))
        _write(products / "blank.csv", PRODUCT.format(rows="deck,Shock,fdn,3,nonfoil,4\n"))
        _write(products / "broken-up.csv", PRODUCT.format(rows="deck,Duress,fdn,4,nonfoil,4\n"))
        _write(products / "precon.csv", PRODUCT.format(rows="commander,Gisa's Bidding,fdn,5,nonfoil,1\n"
                                                           "deck,Sol Ring,fdn,6,nonfoil,1\n"))
        _write(products / "fdn-beginner-box.csv", BOX)
        _write(products / "status.csv", STATUS)
        self.simulation = self.root / "simulation.json"
        self.results = self.root / "results"
        self.results.mkdir()
        self.fake = FakeField()
        self.logs = []
        # The product decks and their statuses are this tree's inventory (decklab/lib/inventory).
        self.addCleanup(inventory.use(FileInventory(self.root)))
        patches = [(decks, "DECKS_DIR", magic / "decks"),
                   (pilots, "SIMULATION_FILE", self.simulation), (lists, "_source", lambda *a, **k: None),
                   (lists, "matchup_key", self.fake.key), (saved, "load", self.fake.load),
                   (saved, "_stored", self.fake.stored), (runner, "run", self.fake.run),
                   (common, "_log", self.logs.append), (field, "LOOP_S", 0.01)]
        if not _built():
            patches += [(seqstats, "decided_share", _decided_share), (seqstats, "apt_pick", _apt_pick),
                        (seqstats, "field_row", _field_row), (seqstats, "field_average", _field_average)]
        for target, name, value in patches:
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def entry(self, deck_id, version="target"):
        summary = decks.find_summary(deck_id)
        return lists.entry(summary["id"], version, summary["title"], decks.engine_kind(summary),
                           decks.load_deck(summary["id"], version))

    def names(self, entries):
        return [f"{e['id']}@{e['version']}" for e in entries]

    def play(self, deck_id="casual/alpha", budget="quick", **kwargs):
        kwargs.setdefault("inflight", 1)
        return field.run_field(self.entry(deck_id), budget, by="Matt", results_dir=self.results, pool=object(),
                               **kwargs)


class MembershipTests(FieldTestCase):

    def test_house_decks_and_intact_products(self):
        # Built with a Built version line: that list; otherwise the target list. A product counts when
        # owned, preordered or ordered and kept intact; a blank intact is "not decided yet".
        # Sorted by title ("Aggro" is the product file's name, title-cased).
        self.assertEqual(self.names(field.field_lists("Constructed")),
                         ["product/aggro@target", "casual/alpha@target", "casual/beta@owned", "casual/gamma@target"])
        self.assertEqual(self.names(field.field_lists("Commander")), ["commander/cmdr@target", "product/precon@target"])
        notes = field.field_notes("Constructed")
        self.assertEqual(len(notes), 1)
        self.assertIn("broken", notes[0].casefold())
        self.assertNotIn("Commander", " ".join(field.field_notes("Commander")))

    def test_simulation_json_adds_and_removes(self):
        _write(self.simulation, json.dumps({"version": 1, "field": {
            "Constructed": {"add": ["product/blank", "pairing/cats+elves", "commander/cmdr"], "remove": ["casual/alpha"]},
            "Commander": {"add": [], "remove": ["product/precon@target"]}}}))
        found = set(self.names(field.field_lists("Constructed")))
        self.assertEqual(found, {"casual/beta@owned", "casual/gamma@target", "product/aggro@target",
                                 "product/blank@target", "pairing/cats+elves@target"})
        self.assertIn("isn't a Constructed deck", " ".join(field.field_notes("Constructed")))
        self.assertEqual(self.names(field.field_lists("Commander")), ["commander/cmdr@target"])

    def test_a_bad_simulation_json_leaves_the_field_alone(self):
        _write(self.simulation, "{not json")
        self.assertEqual(len(field.field_lists("Constructed")), 4)
        self.assertTrue(any("simulation.json" in line for line in self.logs))

    def test_opponents_leave_out_every_list_of_the_deck(self):
        owned_beta = self.entry("casual/beta", "owned")
        target_beta = self.entry("casual/beta", "target")
        for entry in (owned_beta, target_beta):
            self.assertEqual(self.names(field.opponents(entry)),
                             ["product/aggro@target", "casual/alpha@target", "casual/gamma@target"])
        # Any list can be assessed: a product deck not in the field, or a Beginner Box pairing.
        self.assertEqual(len(field.opponents(self.entry("product/blank"))), 4)
        self.assertEqual(self.names(field.opponents(target_beta, ["product/aggro", "casual/gamma@target"])),
                         ["product/aggro@target", "casual/gamma@target"])
        with self.assertRaisesRegex(ValueError, "casual/nope"):
            field.opponents(target_beta, ["casual/nope"])
        with self.assertRaisesRegex(ValueError, "casual/gamma@owned"):
            field.opponents(target_beta, ["casual/gamma@owned"])


class BudgetTests(FieldTestCase):

    def test_budgets(self):
        self.assertEqual(field._budget("quick"), (200, None, False))
        self.assertEqual(field._budget("standard"), (200, 400, False))
        self.assertEqual(field._budget("thorough"), (200, 800, False))
        self.assertEqual(field._budget("fixed:300"), (300, None, True))
        self.assertEqual(field._budget(50), (50, 50, False))
        self.assertEqual(field._budget("2000"), (200, 1600, False))
        for bad in ("lots", "fixed:0", 0, -5, True, None, "fixed:x"):
            with self.subTest(budget=bad), self.assertRaises(ValueError):
                field._budget(bad)

    def test_plan_counts_saved_games(self):
        a = self.entry("casual/alpha")
        self.fake.add_games(a, self.entry("casual/gamma"), 150)
        planned = field.plan(a, "standard")
        floors = {p["opponent"]["id"]: p["floor"] for p in planned["pairs"]}
        self.assertEqual(floors, {"casual/beta": 200, "casual/gamma": 50, "product/aggro": 200})
        self.assertEqual(planned["allocate"], 3 * 400 - 600)
        self.assertEqual(planned["new_games"], 450 + 600)
        self.assertEqual(planned["per_opponent"], 400)
        self.assertEqual(field.plan(a, "quick")["new_games"], 450)


class RunTests(FieldTestCase):

    def test_the_floor_reuses_saved_games(self):
        a = self.entry("casual/alpha")
        self.fake.add_games(a, self.entry("casual/gamma"), 150)
        note = self.play()
        self.assertEqual(sorted((c[0], c[1]) for c in self.fake.calls),
                         [("casual/beta", 200), ("casual/gamma", 50), ("product/aggro", 200)])
        self.assertTrue(all(c[2]["exact"] for c in self.fake.calls))
        self.assertEqual((note["played"], note["planned"], note["stopped"], note["budget"]), (450, 450, False, "quick"))
        self.assertEqual(sorted(note["per_opponent"].values()), [50, 200, 200])
        # The note is appended in the results folder, and the view finds it.
        path = self.results / "field" / f"{a['card_sha']}-Constructed-home.json"
        self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["runs"]), 1)
        self.play()
        self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["runs"]), 2)
        self.assertEqual(field.last_note(a, self.results)["played"], 0)

    def test_apt_gives_the_closest_matchup_the_next_games(self):
        self.fake.rates = {"casual/beta": 0.5, "casual/gamma": 0.85, "product/aggro": 0.95}
        note = self.play(budget="standard")
        floor, rest = self.fake.calls[:3], self.fake.calls[3:]
        self.assertEqual(sorted(c[1] for c in floor), [200, 200, 200])
        self.assertEqual(rest[0][0], "casual/beta")
        self.assertTrue(all(c[1] == seqstats.FIELD_STEP for c in rest))
        self.assertEqual(note["played"], 3 * 400)
        given = {}
        for name, games, _ in self.fake.calls:
            given[name] = given.get(name, 0) + games
        self.assertGreater(given["casual/beta"], given["product/aggro"])

    def test_a_busy_pair_is_tried_again_once_after_the_others(self):
        self.fake.busy = {"casual/beta": 1}
        note = self.play()
        self.assertEqual([c[0] for c in self.fake.calls],
                         ["product/aggro", "casual/beta", "casual/gamma", "casual/beta"])
        self.assertEqual((note["played"], note["dropped"]), (600, {}))
        # With room for two at once, the floor's retry still waits for the other pairs to finish.
        self.fake.calls.clear()
        self.fake.starts.clear()
        self.fake.busy = {"product/aggro": 1}
        self.fake.delay = {"casual/gamma": 0.05}
        note = self.play(deck_id="casual/beta", inflight=2)
        self.assertEqual(note["dropped"], {})
        aggro = [i for i, (name, _) in enumerate(self.fake.starts) if name == "product/aggro"]
        self.assertEqual(len(aggro), 2)
        self.assertEqual(self.fake.starts[aggro[1]][1], 0)
        self.assertEqual(aggro[1], len(self.fake.starts) - 1)
        # Twice busy: left out, with the reason.
        self.fake.calls.clear()
        self.fake.busy = {"product/aggro": 2}
        note = self.play(deck_id="casual/gamma")
        self.assertEqual(list(note["dropped"].values()), [f"couldn't be played: {field.BUSY_TWICE}"])

    def test_a_busy_pick_waits_until_the_other_picks_are_played(self):
        # Beta is the closest matchup, so APT's first pick is beta's: it's BUSY then, and its
        # retry comes once the other picks are played, with one pick's games kept for it.
        self.fake.rates = {"casual/beta": 0.5, "casual/gamma": 0.85, "product/aggro": 0.95}
        self.fake.busy_at = {"casual/beta": {2}}
        self.fake.delay = {"casual/gamma": 0.02, "product/aggro": 0.02}
        note = self.play(budget="standard", inflight=2)
        self.assertEqual(note["dropped"], {})
        self.assertEqual(note["played"], 3 * 400)
        beta = [i for i, (name, _) in enumerate(self.fake.starts) if name == "casual/beta"]
        busy, retry = beta[1], beta[2]
        self.assertGreater(retry, busy + 1)
        self.assertTrue(all(name != "casual/beta" for name, _ in self.fake.starts[busy + 1:retry]))
        self.assertEqual(self.fake.starts[retry][1], 0)
        self.assertEqual(self.fake.calls[retry][1], seqstats.FIELD_STEP)

    def test_only_the_runs_own_games_are_counted(self):
        a, beta = self.entry("casual/alpha"), self.entry("casual/beta", "owned")
        # Games saved under the key the first run comes back with, and games the page plays
        # between the field's pair runs, aren't the field run's.
        self.fake.saved_as = {"casual/beta": "e" * 64}
        self.fake.add_games(a, beta, 100, key="e" * 64)
        self.fake.page = {"casual/gamma": 30}
        seen = []
        note = self.play(budget="standard", opponents=["casual/beta", "casual/gamma"],
                         progress=lambda done, total, detail: seen.append((done, copy.deepcopy(detail))))
        asked = {}
        for name, games, _ in self.fake.calls:
            asked[name] = asked.get(name, 0) + games
        self.assertEqual(note["played"], sum(asked.values()))
        by_key = {"e" * 64: "casual/beta", self.fake.key(a, self.entry("casual/gamma")): "casual/gamma"}
        self.assertEqual({by_key[k]: n for k, n in note["per_opponent"].items()}, asked)
        done, detail = seen[-1]
        self.assertEqual(done, note["played"])
        for key, pair in detail["pairs"].items():
            self.assertEqual(pair["done"], asked[by_key[key]])
            self.assertLessEqual(pair["wins"] + pair["other"], pair["done"])

    def test_a_forge_error_drops_that_opponent(self):
        self.fake.fail = {"casual/gamma": "Forge doesn't know this card, so the matchup can't be played: Opt."}
        note = self.play(budget="standard")
        self.assertEqual(list(note["dropped"].values()),
                         ["couldn't be played: Forge doesn't know this card, so the matchup can't be played: Opt."])
        self.assertEqual([c[0] for c in self.fake.calls].count("casual/gamma"), 1)
        self.assertEqual(note["played"], 2 * 400)

    def test_another_key_stops_the_run(self):
        self.fake.rekey = {"casual/beta": "f" * 64}
        with self.assertRaisesRegex(common.ForgeError, "The engine changed during this run"):
            self.play(budget="standard", opponents=["casual/beta"])
        note = field.last_note(self.entry("casual/alpha"), self.results)
        self.assertEqual(note["error"], field.ENGINE_CHANGED)

    def test_the_progress_detail(self):
        seen = []
        self.play(progress=lambda done, total, detail: seen.append((done, total, copy.deepcopy(detail))))
        done, total, detail = seen[-1]
        self.assertEqual((done, total), (600, 600))
        self.assertEqual(set(detail), {"budget", "phase", "deck", "pairs"})
        self.assertEqual(detail["deck"], {"id": "casual/alpha", "version": "target", "title": "Alpha"})
        self.assertEqual(detail["budget"], "quick")
        self.assertEqual(len(detail["pairs"]), 3)
        for key, pair in detail["pairs"].items():
            self.assertRegex(key, "^[0-9a-f]{64}$")
            self.assertEqual(set(pair), {"opponent", "done", "total", "wins", "other", "playing"})
            self.assertEqual(set(pair["opponent"]), {"id", "version", "title"})
            self.assertEqual((pair["done"], pair["total"], pair["playing"]), (200, 200, False))
        self.assertTrue(any(any(p["playing"] for p in d["pairs"].values()) for _, _, d in seen))
        self.assertTrue(all(d["phase"] == "floor" for _, _, d in seen))

    def test_stop_saves_and_notes(self):
        calls = [0]

        def progress(done, total, detail):
            calls[0] += 1
            if done >= 100:
                stop = jobs.Stopped("stopped")
                stop.by = "User1"
                raise stop
        with self.assertRaises(jobs.Stopped) as caught:
            self.play(progress=progress, inflight=2)
        note = field.last_note(self.entry("casual/alpha"), self.results)
        self.assertTrue(note["stopped"])
        self.assertEqual(note["stopped_by"], "User1")
        self.assertEqual(caught.exception.saved_games, note["played"])
        self.assertLess(note["played"], 600)

    def test_no_opponents(self):
        _write(self.root / "magic" / "products" / "status.csv", "file,status,intact,notes\n")
        with self.assertRaisesRegex(common.ForgeError, "no other deck"):
            self.play(deck_id="commander/cmdr")
        self.assertEqual(self.fake.calls, [])


class ViewTests(FieldTestCase):

    def test_the_view_numbers(self):
        a = self.entry("casual/alpha")
        self.fake.add_games(a, self.entry("casual/beta", "owned"), 200, rate=0.7)
        self.fake.add_games(a, self.entry("casual/gamma"), 100, rate=0.4)
        found = field.view(a, self.results)
        self.assertEqual(set(found), {"deck", "format", "opponents", "average", "rating", "coverage", "last_run",
                                      "notes"})
        self.assertEqual(found["format"], "Constructed")
        self.assertEqual(found["coverage"], {"with_floor": 1, "of": 3})
        rows = {o["id"]: o for o in found["opponents"]}
        self.assertEqual(rows["casual/beta"]["games"], 200)
        self.assertGreater(rows["casual/beta"]["rate"]["value"], rows["casual/gamma"]["rate"]["value"])
        self.assertEqual([o["id"] for o in found["opponents"]][:2], ["casual/beta", "casual/gamma"])
        self.assertIsNone(rows["product/aggro"]["rate"])
        self.assertEqual(rows["product/aggro"]["games"], 0)
        self.assertEqual(rows["casual/beta"]["lead"]["verdict"] in views.VERDICT_WORDS, True)
        for o in found["opponents"]:
            self.assertEqual(set(o), {"id", "version", "title", "kind", "card_sha", "key", "games", "rate", "lead",
                                      "pred", "residual", "not_meaningful", "problem"})
        average = found["average"]
        self.assertEqual((average["counted"], average["of"], average["partial"]), (2, 3, True))
        expected = (rows["casual/beta"]["rate"]["value"] + rows["casual/gamma"]["rate"]["value"]) / 2
        self.assertAlmostEqual(average["value"], expected, places=3)
        json.dumps(found, allow_nan=False)

    def test_not_meaningful_rows_stay_out_of_the_average(self):
        a = self.entry("casual/alpha")
        beta = self.entry("casual/beta", "owned")
        self.fake.add_games(a, beta, 200, rate=0.7)
        self.fake.add_games(a, self.entry("casual/gamma"), 200, rate=0.4)
        meaningless = self.fake.key(a, beta)
        with mock.patch.object(views, "_not_meaningful", lambda result: result["key"] == meaningless):
            found = field.view(a, self.results)
        rows = {o["id"]: o for o in found["opponents"]}
        self.assertTrue(rows["casual/beta"]["not_meaningful"])
        self.assertEqual(found["average"]["counted"], 1)
        self.assertAlmostEqual(found["average"]["value"], rows["casual/gamma"]["rate"]["value"], places=3)

    def test_bradley_terry_data_uses_current_decklab_results_only(self):
        a, beta, gamma = self.entry("casual/alpha"), self.entry("casual/beta", "owned"), self.entry("casual/gamma")
        self.fake.add_games(a, beta, 50)
        self.fake.add_games(beta, gamma, 40)
        old = self.fake.add_games(a, gamma, 30)
        for stored in self.fake.store.values():
            stored["engine"] = {"kind": "decklab"}
            stored["run_version"] = 2
        old["kind"] = "experiment"
        with mock.patch.object(engine, "is_current", lambda result: True):
            data = field._bt_data("Constructed", self.results)
        self.assertEqual({frozenset((i, j)) for i, j, _ in data},
                         {frozenset(("id-casual/alpha", "id-casual/beta")), frozenset(("id-casual/beta", "id-casual/gamma"))})
        self.assertEqual(sum(v[1] for v in data.values()), 90)
        self.assertTrue(all(0 <= v[0] <= v[1] for v in data.values()))
        with mock.patch.object(engine, "is_current", lambda result: None):
            self.assertEqual(field._bt_data("Constructed", self.results), {})


    def test_a_not_meaningful_opponent_isnt_called_unlinked(self):
        a = self.entry("casual/alpha")
        beta, gamma = self.entry("casual/beta", "owned"), self.entry("casual/gamma")
        self.fake.add_games(a, beta, 200, rate=0.7)
        self.fake.add_games(a, gamma, 200, rate=0.4)
        meaningless = self.fake.key(a, gamma)
        fit = {"phi": 1.0}
        patches = [mock.patch.object(views, "_not_meaningful", lambda result: result["key"] == meaningless),
                   mock.patch.object(field, "_side_id", lambda entry, eng: "id-" + entry["id"]),
                   mock.patch.object(field, "_bt_data", lambda fmt, results_dir: {}),
                   mock.patch.object(seqstats, "bt_component", lambda data, player: {player, "id-casual/beta"}),
                   mock.patch.object(seqstats, "bt_fit", lambda data: fit),
                   mock.patch.object(seqstats, "bt_rating", lambda fit, player, ids: None),
                   mock.patch.object(seqstats, "bt_predict", lambda fit, i, j: 0.6),
                   mock.patch.object(seqstats, "residual_flags", lambda data, fit, player, observed: [])]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        found = field.view(a, self.results)
        unlinked = [n for n in found["notes"] if n.startswith("Not rated against")]
        self.assertEqual(len(unlinked), 1)
        self.assertNotIn("Gamma", unlinked[0])
        self.assertIn("Aggro", unlinked[0].title())


class CliTests(FieldTestCase):

    def run_cli(self, *argv):
        """(exit code, stdout, stderr) of field with argv (main() reconfigures stdout)."""
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = cli.main(["field", *argv])
            out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def test_dry_run_and_show(self):
        code, out, err = self.run_cli("casual/alpha", "--dry-run", "--budget", "quick",
                                      "--results-dir", str(self.results))
        self.assertEqual(code, 0, err)
        self.assertIn("3 opponents, about 600 new games", out)
        code, out, _ = self.run_cli("casual/alpha", "--dry-run", "--json", "--fixed", "300",
                                    "--opponents", "product/aggro", "--results-dir", str(self.results))
        planned = json.loads(out)
        self.assertEqual((planned["new_games"], [p["id"] for p in planned["pairs"]]), (300, ["product/aggro"]))
        code, out, _ = self.run_cli("casual/alpha", "--show", "--results-dir", str(self.results))
        self.assertEqual(code, 0)
        self.assertIn("Alpha (target) against the Constructed field: 0 of 3 opponents", out)
        self.assertEqual(self.fake.calls, [])

    def test_the_dry_run_estimates_from_the_results_folder_and_budgets_dont_mix(self):
        asked = []

        def minutes(pairs_games, results_dir=None):
            asked.append(results_dir)
            return (1.0, 2.0)
        with mock.patch.object(estimate, "minutes", minutes):
            code, out, err = self.run_cli("casual/alpha", "--dry-run", "--results-dir", str(self.results))
        self.assertEqual(code, 0, err)
        self.assertEqual(asked, [str(self.results)])
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("casual/alpha", "--dry-run", "--budget", "quick", "--fixed", "300")
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.fake.calls, [])

    def test_a_lead_is_said_from_the_decks_side(self):
        """The printed verdict says "behind" when the opponent leads (side 1), as the page's
        fvVerdict does: a bare "ahead" beside a 10% row read as the deck being ahead."""
        self.assertEqual(cli._field_verdict({"verdict": "ahead", "side": 0}), "ahead")
        self.assertEqual(cli._field_verdict({"verdict": "ahead", "side": 1}), "behind")
        self.assertEqual(cli._field_verdict({"verdict": "slightly_ahead", "side": 1}), "slightly behind")
        self.assertEqual(cli._field_verdict({"verdict": "not_settled", "side": None}), "not settled")

    def test_play_and_bad_names(self):
        code, out, err = self.run_cli("casual/alpha", "--budget", "50", "--opponents", "casual/beta,casual/gamma",
                                      "--results-dir", str(self.results))
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted((c[0], c[1]) for c in self.fake.calls), [("casual/beta", 50), ("casual/gamma", 50)])
        self.assertIn("Played 100 games", out)
        code, _, err = self.run_cli("casual/alpha", "--opponents", "casual/nope", "--results-dir", str(self.results))
        self.assertEqual(code, 1)
        self.assertIn("casual/nope", err)
