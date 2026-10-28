"""What both backends do with an operation's result before saving it, so the same operation
gives the same inventory and the same refusals on either (the foundation review's items 2, 3, 6
and 7).

    after, summary = op.run(detach(before))       # the op gets its own copy of every record
    after = prepare(before, after)                # settled: what a save then a load gives back
    paths = changed_paths(before, after)          # the files a change touches (as rendered)
    words = changed_labels(before, after)         # the same, in plain words for people

- detach(inv): a snapshot whose order records are copies. The rest of a snapshot can't be
  changed in place (frozen rows and sheets, read-only mappings), so an operation that changes a
  record's dict in place changes only its copy, never the snapshot a backend has cached.
- prepare(before, after, revision=None): every source the operation changed is
  1. normalised, in this one place: a collection has collection.csv's columns and is in
     rules.sort_key order, and a collection or tokens file with no rows is no file (a space
     with no cards has none, on both backends); status.csv always has the six columns; a
     payload, the watchlist and tokens.csv their standard ones;
  2. rendered and read back as the files backend reads a file, so its problems, line numbers
     and strict errors are what a load after the save will say (the database backend loads by
     rendering too), keeping each token and watchlist row's hidden id and each product's name;
  3. checked (check()), raising state.Conflict or state.Invalid.
  Sources the operation didn't change stay exactly as they were (a file that couldn't be read,
  or a fixture with a BOM, is never rewritten by a change elsewhere).
  Phase 4's deck parts: a deck's text is final as the operation gives it (rendered before the
  operation runs: nothing here rewrites it, its line endings included) and is read back as a
  Deck; accessories.csv gets its standard columns and its row order (kind, then id) and is read
  back as a Sheet, and with no rows is no file (the database can't hold a header-only file: both
  backends then have none, the foundation review's M4); a picture is kept as given (its bytes
  are what the backend writes).
- check(before, after): refuses (state.Conflict) to rewrite a source that couldn't be read, or
  a tokens.csv with rows tokens.read() leaves out (it would delete them; today's "fix it by
  hand" words); refuses (state.Invalid) a changed tokens.csv whose rows break the token rules, a
  changed collection a strict read refuses, and anything the database couldn't hold
  (table_rows.reasons) in a changed source or newly anywhere: a quantity that isn't a whole
  number of at least 1, a payload no record names, a component whose file isn't there; and
  rewriting a deck file or accessories.csv that couldn't be read, a changed accessories.csv a
  strict read refuses, or a picture whose bytes aren't its meta's.
"""
import copy
import dataclasses

from . import files, paths, rules, table_rows
from .model import (PREVIEW, AccessoryRow, CardRow, Deck, ImageMeta, LocationRow, Product, Sheet, StatusRow,
                    TokenRow, WatchRow, refuse_unreadable_tokens)

SAVE_REFUSED = "The inventory can't be saved like that: {why}"
STANDARD = {"collection": CardRow.COLUMNS, "tokens": TokenRow.COLUMNS, "locations": LocationRow.COLUMNS,
            "status": StatusRow.COLUMNS,
            "watchlist": WatchRow.COLUMNS, "accessories": AccessoryRow.COLUMNS}
PAYLOAD_COLUMNS = {"cards": CardRow.COLUMNS, "tokens": TokenRow.COLUMNS}


def detach(inv):
    """inv with a copy of every order record's data (see the module docstring)."""
    return inv.replace(orders=tuple(dataclasses.replace(o, data=copy.deepcopy(o.data)) for o in inv.orders))


# ------------------------------------------------------------------ sources by path

def source_at(inv, rel):
    """The source of inv at the inventory path rel (a Sheet, Product or Order), or None when inv
    has no file there (a sheet that doesn't exist counts as none)."""
    found = paths.classify(rel)
    if found is None:
        raise ValueError(f"{rel} isn't an inventory path")
    what, detail = found
    if what == "collection":
        sheet = inv.collections.get(detail)
    elif what == "tokens":
        sheet = inv.tokens.get(detail)
    elif what == "locations":
        sheet = inv.locations.get(detail)
    elif what == "status":
        sheet = inv.status
    elif what == "watchlist":
        sheet = inv.watchlist
    elif what == "payload":
        sheet = inv.payloads.get(rel)
    elif what == "product":
        return inv.product(detail)
    elif what == "record":
        return next((o for o in inv.orders if o.file == f"{detail}.json"), None)
    elif what == "deck":
        space, kind, slug = detail
        found = inv.decks.get(Deck(space, kind, slug).id)
        return found if found is not None and found.path == rel else None
    elif what == "accessories":
        sheet = inv.accessories
    elif what == "image":
        return inv.accessory_images.get(detail)
    else:
        raise ValueError(f"{rel} is a raw import, not a source")
    return sheet if sheet is not None and sheet.exists else None


