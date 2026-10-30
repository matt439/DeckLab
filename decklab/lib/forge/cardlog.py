"""The card log (Milestone 8): one game's DL| lines, the checks that make its card data
count, and a batch's per-card tallies.

DeckLabSim (java/decklab/DeckLabSim.java) is Forge's sim with one event listener added,
which logs every card move as a game-log line; Forge prints them in game order among its
own lines, as "Information: DL|...". LogReader hands each game's DL lines to a Game, with
the few Forge lines it needs (the kept hand's size, land plays, turns, casts and failed
casts), and at the game's "Game Result" line calls add(), which checks the game and adds
what each card did to the batch's record (new_record()); the runner stores that record in
the batch as "cards".

The lines (format version 1). Seats are Forge's 1 and 2 ("Ai(1)-..."), a turn is
Forge's global turn (0 while the opening hands are drawn and mulliganed), and a name is
the one the card had in its owner's library (the front face):
    DL|log|1                                    the first DL line of every game
    DL|deck|<seat>|<id>=<name>;...              the seat's library and hand, ids ascending,
                                                before any card moves to a hand
    DL|commander|<seat>|<id>=<name>;...         Commander games: the seat's command zone
    DL|zone|<turn>|<active seat>|<phase>|<from>|<to>|<owner seat>|<id>|<name>
                                                every card move; zones are Forge's ZoneType
                                                names (Library, Hand, Stack...) or "-"
    DL|hand|1|start|<seat>|<id>=<name>;...      the hand as turn 1 begins: the kept hand, less any card
                                                an opening-hand action moved (check 4)
    DL|hand|<turn>|end|<seat>|<id>=<name>;...   the hand after the game (may be empty)
    DL|library|<turn>|end|<seat>|<count>        the library's size after the game
    DL|error|<text>                             the end-of-game snapshot failed
Other DL lines are left alone (the replay check below still catches a move they'd hide).

What counts, per game, side and card. A card is a .dck name (LogReader maps logged names
to the list's, as it does casts); its copies are told apart by id. Ids that are in neither
seat's DL|deck or DL|commander (tokens, effects) are left out of the rows; tokens are
tallied apart (below).
    drawn copy      in the kept hand (DL|hand|1|start, and any copy an opening-hand action
                    moved out of it: check 4), or moved to Hand from any zone at turn 1 or
                    later (tutors and returns count; cards drawn for a mulligan and put back
                    don't)
    drawn_games     1 when any copy was drawn; drawn_wins 1 when also the side won
    copies_drawn    the drawn copies
    used            drawn copies that moved Hand -> Stack or Hand -> Battlefield (a land drop)
                    at least once; used_round_sum adds the round of each one's first such
                    move (round_of: the player's own turn number; round 1 for an opening-hand
                    action at turn 0, a Leyline put onto the battlefield). A failed cast
                    (below) isn't a use
    stuck           drawn copies in the hand after the game: a copy cast, bounced and held
                    is both used and stuck, and a discarded one is neither
    discarded       drawn copies that moved Hand -> Graveyard (a discard, cycling...)
    other_casts     moves to Stack from any zone but Hand and Command, of any copy
                    (flashback, an adventure's creature cast from exile...)
    early_games     1 when any copy was in the hand by the side's own 3rd turn: in the kept
                    hand (as drawn counts it), or moved to Hand from any zone at a turn from 1
                    up to the turn on which the side's 3rd own turn began (the side's 3rd Turn
                    line: Turn lines, not round_of(), so an extra turn counts as the turn it
                    is); in a game that ended before that turn began, any drawn copy.
                    early_wins 1 when also the side won. Unlike drawn_games, it doesn't lean
                    with game length: a long game draws more cards, but not by turn 3
                    (sim-investigation/w1/m8/notes.md)
    commander       a DL|commander card (never in rows): casts (moves to Stack, from any
                    zone), cast_games and cast_wins (cast at least once, and won), and
                    first_round_sum (the round of its first cast)
A token's peak (E7-S08, since 2026-10-29): a token is an id in neither seat's lists whose
move is from "-" (DeckLabSim's "created"; an id first seen moving from a real zone, such as a
card a wish brings from outside the game, isn't one). Its side is its owner seat's (the
DL|zone line's), and its name is its logged one as Forge prints it ("Beast Token"; a token
copy of a card has the card's name), kept from its creation. Per game, side and name, the
peak is the most of that token on the battlefield at once, replaying its moves to and from
the Battlefield up to the end lines (as the checks replay the cards'); a token that never
reached the battlefield (a copied spell, an effect in the Command zone) has none. A peak
over PEAK_CAP counts as PEAK_CAP, so a runaway combo can't grow the record without end.
Used, stuck and discarded only count drawn copies, so none is ever more than copies_drawn;
a game's early copy is a drawn one, so early_games is never more than drawn_games.

A failed cast: Forge's AI can begin casting a spell and then find it can't target. The
card has already moved to the Stack (its DL|zone line); then, instead of "Add To Stack:
Ai(n)-... cast <name>", Forge prints "Add To Stack: <name> (<id>) - [Couldn't add to
stack, failed to target] - ..." and leaves the card there: Forge 2.0.15 doesn't move it
again that game, so it's in no hand at the end (and the checks pass). That move to the
Stack isn't a cast, so Game.not_cast() takes back what it counted: the copy's use and its
round when that was its first use, an other cast, or a commander's cast (and its round
when it was the first). A copy that moves to the Stack again later and is cast counts as
usual. A copy whose only cast failed is drawn, and neither used nor stuck. Forge also
prints the failed line on its error stream, without "Add To Stack: ", while the game is
played (so before that game's lines): that copy is passed over.

A game's card data counts only when every check passes; otherwise add() counts it in
"bad" and none of it (either side) is used:
    1. its first DL line is DL|log|1 (another version can't be read), and no DL|error came;
    2. seats 1 and 2 (no others) each have DL|deck, DL|hand ... start, DL|hand ... end and
       DL|library ... end, once. A second start hand, or a second "has kept a hand" line
       (below), for a seat means the game was restarted (Karn Liberated does that), and
       the card log doesn't follow a restart: that game doesn't count, with its own reason;
    3. replaying every DL|zone move from "DL|deck cards in the Library, DL|commander cards
       in the Command zone" ends with each seat's end hand (the same ids) and library size.
       Only the moves before the end-of-game lines are replayed (and counted above): a
       game stopped by the clock can still be moving cards while the snapshot is taken,
       and a move logged after it came after it. A move logged among the end lines is
       left out too, and can leave them out of step with each other: that game then
       doesn't count;
    4. each seat's kept hand is as big as Forge's "Mulligan: ... has kept a hand of N
       cards" says, when Forge said it. The kept hand is the start hand plus the copies
       that left the seat's hand at turn 0 after that line: opening-hand actions, which
       Forge 2.0.15 takes after every player has kept and before turn 1 begins
       (GameAction.runOpeningHandActions puts a Leyline or Gemstone Caverns onto the
       battlefield, and Gemstone Caverns exiles a card from the hand). Those copies count
       as drawn, and as used in round 1 when they went to the Battlefield or Stack. A move
       out of the hand at turn 0 before the seat's kept line is a mulligan's and counts
       for nothing (without the line, every such move is taken as a mulligan's);
    5. every Forge "Land: ... played X (id)" line has a move of that id to the Battlefield
       on that turn, from any zone: a land can be played from the hand, or from exile
       (impulse draw), the top of the library (Courser of Kruphix) or the graveyard
       (Crucible of Worlds). Only a land played from the hand counts as used.

The batch record (a batch played without the card log has none):
    {"v": RECORD_VERSION, "games": G, "bad": B, "wins": [w0, w1], "first": [f0, f1],
     "rows": [{name: [drawn_games, drawn_wins, copies_drawn, used, stuck, used_round_sum,
                      other_casts, discarded, early_games, early_wins]}, {...side 1}],
     "commander": [{name: [cast_games, cast_wins, casts, first_round_sum]}, {...side 1}],
     "tokens": [{logged name: [n1, n2, ...]}, {...side 1}]}
A token's list counts its peaks over the G games: nk is the games whose peak was k (the
last, k = PEAK_CAP, also those above it); it ends with a non-zero number, and the games
without the token (G less their sum) had a peak of 0. A record without "tokens" (one kept
before 2026-10-29, or merged with one) didn't tally them: that isn't "no tokens".
G and B are the batch's games whose card log passed and failed the checks (G + B is every
game it finished); wins and first are each side's wins and games played first in those G
games (a timeout, draw or error is nobody's win). A card with nothing to count in any of
them has no row. Sides are the result's, never Forge's seats. The versions:
    1   counted a failed cast as a cast: saved.py leaves its records out ("old")
    2   since 2026-10-01: the first 8 numbers of a row
    3   since 2026-10-03 (wave 2): early_games and early_wins added; saved.py pools the 8
        numbers both share over versions 2 and 3, and the early ones over version 3 only;
        since 2026-10-29 a version 3 record may also have "tokens" (no new version: the
        rows didn't change, and readers of the rows leave the key alone)
"""

