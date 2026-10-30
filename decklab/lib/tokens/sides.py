"""Whose side of the table a deck's token lands on (E7-S23): the deck's own, the
opponent's, or either. Part of decklab.lib.tokens (see its docstring).

Scryfall's links between cards and tokens don't say which player gets a token,
so this reads the making card's rules text, sentence by sentence, and is only
ever approximate: the words it gives say so. A sentence counts when it creates
something and names the token (by its name or a face's); when none of a card's
sentences names it, every sentence of the card that creates a token counts.
The clause before "create(s)" says who does (only its part after the last "and", as in "target opponent
loses 2 life and you create", unless that's a joint "... and you each"):

- nobody named or "you" (and "for each opponent, create ..."): the deck's own;
- an opponent ("target opponent", "each opponent", "an opponent", "defending
  player", "each other player"), or "under an opponent's control" after the
  token: the opponent's;
- a player who may be either ("its controller", "target player", "each
  player", "that player", "you and target opponent"): either.

A token several of the deck's cards make is the deck's own only when every one
of them makes it for the deck, the opponent's only when every one makes it for
the opponent, and either otherwise. side() gives the side, the cards that may
give it away and the words; a token no sentence speaks of is the deck's own.
"""
import re

from decklab.lib import cards

from .matching import _and

OWN, OPPONENT, EITHER = "own", "opponent", "either"
SIDES = (OWN, EITHER, OPPONENT)

_SENTENCE = re.compile(r"[^.\n]+")
_CREATE = re.compile(r"\bcreates?\b", re.IGNORECASE)
# Where the subject of "create(s)" starts: after the last of these in the text before it.
_CLAUSE = re.compile(r"[,;:—•(]|\bthen\b|\bif\b|\bwhen(?:ever)?\b|\bunless\b", re.IGNORECASE)
_OPPONENT = re.compile(r"\b(?:target|each|an|that|the chosen) opponents?\b|\bdefending player\b|\beach other player\b"
                       r"|\byour opponents?\b", re.IGNORECASE)
_ANY_PLAYER = re.compile(r"\b(?:target|each|a|that|the chosen) player\b|\bits (?:controller|owner)\b"
                         r"|\b(?:that|the) (?:creature|permanent|spell|artifact|enchantment|land)'s "
                         r"(?:controller|owner)\b|\beach of them\b", re.IGNORECASE)
# A joint subject: "you and target opponent each create", "target opponent and you each create".
_JOINT = re.compile(r"^\s*you and\b|\band you (?:each|both)\s*$", re.IGNORECASE)
_AND = re.compile(r"\band\b", re.IGNORECASE)
# What may follow the last "and" without naming a new subject ("... and then creates", "and may create").
_NO_SUBJECT = re.compile(r"^(?:\s|\bthen\b|\bmay\b)*$", re.IGNORECASE)
_UNDER_OPPONENT = re.compile(r"\bunder (?:an|target|that|each|the chosen) opponent's control\b", re.IGNORECASE)
_UNDER_PLAYER = re.compile(r"\bunder (?:its owner's|its controller's|that player's|target player's) control\b",
                           re.IGNORECASE)


def _subject(sentence, at):
    """The clause before the "create(s)" at index at, and whether it's a joint subject of "you and" another
    player. A clause joined by "and" ("... loses 2 life and you create") gives only the subject after the
    last "and", unless nothing names one there ("target player sacrifices a creature and creates")."""
    before = sentence[:at]
    cut = 0
    for m in _CLAUSE.finditer(before):
        cut = m.end()
    subject = before[cut:]
    if _JOINT.search(subject):
        return subject, True
    ands = list(_AND.finditer(subject))
    if ands and not _NO_SUBJECT.match(subject[ands[-1].end():]):
        subject = subject[ands[-1].end():]
    return subject, False


def sentence_side(sentence):
    """OWN, OPPONENT or EITHER for one sentence that creates something; None when it creates nothing."""
    found = []
    for m in _CREATE.finditer(sentence):
        subject, joint = _subject(sentence, m.start())
        after = sentence[m.end():]
        if _OPPONENT.search(subject):
            side = EITHER if joint else OPPONENT
        elif _ANY_PLAYER.search(subject):
            side = EITHER
        else:
            side = OWN
        if side == OWN and _UNDER_OPPONENT.search(after):
            side = OPPONENT
        elif side == OWN and _UNDER_PLAYER.search(after):
            side = EITHER
        found.append(side)
    return _combine(found) if found else None


def _combine(found):
    found = set(found)
    if found == {OWN}:
        return OWN
    if found == {OPPONENT}:
        return OPPONENT
    return EITHER


def _names_in(sentence, names):
    folded = cards.fold(sentence)
    return any(re.search(rf"\b{re.escape(n)}\b", folded) for n in names if n)


def card_side(text, names):
    """OWN, OPPONENT or EITHER: who a card with rules text makes a token named one of names for (see the
    module's docstring); None when no sentence of its text creates anything."""
    folded_names = [cards.fold(n) for n in names if n]
    sentences = [s for s in _SENTENCE.findall(text or "") if _CREATE.search(s)]
    naming = [s for s in sentences if _names_in(s, folded_names)]
    sides = [sentence_side(s) for s in naming or sentences]
    sides = [s for s in sides if s is not None]
    return _combine(sides) if sides else None


def side(need, texts):
    """(side, the cards that may give it away, words or None) of a need of deck_tokens, from texts:
    {making card's name: its rules text}. The words say it's approximate."""
    names = [need["name"], *need.get("face_names", [])]
    by_card = {}
    for made in need["made_by"]:
        if made["name"] in by_card:
            continue
        by_card[made["name"]] = card_side(texts.get(made["name"], ""), names) or OWN
    overall = _combine(by_card.values()) if by_card else OWN
    givers = [name for name, s in by_card.items() if s != OWN]
    if overall == OWN:
        return OWN, [], None
    whose = "'" if givers[-1].endswith("s") else "'s"
    if overall == OPPONENT:
        words = f"For your opponent: {_and(givers)}{whose} text gives it to another player (approximate)"
    else:
        words = f"Maybe your opponent's: {_and(givers)}{whose} text can give it to another player (approximate)"
    return overall, givers, words
