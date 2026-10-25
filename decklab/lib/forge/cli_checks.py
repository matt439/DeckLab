"""Forge CLI engine qualification: card-log parity and warm-worker checks."""
from . import cli_shared as shared
from . import decisionlog


# ============================================================ cardlog-check

CHECK_SEED = 1                  # the check's seed base (v2: game g's seed is seeds.game_seed(CHECK_SEED, stream, g))
CHECK_GAMES = 12                # Constructed games (--games), each played four ways (_cardlog_check)
CHECK_COMMANDER_GAMES = 3       # Commander games (--commander-games): they take longer
CHECK_MAX_GAMES = shared.seeds.SEAT_BLOCK  # at most one seat block, so each DeckLabSim run is one request in one process
CHECK_PROCESSES = 4             # the check's Forge processes at once (each in a slot of the PC's budget too)
CHECK_REASONS = 5               # reasons shown when card logs failed their checks
# Two fixed 60-card lists whose games move cards through most zones: draws and discards
# (Faithless Looting, Divination, Duress, Mind Rot), library searches (Rampant Growth),
# tokens (Dragon Fodder), exile (Scorching Dragonfire), casts from the graveyard
# (flashback), returns to the hand (Regrowth, Gravedigger, Unsummon) and counters.
CHECK_DECKS = {
    "cardlog-check-a": ["4 Llanowar Elves", "4 Grizzly Bears", "4 Kird Ape", "4 Dragon Fodder", "4 Scorching Dragonfire",
                        "4 Lightning Bolt", "4 Faithless Looting", "4 Rampant Growth", "2 Overrun", "2 Regrowth",
                        "12 Forest", "12 Mountain"],
    "cardlog-check-b": ["4 Duress", "4 Unsummon", "4 Divination", "4 Gravedigger", "4 Walking Corpse", "4 Murder",
                        "4 Counterspell", "4 Mind Rot", "4 Phantom Warrior", "12 Island", "12 Swamp"],
}
# Two fixed 100-card Commander lists, one copy of each card but the basics, with a
# commander each: casts from the command zone (and back to it when a commander dies),
# tokens (Krenko, Mob Boss, Raise the Alarm, Hordeling Outburst), exile (Swords to
# Plowshares, Journey to Nowhere, Scorching Dragonfire), cards exiled and returned
# (Flickerwisp, Restoration Angel), library searches (Idyllic Tutor, Path to Exile) and
# casts from the graveyard (Firebolt).
CHECK_COMMANDER_DECKS = {
    "cardlog-check-krenko": (["1 Krenko, Mob Boss"], [
        "1 Goblin Guide", "1 Monastery Swiftspear", "1 Jackal Pup", "1 Raging Goblin", "1 Mogg Fanatic",
        "1 Goblin Piledriver", "1 Goblin Chieftain", "1 Goblin King", "1 Goblin Instigator", "1 Beetleback Chief",
        "1 Goblin Rabblemaster", "1 Siege-Gang Commander", "1 Hill Giant", "1 Gray Ogre", "1 Fire Elemental",
        "1 Shivan Dragon", "1 Lightning Bolt", "1 Shock", "1 Searing Spear", "1 Lightning Strike", "1 Incinerate",
        "1 Chain Lightning", "1 Volcanic Hammer", "1 Flame Slash", "1 Scorching Dragonfire", "1 Magma Spray",
        "1 Dragon Fodder", "1 Krenko's Command", "1 Hordeling Outburst", "1 Cathartic Reunion", "1 Firebolt",
        "1 Tormenting Voice", "1 Lava Axe", "1 Act of Treason", "1 Rummaging Goblin", "64 Mountain"]),
    "cardlog-check-isamaru": (["1 Isamaru, Hound of Konda"], [
        "1 Savannah Lions", "1 Elite Vanguard", "1 Soldier of the Pantheon", "1 Thalia's Lieutenant",
        "1 Glorious Anthem", "1 Raise the Alarm", "1 Spectral Procession", "1 Captain of the Watch",
        "1 Cloudgoat Ranger", "1 Attended Knight", "1 Swords to Plowshares", "1 Path to Exile",
        "1 Journey to Nowhere", "1 Oblivion Ring", "1 Banishing Light", "1 Serra Angel", "1 Baneslayer Angel",
        "1 White Knight", "1 Benalish Marshal", "1 Honor of the Pure", "1 Disenchant", "1 Pacifism",
        "1 Idyllic Tutor", "1 Knight of the White Orchid", "1 Gods Willing", "1 Valorous Stance",
        "1 Midnight Haunting", "1 Gideon's Lawkeeper", "1 Thraben Inspector", "1 Restoration Angel",
        "1 Flickerwisp", "1 Fiend Hunter", "1 Kor Skyfisher", "1 Seal Away", "1 Faith's Fetters", "64 Plains"]),
}
# The timings in Forge's lines: "ended in 812 ms.", "Took 9 ms.", "Match Duration 0m : 07s".
RE_TIMING = shared.re.compile(r"(?<=ended in )\d+(?= ms)|(?<=Took )\d+(?= ms)|(?<=Match Duration )\d+m : \d+s")
# A game's place in its batch or request ("Game Result: Game 3 ended..."): the v2 engine's game g
# is game 1 of a plain "-n 1" process and game g - first + 1 of a request, so it's masked too.
RE_ORDINAL = shared.re.compile(r"^(Game Result: Game )\d+")
# A Java stack trace's frames (a tab, then "at forge.ai.AiController.chooseSpellAbility...(AiController.java:1699)"
# or "... 12 more"), which name the thread type and the line numbers of Deck Lab's copies of Forge's
# classes (a virtual eval thread, R14a) and so differ from plain Forge's for the same exception.
# The exception's own line is kept.
RE_FRAME = shared.re.compile(r"^\t(?:at |\.\.\. \d+ more)")
# Java's own notices ("WARNING: A terminally deprecated method in sun.misc.Unsafe..."), printed once
# a JVM, inside the first game that sets one off: a DeckLabSim process playing many games prints it
# once, each plain Forge process playing one game its own, so they're left out of the comparison.
JVM_WARNING = "WARNING:"
# Forge's lines that say a game hit one of its time limits, which a busy computer can make
# happen in one copy of a game and not the other.
TIME_LIMITS = (shared.SLOW_STOP, shared.AI_TIMEOUT)
# The attackers Forge's AI declared, which plain Forge itself lists in another order from one
# run to the next, in the same game (seen on 2026-10-01 with Krenko's Goblin tokens): "Combat:
# Ai(1)-a assigned Goblin Token (311), Krenko, Mob Boss (100) and Goblin Token (329) to attack
# Ai(2)-b." They're compared in name order. Each attacker ends with its card id.
RE_ATTACKERS = shared.re.compile(r"^(Combat: .+? assigned )(.+)( to attack .+)$")
RE_ATTACKER = shared.re.compile(r"(?:^|, | and )(.+?\(\d+\))")
# The formats whose games are compared line for line. Plain Forge doesn't repeat a game of
# the Commander lists line for line: on 2026-10-01 two plain runs of seed 1 differed in
# which of two Goblin tokens Isamaru blocked, and two card-log runs in whether Serra Angel
# blocked Krenko, while all four runs' games had the same winners, starters and lengths.
# So Commander games are compared by those (_compare_outcomes), and as a block made another
# way can also change who wins, a difference there can't be put down to the card log: the
# check can't tell. Their card logs' checks and DL|commander lines are what fail it.
LINE_FOR_LINE = ("Constructed",)
# The check's two comparisons ("legs" of _leg_problem), each (what failed, in a sentence with {fmt} and
# {version}; the first copy's name; the second's): Deck Lab's v2 engine with its game patches off against
# plain Forge playing each game alone from its own seed, and the card log off against on.
PARITY = ("Deck Lab's engine (its game patches off) didn't play the same {fmt} games as plain Forge {version}",
          "plain Forge", "Deck Lab's engine")