VERSION = "1"                   # the DL|log version this reads
RECORD_VERSION = 3              # the batch record's "v" (the module docstring's versions)
PRINTED = "Information: "       # what Forge prints before a DL line (it's an INFORMATION entry)
PREFIX = PRINTED + "DL|"        # the start of every DL line Forge prints (the one home of it)
SEATS = (1, 2)                  # Forge's seats; 4-player pods aren't read
EARLY_TURN = 3                  # "in hand by turn 3": the side's own turn whose start is the cut-off
ROW_FIELDS = ("drawn_games", "drawn_wins", "copies_drawn", "used", "stuck", "used_round_sum",
              "other_casts", "discarded", "early_games", "early_wins")
COMMANDER_FIELDS = ("cast_games", "cast_wins", "casts", "first_round_sum")
USED_TO = frozenset(("Stack", "Battlefield"))  # a move there from Hand uses a card (cast or played)
NOT_OTHER = frozenset(("Hand", "Command"))     # a cast from neither is an "other" cast
PEAK_CAP = 30                   # a token's peak above this counts as this (the record's "tokens")
RESTARTED = "the game was restarted (as Karn Liberated does): seat {seat} {what}"


def round_of(turn):
    """The player's own turn number in a 2-player game for Forge's global turn:
    turns 1 and 2 are round 1, turns 3 and 4 round 2."""
    return (turn + 1) // 2


