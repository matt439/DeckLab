"""A precon's fixed bonus cards: explicit choices, checked against a cached source receipt.

Only a preview may fetch MTGJSON's set file. A save reads the kept extract and refuses
an absent or changed source; the ordinary collection receipt still protects the write.
"""
import hashlib
import json

from decklab.lib import precons, sealed
from decklab.lib.inventory import rules

from . import collection_edit as ce
from .common import ApiError, _public


def stale():
    return ApiError(409, "The published list or bonus-card source changed or is unavailable. Preview it again before adding it.",
                    bonus_conflict=True)


def offer(entry, data, existing, *, fetch=False, choices=None, source_sha256=None):
    """Public source rows plus this space's owned/default choices; selected CSV rows separately.

    choices is a page's list of one-based source rows, the CLI's include/skip, or None
    for a preview's defaults. Its hash covers row order and the random-content wording.
    """
    try:
        found = sealed.contents(entry, data, fetch=fetch)
    except precons.PreconError as error:
        raise ApiError(502, _public(error)) from None
    if found is None:
        raise stale()
    encoded = json.dumps([entry["file"], entry["type"], precons.cards_of(data), found],
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    receipt = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if source_sha256 is not None and source_sha256 != receipt:
        raise stale()
    fixed = found.get("fixed") or []
    if len(fixed) > precons.MAX_COUNT:
        raise ApiError(502, "The precon lists too many bonus cards to review safely.")
    if choices not in (None, "include", "skip"):
        if not isinstance(choices, list) or len(choices) > len(fixed) or any(
                not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= len(fixed) for n in choices) \
                or len(set(choices)) != len(choices):
            raise ApiError(400, "bonus_choices must list each selected bonus source row once")
    rows, selected = [], []
    for index, card in enumerate(fixed, 1):
        raw = {"name": card["name"], "set": card["set"], "collector_number": card["number"],
               "finish": card["finish"], "quantity": str(card["count"]), "condition": "", "language": "",
               "notes": f"bonus card in {entry['name']}"}
        owned = sum(int(row["quantity"]) for row in existing if rules.ident(row) == rules.ident(raw))
        _, problem = ce.match(raw)
        checked = (not owned and not problem) if choices is None else (
            choices == "include" or isinstance(choices, list) and index in choices)
        rows.append({"source_row": index, "name": card["name"], "set": card["set"], "number": card["number"],
                     "finish": card["finish"], "qty": card["count"], "owned": owned, "selected": checked,
                     "problem": problem, "words": sealed.describe(card)})
        if checked:
            selected.append(raw)
    random = list(found.get("random") or [])
    notes = [note for note in precons.notes(entry["type"]) if not (random or fixed) or note != precons.RANDOM_NOTE]
    if entry["type"] in precons.PRODUCT_TYPES:
        notes = [note for note in notes if note != precons.RANDOM_NOTE]
    if random:
        notes.append("Also in the box: " + "; ".join(random) + " (random, not added).")
    varies = [sealed.describe(card) for card in found.get("varies") or []]
    if varies:
        notes.append("Varies by box, not added: " + "; ".join(varies) + ".")
    return {"source_sha256": receipt, "rows": rows}, selected, notes
