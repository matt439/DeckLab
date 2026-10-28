"""Commander deck rules and the minimum Commander Bracket: the deck size,
who can be a commander (and which two can be commanders together), one copy
of each card, colour identity, the ban list, Game Changers, mass land denial,
extra turns and two-card combos (Commander Spellbook's list, decklab.lib.combos).
The package docstring (decklab/lib/stats/__init__.py) describes the result."""
from collections import Counter
from datetime import date, datetime, timezone

from decklab.lib import cards, combos, decks, official_lists

from .constants import (
    BANNED_AS_COMPANION, BRACKETS, BRACKET_LABELS, BRACKET_NOT_AUTOMATIC, BRACKET_RULES_DATE,
    COMMANDER_SIZE,
    DECK_COPIES_RE, EXTRA_TURN_TAG, MASS_LAND_DENIAL_TAG, NUMBER_WORDS, OFF_BATTLEFIELD_CREATURE_RE,
    PARTNER_TEXT_RE, PARTNER_WITH_RE, REMINDER_RE, UPGRADED_MAX_GAME_CHANGERS)
from .cardtext import card_list, colour_label, colour_words, front_text, subtypes, type_words

# Read only by _commander_checks below. Tests patch it here, on
# decklab.lib.stats.commander: the package doesn't re-export it, so a patch
# on decklab.lib.stats fails instead of silently missing.
TAG_FILE = None     # None: cards' downloaded oracle_tags file; the tests point it at a fixture
COMBO_FILE = None   # None: combos' two_card.json; the tests point it at a fixture
OFFICIAL_FILE = None    # None: official_lists' official_lists.json; the tests point it at a fixture


def _source_date(value):
    """An index bulk date as an ISO calendar date, or None for unknown metadata."""
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value).date()
    except ValueError:
        return None
    return parsed


def _official(today, cards_date, max_age):
    """What Wizards' latest Commander announcement (official_lists, read from
    the PC only) says about the card data and the bracket rules (E9-S24). The
    card data must be newer than the announcement (data of its own day may
    predate it); the rules, at least as new (BRACKET_RULES_DATE is then the
    announcement's own date). Unknown when no check worked in max_age days."""
    found = official_lists.read(OFFICIAL_FILE)
    announcement = found["announcement"]
    success = _source_date(found["last_success_at"])
    unknown = success is None or not 0 <= (today - success).days <= max_age
    announced = date.fromisoformat(announcement["date"]) if announcement else None
    rules = date.fromisoformat(BRACKET_RULES_DATE)
    return {"official_announcement": announcement,
            "official_checked": success.isoformat() if success else None,
            "official_unknown": unknown,
            "rules_date": rules.isoformat(),
            "cards_older_than_announcement": bool(announced and cards_date and cards_date <= announced),
            "rules_older_than_announcement": bool(announced and rules < announced)}


def _data_dates(combos_date=None):
    """Describe the loaded index's sources, the combo list's date (an ISO
    timestamp, or None when it's unknown) and Wizards' latest Commander
    announcement, without fetching or rebuilding anything. dates_stale is a
    date's own age; stale adds an announcement newer than the card data or the
    bracket rules, or none known."""
    try:
        info = cards.info()
        bulk = info.get("bulk", {}) if isinstance(info, dict) else {}
    except cards.INDEX_ERRORS:
        bulk = {}
    if not isinstance(bulk, dict):
        bulk = {}
    dates = {"cards_date": _source_date(bulk.get("default_cards")),
             "tags_date": _source_date(bulk.get("oracle_tags")),
             "combos_date": _source_date(combos_date)}
    today = datetime.now(timezone.utc).date()
    max_age = cards.MAX_BULK_AGE.days
    dates_stale = any(value is None or not 0 <= (today - value).days <= max_age for value in dates.values())
    official = _official(today, dates["cards_date"], max_age)
    return {**{key: value.isoformat() if value is not None else None for key, value in dates.items()},
            "stale": dates_stale or official["official_unknown"]
            or official["cards_older_than_announcement"] or official["rules_older_than_announcement"],
            "dates_stale": dates_stale, "max_age_days": max_age, **official}