def new_record():
    """A batch's card record before any game (of version RECORD_VERSION)."""
    return {"v": RECORD_VERSION, "games": 0, "bad": 0, "wins": [0, 0], "first": [0, 0],
            "rows": [{}, {}], "commander": [{}, {}], "tokens": [{}, {}]}


def _add_peaks(into, peaks):
    """Add one token's peak counts ([n1, n2, ...]) into another's, number by number (the
    shorter padded with 0s). into changes."""
    into.extend([0] * (len(peaks) - len(into)))
    for i, n in enumerate(peaks):
        into[i] += n


def tokens_less(now, before):
    """What a record's "tokens" gained since an earlier copy of it ([{name: [n1, ...]}]
    per side; before may be None): each token whose counts changed, with the difference,
    its trailing 0s dropped. The warm pool sends a game's part of a chunk's record this
    way (pool_models._cards_delta)."""
    was = before or [{}, {}]
    out = [{}, {}]
    for side in (0, 1):
        for name, peaks in now[side].items():
            old = was[side].get(name, [])
            less = [n - (old[i] if i < len(old) else 0) for i, n in enumerate(peaks)]
            while less and not less[-1]:
                less.pop()
            if less:
                out[side][name] = less
    return out


def merge_record(into, record):
    """Add a batch's record (new_record()'s shape) into another of the same version: its
    games, bad, wins and first summed, and each card's and commander's tallies summed number
    by number (a card only one has is copied). into changes; record doesn't. Returns into.
    The warm pool merges a run's chunks this way. Tokens' peak counts are summed too
    (_add_peaks) when both records have "tokens"; when either hasn't, the merged record has
    none, since its games' tokens weren't all tallied. ValueError for records of different
    versions, or a card's tallies of different lengths."""
    if into.get("v") != record.get("v"):
        raise ValueError(f"card records of versions {into.get('v')} and {record.get('v')} can't be merged")
    into["games"] += record["games"]
    into["bad"] += record["bad"]
    for name in ("wins", "first"):
        into[name] = [a + b for a, b in zip(into[name], record[name])]
    for part in ("rows", "commander"):
        sides = into.setdefault(part, [{}, {}])
        for side, tallies in enumerate(record.get(part, [{}, {}])):
            for card, numbers in tallies.items():
                total = sides[side].get(card)
                if total is None:
                    sides[side][card] = list(numbers)
                elif len(total) != len(numbers):
                    raise ValueError(f"{card}'s tallies have {len(total)} and {len(numbers)} numbers")
                else:
                    sides[side][card] = [a + b for a, b in zip(total, numbers)]
    if "tokens" in into and "tokens" in record:
        for side, tallies in enumerate(record["tokens"]):
            for name, peaks in tallies.items():
                _add_peaks(into["tokens"][side].setdefault(name, []), peaks)
    else:
        into.pop("tokens", None)
    return into


