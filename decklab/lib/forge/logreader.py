"""Reading Forge's output: the lines that matter, and LogReader, which turns one Forge
process's output into game summaries, each side's casts and land plays and, with the
card log, the batch's per-card tallies (cardlog.py). How a game is classified, and when
a batch fails, is in the package docstring's "Reading Forge's output"
(decklab/lib/forge/__init__.py)."""
import re
import threading

from . import cardlog, common
from .common import norm


# ============================================================ reading Forge's output

# "Ai(1)-3f2a9c1b7d4e [Default] vs Ai(2)-9c0d... [Default] - 200 games of Constructed seed 7"
# (the count is sometimes spelled out, with a double space: "fifty  games")
RE_HEADER = re.compile(r"^(Ai\(1\)-.*) - .+? games? of (\w+)(?: seed (-?\d+))?\s*$")
RE_RESULT_WIN = re.compile(r"^Game Result: Game (\d+) ended in (\d+) ms\. Ai\((\d+)\)-.* has won!\s*$")
RE_RESULT_DRAW = re.compile(r"^Game Result: Game (\d+) ended in a Draw! Took (\d+) ms\.\s*$")
RE_ROUNDS = re.compile(r"^Game Outcome: Turn (\d+)\s*$")
# Forge's PlayerOutcome strings: "has won because all opponents have lost", "has lost because
# life total reached 0", "has lost trying to draw cards from empty library", "has conceded"...
# The player name is matched lazily so the first " has won/lost/conceded" is the verb.
RE_OUTCOME = re.compile(r"^Game Outcome: Ai\((\d+)\)-.*? has (won|lost|conceded)\b(?: because)? ?(.*?)\.?\s*$")
RE_TURN = re.compile(r"^Turn: Turn (\d+) \(Ai\((\d+)\)-")
RE_CAST = re.compile(r"^Add To Stack: Ai\((\d+)\)-.*? cast (.+?)(?: targeting .*)?\s*$")
RE_LAND = re.compile(r"^Land: Ai\((\d+)\)-.*? played (.+?) \((\d+)\)\s*$")      # seat, card, card id
# "Mulligan: Ai(1)-3f2a9c1b7d4e has kept a hand of 6 cards" (read only with the card log: its
# kept-hand check, and the moves after it at turn 0 are opening-hand actions)
RE_KEPT = re.compile(r"^Mulligan: Ai\((\d+)\)-.* has kept a hand of (\d+) cards?\s*$")
# "Add To Stack: Felling Blow (11) - [Couldn't add to stack, failed to target] - Put a +1/+1 ..."
# (card id): a cast the AI began and couldn't finish, so not a cast (read only with the card
# log; RE_CAST doesn't match it). Forge's copy on its error stream has no "Add To Stack: ".
RE_NOT_CAST = re.compile(r"^Add To Stack: .*? \((\d+)\) - \[Couldn't add to stack")
RE_UNSUPPORTED = re.compile(r'^An unsupported card was requested: "(.*)" from "(.*)"\.')
RE_NOLOAD = re.compile(r"^(Could not load deck - .*|No deck found in .*|Unknown AI profile - .*)$")
RE_EXC = re.compile(r"^(?:Exception in thread .*|[\w.$]+(?:Exception|Error)(?::.*)?)\s*$")
# The stack traces that come with an AI decision timeout (TimeoutException) and a clock
# stop (InterruptedException, just before or after its line): not a game error. They're
# the only ones in Milestone 0's 326 logs.
EXPECTED_EXC = ("java.util.concurrent.TimeoutException", "java.lang.InterruptedException")
AI_TIMEOUT = "AI eval thread at timeout"
SLOW_STOP = "Stopping slow match as draw"
# DeckLabSim's line saying how a batch's (or a serve request's) games are played, before
# Forge's header line (java/decklab/GameLoop.java engineLine): "DLENGINE|v=1|seeds=batch|
# perf=false|cardlog=on|gamepatches=on|autoprofile=0,0|avgcmc=2,3"; v2 adds base, stream and
# first. Its fields are key=value, separated by "|"; per-seat values are "<seat 1>,<seat 2>"
# (SEAT_FIELDS). Wave 2's contract "The DLENGINE line" has every field; wave 3 adds deckorder,
# ai and pilots (per seat), aiprofiles, overrides and loadseed (sim-wave3-contract.md section 3.5).
ENGINE_PREFIX = "DLENGINE|"
SEAT_FIELDS = ("autoprofile", "avgcmc", "deckorder", "ai", "pilots")