# ------------------------------------------------------ Commander checks

def min_bracket(game_changers, mass_land_denial, extra_turns, two_card_combos=0):
    """The lowest Commander Bracket a deck with these counts fits (1-4;
    Bracket 5 differs from 4 only by intent, so it's never the answer).
    two_card_combos counts the standalone infinite or game-ending two-card
    combos (none in Brackets 1-2); one that destroys lands is counted in
    mass_land_denial instead."""
    bracket = 1
    if extra_turns:
        bracket = max(bracket, 2)
    if game_changers or two_card_combos:
        bracket = max(bracket, 3)
    if game_changers > UPGRADED_MAX_GAME_CHANGERS or mass_land_denial:
        bracket = 4
    return bracket


def _copies_allowed(card):
    """How many copies card text allows (None: any number), or 1."""
    m = DECK_COPIES_RE.search(card["oracle_text"].lower())
    if m is None or m.group(1) == "only one" or m.group(3):
        return 1
    if m.group(1) == "any number of":
        return None
    word = m.group(2)
    return int(word) if word.isdigit() else NUMBER_WORDS.get(word, 1)


def is_basic(card):
    words = type_words(card["type_line"])
    return "Basic" in words and "Land" in words


def _can_be_commander(card):
    """CR 903.3: a legendary creature card, Vehicle card, or Spacecraft card
    with a power/toughness box, or a card that says it can be your commander
    (903.3a). A legendary card that is a creature everywhere but the
    battlefield ("As long as Grist isn't on the battlefield, it's a 1/1
    Insect creature in addition to its other types") is a creature card in
    the command zone. A Background is only one alongside a commander with
    "Choose a Background" (702.124k; see _pairing)."""
    words = type_words(card["type_line"].split(" // ")[0])
    subs = set(subtypes(card["type_line"]))
    text = card["oracle_text"].lower()
    if "can be your commander" in text:
        return True
    return "Legendary" in words and (
        "Creature" in words or "Vehicle" in subs
        or ("Spacecraft" in subs and card.get("power") is not None)
        or OFF_BATTLEFIELD_CREATURE_RE.search(text) is not None)


def _is_background(card):
    """A legendary Background enchantment card (702.124k)."""
    return {"Legendary", "Enchantment"} <= type_words(card["type_line"]) and "Background" in subtypes(card["type_line"])


def _is_doctor(card):
    """A legendary Time Lord Doctor creature card with no other creature types (702.124m)."""
    return ({"Legendary", "Creature"} <= type_words(card["type_line"])
            and sorted(subtypes(card["type_line"])) == ["Doctor", "Time Lord"])


def _partner_abilities(card):
    """The partner abilities (702.124a) on a card's front face, as {key: the
    ability in words}: ("partner",), ("partner—", text) for partner—[text]
    (702.124i; older printings' "Friends forever" is partner—Friends
    forever), ("partner with", name) (702.124j), ("background",) for Choose
    a Background (702.124k) and ("doctor",) for Doctor's companion (702.124m)."""
    found = {}
    for line in REMINDER_RE.sub("", front_text(card)).split("\n"):
        line = " ".join(line.split())
        if (m := PARTNER_WITH_RE.match(line)):
            found[("partner with", cards.fold(m.group(1)))] = f"partner with {m.group(1)}"
            continue
        if (m := PARTNER_TEXT_RE.match(line)):
            found[("partner—", m.group(1).casefold())] = f"partner—{m.group(1)}"
            continue
        for part in line.split(", "):       # a keyword line may list several
            word = part.strip().casefold().replace("’", "'")
            if word == "partner":
                found[("partner",)] = "partner"
            elif word == "friends forever":
                found[("partner—", "friends forever")] = "partner—Friends forever"
            elif word == "choose a background":
                found[("background",)] = "Choose a Background"
            elif word == "doctor's companion":
                found[("doctor",)] = "Doctor's companion"
    return found


