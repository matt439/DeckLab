"""A group run (E3-S31, closing E3-S19's criterion 2): a house deck against a chosen group of
other house decks, such as a space member's Public decks.

A group run is a field run (field.run_field) whose opponents are the chosen decks
(opponent_entries) instead of the whole field, as the gauntlet's run is (gauntlet.run), but its
games go to the ORDINARY results folder: each pair is an ordinary matchup under its own key, so
the games count in Rankings, the ratings and per-card stats like any field run's. Its note goes
to the field's notes file with a "group" part (the chosen lists), which field.last_note leaves
out, so the field view's "last run" stays the last whole-field run.

The view is the gauntlet's overall group (gauntlet._group, the equal-weight average of the
opponents, with its range and spread) over the chosen decks, plus one row per opponent, hardest
first. There's no rating here: field.view has it, over the whole field.

    MAX_OPPONENTS               the most decks a group may have
    house_entry(deck_id, version=None)
                                a house deck's Forge entry: the version given, else the list the
                                field plays (its Built version when built, else its target list)
    check(entry, opponents)     the chosen entries, checked (ValueError with a sentence)
    plan(entry, opponents, budget="standard", results_dir=None, keep=None)
                                field.plan over the group
    run(entry, opponents, budget="standard", *, by, progress=None, results_dir=None, space="home", ...)
                                field.run_field over the group; its note
    view(entry, opponents, results_dir=None, keep=None)
                                the deck against the group (it never plays a game)

Callers check visibility first: every chosen deck must be one the viewer may see (the page's API
answers a hidden one as a missing deck). Nothing here reads who may see what."""
from decklab.lib import decks

from . import field, gauntlet, lists

MAX_OPPONENTS = 12
NOTE_KEY = "group"
NONE = "Choose at least one deck for the group."
TOO_MANY = "A group has at most {n} decks."
TWICE = "{title} is in the group twice."
SELF = "{title} can't be in its own group."
SAME_LIST = "{title} has exactly this deck's list, so it can't be in its group."
WRONG_FORMAT = "{title} plays {other}, but this deck plays {fmt}."
CAVEAT = "This average covers these {m} chosen decks only, not the whole field."
LABEL = "All these decks"


def house_entry(deck_id, version=None):
    """A house deck's Forge entry: version ("target" or "owned"), else the list the field plays
    (field._house_version: its Built version when it's built, else the target list). ValueError
    for a deck that doesn't exist, can't be read or has no such list."""
    summary = decks.find_summary(deck_id)
    if summary is None or summary.get("error"):
        raise ValueError(f"No deck {deck_id!r}")
    version = version or field._house_version(summary)
    if version not in summary.get("versions", []):
        raise ValueError(f"{deck_id} has no {version} list")
    try:
        return field._entry(summary, version)
    except (decks.DeckNotFound, decks.DeckFileError) as e:
        raise ValueError(f"{deck_id} can't be read: {e}") from None


def check(entry, opponents):
    """The chosen entries as a list, in their order. ValueError (a sentence naming only the decks
    given) for none, more than MAX_OPPONENTS, one listed twice, the deck itself, a list identical to
    it (a mirror, which field._opponents would drop) or one of the other format."""
    chosen = list(opponents or ())
    if not chosen:
        raise ValueError(NONE)
    if len(chosen) > MAX_OPPONENTS:
        raise ValueError(TOO_MANY.format(n=MAX_OPPONENTS))
    fmt = lists.fmt_for(entry["kind"])
    seen = set()
    for o in chosen:
        if field._same_id(o["id"], entry["id"]):
            raise ValueError(SELF.format(title=o["title"]))
        if entry.get("card_sha") and o.get("card_sha") == entry["card_sha"]:
            raise ValueError(SAME_LIST.format(title=o["title"]))
        other = lists.fmt_for(o["kind"])
        if other != fmt:
            raise ValueError(WRONG_FORMAT.format(title=o["title"], other=other, fmt=fmt))
        if (o["id"], o["version"]) in seen or any(field._same_id(o["id"], i) for i, _ in seen):
            raise ValueError(TWICE.format(title=o["title"]))
        seen.add((o["id"], o["version"]))
    return chosen


def _who(chosen):
    return [{"id": o["id"], "version": o["version"]} for o in chosen]


def plan(entry, opponents, budget="standard", results_dir=None, keep=None):
    """What a group run would play now (nothing plays): field.plan's answer over the group."""
    return field.plan(entry, budget, results_dir=results_dir, keep=keep, opponent_entries=check(entry, opponents))


def run(entry, opponents, budget="standard", *, by, progress=None, results_dir=None, space="home", **options):
    """Play entry against the group (field.run_field with the chosen decks as its opponents, into
    the ordinary results folder results_dir): its note, which has "group" (the chosen lists).
    options are run_field's others (pool, local, seed_base, log_dir, log_every, inflight, keep).
    ValueError as check's and for a budget that isn't one, ForgeError as run_field's."""
    chosen = check(entry, opponents)
    return field.run_field(entry, budget, by=by, progress=progress, results_dir=results_dir, space=space,
                           opponent_entries=chosen, note_extra={NOTE_KEY: _who(chosen)}, **options)


def _opponent(o, row):
    return {"id": o["id"], "version": o["version"], "title": o["title"], "kind": o["kind"],
            "card_sha": o.get("card_sha"), "key": row["key"], "games": row["n"],
            "rate": gauntlet._rate(row["numbers"]), "lead": row["lead"], "verdict": gauntlet.verdict(row["lead"]),
            "not_meaningful": row["not_meaningful"], "problem": row["problem"], "updated": row.get("updated")}


def view(entry, opponents, results_dir=None, keep=None):
    """entry against the group, from saved games only: {"deck": {"id", "version", "title",
    "card_sha"}, "format", "opponents": [rows, hardest first (lowest range low; those without
    games last)], "overall" (gauntlet._group's row over every chosen deck: the equal-weight
    average, its range, spread and note), "played" (decks with games), "of", "tally"
    (gauntlet._tally), "updated" (the newest row's, or None), "games", "note" (the caveat)}.
    keep(result), when given, is False for a saved result to leave out. ValueError as check's."""
    chosen = check(entry, opponents)
    rows = field._rows(entry, chosen, results_dir, keep)
    members = list(zip(chosen, rows))
    out = [_opponent(o, row) for o, row in members]
    out.sort(key=lambda o: (o["rate"] is None, (o["rate"] or {}).get("low") or 0, o["title"].casefold()))
    dates = [o["updated"] for o in out if isinstance(o.get("updated"), str)]
    return {"deck": {k: entry.get(k) for k in ("id", "version", "title", "card_sha")},
            "format": lists.fmt_for(entry["kind"]), "opponents": out,
            "overall": gauntlet._group("all", LABEL, members), "played": sum(1 for r in rows if r["n"]),
            "of": len(rows), "tally": gauntlet._tally(out), "updated": max(dates) if dates else None,
            "games": sum(r["n"] for r in rows), "note": CAVEAT.format(m=len(rows))}