def with_source(inv, rel, source):
    """inv with source at rel (None: no file there)."""
    what, detail = paths.classify(rel)
    if what in ("collection", "tokens", "locations"):
        attr = {"collection": "collections", "tokens": "tokens", "locations": "locations"}[what]
        mapping = {k: v for k, v in getattr(inv, attr).items() if k != detail}
        if source is not None:
            mapping[detail] = source
        return inv.replace(**{attr: dict(sorted(mapping.items()))})
    if what == "status":
        return inv.replace(status=source if source is not None else files.status_sheet(None))
    if what == "watchlist":
        return inv.replace(watchlist=source if source is not None else files.watchlist_sheet(None))
    if what == "payload":
        payloads = {k: v for k, v in inv.payloads.items() if k != rel}
        if source is not None:
            payloads[rel] = source
        return inv.replace(payloads=dict(sorted(payloads.items())))
    if what == "product":
        return inv.with_product(source) if source is not None else inv.without_product(detail)
    if what == "record":
        kept = inv.replace(orders=tuple(o for o in inv.orders if o.file != f"{detail}.json"))
        return kept.with_order(source) if source is not None else kept
    if what == "deck":
        decks = {k: v for k, v in inv.decks.items() if k != Deck(*detail).id}
        if source is not None:
            decks[source.id] = source
        return inv.replace(decks=dict(sorted(decks.items())))
    if what == "accessories":
        return inv.replace(accessories=source if source is not None else files.accessories_sheet(None))
    if what == "image":
        images = {k: v for k, v in inv.accessory_images.items() if k != detail}
        if source is not None:
            images[detail] = source
        return inv.replace(accessory_images=dict(sorted(images.items())))
    raise ValueError(f"{rel} is a raw import, not a source")


def changed(before, after):
    """The inventory paths whose source differs between two snapshots (added, removed or not
    equal), sorted."""
    a, b = files.sources(before), files.sources(after)
    return sorted(rel for rel in a.keys() | b.keys() if a.get(rel) != b.get(rel))


def changed_paths(before, after):
    """The inventory paths touched, by rendered bytes and product display metadata
    (which the database holds outside the CSV), plus added raw imports. A source
    rewritten the same isn't listed. Used by previews and the deck-table refresh."""
    a, b = files.sources(before), files.sources(after)
    out = []
    for rel in a.keys() | b.keys():
        x, y = a.get(rel), b.get(rel)
        if x == y:
            continue
        metadata_changed = (isinstance(x, Product) and isinstance(y, Product) and
                            (x.name, x.format) != (y.name, y.format))
        if x is None or y is None or metadata_changed or files.render_source(x) != files.render_source(y) \
                or files.render_source(x) is None:
            out.append(rel)
    for space, found in after.imports.items():
        had = {info.name for info in before.imports.get(space, ())}
        out += [f"{paths.imports_dir(space)}/{info.name}" for info in found if info.name not in had]
    return sorted(out)


# The order changed_labels lists the parts of the inventory in.
_LABEL_ORDER = ("collection", "locations", "tokens", "import", "record", "product", "status", "watchlist", "deck",
                "accessories", "image")


def changed_labels(before, after, rels=None):
    """What a change from before to after touches (changed_paths, or rels when given), in plain
    words for a person rather than as the files' paths, one label per part, without repeats:
    "Home's collection", "User2's token cards", "Order 2026-10-05-ronin" (its record and its
    cards or token cards alike), "Product Wretched Ranks", "The products' status", "The purchase
    queue", "Deck Gruul Ramp (casual/gruul-ramp)", "The accessories", ... What a receipt's preview
    and the order commands' dry runs show."""
    from decklab.lib import spaces

    def whose(space):
        try:
            return f"{spaces.get(space).name}'s"
        except (spaces.SpaceNotFound, ValueError, OSError):
            return f"{space}'s"

    def order_of(rel):
        for inv in (after, before):
            for order, component in inv.components():
                if component.path == rel:
                    return order.id
        return None

    def deck_words(detail):
        space, kind, slug = detail
        deck_id = f"{kind}/{slug}" if space == paths.HOME else f"{space}/{kind}/{slug}"
        deck = after.deck(deck_id) or before.deck(deck_id)
        title = None
        if deck is not None and deck.text:
            first = deck.text.lstrip("\ufeff").split("\n", 1)[0].strip()
            title = first[2:].strip() if first.startswith("# ") else None
        return f"Deck {title} ({deck_id})" if title else f"Deck {deck_id}"

    labels = []
    for rel in (changed_paths(before, after) if rels is None else rels):
        found = paths.classify(rel)
        what, detail = found if found is not None else (None, None)
        if what == "collection":
            words = f"{whose(detail)} collection"
        elif what == "tokens":
            words = f"{whose(detail)} token cards"
        elif what == "locations":
            words = f"{whose(detail)} storage locations"
        elif what == "import":
            words = f"{whose(detail[0])} raw imports: {detail[1]}"
        elif what == "record":
            words = f"Order {detail}"
        elif what == "payload":
            order_id = order_of(rel)
            kind = "token cards" if detail[0] == "tokens" else "cards"
            words = f"Order {order_id}" if order_id else f"A {detail[1]} order's {kind}"
            what = "record"                     # listed with the orders' records
        elif what == "product":
            product = after.product(detail) or before.product(detail)
            words = f"Product {product.label('shopping') if product is not None else detail}"
        elif what == "status":
            words = "The products' status"
        elif what == "watchlist":
            words = "The purchase queue"
        elif what == "deck":
            words = deck_words(detail)
        elif what == "accessories":
            words = "The accessories"
        elif what == "image":
            words = f"An accessory's picture ({detail})"
        else:
            words = rel
        rank = _LABEL_ORDER.index(what) if what in _LABEL_ORDER else len(_LABEL_ORDER)
        if all(words != seen for _, seen in labels):
            labels.append((rank, words))
    return [words for _, words in sorted(labels)]


