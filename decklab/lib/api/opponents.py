"""Usual opponents: one deck's metadata save and visibility-filtered reciprocal read links."""
from decklab.lib import decks, inventory, permissions, spaces

from . import common, deck_aliases, guard
from .commits import _conflict, _deck_file, _parse_file, _stored
from .common import ApiError, _keys, _parse_body, _public
from .library import _find_summary, check_deck_id, is_half
from .saving import _deck_refused, apply_op
from .settings import _writer

MAX_OPPONENTS = 64


def _space(summary):
    return summary.get("space", spaces.HOME)


def _catalog(summaries=None):
    listed = list(decks.list_decks() if summaries is None else summaries)
    listed.extend(decks.beginner_box_pairings())
    return {item["id"]: item for item in listed
            if not item.get("error") and item.get("versions") and not is_half(item)}


def _declared(summary):
    stored = inventory.current().deck(summary["id"])
    if stored is None or stored.error is not None:
        return []
    try:
        parsed = decks.parse_deck(stored.data, stored.slug, stored.kind, space=stored.space)
    except decks.DeckFileError:
        return []
    return list(dict.fromkeys(inventory.resolve_deck_id(other)
                             for other in decks.parse_usual_opponents(parsed.get_field(decks.USUAL_OPPONENTS_FIELD))))


def _relations(summaries=None):
    catalog = _catalog(summaries)
    sees = guard.deck_reader()
    visible = {deck_id: item for deck_id, item in catalog.items() if sees(item)}
    declared = {deck_id: [other for other in _declared(item)
                          if other != deck_id and other in visible and _space(visible[other]) == _space(item)]
                for deck_id, item in visible.items()}
    related = {deck_id: list(others) for deck_id, others in declared.items()}
    for deck_id in sorted(visible, key=lambda item: (visible[item]["title"].casefold(), item)):
        for other in declared[deck_id]:
            if deck_id not in related[other]:
                related[other].append(deck_id)
    return visible, declared, related


def usual_opponent_ids(summaries=None):
    """Visible reciprocal ids, including synthetic pairings absent from the library rows."""
    return _relations(summaries)[2]


def add_usual_opponents(summaries, related=None):
    """Add resolved reciprocal ids to library/packing choices, never raw hidden references."""
    related = usual_opponent_ids(summaries) if related is None else related
    for item in summaries:
        item["usual_opponents"] = related.get(item["id"], [])
    return summaries


def usual_opponents(deck_id, summaries=None):
    """Visible existing same-space reciprocal links, with titles for a deck's Overview."""
    deck_id = inventory.resolve_deck_id(deck_id)
    visible, _, related = _relations(summaries)
    return [{"id": item, "title": visible[item]["title"]} for item in related.get(deck_id, [])]


def _visible_summary(deck_id):
    check_deck_id(deck_id)
    guard.require_sees_deck(deck_id)        # a hidden deck answers as a missing one (E10-S30)
    summary = _find_summary(deck_id)
    if not guard.sees_deck(summary):
        raise guard.no_deck(deck_id)
    return summary


def opponents_view(deck_id=None):
    """GET /api/deck/opponents?id: declarations, reciprocal-only links and same-space choices.

    ``opponents`` contains only visible declarations. Saving replaces those visible
    choices, retaining existing hidden declarations and pruning deleted references.
    Product decks/pairings may receive reciprocal links but cannot record metadata.
    """
    with common.state_errors():
        summary = _visible_summary(deck_id)
        visible, declared, related = _relations()
        space, kind, _ = spaces.split_deck_id(summary["id"])
        editable = kind in decks.KINDS and not summary.get("read_only")
        why = permissions.reason(guard.viewer(), "deck.edit", summary, script=guard.script()) if editable else \
            "Product decks and pairings keep their published lists."
        editable = editable and why is None
        stored = inventory.current().deck(summary["id"])
        chosen = declared.get(summary["id"], [])
        choices = [{"id": other, "title": item["title"]} for other, item in visible.items()
                   if other != summary["id"] and _space(item) == space]
        choices.sort(key=lambda item: (item["title"].casefold(), item["id"]))
        return deck_aliases.metadata({"id": summary["id"], "title": summary["title"],
                "sha256": stored.sha256 if stored else None,
                "opponents": chosen, "choices": choices, "editable": editable, "why_not": why,
                "inherited": [{"id": other, "title": visible[other]["title"]}
                              for other in related.get(summary["id"], [])
                              if summary["id"] in declared.get(other, [])]}, deck_id, summary["id"])


def _chosen(value, summary, catalog):
    if not isinstance(value, list) or len(value) > MAX_OPPONENTS:
        raise ApiError(400, f"opponents must be a list of up to {MAX_OPPONENTS} deck ids")
    chosen = []
    for deck_id in value:
        check_deck_id(deck_id)
        deck_id = inventory.resolve_deck_id(deck_id)
        if deck_id not in catalog and deck_id.startswith("pairing/"):
            found = decks.find_summary(deck_id)
            deck_id = found["id"] if found is not None else deck_id
        other = catalog.get(deck_id)
        if other is None or not guard.sees_deck(other) or _space(other) != _space(summary):
            raise ApiError(400, "Choose an available opponent in this deck's space.")
        if deck_id == summary["id"]:
            raise ApiError(400, "A deck can't be its own usual opponent.")
        if deck_id not in chosen:
            chosen.append(deck_id)
    return chosen


def save_opponents(body):
    """POST {profile,id,sha256,opponents:[ids]}: one permissioned deck.save, no counterpart writes."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "sha256", "opponents"))
    with common.state_errors():
        deck_aliases.reject_alias(data["id"], profile)
        summary = _visible_summary(data["id"])
        kind, slug, path = _deck_file(summary["id"])
        stored = _stored(summary["id"], viewer=profile)
        deck = _parse_file(stored.data, kind, slug, path, summary["id"])
        guard.require(profile, "deck.edit", deck)
        if not isinstance(data["sha256"], str) or not common._SHA_RE.fullmatch(data["sha256"]):
            raise ApiError(400, "sha256 must be the deck's 64-character text hash")
        if data["sha256"] != stored.sha256:
            raise _conflict(summary["id"], deck.title, viewer=profile)
        catalog = _catalog()
        chosen = _chosen(data["opponents"], summary, catalog)
        hidden = [other for other in _declared(summary)
                  if other in catalog and other != summary["id"] and _space(catalog[other]) == deck.space
                  and not guard.sees_deck(catalog[other])]
        try:
            decks.set_usual_opponents(deck, [*chosen, *hidden])
            text = decks.render_deck_file(deck)
        except (decks.DeckFileError, ValueError) as error:
            raise ApiError(400, f"The usual opponents can't be written: {_public(error)}") from None
        if text != stored.text:
            operation = inventory.Op("deck.save", {"deck_id": summary["id"], "text": text,
                                                   "base_sha256": stored.sha256})
            after, _ = apply_op(operation, profile, f"choose the usual opponents of {deck.title}",
                                _deck_refused(summary["id"], deck.title, profile))
            held = after.deck(summary["id"])
        else:
            held = stored
        return {"ok": True, "saved": text != stored.text, "sha256": held.sha256,
                "usual_opponents": usual_opponents(summary["id"])}
