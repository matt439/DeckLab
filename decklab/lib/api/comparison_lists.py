"""Intrinsic list-only Compare sides: no collection, kit, simulation or state-store reads."""
from decklab.lib import decks, precons
from . import deck_aliases
from .card_lookup import _lines_json
from .carddata import _require_cards
from .common import ApiError, _public
from .deck_page import _deck_stats
from .library import _deck_sections


def snapshot(sections, summary, version="target", comparison=None):
    """The cards and today's list-derived stats, never a deck's prose, kit or availability."""
    warnings = []
    kind = decks.engine_kind(summary)
    lines = _lines_json(sections, warnings)
    result = _deck_stats(sections, kind, warnings)
    unrecognised = any(line.get("card") is None for rows in lines.values() for line in rows)
    unknown = result is None or bool(result.get("unresolved")) or unrecognised
    note = ("Stats are unknown because this list has cards the current index doesn't recognize."
            if unrecognised or result is not None and result.get("unresolved") else
            "Stats are unknown because they couldn't be worked out." if unknown else None)
    answer = {"summary": {key: summary.get(key) for key in ("id", "title", "kind", "format", "colors")},
              "version": version, "versions": [version], "sections": lines,
              "stats": None if unknown else result, "stats_kind": kind, "stats_unknown": unknown, "stats_note": note, "warnings": warnings}
    if comparison is not None:
        answer["comparison"] = comparison
    return answer


def current_view(deck_id=None, version="target"):
    requested = deck_id
    deck_id = deck_aliases.canonical_id(deck_id)  # hidden404 before version validation
    _require_cards()
    try:
        summary, sections = _deck_sections(deck_id, version)
    except ApiError as error:
        if error.status == 500:
            raise ApiError(500, "This deck's list couldn't be read safely.") from None
        raise
    answer = snapshot(sections, summary, version)
    answer["versions"] = list(summary.get("versions") or [version])
    return deck_aliases.metadata(answer, requested, summary["id"])


def precon_view(file=None):
    """Public MTGJSON list, explicitly picked; it never creates or searches for a household deck."""
    from .precons import _entry
    _require_cards()
    entry = _entry(file)
    try:
        read = precons.cards_of(precons.deck(entry["file"]))
    except precons.PreconError as error:
        raise ApiError(502, _public(error)) from None
    except LookupError:
        raise ApiError(404, "That published precon isn't listed") from None
    if read["problems"]:
        raise ApiError(502, "The published precon's complete list couldn't be read. Try again later.")
    has_commander = any(line["section"] == "Commander" for line in read["lines"])
    kind = "commander" if entry["type"] == "Commander Deck" and has_commander else "casual"
    sections = {}
    for line in read["lines"]:
        section = "Deck" if kind != "commander" and line["section"] == "Commander" else line["section"]
        sections.setdefault(section, []).append(decks.DeckLine(line["count"], line["name"], line["set"], line["number"], line["finish"]))
    return snapshot(sections, {"id": None, "title": entry["name"], "kind": kind,
                              "format": "Commander" if kind == "commander" else "Published precon", "colors": None},
                    comparison={"kind": "precon", "file": entry["file"], "label": f"Published precon: {entry['name']}",
                                "bracket_note": "Bracket judged using today's card data and Commander lists."})