def _pairing(a, b):
    """How two cards can be your two commanders (702.124), or None. Each
    ability pairs only with its own kind (702.124f): partner with partner
    (702.124h); partner—[text] with the same partner—[text] (702.124i);
    partner with [name] when each names the other (702.124j); Choose a
    Background with a legendary Background enchantment card (702.124k);
    Doctor's companion with a legendary Time Lord Doctor creature card that
    has no other creature types (702.124m)."""
    pa, pb = _partner_abilities(a), _partner_abilities(b)
    if ("partner",) in pa and ("partner",) in pb:
        return "partner"
    for key in pa:
        if key[0] == "partner—" and key in pb:
            return pa[key]
    names = {x["name"]: {cards.fold(x["name"]), cards.fold(x["name"].split(" // ")[0])} for x in (a, b)}
    if any(("partner with", n) in pa for n in names[b["name"]]) and \
            any(("partner with", n) in pb for n in names[a["name"]]):
        return "partner with"
    for x, y, px in ((a, b, pa), (b, a, pb)):
        if ("background",) in px and _is_background(y):
            return "background"
        if ("doctor",) in px and {"Legendary", "Creature"} <= type_words(x["type_line"]) and _is_doctor(y):
            return "doctor"
    return None


def _partners(a, b):
    """True when two cards can be your two commanders (see _pairing)."""
    return _pairing(a, b) is not None


def _abilities_in_words(card):
    """'has partner with Krav, the Unredeemed', or 'has no partner ability'."""
    found = list(_partner_abilities(card).values())
    return "has " + (" and ".join(found) if found else "no partner ability")


def _combo_check(by_section):
    """The two-card combos whose pieces are both in the main deck (the
    Commander, Companion and Deck sections; a piece that must be the commander
    only in the Commander section), as bracket["combos"]."""
    names = {}
    for section in ("Deck", "Companion", "Commander"):
        for e in by_section[section]:
            names[e.card["oracle_id"]] = e.name
    try:
        found = combos.find([e.card["oracle_id"] for e in by_section["Commander"]],
                            [e.card["oracle_id"] for e in by_section["Companion"] + by_section["Deck"]],
                            COMBO_FILE)
    except combos.ComboListError as error:
        return {"checked": False, "reason": str(error)}
    matches = []
    for combo in found["matches"]:
        floor = combos.bracket_floor(combo)
        matches.append({"names": [names.get(p["oracle_id"], p["name"]) for p in combo["cards"]],
                        "results": list(combo["results"]), "class": combo["class"],
                        "standalone": combo["standalone"], "raises_floor": floor > 1, "floor": floor,
                        "url": combo["url"]})
    return {"checked": True, "list_date": found["timestamp"], "version": found["version"],
            "matches": matches}


NEAR_MAX = 100      # near combos sent at most (E9-S25); "total" says how many there were