CARD_LOG_LEG = ("The card log changed the {fmt} games it was kept in (Forge {version})",
                "without the card log", "with it")


def _check_legs(games, commander_games):
    """The check's formats: [(Forge's format, {.dck name: ([Commander lines], [Main lines])}, games)]."""
    constructed = {name: ([], cards) for name, cards in CHECK_DECKS.items()}
    return [("Constructed", constructed, games), ("Commander", CHECK_COMMANDER_DECKS, commander_games)]


def _check_sides(decks_, fmt):
    """A format's two check decks as a result's sides are: (their .dck names, the one with the
    smaller card_sha first, and their seed stream, seeds.stream_of)."""
    kind = "commander" if fmt == "Commander" else "constructed"
    shas = {}
    for name, (commander, cards) in decks_.items():
        listed = {section: [[int(line.split(" ", 1)[0]), line.split(" ", 1)[1]] for line in lines]
                  for section, lines in (("Commander", commander), ("Main", cards))}
        shas[name] = shared.lists._list_text(listed, kind)[1]
    names = sorted(decks_, key=lambda name: shas[name])
    return names, shared.seeds.stream_of(shas[names[0]], shas[names[1]])


def _seated(names, game):
    """The two .dck names in game g's seat order (seeds.deck1_side: side 0 is deck 1 in even blocks)."""
    return names if shared.seeds.deck1_side(game) == 0 else names[::-1]


