"""Tests for decklab.lib.forge's card-script overrides (simulation wave 3's R10,
forge-trial/sim-wave3-contract.md section 6): sets.json and its checks, making the files from
Forge's cardsfolder.zip, deploying (deleting other files, writing only what differs, the upstream
check and its cache), ensure_deployed (the lock, a manifest folder, the real folder), user_dir_for
(the experiment and knob folders), the per-list hash, the ai.py overlay and the command line.

They use test_forge.py's made-up Forge folder, whose cardsfolder.zip holds the fixture scripts
(fixtures/forge/cardscripts: fiery_annihilation.txt is Forge 2.0.15's own, so the adopted
"fiery" set fits it), and ForgeCase's pinned override sets (test_forge.OVERRIDE_SETS, in which
only "fiery" is adopted); SetsTests.test_the_repos_sets checks the repo's own sets.

Run from the repo root: python scripts/test_fixtures.py
"""
import hashlib
import json
import os
import shutil
import sys
import zipfile
from unittest import mock

from decklab.lib import forge
from decklab.lib.forge import overrides
from decklab.tests import test_forge
from decklab.tests.test_forge import GREEN, RED, entry, sections

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

REPO_SETS = overrides.SETS_DIR      # the repo's sets (ForgeCase points SETS_DIR at test_forge.OVERRIDE_SETS)


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class OverridesCase(test_forge.ForgeCase):

    def setUp(self):
        super().setUp()
        self.forge_dir = self.tmp / "forge"
        test_forge.make_forge(self.forge_dir)
        self.settings["forge_dir"] = str(self.forge_dir)
        overrides._upstream_memory.clear()
        overrides._ensured.clear()
        self.addCleanup(overrides._upstream_memory.clear)
        self.addCleanup(overrides._ensured.clear)
        self.user = forge.common._user_dir()
        self.cards = self.user / overrides.CUSTOM_CARDS

    def repo_sets(self, sets):
        """A sets.json of the test's own (and its files' folder): sets as given."""
        folder = self.tmp / "sets"
        folder.mkdir(exist_ok=True)
        (folder / "sets.json").write_text(json.dumps({"version": 1, "forge": "2.0.15", "sets": sets}), encoding="utf-8")
        test_forge.pin_override_sets(self, folder)
        return folder

    def fixture_script(self, path):
        return (test_forge.HERE / "cardscripts" / path).read_bytes()

    def remove_set(self, status="experiment", upstream=None, edits=None):
        return {"status": status, "why": "", "files": {"devout_decree.txt": {
            "card": "Devout Decree", "upstream_sha256": upstream if upstream is not None
            else sha(self.fixture_script("d/devout_decree.txt")),
            "edits": edits or [["AI:RemoveDeck:All\n", ""]], "cast_target": 0.5}}}


