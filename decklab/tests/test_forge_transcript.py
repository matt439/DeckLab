"""Single-game selection, readable log and exact replay protocol, with no native game/result writes."""
import argparse
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab.lib.forge import cli, cli_shared as shared, cli_soak, cli_transcript, transcript


LOG = """startup path must not be displayed
Ai(1)-a - Ai(2)-b - 1 game of Constructed
Information: DL|log|1
Information: DL|hand|1|start|1|1=Forest;2=Llanowar Elves
Turn: Turn 1 (Ai(1)-a)
Land: Ai(1)-a played Forest (1)
Add To Stack: Ai(1)-a cast Llanowar Elves
Add To Stack: Llanowar Elves (2) - [Couldn't add to stack]
Combat: Ai(1) attacks with Creature
Life: Ai(2) loses 2 life
Information: DL|hand|2|end|1|2=Llanowar Elves
Information: DL|hand|2|end|2|
Game Result: Game 1 ended in 10 ms. Ai(1)-a has won!
must not include another game
"""


def result(format="Constructed"):
    return {"key": "a"*64, "format": format, "run_version": 2, "engine": {"kind": "decklab"},
            "seeds": {"base": 1, "stream": "0123456789abcdef", "flip": False},
            "sides": [{"card_sha": str(side)*64, "dck": f"[Main]\n60 Land{side}\n",
                       "pilot": {"profile": "Default", "switches": []},
                       "seen_as": [{"id": f"casual/{name}", "title": name}]} for side, name in enumerate(("a", "b"))],
            "batches": [{"games": [{"g": 5, "r": "win", "w": 0, "first": 0, "turns": 2, "ms": 10},
                                    {"g": 9, "r": "win", "w": 1, "first": 1, "turns": 8, "ms": 20},
                                    {"g": 12, "r": "timeout", "w": None, "first": 0, "turns": 30, "ms": 50}]}]}


class TranscriptTests(unittest.TestCase):
    def test_pick_saved_numbers_losses_longest_and_timeouts_without_mutating(self):
        found = result()
        before = copy.deepcopy(found)
        self.assertEqual(transcript.pick(found, 0)["g"], 9)
        self.assertEqual(transcript.pick(found, 1)["g"], 5)
        self.assertEqual(transcript.pick(found, choice="longest")["g"], 12)
        self.assertEqual(transcript.pick(found, choice="timeout")["g"], 12)
        self.assertEqual(transcript.pick(found, number=5)["g"], 5)
        self.assertEqual(found, before)
        with self.assertRaises(ValueError):
            transcript.pick(found, number=6)
        found["batches"][0]["games"].append(found["batches"][0]["games"][0])
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            transcript.pick(found, number=5)

    def test_readable_events_cover_failed_cast_combat_life_and_both_end_hands(self):
        events = transcript.events(LOG)
        self.assertEqual({row["kind"] for row in events}, {"turn", "land", "cast", "failed_cast", "combat", "life", "hand_start", "hand_end", "outcome"})
        ends = [row for row in events if row["kind"] == "hand_end"]
        self.assertEqual([(row["seat"], row["cards"]) for row in ends], [(1, ["Llanowar Elves"]), (2, [])])
        text = transcript.render(events)
        self.assertIn("Turn 1", text)
        self.assertIn("Hand at end, seat 2: empty", text)
        self.assertNotIn("DL|", text)
        self.assertNotIn("startup path", text)
        self.assertNotIn("another game", text)
        with mock.patch.object(transcript, "MAX_EVENTS", 2), self.assertRaises(ValueError):
            transcript.events(LOG)

    def test_replay_one_shot_uses_exact_stored_dcks_number_seed_and_pilot_protocol(self):
        found = result()
        found["sides"][1]["pilot"] = {"profile": "C4", "switches": ["team-pump"]}
        before = copy.deepcopy(found)
        process = SimpleNamespace(communicate=mock.Mock(return_value=(LOG.encode(), None)))
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(shared.runner, "_java", return_value=["java"]), \
                mock.patch.object(shared.runner, "_class_path_launch", return_value=["launch"]), \
                mock.patch.object(shared.runner, "request_args", return_value=["request"]) as args, \
                mock.patch.object(shared, "_prepare_user_dir", return_value={"ONLY": "synthetic"}), \
                mock.patch.object(shared.processes, "start_process", return_value=process) as start:
            setup = {"user_dir": Path(folder)/"user", "forge_dir": Path(folder)/"forge", "clock_s": 120}
            self.assertEqual(transcript.replay(setup, Path(folder), found, 26), LOG)
            self.assertEqual({path.name: path.read_text() for path in Path(folder).glob("*.dck")},
                             {side["card_sha"]+".dck": side["dck"] for side in found["sides"]})
            self.assertEqual(args.call_args.args[4:6], (1, 1))
            self.assertEqual(args.call_args.kwargs["v2"], {"stream": found["seeds"]["stream"], "first": 26})
            self.assertEqual(args.call_args.kwargs["pilots"], [found["sides"][1]["pilot"], found["sides"][0]["pilot"]])
            start.assert_called_once_with(["java", "launch", "request"], cwd=str(setup["forge_dir"]), env={"ONLY": "synthetic"})
        self.assertEqual(found, before)

    def test_soak_probe_reuses_the_same_replay_helper(self):
        with mock.patch.object(transcript, "replay", return_value="log") as replay:
            self.assertEqual(cli_soak._soak_fresh("setup", "folder", "result", 3), "log")
        replay.assert_called_once_with("setup", "folder", "result", 3)

    def test_missing_end_hands_are_explicit_unknown_instead_of_empty(self):
        without = "\n".join(line for line in LOG.splitlines() if "|end|" not in line)
        events = transcript.events(without)
        missing = [event for event in events if event["kind"] == "hand_unavailable"]
        self.assertEqual([event["seat"] for event in missing], [1, 2])
        self.assertTrue(all("not captured" in event["text"] and "cards" not in event for event in missing))

    def test_committed_native_failed_cast_log_is_readable(self):
        source = Path(__file__).parent / "fixtures/forge/cardlog-failed-cast-s5.log"
        events = transcript.events(source.read_text(encoding="utf-8"))
        self.assertTrue(any(event["kind"] == "failed_cast" for event in events))
        self.assertTrue(any(event["kind"] == "turn" for event in events))


