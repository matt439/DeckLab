"""Real-Forge checks of wave 3's Java (sim-wave3-contract.md section 3.7, J3): deck-order-1's
alignment, TeamPumpAi switched off and on, the hybrid AI's determinism, the AI profile folder, and
every current list keeping its .dck order. They need the installed Forge and a JDK, so they run
only with DECKLAB_FORGE_TESTS=1; DECKLAB_J3_FULL=1 plays the contract's sizes (checks 2-6: 20, 60,
60, 10 and 20 games), otherwise smaller ones. Each check plays at most 4 Forge processes at once, in
slots (cli._check_slot), below normal priority (processes.start_process), with a card-log jar built
into a scratch data folder and a scratch Forge user folder, so nothing of a real run is touched.
Check 1 (cardlog-check) is the CLI's own: python -m decklab.lib.forge cardlog-check.

Real-Forge qualification requires separate explicit authorization; the default fixture runner disables it.
Run from the repo root: set DECKLAB_FORGE_TESTS=1 and
python -m unittest decklab.tests.test_forge_deckorder
"""
import os
import re
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from decklab.lib import forge, inventory
from decklab.lib.forge import cli, processes, runner, simjar
from decklab.tests import pre_db

REAL = os.environ.get("DECKLAB_FORGE_TESTS") == "1"
FULL = os.environ.get("DECKLAB_J3_FULL") == "1"
PROCESSES = 4                   # Forge processes at once (sim-wave3-contract.md section 22)
BASE = 3                        # the checks' seed base
STREAM = "5a3c0ffee0ddba11"     # and stream
RE_ZONE = re.compile(r"DL\|zone\|(\d+)\|[^|]*\|[^|]*\|([^|]*)\|([^|]*)\|(\d+|-)\|(\d+)\|(.*)$")
RE_TURN1 = re.compile(r"^Turn: Turn 1 \(Ai\((\d+)\)-")
RE_ENGINE = re.compile(r"^DLENGINE\|(.*)$")
RE_DECK = re.compile(r"DL\|deck\|(\d+)\|(.*)$")
FORGE_PROFILES = ("Cautious", "Default", "Experimental", "Reckless")


def engine(output):
    """The DLENGINE line's fields of a process's output: {key: value}."""
    for line in output.splitlines():
        m = RE_ENGINE.match(line.strip())
        if m:
            return dict(field.split("=", 1) for field in m[1].split("|") if "=" in field)
    return None


def zone_moves(game):
    """A game's DL|zone moves: [(from, to, owner seat, id, name)]."""
    out = []
    for line in game:
        m = RE_ZONE.search(line)
        if m:
            out.append((m[2], m[3], m[4], int(m[5]), m[6].strip()))
    return out


def starter(game):
    for line in game:
        m = RE_TURN1.match(line.strip())
        if m:
            return int(m[1])
    return None


def deck_ids(game):
    """{seat: [(id, name)]} of a game's DL|deck lines, ids ascending as printed."""
    out = {}
    for line in game:
        m = RE_DECK.search(line)
        if m:
            out[int(m[1])] = [(int(i), n) for i, n in (part.split("=", 1) for part in m[2].split(";") if part)]
    return out


def dck_names(text):
    """A .dck text's [Main] names in line order, copies expanded (decklab.DeckOrder.mainNames)."""
    names, main = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            main = line.lower() == "[main]"
            continue
        m = re.match(r"^(\d+)\s+(.+)$", line)
        if main and m:
            names += [m[2].split("|")[0].strip()] * int(m[1])
    return names


NOISE = " Did not have activator set in SpellAbilityRestriction.canPlay()"
RE_SEARCH = re.compile(r"Ai\(1\)-\S+ (?:searches|reveals)|\|Library\|Library\|1\|", re.I)
# A resolving effect that searches or reveals a library (Fierce Empath's "you may search your
# library" names no player): its card is the Zone Changer's, else the line's first id.
RE_LIBRARY_EFFECT = re.compile(r"^Resolve Stack: .*\b(?:search|reveal)\w* .*\b(?:your|their) library", re.I)
RE_EFFECT_CARD = re.compile(r"\[Zone Changer: .*\((\d+)\)\]|\((\d+)\)")


def timed_out(line):
    """A line of the AI's decision timeout (java.util.concurrent.TimeoutException at
    FutureTask.get) or of the stack trace Forge prints with it."""
    return "TimeoutException" in line or line.startswith("\tat ")


