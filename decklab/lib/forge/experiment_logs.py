"""Read experiment game logs and attribute losses after named spells resolve."""
import gzip
import re
from pathlib import Path

from . import common, seeds
from .common import forge_name, norm
from .logreader import EXPECTED_EXC, RE_CAST, RE_EXC, RE_UNSUPPORTED, LogReader

LOG_NAME = re.compile(r"(\d+)-(\d+)\.log\.gz")


# ============================================================ reading the tee'd logs

class _Lost:
    """Own permanents lost after named cards resolve, in one game (section 12.3): after a
    "Resolve Stack:" line naming a card (its spell, or a trigger naming it), the caster's own
    permanents moving Battlefield -> Graveyard or Exile (DL|zone lines), up to the next
    "Resolve Stack:", "Turn:" or "Phase:" line. The caster is the seat of the copy the line
    names by id, else the seat that last cast that card, else the one seat whose list holds it.
    Casts are Forge's "Add To Stack: Ai(n)-... cast <card>" lines."""

    DL = "Information: DL|"

    def __init__(self, names):
        self.names = {norm(n): n for n in names}
        alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        self.pattern = re.compile(r"(?<![\w'])(" + alternatives + r")(?![\w'])", re.IGNORECASE) if names else None
        self.new_game()

    def new_game(self):
        self.ids, self.deck_names, self.last_cast = {}, {1: set(), 2: set()}, {}
        self.window = None
        self.tally = {}             # (seat, card) -> [casts, lost]

    def line(self, line):
        if self.pattern is None:
            return
        if line.startswith(self.DL):
            f = line[len("Information: "):].rstrip().split("|")
            if f[1] in ("deck", "commander") and len(f) > 3:
                seat = int(f[2])
                for part in "|".join(f[3:]).split(";"):
                    card_id, sep, name = part.partition("=")
                    if sep and card_id.isdigit():
                        self.ids[int(card_id)] = seat
                        self.deck_names.setdefault(seat, set()).add(norm(name))
            elif f[1] == "zone" and self.window is not None and len(f) > 7:
                if f[5] == "Battlefield" and f[6] in ("Graveyard", "Exile") and f[7].isdigit() \
                        and int(f[7]) == self.window[0]:
                    self.tally[self.window][1] += 1
            return
        if line.startswith("Resolve Stack: "):
            self.window = None
            rest = line[len("Resolve Stack: "):]
            m = self.pattern.search(rest)
            if m:
                card = norm(m[1])
                seat = None
                after = re.match(r" \((\d+)\)", rest[m.end():])
                if after:
                    seat = self.ids.get(int(after[1]))
                if seat is None:
                    seat = self.last_cast.get(card)
                if seat is None:
                    holders = [s for s, held in self.deck_names.items() if card in held]
                    seat = holders[0] if len(holders) == 1 else None
                if seat is not None:
                    self.window = (seat, card)
                    self.tally.setdefault(self.window, [0, 0])
            return
        if line.startswith("Turn: ") or line.startswith("Phase: "):
            self.window = None
            return
        m = RE_CAST.match(line.rstrip())
        if m:
            card = norm(forge_name(m[2]))
            if card in self.names:
                seat = int(m[1])
                self.last_cast[card] = seat
                self.tally.setdefault((seat, card), [0, 0])[0] += 1


def _rows_copy(rows, keep):
    """The card log's rows of the cards in keep (norm()'d names), copied: {card: numbers} per side."""
    return [{norm(card): list(numbers) for card, numbers in side.items() if norm(card) in keep} for side in rows]


def read_logs(folder, flip, names=(), games=None):
    """The per-game numbers of a result's tee'd logs in folder (<logs>/<arm or control>/<key>/:
    the files <first g>-<last g>.log.gz): {g: {"w", "first", "r", "ai_to", "cards": [{card:
    [the card log's 10 numbers]} per side] or None (the game's card log didn't pass its checks),
    "lost": [{card: [casts, lost]} per side], "errors": [texts]}}, cards norm()'d: only names'
    (the named cards), whose own losses are counted too. flip is the result's (Forge's deck 1
    in game g is seeds.deck1_side(g, flip)). A game in two files (a chunk played again) is taken
    from the first. games, (lowest, highest) game number, leaves out the files of other games: a
    control's logs can hold thousands of games more than an experiment uses."""
    out = {}
    folder = Path(folder)
    try:
        paths = sorted(folder.glob("*.log.gz"), key=lambda p: [int(x) for x in LOG_NAME.fullmatch(p.name).groups()]
                       if LOG_NAME.fullmatch(p.name) else [1 << 62])
    except OSError:
        return out
    for path in paths:
        m = LOG_NAME.fullmatch(path.name)
        if not m:
            continue
        first = int(m[1])
        if games is not None and (int(m[2]) < games[0] or first > games[1]):
            continue
        try:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except (OSError, EOFError) as e:
            common._log(f"The experiment log {path} can't be read: {e}")
            continue
        mine = _read_file(lines, first, flip, names)
        if len(mine) != int(m[2]) - first + 1:
            # Games are numbered by their place in the file: a file holding other than the games its
            # name says would pair its games with the wrong control games, so none of them count.
            common._log(f"The experiment log {path} holds {len(mine)} finished games, not the "
                        f"{int(m[2]) - first + 1} its name says: its games are left out.")
            continue
        for g, game in mine.items():
            out.setdefault(g, game)
    return out


def _read_file(lines, first, flip, names):
    """One tee file's games, numbered from first by their place in it: {g: read_logs' numbers}."""
    out = {}
    deck1 = seeds.deck1_side(first, flip)
    reader = LogReader(deck1=deck1, card_log=True)
    lost = _Lost(list(names))
    keep = {norm(n) for n in names}
    before, bad, errors, index = _rows_copy(reader.cards["rows"], keep), 0, set(), 0
    for line in lines:
        text = line.rstrip("\r\n")
        lost.line(text)
        m = RE_UNSUPPORTED.match(text)
        if m:
            errors.add(f"unsupported card: {m[1]}")
        elif RE_EXC.match(text) and text.split(":", 1)[0].strip() not in EXPECTED_EXC \
                and not text.startswith("Exception in thread"):
            errors.add(text.strip()[:200])
        if reader.feed(text) != "game":
            continue
        g = first + index
        index += 1
        game = reader.games[-1]
        rows = _rows_copy(reader.cards["rows"], keep)
        if reader.cards["bad"] != bad:
            bad = reader.cards["bad"]
            cards = None
        else:
            cards = []
            for side in (0, 1):
                diff = {}
                for card, numbers in rows[side].items():
                    old = before[side].get(card)
                    now = numbers if old is None else [a - b for a, b in zip(numbers, old)]
                    if any(now):
                        diff[card] = now
                cards.append(diff)
        before = rows
        per_side = [{}, {}]
        for (seat, card), numbers in lost.tally.items():
            per_side[deck1 if seat == 1 else 1 - deck1][card] = numbers
        lost.new_game()
        out[g] = {"w": game["w"], "first": game["first"], "r": game["r"], "ai_to": game["ai_to"], "cards": cards,
                  "lost": per_side, "errors": sorted(errors)}
        errors = set()
    return out