def _split_games(output):
    """Forge's output from its header line on, split into games ([lines] per game, each
    ending with its "Game Result" line: Forge prints a game's log just before it). output may
    be several processes' outputs, one after the other (a str, or a list of them): each
    header line starts again, so what a process prints before its header is left out."""
    if not isinstance(output, str):
        output = "\n".join(output)
    games, cur, started = [], [], False
    for line in output.splitlines():
        if shared.RE_HEADER.match(line):
            started, cur = True, []
            continue
        if not started:
            continue
        cur.append(line)
        if line.startswith("Game Result:"):
            games.append(cur)
            cur = []
    return games


def _attackers_in_order(line):
    """A "Combat: ... assigned ... to attack ..." line with its attackers in name order (any
    other line as it is)."""
    m = RE_ATTACKERS.match(line)
    return m[1] + ", ".join(sorted(RE_ATTACKER.findall(m[2]))) + m[3] if m else line


def _games_text(output, keep_card_log=False):
    """_split_games without the card log's lines, Java's stack-trace frames (RE_FRAME) and
    notices (JVM_WARNING), blank lines, the timings and the games' places in their batch or
    request (RE_ORDINAL), and with the attackers in name order: what must be the same in two
    copies of the same games (contract section 4's masks). Blank lines are left out because
    Forge prints one after a game's "Game Result" line when it has a winner, which in a
    process playing many games starts the next game's lines, and in one playing a single game
    (plain Forge's game g, in the v2 check) is never there. keep_card_log keeps the card log's
    DL| lines (engine-check compares two card-log runs). The decision log's DLAI| lines
    (decisionlog.PREFIX) are always left out: they say what the AI weighed, not what it played."""
    drop = (JVM_WARNING, decisionlog.PREFIX) if keep_card_log else (shared.cardlog.PREFIX, JVM_WARNING,
                                                                    decisionlog.PREFIX)
    return [[RE_ORDINAL.sub(r"\g<1>?", RE_TIMING.sub("?", _attackers_in_order(line))) for line in game
             if line.strip() and not line.startswith(drop) and not RE_FRAME.match(line)]
            for game in _split_games(output)]


def _compare(plain, logged, names=PARITY[1:]):
    """None when the two outputs (each a str or a list, as _split_games takes) played the
    same games, else (the number of the first game that differs, where it differs in words,
    the copies named by names)."""
    first, second = names
    a, b = _games_text(plain), _games_text(logged)
    for n, (ga, gb) in enumerate(zip(a, b), 1):
        if ga != gb:
            for i, (la, lb) in enumerate(zip(ga, gb)):
                if la != lb:
                    return n, f"game {n}, line {i + 1}: {first} printed {la!r}, {second} {lb!r}"
            return n, f"game {n}: {first} printed {len(ga)} lines, {second} {len(gb)}"
    if len(a) != len(b):
        return min(len(a), len(b)) + 1, f"{first} played {len(a)} games, {second} {len(b)}"
    return None


def _first_difference(plain, logged, names=PARITY[1:]):
    """None when the two outputs played the same games, else where they first differ, in words."""
    found = _compare(plain, logged, names)
    return found and found[1]


def _outcomes(output):
    """Each game's (result, winner's seat - 1, starter's seat - 1, turns), from Forge's output
    (a str, or a list of processes' outputs in turn)."""
    outputs = [output] if isinstance(output, str) else output
    found = []
    for out in outputs:
        reader = shared.LogReader(0)
        for line in out.splitlines():
            reader.feed(line)
        found += [(g["r"], g["w"], g["first"], g["turns"]) for g in reader.games]
    return found


def _outcome(found):
    """A game's outcome (from _outcomes) in words: "a win for Ai(2) on turn 19 (Ai(1) first)"."""
    result, winner, first, turns = found
    what = f"a win for Ai({winner + 1})" if winner is not None else f"a {result}"
    return f"{what} on turn {turns}" + (f" (Ai({first + 1}) first)" if first is not None else "")


def _compare_outcomes(plain, logged, names=PARITY[1:]):
    """_compare by each game's winner, starter and length only (LINE_FOR_LINE)."""
    first, second = names
    a, b = _outcomes(plain), _outcomes(logged)
    for n, (oa, ob) in enumerate(zip(a, b), 1):
        if oa != ob:
            return n, f"game {n} was {_outcome(oa)} {_with(first)}, {_outcome(ob)} {_with(second)}"
    if len(a) != len(b):
        return min(len(a), len(b)) + 1, f"{first} played {len(a)} games, {second} {len(b)}"
    return None


