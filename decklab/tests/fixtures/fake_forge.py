"""A stand-in for Forge's sim mode, which Deck Lab's tests run instead of Java (see
test_forge.fake_command).

    python fake_forge.py sim -D <deck folder> -d <deck1.dck> <deck2.dck> -n <games> -s <seed>
                         -f Constructed|Commander -c <clock> -a Default Default [--card-log]

It prints what Forge 2.0.15 prints, in its formats (see the real logs in fixtures/forge/):
start-up noise, the header line, then each game's full log with Mulligan, Turn, Land, Add To
Stack, Game Outcome, Match Result and Game Result lines. Everything follows from the seed, so
the same arguments print the same games. As in Forge, game 1's starter is random and the loser
of each game starts the next (deck 1 after a game nobody won). Each player casts a random card
of its deck most turns, apart from Fiery Annihilation and Devout Decree, which the fake AI never
casts, and plays a basic land on its first turns.

With --card-log it is DeckLabSim instead (Forge's sim with the card log,
decklab/lib/forge/java/decklab/DeckLabSim.java, whose lines decklab/lib/forge/cardlog.py reads):
the same games, line for line, with "Information: DL|..." lines among them that follow a real
library. Each seat's [Main] is shuffled (with an RNG of the game's own, so Forge's lines don't
change), 7 cards are drawn and kept, and one more is drawn on each of its turns but the
starter's first. A [Main] of fewer than 7 cards is all drawn and kept, and only then do Forge's
lines differ: its Mulligan line says how many (without --card-log it says 7, as it always has),
so the card log's kept-hand check passes. After both Mulligan lines, every "Leyline of ..." in a
kept hand is put onto the battlefield at turn 0, before the start hands are logged, as Forge's
opening-hand actions (GameAction.runOpeningHandActions) do. A card is cast or played from the
hand: when the fake AI picks one that isn't there, it's first fetched to the hand from the
library (as a tutor would) or, failing that, cast from the graveyard (as flashback would); a
commander is cast from the command zone. A spell goes to the graveyard, a land to the
battlefield, and the copy a land was played from has the id its "Land:" line shows (a basic
beyond the deck's copies is logged as a card in neither list). The end hands and library sizes
are what the moves leave. Before the header it prints DeckLabSim's DLENGINE line
(java/decklab/GameLoop.java engineLine): perf= says whether the user folder's
forge.preferences (APPDATA) turns PERFORMANCE_MODE on, gamepatches=off comes with
--game-patches-off (test_forge.fake_command adds it for setup["game_patches"] False),
gamepatchids= is what --game-patch-ids=<ids> gives (test_forge.fake_command passes the card
log's "game_patches"), each fake deck's average mana value is 2 unless FAKE_FORGE's avgcmc=a,b
says otherwise, and autoprofile follows Forge's rule (the deck's name holds "Control", or its
average mana value is over 3). -dlnocardlog drops the DL| lines (cardlog=off).

With --card-log and -dlgame <stream> <first> it plays wave 2's v2 engine (seeds.py): game i of
the run is the result's game g = first + i, played from its own seed, seeds.game_seed(-s,
stream, g), with a coin flip for who starts, whatever came before it; so game g is the same
game in any chunk that holds it. Without -dlgame, the games are what they always were.

    python fake_forge.py serve [--game-patches-off] [--game-patch-ids=<ids>]

is DeckLabSim's serve mode (java/decklab/DeckLabServe.java, wave 2's contract "Serve
protocol"): "DLSERVE|ready|1|<pid>|0,0,0,0,0,-2,0", then for each "play<TAB><id><TAB>sim<TAB>..."
line on stdin "DLSERVE|begin|<id>", "Simulation mode", what sim --card-log prints for those
arguments, and "DLSERVE|end|<id>|<status>|<games>|<ms>|<detail>" (a done or cancelled request's
detail "heap_mb=64"); "cancel<TAB><id>" stops a
request at its next game boundary (status cancelled); a game that hits the clock (timeout#G),
has an AI timeout (aitimeout#G: Deck Lab's AiController copy counts it, Signals) or crashes
(exception#G) ends its request there with status recycle (detail clock, ai_timeout or crash)
and the worker ("DLSERVE|bye|recycle", exit code 0); a Java error escaping (throw#G) ends it
with "end|<id>|error", "DLSERVE|bye|error" and exit code 1; arguments it can't read end the
request with status error, and it plays on; and "quit" or the end of stdin ends it
("DLSERVE|bye|quit" or "eof").

FAKE_FORGE in the environment makes it misbehave: a ";"-separated list of
what[=value][@seed][#game] (without @seed it applies to every process, without #game to the
whole run). #G is the game's number in its batch, from 1; with -dlgame it's the result's game
number g, from 0, whichever request plays it (and @seed matches the base):
    unsupported     prints Forge's "An unsupported card was requested" line, and plays on
    noload          prints "Could not load deck - ..." and exits with 0, playing nothing (serve:
                    the request ends with status error)
    timeout#G       game G hits the clock: "Stopping slow match as draw", both players "have won"
                    (serve: the request ends there with status recycle, detail clock, and the
                    worker exits)
    exception#G     game G throws: a stack trace, both players "have won" (serve: recycle after
                    it, detail crash)
    aitimeout#G     game G has two "AI eval thread at timeout" lines (serve: recycle after it,
                    detail ai_timeout, as Java's Signals see it)
    aitimeoutunseen#G
                    the same lines, which Java doesn't see (Deck Lab's AiController copy didn't
                    fit): serve plays on, and only Python's reading of the lines can tell
    hang#G          prints nothing more, ever, before game G's result (hang#0 without -dlgame:
                    before the header)
    crash#G         prints a stack trace and exits with code 1 before game G (serve: with no end
                    line)
    throw#G         a Java error escapes before game G: a stack trace, then (serve) "end|<id>|error"
                    with the error, "DLSERVE|bye|error" and exit code 1; (sim) exit code 1
    avgcmc=a,b      seat 1's and seat 2's average mana value (2 each without it), for the DLENGINE
                    line's avgcmc and autoprofile
    badargs         serve: the request's arguments can't be read (as a NumberFormatException in
                    Java): "end|<id>|error" and the worker plays on
    slowstart=S     waits S seconds before the header (serve: before the ready line)
    delay=S         waits S seconds before each game's result
    badcardlog#G    with --card-log, game G's card log is wrong (seat 1's end library size is
                    one too many), so its card data doesn't count
    servefail       serve: prints "DLSERVE|fail|..." instead of the ready line and exits with 3
    cardwins=<name> a seat with that card in its kept hand or among its first three draws (its
                    library's first 10 cards, as the card log shuffles it) wins the game, unless
                    both seats have it (wave 3: paired tests and experiments have a real effect to
                    find). Every process; no @seed or #game
    slowcard=<name>@<ms>
                    each game in which a seat's list holds that card takes ms longer (a sleep, and
                    its "Game Result" line's time). Every process; no @seed or #game
FAKE_FORGE_LOG, when set, is a file each process appends "<pid> <seed> <start time>" to (a
serve worker: for each request).

Wave 3 (forge-trial/sim-wave3-contract.md section 19.1) adds, as DeckLabSim does:
- -Ddecklab.gamePatches=off is --game-patches-off; -Ddecklab.aiprofiles=<dir> is the AI profile
  folder (Startup.afterInitialize): its *.ai names are known to -a along with Forge's own
  (FORGE_PROFILES). A folder that can't be read fails the start: serve prints "DLSERVE|fail|..."
  and exits with 3, sim prints an "Error:" line and exits with 3. --pilot-switches=<ids> are the
  switches the jar holds (simjar.PILOT_SWITCHES' ids, as card_log()["pilot_switches"] lists them).
- -a names each seat's profile (the header shows them, as Forge's does); one Forge doesn't know
  prints Forge's "Unknown AI profile - <name>. Available profiles: ..." line before anything else,
  and the request plays nothing (serve: status error, detail "Unknown AI profile - <name>").
- -dlpilot <seat 1> <seat 2> (v2 only): each a "+"-joined list of switch ids, or "-". An id not in
  --pilot-switches, a missing value, -dlpilot without -dlgame, or team-pump-1 with game patches
  off prints an "Error: ..." line and plays nothing (as Request.parse giving null: serve answers
  status error, "the request's arguments can't be read").
- The DLENGINE line adds deckorder=<s1>,<s2> and loadseed= (1,1 and 1 with game patches on, v2 and
  deck-order-1 among --game-patch-ids; else 0,0 and 0), ai=<p1>,<p2>, pilots=<s1>,<s2> ("-" for
  none), aiprofiles=forge|dl, and overrides=: the hash of the user folder's Forge/custom/cards
  (APPDATA) as it was when the process started (wave 2's engine._overrides form; "none" when
  empty), which serve mode keeps for every request.
- A seat's library is its [Main] in .dck line order, shuffled with the game's own card-log RNG, as
  Forge with deck-order-1 builds it (with deck-order-1 off the fake's order is the same), so an
  aligned variant draws the same cards until its changed slot.
"""
import hashlib
import importlib.util
import math
import os
import queue
import random
import re
import sys
import threading
import time
from pathlib import Path

