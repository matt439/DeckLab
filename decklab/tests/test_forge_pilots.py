"""Tests for decklab.lib.forge's pilots (simulation wave 3's R16, forge-trial/sim-wave3-contract.md
section 5): decklab/simulation.json read and checked (a bad entry left out whole), each list's
pilot on its entry, check_switches, the words, Deck Lab's AI profiles and their folder for Java,
the request's -a and -dlpilot (runner.request_args), and the pilots command.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import json
from unittest import mock

from decklab.lib import forge
from decklab.lib.forge import pilots
from decklab.tests import test_forge
from decklab.tests.test_forge import GREEN, entry

SWITCHES = {"team-pump-1": "decklab/TeamPumpAi.class", "aisim-hybrid-1": "decklab/GameLoop.class"}


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


class PilotsCase(test_forge.ForgeCase):

    def setUp(self):
        super().setUp()
        self.forge_dir = self.tmp / "forge"
        test_forge.make_forge(self.forge_dir)
        (self.forge_dir / "res" / "ai").mkdir(parents=True)
        for name in ("Default", "Reckless", "Cautious", "Experimental"):
            (self.forge_dir / "res" / "ai" / f"{name}.ai").write_text(f"# {name}\nPLAY_AGGRO=false\n", encoding="utf-8")
        self.settings["forge_dir"] = str(self.forge_dir)
        self.file = self.tmp / "simulation.json"
        for p in (mock.patch.object(pilots, "SIMULATION_FILE", self.file),
                  mock.patch.object(forge.simjar, "PILOT_SWITCHES", dict(SWITCHES), create=True)):
            p.start()
            self.addCleanup(p.stop)
        pilots._loaded.clear()
        self.addCleanup(pilots._loaded.clear)

    def write(self, lists, default=None):
        pilots_part = {"lists": lists}
        if default is not None:
            pilots_part["default"] = default
        self.file.write_text(json.dumps({"version": 1, "pilots": pilots_part, "field": {}}), encoding="utf-8")
        pilots._loaded.clear()


class LoadTests(PilotsCase):

    def test_the_shipped_file_has_only_the_adopted_pilots(self):
        # AI round 1's one adoption (2026-10-21): The Free Peoples with the optional-target fix.
        shipped = json.loads((forge.lists.config.DECKLAB / "simulation.json").read_text(encoding="utf-8"))
        self.assertEqual(shipped["pilots"], {"default": {"profile": "Default"}, "lists": {
            "casual/the-free-peoples": {"profile": "Default", "switches": ["etb-harmless-1"]}}})

    def test_resolution(self):
        self.write({"casual/rabbits": {"profile": "Reckless", "switches": ["team-pump-1"]},
                    "casual/rabbits@owned": {"profile": "DLAggro"}})
        self.assertEqual(pilots.pilot_for("casual/rabbits", "target"), {"profile": "Reckless", "switches": ["team-pump-1"]})
        self.assertEqual(pilots.pilot_for("casual/rabbits", "owned"), {"profile": "DLAggro", "switches": []})
        self.assertEqual(pilots.pilot_for("casual/other", "target"), {"profile": "Default", "switches": []})
        self.assertEqual(pilots.problems(), [])
        # Entries carry it; .dck files have the default.
        with mock.patch.object(forge.lists, "_source", return_value=None):
            self.assertEqual(entry(GREEN, "casual/rabbits")["pilot"], {"profile": "Reckless", "switches": ["team-pump-1"]})
            self.assertEqual(entry(GREEN, "casual/rabbits", version="owned")["pilot"]["profile"], "DLAggro")
        # A change of the file is read at once (its modification time).
        self.write({})
        self.assertEqual(pilots.pilot_for("casual/rabbits", "target")["profile"], "Default")

    def test_a_bad_entry_is_left_out_whole(self):
        self.write({"casual/a": {"profile": "Nobody"}, "casual/b": {"profile": "Reckless", "switches": ["warp-9"]},
                    "casual/c@sideboard": {"profile": "Reckless"}, "casual/d": "Reckless",
                    "casual/e": {"profile": "Reck|less"}, "casual/f": {"profile": "Cautious", "switches": []}})
        with mock.patch.object(forge.common, "_log") as log:
            problems = pilots.problems()
        self.assertEqual(len(problems), 5)
        self.assertEqual(log.call_count, 5)
        self.assertEqual(pilots.pilot_for("casual/b", "target"), {"profile": "Default", "switches": []})
        self.assertEqual(pilots.pilot_for("casual/f", "target")["profile"], "Cautious")
        # The command: --check exits 1.
        code, out, _ = test_forge.CommandLineTests.run_main(self, "pilots", "--check")
        self.assertEqual(code, 1)
        self.assertIn("casual/f: Forge's AI plays it with the Cautious profile", out)
        self.assertIn("DLAggro (Deck Lab's)", out)
        code, out, _ = test_forge.CommandLineTests.run_main(self, "pilots", "--json")
        self.assertEqual((code, json.loads(out)["available"]["switches"]),
                         (0, ["aisim-hybrid-1", "etb-harmless-1", "prowess-precombat-1", "removal-in-combat-1",
                              "team-pump-1"]))
        # A file that can't be read: every list plays with the default pilot, and it's said.
        self.file.write_text("{", encoding="utf-8")
        pilots._loaded.clear()
        with mock.patch.object(forge.common, "_log"):
            self.assertEqual(pilots.pilot_for("casual/f", "target")["profile"], "Default")
            self.assertEqual(len(pilots.problems()), 1)

    def test_words(self):
        self.assertIsNone(pilots.words({"profile": "Default", "switches": []}))
        self.assertIsNone(pilots.words(None))
        self.assertEqual(pilots.words({"profile": "Reckless", "switches": ["team-pump-1"]}),
                         "Forge's AI plays it with the Reckless profile and the team-pump fix")
        self.assertEqual(pilots.words({"profile": "DLAggro", "switches": ["aisim-hybrid-1", "team-pump-1"]}),
                         "Forge's AI plays it with Deck Lab's DLAggro profile, the look-ahead AI (experimental) and "
                         "the team-pump fix")
        self.assertEqual(pilots.words({"profile": "Default", "switches": ["team-pump-1"]}),
                         "Forge's AI plays it with the team-pump fix")

    def test_check_switches(self):
        decklab = {"kind": "decklab", "game_patches": ["attack-requirements-in-order-1"]}
        pumped = {"profile": "Default", "switches": ["team-pump-1"]}
        self.assertIsNone(pilots.check_switches(decklab, pumped))
        with self.assertRaisesRegex(ValueError, r"^The team-pump fix \(team-pump-1\) needs Deck Lab's game patches on"):
            pilots.check_switches(dict(decklab, game_patches=[]), pumped)
        self.assertIsNone(pilots.check_switches(dict(decklab, game_patches=[]),
                                                {"profile": "Default", "switches": ["aisim-hybrid-1"]}))

    def test_fork_switches(self):
        """AI round 1: simulation.json may name the fork's switches; a run refuses one its build lacks, and any
        fork switch with game patches off (the setup's knob, eng["game_patches_on"])."""
        self.assertEqual(pilots.FORK_SWITCHES, ("etb-harmless-1", "prowess-precombat-1", "removal-in-combat-1"))
        self.write({"casual/izzet": {"profile": "Default", "switches": ["prowess-precombat-1"]},
                    "casual/tfp": {"profile": "Default", "switches": ["etb-harmless-1", "removal-in-combat-1"]}})
        self.assertEqual(pilots.problems(), [])
        self.assertEqual(pilots.pilot_for("casual/tfp", "target")["switches"], ["etb-harmless-1", "removal-in-combat-1"])
        self.assertEqual(pilots.words({"profile": "Default", "switches": ["removal-in-combat-1"]}),
                         "Forge's AI plays it with the combat-removal fix")
        fixed = {"profile": "Default", "switches": ["etb-harmless-1"]}
        has = {"kind": "decklab", "game_patches": [], "game_patches_on": True,
               "switches": ["aisim-hybrid-1", "etb-harmless-1", "team-pump-1"]}
        self.assertIsNone(pilots.check_switches(has, fixed))    # no game-changing patch, but patches on
        with self.assertRaisesRegex(ValueError, r"^This Forge build doesn't have the optional-target fix "
                                                r"\(etb-harmless-1\), so this run wasn't started\.$"):
            pilots.check_switches(dict(has, switches=["aisim-hybrid-1", "team-pump-1"]), fixed)
        with self.assertRaisesRegex(ValueError, r"^The optional-target fix \(etb-harmless-1\) needs Deck Lab's game "
                                                r"patches on"):
            pilots.check_switches(dict(has, game_patches=["deck-order-1"], game_patches_on=False), fixed)
        # An engine from before AI round 1 (no game_patches_on, no switches): as before.
        self.assertIsNone(pilots.check_switches({"kind": "decklab", "game_patches": ["a-1"]}, fixed))
        # Plain Forge plays no switches: nothing to refuse.
        self.assertIsNone(pilots.check_switches({"kind": "plain", "game_patches": [], "switches": []}, fixed))


class ProfileFolderTests(PilotsCase):

    def test_the_mirror(self):
        setup = forge.install._setup()
        folder = setup["aiprofiles"]
        self.assertEqual(folder, pilots.profile_folder(setup))
        self.assertEqual(folder.parent, forge.common.DATA_DIR / "ai-profiles")
        self.assertRegex(folder.name, r"^[0-9a-f]{12}$")
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["Cautious.ai", "DLAggro.ai", "DLControl.ai", "DLTempo.ai", "Default.ai", "Experimental.ai",
                          "Reckless.ai"])
        self.assertEqual((folder / "DLControl.ai").read_bytes(), (pilots.PROFILES_DIR / "DLControl.ai").read_bytes())
        # Another of Forge's profiles: another folder.
        (self.forge_dir / "res" / "ai" / "Reckless.ai").write_text("# changed\n", encoding="utf-8")
        self.assertNotEqual(pilots.profile_folder(setup), folder)
        # No profiles in Forge's folder: none.
        self.assertIsNone(pilots.profile_folder(dict(setup, forge_dir=self.tmp / "nowhere")))
        # DeckLabSim's launches get the flag; plain Forge's don't.
        java = forge.runner._java(dict(setup, card_log=dict(test_forge.CARD_LOG)))
        self.assertIn(f"-Ddecklab.aiprofiles={folder}", java)
        self.assertFalse([a for a in forge.runner._java(setup) if a.startswith("-Ddecklab.aiprofiles")])

    def test_deck_labs_profiles_are_full_copies_of_default(self):
        default_keys = None
        for path in sorted(pilots.PROFILES_DIR.glob("*.ai")):
            keys = [line.split("=", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()
                    if line and not line.startswith("#")]
            with self.subTest(profile=path.stem):
                self.assertEqual(len(keys), 121)
                if default_keys is not None:
                    self.assertEqual(keys, default_keys)
                default_keys = keys
        self.assertIn("MIN_SPELL_CMC_TO_COUNTER=2", (pilots.PROFILES_DIR / "DLControl.ai").read_text(encoding="utf-8"))


class RequestTests(PilotsCase):

    SETUP = {"decks_dir": "C:/decks", "clock_s": 120}
    V2 = {"stream": "0123456789abcdef", "first": 25}

    def test_pilots_on_the_request(self):
        args = forge.runner.request_args(self.SETUP, "Constructed", "a.dck", "b.dck", 25, 1, self.V2,
                                         pilots=[{"profile": "Reckless", "switches": []},
                                                 {"profile": "DLAggro", "switches": ["team-pump-1", "aisim-hybrid-1"]}])
        self.assertEqual(args[args.index("-a"):args.index("-a") + 3], ["-a", "Reckless", "DLAggro"])
        self.assertEqual(args[args.index("-dlpilot"):], ["-dlpilot", "-", "aisim-hybrid-1+team-pump-1"])
        self.assertEqual(args.index("-dlpilot"), args.index("-dlgame") + 3)
        # No switch: no -dlpilot (a wave 2 request).
        plain = forge.runner.request_args(self.SETUP, "Constructed", "a.dck", "b.dck", 25, 1, self.V2,
                                          pilots=[{"profile": "Default", "switches": []}] * 2)
        self.assertEqual(plain, forge.runner.request_args(self.SETUP, "Constructed", "a.dck", "b.dck", 25, 1, self.V2))
        # v1 takes profiles only.
        v1 = forge.runner.request_args(self.SETUP, "Constructed", "a.dck", "b.dck", 25, 1,
                                       pilots=[{"profile": "Reckless", "switches": []}, {"profile": "Default"}])
        self.assertEqual(v1[v1.index("-a"):], ["-a", "Reckless", "Default"])
        for bad in ([{}, {}], [{"profile": "A,B"}] * 2, [{"profile": "Default", "switches": ["x|y"]}] * 2,
                    [{"profile": "Default"}]):
            with self.subTest(pilots=bad), self.assertRaises(ValueError):
                forge.runner.request_args(self.SETUP, "Constructed", "a.dck", "b.dck", 25, 1, self.V2, pilots=bad)
        with self.assertRaises(ValueError):
            forge.runner.request_args(self.SETUP, "Constructed", "a.dck", "b.dck", 25, 1,
                                      pilots=[{"profile": "Default", "switches": ["team-pump-1"]}] * 2)
