"""Tests for decklab.lib.api: the JSON answers behind the web page.

Each test runs in a Sandbox: a temp folder with a small magic/ tree (a
collection, deck files, a Beginner Box with three halves and a preordered
precon), a data folder (profiles, images, the exchange rate), a config.json
with two profiles, and the fixture card index test_cards.py uses. cards, decks,
pool, config and api are pointed at it, the exchange rate and image downloads
are mocked, and decklab.lib.stats, decklab.lib.goldfish and decklab.lib.forge
are stand-in modules (FakeGoldfish and FakeForge "play" at once, or when a
test lets them), with fresh job runners, so nothing touches the network, the
real magic/ folder, Forge or the real decklab/data/. The matchup tests are in
test_matchups_api.py. One practice-hand test runs the real goldfish module,
small, with its results saved in the sandbox. The last tests run every frozen
deck file in fixtures/decks/ through deck_view(). test_server.py and
test_editor.py use the Sandbox too: it fixes today's date for the editor,
and gives the stand-in stats module the real deck_rules. The state store (wishlists, settings, the
simulations mode, play records: decklab.lib.state) is a fresh in-memory one
per sandbox (Sandbox.state), with simulations open to everyone, and the
inventory backend (decklab.lib.inventory) is a FileInventory over the
sandbox's own tree (Sandbox.inventory).

Run from the repo root: python scripts/test_fixtures.py
Deck pages are tested in test_api_decks.py; practice hands, search and images in
test_api_practice.py. Sandbox fixtures and status/profile tests remain here.
"""
import contextlib
import copy
import hashlib
import json
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
import zlib
from collections import Counter
from pathlib import Path
from unittest import mock

from decklab.lib import access, accessories, api, cards, config, decks, inventory, jobs, state, tokens
from decklab.lib import goldfish as real_goldfish      # imported now, with the real stats module
from decklab.lib import stats as real_stats
from decklab.lib.stats import commander as real_stats_commander     # where TAG_FILE, COMBO_FILE and OFFICIAL_FILE are read
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state.memory import MemoryStore

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RATE = (2.0, "2026-09-28")      # 1 USD = 2 AUD
# Wave 3's profile settings (forge-trial/sim-wave3-contract.md section 17), at their defaults.
W3_SETTINGS = {"matchup_mode": "assess", "field_budget": "standard"}
BULK_DATES = {"default_cards": "2026-09-28T21:05:39.249+00:00",
              "oracle_tags": "2026-09-28T21:00:42.364+00:00"}

CONFIG = {"profiles": [
    {"id": "matt", "name": "Matt", "plays_as": "user"},
    {"id": "user1", "name": "User1", "plays_as": "wife"},
    {"id": "../evil", "name": "Evil", "plays_as": "user"},      # skipped: bad id
    {"id": "guest", "name": "Guest", "plays_as": "nobody"},     # skipped: bad plays_as
    {"id": "matt", "name": "Matt again", "plays_as": "user"},   # skipped: repeated id
]}

GRUUL = """# Gruul Test

- **Format:** Casual 60-card, 1v1
- **Played by:** either
- **Status:** building

## Decklist

```
Deck
4 Llanowar Elves (FDN) 227
2 Elvish Mystic
1 Llanowar Elves (M19)
1 Llanowar Elves (PDMU) 1★
1 Black Lotus
1 Very Cryptic Command (UST) 49d
1 Murderous Rider (ELD) 97
1 Opt (FDN) 512
1 Fire // Ice (APC) 999
1 Sol Ring (MKM) 170
9 Forest

Sideboard
2 Pick Your Poison (MKM) 170
```

## Substitutes

### Owned-only version

```
Deck
4 Llanowar Elves (FDN) 227
```
"""

ELF_COMMANDER = """# Elf Commander

- **Format:** Commander
- **Played by:** wife
- **Status:** idea
- **Target bracket:** 2

## Decklist

```
Commander
1 Ghalta, Primal Hunger (RIX) 130

Deck
1 Llanowar Elves (FDN) 227
1 Sol Ring (ECC) 57
```
"""

BROKEN = "# Broken\n\n- **Status:** idea\n\nNo decklist here.\n"

BEGINNER_BOX = """deck,name,set,collector_number,finish,quantity,rarity,notes
Elves,Llanowar Elves,fdn,227,nonfoil,1,common,
Elves,Elvish Mystic,cmm,648,nonfoil,1,common,
Elves,Forest,fdn,,nonfoil,7,common,
Cats,Llanowar Elves,fdn,227,nonfoil,1,common,
Cats,Pick Your Poison,mkm,170,nonfoil,1,common,
Goblins,Aerie Mystics,con,1,nonfoil,1,common,
"""

PRECON = """section,name,set,collector_number,finish,quantity,rarity,notes
commander,Abaddon the Despoiler,40k,319,etched,1,mythic,
deck,Sol Ring,ecc,57,nonfoil,1,uncommon,
deck,Swamp,fdc,,nonfoil,10,common,
"""

STATUS = """file,status,intact,notes
fdn-beginner-box.csv,owned,yes,kept as its decks
fdc-test-precon.csv,preordered,,due soon
"""

