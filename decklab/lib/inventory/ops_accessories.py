"""Phase 4's accessory, picture and kit operations (decklab/PLAN.md phase 4; the phase 4 design's
amendments R4 and R6), registered like the deck operations (ops_decks.py imports this module, so
importing either registers both) and run by inventory.apply() or preview() on either backend.

    accessory.add      {row, sha256, owners, image=None}
    accessory.edit     {id, row, sha256, owners, image="keep"}
    accessory.remove   {id, sha256, owners}
    image.put          {name, content}
    image.remove       {name}
    kit.set            {holders: [{id, expected}], changes: [{holder, field, value, expect?, loose?}], owners,
                        editor=None}

owners is permissions.accessory_owners of whoever asks: a frozenset of the owners whose rows it
sees (its own id and "shared"), or None for all (a local command line). A row it doesn't see is
"not found" (404), as if it weren't there; a row it saves must be its own or shared (403).

sha256 is the list's token as the asker read it: accessories.view_sha256 over the rows owners
see (None while it sees none), so another owner's change never refuses a save, nor tells of
it. A different token is AccessoryRefused, code 409, reason "changed" (the page answers with the
list as it is now; reason "deleted" when the row an edit or removal names has gone). A list a
strict read refuses is 409 with its words ("..." and rules.UNTIL_PUT_RIGHT).

row is the columns a page gives (accessories.ROW_KEYS; a new row's owner as the asker chose it,
which the page fills with the writer's own id when it doesn't say); an edit's are merged over the
row as it is. A new row's id is made from its brand, name and colour (accessories.new_id) and
never changes. capacity is cleared when the kind isn't a deck box and the row doesn't give one.
image: an add's picture bytes (or None); an edit's "keep", None (no picture) or new bytes. A new
picture is stored as <id>.<jpg|png|webp> (its first bytes say which; the page checks its size
first, accessory_fetch.check_image) and the old one, if its name differs, is removed; a new or
removed picture clears the crop unless the row gives one. A removed row's picture goes with it.
A row a deck or product uses can't be removed, change kind, or go to an owner one of its holders
may not use: AccessoryRefused 409 with extra {"blocks": [{id, title}]} (a holder owners don't
see named "one of User1's decks", with id None).

image.put and image.remove are the command line's (no owners: everything). image.put stores a
picture for the row whose id is the name's stem (its image becomes the name, the crop cleared
when the picture's name changes, and a picture of another name removed); image.remove removes a
picture, and clears image and crop on a row naming it.

kit.set is the only writer of a deck's Sleeves and Deck box header lines and of an intact
product's status.csv sleeves and deck_box (see its docstring). editor is the profile a page's
write is made by: each deck it names must be one that profile may edit (permissions' deck.edit,
E10-S42), checked here again under the lock; None (the command line) checks nothing more. Its refusals are AccessoryRefused
with the HTTP status the page answers with, and for a deck box every one of which is held extra
{"taken_by": [{holder, title}]}, anonymised as above. Sleeves are never taken: several holders
may use one design.
"""
from decklab.lib.state import Invalid

from . import Summary, paths, register, rules
from .ops_decks import KIT_FIELDS, DeckRefused, parsed_deck

CANT_HOLD = "Only a built deck or a product kept intact has sleeves or a deck box"
_KIND_WORDS = {"sleeves": "sleeves", "deck_box": "deck box", "playmat": "playmat"}
_HEADER = {"sleeves": "Sleeves", "deck_box": "Deck box"}


class AccessoryRefused(DeckRefused):
    """An accessory or kit operation refused: code, reason and ids as DeckRefused's; extra the
    keys a page's answer adds ({"blocks": ...}, {"taken_by": ...})."""

    def __init__(self, message, code=409, reason=None, ids=(), **extra):
        super().__init__(message, code, reason, ids)
        self.extra = extra


# ------------------------------------------------------------------ reading inside an operation

def _list(inv, strict=True):
    """accessories.from_sheet of inv's sheet; a strict read's refusal as AccessoryRefused 409, a
    list that can't be read at all as 500."""
    from decklab.lib import accessories
    try:
        return accessories.from_sheet(inv.accessories, strict=strict)
    except accessories.AccessoriesError as e:
        raise AccessoryRefused(str(e), 409) from None
    except OSError as e:
        raise AccessoryRefused(str(e), 500) from None


def _owners(owners):
    return None if owners is None else frozenset(owners)


