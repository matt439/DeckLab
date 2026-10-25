"""Real-Java tests of DeckLabSim's v2 game loop (java/decklab/GameLoop.java playGames, with
Request.java's v2 arguments; wave 2's contract, forge-trial/sim-wave2-contract.md, "The v2 game
loop" and "The request"), against the installed Forge and JDK. They need DECKLAB_FORGE_TESTS=1
(and Forge and a JDK); without it every test is skipped.

They play cardlog-check's decks (cli.CHECK_DECKS, CHECK_COMMANDER_DECKS, plus two made to set
Forge's auto-profile) with DeckLabSim built from this checkout's source (simjar.card_log with
checking=True) and with plain Forge, at most AT_ONCE processes at once, below normal priority,
about 40 games in all. Each process holds one of the PC's own Forge slots while it runs (slots.py,
waiting for one): decklab/tests/__init__.py points the tests at a slots folder of their own, but
these play real Forge on a PC that pools, runs and checks share, so this module points them back
at the PC's while it runs.
- parity: game g of a v2 request, with the game patches off, is plain Forge's "sim -n 1 -s
  <seeds.game_seed(base, stream, g)>" with the same deck order, line for line with cardlog-check's
  masks (cli._games_text: timings, the Game Result ordinal, stack-trace frames, attackers in name
  order, no DL| lines), without the JVM's "WARNING:" lines and each game's leading blank lines
  (trimmed) in Constructed, and by winner, starter and length in Commander;
- chunks: games [0, 6) in one request, in two ([0, 2) and [2, 6)), and game 4 alone, are the same
  games, card log lines and all;
- the card log on and off (-dlnocardlog): the same games;
- the DLENGINE line's v2 fields and Forge's header line (its seed is the result's base), the
  auto-profile flags of a deck named "... Control" and of one averaging over 3, and
  PERFORMANCE_MODE taken from the user folder's preferences file (perf=true);
- through one serve worker: the requests Request.parse refuses with -dlgame, a deck or AI profile
  Forge doesn't know (each request ends "error", and the worker plays on), and a good request
  (with -f in lower case, which Forge reads as its game type).

Run from the repo root (PowerShell): $env:DECKLAB_FORGE_TESTS=1; python -m unittest decklab.tests.test_forge_v2loop
"""
import hashlib
import inspect
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from decklab.lib.forge import cardlog, cli, install, logreader, processes, runner, seeds, simjar, slots

REAL = os.environ.get("DECKLAB_FORGE_TESTS") == "1"
AT_ONCE = 3                     # Forge processes at once
TIMEOUT = 600                   # seconds a process may take
BASE = cli.CHECK_SEED
A, B = "cardlog-check-a.dck", "cardlog-check-b.dck"
KRENKO, ISAMARU = "cardlog-check-krenko.dck", "cardlog-check-isamaru.dck"
CONTROL, BIG = "v2-control.dck", "v2-big.dck"
# A deck whose name holds "Control" (cardlog-check-b's cards: average mana value 2), and one
# averaging 4 (Forge's Deck.getAverageCMC: over distinct nonland cards, the division truncated).
EXTRA_DECKS = {
    CONTROL: ("Draw-Go Control", cli.CHECK_DECKS["cardlog-check-b"]),
    BIG: ("v2-big", ["4 Shivan Dragon", "4 Serra Angel", "4 Hill Giant", "4 Fire Elemental", "4 Gray Ogre",
                     "10 Mountain", "10 Plains"]),
}
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)

S = {}                          # setUpModule's: setup, folder, env, stream, outputs


