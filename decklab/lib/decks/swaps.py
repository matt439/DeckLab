"""Swaps: owned cards that could stand in for a card missing from a deck's list, and the swaps
its Play-now list already makes (E2-S07). The same rules rank free pool cards that could replace a
card the list does hold (E3-S25: a card Forge says was drawn and never cast), so "missing" below
is the card whose slot a candidate would fill, whether it's short or in the list.

These are strategic substitutes, picked into the Play-now list in place of the missing card.
The Packing plan's physical stand-ins (E4-S21, standins.py) are a different thing: any spare
card sleeved to represent a card, which never changes a list.

A card can stand in for a missing card (Matt, 2026-10-19: "the same card type, shares a colour,
mana value within 1"; the rest decided 2026-10-20) when:

- Type: both have the same primary type (primary_type): the first of TYPE_ORDER that the front
  face's type line names before " — ". An Artifact Creature or Enchantment Creature is a
  creature, Dryad Arbor and an artifact land are lands; Kindred, Tribal and supertypes don't
  count. An adventure, a modal or transforming card goes by its front face, as the editor's
  finder does; a split card ("Instant // Sorcery") by its first half. Instants and sorceries
  stay apart.
- Colour: their colours (the mana cost's, Scryfall's "colors") overlap. A colourless missing card
  matches only colourless cards and a coloured one never a colourless card. On top of that the
  stand-in must be castable in the deck: a casual deck's stand-in has only colours of the
  Planned list's non-land cards (deck_colours), a Commander deck's a colour identity within the
  commander's.
- Lands: a land matches only lands and a non-land never a land. Mana value doesn't count for
  lands; their colours are the mana they make (Scryfall's produced_mana, less colourless) and
  their colour identity: Rootbound Crag is R and G, Command Tower and City of Brass all five.
  A land that makes no colour (Rogue's Passage, Evolving Wilds) matches colourless lands. In a
  casual deck a stand-in land makes only the deck's colours, or every colour (City of Brass); in a
  Commander deck its identity is within the commander's, as for any card. Plain basics aren't
  counted in the pool, so a missing land also gets the deck's basics of its colours (basics_for),
  always there.
- Mana value: within 1 of the missing card's (Scryfall's cmc; X counts as 0).

What may be swapped: a Deck or Sideboard line that's short (never Commander or Companion, which
make the deck what it is, and never a basic land). A stand-in goes into the missing card's
section.

Candidates are ranked by rank_key (ranked picks and orders them for one slot), and swap_note says in plain words what a swap costs the deck
(severity 0 "Close to even", 1-2 "A little weaker", 3 or more "Clearly weaker"). The note is a
starting point: the editor writes it into the Substitutes prose once, when a stand-in is picked,
and Deck Lab never writes that prose again.

A swap is never stored: derive_swaps works the swaps out from the two lists (what the Play-now
list has fewer of than the Planned list, and what it has instead), each paired with the first
line of the Substitutes prose naming the missing card as a whole word (find_note; "Anger"
isn't named by "Anger of the Gods" when that's a card of either list), so a hand-written table
pairs as well as Deck Lab's own rows. A stand-in's surplus copies are shared out among the swaps
whose lines name it (_share), never counted twice.
"""
import re
from collections import Counter

from .decklist import is_basic_land

# A card's primary type: the first of these its front face's type line names.
TYPE_ORDER = ("land", "creature", "planeswalker", "battle", "instant", "sorcery", "artifact", "enchantment")
SWAPPABLE = ("Deck", "Sideboard")        # the sections whose missing cards get stand-ins
COLOURS = "WUBRG"
BASICS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
COLOUR_WORDS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
MAX_CANDIDATES = 12                      # stand-ins listed for one missing card (the rest are counted)
MAX_REPLACEMENTS = 5                     # free pool cards offered for a card the list holds (E3-S25)
CASUAL_COPIES = 4                        # copies of a name a casual list may hold
# Keywords that say how a card works rather than what it's good at: never a loss or a gain in a note.
MECHANICS = frozenset(("transform", "daybound", "nightbound", "meld", "treasure", "food", "clue", "blood",
                       "map", "powerstone", "incubate", "role"))
# Severity score -> the note's first words.
SEVERITY_WORDS = ((0, "Close to even"), (2, "A little weaker"), (None, "Clearly weaker"))


def front_type_line(card):
    """The front face's type line (a split card's first half), without its subtypes."""
    return (card.get("type_line") or "").split(" // ")[0].split(" — ")[0]


def primary_type(card):
    """The first of TYPE_ORDER the card's front face names, or None (a token, a scheme, ...)."""
    words = front_type_line(card).lower().split()
    return next((t for t in TYPE_ORDER if t in words), None)