def _check_token(acc, sha256, owners, rid=None):
    """AccessoryRefused 409 "changed" (or "deleted", for an id no longer there) when the list's
    token for owners isn't sha256."""
    from decklab.lib import accessories
    if accessories.view_sha256(acc, owners) == sha256:
        return
    row = acc.rows_by_id.get(rid) if rid else None
    gone = rid is not None and (row is None or not accessories.visible(row["owner"], owners))
    raise AccessoryRefused("The accessories list changed after you opened it.", 409,
                           "deleted" if gone else "changed")


def usage(inv):
    """(holders found, accessories.holders()'s usage) of inv, read under pinned(inv): who holds
    what in the snapshot an operation is making."""
    from decklab.lib import accessories, inventory
    with inventory.pinned(inv):
        found, _ = accessories._scan([])        # reading problems show on the pages, not here
        return found, accessories._usage(found, _list(inv, strict=False))


def shown_users(users, owners):
    """Holders as the asker may see them: one whose owner it can't see keeps only its kind and
    need, with holder None, named "one of User1's decks"."""
    from decklab.lib import accessories
    return [{k: h[k] for k in ("holder", "title", "kind", "need")} if accessories.visible(h["owner"], owners)
            else {"holder": None, "title": accessories.hidden_title(h["owner"], h["kind"]), "kind": h["kind"],
                  "need": h["need"]}
            for h in users]


def _blocks(users, row, change=None):
    from decklab.lib import accessories
    names = accessories._and(h["title"] for h in users)
    word = "these sleeves" if row["kind"] == "sleeves" else f"this {_KIND_WORDS[row['kind']]}"
    other = "other sleeves" if row["kind"] == "sleeves" else f"another {_KIND_WORDS[row['kind']]}"
    uses = "uses" if len(users) == 1 else "use"
    them = "it" if len(users) == 1 else "them"
    if change:
        text = (f"{names} {uses} {word}, so it can't become "
                f"{'sleeves' if change == 'sleeves' else 'a ' + _KIND_WORDS[change]}. Choose {other} for {them} first.")
    else:
        text = f"{names} {uses} {word}. Choose {other} for {them} first, or set the quantity to 0."
    return AccessoryRefused(text, 409, "blocks", blocks=[{"id": h["holder"], "title": h["title"]} for h in users])


def _owner_blocks(users, row, owner):
    from decklab.lib import accessories
    names = accessories._and(h["title"] for h in users)
    word = "these sleeves" if row["kind"] == "sleeves" else f"this {_KIND_WORDS[row['kind']]}"
    other = "other sleeves" if row["kind"] == "sleeves" else f"another {_KIND_WORDS[row['kind']]}"
    uses = "uses" if len(users) == 1 else "use"
    them = "it" if len(users) == 1 else "them"
    whose = "shared" if owner == accessories.SHARED else f"{accessories.owner_name(owner)}'s"
    return AccessoryRefused(
        f"{names} {uses} {word}, so {'they' if row['kind'] == 'sleeves' else 'it'} can't become {whose}: a deck "
        f"uses its player's accessories or shared ones. Choose {other} for {them} first.", 409, "blocks",
        blocks=[{"id": h["holder"], "title": h["title"]} for h in users if h["holder"]])


def _picture_ext(content):
    """The extension a picture's first bytes say ("jpg", "png", "webp"); Invalid for anything
    else or a picture over accessory_fetch.MAX_IMAGE."""
    from decklab.lib import accessory_fetch
    if not isinstance(content, (bytes, bytearray)):
        raise Invalid("a picture must be its bytes")
    if len(content) > accessory_fetch.MAX_IMAGE:
        raise Invalid(f"a picture must be at most {accessory_fetch.MAX_IMAGE // (1024 * 1024)} MB")
    ext = accessory_fetch.sniff(bytes(content))
    if ext is None:
        raise Invalid("a picture must be a JPEG, PNG or WebP file")
    return ext


def _row_input(row):
    from decklab.lib import accessories
    if not isinstance(row, dict):
        raise Invalid("row must be an object")
    unknown = sorted(set(row) - set(accessories.ROW_KEYS))
    if unknown:
        raise Invalid(f"Unknown row key {unknown[0]!r}; a row takes: {', '.join(accessories.ROW_KEYS)}")
    return dict(row)


