"""The editor's endpoints that write: POST /api/deck/save (save_deck), POST
/api/decks (create_deck), GET /api/tables/stale (stale_view) and POST
/api/tables/update (update_tables).

Each save is one inventory operation (decklab/lib/inventory/ops_decks.py;
the phase 4 design's R4), saved in Deck Lab's storage with who made it, as
every inventory change is: deck.save, deck.create, deck.update_tables, and
kit.set for a change to a deck's Sleeves or Deck box. The page's work (the
lists and fields applied, the owned-vs-needed table priced, the text
rendered) happens first, against the request's snapshot; the operation then
checks the deck still has the sha256 the page read (else 409, naming who
saved it since: commits._conflict) and stores the text. Nothing is
committed to git.

_today and _stale_after live here only, beside the endpoints that read
them (tests patch both here).
"""
import contextlib
import threading
from datetime import date

from decklab.lib import decks, inventory, pool, spaces
from decklab.lib.inventory import ops_decks

from . import drafts, guard
from .carddata import _require_cards
from .commits import (_conflict, _deck_file, _parse_file, _rewrite_table, _stale_list, _stored,
                      _without_own_built_warning)
from .common import (_CONTROL_RE, DATABASE_DOWN, ApiError, _flag, _keys, _parse_body, _public, _scrub, _sha,
                     _strip_paths, _unique)
from .drafts import _blocks_error, _bracket_names, _new_fields, _rule_warnings, _warnings_json
from .editor import _new_source, edit_view
from .library import _load_pool, visible_unresolved
from .settings import _web_actor, _writer

MAX_TITLE = 100                 # characters in a new deck's title
MAX_TABLE_DECKS = 200           # decks in one update_tables() request (the Decks page's Update all: one change)
# Held around every inventory write with the files backend (inventory_write_lock: deck
# saves, accessory and kit saves, collection and token saves, receipts).
_save_lock = threading.Lock()


def inventory_write_lock():
    """What an inventory write holds around inventory.apply (the lock order: _save_lock first,
    then apply's own lock). With the files backend,
    _save_lock: a second writer in this server waits here instead of finding the inventory lock
    taken (BUSY), and the decks a refreshing write (a receipt, an order or product change:
    refresh.in_op) rewrites inside its change are written under it as a deck save's are. With
    the database, nothing: its advisory lock queues the writers (phase 3 design, P6). Every deck
    write (deck.*, precon.add) and every accessory write (accessory.*, image.*, and kit.set: any
    sleeve or deck-box move between decks and products is one operation, api/accessories.py)
    goes through it."""
    return _save_lock if getattr(inventory.backend(), "name", None) == "files" else contextlib.nullcontext()


def _today():
    """Today's date for the "Decklist changed" line (the tests fix it)."""
    return date.today().isoformat()


def _stale_after(exclude, warnings):
    """Other deck files whose tables no longer match the pool, after a write
    (_stale_list); the pool's warnings, as it is after the write, go in warnings
    when this visitor may see home's inventory (R6d)."""
    seen = []
    stale = _stale_list(_load_pool(seen), exclude)
    if guard.sees_inventory(spaces.HOME):
        warnings.extend(seen)
    return stale


# ---- running a deck operation

class _KitThenSave:
    """deck.save of the page's text and kit.set for that deck's Sleeves and Deck box, as one
    change (inventory.apply runs any object with run(inv)): a save that chooses, changes or
    clears a deck's kit (deck.save alone refuses any change to those lines, ops_decks.same_kit).
    The order follows the deck's status, since kit.set gives sleeves or a deck box only to a
    built deck: a save that makes a deck built saves the text first (with the kit lines as they
    were) and then chooses its kit; any other (a deck taken apart, or one that stays built) has
    its kit changed first, then the text saved on what that leaves."""
    kind = "deck.save"

    def __init__(self, deck_id, text, base_sha256, changes, owners, building=False):
        self.params = {"deck_id": deck_id, "text": text, "base_sha256": base_sha256, "changes": changes,
                       "owners": owners}
        self.building = building

    def _kit(self, inv, expected):
        p = self.params
        return inventory.Op("kit.set", {"holders": [{"id": p["deck_id"], "expected": expected}],
                                        "changes": p["changes"], "owners": p["owners"]}).run(inv)

    def _save(self, inv, text, base):
        return inventory.Op("deck.save", {"deck_id": self.params["deck_id"], "text": text,
                                          "base_sha256": base}).run(inv)

    def run(self, inv):
        p = self.params
        if self.building:
            inv, _ = self._save(inv, _with_kit(p["text"], inv.deck(p["deck_id"])), p["base_sha256"])
            return self._kit(inv, _held_sha(inv, p["deck_id"], p["base_sha256"]))
        inv, _ = self._kit(inv, p["base_sha256"])
        return self._save(inv, p["text"], _held_sha(inv, p["deck_id"], p["base_sha256"]))


