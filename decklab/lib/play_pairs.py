"""Tonight's pairs (E1-S28): up to three ready pairs of home's built casual decks, one deck for each
home player, ranked by how evenly they're matched and how long since they last met, each with plain
reasons. Pure: the caller (lib/api/play_tonight.py) gives it only decks, games and Forge results the
viewer may see, so nothing here reads the database, the pool or Forge.

    suggest(decks, games, forge_pairs, today, limit=3)
        decks       [{"id", "title", "player" (user, wife or either), "status", "kind", "ready", "version"
                    (its built list, passed through)}]: only
                    built casual decks with "ready" true take part (a deck missing cards for its built
                    list, or whose availability can't be confirmed, isn't ready).
        games       [{"date": ISO date, "sides": [deck id, deck id], "result": "a", "b" or "draw"}]: real
                    two-player games, any lists of the two decks.
        forge_pairs {(deck id, deck id): {"value": the first's win share or None, "games"}}: saved Forge
                    results of the decks' built lists (either order is enough; the caller drops a
                    result of any other list).
        today       ISO date, for "days ago".

Each pair is {"sides": [{"id", "title", "version", "seat"}, ...] (seat "user" then "wife": the deck each player
takes), "evenness": {"band", "source", "share", "games", "forge_games"}, "last_played", "days",
"reasons"}. The band is "even" (the first side's share within 10 points of 50%), "fair" (within 20),
"uneven" or "unknown"; the source is "real" when the two decks have met at least MINIMUM_GAMES times
(the real record decides), else "forge" when Forge has a result, else None. share is the first side's,
draws counting half.

Ranking: the band (even, fair, unknown, then uneven), then the pair never met or met longest ago,
then whichever's decks were played longest ago, then the closer share, then the titles. A deck is
used in one suggestion while another pair without it is left, so three suggestions show more choice.
"""
from datetime import date

MINIMUM_GAMES = 10              # play_comparison's: fewer real games can't decide evenness
EVEN, FAIR = 0.10, 0.20         # how far from 50% a share may be for each band
LIMIT = 3
SEATS = ("user", "wife")
BAND_ORDER = {"even": 0, "fair": 1, "unknown": 2, "uneven": 3}
BAND_WORDS = {"even": "Evenly matched", "fair": "Fairly even", "uneven": "One-sided"}


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _eligible(deck):
    return (deck.get("kind") == "casual" and deck.get("status") == "built" and deck.get("ready") is True
            and deck.get("player") in ("user", "wife", "either") and isinstance(deck.get("id"), str))


def _fits(deck, seat):
    return deck["player"] in (seat, "either")


def _oriented(x, y):
    """(user's deck, wife's deck) for two decks, or None when no seating fits. Of two seatings, the one
    where more decks sit with the player they're Played by (not "either"); else x first."""
    options = [(a, b) for a, b in ((x, y), (y, x)) if _fits(a, "user") and _fits(b, "wife")]
    if not options:
        return None
    return max(options, key=lambda pair: (pair[0]["player"] == "user") + (pair[1]["player"] == "wife"))


def _record(games, a, b):
    """The real record of a against b: (a's wins, b's wins, draws, last date or None)."""
    wins, draws, last = [0, 0], 0, None
    for game in games:
        sides = game.get("sides") or []
        if len(sides) != 2 or {sides[0], sides[1]} != {a, b} or a == b:
            continue
        last = max(last or game["date"], game["date"])
        if game.get("result") == "draw":
            draws += 1
        elif game.get("result") in ("a", "b"):
            winner = sides[0] if game["result"] == "a" else sides[1]
            wins[0 if winner == a else 1] += 1
    return wins[0], wins[1], draws, last


def _forge(forge_pairs, a, b):
    """(a's Forge share, games) or None."""
    found = forge_pairs.get((a, b))
    if found and found.get("value") is not None:
        return found["value"], found.get("games") or 0
    found = forge_pairs.get((b, a))
    if found and found.get("value") is not None:
        return 1 - found["value"], found.get("games") or 0
    return None


