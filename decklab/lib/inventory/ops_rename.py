"""A title and ID rename, without rewriting the rest of a saved deck's bytes."""
import re

from decklab.lib.state import Invalid, Unavailable

from . import Summary, register
from .aliases import deck_lineage
from .ops_decks import DeckRefused, _current, _parse, parsed_deck

MIGRATE = "Renaming decks needs the database migration: python -m decklab.db migrate"
MAX_TITLE = 100


def _namespace(deck_id):
    from decklab.lib import decks
    try:
        space, _, slug = decks.split_id(deck_id)
        return space, slug.lower()
    except (TypeError, ValueError):
        return None


def reserved(inv, space, slug):
    """A former ID whose slug may not name an unrelated newly created deck."""
    return next((old for old in inv.deck_aliases if _namespace(old) == (space, slug.lower())), None)


def title_text(text, title):
    """Replace just the first H1's text, keeping BOM, prefix and line ending."""
    first = re.match(r"(\ufeff*# )[^\r\n]*(.*)", text, re.DOTALL)
    if first is None:
        raise Invalid("The deck's first line must be its title heading")
    return first[1] + title + first[2]


@register("deck.rename")
def rename(inv, *, deck_id, new_slug, title, base_sha256, revision):
    from decklab.lib import decks
    if not inv.aliases_ready:
        raise Unavailable(MIGRATE)
    held = _current(inv, deck_id, base_sha256)
    if type(revision) is not int or revision < 1:
        raise Invalid("Give the saved deck's revision before renaming it")
    if held.revision != revision:
        raise DeckRefused(f"{deck_id} changed after you opened it.", 409, "changed", [deck_id])
    if not isinstance(title, str) or title != decks.clean_title(title) or not 1 <= len(title) <= MAX_TITLE:
        raise Invalid(f"Give a deck title of 1 to {MAX_TITLE} characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in title):
        raise Invalid("A deck title cannot contain control characters")
    if not decks.valid_slug(new_slug) or new_slug != decks.title_slug(title):
        raise Invalid("The new deck id must be the slug derived from its title")
    current = _parse(held.id, held.text, held.space, held.kind, held.slug, parsed_deck(held))
    moved = held.replace(slug=new_slug, text=title_text(held.text, title))
    lineage = set(deck_lineage(deck_id, inv))
    for claimed in set(inv.decks) | set(inv.deck_aliases) | set(inv.deck_history_ids):
        if claimed not in lineage and _namespace(claimed) == (held.space, new_slug.lower()):
            raise DeckRefused("That deck id is already used by another deck or its history.", 409, "exists", [claimed])
    _parse(moved.id, moved.text, moved.space, moved.kind, moved.slug, current)
    if moved.id == held.id and moved.text == held.text:
        return inv, Summary("Nothing to change")
    moved = moved.replace(rename_version=held.rename_version + 1)
    aliases = dict(inv.deck_aliases)
    if moved.id != held.id:
        aliases = {alias: moved.id if target == held.id else target for alias, target in aliases.items()
                   if alias != moved.id}
        aliases[held.id] = moved.id
    after = inv.without_deck(held.id).with_deck(moved).replace(deck_aliases=dict(sorted(aliases.items())))
    return after, Summary(f"Renamed {current.title} to {title}", {"decks": 1},
                          {held.path: ["renamed"], moved.path: ["renamed"]},
                          {"deck": moved.id, "renamed": {"from": held.id, "to": moved.id}})