COLLECTION = """name,set,collector_number,finish,quantity,condition,language,notes
Llanowar Elves,fdn,227,nonfoil,5,NM,en,
Elvish Mystic,cmm,648,nonfoil,1,NM,en,
Black Lotus,lea,232,nonfoil,1,NM,en,
"""


def fake_stats(sections, kind):
    """The stand-in for decklab.lib.stats.deck_stats; returns a tuple and a
    set on purpose, to check deck_view makes them JSON."""
    return {"kind": kind, "cards": sum(l.quantity for lines in sections.values() for l in lines),
            "sections": tuple(sections), "colors": {"G", "B"}}


class FakeGoldfish(types.ModuleType):
    """The stand-in for decklab.lib.goldfish: cache_key, saved_result and
    get_or_simulate, with each "result" saved in self.saved under a key made
    from the main deck, kind and settings. A run reports progress 100 of 400,
    waits until self.gate is set (it is, unless a test clears it), then raises
    self.error if there is one, or reports 400 of 400 and saves its result.
    self.runs lists each run's (sections, kind, settings); key_error makes
    cache_key raise."""

    def __init__(self):
        super().__init__("decklab.lib.goldfish")
        self.saved, self.runs = {}, []
        self.gate = threading.Event()
        self.gate.set()
        self.error = self.key_error = None

    def cache_key(self, sections, kind, **settings):
        if self.key_error:
            raise self.key_error
        lines = sorted((s, line.name, line.quantity) for s, section in sections.items() if s != "Sideboard"
                       for line in section)
        return hashlib.sha1(repr((lines, kind, sorted(settings.items()))).encode()).hexdigest()

    def saved_result(self, key):
        result = self.saved.get(key)
        return dict(result, cached=True) if result else None

    def get_or_simulate(self, sections, kind, progress=None, **settings):
        self.runs.append((sections, kind, settings))
        progress(100, 400)
        if not self.gate.wait(5):
            raise TimeoutError("the test never let the run finish")
        if self.error:
            raise self.error
        progress(400, 400)
        key = self.cache_key(sections, kind, **settings)
        cards_ = sum(line.quantity for s in ("Commander", "Deck") for line in sections.get(s, []))
        self.saved[key] = {"cache_key": key, "kind": kind, "cards": cards_, "games": settings.get("games"),
                           "warnings": [f"{config.REPO / 'magic' / 'x.csv'}: a warning"]}
        return dict(self.saved[key], cached=False)


