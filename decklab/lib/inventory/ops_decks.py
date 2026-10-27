"""Phase 4's inventory operations: the decks, the kit holders, precons, the accessories and their
pictures (decklab/PLAN.md phase 4; the phase 4 design's amendment R4), registered like phase 3's
and run by inventory.apply() or preview() on either backend.

    from decklab.lib import inventory
    from decklab.lib.inventory import ops_decks
    inventory.apply(inventory.Op("deck.save", {"deck_id": "casual/gruul-ramp", "text": text,
                                               "base_sha256": sha}), actor, "save Gruul Ramp")

Operations take final text (R4): the pricing and rendering a page or the command line does
(apply_edit, the owned-vs-needed table, render_deck_file, new_deck_text) happen before apply,
against the current snapshot, never inside the backend's lock (a price fetch can take seconds).
An operation only checks and stores:

    deck.save          {deck_id, text, base_sha256}
    deck.create        {space, kind, slug, text, owners}
    deck.update_tables {items: [{id, text, base_sha256}]}      all or nothing
    deck.delete        {deck_id, base_sha256}
    kit.set            {holders: [{id, expected}], changes: [{holder, field, value, expect?}], owners}
    precon.add         {space, kind, slug, text, collection: {collection.import's params}, owners}
    accessory.add      {row, sha256, owners}
    accessory.edit     {id, row, sha256, owners}
    accessory.remove   {id, sha256, owners}
    image.put          {name, content}
    image.remove       {name}

base_sha256 is the sha256 of the deck's text as the page or command line read it (Deck.sha256,
decks.text_sha), always given (a string): the operation refuses when the deck has changed since
(DeckRefused, reason "changed"; the caller builds its "who changed it" answer). A text must parse
as a deck file (decks.parse_deck; DeckFileError's words, as Invalid). A save or table update that
gives the text the deck already has changes nothing; deck.update_tables names each deck once. A
new deck's slug must be a valid one and not be taken in its space by a deck of either kind,
compared without case (decks.existing_deck_id's rule, checked inside the operation). A deck that
is built and holds sleeves or a deck box can't be deleted (take it apart first).

The kit (the foundation review's H3). The Sleeves and Deck box header lines are written only by
kit.set, which checks who may choose them (owners: permissions.accessory_owners of whoever asks;
None for everything, a local command line). deck.save, deck.update_tables and the in-op table
refresh refuse a text whose (Sleeves, Deck box) differ from the deck's now, or that takes a built
deck holding them apart (its Status leaving "built"): DeckRefused, code 409, reason "kit"; kit.set
clears them first. deck.create (and precon.add) may give a new deck kit lines, checked as kit.set
checks a choice (each value an accessory id the owners see and the deck's owner may use, or older
free text: guard.require_kit_choice's rule; refused with code 400 or 403, reason "kit"). A deck in
a person's own space has no Played by, Sleeves or Deck box line (drafts._HOME_ONLY): a text adding
one, or changing one already there, is refused (Invalid); a value already in the file may stay.

A deck's Printings in box line (lib/decks/printings.py) is checked when a save or a new deck
changes it: it must describe what the built box holds (DeckRefused, code 400, reason
"printings"), and the space's built decks may not then record more copies of a printing than its
collection has where they recorded fewer before (code 409, reason "printings"). A save given
defer_printings (Finish building's several saves) leaves that check to its caller
(check_printings). A save whose physical build changes (allow_assembled) drops the parts the new
box can't hold.

kit.set, accessory.* and image.* are in ops_accessories.py (registered when this module is
imported).
"""
from decklab.lib.state import Conflict, Invalid

from . import Summary, files, register, rules
from .model import Deck

MAX_TEXT = 1024 * 1024                  # a deck text's most bytes (the history's 1 MiB limit)
# The header fields a deck in a person's own space doesn't have (drafts._HOME_ONLY's).
HOME_ONLY = {"Played by": "a deck in a person's own space has no Played by: it's theirs by where it's kept",
             "Sleeves": "sleeves are recorded only for the home decks (the accessories are home's)",
             "Deck box": "deck boxes are recorded only for the home decks (the accessories are home's)",
             "Printings in box": "printings in box are recorded only for the home decks (Build decks is home's)"}
KIT_FIELDS = ("sleeves", "deck_box")    # kit.set's fields, the header lines Sleeves and Deck box
KIT_ONLY = ("{deck_id}: the Sleeves and Deck box lines are chosen on their own (kit.set), not in a save "
            "of the deck's text")