class TranscriptCommandTests(unittest.TestCase):
    def args(self, *words):
        parser = argparse.ArgumentParser()
        cli_transcript.add_parser(parser.add_subparsers(dest="command", required=True))
        return parser.parse_args(["game", "casual/a", "casual/b", *words])

    def test_command_is_registered_and_rejects_other_engine_before_setup_or_game(self):
        self.assertIn("game", cli.COMMANDS)
        with mock.patch.object(shared.saved, "_stored", return_value=[result()]), \
                mock.patch.object(shared.engine, "is_current", return_value=False), \
                mock.patch.object(shared.engine, "words", return_value="other card overrides"), \
                mock.patch.object(shared, "_setup") as setup, mock.patch.object(transcript, "replay") as replay:
            with self.assertRaisesRegex(shared._CliError, "other card overrides"):
                cli_transcript.command(self.args("--game", "5"))
        setup.assert_not_called()
        replay.assert_not_called()

    def test_commander_json_records_outcome_difference_without_saving_statistics(self):
        found = result("Commander")
        before = copy.deepcopy(found)
        output = io.StringIO()
        with mock.patch.object(shared.saved, "_stored", return_value=[found]), \
                mock.patch.object(shared.engine, "is_current", return_value=True), \
                mock.patch.object(shared, "_setup", return_value={"java": "fake", "forge_dir": "fake", "jar": "fake", "version": "fake"}), \
                mock.patch.object(shared.simjar, "card_log", return_value={"ready": True}), \
                mock.patch.object(shared.slots, "claim", return_value=contextlib.nullcontext()), \
                mock.patch.object(transcript, "replay", return_value=LOG), \
                mock.patch.object(cli_transcript.checks, "_outcomes", return_value=[("win", 1, 0, 4)]), \
                mock.patch.object(shared, "run", side_effect=AssertionError("No result pipeline")) as run, \
                mock.patch.object(shared.common, "_write_atomic", side_effect=AssertionError("No result write")), \
                contextlib.redirect_stdout(output):
            self.assertEqual(cli_transcript.command(self.args("--game", "5", "--json")), 0)
        answer = json.loads(output.getvalue())
        self.assertEqual(answer["game"], 5)
        self.assertFalse(answer["statistics_written"])
        self.assertEqual(answer["differences"], ["winner", "turns"])
        self.assertIn("outcome only, not line for line", answer["note"])
        self.assertIn("Differs from the saved record", answer["note"])
        self.assertEqual(found, before)
        run.assert_not_called()