def _write_deck(folder, file_name, name, main, commander=()):
    sections = ([("Commander", commander)] if commander else []) + [("Main", main)]
    text = f"[metadata]\nName={name}\n" + "".join(f"[{section}]\n" + "\n".join(lines) + "\n"
                                                 for section, lines in sections)
    (folder / file_name).write_text(text, encoding="utf-8", newline="\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def setUpModule():
    # Everything made here is undone by a module cleanup registered as soon as it's made: those
    # run when setUpModule fails part way too, which tearDownModule doesn't.
    if not REAL:
        return
    named = os.environ.pop(slots.ENV, None)     # the PC's own slots while this module runs
    if named is not None:
        unittest.addModuleCleanup(os.environ.__setitem__, slots.ENV, named)
    setup = install._setup()
    log = simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], setup["version"], checking=True)
    if not log["ready"]:
        raise unittest.SkipTest(f"the card log can't be built: {log['problem']}")
    folder = Path(tempfile.mkdtemp(prefix="decklab-v2loop-"))
    unittest.addModuleCleanup(shutil.rmtree, folder, ignore_errors=True)
    shas = [_write_deck(folder, f"{name}.dck", name, cards) for name, cards in cli.CHECK_DECKS.items()]
    for name, (commander, cards) in cli.CHECK_COMMANDER_DECKS.items():
        _write_deck(folder, f"{name}.dck", name, cards, commander)
    for file_name, (name, cards) in EXTRA_DECKS.items():
        _write_deck(folder, file_name, name, cards)
    perf_user = Path(tempfile.mkdtemp(prefix="decklab-v2loop-user-"))
    unittest.addModuleCleanup(shutil.rmtree, perf_user, ignore_errors=True)
    prefs = perf_user / "Forge" / "preferences" / "forge.preferences"
    prefs.parent.mkdir(parents=True)
    prefs.write_text(runner.PREFERENCES.replace("PERFORMANCE_MODE=true\n", "") + "PERFORMANCE_MODE=true\n",
                     encoding="utf-8", newline="\n")
    perf_env = dict(os.environ, APPDATA=str(perf_user), LOCALAPPDATA=str(perf_user))
    unittest.addModuleCleanup(runner._tidy_user_dir, setup["user_dir"])
    env = runner._prepare_user_dir(setup["user_dir"])
    S.update(setup=dict(setup, decks_dir=folder, card_log=log), folder=folder, env=env, perf_env=perf_env,
             stream=seeds.stream_hex(seeds.stream_of(*shas)), outputs={})


def v2(first, games, deck1=A, deck2=B, fmt="Constructed", patches=True, card_log=True):
    """A v2 one-shot DeckLabSim command line: games [first, first + games) of the check's result."""
    launch = S["setup"] if patches else dict(S["setup"], game_patches=False)
    spec = {"stream": S["stream"], "first": first}
    if not card_log:
        spec["card_log"] = False
    return runner.build_command(launch, fmt, deck1, deck2, games, BASE, spec)


def plain(game, deck1=A, deck2=B, fmt="Constructed"):
    """Plain Forge's "sim -n 1 -s <game g's seed>"."""
    launch = dict(S["setup"], card_log={"ready": False})
    return runner.build_command(launch, fmt, deck1, deck2, 1, seeds.game_seed(BASE, int(S["stream"], 16), game))


def _run(argv, env):
    """One process's output (stdout and stderr), killed after TIMEOUT seconds. It holds one of
    the PC's slots while it runs, waiting for one (as cardlog-check's processes do)."""
    lease = slots.claim(1, S["setup"]["workers"], what="test_forge_v2loop")
    try:
        proc = processes.start_process(argv, cwd=S["setup"]["forge_dir"], env=env)
        timer = threading.Timer(TIMEOUT, processes.kill_process, (proc,))
        timer.start()
        try:
            out = proc.stdout.read()
            proc.wait()
        finally:
            timer.cancel()
            processes.kill_process(proc)
            proc.stdout.close()
            processes._end_process(proc)
    finally:
        lease.release()
    return out


def _start_worker(argv, cwd, env):
    """A serve worker with its input and output on pipes: through processes.start_process (in
    Deck Lab's Job Object, below normal priority) once it can give one its input (wave 2's PP
    adds stdin=True for the warm pool), else Popen below normal priority."""
    if "stdin" in inspect.signature(processes.start_process).parameters:
        return processes.start_process(argv, cwd=cwd, env=env, stdin=True)
    return subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1,
                            creationflags=FLAGS)