class FakeForge(types.ModuleType):
    """The stand-in for decklab.lib.forge: the contract's public functions
    (Milestone 5) over results kept in self.saved {key: stored}, in a small
    stored form of its own.

    card_sha is a hash of the Commander and Deck lines (name and copies), so
    it's the same for the same cards under two ids and changes with the
    list. A run (self.runs lists each one's (a id, b id, games, by)) plays
    four quarter "batches": side 0 (the smaller card_sha) wins 3 in 5
    games. After the first it keeps reporting, as Forge does after every
    game, until self.gate is set (it is, unless a test clears it; started
    is set meanwhile). With self.slow_start, it reports 0 games until the
    gate opens, as Forge starting up does. Its progress detail's "waiting"
    is self.waiting (None unless a test sets it; forge gives slots.WAITING
    while other runs on the PC hold every slot). When its progress raises (Stop),
    it waits self.stop_delay seconds (killing Forge, writing the file),
    saves the batches before that one with "stopped" (and the exception's
    "by") and re-raises. self.failed_batches of the four fail (their games
    aren't counted). self.error is raised instead of playing: a ForgeError
    saves a run record that played nothing first. self.ready and
    self.problem are status()'s; self.fail is raised by results() and
    results_for() (the deck page must survive it). As in forge, list
    sides' kind is the deck id's first part (page_kind), a list without a
    perspective puts the list the last run was asked for first, results()
    leaves out results with no games counted, and view()'s run records
    have the batch counts. Per-card stats (Milestone 8): a run's games
    have card data while self.card_log is True (it is, unless a test
    clears it); view()'s "cards" and list_cards() give CardStats with
    their counts ("games", "of", "matchups"; "old" is always 0) and no
    rows, None without card data, and list_cards() raises
    self.cards_fail when it's set.
    Engines (simulation wave 2): every result is today's engine's
    ({"kind": "decklab", "run_version": 2, "current": True, "words": None},
    its "engine" in list items and views) unless a test sets a stored
    result's "engine" to another; list sides' "auto_profile" is the stored
    side's (None unless a test sets it), and self.engine.held() and
    self.engine.auto_profile_flag() are forge.engine's stand-ins.
    test_matchups_api.py's RealForgeTests check the api against the real
    forge package too."""

    FORGE_RUN_VERSION = 2
    TODAYS_ENGINE = {"kind": "decklab", "run_version": 2, "current": True, "words": None}
    GAME_CHOICES = (200, 400, 800, 1600, 3200)
    DEFAULT_GAMES = 800
    SEED_BASE = 1
    MIN_GAMES_NEVER_CAST = 100

    class ForgeError(Exception):
        pass

    class Stopped(Exception):
        pass

    def __init__(self):
        super().__init__("decklab.lib.forge")
        self.saved, self.runs = {}, []
        self.gate, self.started = threading.Event(), threading.Event()
        self.gate.set()
        self.error = self.fail = None
        self.ready, self.problem = True, None
        self.card_log, self.cards_fail = True, None
        self.failed_batches = 0
        self.slow_start, self.stop_delay = False, 0
        self.waiting = None
        self.clock = 0
        self.held = 0                   # blocks in self.engine.held() entered
        self.engine = types.SimpleNamespace(held=self._held, auto_profile_flag=self._auto_profile_flag)
        # The deck page's suggested token counts (E7-S08): no saved game counted any (test_token_peaks has them).
        self.tokenpeaks = types.SimpleNamespace(list_token_peaks=lambda sections, kind, keep=None: None)

    @contextlib.contextmanager
    def _held(self):
        self.held += 1
        yield

    @staticmethod
    def _auto_profile_flag(side):
        return (side.get("auto_profile") or {}).get("flag")

    def status(self):
        # "pool": the server's warm pool's state (forge.pool.status()), when a test sets self.pool
        # (forge's always has it: None outside the server).
        found = {"ready": self.ready, "version": "2.0.15" if self.ready else None,
                 "problem": None if self.ready else (self.problem or "Forge isn't installed at the folder "
                                                                     "config.json names")}
        if getattr(self, "pool", None) is not None:
            found["pool"] = self.pool
        return found

    def entry(self, deck_id, version, title, kind, sections):
        copies = Counter()
        for section in ("Commander", "Deck"):
            for line in sections.get(section, []):
                copies[(section, line.name.split(" // ")[0])] += line.quantity
        card_sha = hashlib.sha256(repr(sorted(copies.items())).encode()).hexdigest()
        return {"id": deck_id, "version": version, "title": title, "kind": kind, "card_sha": card_sha,
                "card_count": sum(copies.values()), "dck": "[metadata]\n", "source": None}

    def card_sha(self, sections, kind):
        return self.entry(None, None, None, kind, sections)["card_sha"]

    def page_kind(self, deck_id):
        prefix = (deck_id or "").split("/", 1)[0]
        return prefix if prefix in ("casual", "commander", "product", "pairing") else "casual"

    def fmt_for(self, kind):
        return "Commander" if kind == "commander" else "Constructed"

    def matchup_key(self, entry_a, entry_b):
        if entry_a["kind"] != entry_b["kind"]:
            raise self.ForgeError("A Commander deck can only play another Commander deck.")
        return hashlib.sha256(json.dumps([sorted([entry_a["card_sha"], entry_b["card_sha"]]),
                                          self.fmt_for(entry_a["kind"]), self.FORGE_RUN_VERSION, "2.0.15", 120,
                                          ["Default", "Default"]]).encode()).hexdigest()

    def _save(self, entry_a, entry_b, games, by, played, stopped=None, error=None, failed=0):
        key = self.matchup_key(entry_a, entry_b)
        pair = sorted([entry_a, entry_b], key=lambda e: e["card_sha"])
        stored = self.saved.setdefault(key, {
            "key": key, "format": self.fmt_for(entry_a["kind"]), "forge_version": "2.0.15",
            "sides": [{"card_sha": e["card_sha"], "card_count": e["card_count"], "kind": e["kind"], "seen_as": []}
                      for e in pair],
            "runs": [], "games": 0, "wins": [0, 0], "card_games": 0})
        for side, e in zip(stored["sides"], pair):
            side["seen_as"] = [s for s in side["seen_as"] if (s["id"], s["version"]) != (e["id"], e["version"])]
            side["seen_as"].append({"id": e["id"], "version": e["version"], "title": e["title"]})
        self.clock += 1
        stored["updated"] = f"2026-10-01T12:00:{self.clock:02d}"
        stored["runs"].append({"when": stored["updated"], "by": by, "a": entry_a["card_sha"], "asked": games,
                               "played": played,
                               "stopped": stopped is not None, "stopped_by": getattr(stopped, "by", None),
                               "error": error, "batches": 4, "failed": failed,
                               "failure": "Forge stopped responding" if failed else None,
                               "card_log": self.card_log,
                               "card_log_problem": None if self.card_log else "The card log is off."})
        stored["games"] += played
        stored["card_games"] += played if self.card_log else 0
        stored["wins"][0] += played * 3 // 5
        stored["wins"][1] += played - played * 3 // 5
        return copy.deepcopy(stored)

    def run(self, entry_a, entry_b, games, *, by, progress=None, results_dir=None, workers=None, pool=None,
            local=False):
        # Its progress detail's "fallback" is self.fallback when a test sets it (forge's sentence when the
        # warm pool's workers couldn't start, pool.FALLBACK), else None.
        self.runs.append((entry_a["id"], entry_b["id"], games, by))
        if self.error is not None:
            if isinstance(self.error, self.ForgeError):
                self._save(entry_a, entry_b, games, by, 0, error=str(self.error))
            raise self.error
        step, done = games // 4, 0

        def report(n):
            progress(n, games, {"wins": [n * 3 // 5, n - n * 3 // 5], "other": 0, "games_per_min": 600.0,
                                "eta_s": (games - n) / 10, "failed_batches": 0, "waiting": self.waiting,
                                "fallback": getattr(self, "fallback", None)})

        def hold():
            self.started.set()
            deadline = time.monotonic() + 5
            while not self.gate.wait(0.005):
                if time.monotonic() > deadline:
                    raise TimeoutError("the test never let the run finish")
                report(done)

        try:
            report(0)
            if self.slow_start:
                hold()
            for batch in range(4):
                report(done + step)
                done += step
                if batch == 0 and not self.slow_start:
                    hold()
        except jobs.Stopped as e:
            time.sleep(self.stop_delay)
            self._save(entry_a, entry_b, games, by, done, stopped=e)        # the games that finished
            raise
        failed = self.failed_batches
        return self._save(entry_a, entry_b, games, by, games - failed * step, failed=failed)

    def load(self, key, results_dir=None):
        stored = self.saved.get(key)
        return copy.deepcopy(stored) if stored is not None else None

    def _index(self, result, perspective_sha):
        return 1 if perspective_sha is not None and result["sides"][0]["card_sha"] != perspective_sha else 0

    def list_item(self, result, perspective_sha=None):
        # As in forge.list_item, without a perspective the list the last run was asked for first comes first.
        first = self._index(result, perspective_sha or result["runs"][-1].get("a"))
        sides = [dict(result["sides"][i]["seen_as"][-1], kind=result["sides"][i]["seen_as"][-1]["id"].split("/")[0],
                      card_sha=result["sides"][i]["card_sha"], card_count=result["sides"][i]["card_count"],
                      current=None, auto_profile=self._auto_profile_flag(result["sides"][i]))
                 for i in (first, 1 - first)]
        view = self.view(result, sides[0]["card_sha"])
        return {"key": result["key"], "format": result["format"], "sides": sides, "games": result["games"],
                "winrate": view["winrate"], "updated": result["updated"], "by": result["runs"][-1]["by"],
                "not_meaningful": False, "engine": view["engine"]}

    def view(self, result, perspective_sha):
        first = self._index(result, perspective_sha)
        wins = [result["wins"][first], result["wins"][1 - first]]
        rate = wins[0] / result["games"] if result["games"] else None
        return {"key": result["key"], "format": result["format"], "forge_version": "2.0.15",
                "games": result["games"], "wins": wins, "draws": 0, "timeouts": 0, "errors": 0,
                "winrate": {"value": rate, "low": rate, "high": rate, "balanced": True},
                "cards": [self._card_stats(result["card_games"], result["games"], 1,
                                           {"for": result["sides"][i]["card_sha"]})
                          for i in (first, 1 - first)],
                "runs": [{k: run[k] for k in ("when", "by", "asked", "played", "stopped", "stopped_by", "error",
                                              "batches", "failed", "failure", "card_log", "card_log_problem")}
                         for run in result["runs"]],
                "failed_batches": sum(run["failed"] for run in result["runs"]),
                "not_meaningful": False, "updated": result["updated"],
                "engine": dict(result.get("engine") or self.TODAYS_ENGINE)}

    def _card_stats(self, games, of, matchups, extra=None):
        """CardStats without rows, or None without card data ("for", in a view's, says which
        stored side it describes)."""
        if not matchups or not games:
            return None
        return {"games": games, "bad": 0, "old": 0, "of": of, "matchups": matchups, "enough": games >= 100,
                "min_games": 100, "min_split": 30, "rows": [], "commander": [], **(extra or {})}

    def list_cards(self, sections, kind, results=None, results_dir=None, *, keep=None):
        # As in forge.list_cards: every saved result with this list adds its games (a mirror's twice).
        if self.cards_fail:
            raise self.cards_fail
        sha = self.card_sha(sections, kind)
        games = of = matchups = 0
        for r in self._stored() if results is None else results:
            if keep is not None and not keep(r):
                continue
            sides = sum(s["card_sha"] == sha for s in r["sides"])
            games += sides * r["card_games"]
            of += sides * r["games"]
            matchups += bool(sides and r["card_games"])
        return self._card_stats(games, of, matchups)

    def _stored(self):
        if self.fail:
            raise self.fail
        return sorted((r for r in self.saved.values() if r["games"]), key=lambda r: r["updated"], reverse=True)

    def results(self, results_dir=None):
        return [self.list_item(r) for r in self._stored()]

    def results_for(self, card_sha, results_dir=None):
        return [self.list_item(r, card_sha) for r in self._stored()
                if card_sha in (s["card_sha"] for s in r["sides"])]

    def ai_limits(self, sections, kind, results=None):
        dead = [{"name": line.name, "qty": line.quantity, "why": "script"}
                for line in sections.get("Deck", []) if line.name == "Black Lotus"]
        sha = self.card_sha(sections, kind)
        games = sum(r["games"] for r in results or () for s in r["sides"] if s["card_sha"] == sha)
        return {"cannot_play": dead, "commander_unplayable": False, "team_pump": None, "unknown": [],
                "problem": None, "games": games}

    def list_ai(self, sections, kind, results_dir=None, pilot=None, *, keep=None):
        # As in forge.list_ai: "games" adds up every saved result's games with this list (a mirror's twice).
        return self.ai_limits(sections, kind, [r for r in self._stored() if keep is None or keep(r)])

    def side_ai(self, result, side):
        # "for" says which stored side it describes, so the tests can check the perspective.
        return {"cannot_play": [], "commander_unplayable": False, "team_pump": None, "unknown": [],
                "problem": None, "games": result["games"], "for": result["sides"][side]["card_sha"]}


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


class Sandbox:
    """Everything the api package reads, in a temp folder (see the module docstring).

    start() applies the patches and returns self; stop() undoes them. Useful
    attributes: root, magic, data, web, state (the MemoryStore installed),
    inventory (the FileInventory installed),
    stats (the stand-in deck_stats Mock), goldfish (the FakeGoldfish module),
    forge (the FakeForge module), logs (lines api.common._log wrote) and
    downloads (image URLs fetched)."""

    def __init__(self):
        self.stack = contextlib.ExitStack()
        self.logs = []
        self.downloads = []

    def start(self):
        try:
            self._start()
        except BaseException:
            self.stack.close()
            raise
        return self

    def _start(self):
        self.root = Path(tempfile.mkdtemp()).resolve()  # long form, as golden_dump.pointed() resolves it
        self.stack.callback(shutil.rmtree, self.root, True)
        self.magic, self.data, self.web = self.root / "magic", self.root / "data", self.root / "web"
        _write(self.magic / "collection.csv", COLLECTION)
        (self.magic / "orders" / "received").mkdir(parents=True)
        _write(self.magic / "products" / "fdn-beginner-box.csv", BEGINNER_BOX)
        _write(self.magic / "products" / "fdc-test-precon.csv", PRECON)
        _write(self.magic / "products" / "status.csv", STATUS)
        _write(self.magic / "decks" / "casual" / "gruul-test.md", GRUUL)
        _write(self.magic / "decks" / "casual" / "broken.md", BROKEN)
        _write(self.magic / "decks" / "commander" / "elf-commander.md", ELF_COMMANDER)
        _write(self.root / "config.json", json.dumps(CONFIG))
        (self.data / "images").mkdir(parents=True)
        index = cards.build_index(FIXTURES / "default_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                                  BULK_DATES, log=lambda *a: None)
        cards.write_index(index, self.data / "scryfall" / "index.json.gz")

        def fake_download(url, dest, accept="*/*"):
            self.downloads.append(url)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"\xff\xd8jpeg")
            return 6

        self.stats = mock.Mock(side_effect=fake_stats)
        stats_module = types.ModuleType("decklab.lib.stats")
        stats_module.deck_stats = self.stats
        # The editor's rule warnings and bracket names are the real ones (small and quick).
        stats_module.deck_rules = real_stats.deck_rules
        stats_module.BRACKETS = real_stats.BRACKETS
        for target, name, value in (
                # The pool and the product decks read the inventory (self.inventory, below).
                (decks, "DECKS_DIR", self.magic / "decks"),
                (accessories, "PATH", self.magic / "accessories.csv"),
                (accessories, "IMAGES", self.magic / "accessories" / "images"),
                (config, "CONFIG_FILE", self.root / "config.json"),
                (cards, "INDEX_FILE", self.data / "scryfall" / "index.json.gz"),
                (cards, "_index", None),                 # loads INDEX_FILE on first use
                (cards, "FX_FILE", self.data / "fx.json"),
                (cards, "IMAGES_DIR", self.data / "images"),
                (cards, "_download", mock.Mock(side_effect=fake_download)),
                (cards, "usd_to_aud", mock.Mock(return_value=RATE)),
                (api.carddata, "UPDATE", {"running": False, "error": None}),
                (api.practice, "JOBS", api._job_runner()),
                (api.forge_runs, "FORGE_JOBS", api._forge_runner()),
                (api.common, "_log", self.logs.append),
                (api.saving, "_today", lambda: "2026-10-05"),
                (real_stats_commander, "TAG_FILE", FIXTURES / "oracle_tags.jsonl"),
                (real_stats_commander, "COMBO_FILE", FIXTURES / "stats_combos.json"),
                (real_stats_commander, "OFFICIAL_FILE", FIXTURES / "stats_official_lists.json")):
            self.stack.enter_context(mock.patch.object(target, name, value))
        tokens.clear_cache()
        self.stack.callback(tokens.clear_cache)
        # The personal state lives in memory, never in a database (decklab/tests/__init__.py).
        self.state = MemoryStore(mode="everyone")
        self.stack.callback(state.use(self.state))
        # The inventory is the sandbox's files (decklab/lib/inventory), never the live repo's.
        self.inventory = FileInventory(self.root)
        self.stack.callback(inventory.use(self.inventory))
        self.goldfish = FakeGoldfish()
        self.forge = FakeForge()
        self._swap_module("decklab.lib.stats", stats_module)
        self._swap_module("decklab.lib.goldfish", self.goldfish)
        self._swap_module("decklab.lib.forge", self.forge)
        self.stack.callback(self.wait_for_jobs)     # first, while the patches still apply

    def _swap_module(self, name, module):
        # mock.patch.dict on sys.modules would drop every module imported
        # meanwhile when it's undone, so swap the one entry by hand.
        old = sys.modules.get(name)
        sys.modules[name] = module
        self.stack.callback(lambda: sys.modules.__setitem__(name, old) if old else sys.modules.pop(name, None))

    def wait_for_jobs(self, timeout=10):
        """Let every background job finish (the stand-ins' gates open)."""
        self.goldfish.gate.set()
        self.forge.gate.set()
        for job in [*api.practice.JOBS._jobs.values(), *api.forge_runs.FORGE_JOBS._jobs.values()]:
            if not job.wait(timeout):
                raise AssertionError(f"job {job.key} didn't finish")

    def stop(self):
        self.stack.close()

    def no_index(self):
        """Make the card index missing until the test ends (use in a with block)."""
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(cards, "INDEX_FILE", self.data / "missing.json.gz"))
        stack.enter_context(mock.patch.object(cards, "_index", None))
        return stack


