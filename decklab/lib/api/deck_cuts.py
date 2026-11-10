"""Countable Commander cut evidence, including a bounded unsaved draft preview. No writes or fetches."""
from decklab.lib import cards, decks, edhrec, spaces
from . import common, deck_aliases, drafts, guard
from .card_lookup import _card_json, _shown_printing
from .carddata import _require_cards
from .common import ApiError, MAX_NAME, MAX_QTY, NUMBER_RE, SET_RE, _CONTROL_RE, _keys, _parse_body
from .library import _find_summary

MAX_BODY = common.MAX_EDIT_BODY       # the same bounded list payload as the editor, without fields/prose


def _saved(deck_id):
    deck_id = deck_aliases.canonical_id(deck_id)
    summary = _find_summary(deck_id)
    if spaces.split_deck_id(deck_id)[1] != "commander":
        raise ApiError(400, "Cuts are for Commander decks.")
    return deck_id, summary


def _forge_facts(sections):
    """The established per-card result visibility filter, before any private evidence is pooled."""
    from .forge_runs import _Seen, _forge_module
    try:
        forge = _forge_module()
        seen = _Seen()
        return forge.list_cards(sections, "commander", keep=lambda result: seen.result(forge, result))
    except Exception:
        return None                 # optional evidence never prevents a user from reviewing their list


def _result(deck_id, sections, commanders=None, *, page=None, forge_stats=None, draft=False):
    try:
        answer = edhrec.cuts(deck_id, sections=sections, commanders=commanders, page=page, forge_stats=forge_stats)
    except edhrec.UnknownPage:
        raise ApiError(400, "Choose a page offered by the cached commander page.") from None
    except edhrec.NotCommander:
        raise ApiError(400, "Choose a commander before reviewing cuts.") from None
    except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError):
        raise ApiError(500, "This deck's cut evidence couldn't be read safely.") from None
    deck = answer.pop("deck")
    profile = guard.viewer()
    may_edit = deck is not None and profile is not None and guard.allowed(profile, "deck.edit", deck)
    # Raw text receipts include private kit/table changes; only the existing editor boundary needs one.
    answer.update(deck_id=deck_id, sha256=deck.sha256 if may_edit else None, draft=draft, may_edit=may_edit)
    for group in answer["groups"]:
        for row in group["cards"]:
            card = cards.card(row["name"])
            row["card"] = _card_json(card, _shown_printing(card)) if card else None
    return answer


def cuts_view(deck_id=None, page=None):
    deck_id, _summary = _saved(deck_id)       # hidden404 before page/list/card validation
    from .edhrec import _page
    page = _page(page)
    _require_cards()
    try:
        deck, _names = edhrec._deck(deck_id)
    except edhrec.NotCommander:
        raise ApiError(400, "Choose a commander before reviewing cuts.") from None
    except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError):
        raise ApiError(500, "This deck's list couldn't be read safely.") from None
    return _result(deck_id, deck.target, page=page, forge_stats=_forge_facts(deck.target))


def _sections(value):
    """A list-only preview keeps printing/category intent, without assigning defaults or consulting a pool."""
    if not isinstance(value, dict) or set(value) - {"Commander", "Deck", "Companion"}:
        raise ApiError(400, "sections must contain the Planned Commander, Deck and optional Companion lists")
    result = {}
    for section, lines in value.items():
        if not isinstance(lines, list) or len(lines) > drafts.MAX_LINES:
            raise ApiError(400, "A preview section has too many card lines")
        result[section] = []
        for line in lines:
            if not isinstance(line, dict):
                raise ApiError(400, "Give each preview card as a card line")
            _keys(line, ("name", "qty"), ("set", "number", "finish", "category"))
            name, qty = line["name"], line["qty"]
            if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or _CONTROL_RE.search(name):
                raise ApiError(400, "Give a valid preview card name")
            if type(qty) is not int or not 1 <= qty <= MAX_QTY:
                raise ApiError(400, f"Preview quantities must be whole numbers from 1 to {MAX_QTY}")
            set_code, number = line.get("set") or None, line.get("number") or None
            if set_code is not None and (not isinstance(set_code, str) or not SET_RE.fullmatch(set_code)):
                raise ApiError(400, "Give a valid preview set code")
            if number is not None and (not isinstance(number, str) or not NUMBER_RE.fullmatch(number)):
                raise ApiError(400, "Give a valid preview collector number")
            finish = line.get("finish") or "nonfoil"
            if finish not in common.LINE_FINISHES:
                raise ApiError(400, "Give a valid preview finish")
            category = line.get("category") or None
            if category is not None and (not isinstance(category, str) or len(category) > 80 or _CONTROL_RE.search(category)):
                raise ApiError(400, "Give a valid preview category")
            result[section].append(decks.DeckLine(qty, name.strip(), set_code, number, finish, category))
    return result


def preview_cuts(body):
    data = _parse_body(body, MAX_BODY)
    deck_id = data.get("id")
    if deck_id is not None:
        deck_id, summary = _saved(deck_id)   # hidden404 before any draft fields are validated
        space = summary.get("space") or spaces.split_deck_id(deck_id)[0]
    else:
        if guard.viewer() is None and not guard.script():
            raise ApiError(403, "Choose a profile before reviewing a draft.")
        space = drafts._new_space(data, guard.viewer())
    _keys(data, ("sections",), ("id", "space", "page", "profile"))
    if deck_id and data.get("space") not in (None, space):
        raise ApiError(400, "The draft must stay in its deck's space")
    from .edhrec import _page
    page = _page(data.get("page"))
    _require_cards()
    sections = _sections(data["sections"])
    commanders = list(dict.fromkeys(cards.resolve(line.name) or line.name for line in sections.get("Commander", [])))
    if not 1 <= len(commanders) <= 2:
        raise ApiError(400, "Choose one or two commanders before reviewing cuts.")
    # Only exact current lists get Forge evidence. A partial/changed draft never borrows old games.
    evidence = None
    if deck_id:
        deck, _names = edhrec._deck(deck_id, commanders)
        current = {key: deck.target[key] for key in ("Commander", "Deck", "Companion") if deck.target.get(key)}
        if {key: rows for key, rows in sections.items() if rows} == current:
            evidence = _forge_facts(sections)
    return _result(deck_id, sections, commanders, page=page, forge_stats=evidence, draft=True)