class SetsTests(OverridesCase):

    PINNED_SETS = ("fiery", "etb", "etb-flagged", "tgt", "tgt-gift", "remove", "flash", "hints")

    def check_sets(self, names=PINNED_SETS):
        """The sets SETS_DIR holds: each file is its card's script with its edits, made from Forge's."""
        data = overrides.load_sets()
        self.assertEqual(list(data["sets"]), list(names))
        for name, found in data["sets"].items():
            for file_name, info in found["files"].items():
                with self.subTest(file=f"{name}/{file_name}"):
                    text = (overrides.SETS_DIR / name / file_name).read_text(encoding="utf-8")
                    self.assertEqual(overrides._script_name(text), info["card"])
                    self.assertRegex(info["upstream_sha256"], r"^[0-9a-f]{64}$")
                    for _, new in info["edits"]:
                        self.assertIn(new, text)
        self.assertEqual(data["sets"]["fiery"]["files"]["fiery_annihilation.txt"]["upstream_sha256"],
                         sha(self.fixture_script("f/fiery_annihilation.txt")))

    def test_the_repos_sets(self):
        # The repo's own sets, not the pinned copy every other test reads.
        test_forge.pin_override_sets(self, REPO_SETS)
        self.check_sets(self.PINNED_SETS + ("etb-tfp", "etb-tfp-jailer", "cmdr-hints"))     # AI round 1's experiments
        self.assertEqual(overrides.adopted(), ["fiery", "remove"])      # remove adopted 2026-10-04

    def test_the_tests_pinned_sets(self):
        # ForgeCase's pinned copy of the repo's sets: only "fiery" adopted, whatever the repo adopts later.
        self.assertEqual((overrides.SETS_DIR, overrides.SETS_FILE),
                         (test_forge.OVERRIDE_SETS, test_forge.OVERRIDE_SETS / "sets.json"))
        self.check_sets()
        self.assertEqual(overrides.adopted(), ["fiery"])

    def test_bad_sets_are_refused(self):
        good = {"version": 1, "sets": {"x": self.remove_set()}}
        self.assertIs(overrides._check_sets(good), good)
        bad = {
            "status": {"version": 1, "sets": {"x": dict(self.remove_set(), status="maybe")}},
            "edits": {"version": 1, "sets": {"x": self.remove_set(edits=[["", "x"]])}},
            "upstream": {"version": 1, "sets": {"x": self.remove_set(upstream="abc")}},
            "version": {"version": 2, "sets": {}},
        }
        for name, data in bad.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                overrides._check_sets(data)

    def test_make_from_forges_scripts(self):
        folder = self.repo_sets({"remove": self.remove_set(upstream="")})
        self.assertEqual(overrides.make(), {"remove": ["devout_decree.txt"]})
        made = (folder / "remove" / "devout_decree.txt").read_text(encoding="utf-8")
        self.assertEqual(made, self.fixture_script("d/devout_decree.txt").decode("utf-8").replace("AI:RemoveDeck:All\n", ""))
        self.assertEqual(json.loads((folder / "sets.json").read_text(encoding="utf-8"))["sets"]["remove"]["files"]
                         ["devout_decree.txt"]["upstream_sha256"], sha(self.fixture_script("d/devout_decree.txt")))
        self.assertEqual(overrides.check(), [])
        # An edit whose old text isn't in Forge's script exactly once: loud, naming the card, nothing written.
        self.repo_sets({"remove": self.remove_set(edits=[["No such text", ""]])})
        (folder / "remove" / "devout_decree.txt").unlink()
        with self.assertRaisesRegex(ValueError, "^Devout Decree: an edit's old text"):
            overrides.make(["remove"])
        self.assertFalse((folder / "remove" / "devout_decree.txt").exists())
        self.assertTrue(any("is missing" in p for p in overrides.check()))
        # The command line.
        code, out, _ = test_forge.CommandLineTests.run_main(self, "overrides", "make", "--set", "remove")
        self.assertEqual(code, 1)