def _cards(text):
    """[(id, name)] of an "<id>=<name>;<id>=<name>;..." list (empty text: none)."""
    out = []
    for part in text.split(";"):
        if part:
            card_id, sep, name = part.partition("=")
            if not sep:
                raise ValueError(f"no '=' in {part!r}")
            out.append((int(card_id), name))
    return out


class Game:
    """One game's card log, fed a line at a time (line(), turn(), kept_hand(), land()),
    and checked (check()) once the game is over. After the first problem it reads nothing
    more: the game won't count."""

    def __init__(self):
        self.problem = None         # why this game's card data can't count (the first reason)
        self.version = None         # DL|log's version
        self.seen = False           # any DL line came
        self.decks = {}             # seat -> {id: name} of its DL|deck
        self.commanders = {}        # seat -> {id: name} of its DL|commander
        self.seat = {}              # id -> seat, of every card in those
        self.zone = {}              # id -> the zone it's in now, replaying the moves
        self.start = {}             # seat -> [ids] of DL|hand ... start
        self.end = {}               # seat -> [ids] of DL|hand ... end
        self.library = {}           # seat -> DL|library ... end's count
        self.over = False           # the end-of-game lines have begun: later moves aren't replayed
        self.kept = {}              # seat -> Forge's "has kept a hand of N cards"
        self.opening = {s: set() for s in SEATS}    # seat -> ids an opening-hand action moved out of its hand
        self.drawn = {}             # id -> the turn of its first move to Hand at turn 1 or later
        self.own_turns = dict.fromkeys(SEATS, 0)    # seat -> its own turns begun (its Turn lines)
        self.early_cut = {}         # seat -> the turn its EARLY_TURN-th own turn began, once it has
        self.used = {}              # id -> round of its first Hand -> Stack/Battlefield move
        self.discarded = set()      # ids moved Hand -> Graveyard
        self.other = {}             # id -> casts from neither the hand nor the command zone
        self.cmd = {}               # commander id -> [casts, round of the first]
        self.tried = {}             # id -> what its move to the Stack counted ("used", "other" or
                                    # "commander"), till a cast line or its next move: not_cast() takes it back
        self.played = set()         # (id, turn) of every move to the Battlefield, any id, from any zone
        self.lands = []             # (id, turn) of Forge's Land lines
        self.tokens = {}            # token id -> [(owner seat or None, logged name), its zone now]
        self.on_field = {}          # (seat, name) -> that token's copies on the battlefield now
        self.peak = {}              # (seat, name) -> the most of them there at once

    def fail(self, why):
        if self.problem is None:
            self.problem = why

    def line(self, text):
        """Read one DL line: the text after "Information: ", "DL|..."."""
        if self.problem is not None:
            return
        try:
            self._line(text.rstrip())
        except (ValueError, IndexError) as e:
            self.fail(f"unreadable card log line ({e})")

    def _line(self, text):
        f = text.split("|")
        kind = f[1]
        if kind == "zone":      # the most common line by far: kept short
            if self.version is None:
                return self.fail("no DL|log line first")
            turn, frm, to, card_id = int(f[2]), f[5], f[6], int(f[8])
            if to == "Battlefield":
                self.played.add((card_id, turn))    # still noted after the end lines: its Land line may follow
            if self.over:
                return
            if card_id not in self.zone:
                return self._token(card_id, frm, to, f[7], f[9])
            self.zone[card_id] = to
            self.tried.pop(card_id, None)
            if card_id in self.cmd:
                if to == "Stack":
                    casts = self.cmd[card_id]
                    if not casts[0]:
                        casts[1] = round_of(turn)
                    casts[0] += 1
                    self.tried[card_id] = "commander"
                return
            if to == "Hand":
                if turn >= 1:
                    self.drawn.setdefault(card_id, turn)
            elif frm == "Hand":
                if turn < 1:
                    seat = self.seat[card_id]
                    if seat not in self.kept:
                        return                          # a mulligan's move
                    self.opening[seat].add(card_id)     # after the keep: an opening-hand action (check 4)
                if to in USED_TO:
                    if card_id not in self.used:
                        self.used[card_id] = max(round_of(turn), 1)
                        if to == "Stack":
                            self.tried[card_id] = "used"
                elif to == "Graveyard":
                    self.discarded.add(card_id)
            if to == "Stack" and frm not in NOT_OTHER:
                self.other[card_id] = self.other.get(card_id, 0) + 1
                self.tried[card_id] = "other"
            return
        if kind == "log":
            if self.seen:
                return self.fail("DL|log wasn't the first DL line")
            self.seen = True
            self.version = f[2]
            if self.version != VERSION:
                self.fail(f"card log version {self.version} (this reads {VERSION})")
            return
        self.seen = True
        if self.version is None:
            return self.fail("no DL|log line first")
        if kind == "deck" or kind == "commander":
            seat = self._seat(f[2])
            into = self.decks if kind == "deck" else self.commanders
            if seat in into:
                return self.fail(f"two DL|{kind} lines for seat {seat}")
            cards = dict(_cards("|".join(f[3:])))
            into[seat] = cards
            where = "Library" if kind == "deck" else "Command"
            for card_id in cards:
                if card_id in self.seat:
                    return self.fail(f"card {card_id} listed twice")
                self.seat[card_id] = seat
                self.zone[card_id] = where
                if kind == "commander":
                    self.cmd[card_id] = [0, None]
        elif kind == "hand":
            when, seat = f[3], self._seat(f[4])
            into = {"start": self.start, "end": self.end}.get(when)
            if into is None:
                return self.fail(f"DL|hand ... {when}")
            if seat in into:
                if when == "start":
                    return self.fail(RESTARTED.format(seat=seat, what="has a second start hand"))
                return self.fail(f"two {when} hands for seat {seat}")
            into[seat] = [card_id for card_id, _ in _cards("|".join(f[5:]))]
            if when == "end":
                self.over = True
        elif kind == "library":
            seat = self._seat(f[4])
            if seat in self.library:
                return self.fail(f"two end library sizes for seat {seat}")
            self.library[seat] = int(f[5])
            self.over = True
        elif kind == "error":
            self.fail("the card log's end-of-game snapshot failed: " + "|".join(f[2:]))

    def _token(self, card_id, frm, to, owner, name):
        """A move of an id in neither seat's lists: a token's peak (the module docstring).
        An id that isn't a token (an effect, a card from outside the game) costs a lookup."""
        token = self.tokens.get(card_id)
        if token is None and frm != "-":
            return
        if token is not None and token[1] == "Battlefield":
            self.on_field[token[0]] -= 1
        if frm == "-":      # created (again, for an id Forge reused)
            token = self.tokens[card_id] = [(int(owner) if owner.isdigit() else None, name), to]
        else:
            token[1] = to
        if to == "Battlefield":
            key = token[0]
            n = self.on_field[key] = self.on_field.get(key, 0) + 1
            if n > self.peak.get(key, 0):
                self.peak[key] = n

    def _seat(self, text):
        seat = int(text)
        if seat not in SEATS:
            raise ValueError(f"seat {seat}")
        return seat

    def turn(self, turn, seat):
        """Forge's "Turn: Turn <turn> (Ai(<seat>)-...)": a turn begins, seat's. LogReader
        calls it for every Turn line. The seat's EARLY_TURN-th one sets its cut-off for
        "in hand by turn 3" (early_games): an extra turn is a turn of its own here, as it
        is in the game. A seat other than 1 or 2 is left alone."""
        if seat in self.own_turns:
            self.own_turns[seat] += 1
            if self.own_turns[seat] == EARLY_TURN:
                self.early_cut[seat] = turn

    def kept_hand(self, seat, size):
        """Forge's "Mulligan: Ai(<seat>)-... has kept a hand of <size> cards"."""
        if seat in self.kept:
            self.fail(RESTARTED.format(seat=seat, what="kept a second hand"))
        self.kept[seat] = size

    def land(self, card_id, turn):
        """Forge's "Land: Ai(n)-... played X (<card_id>)" on turn <turn>."""
        self.lands.append((card_id, turn))

    def cast(self):
        """Forge's "Add To Stack: Ai(n)-... cast X": the cast that the latest move to the
        Stack began went through (the line comes after that move, before any other card
        moves there), so a failed line naming one of the copies moved there before it (a
        trigger of the spell on the Stack that can't target) takes nothing back."""
        self.tried.clear()

    def not_cast(self, card_id):
        """Forge's "Add To Stack: X (<card_id>) - [Couldn't add to stack, ...]": the copy's
        latest move to the Stack wasn't a cast (a failed cast: the module docstring), so
        take back what that move counted. Nothing changes for a copy that has moved again
        since (a move the replay reads) or whose cast line came."""
        if self.problem is not None:
            return
        what = self.tried.pop(card_id, None)
        if what == "used":
            del self.used[card_id]
        elif what == "other":
            self.other[card_id] -= 1
        elif what == "commander":
            casts = self.cmd[card_id]
            casts[0] -= 1
            if not casts[0]:
                casts[1] = None

    def check(self):
        """None when this game's card data counts, else why not (the checks above)."""
        if self.problem is not None:
            return self.problem
        if not self.seen:
            return "no card log"
        for seat in SEATS:
            for what, have in (("DL|deck", self.decks), ("start hand", self.start),
                               ("end hand", self.end), ("end library size", self.library)):
                if seat not in have:
                    return f"no {what} for seat {seat}"
        hands, libraries = {seat: [] for seat in SEATS}, dict.fromkeys(SEATS, 0)
        for card_id, zone in self.zone.items():
            if zone == "Hand":
                hands[self.seat[card_id]].append(card_id)
            elif zone == "Library":
                libraries[self.seat[card_id]] += 1
        for seat in SEATS:
            if sorted(hands[seat]) != sorted(self.end[seat]):
                return f"seat {seat}'s end hand isn't what its moves add up to"
            if libraries[seat] != self.library[seat]:
                return (f"seat {seat}'s library ends with {self.library[seat]} cards, "
                        f"its moves leave {libraries[seat]}")
            held, left = len(self.start[seat]), len(self.opening[seat].difference(self.start[seat]))
            if seat in self.kept and self.kept[seat] != held + left:
                return (f"seat {seat} kept {self.kept[seat]} cards, its start hand has {held}"
                        + (f" and {left} left the hand before turn 1" if left else ""))
        for card_id, turn in self.lands:
            if (card_id, turn) not in self.played:
                return f"no move to the Battlefield for the land played as {card_id} on turn {turn}"
        return None


