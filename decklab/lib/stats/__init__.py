"""Deck stats worked out straight from a decklist (PLAN.md part 4): the curve,
the land count against Frank Karsten's formula, coloured sources against his
tables, card types and roles, tribes and keywords, and for Commander decks the
deck rules and the minimum Commander Bracket.

Usage (from the repo root):
    python -m decklab.lib.stats casual/gruul-ramp       a summary of one deck
        [--owned]      the deck file's owned-only list instead of the target list
        [--json]       the whole result as JSON
    python -m decklab.lib.stats --all [--pairings]      headline numbers for every deck

From code:

    from decklab.lib import decks, stats
    result = stats.deck_stats(decks.load_deck("casual/gruul-ramp"), "constructed")
    result = stats.deck_stats(decks.load_deck("commander/giada-angels"), "commander")
    stats.headline(result)        # the few numbers the library page shows
    stats.deck_rules(sections, "constructed")   # only the deck-building rules it breaks (the editor)

sections is {section: [decks.DeckLine]}, as decks.load_deck() returns it, and
kind is "commander" or "constructed". The result holds only dicts, lists,
strings, numbers, booleans and None, so it goes straight to JSON. Card data
comes from cards.py. A name that doesn't resolve still counts towards the
deck size but is left out of everything else, with a warning.
Commander bracket.data reports the loaded index's card and oracle-tag source
dates and the combo list's, and whether any is unknown, future-dated or over
MAX_BULK_AGE old. bracket.unknown_cards names unresolved main-deck/commander/
companion cards. bracket.combos holds the two-card combos from Commander
Spellbook's list (decklab.lib.combos, matched on the PC: no decklist is sent
anywhere) whose pieces are both in the main deck. These checks do not certify
a bracket or detect combos of three or more cards, speed, intent or chained
extra turns. They fetch nothing: bracket.data also compares the date of
Wizards' latest Commander announcement, as the card data update last found it
(decklab.lib.official_lists), with the card data's and the bracket rules'
(constants.BRACKET_RULES_DATE), and says when it's unknown.

Where things are (decklab.lib.stats itself offers every name in these
files, except commander.TAG_FILE, COMBO_FILE and OFFICIAL_FILE)
    __init__.py     deck_stats, deck_rules, headline and the command line
    constants.py    every figure, with its source; KINDS; the card-text patterns
    cardtext.py     how a card is read (shared with goldfish/model.py)
    deckparts.py    resolving the decklist, guidance size, curve, land count,
                    types, roles, tribes and keywords
    colourcheck.py  the coloured-source check
    role_targets.py the Command Zone template's Commander role targets (E9-S26)
    commander.py    the Commander checks and bracket, TAG_FILE, COMBO_FILE and
                    OFFICIAL_FILE
    __main__.py     python -m decklab.lib.stats

Every number the guidance uses is a named constant in constants.py, with its
source and the date it was looked up (PLAN.md: never from memory). "sources"
in the result lists them again, so the page can cite them.

What counts
    The main deck is Commander + Companion + Deck. The sideboard is reported
    on its own and left out of everything else, except that its spells are
    checked against the main deck's coloured sources (Karsten counts the
    sideboard's requirements too). The deck size is Commander + Deck, as
    decks.card_count() counts it; a companion sits outside the deck. The size
    picks the guidance: 20, 40 or 60 cards for constructed decks, 100 for
    Commander. Any other size uses the nearest (a tie goes to the larger one),
    and guidance.note says so.

    The curve and the land formula describe the library, the cards you draw:
    the Deck section. A commander or companion is cast from outside it, so it
    is listed in curve.outside instead; Karsten's Commander formula treats
    the commander as a companion, and companions sat outside his decks.
    Types, roles, tribes, keywords and the colour check cover the whole main
    deck, commander and companion included.

    A multi-face card is what its front face is (cards.py stores the front
    face's type line and mana cost; a split card has both halves'): an
    adventure is a creature, a spell // land modal card is a spell at its
    front face's mana value, and a card is a land only when its front face is
    one. Mana value is Scryfall's cmc (X counts as 0; a split card's is both
    halves added). The colour check looks at every face you can cast: both
    halves of a split card, an adventure's or prepare card's spell, and both
    faces of a spell // spell modal card.

Land count (Karsten, "How Many Lands Do You Need in Your Deck?", 2022)
    effective lands = lands + 0.38 per spell // land modal card whose land
    always enters tapped + 0.74 per one whose land can enter untapped (his
    weights are by rarity; "can enter untapped" is his stated reason). The
    recommended count is his formula for the guidance size (LAND_FORMULAS
    says which are published and which are our extrapolation) from:
    - the average mana value of the library's nonland cards, per copy,
      spell // land modal cards at their front face's (his definition);
    - the number of cheap card draw and cheap mana ramp spells: his Oracle
      text rules, run as written on the lowercased text (reminder text
      included) of the faces you can cast. Mana creatures and rocks of mana
      value 2 or less count here, lowering the target; they're never added
      to the lands. A spell // land modal card counts as part of a land
      instead, as he counts them;
    - the number of companions (for Commander the formula already counts
      the commander as one).
    verdict: d = effective lands - recommended, band b = max(1, N/60) with N
    the library size the formula is for (1.65 for Commander): "ok" when
    |d| <= b, "slightly low/high" when |d| <= 2b, else "low/high". A
    Commander deck under 37 effective lands is always "low". The band is our
    choice (the research's suggested +/-1); no source sets one.

Colour check (Karsten, "How Many Sources Do You Need...?", 2022 update)
    Each spell needs enough sources of each colour to have a (89 + MV)%
    chance of casting it on the turn equal to its mana value, on the play:
    a cost of 1GG is "1CC by turn 3", which needs 18 green sources in 60
    cards. The table is picked by the guidance size (40, 60 or 99 cards; he
    publishes nothing below 40, so a 20-card half gets its sources and
    requirements listed without a verdict). How the costs are read:
    - turn = mana value; X counts as 1 (he says to use the X you usually
      pay, which a list can't tell). Turns past 7 use the 7-mana row, the
      last he publishes, which asks for a little more than needed;
    - a gold card is checked per colour with 1 added, and for its colours
      together (sources of either count) with 1 added, unless all but one of
      its colours are made by every land (a splash), when there's no +1;
    - a hybrid symbol needs sources of either colour; {2/W} and Phyrexian
      symbols can be paid without the colour, so they aren't requirements;
      {C} is a colour of its own; {S} (snow) isn't checked;
    - a few costs his tables skip (6C, 2CCCC, 3CCCC, five symbols) use
      numbers our research computed with his model: "published" is False.
    Sources are counted per requirement, since some count only for later
    turns (COLOUR_SOURCE_RULES lists the rules and weights):
    - a land that makes the colour is 1 source; on turn 1 only lands that
      can enter untapped count. A land that searches for a basic is a
      source of every basic's colour in the deck (2/3 of one in decks
      needing 3+ colours); one that searches for a land type, of each colour
      the deck's lands of that type make. When the search costs mana
      (Myriad Landscape, {2}), the colours it finds count only from the turn
      after it can first be paid for (turn 4 for {2}; our rule, since
      Karsten's full source is for searches that cost nothing). A spell //
      land modal card is 0.8 (1 if its land can enter untapped);
    - mana creatures 0.5 from the turn after they're cast (turn 2 at the
      earliest), mana rocks 0.75 (turn 3 at the earliest), 2-mana land
      ramp 0.75 from turn 3 and 3-mana land ramp 0.5 from turn 5, each only
      when the deck can cast the card itself consistently;
    - each cheap card draw spell (mana value 2 or less, castable) digs for
      lands: (sources of the colour / deck size) rounded down to a quarter,
      for spells cast after it, the first 10 only;
    - Exotic Orchard 0.75, Fellwar Stone 0.5 (unknown opponents).
    Not counted: Treasure, scry, a Verge land's condition (it counts fully
    for both colours), and any other nonland card: only creatures and
    artifacts with a "{T}: Add" ability, land ramp and cheap card draw count.

Commander checks (kind "commander" only; casual decks get none, since
AGENTS.md says to ignore ban lists and legality for casual decks)
    100 cards with the commander(s); one copy of each card except basic
    lands and cards whose text allows more ("A deck can have any number of
    cards named ..."); every card's colour identity inside the commanders'
    combined identity; banned cards (Scryfall's legalities.commander, plus
    Lutri, which is only banned as a companion) and not_legal ones; Game
    Changers (Scryfall's game_changer flag, the list cards.game_changers()
    returns), mass land denial and extra-turn cards (Scryfall oracle tags
    mass-land-denial and extra-turn, read with cards.tag_members), and the
    minimum bracket they allow. Two-card combos come from Commander
    Spellbook's list (bracket.combos); combos of three or more cards, intent
    and whether extra turns chain can't be judged from a list; the result
    says so.

Result (every key is always there; None where it doesn't apply)
    kind            "constructed" or "commander"
    counts          {"commander", "companion", "deck", "sideboard", "main"}:
                    copies per section; main = commander + deck
    guidance        {"size": 20|40|60|100, "deck_size", "library": the
                    library size the formulas are for (99 for Commander),
                    "note": str or None when the size isn't one of those}
    unresolved      [{"name", "qty", "section"}]: names that aren't cards
    warnings        [str]
    curve
        buckets     [{"mv": "0".."6" or "7+", "creatures", "noncreatures",
                    "total", "cards": [card]}]
        nonland, creatures, noncreatures     copies
        average_mv  float or None (no nonland cards); average_mv_definition str
        x_spells    {"count", "cards": [card]}
        outside     [{"name", "qty", "section", "mv", "creature"}]
    lands
        lands       copies of cards whose front face is a land
        mdfc        {"tapped", "untapped": copies, "cards": [card + "land_enters"]}
        effective   lands + the modal cards' weights
        cheap       {"count", "draw": [card], "ramp": [card]}
        mana_creatures, mana_rocks   [card + "mv", "produces", "cheap"]
        average_mv, companions
        formula     {"text", "worked", "published": bool, "status", "source"}
        recommended float or None; band; delta (effective - recommended)
        verdict     "low" | "slightly low" | "ok" | "slightly high" | "high" | None
        verdict_text  str; floor: 37 for Commander, else None
        rule_of_thumb {"text", "sources": [source id]}
    colours
        table       40 | 60 | 99 | None (20-card decks: no table)
        definition, table_note (None or why there's no verdict)
        assumed_lands (the table's), deck_lands, land_note (None or a caution)
        colours     [summary]: one per colour or colour group a spell needs,
                    single colours first (WUBRG, then C), then groups
        sources     [{"name", "qty", "kind", "colours", "weight", "from_turn",
                    "turn_one", "counted", "found_from_turn", "note"}];
                    found_from_turn is the turn the colours a land's paid-for
                    search finds start counting (None for every other source)
        rules       [str]: how sources were counted
        ok          all requirements met (None without a table)
        source      "karsten-sources"
    colour summary  {"colours": "G", or "WU" when sources of any of them count
                    (a gold card's colours together, or a hybrid symbol),
                    "name" ("green", "white or blue"), "land_sources": lands
                    making it (weights applied), "ok" (None without a table),
                    "hardest": check, "short": [check], "checks": [check]}
    check           {"colours", "cost": Karsten's notation ("1CC": two symbols
                    of the colour and one other mana), "cost_in_colours": "1GG",
                    or "1{W/U}{W/U}" for hybrid symbols, or for a gold card's
                    colours together the printed cost ("{1}{W}{U}"; cards with
                    different costs get a check each), "turn", "pips", "gold":
                    bool (1 was added), "needed" (None: no table or no entry),
                    "published" (False: our computed number), "have",
                    "have_lands" (lands only), "ok", "margin" (have - needed),
                    "cards": [card] (a face you cast as "Fire // Ice (Fire)"),
                    "notes": [str]: why the number is what it is (gold +1,
                    X counted as 1, a turn past 7, ...), for the page to show};
                    checks are sorted hardest first (smallest margin)
    types           [{"type", "count", "cards"}] for creature, instant, sorcery,
                    artifact, enchantment, planeswalker, battle, land
    roles           [{"role", "count", "cards"}] for cards.ROLES
    role_targets    None for constructed decks, else the Command Zone template's
                    categories beside the deck's counts (role_targets.py, E9-S26):
                    {"source", "episode", "episode_date", "checked", "categories":
                    [{"category", "label", "target", "about", "count" (None: no
                    Deck Lab measure), "status" ("below" | "at" | "above" | None),
                    "roles", "except", "role_bar", "measure"}], "by_role"}
    tribes          {"types": [{"type", "count", "cards"}] most first,
                    "changelings": {"count", "cards", "note"}}
    keywords        [{"keyword", "count", "cards"}] most first
    sideboard       {"count", "cards": [card], "checks": [check]}
    commander       None for constructed decks, else:
        ok, problems      bool, [str]: every rule broken, in words
        commanders        [name]; colour_identity: "WG" ("" if colourless)
        size              {"cards", "expected": 100, "ok", "companion", "note"}
        eligibility       {"ok", "problems": [str]} (legendary creature, partners)
        singleton         {"ok", "duplicates": [{"name", "copies", "limit"}],
                          "allowed": [{"name", "copies", "rule"}] (text allows more)}
        identity          {"ok", "outside": [{"name", "colour_identity", "outside"}],
                          "checked": False when there's no commander}
        legality          {"ok", "banned", "banned_as_companion", "not_legal": [card],
                          "source"}
        bracket           {"minimum": 1-4, "cards_minimum": 1-4, the minimum
                          without the two-card combos (so the page can tell
                          a combo's floor from a card's), "label", "reasons": [str],
                          "data": {"cards_date", "tags_date", "combos_date",
                          "stale", "dates_stale", "max_age_days",
                          "official_announcement": {"date", "url"} or None,
                          "official_checked": date of the last good check or
                          None, "official_unknown": no good check in
                          max_age_days, "rules_date",
                          "cards_older_than_announcement",
                          "rules_older_than_announcement"},
                          dates_stale: a date unknown, in the future or over
                          max_age_days old; stale: that, or official_unknown,
                          or either older_than_announcement,
                          "game_changers": [card], "mass_land_denial",
                          "extra_turns": [card] or None (no tag data),
                          "combos": {"checked": True, "list_date", "version",
                          "matches": [{"names": [the two cards' names], "results":
                          [str], "class" (combos.CLASSES), "standalone": False when
                          it needs a payoff, "raises_floor": bool, "floor": 1, 3
                          or 4, "url": its Spellbook page}]} or {"checked": False,
                          "reason"} (no combo list),
                          "near_combos" (only beside a readable list and a
                          commander; E9-S25): {"checked": True, "total",
                          "matches": [{as a combo, minus raises_floor, plus
                          "missing": the card to add, "minimum_with": the
                          minimum with it added, "raises_minimum": bool}]},
                          the missing piece in the commander's colours and
                          legal in Commander,
                          "not_automatic": [str], "brackets": the five brackets'
                          rules (BRACKETS), "sources": [source id]}
                          A standalone infinite or game-ending combo raises the
                          minimum to 3; one that destroys lands counts as mass
                          land denial (4), standalone or not. Locks, draws,
                          near-infinites and other combos needing a payoff
                          raise nothing.
    sources         {source id: {"title", "date", "url"}}
    card            {"name", "qty"}; lists of cards are sorted by name
"""
import argparse
import json
import sys
from collections import Counter