def _with_rows(inv, rows, put=None, drop=()):
    """inv with accessories.csv holding rows (dicts), a picture put ((name, bytes)) and pictures
    removed (names)."""
    out = inv.with_accessories(rows)
    for name in drop:
        if name and (put is None or name != put[0]) and out.image_meta(name) is not None:
            out = out.without_image(name)
    if put is not None:
        out = out.with_image(*put)
    return out


def _summary(text, rid, changed, pictures=()):
    found = {paths.ACCESSORIES: changed}
    for name in pictures:
        found[paths.image(name)] = ["picture"]
    return Summary(text, {"accessories": 1}, found, {"id": rid})


# ------------------------------------------------------------------ the rows

def _merged(row, base, owners, rid, image, keep_image):
    """The validated row an add (base None) or edit gives, or Invalid / AccessoryRefused 403."""
    from decklab.lib import accessories
    fields = {k: "" for k in accessories.ROW_KEYS if k != "quantity"}
    fields.update(base or {})
    fields.update(row)
    if not accessories.visible(fields.get("owner"), owners):
        raise AccessoryRefused("An accessory you save is yours or shared: choose yourself or Shared as its owner.",
                               403)
    if fields.get("kind") != "deck_box" and "capacity" not in row:
        fields["capacity"] = None       # only a deck box has one
    fields["id"] = rid
    if keep_image:
        fields["image"] = (base or {}).get("image", "")
    else:
        fields["image"] = f"{rid}.{image}" if image else ""
        if "crop" not in row:
            fields["crop"] = ""         # the old picture's crop doesn't fit a new one
    try:
        return accessories.validate_row(fields)
    except ValueError as e:
        raise Invalid(f"The accessory can't be saved: {e}") from None


@register("accessory.add")
def add_accessory(inv, *, row, sha256, owners, image=None):
    """A new row (see the module docstring); Summary.extra["id"] is its id."""
    from decklab.lib import accessories
    row = _row_input(row)
    owners = _owners(owners)
    acc = _list(inv)
    _check_token(acc, sha256, owners)
    ext = _picture_ext(image) if image is not None else None
    rid = accessories.new_id({**row}, acc.rows_by_id)
    new = _merged(row, None, owners, rid, ext, keep_image=False)
    rows = {**acc.rows_by_id, rid: new}
    put = (new["image"], bytes(image)) if ext else None
    return _with_rows(inv, rows.values(), put), _summary(
        f"Added the {_KIND_WORDS[new['kind']]} {accessories.label(new)}", rid, ["added"],
        [put[0]] if put else [])


def _existing(acc, rid, owners):
    from decklab.lib import accessories
    if not (isinstance(rid, str) and accessories.valid_id(rid)):
        raise Invalid("id must be an accessory id")
    old = acc.rows_by_id.get(rid)
    if old is None or not accessories.visible(old["owner"], owners):
        raise AccessoryRefused(f"No accessory {rid} in the accessories list", 404)
    return old


@register("accessory.edit")
def edit_accessory(inv, *, id, row, sha256, owners, image="keep"):
    """A row changed (see the module docstring)."""
    from decklab.lib import accessories
    row = _row_input(row)
    owners = _owners(owners)
    acc = _list(inv)
    _check_token(acc, sha256, owners, id)
    old = _existing(acc, id, owners)
    keep = isinstance(image, str) and image == "keep"
    ext = None if keep or image is None else _picture_ext(image)
    new = _merged(row, old, owners, id, ext, keep_image=keep)
    _, found = usage(inv)
    users = accessories.used_by(found, old)
    if users and new["kind"] != old["kind"]:
        raise _blocks(shown_users(users, owners), old, new["kind"])
    cant = [h for h in users if not accessories.usable(new["owner"], h["owner"])]
    if cant:
        raise _owner_blocks(shown_users(cant, owners), old, new["owner"])
    put = (new["image"], bytes(image)) if ext else None
    gone = [old["image"]] if old.get("image") and old["image"] != new["image"] else []
    if new == old and put is None:
        return inv, Summary("Nothing to change", {}, {}, {"id": id})
    out = _with_rows(inv, {**acc.rows_by_id, id: new}.values(), put, gone)
    return out, _summary(f"Changed the {_KIND_WORDS[new['kind']]} {accessories.label(new)}", id, ["changed"],
                         ([put[0]] if put else []) + gone)


