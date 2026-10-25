"""The decision log (AI round 1, the ai-r1 contract's section 3.8): which of its chances Forge's
AI took to cast or activate the cards it was asked about, and why it passed the others.

The fork's forge.ai.AiDecisionLog prints a line for each ability of a named card the AI weighs
when it chooses what to play with priority (AiController.chooseSpellAbilityToPlayFromList):
    DLAI|1|<turn>|<active seat>|<phase>|<seat>|<decision>|<api>|<card>
turn is the game's turn number, the seats are the N of "Ai(N)-..." ("?" when not known), phase is
Forge's PhaseType ("MAIN1", "COMBAT_DECLARE_BLOCKERS"; "-" for none), decision the AI's
AiPlayDecision ("WillPlay", "CantAfford"...), api the ability's ("Draw"; "-" for none) and card
its host's name. It's off unless the JVM has -Ddecklab.decisionLog=<names> (config's
forge_decision_log, runner_launch._java), which the fork reads once a JVM: a new list needs a
fresh launch (--local), as the server's warm pool doesn't have the knob.

An opportunity is one card in one priority window: a distinct (turn, phase, seat, card) with at
least one decision other than NOT_A_CHANCE (CantPlaySa, CantAfford, CantAffordX and
TimingRestrictions, which canPlaySa gives a sorcery-speed card in every step that isn't a main
phase). It's taken when one of its decisions is WILLING, else declined under its last decision
that isn't NOT_A_CHANCE.
An opportunity doesn't mean the AI could pay: CantAfford comes only after canPlaySa said yes, so a
card it can't pay for usually shows its API's refusal (CantPlayAi, MissingPhaseRestrictions...).
Instants are weighed in every priority window, so compare them per phase, not only per game.

Known limits: a mirror (both seats one list) can't be split by card name, so the counts are per
seat and say nothing about which side; and a DLAI line is printed from the AI's evaluation
thread, which keeps going after an AI timeout, so after a timeout a line can land in the next
game (rare; counted as it is).

    parse(line)             a DLAI line as a dict, or None
    read(lines, names=None) per game: {card: counts}
    read_folder(folder, names=None, games=None)
                            the same for a tee folder's <first>-<last>.log.gz files: {g: ...}
    summary(per_game)       {card: counts over the games, with "games" (games with an opportunity)}

This part comes after experiment_logs.py, whose LOG_NAME names a tee folder's files."""
import gzip
from pathlib import Path

from . import common
from .common import norm
from .experiment_logs import LOG_NAME

PREFIX = "DLAI|"                # the start of every decision-log line
VERSION = "1"                   # the DLAI line version this reads
FIELDS = ("turn", "active", "phase", "seat", "decision", "api", "card")
GAME_END = "Game Result: Game"  # the line that ends a game in Forge's output
# Decisions that aren't a chance to play the card at all.
NOT_A_CHANCE = frozenset({"CantPlaySa", "CantAfford", "CantAffordX", "TimingRestrictions"})
# Decisions that mean the AI will play it (AiPlayDecision.willingToPlay).
WILLING = frozenset({"WillPlay", "MandatoryPlay", "PlayToEmptyHand", "AddBoardPresence", "ImpactCombat",
                     "ResponseToStackResolve", "Removal", "Tempo", "CardAdvantage"})


def parse(line):
    """A DLAI line as {"turn": int, "active", "phase", "seat", "decision", "api", "card"}, or
    None for any other line (or one of another version)."""
    line = line.rstrip("\r\n")
    if not line.startswith(PREFIX):
        return None
    parts = line[len(PREFIX):].split("|", len(FIELDS))
    if len(parts) != len(FIELDS) + 1 or parts[0] != VERSION:
        return None
    try:
        turn = int(parts[1])
    except ValueError:
        return None
    found = dict(zip(FIELDS, parts[1:]))
    found["turn"] = turn
    return found if found["card"] and found["decision"] else None


def _counts():
    return {"opportunities": 0, "taken": 0}


