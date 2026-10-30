"""Free dual lands for a colour shortfall (E3-S25, slice 3): when the Stats tab's colour check (Karsten's
sources, lib/stats colourcheck) finds a colour short, the free lands of the deck's space that make that
colour and another of the deck's, each with the basic land it would replace.

The shortfall is the stats' own: a single colour (W, U, B, R or G) whose summary isn't ok. A gold or hybrid
group's check isn't read on its own (a land making one of its colours shows up for that colour's check), and
without Karsten's table (a 20-card deck) nothing is short.

A land is offered (dual_lands) when it's free (spare copies, the caller's count: owned and on the way, less
other built decks', intact products' and the list's own), isn't a basic, is castable in the deck
(swaps.castable: a casual deck's land makes only the deck's colours or every colour, a Commander deck's
identity is within the commander's), makes at least one short colour and makes two or more of the deck's
colours (makes: its produced mana alone, so a utility land whose identity comes only from an ability's cost,
such as Kessig Wolf Run, makes none); in a casual deck, never a land whose mana needs a commander (Command
Tower). Each gets the basic
of the list's Deck section it would replace (replaced_basic):

- first a basic of a colour the land makes that isn't short: the swap only gains (Rootbound Crag for a Forest
  when red is short);
- then a basic of a short colour the land makes, when it also makes another short colour: that colour gains
  and the basic's stays;
- then a basic of a colour that isn't short and the land doesn't make: that colour loses a source (the one
  with the most sources to spare first, by its hardest check's margin).

A basic of a short colour the land doesn't make is never replaced, and a land with no basic to replace isn't
offered. Ties go to the basic the list plays most copies of, then WUBRG order. Lands are ranked by rank_key:
most short colours fixed, nothing lost, not entering tapped, a copy here before on the way only, most
printings, then the name.
"""
import re

from .decklist import is_basic_land
from .swaps import BASICS, CASUAL_COPIES, COLOURS, castable, primary_type, severity_words, _colour_words

COLOUR_OF_BASIC = {name: colour for colour, name in BASICS.items()}
# "enters tapped", "enters the battlefield tapped": always, or with "unless"/"if" in the sentence, maybe.
TAPPED = re.compile(r"[^.\n]*\benters(?: the battlefield)? tapped\b[^.\n]*", re.IGNORECASE)


def short_colours(stats):
    """(short, margins) from deck_stats' answer: short the single colours whose summary isn't ok, in WUBRG
    order ([{"colour", "name", "have", "needed"}] from each one's hardest check); margins {colour: the hardest
    check's margin (have - needed)} of every single colour checked against a table. Both empty without the
    colour check's verdict (no stats, no table)."""
    summaries = ((stats or {}).get("colours") or {}).get("colours") or ()
    short, margins = [], {}
    for summary in summaries:
        colour = summary.get("colours") if isinstance(summary, dict) else None
        if colour not in tuple(COLOURS):
            continue
        hardest = summary.get("hardest") or {}
        if isinstance(hardest.get("margin"), (int, float)):
            margins[colour] = hardest["margin"]
        if summary.get("ok") is False:
            short.append({"colour": colour, "name": summary.get("name") or _colour_words(colour),
                          "have": hardest.get("have"), "needed": hardest.get("needed")})
    short.sort(key=lambda s: COLOURS.index(s["colour"]))
    return short, margins


def deck_basics(sections):
    """{basic land name: copies} of the list's Deck section (Plains to Forest; never Wastes or a snow basic)."""
    out = {}
    for line in sections.get("Deck", ()):
        if line.name in COLOUR_OF_BASIC:
            out[line.name] = out.get(line.name, 0) + line.quantity
    return out


def _front_text(card):
    faces = card.get("card_faces") or ()
    return (faces[0].get("oracle_text") if faces else card.get("oracle_text")) or ""


def _needs_commander(card):
    """Whether the land's mana depends on a commander (Command Tower, Path of Ancestry): no use in a
    casual deck, which has none."""
    return "commander" in _front_text(card).casefold()


def tapped(card):
    """"always", "maybe" (the sentence saying so has an unless or if) or None, from the front face's text."""
    found = TAPPED.search(_front_text(card))
    if not found:
        return None
    return "maybe" if re.search(r"\b(?:unless|if)\b", found.group(0), re.IGNORECASE) else "always"