class DeckRefused(Conflict):
    """A deck operation refused: code is the HTTP status a page answers with (400, 403, 404,
    409); reason is "changed" when a deck changed since it was read, "exists" for a slug already
    taken, "kit" for a change to the Sleeves or Deck box lines only kit.set may make (or a choice
    the owners may not make), else None; ids names the decks it's about (deck.update_tables lists
    every one that changed)."""

    def __init__(self, message, code=409, reason=None, ids=()):
        super().__init__(message)
        self.code = code
        self.reason = reason
        self.ids = list(ids)


def _field(deck_file, key):
    """A header field's value as written, trimmed ("" when there's none or no parse)."""
    return (deck_file.get_field(key) or "").strip() if deck_file is not None else ""


def kit_of(deck_file):
    """(Sleeves, Deck box) as a parsed text writes them ((None, None) for no parse): what only
    kit.set may change."""
    if deck_file is None:
        return None, None
    return deck_file.sleeves, deck_file.deck_box


def parsed_deck(deck):
    """The DeckFile a stored Deck's text holds, or None when it has none or can't be parsed."""
    from decklab.lib import decks
    if deck is None or deck.text is None:
        return None
    try:
        return decks.parse_deck(deck.text.encode("utf-8"), deck.slug, deck.kind, None, deck.space)
    except decks.DeckFileError:
        return None


def _parse(deck_id, text, space, kind, slug, before=None):
    """The DeckFile text holds; Invalid with DeckFileError's words when it can't be read, or for a
    home-only header field a person's deck gains or changes (before: the DeckFile the deck has
    now, whose values may stay)."""
    from decklab.lib import decks, spaces
    if not isinstance(text, str):
        raise Invalid(f"{deck_id}: the deck's text must be text")
    if "\0" in text:
        raise Invalid(f"{deck_id}: the deck's text holds a NUL character")
    if len(text.encode("utf-8")) > MAX_TEXT:
        raise Invalid(f"{deck_id}: the deck's text is over {MAX_TEXT // 1024} KiB")
    try:
        parsed = decks.parse_deck(text.encode("utf-8"), slug, kind, None, space)
        from decklab.lib.decks import assembled
        physical = assembled.get(parsed)
        assembled.generation(parsed)
        if physical is not None:
            if parsed.status != "built" and not (before is not None and before.status == "built"):
                raise assembled.AssembledError("An unbuilt deck cannot retain an active Assembled snapshot")
            if parsed.built_version is not None and parsed.built_version != physical["version"]:
                raise assembled.AssembledError("Built version and Assembled must describe the same physical list")
    except decks.DeckFileError as e:
        raise Invalid(f"{deck_id}: {e}") from None
    if space != spaces.HOME:
        for key, words in HOME_ONLY.items():
            value = _field(parsed, key)
            if value and value != _field(before, key):
                raise Invalid(f"{deck_id}: {words}")
    return parsed


def same_kit(deck_id, before, after):
    """DeckRefused (code 409, reason "kit") when after (a DeckFile) has other Sleeves or Deck box
    values than before, or stops a built deck holding them being built: only kit.set changes them."""
    held = any(kit_of(before))
    if kit_of(after) != kit_of(before) or (held and before.status == "built" and after.status != "built"):
        raise DeckRefused(KIT_ONLY.format(deck_id=deck_id), 409, "kit", [deck_id])


def check_kit(inv, deck_id, parsed, owners):
    """Sleeves and Deck box values a deck is given, checked as a choice is (guard.require_kit_choice's
    rule): each value that's an accessory id in inv's accessories.csv must be one owners
    (permissions.accessory_owners; None: all) see that the deck's owner may use (its own or
    shared); older free text isn't checked. DeckRefused (reason "kit", code 403 when the deck's
    kit isn't the owners' to choose, else 400) otherwise."""
    from decklab.lib import accessories, spaces
    chosen = [(key, value) for key, value in zip(KIT_FIELDS, kit_of(parsed)) if value]
    if not chosen:
        return
    if parsed.space not in (None, spaces.HOME):
        raise DeckRefused(f"{deck_id}: a deck in a person's own space has no sleeves or deck box.", 400, "kit",
                          [deck_id])
    owner = accessories.player_owner(parsed.player)
    if not accessories.visible(owner, owners):
        raise DeckRefused(f"{deck_id}: this deck's sleeves and deck box are {accessories.owner_name(owner)}'s "
                          "to choose.", 403, "kit", [deck_id])
    sheet = inv.accessories
    rows = accessories.parse(files.render_sheet(sheet)).rows_by_id if sheet.exists and sheet.error is None else {}
    for key, value in chosen:
        value = " ".join(value.split())
        row = rows.get(value)
        if row is None:
            continue                    # older free text
        what = "sleeves" if key == "sleeves" else "deck box"
        if not accessories.visible(row["owner"], owners):
            raise DeckRefused(f"{deck_id}: there's no {what} {value} in the accessories list", 400, "kit", [deck_id])
        if not accessories.usable(row["owner"], owner):
            raise DeckRefused(f"{deck_id}: {accessories.label(row)} {'are' if key == 'sleeves' else 'is'} "
                              f"{accessories.owner_name(row['owner'])}'s, not this deck's to use.", 400, "kit",
                              [deck_id])


