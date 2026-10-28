"""Freeze optional saved-home needs beside unchanged legacy queue names.

Only a fresh persisted inventory and one prepared card-index generation can
prove additional names. The nested read projection keeps physical home supply
and intact products, but removes member decks before any deck parser runs.
No retailer, shop cache, wishlist, editor draft or write lives here.
"""
import re
from dataclasses import dataclass

from decklab.lib import buying_needs, cards, decks, inventory, shops, spaces
from decklab.lib.inventory.model import Deck, Inventory

NOTICES = {
    "ready": None,
    "partial": "Some saved home decks could not be counted; only confirmed missing names were added.",
    "unavailable": "Saved home missing names could not be confirmed; the purchase queue is unchanged.",
    "over_limit": "Saved home missing names exceed the snapshot limit; the purchase queue is unchanged.",
}


@dataclass(frozen=True)
class NamesPlan:
    names: tuple[str, ...]
    status: str


def _name(value):
    if (not isinstance(value, str) or not 0 < len(value) <= 200 or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def _home_id(value):
    """Strict home file identity, without space existence/configuration reads."""
    if not isinstance(value, str) or not 3 <= len(value) <= 200:
        return False
    try:
        owner, kind, slug = spaces.split_deck_id(value)
    except ValueError:
        return False
    return (owner == spaces.HOME and kind in decks.KINDS and bool(slug) and "/" not in slug
            and not slug.startswith(".") and not re.search(r"[\\:\x00-\x1f\x7f]", slug))


def _projection(snapshot):
    if (not isinstance(snapshot, Inventory) or type(snapshot.revision) is not str or not snapshot.revision.strip()
            or snapshot.stale is not None or snapshot.persisted is not True or snapshot.backend not in ("files", "db")):
        raise ValueError("unproven snapshot")
    home = {}
    for raw, stored in snapshot.decks.items():
        # Inspect metadata only before deciding whether this record may be parsed.
        if not isinstance(raw, str) or not isinstance(stored, Deck):
            raise TypeError("unproven deck metadata")
        try:
            owner, kind, slug = spaces.split_deck_id(raw)
        except ValueError:
            raise ValueError("unproven deck identity") from None
        if (kind not in decks.KINDS or not slug or "/" in slug or slug.startswith(".")
                or re.search(r"[\\:\x00-\x1f\x7f]", slug) or len(raw) > 200
                or stored.space != owner or stored.kind != kind or stored.slug != slug or stored.id != raw):
            raise ValueError("unproven home deck identity")
        if owner == spaces.HOME:
            home[raw] = stored
    aliases = {}
    for raw, canonical in snapshot.deck_aliases.items():
        if not isinstance(raw, str):
            raise TypeError("unproven alias identity")
        if raw.startswith(("casual/", "commander/")):
            if not _home_id(raw) or canonical is not None and not _home_id(canonical):
                raise ValueError("unproven home alias")
            if raw in home and canonical != raw:
                raise ValueError("an active home deck cannot be an old alias")
            if canonical is not None:
                aliases[raw] = canonical
    for raw, canonical in aliases.items():
        if aliases.get(canonical, canonical) != canonical or raw in home and canonical not in home:
            raise ValueError("unproven canonical home deck")
    return snapshot.replace(decks=home, deck_aliases=aliases)


def _resolver():
    loaded = cards._get()
    known, aliases = loaded.data["cards"], loaded.by_key
    if not isinstance(known, dict) or not isinstance(aliases, dict):
        raise TypeError("unproven card index")
    memo = {}

    def resolve(name):
        if name not in memo:
            if not _name(name):
                return None
            canonical = name if name in known else aliases.get(cards.fold(name))
            if canonical is not None and (not _name(canonical) or canonical not in known):
                raise ValueError("unproven card identity")
            memo[name] = canonical
        return memo[name]

    return loaded, resolve


def _summaries(snapshot):
    found, errors, seen = [], [], set()
    for raw in snapshot.decks:
        canonical = snapshot.deck_aliases.get(raw, raw)
        if canonical in seen:
            continue
        seen.add(canonical)
        stored = snapshot.decks[canonical]
        try:
            if stored.error is not None or stored.data is None:
                raise ValueError("unreadable home deck")
            parsed = decks.parse_deck(stored.data, stored.slug, stored.kind, space=spaces.HOME)
            found.append({"id": canonical, "title": parsed.title, "kind": stored.kind,
                          "player": parsed.player, "status": parsed.status,
                          "versions": ["target"] if parsed.has_decklist else []})
        except Exception:  # noqa: BLE001 - one unreadable target remains explicitly partial
            errors.append({"message": "A saved home deck could not be read."})
    return found, errors


def _public(_value):
    return "A saved home count could not be confirmed."


def _log(_value):
    pass


def names(queue, snapshot):
    """Keep every queued spelling; append only proven, canonically new missing names.

    All work finishes before a caller creates a retailer session. Ordinary
    optional-data failures preserve the exact original queue name tuple.
    """
    fallback = tuple(shops.queue_names(queue))
    try:
        projected = _projection(snapshot)
        if not projected.decks:
            status = "over_limit" if len(fallback) > shops.MAX_SNAPSHOT_NAMES else "ready"
            return NamesPlan(fallback, status)
        loaded, resolve = _resolver()

        def strict(name):
            canonical = resolve(name)
            if canonical is None:
                raise ValueError("unproven missing card")
            return canonical

        with inventory.pinned(projected):
            summaries, errors = _summaries(projected)
            counted = buying_needs.count(summaries, canonical=strict, public=_public, log=_log, errors=errors)
        if cards._index is not loaded or counted.status == "unavailable":
            return NamesPlan(fallback, "unavailable")
        combined = list(fallback)
        identities = set()
        for name in fallback:
            try:
                canonical = resolve(name)
            except ValueError:
                canonical = None  # An unknown queued label does not invent or block a missing need.
            identities.add((canonical or name).casefold())
        for row in counted.rows:
            if not isinstance(row, dict) or type(row.get("missing")) is not int or row["missing"] <= 0:
                raise ValueError("unproven missing count")
            canonical = strict(row.get("name"))
            if canonical.casefold() not in identities:
                identities.add(canonical.casefold())
                combined.append(canonical)
        if len(combined) > shops.MAX_SNAPSHOT_NAMES:
            return NamesPlan(fallback, "over_limit")
        return NamesPlan(tuple(combined), counted.status)
    except Exception:  # noqa: BLE001 - optional evidence never disables the queue snapshot
        return NamesPlan(fallback, "unavailable")