def _held_sha(inv, deck_id, fallback):
    held = inv.deck(deck_id)
    return held.sha256 if held is not None else fallback


def _with_kit(text, held):
    """text (the page's for the deck inventory model.Deck held stores) with the Sleeves and Deck
    box lines held has: the page's text without the kit it chooses, for the deck.save before
    kit.set chooses it (text as it is when held is gone or won't parse: deck.save refuses then)."""
    kit = ops_decks.kit_of(ops_decks.parsed_deck(held))
    if held is None:
        return text
    try:
        deck = decks.parse_deck(text.encode("utf-8"), held.slug, held.kind, None, held.space)
    except decks.DeckFileError:
        return text
    if ops_decks.kit_of(deck) == kit:
        return text
    decks.set_sleeves(deck, kit[0])
    decks.set_deck_box(deck, kit[1])
    return decks.render_deck_file(deck)


def _refused(e):
    """The page's answer to an inventory refusal that isn't about a particular deck: Invalid
    400, Unavailable 503 (the database down, or not holding the decks yet), Conflict 409."""
    if isinstance(e, inventory.Unavailable):
        if str(e) == inventory.DECK_SAVES_PAUSED:
            return ApiError(503, inventory.DECK_SAVES_PAUSED)
        return ApiError(503, DATABASE_DOWN, reason="database")
    if isinstance(e, inventory.Invalid):
        return ApiError(400, _public(e))
    return ApiError(409, _public(e))


def apply_op(op, profile, message, refused=None, *, reason=None):
    """inventory.apply(op) as profile (settings._web_actor), under inventory_write_lock: (the
    inventory after, Summary). refused(error) turns a refusal into the page's answer first
    (an ApiError, or None to leave it to the default: a DeckRefused with its code and words,
    else _refused)."""
    try:
        with inventory_write_lock():
            return inventory.apply(op, _web_actor(profile), message, **({"reason": reason} if reason is not None else {}))
    except (inventory.Invalid, inventory.Conflict, inventory.Unavailable) as e:
        mapped = refused(e) if refused is not None else None
        if mapped is not None:
            raise mapped from None
        if isinstance(e, ops_decks.DeckRefused):    # kit.set's refusals too (they add extra keys)
            raise ApiError(e.code, _public(e), **(getattr(e, "extra", None) or {})) from None
        raise _refused(e) from None


def _deck_refused(deck_id, title, profile):
    """apply_op's refused for an operation on one deck (deck.save, and kit.set in a _KitThenSave):
    a deck changed since (409) or gone (404: the 409 for a deleted deck) gets _conflict's answer."""
    def refused(e):
        if not isinstance(e, ops_decks.DeckRefused):
            return None
        if e.reason == "changed":
            return _conflict(deck_id, title, viewer=profile)
        if e.code == 404 and e.reason is None:
            from .deck_aliases import after_refusal
            moved = after_refusal(deck_id, profile)
            if moved is not None:
                return moved
            return _conflict(deck_id, title, deleted=True, viewer=profile)
        return None
    return refused


def _kit_changes(deck_id, before, after):
    """kit.set's changes for a save that leaves the deck with after's (Sleeves, Deck box)
    instead of before's ([] when they're the same). Each is loose: the editor's header values are
    checked as a deck save checks them (older free text kept as written, sleeves another deck has
    a warning, not a refusal), unlike the picker's choices (api/accessories.py)."""
    return [{"holder": deck_id, "field": field, "value": now or None, "loose": True}
            for field, was, now in zip(ops_decks.KIT_FIELDS, ops_decks.kit_of(before), ops_decks.kit_of(after))
            if (was or None) != (now or None)]


