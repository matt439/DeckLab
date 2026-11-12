"""GET /api/official-changes: the Game Changer and Commander ban changes the last card data update found, and
the viewer's Commander decks that hold them (E9-S36), for the Decks page's read-only panel.

    {"change": None}        no change has been kept (or the file can't be read: never "no change")
    {"change": {"recorded_at", "old_date", "new_date"},
     "cards": [{"name", "kind" (official_lists.CHANGE_KINDS), "words",
                "now": {"game_changer", "banned"} or None (today's card data; None for a card it lacks),
                "decks": [{"id", "title", "status", "version", "target_bracket", "minimum", "label"}]}],
     "unread": N}           Commander decks the viewer may see whose lists couldn't be read

cards update keeps the change (official_lists.record_changes, beside the card index). A deck holds a card when
the list it's played from (a built deck's Built version, else its Planned list) has it in its Commander,
Companion or Deck section; "minimum" is that list's counted minimum bracket on today's card data
(stats.deck_rules, as the editor's bracket box counts it), None when it can't be worked out. Only the
library's Commander decks the viewer may see (guard.deck_reader, E10-S30) are read, a Commander product's
decks among them (home's): a hidden deck is never named or counted, and a trial of a precon not owned
(E3-S39) isn't one of ours. The cards themselves are
public card data. Nothing is written or fetched.
"""
import csv

from decklab.lib import cards, decks, official_lists

from . import guard
from .carddata import _require_cards

HOLDING = ("Commander", "Companion", "Deck")
CHANGES_FILE = None     # None: official_lists.changes_path(); the tests point it at a fixture


def _version(summary):
    """The list a deck is played from: a built deck's Built version, else its Planned list."""
    if summary.get("status") == "built" and summary.get("built_version") == "owned" \
            and "owned" in (summary.get("versions") or ()):
        return "owned"
    return "target"


def _held(sections):
    """The exact card names in a list's Commander, Companion and Deck sections."""
    found = set()
    for section in HOLDING:
        for line in sections.get(section, ()):
            exact = cards.resolve(line.name)
            if exact:
                found.add(exact)
    return found


def _minimum(sections):
    """(minimum, label) of a Commander list on today's card data, or (None, None)."""
    from decklab.lib.stats import deck_rules       # when first needed, as the other parts import stats
    try:
        bracket = deck_rules(sections, "commander")["commander"]["bracket"]
        return bracket["minimum"], bracket["label"]
    except (KeyError, TypeError, ValueError):
        return None, None


def _flags_today(name):
    card = cards.card(name)
    if card is None:
        return None
    return {"game_changer": bool(card.get("game_changer")), "banned": card.get("commander_legality") == "banned"}


def _commander_decks(sees):
    """The viewer's Commander decks, by title: [(summary, version, sections)], and how many couldn't be read."""
    found, unread = [], 0
    for summary in decks.list_decks():
        if summary.get("kind") != "commander" or summary.get("trial") or not sees(summary):
            continue
        if summary.get("error"):
            unread += 1
            continue
        version = _version(summary)
        try:
            sections = decks.load_deck(summary["id"], version)
        except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError, csv.Error):
            unread += 1
            continue
        found.append((summary, version, sections))
    found.sort(key=lambda item: ((item[0].get("title") or "").casefold(), item[0]["id"]))
    return found, unread


def view():
    """GET /api/official-changes (the module docstring)."""
    sees = guard.deck_reader()
    change = official_lists.read_changes(CHANGES_FILE)
    if change is None:
        return {"change": None}
    _require_cards()
    names = {c["name"] for c in change["changes"]}
    holding = {name: [] for name in names}
    found, unread = _commander_decks(sees)
    for summary, version, sections in found:
        held = _held(sections) & names
        if not held:
            continue
        minimum, label = _minimum(sections)
        entry = {"id": summary["id"], "title": summary.get("title") or summary["id"],
                 "status": summary.get("status"), "version": version,
                 "target_bracket": summary.get("target_bracket"), "minimum": minimum, "label": label}
        for name in held:
            holding[name].append(entry)
    return {"change": {key: change[key] for key in ("recorded_at", "old_date", "new_date")},
            "cards": [{"name": c["name"], "kind": c["kind"], "words": official_lists.CHANGE_WORDS[c["kind"]],
                       "now": _flags_today(c["name"]), "decks": holding[c["name"]]} for c in change["changes"]],
            "unread": unread}
