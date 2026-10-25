"""Run one headless Forge simulation process and summarise it as JSON.

Usage
-----
    python run_sim.py DECK1.dck DECK2.dck [DECK3.dck ...] [options]

    Decks are .dck files (make them with to_dck.py). Paths may be absolute or relative to the
    current directory; they are passed to Forge as paths relative to -D <their common folder>,
    because Forge's -d always prepends a base folder (an absolute -d path fails to load).

Options
    -n, --games N        games to play in this process (default 10). Forge -n.
    -s, --seed S         RNG seed (Forge -s). The same seed, decks and Forge version replay the
                         same games exactly (tested 2026-09-29); omit for a random run.
    -f, --format F       Forge game type (default Constructed; e.g. Commander). Forge -f.
    -c, --timeout SEC    per-game clock in seconds; a game still running is stopped and counted
                         as a draw (default 120, Forge's own default). Forge -c.
    -q, --quiet          Forge -q: print only results, not the full game log. Without it the log
                         (about 250-400 lines per game) is saved and the summary also reports who
                         went first in each game.
    -a, --ai PROFILE..   AI profile per deck, in deck order ("-a Default Reckless" or repeated
                         -a; Default, Cautious, Reckless, Experimental). Default: "Default" for every deck, so results don't
                         depend on Forge's saved preferences.
    --log PATH           where to save Forge's merged stdout+stderr (default:
                         logs/sim-<timestamp>.log next to this script)
    --json PATH          also write the JSON summary to this file
    --java PATH          java.exe to use (default: the JDK 26 java.exe; see JAVA below)
    --xmx SIZE           JVM heap limit (default 1024m; "none" leaves -Xmx out)
    --forge-dir PATH     Forge install (default C:/Tools/forge); the process runs with this as
                         its working directory
    --process-timeout S  kill the whole process after S seconds (default: 60 + games x
                         (timeout + 5)); a killed run reports the games finished so far
    --user-dir PATH      Forge's user-data folder for this run (default: forge-user/ next to this
                         script). Set via APPDATA/LOCALAPPDATA for the child process only, so
                         Forge's preferences and its per-process log files stay out of the user's
                         own %APPDATA%/Forge; "default" uses the normal %APPDATA%/Forge.
    --lazy               load card scripts lazily (Forge preference LOAD_CARD_SCRIPTS_LAZILY,
                         written to <user-dir>/Forge/preferences/forge.preferences). Measured
                         2026-09-29: start-up 9.0 s -> 1.2 s, peak memory 1030 -> 763 MB, the same
                         50 games (seed 1) as eager loading. Off by default (Forge's default).
                         Runs sharing a --user-dir must agree on --lazy.
    --jvm FLAG           extra JVM flag, repeatable (e.g. --jvm=-XX:+DisableExplicitGC, measured
                         about 14% faster per game with identical results)
    --keep-forge-logs K  keep the newest K archived forge.<timestamp>.log files in the user dir
                         (default 20); older ones are deleted before the run
    --mem                also measure the java process (Windows only): "mem" (peak working set
                         and peak private bytes in MB, from GetProcessMemoryInfo on a handle kept
                         until exit) and "cpu_s" (user + kernel CPU seconds, GetProcessTimes).
                         Off by default. (Added 2026-09-29 for the formats trial, formats.md.)
    --card-log           run Deck Lab's card-log jar (decklab.DeckLabSim) instead of Forge's own sim:
                         the same games (checked 2026-09-29 with the same seed: identical log apart
                         from the extra lines), plus "Information: DL|..." lines in each game's log
                         giving every player's deck with card ids, every card movement (draws,
                         casts, land drops, scry, deaths...), the kept opening hands and the hands
                         at the end. Needs the full log (not with -q). The jar is the one Deck Lab
                         builds for Forge 2.0.15 from decklab/lib/forge/java/decklab/DeckLabSim.java
                         (any Deck Lab matchup run builds it); parse the log with parse_log.py.

Output: one JSON object on stdout, e.g.
    {"ok": true, "games_played": 10, "decks": [{"index": 1, "name": "Gruul Ramp (owned)",
     "wins": 6}, {"index": 2, "name": "Izzet Prowess (owned)", "wins": 4}], "draws": 0,
     "timeouts": 0, "errors": 0, "startup_s": 9.4, "games_wall_s": 8.1,
     "game_ms": {"mean": 812.0, "min": 358, "max": 1907}, "games": [{"game": 1, "winner": 1,
     "ms": 1121, "rounds": 7, "first": 2, "result": "win"}, ...],
     "unsupported_cards": [], "log": "...", ...}
    Exit code 0 when Forge played every requested game, 1 otherwise (see "error").

    "winner" and "first" are deck indexes (1-based, in the order given). "rounds" is Forge's
    "Game Outcome: Turn N", which is ceil(total turns / 2) whatever the player count, so it is
    rounds only for 2 players (a 4-player game of 36 turns prints "Turn 18").
    "first" and "turns" (total turns taken, from the last "Turn: Turn N (<player>)" line) are only
    known without --quiet.
    "loss_reason" lists each loser's reason ("life total reached 0", "trying to draw cards from
    empty library", "due to accumulation of 21 damage from generals", "conceded", ...);
    "win_reason" is added when the win was not "all opponents have lost" (an alternate win, e.g.
    "due to effect of 'Felidar Sovereign'"). Forge prints these PlayerOutcome strings from
    res/languages/en-US.properties; before 2026-09-29 this script only understood the
    "has won/lost because ..." forms, so decking and commander-damage losses had no loss_reason
    and alternate wins were misread as draws (formats.md, section 5).
    A "draw" is a real draw; a "timeout" is Forge's "Stopping slow match as draw"; an "error"
    is a game that threw (stack trace in the log), which Forge also reports as a draw.
    "unsupported_cards" lists names Forge couldn't find: Forge silently REMOVES those cards
    from the deck and plays on, so treat a non-empty list as a failed run.

Forge behaviour this relies on (forge-gui-desktop SimulateMatch.java, tag forge-2.0.15)
    - All games of one run are one Forge Match: game 1's starting player is random; after that
      the loser of the previous game goes first (after a draw, deck 1). The AI always chooses
      to play first. AI sideboarding between games is off in sim mode.
    - Player names are "Ai(<index>)-<deck Name=>", which this script maps back to deck indexes.
    - Forge exits with code 0 even when a deck fails to load; this script checks the output.

JAVA: Forge 2.0.15 runs on the installed JDK 26 (C:/Program Files/Java/jdk-26.0.1). Call that
java.exe directly rather than the "javapath" java.exe on PATH, which is a small launcher stub.
JVM flags are the ones forge.exe/forge.sh use: -Xmx, -Dio.netty.tryReflectionSetAccessible=true
and -Dfile.encoding=UTF-8 (the jar's manifest carries the --add-opens list).

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_FORGE_DIR = Path("C:/Tools/forge")
DEFAULT_JAVA = "C:/Program Files/Java/jdk-26.0.1/bin/java.exe"
DEFAULT_USER_DIR = HERE / "forge-user"
JAR_GLOB = "forge-gui-desktop-*-jar-with-dependencies.jar"
# Built by Deck Lab (decklab/lib/forge/simjar.py) from decklab/lib/forge/java/decklab/DeckLabSim.java,
# one jar per stamp (the source, Forge's jar and javac): decklab-sim-2.0.15-<the first 12 hex digits of
# the SHA-256 of its stamp>.jar. The newest is used: Deck Lab touches the jar each run starts with, so
# that's the one a Deck Lab run used most recently.
CARD_LOG_DIR = HERE.parent / "data" / "forge" / "cardlog"
CARD_LOG_JARS = "decklab-sim-2.0.15-*.jar"
CARD_LOG_MAIN = "decklab.DeckLabSim"

# e.g. "Ai(1)-Gruul Ramp (owned) vs Ai(2)-Izzet Prowess (owned) - fifty  games of Constructed seed 1"
# (Forge spells the count out in words, sometimes with a double space)
RE_HEADER = re.compile(r"^(Ai\(1\)-.*) - .+? games? of (\w+)(?: seed (-?\d+))?\s*$")
RE_RESULT_WIN = re.compile(r"^Game Result: Game (\d+) ended in (\d+) ms\. Ai\((\d+)\)-.* has won!\s*$")
RE_RESULT_DRAW = re.compile(r"^Game Result: Game (\d+) ended in a Draw! Took (\d+) ms\.\s*$")
RE_ROUNDS = re.compile(r"^Game Outcome: Turn (\d+)\s*$")
# Forge's PlayerOutcome strings (res/languages/en-US.properties, "#PlayerOutcome.java" block):
#   has won because all opponents have lost        has won due to effect of '<card>'
#   has lost because life total reached 0          has lost trying to draw cards from empty library
#   has lost because of obtaining 10 poison counters
#   has lost because an opponent has won by spell '<card>'   has lost due to effect of spell '<card>'
#   has lost due to accumulation of 21 damage from generals  has conceded
#   has accepted that the game is a draw (ignored)  has lost for unknown reason (this is a bug)
# The player name is matched lazily so the first " has won/lost/conceded" is the verb (a loss
# reason can itself contain "has won by spell").
RE_OUTCOME = re.compile(r"^Game Outcome: Ai\((\d+)\)-.*? has (won|lost|conceded)\b(?: because)? ?(.*?)\.?\s*$")
RE_FIRST = re.compile(r"^Turn: Turn 1 \(Ai\((\d+)\)-")
RE_TURN = re.compile(r"^Turn: Turn (\d+) \(Ai\((\d+)\)-")
RE_UNSUPPORTED = re.compile(r'^An unsupported card was requested: "(.*)" from "(.*)"\.')
RE_NOLOAD = re.compile(r"^(Could not load deck - .*|No deck found in .*|Unknown AI profile - .*)$")
RE_EXC = re.compile(r"^(?:Exception in thread .*|[\w.$]+(?:Exception|Error)(?::.*)?)\s*$")


class ProcStats:
    """--mem: peak memory and CPU time of one process (Win32; same method as measure_run.py).

    Opens a query handle right after the process starts and keeps it until after exit, so the
    final PeakWorkingSetSize / PeakPagefileUsage (private bytes) / GetProcessTimes are read from
    the finished process. A 0.5 s sampler also keeps the largest working set seen, as a fallback.
    """

    def __init__(self, pid: int):
        import ctypes
        import ctypes.wintypes as wt

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        self._ct, self._wt, self._PMC = ctypes, wt, PMC
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self._k32.OpenProcess.restype = wt.HANDLE
        self._k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        self._psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
        self._k32.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
        self._h = self._k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        self._max_ws = 0
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._sample, daemon=True)
        self._th.start()

    def _mem(self):
        pmc = self._PMC()
        pmc.cb = self._ct.sizeof(self._PMC)
        if not self._h or not self._psapi.GetProcessMemoryInfo(self._h, self._ct.byref(pmc), pmc.cb):
            return None
        return pmc

    def _sample(self):
        while not self._stop.is_set():
            m = self._mem()
            if m:
                self._max_ws = max(self._max_ws, m.WorkingSetSize)
            self._stop.wait(0.5)

    def finish(self) -> dict:
        self._stop.set()
        self._th.join()
        m = self._mem()
        c, e, k, u = (self._wt.FILETIME() for _ in range(4))
        cpu = None
        if self._h and self._k32.GetProcessTimes(self._h, *(self._ct.byref(x) for x in (c, e, k, u))):
            f = lambda ft: ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7
            cpu = round(f(k) + f(u), 2)
        mb = lambda b: round(b / 2**20, 1)
        return {"mem": {"peak_working_set_mb": mb(m.PeakWorkingSetSize) if m else mb(self._max_ws),
                        "peak_private_mb": mb(m.PeakPagefileUsage) if m else None,
                        "sampled_max_working_set_mb": mb(self._max_ws)},
                "cpu_s": cpu}


def prepare_user_dir(user_dir: str, lazy: bool, keep_logs: int) -> dict | None:
    """Environment for the Forge process.

    On Windows Forge keeps preferences, logs and its card cache under %APPDATA%/Forge and
    %LOCALAPPDATA%/Forge/Cache (ForgeProfileProperties.getDefaultDirs), read from the environment,
    so pointing both variables at our own folder isolates Forge from the user's normal profile:
    its forge.preferences is ours to write (lazy card loading) and its per-process log files
    (forge.log, archived as forge.<timestamp>.log on the next start and never pruned in sim mode)
    stay in a folder we can prune. user_dir "default" leaves the environment alone.
    """
    if user_dir == "default":
        if lazy:
            raise SystemExit("error: --lazy needs our own --user-dir (it writes forge.preferences)")
        return None
    root = Path(user_dir).resolve()
    fdir = root / "Forge"
    (fdir / "preferences").mkdir(parents=True, exist_ok=True)
    prefs = fdir / "preferences" / "forge.preferences"
    want = f"LOAD_CARD_SCRIPTS_LAZILY={'true' if lazy else 'false'}\n"
    try:
        have = prefs.read_text(encoding="utf-8")
    except FileNotFoundError:
        have = None
    if have != want:
        prefs.write_text(want, encoding="utf-8", newline="\n")
    archives = sorted(fdir.glob("forge.*.log"), key=lambda f: f.stat().st_mtime)
    for f in archives[: max(0, len(archives) - keep_logs)]:
        try:
            f.unlink()
        except OSError:
            pass
    env = dict(os.environ)
    env["APPDATA"] = str(root)
    env["LOCALAPPDATA"] = str(root)
    return env


def manifest_add_opens(jar_path: Path) -> list[str]:
    """--add-opens flags for the Forge jar's manifest "Add-Opens" list.

    Java applies that attribute only to the jar started with -jar; --card-log starts Forge with
    -cp (to add DeckLabSim), so the same list is passed on the command line instead.
    """
    import zipfile
    with zipfile.ZipFile(jar_path) as z:
        text = z.read("META-INF/MANIFEST.MF").decode("utf-8")
    text = text.replace("\r\n", "\n").replace("\n ", "")  # manifest continuation lines
    for line in text.split("\n"):
        if line.startswith("Add-Opens:"):
            return [f for m in line[len("Add-Opens:"):].split() for f in ("--add-opens", f"{m}=ALL-UNNAMED")]
    return []


def find_jar(forge_dir: Path) -> str:
    jars = sorted(forge_dir.glob(JAR_GLOB))
    if not jars:
        raise SystemExit(f"error: no {JAR_GLOB} in {forge_dir}")
    return jars[-1].name


def deck_args(paths: list[Path]) -> tuple[str, list[str], str | None]:
    """(-D dir, -d names relative to it, temp dir to delete or None)."""
    paths = [p.resolve() for p in paths]
    for p in paths:
        if not p.is_file():
            raise SystemExit(f"error: deck file not found: {p}")
        if len(p.suffix) != 4:
            raise SystemExit(f"error: Forge only treats a -d argument as a file when it ends in a "
                             f"3-letter extension like .dck: {p}")
    try:
        base = Path(os.path.commonpath([str(p.parent) for p in paths]))
        return str(base), [p.relative_to(base).as_posix() for p in paths], None
    except ValueError:  # different drives: copy into one folder
        tmp = tempfile.mkdtemp(prefix="forge-decks-")
        names = []
        for i, p in enumerate(paths, 1):
            n = f"{i}-{p.name}"
            shutil.copy(p, Path(tmp) / n)
            names.append(n)
        return tmp, names, tmp


def _new_game() -> dict:
    return {"rounds": None, "first": None, "turns": None, "won": {}, "lost": {}, "timeout": False,
            "exception": False}


def parse(lines: list[str], n_decks: int) -> dict:
    """Parse Forge sim output (stdout+stderr merged) into games.

    Forge 2.0.15 does NOT report a stopped game as a draw: when the -c clock runs out (or the game
    throws), SimulateMatch calls setGameOver(Draw), every player who hasn't lost is given a "win",
    and "Game Result" names whichever of them a HashMap yields first. So a game's winner is only
    trusted when exactly one player "has won" and nobody timed out; otherwise the game is a
    timeout ("Stopping slow match as draw" seen), an error (stack trace seen) or a draw.
    """
    s = {"header": None, "players": None, "format": None, "seed": None, "games": [], "unsupported": set(),
         "load_errors": [], "exceptions": 0}
    cur = _new_game()
    for line in lines:
        line = line.rstrip("\r\n")
        m = RE_HEADER.match(line)
        if m and s["header"] is None:
            s["header"], s["players"], s["format"], s["seed"] = line, m[1], m[2], m[3]
            continue
        m = RE_UNSUPPORTED.match(line)
        if m:
            s["unsupported"].add(m[1])
            continue
        m = RE_NOLOAD.match(line)
        if m:
            s["load_errors"].append(line)
            continue
        if line.startswith("Stopping slow match as draw"):
            cur["timeout"] = True
            continue
        if s["header"] is not None and RE_EXC.match(line):
            cur["exception"] = True
            s["exceptions"] += 1
            continue
        m = RE_TURN.match(line)
        if m:
            cur["turns"] = int(m[1])
            if m[1] == "1" and cur["first"] is None:
                cur["first"] = int(m[2])
            continue
        m = RE_ROUNDS.match(line)
        if m:
            cur["rounds"] = int(m[1])
            continue
        m = RE_OUTCOME.match(line)
        if m:
            verb, reason = m[2], m[3]
            if verb == "conceded":
                verb, reason = "lost", "conceded"
            cur["won" if verb == "won" else "lost"][int(m[1])] = reason
            continue
        m = RE_RESULT_WIN.match(line) or RE_RESULT_DRAW.match(line)
        if m:
            reported = int(m[3]) if m.re is RE_RESULT_WIN else None
            if cur["timeout"]:
                result, winner = "timeout", None
            elif reported is not None and len(cur["won"]) == 1 and reported in cur["won"]:
                result, winner = "win", reported
            elif cur["exception"]:
                result, winner = "error", None
            else:
                result, winner = "draw", None
            g = {"game": int(m[1]), "result": result, "winner": winner, "ms": int(m[2]),
                 "rounds": cur["rounds"], "first": cur["first"], "turns": cur["turns"]}
            if reported is not None and winner is None:
                g["forge_reported_winner"] = reported
            if winner is not None and cur["won"][winner] != "all opponents have lost":
                g["win_reason"] = cur["won"][winner]
            if cur["lost"]:
                g["loss_reason"] = "; ".join(f"Ai({k}): {v}" for k, v in sorted(cur["lost"].items()))
            s["games"].append(g)
            cur = _new_game()
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run one headless Forge sim process; print a JSON summary.")
    ap.add_argument("decks", nargs="+", type=Path)
    ap.add_argument("-n", "--games", type=int, default=10)
    ap.add_argument("-s", "--seed", type=int)
    ap.add_argument("-f", "--format", default="Constructed")
    ap.add_argument("-c", "--timeout", type=int, default=120)
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("-a", "--ai", action="extend", nargs="+")
    ap.add_argument("--log", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--java", default=DEFAULT_JAVA)
    ap.add_argument("--xmx", default="1024m")
    ap.add_argument("--forge-dir", type=Path, default=DEFAULT_FORGE_DIR)
    ap.add_argument("--process-timeout", type=float)
    ap.add_argument("--user-dir", default=str(DEFAULT_USER_DIR))
    ap.add_argument("--lazy", action="store_true")
    ap.add_argument("--jvm", action="append", default=[])
    ap.add_argument("--keep-forge-logs", type=int, default=20)
    ap.add_argument("--card-log", action="store_true")
    ap.add_argument("--mem", action="store_true")
    a = ap.parse_args(argv)
    if a.mem and os.name != "nt":
        raise SystemExit("error: --mem is Windows-only")

    if len(a.decks) < 2:
        raise SystemExit("error: give at least two decks")
    ai = a.ai or ["Default"] * len(a.decks)
    if len(ai) != len(a.decks):
        raise SystemExit("error: give one --ai per deck (or none)")
    ddir, dnames, tmpdir = deck_args(a.decks)
    jar = find_jar(a.forge_dir)
    jvm = ([f"-Xmx{a.xmx}"] if a.xmx.lower() != "none" else []) + [
        "-Dio.netty.tryReflectionSetAccessible=true", "-Dfile.encoding=UTF-8"] + a.jvm
    env = prepare_user_dir(a.user_dir, a.lazy, a.keep_forge_logs)
    if a.card_log:
        if a.quiet:
            raise SystemExit("error: --card-log writes into the full game log; drop -q")
        card_log_jars = sorted(CARD_LOG_DIR.glob(CARD_LOG_JARS), key=lambda p: p.stat().st_mtime)
        if not card_log_jars:
            raise SystemExit(f"error: no {CARD_LOG_JARS} in {CARD_LOG_DIR}; any Deck Lab matchup run builds it "
                             f"(python -m decklab.lib.forge play ...)")
        launch = [*manifest_add_opens(a.forge_dir / jar), "-cp",
                  os.pathsep.join([jar, str(card_log_jars[-1])]), CARD_LOG_MAIN]
    else:
        launch = ["-jar", jar]
    cmd = [a.java, *jvm, *launch, "sim", "-D", ddir, "-d", *dnames, "-n", str(a.games),
           "-f", a.format, "-c", str(a.timeout), "-a", *ai]
    if a.seed is not None:
        cmd += ["-s", str(a.seed)]
    if a.quiet:
        cmd.append("-q")
    log_path = a.log or HERE / "logs" / f"sim-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ptimeout = a.process_timeout or 60 + a.games * (a.timeout + 5)

    t0 = time.perf_counter()
    lines: list[str] = []
    t_header = None
    killed = False
    with open(log_path, "w", encoding="utf-8", newline="\n") as log:
        p = subprocess.Popen(cmd, cwd=a.forge_dir, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                             encoding="utf-8", errors="replace", bufsize=1)
        pstats = ProcStats(p.pid) if a.mem else None

        def _kill():
            nonlocal killed
            killed = True
            p.kill()

        timer = threading.Timer(ptimeout, _kill)
        timer.daemon = True
        timer.start()
        for line in p.stdout:
            log.write(line)
            lines.append(line)
            if t_header is None and RE_HEADER.match(line.rstrip("\r\n")):
                t_header = time.perf_counter() - t0
        p.wait()
        timer.cancel()
    wall = time.perf_counter() - t0
    proc_stats = pstats.finish() if pstats else None
    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)

    s = parse(lines, len(a.decks))
    names = {}
    if s["players"]:
        for m in re.finditer(r"Ai\((\d+)\)-(.*?)(?: \[[^\]]*\])?(?= vs Ai\(\d+\)-|$)", s["players"]):
            names[int(m[1])] = m[2]
    games = s["games"]
    ms = [g["ms"] for g in games]
    decks = [{"index": i, "name": names.get(i), "path": str(p), "ai": ai[i - 1],
              "wins": sum(1 for g in games if g["winner"] == i),
              "went_first": sum(1 for g in games if g["first"] == i) if not a.quiet else None}
             for i, p in enumerate(a.decks, 1)]
    error = None
    if s["load_errors"]:
        error = "; ".join(s["load_errors"])
    elif killed:
        error = f"process killed after {ptimeout:.0f} s"
    elif p.returncode != 0:
        error = f"java exited with code {p.returncode}"
    elif len(games) < a.games:
        error = f"only {len(games)} of {a.games} games reported"
    if s["unsupported"] and not error:
        error = "unsupported cards were removed from a deck: " + ", ".join(sorted(s["unsupported"]))
    summary = {
        "ok": error is None,
        "error": error,
        "games_requested": a.games,
        "games_played": len(games),
        "decks": decks,
        "draws": sum(1 for g in games if g["result"] == "draw"),
        "timeouts": sum(1 for g in games if g["result"] == "timeout"),
        "errors": sum(1 for g in games if g["result"] == "error"),
        "format": s["format"] or a.format,
        "seed": a.seed,
        "startup_s": round(t_header, 2) if t_header is not None else None,
        "games_wall_s": round(wall - t_header, 2) if t_header is not None else None,
        "wall_s": round(wall, 2),
        "game_ms": {"mean": round(sum(ms) / len(ms), 1), "min": min(ms), "max": max(ms)} if ms else None,
        "games_per_min": round(len(games) / (wall - t_header) * 60, 1) if games and t_header else None,
        "unsupported_cards": sorted(s["unsupported"]),
        "exception_lines": s["exceptions"],
        "exit_code": p.returncode,
        "log": str(log_path),
        "cmd": cmd,
        "cwd": str(a.forge_dir),
        "user_dir": a.user_dir,
        "lazy_card_loading": a.lazy,
        "card_log": a.card_log,
        "games": games,
    }
    if proc_stats:
        summary.update(proc_stats)
    text = json.dumps(summary, indent=1)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(text, encoding="utf-8")
    print(text)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
