"""The decks Deck Lab can save, for the editor: which deck ids can be saved
and reading them from the inventory's snapshot (decklab/lib/inventory: the
deck parts), the 409 answer for a deck that changed (when and by whom, from
its saved revisions), rewriting a deck's owned-vs-needed table, and other
decks' out-of-date tables.

Nothing here commits anything: the module keeps its older name. Decks are
saved by the inventory's deck operations (inventory/ops_decks.py, from
api/saving.py and api/precons.py), in the database.
"""
import contextlib
from datetime import datetime, timezone
from pathlib import Path

from decklab.lib import cards, config, decks, inventory, pool, spaces

from . import common, guard
from .carddata import _INDEX_ERRORS
from .common import ApiError, _jsonable, _public, _strip_paths
from .library import check_deck_id


def _deck_file(deck_id):
    """(kind, slug, path) for a deck Deck Lab can save, at home or in a
    person's space (the id says which); ApiError 400 otherwise, 404 for a
    space config.json doesn't list. path is where the deck's file is in the
    files backend's tree (decks.deck_path), for the readers that still take
    a path."""
    check_deck_id(deck_id)
    try:
        space, kind, slug = decks.split_id(deck_id)
    except ValueError:
        raise ApiError(400, "Only decks of your own (casual/... and commander/...) can be saved: save a product "
                            "deck or pairing as a new deck") from None
    if not decks.valid_slug(slug):
        raise ApiError(400, f"Deck Lab can't save {deck_id}: only decks named with lowercase letters, digits "
                            f"and hyphens can be saved")
    if not spaces.exists(space):
        raise guard.no_deck(deck_id)              # as any missing deck: no word of which spaces exist
    return kind, slug, decks.deck_path(kind, slug, space)


def _parse_file(data, kind, slug, path, deck_id):
    try:
        return decks.parse_deck(data, slug, kind, path)
    except decks.DeckFileError as e:
        raise ApiError(500, f"{deck_id} can't be read: {_public(e)}") from None


def _title_of(data, fallback):
    """The "# Title" on a deck text's first line (bytes), else fallback."""
    first = data.split(b"\n", 1)[0].decode("utf-8-sig", "replace").strip()
    return first[2:].strip() if first.startswith("# ") and first[2:].strip() else fallback


def _source(path):
    path = Path(path)
    return path.relative_to(config.REPO).as_posix() if path.is_relative_to(config.REPO) else path.name


def _stored(deck_id, sha=None, viewer=False):
    """The inventory's Deck deck_id names (model.Deck), as the request's snapshot has it, which
    must still have sha256 sha when one is given: ApiError 409 (_conflict) when it doesn't or
    the deck is gone (404 for one that never existed), 500 when it can't be read. A deck viewer
    may not see (guard.sees_deck: viewer False, this request's) is 404 as one that never existed,
    before anything else is looked up, so a write never says whether it's there (E10-S30)."""
    from .deck_aliases import reject_alias
    guard.require_sees_deck(deck_id, viewer)
    with common.state_errors():
        reject_alias(deck_id, viewer)
        found = inventory.current().deck(deck_id)
    slug = deck_id.rsplit("/", 1)[-1]
    if found is None:
        raise _conflict(deck_id, slug, deleted=True, viewer=viewer)
    if found.error is not None:
        raise ApiError(500, f"{deck_id} can't be read: {_public(found.error)}")
    if sha is not None and found.sha256 != sha:
        raise _conflict(deck_id, _title_of(found.data, slug), viewer=viewer)
    return found


# ---- when and by whom a deck changed (for the 409 answer)

def _when(moment):
    """"at 2:31 pm today", "at 9:05 am yesterday" or "on 28 Sep at 2:31 pm", in the PC's local time."""
    local = moment.astimezone()
    clock = local.strftime("%I:%M %p").lstrip("0").lower()
    days = (datetime.now().astimezone().date() - local.date()).days
    if days == 0:
        return f"at {clock} today"
    if days == 1:
        return f"at {clock} yesterday"
    return f"on {local.day} {local.strftime('%b')} at {clock}"


def _actor_name(actor):
    """How a revision's actor (a profile id, or "claude", "system", ...) is named on the page."""
    from .activity import ACTOR_NAMES
    from .settings import _config_profiles
    try:
        names = {p["id"]: p["name"] for p in _config_profiles()}
    except ApiError:
        names = {}
    return names.get(actor) or ACTOR_NAMES.get(actor) or actor


def _viewer_id(viewer):
    """(the viewer's profile id or None, whether it sees every message: a script naming nobody,
    guard.script()). viewer: a profile dict, None, or False for this request's
    (guard.viewer)."""
    from . import guard
    if viewer is False:
        try:
            viewer = guard.viewer()
        except ApiError:
            return None, False
    vid = viewer["id"] if isinstance(viewer, dict) else None
    return vid, vid is None and guard.script()


def _last_revision(deck_id):
    """inventory.last_revision(deck_id), or None when it can't be asked (logged)."""
    try:
        return inventory.last_revision(deck_id)
    except Exception as e:     # noqa: BLE001 - the answer is still a 409, just without who
        common._log(f"Can't read {deck_id}'s revisions: {type(e).__name__}: {e}")
        return None