from decklab.lib import decks

# Every function, class and constant the module had before Milestone 7
# split it up, except commander.TAG_FILE (tests patch it there; a copy here
# would miss).
from .constants import (
    KINDS, SOURCES, COMBO_LIST_UNREAD, CONSTRUCTED_SIZES, COMMANDER_SIZE, COMMANDER_LIBRARY, LAND_INTERCEPT,
    LAND_PER_AMV, LAND_PER_COMPANION, LAND_PER_CHEAP, COMMANDER_LAND_INTERCEPT,
    COMMANDER_LAND_PER_AMV, LAND_FORMULAS, MDFC_LAND_WEIGHTS, LAND_BAND_MIN, COMMANDER_LAND_FLOOR,
    LAND_RULES_OF_THUMB, CHEAP_MAX_MV, CHEAP_DRAW_WORDS, CHEAP_DRAW_NOT, CHEAP_DRAW_CREATURE_WORDS,
    CHEAP_LOOK_WORDS, CHEAP_LOOK_NOT, CHEAP_RAMP_NOT, CHEAP_RAMP_CREATURE_NOT, CHEAP_RAMP_AURA,
    CHEAP_RAMP_CHEAT, COLOUR_SOURCES_NEEDED, COLOUR_SOURCES_COMPUTED, COLOUR_TABLES,
    COLOUR_ASSUMED_LANDS, COLOUR_LAND_TOLERANCE, COLOUR_MAX_TURN, COLOUR_X_VALUE, GOLD_EXTRA,
    LAND_SOURCE, MDFC_SOURCE_WEIGHTS, MULTICOLOUR_FETCH_WEIGHT, DORK_WEIGHT, DORK_FIRST_TURN,
    ROCK_WEIGHT, ROCK_FIRST_TURN, RAMP2_WEIGHT, RAMP2_FIRST_TURN, RAMP3_WEIGHT, RAMP3_FIRST_TURN,
    CANTRIP_MAX_MV, CANTRIP_MAX_COUNTED, CANTRIP_ROUNDING, SPECIAL_SOURCE_WEIGHTS,
    COLOUR_SOURCE_RULES, DECK_COPIES_RE, PARTNER_WITH_RE, PARTNER_TEXT_RE,
    OFF_BATTLEFIELD_CREATURE_RE, NUMBER_WORDS, BANNED_AS_COMPANION, BRACKETS,
    UPGRADED_MAX_GAME_CHANGERS, BRACKET_LABELS, MASS_LAND_DENIAL_TAG, EXTRA_TURN_TAG,
    BRACKET_NOT_AUTOMATIC, COLOURS, MANA_COLOURS, COLOUR_NAMES, CARD_TYPES, LAND_TYPES,
    TRIBAL_TYPES, MULTIWORD_SUBTYPES, CAST_EVERY_FACE, SYMBOL_RE, REMINDER_RE, TAP_ADD_RE,
    MANA_COST_PART_RE, ABILITY_WORD_RE, SEARCH_RE, ENTERS_TAPPED_RE, UNTAPPED_OPTION_RE,
    MULTIPLAYER_UNTAPPED_RE, CYCLING_RE, LAND_KINDS)
