"""Content signals over authorized projections, never global revisions, row ids or positions.

The first two signals belong only to the viewer's own space. The library signal
also covers already-Public deck projections; it never publishes their inventory.
"""
import dataclasses
import hashlib
import json

from decklab.lib import decks, permissions, spaces
from decklab.lib.api.guide import playing_guide


class Unverified(ValueError):
    """No fresh reliable signal; this must never become an empty/zero revision."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _rows(sheet, *, keep=None, omit=(), strict=True):
    if sheet is None:
        return []
    if sheet.error or sheet.csv_error or strict and sheet.strict_error:
        raise Unverified("A scoped source cannot be read")
    values = sheet.rows if hasattr(sheet, "rows") else sheet.items
    rows = [{key: value for key, value in row.as_dict().items() if key not in omit}
            for row in values if keep is None or keep(row)]
    return sorted(rows, key=_json)


def _kit_rows(inv, owners):
    # Whole-file row diagnostics may belong to a private owner. Only an unreadable
    # whole source is unknown; per-row/global problems never enter a signal.
    rows = _rows(inv.accessories, keep=lambda row: row.owner in owners, strict=False)
    images = {row.get("image") for row in rows if row.get("image")}
    return rows, sorted((name, inv.accessory_images[name].sha256) for name in images if name in inv.accessory_images)


def _inventory(inv, space, owners):
    out = {name: _rows(getattr(inv, name).get(space)) for name in ("collections", "tokens", "locations", "dice", "loans")}
    out["imports"] = sorted((item.name, item.size, item.sha256) for item in inv.imports.get(space, ()))
    out["kit"] = _kit_rows(inv, owners)
    if space == spaces.HOME:
        out["status"] = _rows(inv.status)
        out["watchlist"] = _rows(inv.watchlist)
        out["products"] = [(product.file, product.name, product.format, _rows(product)) for product in inv.products]
        out["orders"] = []
        for order in inv.orders:
            if order.error:
                raise Unverified("An own-space order cannot be read")
            out["orders"].append((order.file, order.record()))
        out["orders"].sort(key=lambda row: row[0])
        out["payloads"] = [(path, _rows(sheet)) for path, sheet in sorted(inv.payloads.items())]
    return out


def _kit_owner(parsed, home_players):
    if parsed.space != spaces.HOME:
        return parsed.space
    return "shared" if parsed.player == "either" else home_players.get(parsed.player)


def _deck(record, *, own, readers, home_players):
    if record.error or record.text is None:
        raise Unverified("A visible deck cannot be read")
    try:
        parsed = decks.parse_deck(record.data, record.slug, record.kind, space=record.space)
    except (ValueError, decks.DeckFileError):
        raise Unverified("A visible deck cannot be read") from None
    shown = readers is None or _kit_owner(parsed, home_players) in readers
    kit = {"sleeves": parsed.sleeves, "deck_box": parsed.deck_box} if shown else None
    if own:
        # Rebuild just the header, avoiding an added/removed private kit line or
        # its line ending shifting an otherwise identical visible-text digest.
        start, end = parsed.spans["header"]
        fields = [(key, value) for key, value in parsed.fields if key.casefold() not in ("sleeves", "deck box")]
        value = (parsed.text[:start].rstrip("\r\n"), fields, parsed.text[end:].lstrip("\r\n"))
    else:
        # An outside Public reader sees intrinsic deck data and gameplay prose,
        # never the raw owned-vs-needed table, purchase text or private headers.
        fields = {key.casefold(): value for key, value in parsed.fields if key.casefold() in
                  {"format", "archetype", "played by", "status", "built version", "target bracket", "cover card"}}
        value = {"title": parsed.title, "fields": fields, "target": parsed.target,
                 "owned": parsed.owned, "considering": parsed.considering, "guide": playing_guide(parsed)}
        value = _plain(value)
    return {"value": value, "kit": kit}


def _plain(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def project(inv, profile, visibility, listed):
    """No I/O, writes or mutation; callers supply one fresh inventory/visibility view."""
    if inv.stale or not inv.persisted:
        raise Unverified("The current inventory is not fresh")
    if inv.backend == "db" and not all((inv.locations_ready, inv.dice_ready, inv.loans_ready)):
        raise Unverified("An inventory source is not available on this schema")
    own_space = permissions._space_of(profile)
    configured = {permissions._space_of(person) for person in listed}
    public = {owner for owner, thing in visibility if thing == "decks" and owner in configured}
    public_kit = {owner for owner, thing in visibility if thing == "accessories"}
    readers = permissions.accessory_readers(profile, public=public_kit)
    namespace_owners = {person["id"] for person in listed if permissions._space_of(person) == own_space}
    if own_space == spaces.HOME:
        namespace_owners.add("shared")
    own_readers = readers & namespace_owners
    home_players = {}
    for person in listed:
        if permissions._space_of(person) == spaces.HOME and person.get("plays_as"):
            home_players.setdefault(person["plays_as"], person["id"])
    own, visible = [], []
    referenced = set()
    for deck_id, record in sorted(inv.decks.items()):
        same = record.space == own_space
        if not same and record.space not in public:
            continue                    # hidden decks are never parsed or inspected
        value = _deck(record, own=same, readers=readers, home_players=home_players)
        visible.append((deck_id, value))
        if same:
            own.append((deck_id, value))
        if value["kit"]:
            referenced.update(item for item in value["kit"].values() if item)
    aliases = [(old, new) for old, new in sorted(inv.deck_aliases.items())
               if (permissions._deck_space(old) == own_space or permissions._deck_space(old) in public)
               and (permissions._deck_space(new) == own_space or permissions._deck_space(new) in public)]
    kits, images = _kit_rows(inv, readers)
    kits = [row for row in kits if row.get("id") in referenced]
    used_images = {row.get("image") for row in kits}
    images = [row for row in images if row[0] in used_images]
    own_aliases = [pair for pair in aliases if permissions._deck_space(pair[0]) == own_space]
    return {"ready": True, "inventory": _digest(_inventory(inv, own_space, own_readers)),
            "decks": _digest([own, own_aliases]), "library": _digest([visible, aliases, kits, images])}