# ------------------------------------------------------------------ settling a result

def _normal(rel, source):
    """A changed source as every writer leaves it (see the module docstring); None when it
    should have no file."""
    if not isinstance(source, Sheet) or source.error is not None:
        return source
    what, detail = paths.classify(rel)
    columns = PAYLOAD_COLUMNS[detail[0]] if what == "payload" else STANDARD[what]
    rows = source.rows
    if what in ("collection", "locations"):
        try:
            rows = tuple(sorted(rows, key=lambda row: rules.sort_key(row.as_dict())))
        except (KeyError, TypeError):           # a row without a cell: check() refuses it
            pass
    if what == "accessories":
        rows = tuple(sorted(rows, key=lambda row: rules.accessory_sort_key(row.as_dict())))
    if what in ("collection", "tokens", "locations", "accessories") and not rows and not source.problems:
        return None
    return dataclasses.replace(source, columns=tuple(columns), rows=rows, exists=True)


def _keep_identity(made, fresh):
    """fresh (a source read back from made's rendered bytes) with what the bytes don't hold:
    a product's name and format, and the token and watchlist rows' hidden ids (while every
    row came back)."""
    if isinstance(made, Product):
        return dataclasses.replace(fresh, name=made.name, format=made.format)
    if isinstance(made, Deck):
        return dataclasses.replace(fresh, revision=made.revision, rename_version=made.rename_version)
    if isinstance(made, Sheet) and len(made.rows) == len(fresh.rows) and any(r.id for r in made.rows):
        return dataclasses.replace(fresh, rows=tuple(dataclasses.replace(r, id=m.id)
                                                     for r, m in zip(fresh.rows, made.rows)))
    return fresh


def reread(before, after, revision=None):
    """after with every source it changes from before normalised and read back (steps 1 and 2
    of prepare); revision replaces after's when given. A storage location whose collection row
    is gone goes with it (E8-S22), whichever operation removed or rekeyed the row."""
    after = after.without_stray_locations()
    names = changed(before, after)
    out = after
    if names:
        normal = {rel: _normal(rel, source_at(after, rel)) for rel in names}
        rendered = {}
        for rel, source in normal.items():
            if isinstance(source, ImageMeta):   # kept as given: its bytes are what's written
                continue
            data = files.render_source(source) if source is not None else None
            if data is not None:
                rendered[rel] = data
        fresh = files.build(rendered, revision="")
        for rel in names:
            source = normal[rel]
            if rel in rendered:
                source = _keep_identity(source, source_at(fresh, rel))
            out = with_source(out, rel, source)
    if revision is None:
        return out
    if any(paths.is_deck_part(rel) for rel in names):     # a preview's decks are never saved either
        out = out.replace(decks_revision=after.decks_revision + PREVIEW)
    return out.replace(revision=revision)


def check(before, after):
    """Refuse a settled result neither backend may save (see the module docstring)."""
    from decklab.lib.state import Conflict, Invalid
    names = changed(before, after)
    for rel in names:
        old, new = source_at(before, rel), source_at(after, rel)
        what = paths.classify(rel)[0]
        if old is not None and getattr(old, "error", None) is not None and new is not None:
            raise Conflict(f"{rel} can't be read ({old.error}){rules.UNTIL_PUT_RIGHT}")
        if what == "tokens" and old is not None:
            refuse_unreadable_tokens(old)
        if new is None:
            continue
        if getattr(new, "error", None) is not None:
            raise Invalid(SAVE_REFUSED.format(why=f"{rel} can't be read back ({new.error})"))
        if what == "tokens" and new.problems:
            raise Invalid(SAVE_REFUSED.format(why=new.problems[0]))
        if what in ("collection", "locations") and new.strict_error:
            raise Invalid(SAVE_REFUSED.format(why=new.strict_error))
        if what == "accessories" and new.strict_error:
            raise Invalid(SAVE_REFUSED.format(why=new.strict_error))
        if what == "image" and (new.content is None or ImageMeta.of(new.name, new.content) != new):
            raise ValueError(f"{rel}: a changed picture needs its bytes (Inventory.with_image)")
    found_before = table_rows.reasons(before)
    for rel, texts in table_rows.reasons(after).items():
        old = set(found_before.get(rel, ()))
        for text in texts:
            if rel in names or text not in old:
                raise Invalid(SAVE_REFUSED.format(why=text))


def prepare(before, after, revision=None):
    """after settled (normalised, read back) and checked: what a backend saves, and what a
    preview shows (see the module docstring). Raises state.Conflict / state.Invalid."""
    settled = reread(before, after, revision)
    check(before, settled)
    return settled