def subtypes(card):
    """The front face's subtypes ("Elf", "Druid"), case-folded."""
    parts = (card.get("type_line") or "").split(" // ")[0].split(" — ", 1)
    return {w.casefold() for w in parts[1].split()} if len(parts) > 1 else set()


def colours_of(card):
    """The colours a card is matched by: a land's the mana it makes and its colour identity (Command
    Tower's all five, though its identity is none), any other card's colours."""
    if primary_type(card) == "land":
        return set(card.get("color_identity") or ()) | (set(card.get("produced_mana") or ()) & set(COLOURS))
    return set(card.get("colors") or ())


def deck_colours(sections, kind, card_of):
    """The colours a stand-in may have in this deck: a casual deck's are the colours of its Planned
    list's non-land cards (every section); a Commander deck's the colour identity of its
    commanders. card_of(name) is the card, or None for a name that isn't one (skipped)."""
    out = set()
    wanted = ("Commander",) if kind == "commander" else tuple(sections)
    for section in wanted:
        for line in sections.get(section, ()):
            card = card_of(line.name)
            if card is None:
                continue
            if kind == "commander":
                out |= set(card.get("color_identity") or ())
            elif primary_type(card) != "land":
                out |= set(card.get("colors") or ())
    return out


def castable(candidate, colours, kind):
    """Whether candidate can be played in a deck of these colours (see deck_colours). A casual deck's
    land makes only the deck's colours, or every colour (City of Brass), since a land has none."""
    if kind == "commander":
        return set(candidate.get("color_identity") or ()) <= colours
    if primary_type(candidate) == "land":
        makes = colours_of(candidate)
        return makes <= colours or len(makes) == len(COLOURS) and bool(makes & colours)
    return set(candidate.get("colors") or ()) <= colours


def fits(missing, candidate, colours, kind):
    """Whether candidate can stand in for missing (both cards): the rules in the module's docstring."""
    if missing is None or candidate is None or missing["name"] == candidate["name"]:
        return False
    kind_of = primary_type(missing)
    if kind_of is None or primary_type(candidate) != kind_of:
        return False
    if is_basic_land(candidate["name"]) or not castable(candidate, colours, kind):
        return False
    mine, theirs = colours_of(missing), colours_of(candidate)
    if mine and not mine & theirs or not mine and theirs:
        return False
    return kind_of == "land" or abs((candidate.get("cmc") or 0) - (missing.get("cmc") or 0)) <= 1


def basics_for(missing, colours, kind):
    """The basic land names that may stand in for a missing land: one per colour the land makes
    that the deck plays (Wastes for a colourless land in a Commander deck with no colours)."""
    if primary_type(missing) != "land":
        return []
    wanted = colours_of(missing) & colours if colours else colours_of(missing)
    if not colours_of(missing):
        return ["Wastes"] if kind == "commander" and not colours else []
    return [BASICS[c] for c in COLOURS if c in wanted]