NEVER_CAST = {"Fiery Annihilation", "Devout Decree"}
OPENING = "Leyline of "         # put onto the battlefield from a kept hand, with --card-log
BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest"}
WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]


def say(text=""):
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def log_start(path, seed):
    """Serialize appends: Windows append streams can otherwise overwrite each other's rows."""
    with open(path, "ab") as stream:
        if os.name == "nt":
            import msvcrt
            # A byte beyond EOF leaves live readers unblocked and never grows the file.
            stream.seek(1 << 20)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            stream.seek(0, os.SEEK_END)
            stream.write(f"{os.getpid()} {seed} {time.time():.3f}\n".encode("utf-8"))
            stream.flush()       # every byte of the record is visible before unlocking
        finally:
            if os.name == "nt":
                stream.seek(1 << 20)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def options(argv):
    """Forge's way: each -x (or -xyz: Deck Lab's -dlgame) starts an option, and the words
    after it are its values."""
    out, key = {}, None
    for word in argv:
        if word.startswith("-") and len(word) >= 2:
            key = word[1:]
            out[key] = []
        elif key:
            out[key].append(word)
    return out


def modes(seed):
    """{what: [game number or value]} of FAKE_FORGE's items that apply to this seed (a value
    with commas, avgcmc's: a tuple of numbers; cardwins' a card name; slowcard's (name, ms))."""
    out = {}
    for item in filter(None, (os.environ.get("FAKE_FORGE") or "").split(";")):
        if item.startswith("cardwins="):
            out.setdefault("cardwins", []).append(item[len("cardwins="):])
            continue
        if item.startswith("slowcard="):
            name, _, ms = item[len("slowcard="):].rpartition("@")
            out.setdefault("slowcard", []).append((name, float(ms)))
            continue
        item, _, game = item.partition("#")
        item, _, only = item.partition("@")
        if only and int(only) != seed:
            continue
        what, _, value = item.partition("=")
        if "," in value:
            value = tuple(float(v) for v in value.split(","))
        elif value:
            value = float(value)
        out.setdefault(what, []).append(value if value != "" else (int(game) if game else 0))
    return out


