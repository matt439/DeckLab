"""A suggested count for each token a deck makes (E7-S08): the card log's per-game peaks (the
most of a token on the battlefield at once, cardlog.py), pooled over the list's saved Forge
results (forge/tokenpeaks.py), matched to the deck's needs by name. Part of decklab.lib.tokens
(see its docstring); the deck page's Tokens part shows it (lib/api/token_peaks.py), only to
the viewers who see the rest of that part.

Forge logs a token by its name as it prints it ("Rabbit Token"; a token copy of a card has the
card's name), so a need matches a logged name that is its name or one of its face names, with
or without " Token" after it, ignoring case and accents. Two needs with one name (two kinds of
Soldier) can't be told apart: both get that name's counts, saying so. Only tokens are counted:
an emblem or reminder never reaches the battlefield, and the Copy need is anything copied. A
token the cards' text gives only to the opponent lands on the other side, among that deck's own
tokens, so it gets no count either.

It's an estimate from simulated games: Forge's AI plays the list, not the household, and its
opponents are the saved matchups'. Nothing here is a purchase or a claim of what a game needs.
"""
from decklab.lib import cards

PEAK_CAP = 30                   # cardlog.PEAK_CAP: a peak of this many also counts the games above it
MOST_SHARE = (9, 10)            # "most games": the fewest that 9 in 10 of the games that made one stayed at or under
NOTE = ("Suggested counts come from Deck Lab's simulated Forge games of this list: the most of each token on the "
        "battlefield at once in a game. Forge's AI isn't you and its opponents are the saved matchups', so "
        "they're estimates. Forge names a token by its name only, so tokens with the same name count together.")
NO_GAMES = "No suggested counts: this list has no saved Forge games. Play its matchups to get them."
UNTALLIED = ("No suggested counts yet: this list's {games} saved Forge games were played before Deck Lab "
             "counted tokens. Play its matchups again to get them.")
OTHER_ENGINE = ("No suggested counts yet: this list's {games} saved Forge games were played with an earlier "
                "Forge engine. Play its matchups again to get them.")
OLDER = ("No suggested counts yet: this list's {games} saved Forge games were played with an earlier Forge "
         "engine or before Deck Lab counted tokens. Play its matchups again to get them.")


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _base(name):
    """A logged name folded, without its " Token" ("Rabbit Token" -> "rabbit")."""
    folded = cards.fold(name).strip()
    return folded[:-len(" token")].rstrip() if folded.endswith(" token") else folded


def _keys(need):
    return {cards.fold(n).strip() for n in [need.get("name") or "", *(need.get("face_names") or [])] if n}


def _counted(need):
    return (need.get("kind", "token") == "token" and need.get("side") != "opponent"
            and cards.fold(need.get("name") or "") != "copy")


def _most(peaks, made):
    """The fewest k with at least MOST_SHARE of the made games peaking at k or under."""
    share, out_of = MOST_SHARE
    running = 0
    for k, n in enumerate(peaks, 1):
        running += n
        if running * out_of >= made * share:
            return k
    return len(peaks)


def _words(found):
    if not found["games"]:
        return f"No Forge game of the {found['of']} put one on the battlefield"
    def shown(n):
        return f"{n} or more" if n >= PEAK_CAP else str(n)
    words = (f"Forge games peaked at {shown(found['peak'])}; most games at most {shown(found['most'])} "
             f"({_plural(found['games'], 'game')} of {found['of']} made one)")
    if found["together"]:
        words += f"; every {found['name']} token counted together"
    if found["more"]:
        words += f" · {found['more']} more than the cards that fit"
    return words


def annotate(result, pooled):
    """A copy of deck_tokens' result with "forge": {"games", "matchups", "untallied", "note"} when
    pooled (forge.tokenpeaks.list_token_peaks) counted games, else {"games": 0, "why"} (no saved
    games: NO_GAMES; only games before the tally: UNTALLIED; only another engine's: OTHER_ENGINE;
    both of those: OLDER); and, with games, each counted need
    (_counted) with "forge": {"name", "games" (games that made one), "of", "peak", "most", "together"
    (another need has its name), "more" (most less the cards that fit, "usable", at least 0),
    "words"}. A result without needs comes back as it is; the cached result is never changed."""
    needs = result.get("needs") if isinstance(result, dict) else None
    if not needs:
        return result
    out = dict(result)
    if not pooled or not pooled.get("games"):
        untallied = (pooled or {}).get("untallied", 0)
        other = (pooled or {}).get("other_engine_games", 0)
        why = (OLDER if untallied and other else UNTALLIED if untallied else OTHER_ENGINE if other else None)
        out["forge"] = {"games": 0, "why": why.format(games=untallied + other) if why else NO_GAMES}
        return out
    games = pooled["games"]
    out["forge"] = {"games": games, "matchups": pooled.get("matchups", 0), "untallied": pooled.get("untallied", 0),
                    "note": NOTE}
    logged = {}
    for name, peaks in pooled.get("tokens", {}).items():
        logged.setdefault(_base(name), []).append(peaks)
    names = [cards.fold(n.get("name") or "").strip() for n in needs if _counted(n)]
    annotated = []
    for need in needs:
        if not _counted(need):
            annotated.append(need)
            continue
        # One name logged two ways (a rare "Rabbit" beside "Rabbit Token"): the one more games made.
        candidates = [peaks for key in _keys(need) for peaks in logged.get(key, [])]
        peaks = max(candidates, key=sum, default=[])
        made = sum(peaks)
        found = {"name": need["name"], "games": made, "of": games, "peak": len(peaks) if made else 0,
                 "most": _most(peaks, made) if made else 0,
                 "together": names.count(cards.fold(need["name"]).strip()) > 1}
        found["more"] = max(found["most"] - int(need.get("usable") or 0), 0)
        found["words"] = _words(found)
        annotated.append(dict(need, forge=found))
    out["needs"] = annotated
    return out