def _near_combo_check(by_section, identity, counts, minimum, tags):
    """The two-card combos the main deck is one card away from (E9-S25), as bracket["near_combos"]:
    {"checked": True, "matches": [...], "total"}, at most NEAR_MAX, most serious first, or None when
    the list can't be read (the complete check already says so). The missing piece must fit the
    commander's colour identity (identity: a set of colour letters) and be legal in Commander (the
    ban list, from the card data); a piece Deck Lab has no card for is left out too. Each match
    says what the deck's minimum bracket would be with the piece added ("minimum_with"): its
    combo's floor, plus the card itself as a Game Changer, mass land denial or extra turn (tags:
    cards.tag_members' sets, or None when they couldn't be read). counts: (Game Changer names,
    mass land denial, extra turns, infinite combos) as the deck's minimum counted them."""
    names = {}
    for section in ("Deck", "Companion", "Commander"):
        for e in by_section[section]:
            names[e.card["oracle_id"]] = e.name
    try:
        found = combos.find([e.card["oracle_id"] for e in by_section["Commander"]],
                            [e.card["oracle_id"] for e in by_section["Companion"] + by_section["Deck"]],
                            COMBO_FILE, near=True)
    except combos.ComboListError:
        return None
    game_changers, n_mld, n_extra, n_infinite = counts
    matches = []
    for combo in found["matches"]:
        piece = combo["cards"][combo["missing"]]
        name = cards.resolve(piece["name"])
        card = cards.card(name) if name else None
        if (card is None or set(card.get("color_identity", [])) - identity
                or card.get("commander_legality") != "legal"):
            continue
        floor = combos.bracket_floor(combo)
        oracle_id = card["oracle_id"]
        with_it = min_bracket(len(game_changers | ({name} if card.get("game_changer") else set())),
                              n_mld + (floor == 4) + bool(tags and oracle_id in tags[MASS_LAND_DENIAL_TAG]),
                              n_extra + bool(tags and oracle_id in tags[EXTRA_TURN_TAG]),
                              n_infinite + (floor == 3))
        matches.append({"names": [name if p is piece else names.get(p["oracle_id"], p["name"])
                                  for p in combo["cards"]],
                        "missing": name, "results": list(combo["results"]), "class": combo["class"],
                        "standalone": combo["standalone"], "floor": floor, "url": combo["url"],
                        "minimum_with": with_it, "raises_minimum": with_it > minimum})
    return {"checked": True, "matches": matches[:NEAR_MAX], "total": len(matches)}