def _card_counts():
    return {"opportunities": 0, "taken": 0, "declined": {}, "by_phase": {}, "by_seat": {}}


def _game(windows):
    """One game's {card: counts} from its windows ({(turn, phase, seat, card): [decisions]})."""
    out = {}
    for (_, phase, seat, card), decisions in windows.items():
        counts = out.setdefault(card, _card_counts())
        chances = [d for d in decisions if d not in NOT_A_CHANCE]
        if not chances:
            continue
        taken = any(d in WILLING for d in chances)
        for part in (counts, counts["by_phase"].setdefault(phase, _counts()),
                     counts["by_seat"].setdefault(seat, _counts())):
            part["opportunities"] += 1
            part["taken"] += taken
        if not taken:
            counts["declined"][chances[-1]] = counts["declined"].get(chances[-1], 0) + 1
    return out


def read(lines, names=None):
    """Per game, in order, {card: {"opportunities", "taken", "declined": {decision: n},
    "by_phase": {phase: {"opportunities", "taken"}}, "by_seat": {seat: {...}}}} from Forge's
    output lines: games end at their "Game Result: Game" line, and the DLAI lines before it are
    that game's (a game with no result line yet isn't counted). names (card names) keeps only
    those cards; a card with lines but no opportunity has zero counts."""
    keep = {norm(n) for n in names} if names else None
    games, windows = [], {}
    for line in lines:
        if line.startswith(GAME_END):
            games.append(_game(windows))
            windows = {}
            continue
        found = parse(line)
        if found is None or (keep is not None and norm(found["card"]) not in keep):
            continue
        window = (found["turn"], found["phase"], found["seat"], found["card"])
        windows.setdefault(window, []).append(found["decision"])
    return games


def read_folder(folder, names=None, games=None):
    """read() of a tee folder (<logs>/<arm or control>/<key>/, its <first g>-<last g>.log.gz
    files, experiment_logs.LOG_NAME): {g: read()'s game}, g being first + the game's place in its
    file. A game in two files (a chunk played again) is taken from the first; a file holding
    other than the games its name says is left out (logged), as experiment_logs.read_logs does.
    games, (lowest, highest) game number, leaves out the files of other games."""
    out = {}
    folder = Path(folder)
    try:
        paths = [p for p in folder.glob("*.log.gz") if LOG_NAME.fullmatch(p.name)]
    except OSError:
        return out
    for path in sorted(paths, key=lambda p: [int(x) for x in LOG_NAME.fullmatch(p.name).groups()]):
        first, last = (int(x) for x in LOG_NAME.fullmatch(path.name).groups())
        if games is not None and (last < games[0] or first > games[1]):
            continue
        try:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except (OSError, EOFError) as e:
            common._log(f"The decision log in {path} can't be read: {e}")
            continue
        found = read(lines, names)
        if len(found) != last - first + 1:
            common._log(f"The log {path} holds {len(found)} finished games, not the {last - first + 1} its name "
                        "says: its decisions are left out.")
            continue
        for i, game in enumerate(found):
            g = first + i
            if games is None or games[0] <= g <= games[1]:
                out.setdefault(g, game)
    return out


def _add(into, part):
    into["opportunities"] += part["opportunities"]
    into["taken"] += part["taken"]


def summary(per_game):
    """{card: {"games": games with an opportunity, "opportunities", "taken", "declined",
    "by_phase", "by_seat"}} over per_game (read()'s list, or read_folder()'s dict)."""
    games = per_game.values() if isinstance(per_game, dict) else per_game
    out = {}
    for game in games:
        for card, counts in game.items():
            total = out.setdefault(card, dict(_card_counts(), games=0))
            total["games"] += counts["opportunities"] > 0
            _add(total, counts)
            for decision, n in counts["declined"].items():
                total["declined"][decision] = total["declined"].get(decision, 0) + n
            for key in ("by_phase", "by_seat"):
                for name, part in counts[key].items():
                    _add(total[key].setdefault(name, _counts()), part)
    return out
