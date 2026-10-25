"""Tests for decklab.lib.forge's decision log (AI round 1, the ai-r1 contract's section 3.8): its
DLAI| lines read (decisionlog.parse, read, read_folder, summary), the decisions command, the JVM
flag runner_launch._java adds, the warm pool's launch fields, and the readers that must pass over
the lines (LogReader, cli_checks._games_text).

No Forge runs: the lines are written here as the fork's forge.ai.AiDecisionLog prints them.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import gzip
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import forge
from decklab.lib.forge import cli_checks, decisionlog, runner_launch


def run_main(*argv):
    """(exit code, stdout) of forge.main(argv)."""
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")
    with mock.patch("sys.stdout", out), mock.patch("sys.stderr", io.StringIO()):
        code = forge.main(list(argv))
        out.flush()
    return code, out.buffer.getvalue().decode("utf-8")


def dlai(turn, phase, seat, decision, card, api="Draw", active=None):
    return f"DLAI|1|{turn}|{active or seat}|{phase}|{seat}|{decision}|{api}|{card}"


HEADER = "Ai(1)-Izzet vs Ai(2)-Gruul"
GAME_1 = [
    dlai(1, "MAIN1", 1, "CantAfford", "Pearl of Wisdom"),
    dlai(1, "UPKEEP", 1, "TimingRestrictions", "Divination"),           # sorcery speed outside a main phase
    dlai(1, "MAIN1", 1, "CantPlayAi", "Divination"),
    dlai(2, "MAIN1", 1, "CantPlayAi", "Pearl of Wisdom"),
    dlai(2, "MAIN1", 1, "WillPlay", "Pearl of Wisdom"),
    dlai(2, "END_OF_TURN", 2, "AnotherTime", "Pearl of Wisdom", active=1),
    "Turn: Turn 3 (Ai(1)-Izzet)",
    "Game Result: Game 1 ended in 812 ms. Ai(1)-Izzet has won!",
]
GAME_2 = [
    dlai(1, "MAIN1", 2, "CantPlayAi", "Pearl of Wisdom"),
    dlai(1, "MAIN2", 2, "MissingPhaseRestrictions", "Pearl of Wisdom"),
    "Game Result: Game 2 ended in 700 ms. Ai(2)-Gruul has won!",
    dlai(1, "MAIN1", 1, "WillPlay", "Pearl of Wisdom"),                  # a game with no result yet
]


class ParseTests(unittest.TestCase):

    def test_parse(self):
        self.assertEqual(decisionlog.parse(dlai(3, "MAIN1", 2, "WillPlay", "Burst Lightning", api="DealDamage",
                                                active=2) + "\r\n"),
                         {"turn": 3, "active": "2", "phase": "MAIN1", "seat": "2", "decision": "WillPlay",
                          "api": "DealDamage", "card": "Burst Lightning"})
        # The card is the rest of the line, whatever it holds.
        self.assertEqual(decisionlog.parse("DLAI|1|1|?|-|?|CantPlaySa|-|Fire // Ice")["card"], "Fire // Ice")
        for line in ("Information: DL|log|1", "DLAI|2|1|1|MAIN1|1|WillPlay|Draw|X", "DLAI|1|x|1|MAIN1|1|WillPlay|Draw|X",
                     "DLAI|1|1|1|MAIN1|1|WillPlay|Draw", "DLAI|1|1|1|MAIN1|1||Draw|X", "Turn: Turn 1"):
            with self.subTest(line=line):
                self.assertIsNone(decisionlog.parse(line))


class ReadTests(unittest.TestCase):

    def test_games_opportunities_taken_and_declined(self):
        games = decisionlog.read(GAME_1 + GAME_2)
        self.assertEqual(len(games), 2)                     # the third game has no result line yet
        pearl = games[0]["Pearl of Wisdom"]
        # Turn 1 MAIN1 was CantAfford only: no chance. Turn 2 MAIN1 was taken; seat 2's end step declined.
        self.assertEqual((pearl["opportunities"], pearl["taken"], pearl["declined"]), (2, 1, {"AnotherTime": 1}))
        self.assertEqual(pearl["by_phase"], {"MAIN1": {"opportunities": 1, "taken": 1},
                                             "END_OF_TURN": {"opportunities": 1, "taken": 0}})
        self.assertEqual(pearl["by_seat"], {"1": {"opportunities": 1, "taken": 1}, "2": {"opportunities": 1, "taken": 0}})
        # A TimingRestrictions-only window isn't an opportunity; the MAIN1 refusal is, declined.
        divination = games[0]["Divination"]
        self.assertEqual((divination["opportunities"], divination["taken"], divination["declined"]),
                         (1, 0, {"CantPlayAi": 1}))
        self.assertEqual(list(divination["by_phase"]), ["MAIN1"])
        # Each window counts once, declined under its last decision.
        self.assertEqual(games[1]["Pearl of Wisdom"]["declined"], {"CantPlayAi": 1, "MissingPhaseRestrictions": 1})
        # A no-chance decision after the refusal (a second ability, mana spent) doesn't name the reason.
        later = decisionlog.read([dlai(1, "MAIN1", 1, "CantPlayAi", "Opt"), dlai(1, "MAIN1", 1, "CantAfford", "Opt"),
                                  "Game Result: Game 1 ended in 1 ms."])
        self.assertEqual(later[0]["Opt"]["declined"], {"CantPlayAi": 1})

    def test_only_the_cards_named(self):
        games = decisionlog.read(GAME_1, names=["pearl of wisdom"])
        self.assertEqual(list(games[0]), ["Pearl of Wisdom"])
        # A card whose lines are all no-chance decisions is listed with nothing counted.
        only = decisionlog.read([dlai(1, "MAIN1", 1, "CantAfford", "Opt"), "Game Result: Game 1 ended in 1 ms."])
        self.assertEqual(only[0]["Opt"]["opportunities"], 0)

    def test_summary(self):
        totals = decisionlog.summary(decisionlog.read(GAME_1 + GAME_2))
        pearl = totals["Pearl of Wisdom"]
        self.assertEqual((pearl["games"], pearl["opportunities"], pearl["taken"]), (2, 4, 1))
        self.assertEqual(pearl["declined"], {"AnotherTime": 1, "CantPlayAi": 1, "MissingPhaseRestrictions": 1})
        self.assertEqual(pearl["by_phase"]["MAIN1"], {"opportunities": 2, "taken": 1})
        self.assertEqual(pearl["by_seat"]["2"], {"opportunities": 3, "taken": 0})


class FolderTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name, lines):
        with gzip.open(self.tmp / name, "wt", encoding="utf-8") as f:
            f.write("\n".join([HEADER, *lines]) + "\n")

    def test_a_tee_folder(self):
        self.write("0-1.log.gz", GAME_1 + GAME_2[:3])
        self.write("2-2.log.gz", GAME_1)
        self.write("1-1.log.gz", GAME_1)                    # a chunk played again: game 1 is the first file's
        self.write("5-6.log.gz", GAME_1)                    # one game, not the two its name says
        (self.tmp / "notes.txt").write_text("x", encoding="utf-8")
        with mock.patch.object(forge.common, "_log") as log:
            games = decisionlog.read_folder(self.tmp)
        self.assertEqual(sorted(games), [0, 1, 2])
        self.assertEqual(games[0]["Pearl of Wisdom"]["taken"], 1)
        self.assertEqual(games[1]["Pearl of Wisdom"]["taken"], 0)
        self.assertIn("5-6.log.gz", log.call_args[0][0])
        self.assertEqual(sorted(decisionlog.read_folder(self.tmp, games=(2, 9))), [2])
        self.assertEqual(list(decisionlog.read_folder(self.tmp, names=["Divination"])[0]), ["Divination"])

    def test_the_decisions_command(self):
        self.write("0-1.log.gz", GAME_1 + GAME_2[:3])
        code, text = run_main("decisions", str(self.tmp), "--card", "Pearl of Wisdom")
        self.assertEqual(code, 0)
        self.assertIn("2 games in", text)
        self.assertIn("Pearl of Wisdom: an opportunity in 2 games; 4 opportunities, 1 taken", text)
        self.assertIn("declined: AnotherTime 1, CantPlayAi 1, MissingPhaseRestrictions 1", text)
        self.assertIn("by phase: MAIN1 1/2", text)
        code, out = run_main("decisions", str(self.tmp), "--json")
        found = json.loads(out)
        self.assertEqual((found["games"], found["cards"]["Divination"]["opportunities"]), (2, 1))


class LaunchTests(unittest.TestCase):

    def setup(self, **extra):
        return {"java": "java", "xmx": "64m", "card_log": {"ready": True}, **extra}

    def test_the_flag_needs_the_card_log_and_names(self):
        flag = runner_launch.DECISION_LOG_FLAG
        self.assertEqual(flag, "-Ddecklab.decisionLog")
        argv = runner_launch._java(self.setup(decision_log=["Pearl of Wisdom", "Éowyn, Fearless Knight",
                                                             "Fire // Ice", "100%; Odd|Name"]))
        found = [a for a in argv if a.startswith(flag + "=")]
        self.assertEqual(found, [flag + "=Pearl of Wisdom;%C3%89owyn, Fearless Knight;Fire;100%25%3B Odd%7CName"])
        # "*" (every card) goes as it is.
        self.assertIn(flag + "=*", runner_launch._java(self.setup(decision_log=["*"])))
        self.assertFalse(any(a.startswith(flag) for a in runner_launch._java(self.setup(decision_log=[]))))
        self.assertFalse(any(a.startswith(flag) for a in runner_launch._java(self.setup())))
        self.assertFalse(any(a.startswith(flag) for a in runner_launch._java(
            {"java": "java", "xmx": "64m", "card_log": {"ready": False}, "decision_log": ["Opt"]})))

    def test_launch_fields_carry_the_list(self):
        eng = {"deployed": {"hash": "none"}, "performance_mode": True}
        fields = forge.engine.launch_fields({"user_dir": "u", "decision_log": ["Opt", "Divination"]}, eng)
        self.assertEqual(fields["decision_log"], ["Divination", "Opt"])
        self.assertIsNone(forge.engine.launch_fields({"user_dir": "u"}, eng)["decision_log"])
        self.assertEqual(forge.pool.LAUNCH_WORDS["decision_log"], "the decision log (forge_decision_log)")


class ReaderTests(unittest.TestCase):

    GAME = ["Simulation mode", "Ai(1)-a vs Ai(2)-b - 1 game of Constructed",
            "Turn: Turn 1 (Ai(1)-a)", dlai(1, "MAIN1", 1, "WillPlay", "Opt"),
            "Add To Stack: Ai(1)-a cast Opt (12)", dlai(1, "MAIN1", 2, "CantPlayAi", "Opt"),
            "Game Outcome: Ai(1)-a has won because all opponents have lost",
            "Game Result: Game 1 ended in 812 ms. Ai(1)-a has won!"]

    def read(self, lines):
        reader = forge.LogReader(0)
        for line in lines:
            reader.feed(line)
        reader.close()
        return reader

    def test_log_reader_and_games_text_pass_over_dlai_lines(self):
        plain = [line for line in self.GAME if not line.startswith(decisionlog.PREFIX)]
        a, b = self.read(self.GAME), self.read(plain)
        self.assertEqual((a.games, a.casts), (b.games, b.casts))
        self.assertEqual(cli_checks._games_text("\n".join(self.GAME)), cli_checks._games_text("\n".join(plain)))
        self.assertEqual(cli_checks._games_text("\n".join(self.GAME), keep_card_log=True),
                         cli_checks._games_text("\n".join(plain), keep_card_log=True))
        # keep_card_log keeps the card log's DL| lines; without it they go.
        logged = self.GAME[:3] + ["Information: DL|zone|1"] + self.GAME[3:]
        self.assertIn("Information: DL|zone|1", cli_checks._games_text("\n".join(logged), keep_card_log=True)[0])
        self.assertNotIn("Information: DL|zone|1", cli_checks._games_text("\n".join(logged))[0])


if __name__ == "__main__":
    unittest.main()
