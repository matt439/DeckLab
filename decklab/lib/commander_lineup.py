"""A Commander night line-up (E9-S34): home's Commander decks sorted against the recorded night's
bracket aim and published range, so a deck that fits the pod can be picked without opening every
deck page. Pure: the caller (lib/api/commander_lineup.py) works each deck's counted minimum out
(lib/stats/commander.py) and passes only decks and facts the viewer may see, so nothing here reads
the database, the card data or the Game log.

    lineup(entries, night, today)
        entries [{"id", "title", "status" (idea, building or built), "version" (the list judged: a built
                deck's built list, else "target"), "trial", "target_bracket", "bracket" (the stats'
                commander bracket: "minimum", "game_changers", "mass_land_denial" and "extra_turns" (each
                [{"name"}] or [names], None when the tags couldn't be read), "combos" ({"checked",
                "matches": [{"names", "floor"}]}), "unknown_cards"), or None), "unknown" (a sentence:
                why the checks didn't give an answer, such as running out of time; else None),
                "last_played" (ISO date or None), "played_known" (False when the Game log couldn't be
                read), and, only for viewers who may see them, "stand_ins" ([{"for", "using", "qty"}])
                and "box_checked_on" (ISO date or None)}]
        night   the recorded night ({"name", "venue", "target_bracket", "published_min",
                "published_max", ...}) or None
        today   ISO date, for "days ago"

Returns {"night": the night's name, venue, aim and range or None, "limit": the highest bracket that
fits (the aim and the range's top, the lower of the two recorded; None when neither is), "basis": a
sentence saying where the limit comes from, "groups": {"fits", "above", "unknown"}: rows, "counts"}.

A deck fits when its counted minimum is at or below the limit; it's above when its minimum is
higher, naming the cards that decide it ("deciding": [{"reason", "cards"}]: the rule each card's
group breaks at the limit); it's unknown, never fitting, when there's no night or the night records
neither an aim nor a range, when its bracket couldn't be worked out, or when the card data, the oracle
tags or the combo list couldn't be read for it (an unknown card name, tags or combos not read). An
unknown row still says what was counted so far ("minimum_so_far": the floor from what could be read,
which can only rise). Trials and retired decks never take part. The counted minimum counts only what
the bracket rules name (Game Changers, mass land denial, extra turns, two-card combos), never a deck's
real power or intent: the page says so.

Each row is {"id", "title", "status", "built", "version", "target_bracket", "minimum",
"below_range" (its minimum is under the published range's bottom), "deciding", "unknown_reason",
"minimum_so_far", "last_played", "days_since_played", "played_known"}, plus "stand_ins" and
"box_checked_on" when the entry had them. Fits list built decks first, then the highest minimum
(closest to the limit), then the title; above, the lowest minimum first; unknown, built first, by
title.
"""
from datetime import date

GROUPS = ("fits", "above", "unknown")
BRACKETS = range(1, 6)
UPGRADED_MAX_GAME_CHANGERS = 3      # stats.constants': Bracket 3 allows up to 3 Game Changers

NO_NIGHT = "No Commander night is recorded, so no deck can be judged against it."
NO_AIM = "The recorded night has no bracket aim or published range, so no deck can be judged against it."
NO_BRACKET = "Its minimum bracket couldn't be worked out."
NO_TAGS = "Scryfall's oracle tags couldn't be read, so mass land denial and extra turns weren't counted."
NO_COMBOS = "The two-card combo list couldn't be read, so combos weren't counted."


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _bracket_number(value):
    return value if type(value) is int and value in BRACKETS else None


def _night_view(night):
    if not isinstance(night, dict):
        return None
    return {"name": night.get("name") or "", "venue": night.get("venue") or "",
            "target_bracket": _bracket_number(night.get("target_bracket")),
            "published_min": _bracket_number(night.get("published_min")),
            "published_max": _bracket_number(night.get("published_max")),
            "checked_on": night.get("checked_on") or ""}


def limit_of(night):
    """(the highest bracket that fits, a sentence saying why), or (None, why not)."""
    shown = _night_view(night)
    if shown is None:
        return None, NO_NIGHT
    aim, top = shown["target_bracket"], shown["published_max"]
    if aim is None and top is None:
        return None, NO_AIM
    if aim is not None and top is not None and top < aim:
        return top, f"The venue's published range tops out at Bracket {top}, below the household's Bracket {aim} aim."
    if aim is not None:
        return aim, f"The household aims for Bracket {aim} at this night."
    return top, f"No household aim is recorded; the venue's published range tops out at Bracket {top}."


def _names(rows):
    """Card names of a stats list ([{"name"}] or [names]), or None when it couldn't be counted."""
    if rows is None:
        return None
    found = []
    for row in rows:
        name = row.get("name") if isinstance(row, dict) else row
        if isinstance(name, str) and name and name not in found:
            found.append(name)
    return found


def _combos(bracket):
    """[(names, floor)] of the two-card combos, or None when the combo list couldn't be read."""
    combos = bracket.get("combos")
    if not isinstance(combos, dict) or combos.get("checked") is not True:
        return None
    found = []
    for match in combos.get("matches") or []:
        if isinstance(match, dict) and match.get("floor") in (3, 4):
            found.append((_names(match.get("names") or []), match["floor"]))
    return found