def play(runs):
    """{name: output} for runs ({name: (argv, env)}), each played once per module (kept in
    S["outputs"]), AT_ONCE at a time; on a user folder's first use, the first process alone
    (as runner._play does)."""
    todo = {name: run for name, run in runs.items() if name not in S["outputs"]}
    marker = runner._first_use_marker(S["setup"]["user_dir"], S["setup"]["version"])
    if todo and not marker.exists():
        name = next(iter(todo))
        S["outputs"][name] = _run(*todo.pop(name))
        marker.touch()
    with ThreadPoolExecutor(AT_ONCE) as pool:
        found = {name: pool.submit(_run, *run) for name, run in todo.items()}
        S["outputs"].update({name: future.result() for name, future in found.items()})
    return {name: S["outputs"][name] for name in runs}


def engine(output):
    """The output's DLENGINE fields."""
    return logreader.engine_fields(next(line for line in output.splitlines()
                                        if line.startswith(logreader.ENGINE_PREFIX)))


def without_warnings(output):
    """output without the JVM's "WARNING:" lines, which it prints once per process, inside the
    first game that sets them off (the contract's "Mapping to today's readers")."""
    return "".join(line for line in output.splitlines(keepends=True) if not line.startswith("WARNING:"))


def trimmed(game):
    """A game's lines without the blank lines it starts with. Forge follows a won game's "Game
    Result" line with a blank line (its printf ends "has won!\\n%n"), which _split_games gives
    to the next game in the same output: so a game's first line depends on the game before it,
    and a game alone (the first of its output, or one after a draw) has none."""
    at = 0
    while at < len(game) and not game[at].strip():
        at += 1
    return game[at:]


def games_text(output):
    """cli._games_text (cardlog-check's masks) without the JVM's warnings, each game trimmed."""
    return [trimmed(game) for game in cli._games_text(without_warnings(output))]


def where(a, b):
    """Where two games' lines (_games_text) first differ, in words."""
    for i, (la, lb) in enumerate(zip(a, b)):
        if la != lb:
            return f"line {i + 1}: {la!r} vs {lb!r}"
    return f"{len(a)} lines vs {len(b)}"


def games_with_card_log(output):
    """_games_text with the card log's lines kept: each game's lines, masked as cardlog-check
    masks them."""
    return [trimmed([cli.RE_ORDINAL.sub(r"\g<1>?", cli.RE_TIMING.sub("?", cli._attackers_in_order(line)))
                     for line in game if not cli.RE_FRAME.match(line)])
            for game in cli._split_games(without_warnings(output))]