class ApiTestCase(unittest.TestCase):

    def setUp(self):
        self.box = Sandbox().start()
        self.addCleanup(self.box.stop)

    def assertApiError(self, status, call, *args, contains=None):
        with self.assertRaises(api.ApiError) as caught:
            call(*args)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        if contains:
            self.assertIn(contains, caught.exception.message)
        return caught.exception


class SandboxTests(ApiTestCase):

    def test_token_reads_stay_in_the_sandbox(self):
        # The deck page and library read the sandbox's token cards (its installed
        # inventory) and order records, never the live repo's.
        self.assertIs(inventory.backend(), self.box.inventory)
        _write(self.box.magic / "tokens.csv", ",".join(tokens.FIELDS) + "\nGoblin,,,,,,3,,,single-sided verified\n")
        self.assertEqual([r["front"] for r in tokens.read().rows], ["Goblin"])
        loads, real_load = [], self.box.inventory.load

        def load():
            loads.append(1)
            return real_load()
        with mock.patch.object(self.box.inventory, "load", side_effect=load):
            api.deck_view("casual/gruul-test")
            api.decks_index()
        self.assertTrue(loads)
        self.assertEqual(tokens.incoming(), ([], []))       # the sandbox has no order records

    def test_stop_restores_the_inventory_backend(self):
        before = inventory.backend()
        box = Sandbox().start()
        self.assertIs(inventory.backend(), box.inventory)
        box.stop()
        self.assertIs(inventory.backend(), before)