def _band(share):
    if share is None:
        return "unknown"
    off = abs(share - 0.5)
    return "even" if off <= EVEN + 1e-9 else "fair" if off <= FAIR + 1e-9 else "uneven"


def _days(today, day):
    return None if day is None else (date.fromisoformat(today) - date.fromisoformat(day)).days


def _when(days):
    if days is None:
        return "Not played against each other yet."
    if days <= 0:
        return "Last played against each other today."
    return f"Last played against each other {_plural(days, 'day')} ago."


def _pair(user, wife, games, forge_pairs, today):
    a, b = user["id"], wife["id"]
    won, lost, draws, last = _record(games, a, b)
    played = won + lost + draws
    forge = _forge(forge_pairs, a, b)
    reasons = []
    if played >= MINIMUM_GAMES:
        source, share = "real", (won + draws / 2) / played
        band = _band(share)
        reasons.append(f"{BAND_WORDS[band]} in {_plural(played, 'real game')}: {user['title']} "
                       f"{_plural(won, 'win')}, {wife['title']} {_plural(lost, 'win')}"
                       + (f", {_plural(draws, 'draw')}." if draws else "."))
    elif forge is not None:
        source, share = "forge", forge[0]
        band = _band(share)
        reasons.append(f"{BAND_WORDS[band]} by Forge: {user['title']} wins {round(share * 100)}% of "
                       f"{_plural(forge[1], 'simulated game')}.")
        if played:
            reasons.append(f"Only {_plural(played, 'real game')} so far, too few to go by.")
    else:
        source, share, band = None, None, "unknown"
        reasons.append("How even it is isn't known yet: "
                       + (f"only {_plural(played, 'real game')} and no Forge result."
                          if played else "no real games or Forge result."))
    days = _days(today, last)
    reasons.append(_when(days))
    return {"sides": [{"id": a, "title": user["title"], "version": user.get("version"), "seat": "user"},
                      {"id": b, "title": wife["title"], "version": wife.get("version"), "seat": "wife"}],
            "evenness": {"band": band, "source": source, "share": None if share is None else round(share, 4),
                         "games": played, "forge_games": forge[1] if forge else None},
            "last_played": last, "days": days, "reasons": reasons}


def _deck_last(games):
    last = {}
    for game in games:
        for deck_id in game.get("sides") or []:
            last[deck_id] = max(last.get(deck_id, game["date"]), game["date"])
    return last


def suggest(decks, games, forge_pairs, today, limit=LIMIT):
    """Up to limit pairs, best first (the module docstring)."""
    ready = sorted((d for d in decks if _eligible(d)), key=lambda d: (str(d.get("title")).casefold(), d["id"]))
    games = [g for g in games or [] if isinstance(g, dict) and isinstance(g.get("date"), str)]
    forge_pairs = forge_pairs or {}
    deck_last = _deck_last(games)
    pairs = []
    for i, x in enumerate(ready):
        for y in ready[i + 1:]:
            seated = _oriented(x, y)
            if seated:
                pairs.append(_pair(*seated, games, forge_pairs, today))

    def rank(pair):
        ids = [side["id"] for side in pair["sides"]]
        share = pair["evenness"]["share"]
        return (BAND_ORDER[pair["evenness"]["band"]], pair["last_played"] or "", max(deck_last.get(i, "") for i in ids),
                abs(share - 0.5) if share is not None else 1, [side["title"].casefold() for side in pair["sides"]])
    pairs.sort(key=rank)
    chosen, used = [], set()
    for pair in pairs:              # first, pairs whose decks no earlier suggestion takes
        ids = {side["id"] for side in pair["sides"]}
        if len(chosen) < limit and not ids & used:
            chosen.append(pair)
            used |= ids
    for pair in pairs:              # then the best of the rest
        if len(chosen) < limit and pair not in chosen:
            chosen.append(pair)
    return sorted(chosen, key=rank)