def _source_of(rev):
    """The source of the change set that saved rev (audit.change_source: "web" for the pages,
    "cli", ...), or None for an imported revision or when it can't be asked (logged)."""
    if rev is None or rev.change_set_id is None:
        return None
    from decklab.lib.inventory import audit
    try:
        return audit.change_source(rev.change_set_id)
    except Exception as e:     # noqa: BLE001 - the answer is still a 409, just not "in Deck Lab"
        common._log(f"Can't read the source of change {rev.change_set_id}: {type(e).__name__}: {e}")
        return None


def _gone_title(deck_id, rev, fallback):
    """The title a deleted deck had (rev: its deletion): its last saved text's, else fallback."""
    if rev is None or rev.revision < 2:
        return fallback
    try:
        before = inventory.deck_revision(deck_id, rev.revision - 1)
    except Exception:          # noqa: BLE001 - the slug names it then
        before = None
    if before is None or not before.text:
        return fallback
    return _title_of(before.text.encode("utf-8"), fallback)


def _conflict(deck_id, title, deleted=False, viewer=False):
    """ApiError 409 for a deck that changed (or was deleted) since the page read it, naming who
    and when from its newest saved revision (inventory.last_revision): conflict {"reason":
    "changed" | "deleted", "by" (the profile's name, or Claude, System), "deck_lab" (saved
    on Deck Lab's pages, audit.change_source "web"; False for a command-line change or a
    revision imported from git), "when", "subject" (the first line of the change's message; None
    when the revision changed the deck's sleeves or deck box and viewer isn't who changed them,
    DeckRevision.message_for)}. Alias writes are refused before this deletion check. A
    deleted deck is named by its last text's title. A deck that's gone with no revision is
    ApiError 404: there was never such a deck (the files backend keeps no revisions, so there
    every deck that's gone is 404, and
    a changed one has no by or when). viewer: the profile the answer is for (False: this
    request's). A deck viewer may not see is the 404 too, whatever its revisions (E10-S30)."""
    if not guard.sees_deck(deck_id, viewer):
        return guard.no_deck(deck_id)
    rev = _last_revision(deck_id)
    if deleted and rev is None:
        return guard.no_deck(deck_id)
    if deleted:
        title = _gone_title(deck_id, rev, title)
    conflict = {"reason": "deleted" if deleted else "changed", "by": None, "deck_lab": False, "when": None,
                "subject": None}
    if rev is not None:
        vid, everything = _viewer_id(viewer)
        message = rev.message_for(vid, everything)
        subject = message.strip().splitlines()[0].strip() if message and message.strip() else None
        moment = rev.at if rev.at.tzinfo else rev.at.replace(tzinfo=timezone.utc)
        by = _actor_name(rev.actor)
        conflict.update(by=by, deck_lab=_source_of(rev) == "web", when=moment.isoformat(), subject=subject)
        quoted = f" (\"{subject}\")" if subject and not conflict["deck_lab"] else ""
        if deleted:
            detail = f"{by} deleted it {_when(moment)}{quoted}"
        elif conflict["deck_lab"]:
            detail = f"{by} saved it in Deck Lab {_when(moment)}"
        else:
            detail = f"{by} changed it {_when(moment)}{quoted}"
    else:
        detail = "it was saved again since"
    what = "was deleted" if deleted else "changed"
    error = ApiError(409, f"{title} {what} after you opened it: {detail}. Your changes weren't saved.",
                     conflict=conflict)
    error.title = title             # for "Update their tables", which lists each deck by title
    return error


# ---- the table, and other decks' tables