@unittest.skipUnless(REAL, "set DECKLAB_FORGE_TESTS=1 to play real Forge games")
class ConstructedTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        env = S["env"]
        runs = {"v2 off": (v2(0, 6, patches=False), env), "chunk": (v2(0, 6), env),
                "chunk 0-2": (v2(0, 2), env), "chunk 2-6": (v2(2, 4), env), "game 4": (v2(4, 1), env),
                "no card log": (v2(0, 6, card_log=False), env)}
        runs.update({f"plain {g}": (plain(g), env) for g in range(6)})
        cls.out = play(runs)

    def test_game_g_is_plain_forges_game_of_its_seed(self):
        played = games_text(self.out["v2 off"])
        self.assertEqual(len(played), 6)
        for g in range(6):
            alone = games_text(self.out[f"plain {g}"])
            self.assertEqual(len(alone), 1, g)
            self.assertEqual(played[g], alone[0], f"game {g}: {where(alone[0], played[g])}")
        # Each game has a seed of its own: the six aren't one game six times.
        self.assertGreater(len({tuple(game) for game in played}), 1)

    def test_a_game_is_the_same_alone_and_in_any_chunk(self):
        whole = games_with_card_log(self.out["chunk"])
        self.assertEqual(len(whole), 6)
        self.assertEqual(games_with_card_log(self.out["chunk 0-2"]) + games_with_card_log(self.out["chunk 2-6"]),
                         whole)
        self.assertEqual(games_with_card_log(self.out["game 4"]), whole[4:5])
        self.assertTrue(all(any(line.startswith(cardlog.PREFIX + "log|") for line in game) for game in whole))

    def test_the_card_log_changes_no_game(self):
        self.assertEqual(games_text(self.out["no card log"]), games_text(self.out["chunk"]))
        self.assertFalse(any(line.startswith(cardlog.PREFIX) for line in self.out["no card log"].splitlines()))
        # Without game-changing patches in this jar, the patches-off games are the same as well.
        if not S["setup"]["card_log"].get("game_patches"):
            self.assertEqual(games_text(self.out["v2 off"]), games_text(self.out["chunk"]))

    def test_the_engine_line_and_the_header(self):
        perf = "true" if "PERFORMANCE_MODE=true" in runner.PREFERENCES.splitlines() else "false"
        patch_ids = ",".join(sorted(S["setup"]["card_log"].get("game_patches") or []))
        for name, first, card_log, patches in (("chunk", 0, "on", "on"), ("chunk 2-6", 2, "on", "on"),
                                                ("no card log", 0, "off", "on"), ("v2 off", 0, "on", "off")):
            fields = engine(self.out[name])
            # Wave 3's overrides field is the hash of the override sets in use, so only its form is fixed.
            self.assertRegex(fields.pop("overrides", ""), r"^[0-9a-f]{64}$", name)
            self.assertEqual(fields, {
                "v": "2", "seeds": "game", "base": str(BASE), "stream": S["stream"], "first": str(first),
                "perf": perf, "cardlog": card_log, "gamepatches": patches, "gamepatchids": patch_ids,
                "autoprofile": "0,0", "avgcmc": "1,2",
                # Deck order and the load seed are game patches, so they go off with them.
                "ai": "Default,Default", "aiprofiles": "dl", "pilots": "-,-",
                "deckorder": "1,1" if patches == "on" else "0,0", "loadseed": "1" if patches == "on" else "0"},
                name)
            lines = self.out[name].splitlines()
            at = next(i for i, line in enumerate(lines) if line.startswith(logreader.ENGINE_PREFIX))
            header = logreader.RE_HEADER.match(lines[at + 1])
            self.assertIsNotNone(header, lines[at + 1])
            self.assertEqual((header[1], header[2], header[3]),
                             ("Ai(1)-cardlog-check-a [Default] vs Ai(2)-cardlog-check-b [Default]", "Constructed",
                              str(BASE)))
        reader = logreader.LogReader(0, card_log=True)
        for line in self.out["chunk"].splitlines():
            reader.feed(line)
        self.assertEqual((len(reader.games), reader.cards["bad"], reader.failure(6, 0)), (6, 0, None))
        self.assertEqual(reader.engine["v"], "2")


@unittest.skipUnless(REAL, "set DECKLAB_FORGE_TESTS=1 to play real Forge games")
class CommanderTests(unittest.TestCase):

    def test_commander_games_match_plain_forge_by_outcome(self):
        env = S["env"]
        runs = {"commander v2": (v2(0, 2, KRENKO, ISAMARU, "Commander", patches=False), env)}
        runs.update({f"commander plain {g}": (plain(g, KRENKO, ISAMARU, "Commander"), env) for g in range(2)})
        out = play(runs)
        played = cli._outcomes(out["commander v2"])
        self.assertEqual(len(played), 2)
        for g in range(2):
            self.assertEqual(played[g], cli._outcomes(out[f"commander plain {g}"])[0], g)
        self.assertTrue(all(cli._names_both_commanders(game) for game in cli._split_games(out["commander v2"])))
        self.assertEqual(engine(out["commander v2"])["v"], "2")


@unittest.skipUnless(REAL, "set DECKLAB_FORGE_TESTS=1 to play real Forge games")
class AutoProfileTests(unittest.TestCase):

    def test_flags_and_performance_mode_from_the_preferences(self):
        out = play({"autoprofile": (v2(0, 1, CONTROL, BIG), S["perf_env"])})["autoprofile"]
        fields = engine(out)
        self.assertEqual((fields["autoprofile"], fields["avgcmc"]), ("1,1", "2,4"))
        self.assertEqual(fields["perf"], "true")
        self.assertEqual(len(cli._split_games(out)), 1)