@register("accessory.remove")
def remove_accessory(inv, *, id, sha256, owners):
    """A row removed, with its picture (see the module docstring)."""
    from decklab.lib import accessories
    owners = _owners(owners)
    acc = _list(inv)
    _check_token(acc, sha256, owners, id)
    old = _existing(acc, id, owners)
    _, found = usage(inv)
    users = accessories.used_by(found, old)
    if users:
        raise _blocks(shown_users(users, owners), old)
    rows = {k: v for k, v in acc.rows_by_id.items() if k != id}
    gone = [old["image"]] if old.get("image") else []
    return _with_rows(inv, rows.values(), None, gone), _summary(
        f"Removed the {_KIND_WORDS[old['kind']]} {accessories.label(old)}", id, ["removed"], gone)


# ------------------------------------------------------------------ pictures (the command line's)

@register("image.put")
def put_image(inv, *, name, content):
    """A picture stored for the row whose id is name's stem (see the module docstring)."""
    from decklab.lib import accessories
    m = accessories.IMAGE_RE.match(name) if isinstance(name, str) else None
    if m is None:
        raise Invalid(f"{name!r} isn't a picture's name: <accessory id>.jpg, .png or .webp")
    if _picture_ext(content) != m.group(2):
        raise Invalid(f"{name}: the picture's first bytes say it isn't a .{m.group(2)} file")
    acc = _list(inv)
    row = acc.rows_by_id.get(m.group(1))
    if row is None:
        raise AccessoryRefused(f"No accessory {m.group(1)} in the accessories list", 404)
    new = {**row, "image": name, "crop": row["crop"] if row.get("image") == name else ""}
    gone = [row["image"]] if row.get("image") and row["image"] != name else []
    out = _with_rows(inv, {**acc.rows_by_id, row["id"]: new}.values(), (name, bytes(content)), gone)
    return out, _summary(f"Stored the picture {name}", row["id"], ["picture"], [name] + gone)


@register("image.remove")
def remove_image(inv, *, name):
    """A picture removed; a row naming it keeps no picture (see the module docstring)."""
    from decklab.lib import accessories
    if not (isinstance(name, str) and accessories.IMAGE_RE.match(name)):
        raise Invalid(f"{name!r} isn't a picture's name: <accessory id>.jpg, .png or .webp")
    acc = _list(inv)
    naming = [r for r in acc.rows_by_id.values() if r.get("image") == name]
    if inv.image_meta(name) is None and not naming:
        raise AccessoryRefused(f"There's no picture {name}", 404)
    out = inv
    if naming:
        rows = {**acc.rows_by_id, **{r["id"]: {**r, "image": "", "crop": ""} for r in naming}}
        out = out.with_accessories(rows.values())
    if out.image_meta(name) is not None:
        out = out.without_image(name)
    return out, _summary(f"Removed the picture {name}", naming[0]["id"] if naming else None, ["picture"], [name])


# ------------------------------------------------------------------ kit.set