def engine_fields(line):
    """A DLENGINE line's fields: {key: value} (text), a field without "=" left out."""
    fields = {}
    for part in line.rstrip("\r\n")[len(ENGINE_PREFIX):].split("|"):
        name, sep, value = part.partition("=")
        if sep and name:
            fields[name] = value
    return fields


class LogReader:
    """Reads one Forge process's output, a line at a time (feed), into game summaries.

    deck1 is the side (0 or 1) playing as Forge's deck 1, "Ai(1)"; names[side] maps a
    logged card name's key to the list's .dck name (_log_names). Afterwards: header
    (seen?), games [{"w", "r", "first", "rounds", "turns", "ms", "loss", "ai_to"}] with
    sides for w and first, casts [{card: [casts, games cast in]}] and lands
    [{card: games played}] per side, unsupported (names) and load_errors (lines).
    A game only counts once its "Game Result" line is read, so a stopped process's
    games are the ones it finished; close() makes it read nothing more.
    engine is the batch's DLENGINE line's fields (engine_fields; {} without one: plain
    Forge prints none), and engine_by_side() the per-seat ones by side.
    With card_log (Forge run as DeckLabSim), cards is the batch's card record
    (cardlog.new_record(): every finished game is in its "games" or "bad", so a stopped
    batch's is its finished games'), and card_problems the first few reasons a game's
    card data didn't count, as (game number, reason). Without it, cards is None and the
    DL lines are passed over; they never change games, casts or lands either way."""

    PROBLEMS_KEPT = 20          # card_problems kept per batch (the rest are only counted)

    def __init__(self, deck1=0, names=None, card_log=False):
        self.deck1 = deck1
        self.names = names or [{}, {}]
        self.header = False
        self.games = []
        self.casts = [{}, {}]
        self.lands = [{}, {}]
        self.unsupported = set()
        self.load_errors = []
        self.closed = False
        self.engine = {}
        self.cards = cardlog.new_record() if card_log else None
        self.card_problems = []
        self._dl_names = [{}, {}]       # side -> {logged name: .dck name}, as _card maps them
        self._lock = threading.Lock()
        self._new_game()

    def close(self):
        """Read nothing more: games, casts and lands stay as they are now (a killed
        process's reader thread may still be going)."""
        with self._lock:
            self.closed = True

    def _new_game(self):
        self._game = {"first": None, "turns": None, "rounds": None, "won": {}, "lost": {},
                      "timeout": False, "exception": False, "ai_to": 0,
                      "casts": [{}, {}], "lands": [set(), set()]}
        self._cards = cardlog.Game() if self.cards is not None else None

    def side(self, seat):
        """The side playing in Forge's seat 1 or 2."""
        return self.deck1 if seat == 1 else 1 - self.deck1

    def engine_by_side(self):
        """[side 0's, side 1's] DLENGINE fields: SEAT_FIELDS' values ("<seat 1>,<seat 2>")
        split by seat and put on that seat's side, e.g. [{"autoprofile": "0", "avgcmc": "2"},
        {"autoprofile": "1", "avgcmc": "4"}]; the other fields aren't a side's. [{}, {}]
        without a DLENGINE line."""
        out = [{}, {}]
        for name in SEAT_FIELDS:
            values = self.engine.get(name, "").split(",")
            if len(values) == 2:
                for seat, value in enumerate(values, 1):
                    out[self.side(seat)][name] = value
        return out

    def _card(self, side, name):
        name = name.strip()
        return self.names[side].get(norm(name), name)

    def _dl_card(self, side, name):
        """_card for the card log, remembered: every game logs the same deck lists."""
        known = self._dl_names[side]
        if name not in known:
            known[name] = self._card(side, name)
        return known[name]

    def feed(self, line):
        """Read one line. Returns "header" or "game" when that line completes one, else None."""
        with self._lock:
            return None if self.closed else self._feed(line)

    def _feed(self, line):
        line = line.rstrip("\r\n")
        cur = self._game
        if not self.header:
            if line.startswith(ENGINE_PREFIX):
                self.engine = engine_fields(line)
                return None
            if RE_HEADER.match(line):
                self.header = True
                return "header"
        m = RE_UNSUPPORTED.match(line)
        if m:
            self.unsupported.add(m[1])
            return None
        if RE_NOLOAD.match(line):
            self.load_errors.append(line)
            return None
        if not self.header:
            return None
        if line.startswith(cardlog.PREFIX):
            if self._cards is not None:
                self._cards.line(line[len(cardlog.PRINTED):])
            return None
        if line.startswith(SLOW_STOP):
            cur["timeout"] = True
            return None
        if line.startswith(AI_TIMEOUT):
            cur["ai_to"] += 1
            return None
        if RE_EXC.match(line):
            if line.split(":", 1)[0].strip() not in EXPECTED_EXC:
                cur["exception"] = True
            return None
        m = RE_CAST.match(line)
        if m:
            side = self.side(int(m[1]))
            card = self._card(side, m[2])
            cur["casts"][side][card] = cur["casts"][side].get(card, 0) + 1
            if self._cards is not None:
                self._cards.cast()
            return None
        m = RE_LAND.match(line)
        if m:
            side = self.side(int(m[1]))
            cur["lands"][side].add(self._card(side, m[2]))
            if self._cards is not None:
                self._cards.land(int(m[3]), cur["turns"] or 0)
            return None
        m = RE_TURN.match(line)
        if m:
            cur["turns"] = int(m[1])
            if m[1] == "1" and cur["first"] is None:
                cur["first"] = int(m[2])
            if self._cards is not None:
                self._cards.turn(int(m[1]), int(m[2]))
            return None
        m = RE_ROUNDS.match(line)
        if m:
            cur["rounds"] = int(m[1])
            return None
        m = RE_OUTCOME.match(line)
        if m:
            verb, reason = m[2], m[3]
            if verb == "conceded":
                verb, reason = "lost", "conceded"
            cur["won" if verb == "won" else "lost"][int(m[1])] = reason
            return None
        m = RE_RESULT_WIN.match(line) or RE_RESULT_DRAW.match(line)
        if m:
            self._finish(m)
            return "game"
        if self._cards is not None:
            m = RE_KEPT.match(line)
            if m:
                self._cards.kept_hand(int(m[1]), int(m[2]))
                return None
            m = RE_NOT_CAST.match(line)
            if m:
                self._cards.not_cast(int(m[1]))
        return None

    def _finish(self, m):
        """A "Game Result" line: classify the game (see the package docstring) and count it."""
        cur = self._game
        reported = int(m[3]) if m.re is RE_RESULT_WIN else None
        if cur["timeout"]:
            result, winner = "timeout", None
        elif reported is not None and len(cur["won"]) == 1 and reported in cur["won"]:
            result, winner = "win", reported
        elif cur["exception"]:
            result, winner = "error", None
        else:
            result, winner = "draw", None
        loss = cur["lost"].get(3 - winner) if winner else None
        self.games.append({
            "w": self.side(winner) if winner else None, "r": result,
            "first": self.side(cur["first"]) if cur["first"] else None,
            "rounds": cur["rounds"], "turns": cur["turns"], "ms": int(m[2]), "loss": loss,
            "ai_to": cur["ai_to"],
        })
        for side in (0, 1):
            for card, n in cur["casts"][side].items():
                total = self.casts[side].setdefault(card, [0, 0])
                total[0] += n
                total[1] += 1
            for card in cur["lands"][side]:
                self.lands[side][card] = self.lands[side].get(card, 0) + 1
        if self.cards is not None:
            self._finish_cards(self.games[-1])
        self._new_game()

    def _finish_cards(self, game):
        """Add the game that just finished to the card record, or count it as bad."""
        try:
            problem = cardlog.add(self.cards, self._cards, game["w"], game["first"],
                                  self.side, self._dl_card)
        except Exception as e:      # a bug here mustn't cost the batch its games
            common._log(f"Game {len(self.games)}'s card log couldn't be read: {e!r}")
            self.cards["bad"] += 1
            problem = "the card log couldn't be read"
        if problem is not None and len(self.card_problems) < self.PROBLEMS_KEPT:
            self.card_problems.append((len(self.games), problem))

    def failure(self, games_asked, exit_code):
        """Why this batch doesn't count, in plain words, or None if it does."""
        if self.load_errors:
            return "Forge couldn't load one of the decks"
        if self.unsupported:
            return "Forge doesn't know these cards: " + ", ".join(sorted(self.unsupported))
        if exit_code not in (0, None):
            return f"Forge stopped with an error (exit code {exit_code})"
        if len(self.games) < games_asked:
            return f"Forge played only {len(self.games)} of {games_asked} games"
        return None