from .cardtext import (
    Entry, _r, card_list, type_words, subtypes, is_land, is_creature, _faces, front_text, land_face,
    cast_faces, _spell_text, _has_x, untapped_on_turn_one, _parse_cost, _cycles_for_one,
    _cheap_kind, mana_abilities, mana_ability, mana_kind, land_search, search_cost,
    _searchable_colours, colour_label, colour_words, _colour_name)
from .deckparts import (
    resolve_entries, _guidance, _average_mv, _curve, _lands, _land_verdict, _types, _roles, _tribes,
    _keywords)
from .colourcheck import (
    _Source, _requirements, _checks, _needed, _cost_key, _Sources, _colour_groups, _hardest_first,
    _colour_check)
from .role_targets import SOURCE_ID as ROLE_TARGETS_SOURCE_ID, role_targets as _role_targets
from .commander import (
    min_bracket, _copies_allowed, is_basic, _can_be_commander, _is_background, _is_doctor,
    _partner_abilities, _pairing, _partners, _abilities_in_words, _commander_checks)


# ================================================================= public

def deck_stats(sections, kind):
    """Stats for a decklist {section: [decks.DeckLine]}; kind is "commander"
    or "constructed". Returns the JSON-safe dict the module docstring describes."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    warnings = []
    entries, unresolved = resolve_entries(sections, warnings)
    by_section = {s: [e for e in entries if e.section == s] for s in decks.SECTIONS}
    library = by_section["Deck"]
    outside = by_section["Commander"] + by_section["Companion"]
    main = outside + library
    counts = {s.lower(): sum(line.quantity for line in sections.get(s, [])) for s in decks.SECTIONS}
    counts["main"] = counts["commander"] + counts["deck"]
    guidance = _guidance(kind, counts["main"])
    if guidance["note"]:
        warnings.append(guidance["note"])
    if unresolved:
        total = sum(unresolved.values())
        warnings.append(f"{total} card{'s' if total != 1 else ''} with names that aren't Scryfall "
                        f"cards {'count' if total != 1 else 'counts'} towards the deck size but "
                        f"nothing else: " + ", ".join(sorted({n for _, n in unresolved})))
    if kind == "commander" and not by_section["Commander"]:
        warnings.append("This Commander deck has no Commander section.")

    curve = _curve(library, outside)
    lands = _lands(library, sum(e.qty for e in by_section["Companion"]), kind, guidance)
    colours, sideboard_checks = _colour_check(main, library, by_section["Sideboard"], guidance, lands, kind)
    commander = _commander_checks(by_section, sections, unresolved, warnings) if kind == "commander" else None
    sources = {key: dict(value) for key, value in SOURCES.items()}
    if kind != "commander":       # the role targets' template is cited only where they show
        sources.pop(ROLE_TARGETS_SOURCE_ID, None)
    combos = commander["bracket"]["combos"] if commander else {}
    if combos.get("checked"):       # the combo list's date is its own, known only now
        sources["commander-spellbook"]["date"] = (
            f"list of {commander['bracket']['data']['combos_date'] or 'an unknown date'}"
            + (f", version {combos['version']}" if combos.get("version") else ""))
    elif commander:
        sources["commander-spellbook"]["date"] = COMBO_LIST_UNREAD
    return {
        "kind": kind,
        "counts": counts,
        "guidance": guidance,
        "unresolved": [{"name": name, "qty": qty, "section": section}
                       for (section, name), qty in sorted(unresolved.items())],
        "warnings": warnings,
        "curve": curve,
        "lands": lands,
        "colours": colours,
        "types": _types(main),
        "roles": _roles(main),
        "role_targets": _role_targets(main, lands["lands"]) if kind == "commander" else None,
        "tribes": _tribes(main),
        "keywords": _keywords(main),
        "sideboard": {"count": counts["sideboard"], "cards": card_list(by_section["Sideboard"]),
                      "checks": sideboard_checks},
        "commander": commander,
        "sources": sources,
    }


CONSTRUCTED_MIN_SIZE = 60           # AGENTS.md: casual decks have at least 60 cards
CONSTRUCTED_MAX_COPIES = 4          # ... and at most 4 of a card other than basic lands


def _constructed_limit(card):
    """How many copies a 60-card deck may have (None: any number). Text that
    allows only one ("A deck can have only one card named ...") means one."""
    m = DECK_COPIES_RE.search(card["oracle_text"].lower())
    if m is None:
        return CONSTRUCTED_MAX_COPIES
    allowed = _copies_allowed(card)
    if allowed is None or m.group(1) == "only one" or m.group(3):
        return allowed
    return max(allowed, CONSTRUCTED_MAX_COPIES)


def deck_rules(sections, kind):
    """The deck-building rules a decklist breaks, for the editor, which shows
    them as warnings before saving (decks in progress are saved too).

    constructed (casual decks, AGENTS.md): at least 60 cards (Commander +
    Deck), and at most 4 copies of a card other than basic lands, counting
    the deck and sideboard together; a card whose text allows more ("A deck
    can have any number of cards named ...") uses that. Ban lists and
    legality don't apply.
    commander: the checks deck_stats makes (100 cards, one of each card,
    colour identity, commander eligibility, the ban list, Game Changers and
    the minimum bracket).

    Returns {"kind", "problems": [str], "problem_cards": [[str]] (for each
    problem, the names of the cards it's about, as the list has them; [] for
    one about the whole deck, such as its size), "commander": the "commander"
    part of deck_stats (None for constructed), "warnings": [str]}.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    warnings = []
    entries, unresolved = resolve_entries(sections, warnings)
    by_section = {s: [e for e in entries if e.section == s] for s in decks.SECTIONS}
    if kind == "commander":
        checks = _commander_checks(by_section, sections, unresolved, warnings)
        return {"kind": kind, "problems": list(checks["problems"]),
                "problem_cards": [list(names) for names in checks["problem_cards"]], "commander": checks,
                "warnings": warnings}
    problems, problem_cards = [], []
    size = decks.card_count(sections)
    if size < CONSTRUCTED_MIN_SIZE:
        problems.append(f"{size} card{'' if size == 1 else 's'}; a casual deck has at least {CONSTRUCTED_MIN_SIZE}.")
        problem_cards.append([])
    copies, by_name = Counter(), {}
    for e in entries:
        copies[e.name] += e.qty
        by_name[e.name] = e.card
    for (_, name), qty in unresolved.items():
        if not decks.is_basic_land(name):
            copies[name] += qty
    in_sideboard = {e.name for e in by_section["Sideboard"]} | {n for s, n in unresolved if s == "Sideboard"}
    for name, n in sorted(copies.items()):
        card = by_name.get(name)
        if n < 2 or (card is not None and is_basic(card)):
            continue
        limit = _constructed_limit(card) if card is not None else CONSTRUCTED_MAX_COPIES
        if limit is not None and n > limit:
            where = " (deck and sideboard together)" if name in in_sideboard else ""
            problems.append(f"{n} copies of {name}{where}; a deck can have at most {limit}.")
            problem_cards.append([name])
    return {"kind": kind, "problems": problems, "problem_cards": problem_cards, "commander": None,
            "warnings": warnings}


def headline(result):
    """The few numbers a deck list or summary shows: cards, lands, the
    recommended count and verdict, average mana value, colour shortfalls
    (["G 1CC: 17.5 of 18", "R 1C (gold card, +1): 13 of 14", ...]) and, for
    Commander, the minimum bracket."""
    lands = result["lands"]
    short = []
    for summary in result["colours"]["colours"]:
        for check in summary["short"]:
            gold = " (gold card, +1)" if check["gold"] else ""
            short.append(f"{check['colours']} {check['cost']}{gold}: {check['have']:g} of {check['needed']}")
    commander = result["commander"]
    return {
        "cards": result["counts"]["main"],
        "lands": lands["effective"],
        "recommended": lands["recommended"],
        "verdict": lands["verdict"],
        "average_mv": lands["average_mv"],
        "colours_ok": result["colours"]["ok"],
        "colour_short": short,
        "min_bracket": commander["bracket"]["minimum"] if commander else None,
        "commander_ok": commander["ok"] if commander else None,
    }


# ------------------------------------------------------------ command line

def _print_summary(deck_id, result):
    h = headline(result)
    print(f"{deck_id}: {h['cards']} cards ({result['guidance']['size']}-card guidance)")
    for warning in result["warnings"]:
        print(f"  ! {warning}")
    lands = result["lands"]
    print(f"  Lands: {lands['effective']:g} (formula {lands['recommended']}: {lands['verdict']}); "
          f"{lands['formula']['worked']}")
    print(f"  Rule of thumb: {lands['rule_of_thumb']['text']}")
    print("  Curve: " + "  ".join(f"{b['mv']}:{b['total']}" for b in result["curve"]["buckets"])
          + f"  (average {result['curve']['average_mv']})")
    for summary in result["colours"]["colours"]:
        hard = summary["hardest"]
        status = {True: "ok", False: "SHORT", None: "no table"}[summary["ok"]]
        print(f"  {summary['colours']:<3} {status:<8} hardest {hard['cost_in_colours']} by turn "
              f"{hard['turn']}: needs {hard['needed']}, has {hard['have']:g} "
              f"({', '.join(c['name'] for c in hard['cards'][:4])})")
    print("  Types: " + ", ".join(f"{t['count']} {t['type']}" for t in result["types"] if t["count"]))
    print("  Roles: " + ", ".join(f"{r['count']} {r['role']}" for r in result["roles"] if r["count"]))
    tribes = result["tribes"]["types"][:3]
    if tribes:
        print("  Tribes: " + ", ".join(f"{t['count']} {t['type']}" for t in tribes))
    commander = result["commander"]
    if commander:
        print(f"  Commander: {commander['bracket']['label']}; "
              + ("legal" if commander["ok"] else "; ".join(commander["problems"])))


def main(argv=None):
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.stats",
                                     description="Deck stats for a Deck Lab deck.")
    parser.add_argument("deck_id", nargs="?", help='e.g. casual/gruul-ramp, "pairing/cats+elves"')
    parser.add_argument("--owned", action="store_true", help="the owned-only list")
    parser.add_argument("--json", action="store_true", help="print the whole result as JSON")
    parser.add_argument("--all", action="store_true", help="headline numbers for every deck")
    parser.add_argument("--pairings", action="store_true", help="with --all: the 45 Beginner Box pairings too")
    args = parser.parse_args(argv)
    if not args.all and not args.deck_id:
        parser.error("give a deck id or --all")
    if args.all:
        summaries = [s for s in decks.list_decks() if not s.get("error")]
        if args.pairings:
            summaries += decks.beginner_box_pairings()
        print(f"{'deck':<48} {'ver':<6} {'cards':>5} {'lands':>6} {'rec':>6} {'verdict':<13} "
              f"{'avg MV':>6} {'bracket':>7}  colour shortfalls")
        for summary in summaries:
            for version in summary["versions"]:
                result = deck_stats(decks.load_deck(summary["id"], version), decks.engine_kind(summary))
                h = headline(result)
                print(f"{summary['id']:<48} {version:<6} {h['cards']:>5} {h['lands']:>6g} "
                      f"{h['recommended'] or '-':>6} {h['verdict'] or '-':<13} "
                      f"{h['average_mv'] or '-':>6} {h['min_bracket'] or '-':>7}  "
                      + ("; ".join(h["colour_short"]) or ("-" if h["colours_ok"] is None else "none")))
        return 0
    summary = decks.find_summary(args.deck_id)       # a pairing's halves in either order
    if summary is None:
        print(f"No deck {args.deck_id!r}", file=sys.stderr)
        return 1
    result = deck_stats(decks.load_deck(summary["id"], "owned" if args.owned else "target"),
                        decks.engine_kind(summary))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_summary(args.deck_id, result)
    return 0
