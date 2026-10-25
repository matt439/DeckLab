"""Forge models tests; shared fixtures remain in test_forge."""
import unittest
import hashlib
import json
import subprocess
import zipfile
from unittest import mock
from decklab.lib import cards, config, decks, forge, gitops, inventory
from decklab.lib.inventory.files import FileInventory
from decklab.tests.test_forge import (
    ForgeCase, GISA, GREEN, RED, entry,
    make_forge, read_log, sections, setUpModule, stored,
    tearDownModule,
)


class DckTests(ForgeCase):

    def test_dck_is_sorted_name_only_front_faces_merged_without_sideboard(self):
        e = entry(GREEN)
        self.assertEqual(e["dck"].splitlines(), [
            "[metadata]", f"Name={e['card_sha'][:12]}", "[Main]",
            "1 Fiery Annihilation", "6 Forest", "2 Giant Growth", "2 Glorious Anthem", "4 Grizzly Bears",
            "4 Llanowar Elves", "2 Overrun", "1 Rabbit Response"])
        self.assertEqual(e["card_count"], 22)       # the sideboard's 2 Lightning Bolt aren't played
        red = entry(RED)
        self.assertIn("2 Fire", red["dck"].splitlines())                # split card: its front face
        self.assertIn("2 Murderous Rider", red["dck"].splitlines())     # adventure: its front face

    def test_card_sha_is_the_card_lines_only_and_ignores_the_list_order(self):
        e = entry(GREEN)
        card_text = e["dck"].split("\n", 2)[2]          # without [metadata] and Name=
        self.assertEqual(e["card_sha"], hashlib.sha256(card_text.encode("utf-8")).hexdigest())
        shuffled = "Deck\n6 Forest\n1 Rabbit Response\n4 Llanowar Elves\n2 Overrun\n4 Grizzly Bears\n" \
                   "2 Giant Growth\n1 Fiery Annihilation\n2 Glorious Anthem\n"
        self.assertEqual(entry(shuffled)["card_sha"], e["card_sha"])
        self.assertNotEqual(entry(GREEN.replace("6 Forest", "7 Forest"))["card_sha"], e["card_sha"])

    def test_commander_decks_get_a_commander_section_constructed_ones_dont(self):
        e = entry(GISA, "commander/gisa", "commander")
        self.assertEqual(e["dck"].splitlines()[2:], ["[Commander]", "1 Ghoulcaller Gisa", "[Main]",
                                                     "4 Murderous Rider", "10 Swamp"])
        self.assertEqual(e["card_count"], 15)
        as_constructed = entry(GISA, "product/x", "constructed")
        self.assertEqual(as_constructed["dck"].splitlines()[2:], ["[Main]", "1 Ghoulcaller Gisa",
                                                                  "4 Murderous Rider", "10 Swamp"])
        self.assertNotEqual(as_constructed["card_sha"], e["card_sha"])

    def test_entry_keeps_the_scryfall_names_and_the_ids(self):
        e = entry(GREEN, "casual/green", version="owned", title="Green")
        self.assertEqual((e["id"], e["version"], e["title"], e["kind"]), ("casual/green", "owned", "Green", "constructed"))
        self.assertIn([2, "Overrun"], e["cards"]["Main"])
        self.assertEqual(e["cards"]["Commander"], [])
        self.assertIsNone(e["source"])          # no such deck file

    def deck_inventory(self):
        """The files backend's inventory (in self.tmp) with one deck: its id. The files backend keeps
        no revisions, so the deck's source is None."""
        repo = self.tmp / "repo"
        path = repo / "magic" / "decks" / "casual" / "green.md"
        path.parent.mkdir(parents=True)
        path.write_bytes(("# Green\n\n- **Status:** idea\n\n## Decklist\n\n```\n" + GREEN + "```\n").encode())
        p = mock.patch.object(decks, "DECKS_DIR", repo / "magic" / "decks")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(inventory.use(FileInventory(repo)))      # the decks are the inventory's
        return "casual/green"

    def dck_repo(self):
        """A git repo (in self.tmp) with one committed .dck file, which config.REPO and gitops.REPO
        name: the file's path. Never the live checkout."""
        repo = self.tmp / "repo"
        path = repo / "decklab" / "forge-trial" / "green.dck"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"[metadata]\nName=Green\n[Main]\n4 Llanowar Elves\n20 Forest\n")
        for args in (("init", "-q"), ("config", "user.name", "T"), ("config", "user.email", "t@example.com"),
                     ("add", "-A"), ("commit", "-qm", "green")):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
        for p in (mock.patch.object(config, "REPO", repo.resolve()), mock.patch.object(gitops, "REPO", repo)):
            p.start()
            self.addCleanup(p.stop)
        forge.lists._sources.clear()
        self.addCleanup(forge.lists._sources.clear)
        return path

    def test_a_deck_ids_source_never_asks_git(self):
        deck_id = self.deck_inventory()
        with mock.patch.object(gitops, "run", side_effect=AssertionError("git ran")):
            self.assertIsNone(forge._source(deck_id))
            self.assertIsNone(forge._source("casual/no-such-deck"))
            self.assertIsNone(forge.entry(deck_id, "target", "X", "constructed", sections(GREEN))["source"])

    def test_a_dck_files_source_names_the_file_and_its_commit(self):
        path = self.dck_repo()
        e = forge.entry_from_dck(path)
        self.assertEqual(e["id"], "file:decklab/forge-trial/green.dck")
        source = e["source"]
        self.assertEqual(source["file"], "decklab/forge-trial/green.dck")
        self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")
        self.assertIs(source["dirty"], False)
        path.write_bytes(path.read_bytes() + b"1 Overrun\n")
        self.assertIs(forge.entry_from_dck(path)["source"]["dirty"], True)

    def test_a_product_or_pairing_source_is_its_product_and_the_inventory_revision(self):
        from decklab.lib import inventory
        from decklab.tests import pre_db
        real = pre_db.inventory()         # the real product lists, at tag pre-db-inventory (git runs here)
        with mock.patch.object(gitops, "run", side_effect=AssertionError("git ran")), \
                inventory.use(real), inventory.pinned() as current:
            snapshot = current()
            revision = snapshot.revision
            self.assertEqual(forge._source("pairing/cats+elves"),
                             {"product": "fdn-beginner-box", "revision": revision})
            self.assertEqual(forge._source("product/fdn-beginner-box/cats"),
                             {"product": "fdn-beginner-box", "revision": revision})
            self.assertIsNone(forge._source("product/no-such-product"))
        preview = snapshot.replace(revision=revision + inventory.PREVIEW)
        with inventory.pinned(preview):          # a preview's revision is never named
            self.assertIsNone(forge._source("pairing/cats+elves"))

    def test_a_dck_files_source_is_none_when_git_fails(self):
        path = self.dck_repo()
        with mock.patch.object(gitops, "run", side_effect=gitops.GitError("missing", "git isn't installed")):
            self.assertIsNone(forge._source(None, path))
            self.assertIsNone(forge.entry_from_dck(path)["source"])

    def test_card_sha_alone_needs_no_git(self):
        with mock.patch.object(gitops, "run", side_effect=AssertionError("git ran")):
            self.assertEqual(forge.card_sha(sections(GREEN), "constructed"), entry(GREEN)["card_sha"])
            self.assertEqual(forge.card_sha(sections(GISA), "commander"),
                             entry(GISA, "commander/gisa", "commander")["card_sha"])

    def test_kinds(self):
        self.assertEqual([forge.page_kind(i) for i in ("casual/x", "commander/y", "product/z/1", "pairing/a+b",
                                                        "file:decklab/x.dck", None)],
                         ["casual", "commander", "product", "pairing", "casual", "casual"])
        self.assertEqual([forge.engine_kind({"kind": k}) for k in ("commander", "casual", "product")],
                         ["commander", "constructed", "constructed"])

    def test_a_dck_file_plays_as_it_is(self):
        path = self.tmp / "izzet.dck"
        path.write_text("[metadata]\nName=Izzet\n[Main]\n4 Preordain\n2 Abrade|FDN\n7 Island\n[Sideboard]\n1 X\n",
                        encoding="utf-8")
        e = forge.entry_from_dck(path)
        self.assertEqual(e["dck"].splitlines()[2:], ["[Main]", "4 Preordain", "2 Abrade", "7 Island"])
        self.assertEqual((e["title"], e["kind"], e["card_count"]), ("Izzet", "constructed", 13))
        self.assertNotEqual(e["card_sha"], entry("Deck\n4 Preordain\n2 Abrade\n7 Island\n")["card_sha"])