def _commander_checks(by_section, sections, unresolved, warnings):
    commanders = by_section["Commander"]
    companions = by_section["Companion"]
    in_deck = commanders + by_section["Deck"]
    problems, problem_cards = [], []        # each problem, and the card names it's about

    def problem(text, names=()):
        problems.append(text)
        problem_cards.append(list(dict.fromkeys(names)))

    n_commanders = sum(e.qty for e in commanders) + sum(q for (s, _), q in unresolved.items()
                                                       if s == "Commander")
    size = decks.card_count(sections)
    size_ok = size == COMMANDER_SIZE
    if not size_ok:
        cards_text = f"{size} card{'' if size == 1 else 's'}"
        problem(f"{cards_text} with the commander{'s' if n_commanders > 1 else ''}; a Commander deck "
                f"has exactly 100." if n_commanders else
                f"{cards_text}; a Commander deck has exactly 100, its commander included.")

    eligibility, eligibility_cards = [], []
    def ineligible(text, names=()):
        eligibility.append(text)
        eligibility_cards.append(list(names))

    if n_commanders == 0:
        ineligible("There's no Commander section.")
    pairing = _pairing(commanders[0].card, commanders[1].card) if len(commanders) == 2 else None
    for e in commanders:
        if _is_background(e.card):
            if pairing != "background":
                ineligible(f"{e.name} is a Background: it can only be a commander alongside a "
                           f"commander that has \"Choose a Background\".", [e.name])
        elif not _can_be_commander(e.card):
            ineligible(f"{e.name} can't be a commander: it isn't a legendary creature, "
                       f"Vehicle or Spacecraft with power and toughness, and doesn't say "
                       f"it can be.", [e.name])
    if n_commanders > 2:
        ineligible(f"{n_commanders} commanders; a deck can have at most two.",
                   [e.name for e in commanders] + [n for (s, n) in unresolved if s == "Commander"])
    elif len(commanders) == 2 and pairing is None and not any(_is_background(e.card) for e in commanders):
        a, b = commanders           # (a Background's own warning above says what it needs)
        ineligible(f"{a.name} and {b.name} can't be commanders together: {a.name} "
                   f"{_abilities_in_words(a.card)}, and {b.name} {_abilities_in_words(b.card)}. "
                   f"Two commanders need matching partner abilities.", [a.name, b.name])
    for text, names in zip(eligibility, eligibility_cards):
        problem(text, names)

    # Singleton (CR 903.5b), by resolved name; unresolved names by their text.
    copies, written = Counter(), {}         # written: unresolved names as the list has them
    for e in in_deck:
        copies[e.name] += e.qty
    for (section, name), qty in unresolved.items():
        if section in ("Commander", "Deck"):
            copies[cards.fold(name)] += qty
            written.setdefault(cards.fold(name), []).append(name)
    by_name = {e.name: e.card for e in in_deck}
    duplicates, allowed = [], []
    for name, n in sorted(copies.items()):
        card = by_name.get(name)
        if n < 2:
            continue
        if card is not None and is_basic(card):
            continue
        limit = _copies_allowed(card) if card is not None else 1
        if limit is None or n <= limit:
            allowed.append({"name": name, "copies": n,
                            "rule": "any number" if limit is None else f"up to {limit}"})
        else:
            duplicates.append({"name": name, "copies": n, "limit": limit})
            problem(f"{n} copies of {name}; " + (
                "a Commander deck has one of each card." if limit == 1 else f"its text allows {limit}."),
                written.get(name, [name]) if card is None else [name])
    for e in companions:
        if e.name in copies:
            duplicates.append({"name": e.name, "copies": copies[e.name] + e.qty, "limit": 1})
            problem(f"The companion {e.name} is also in the deck; it can only be in one place.", [e.name])

    # Colour identity (CR 903.4, 903.5c).
    identity = set()
    for e in commanders:
        identity.update(e.card.get("color_identity", []))
    outside = []
    if commanders:
        for e in by_section["Deck"] + companions:
            extra = set(e.card.get("color_identity", [])) - identity
            if extra:
                outside.append({"name": e.name, "colour_identity": colour_label(e.card["color_identity"]),
                                "outside": colour_label(extra)})
        if outside:
            problem(f"{len(outside)} card{'s' if len(outside) != 1 else ''} outside the "
                    f"commander's colour identity ({colour_words(identity)}): "
                    + ", ".join(o["name"] for o in outside) + ".", [o["name"] for o in outside])

    # Ban list and legality.
    banned = [e for e in in_deck + companions if e.card.get("commander_legality") == "banned"]
    banned_companion = [e for e in companions if e.name in BANNED_AS_COMPANION]
    not_legal = [e for e in in_deck + companions if e.card.get("commander_legality") == "not_legal"]
    if banned:
        names = sorted({e.name for e in banned})
        problem("Banned in Commander: " + ", ".join(names) + ".", names)
    for e in banned_companion:
        problem(f"{e.name} is banned as a companion (it's fine in the deck or as the commander).", [e.name])
    if not_legal:
        names = sorted({e.name for e in not_legal})
        problem("Not legal in Commander (Bracket 1 may allow them if the other players agree): "
                + ", ".join(names) + ".", names)

    # Brackets.
    game_changers = [e for e in in_deck if e.card.get("game_changer")]
    try:
        tags = cards.tag_members([MASS_LAND_DENIAL_TAG, EXTRA_TURN_TAG], TAG_FILE)
        mld = [e for e in in_deck if e.card["oracle_id"] in tags[MASS_LAND_DENIAL_TAG]]
        extra_turns = [e for e in in_deck if e.card["oracle_id"] in tags[EXTRA_TURN_TAG]]
    except (OSError, KeyError, ValueError) as error:
        warnings.append(f"Scryfall's oracle tags couldn't be read ({error}), so mass land denial "
                        f"and extra turns weren't counted for the bracket.")
        mld = extra_turns = tags = None
    two_card = _combo_check(by_section)
    found = two_card["matches"] if two_card["checked"] else []
    infinite_combos, land_combos = ([" + ".join(m["names"]) for m in found if m["floor"] == floor]
                                    for floor in (3, 4))
    n_gc = len({e.name for e in game_changers})
    cards_bracket = min_bracket(n_gc, len(mld or []), len(extra_turns or []))
    bracket = min_bracket(n_gc, len(mld or []) + len(land_combos), len(extra_turns or []),
                          len(infinite_combos))
    reasons = []
    if n_gc:
        reasons.append(f"{n_gc} Game Changer{'s' if n_gc != 1 else ''} (Brackets 1-2 allow none, "
                       f"Bracket 3 up to {UPGRADED_MAX_GAME_CHANGERS}): "
                       + ", ".join(sorted({e.name for e in game_changers})))
    if mld:
        reasons.append("Mass land denial (not allowed in Brackets 1-3): "
                       + ", ".join(sorted({e.name for e in mld})))
    if extra_turns:
        reasons.append("Extra turns (none in Bracket 1; a few, never chained, in 2-3): "
                       + ", ".join(sorted({e.name for e in extra_turns})))
    if infinite_combos:
        what = ("a two-card combo that goes infinite or ends" if len(infinite_combos) == 1
                else f"{len(infinite_combos)} two-card combos that go infinite or end")
        reasons.append(f"Holds both pieces of {what} the game (none in Brackets 1-2): "
                       + ", ".join(infinite_combos))
    if land_combos:
        what = ("a two-card combo that destroys" if len(land_combos) == 1
                else f"{len(land_combos)} two-card combos that destroy")
        reasons.append(f"Holds both pieces of {what} lands (mass land denial, not allowed in "
                       f"Brackets 1-3): " + ", ".join(land_combos))
    if not reasons and mld is not None:
        reasons.append("No Game Changers, mass land denial or extra turns.")
    elif not reasons:
        reasons.append("No Game Changers.")
    if mld is None:
        reasons.append("Mass land denial and extra turns weren't counted (no tag data).")
    if not two_card["checked"]:
        reasons.append("Two-card combos weren't checked (the combo list can't be read).")
        warnings.append(f"{two_card['reason']}, so two-card combos weren't checked for the bracket.")

    near = None
    if two_card["checked"] and commanders:
        near = _near_combo_check(by_section, identity,
                                 ({e.name for e in game_changers}, len(mld or []) + len(land_combos),
                                  len(extra_turns or []), len(infinite_combos)), bracket, tags)

    answer = {
        "ok": not problems,
        "problems": problems,
        "problem_cards": problem_cards,
        "commanders": [e.name for e in commanders],
        "colour_identity": colour_label(identity),
        "size": {"cards": size, "expected": COMMANDER_SIZE, "ok": size_ok,
                 "companion": sum(e.qty for e in companions),
                 "note": "Commander + Deck; a companion sits outside the 100 (CR 903.5a, 903.11)."},
        "eligibility": {"ok": not eligibility, "problems": eligibility, "problem_cards": eligibility_cards},
        "singleton": {"ok": not duplicates, "duplicates": duplicates, "allowed": allowed},
        "identity": {"ok": not outside, "outside": outside, "checked": bool(commanders)},
        "legality": {"ok": not (banned or banned_companion or not_legal),
                     "banned": card_list(banned), "banned_as_companion": card_list(banned_companion),
                     "not_legal": card_list(not_legal), "source": "banned-list"},
        "bracket": {
            "minimum": bracket, "cards_minimum": cards_bracket, "label": BRACKET_LABELS[bracket],
            "reasons": reasons,
            "data": _data_dates(two_card.get("list_date")),
            "unknown_cards": sorted({name for section, name in unresolved
                                     if section in ("Commander", "Deck", "Companion")}),
            "game_changers": card_list(game_changers),
            "mass_land_denial": None if mld is None else card_list(mld),
            "extra_turns": None if extra_turns is None else card_list(extra_turns),
            "combos": two_card,
            "not_automatic": list(BRACKET_NOT_AUTOMATIC),
            "brackets": [dict(b) for b in BRACKETS],
            "sources": ["wizards-commander", "brackets-2025-02", "brackets-2025-10",
                        "brackets-2026-02", "tagger", "commander-spellbook"]},
    }
    if near is not None:        # only beside a combo list that could be read, and a commander
        answer["bracket"]["near_combos"] = near
    return answer
