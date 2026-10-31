"""The counters and dice a deck's cards call for (E7-S24's read-only slice). Part
of decklab.lib.tokens (see its docstring).

Read from each card's rules text (reminder text included), its type line and
Scryfall's keywords, so it's approximate, and never says how many a game
needs. A kind of counter is the word (or P/T, such as +1/+1) right before
"counter(s)" in the text ("a shield counter", "three time counters"), unless
that word only counts or points ("a counter", "another counter", "may
counter target spell"). Besides the text:

- a planeswalker (any face) uses loyalty counters, a battle defense counters
  and a Saga lore counters;
- {E} in the text is energy;
- a keyword whose reminder text a card may leave out adds its counters
  (KEYWORD_KINDS: undying +1/+1, persist -1/-1, infect -1/-1 and poison, ...);
- "roll a d20" (or "a six-sided die") is a die of that many sides.

Counters players get (poison, energy, experience, rad, ticket) are grouped as
"player"; the rest, on permanents, as "permanent"; dice as "die". Whether
the dice and counters owned cover them is dice_cover.py's: nothing here reads
or writes the inventory, a decklist or a table.
"""
import re

from decklab.lib import cards

NOTE = ("Read from the cards' rules text, types and keywords, so it's approximate: a card may only "
        "check for a counter, or put it on an opponent's permanent. Whether your dice and counters cover "
        "them is approximate too (a die or a counter with no kind stands for any kind), and Deck Lab never "
        "says how many a game needs.")
GROUPS = ("permanent", "player", "die")         # also the order shown
PLAYER_KINDS = frozenset({"poison", "energy", "experience", "rad", "ticket"})

# The word before "counter(s)": a P/T, a two-word keyword counter, or one word.
_COUNTER = re.compile(r"(?<![\w/])([+\-−]\d+/[+\-−]\d+|(?:first|double) strike|[a-z][a-z'\-]*)"
                      r"\s+counters?\b", re.IGNORECASE)
# Words before "counter(s)" that count, point or make it a verb rather than naming a kind.
_NOT_KINDS = frozenset("""
a an the that this those these its their his her each any all no none one two three four five six seven
eight nine ten x of additional more another other same and or to may can can't cannot would will then you
do does did many much with put puts remove removes removed distribute single extra twice kind kinds number
be is are was has had have on from for if as it there half least most fewer greater equal total such
different chosen new than not instead moved control controls get gets spell ability
""".split())
# Keywords whose counters their reminder text says, for a card printed without it (Scryfall's keywords list).
KEYWORD_KINDS = {
    "adapt": ("+1/+1",), "amass": ("+1/+1",), "backup": ("+1/+1",), "bloodthirst": ("+1/+1",),
    "bolster": ("+1/+1",), "dethrone": ("+1/+1",), "devour": ("+1/+1",), "evolve": ("+1/+1",),
    "fabricate": ("+1/+1",), "graft": ("+1/+1",), "mentor": ("+1/+1",), "modular": ("+1/+1",),
    "monstrosity": ("+1/+1",), "outlast": ("+1/+1",), "ravenous": ("+1/+1",), "renown": ("+1/+1",),
    "riot": ("+1/+1",), "scavenge": ("+1/+1",), "support": ("+1/+1",), "training": ("+1/+1",),
    "tribute": ("+1/+1",), "undying": ("+1/+1",), "unleash": ("+1/+1",),
    "persist": ("-1/-1",), "wither": ("-1/-1",), "infect": ("-1/-1", "poison"),
    "toxic": ("poison",), "poisonous": ("poison",),
    "suspend": ("time",), "vanishing": ("time",), "fading": ("fade",), "level up": ("level",),
}
_DIE_WORDS = {"four": 4, "six": 6, "eight": 8, "ten": 10, "twelve": 12, "twenty": 20}
_DIE = re.compile(r"\brolls? (?:a|an|one|two|three|four|five|\d+|x|that many) "
                  r"(?:d(4|6|8|10|12|20|100)s?\b|(four|six|eight|ten|twelve|twenty)-sided dic?e\b)", re.IGNORECASE)
_ENERGY = re.compile(r"\{E\}")


def _kind_name(kind):
    """'+1/+1 counters', 'Loyalty counters', 'd20'."""
    if kind.startswith("d") and kind[1:].isdigit():
        return kind
    return f"{kind[:1].upper()}{kind[1:]} counters"


def _group(kind):
    if kind.startswith("d") and kind[1:].isdigit():
        return "die"
    return "player" if kind in PLAYER_KINDS else "permanent"


def text_kinds(text):
    """The kinds of counter and the dice ("d20") one rules text names, in the order it names them."""
    found = []
    for m in _COUNTER.finditer(text or ""):
        word = m.group(1).lower().replace("−", "-")
        if word in _NOT_KINDS or word.endswith("'s"):     # "Zack Fair's counters" is no kind
            continue
        found.append(word)
    if _ENERGY.search(text or ""):
        found.append("energy")
    for m in _DIE.finditer(text or ""):
        found.append(f"d{m.group(1) or _DIE_WORDS[m.group(2).lower()]}")
    return list(dict.fromkeys(found))


def card_kinds(card):
    """The kinds of counter and dice a card from the card index calls for (see the module's docstring)."""
    texts = [card.get("oracle_text") or ""] + [face.get("oracle_text") or "" for face in card.get("faces", [])]
    types = [card.get("type_line") or ""] + [face.get("type_line") or "" for face in card.get("faces", [])]
    found = []
    for text in texts:
        found.extend(text_kinds(text))
    type_words = " ".join(types)
    if re.search(r"\bPlaneswalker\b", type_words) or card.get("loyalty"):
        found.append("loyalty")
    if re.search(r"\bBattle\b", type_words):
        found.append("defense")
    if re.search(r"\bSaga\b", type_words):
        found.append("lore")
    for keyword in card.get("keywords") or []:
        found.extend(KEYWORD_KINDS.get(str(keyword).lower(), ()))
    return list(dict.fromkeys(found))


def deck_counters(played):
    """{needs: [{key, name, group, made_by: [{name, quantity, section}], sideboard_only}], note} for
    played, [(card name, quantity, section)] of a decklist's cards in the card index. key is the kind
    ("+1/+1", "loyalty", "d20"); needs are in GROUPS' order, then by name."""
    needs = {}
    for name, quantity, section in played:
        card = cards.card(name)
        if card is None:
            continue
        for kind in card_kinds(card):
            need = needs.setdefault(kind, {"key": kind, "name": _kind_name(kind), "group": _group(kind),
                                           "made_by": []})
            for made in need["made_by"]:
                if made["name"] == name and made["section"] == section:
                    made["quantity"] += quantity
                    break
            else:
                need["made_by"].append({"name": name, "quantity": quantity, "section": section})
    out = list(needs.values())
    for need in out:
        need["sideboard_only"] = all(m["section"] == "Sideboard" for m in need["made_by"])
    out.sort(key=lambda n: (GROUPS.index(n["group"]), n["key"][:1] not in "+-",
                            int(n["key"][1:]) if n["group"] == "die" else 0, cards.fold(n["name"])))
    return {"needs": out, "note": NOTE}