def _with(name):
    """A copy's name after an outcome: "with plain Forge", "without the card log", "with it"."""
    return name if name.startswith(("with ", "without ")) else f"with {name}"


def _time_limit_hit(output, n):
    """The first game, from 1 to n, that hit one of Forge's time limits in the process that
    played game n, or None: a game stopped by the clock, or whose AI evaluation timed out,
    can leave a thread running that draws from the next game's random numbers, so in v2,
    where each game of a DeckLabSim process is reseeded, every later game of the same
    process is unsure too (contract section 18). output is one process's (a str) or several
    in turn (a list: plain Forge's, one game each, where only game n itself counts)."""
    outputs = [output] if isinstance(output, str) else list(output)
    first = 1
    for i, out in enumerate(outputs):
        games = _split_games(out)
        last = first + len(games) - 1
        if n <= last or i == len(outputs) - 1:
            for m in range(first, min(n, last) + 1):
                if any(line.startswith(TIME_LIMITS) for line in games[m - first]):
                    return m
            return None
        first = last + 1
    return None


def _time_limit_game(plain, logged, n):
    """The first game that hit one of Forge's time limits in either copy, in game n's process
    up to game n (_time_limit_hit); None when none did."""
    return min((hit for hit in (_time_limit_hit(plain, n), _time_limit_hit(logged, n)) if hit is not None),
               default=None)


def _names_both_commanders(game):
    """Does a game's output have the card log's DL|commander line for both seats?"""
    start = shared.cardlog.PREFIX + "commander|"
    return {line[len(start):].split("|", 1)[0] for line in game if line.startswith(start)} >= {"1", "2"}


def _card_log_problems(fmt, games, logged, reader):
    """What went wrong with the card log itself in one process's games, whatever the games
    played: [lines to print], empty when nothing did. Every game must have its DL|log line
    and, in Commander, both seats' DL|commander lines, and no game's card log may fail its
    checks."""
    played = _split_games(logged)[:games]
    lines = []
    logs = sum(1 for game in played if any(line.startswith(shared.cardlog.PREFIX + "log|") for line in game))
    if logs != games:
        lines.append(f"The card log wrote its lines in {logs} of the {games} {fmt} games.")
    if fmt == "Commander":
        missing = sum(1 for game in played if not _names_both_commanders(game))
        if missing:
            lines.append(f"The card log didn't name both commanders in {missing} of the {games} Commander games.")
    bad = (reader.cards or {}).get("bad")
    if bad:
        lines += ([f"The card log of {bad} of the {games} {fmt} games failed its checks:"]
                  + [f"  game {n}: {why}" for n, why in reader.card_problems[:CHECK_REASONS]])
    return lines


def _leg_problem(version, fmt, games, plain, logged, reader, leg=PARITY):
    """What one comparison of the check (leg: PARITY or CARD_LOG_LEG, which names it and its
    two copies) found wrong, or None. plain is the first copy's output (a str, or a list of
    processes' outputs in turn), logged the second's, one process played with the card log
    (reader its LogReader). ("failed", [lines to print]) when the card log itself went wrong
    (_card_log_problems), whatever else happened, or the games differ for no other reason;
    ("unsure", [lines]) when the only problem is games that differ in a way that says nothing
    about the engine: from a game that hit one of Forge's time limits, that game or an earlier
    one of the same process (_time_limit_game), or in a Commander game's outcome, which plain
    Forge's own games can differ in."""
    what, first, second = leg
    problems = _card_log_problems(fmt, games, logged, reader)
    by_line = fmt in LINE_FOR_LINE
    found = (_compare if by_line else _compare_outcomes)(plain, logged, (first, second))
    if found is None:
        return ("failed", problems) if problems else None
    n, where = found
    lines = [f"{what.format(fmt=fmt, version=version)}: {where}."] + problems
    if problems:
        return "failed", lines
    hit = _time_limit_game(plain, logged, n)
    limits = f"one of Forge's time limits (\"{shared.SLOW_STOP}\" or \"{shared.AI_TIMEOUT}\")"
    if hit == n:
        why = f"That game hit {limits}, which a busy computer can cause in one copy of a game and not the other"
    elif hit is not None:
        why = (f"Game {hit} hit {limits}, which a busy computer can cause in one copy of a game and not the other, "
               "and which can change the games after it in the same process")
    elif not by_line:
        why = (f"Plain Forge itself doesn't play a {fmt} game the same way every time (two runs of one seed can "
               "block differently, which can change how a game ends)")
    else:
        return "failed", lines
    return "unsure", lines + [f"{why}, so the check can't tell whether the card log plays the same games. "
                              + ("Run it again when the computer is less busy." if hit else "Run it again.")]