def searched(line, ids):
    """Whether a line is seat 1 searching or revealing its library: RE_SEARCH, or a resolving
    effect of a card whose id is one of ids (seat 1's) that does."""
    if RE_SEARCH.search(line):
        return True
    if not RE_LIBRARY_EFFECT.match(line.strip()):
        return False
    found = RE_EFFECT_CARD.findall(line)
    card = next((z for z, _ in found if z), None) or next((n for _, n in found if n), None)
    return card is not None and int(card) in ids


def draws_since_search(game, k, ids):
    """Seat 1's moves out of its library to its hand in game[s + 1:k], s being the last line at
    or before k + 3 where seat 1 searched or revealed its library (searched(); ids: seat 1's card
    ids); None when there's no such line."""
    found = [i for i, line in enumerate(game[:k + 4]) if searched(line, ids)]
    if not found:
        return None
    return sum(1 for line in game[found[-1] + 1:k] if (m := RE_ZONE.search(line))
               and (m[2], m[3], m[4]) == ("Library", "Hand", "1"))


def divergence(a, b, changed):
    """How two arms' games (lines) of an aligned pair compare: "same" when they never differ; "seen"
    when they first differ after a card of a changed slot (changed: its ids) moved; "timed out" when
    either arm's AI hit its decision timeout at or just after the first difference, or before it
    (TimeoutException: it depends on the PC's load, and a fallback decision can change the game);
    "searched" when they first differ after seat 1 searched or revealed its library, before seat 1's
    next draw (a hidden-library read, which may see a changed card without moving it, and so change
    the AI's choice and the shuffle that follows: sim-wave3-contract.md section 3.2; a difference
    after that draw would be a misalignment the search doesn't explain); None otherwise."""
    def kept(game):
        """Without the changed seat's deck line, Java's notices and the AI's own println noise about
        the cards it looks at (which differ with a changed card in hand), timings masked (cli's)."""
        return [cli.RE_ORDINAL.sub(r"\g<1>?", cli.RE_TIMING.sub("?", l)) for l in game
                if l.strip() and "DL|deck|" not in l and not l.startswith("WARNING") and NOISE not in l]

    la, lb = kept(a), kept(b)
    k = next((i for i, (x, y) in enumerate(zip(la, lb)) if x != y), None)
    if k is None and len(la) == len(lb):
        return "same"
    k = min(len(la), len(lb)) if k is None else k
    before = la[:k + 1] + lb[:k + 1]     # the differing line too: it may be the changed card's own move
    for line in before:
        m = RE_ZONE.search(line)
        if m and int(m[5]) in changed:
            return "seen"
    # A stack trace's lines, and a resolving effect's line, can come just after the first
    # difference: Forge logs an effect's line after the moves it made.
    after = la[k + 1:k + 4] + lb[k + 1:k + 4]
    if any(timed_out(line) for line in before + after):
        return "timed out"
    ids = {i for i, _ in deck_ids(a).get(1, [])} | {i for i, _ in deck_ids(b).get(1, [])}
    if 0 in (draws_since_search(la, k, ids), draws_since_search(lb, k, ids)):
        return "searched"
    print("\n".join(["", "the first difference:", *la[max(0, k - 8):k + 2], "----", *lb[max(0, k - 2):k + 2]]))
    return None


def key(name):
    """DeckOrder.key: the front face, accents off, lower case."""
    return forge.common.norm(name.split(" // ")[0])