class _Holder:
    """One holder kit.set changes: a home deck, or an intact product's status.csv row."""

    def __init__(self, inv, holder_id, expected, owners, editor=None):
        from decklab.lib import accessories, permissions, spaces
        from . import kit
        self.id = holder_id
        self.product = holder_id.startswith("product/")
        if self.product:
            self.stem = holder_id.split("/", 1)[1]
            sheet = inv.status
            name = f"products/{paths.STATUS_NAME}"
            if not sheet.exists:
                raise AccessoryRefused(f"{name} is missing", 404, ids=[holder_id])
            if sheet.error is not None:
                raise AccessoryRefused(f"{name} can't be read: {sheet.error}", 500, ids=[holder_id])
            self.sha = kit.status_sha256(inv)
            if expected is not None and self.sha != expected:
                raise AccessoryRefused("The products list changed after you opened it.", 409, "changed",
                                       [holder_id])
            if sheet.strict_error is not None:
                raise AccessoryRefused(f"{name} can't be read: {sheet.strict_error}", 409, ids=[holder_id])
            index = kit.row_index(sheet, self.stem)
            if index is None:
                raise AccessoryRefused(f"{self.stem}.csv isn't in {name}", 404, ids=[holder_id])
            self.index = index
            self.row = sheet.rows[index]
            self.title = accessories._product_title(inv, f"{self.stem}.csv")
            self.can_hold = kit.can_hold(self.row)
            self.owner = accessories.SHARED
        else:
            deck = inv.decks.get(holder_id)
            if deck is None:
                raise AccessoryRefused(f"There's no deck {holder_id}.", 404, ids=[holder_id])
            if deck.space != spaces.HOME:
                raise AccessoryRefused(f"{holder_id} is in a person's own space: sleeves and deck boxes are "
                                       "recorded only for the home decks", 400, ids=[holder_id])
            if deck.error is not None:
                raise AccessoryRefused(f"{holder_id} can't be read ({deck.error}){rules.UNTIL_PUT_RIGHT}", 409,
                                       ids=[holder_id])
            if expected is not None and deck.sha256 != expected:
                raise AccessoryRefused(f"{holder_id} changed after you opened it.", 409, "changed", [holder_id])
            parsed = parsed_deck(deck)
            if parsed is None:
                raise AccessoryRefused(f"{holder_id} can't be read{rules.UNTIL_PUT_RIGHT}", 409, ids=[holder_id])
            if editor is not None:
                why = permissions.reason(editor, "deck.edit", parsed)
                if why is not None:
                    raise AccessoryRefused(why, 403, ids=[holder_id])
            self.deck, self.parsed = deck, parsed
            self.title = parsed.title
            self.can_hold = parsed.status == "built"
            self.owner = accessories.player_owner(parsed.player)
        if not accessories.visible(self.owner, owners):
            raise AccessoryRefused(f"{self.title}'s sleeves and deck box are {accessories.owner_name(self.owner)}'s "
                                   "to choose.", 403, ids=[holder_id])
        self.held = {f: self.value(f) for f in KIT_FIELDS}
        self.changed = []

    def value(self, field):
        if self.product:
            return self.row.text(field).strip()
        return (self.parsed.get_field(_HEADER[field]) or "").strip()

    def set(self, field, value):
        from decklab.lib import decks
        if self.product:
            self.row = self.row.replace(**{field: value or ""})
        else:
            try:
                (decks.set_sleeves if field == "sleeves" else decks.set_deck_box)(self.parsed, value)
            except ValueError as e:
                raise Invalid(f"The {_KIND_WORDS[field]} can't be set: {e}") from None
        self.changed.append(field)


