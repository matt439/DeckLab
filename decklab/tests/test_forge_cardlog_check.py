"""Tests for cardlog-check: the check that the card log and Deck Lab's engine play the same games
as plain Forge. The shared fixtures, setUpModule and tearDownModule stay in test_forge."""
import io
import json
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from decklab.lib import decks, forge
from decklab.tests import test_forge
from decklab.tests.test_forge import (
    CARD_LOG, CHECKED_BUILD, GREEN, NO_JDK, RED, ForgeCase, load_json, make_forge, sections,
    setUpModule, tearDownModule, wait_dead,
)


class CardlogCheckTests(ForgeCase):

    run_main = test_forge.CommandLineTests.run_main
    check_command = test_forge.CommandLineTests.check_command
    check = test_forge.CommandLineTests.check
    made_up_jdk = test_forge.CommandLineTests.made_up_jdk

    def setUp(self):
        # The same decks as CommandLineTests, whose setUp these cases ran under before the split.
        super().setUp()
        summaries = [{"id": "casual/green", "title": "Green", "kind": "casual", "versions": ["target", "owned"]},
                     {"id": "casual/red", "title": "Red", "kind": "casual", "versions": ["target"]}]
        lists = {"casual/green": GREEN, "casual/red": RED}
        for p in (mock.patch.object(decks, "list_decks", return_value=summaries),
                  mock.patch.object(decks, "beginner_box_pairings", return_value=[]),
                  mock.patch.object(decks, "load_deck", side_effect=lambda deck_id, version: sections(lists[deck_id]))):
            p.start()
            self.addCleanup(p.stop)

    def test_cardlog_check_notes_a_version_that_plays_the_same_games(self):
        code, out, err = self.check()
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "The card log played the same 6 Constructed and 2 Commander games as plain Forge "
                              "2.0.15, so runs with Forge 2.0.15 use it from now on.\n")
        self.assertRegex(err, r"\n  Constructed: plain Forge took [\d.]+ s \(6 processes\), Deck Lab's engine [\d.]+ s "
                              r"with its game patches off, [\d.]+ s on, [\d.]+ s without the card log\n"
                              r"  Commander: plain Forge took [\d.]+ s \(2 processes\), Deck Lab's engine [\d.]+ s with "
                              r"its game patches off, [\d.]+ s on, [\d.]+ s without the card log\n"
                              r"(?:  .+\n)*$")        # then the warm leg's own lines (servecheck.warm_leg)
        checked = load_json(forge.common.DATA_DIR / "cardlog" / "checked.json")
        self.assertEqual(checked["versions"]["2.0.15"],
                         {"when": checked["versions"]["2.0.15"]["when"], "games": 8, "build": CHECKED_BUILD,
                          "source_sha256": forge.simjar.source_sha256()})

    def test_cardlog_check_plays_the_v2_engine_four_ways(self):
        self.assertEqual(self.check()[0], 0)
        for fmt, decks_, n in forge.cli._check_legs(6, 2):
            names, stream = forge.cli._check_sides(decks_, fmt)
            seated = (f"{names[0]}.dck", f"{names[1]}.dck")         # side 0 (the smaller card_sha) is deck 1 in block 0
            v2 = {"stream": forge.seeds.stream_hex(stream), "first": 0}
            runs = sorted(((r["card_log"], r["games"], r["seed"], json.dumps(r["v2"], sort_keys=True), r["game_patches"],
                            r["decks"]) for r in self.built if r["fmt"] == fmt), key=repr)
            expected = [(True, n, 1, json.dumps(v2, sort_keys=True), False, seated),
                        (True, n, 1, json.dumps(v2, sort_keys=True), True, seated),
                        (True, n, 1, json.dumps(dict(v2, card_log=False), sort_keys=True), True, seated)]
            expected += [(False, 1, forge.seeds.game_seed(1, stream, g), "null", False, seated) for g in range(n)]
            # The warm leg's fresh process (servecheck.warm_leg), as Forge's setup has it: game patches on.
            expected.append((True, n, 1, json.dumps(v2, sort_keys=True), None, seated))
            with self.subTest(fmt=fmt):
                self.assertEqual(runs, sorted(expected, key=repr))
        # The decks: 60 cards, or 100 with a commander, one of each card but the basics.
        started = []
        real = forge.processes.start_process

        def start(argv, **kwargs):
            if "-D" in argv:            # (a serve worker gets its decks with each request)
                folder = Path(argv[argv.index("-D") + 1])
                started.append((argv[argv.index("-f") + 1], [(folder / name).read_text(encoding="utf-8")
                                                             for name in argv[argv.index("-d") + 1:][:2]]))
            return real(argv, **kwargs)

        with mock.patch.object(forge.processes, "start_process", start):
            self.assertEqual(self.check()[0], 0)
        for fmt, decks_ in started:
            for text in decks_:
                listed = sum(int(line.split(" ", 1)[0]) for line in text.splitlines() if line[:1].isdigit())
                if fmt == "Commander":
                    self.assertEqual((listed, text.count("[Commander]\n1 ")), (100, 1))
                    mains = [line for line in text.split("[Main]\n")[1].splitlines() if not line.startswith("64 ")]
                    self.assertTrue(all(line.startswith("1 ") for line in mains))       # one of each but basics
                else:
                    self.assertEqual((listed, "[Commander]" in text), (60, False))
        self.assertIn("4 Dragon Fodder", forge.cli.CHECK_DECKS["cardlog-check-a"])          # tokens
        self.assertIn("4 Scorching Dragonfire", forge.cli.CHECK_DECKS["cardlog-check-a"])   # exile

    def test_cardlog_check_plays_at_most_one_seat_block(self):
        for flag in ("--games", "--commander-games"):
            with mock.patch("sys.stderr", io.StringIO()) as err, self.assertRaises(SystemExit) as caught:
                forge.main(["cardlog-check", flag, "26"])
            self.assertEqual(caught.exception.code, 2)
            self.assertIn(f"argument {flag}: must be at most 25, not '26'", err.getvalue())
        self.assertEqual(forge.cli.CHECK_MAX_GAMES, forge.seeds.SEAT_BLOCK)

    def test_cardlog_check_notes_the_forge_build_it_checked(self):
        forge_dir = self.tmp / "forge-snapshot"         # a later snapshot under the same jar name
        make_forge(forge_dir)
        with zipfile.ZipFile(forge_dir / "forge-gui-desktop-2.0.15-jar-with-dependencies.jar", "w") as z:
            z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n"
                                               "Implementation-Version: 2.0.15-SNAPSHOT-10.02\r\n\r\n")
            z.writestr(forge.simjar.FORGE_PATCH_LIST, "forge/game/mulligan/AbstractMulligan.class -\n")
        self.settings["forge_dir"] = str(forge_dir)
        self.made_up_jdk()
        self.assertIn("\ncard log: off. This Forge 2.0.15 is build 2.0.15-SNAPSHOT-10.02, not the "
                      "2.0.15-SNAPSHOT-09.28 the card log was checked with", self.run_main("status")[1])
        self.assertEqual(self.check()[0], 0)
        checked = load_json(forge.common.DATA_DIR / "cardlog" / "checked.json")
        self.assertEqual(checked["versions"]["2.0.15"]["build"], "2.0.15-SNAPSHOT-10.02")
        self.assertIn("\ncard log: on (per-card stats)\n", self.run_main("status")[1])

    def test_cardlog_check_notes_when_the_engine_plays_other_games_than_plain_forge(self):
        def other_base(run):            # Deck Lab's engine with its game patches off plays other games
            return {"seed": run["seed"] + 1} if run["card_log"] and run["game_patches"] is False else None

        self.made_up_jdk()
        self.assertEqual(forge.status()["card_log"], {"ready": True, "problem": None})     # 2.0.15 is in CHECKED
        code, out, err = self.check(change=other_base)
        self.assertEqual(code, 1, err)
        self.assertRegex(out, r"^Deck Lab's engine \(its game patches off\) didn't play the same Constructed games as "
                              r"plain Forge 2\.0\.15: game \d+, line \d+: plain Forge printed .*, Deck Lab's engine .*\.\n"
                              r"Deck Lab's engine \(its game patches off\) didn't play the same Commander games as "
                              r"plain Forge 2\.0\.15: game \d+ was .+ with plain Forge, .+ with Deck Lab's engine\.\n"
                              r"Plain Forge itself doesn't play a Commander game the same way .*\n"
                              r"Runs with Forge 2\.0\.15 go without the card log until a check passes\.\n$")
        checked = load_json(forge.common.DATA_DIR / "cardlog" / "checked.json")
        self.assertEqual((checked["versions"]["2.0.15"]["failed"], checked["versions"]["2.0.15"]["games"]), (True, 8))
        # Off, though 2.0.15 is in CHECKED, until a check passes.
        self.assertEqual(forge.status()["card_log"], {"ready": False, "problem": forge.simjar.failed_problem("2.0.15")})
        self.assertEqual(self.check()[0], 0)
        self.assertEqual(forge.status()["card_log"], {"ready": True, "problem": None})

    def test_cardlog_check_notes_when_the_card_log_changes_the_games(self):
        def other_base(run):            # without the card log, other games
            return {"seed": run["seed"] + 1} if (run["v2"] or {}).get("card_log") is False else None

        code, out, err = self.check(change=other_base)
        self.assertEqual(code, 1, err)
        self.assertRegex(out, r"^The card log changed the Constructed games it was kept in \(Forge 2\.0\.15\): game \d+, "
                              r"line \d+: without the card log printed .*, with it .*\.\n")
        self.assertIn("The card log changed the Commander games it was kept in (Forge 2.0.15): game ", out)
        self.assertTrue(out.endswith("Runs with Forge 2.0.15 go without the card log until a check passes.\n"))

    def test_cardlog_check_cant_tell_when_a_game_that_differs_hit_a_time_limit(self):
        real = forge.processes.start_process

        def start(argv, **kwargs):      # AI decision timeouts in the third game (g 2) of the engine's run, patches off
            if "--game-patches-off" in argv and argv[argv.index("-n") + 1] != "1":
                kwargs["env"] = dict(kwargs["env"], FAKE_FORGE="aitimeout#2")
            return real(argv, **kwargs)

        with mock.patch.object(forge.processes, "start_process", start):
            code, out, err = self.check()
        self.assertEqual(code, 1, err)
        # (The Commander leg's games are compared by their outcomes, which the timeouts don't change.)
        self.assertRegex(out, r"^Deck Lab's engine \(its game patches off\) didn't play the same Constructed games as "
                              r"plain Forge 2\.0\.15: game 3, line \d+: .*\.\nThat game hit")
        self.assertTrue(out.endswith("\nThat game hit one of Forge's time limits (\"Stopping slow match as draw\" or "
                                     "\"AI eval thread at timeout\"), which a busy computer can cause in one copy of a "
                                     "game and not the other, so the check can't tell whether the card log plays the "
                                     "same games. Run it again when the computer is less busy.\n"
                                     "Nothing was noted, so runs with Forge 2.0.15 go on as they were.\n"), out)
        self.assertFalse((forge.common.DATA_DIR / "cardlog" / "checked.json").exists())

    def test_cardlog_check_cant_tell_when_a_commander_game_ends_differently(self):
        def other_commander_games(run):     # as plain Forge's own can
            return {"seed": run["seed"] + 1} if run["fmt"] == "Commander" and run["game_patches"] is False \
                and run["card_log"] else None

        self.made_up_jdk()
        code, out, err = self.check(change=other_commander_games)
        self.assertEqual(code, 1, err)
        self.assertRegex(out, r"^Deck Lab's engine \(its game patches off\) didn't play the same Commander games as "
                              r"plain Forge 2\.0\.15: game \d+ was .+ with plain Forge, .+ with Deck Lab's engine\.\n"
                              r"Plain Forge itself doesn't play a Commander game the same way every time \(two runs of "
                              r"one seed can block differently, which can change how a game ends\), so the check can't "
                              r"tell whether the card log plays the same games\. Run it again\.\n"
                              r"Nothing was noted, so runs with Forge 2\.0\.15 go on as they were\.\n$")
        self.assertFalse((forge.common.DATA_DIR / "cardlog" / "checked.json").exists())
        self.assertEqual(forge.status()["card_log"], {"ready": True, "problem": None})     # still on: in CHECKED

    def test_cardlog_check_notes_when_a_card_log_fails_its_checks(self):
        self.fake("badcardlog#1")       # the second game (g 1) of every run kept with the card log
        code, out, err = self.check()
        self.assertEqual(code, 1, err)
        self.assertRegex(out, r"^(The card log of 1 of the 6 Constructed games failed its checks:\n  game 2: .+\n){2}"
                              r"(The card log of 1 of the 2 Commander games failed its checks:\n  game 2: .+\n){2}"
                              # the warm leg's (servecheck.warm_leg): the same card logs, played warm and fresh
                              r"A warm worker didn't play the same games as fresh processes with Forge 2\.0\.15:\n"
                              r"(  .+, played (fresh|warm): .+\n)+"
                              r"Runs with Forge 2\.0\.15 go without the card log until a check passes\.\n$")
        checked = load_json(forge.common.DATA_DIR / "cardlog" / "checked.json")
        self.assertIs(checked["versions"]["2.0.15"]["failed"], True)
        self.assertNotIn("2.0.15", forge.simjar.checked_versions())

    def test_cardlog_check_that_cant_note_a_failed_check(self):
        self.fake("badcardlog#1")
        forge.common.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (forge.common.DATA_DIR / "cardlog").write_text("a file, not a folder", encoding="utf-8")
        code, out, err = self.check()
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("The card log of 1 of the 6 Constructed games failed its checks:\n  game 2: "), out)
        self.assertNotIn("Runs with Forge", out)
        self.assertEqual(err.splitlines()[-1], "Error: Deck Lab couldn't note that the card log failed its checks "
                                               "(its data folder can't be written).")

    def test_cardlog_check_stops_its_processes_at_ctrl_c(self):
        import _thread
        # Every process hangs before its first game's result; Ctrl+C comes a moment after the first starts.
        self.fake("hang#0")
        setup = forge.install._setup()
        marker = forge.runner._first_use_marker(setup["user_dir"], setup["version"])
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()                      # Forge has started in this user folder: all at once from the start
        real_start = forge.processes.start_process
        started, pressed = [], []

        def ctrl_c():
            pressed.append(len(started))
            _thread.interrupt_main()

        def start(argv, **kwargs):
            proc = real_start(argv, **kwargs)
            self.addCleanup(forge.kill_process, proc)
            started.append(proc)
            if len(started) == 1:
                threading.Timer(1, ctrl_c).start()
            return proc

        t0 = time.monotonic()
        with mock.patch.object(forge.processes, "start_process", start):
            code, _, err = self.check()
        self.assertEqual(code, 130, err)
        self.assertLess(time.monotonic() - t0, forge.cli.CHECK_STOP_WAIT)
        # As many processes as there were slots for went; they were killed, and none started after Ctrl+C, though
        # the check's other runs (CHECK_PROCESSES at once) were waiting for a slot.
        self.assertEqual(pressed, [min(forge.cli.CHECK_PROCESSES, setup["workers"])])
        self.assertEqual(len(started), pressed[0])
        self.assertEqual(len(self.built), forge.cli.CHECK_PROCESSES)
        self.assertTrue(all(wait_dead(proc.pid) for proc in started))
        self.assertTrue(all(wait_dead(pid) for pid, _, _ in self.starts()))
        self.assertFalse(any(row["held"] for row in forge.slots.status()["slots"]))     # their slots given back

    def test_cardlog_check_without_a_jdk(self):
        code, out, err = self.run_main("cardlog-check")
        self.assertEqual((code, out, err), (1, "", f"{NO_JDK}\n"))

    def test_cardlog_check_has_a_warm_leg(self):
        calls = []

        def warm(found):
            def leg(setup, folder, env, card_log, requests):
                calls.append((setup["card_log"], card_log, folder.is_dir(), requests,
                              sorted(p.name for p in folder.glob("*.dck"))))
                return found
            return leg

        with mock.patch.object(forge.servecheck, "warm_leg", warm(None)):
            self.assertEqual(self.check()[0], 0)
        (log, card_log, there, requests, dcks), = calls
        self.assertEqual((log, card_log, there), (CARD_LOG, CARD_LOG, True))
        legs = {fmt: forge.cli._check_sides(decks_, fmt) for fmt, decks_, _ in forge.cli._check_legs(6, 2)}
        self.assertEqual(requests, [(fmt, f"{legs[fmt][0][0]}.dck", f"{legs[fmt][0][1]}.dck", n, 1,
                                     {"stream": forge.seeds.stream_hex(legs[fmt][1]), "first": 0})
                                    for fmt, n in (("Constructed", 6), ("Commander", 2))])
        self.assertEqual(len(dcks), 4)
        with mock.patch.object(forge.servecheck, "warm_leg", warm(("unsure", ["A warm game differed once."]))):
            code, out, _ = self.check()
        self.assertEqual((code, out), (1, "A warm game differed once.\nNothing was noted, so runs with Forge 2.0.15 "
                                          "go on as they were.\n"))
        with mock.patch.object(forge.servecheck, "warm_leg", warm(("failed", ["A warm game differed twice."]))):
            code, out, _ = self.check()
        self.assertEqual((code, out), (1, "A warm game differed twice.\nRuns with Forge 2.0.15 go without the card log "
                                          "until a check passes.\n"))

    def test_the_cardlog_check_compares_games_without_card_log_lines_or_timings(self):
        header = "Ai(1)-a [Default] vs Ai(2)-b [Default] - 2 games of Constructed seed 1\n"
        plain = ("noise 12 ms\n" + header + "Turn: Turn 1 (Ai(1)-a)\nGame Outcome: Match Duration 0m : 07s\n"
                 "Game Result: Game 1 ended in 812 ms. Ai(1)-a has won!\n"
                 "Turn: Turn 1 (Ai(2)-b)\nGame Result: Game 2 ended in a Draw! Took 5 ms.\n")
        logged = ("other noise\nDLENGINE|v=2|seeds=game\n" + header + "Information: DL|log|1\nTurn: Turn 1 (Ai(1)-a)\n"
                  "Information: DL|hand|1|start|1|\nWARNING: A terminally deprecated method in sun.misc.Unsafe\n"
                  "Game Outcome: Match Duration 0m : 06s\n"
                  "Game Result: Game 1 ended in 799 ms. Ai(1)-a has won!\nInformation: DL|log|1\nTurn: Turn 1 (Ai(2)-b)\n"
                  "Game Result: Game 2 ended in a Draw! Took 9 ms.\n")
        self.assertIsNone(forge.cli._first_difference(plain, logged))
        self.assertEqual(forge.cli._first_difference(plain, logged.replace("(Ai(2)-b)", "(Ai(1)-a)")),
                         "game 2, line 1: plain Forge printed 'Turn: Turn 1 (Ai(2)-b)', "
                         "Deck Lab's engine 'Turn: Turn 1 (Ai(1)-a)'")
        self.assertEqual(forge.cli._first_difference(plain, logged.split("Information: DL|log|1\nTurn: Turn 1 (Ai(2)")[0]),
                         "plain Forge played 2 games, Deck Lab's engine 1")
        # Plain Forge's one-game processes, one after the other, are the same games: each its own header, its game
        # "Game 1", and its own noise and JVM warning.
        one = header.replace("2 games", "one game")
        apart = ["noise\n" + one + "Turn: Turn 1 (Ai(1)-a)\nWARNING: x\nGame Outcome: Match Duration 0m : 01s\n"
                 "Game Result: Game 1 ended in 5 ms. Ai(1)-a has won!\n",
                 "more noise\n" + one + "Turn: Turn 1 (Ai(2)-b)\nGame Result: Game 1 ended in a Draw! Took 1 ms."]
        self.assertIsNone(forge.cli._first_difference(apart, logged))
        self.assertEqual(len(forge.cli._split_games(apart)), 2)
        # Attackers in another order are the same (plain Forge itself lists them in any order).
        attack = "Combat: Ai(1)-a assigned {} to attack Ai(2)-b.\nGame Outcome: Match"
        self.assertIsNone(forge.cli._first_difference(
            plain.replace("Game Outcome: Match", attack.format("Krenko, Mob Boss (100), Goblin Token (311) and Goblin Token (30)")),
            logged.replace("Game Outcome: Match", attack.format("Goblin Token (30), Goblin Token (311) and Krenko, Mob Boss (100)"))))
        self.assertIsNotNone(forge.cli._first_difference(
            plain.replace("Game Outcome: Match", attack.format("Krenko, Mob Boss (100) and Goblin Token (311)")),
            logged.replace("Game Outcome: Match", attack.format("Goblin Token (30) and Krenko, Mob Boss (100)"))))
        # A difference in a game that hit one of Forge's time limits, in either copy, can't tell.
        reader = mock.Mock(cards={"bad": 0}, card_problems=[])
        other = logged.replace("(Ai(2)-b)", "(Ai(1)-a)")
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Constructed", 2, plain, other, reader)[0], "failed")
        slow = other.replace("Information: DL|log|1\nTurn: Turn 1 (Ai(1)-a)\nGame Result: Game 2",
                             "Information: DL|log|1\nAI eval thread at timeout:\nTurn: Turn 1 (Ai(1)-a)\nGame Result: Game 2")
        self.assertNotEqual(slow, other)
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Constructed", 2, plain, slow, reader)[0], "unsure")
        slow_plain = plain.replace("Turn: Turn 1 (Ai(2)-b)", "Stopping slow match as draw\nTurn: Turn 1 (Ai(2)-b)")
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Constructed", 2, slow_plain, other, reader)[0], "unsure")
        # A time limit hit in game 1 of the same process can change game 2 (its thread can still be going and
        # drawing from game 2's random numbers): unsure too, in Constructed as in Commander.
        early = other.replace("Information: DL|hand|1|start|1|\n", "Information: DL|hand|1|start|1|\nAI eval thread at timeout:\n")
        early_plain = plain.replace("Game Outcome: Match", "AI eval thread at timeout:\nGame Outcome: Match")
        found = forge.cli._leg_problem("2.0.15", "Constructed", 2, early_plain, early, reader)
        self.assertEqual(found[0], "unsure")
        self.assertTrue(found[1][-1].startswith("Game 1 hit one of Forge's time limits"), found)
        self.assertIn("can change the games after it in the same process", found[1][-1])
        # Plain Forge playing each game in a process of its own: a time limit in its game 1 isn't game 2's.
        early_apart = [apart[0].replace("WARNING: x\n", "AI eval thread at timeout:\n"), apart[1].replace("Ai(2)-b)", "Ai(1)-a)")]
        self.assertEqual(forge.cli._time_limit_game(early_apart, logged, 2), None)
        self.assertEqual(forge.cli._time_limit_game(early_apart, logged, 1), 1)
        self.assertEqual(forge.cli._time_limit_game(early_plain, logged, 2), 1)      # one process: game 1 counts
        self.assertIsNone(forge.cli._leg_problem("2.0.15", "Constructed", 2, plain, logged, reader))
        # A card log that went wrong fails the check whatever the timing.
        bad = mock.Mock(cards={"bad": 1}, card_problems=[(2, "seat 1's end hand isn't what its moves add up to")])
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Constructed", 2, plain, slow, bad),
                         ("failed", ["Deck Lab's engine (its game patches off) didn't play the same Constructed games as "
                                     "plain Forge 2.0.15: game 2, line 1: plain Forge printed 'Turn: Turn 1 (Ai(2)-b)', "
                                     "Deck Lab's engine 'AI eval thread at timeout:'.",
                                     "The card log of 1 of the 2 Constructed games failed its checks:",
                                     "  game 2: seat 1's end hand isn't what its moves add up to"]))
        no_log = slow.replace("Information: DL|log|1\nAI eval", "AI eval")
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Constructed", 2, plain, no_log, reader),
                         ("failed", ["Deck Lab's engine (its game patches off) didn't play the same Constructed games as "
                                     "plain Forge 2.0.15: game 2, line 1: plain Forge printed 'Turn: Turn 1 (Ai(2)-b)', "
                                     "Deck Lab's engine 'AI eval thread at timeout:'.",
                                     "The card log wrote its lines in 1 of the 2 Constructed games."]))
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Constructed", 2, plain,
                                                logged.replace("Information: DL|log|1\nTurn: Turn 1 (Ai(2)", "Turn: Turn 1 (Ai(2)"),
                                                reader),
                         ("failed", ["The card log wrote its lines in 1 of the 2 Constructed games."]))
        # The card log on against off: named so.
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Constructed", 2, plain, other, reader,
                                                forge.cli.CARD_LOG_LEG)[1][0],
                         "The card log changed the Constructed games it was kept in (Forge 2.0.15): game 2, line 1: "
                         "without the card log printed 'Turn: Turn 1 (Ai(2)-b)', with it 'Turn: Turn 1 (Ai(1)-a)'.")

    def test_the_cardlog_check_needs_both_commanders_in_every_commander_game(self):
        header = "Ai(1)-a [Default] vs Ai(2)-b [Default] - 2 games of Commander seed 1\n"
        plain = header + "".join(f"Turn: Turn 1 (Ai(1)-a)\nGame Result: Game {n} ended in 5 ms. Ai(1)-a has won!\n"
                                 for n in (1, 2))
        logged = header + "".join(
            "Information: DL|log|1\nInformation: DL|deck|1|1=X\nInformation: DL|commander|1|901=A\n"
            + ("Information: DL|commander|2|902=B\n" if n == 1 else "")
            + f"Turn: Turn 1 (Ai(1)-a)\nGame Result: Game {n} ended in 7 ms. Ai(1)-a has won!\n" for n in (1, 2))
        reader = mock.Mock(cards={"bad": 0}, card_problems=[])
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Commander", 2, plain, logged, reader),
                         ("failed", ["The card log didn't name both commanders in 1 of the 2 Commander games."]))
        both = logged.replace("Information: DL|commander|1|901=A\nTurn", "Information: DL|commander|1|901=A\n"
                                                                           "Information: DL|commander|2|902=B\nTurn")
        self.assertIsNone(forge.cli._leg_problem("2.0.15", "Commander", 2, plain, both, reader))
        self.assertIsNone(forge.cli._leg_problem("2.0.15", "Constructed", 2, plain, logged, reader))   # not asked for
        reader = mock.Mock(cards={"bad": 1}, card_problems=[(2, "seat 1's end hand isn't what its moves add up to")])
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Commander", 2, plain, both, reader),
                         ("failed", ["The card log of 1 of the 2 Commander games failed its checks:",
                                     "  game 2: seat 1's end hand isn't what its moves add up to"]))
        # Commander games are compared by winner, starter and length, not line for line.
        reader = mock.Mock(cards={"bad": 0}, card_problems=[])
        blocked = both.replace("Turn: Turn 1 (Ai(1)-a)\nGame Result: Game 1",
                               "Turn: Turn 1 (Ai(1)-a)\nCombat: Ai(2)-b assigned X (3) to block Y (4).\nGame Result: Game 1")
        self.assertNotEqual(blocked, both)
        self.assertIsNone(forge.cli._leg_problem("2.0.15", "Commander", 2, plain, blocked, reader))
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Constructed", 2, plain, blocked, reader)[0], "failed")
        # Plain Forge's games, one process each, are compared the same way.
        apart = [header.replace("2 games", "one game") + "Turn: Turn 1 (Ai(1)-a)\n"
                 "Game Result: Game 1 ended in 5 ms. Ai(1)-a has won!\n"] * 2
        self.assertIsNone(forge.cli._leg_problem("2.0.15", "Commander", 2, apart, blocked, reader))
        # A Commander game that ends differently can't be put down to the card log: plain Forge's
        # own Commander games can block differently, which can change how a game ends.
        longer = both.replace("Turn: Turn 1 (Ai(1)-a)\nGame Result: Game 2",
                              "Turn: Turn 1 (Ai(1)-a)\nTurn: Turn 2 (Ai(2)-b)\nGame Result: Game 2")
        differs = ("Deck Lab's engine (its game patches off) didn't play the same Commander games as plain Forge 2.0.15: "
                   "game 2 was a draw on turn 1 (Ai(1) first) with plain Forge, a draw on turn 2 (Ai(1) first) with "
                   "Deck Lab's engine.")   # no "has won" line
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Commander", 2, plain, longer, reader),
                         ("unsure", [differs, "Plain Forge itself doesn't play a Commander game the same way every time "
                                              "(two runs of one seed can block differently, which can change how a game "
                                              "ends), so the check can't tell whether the card log plays the same games. "
                                              "Run it again."]))
        # A time limit in that game or one before it of the same process (its thread can play on into the
        # games after it) is said instead.
        limits = ("one of Forge's time limits (\"Stopping slow match as draw\" or \"AI eval thread at timeout\"), which a "
                  "busy computer can cause in one copy of a game and not the other")
        tail = ", so the check can't tell whether the card log plays the same games. Run it again when the computer is less busy."
        slow_first = longer.replace("Game Result: Game 1", "AI eval thread at timeout:\nGame Result: Game 1")
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Commander", 2, plain, slow_first, reader),
                         ("unsure", [differs, f"Game 1 hit {limits}, and which can change the games after it in the same "
                                              f"process{tail}"]))
        slow_plain = plain.replace("Game Result: Game 2", "AI eval thread at timeout:\nGame Result: Game 2")
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Commander", 2, slow_plain, slow_first, reader),
                         ("unsure", [differs, f"Game 1 hit {limits}, and which can change the games after it in the same "
                                              f"process{tail}"]))       # the first one either copy hit
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Commander", 2, slow_plain, longer, reader),
                         ("unsure", [differs, f"That game hit {limits}{tail}"]))
        # But a card log that went wrong fails it, however the games ended.
        bad = mock.Mock(cards={"bad": 1}, card_problems=[(1, "seat 2 has no end hand")])
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Commander", 2, slow_plain, longer, bad),
                         ("failed", [differs, "The card log of 1 of the 2 Commander games failed its checks:",
                                     "  game 1: seat 2 has no end hand"]))
        unnamed = longer.replace("Information: DL|commander|2|902=B\nTurn: Turn 1 (Ai(1)-a)\nTurn: Turn 2",
                                 "Turn: Turn 1 (Ai(1)-a)\nTurn: Turn 2")
        self.assertNotEqual(unnamed, longer)
        self.assertEqual(forge.cli._leg_problem("2.0.15", "Commander", 2, plain, unnamed, reader),
                         ("failed", [differs, "The card log didn't name both commanders in 1 of the 2 Commander games."]))


if __name__ == "__main__":
    unittest.main()