class StatusTests(ApiTestCase):

    def test_ready_with_the_index_dates_and_the_cached_rate(self):
        _write(self.box.data / "fx.json", json.dumps({"rate": 1.4237, "date": "2026-09-28",
                                                      "fetched_on": "2026-09-29"}))
        status = api.status()
        self.assertEqual(status["cards"]["ready"], True)
        self.assertEqual(status["cards"]["price_date"], "2026-09-28")
        self.assertIsNone(status["cards"]["error"])
        self.assertRegex(status["cards"]["built_at"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertEqual((status["updating"], status["update_error"]), (False, None))
        self.assertEqual(status["fx"], {"rate": 1.4237, "date": "2026-09-28"})
        cards.usd_to_aud.assert_not_called()        # status never fetches a rate
        json.dumps(status, allow_nan=False)

    def test_no_cached_rate(self):
        self.assertIsNone(api.status()["fx"])
        _write(self.box.data / "fx.json", "not json")
        self.assertIsNone(api.status()["fx"])

    def test_not_ready_while_updating(self):
        with self.box.no_index(), mock.patch.dict(api.carddata.UPDATE, running=True):
            status = api.status()
            self.assertEqual((status["cards"]["ready"], status["updating"]), (False, True))
            self.assertEqual(status["cards"]["error"], "There's no card data on the PC yet")
            for call, args in ((api.decks_index, ()), (api.deck_view, ("casual/gruul-test",)),
                               (api.search, ("llan",)), (api.image_file, ("fdn", "227", "small"))):
                self.assertApiError(503, call, *args, contains="still being downloaded")

    def test_not_ready_after_a_failed_update(self):
        # The page gets a plain sentence; the details stay in status() and the log.
        with self.box.no_index(), mock.patch.dict(api.carddata.UPDATE, error="Scryfall is down"):
            error = self.assertApiError(503, api.decks_index, contains="the last download from Scryfall failed")
            self.assertNotIn("Scryfall is down", error.message)
            self.assertEqual(api.status()["update_error"], "Scryfall is down")
        with self.box.no_index():
            error = self.assertApiError(503, api.decks_index, contains="There's no card data on the PC yet")
            self.assertNotIn("python -m", error.message)

    def test_no_local_paths_in_answers_without_a_card_index(self):
        # Every device on the home network reads these, so no absolute path (and so no
        # Windows user name) may be in them; the log gets the full error, once.
        with self.box.no_index():
            status = api.status()
            api.status()
            answers = [json.dumps(status)]
            for call, args in ((api.decks_index, ()), (api.deck_view, ("casual/gruul-test",)),
                               (api.search, ("llan",)), (api.image_file, ("fdn", "227", "small"))):
                answers.append(self.assertApiError(503, call, *args).message)
        for answer in answers:
            self.assertNotIn(str(self.box.root), answer.replace("\\\\", "\\"))
            self.assertNotRegex(answer, r"[A-Za-z]:\\")
        logged = [line for line in self.box.logs if "card index can't be loaded" in line]
        self.assertEqual(len(logged), 1)
        self.assertIn("missing.json.gz", logged[0])

    def test_a_damaged_index_is_not_ready_rather_than_a_crash(self):
        # A damaged deflate stream raises zlib.error, which isn't an OSError.
        good = (self.box.data / "scryfall" / "index.json.gz").read_bytes()
        damaged = bytearray(good)
        for i in range(20, 84):
            damaged[i] ^= 0xFF
        bad = self.box.data / "damaged.json.gz"
        bad.write_bytes(bytes(damaged))
        with self.assertRaises(zlib.error):
            cards._read_index(bad)
        with mock.patch.object(cards, "INDEX_FILE", bad), mock.patch.object(cards, "_index", None):
            status = api.status()
            self.assertFalse(status["cards"]["ready"])
            self.assertIn("damaged", status["cards"]["error"])
            self.assertApiError(503, api.decks_index, contains="can't be read")

    def test_profiles_dont_need_the_card_index(self):
        with self.box.no_index():
            self.assertEqual(len(api.profiles()["profiles"]), 2)
            self.assertEqual(api.get_settings("matt"), {"theme": "system", "matchup_games": "800", **W3_SETTINGS})


class UpdateTests(ApiTestCase):

    def test_update_runs_and_says_so_meanwhile(self):
        seen = []
        with mock.patch.object(cards, "update", side_effect=lambda **kw: seen.append(api.status()["updating"])):
            self.assertTrue(api.update_cards(log=self.box.logs.append))
        self.assertEqual(seen, [True])
        self.assertEqual((api.carddata.UPDATE["running"], api.carddata.UPDATE["error"]), (False, None))
        cards.usd_to_aud.assert_called_once()      # the rate is fetched ahead of the first page

    def test_a_failed_update_is_kept_for_status_not_raised(self):
        logs = []
        with mock.patch.object(cards, "update", side_effect=RuntimeError("offline, no local copy")):
            self.assertTrue(api.update_cards(log=logs.append))
        self.assertEqual(api.status()["update_error"], "offline, no local copy")
        self.assertFalse(api.carddata.UPDATE["running"])
        self.assertIn("Traceback", "".join(logs))

    def test_no_rate_isnt_a_failed_update(self):
        logs = []
        with mock.patch.object(cards, "update"), \
                mock.patch.object(cards, "usd_to_aud", side_effect=RuntimeError("no rate")):
            api.update_cards(log=logs.append)
        self.assertIsNone(api.carddata.UPDATE["error"])
        self.assertIn("no rate", "".join(logs))

    def test_only_one_update_at_a_time(self):
        started, release = threading.Event(), threading.Event()

        def slow_update(**kw):
            started.set()
            release.wait(5)

        with mock.patch.object(cards, "update", side_effect=slow_update):
            first = threading.Thread(target=api.update_cards, kwargs={"log": lambda *a: None})
            first.start()
            started.wait(5)
            self.assertFalse(api.update_cards(log=lambda *a: None))
            release.set()
            first.join(5)
        self.assertFalse(api.carddata.UPDATE["running"])


class ProfileTests(ApiTestCase):

    def saved(self, profile="matt"):
        """The profile's settings as the store keeps them, None when it has none."""
        return self.box.state.settings(profile) or None

    def test_profiles_come_from_config_skipping_bad_entries(self):
        # No profile names a role, so it's an older config: everyone is an admin, at home, and no one
        # is named as the admin to ask (E10-S38).
        self.assertEqual(api.profiles(), {"profiles": [
            {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
            {"id": "user1", "name": "User1", "plays_as": "wife", "role": "admin", "space": "home"}], "admins": []})

    def test_a_broken_config_is_a_clear_error(self):
        _write(self.box.root / "config.json", "{not json")
        self.assertApiError(500, api.profiles, contains="config.json")

    def test_defaults_when_nothing_is_saved(self):
        self.assertEqual(api.get_settings("user1"), {"theme": "system", "matchup_games": "800", **W3_SETTINGS})
        self.assertIsNone(self.saved("user1"))

    def test_round_trip(self):
        dark = {"theme": "dark", "matchup_games": "800", **W3_SETTINGS}
        self.assertEqual(api.put_settings("matt", b'{"theme": "dark"}'), dark)
        self.assertEqual(api.get_settings("matt"), dark)
        self.assertEqual(self.saved(), {"theme": "dark"})
        self.assertEqual(api.get_settings("user1"), {"theme": "system", "matchup_games": "800", **W3_SETTINGS})   # each person's own
        # Only the keys sent change; an empty object changes nothing.
        self.assertEqual(api.put_settings("matt", b"{}"), dark)
        self.assertEqual(api.put_settings("matt", '{"theme": "light"}'), dict(dark, theme="light"))
        self.assertEqual(api.put_settings("matt", '{"matchup_games": "3200"}'),
                         {"theme": "light", "matchup_games": "3200", **W3_SETTINGS})
        # Only the keys that change are saved.
        self.assertEqual(self.saved(), {"theme": "light", "matchup_games": "3200"})

    def test_the_matchup_games_setting(self):
        # The games a matchup page offers first: 800 unless the person picked another choice.
        self.assertEqual(api.SETTINGS["matchup_games"], ("800", "200", "400", "1600", "3200"))
        for value in ("200", "400", "800", "1600", "3200"):
            with self.subTest(value=value):
                body = json.dumps({"matchup_games": value}).encode()
                self.assertEqual(api.put_settings("user1", body)["matchup_games"], value)
        for body in (b'{"matchup_games": 800}', b'{"matchup_games": "100"}', b'{"matchup_games": "800 "}',
                     b'{"matchup_games": null}'):
            with self.subTest(body=body):
                self.assertApiError(400, api.put_settings, "user1", body)
        self.assertEqual(api.get_settings("user1")["matchup_games"], "3200")

    def test_bad_bodies_are_refused_and_nothing_is_saved(self):
        for body in (b"", b"not json", b'"dark"', b'["dark"]', b"null", b'{"theme": 1}',
                     b'{"theme": "blue"}', b'{"theme": "Dark"}', b'{"colour": "dark"}',
                     b'{"theme": "dark", "theme": "light"}', b'{"theme": NaN}', b"\xff\xfe{}",
                     b'{"theme": ["dark"]}'):
            with self.subTest(body=body):
                self.assertApiError(400, api.put_settings, "matt", body)
        self.assertApiError(413, api.put_settings, "matt", b'{"theme": "dark"}' + b" " * api.MAX_BODY)
        self.assertIsNone(self.saved())

    def test_unknown_or_malformed_profiles_are_404(self):
        for profile in ("nobody", "Matt", "../matt", "matt/../user1", "", "con", "guest",
                        "..", "matt.json", "a" * 41, None):
            with self.subTest(profile=profile):
                self.assertApiError(404, api.get_settings, profile)
                self.assertApiError(404, api.put_settings, profile, b'{"theme": "dark"}')
        self.assertEqual(self.box.state.changes(), [])

    def test_a_value_no_longer_allowed_is_dropped(self):
        self.box.state.settings_put("matt", {"theme": "neon", "matchup_games": "100", "extra": "1"},
                                    state.Actor("test", "Test"), "Old values")
        self.assertEqual(api.get_settings("matt"), {"theme": "system", "matchup_games": "800", **W3_SETTINGS})
        # A save writes the value sent over the old one; the others are left as they were.
        self.assertEqual(api.put_settings("matt", b'{"theme": "dark"}'),
                         {"theme": "dark", "matchup_games": "800", **W3_SETTINGS})
        self.assertEqual(self.saved(), {"theme": "dark", "matchup_games": "100", "extra": "1"})

    def test_who_changed_it_and_nothing_written_when_nothing_changes(self):
        api.put_settings("user1", b'{"theme": "dark", "matchup_games": "800"}')
        api.put_settings("user1", b'{"theme": "dark"}')                    # already so: no change
        api.put_settings("user1", b"{}")
        with access.viewing("matt"):                                        # the chooser names Matt
            api.put_settings("user1", b'{"field_budget": "quick"}')
        with access.using({"profile": "user1", "email": "", "remote": True}):
            api.put_settings("user1", b'{"theme": "light"}')
        got = [(c["actor"], c["via"], c["source"], c["message"]) for c in self.box.state.changes()]
        self.assertEqual(got, [("home", "home", "web", "Change User1's settings: theme, matchup_games"),
                               ("matt", "home", "web", "Change User1's settings: field_budget"),
                               ("user1", "tunnel", "web", "Change User1's settings: theme")])

    def test_the_database_down(self):
        api.put_settings("matt", b'{"theme": "dark"}')
        self.box.state.down = True
        for call, args in ((api.get_settings, ("matt",)), (api.put_settings, ("matt", b'{"theme": "light"}'))):
            with self.subTest(call=call.__name__), self.assertRaises(api.ApiError) as caught:
                call(*args)
            self.assertEqual((caught.exception.status, caught.exception.extra), (503, {"reason": "database"}))
        # The matchup and field pages' defaults never fail: the last values known, else the defaults.
        self.assertEqual(api._current_settings("matt")["theme"], "dark")
        self.assertEqual(api._current_settings("user1"), {"theme": "system", "matchup_games": "800", **W3_SETTINGS})
        self.box.state.down = False
        self.assertEqual(self.saved(), {"theme": "dark"})



class PackageTests(unittest.TestCase):
    """api is a package (Milestone 7). Each name the tests patch has one
    binding, in the part whose code reads it, and none in the package
    itself, so a patch on the wrong module fails instead of doing nothing."""

    PATCHED = {"UPDATE": "carddata", "JOBS": "practice",
               "GOLDFISH_SETTINGS": "practice", "FORGE_JOBS": "forge_runs", "STOP_WAIT": "forge_runs",
               "_log": "common", "_read_draft": "drafts", "_today": "saving", "_stale_after": "saving"}

    def test_each_patched_name_has_one_binding(self):
        # Feature-route modules may load on their first request. Include those
        # in the ownership check even when running this test on its own.
        import importlib
        parts = {path.stem: importlib.import_module(f"decklab.lib.api.{path.stem}")
                 for path in Path(api.__file__).parent.glob("*.py") if path.stem != "__init__"}
        for name, owner in self.PATCHED.items():
            with self.subTest(name=name):
                self.assertEqual([part for part, module in sorted(parts.items()) if name in vars(module)], [owner])
                self.assertNotIn(name, vars(api))
                with self.assertRaises(AttributeError), mock.patch.object(api, name, None):
                    pass


if __name__ == "__main__":
    unittest.main()