_said = set()                   # what the check has said about slots (each once is enough)
_said_lock = shared.threading.Lock()


def _say_once(what, text):
    with _said_lock:
        if what in _said:
            return
        _said.add(what)
    print(text, file=shared.sys.stderr)


def _check_slot(setup):
    """A slot of the PC's budget of Forge processes (slots.py) for one of the check's
    processes, waiting for one while every slot is another run's (said once); an empty
    Lease when the slots can't be used (said once too), so the check goes on without them."""
    try:
        return shared.slots.claim(1, setup["workers"], waiting=lambda: _say_once("waiting", shared.slots.WAITING),
                           what="cardlog-check")
    except OSError as e:
        _say_once("unusable", f"Forge's slots in {shared.slots.folder()} can't be used ({shared._os_reason(e)}), so the check "
                              "doesn't wait for other Forge runs.")
        return shared.slots.Lease()


class _CheckProcesses:
    """The check's Forge processes going now, so Ctrl+C ends them at once (stop()), and no
    other starts after it: _check_run asks stopped before it starts one, and a process it
    started as stop() came (add()) is killed straight away."""

    def __init__(self):
        self._lock, self._going, self.stopped = shared.threading.Lock(), set(), False

    def add(self, proc):
        with self._lock:
            if not self.stopped:
                self._going.add(proc)
                return
        shared.processes.kill_process(proc)

    def discard(self, proc):
        with self._lock:
            self._going.discard(proc)

    def stop(self):
        """Kill every process going, and start no more. Killed under the lock, so a process is
        never killed after its run has closed its job (discard first)."""
        with self._lock:
            self.stopped = True
            for proc in self._going:
                shared.processes.kill_process(proc)


class _CheckStopped(Exception):
    """A run of the check not started because Ctrl+C stopped the check (_CheckProcesses)."""


def _check_run(setup, folder, fmt, decks_, games, env, card_log, seed=CHECK_SEED, v2=None, game_patches=False,
               going=None, pilots=None):
    """Play one of the check's runs: (output, its LogReader, seconds taken). card_log None is
    plain Forge (seed its -s); else DeckLabSim with the card log's jar, playing v2's request
    (runner.request_args: "card_log": False plays without the card log's listener) with Deck
    Lab's changes to Forge's classes that change games (Forge's jar's simjar.FORGE_PATCH_LIST) on
    or (game_patches False: -Ddecklab.gamePatches=off) playing Forge's own code; those that only
    make games faster play as in runs. Plain Forge always plays with them off. decks_ are the .dck names in deck 1, deck 2 order. The process
    runs in a slot (_check_slot), and while it runs it's one of going (a _CheckProcesses, if
    given: _CheckStopped instead of starting once that's stopped). pilots (engine-check):
    [deck 1's pilot, deck 2's pilot] for a v2 request, as runner.build_command takes them."""
    launch = dict(setup, decks_dir=folder, card_log=card_log or {"ready": False}, game_patches=game_patches)
    more = {} if pilots is None else {"pilots": pilots}
    argv = shared.runner.build_command(launch, fmt, *(f"{name}.dck" for name in decks_), games, seed, v2, **more)
    logged = bool(card_log) and (v2 or {}).get("card_log") is not False
    reader = shared.LogReader(0, None, card_log=logged)
    lines = []
    lease = _check_slot(setup)
    if going is not None and going.stopped:
        lease.release()
        raise _CheckStopped
    t0 = shared.time.monotonic()
    try:
        proc = shared.processes.start_process(argv, cwd=setup["forge_dir"], env=env)
    except OSError as e:
        lease.release()
        raise shared._CliError(f"Forge couldn't be started ({shared._os_reason(e)}).") from None
    if going is not None:
        going.add(proc)
    try:
        for line in proc.stdout:
            lines.append(line)
            reader.feed(line)
        proc.wait()
    finally:
        if going is not None:
            going.discard(proc)
        shared.processes.kill_process(proc)        # only when stopped part way: it has ended otherwise
        proc.stdout.close()
        shared._end_process(proc)
        lease.release()
    reader.close()
    problem = reader.failure(games, proc.returncode)
    if problem:
        which = ("with plain Forge" if not card_log else "without the card log" if not logged
                 else f"with Deck Lab's engine (its game patches {'on' if game_patches else 'off'})")
        raise shared._CliError(f"The check's {fmt} games couldn't be played {which}. {problem}.")
    return "".join(lines), reader, shared.time.monotonic() - t0