def _owners(owners):
    """owners as a frozenset, or None (everything)."""
    return None if owners is None else frozenset(owners)


def _current(inv, deck_id, base_sha256):
    """The Deck deck_id names, checked against base_sha256 (DeckRefused otherwise; Invalid when
    no sha256 is given)."""
    if not isinstance(base_sha256, str) or not base_sha256:
        raise Invalid(f"{deck_id}: the sha256 of the deck as it was read must be given")
    deck = inv.decks.get(deck_id)
    if deck is None:
        raise DeckRefused(f"There's no deck {deck_id}.", 404, ids=[deck_id])
    if deck.error is not None:
        raise DeckRefused(f"{deck_id} can't be read ({deck.error}){rules.UNTIL_PUT_RIGHT}", 409, ids=[deck_id])
    if deck.sha256 != base_sha256:
        raise DeckRefused(f"{deck_id} changed after you opened it.", 409, "changed", [deck_id])
    return deck


def space_printings(inv, space):
    """{deck_id: [PrintingLine]} of a space's built decks with a readable Printings in box line."""
    from decklab.lib.decks import printings
    out = {}
    for deck in inv.decks.values():
        if deck.space != space:
            continue
        parsed = parsed_deck(deck)
        if parsed is None or parsed.status != "built":
            continue
        try:
            lines = printings.printings(parsed)
        except Exception:       # an unreadable line is the deck's own problem (db check), not this save's
            continue
        if lines:
            out[deck.id] = lines
    return out


def check_printings(before, after, deck_ids):
    """DeckRefused when a deck of deck_ids whose Printings in box line differs between the
    snapshots before and after has a record its box can't hold (code 400), or when after's built
    decks record more copies of a printing than the collection has, and more than before did
    (code 409). Parts no save here changed stay as they are."""
    from decklab.lib.decks import printings
    changed, spaces_seen = [], set()
    for deck_id in deck_ids:
        new = after.deck(deck_id)
        parsed = parsed_deck(new)
        if parsed is None:
            continue
        old = parsed_deck(before.deck(deck_id))
        try:
            lines = printings.printings(parsed) if parsed.status == "built" else []
        except Exception as e:
            raise DeckRefused(f"{deck_id}: {e}", 400, "printings", [deck_id]) from None
        try:
            was = printings.printings(old) if old is not None and old.status == "built" else []
        except Exception:
            was = None
        if lines == was:
            continue
        problems = printings.local_problems(lines, printings.held_counts(parsed))
        if problems:
            raise DeckRefused(f"{parsed.title}: the printings in box don't fit the box: " + "; ".join(problems),
                              400, "printings", [deck_id])
        changed.append((deck_id, parsed, lines))
        spaces_seen.add(new.space)
    for space in spaces_seen:
        owned = printings.capacity(after.collection(space).rows)
        for deck_id, parsed, lines in changed:
            if after.deck(deck_id).space == space:
                problems = printings.problems_against(lines, owned)
                if problems:
                    raise DeckRefused(f"{parsed.title}: " + "; ".join(problems), 400, "printings", [deck_id])
        was, now = printings.totals(space_printings(before, space)), printings.totals(space_printings(after, space))
        for key, copies in sorted(now.items()):
            have = owned.get(key, ("", 0))
            if copies > have[1] and copies > was.get(key, 0):
                label = printings.PrintingLine(1, have[0], *key).label()
                ids = [deck_id for deck_id, _, lines in changed if any(line.key == key for line in lines)]
                raise DeckRefused(f"{have[0] or 'A card'} {label}: the built decks would record {copies} "
                                  f"in their boxes, but the collection has {have[1]}.", 409, "printings", ids)