def deciding(bracket, limit):
    """The groups of cards that put a deck's counted minimum above limit: [{"reason", "cards"}]."""
    gc = _names(bracket.get("game_changers")) or []
    mld = _names(bracket.get("mass_land_denial")) or []
    turns = _names(bracket.get("extra_turns")) or []
    combos = _combos(bracket) or []
    groups = []
    if turns and limit < 2:
        groups.append({"reason": "Extra turns (none in Bracket 1)", "cards": sorted(turns)})
    if gc and (limit < 3 or (limit == 3 and len(gc) > UPGRADED_MAX_GAME_CHANGERS)):
        groups.append({"reason": f"{_plural(len(gc), 'Game Changer')} (none in Brackets 1-2)" if limit < 3 else
                       f"{_plural(len(gc), 'Game Changer')} (Bracket 3 allows up to {UPGRADED_MAX_GAME_CHANGERS})",
                       "cards": sorted(gc)})
    infinite = [names for names, floor in combos if floor == 3]
    if infinite and limit < 3:
        groups.append({"reason": "Two-card combos that go infinite or end the game (none in Brackets 1-2)",
                       "cards": [" + ".join(names) for names in infinite]})
    if mld and limit < 4:
        groups.append({"reason": "Mass land denial (not allowed in Brackets 1-3)", "cards": sorted(mld)})
    land = [names for names, floor in combos if floor == 4]
    if land and limit < 4:
        groups.append({"reason": "Two-card combos that destroy lands (not allowed in Brackets 1-3)",
                       "cards": [" + ".join(names) for names in land]})
    return groups


def _unknown_reasons(bracket):
    """Why a worked-out bracket still can't say a deck fits: the data it couldn't read."""
    reasons = []
    unknown = bracket.get("unknown_cards") or []
    if unknown:
        named = ", ".join(sorted(unknown)[:5]) + ("…" if len(unknown) > 5 else "")
        verb = "isn't" if len(unknown) == 1 else "aren't"
        reasons.append(f"{_plural(len(unknown), 'card name')} {verb} in the card data, so the minimum isn't "
                       f"known: {named}.")
    if bracket.get("mass_land_denial") is None or bracket.get("extra_turns") is None:
        reasons.append(NO_TAGS)
    if _combos(bracket) is None:
        reasons.append(NO_COMBOS)
    return reasons


def _days(today, day):
    try:
        return (date.fromisoformat(today) - date.fromisoformat(day)).days
    except (TypeError, ValueError):
        return None


def _row(entry, today):
    built = entry.get("status") == "built"
    row = {"id": entry["id"], "title": entry.get("title") or entry["id"], "status": entry.get("status"),
           "built": built, "version": entry.get("version") or "target",
           "target_bracket": _bracket_number(entry.get("target_bracket")), "minimum": None, "below_range": False,
           "deciding": [], "unknown_reason": None, "minimum_so_far": None,
           "last_played": entry.get("last_played"), "days_since_played": None,
           "played_known": entry.get("played_known", True) is not False}
    if row["last_played"]:
        row["days_since_played"] = _days(today, row["last_played"])
    for key in ("stand_ins", "box_checked_on"):
        if key in entry:
            row[key] = entry[key]
    return row


def _eligible(entry):
    return (isinstance(entry, dict) and isinstance(entry.get("id"), str) and not entry.get("trial")
            and not entry.get("retired") and entry.get("kind", "commander") == "commander")


def lineup(entries, night, today, *, night_unavailable=None):
    """The line-up (the module docstring). night_unavailable is a sentence when the night couldn't be
    read: no deck is then judged, and that sentence says why."""
    if night_unavailable:
        night, (limit, basis) = None, (None, night_unavailable)
    else:
        limit, basis = limit_of(night)
    shown = _night_view(night)
    groups = {group: [] for group in GROUPS}
    for entry in entries or []:
        if not _eligible(entry):
            continue
        row = _row(entry, today)
        bracket = entry.get("bracket") if isinstance(entry.get("bracket"), dict) else None
        minimum = _bracket_number(bracket.get("minimum")) if bracket else None
        if entry.get("unknown"):
            row["unknown_reason"] = entry["unknown"]
        elif minimum is None:
            row["unknown_reason"] = NO_BRACKET
        else:
            missing = _unknown_reasons(bracket)
            if missing:
                row["unknown_reason"] = " ".join(missing)
                row["minimum_so_far"] = minimum
            else:
                row["minimum"] = minimum
        if row["unknown_reason"] is None and limit is None:
            row["unknown_reason"] = basis
        if row["unknown_reason"] is not None:
            groups["unknown"].append(row)
            continue
        low = shown["published_min"] if shown else None
        row["below_range"] = low is not None and minimum < low
        if minimum <= limit:
            groups["fits"].append(row)
        else:
            row["deciding"] = deciding(bracket, limit)
            groups["above"].append(row)
    def title(row):
        return row["title"].casefold(), row["id"]
    groups["fits"].sort(key=lambda row: (not row["built"], -row["minimum"], title(row)))
    groups["above"].sort(key=lambda row: (row["minimum"], not row["built"], title(row)))
    groups["unknown"].sort(key=lambda row: (not row["built"], title(row)))
    return {"night": shown, "limit": limit, "basis": basis, "groups": groups,
            "counts": {group: len(rows) for group, rows in groups.items()}}