def _check_runs(setup, folder, legs, env, log):
    """Every run the check plays, {name: (fmt, the .dck names in seat order, games, card_log, seed, v2,
    game_patches)}, _check_run's arguments after folder but env: for each format,
    DeckLabSim's request for games 0 to n - 1 of the check decks' stream (base CHECK_SEED) with
    its game patches off ("off") and on ("on"), on without the card log ("nolog"), and plain
    Forge playing each game g alone from its own seed ("plain", g), the decks in game g's seats."""
    runs = {}
    for fmt, decks_, n in legs:
        names, stream = _check_sides(decks_, fmt)
        v2 = {"stream": shared.seeds.stream_hex(stream), "first": 0}
        seated = _seated(names, 0)          # a request never spans a seat block (n <= CHECK_MAX_GAMES)
        runs[fmt, "off"] = (fmt, seated, n, log, CHECK_SEED, v2, False)
        runs[fmt, "on"] = (fmt, seated, n, log, CHECK_SEED, v2, True)
        runs[fmt, "nolog"] = (fmt, seated, n, log, CHECK_SEED, dict(v2, card_log=False), True)
        for g in range(n):
            runs[fmt, "plain", g] = (fmt, _seated(names, g), 1, None, shared.seeds.game_seed(CHECK_SEED, stream, g), None,
                                     False)
    return runs


CHECK_STOP_WAIT = 10            # seconds Ctrl+C waits for the check's runs to end once their processes are killed


class RunOptions(dict):
    """The last of a run's arguments in _play_check_runs, when it has keywords of its own: "setup"
    and "env" in place of the shared ones, "pilots" for _check_run (engine-check)."""


def _run_one(setup, folder, env, args, going):
    """_check_run for one of _play_check_runs' runs: args as _check_runs gives them, with an
    optional RunOptions at the end."""
    args, more = (args[:-1], dict(args[-1])) if args and isinstance(args[-1], RunOptions) else (args, {})
    setup, env = more.pop("setup", setup), more.pop("env", env)
    return _check_run(setup, folder, *args[:3], env, *args[3:], going=going, **more)


def _play_check_runs(setup, folder, env, runs, first_use):
    """_check_run for each of runs, CHECK_PROCESSES at once (the first alone when Forge's user
    folder is new, first_use: see runner._play); {name: (output, reader, seconds)}. A run's
    arguments may end with a RunOptions (engine-check: its own setup and pilots). The first
    error is raised again once the processes going have ended (the rest aren't started).
    Ctrl+C kills the processes going, starts no more, waits a little for their runs to end
    (CHECK_STOP_WAIT, so their slots are given back before the check's folder goes) and is
    raised again."""
    todo, done, errors = list(runs.items()), {}, []
    lock, going = shared.threading.Lock(), _CheckProcesses()

    def worker():
        while True:
            with lock:
                if errors or not todo or going.stopped:
                    return
                name, args = todo.pop(0)
            try:
                found = _run_one(setup, folder, env, args, going)
            except BaseException as e:      # raised again in the main thread
                with lock:
                    errors.append(e)
                return
            with lock:
                done[name] = found

    def wait(threads):
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                while thread.is_alive():
                    thread.join(0.2)        # short waits, so Ctrl+C is noticed
        except KeyboardInterrupt:
            going.stop()
            until = shared.time.monotonic() + CHECK_STOP_WAIT
            for thread in threads:
                while thread.is_alive() and shared.time.monotonic() < until:
                    thread.join(0.2)
            raise

    if first_use and todo:
        alone, todo[:] = todo[:1], todo[1:]
        name, args = alone[0]
        try:
            done[name] = _run_one(setup, folder, env, args, None)
        except BaseException as e:
            errors.append(e)
    if not errors:
        wait([shared.threading.Thread(target=worker, daemon=True) for _ in range(min(CHECK_PROCESSES, len(todo)))])
    if errors:
        raise errors[0]
    return done


class _CardLogUnavailable(shared._CliError):
    """cardlog-check stopped before playing anything: the card log can't be built (or its
    DeckLabSim source can't be read). upgrade-check skips serve-check for this one only, since
    serve-check needs the same card log; any other _CliError of the check came after it was built."""