def _physical_save(deck_id, before, after, allow_assembled=False):
    """Old clients cannot overwrite physical reservations through a text save."""
    from decklab.lib import decks
    from decklab.lib.decks import assembled, standins
    if after.status != "built":
        serial = assembled.generation(before) if before is not None else assembled.generation(after)
        assembled.clear(after, serial=serial + 1 if before is not None and before.status == "built" else serial or None)
        return decks.render_deck_file(after)
    current = assembled.get(before) if before is not None else None
    proposed = assembled.get(after)
    if (not allow_assembled and before is not None
            and assembled.generation(before) != assembled.generation(after)):
        raise DeckRefused(f"{deck_id}: physical assembly history is changed in Build decks.",
                          409, "assembled", [deck_id])
    if not allow_assembled and current:
        if (current != proposed or assembled.generation(before) != assembled.generation(after)
                or before.built_version != after.built_version
                or standins.installed_for(before) != standins.installed_for(after)):
            raise DeckRefused(f"{deck_id}: take this deck apart before changing its physical build, "
                              "or refresh and repack it in Build decks.", 409, "assembled", [deck_id])
    elif not allow_assembled and proposed:
        raise DeckRefused(f"{deck_id}: physical assembly is recorded in Build decks.", 409, "assembled", [deck_id])
    elif not allow_assembled and before is not None and before.status == "built":
        # Freeze the old physical recipe before an intended-list edit can move cards.
        if (assembled.version(before) == assembled.version(after)
                and decks.clean_sections(assembled.sections(before)) != decks.clean_sections(assembled.sections(after))):
            assembled.install(after, assembled.version(before), assembled.sections(before))
    if allow_assembled:
        from decklab.lib.decks import printings
        try:
            lines = printings.printings(after)
        except decks.DeckFileError:
            lines = None
        if lines:
            printings.set_printings(after, printings.trim(lines, printings.held_counts(after)))
    return decks.render_deck_file(after)


@register("deck.save")
def save(inv, *, deck_id, text, base_sha256, allow_assembled=False, defer_printings=False):
    """The deck's text replaced by text (see the module docstring)."""
    deck = _current(inv, deck_id, base_sha256)
    before = parsed_deck(deck)
    parsed = _parse(deck_id, text, deck.space, deck.kind, deck.slug, before)
    text = _physical_save(deck_id, before, parsed, allow_assembled)
    if text == deck.text:
        return inv, Summary("Nothing to change")
    same_kit(deck_id, before, parsed)
    out = inv.with_deck(deck.replace(text=text))
    if not defer_printings:
        check_printings(inv, out, [deck_id])
    return out, Summary(
        f"Saved {parsed.title}", {"decks": 1}, {deck.path: ["text"]}, {"deck": deck_id})


@register("deck.create")
def create(inv, *, space, kind, slug, text, owners=frozenset()):
    """A new deck (see the module docstring). owners: whose accessories the creator sees
    (permissions.accessory_owners; None for all), for any Sleeves or Deck box line the text has."""
    from decklab.lib import decks, spaces
    if kind not in decks.KINDS:
        raise Invalid(f"kind must be one of {', '.join(decks.KINDS)}, not {kind!r}")
    if not decks.valid_slug(slug):
        raise Invalid(decks._slug_problem(slug))
    if not spaces.exists(space):
        raise DeckRefused(f"There's no space {space!r}.", 404)
    deck = Deck(space, kind, slug, text)
    taken = next((d for d in inv.decks.values() if d.space == space and d.slug.lower() == slug.lower()), None)
    if taken is not None:
        raise DeckRefused(f"{taken.id} already exists.", 409, "exists", [taken.id])
    from .ops_rename import reserved
    former = reserved(inv, space, slug)
    if former is not None:
        raise DeckRefused("That deck id is retained as a former name of another deck.", 409, "exists", [former])
    parsed = _parse(deck.id, text, space, kind, slug)
    check_kit(inv, deck.id, parsed, _owners(owners))
    if parsed.status != "built" and _field(parsed, "Printings in box"):
        raise DeckRefused(f"{deck.id}: only a built deck has printings in its box.", 400, "printings", [deck.id])
    out = inv.with_deck(deck)
    check_printings(inv, out, [deck.id])
    return out, Summary(f"Created {parsed.title}", {"decks": 1}, {deck.path: ["created"]},
                                        {"deck": deck.id})


@register("deck.update_tables")
def update_tables(inv, *, items):
    """Several decks' texts replaced at once, or none (DeckRefused listing every deck that
    changed since it was read, or is gone)."""
    out, done = _save_many(inv, "deck.update_tables", "the tables were worked out", items, "table")
    if not done:
        return inv, Summary("Nothing to change")
    return out, Summary(f"Updated the tables of {len(done)} deck{'s' if len(done) != 1 else ''}",
                        {"decks": len(done)}, done)


