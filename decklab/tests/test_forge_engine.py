"""Tests for decklab.lib.forge's engine id (simulation wave 2, the report's R06; wave 2's
contract, forge-trial/sim-wave2-contract.md, "Engine id"): the canonical description and the
key, each side's own id, the plain-Forge fallback keyed as its own engine, what's remembered
of Forge's folder, the DLENGINE echo check, PERFORMANCE_MODE in Forge's preferences, and every
consumer that pools results by a list's card_sha: the page's engine labels (views), the
deck page's per-card numbers (cardstats.list_cards) and never-cast cards (ai.list_ai), the
command line's list and play lines, and the page's script (matchups.js, under Node.js when it's
installed).

They use test_forge.py's made-up Forge folder and fixtures/fake_forge.py, whose setUpModule
and tearDownModule they share. The tests' Java is this Python, so the card log isn't ready
unless a test says so (simjar.readiness for pages, simjar.card_log for runs).

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import hashlib
import json
import subprocess
import sys
import zipfile
from unittest import mock

from decklab.lib import forge
from decklab.tests import test_forge
from decklab.tests.test_forge import CARD_LOG, CHECKED_BUILD, GISA, GREEN, RED, entry, make_forge, sections, stored
from decklab.tests.test_web import MATCHUP_SCRIPTS, NODE, _run_page

READY = {"ready": True, "problem": None}


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                          .encode("ascii")).hexdigest()


class EngineCase(test_forge.ForgeCase):

    def setUp(self):
        super().setUp()
        # A Forge folder of the test's own, with Forge's Default AI profile.
        self.forge_dir = self.tmp / "forge"
        make_forge(self.forge_dir)
        self.ai_file = self.forge_dir / "res" / "ai" / "Default.ai"
        self.ai_file.parent.mkdir(parents=True)
        self.ai_file.write_bytes(b"Name=Default\nMulliganThreshold=2\n")
        self.settings["forge_dir"] = str(self.forge_dir)
        self.a, self.b = entry(GREEN, "casual/green"), entry(RED, "casual/red")

    def ready(self):
        """Pages see the card log as usable (install.status() asks simjar.readiness)."""
        return mock.patch.object(forge.simjar, "readiness", return_value=dict(READY))

    def card_log(self, **extra):
        """Runs use the card log (the fake Forge then prints DL| lines)."""
        return mock.patch.object(forge.simjar, "card_log", return_value=dict(CARD_LOG, **extra))

    def run_matchup(self, games=200, a=None, b=None, **kwargs):
        kwargs.setdefault("results_dir", self.results)
        return forge.run(a or self.a, b or self.b, games, by="Matt", **kwargs)

    def ai_sha(self):
        return hashlib.sha256(self.ai_file.read_bytes()).hexdigest()

    def fiery(self):
        """Wave 3's per-matchup overrides (section 4.2) of a matchup holding Fiery Annihilation, whose adopted
        override the made-up Forge's script fits (its fixture is Forge 2.0.15's own): Deck Lab's user folder
        holds it once status() or a run has deployed it."""
        sha = hashlib.sha256((forge.overrides.SETS_DIR / "fiery" / "fiery_annihilation.txt").read_bytes()).hexdigest()
        return hashlib.sha256(f"Fiery Annihilation\n{sha}\n".encode("utf-8")).hexdigest()


# ============================================================ the key

class KeyTests(EngineCase):

    def description(self, kind="plain", **changes):
        desc = {"id_version": 3, "run_version": 2, "kind": kind, "forge": "2.0.15", "format": "Constructed",
                "clock_s": 120, "seeds": forge.seeds.SCHEME if kind == "decklab" else "batch",
                "performance_mode": True, "game_patches": [], "overrides": self.fiery(),
                "sides": sorted([[self.a["card_sha"], "Default", self.ai_sha()],
                                 [self.b["card_sha"], "Default", self.ai_sha()]])}
        desc.update(changes)
        return desc

    def test_the_key_is_the_sha256_of_the_canonical_description(self):
        self.assertEqual(forge.matchup_key(self.a, self.b), canonical_sha(self.description()))
        self.assertEqual(forge.matchup_key(self.b, self.a), forge.matchup_key(self.a, self.b))
        self.assertEqual(forge.FORGE_RUN_VERSION, 2)
        # With the card log usable, the decklab kind's: a seed for each game, and the jar's game patches.
        with self.ready():
            self.assertEqual(forge.matchup_key(self.a, self.b), canonical_sha(self.description("decklab")))
        # v1's key (lists._key) is another: before wave 2, results were keyed by run_version 1.
        self.assertNotEqual(forge.lists._key(self.a, self.b, "2.0.15", 120), forge.matchup_key(self.a, self.b))

    def test_a_run_saves_under_the_key_with_its_description(self):
        result = self.run_matchup(200)
        self.assertEqual(result["key"], forge.matchup_key(self.a, self.b))
        self.assertEqual((result["run_version"], {k: v for k, v in result["engine"].items() if k != "overrides"}),
                         (2, {k: v for k, v in self.description().items() if k not in ("format", "sides", "overrides")}))
        # The result holds the whole description: its engine, its format, and each side's triple (the matchup's
        # overrides once the runner records them, engine.result_fields(eng, entries), wave 3's R).
        sides = [[s["card_sha"], s["ai"], s["ai_sha"]] for s in result["sides"]]
        self.assertEqual(canonical_sha({**result["engine"], "overrides": self.fiery(), "format": result["format"],
                                        "sides": sorted(sides)}), result["key"])
        self.assertEqual(forge.engine.result_fields(forge.engine.today(), [self.a, self.b])["engine"]["overrides"],
                         self.fiery())
        with self.card_log(), self.ready():
            logged = self.run_matchup(200)
            self.assertEqual((logged["engine"]["kind"], logged["key"]), ("decklab", forge.matchup_key(self.a, self.b)))
        self.assertNotEqual(logged["key"], result["key"])           # plain Forge's games are kept apart

    def test_every_setting_that_changes_games_changes_the_key(self):
        eng = forge.engine.current(forge.install._setup(), dict(CARD_LOG))
        key = forge.engine.key(self.a, self.b, eng)
        changed = {
            "game patches": dict(eng, game_patches=["attack-requirements-in-order-1"]),
            "Forge": dict(eng, forge="2.0.16"),
            "clock": dict(eng, clock_s=60),
            "PERFORMANCE_MODE": dict(eng, performance_mode=False),
            "run version": dict(eng, run_version=3),
            "overrides": dict(eng, deployed=dict(eng["deployed"], index={"Fiery Annihilation": "0" * 64})),
            "AI profile": dict(eng, ai_sha={"Default": "0" * 64}),
            "plain Forge": forge.engine.current(forge.install._setup(), {"ready": False}),
        }
        keys = {name: forge.engine.key(self.a, self.b, e) for name, e in changed.items()}
        for name, other in keys.items():
            with self.subTest(changed=name):
                self.assertNotEqual(other, key)
        self.assertEqual(len(set(keys.values())), len(keys))
        # The format and the lists too.
        gisa = entry(GISA, "commander/gisa", "commander")
        self.assertNotEqual(forge.engine.key(gisa, gisa, eng), forge.engine.key(self.a, self.a, eng))
        # Not what doesn't change games: the heap, the workers, the user folder's other preferences.
        setup = dict(forge.install._setup(), xmx="4096m", workers=1)
        self.assertEqual(forge.engine.key(self.a, self.b, forge.engine.current(setup, dict(CARD_LOG))), key)
        # Nor an override of a card in neither list, nor the folder's whole hash (wave 3: per-list overrides).
        other = dict(eng, overrides="0" * 64, deployed=dict(eng["deployed"], index={**eng["deployed"]["index"],
                                                                                    "Island": "1" * 64}))
        self.assertEqual(forge.engine.key(self.a, self.b, other), key)

    def test_each_side_keeps_its_own_ai_profile_paired(self):
        eng = forge.engine.current(forge.install._setup(), dict(CARD_LOG))
        eng = dict(eng, ai_sha={"Default": "d" * 64, "Reckless": "r" * 64})
        reckless = {"profile": "Reckless", "switches": []}
        mixed = forge.engine.key(dict(self.a, pilot=reckless), self.b, eng)
        other = forge.engine.key(self.a, dict(self.b, pilot=reckless), eng)
        self.assertNotEqual(mixed, other)       # A-Reckless v B-Default is not A-Default v B-Reckless
        self.assertEqual(forge.engine.key(self.b, dict(self.a, pilot=reckless), eng), mixed)
        # A stored side of wave 2's has its "ai" and no pilot.
        self.assertEqual(forge.engine.key({k: v for k, v in self.a.items() if k != "pilot"} | {"ai": "Reckless"},
                                          self.b, eng), mixed)

    def test_the_ai_profile_and_the_overrides_are_read_from_their_files(self):
        key = forge.matchup_key(self.a, self.b)
        self.ai_file.write_bytes(b"Name=Default\nMulliganThreshold=13\n")    # (another size: a cached SHA is kept by size and time)
        newer = forge.matchup_key(self.a, self.b)
        self.assertNotEqual(newer, key)
        # Line endings alone don't change it.
        self.ai_file.write_bytes(self.ai_file.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(forge.matchup_key(self.a, self.b), newer)
        # A card script in Forge's user folder's custom/cards is played over Forge's own: Deck Lab's folder holds
        # the adopted sets' (wave 3), and status() puts them back as they should be.
        cards_dir = forge.common._user_dir() / forge.engine.OVERRIDES
        self.assertEqual(sorted(p.name for p in cards_dir.iterdir()), ["fiery_annihilation.txt"])
        self.assertEqual(forge.engine.today()["overrides"], forge.engine._overrides(forge.common._user_dir()))
        (cards_dir / "fiery_annihilation.txt").write_text("Name:Fiery Annihilation\nA:changed\n", encoding="utf-8")
        (cards_dir / "stray.txt").write_text("Name:Grizzly Bears\n", encoding="utf-8")
        held = forge.engine.key(self.a, self.b, forge.engine._engine(
            "plain", "2.0.15", 120, [], forge.engine._deployed(forge.common._user_dir()), {"Default": self.ai_sha()},
            True))
        self.assertNotEqual(held, newer)                               # what's there is what's keyed
        self.assertEqual(forge.matchup_key(self.a, self.b), newer)      # and status() deployed the right files again
        self.assertEqual(sorted(p.name for p in cards_dir.iterdir()), ["fiery_annihilation.txt"])
        # A matchup without Fiery Annihilation has no overrides.
        self.assertEqual(forge.engine.key(self.b, self.b, forge.engine.today()),
                         canonical_sha(self.description(overrides="none", sides=[
                             [self.b["card_sha"], "Default", forge.engine.today()["ai_sha"]["Default"]]] * 2)))

    def test_keys_stay_while_forges_folder_cant_be_reached(self):
        key = forge.matchup_key(self.a, self.b)
        with self.ready():
            logged = forge.matchup_key(self.a, self.b)
            patches = forge.engine.today()["game_patches"]
        remembered = json.loads((forge.common.DATA_DIR / forge.engine.REMEMBERED).read_text(encoding="utf-8"))
        self.assertEqual(remembered["versions"]["2.0.15"],
                         {"last": CHECKED_BUILD, "builds": {CHECKED_BUILD: {"ai": {"Default": self.ai_sha()},
                                                                             "game_patches": patches,
                                                                             "engine_forge": "2.0.15"}}})
        # The drive isn't connected: the same keys, from what was read before.
        self.settings["forge_dir"] = str(self.tmp / "nowhere")
        self.assertEqual(forge.matchup_key(self.a, self.b), key)
        self.assertEqual(forge.engine.key(self.a, self.b, forge.engine.today("decklab")), logged)
        self.assertTrue(forge.engine.today()["complete"])
        # A new process: from the data folder.
        forge.engine._memory.clear()
        forge.install._known.clear()
        self.assertEqual(forge.matchup_key(self.a, self.b), key)
        # Nothing remembered (a data folder from before wave 2): the key can't be told.
        (forge.common.DATA_DIR / forge.engine.REMEMBERED).unlink()
        forge.engine._memory.clear()
        self.assertFalse(forge.engine.today()["complete"])

    def test_the_game_patches_a_run_plays_are_remembered_by_forge_build(self):
        forge.engine.current(forge.install._setup(), dict(CARD_LOG, game_patches=["b-1", "a-1"]))
        remembered = json.loads((forge.common.DATA_DIR / forge.engine.REMEMBERED).read_text(encoding="utf-8"))
        self.assertEqual(remembered["versions"]["2.0.15"]["builds"][CHECKED_BUILD]["game_patches"], ["a-1", "b-1"])
        # Another build of 2.0.15 is remembered on its own, and is the one used next.
        with mock.patch.object(forge.simjar, "forge_build", return_value="2.0.15-SNAPSHOT-10.02"):
            forge.engine.current(forge.install._setup(), dict(CARD_LOG, game_patches=[]))
        remembered = json.loads((forge.common.DATA_DIR / forge.engine.REMEMBERED).read_text(encoding="utf-8"))
        self.assertEqual(remembered["versions"]["2.0.15"]["last"], "2.0.15-SNAPSHOT-10.02")
        self.assertEqual(remembered["versions"]["2.0.15"]["builds"][CHECKED_BUILD]["game_patches"], ["a-1", "b-1"])
        self.settings["forge_dir"] = str(self.tmp / "nowhere")
        self.assertEqual(forge.engine.today("decklab")["game_patches"], [])

    def test_what_cant_be_read_for_a_moment_is_what_was_remembered(self):
        remembered = forge.common.DATA_DIR / forge.engine.REMEMBERED
        patch = {"forge/ai/X.class": "x-1"}         # a game patch in Forge's jar, as the fork's are
        with mock.patch.object(forge.simjar, "forge_patches", return_value=patch):
            eng = forge.engine.today("decklab")
        self.assertEqual((eng["game_patches"], eng["ai_sha"]), (["x-1"], {"Default": self.ai_sha()}))
        key = forge.engine.key(self.a, self.b, eng)
        noted = remembered.read_text(encoding="utf-8")
        # An antivirus scan holds Forge's jar and its AI profile: neither can be read, though the folder is there.
        forge.engine._ai_cache.clear()
        with mock.patch.object(forge.engine.zipfile, "ZipFile", side_effect=PermissionError("in use")), \
                mock.patch.object(forge.engine, "_file_sha", side_effect=PermissionError("in use")), \
                mock.patch.object(forge.common, "_log"):
            held = forge.engine.today("decklab")
            run = forge.engine.current(forge.install._setup(), dict(CARD_LOG, game_patches=["x-1"]))
        self.assertEqual((held["game_patches"], held["ai_sha"], held["complete"]), (["x-1"], eng["ai_sha"], True))
        self.assertEqual(forge.engine.key(self.a, self.b, held), key)
        self.assertEqual(forge.engine.key(self.a, self.b, run), key)
        self.assertEqual(remembered.read_text(encoding="utf-8"), noted)     # nothing that couldn't be read noted
        # The drive goes next: still the same key, from what was remembered.
        self.settings["forge_dir"] = str(self.tmp / "nowhere")
        self.assertEqual(forge.engine.key(self.a, self.b, forge.engine.today("decklab")), key)
        # Nothing read from a jar whose build can't be read is remembered (it may be one being replaced).
        self.settings["forge_dir"] = str(self.forge_dir)
        forge.engine._ai_cache.clear()
        self.addCleanup(forge.engine._ai_cache.clear)
        with mock.patch.object(forge.simjar, "forge_build", return_value=None), \
                mock.patch.object(forge.engine, "_file_sha", return_value="0" * 64):
            self.assertEqual(forge.engine.today("decklab")["ai_sha"], {"Default": "0" * 64})
        self.assertEqual(remembered.read_text(encoding="utf-8"), noted)

    def test_a_jar_where_no_patch_fits_has_none(self):
        # A readable jar without Deck Lab's list of changes (make_forge's: a manifest alone).
        self.assertEqual(forge.engine.today("decklab")["game_patches"], [])
        self.assertTrue(forge.engine.today("decklab")["complete"])
        noted = json.loads((forge.common.DATA_DIR / forge.engine.REMEMBERED).read_text(encoding="utf-8"))
        self.assertEqual(noted["versions"]["2.0.15"]["builds"][CHECKED_BUILD]["game_patches"], [])
        # Nothing ever read from the jar, and it can't be read: the decklab kind's key can't be told.
        forge.engine._memory.clear()
        (forge.common.DATA_DIR / forge.engine.REMEMBERED).unlink()
        with mock.patch.object(forge.engine.zipfile, "ZipFile", side_effect=PermissionError("in use")), \
                mock.patch.object(forge.common, "_log"), mock.patch.dict(forge.simjar._forge_patches, clear=True):
            forge.engine._jar_cache.clear()
            self.assertFalse(forge.engine.today("decklab")["complete"])
            self.assertTrue(forge.engine.today("plain")["complete"])

    def test_side_ids_are_a_lists_own_whatever_its_opponent(self):
        a_vs_b = self.run_matchup(200)
        gisa = entry(GISA, "commander/gisa", "commander")
        ids = forge.engine.side_ids(self.a["card_sha"], "constructed")
        side = next(s for s in a_vs_b["sides"] if s["card_sha"] == self.a["card_sha"])
        self.assertEqual(side["engine_id"], ids["plain"])
        self.assertNotEqual(ids["plain"], ids["decklab"])
        a_vs_a = self.run_matchup(200, b=self.a)
        self.assertEqual({s["engine_id"] for s in a_vs_a["sides"]}, {ids["plain"]})
        self.assertNotEqual(forge.engine.side_ids(gisa["card_sha"], "commander")["plain"],
                            forge.engine.side_ids(gisa["card_sha"], "constructed")["plain"])
        # The decklab kind's whatever the card log's state now: a run with the card log has it.
        with self.card_log():
            logged = self.run_matchup(200)
        self.assertEqual({s["engine_id"] for s in logged["sides"] if s["card_sha"] == self.a["card_sha"]},
                         {ids["decklab"]})

    def test_a_runs_sides_record_their_auto_profile(self):
        self.fake("avgcmc=4,2")
        with self.card_log():
            result = self.run_matchup(200, workers=1)
        # Seat 1 averaged 4 mana: Forge plays it as a slower, non-aggro deck. The first batch (one at a time) has
        # side 0 as deck 1.
        self.assertEqual([s["auto_profile"] for s in result["sides"]],
                         [{"flag": True, "avg_cmc": 4}, {"flag": False, "avg_cmc": 2}])
        self.assertEqual([s["ai"] for s in result["sides"]], ["Default", "Default"])
        self.assertEqual([s["deckorder"] for s in result["sides"]], [False, False])     # no deck-order-1 in the jar
        # Plain Forge doesn't say: nothing is recorded.
        plain = self.run_matchup(200)
        self.assertTrue(all("auto_profile" not in s for s in plain["sides"]))
        self.assertEqual(forge.engine.side_fields(forge.engine.today(), plain["sides"][0], {"autoprofile": "x"}),
                         {**{k: plain["sides"][0][k] for k in ("engine_id", "ai", "ai_sha")},
                          "pilot": {"profile": "Default", "switches": []}})


# ============================================================ the DLENGINE echo and PERFORMANCE_MODE

class EchoTests(EngineCase):

    def fake_echo(self, game_patches=True, patch_ids="a-1", card_log=True):
        """The DLENGINE fields of a v2 request the fake Forge plays with the user folder's preferences."""
        setup = forge.install._setup()
        env = forge.runner._prepare_user_dir(setup["user_dir"])
        folder = self.tmp / "decks"
        folder.mkdir(exist_ok=True)
        for e in (self.a, self.b):
            (folder / f"{e['card_sha']}.dck").write_text(e["dck"], encoding="utf-8")
        launch = dict(setup, decks_dir=folder, card_log=dict(CARD_LOG, game_patches=patch_ids.split(",") if patch_ids else []),
                      game_patches=game_patches)
        argv = test_forge.fake_command(launch, "Constructed", f"{self.a['card_sha']}.dck", f"{self.b['card_sha']}.dck", 2,
                                       1, {"stream": "0123456789abcdef", "first": 0, "card_log": card_log})
        done = subprocess.run(argv, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        reader = forge.LogReader(0)
        for line in done.stdout.splitlines():
            reader.feed(line)
        return reader.engine

    def test_forge_runs_with_performance_mode_on(self):
        self.assertEqual(forge.runner.PREFERENCES, "LOAD_CARD_SCRIPTS_LAZILY=true\nPERFORMANCE_MODE=true\n")
        user = self.tmp / "user"
        forge.runner._prepare_user_dir(user)
        prefs = user / "Forge" / "preferences" / "forge.preferences"
        self.assertEqual(prefs.read_text(encoding="utf-8").splitlines(),
                         ["LOAD_CARD_SCRIPTS_LAZILY=true", "PERFORMANCE_MODE=true"])
        self.assertIs(forge.engine.PERFORMANCE_MODE, True)
        self.assertIs(forge.engine.today()["performance_mode"], True)
        # Custom card scripts are Deck Lab's (wave 3): a worker's folder gets exactly the adopted sets' files.
        cards_dir = user / forge.engine.OVERRIDES
        (cards_dir / "x.txt").write_text("Name:X\n", encoding="utf-8")
        forge.runner._prepare_user_dir(user)
        self.assertEqual(sorted(p.name for p in cards_dir.iterdir()), ["fiery_annihilation.txt"])
        # The knob's folder (forge_performance_mode false) has PERFORMANCE_MODE off and the adopted sets.
        self.settings["forge_performance_mode"] = False
        setup = forge.install._setup()
        self.assertEqual(setup["user_dir"].parent.name, "users")
        forge.runner._prepare_user_dir(setup["user_dir"])
        self.assertIn("PERFORMANCE_MODE=false",
                      (setup["user_dir"] / "Forge" / "preferences" / "forge.preferences").read_text(encoding="utf-8"))
        self.assertIs(forge.engine.today()["performance_mode"], False)
        self.assertIs(forge.engine.current(setup, dict(CARD_LOG))["performance_mode"], False)
        self.assertEqual(forge.engine.today()["deployed"]["user_dir"], str(setup["user_dir"]))
        self.assertTrue((user / "Forge" / "preferences" / "forge.preferences").read_text(encoding="utf-8")
                        .endswith("PERFORMANCE_MODE=true\n"))     # the real folder's is left as it was
        # The knob's folder can't be made (sets.json unreadable): today() still answers, from the real folder.
        with mock.patch.object(forge.install, "_run_user_dir", side_effect=forge.common.ForgeError("no")):
            self.assertEqual(forge.engine.today()["deployed"]["user_dir"], str(forge.common._user_dir()))

    def test_a_chunk_is_checked_against_the_engine(self):
        eng = forge.engine.current(forge.install._setup(), dict(CARD_LOG, game_patches=["a-1"]))
        echo = self.fake_echo()
        self.assertEqual((echo["perf"], echo["seeds"], echo["gamepatches"], echo["gamepatchids"], echo["cardlog"]),
                         ("true", "game", "on", "a-1", "on"))
        self.assertIsNone(forge.engine.check_echo(eng, echo))
        cases = {
            "PERFORMANCE_MODE was off": dict(echo, perf="false"),
            "weren't played with a seed each": dict(echo, seeds="batch"),
            "game patches were off": self.fake_echo(game_patches=False),
            "other game patches (none)": self.fake_echo(patch_ids=""),
            "card log was off": self.fake_echo(card_log=False),
            "didn't say how it played": {},
        }
        for words, found in cases.items():
            with self.subTest(case=words):
                problem = forge.engine.check_echo(eng, found)
                self.assertIn(words, problem)
                self.assertTrue(problem.endswith("."))
        self.assertIn("other game patches (a-1) than the engine's (b-1)",
                      forge.engine.check_echo(dict(eng, game_patches=["b-1"]), echo))
        # The plain engine has no DLENGINE line to check.
        self.assertIsNone(forge.engine.check_echo(forge.engine.today("plain"), {}))


# ============================================================ consumers

class ViewTests(EngineCase):

    def test_a_result_from_before_wave_2_is_v1(self):
        old = stored([(0, "win", 0), (1, "win", 1)])
        self.assertEqual(forge.views._engine_view(old),
                         {"kind": "v1", "run_version": 1, "current": False, "words": forge.engine.V1_WORDS})
        self.assertEqual(forge.list_item(old)["engine"], forge.views._engine_view(old))
        self.assertEqual(forge.view(old, "a" * 64)["engine"]["kind"], "v1")

    def test_todays_result_and_an_earlier_engines(self):
        result = self.run_matchup(200)
        self.assertEqual(forge.view(result, self.a["card_sha"])["engine"],
                         {"kind": "plain", "run_version": 2, "current": True, "words": forge.engine.PLAIN_WORDS})
        # The card log becomes usable: plain Forge's result is an earlier engine's until it isn't again.
        with self.ready():
            found = forge.list_item(result)["engine"]
            self.assertEqual((found["kind"], found["current"]), ("plain", False))
            self.assertEqual(found["words"], "Played with an earlier engine (plain Forge, while the card log was off). "
                                             "Playing more starts a new result with today's engine.")
        with self.card_log(), self.ready():
            logged = self.run_matchup(200)
            self.assertEqual(forge.list_item(logged)["engine"],
                             {"kind": "decklab", "run_version": 2, "current": True, "words": None})
        self.assertFalse(forge.list_item(logged)["engine"]["current"])
        # Another clock, another Forge version: each says what changed.
        self.settings["forge_clock_s"] = 60
        self.assertIn("a 120-second time limit, not 60", forge.list_item(result)["engine"]["words"])
        self.settings["forge_clock_s"] = 120
        with zipfile.ZipFile(self.forge_dir / "forge-gui-desktop-2.0.16-jar-with-dependencies.jar", "w") as z:
            z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\nImplementation-Version: 2.0.16\r\n\r\n")
        self.assertIn("Forge 2.0.15, not 2.0.16", forge.list_item(result)["engine"]["words"])

    def test_a_result_whose_engine_cant_be_told(self):
        result = self.run_matchup(200)
        self.settings["forge_dir"] = str(self.tmp / "nowhere")
        (forge.common.DATA_DIR / forge.engine.REMEMBERED).unlink()
        (forge.common.DATA_DIR / forge.install.VERSION_FILE).unlink()
        forge.engine._memory.clear()
        forge.install._known.clear()
        self.assertEqual(forge.views._engine_view(result),
                         {"kind": "plain", "run_version": 2, "current": None, "words": None})
        # Settings that can't be read: logged, and the page still shows.
        with mock.patch.object(forge.engine, "today", side_effect=KeyError("forge_clock_s")), \
                mock.patch.object(forge.common, "_log") as log:
            self.assertEqual(forge.views._engine_view(result)["current"], None)
        self.assertIn("can't be worked out", log.call_args[0][0])

    def test_a_list_works_out_todays_engine_once(self):
        for clock in (120, 60):
            self.settings["forge_clock_s"] = clock
            self.run_matchup(200)
            self.run_matchup(200, b=self.a)
        with mock.patch.object(forge.install, "status", wraps=forge.install.status) as status:
            listed = forge.results(self.results)
        self.assertEqual(len(listed), 4)
        self.assertEqual(status.call_count, 1)
        self.assertEqual(sorted(item["engine"]["current"] for item in listed), [False, False, True, True])
        with mock.patch.object(forge.install, "status", wraps=forge.install.status) as status:
            self.assertEqual(len(forge.results_for(self.a["card_sha"], self.results)), 4)
        self.assertEqual(status.call_count, 1)

    def test_the_page_sides_say_the_auto_profile(self):
        self.fake("avgcmc=4,2")
        with self.card_log():
            result = self.run_matchup(200, workers=1)
        heavy = result["sides"][0]["card_sha"]
        item = forge.list_item(result, heavy)
        self.assertEqual([s["auto_profile"] for s in item["sides"]], [True, False])
        self.assertEqual([s["auto_profile"] for s in forge.list_item(result, result["sides"][1]["card_sha"])["sides"]],
                         [False, True])
        self.assertEqual([s["auto_profile"] for s in forge.list_item(stored([(0, "win", 0)]))["sides"]], [None, None])
        for odd in ({"flag": "yes"}, "on", None, {}):
            self.assertIsNone(forge.views._page_side(dict(result["sides"][0], auto_profile=odd))["auto_profile"])


class PoolingTests(EngineCase):
    """The deck page's per-card numbers and never-cast cards pool a list's sides of today's engine only."""

    def test_per_card_numbers_come_from_todays_card_log_engine_only(self):
        with self.card_log():
            logged = self.run_matchup(200)
        self.run_matchup(200)                                   # plain Forge (the card log is off for runs)
        old = stored([(0, "win", i % 2) for i in range(100)])   # before wave 2, as a saved file
        old["key"] = "e" * 64
        old["sides"][0]["card_sha"] = self.a["card_sha"]
        (self.results / f"{old['key']}.json").write_text(json.dumps(old), encoding="utf-8")
        stats = forge.list_cards(sections(GREEN), "constructed", results_dir=self.results)
        self.assertEqual((stats["games"], stats["of"], stats["matchups"], stats["other_engine_games"]),
                         (200, 200, 1, 300))
        self.assertEqual(stats, forge.list_cards(sections(GREEN), "constructed", [logged]) | {"other_engine_games": 300})
        # The same while the card log is usable or not: per-card data only ever comes from it.
        with self.ready():
            self.assertEqual(forge.list_cards(sections(GREEN), "constructed", results_dir=self.results), stats)
        # Only results of another engine (every list's, right after the engine changes, until replay): no numbers,
        # but stats saying how many games were left out, not None (which the page reads as "no game of this list
        # was played with the card log"), though the card log's result of an earlier engine has card data of its
        # own (its matchup page shows it).
        earlier = forge.load(logged["key"], self.results)
        for side in earlier["sides"]:
            side["engine_id"] = "e" * 64
        (self.results / f"{logged['key']}.json").write_text(json.dumps(earlier), encoding="utf-8")
        forge.saved._read_cache.clear()
        only = forge.list_cards(sections(GREEN), "constructed", results_dir=self.results)
        self.assertEqual((only["games"], only["of"], only["matchups"], only["old"], only["other_engine_games"]),
                         (0, 0, 0, 0, 500))
        self.assertEqual({row["drawn_games"] for row in only["rows"]}, {0})
        self.assertEqual(forge.side_cards(earlier, 0)["games"], 200)
        # No saved result of the list at all: None.
        self.assertIsNone(forge.list_cards(sections(GREEN.replace("4 Grizzly Bears", "3 Grizzly Bears")),
                                           "constructed", results_dir=self.results))
        # Results given are pooled as they are (and nothing is said of other engines).
        self.assertNotIn("other_engine_games", forge.list_cards(sections(GREEN), "constructed", [logged]))

    def test_never_cast_cards_are_judged_by_todays_engine(self):
        with self.card_log():
            self.run_matchup(200)
        self.run_matchup(200)
        old = stored([(0, "win", i % 2) for i in range(300)])
        old["key"] = "e" * 64
        old["sides"][0]["card_sha"] = self.a["card_sha"]
        (self.results / f"{old['key']}.json").write_text(json.dumps(old), encoding="utf-8")
        # The card log is off now: plain Forge's games count with the card log's, not v1's.
        limits = forge.list_ai(sections(GREEN), "constructed", self.results)
        self.assertEqual((limits["games"], limits["cannot_play"]),
                         (400, [{"name": "Fiery Annihilation", "qty": 1, "why": "never_cast"}]))
        self.assertEqual(limits["other_engine_games"], 300)    # left out, and said to be (so the page can say why)
        # On: the card log's only, with how often it was drawn.
        with self.ready():
            limits = forge.list_ai(sections(GREEN), "constructed", self.results)
        self.assertEqual((limits["games"], limits["other_engine_games"]), (200, 500))
        self.assertEqual([(c["name"], c["why"]) for c in limits["cannot_play"]], [("Fiery Annihilation", "never_cast")])
        self.assertIn("drawn_games", limits["cannot_play"][0])
        self.assertFalse(limits["other_engine_commander_unplayable"])      # a 60-card list has no commander

    def test_an_earlier_engines_commander_never_cast_is_said(self):
        # The deck page says what a list's earlier engine's games showed (its commander never cast) rather than
        # an all-clear, while today's engine hasn't played it (forge.list_ai's other_engine_commander_unplayable).
        # (A commander whose card script lets the AI cast it: Gisa's never does, whatever the games.)
        bears = sections("Commander\n1 Grizzly Bears\n\nDeck\n20 Forest\n")
        sha = forge.ai._list_text(forge.ai._section_cards(bears), "commander")[1]
        listed = {"Commander": [[1, "Grizzly Bears"]], "Main": [[20, "Forest"]]}
        old = stored([(0, "win", i % 2) for i in range(120)], cards_a=listed, kinds=("commander", "commander"))
        old["key"] = "e" * 64
        old["format"] = "Commander"
        old["sides"][0]["card_sha"] = sha
        self.results.mkdir(parents=True, exist_ok=True)
        (self.results / f"{old['key']}.json").write_text(json.dumps(old), encoding="utf-8")
        limits = forge.list_ai(bears, "commander", self.results)
        self.assertEqual((limits["games"], limits["other_engine_games"]), (0, 120))
        self.assertTrue(limits["other_engine_commander_unplayable"])
        # Cast in those games: nothing to say.
        old["batches"][0]["casts"] = [{"Grizzly Bears": [40, 40]}, {}]
        (self.results / f"{old['key']}.json").write_text(json.dumps(old), encoding="utf-8")
        self.assertFalse(forge.list_ai(bears, "commander", self.results)["other_engine_commander_unplayable"])


# ============================================================ the command line

class CommandLineTests(EngineCase):

    def setUp(self):
        super().setUp()
        from decklab.lib import inventory
        from decklab.lib.inventory.files import FileInventory
        # Keep alias reads isolated; restore the backend before ForgeCase deletes its folder.
        self.addCleanup(inventory.use(FileInventory(self.tmp)))
        summaries = [{"id": "casual/green", "title": "Green", "kind": "casual", "versions": ["target"]},
                     {"id": "casual/red", "title": "Red", "kind": "casual", "versions": ["target"]}]
        lists = {"casual/green": GREEN, "casual/red": RED}
        for p in (mock.patch.object(forge.cli.decks, "list_decks", return_value=summaries),
                  mock.patch.object(forge.cli.decks, "beginner_box_pairings", return_value=[]),
                  mock.patch.object(forge.cli.decks, "load_deck",
                                    side_effect=lambda deck_id, version: sections(lists[deck_id]))):
            p.start()
            self.addCleanup(p.stop)

    run_main = test_forge.CommandLineTests.run_main

    def play(self, *argv):
        return self.run_main("play", "casual/green", "casual/red", "--games", "200", "--results-dir",
                             str(self.results), *argv)

    def test_play_says_how_the_engine_played(self):
        code, out, _ = self.play()
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertIn(f"  ! {forge.engine.PLAIN_WORDS} {test_forge.NO_JDK}", lines)
        self.fake("avgcmc=2,4")
        with self.card_log(), self.ready():
            out = self.play("--workers", "1")[1]        # one batch at a time: the first, seat 2 averaging 4
        self.assertNotIn(forge.engine.PLAIN_WORDS, out)
        heavy = [line for line in out.splitlines() if "slower, non-aggro" in line]
        self.assertEqual(len(heavy), 1)
        # Forge's rule: its average (each different nonland card once, rounded down) over 3, so 4 or more.
        self.assertRegex(heavy[0], r"^  ! Forge's AI plays (Green|Red) as a slower, non-aggro deck in every game "
                                   r"\(Forge's auto-profile, for a deck whose nonland cards average 4 mana or more, "
                                   r"counting each different card once and rounding down; Forge's average for it is "
                                   r"4\)\.$")
        self.assertNotIn("over 3", out)
        self.assertNotIn("about 4", out)

    def test_cards_says_what_another_engine_played(self):
        with self.card_log():
            logged = self.run_matchup(200)
        self.run_matchup(200)                                   # plain Forge (the card log is off for runs)
        cards = lambda: self.run_main("cards", "casual/green", "--results-dir", str(self.results))[1]   # noqa: E731
        lines = cards().splitlines()
        self.assertTrue(lines[0].startswith("casual/green (target): card data from 200 of 200 games in 1 matchup"))
        self.assertEqual(lines[1], "  200 more of this list's games were played with an earlier engine, or without "
                                   "the card log, so they are left out (replay plays those matchups again with today's "
                                   "engine)")
        # Only another engine's games: why there are no numbers, and how to get some (not a table of 0s).
        earlier = forge.load(logged["key"], self.results)
        for side in earlier["sides"]:
            side["engine_id"] = "e" * 64
        (self.results / f"{logged['key']}.json").write_text(json.dumps(earlier), encoding="utf-8")
        forge.saved._read_cache.clear()
        self.assertEqual(cards(), "casual/green (target): card data from 0 of 0 games in 0 matchups\n"
                                  "  400 more of this list's games were played with an earlier engine, or without the "
                                  "card log, so they are left out (replay plays those matchups again with today's "
                                  "engine)\n"
                                  "  No per-card numbers yet: play more games, or replay those matchups, to get some.\n")

    def test_list_marks_results_of_another_engine(self):
        self.play()
        with self.card_log(), self.ready():
            self.play()
            old = stored([(0, "win", 0)] * 10)
            (self.results / f"{old['key']}.json").write_text(json.dumps(old), encoding="utf-8")
            out = self.run_main("list", "--results-dir", str(self.results))[1]
        lines = out.splitlines()
        self.assertEqual(sum(line.endswith("  [earlier engine: plain Forge]") for line in lines), 1)
        self.assertEqual(sum(line.endswith("  [earlier engine: v1]") for line in lines), 1)
        self.assertEqual(sum(line.endswith("by command line") for line in lines), 1)     # today's: no mark
        self.assertTrue(lines[-1].startswith("Results marked \"earlier engine\" were played with another engine"))
        # The card log off again: plain Forge's is today's, and the card log's an earlier engine's.
        lines = self.run_main("list", "--results-dir", str(self.results))[1].splitlines()
        self.assertEqual(sum(line.endswith("  [plain Forge]") for line in lines), 1)
        self.assertEqual(sum(line.endswith("  [earlier engine]") for line in lines), 1)


# ============================================================ the page

class PageTests(EngineCase):
    """matchups.js's engine parts, run under Node.js (test_web._run_page)."""

    def setUp(self):
        super().setUp()
        if not NODE:
            self.skipTest("Node.js isn't installed")

    def test_the_deck_page_says_what_another_engine_played(self):
        # list_cards' and list_ai's other_engine_games: right after the engine changes, a list's only card data is
        # in earlier engines' results, and the page mustn't say none of its games was played with the card log.
        stats = lambda **more: dict({"games": 0, "bad": 0, "old": 0, "of": 0, "matchups": 0, "enough": False,   # noqa: E731
                                     "min_games": 800, "min_split": 30, "basis": "drawn", "early_of": 0,
                                     "rows": [], "commander": []}, **more)
        current = {"results": [{"sides": [{"current": True}]}]}
        stub = "globalThis.cardLink = (entry) => el('span', {}, entry.name); "
        only, one, some, also_old, page = _run_page([
            f"cardStatsCoverage({json.dumps(stats(other_engine_games=3600))}, true)",
            f"cardStatsCoverage({json.dumps(stats(other_engine_games=1))}, true)",
            f"cardStatsCoverage({json.dumps(stats(games=400, of=400, matchups=1, enough=True, other_engine_games=3600))}, true)",
            f"cardStatsCoverage({json.dumps(stats(old=200, of=200, other_engine_games=3600))}, true)",
            f"{stub}deckCardStats({json.dumps(dict(current, cards=stats(other_engine_games=3600)))}, 'target list')"])
        self.assertEqual(only, "No per-card numbers yet.This list's 3,600 games were played with an earlier engine, or "
                               "without the card log, and these numbers count only today's engine's games. Play more "
                               "games, or replay those matchups with today's engine, to get some.")
        self.assertTrue(one.startswith("No per-card numbers yet.This list's 1 game was played with an earlier engine"), one)
        self.assertEqual(some, "From this list's 400 games, across 1 matchup, every one with card data. 3,600 more of "
                               "this list's games were played with an earlier engine, or without the card log, so "
                               "they're left out: replaying those matchups with today's engine plays them again.")
        self.assertTrue(also_old.endswith("Play more games to get some. 3,600 more were played with an earlier "
                                          "engine, or without the card log, so they're left out."), also_old)
        self.assertEqual(page, "How its cards played" + only)
        self.assertNotIn("played with the card log,", page)
        # The never-cast check (forge.list_ai) waits for today's engine's games, and says why with earlier ones.
        ai = {"cannot_play": [], "commander_unplayable": False, "team_pump": None, "pilot": None, "unknown": [],
              "problem": None}
        parts = lambda limits, deck_page=True: (f"aiLimitsParts({json.dumps(limits)}, 'A', "     # noqa: E731
                                                f"{{deckPage: {json.dumps(deck_page)}}}).map((n) => n.textContent)"
                                                ".join('|')")
        none, few, matchup, before = _run_page([parts(dict(ai, games=0, other_engine_games=3600)),
                                                parts(dict(ai, games=40, other_engine_games=1)),
                                                parts(dict(ai, games=40, other_engine_games=3600), False),
                                                parts(dict(ai, games=40))])
        self.assertTrue(none.endswith("|Cards it never casts show up here once this list has played 100 games with "
                                      "today's engine (3,600 more were played with an earlier engine, or without the "
                                      "card log, and don't count)."), none)
        self.assertTrue(few.endswith("|Cards it never casts show up here once this list has played 100 games with "
                                     "today's engine (40 so far; 1 more was played with an earlier engine, or without "
                                     "the card log, and doesn't count)."), few)
        self.assertTrue(matchup.endswith("|Cards it never casts show up here once this matchup has 100 games (40 so "
                                         "far)."), matchup)
        self.assertTrue(before.endswith("|Cards it never casts show up here once this list has played 100 games (40 "
                                        "so far)."), before)

    def test_rows_and_links_of_an_earlier_engine(self):
        side = {"id": "casual/a", "version": "target", "title": "A", "current": True}
        item = {"key": "k" * 64, "sides": [side, dict(side, id="casual/b", title="B")], "games": 10,
                "winrate": {"value": 0.5, "low": 0.4, "high": 0.6}, "by": "Matt", "updated": None}
        today = dict(item, engine={"kind": "decklab", "run_version": 2, "current": True, "words": None})
        earlier = dict(item, engine={"kind": "v1", "run_version": 1, "current": False, "words": "old"})
        calls = [f"itemHref({json.dumps(x)})" for x in (item, today, earlier)]
        calls += [f"resultRow({json.dumps(x)}, {{ engineTag: true }}).textContent" for x in (today, earlier)]
        calls += [f"resultRow({json.dumps(earlier)}).textContent",
                  f"allEarlierLine({json.dumps([earlier])}).children[0].textContent",
                  f"String(allEarlierLine({json.dumps([earlier, today])}))"]
        older, todays, earliers, row_today, row_earlier, untagged, line, none = _run_page(calls)
        self.assertEqual((older, todays), ("#/matchup?a=casual%2Fa&av=target&b=casual%2Fb&bv=target",) * 2)
        self.assertEqual(earliers, f"#/matchup?key={'k' * 64}")
        self.assertNotIn("Earlier engine", row_today)
        self.assertIn("Earlier engine", row_earlier)
        # While every result is an earlier engine's, rows carry no tag: one line above the list says it once.
        self.assertNotIn("Earlier engine", untagged)
        self.assertEqual(line, "Every result here was played with an earlier version of Forge's engine. Playing a "
                               "matchup again starts a new result with today's.")
        self.assertEqual(none, "null")
        # Said once: "Got it" dismisses it on this device, and then it isn't shown again (nor the pair page's
        # sentence under Play with today's engine).
        button, dismissed = _run_page([
            f"allEarlierLine({json.dumps([earlier])}).children[1].textContent",
            "(() => { const store = new Map(); window.localStorage = { getItem: (k) => store.has(k) ? store.get(k) : null,"
            " setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };"
            f" local.set(ENGINE_NOTE_KEY, '1'); return String(allEarlierLine({json.dumps([earlier])})); }})()"])
        self.assertEqual((button, dismissed), ("Got it", "null"))

    def test_how_the_games_were_played_by_engine(self):
        base = {"forge_version": "2.0.15", "games": 800, "seeds": 16, "runs": [], "settings": {"clock_s": 120}}
        decklab = dict(base, engine={"kind": "decklab", "run_version": 2, "current": True, "words": None})
        plain = dict(base, engine={"kind": "plain", "run_version": 2, "current": True, "words": None})
        v1 = dict(base, engine={"kind": "v1", "run_version": 1, "current": False, "words": "Played with v1."})
        data = {"format": "Constructed"}
        texts = _run_page([f"howPart({json.dumps(r)}, {json.dumps(data)}).textContent" for r in (decklab, plain, v1)]
                          + [f"playDrawPanel({json.dumps(r)}, 'A').textContent" for r in (decklab, v1)],
                          ("core.js", "stats.js", *MATCHUP_SCRIPTS))
        how_decklab, how_plain, how_v1, first_decklab, first_v1 = texts
        self.assertIn("Each game has its own random seed and a coin flip for who starts, and the decks swap seats "
                      "every 25 games.", how_decklab)
        self.assertIn("800 games so far.", how_decklab)
        self.assertNotIn("batches so far", how_decklab)
        self.assertIn("16 batches so far.", how_v1)
        self.assertIn("each batch has its own random seed, the loser of each game starts the next", how_v1)
        self.assertIn("Played with v1.", how_v1)
        self.assertIn("Played with plain Forge, as the card log couldn't be used.", how_plain)
        self.assertIn("A coin flip decides who goes first in each game", first_decklab)
        self.assertIn("the loser of each game goes first in the next one", first_v1)

    def test_the_auto_profile_and_earlier_results(self):
        side = {"id": "casual/a", "version": "target", "title": "A", "kind": "casual", "card_count": 60, "ai": None}
        on, off = _run_page([f"sideBox({json.dumps(dict(side, auto_profile=True))}, 0).textContent",
                             f"sideBox({json.dumps(dict(side, auto_profile=None))}, 0).textContent"])
        # Forge's rule is an average over 3 that counts each different nonland card once and rounds down: 4 or more.
        self.assertIn("Forge's AI plays this deck as a slower, non-aggro deck in every game: Forge does that for a "
                      "deck whose nonland cards average 4 mana or more (counting each different card once and "
                      "rounding down).", on)
        self.assertNotIn("over 3", on)
        self.assertNotIn("slower", off)
        self.assertEqual(forge.cli.AUTO_PROFILE_WORDS,
                         "Forge's AI plays this deck as a slower, non-aggro deck in every game")
        links = ("(function links(n) { return (n.tag === 'a' ? [n.getAttribute('href') + ' '"
                 " + (n.getAttribute('aria-label') || n.textContent)] : []).concat(...n.children.map(links)); })")
        cases = ([], ["a" * 64], ["a" * 64, "b" * 64])
        none, one, two = _run_page([f"earlierBox({json.dumps({'earlier': keys})})" for keys in cases])
        one_links, two_links = _run_page([f"{links}(earlierBox({json.dumps({'earlier': keys})})).join('|')"
                                          for keys in cases[1:]])
        self.assertEqual(none, "")
        self.assertEqual(one, "These two lists were played with an earlier engine (see that result); games played "
                              "now go into a new result with today's engine.")
        self.assertEqual(two, "These two lists were played with earlier engines (see results 1, 2); games played "
                              "now go into a new result with today's engine.")
        self.assertEqual(one_links, f"#/matchup?key={'a' * 64} see that result")
        self.assertEqual(two_links, f"#/matchup?key={'a' * 64} earlier result 1|#/matchup?key={'b' * 64} earlier result 2")

    def test_play_more_on_an_earlier_engines_result(self):
        side = {"id": "casual/a", "version": "target", "title": "A", "current": True}
        data = {"key": "k" * 64, "format": "Constructed", "sides": [side, dict(side, id="casual/b", title="B")],
                "choices": [200, 800], "default_games": 800, "status": "done",
                "result": {"engine": {"kind": "v1", "run_version": 1, "current": False, "words": "old"}}}
        text, = _run_page([f"actionsPart({{}}, {json.dumps(data)}).textContent"])
        self.assertIn("This result was played with an earlier engine. Playing more starts a new result with today's "
                      "engine; this one stays as it is.", text)
        self.assertIn("Play with today's engine", text)       # wave 3: an adaptive run by default (test_web)
        data["result"]["engine"]["current"] = True
        text, = _run_page([f"actionsPart({{}}, {json.dumps(data)}).textContent"])
        self.assertIn("Play more", text)
        self.assertNotIn("earlier engine", text)


# ============================================================ wave 3: id_version 2, pilots and per-list overrides

class Wave3KeyTests(EngineCase):
    """Engine id version 2 (sim-wave3-contract.md section 4): pilots in the sides, their sort, per-list overrides,
    plain-kind sides, side ids and the launch fields."""

    def eng(self, **changes):
        eng = forge.engine.current(forge.install._setup(), dict(CARD_LOG))
        return dict(eng, ai_sha={"Default": "d" * 64, "Reckless": "r" * 64}, **changes)

    def test_id_version_3_and_the_side_lists(self):
        eng = self.eng()
        self.assertEqual(eng["id_version"], 3)       # AI round 1: "forge" is the engine release
        self.assertEqual(forge.engine.side_list(self.a, eng), [self.a["card_sha"], "Default", "d" * 64])
        pumped = dict(self.a, pilot={"profile": "Reckless", "switches": ["team-pump-1"]})
        self.assertEqual(forge.engine.side_list(pumped, eng),
                         [self.a["card_sha"], "Reckless", "r" * 64, ["team-pump-1"]])
        # Deck Lab's own profiles: the repo file's SHA-256, always known.
        mine = dict(self.a, pilot={"profile": "DLAggro", "switches": []})
        self.assertEqual(forge.engine.side_list(mine, eng)[2], forge.pilots.profile_sha("DLAggro"))
        self.assertRegex(forge.pilots.profile_sha("DLAggro"), r"^[0-9a-f]{64}$")

    def test_a_pilot_mirror_has_one_order(self):
        eng = self.eng()
        plain = dict(self.a, pilot={"profile": "Default", "switches": []})
        pumped = dict(self.a, pilot={"profile": "Default", "switches": ["team-pump-1"]})
        key = forge.engine.key(plain, pumped, eng)
        self.assertEqual(forge.engine.key(pumped, plain, eng), key)
        sides = forge.engine.describe(eng, "Constructed", [forge.engine.side_list(pumped, eng),
                                                           forge.engine.side_list(plain, eng)])["sides"]
        self.assertEqual(sides, [forge.engine.side_list(plain, eng), forge.engine.side_list(pumped, eng)])  # shorter first
        self.assertNotEqual(key, forge.engine.key(plain, plain, eng))
        # An ai_sha None (a profile not known) never meets a string in the sort.
        unknown = dict(eng, ai_sha={})
        self.assertEqual(forge.engine.side_order([[self.a["card_sha"], "Default", "e" * 64],
                                                  [self.a["card_sha"], "Default", None]])[0][2], None)
        self.assertRegex(forge.engine.key(plain, dict(self.a, pilot={"profile": "Reckless", "switches": []}), unknown),
                         r"^[0-9a-f]{64}$")

    def test_plain_forge_sides_record_what_it_plays(self):
        plain = forge.engine.current(forge.install._setup(), {"ready": False})
        pilot = dict(self.a, pilot={"profile": "DLAggro", "switches": ["team-pump-1"]})
        self.assertEqual(forge.engine.side_list(pilot, plain), [self.a["card_sha"], "Default", plain["ai_sha"]["Default"]])
        self.assertEqual(forge.engine.side_fields(plain, dict(pilot, kind="constructed"), {})["pilot"],
                         {"profile": "Default", "switches": []})
        # plain Forge refuses nothing: it plays no switches.
        self.assertIsNone(forge.pilots.check_switches(plain, pilot["pilot"]))
        # The as-played pilot a request's -a and seat check take: never a Deck Lab profile under plain Forge.
        self.assertEqual(forge.engine.played_pilot(pilot, plain), {"profile": "Default", "switches": []})
        self.assertEqual(forge.engine.played_pilot(pilot, self.eng()), {"profile": "DLAggro", "switches": ["team-pump-1"]})

    def test_overrides_count_per_list(self):
        eng = self.eng()
        red_a = forge.engine.entry_side_id(self.b, eng=eng)
        green = forge.engine.entry_side_id(self.a, eng=eng)
        moved = dict(eng, deployed=dict(eng["deployed"], index={"Fiery Annihilation": "0" * 64}))
        self.assertEqual(forge.engine.entry_side_id(self.b, eng=moved), red_a)        # RED holds no Fiery Annihilation
        self.assertNotEqual(forge.engine.entry_side_id(self.a, eng=moved), green)
        self.assertNotEqual(forge.engine.key(self.a, self.b, moved), forge.engine.key(self.a, self.b, eng))
        self.assertEqual(forge.engine.key(self.b, self.b, moved), forge.engine.key(self.b, self.b, eng))
        # The deployed index is the run's folder's: an experiment arm's own.
        self.assertEqual(eng["deployed"]["user_dir"], str(forge.install._setup()["user_dir"]))
        self.assertEqual(sorted(eng["deployed"]["index"]), ["Fiery Annihilation"])
        self.assertEqual(forge.overrides.relevant_hash(eng["deployed"], ["fiery annihilation"]), self.fiery())
        self.assertEqual(forge.overrides.relevant_hash(eng["deployed"], ["Island"]), "none")
        # A folder that can't be read: no key claims to know.
        broken = dict(eng, deployed=dict(eng["deployed"], hash="unreadable"))
        self.assertEqual(forge.engine.describe(broken, "Constructed", [], [self.b])["overrides"], "unreadable")

    def test_side_ids_follow_the_pilot(self):
        self.run_matchup(200)           # writes the lists' .dck files, which side_ids reads without cards
        ids = forge.engine.side_ids(self.a["card_sha"], "constructed", cards=self.a["cards"])
        self.assertEqual(ids, forge.engine.side_ids(self.a["card_sha"], "constructed",
                                                    {"profile": "Default", "switches": []}, self.a["cards"]))
        pumped = forge.engine.side_ids(self.a["card_sha"], "constructed", {"profile": "Default", "switches": ["team-pump-1"]},
                                       self.a["cards"])
        self.assertNotEqual(pumped["decklab"], ids["decklab"])
        self.assertEqual(pumped["plain"], ids["plain"])            # plain Forge plays no switches
        self.assertEqual(forge.engine.entry_side_id(self.a, eng=forge.engine.today("decklab")), ids["decklab"])
        # Without the list's cards: from its .dck in the decks folder, which a run writes.
        self.assertEqual(forge.engine.side_ids(self.a["card_sha"], "constructed"), ids)

    def test_a_run_keys_and_records_its_pilots(self):
        result = self.run_matchup(200)
        self.assertEqual([s["pilot"] for s in result["sides"]], [{"profile": "Default", "switches": []}] * 2)
        self.assertTrue(forge.engine.is_current(result))
        self.assertEqual(forge.list_item(result, self.a["card_sha"])["sides"][0]["pilot"],
                         {"profile": "Default", "switches": [], "words": None})
        side = forge.views._page_side(dict(result["sides"][0], pilot={"profile": "Reckless", "switches": ["team-pump-1"]}))
        self.assertEqual(side["pilot"]["words"], "Forge's AI plays it with the Reckless profile and the team-pump fix")
        self.assertEqual(forge.views._page_side(dict(result["sides"][0], pilot=None, ai="DLTempo"))["pilot"]["words"],
                         "Forge's AI plays it with Deck Lab's DLTempo profile")

    def test_launch_fields(self):
        setup = forge.install._setup()
        eng = forge.engine.current(setup, dict(CARD_LOG))
        fields = forge.engine.launch_fields(setup, eng)
        self.assertEqual(fields, {"overrides": eng["deployed"]["hash"], "user_dir": str(setup["user_dir"]),
                                  "aiprofiles": setup["aiprofiles"].name, "performance_mode": True,
                                  "game_patches": True, "decision_log": None})
        self.assertRegex(fields["aiprofiles"], r"^[0-9a-f]{12}$")
        self.assertEqual(eng["deployed"]["hash"], forge.overrides.deployed_hash(setup["user_dir"]))
        self.settings["forge_game_patches"] = False
        off = forge.install._setup()
        self.assertIs(off["game_patches"], False)
        eng_off = forge.engine.current(off, dict(CARD_LOG, game_patches=["a-1"]))
        self.assertEqual(eng_off["game_patches"], [])
        self.assertIs(forge.engine.launch_fields(off, eng_off)["game_patches"], False)
        with self.assertRaisesRegex(ValueError, "needs Deck Lab's game patches on"):
            forge.pilots.check_switches(eng_off, {"profile": "Default", "switches": ["team-pump-1"]})
        self.assertIsNone(forge.pilots.check_switches(eng_off, {"profile": "Default", "switches": ["aisim-hybrid-1"]}))
        self.assertIsNone(forge.pilots.check_switches(dict(eng, game_patches=["a-1"]),
                                                      {"profile": "Default", "switches": ["team-pump-1"]}))


class Wave3EchoTests(EngineCase):
    """The echo checks wave 3 adds (section 4.4)."""

    ECHO = {"perf": "true", "seeds": "game", "gamepatches": "on", "gamepatchids": "", "cardlog": "on",
            "deckorder": "0,0", "loadseed": "0", "ai": "Default,Reckless", "pilots": "-,team-pump-1"}

    def setUp(self):
        super().setUp()
        self.eng = forge.engine.current(forge.install._setup(), dict(CARD_LOG))
        self.echo = dict(self.ECHO, overrides=self.eng["deployed"]["hash"])
        self.seats = [{"profile": "Default", "switches": []}, {"profile": "Reckless", "switches": ["team-pump-1"]}]

    def test_pilots_seat_by_seat(self):
        self.assertIsNone(forge.engine.check_echo(self.eng, self.echo, self.seats))
        self.assertIsNone(forge.engine.check_echo(self.eng, self.echo))              # wave 2's callers: not checked
        self.assertIn("other profiles (Default,Reckless) than the decks' pilots (Reckless,Default)",
                      forge.engine.check_echo(self.eng, self.echo, self.seats[::-1]))
        self.assertIn("other switches", forge.engine.check_echo(self.eng, dict(self.echo, pilots="-,-"), self.seats))

    def test_deck_order_and_load_seed_follow_the_engine(self):
        self.assertIn("in an order", forge.engine.check_echo(self.eng, dict(self.echo, deckorder="1,1")))
        self.assertIn("another seed", forge.engine.check_echo(self.eng, dict(self.echo, loadseed="1")))
        ordered = dict(self.eng, game_patches=["deck-order-1"])
        echo = dict(self.echo, gamepatchids="deck-order-1")
        self.assertIn("deck files' order", forge.engine.check_echo(ordered, echo))
        self.assertIn("deck files' order", forge.engine.check_echo(ordered, dict(echo, deckorder="1,0", loadseed="1")))
        self.assertIsNone(forge.engine.check_echo(ordered, dict(echo, deckorder="1,1", loadseed="1")))
        self.assertIn("another seed", forge.engine.check_echo(ordered, dict(echo, deckorder="1,1", loadseed="0")))

    def test_overrides_and_game_patches_off(self):
        self.assertEqual(forge.engine.check_echo(self.eng, dict(self.echo, overrides="none")),
                         "The card-script overrides changed while this run was playing: play it again.")
        # gamepatches=off: accepted exactly when the engine has no game patch (the forge_game_patches knob).
        self.assertIsNone(forge.engine.check_echo(self.eng, dict(self.echo, gamepatches="off")))
        # A real jar lists the copies it holds even with the knob off (GameLoop.gamePatchIds): the
        # overnight run's B7-off leg was refused on that before the ids were ignored when off.
        self.assertIsNone(forge.engine.check_echo(self.eng, dict(
            self.echo, gamepatches="off", gamepatchids="attack-requirements-in-order-1,deck-order-1")))
        patched = dict(self.eng, game_patches=["a-1"])
        self.assertIn("game patches were off",
                      forge.engine.check_echo(patched, dict(self.echo, gamepatches="off", gamepatchids="a-1")))

    def test_the_fake_echo_passes_with_and_without_deck_order(self):
        setup = forge.install._setup()
        env = forge.runner._prepare_user_dir(setup["user_dir"])
        folder = self.tmp / "decks"
        folder.mkdir(exist_ok=True)
        for e in (self.a, self.b):
            (folder / f"{e['card_sha']}.dck").write_text(e["dck"], encoding="utf-8")
        for patches in ([], ["deck-order-1"]):
            with self.subTest(patches=patches):
                log = dict(CARD_LOG, game_patches=patches, pilot_switches=["aisim-hybrid-1", "team-pump-1"])
                launch = dict(setup, decks_dir=folder, card_log=log)
                eng = forge.engine.current(setup, log)
                args = forge.runner.request_args(launch, "Constructed", f"{self.a['card_sha']}.dck",
                                                 f"{self.b['card_sha']}.dck", 2, 1,
                                                 {"stream": "0123456789abcdef", "first": 0}, pilots=self.seats)
                argv = [sys.executable, str(test_forge.FAKE), *args, "--card-log",
                        "--game-patch-ids=" + ",".join(patches), *test_forge._wave3_flags(launch)]
                done = subprocess.run(argv, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
                reader = forge.LogReader(0)
                for line in done.stdout.splitlines():
                    reader.feed(line)
                self.assertIsNone(forge.engine.check_echo(eng, reader.engine, self.seats), done.stdout[-500:])
                self.assertEqual(reader.engine["aiprofiles"], "dl")
                self.assertEqual(reader.engine["overrides"], eng["deployed"]["hash"])


class Wave3PageTests(EngineCase):
    """matchups.js's pilot words (wave 3, section 5.4), run under Node.js (test_web._run_page)."""

    def setUp(self):
        super().setUp()
        if not NODE:
            self.skipTest("Node.js isn't installed")

    def test_the_side_box_and_the_pilot_flag_say_the_pilot(self):
        words = "Forge's AI plays it with the Reckless profile and the team-pump fix"
        pilot = {"poor": True, "why": "share", "cards": [{"name": "X", "qty": 5, "why": ["etb"]}], "copies": 5,
                 "needed": 4, "team_pumps": 0, "team_pump_spells": 0, "counterspells": 0, "team_pump_fix": True}
        side, plain, reason, split = _run_page([
            f"pilotNote({json.dumps({'pilot': {'profile': 'Reckless', 'switches': ['team-pump-1'], 'words': words}})})"
            ".textContent",
            f"String(pilotNote({json.dumps({'pilot': {'profile': 'Default', 'switches': [], 'words': None}})}))",
            f"pilotReason({json.dumps(pilot)})",
            f"pumpSplit({json.dumps(dict(pilot, team_pumps=3, team_pump_spells=3))})"])
        self.assertEqual(side, words + ".")
        self.assertEqual(plain, "null")
        self.assertEqual(reason, "5 of its cards are kinds Forge's AI misplays (with Deck Lab's team-pump fix). Its "
                                 "win rates here are probably lower than the real deck's.")
        self.assertEqual(split, "3 spells")       # counts only: with the fix no team pumps are counted



# ============================================================ AI round 1: the engine release

class EngineReleaseTests(EngineCase):
    """AI round 1 (the ai-r1 contract's D1, section 3.6): the description's "forge" is the engine release
    (install.engine_forge), id_version 3, so two builds of the fork that play the same games share keys."""

    RES = "0123456789ab" + "c" * 52

    def build_file(self, **lines):
        """Write the install folder's decklab-build.txt (None: remove it)."""
        path = self.forge_dir / forge.install.BUILD_FILE
        forge.install._build_infos.clear()
        if lines.get("remove"):
            path.unlink(missing_ok=True)
            return
        path.write_text("".join(f"{k}={v}\n" for k, v in lines.items()), encoding="utf-8")

    def key(self, log=None):
        eng = forge.engine.current(forge.install._setup(), dict(CARD_LOG, **(log or {})))
        return forge.engine.key(self.a, self.b, eng), eng

    def test_id_version_3(self):
        self.assertEqual(forge.engine.ID_VERSION, 3)
        self.assertEqual(self.key()[1]["id_version"], 3)

    def test_the_release_rules(self):
        jar = "forge-gui-desktop-2.0.15-jar-with-dependencies.jar"
        self.assertEqual(forge.install.release_of(jar), "2.0.15")
        self.assertIsNone(forge.install.release_of("forge.jar"))
        # Stock Forge: no decklab-build.txt, the jar name's release.
        self.assertEqual(forge.install.build_info(self.forge_dir), {})
        self.assertEqual(forge.install.engine_forge(self.forge_dir, jar), "2.0.15")
        self.assertEqual(forge.install._setup()["engine_forge"], "2.0.15")
        # A fork build from before AI round 1 (no res_sha256=): its whole build name.
        self.build_file(build="2.0.15-decklab-d84031a6d", commit="d84031a6d", base="forge-2.0.15", scripts_changed=2)
        self.assertEqual(forge.install.engine_forge(self.forge_dir, jar), "2.0.15-decklab-d84031a6d")
        # From AI round 1 on: base='s release and the res files' hash; base= wins over the jar name.
        self.build_file(build="2.0.15-decklab-aaa", base="forge-2.0.16", res_sha256=self.RES)
        self.assertEqual(forge.install.engine_forge(self.forge_dir, jar), "2.0.16+res.0123456789ab")
        self.build_file(build="2.0.15-decklab-aaa", res_sha256=self.RES)
        self.assertEqual(forge.install.engine_forge(self.forge_dir, jar), "2.0.15+res.0123456789ab")
        # A file there that lacks what's needed, or can't be read: unknown, never the jar name's.
        self.build_file(commit="aaa")
        self.assertIsNone(forge.install.engine_forge(self.forge_dir, jar))
        self.build_file(remove=True)
        (self.forge_dir / forge.install.BUILD_FILE).mkdir()
        self.assertIsNone(forge.install.build_info(self.forge_dir))
        self.assertIsNone(forge.install.engine_forge(self.forge_dir, jar))

    def test_two_builds_that_play_the_same_share_keys(self):
        stock, _ = self.key()
        self.build_file(build="2.0.15-decklab-aaa", commit="aaa", base="forge-2.0.15", res_sha256=self.RES)
        aaa, eng = self.key()
        self.assertEqual(eng["forge"], "2.0.15+res.0123456789ab")
        self.build_file(build="2.0.15-decklab-bbb", commit="bbb", base="forge-2.0.15", res_sha256=self.RES)
        with mock.patch.object(forge.simjar, "forge_build", return_value="2.0.15-decklab-bbb"):
            bbb, _ = self.key()
        self.assertEqual(bbb, aaa)
        # Another res hash, or another game patch: another key.
        self.build_file(build="2.0.15-decklab-ccc", base="forge-2.0.15", res_sha256="f" * 64)
        self.assertNotEqual(self.key()[0], aaa)
        self.build_file(build="2.0.15-decklab-aaa", base="forge-2.0.15", res_sha256=self.RES)
        self.assertNotEqual(self.key({"game_patches": ["gisa-bontu-1"]})[0], aaa)
        self.assertNotEqual(aaa, stock)
        # An old fork build keeps a key of its own, never stock Forge's.
        self.build_file(build="2.0.15-decklab-d84031a6d", base="forge-2.0.15")
        old, eng = self.key()
        self.assertEqual(eng["forge"], "2.0.15-decklab-d84031a6d")
        self.assertNotEqual(old, stock)
        # Duplicate game-patch ids (several classes, one id) are one.
        self.assertEqual(self.key({"game_patches": ["b-1", "a-1", "b-1"]})[1]["game_patches"], ["a-1", "b-1"])

    def test_a_build_file_that_cant_be_read(self):
        self.build_file(build="2.0.15-decklab-aaa", base="forge-2.0.15", res_sha256=self.RES)
        key, _ = self.key()
        self.assertEqual(forge.engine.today()["forge"], "2.0.15+res.0123456789ab")
        self.build_file(remove=True)
        (self.forge_dir / forge.install.BUILD_FILE).mkdir()
        # Remembered for this version and build: the same key, and today's is complete.
        self.assertEqual(self.key()[0], key)
        self.assertEqual(forge.engine.today()["forge"], "2.0.15+res.0123456789ab")
        self.assertTrue(forge.engine.today()["complete"])
        # Nothing remembered: a run refuses rather than guess, and a page can't tell.
        (forge.common.DATA_DIR / forge.engine.REMEMBERED).unlink()
        forge.engine._memory.clear()
        with self.assertRaises(forge.ForgeError) as caught:
            self.key()
        self.assertEqual(str(caught.exception), forge.engine.CANT_KEY)
        self.assertIn("decklab-build.txt can't be read", str(caught.exception))
        self.assertFalse(forge.engine.today()["complete"])

    def test_engine_check_notes_nothing(self):
        for name in (forge.engine.REMEMBERED, forge.install.VERSION_FILE):
            (forge.common.DATA_DIR / name).unlink(missing_ok=True)
        forge.engine._memory.clear()
        forge.install._known.clear()
        setup = forge.install._setup(forge_dir=self.forge_dir, remember=False)
        eng = forge.engine.current(setup, dict(CARD_LOG), remember=False)
        self.assertEqual(eng["forge"], "2.0.15")
        for name in (forge.engine.REMEMBERED, forge.install.VERSION_FILE):
            self.assertFalse((forge.common.DATA_DIR / name).exists(), name)
        # A run's setup and engine do note them.
        forge.engine.current(forge.install._setup(), dict(CARD_LOG))
        for name in (forge.engine.REMEMBERED, forge.install.VERSION_FILE):
            self.assertTrue((forge.common.DATA_DIR / name).exists(), name)

    def test_game_patches_on_and_switches(self):
        _, eng = self.key({"pilot_switches": ["aisim-hybrid-1", "etb-harmless-1", "team-pump-1"]})
        self.assertIs(eng["game_patches_on"], True)
        self.assertEqual(eng["switches"], ["aisim-hybrid-1", "etb-harmless-1", "team-pump-1"])
        self.assertNotIn("switches", self.key()[1])        # a card log that doesn't say
        plain = forge.engine.current(forge.install._setup(), {"ready": False})
        self.assertEqual(plain["switches"], [])
        self.settings["forge_game_patches"] = False
        off = forge.engine.current(forge.install._setup(), dict(CARD_LOG, game_patches=["a-1"]))
        self.assertEqual((off["game_patches_on"], off["game_patches"]), (False, []))
        with self.assertRaisesRegex(ValueError, r"optional-target fix \(etb-harmless-1\) needs Deck Lab's game"):
            forge.pilots.check_switches(off, {"profile": "Default", "switches": ["etb-harmless-1"]})

    def test_a_fork_switch_enters_a_side_only_through_its_pilot(self):
        key, eng = self.key({"pilot_switches": ["etb-harmless-1"]})
        # The switches a build has don't change a key...
        self.assertEqual(forge.engine.key(self.a, self.b, dict(eng, switches=[])), key)
        # ...a pilot naming one does, for its own side only.
        fixed = dict(self.a, pilot={"profile": "Default", "switches": ["etb-harmless-1"]})
        self.assertNotEqual(forge.engine.key(fixed, self.b, eng), key)
        self.assertEqual(forge.engine.side_list(fixed, eng)[3], ["etb-harmless-1"])