def _rewrite_table(deck, p):
    """Rewrite a deck file's owned-vs-needed table (in the model) from its
    target list with the pool, prices and rate as they are now, keeping hand
    notes. When the paragraph above the table words the rate some other way
    it isn't repriced (decks.set_table keeps the price cells that still apply
    and blanks the rest), and neither is it without a rate. Returns
    {"rewritten", "repriced", "note": plain words or None}."""
    if deck.rows is None:
        return {"rewritten": False, "repriced": False,
                "note": "This deck has no owned-vs-needed table, so none was written."}
    if p is None:
        return {"rewritten": False, "repriced": False,
                "note": "The owned-vs-needed table wasn't updated: the card pool can't be read (see the warnings)."}
    other = "prices_other" in deck.spans
    found = decks.other_rate(deck) if other else None       # read before the table changes
    try:
        p = pool.for_space(deck.space, p)       # a deck is counted against its own space's pool
    except (ValueError, OSError, spaces.SpaceNotFound) as e:
        return {"rewritten": False, "repriced": False,
                "note": f"The owned-vs-needed table wasn't updated: the card pool can't be read ({_public(e)})."}
    result = pool.compare(deck.target, p, pool.self_ids(deck.deck_id), prices=not other)
    rows, total, stamp = pool.table_rows(result)
    decks.set_table(deck, rows, total, stamp)
    note = None
    if other:
        wording = decks.PRICE_STAMP
        try:                            # the wording with today's figures, as an example
            rate, rate_date = cards.usd_to_aud()
            wording = decks.PriceStamp(rate, rate_date, cards.price_date() or rate_date).text()
        except (TypeError, *_INDEX_ERRORS):
            pass
        kept = "Prices that still apply were kept and the rest left blank."
        if found and found["where"] == "alone":
            note = (f"The table's prices weren't updated: the paragraph above it that starts \"{found['paragraph']}\" "
                    f"gives the exchange rate in its own words (\"{found['found']}\"), so new prices would contradict "
                    f"it. {kept} To let Deck Lab reprice the table, reword that rate exactly as \"{wording}\".")
        elif found and found["where"] == "beside_stamp":
            note = (f"The table's prices weren't updated: the paragraph above it that starts \"{found['paragraph']}\" "
                    f"has Deck Lab's rate (\"{found['stamp']}\") but gives another one too (\"{found['found']}\"), so "
                    f"new prices would contradict it. {kept} To let Deck Lab reprice the table, take the other rate "
                    f"out of that paragraph, leaving only \"{found['stamp']}\".")
        elif found:
            note = (f"The table's prices weren't updated: besides Deck Lab's rate (\"{found['stamp']}\"), the "
                    f"paragraph above the table that starts \"{found['paragraph']}\" gives another one "
                    f"(\"{found['found']}\"), so new prices would contradict it. {kept} To let Deck Lab reprice the "
                    f"table, take that rate out, so the only rate above the table is \"{found['stamp']}\".")
        else:
            note = ("The table's prices weren't updated: the paragraph above it gives the exchange rate in its own "
                    f"words, so new prices would contradict it. {kept} Reword the rate as \"{wording}\" to let Deck "
                    "Lab reprice the table.")
    elif stamp is None:
        note = (f"The table was updated without prices ({_public(result['price_error'] or 'no exchange rate')}); "
                f"prices that still apply were kept and the rest left blank.")
    return {"rewritten": True, "repriced": stamp is not None, "note": note}


def _stale_list(p, exclude=(), only=None):
    """pool.stale_tables(p, exclude, only) as JSON: the decks whose owned-vs-needed tables no
    longer match the pool ([] when the pool can't be read). Only decks this visitor may see
    (guard.sees_deck, E10-S30: an admin's Update all can't post another space's deck, which
    answers as a missing one) of a space whose inventory it may see (guard.sees_inventory, R6d):
    an entry's changes are its owned-vs-needed counts.
    Each entry gains may_update: whether this visitor (guard.viewer()) may update its table
    (tables.update, as update_tables checks it)."""
    stale = _jsonable(pool.stale_tables(p, exclude, only)) if p is not None else []
    sees = guard.deck_reader()
    shown = [entry for entry in stale
             if sees(entry["id"]) and guard.sees_inventory(spaces.split_deck_id(entry["id"])[0])]
    from .inventory_views import table_changes
    for entry in shown:
        entry["changes"] = table_changes(entry.get("changes", []), spaces.split_deck_id(entry["id"])[0])
    _with_may_update(shown)
    return shown


def _with_may_update(entries):
    """Sets each stale entry's may_update (in place): guard.allowed(viewer(), "tables.update",
    the deck as the inventory has it). False for every one when the viewer can't be told (a
    login that isn't set up)."""
    if not entries:
        return
    from decklab.lib.inventory import ops_decks
    try:
        viewer = guard.viewer()
    except ApiError:
        for entry in entries:
            entry["may_update"] = False
        return
    with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
        snapshot = inventory.current()
        for entry in entries:
            deck = ops_decks.parsed_deck(snapshot.decks.get(entry["id"]))
            target = deck if deck is not None else {"space": spaces.split_deck_id(entry["id"])[0], "player": None}
            entry["may_update"] = guard.allowed(viewer, "tables.update", target)


def _table_json(deck, p):
    """The "this table is out of date" note for a deck file: {"has_table",
    "stale" (None when the pool can't be read), "changes" (pool.table_changes),
    "sha256" (what update_tables needs)}. A file Deck Lab can't write (a
    hand-made name like Gruul_Ramp.md) counts as having no table to update."""
    has = deck.rows is not None and deck.has_decklist and decks.valid_slug(deck.slug)
    changes = pool.table_changes(deck, p) if has and p is not None else []
    from .inventory_views import table_changes
    changes = table_changes(changes, deck.space)
    return {"has_table": has, "stale": (bool(changes) if p is not None else None) if has else False,
            "changes": _jsonable(changes), "sha256": deck.sha256}


def _without_own_built_warning(warnings, path):
    """The pool's warnings without its "<this file> is built but has no
    'Built version' field ..." (or a Built version it can't read): the deck
    rules' warning, from the lists and fields being checked or saved, says
    so when it still applies, and says it once."""
    # The pool names the file relative to the repo (or by its absolute path, scrubbed).
    own = tuple(f"{name} is built but has " for name in {_source(path), _strip_paths(str(path))})
    return [w for w in warnings if not w.startswith(own)]