def _number(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _body(card):
    """A creature's power plus toughness, or None when either isn't a plain number ("*")."""
    power, toughness = _number(card.get("power")), _number(card.get("toughness"))
    return None if power is None or toughness is None else power + toughness


def rank_key(missing, candidate, here):
    """Sort key for candidates, best first: most shared roles (removal, ramp, ...), most shared
    subtypes, mana value equal then 1 cheaper then 1 dearer, most shared keywords, a copy here
    before on the way only, most printings (how much a card is played), then the name."""
    diff = (candidate.get("cmc") or 0) - (missing.get("cmc") or 0)
    return (-len(set(missing.get("roles") or ()) & set(candidate.get("roles") or ())),
            -len(subtypes(missing) & subtypes(candidate)),
            0 if diff == 0 else 1 if diff < 0 else 2,
            -len({k.casefold() for k in missing.get("keywords") or ()}
                 & {k.casefold() for k in candidate.get("keywords") or ()}),
            0 if here else 1,
            -len(candidate.get("printings") or ()),
            candidate["name"].casefold())


def ranked(slot, spares, colours, kind, copies, in_list, here):
    """The candidates for slot (a card: one missing from a list, or one in it to be replaced), best
    first: [(rank_key, name, spare, take)]. spares is [(name, spare copies, card)], the free copies
    of the deck's space; each that fits slot (fits, castable in colours) is kept with take, the
    copies it could fill: at most copies (the slot's), its spare copies, and the room the list has
    for it (in_list: name -> copies already there; a Commander deck one copy of a card, a casual
    deck CASUAL_COPIES). here is name -> of its spare copies, those not on the way (rank_key)."""
    found = []
    for name, spare, other in spares:
        if not fits(slot, other, colours, kind):
            continue
        room = (0 if in_list.get(name) else 1) if kind == "commander" else CASUAL_COPIES - in_list.get(name, 0)
        take = min(copies, spare, room)
        if take > 0:
            found.append((rank_key(slot, other, here.get(name, 0)), name, spare, take))
    found.sort()
    return found


def _words(items):
    items = list(items)
    if len(items) < 2:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _colour_words(colours):
    return _words(COLOUR_WORDS[c] for c in COLOURS if c in colours) or "colourless"


def severity_words(score):
    return next(words for top, words in SEVERITY_WORDS if top is None or score <= top)


def _keywords(card):
    """The card's keywords that count in a note (not MECHANICS), case-folded, in order."""
    return [k.casefold() for k in card.get("keywords") or () if k.casefold() not in MECHANICS]


def swap_note(missing, candidate, colours=None):
    """What playing candidate instead of missing costs the deck, from the cards' facts:
    {"severity": score, "words": "A little weaker", "text": "A little weaker: costs 1 more (5 vs 4);
    loses haste."}. The score is 2 for each role lost, 1 for each keyword lost (MECHANICS never
    count), 1 for costing more, 1 for a creature body 2 or more smaller and 1 for a land making
    fewer of the deck's colours (colours, deck_colours; every colour when None). No prices: they'd
    go stale in the prose, and the table has them."""
    score, facts = 0, []
    if primary_type(missing) == "land":
        lost = colours_of(missing) - colours_of(candidate)
        if colours is not None:
            lost &= colours
        if lost:
            score += 1
            facts.append(f"makes no {_colour_words(lost)} mana")
    else:
        mv, other = missing.get("cmc") or 0, candidate.get("cmc") or 0
        if other > mv:
            score += 1
            facts.append(f"costs {other - mv:g} more ({other:g} vs {mv:g})")
        elif other < mv:
            facts.append(f"costs {mv - other:g} less ({other:g} vs {mv:g})")
    if primary_type(missing) == "creature" and primary_type(candidate) == "creature":
        mine, theirs = _body(missing), _body(candidate)
        if mine is not None and theirs is not None and (missing.get("power"), missing.get("toughness")) != \
                (candidate.get("power"), candidate.get("toughness")):
            facts.append(f"{candidate['power']}/{candidate['toughness']} instead of "
                         f"{missing['power']}/{missing['toughness']}")
            if mine - theirs >= 2:
                score += 1
    mine_keys, their_keys = _keywords(missing), _keywords(candidate)
    lost_keys = [k for k in mine_keys if k not in their_keys]
    gained_keys = [k for k in their_keys if k not in mine_keys]
    roles, other_roles = list(missing.get("roles") or ()), set(candidate.get("roles") or ())
    lost_roles = [r for r in roles if r not in other_roles]
    gained_roles = [r for r in candidate.get("roles") or () if r not in roles]
    score += len(lost_keys) + 2 * len(lost_roles)
    losses = lost_keys + [f"its {r}" for r in lost_roles]
    if losses:
        facts.append(f"loses {_words(losses)}")
    gains = gained_keys + gained_roles
    if gains:
        facts.append(f"gains {_words(gains)}")
    words = severity_words(score)
    text = f"{words}: {'; '.join(facts)}." if facts else f"{words}: the same job at the same cost."
    return {"severity": score, "words": words, "text": text}


def basic_note(missing, basic, colours=None):
    """swap_note for a basic land standing in for a missing land (colours as there)."""
    lost = colours_of(missing) - {c for c, name in BASICS.items() if name == basic}
    if colours is not None:
        lost &= colours
    if not lost:
        return {"severity": 0, "words": severity_words(0), "text": f"{severity_words(0)}: a basic of the same colour."}
    return {"severity": 1, "words": severity_words(1),
            "text": f"{severity_words(1)}: makes no {_colour_words(lost)} mana."}


# ----------------------------------------------------------------- the swaps a list makes

def _pattern(name):
    """The whole-word pattern for a card name (and a double-faced card's front face) in prose:
    not part of a longer word ("Bolt" isn't in "Boltwing Marauder"). The page's noteNaming is
    the same rule."""
    names = {name.casefold(), name.split(" // ")[0].casefold()}
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?:^|[^\w'])(?:{alternatives})(?=$|[^\w'])", re.ASCII)


def _without_longer(line, name, others):
    """line case-folded, with every name among others that names the card inside it ("Anger of the
    Gods" for "Anger") taken out, longest first."""
    text, pattern = line.casefold(), _pattern(name)
    for other in sorted(others, key=len, reverse=True):
        folded = other.casefold()
        if len(folded) > len(name) and folded != name.casefold() and pattern.search(folded):
            text = text.replace(folded, " ~ ")
    return text


def names_card(line, name, others=()):
    """Whether a line of prose names the card (find_note's rule). others are the other card names
    in play (both lists'): a longer one naming this one inside it is taken out of the line first, so
    "Anger of the Gods"'s line doesn't name Anger."""
    return bool(_pattern(name).search(_without_longer(line, name, others)))