def _cardlog_check(games, commander_games=CHECK_COMMANDER_GAMES):
    """cardlog-check, for wave 2's engine (contract section 18). For each format (Constructed,
    Commander) the check decks play games 0 to n - 1 of their seed stream (base CHECK_SEED):
      1. Parity with plain Forge: one DeckLabSim process plays them (-dlgame) with its game
         patches off, and plain Forge plays each game g alone, from its own seed
         (seeds.game_seed), in its own process; game for game the same (PARITY).
      2. The card log on and off: DeckLabSim plays them with its game patches on, with and
         without the card log; the same games (CARD_LOG_LEG).
      3. Warm: one serve worker plays them, chunked and repeated, as fresh processes do
         (servecheck.warm_leg).
      4. Every game's card log passes its checks, and every Commander game names both
         commanders (in each card-log run of 1 and 2).
    Games are compared line for line in Constructed, with the card log's lines, Java's stack
    frames and notices, timings and the games' places masked and attackers in name order
    (_games_text), and by winner, starter and length in Commander (LINE_FOR_LINE). When all
    of it holds, this Forge version and build is noted as checked with this DeckLabSim source
    (simjar.record_checked), so runs use the card log with it. When the card log or the engine
    itself went wrong, the failed check is noted (simjar.record_failed), so runs go without the
    card log on this version, even one checked before, until a check passes. When the only
    problem is games that differ in a way that says nothing about the engine (a game that hit
    one of Forge's time limits, or one after it in the same DeckLabSim process; a Commander
    game that ended differently; a warm game whose difference didn't come back: _leg_problem,
    warm_leg), the check can't tell, and nothing is noted."""
    setup = shared._setup()
    version = setup["version"]
    build = shared.simjar.forge_build(setup["forge_dir"] / setup["jar"])
    try:
        source = shared.simjar.source_sha256()
    except OSError:
        raise _CardLogUnavailable(shared.simjar.NO_SOURCE) from None
    log = shared.simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], version, checking=True)
    if not log["ready"]:
        raise _CardLogUnavailable(log["problem"])
    legs = _check_legs(games, commander_games)
    folder = shared.Path(shared.tempfile.mkdtemp(prefix="decklab-cardlog-check-"))
    try:
        for _, decks_, _ in legs:
            for name, (commander, cards) in decks_.items():
                sections = ([("Commander", commander)] if commander else []) + [("Main", cards)]
                text = f"[metadata]\nName={name}\n" + "".join(f"[{section}]\n" + "\n".join(lines) + "\n"
                                                             for section, lines in sections)
                (folder / f"{name}.dck").write_text(text, encoding="utf-8", newline="\n")
        env = shared._prepare_user_dir(setup["user_dir"])
        print(f"Checking the card log with Forge {version}: {games} Constructed and {commander_games} Commander "
              f"games (seed base {CHECK_SEED}), each played by plain Forge, by Deck Lab's engine with its game "
              "patches off and on, without the card log, and by a warm worker...", file=shared.sys.stderr)
        marker = shared.runner._first_use_marker(setup["user_dir"], version)
        runs = _check_runs(setup, folder, legs, env, log)
        done = _play_check_runs(setup, folder, env, runs, not marker.exists())
        try:
            marker.touch()
        except OSError:
            pass
        problems = []
        for fmt, _, n in legs:
            plain = [done[fmt, "plain", g][0] for g in range(n)]
            off, off_reader, off_s = done[fmt, "off"]
            on, on_reader, on_s = done[fmt, "on"]
            nolog, _, nolog_s = done[fmt, "nolog"]
            plain_s = sum(done[fmt, "plain", g][2] for g in range(n))
            print(f"  {fmt}: plain Forge took {plain_s:.1f} s ({n} processes), Deck Lab's engine {off_s:.1f} s with "
                  f"its game patches off, {on_s:.1f} s on, {nolog_s:.1f} s without the card log", file=shared.sys.stderr)
            for found in (_leg_problem(version, fmt, n, plain, off, off_reader, PARITY),
                          _leg_problem(version, fmt, n, nolog, on, on_reader, CARD_LOG_LEG)):
                if found:
                    problems.append(found)
        requests = [(fmt, f"{runs[fmt, 'off'][1][0]}.dck", f"{runs[fmt, 'off'][1][1]}.dck", n, CHECK_SEED,
                     runs[fmt, "off"][5]) for fmt, _, n in legs]
        warm = shared.servecheck.warm_leg(dict(setup, card_log=log), folder, env, log, requests)
        if warm:
            problems.append(warm)
    finally:
        shared.shutil.rmtree(folder, ignore_errors=True)
        shared.runner._tidy_user_dir(setup["user_dir"])
    for _, lines in problems:
        print("\n".join(lines))
    if any(kind == "failed" for kind, _ in problems):
        shared.simjar.record_failed(version, games + commander_games, build, source)    # a ForgeError: main() says it wasn't noted
        print(f"Runs with Forge {version} go without the card log until a check passes.")
        return 1
    if problems:
        print(f"Nothing was noted, so runs with Forge {version} go on as they were.")
        return 1
    shared.simjar.record_checked(version, games + commander_games, build, source)
    print(f"The card log played the same {games} Constructed and {commander_games} Commander games as plain "
          f"Forge {version}, so runs with Forge {version} use it from now on.")
    return 0