@unittest.skipUnless(REAL, "set DECKLAB_FORGE_TESTS=1 to play real Forge games")
class RefusalTests(unittest.TestCase):
    """Requests through one serve worker (DeckLabServe passes them to Request.parse and
    GameLoop.play): each refusal ends "error" and the worker plays on."""

    def test_v2_requests_it_refuses(self):
        setup = S["setup"]
        lease = slots.claim(1, setup["workers"], what="test_forge_v2loop serve")
        self.addCleanup(lease.release)
        proc = _start_worker(runner.serve_command(setup), setup["forge_dir"], S["env"])
        lines = queue.Queue()

        def read():
            for line in proc.stdout:
                lines.put(line.rstrip("\n"))
            lines.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()

        def stop_worker():
            processes.kill_process(proc)
            proc.wait(30)
            reader.join(30)
            for stream in (proc.stdin, proc.stdout):
                try:
                    stream.close()
                except OSError:
                    pass
            processes._end_process(proc)

        self.addCleanup(stop_worker)        # cleanups go last first: the worker, then its slot

        def until(what, timeout=TIMEOUT):
            got, deadline = [], time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=1)
                except queue.Empty:
                    continue
                self.assertIsNotNone(line, "the worker ended: " + "\n".join(got[-20:]))
                got.append(line)
                event = runner.serve_event(line)
                if event and event["what"] == what:
                    return event, got
            self.fail(f"no {what} line in {timeout} s")

        until("ready")
        args = runner.request_args(setup, "Constructed", A, B, 1, BASE, {"stream": S["stream"], "first": 3})

        def changed(**edits):
            edited = list(args)
            for flag, values in edits.items():
                at = edited.index("-" + flag)
                after = at + 1
                while after < len(edited) and not edited[after].startswith("-"):
                    after += 1
                edited[at:after] = [] if values is None else ["-" + flag, *values]
            return edited

        too_big = str(2 ** 31)              # one more than Integer.MAX_VALUE
        cases = {
            "stream": changed(dlgame=["0123456789ABCDEF", "0"]),
            "first": changed(dlgame=[S["stream"], "x"]),
            "seed": changed(s=None),
            "games": changed(n=["0"]),
            "games past an int": changed(n=[too_big]),
            "match": args + ["-m", "3"],
            "deck folder without its value": changed(D=[]),
            "two deck folders": changed(D=[str(S["folder"]), str(S["folder"])]),
            "decks": changed(d=[A]),
            "clock": changed(c=["soon"]),
            "clock past an int": changed(c=[too_big]),
            "format": changed(f=["Nonsense"]),
            "format in capitals": changed(f=["CONSTRUCTED"]),
            "two formats": changed(f=["Constructed", "Commander"]),
        }
        for n, (why, bad) in enumerate(cases.items()):
            proc.stdin.write(runner.request_line(f"bad{n}", bad))
            proc.stdin.flush()
            ended, got = until("end")
            self.assertEqual((ended["id"], ended["status"], ended["games"]), (f"bad{n}", "error", 0), why)
            # Request.parse's own line, not serve's report of an exception ("Error: java.lang...").
            self.assertTrue(any(line.startswith("Error: -dlgame") for line in got), why)
            self.assertFalse(any(line.startswith(logreader.ENGINE_PREFIX) for line in got), why)
        for n, (bad, detail) in enumerate(((changed(a=["Default", "Nobody"]), "Unknown AI profile - Nobody"),
                                           (changed(d=[A, "missing.dck"]), "Could not load deck - missing.dck"))):
            proc.stdin.write(runner.request_line(f"forge{n}", bad))
            proc.stdin.flush()
            ended, got = until("end")
            self.assertEqual((ended["status"], ended["games"], ended["detail"]), ("error", 0, detail))
        # -f in lower case is Forge's Constructed (GameLoop reads it as SimulateMatch does).
        proc.stdin.write(runner.request_line("good", changed(f=["constructed"])))
        proc.stdin.flush()
        ended, got = until("end")
        self.assertEqual((ended["id"], ended["status"], ended["games"]), ("good", "done", 1))
        output = "\n".join(got)
        self.assertEqual(engine(output)["first"], "3")
        header = next(match for match in map(logreader.RE_HEADER.match, got) if match)
        self.assertEqual((header[2], header[3]), ("Constructed", str(BASE)))
        proc.stdin.write("quit\n")
        proc.stdin.flush()
        self.assertEqual(until("bye")[0]["why"], "quit")


if __name__ == "__main__":
    unittest.main()