@register("deck.token_cards")
def token_cards(inv, *, items, expected_inventory_revision=None, expected_decks_revision=None):
    """Several built decks' texts replaced at once with new Token cards lines (the Tokens page's
    plan, lib/api/token_plan.py), or none, as deck.update_tables."""
    if expected_inventory_revision is not None and inv.revision != expected_inventory_revision:
        raise DeckRefused("The inventory changed after the token cards were planned.", 409, "changed")
    if expected_decks_revision is not None and inv.decks_revision != expected_decks_revision:
        raise DeckRefused("The decks changed after the token cards were planned.", 409, "changed")
    out, done = _save_many(inv, "deck.token_cards", "the token cards were planned", items, "token cards")
    if not done:
        return inv, Summary("Nothing to change")
    return out, Summary(f"Packed token cards in {len(done)} deck{'s' if len(done) != 1 else ''}",
                        {"decks": len(done)}, done)


def _save_many(inv, kind, when, items, field):
    """(inventory, {path: [field]}): items ([{id, text, base_sha256}]) saved one after another,
    each as deck.save would, refusing all of them when one changed since `when` or is gone."""
    ids = [item["id"] for item in items]
    twice = sorted({i for i in ids if ids.count(i) > 1})
    if twice:
        raise Invalid(f"{kind} names {', '.join(twice)} more than once")
    changed = [item["id"] for item in items
               if inv.decks.get(item["id"]) is None or inv.decks[item["id"]].sha256 != item.get("base_sha256")]
    if changed:
        raise DeckRefused(f"{', '.join(changed)} changed after {when}.", 409, "changed", changed)
    out, done = inv, {}
    for item in items:
        deck = _current(out, item["id"], item.get("base_sha256"))
        before = parsed_deck(deck)
        parsed = _parse(deck.id, item["text"], deck.space, deck.kind, deck.slug, before)
        text = _physical_save(deck.id, before, parsed)
        if text != deck.text:
            same_kit(deck.id, before, parsed)
            out = out.with_deck(deck.replace(text=text))
            done[deck.path] = [field]
    return out, done


@register("deck.delete")
def delete(inv, *, deck_id, base_sha256):
    """The deck removed (its history stays with the backend's revisions). Refuses a built deck
    that holds sleeves or a deck box."""
    deck = _current(inv, deck_id, base_sha256)
    parsed = _parse(deck_id, deck.text, deck.space, deck.kind, deck.slug, parsed_deck(deck))
    if parsed.status == "built" and (parsed.sleeves or parsed.deck_box):
        raise DeckRefused(f"{parsed.title} is built and holds sleeves or a deck box: take it apart first.",
                          409, "kit", [deck_id])
    return inv.without_deck(deck_id), Summary(f"Deleted {parsed.title}", {"decks": 1}, {deck.path: ["deleted"]},
                                              {"deck": deck_id})


@register("precon.add")
def add_precon(inv, *, space, kind, slug, text, collection, owners=frozenset(), token_rows=(), tokens_sha256=None):
    """A precon's cards merged into the space's collection (collection.import, with collection
    as its parameters) and its deck created (deck.create, owners as its), on the same snapshot:
    one change."""
    from . import ops_collection
    merged, imported = ops_collection.merge(inv, **dict(collection))
    token_cards = 0
    if token_rows:
        from decklab.lib import precon_tokens
        from decklab.lib.tokens import ops as token_ops
        expected = tokens_sha256
        for row in token_rows:
            try:
                merged, _ = token_ops.add(merged, space=space, sha256=expected, row=row, separate=True)
            except token_ops.Stale:
                raise
            except Conflict:
                raise precon_tokens.TokenConflict("The token cards need a fresh preview before this precon can be added.") from None
            token_cards += int(row["quantity"])
            sheet = merged.token_set(space)
            expected = files.rendered_sha256(sheet) if sheet.exists else None
    made, created = create(merged, space=space, kind=kind, slug=slug, text=text, owners=owners)
    extra = {**(imported.extra or {}), **(created.extra or {})}
    counts = {**imported.counts, **created.counts}
    words = f"{imported.text}; {created.text}"
    if token_rows:
        counts.update(token_cards=token_cards, token_rows=len(token_rows))
        words += f"; added {token_cards} token cards with printing and reverse face unconfirmed"
    return made, Summary(words, counts,
                         {**imported.changed, **created.changed}, extra)


KINDS = ("deck.save", "deck.create", "deck.update_tables", "deck.delete", "deck.rename", "kit.set", "precon.add",
         "accessory.add", "accessory.edit", "accessory.remove", "image.put", "image.remove")

# The accessory, picture and kit operations (kit.set, accessory.*, image.*) live in their own module;
# importing this one registers them too.
from . import ops_accessories  # noqa: E402,F401
from . import ops_rename  # noqa: E402,F401