def _check_games(text):
    """argparse's type for cardlog-check's games: a whole number from 1 to CHECK_MAX_GAMES (one
    seat block, so DeckLabSim plays them as one request)."""
    number = shared._positive(text)
    if number > CHECK_MAX_GAMES:
        raise shared.argparse.ArgumentTypeError(f"must be at most {CHECK_MAX_GAMES}, not {text!r}")
    return number


def _cardlog_check_args(sub):
    check = sub.add_parser("cardlog-check", help="check the card log plays the same games as plain Forge")
    check.add_argument("--games", type=_check_games, default=CHECK_GAMES,
                       help=f"Constructed games each way (at most {CHECK_MAX_GAMES})")
    check.add_argument("--commander-games", type=_check_games, default=CHECK_COMMANDER_GAMES,
                       help=f"Commander games each way (at most {CHECK_MAX_GAMES})")


def _cmd_cardlog_check(args):
    return _cardlog_check(args.games, args.commander_games)


def _serve_check_args(sub):
    """serve-check: the warm-equivalence check alone (servecheck.py)."""
    from . import servecheck
    check = sub.add_parser("serve-check", help="check a warm worker plays the same games as a fresh process")
    check.add_argument("--games", type=shared._positive, default=servecheck.GAMES,
                       help="games of cardlog-check's 60-card lists (and half as many of two lists of "
                            "double-faced and adventure cards, when Deck Lab's copy of Forge's attack checks "
                            "plays), each played warm and fresh")
    check.add_argument("--commander-games", type=shared._positive, default=servecheck.COMMANDER_GAMES,
                       help="games of cardlog-check's Commander lists, each played warm and fresh")
    check.add_argument("--v1", action="store_true",
                       help="play the v1 engine's requests (one seed a request) instead of the v2 engine's")


def _cmd_serve_check(args):
    """serve-check: servecheck.warm_leg on cardlog-check's lists and servecheck.warm_decks()
    (WARM_DECKS, when their games repeat), with the card-log jar of this source whatever the
    checks say (as cardlog-check builds it). It notes nothing: cardlog-check, of which it is a
    leg, is what lets runs use the card log."""
    from . import servecheck
    setup = shared._setup()
    version = setup["version"]
    log = shared.simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], version, checking=True)
    if not log["ready"]:
        raise shared._CliError(log["problem"])
    legs = [("Constructed", {name: ([], cards) for name, cards in CHECK_DECKS.items()}, args.games)]
    warm_decks = servecheck.warm_decks(setup, log)
    if warm_decks:
        legs.append(("Constructed", warm_decks, max(2, args.games // 2)))
    else:
        print("Its lists of double-faced and adventure cards are left out: Deck Lab's copy of Forge's attack "
              "checks isn't playing, and without it some of their games differ even between two fresh "
              "processes.", file=shared.sys.stderr)
    legs.append(("Commander", CHECK_COMMANDER_DECKS, args.commander_games))
    folder = shared.Path(shared.tempfile.mkdtemp(prefix="decklab-serve-check-"))
    try:
        requests = servecheck.check_requests(folder, legs, CHECK_SEED, v1=args.v1)
        games = sum(request[3] for request in requests)
        env = shared._prepare_user_dir(setup["user_dir"])
        print(f"Checking a warm worker with Forge {version}: {len(requests)} requests of {games} games "
              f"({'v1' if args.v1 else 'v2'}), each played by one warm worker after other matchups' and by a "
              "fresh process...", file=shared.sys.stderr)
        found = servecheck.warm_leg(setup, folder, env, log, requests)
    finally:
        shared.shutil.rmtree(folder, ignore_errors=True)
        shared.runner._tidy_user_dir(setup["user_dir"])
    if found is None:
        print(f"A warm worker played the same {games} games as fresh processes with Forge {version}.")
        return 0
    kind, lines = found
    print("\n".join(lines))
    if kind == "failed":
        print("A warm pool would play other games than fresh processes with this Forge version and source.")
    return 1