def add(record, game, winner, first, side, name):
    """Add one finished game to a batch's record: None when it counted, else why its card
    data didn't (it's then counted in "bad"). winner and first are sides (None: nobody
    won; unknown); side(seat) is a seat's side and name(side, logged) a logged name's
    .dck name. Everything is worked out before the record changes, so it never holds part
    of a game."""
    problem = game.check()
    if problem is not None:
        record["bad"] += 1
        return problem
    rows, commanders = [{}, {}], [{}, {}]
    for seat in SEATS:
        s = side(seat)
        won = int(winner == s)
        kept = game.opening[seat].union(game.start[seat])
        drawn = kept.union(game.drawn)
        cut = game.early_cut.get(seat)      # None: the seat's 3rd own turn never began
        end = set(game.end[seat])
        tally = {}      # name -> [any copy drawn, copies_drawn, used, stuck, round sum, other casts, discarded,
                        #          any copy in hand by turn 3]
        for card_id, logged in game.decks[seat].items():
            other = game.other.get(card_id, 0)
            if card_id not in drawn and not other:
                continue
            t = tally.setdefault(name(s, logged), [0, 0, 0, 0, 0, 0, 0, 0])
            t[5] += other
            if card_id in drawn:
                t[0] = 1
                t[1] += 1
                if card_id in game.used:
                    t[2] += 1
                    t[4] += game.used[card_id]
                t[3] += card_id in end
                t[6] += card_id in game.discarded
                if card_id in kept or cut is None or game.drawn[card_id] <= cut:
                    t[7] = 1
        rows[s] = {card: [t[0], t[0] * won, t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[7] * won]
                   for card, t in tally.items()}
        cast = {}       # name -> [casts, round of the first]
        for card_id, logged in game.commanders.get(seat, {}).items():
            casts, rnd = game.cmd[card_id]
            if casts:
                c = cast.setdefault(name(s, logged), [0, rnd])
                c[0] += casts
                c[1] = min(c[1], rnd)
        commanders[s] = {card: [1, won, n, rnd] for card, (n, rnd) in cast.items()}
    peaks = [{}, {}]
    for (seat, logged), n in game.peak.items():
        if seat in SEATS:       # a token without a known owner seat has no side
            peaks[side(seat)][logged] = min(n, PEAK_CAP)
    record["games"] += 1
    if winner is not None:
        record["wins"][winner] += 1
    if first is not None:
        record["first"][first] += 1
    for s in (0, 1):
        for into, part in ((record["rows"][s], rows[s]), (record["commander"][s], commanders[s])):
            for card, numbers in part.items():
                total = into.get(card)
                if total is None:
                    into[card] = numbers
                else:
                    for i, n in enumerate(numbers):
                        total[i] += n
    if "tokens" in record:
        for s in (0, 1):
            for logged, n in peaks[s].items():
                counts = record["tokens"][s].setdefault(logged, [])
                counts.extend([0] * (n - len(counts)))
                counts[n - 1] += 1
    return None