def _is_rule(line):
    return bool(re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*", line))


def find_note(prose, name, others=()):
    """The first line of prose (the Substitutes section) that names the card (names_card, with the
    other card names others), or None. A table's "|---|" line never counts."""
    for line in (prose or "").split("\n"):
        if line.strip() and not _is_rule(line) and names_card(line, name, others):
            return line
    return None


def note_of(line):
    """A Substitutes line's note: a table row's last cell, the text after a bullet's bold lead
    ("- **2 A → 2 B:** note"), else the text after the first ": ", else the whole line."""
    text = line.strip()
    if text.startswith("|"):
        cells = [c.strip() for c in text.strip("|").split("|")]
        return cells[-1] if cells else ""
    bold = re.match(r"^[-*+]\s+\*\*(.+?)\*\*\s*:?\s*(.*)$", text)
    if bold:
        return bold.group(2).strip() or bold.group(1).strip()
    text = re.sub(r"^[-*+]\s+", "", text)
    return text.split(": ", 1)[1].strip() if ": " in text else text


def _counts(sections, exact):
    out = Counter()
    for lines in (sections or {}).values():
        for line in lines:
            out[exact(line.name)] += line.quantity
    return out


def derive_swaps(target, owned, prose, exact=None):
    """The swaps a Play-now list makes against the Planned list: {"swaps": [{"for", "out_qty",
    "using": [{"name", "qty"}], "note", "note_line"}], "unpaired": [{"name", "qty"}]}.

    out is what the Play-now list has fewer of (all sections together, so moving a card between
    the deck and the sideboard isn't a swap), in is what it has more of. Each out card is paired
    with the first Substitutes line naming it (find_note): its note is note_of that line (None with
    no line) and its using the in cards that line names. In cards no paired line names are
    unpaired. Both lists in the Planned list's order of first appearance, then by name. exact(name)
    gives a name as written its exact card name (cards.resolve; as written by default)."""
    exact = exact or (lambda name: name)
    have, want = _counts(owned, exact), _counts(target, exact)
    order = {}
    for sections in (target, owned):
        for lines in (sections or {}).values():
            for line in lines:
                order.setdefault(exact(line.name), len(order))
    gone = sorted((n for n in want if want[n] > have.get(n, 0)), key=lambda n: (order[n], n))
    added = sorted((n for n in have if have[n] > want.get(n, 0)), key=lambda n: (order[n], n))
    names = list(order)
    swaps, named = [], []
    for name in gone:
        line = find_note(prose, name, names)
        named.append([n for n in added if line and names_card(line, n, names)])
        swaps.append({"for": name, "out_qty": want[name] - have.get(name, 0), "using": [],
                      "note": note_of(line) if line else None, "note_line": line})
    left = {n: have[n] - want.get(n, 0) for n in added}
    for swap, using in zip(swaps, _share(swaps, named, left, names)):
        swap["using"] = using
    unpaired = [{"name": n, "qty": left[n]} for n in added if left[n] > 0]
    return {"swaps": swaps, "unpaired": unpaired}


def _stated(line, name, others):
    """The copies a Substitutes line gives a card ("2 Shock", "2x Shock", "Shock x2"), or None."""
    text = _without_longer(line, name, others)
    alternatives = "|".join(re.escape(n) for n in sorted({name.casefold(), name.split(" // ")[0].casefold()},
                                                         key=len, reverse=True))
    found = re.search(rf"(?:^|[^\w'])(\d{{1,3}})\s*[x×]?\s+(?:{alternatives})(?=$|[^\w'])", text, re.ASCII) \
        or re.search(rf"(?:^|[^\w'])(?:{alternatives})\s*[x×]\s*(\d{{1,3}})\b", text, re.ASCII)
    return int(found.group(1)) if found else None


def _share(swaps, named, left, names):
    """Each swap's using ([{"name", "qty"}]), sharing out the surplus copies left (taken from as
    they're given): first the copies each line states for a card, then, in the swaps' order, what's
    still there up to the copies the swap takes out. A card with nothing left for a line drops out
    of its using; what no line takes stays in left (unpaired)."""
    given = [{} for _ in swaps]
    for i, (swap, cards) in enumerate(zip(swaps, named)):
        for n in cards:
            stated = _stated(swap["note_line"], n, names)
            if stated is not None:
                given[i][n] = min(stated, left[n])
                left[n] -= given[i][n]
    for i, (swap, cards) in enumerate(zip(swaps, named)):
        for n in cards:
            if n not in given[i]:
                given[i][n] = min(left[n], swap["out_qty"])
                left[n] -= given[i][n]
    return [[{"name": n, "qty": given[i][n]} for n in cards if given[i][n] > 0] for i, cards in enumerate(named)]