class DeployTests(OverridesCase):

    def test_the_real_folder_gets_the_adopted_sets(self):
        (self.cards / "old").mkdir(parents=True)
        (self.cards / "old" / "stray.txt").write_text("Name:Grizzly Bears\n", encoding="utf-8")
        (self.cards / "notes.md").write_text("x", encoding="utf-8")
        found = overrides.ensure_deployed(self.user)
        self.assertEqual(sorted(p.relative_to(self.cards).as_posix() for p in self.cards.rglob("*")),
                         ["fiery_annihilation.txt"])
        repo = overrides.SETS_DIR / "fiery" / "fiery_annihilation.txt"
        self.assertEqual((self.cards / "fiery_annihilation.txt").read_bytes(), repo.read_bytes())
        self.assertEqual(found, {"index": {"Fiery Annihilation": sha(repo.read_bytes())},
                                 "hash": forge.engine._overrides(self.user)})
        self.assertEqual(found["hash"], overrides.deployed_hash(self.user))
        # Written only when it differs.
        stamp = (self.cards / "fiery_annihilation.txt").stat().st_mtime_ns
        overrides._ensured.clear()
        overrides.ensure_deployed(self.user)
        self.assertEqual((self.cards / "fiery_annihilation.txt").stat().st_mtime_ns, stamp)
        # The upstream cache: per Forge version and build.
        cache = json.loads((forge.common.DATA_DIR / overrides.UPSTREAM_FILE).read_text(encoding="utf-8"))
        self.assertEqual(cache["versions"]["2.0.15"]["builds"][test_forge.CHECKED_BUILD],
                         {"Fiery Annihilation": sha(self.fixture_script("f/fiery_annihilation.txt"))})

    def test_a_later_set_wins_and_deploy_names_the_file(self):
        found = overrides.deploy(self.tmp / "u", ["etb", "etb-flagged"])
        self.assertEqual(found["files"].get("Fires of Mount Doom"), None)    # not in the made-up Forge's scripts
        chosen = overrides._chosen(["etb", "etb-flagged"])
        self.assertEqual(chosen["Fires of Mount Doom"][0], "etb-flagged")
        self.assertEqual(overrides._chosen(["etb-flagged", "etb"])["Fires of Mount Doom"][0], "etb")
        with self.assertRaisesRegex(ValueError, "no override set called nope"):
            overrides.deploy(self.tmp / "u", ["nope"])

    def test_an_override_that_doesnt_fit_forge_isnt_deployed(self):
        self.repo_sets({"fiery": dict(self.remove_set("adopted"), files={"fiery_annihilation.txt": {
            "card": "Fiery Annihilation", "upstream_sha256": "0" * 64, "edits": [["x", "y"]], "cast_target": None}})})
        with mock.patch.object(forge.common, "_log") as log:
            found = overrides.deploy(self.user)
        self.assertEqual((found["deployed"], found["stale"], found["hash"]), ([], ["Fiery Annihilation"], "none"))
        self.assertIn("doesn't fit this Forge's script", log.call_args[0][0])
        self.assertEqual(overrides.stale(), ["Fiery Annihilation"])
        self.assertEqual(forge.install.status()["overrides"]["stale"], ["Fiery Annihilation"])

    def test_forges_scripts_that_cant_be_read(self):
        overrides.ensure_deployed(self.user)
        before = overrides.deployed_hash(self.user)
        # The zip can't be read now: what was read for this build is used, and nothing changes.
        overrides._ensured.clear()
        with mock.patch.object(overrides, "_zip_scripts", side_effect=OSError("in use")):
            self.assertEqual(overrides.ensure_deployed(self.user)["hash"], before)
        # Nothing ever read (a fresh data folder) and Forge away: the folder is left as it is.
        (forge.common.DATA_DIR / overrides.UPSTREAM_FILE).unlink()
        overrides._upstream_memory.clear()
        overrides._ensured.clear()
        (self.cards / "stray.txt").write_text("Name:Grizzly Bears\n", encoding="utf-8")
        self.settings["forge_dir"] = str(self.tmp / "nowhere")
        with mock.patch.object(forge.common, "_log"):
            found = overrides.deploy(self.user)
        self.assertEqual(found["unknown"], ["Fiery Annihilation"])
        self.assertTrue((self.cards / "stray.txt").exists())

    def test_the_check_of_a_staged_build_reads_its_scripts(self):
        """upgrade-check --dir (E11-S45): check(forge_dir) reads that build's cardsfolder.zip, not
        the installed one's, and writes nothing."""
        fiery = overrides.load_sets()["sets"]["fiery"]
        folder = self.repo_sets({"fiery": fiery})       # only the set whose script the fixture Forge has
        shutil.copytree(test_forge.OVERRIDE_SETS / "fiery", folder / "fiery")
        self.assertEqual(overrides.check(), [])
        staged = self.tmp / "staged"
        test_forge.make_forge(staged)
        self.assertEqual(overrides.check(staged), [])
        # The staged build's Fiery Annihilation changed upstream: only its check says so.
        with zipfile.ZipFile(staged / forge.SCRIPTS_ZIP, "w") as z:
            z.writestr("f/fiery_annihilation.txt", self.fixture_script("f/fiery_annihilation.txt") + b"# 2.0.16\n")
        upstream = forge.common.DATA_DIR / overrides.UPSTREAM_FILE
        before = upstream.read_bytes() if upstream.exists() else None
        problems = overrides.check(staged)
        self.assertEqual(len(problems), 1)
        self.assertIn("Fiery Annihilation (fiery): Forge's script isn't the one the override was made from", problems[0])
        self.assertEqual(overrides.check(), [])
        self.assertEqual(upstream.read_bytes() if upstream.exists() else None, before)
        # No Forge in the staged folder: said with that folder, not config's.
        nowhere = self.tmp / "nowhere"
        nowhere.mkdir()
        self.assertIn(f"Forge isn't installed at {nowhere}.", overrides.check(nowhere))

    def test_the_lock_is_one_process_at_a_time(self):
        forge.common.DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(forge.common.DATA_DIR / overrides.LOCK_FILE, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0))
        self.addCleanup(os.close, fd)
        if sys.platform == "win32":
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with mock.patch.object(overrides, "LOCK_WAIT_S", 0.3), mock.patch.object(forge.common, "_log") as log:
            found = overrides.ensure_deployed(self.user)
        self.assertEqual(found["hash"], "none")           # left as it was
        self.assertIn("couldn't be checked", log.call_args[0][0])
        if sys.platform == "win32":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertNotEqual(overrides.ensure_deployed(self.user)["hash"], "none")

    def test_an_interrupted_wait_gives_the_lock_back(self):
        # Not only OSError: a thread interrupted while it waits (a patched sleep raising, an
        # interrupt) mustn't leave this process's later deploys waiting forever.
        forge.common.DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(forge.common.DATA_DIR / overrides.LOCK_FILE, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0))
        self.addCleanup(os.close, fd)
        if sys.platform == "win32":
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with mock.patch.object(overrides.time, "sleep", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            overrides.ensure_deployed(self.user)
        self.assertFalse(overrides._deploy_lock.locked())
        if sys.platform == "win32":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertNotEqual(overrides.ensure_deployed(self.user)["hash"], "none")

    def test_experiment_and_knob_folders(self):
        folder = overrides.user_dir_for(["fiery", "remove"])
        self.assertEqual(folder.parent, forge.common.DATA_DIR / "users")
        self.assertRegex(folder.name, r"^exp-[0-9a-f]{12}$")
        self.assertEqual(overrides.manifest(folder), {"sets": ["fiery", "remove"], "performance_mode": True})
        self.assertEqual(overrides.user_dir_for(["fiery", "remove"]), folder)
        self.assertNotEqual(overrides.user_dir_for(["remove", "fiery"]), folder)
        knob = overrides.user_dir_for(["fiery"], performance_mode=False)
        self.assertNotEqual(knob, overrides.user_dir_for(["fiery"]))
        with self.assertRaises(ValueError):
            overrides.user_dir_for(["nope"])
        # A manifest folder gets exactly its sets; a worker started there keeps them (runner._prepare_user_dir).
        (folder / overrides.CUSTOM_CARDS).mkdir(parents=True)
        (folder / overrides.CUSTOM_CARDS / "x.txt").write_text("Name:X\n", encoding="utf-8")
        forge.runner._prepare_user_dir(folder)
        self.assertEqual(sorted(overrides.deployed_index(folder)), ["Devout Decree", "Fiery Annihilation"])
        self.assertNotIn("AI:RemoveDeck:All",
                         (folder / overrides.CUSTOM_CARDS / "devout_decree.txt").read_text(encoding="utf-8"))
        forge.runner._prepare_user_dir(knob)
        self.assertIn("PERFORMANCE_MODE=false",
                      (knob / "Forge" / "preferences" / "forge.preferences").read_text(encoding="utf-8"))
        # A run's engine keys by its own folder's files.
        eng = forge.engine.current(dict(forge.install._setup(), user_dir=folder), dict(test_forge.CARD_LOG))
        self.assertEqual(eng["deployed"]["user_dir"], str(folder))
        self.assertEqual(eng["deployed"]["hash"], overrides.deployed_hash(folder))

    def test_a_sets_change_is_followed_at_once(self):
        a, b = entry(GREEN), entry(RED)
        key = forge.matchup_key(a, b)
        self.assertEqual(sorted(overrides.deployed_index(self.user)), ["Fiery Annihilation"])
        data = overrides.load_sets()
        data = json.loads(json.dumps(data))
        data["sets"]["fiery"]["status"] = "experiment"
        folder = self.repo_sets(data["sets"])
        shutil.copytree(test_forge.OVERRIDE_SETS, folder, dirs_exist_ok=True)
        (folder / "sets.json").write_text(json.dumps(data), encoding="utf-8")
        forge.install._status = None
        self.assertNotEqual(forge.matchup_key(a, b), key)
        self.assertEqual(overrides.deployed_index(self.user), {})
        self.assertEqual(forge.matchup_key(b, b), forge.engine.key(b, b, forge.engine.today()))


class HashTests(OverridesCase):

    def test_relevant_hash(self):
        deployed = {"index": {"Fiery Annihilation": "a" * 64, "Éowyn, Fearless Knight": "b" * 64}}
        self.assertEqual(overrides.relevant_hash(deployed, []), "none")
        self.assertEqual(overrides.relevant_hash(deployed, ["Fiery Annihilation"]),
                         sha(f"Fiery Annihilation\n{'a' * 64}\n".encode("utf-8")))
        both = overrides.relevant_hash(deployed, ["eowyn, fearless knight", "Fiery Annihilation", "Island"])
        self.assertEqual(both, sha(f"Fiery Annihilation\n{'a' * 64}\nÉowyn, Fearless Knight\n{'b' * 64}\n".encode("utf-8")))

    def test_the_hash_is_engines_and_ignores_line_endings(self):
        self.cards.mkdir(parents=True)
        (self.cards / "a.txt").write_bytes(b"Name:A\r\nx\r\n")
        lf = overrides.deployed_hash(self.user)
        self.assertEqual(lf, forge.engine._overrides(self.user))
        (self.cards / "a.txt").write_bytes(b"Name:A\nx\n")
        forge.engine._override_cache.clear()
        self.assertEqual(overrides.deployed_hash(self.user), lf)
        self.assertEqual(overrides.deployed_index(self.user), {"A": sha(b"Name:A\nx\n")})


class OverlayTests(OverridesCase):

    def test_a_deployed_script_takes_forges_place_for_the_ai(self):
        red = forge.ai_limits(sections(RED), "constructed")
        self.assertEqual(red["cannot_play"], [{"name": "Devout Decree", "qty": 1, "why": "script"}])
        self.cards.mkdir(parents=True)
        (self.cards / "devout_decree.txt").write_bytes(
            self.fixture_script("d/devout_decree.txt").replace(b"AI:RemoveDeck:All\n", b""))
        self.assertEqual(forge.ai_limits(sections(RED), "constructed")["cannot_play"], [])
        index = forge.install.script_index()
        self.assertIn("Devout Decree", index["remove_all"])          # the cached index itself isn't changed
        self.assertNotIn("Devout Decree", overrides.overlay_index(index)["remove_all_set"])
        self.assertNotIn("devout decree", forge.ai.weak_cards())
        # A team pump fixed by its pilot isn't counted (team-pump-1, TeamPumpAi).
        green = forge.ai_limits(sections(GREEN), "constructed")["pilot"]
        fixed = forge.ai_limits(sections(GREEN), "constructed", pilot={"profile": "Default",
                                                                       "switches": ["team-pump-1"]})["pilot"]
        self.assertGreater(green["team_pumps"], 0)
        self.assertEqual((fixed["team_pumps"], fixed["team_pump_fix"], green["team_pump_fix"]), (0, True, False))


class CommandLineTests(OverridesCase):

    run_main = test_forge.CommandLineTests.run_main

    def test_overrides_commands(self):
        code, out, _ = self.run_main("overrides", "deploy")
        self.assertEqual(code, 0)
        self.assertIn("deployed: Fiery Annihilation", out)
        self.assertIn(f"hash: {overrides.deployed_hash(self.user)}", out)
        code, out, _ = self.run_main("overrides", "list")
        self.assertIn("fiery [adopted]: Fiery Annihilation", out)
        code, out, _ = self.run_main("overrides", "deploy", "--user-dir", str(self.tmp / "u"), "--sets", "fiery",
                                     "--json")
        self.assertEqual(json.loads(out)["deployed"], ["Fiery Annihilation"])
        code, out, err = self.run_main("overrides", "deploy", "--sets", "nope")
        self.assertEqual(code, 1)
        # Named sets without --user-dir go into their own experiment folder (section 6.2), never
        # into the real run folder, which keeps exactly the adopted sets.
        before = overrides.deployed_hash(self.user)
        code, out, _ = self.run_main("overrides", "deploy", "--sets", "remove", "--json")
        self.assertEqual(code, 0)
        found = json.loads(out)
        folder = overrides.user_dir_for(["remove"], performance_mode=True)
        self.assertEqual((found["user_dir"], found["deployed"]), (str(folder), ["Devout Decree"]))
        self.assertEqual(sorted(overrides.deployed_index(folder)), ["Devout Decree"])
        self.assertEqual(overrides.deployed_hash(self.user), before)
        code, out, err = self.run_main("overrides", "deploy", "--user-dir", str(self.user), "--sets", "remove")
        self.assertEqual(code, 1)
        self.assertIn("holds only the adopted override sets", err)
        self.assertEqual(overrides.deployed_hash(self.user), before)
        code, out, _ = self.run_main("status")
        self.assertIn("card-script overrides: Fiery Annihilation", out)
