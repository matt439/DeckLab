"""Build one reviewed Play-now proposal from a saved Commander deck's own inventory."""
from functools import cache

from decklab.lib import cards, decks, pool
from decklab.lib.decks import play_now

from . import drafts, guard
from .card_lookup import _default_printing, _line_json, _resolve
from .common import MAX_NAME, ApiError, _keys, _parse_body, _sha
from .settings import _writer
from .swaps import _deck, _space_pool

MAX_BODY = 96 * 1024
MAX_COPIES = 250  # a Commander list with room for a companion, sideboard and unfinished drafts


def _source(raw, deck):
    """Validate the edited list using the normal line reader, keeping row positions for review."""
    if not isinstance(raw, dict) or not raw or any(s not in decks.SECTIONS for s in raw):
        raise ApiError(400, "Send a list to check for stand-ins.")
    if any(not isinstance(lines, list) for lines in raw.values()) or sum(map(len, raw.values())) > MAX_COPIES:
        raise ApiError(400, f"Use a list of up to {MAX_COPIES} cards.")
    draft = drafts._Draft(deck.kind, drafts._known(deck.target, deck.owned), deck.space)
    sections = {}
    for section, lines in raw.items():
        sections[section] = parsed = []
        for index, value in enumerate(lines):
            if not isinstance(value, dict):
                raise ApiError(400, "Each card line must be an object.")
            line = drafts._read_line(draft, value, {"list": "owned", "section": section, "index": index})
            if line is not None:
                exact = _resolve(line.name)
                if exact is None:
                    raise ApiError(400, "Check the list's unknown card names before looking for stand-ins.")
                line.name = exact
                parsed.append(line)
    if draft.blocks:
        raise drafts._blocks_error(draft.blocks)
    count = sum(line.quantity for lines in sections.values() for line in lines)
    if not 1 <= count <= MAX_COPIES:
        raise ApiError(400, f"Use a list of up to {MAX_COPIES} cards.")
    if not sections.get("Commander"):
        raise ApiError(400, "Choose the deck's commander before looking for stand-ins.")
    return sections


def _locked(raw, sections):
    if not isinstance(raw, list) or len(raw) > MAX_COPIES:
        raise ApiError(400, "Send the names of cards to keep in the list.")
    names = {line.name for lines in sections.values() for line in lines}
    locked = set()
    for value in raw:
        exact = _resolve(value) if isinstance(value, str) and 0 < len(value) <= MAX_NAME else None
        if exact not in names:
            raise ApiError(400, "Each locked card must be in the list.")
        locked.add(exact)
    return locked


def preview(body):
    """POST /api/deck/play-now/preview. Same-space, editable deck; no writes or reservations."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "sha256", "list"), ("locked",))
    summary, deck = _deck(data["id"])
    guard.require(profile, "deck.edit", summary)
    if deck.kind != "commander":
        raise ApiError(400, "Drafting from free copies is available for saved Commander decks.")
    if _sha(data["sha256"]) != deck.sha256:
        raise ApiError(409, "The saved deck changed. Reopen the editor before reviewing stand-ins.")
    source = _source(data["list"], deck)
    locked = _locked(data.get("locked", []), source)
    warnings = []
    p = _space_pool(deck.space, warnings)
    if warnings or p.warnings or p.unresolved:
        raise ApiError(409, "Some collection records need checking before free copies can be confirmed.")
    physical = pool.physical_free_copies(p, pool.free_copies(p, pool.self_ids(summary["id"])))
    counts = {key: {"owned": row["owned"]} for key, row in drafts._visible_counts(deck.space).items()
              if row.get("owned")}

    @cache
    def paper(name):
        return _default_printing(name, counts)

    shortages, proposal = play_now.propose(source, physical, cards.card, locked, paper)
    from decklab.lib.stats import deck_rules
    checks = deck_rules(proposal, "commander")
    bracket = (checks.get("commander") or {}).get("bracket")
    return {"deck_id": summary["id"], "sha256": deck.sha256, "rows": [
        {**row, "unfilled": row["missing"] - len(row["adds"]),
         "adds": [{"line": _line_json(added, row["section"], []), "note": note} for added, note in row["adds"]]}
        for row in shortages], "checks": checks["problems"],
        "bracket": {"minimum": bracket["minimum"], "target": deck.target_bracket} if bracket else None}