@unittest.skipUnless(REAL, "set DECKLAB_FORGE_TESTS=1 to play wave 3's Java checks with the real Forge")
class DeckOrderChecks(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        settings = forge.common._settings()
        cls.java = str(forge.find_java(settings.get("forge_java")))
        cls.forge_dir = Path(settings["forge_dir"])
        cls.jar_name, cls.version = forge.install._find_jar(cls.forge_dir)
        if simjar.forge_build(cls.forge_dir / cls.jar_name) != simjar.CHECKED_BUILDS.get(cls.version):
            raise unittest.SkipTest("the installed Forge isn't the build Deck Lab's copies were made from")
        # The decks as the pre-db-decks tag holds them: the tests never read the live database.
        cls.restore_inventory = inventory.use(pre_db.decks_inventory())
        cls.tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(forge.common, "DATA_DIR", cls.tmp / "data"):
            simjar._built.clear()
            cls.log = simjar.card_log(cls.java, cls.forge_dir, cls.jar_name, cls.version, checking=True)
            simjar._built.clear()
        if not cls.log.get("ready"):
            raise unittest.SkipTest(f"the card log couldn't be built: {cls.log.get('problem')}")
        cls.decks = cls.tmp / "decks"
        cls.decks.mkdir()
        cls.env = runner._prepare_user_dir(cls.tmp / "user")
        cls.setup = {"java": cls.java, "xmx": settings.get("forge_xmx", "1024m"), "jar": str(cls.forge_dir / cls.jar_name),
                     "decks_dir": cls.decks, "clock_s": 120, "card_log": cls.log, "forge_dir": cls.forge_dir,
                     "workers": settings.get("forge_workers", 16)}
        cls.lock = threading.Lock()
        # A new user folder's first Forge start runs alone (runner._play's rule): processes that
        # start together in one fail now and then.
        first = cls("test_7_every_list_keeps_its_order")
        izzet = cls.write("first-use", cls.entry_dck("casual/izzet-prowess"))
        first.play(izzet, izzet, 0, 1, decks_only=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.restore_inventory()

    # ------------------------------------------------------------ playing

    @classmethod
    def write(cls, name, text):
        (cls.decks / f"{name}.dck").write_text(text, encoding="utf-8")
        return f"{name}.dck"

    @classmethod
    def entry_dck(cls, deck_id, owned=False):
        return cli._cli_entry(deck_id, owned)["dck"]

    def play(self, d1, d2, first, games, *, fmt="Constructed", jvm=(), profiles=None, pilots=None, decks_only=False):
        """One DeckLabSim process: games first.. of the checks' stream, d1 and d2 the .dck names.
        decks_only: end the process once both seats' DL|deck lines are out (check 7)."""
        argv = runner.build_command(self.setup, fmt, d1, d2, games, BASE, {"stream": STREAM, "first": first})
        argv[1:1] = list(jvm)
        if profiles:
            at = argv.index("-a")
            argv[at + 1:at + 3] = list(profiles)
        if pilots:
            argv += ["-dlpilot", *pilots]
        lease = cli._check_slot(self.setup)
        lines, seen = [], 0
        try:
            proc = processes.start_process(argv, cwd=self.forge_dir, env=self.env)
            try:
                for line in proc.stdout:
                    lines.append(line)
                    if decks_only and "DL|deck|" in line:
                        seen += 1
                        if seen == 2:
                            break
                    if decks_only and (line.startswith(("Error:", "Unknown AI")) or "match cannot start" in line):
                        break
            finally:
                processes.kill_process(proc)
                proc.stdout.close()
                proc.wait()
        finally:
            lease.release()
        return "".join(lines)

    def play_many(self, d1, d2, games, **kwargs):
        """games 0..games-1 over at most PROCESSES processes: (the first process's output, every
        game's lines in order)."""
        per = max(1, -(-games // PROCESSES))
        ranges = [(first, min(per, games - first)) for first in range(0, games, per)]
        with ThreadPoolExecutor(PROCESSES) as pool:
            outputs = list(pool.map(lambda r: self.play(d1, d2, r[0], r[1], **kwargs), ranges))
        played = [game for output in outputs for game in cli._split_games(output)]
        short = [output[-1500:] for (first, n), output in zip(ranges, outputs) if len(cli._split_games(output)) != n]
        self.assertEqual(len(played), games, short[:1])
        return outputs[0], played

    # ------------------------------------------------------------ the checks

    def test_2_alignment(self):
        """Gruul Ramp (target) against Izzet Prowess: a variant in its base's order draws the same
        cards, and the same seat starts, until the changed slot's card is seen."""
        games = 20 if FULL else 8
        base_text = self.entry_dck("casual/gruul-ramp")
        izzet = self.write("izzet", self.entry_dck("casual/izzet-prowess"))
        lines = base_text.splitlines()
        main = lines.index("[Main]")
        cards = [(i, int(l.split(" ", 1)[0]), l.split(" ", 1)[1]) for i, l in enumerate(lines) if i > main and l.strip()]
        lands = {"Forest", "Mountain", "Plains", "Island", "Swamp"}
        spells = [c for c in cards if c[1] >= 2 and c[2] not in lands]
        spells4 = sorted(spells, key=lambda c: -c[1])           # the most copies first (any list's)
        other = next(c for c in cards if c[2] not in lands and c[2] != spells4[0][2])

        def variant(changes):
            """The base text with each (line index, new name) taking that line's last copy."""
            out = list(lines)
            for index, new in sorted(changes, reverse=True):
                q, name = int(out[index].split(" ", 1)[0]), out[index].split(" ", 1)[1]
                out[index:index + 1] = [f"{q - 1} {name}", f"1 {new}"]
            return "\n".join(out) + "\n"

        arms = {"v1": variant([(spells4[0][0], other[2])]),
                "v2": variant([(spells[0][0], "Mountain"), (spells[1][0], "Forest")])}
        base = self.write("gruul", base_text)
        _, base_games = self.play_many(base, izzet, games)
        for arm, text in arms.items():
            with self.subTest(arm):
                _, arm_games = self.play_many(self.write(f"gruul-{arm}", text), izzet, games)
                counts = {"same": 0, "seen": 0, "searched": 0, "timed out": 0}
                for n, (a, b) in enumerate(zip(base_games, arm_games)):
                    self.assertEqual(starter(a), starter(b), f"game {n}: another seat started")
                    ids_a, ids_b = deck_ids(a), deck_ids(b)
                    changed = {i for (i, x), (_, y) in zip(ids_a[1], ids_b[1]) if x != y}
                    self.assertTrue(changed, f"game {n}: no slot changed")
                    self.assertEqual(ids_a[2], ids_b[2])            # the opponent's library is the same
                    how = divergence(a, b, changed)
                    self.assertIsNotNone(how, f"{arm} game {n}: the arms differ before the changed slot was seen, "
                                              f"or after Gruul's next draw since it searched its library")
                    counts[how] += 1
                print(f"\n{arm}, {games} games: {counts['same']} the same throughout, {counts['seen']} the same "
                      f"until the changed slot's card moved, {counts['searched']} until Gruul searched or revealed "
                      f"its library (a hidden-library read), {counts['timed out']} until an AI decision timed out "
                      f"(the PC's load)")
                self.assertGreaterEqual(counts["same"] + counts["seen"], (games - counts["timed out"]) // 2)

    def test_3_team_pump_off_changes_nothing(self):
        """Selesnya Rabbits against Orzhov Vampires: TeamPumpAi installed with no seat switched on
        plays exactly Forge's games (installed against -Ddecklab.aipatches.install=false)."""
        games = 60 if FULL else 12
        rabbits = self.write("rabbits", self.entry_dck("casual/selesnya-rabbits"))
        vampires = self.write("vampires", self.entry_dck("casual/orzhov-vampires"))
        off_out, off = self.play_many(rabbits, vampires, games, jvm=["-Ddecklab.aipatches.install=false"])
        on_out, on = self.play_many(rabbits, vampires, games)
        self.assertNotIn("DL-START|aipatch|PumpAll", off_out)
        self.assertIn("DL-START|aipatch|PumpAll", on_out)
        self.assertIsNone(cli._compare(self._joined(off), self._joined(on), ("not installed", "installed")))

    def test_4_team_pump_on(self):
        """The same games with Rabbits' seat on team-pump-1: no exception, and a team pump cast at
        least once (a smoke check, not a measurement: the counts are printed)."""
        games = 60 if FULL else 12
        rabbits = self.write("rabbits", self.entry_dck("casual/selesnya-rabbits"))
        vampires = self.write("vampires", self.entry_dck("casual/orzhov-vampires"))
        _, off = self.play_many(rabbits, vampires, games)
        out, on = self.play_many(rabbits, vampires, games, pilots=["team-pump-1", "-"])
        self.assertEqual(engine(out)["pilots"], "team-pump-1,-")
        pumps = ("Overrun", "Rabbit Response")

        def casts(played):
            return sum(1 for game in played for m in zone_moves(game)
                       if m[0] == "Hand" and m[1] == "Stack" and m[2] == "1" and m[4] in pumps)

        for game in on:
            self.assertFalse(any("Exception" in line for line in game))
        print(f"\nteam pumps cast by Rabbits: {casts(off)} switched off, {casts(on)} switched on, {games} games")
        self.assertGreater(casts(on), 0)

    def test_5_hybrid_is_deterministic(self):
        """Izzet against Gruul with seat 1 on aisim-hybrid-1, twice: the same games."""
        games = 10 if FULL else 4
        izzet = self.write("izzet", self.entry_dck("casual/izzet-prowess"))
        gruul = self.write("gruul", self.entry_dck("casual/gruul-ramp"))
        out1, one = self.play_many(izzet, gruul, games, pilots=["aisim-hybrid-1", "-"])
        _, two = self.play_many(izzet, gruul, games, pilots=["aisim-hybrid-1", "-"])
        self.assertEqual(engine(out1)["pilots"], "aisim-hybrid-1,-")
        self.assertIsNone(cli._compare(self._joined(one), self._joined(two), ("first", "second")))

    def test_6_profile_folder(self):
        """A folder of Forge's four profiles and DLAggro.ai: -a DLAggro Default loads, and Default
        games play the same with the folder as without it."""
        games = 20 if FULL else 8
        folder = self.tmp / "profiles"
        folder.mkdir(exist_ok=True)
        for name in FORGE_PROFILES:
            shutil.copy(self.forge_dir / "res" / "ai" / f"{name}.ai", folder / f"{name}.ai")
        default = (folder / "Default.ai").read_text(encoding="utf-8")
        (folder / "DLAggro.ai").write_text(default.replace("PLAY_AGGRO=false", "PLAY_AGGRO=true"), encoding="utf-8")
        flag = f"-Ddecklab.aiprofiles={folder}"
        izzet = self.write("izzet", self.entry_dck("casual/izzet-prowess"))
        gruul = self.write("gruul", self.entry_dck("casual/gruul-ramp"))
        aggro = self.play(izzet, gruul, 0, 1, jvm=[flag], profiles=["DLAggro", "Default"])
        self.assertEqual(engine(aggro)["ai"], "DLAggro,Default")
        self.assertEqual(engine(aggro)["aiprofiles"], "dl")
        self.assertEqual(len(cli._split_games(aggro)), 1)
        unknown = self.play(izzet, gruul, 0, 1, profiles=["DLAggro", "Default"])      # without the folder
        self.assertIn("Unknown AI profile - DLAggro", unknown)
        with_out, with_folder = self.play_many(izzet, gruul, games, jvm=[flag])
        without_out, without = self.play_many(izzet, gruul, games)
        self.assertEqual((engine(with_out)["aiprofiles"], engine(without_out)["aiprofiles"]), ("dl", "forge"))
        self.assertIsNone(cli._compare(self._joined(without), self._joined(with_folder), ("res/ai", "the folder")))
        broken = self.tmp / "no-such-folder"
        failed = self.play(izzet, gruul, 0, 1, jvm=[f"-Ddecklab.aiprofiles={broken}"])
        self.assertIn("Error: the AI profile folder", failed)

    def test_7_every_list_keeps_its_order(self):
        """One v2 game of each current list (target and owned-only, and every product deck) against
        Izzet Prowess (Constructed) or Giada (Commander): deckorder=1,1, and each seat's cards made
        in its .dck order."""
        from decklab.lib import decks
        refs = []
        for summary in decks.list_decks():
            if summary.get("error"):
                continue
            for version in summary["versions"]:
                refs.append((summary["id"], version == "owned", cli.engine_kind(summary)))
        opponents = {"constructed": ("casual/izzet-prowess", "Constructed"), "commander": ("commander/giada-angels", "Commander")}
        names = {kind: self.write(f"opp-{kind}", self.entry_dck(ref)) for kind, (ref, _) in opponents.items()}

        def one(ref):
            deck_id, owned, kind = ref
            text = self.entry_dck(deck_id, owned)
            name = self.write(re.sub(r"[^a-z0-9]+", "-", f"{deck_id}-{owned}"), text)
            out = self.play(name, names[kind], 0, 1, fmt=opponents[kind][1], decks_only=True)
            return ref, text, out

        problems = []
        with ThreadPoolExecutor(PROCESSES) as pool:
            for (deck_id, owned, kind), text, out in pool.map(one, refs):
                which = f"{deck_id} ({'owned' if owned else 'target'})"
                found = engine(out)
                if found is None or found.get("deckorder") != "1,1":
                    problems.append(f"{which}: deckorder={found and found.get('deckorder')}")
                    continue
                made = deck_ids(out.splitlines()).get(1, [])
                if [key(n) for _, n in made] != [key(n) for n in dck_names(text)]:
                    problems.append(f"{which}: its cards weren't made in .dck order")
        print(f"\n{len(refs)} lists checked")
        self.assertEqual(problems, [])

    def test_overrides_hash_is_pythons(self):
        """Startup's start-up hash of a custom/cards folder is engine._overrides' (and
        overrides.deployed_hash's), byte for byte: nested files, CRLF, a non-ASCII path, upper case."""
        user = self.tmp / "hash-user"
        cards = user / "Forge" / "custom" / "cards"
        (cards / "sub").mkdir(parents=True)
        (cards / "Ü").mkdir()
        (cards / "fiery_annihilation.txt").write_bytes(b"Name:Fiery Annihilation\r\nA:x\r\n")
        (cards / "sub" / "b.txt").write_bytes(b"Name:B\nA:y\n")
        (cards / "Ü" / "c.txt").write_bytes(b"z")
        (cards / "a.TXT").write_bytes(b"q")
        empty = self.tmp / "hash-empty"
        empty.mkdir()
        cp = os.pathsep.join([self.log["jar"], self.setup["jar"]])
        done = processes.subprocess.run([self.java, "-cp", cp, "decklab.Startup", str(cards), str(empty),
                                         str(self.tmp / "hash-missing")], capture_output=True, text=True,
                                        encoding="utf-8", timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.split(), [forge.engine._overrides(user), "none", "none"])
        self.assertEqual(forge.engine._overrides(user), forge.overrides.deployed_hash(user))

    def test_pilot_refusals(self):
        """-dlpilot's refusals (Request.parse): an id that isn't a switch, team-pump-1 with game
        patches off, and -dlpilot without -dlgame; and the echo of a seat's switches."""
        izzet = self.write("izzet", self.entry_dck("casual/izzet-prowess"))
        gruul = self.write("gruul", self.entry_dck("casual/gruul-ramp"))
        self.assertIn("Error: -dlpilot: no switch called nope", self.play(izzet, gruul, 0, 1, pilots=["nope", "-"]))
        self.assertIn("Error: team-pump-1 needs game patches on",
                      self.play(izzet, gruul, 0, 1, jvm=[simjar.GAME_PATCHES_OFF], pilots=["-", "team-pump-1"]))
        argv = runner.build_command(self.setup, "Constructed", izzet, gruul, 1, BASE) + ["-dlpilot", "-", "-"]
        lease = cli._check_slot(self.setup)
        try:
            done = processes.subprocess.run(argv, cwd=self.forge_dir, env=self.env, capture_output=True, text=True,
                                            encoding="utf-8", errors="replace", timeout=300,
                                            creationflags=getattr(processes.subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
        finally:
            lease.release()
        self.assertIn("Error: -dlpilot needs -dlgame", done.stdout)
        out = self.play(izzet, gruul, 0, 1, pilots=["team-pump-1+aisim-hybrid-1", "-"], decks_only=True)
        self.assertEqual(engine(out)["pilots"], "aisim-hybrid-1+team-pump-1,-")

    def test_a_fork_switch_reaches_the_seat(self):
        """AI round 1: a fork switch the build has (forge.ai.AiSwitches) is taken by -dlpilot and
        echoed. Request.parse refuses one when Startup couldn't install Pilots.forkOn as AiSwitches'
        hook, so this also shows the hook is in."""
        fork = sorted(set(self.log.get("pilot_switches") or []) & set(forge.pilots.FORK_SWITCHES))
        if not fork:
            self.skipTest("this Forge build has no fork AI switches")
        izzet = self.write("izzet", self.entry_dck("casual/izzet-prowess"))
        gruul = self.write("gruul", self.entry_dck("casual/gruul-ramp"))
        out = self.play(izzet, gruul, 0, 1, pilots=[fork[0], "-"], decks_only=True)
        self.assertNotIn("Error:", out)
        self.assertEqual(engine(out)["pilots"], f"{fork[0]},-")

    @staticmethod
    def _joined(played):
        """Games (each a list of lines) as one output for cli._compare, each after a header line."""
        return ["Ai(1)-x [Default] vs Ai(2)-y [Default] - one game of Constructed seed 0\n" + "\n".join(game)
                for game in played]


if __name__ == "__main__":
    unittest.main()