@register("kit.set")
def set_kit(inv, *, holders, changes, owners=frozenset(), editor=None):
    """Every sleeve and deck-box move between decks and products in one operation: the only
    writer of a deck's Sleeves and Deck box lines and of an intact product's status.csv sleeves
    and deck_box (product.set-kit, inventory/kit.py, is kept for older callers).

    holders: [{id: a home deck's id, or "product/<stem>"; expected: the deck's Deck.sha256, or
    kit.status_sha256() for a product, as read; None: not checked, allowed only for a holder
    whose every change has expect (one only taken from); Invalid otherwise}], each holder a change names listed once. changes, made in order:
    [{holder: one of the holders' ids; field: "sleeves" or "deck_box"; value: an accessory id of
    that kind, or None to clear; expect (optional): apply it only while the holder still holds
    this value, so a move takes sleeves from a holder only if it still has them; loose (optional):
    a deck editor's header value, checked as a deck save checks one (ops_decks.check_kit): older
    free text that isn't an accessory id is kept as written, unchecked, and a deck box short of
    boxes is left to the warnings (AGENTS.md's "warns rather than blocks")}]. owners: whose
    accessories the asker sees (permissions.accessory_owners; None for all). editor: the profile
    a page's write is made by, which must be allowed deck.edit on every deck holder as it is now,
    a move's source included (permissions.reason; None: not checked, the command line and callers
    that checked it themselves). Sleeves other
    holders use are chosen as they are, whatever the change: one design may sleeve several decks
    and products, and both keep it (a move, with expect, is how one takes them from another).

    Refusals (AccessoryRefused): a holder that isn't there (404), a person's deck (400), a holder
    changed since it was read (409 "changed"), a holder whose kit isn't the owners' to choose
    (403), a deck the editor may not edit (403, with permissions' reason); a value that isn't
    an accessory of that kind the owners see, or one the holder's owner may not use, or a holder that isn't a built deck or a product kept intact (400); a deck box
    with quantity 0 (409), or a deck box every one of which is held (409 with extra taken_by),
    unless the holder already has it (neither for a loose change)."""
    from decklab.lib import accessories, decks
    owners = _owners(owners)
    if not isinstance(holders, (list, tuple)) or not isinstance(changes, (list, tuple)):
        raise Invalid("kit.set needs a list of holders and a list of changes")
    acc = _list(inv)
    loaded = {}
    for item in holders:
        hid = item.get("id") if isinstance(item, dict) else None
        if not isinstance(hid, str) or hid in loaded:
            raise Invalid("kit.set's holders each name a deck or product/<stem>, once")
        loaded[hid] = _Holder(inv, hid, item.get("expected"), owners, editor)
        if item.get("expected") is None and any(
                isinstance(c, dict) and c.get("holder") == hid and "expect" not in c for c in changes):
            raise Invalid(f"kit.set's holder {hid} needs its expected sha256: only a holder whose every change "
                          "has expect may leave it unchecked")
    chosen = []
    for change in changes:
        holder = loaded.get(change.get("holder")) if isinstance(change, dict) else None
        if holder is None:
            raise Invalid("each change names one of kit.set's holders")
        field, value = change.get("field"), change.get("value")
        if field not in KIT_FIELDS:
            raise Invalid(f"a holder's kit has no field {field!r}")
        if value is not None and not isinstance(value, str):
            raise Invalid("a kit value is an accessory id, or None")
        if "expect" in change and holder.value(field) != (change["expect"] or ""):
            continue
        what = _KIND_WORDS[field]
        loose = bool(change.get("loose"))
        if value is not None:
            row = acc.rows_by_id.get(" ".join(value.split()) if loose else value)
            if (row is None and not loose) or (row is not None and not accessories.visible(row["owner"], owners)) or (
                    row is not None and not loose and row["kind"] != field):
                raise AccessoryRefused(f"There's no {what} {value} in the accessories list", 400, ids=[holder.id])
            if row is not None and not accessories.usable(row["owner"], holder.owner):
                whose = ("only shared ones" if holder.owner == accessories.SHARED
                         else f"only {accessories.owner_name(holder.owner)}'s or shared ones")
                raise AccessoryRefused(f"{accessories.label(row)} {'are' if field == 'sleeves' else 'is'} "
                                       f"{accessories.owner_name(row['owner'])}'s: {holder.title} uses {whose}.",
                                       400, ids=[holder.id])
            if not holder.can_hold:
                raise AccessoryRefused(CANT_HOLD, 400, ids=[holder.id])
            if loose:
                pass        # older free text, a wrong kind, or kit already held: warnings, not refusals
            elif field == "deck_box" and row["quantity"] == 0 and holder.held[field] != value:
                raise AccessoryRefused(f"There are no {accessories.label(row)} deck boxes left (its quantity is 0). "
                                       "Set its quantity on the Accessories page, or choose another deck box.", 409,
                                       ids=[holder.id])
            else:
                chosen.append((holder, field, row))
        if holder.value(field) != (value or ""):
            holder.set(field, value)
    out, done = inv, {}
    status_rows = None
    for holder in loaded.values():
        if not holder.changed:
            continue
        if holder.product:
            status_rows = list(out.status.rows) if status_rows is None else status_rows
            status_rows[holder.index] = holder.row
            done.setdefault(paths.STATUS, []).extend(f"{f} of {holder.stem}" for f in holder.changed)
        else:
            out = out.with_deck(holder.deck.replace(text=decks.render_deck_file(holder.parsed)))
            done[holder.deck.path] = list(holder.changed)
    if status_rows is not None:
        out = out.with_status_rows(status_rows)
    if not done:
        return inv, Summary("Nothing to change")
    # Sleeves are never taken: one design may sleeve several holders (it's up to the players not to
    # play two of them at once). A deck box is one box per holder, up to the row's quantity.
    boxes = [(holder, row) for holder, field, row in chosen if field == "deck_box"]
    if boxes:
        _, found = usage(out)
        for holder, row in boxes:
            if holder.held["deck_box"] == row["id"]:
                continue                # it had it already: nothing new is taken
            others = [h for h in accessories.used_by(found, row) if h["holder"] != holder.id]
            if len(others) >= row["quantity"]:
                shown = shown_users(others, owners)
                raise AccessoryRefused(
                    f"{accessories._and(h['title'] for h in shown)} {'uses' if len(shown) == 1 else 'use'} "
                    f"every deck box of this kind. Move it here, or choose another deck box.", 409,
                    "taken", [holder.id], taken_by=[{"holder": h["holder"], "title": h["title"]} for h in shown])
    return out, Summary(f"Set the kit of {len(done)} holder{'s' if len(done) != 1 else ''}",
                        {"holders": len(done)}, done)
