"""The gauntlet's precon source (design section 3): Wizards' Commander precons, the Bracket 2
anchor tier.

MTGJSON's lists come through lib/precons.py (its own cache and politeness): deck_list() filtered
to "Commander Deck", newest first, then deck() and cards_of() for each of the NEWEST newest. When
MTGJSON can't be had at all, Forge's own res/quest/commanderprecons files stand in
(forge_source.commander_precons), under the same ids: MTGJSON's file name is the deck's name
without its spaces and punctuation, then "_" and the set code ("WretchedRanks_FDC"), and a Forge
file names the deck and its set ("Wretched Ranks [FDC] [2024]").
"""
import re

from decklab.lib import precons

from . import forge_source, slug

NEWEST = 60
TYPE = "Commander Deck"


def mtgjson_stem(name, code):
    """MTGJSON's file name for a deck called name in set code: "Wretched Ranks", "fdc" ->
    "WretchedRanks_FDC"."""
    return re.sub(r"[^A-Za-z0-9]", "", name) + "_" + code.upper()


def _record(file, title, released, url, fetched, rank, commanders, main, problems, kind="mtgjson"):
    return {"id": f"gauntlet:precon/{file}", "title": title, "kind": "commander", "tier": "precon",
            "source": {"kind": kind, ("url" if kind == "mtgjson" else "file"): url, "fetched": fetched,
                       "rank": rank, "decks": None},
            "released": released, "commanders": commanders, "cards": main, "themes": [], "problems": problems}


def _from_mtgjson(listed, newest, log):
    chosen = [d for d in listed["decks"] if d["type"] == TYPE][:newest]
    records, excluded = [], []
    for rank, d in enumerate(chosen, 1):
        deck_id = f"gauntlet:precon/{d['file']}"
        try:
            read = precons.cards_of(precons.deck(d["file"]))
        except (precons.PreconError, LookupError) as e:
            excluded.append((deck_id, f"MTGJSON's list couldn't be had ({e})"))
            continue
        commanders = [line["name"] for line in read["lines"] if line["section"] == "Commander"]
        main = [[line["count"], line["name"]] for line in read["lines"] if line["section"] == "Deck"]
        records.append(_record(d["file"], d["name"], d["released"], precons.DECK_URL.format(d["file"]),
                               listed["date"] or None, rank, commanders, main, list(read["problems"])))
    log(f"MTGJSON: {len(records)} Commander precons")
    return records, excluded


def _from_forge(root, newest, log):
    """The commander precons from Forge's own files (newest first by the year in their names)."""
    found = forge_source.commander_precons(root)
    found.sort(key=lambda d: (d["year"], d["set"], d["title"]), reverse=True)
    records = []
    for rank, d in enumerate(found[:newest], 1):
        stem = mtgjson_stem(d["title"], d["set"]) if d["set"] else slug(d["stem"])
        records.append(_record(stem, d["title"], str(d["year"] or ""), d["file"], None, rank,
                               [n for _, n in d["cards"]["Commander"]], d["cards"]["Main"], [], kind="forge"))
    log(f"Forge's commander precons, standing in for MTGJSON's: {len(records)}")
    return records


def decks(newest=NEWEST, offline=False, root=None, log=print):
    """(records, excluded): the newest Commander precons as raw source records. offline (a dry
    run) still reads precons.py's cache, which fetches only what's out of date: so a dry run
    uses Forge's files instead and fetches nothing."""
    listed = None
    if not offline:
        try:
            listed = precons.deck_list()
        except precons.PreconError as e:
            log(f"MTGJSON's deck list couldn't be had ({e}); Forge's commander precons stand in.")
    if listed is not None:
        return _from_mtgjson(listed, newest, log)
    try:
        return _from_forge(root, newest, log), []
    except OSError as e:
        return [], [("gauntlet:precon", f"Forge's commander precons couldn't be read ({e})")]