def read_deck(path):
    """(Name=, [(qty, card)] of [Commander] and [Main])."""
    name, cards, section = path.stem, [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line.lower()
        elif line.startswith("Name="):
            name = line[5:]
        elif section in ("[main]", "[commander]") and line:
            qty, card = line.split(" ", 1)
            cards.append((int(qty), card))
    return name, cards


def deck_sections(path):
    """([names] of [Commander], [names] of [Main]) of a .dck, a name per copy, in file order."""
    out, section = {"[commander]": [], "[main]": []}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line.lower()
        elif section in out and line:
            qty, card = line.split(" ", 1)
            out[section] += [card] * int(qty)
    return out["[commander]"], out["[main]"]


def plan_turns(rng, decks, first, turns):
    """Each turn's plays, from the game's RNG: [{"turn", "seat", "land" (or None), "land_id",
    "card" (cast, or None), "target" (the cast line's end), "trigger"}]."""
    plays, card_id = [], 100
    for turn in range(1, turns + 1):
        seat = first if turn % 2 else 3 - first
        deck = decks[seat - 1][1]
        lands = [c for _, c in deck if c in BASICS]
        spells = [c for _, c in deck if c not in BASICS and c not in NEVER_CAST]
        land = card = None
        target = ""
        if lands and turn <= 10:
            card_id += 1
            land = rng.choice(lands)
        if spells and rng.random() < 0.8:
            card = rng.choice(spells)
            target = f" targeting [Grizzly Bears ({card_id})]" if rng.random() < 0.3 else ""
        plays.append({"turn": turn, "seat": seat, "land": land, "land_id": card_id, "card": card,
                      "target": target, "trigger": rng.random() < 0.2})
    return plays


class CardLog:
    """The DL lines of one game (--card-log), worked out before any is printed: the game's
    plays are replayed on each seat's shuffled library and hand first, so a "Land:" line's
    land can be a copy that's in the hand, and that copy then gets the line's id. say(hook)
    prints the lines that go at one place among Forge's (see main)."""

    def __init__(self, sections, plays, rng, broken=False):
        self.names, self.zone, self.seat_of = {}, {}, {}
        self.library, self.hand, self.lists, self.commanders = {}, {}, {}, {}
        # While replaying, a copy is known by seat * 1000 + its place in the list (a commander
        # by seat * 1000 + 900 + its place); ids maps the copies lands were played from to the
        # ids of their "Land:" lines (101 and up, as Forge's lines have them).
        for seat, (commander, main) in enumerate(sections, 1):
            self.lists[seat] = {seat * 1000 + i: card for i, card in enumerate(main, 1)}
            self.commanders[seat] = {seat * 1000 + 900 + i: card for i, card in enumerate(commander, 1)}
            for zone, cards in (("Library", self.lists[seat]), ("Command", self.commanders[seat])):
                for key, card in cards.items():
                    self.names[key], self.zone[key], self.seat_of[key] = card, zone, seat
            self.library[seat] = list(self.lists[seat])
            rng.shuffle(self.library[seat])
            self.hand[seat] = []
        self.ids, self.out = {}, {}
        self.turn, self.active, self.phase = 0, "-", "-"
        self.at("opening")
        self.events += [("log",)] + [(kind, seat) for seat in (1, 2) for kind in ("deck", "commander")]
        for seat in (1, 2):
            for key in self.library[seat][:7]:
                self.move(key, "Hand")
        self.kept = {seat: len(self.hand[seat]) for seat in (1, 2)}    # 7, or all of a shorter [Main]
        self.at("kept")
        for seat in (1, 2):
            for key in [key for key in self.hand[seat] if self.names[key].startswith(OPENING)]:
                self.move(key, "Battlefield")           # an opening-hand action, at turn 0
        self.events += [("hand", "start", seat, list(self.hand[seat])) for seat in (1, 2)]
        for play in plays:
            self.turn, self.active, self.phase = play["turn"], play["seat"], "DRAW"
            self.at(("begin", self.turn))
            if self.turn > 1 and self.library[self.active]:
                self.move(self.library[self.active][0], "Hand")
            self.phase = "MAIN1"
            if play["land"]:
                self.at(("land", self.turn))
                self.land(play["land"], play["land_id"])
            if play["card"]:
                self.at(("cast", self.turn))
                casting = self.cast(play["card"])
                self.at(("resolve", self.turn))
                if casting:
                    self.move(*casting)
        self.at("end")
        self.events += [("hand", "end", seat, list(self.hand[seat])) for seat in (1, 2)]
        self.events += [("library", seat, len(self.library[seat]) + (broken and seat == 1)) for seat in (1, 2)]

    def at(self, hook):
        """The lines from here on go at hook."""
        self.events = self.out.setdefault(hook, [])

    def move(self, key, to, card=None):
        """One card's move to zone to (key: a copy; or the id of a card in neither list, named
        card, played from the hand)."""
        frm = self.zone.get(key, "Hand")
        seat = self.seat_of.get(key, self.active)
        if key in self.zone:
            if frm == "Library":
                self.library[seat].remove(key)
            elif frm == "Hand":
                self.hand[seat].remove(key)
            if to == "Hand":
                self.hand[seat].append(key)
            self.zone[key] = to
        self.events.append(("zone", self.turn, self.active, self.phase, frm, to, seat, key,
                            self.names.get(key, card)))

    def land(self, card, land_id):
        """Play a land named card from the hand (fetched there from the library if it has to be)."""
        held = [key for key in self.hand[self.active] if self.names[key] == card]
        if not held:
            held = [key for key in self.library[self.active] if self.names[key] == card][:1]
            if held:
                self.move(held[0], "Hand")              # a tutor
        if held:
            self.ids[held[0]] = land_id
            self.move(held[0], "Battlefield")
        else:
            self.move(land_id, "Battlefield", card)     # a basic beyond the deck's copies

    def cast(self, card):
        """Cast a card named card: (the copy, where it goes when it resolves), or None."""
        for key, name in self.commanders[self.active].items():
            if name == card:
                if self.zone[key] == "Battlefield":
                    self.move(key, "Command")           # it died: back to the command zone
                self.move(key, "Stack")
                return key, "Battlefield"
        copies = [key for key, name in self.lists[self.active].items() if name == card]
        held = [key for key in self.hand[self.active] if key in copies]
        if not held:
            held = [key for key in self.library[self.active] if key in copies][:1]
            if held:
                self.move(held[0], "Hand")              # a tutor
        if not held:
            held = [key for key in copies if self.zone[key] == "Graveyard"]    # flashback
        if not held:
            return None
        self.move(held[0], "Stack")
        return held[0], "Graveyard"

    def listed(self, keys):
        return ";".join(f"{self.ids.get(key, key)}={self.names[key]}" for key in keys)

    def line(self, event):
        kind = event[0]
        if kind == "zone":
            turn, active, phase, frm, to, seat, key, card = event[1:]
            return f"DL|zone|{turn}|{active}|{phase}|{frm}|{to}|{seat}|{self.ids.get(key, key)}|{card}"
        if kind == "log":
            return "DL|log|1"
        if kind in ("deck", "commander"):
            cards = (self.lists if kind == "deck" else self.commanders)[event[1]]
            if not cards and kind == "commander":       # DL|commander is for Commander games only
                return None
            return f"DL|{kind}|{event[1]}|{self.listed(sorted(cards, key=lambda k: self.ids.get(k, k)))}"
        if kind == "hand":
            when, seat, keys = event[1:]
            return f"DL|hand|{1 if when == 'start' else self.turn}|{when}|{seat}|{self.listed(keys)}"
        return f"DL|library|{self.turn}|end|{event[1]}|{event[2]}"

    def say(self, hook):
        for event in self.out.get(hook, ()):
            text = self.line(event)
            if text is not None:
                say("Information: " + text)


def _seeds():
    """decklab/lib/forge/seeds.py, loaded on its own (the package would pull in all of Deck Lab)."""
    path = Path(__file__).resolve().parents[2] / "lib" / "forge" / "seeds.py"
    spec = importlib.util.spec_from_file_location("decklab_fake_seeds", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def performance_mode():
    """Forge's PERFORMANCE_MODE preference as the user folder's forge.preferences sets it
    (APPDATA, as runner._prepare_user_dir points it), as DeckLabSim's perf= says."""
    prefs = Path(os.environ.get("APPDATA") or ".") / "Forge" / "preferences" / "forge.preferences"
    try:
        return "PERFORMANCE_MODE=true" in prefs.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False


FORGE_PROFILES = ("Cautious", "Default", "Experimental", "Reckless")      # Forge 2.0.15's res/ai
DECK_ORDER = "deck-order-1"             # wave 3's game patch: the library in .dck line order
PILOT_OPTION = "dlpilot"
# What this process was started with (main): the AI profile folder (-Ddecklab.aiprofiles), the
# pilot switches the jar holds (--pilot-switches), and the overrides hash of the user folder's
# custom/cards at start-up (as Startup.afterInitialize works it out once per JVM).
PROCESS = {"aiprofiles": None, "profiles": FORGE_PROFILES, "pilot_switches": (), "overrides": "none"}


def overrides_hash():
    """The hash of APPDATA's Forge/custom/cards (wave 2's engine._overrides form: each file's path
    from that folder with "/", a NUL, the SHA-256 of its bytes with CRLF made LF, and a newline,
    in path order; the SHA-256 of all that), or "none" when it holds no file."""
    folder = Path(os.environ.get("APPDATA") or ".") / "Forge" / "custom" / "cards"
    try:
        names = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
        text = "".join(name + "\0" + hashlib.sha256((folder / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                       + "\n" for name in names)
    except OSError:
        return "unreadable"
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if names else "none"


def start_process(argv):
    """The start-up DeckLabSim does once per JVM (Startup.afterInitialize): the AI profile
    folder, the pilot switches and the overrides hash, into PROCESS. Returns why the folder can't
    be used, or None."""
    folder = next((word.split("=", 1)[1] for word in argv if word.startswith(AI_PROFILES_FLAG)), None)
    switches = next((word[len(PILOT_SWITCHES):] for word in argv if word.startswith(PILOT_SWITCHES)), "")
    PROCESS["pilot_switches"] = tuple(filter(None, switches.split(",")))
    PROCESS["overrides"] = overrides_hash()
    if folder is None:
        return None
    PROCESS["aiprofiles"] = folder
    try:
        names = sorted(p.stem for p in Path(folder).iterdir() if p.suffix == ".ai")
    except OSError as e:
        return f"the AI profile folder {folder} can't be read ({type(e).__name__})"
    PROCESS["profiles"] = tuple(sorted(set(FORGE_PROFILES) | set(names)))
    return None


def pilot_problem(opts, v2, game_patches):
    """Why -dlpilot can't be read (Request.parse's checks), or None."""
    if PILOT_OPTION not in opts:
        return None
    values = opts[PILOT_OPTION]
    if len(values) != 2:
        return "Error: -dlpilot needs each seat's switches (a + between ids, or - for none)"
    if v2 is None:
        return "Error: -dlpilot needs -dlgame"
    for value in values:
        for switch in ([] if value == "-" else value.split("+")):
            if switch not in PROCESS["pilot_switches"]:
                return f"Error: -dlpilot: no switch called {switch}"
            if switch == "team-pump-1" and not game_patches:
                return "Error: team-pump-1 needs game patches on"
    return None


def first_draws(sections, log_seed):
    """Each seat's library's first 10 card names (the kept hand and its first three draws), as
    CardLog shuffles it from log_seed: [seat 1's, seat 2's]."""
    rng = random.Random(log_seed)
    out = []
    for _, main_ in sections:
        order = list(range(len(main_)))
        rng.shuffle(order)
        out.append([main_[i] for i in order[:10]])
    return out


def engine_line(decks, card_log, game_patches, v2, how, patch_ids="", profiles=("Default", "Default"),
                pilots=("-", "-")):
    """DeckLabSim's DLENGINE line (GameLoop.engineLine): each fake deck averages 2 mana unless
    FAKE_FORGE's avgcmc=a,b says otherwise; autoprofile by Forge's rule (a name holding
    "Control", or an average over 3); gamepatchids= is patch_ids (--game-patch-ids). Wave 3's
    fields follow (the module docstring)."""
    loop = (f"v=2|seeds=game|base={v2['base']}|stream={v2['stream']}|first={v2['first']}" if v2
            else "v=1|seeds=batch")
    averages = [int(x) for x in how["avgcmc"][0]] if "avgcmc" in how else [2, 2]
    flags = ["1" if "Control" in name or average > 3 else "0" for (name, _), average in zip(decks, averages)]
    order = bool(game_patches and v2 and DECK_ORDER in patch_ids.split(","))
    return (f"DLENGINE|{loop}|perf={'true' if performance_mode() else 'false'}|cardlog={'on' if card_log else 'off'}"
            f"|gamepatches={'on' if game_patches else 'off'}|gamepatchids={patch_ids}"
            f"|autoprofile={','.join(flags)}|avgcmc={','.join(str(a) for a in averages)}"
            f"|deckorder={'1,1' if order else '0,0'}|ai={','.join(profiles)}|pilots={','.join(pilots)}"
            f"|aiprofiles={'dl' if PROCESS['aiprofiles'] else 'forge'}|overrides={PROCESS['overrides']}"
            f"|loadseed={1 if order else 0}")


def simulate(args, decklab=False, game_patches=True, between=None, patch_ids=""):
    """One sim run's output for args (from "sim" on): plain Forge, or DeckLabSim with
    decklab (the DLENGINE line, the card log unless -dlnocardlog, and -dlgame). between(game)
    is asked before every game but the first (serve mode's cancel): False stops there.
    Returns (status, games played, detail): status "done", "cancelled", "recycle" (between
    was given, so it's serve mode, and a game hit the clock, had an AI timeout Java saw or
    crashed: detail clock, ai_timeout or crash; serve mode stops after it), "crash" (crash#G),
    "throw" (throw#G: detail the error) or "error"."""
    opts = options(args[1:])
    seed = int(opts.get("s", ["0"])[0])
    games = int(opts.get("n", ["1"])[0])
    fmt = opts.get("f", ["Constructed"])[0]
    folder = Path(opts["D"][0])
    v2 = None
    if decklab and "dlgame" in opts:
        stream, first_game = opts["dlgame"]
        v2 = {"base": seed, "stream": stream, "first": int(first_game), "number": int(stream, 16)}
    card_log = decklab and "dlnocardlog" not in opts
    if decklab:
        problem = pilot_problem(opts, v2, game_patches)
        if problem:
            say(problem)
            return "error", 0, "the request's arguments can't be read"
    profiles = (opts.get("a") or ["Default", "Default"])[:2]
    pilots = opts.get(PILOT_OPTION) or ["-", "-"]
    how = modes(seed)
    if os.environ.get("FAKE_FORGE_LOG"):
        log_start(os.environ["FAKE_FORGE_LOG"], seed)
    if "slowstart" in how and between is None:
        time.sleep(how["slowstart"][0])
    if 0 in how.get("hang", []) and v2 is None:
        time.sleep(3600)
    unknown = next((name for name in profiles if name not in PROCESS["profiles"]), None)
    if unknown is not None:
        say(f"Unknown AI profile - {unknown}. Available profiles: {', '.join(PROCESS['profiles'])}")
        return "error", 0, f"Unknown AI profile - {unknown}"
    if "noload" in how:
        say(f"No deck found in {folder}")
        say(f"Could not load deck - {opts['d'][0]}, match cannot start")
        return "error", 0, f"Could not load deck - {opts['d'][0]}"
    decks = [read_deck(folder / name) for name in opts["d"]]
    wanted = card_log or "cardwins" in how
    sections = [deck_sections(folder / name) for name in opts["d"]] if wanted else None
    slow = sum(ms for name, ms in how.get("slowcard", []) if any(card == name for _, deck in decks for _, card in deck))
    players = [f"Ai({i})-{name}" for i, (name, _) in enumerate(decks, 1)]
    if "unsupported" in how:
        say('An unsupported card was requested: "Totally Fake Card" from "null".')
        say("Forge could not find this card in the Database. Any chance you might have mistyped the card name?")
    count = WORDS[games] + ("  games" if games > 1 else " game") if games <= 20 else f"{games} games"
    if decklab:
        say(engine_line(decks, card_log, game_patches, v2, how, patch_ids, profiles, pilots))
    say(f"{players[0]} [{profiles[0]}] vs {players[1]} [{profiles[1]}] - {count} of {fmt} seed {seed}")
    say("WARNING: A terminally deprecated method in sun.misc.Unsafe has been called")
    score = [0, 0]
    first = random.Random(seed).choice([1, 2])
    recycle = None          # serve mode: why the worker can't play on after the game before
    for game in range(1, games + 1):
        if v2:
            score = [0, 0]      # v2: every game is a Match of its own, as in DeckLabSim
        # A failure mode's #G is the game's number: in its batch from 1 (v1), or the result's
        # game number from 0 (v2: first + the game's place in the request).
        number = v2["first"] + game - 1 if v2 else game
        if game > 1 and between is not None and (recycle or not between(game)):
            return ("recycle" if recycle else "cancelled"), game - 1, recycle or ""
        if number in how.get("crash", []):
            say('Exception in thread "main" java.lang.OutOfMemoryError: Java heap space')
            say("\tat forge.game.Match.startGame(Match.java:92)")
            return "crash", game - 1, ""
        if number in how.get("throw", []):
            error = "java.lang.IllegalStateException: Forge's state can't be reset (the fake was asked to throw)"
            say(error)
            say("\tat decklab.WarmState.reset(WarmState.java:74)")
            return "throw", game - 1, error
        if v2:
            # Game g alone: its own seed, its own coin flip (a new Match), whatever came before it.
            game_seed = SEEDS.game_seed(seed, v2["number"], number)
            rng = random.Random(game_seed)
            first = rng.choice([1, 2])
            log_seed = f"card log {game_seed}"
        else:
            rng = random.Random(seed * 100_003 + game)
            log_seed = f"card log {seed} {game}"
        log_rng = random.Random(log_seed)
        turns = rng.randint(8, 16)
        plays = plan_turns(rng, decks, first, turns)
        log = CardLog(sections, plays, log_rng, number in how.get("badcardlog", [])) if card_log else None
        timed_out = number in how.get("timeout", [])
        threw = number in how.get("exception", [])
        if between is not None:
            # As DeckLabServe.recycleReason: the clock first, then an AI timeout Java saw, then a crash.
            recycle = ("clock" if timed_out else "ai_timeout" if number in how.get("aitimeout", [])
                       else "crash" if threw else None)
        if timed_out:
            say("Stopping slow match as draw")
            say("java.lang.InterruptedException")
            say("\tat forge.ai.AiController.chooseSpellAbilityToPlayFromList(AiController.java:1686)")
        if threw:
            say("java.lang.NullPointerException: Cannot invoke \"forge.game.card.Card.getName()\"")
            say("\tat forge.game.GameAction.checkStateEffects(GameAction.java:1540)")
        if number in how.get("aitimeout", []) or number in how.get("aitimeoutunseen", []):
            for _ in range(2):
                say("java.util.concurrent.TimeoutException")
                say("AI eval thread at timeout:")
                say("\tat forge.game.combat.Combat.getBlockers(Combat.java:429)")
        if log:
            log.say("opening")
        for seat in (first, 3 - first):
            say(f"Mulligan: {players[seat - 1]} has kept a hand of {log.kept[seat] if log else 7} cards")
        if log:
            log.say("kept")
        for play in plays:
            player = players[play["seat"] - 1]
            say(f"Turn: Turn {play['turn']} ({player})")
            say(f"Phase: {player}'s Untap step")
            if log:
                log.say(("begin", play["turn"]))
            if play["land"]:
                if log:
                    log.say(("land", play["turn"]))
                say(f"Land: {player} played {play['land']} ({play['land_id']})")
            if play["card"]:
                if log:
                    log.say(("cast", play["turn"]))
                say(f"Add To Stack: {player} cast {play['card']}{play['target']}")
                say(f"Resolve Stack: {play['card']} - does something")
                if log:
                    log.say(("resolve", play["turn"]))
            if play["trigger"]:
                say(f"Add To Stack: {player} triggered Something Else")
        if number in how.get("hang", []):
            time.sleep(3600)
        if "delay" in how:
            time.sleep(how["delay"][0])
        if slow:
            time.sleep(slow / 1000)
        winner = first if rng.random() < 0.55 else 3 - first
        if "cardwins" in how:
            early = first_draws(sections, log_seed)
            holders = [seat for seat in (1, 2) if any(name in early[seat - 1] for name in how["cardwins"])]
            if len(holders) == 1:
                winner = holders[0]
        say(f"Game Outcome: Match Duration 0m : 0{rng.randint(0, 9)}s")
        say(f"Game Outcome: Turn {math.ceil(turns / 2)}")
        if timed_out or threw:
            for seat in (1, 2):
                say(f"Game Outcome: {players[seat - 1]} has won because all opponents have lost")
            winner = 2      # Forge names an arbitrary player
        else:
            loser = 3 - winner
            reason = "life total reached 0" if rng.random() < 0.9 else "trying to draw cards from empty library"
            say(f"Game Outcome: {players[winner - 1]} has won because all opponents have lost")
            if reason.startswith("trying"):
                say(f"Game Outcome: {players[loser - 1]} has lost {reason}")
            else:
                say(f"Game Outcome: {players[loser - 1]} has lost because {reason}")
        score[winner - 1] += 1
        say(f"Match Result: {players[0]}: {score[0]} {players[1]}: {score[1]} ")
        if log:
            log.say("end")
        say()
        say(f"Game Result: Game {game} ended in {rng.randint(300, 3000) + round(slow)} ms. "
            f"{players[winner - 1]} has won!")
        say()
        # The next game: the first player (in seat order) who didn't win starts; deck 1 after a stop.
        first = 1 if timed_out or threw else 3 - winner
    if recycle:
        return "recycle", games, recycle
    return "done", games, ""


def start_up():
    say("Error handling registered!")
    say("Language 'en-US' loaded successfully.")
    say("Lazy card database: indexed 35240 card names from 33980 files in 510 ms")


def serve(game_patches=True, patch_ids="", startup_problem=None):
    """DeckLabSim serve (java/decklab/DeckLabServe.java): its protocol, with sim's games
    for each request (simulate). FAKE_FORGE's slowstart waits before the ready line,
    "servefail" makes it fail to start (DLSERVE|fail, exit code 3), and "badargs" makes
    every request's arguments unreadable. startup_problem (start_process's: an AI profile
    folder that can't be read) fails the start the same way."""
    how = modes(None)
    start_up()
    if "slowstart" in how:
        time.sleep(how["slowstart"][0])
    if "servefail" in how:
        say("DLSERVE|fail|Forge's state can't be reset (the fake was asked to fail)")
        return 3
    if startup_problem:
        say(f"DLSERVE|fail|{startup_problem}")
        return 3
    commands = queue.Queue()
    cancelled, leaving = set(), threading.Event()

    def read():
        for raw in sys.stdin:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            fields = line.split("\t")
            if fields[0] == "cancel":
                if len(fields) == 2 and REQUEST_ID.fullmatch(fields[1]):
                    cancelled.add(fields[1])
                else:
                    say(f"DLSERVE|bad|{line}")
                continue
            if fields[0] == "quit":
                leaving.set()
            commands.put(fields)
        leaving.set()
        commands.put(["eof"])

    threading.Thread(target=read, daemon=True).start()
    say(f"DLSERVE|ready|1|{os.getpid()}|0,0,0,0,0,-2,0")
    while True:
        fields = commands.get()
        if fields[0] in ("quit", "eof"):
            say(f"DLSERVE|bye|{fields[0]}")
            return 0
        if fields[0] != "play" or len(fields) < 4 or not REQUEST_ID.fullmatch(fields[1]) or fields[2] != "sim":
            say(f"DLSERVE|bad|{' '.join(fields)}")
            continue
        request_id, t0 = fields[1], time.monotonic()
        say(f"DLSERVE|begin|{request_id}")
        stop = lambda: leaving.is_set() or request_id in cancelled     # noqa: E731
        if stop():
            status, games, detail = "cancelled", 0, ""
        elif "badargs" in how:
            say("Simulation mode")
            say('Error: java.lang.NumberFormatException: For input string: "x"')
            status, games, detail = "error", 0, "the request's arguments can't be read"
        else:
            say("Simulation mode")
            status, games, detail = simulate(fields[2:], True, game_patches, lambda game: not stop(), patch_ids)
        if status == "crash":
            return 1                # no end line: the worker died part way
        cancelled.discard(request_id)
        escaped = status == "throw"         # a Java error escaped (throw#G): the worker ends
        status = "error" if escaped else status
        detail = detail or "heap_mb=64"     # done or cancelled: the heap after the latest GC
        say(f"DLSERVE|end|{request_id}|{status}|{games}|{round((time.monotonic() - t0) * 1000)}|{detail}")
        if status == "recycle":
            say("DLSERVE|bye|recycle")
            return 0
        if escaped:
            say("DLSERVE|bye|error")
            return 1


PATCH_IDS = "--game-patch-ids="
PILOT_SWITCHES = "--pilot-switches="
AI_PROFILES_FLAG = "-Ddecklab.aiprofiles="
GAME_PATCHES_OFF = "-Ddecklab.gamePatches=off"      # simjar.GAME_PATCHES_OFF, as --game-patches-off


def main(argv):
    """sim [--card-log] [--game-patches-off] [--game-patch-ids=<ids>] [--pilot-switches=<ids>]
    [-Ddecklab.aiprofiles=<dir>] ...: one batch, as Forge's sim or (--card-log) DeckLabSim's;
    serve [the same flags]: a warm worker (serve())."""
    game_patches = "--game-patches-off" not in argv and GAME_PATCHES_OFF not in argv
    patch_ids = next((word[len(PATCH_IDS):] for word in argv if word.startswith(PATCH_IDS)), "")
    problem = start_process(argv)
    words = [word for word in argv if word not in ("--card-log", "--game-patches-off", GAME_PATCHES_OFF)
             and not word.startswith((PATCH_IDS, PILOT_SWITCHES, AI_PROFILES_FLAG))]
    if words and words[0] == "serve":
        return serve(game_patches, patch_ids, problem)
    start_up()
    if problem:
        say(f"Error: {problem}")
        return 3
    say("Simulation mode")
    status, _, _ = simulate(words, "--card-log" in argv, game_patches, patch_ids=patch_ids)
    return 1 if status in ("crash", "throw") else 0


SEEDS = _seeds()
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