def makes_colours(card):
    """The colours of mana the land makes, from its produced mana alone (swaps.colours_of adds its colour
    identity, which for Kessig Wolf Run is red and green though it taps only for colourless)."""
    return set(card.get("produced_mana") or ()) & set(COLOURS)


def replaced_basic(makes, short, basics, margins):
    """(basic name, tier) the land would replace (the module docstring's tiers 0, 1 and 2), or (None, None).
    makes and short are sets of colours; basics deck_basics; margins short_colours'."""
    best = None
    for name, qty in basics.items():
        colour = COLOUR_OF_BASIC[name]
        if colour in makes and colour not in short:
            tier = 0
        elif colour in makes and (short & makes) - {colour}:
            tier = 1
        elif colour not in makes and colour not in short:
            tier = 2
        else:
            continue
        key = (tier, -margins.get(colour, 0), -qty, COLOURS.index(colour))
        if best is None or key < best[0]:
            best = (key, name, tier)
    return (best[1], best[2]) if best else (None, None)


def note(makes, short, basic, tier, entering):
    """What the swap does, in swap_note's shape: {"severity", "words", "text"}. Severity 1 for a colour a
    basic made that the land doesn't, 1 for entering tapped (always or maybe)."""
    fixes = _colour_words(short & makes - {COLOUR_OF_BASIC[basic]})
    lost = COLOUR_OF_BASIC[basic]
    facts = [f"makes {fixes} mana, which the deck is short of"]
    if tier == 2:
        facts.append(f"no {_colour_words(lost)} mana in place of a {basic}")
    else:
        facts.append(f"keeps the {_colour_words(lost)} a {basic} makes")
    if entering:
        facts.append("enters tapped" if entering == "always" else "may enter tapped")
    score = (tier == 2) + bool(entering)
    words = severity_words(score)
    return {"severity": score, "words": words, "text": f"{words}: {'; '.join(facts)}."}


def rank_key(fixed, tier, entering, here, card):
    return (-fixed, tier == 2, 0 if not entering else 1 if entering == "maybe" else 2, 0 if here else 1,
            -len(card.get("printings") or ()), card["name"].casefold())


def dual_lands(spares, colours, kind, short, basics, margins, in_list, here):
    """The free dual lands for the short colours, best first: [(rank_key, entry)], entry {"name", "free",
    "makes" (the deck's colours it makes, WUBRG order), "fixes" (the short colours it adds), "replaces"
    {"name", "qty" (copies in the Deck section)}, "max_qty", "tapped", "note"}.

    spares is [(name, spare copies, card)]; colours the deck's (swaps.deck_colours); kind "casual" or
    "commander"; short a set of colours; basics deck_basics; margins short_colours'; in_list name -> copies
    the list holds (the room left: one copy in a Commander deck, CASUAL_COPIES in a casual one); here name ->
    spare copies not on the way."""
    found = []
    if not short:
        return found
    for name, spare, card in spares:
        if card is None or spare <= 0 or is_basic_land(name) or primary_type(card) != "land":
            continue
        if not castable(card, colours, kind) or kind != "commander" and _needs_commander(card):
            continue
        makes = makes_colours(card) & colours
        if not makes & short or len(makes) < 2:
            continue
        basic, tier = replaced_basic(makes, short, basics, margins)
        if basic is None:
            continue
        fixes = short & makes - {COLOUR_OF_BASIC[basic]}
        room = (0 if in_list.get(name) else 1) if kind == "commander" else CASUAL_COPIES - in_list.get(name, 0)
        take = min(spare, room, basics[basic])
        if take <= 0 or not fixes:
            continue
        entering = tapped(card)
        entry = {"name": name, "free": spare, "makes": [c for c in COLOURS if c in makes],
                 "fixes": [c for c in COLOURS if c in fixes], "replaces": {"name": basic, "qty": basics[basic]},
                 "max_qty": take, "tapped": entering, "note": note(makes, short, basic, tier, entering)}
        found.append((rank_key(len(fixes), tier, entering, here.get(name, 0), card), entry))
    found.sort(key=lambda pair: pair[0])
    return found