class KeyTests(ForgeCase):

    def test_key_is_symmetric(self):
        a, b = entry(GREEN), entry(RED)
        self.assertEqual(forge.matchup_key(a, b), forge.matchup_key(b, a))
        self.assertRegex(forge.matchup_key(a, b), r"^[0-9a-f]{64}$")

    def test_key_is_the_contract_sha(self):
        # Wave 2's engine id (contract "Engine id"): the SHA-256 of the engine's canonical description. The
        # tests' Java has no JDK, so it's plain Forge's; the made-up Forge folder has no AI profile file.
        a, b = entry(GREEN), entry(RED)
        fiery = hashlib.sha256((forge.overrides.SETS_DIR / "fiery" / "fiery_annihilation.txt").read_bytes()).hexdigest()
        desc = {"id_version": 3, "run_version": forge.FORGE_RUN_VERSION, "kind": "plain", "forge": "2.0.15",
                "format": "Constructed", "clock_s": 120, "seeds": "batch", "performance_mode": True,
                "game_patches": [],
                "overrides": hashlib.sha256(f"Fiery Annihilation\n{fiery}\n".encode("utf-8")).hexdigest(),
                "sides": sorted([[a["card_sha"], "Default", None], [b["card_sha"], "Default", None]])}
        payload = json.dumps(desc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        self.assertEqual(forge.matchup_key(a, b), hashlib.sha256(payload.encode("utf-8")).hexdigest())
        # Before wave 2 (run_version 1, lists._key): another key, which no run saves under now.
        old = json.dumps([sorted([a["card_sha"], b["card_sha"]]), "Constructed", 1, "2.0.15", 120, ["Default", "Default"]])
        self.assertEqual(forge.lists._key(a, b, "2.0.15", 120), hashlib.sha256(old.encode("utf-8")).hexdigest())
        self.assertNotEqual(forge.matchup_key(a, b), forge.lists._key(a, b, "2.0.15", 120))

    def test_key_changes_with_the_lists_and_the_clock(self):
        a, b = entry(GREEN), entry(RED)
        key = forge.matchup_key(a, b)
        self.assertNotEqual(forge.matchup_key(a, a), key)
        self.settings["forge_clock_s"] = 60
        self.assertNotEqual(forge.matchup_key(a, b), key)

    def test_the_key_has_the_forge_version_a_run_plays_with(self):
        folder = self.tmp / "forge"
        make_forge(folder)
        self.settings["forge_dir"] = str(folder)
        a, b = entry(GREEN), entry(RED)
        old = forge.matchup_key(a, b)
        self.assertEqual(forge.status()["version"], "2.0.15")
        # Forge is upgraded while Deck Lab runs (a jar with only its manifest, which the engine id reads).
        with zipfile.ZipFile(folder / "forge-gui-desktop-2.0.16-jar-with-dependencies.jar", "w") as z:
            z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\nImplementation-Version: 2.0.16\r\n\r\n")
        self.assertEqual(forge.status()["version"], "2.0.16")          # seen without a refresh
        new = forge.matchup_key(a, b)
        self.assertNotEqual(new, old)
        result = forge.run(a, b, 200, by="Matt", results_dir=self.results)
        self.assertEqual((result["key"], result["forge_version"]), (new, "2.0.16"))
        self.assertIsNone(forge.load(old, self.results))

    def test_the_key_doesnt_need_java_or_forge_once_a_version_was_found(self):
        a, b = entry(GREEN), entry(RED)
        key = forge.matchup_key(a, b)
        self.settings["forge_java"] = str(self.tmp / "no-java.exe")
        self.assertFalse(forge.status(refresh=True)["ready"])
        self.assertEqual(forge.matchup_key(a, b), key)
        self.settings["forge_dir"] = str(self.tmp / "nowhere")        # a drive that isn't connected
        self.assertEqual(forge.matchup_key(a, b), key)
        forge.install._known.clear()                                    # a new process: the file remembers
        self.assertEqual((forge.common.DATA_DIR / "forge-version.txt").read_text(encoding="utf-8"), "2.0.15\n")
        self.assertEqual(forge.matchup_key(a, b), key)
        self.assertEqual(forge.forge_version(), "2.0.15")

    def test_a_commander_deck_cant_play_a_constructed_one(self):
        with self.assertRaises(forge.ForgeError) as caught:
            forge.matchup_key(entry(GREEN), entry(GISA, "commander/gisa", "commander"))
        self.assertIn("Commander", str(caught.exception))
        self.assertEqual(forge.fmt_for("commander"), "Commander")
        self.assertEqual(forge.fmt_for("constructed"), "Constructed")



class PlanTests(ForgeCase):

    def test_sizes(self):
        # The largest even number of batches, at most one per worker and of 25 games or more, that divides
        # the games (R02; test_forge_batchplan has the rest).
        for games, workers, size, count in ((200, 16, 25, 8), (800, 16, 50, 16), (1600, 16, 100, 16),
                                            (3200, 16, 200, 16), (1600, 8, 200, 8), (800, 4, 200, 4),
                                            (400, 12, 40, 10), (200, 2, 100, 2)):
            batches = forge.plan(games, workers=workers)
            self.assertEqual(({b["games"] for b in batches}, len(batches)), ({size}, count), (games, workers))
            self.assertEqual(sum(b["games"] for b in batches), games)
            self.assertEqual(len(batches) % 2, 0)

    def test_seeds_start_at_one_and_deck_order_alternates(self):
        batches = forge.plan(400, workers=4)
        self.assertEqual([(b["n"], b["seed"], b["deck1"]) for b in batches],
                         [(0, 1, 0), (1, 2, 1), (2, 3, 0), (3, 4, 1)])

    def test_more_games_go_on_from_the_highest_seed_failed_ones_included(self):
        existing = {"batches": [{"n": 0, "seed": 1}, {"n": 2, "seed": 3}], "failed": [{"n": 1, "seed": 2}, {"n": 3, "seed": 4}]}
        batches = forge.plan(200, existing, workers=2)
        self.assertEqual([(b["n"], b["seed"], b["deck1"]) for b in batches], [(4, 5, 0), (5, 6, 1)])

    def test_only_the_choices_unless_the_batch_is_given(self):
        for games in (0, 100, 300, 5000):
            with self.assertRaises(ValueError):
                forge.plan(games)
        batches = forge.plan(400, batch=200, seed_base=210000)
        self.assertEqual([(b["seed"], b["games"], b["deck1"]) for b in batches], [(210000, 200, 0), (210001, 200, 1)])
        self.assertEqual(len(forge.plan(20, batch=10)), 2)
        with self.assertRaises(ValueError):
            forge.plan(25, batch=10)



class LogReaderTests(unittest.TestCase):

    def test_a_whole_game(self):
        # Seed 7: Gruul Ramp (deck 1) went first and won in round 7 (turn 13).
        r = read_log("full-game-s7.log")
        self.assertTrue(r.header)
        self.assertEqual(r.games, [{"w": 0, "r": "win", "first": 0, "rounds": 7, "turns": 13, "ms": 1312,
                                    "loss": "life total reached 0", "ai_to": 0}])
        self.assertEqual(r.casts[0]["Scavenging Ooze"], [2, 1])     # cast twice in one game
        self.assertEqual(r.casts[0]["Rabid Gnaw"], [2, 1])          # "... targeting [...]" is left out
        self.assertEqual(r.casts[1]["Scorching Dragonfire"], [1, 1])
        self.assertEqual(r.lands, [{"Forest": 1, "Mountain": 1},
                                   {"Temple of Epiphany": 1, "Mountain": 1, "Island": 1, "Swiftwater Cliffs": 1}])
        self.assertNotIn("Swiftwater Cliffs", r.casts[1])            # its trigger isn't a cast
        self.assertIsNone(r.failure(1, 0))

    def test_sides_follow_the_deck_order(self):
        r = read_log("full-game-s7.log", deck1=1)
        self.assertEqual((r.games[0]["w"], r.games[0]["first"]), (1, 1))
        self.assertEqual(r.casts[1]["Scavenging Ooze"], [2, 1])

    def test_a_game_stopped_by_the_clock_is_not_a_win(self):
        # -c 1: Forge printed "has won" for both players and named Izzet the winner of games 1 and 2.
        r = read_log("timeouts-c1.log", deck1=1)
        self.assertEqual([(g["r"], g["w"]) for g in r.games],
                         [("timeout", None), ("timeout", None), ("win", 0), ("win", 0)])
        self.assertEqual([g["first"] for g in r.games], [1, 1, 1, 1])
        self.assertIsNone(r.games[0]["loss"])
        self.assertEqual(r.failure(5, 0), "Forge played only 4 of 5 games")

    def test_ai_decision_timeouts_are_counted(self):
        r = read_log("ai-timeouts.log")
        self.assertEqual([(g["r"], g["ai_to"], g["rounds"], g["ms"]) for g in r.games], [("timeout", 3, 22, 120002)])

    def test_draws_errors_and_other_outcomes(self):
        r = forge.LogReader()
        lines = ["Ai(1)-a [Default] vs Ai(2)-b [Default] - fifty  games of Constructed seed 1",
                 "java.lang.NullPointerException: boom",
                 "Game Outcome: Ai(1)-a has won because all opponents have lost",
                 "Game Outcome: Ai(2)-b has won because all opponents have lost",
                 "Game Result: Game 1 ended in 5 ms. Ai(1)-a has won!",
                 "Game Result: Game 2 ended in a Draw! Took 7 ms.",
                 "Game Outcome: Ai(2)-b has conceded",
                 "Game Outcome: Ai(1)-a has won because all opponents have lost",
                 "Game Result: Game 3 ended in 9 ms. Ai(1)-a has won!"]
        what = [r.feed(line) for line in lines]
        self.assertEqual(what[0], "header")
        self.assertEqual([(g["r"], g["w"], g["loss"]) for g in r.games],
                         [("error", None, None), ("draw", None, None), ("win", 0, "conceded")])

    def test_the_stack_traces_of_ai_timeouts_and_clock_stops_arent_errors(self):
        r = forge.LogReader()
        for line in ["Ai(1)-a [Default] vs Ai(2)-b [Default] - fifty  games of Constructed seed 1",
                     "java.util.concurrent.TimeoutException",
                     "\tat java.base/java.util.concurrent.FutureTask.get(FutureTask.java:204)",
                     "AI eval thread at timeout:",
                     "Turn: Turn 1 (Ai(1)-x)",
                     "Game Result: Game 1 ended in a Draw! Took 10 ms.",
                     "java.lang.InterruptedException",
                     "Game Result: Game 2 ended in a Draw! Took 10 ms.",
                     "java.lang.NullPointerException: boom",
                     "Game Result: Game 3 ended in a Draw! Took 10 ms."]:
            r.feed(line)
        self.assertEqual([(g["r"], g["ai_to"]) for g in r.games], [("draw", 1), ("draw", 0), ("error", 0)])

    def test_a_closed_reader_reads_nothing_more(self):
        r = forge.LogReader()
        r.feed("Ai(1)-a [Default] vs Ai(2)-b [Default] - two  games of Constructed seed 1")
        r.feed("Game Result: Game 1 ended in a Draw! Took 7 ms.")
        r.close()
        self.assertIsNone(r.feed("Game Result: Game 2 ended in a Draw! Took 7 ms."))
        self.assertEqual(len(r.games), 1)

    def test_failed_batches(self):
        r = forge.LogReader()
        r.feed('An unsupported card was requested: "Totally Fake Card" from "null".')
        self.assertEqual(r.failure(0, 0), "Forge doesn't know these cards: Totally Fake Card")
        r = forge.LogReader()
        r.feed("Could not load deck - a.dck, match cannot start")
        self.assertEqual(r.failure(1, 0), "Forge couldn't load one of the decks")
        self.assertEqual(forge.LogReader().failure(0, 1), "Forge stopped with an error (exit code 1)")

    def test_logged_names_map_to_the_list_names(self):
        index = {"names": {"murderous rider": "Murderous Rider", "swift end": "Murderous Rider"},
                 "faces": {"Murderous Rider": ["Murderous Rider", "Swift End"]}}
        names = forge._log_names(["Murderous Rider"], index)
        r = forge.LogReader(0, [names, {}])
        r.feed("Ai(1)-a vs Ai(2)-b - one game of Constructed seed 1")
        r.feed("Add To Stack: Ai(1)-a cast Swift End targeting [Grizzly Bears (5)]")
        r.feed("Game Result: Game 1 ended in a Draw! Took 7 ms.")
        self.assertEqual(r.casts[0], {"Murderous Rider": [1, 1]})



class MathsTests(unittest.TestCase):

    def test_wilson(self):
        # 50 of 100: p = 0.5, z = 1.96. d = 1 + 3.8416/100 = 1.038416; centre = (0.5 + 0.019208)/d = 0.5;
        # half = 1.96 * sqrt(0.0025 + 3.8416/40000) / d = 1.96 * 0.0509513 / 1.038416 = 0.0961700.
        low, high = forge.wilson(50, 100)
        self.assertAlmostEqual(low, 0.4038300, places=6)
        self.assertAlmostEqual(high, 0.5961700, places=6)
        # 0 of 10: centre = 0.192080 / 1.384160 = 0.138770; half = 1.96 * sqrt(0.0096040) / 1.38416
        #   = 1.96 * 0.0980000 / 1.38416 = 0.138770, so the range is 0 to 0.277540.
        low, high = forge.wilson(0, 10)
        self.assertAlmostEqual(low, 0.0, places=6)
        self.assertAlmostEqual(high, 0.2775401, places=6)
        self.assertEqual(forge.wilson(0, 0), (None, None))

    def test_balanced(self):
        # Wilson score intervals for 30/50 and 20/50, combined by MOVER with weights 1/2.
        value, low, high = forge.balanced(30, 50, 20, 50)
        self.assertAlmostEqual(value, 0.5)
        self.assertAlmostEqual(low, 0.4071942, places=6)
        self.assertAlmostEqual(high, 0.5928058, places=6)
        self.assertIsNone(forge.balanced(3, 5, 0, 0))

    def test_balanced_small_samples_are_not_certain(self):
        won = forge.balanced(1, 1, 1, 1)
        lost = forge.balanced(0, 1, 0, 1)
        self.assertEqual((won[0], won[2], lost[0], lost[1]), (1.0, 1.0, 0.0, 0.0))
        self.assertLess(won[1], 0.5)
        self.assertGreater(lost[2], 0.5)
        self.assertAlmostEqual(won[1], 1 - lost[2])
        self.assertGreater(forge.balanced(5, 5, 5, 5)[1], won[1])
        self.assertLess(forge.balanced(5, 5, 5, 5)[1], 1)

    def test_balanced_range_respects_strata_and_complements(self):
        for a, n, b, m in ((0, 1, 8, 10), (1, 1, 0, 20), (30, 50, 20, 50)):
            value, low, high = forge.balanced(a, n, b, m)
            self.assertEqual((value, low, high), forge.balanced(b, m, a, n))
            other = forge.balanced(n - a, n, m - b, m)
            for actual, expected in zip(other, (1 - value, 1 - high, 1 - low)):
                self.assertAlmostEqual(actual, expected)
            self.assertTrue(0 <= low <= value <= high <= 1)



class ViewTests(ForgeCase):

    def setUp(self):
        super().setUp()
        # Side 0 on the play: 6 games, wins 4, loses 1, 1 timeout. On the draw: 4 games, wins 1, loses 3.
        self.games = [(0, "win", 0)] * 4 + [(1, "win", 0), (None, "timeout", 0)] + [(0, "win", 1)] + [(1, "win", 1)] * 3
        self.result = stored(self.games, casts=[{"Grizzly Bears": [7, 5]}, {}])

    def test_numbers_from_side_0(self):
        v = forge.view(self.result, "a" * 64)
        self.assertEqual((v["games"], v["wins"], v["draws"], v["timeouts"], v["errors"]), (10, [5, 4], 0, 1, 0))
        self.assertEqual(v["on_play"], {"games": 6, "wins": 4, "value": 0.6667})
        self.assertEqual(v["on_draw"], {"games": 4, "wins": 1, "value": 0.25})
        # Balanced: (4/6 + 1/4) / 2 = 0.458333; raw 5/10.
        self.assertEqual(v["winrate"]["value"], 0.4583)
        self.assertTrue(v["winrate"]["balanced"])
        self.assertEqual(v["raw"]["value"], 0.5)
        self.assertEqual(v["raw"]["low"], round(forge.wilson(5, 10)[0], 4))
        # The starting player: the average of both decks going first, side 0 winning 4 of its 6 games on the
        # play and side 1 3 of its 4, (4/6 + 3/4) / 2 = 0.7083 (the plain share, 7 of 10, leans to whichever
        # deck went first more).
        self.assertEqual(v["starter"]["value"], 0.7083)
        self.assertTrue(v["starter"]["balanced"])
        self.assertLess(v["starter"]["low"], 0.7083)
        self.assertGreater(v["starter"]["high"], 0.7083)
        self.assertEqual(v["rounds"], {"mean": 5.9, "min": 5, "max": 7})      # 5 6 7 5 6 7 5 6 7 5
        self.assertEqual(v["game_ms"], {"mean": 804, "max": 809})             # 800..809: 804.5 rounds to even
        self.assertEqual(v["ai_timeouts"], 5)
        self.assertEqual(v["loss_reasons"], [{"reason": "life total reached 0", "games": 9}])
        self.assertEqual(v["casts"][0], [{"name": "Grizzly Bears", "qty": 4, "casts": 7, "games": 5}])
        self.assertEqual(v["casts"][1], [{"name": "Grizzly Bears", "qty": 4, "casts": 0, "games": 0}])
        self.assertEqual(v["speed"], {"games_per_min": 20.0, "wall_s": 30.0})
        self.assertEqual(v["failed_batches"], 1)
        self.assertEqual(v["seeds"], 2)
        self.assertEqual(v["settings"]["clock_s"], 120)
        self.assertFalse(v["not_meaningful"])
        self.assertEqual(v["runs"][0]["by"], "Matt")

    def test_the_other_side_sees_it_turned_round(self):
        a, b = forge.view(self.result, "a" * 64), forge.view(self.result, "b" * 64)
        self.assertEqual(b["wins"], a["wins"][::-1])
        self.assertEqual(b["on_play"], {"games": 4, "wins": 3, "value": 0.75})
        self.assertEqual(b["on_draw"], {"games": 6, "wins": 1, "value": 0.1667})
        self.assertEqual(b["casts"], a["casts"][::-1])
        self.assertEqual(b["starter"], a["starter"])
        self.assertEqual(b["winrate"]["value"], round((0.75 + 1 / 6) / 2, 4))

    def test_one_sided_starts_fall_back_to_the_raw_rate(self):
        v = forge.view(stored([(0, "win", 0), (1, "win", 0), (0, "win", 0)]), "a" * 64)
        self.assertFalse(v["winrate"]["balanced"])
        self.assertEqual(v["winrate"]["value"], v["raw"]["value"])

    def test_no_games(self):
        result = stored([])
        result["batches"] = []
        v = forge.view(result, "a" * 64)
        self.assertEqual(v["games"], 0)
        self.assertIsNone(v["winrate"]["value"])
        self.assertIsNone(v["comparison"])

    def test_nonwins_compare_both_sides_instead_of_the_fifty_percent_line(self):
        games = []
        for first in (0, 1):
            games += [(0, "win", first)] * 180 + [(1, "win", first)] * 120
            games += [(None, "draw", first)] * 40 + [(None, "timeout", first)] * 40
            games += [(None, "error", first)] * 20
        result = stored(games)
        a, b = (forge.view(result, sha * 64) for sha in ("a", "b"))
        self.assertLess(a["winrate"]["high"], 0.5)  # The old rule incorrectly put B ahead.
        self.assertAlmostEqual(a["comparison"]["value"], 0.15)
        self.assertGreater(a["comparison"]["low"], 0)
        self.assertLess(b["comparison"]["high"], 0)
        self.assertEqual(b["comparison"]["low"], -a["comparison"]["high"])
        self.assertEqual(b["comparison"]["high"], -a["comparison"]["low"])
        self.assertTrue(a["comparison"]["balanced"])

    def test_comparison_handles_partial_runs_and_no_winners(self):
        for games in ([(0, "win", 0), (0, "win", 1)],
                      [(0, "win", 0)],
                      [(0, "win", None)],
                      [(None, "timeout", 0)] * 100 + [(None, "timeout", 1)] * 100):
            with self.subTest(games=games[:2]):
                comparison = forge.view(stored(games), "a" * 64)["comparison"]
                self.assertLessEqual(comparison["low"], 0)
                self.assertGreaterEqual(comparison["high"], 0)
        comparison = forge.view(stored([(0, "win", 0)] * 100 + [(1, "win", 0)] * 10),
                                "a" * 64)["comparison"]
        self.assertFalse(comparison["balanced"])
        self.assertGreater(comparison["low"], 0)

    def test_comparison_balances_nonwin_rates_without_discarding_them(self):
        # Dropping nonwins would make each side win one starter stratum and call this even.
        games = ([(0, "win", 0)] + [(None, "timeout", 0)] * 999
                 + [(1, "win", 1)] * 900 + [(None, "timeout", 1)] * 100)
        comparison = forge.view(stored(games), "a" * 64)["comparison"]
        self.assertAlmostEqual(comparison["value"], -0.4495)
        self.assertLess(comparison["high"], 0)

    def test_list_item(self):
        item = forge.list_item(self.result, "b" * 64)
        self.assertEqual([s["id"] for s in item["sides"]], ["casual/bbb", "casual/aaa"])
        self.assertEqual(item["sides"][0], {"id": "casual/bbb", "version": "target", "title": "BBB", "kind": "casual",
                                            "card_sha": "b" * 64, "card_count": 24, "current": None,
                                            "auto_profile": None,
                                            "pilot": {"profile": "Default", "switches": [], "words": None}})
        # Saved before wave 2: its engine says so (test_forge_engine has the rest).
        self.assertEqual(item["engine"], {"kind": "v1", "run_version": 1, "current": False,
                                          "words": forge.engine.V1_WORDS})
        self.assertEqual((item["games"], item["by"], item["updated"], item["not_meaningful"]),
                         (10, "Matt", "2026-10-01T10:00:30", False))
        self.assertEqual(item["winrate"], forge.view(self.result, "b" * 64)["winrate"])
        self.assertEqual(forge.list_item(self.result)["sides"][0]["id"], "casual/aaa")
        # Without a perspective, the list the last run was asked for first comes first.
        self.result["runs"][-1]["a"] = "b" * 64
        self.assertEqual(forge.list_item(self.result)["sides"][0]["id"], "casual/bbb")
        self.assertEqual(forge.list_item(self.result, "a" * 64)["sides"][0]["id"], "casual/aaa")

    def test_saved_results(self):
        older = stored(self.games)
        newer = stored(self.games)
        newer["key"], newer["updated"] = "d" * 64, "2026-10-02T09:00:00"
        newer["sides"][1]["card_sha"] = "e" * 64
        empty = stored([])
        empty["key"], empty["batches"] = "f" * 64, []
        self.results.mkdir()
        for r in (older, newer, empty):
            (self.results / f"{r['key']}.json").write_text(json.dumps(r), encoding="utf-8")
        (self.results / "broken.json").write_text("{", encoding="utf-8")
        self.assertEqual([i["key"] for i in forge.results(self.results)], ["d" * 64, "c" * 64])   # newest first
        self.assertEqual([i["key"] for i in forge.results_for("b" * 64, self.results)], ["c" * 64])
        self.assertEqual(forge.results_for("a" * 64, self.results)[0]["sides"][0]["card_sha"], "a" * 64)
        self.assertEqual(forge.load("c" * 64, self.results)["updated"], "2026-10-01T10:00:30")
        self.assertIsNotNone(forge.load("f" * 64, self.results))       # kept, though not listed
        self.assertIsNone(forge.load("0" * 64, self.results))
        self.assertIsNone(forge.load("../x", self.results))
        loaded = forge.load("c" * 64, self.results)
        loaded["updated"] = "changed"
        self.assertEqual(forge.load("c" * 64, self.results)["updated"], "2026-10-01T10:00:30")

    def test_a_file_that_isnt_a_result_is_left_out(self):
        # A hand edit, another program's file or a future format: never a 500 for the whole list.
        self.results.mkdir()
        good = stored(self.games)
        (self.results / f"{good['key']}.json").write_text(json.dumps(good), encoding="utf-8")
        no_sides = dict(good, sides=good["sides"][:1])
        bad_game = json.loads(json.dumps(good))
        del bad_game["batches"][0]["games"][0]["first"]
        renamed = dict(good)                    # its key isn't its file name
        for n, data in enumerate(([], {"x": 1}, "text", None, no_sides, bad_game, renamed,
                                  dict(good, batches={}), dict(good, updated=5))):
            key = f"{n:x}" * 64
            (self.results / f"{key}.json").write_text(json.dumps(data), encoding="utf-8")
            self.assertIsNone(forge.load(key, self.results), n)
        self.assertEqual([i["key"] for i in forge.results(self.results)], ["c" * 64])
        self.assertEqual([i["key"] for i in forge.results_for("a" * 64, self.results)], ["c" * 64])

    def test_a_result_that_cant_be_listed_doesnt_hide_the_rest(self):
        self.results.mkdir()
        newer = stored(self.games)
        newer["key"], newer["updated"] = "d" * 64, "2026-10-02T09:00:00"
        for r in (stored(self.games), newer):
            (self.results / f"{r['key']}.json").write_text(json.dumps(r), encoding="utf-8")
        real = forge.list_item

        def list_item(result, perspective_sha=None):
            if result["key"] == "d" * 64:
                raise KeyError("a shape nobody thought of")
            return real(result, perspective_sha)

        with mock.patch.object(forge.views, "list_item", list_item), mock.patch.object(forge.common, "_log") as log:
            self.assertEqual([i["key"] for i in forge.results(self.results)], ["c" * 64])
            self.assertEqual([i["key"] for i in forge.results_for("a" * 64, self.results)], ["c" * 64])
        self.assertIn("dddddddddddd", log.call_args[0][0])

    def test_not_meaningful_looks_only_at_commanders(self):
        # A constructed result needs no AI limits at all for its list row.
        with mock.patch.object(forge.ai, "side_ai", side_effect=AssertionError("side_ai ran")), \
                mock.patch.object(cards, "tag_members", side_effect=AssertionError("tags read")):
            self.assertFalse(forge.list_item(self.result)["not_meaningful"])
            self.assertFalse(forge.view(self.result, "a" * 64)["not_meaningful"])
        # A commander the AI never cast in 100 games makes it meaningless, as side_ai says.
        bears = {"Commander": [[1, "Grizzly Bears"]], "Main": [[20, "Forest"]]}
        never = stored([(0, "win", 0), (1, "win", 1)] * 50, cards_a=bears, cards_b=bears, kinds=("commander", "commander"))
        cast = stored([(0, "win", 0), (1, "win", 1)] * 50, casts=[{"Grizzly Bears": [3, 3]}, {"Grizzly Bears": [1, 1]}],
                      cards_a=bears, cards_b=bears, kinds=("commander", "commander"))
        for result, expected in ((never, True), (cast, False)):
            self.assertEqual(forge.list_item(result)["not_meaningful"], expected)
            self.assertEqual(any(forge.side_ai(result, s)["commander_unplayable"] for s in (0, 1)), expected)
        short = stored([(0, "win", 0)] * 99, cards_a=bears, cards_b=bears, kinds=("commander", "commander"))
        self.assertFalse(forge.list_item(short)["not_meaningful"])         # too few games to judge



if __name__ == "__main__":
    unittest.main()