# ---- the endpoints

def save_deck(body):
    """POST /api/deck/save {"profile", "id", "sha256", "lists"?, "fields"?, "confirm_empty"?}.

    The deck must still have sha256 (else ApiError 409 with "conflict", see
    commits._conflict); a draft with blocks is refused (400 with "blocks");
    the lists and fields are applied (decks.apply_edit, which adds the
    "Decklist changed" line when a list changed); if anything changed, the
    owned-vs-needed table is rewritten (_rewrite_table) and the text saved
    in Deck Lab (deck.save, "save <Title>"; a change of Sleeves or Deck box
    goes through kit.set in the same change). A save that changes nothing
    saves nothing.

    prose ({"substitutes"?, "notes"?}: the write-up, the editor's Notes tab;
    drafts._read_prose) replaces those sections' text, and mark_current
    true takes the "Decklist changed" line off (it isn't added either, when
    the list changes in the same save). Neither changes the table.

    Returns saved, id, title, sha256 (the deck's new hash), changed, marked
    (the "Decklist changed" date, when a list changed and the line wasn't
    taken off), unmarked (the line was there and is gone), table
    (_rewrite_table's answer), bracket, warnings and warning_cards (as
    check_draft's), stale_tables (other decks whose tables are now out of
    date, _stale_list) and deck (edit_view of the saved deck).

    An empty target list for a deck that has cards needs "confirm_empty":
    true (a block otherwise). Taking a built deck apart (status built ->
    building or idea) removes its Built version, Sleeves and Deck box."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "sha256"), ("lists", "fields", "confirm_empty", "prose", "mark_current"))
    _flag(data, "confirm_empty")
    mark_current = _flag(data, "mark_current")
    prose = drafts._read_prose(data)
    kind, slug, path = _deck_file(data["id"])
    sha = _sha(data["sha256"])
    deck_id = data["id"]
    _require_cards()
    stored = _stored(deck_id, viewer=profile)
    deck = _parse_file(stored.data, kind, slug, path, deck_id)
    before = _parse_file(stored.data, kind, slug, path, deck_id)
    guard.require(profile, "deck.edit", deck)
    if stored.sha256 != sha:        # who changed it is told only to someone who may edit it
        raise _conflict(deck_id, deck.title, viewer=profile)
    if not deck.has_decklist:
        raise ApiError(500, f"{deck_id} can't be saved: it has {decks.NO_DECKLIST}")
    draft = drafts._read_draft(data, kind, deck)
    guard.require(profile, "deck.edit", guard.deck_after(deck, draft.fields))
    choosing = guard.accessories_changed(deck, draft.fields)
    if choosing:
        guard.require_kit_choice(profile, guard.deck_after(deck, draft.fields), draft.fields)
    _require_kit_moves(profile, deck, draft.fields)
    bracket = _rule_warnings(draft, deck)
    if draft.blocks:
        raise _blocks_error(draft.blocks)
    warnings = []
    try:
        changes = decks.apply_edit(deck, draft.lists["target"], draft.lists["owned"], draft.fields,
                                   _today(), _bracket_names(), considering=draft.lists["considering"])
    except ValueError as e:
        raise ApiError(400, f"The deck can't be saved: {e}") from None
    if mark_current:
        # The write-up is current (the editor's "Mark write-up as current"): the line goes, even when this
        # save changes the list too.
        deck.changed_on = None
    table = {"rewritten": False, "repriced": False, "note": None}
    if changes["decklist"] or changes["fields"]:
        # The pool as it is before the save: this deck's own changes don't
        # count in its table (pool.self_ids). Its warnings come from after.
        table = _rewrite_table(deck, _load_pool([], deck.space))
    try:
        out = decks.render_deck_file(deck)
    except (decks.DeckFileError, ValueError) as e:
        raise ApiError(500, f"{deck_id} can't be saved: {_public(e)}") from None
    if prose:
        out = _with_prose(out, prose, deck, slug, kind, path)
    new_sha = sha
    if out != stored.text:
        kit = _kit_changes(deck_id, before, decks.parse_deck(out.encode("utf-8"), slug, kind, path, deck.space))
        # A kit only freed (a deck taken apart) is no choice to check: anyone who may edit the deck may.
        building = before.status != "built" and deck.status == "built"
        op = (_KitThenSave(deck_id, out, sha, kit, guard.accessory_owners(profile) if choosing else None, building)
              if kit else inventory.Op("deck.save", {"deck_id": deck_id, "text": out, "base_sha256": sha}))
        after, _ = apply_op(op, profile, f"save {deck.title}", _deck_refused(deck_id, deck.title, profile))
        # As stored: kit.set may place a kit line elsewhere than the page's text did.
        new_sha = _held_sha(after, deck_id, decks.text_sha(out))
    stale = _stale_after({deck_id}, warnings)
    shown, about = _warnings_json(draft.warnings + _without_own_built_warning(warnings, deck_id), draft.about)
    return {"saved": True, "id": deck_id, "title": deck.title, "sha256": new_sha, "changed": out != stored.text,
            "marked": deck.changed_on if changes["decklist"] else None, "table": table,
            "unmarked": bool(mark_current and before.changed_on),
            "bracket": bracket, "stale_tables": stale, "warnings": shown, "warning_cards": about,
            "deck": edit_view(deck_id)}


def _with_prose(out, prose, deck, slug, kind, path):
    """out (a deck's rendered text) with its write-up replaced (drafts.with_prose); ApiError 400 when the new
    text would read differently anywhere but the write-up (its lists, table, header or marker)."""
    text = drafts.with_prose(out, prose, deck.newline)
    if text == out:
        return out
    try:
        was = decks.parse_deck(out.encode("utf-8"), slug, kind, path, deck.space)
        now = decks.parse_deck(text.encode("utf-8"), slug, kind, path, deck.space)
    except decks.DeckFileError as e:
        raise ApiError(400, f"The write-up can't be saved: {_public(e)}") from None
    same = lambda d: (d.title, d.fields, d.target, d.owned, d.considering, d.rows, d.total, d.changed_on,  # noqa: E731
                      d.prices)
    if same(was) != same(now):
        raise ApiError(400, "The write-up can't be saved: it would change how the deck's lists, table or header "
                            "are read")
    return text


def _require_kit_moves(profile, deck, fields):
    """A save changing the Played by of a built deck that holds Sleeves or a Deck box hands that
    kit to the new owner, so it's an accessories change: the profile must see the stored owner's
    kit (guard.sees_kit; 403 otherwise, without naming it) and may choose it for the new owner
    (guard.require_kit_choice over the kit the deck keeps)."""
    from decklab.lib import accessories
    if "player" not in fields or fields["player"] == deck.player:
        return
    if (fields.get("status") or deck.status) != "built":
        return                          # taken apart: its kit is freed, not handed on
    kit = {key: fields[key] if key in fields else getattr(deck, key, None) for key in accessories.HOLDER_FIELDS}
    stored = [getattr(deck, key, None) for key in accessories.HOLDER_FIELDS]
    if not any(stored):
        return
    owners = guard.accessory_owners(profile)
    if not guard.sees_kit({"space": deck.space, "player": deck.player}, owners):
        raise ApiError(403, "This deck's sleeves and deck box aren't yours to hand on: only their owner can "
                            "change who plays it while it holds them.")
    guard.require_kit_choice(profile, guard.deck_after(deck, fields),
                             {key: value or "" for key, value in kit.items()})


def create_deck(body):
    """POST /api/decks {"profile", "title", "kind" | "from", "space"?, "fields"?, "lists"?}: a new deck.

    From scratch ("kind": casual or commander) or "Save as a new deck" from
    any library deck ("from": a product deck, Beginner Box half or pairing;
    the kind follows it). lists holds only "target" (default: the source's
    list, or empty). fields: archetype, player (default: the profile's
    plays_as), status (default idea), sleeves and deck_box (a built deck's:
    an accessory id, or free text) and, for Commander, target_bracket
    (default 2). space (lib/spaces.py) is whose deck it is: "home" or a
    person's space (ApiError 404 for one config.json doesn't list); by
    default the profile's own (drafts._new_space). A member may create only
    in their own space, or at home Played by them (guard.py: 403). A
    person's deck has no Played by line (it's theirs by where it lives), and
    no Sleeves or Deck box (accessories are home's), so those fields are
    blocks there; its table is worked out from their pool, and its id is
    "<space>/<kind>/<slug>". The slug comes from the title
    (decks.title_slug); one taken by a deck of either kind in the space is
    ApiError 409 with "conflict". The text is decks.new_deck_text with the
    table worked out from the pool and the rate line in AGENTS.md's wording,
    saved in Deck Lab as "new deck <Title>" (deck.create). Returns (sent
    with 201) created, id, title, sha256, table, bracket, warnings,
    warning_cards (as check_draft's), stale_tables and deck (edit_view)."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "title"), ("kind", "from", "space", "fields", "lists"))
    return write_new_deck(plan_new_deck(data, profile))


def plan_new_deck(data, profile, notes=None):
    """Everything create_deck checks before it saves, for data (its body,
    parsed) by profile: ApiError for a refusal or a draft with blocks.
    Returns the plan write_new_deck() takes. notes: the new deck's Notes
    section, instead of create_deck's "Started in Deck Lab ..." line."""
    space = drafts._new_space(data, profile)
    require_sees_space(space, profile)
    guard.require(profile, "deck.create", {"space": space, "player": None})
    _require_cards()
    kind, source, summary = _new_source(data)
    draft = drafts._read_draft(data, kind, source=source, space=space)
    title = data["title"]
    # Invisible characters (a zero-width space, a bidi override) are dropped first,
    # so a title of nothing else is empty, and the text, slug and message agree.
    title = decks.clean_title(title) if isinstance(title, str) and not _CONTROL_RE.search(title) else None
    if not title or len(title) > MAX_TITLE:
        draft.block(f"The title must be one line of 1-{MAX_TITLE} characters", field="title")
        title, slug = "", ""
    else:
        slug = decks.title_slug(title)
        if not decks.valid_slug(slug):
            draft.block("The title needs some letters or digits for the deck's name (and can't be a Windows "
                        "device name such as con or aux)", field="title")
    if draft.lists["target"] is None:
        draft.lists["target"] = decks.clean_sections(source)
    draft.fields = fields = _new_fields(draft, kind, profile, space)
    guard.require(profile, "deck.create", {"space": space, "player": fields.get("player")})
    if guard.accessories_changed(None, fields):
        guard.require_kit_choice(profile, {"space": space, "player": fields.get("player")}, fields)
    bracket = _rule_warnings(draft, None)
    if draft.blocks:
        raise _blocks_error(draft.blocks)
    header = [("Format", decks.FORMATS[kind])]
    if fields.get("archetype"):
        header.append(("Archetype", fields["archetype"]))
    if fields.get("player"):
        header.append(("Played by", fields["player"]))
    header.append(("Status", fields["status"]))
    if kind == "commander":
        name = _bracket_names().get(fields["target_bracket"])
        header.append(("Target bracket", f"{fields['target_bracket']} ({name})" if name else
                       str(fields["target_bracket"])))
    if fields.get("sleeves"):
        header.append(("Sleeves", fields["sleeves"]))
    if fields.get("deck_box"):
        header.append(("Deck box", fields["deck_box"]))
    if notes is None:
        notes = (f"Started in Deck Lab on {_today()} by {profile['name']}, from {summary['title']}."
                 if summary else "")
    try:        # the text, made now so a caller saves nothing else before a refusal
        deck = decks.parse_deck(decks.new_deck_text(title, kind, header, draft.lists["target"], notes=notes)
                                .encode("utf-8"), slug, kind, decks.deck_path(kind, slug, space), space)
    except (decks.DeckFileError, ValueError) as e:
        raise ApiError(400, f"The deck can't be created: {_public(e)}") from None
    return {"profile": profile, "space": space, "kind": kind, "title": title, "slug": slug, "deck": deck,
            "draft": draft, "bracket": bracket}


# The 403 for a new deck in a space whose decks the viewer can't see (E10-S30).
HIDDEN_SPACE = guard.HIDDEN_SPACE


def require_sees_space(space, profile=False):
    """ApiError 403 (HIDDEN_SPACE) unless profile (the request's viewer by default) may see
    space's decks (guard.sees_deck, no admin override, E10-S30): checked before deck.create
    and before the name is looked up, so a new deck's 409 never tells whether a hidden deck
    has that name, and nothing is saved that its maker couldn't then open."""
    if not guard.sees_deck({"space": space}, profile):
        raise ApiError(403, HIDDEN_SPACE)


def _taken(slug, existing):
    """The 409 for a new deck whose name another deck of the space has."""
    return ApiError(409, f"There's already a deck called {slug} ({existing}): pick another title.",
                    conflict={"reason": "exists", "id": existing})


def check_free(plan):
    """ApiError 409 (_taken) when the plan's slug is taken in its space, by a deck of either
    kind (compared without case; deck.create checks again as it saves)."""
    existing = decks.existing_deck_id(plan["slug"], plan["space"])
    if existing:
        raise _taken(plan["slug"], existing)


def new_deck_text(plan):
    """(deck id, the table's answer, the text) of the deck plan_new_deck() planned: its table
    worked out from the pool as it is (ApiError 400 when it can't be rendered)."""
    space, kind, slug, deck = (plan[k] for k in ("space", "kind", "slug", "deck"))
    try:
        table = _rewrite_table(deck, _load_pool([], space))     # the pool's warnings come from after the save
        text = decks.render_deck_file(deck)
    except (decks.DeckFileError, ValueError) as e:
        raise ApiError(400, f"The deck can't be created: {_public(e)}") from None
    return spaces.join_deck_id(space, kind, slug), table, text


def new_deck_refused(plan):
    """apply_op's refused for an operation creating plan's deck: a name taken meanwhile is 409
    (_taken)."""
    def refused(e):
        if isinstance(e, ops_decks.DeckRefused) and e.reason == "exists":
            return _taken(plan["slug"], e.ids[0] if e.ids else plan["slug"])
        return None
    return refused


def created_answer(plan, deck_id, table, text, warnings=None):
    """create_deck's answer for the deck just saved."""
    warnings = list(warnings or [])
    draft = plan["draft"]
    stale = _stale_after({deck_id}, warnings)
    shown, about = _warnings_json(draft.warnings + warnings, draft.about)
    return {"created": True, "id": deck_id, "title": plan["title"], "sha256": decks.text_sha(text), "table": table,
            "bracket": plan["bracket"], "stale_tables": stale, "warnings": shown, "warning_cards": about,
            "deck": edit_view(deck_id)}


def write_new_deck(plan):
    """Save the deck plan_new_deck() planned (deck.create, "new deck <Title>"): create_deck's
    answer."""
    check_free(plan)
    deck_id, table, text = new_deck_text(plan)
    apply_op(inventory.Op("deck.create", {"space": plan["space"], "kind": plan["kind"], "slug": plan["slug"],
                                          "text": text, "owners": guard.accessory_owners(plan["profile"])}),
             plan["profile"], f"new deck {plan['title']}", new_deck_refused(plan))
    return created_answer(plan, deck_id, table, text)


def stale_view():
    """GET /api/tables/stale: the Decks page's "Tables out of date" list.

        {"stale": [_stale_list entries, with may_update], "blocked": [deck blockers],
         "held": [space blockers], "warnings"}

    stale: the decks whose owned-vs-needed tables are out of date and can be updated, each with
    may_update (whether this visitor may: Update all posts only those). blocked: the decks
    deck tables can't update, and why (pool.table_blockers' "decks": {"id", "title", "space",
    "reason", "version", "cards", "why"}); a deck in it is left out of stale. held: the spaces
    whose pools are incomplete, so receipts and order changes can't refresh their tables
    (table_blockers' "spaces": {"space", "warnings", "unknown": [{"name", "where"}], "why"}).
    Each list holds only what's of a space whose inventory this visitor may see (R6d, as
    _stale_list), and stale and blocked only the decks it may see (guard.sees_deck, E10-S30),
    with no paths in its words. A held space's warnings and unknown cards ("where") name no
    deck it may not see, and none of home's order or product files unless it sees home's
    records (E10-S29: _seen_warning, library.visible_unresolved)."""
    _require_cards()
    warnings = []
    p = _load_pool(warnings)
    if not guard.sees_inventory(spaces.HOME):     # home's pool warnings are its inventory's (R6d)
        warnings = []
    found = pool.table_blockers(p)
    sees = guard.deck_reader()
    blocked = [_scrubbed(entry, ("title", "why")) for entry in found["decks"]
               if sees(entry["id"]) and guard.sees_inventory(entry["space"])]
    held = [_scrubbed(entry, ("why",)) for entry in found["spaces"] if guard.sees_inventory(entry["space"])]
    records = guard.sees_home_records()
    for entry in held:
        # No deck or card of a deck this viewer can't see, and none of home's order or product
        # files unless it sees home's records (E10-S29): its pool's warnings as library's
        # visible_warnings would leave them, and each unknown name only with the places it may
        # be told (visible_place), the name itself only when one is left.
        entry["warnings"] = _scrub([text for text in entry["warnings"]
                                    if _seen_warning(text, entry["space"], sees, records)])
        unknown = visible_unresolved({u["name"]: u["where"] for u in entry["unknown"]}, sees, records)
        entry["unknown"] = [{"name": u["name"], "where": _scrub(unknown[u["name"]])}
                            for u in entry["unknown"] if u["name"] in unknown]
    stuck = {entry["id"] for entry in found["decks"]}
    return {"stale": [entry for entry in _stale_list(p) if entry["id"] not in stuck], "blocked": blocked,
            "held": held, "warnings": _unique(_scrub(warnings))}


def _seen_warning(text, space, sees, records):
    """Whether a held space's pool warning may be shown (as library.visible_warnings decides for
    a pool): one that starts with a deck id (a deck's own problem) only when this viewer may see
    that deck (sees); any other of home's (its orders, products and status lines) only when it
    sees home's records."""
    first = str(text).split(" ", 1)[0].rstrip(":")
    try:
        spaces.split_deck_id(first)
    except ValueError:
        return space != spaces.HOME or records
    return sees(first)


def _scrubbed(entry, keys):
    """A copy of a blocker entry with no paths in its words (keys)."""
    out = dict(entry)
    for key in keys:
        out[key] = _strip_paths(out[key])
    return out


def update_tables(body):
    """POST /api/tables/update {"profile", "decks": [{"id", "sha256"}]}: "Update their tables".

    Rewrites only the owned-vs-needed tables (and the rate line above each)
    of those decks, from each target list and the pool as it is now,
    keeping hand notes; no "Decklist changed" line. Every deck's sha256 is
    checked first: if any changed, ApiError 409 with conflict {"reason":
    "changed", "decks": [...]} and nothing is saved. The tables are saved in
    one change (deck.update_tables, all or nothing: "update the owned-vs-
    needed tables of <titles>"). Returns updated [{"id", "title", "sha256",
    "repriced", "note"}], unchanged [id], skipped_not_allowed [{"id",
    "title"}] (decks the profile may not change, lib/api/guard.py: left as
    they are; 403 when that's every one of them), stale_tables (what's still
    out of date) and warnings."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "decks"))
    items = data["decks"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_TABLE_DECKS:
        raise ApiError(400, f"decks must be a list of 1-{MAX_TABLE_DECKS} {{\"id\", \"sha256\"}} objects")
    wanted = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "sha256"}:
            raise ApiError(400, 'Each deck must be {"id": ..., "sha256": ...}')
        kind, slug, path = _deck_file(item["id"])
        if any(w[0] == item["id"] for w in wanted):
            raise ApiError(400, f"{item['id']} is listed twice")
        wanted.append((item["id"], kind, slug, path, _sha(item["sha256"])))
    _require_cards()
    warnings = []
    loaded, conflicts = [], []
    for deck_id, kind, slug, path, sha in wanted:
        try:
            stored = _stored(deck_id, viewer=profile)
        except ApiError as e:
            if e.status != 409:         # 404: a deck with no revision at all (as save_deck's)
                raise
            conflicts.append((deck_id, getattr(e, "title", slug), e))
            continue
        loaded.append((deck_id, stored, _parse_file(stored.data, kind, slug, path, deck_id), sha))
    # Only the decks this profile may change (guard.py); the rest are left as they are, and
    # whether they changed (and who changed them) isn't checked or told.
    denied = [(deck_id, deck) for deck_id, _, deck, _ in loaded if not guard.allowed(profile, "tables.update", deck)]
    if denied and len(denied) == len(loaded) and not conflicts:
        guard.require(profile, "tables.update", denied[0][1])
    denied_ids = {deck_id for deck_id, _ in denied}
    loaded = [item for item in loaded if item[0] not in denied_ids]
    for deck_id, stored, deck, sha in loaded:
        if stored.sha256 != sha:
            conflicts.append((deck_id, deck.title, _conflict(deck_id, deck.title, viewer=profile)))
    if conflicts:
        order = [w[0] for w in wanted]
        raise _tables_conflict(sorted(conflicts, key=lambda c: order.index(c[0])))
    loaded = [(deck_id, stored, deck) for deck_id, stored, deck, _ in loaded]
    seen = []
    p = _load_pool(seen)
    if guard.sees_inventory(spaces.HOME):      # home's pool warnings name its orders and products (R6d)
        warnings.extend(seen)
    if p is None:
        raise ApiError(500, "The card pool can't be read, so the tables can't be worked out (see the warnings "
                            "on the deck pages).")
    planned = []
    for deck_id, stored, deck in loaded:
        table = _rewrite_table(deck, p)
        try:
            out = decks.render_deck_file(deck)
        except (decks.DeckFileError, ValueError) as e:
            raise ApiError(500, f"{deck_id} can't be saved: {_public(e)}") from None
        planned.append((deck_id, stored, out, deck, table))
    written = [(deck_id, stored, out, deck, table) for deck_id, stored, out, deck, table in planned
               if out != stored.text]
    if written:
        titles = {deck_id: deck.title for deck_id, _, _, deck, _ in written}
        op = inventory.Op("deck.update_tables", {"items": [{"id": deck_id, "text": out, "base_sha256": stored.sha256}
                                                           for deck_id, stored, out, _, _ in written]})
        apply_op(op, profile, f"update the owned-vs-needed tables of {_and(titles.values())}",
                 lambda e: _tables_refused(e, titles, profile))
    updated = [{"id": deck_id, "title": deck.title, "sha256": decks.text_sha(out), "repriced": table["repriced"],
                "note": table["note"]} for deck_id, _, out, deck, table in written]
    written_ids = {w[0] for w in written}
    return {"updated": updated, "unchanged": [deck_id for deck_id, *_ in planned if deck_id not in written_ids],
            "skipped_not_allowed": [{"id": deck_id, "title": deck.title} for deck_id, deck in denied],
            "stale_tables": _stale_after(set(), warnings), "warnings": _unique(_scrub(warnings))}


def _and(names):
    """"A", "A and B", "A, B and C" ("" for none)."""
    names = list(names)
    if not names:
        return ""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _tables_refused(e, titles, profile):
    """apply_op's refused for deck.update_tables: the decks it names as changed since (or gone)
    get _tables_conflict's 409."""
    if not (isinstance(e, ops_decks.DeckRefused) and e.reason == "changed"):
        return None
    try:            # the inventory as it is now: the request's snapshot still has every deck
        now = inventory.backend().load()
    except Exception:          # noqa: BLE001 - every one is then "changed"
        now = None
    conflicts = []
    for deck_id in e.ids:
        title = titles.get(deck_id, deck_id)
        error = _conflict(deck_id, title, viewer=profile, deleted=now is not None and now.deck(deck_id) is None)
        conflicts.append((deck_id, title, _gone(deck_id, title) if error.status == 404 else error))
    return _tables_conflict(conflicts)


def _gone(deck_id, title):
    """The 409 for a deck that's gone with no revision to say who deleted it or when (the files
    backend keeps none, where _conflict answers 404): _conflict's keys, by and when unknown."""
    error = ApiError(409, f"{title} was deleted after you opened it. Your changes weren't saved.",
                     conflict={"reason": "deleted", "by": None, "deck_lab": False, "when": None,
                               "subject": None})
    error.title = title
    return error


def _tables_conflict(conflicts):
    """The 409 for "Update their tables" when decks changed: [(deck id, title, the deck's _conflict error)]."""
    first = conflicts[0][2].message.removesuffix(" Your changes weren't saved.").rstrip(".")
    more = f" ({len(conflicts) - 1} more changed too)" if len(conflicts) > 1 else ""
    return ApiError(409, f"{first}{more}. No tables were updated: look at the list again.",
                    conflict={"reason": "changed", "decks": [dict(error.extra.get("conflict") or {}, id=deck_id,
                                                                  title=title)
                                                             for deck_id, title, error in conflicts]})
