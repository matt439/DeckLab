"""The Tokens page's API: the physical token and reminder cards in the
inventory (magic/tokens.csv), which deck each one serves, and the tokens the
decks need that nobody owns (lib/tokens reads and matches all of it; this
module and receipts are the only writers). Imported when first needed, by
feature_routes.dispatch.

    GET  /api/tokens[?space=]  tokens_view(): rows, uses, missing, incoming, problems (home by default)
    POST /api/tokens/save     save_token(body): add, edit or remove one row

Each takes a space (lib/spaces.py; "space" in the query or body, home by
default): a person's tokens are magic/people/<id>/tokens.csv, with no token
orders, and their own decks' needs. Writes need tokens.edit on the space
(guard.py): only its own profiles, home's Matt and User1 (E10-S29, E10-S43).

Every write is one inventory operation (lib/tokens/ops.py: tokens.add,
tokens.edit, tokens.remove) through inventory.apply, whichever backend holds
the inventory. tokens.csv has no ids the page knows, so a row is named by
its ten values as the page loaded them ("base"); the first equal row is the
one changed. The space's tokens.csv must still have the sha256 the page
loaded (the sha of the file as rendered, tokens.read()): it is checked once
before the write and again by the operation, under the inventory's lock
(409 with "conflict" and "latest", the view as it is now, otherwise; with a
base, conflict also has base_state and current, and reason is "deleted"
only when no row names that card any more; see _conflict_error). Who made
the change that got in the way comes from the audit trail for the database
(a test's files backend keeps no history, so it names nobody). Quantities are compared as
numbers, as the view sends them. The rows are kept sorted by
rules.token_sort_key.

Each write is one change set in the audit trail ("<add|edit|remove> token
<Front> // <Back>", by the profile, with the reason); nothing is
committed to git (the files backend, the tests', writes plain files). A save
takes saving._save_lock before apply, so it queues behind another page's save
in the same server.

The page never merges rows by itself: an add or edit that would leave two
rows naming the same card (rules.token_identity) answers 409 with
"same_row", unless "separate" asks to keep them apart, which is allowed only
when either row isn't fully known (rules.token_known), as receipts keep
unverified variants apart.

Side effects, all intended: a save changes the inventory's revision, so a
receipt previewed before it must be previewed again. The page never edits
order payloads or their checks, and never receives orders (the Receipts
page does).
"""
import contextlib
import re
import traceback
from datetime import timezone

from decklab.lib import cards, decks, inventory, spaces, tokens
from decklab.lib.inventory import Op
from decklab.lib.inventory import files as inventory_files
from decklab.lib.inventory import rules
from decklab.lib.tokens import ops as token_ops

from . import common, guard, saving
from .collection import space_param as _space
from .commits import _when
from .card_lookup import image_url
from .common import ApiError, _keys, _parse_body, _public, _scrub, _unique
from .settings import _web_actor, _writer

MAX_SAVE_BODY = 16 * 1024           # bytes: a row and its base copy
MAX_REASON = 200
BLANK_BACK = "Leave the back blank only for a single-sided card; tick 'Single-sided (checked)' to note it"
VIEW_FAILED = "Saved, but the tokens list couldn't be shown again; reload the page"
NOT_LISTED = "That token card isn't in the tokens list any more; reload the page to see the list as it is"
NOT_AS_SENT = "That token card isn't in the tokens list as the page sent it; reload the page and try again"
RESORTED = token_ops.RESORTED
_TITLE = "The tokens list"
_SINGLE = re.compile(r"single-sided verified", re.IGNORECASE)


def _whose(space):
    """How a change's message names a person's tokens: " (User2's tokens)"; "" at home."""
    return "" if space == spaces.HOME else f" ({spaces.get(space).name}'s tokens)"


# ---- reading

_PT_RE = re.compile(r"^\s*([0-9*+X-]+)\s*/\s*([0-9*+X-]+)\s*$")
_examples_cache = {"data": None, "faces": {}}


def _example_entries():
    """{cards.fold(face name): [token entries with a picture whose front face is that name]}, from the
    card index (built once per index loaded): single-faced entries first, then double-faced ones whose
    front it is, since a double-faced token's picture is its front."""
    data = cards._get().data
    if _examples_cache["data"] is not data:
        faces = {}
        entries = sorted(data.get("tokens", {}).values(), key=lambda e: len(e.get("face_names") or []) > 1)
        for entry in entries:
            if not entry.get("image"):
                continue
            names = entry.get("face_names") or [entry["name"]]
            faces.setdefault(cards.fold(names[0]), []).append(entry)
        _examples_cache.update(data=data, faces=faces)
    return _examples_cache["faces"]


def _example_image(name, details):
    """An example picture of a token face named name ("/img/..." small), for a row that records no
    printing: never the row's printing, only how such a token can look. The one whose power and
    toughness match the details' ("3/3; green") when there is one, else the first. None when the
    card index has no token face of that name with a picture."""
    found = _example_entries().get(cards.fold(name or "")) if name else None
    if not found:
        return None
    first = (details or "").split(";")[0]
    pt = _PT_RE.match(first)
    if pt:
        same = [e for e in found if (e.get("power"), e.get("toughness")) == (pt.group(1), pt.group(2))]
        found = same or found
    set_code, number = found[0]["image"]
    return image_url(set_code, number, "small")


def _face(row, side, index_ready):
    """{side, name, details, known, image, example} for one face of a row. known: the
    name is a Scryfall token, emblem or reminder face (None while the card
    index isn't ready). image: the row's own printing when it records one. example: when it
    doesn't, an example picture of a token with that face name (_example_image), which the page
    labels "example art, printing not recorded": it never says which printing the card is."""
    name = row[side]
    known = image = example = None
    if index_ready:
        known = cards.token_face(name) is not None
        number = row[f"{side}_collector_number"]
        # A double-faced printing has one picture, the front's.
        if row["set"] and number and (side == "front" or number != row["front_collector_number"]):
            found = cards.token_faces_at(row["set"], number)
            if found is not None:
                image = image_url(row["set"], number, "small")
        if image is None and not (row["set"] and number) and known:
            try:
                example = _example_image(name, row[f"{side}_details"])
            except (KeyError, TypeError, ValueError):       # an index without token pictures
                example = None
    return {"side": side, "name": name, "details": row[f"{side}_details"], "known": known, "image": image,
            "example": example}


def _row_json(i, row, uses, shared, index_ready):
    return {"key": f"r{i}", "index": i, **row, "quantity": int(row["quantity"]),
            "single_sided": not row["back"] and bool(_SINGLE.search(row["notes"])),
            "unconfirmed": rules.token_uncertain(row),
            "faces": [_face(row, side, index_ready) for side in ("front", "back") if side == "front" or row[side]],
            "uses": uses.get(i, []), "shared": shared.get(i, [])}


def _incoming_json(found):
    return [{"order": item["order"], "component": item["component"], "path": item["path"],
             "cards": sum(int(r["quantity"]) for r in item["rows"]),
             "rows": [{"front": r["front"], "back": r["back"], "quantity": int(r["quantity"]),
                       "front_details": r["front_details"], "back_details": r["back_details"]}
                      for r in item["rows"]]}
            for item in found]


def _deck_side(what, work, empty, info):
    """work() for the decks' side of the view (row uses, missing tokens), or
    empty with a line in info when the card index isn't ready or the work
    fails; the page still lists the rows."""
    try:
        return work()
    except RuntimeError:
        info.append("Which tokens the decks need isn't shown: card data is still loading")
    except Exception:
        common._log(f"Couldn't work out the decks' {what}:\n{traceback.format_exc()}")
        info.append(f"The decks' {what} couldn't be worked out; the server log says why")
    return empty


def tokens_view(space=None):
    """GET /api/tokens[?space=<id>]: one space's token cards (home's by
    default; a person's magic/people/<id>/tokens.csv, matched against their
    own decks, with no orders): {space, sha256 (None before the space has
    any), exists, sorted, index_ready, rows: [{key "r<i>", index, the ten
    fields (quantity an int), single_sided, unconfirmed, faces [{side, name,
    details, known, image, example}], uses [{deck, title, token, side, state}],
    shared [{deck, title, link}]: the built decks that use the row, when there are more than its
    cards (tokens.shared_rows; [] otherwise)}],
    cards (physical cards in all), missing (tokens.gaps: the tokens built and
    building decks and intact products need with nothing owned), incoming
    (pending token orders: {order, component, path, cards, rows}),
    face_names (for the sheet's suggestions; [] while the card index isn't
    ready), keywords (those a details part may list, lower case, for the
    sheet's "Read as" line, as parse_details reads them), problems (rows of tokens.csv that can't be read) and info}. One
    inventory snapshot answers it all. 403 for a space whose inventory the visitor may not see
    (guard.require_sees_inventory)."""
    space = _space(space)
    guard.require_sees_inventory(space)
    return _tokens_view(space)


def _tokens_view(space):
    """tokens_view(space) without the inventory check, for a write that has
    passed guard.require (tokens.edit): its 409 "latest" and its answer's
    "data" show the list it writes, as collection_edit's 409 rows do, rather
    than turning a conflict or a saved change into a 403. A writer that
    passed tokens.edit (by its own rights, at home as through the tunnel)
    may see the list it writes."""
    info, warnings = [], []
    try:
        with inventory.pinned() if not inventory.is_pinned() else contextlib.nullcontext():
            inv = tokens.read(space=space)
            # Token orders are home's only (lib/spaces.py).
            found, incoming_problems = (tokens.incoming() if space == spaces.HOME and guard.sees_home_records()
                                        else ([], []))
            index_ready = tokens._ready()
            uses = _deck_side("token uses", lambda: tokens.row_uses(inv, found, warnings, space), {}, info)
            shared = _deck_side("shared token cards",
                                lambda: tokens.shared_rows(inv, uses, tokens.built_ids(space)), {}, info)
            missing = _deck_side("missing tokens", lambda: tokens.gaps(inv, found, warnings, space), [], info)
    except OSError as e:
        raise ApiError(500, f"The tokens list can't be read: {_public(e)}") from None
    except ValueError as e:
        raise ApiError(409, f"The tokens list can't be read: {_public(e)}") from None
    face_names = cards.token_face_names() if index_ready else []
    if not index_ready:
        info.append(tokens.NAMES_UNCHECKED)
    # What this viewer may be told (E10-S29): decks only when it may see them, and home's
    # pending token orders and their problems only when it sees home's records.
    sees, records = guard.deck_reader(), guard.sees_home_records()
    if not records:
        found, incoming_problems = [], []
    uses = {i: _seen_uses(items, sees) for i, items in uses.items()}
    shared = {i: _seen_holders(holders, sees) for i, holders in shared.items()}
    missing = [_seen_gap(gap, sees) for gap in missing]
    warnings = [text for text in warnings if _seen_text(text, sees, records)]
    return {"space": space, "sha256": inv.sha256, "exists": inv.sha256 is not None, "sorted": inv.sorted,
            "index_ready": index_ready,
            "rows": [_row_json(i, row, uses, shared, index_ready) for i, row in enumerate(inv.rows)],
            "cards": sum(int(row["quantity"]) for row in inv.rows),
            "missing": missing, "incoming": _incoming_json(found), "face_names": face_names,
            "keywords": sorted(tokens._keywords()), "problems": _unique(_scrub(inv.problems)),
            "info": _unique(_scrub(incoming_problems + warnings + info))}


def _seen_use(use, sees):
    """A row's use ({deck, title, link, token, side, state}) as the viewer may see it: a deck it
    may not see (guard.sees_deck) has no id or link, and its title is guard.hidden_deck's
    "one of the home decks"."""
    from .inventory_views import named_holder
    if named_holder(use["deck"], sees):
        return use
    return {**use, "deck": None, "title": guard.hidden_deck(use["deck"]), "link": None}


def _seen_holders(holders, sees):
    """A shared row's built holders ({deck, title, link}, tokens.shared_rows), or [] when the
    viewer may not see one of them: the warning would tell how many hidden decks use the row,
    which _seen_uses keeps from being told."""
    from .inventory_views import named_holder
    return holders if all(named_holder(h["deck"], sees) for h in holders) else []


def _seen_uses(items, sees):
    """A row's uses as the viewer may see them (_seen_use), hidden decks' alike uses merged into
    one, so how many hidden decks it serves isn't told either."""
    out, seen = [], set()
    for use in items:
        shown = _seen_use(use, sees)
        if shown["deck"] is None:
            key = (shown["title"], shown["token"], shown["side"], shown["state"])
            if key in seen:
                continue
            seen.add(key)
        out.append(shown)
    return out


def _seen_gap(gap, sees):
    """A missing token's decks as the viewer may see them: hidden ones as one entry per
    space's words, with no id or link, so neither which decks nor how many is told."""
    from .inventory_views import named_holder
    decks_, hidden = [], set()
    for deck in gap["decks"]:
        if named_holder(deck["id"], sees):
            decks_.append(deck)
            continue
        words = guard.hidden_deck(deck["id"])
        if words not in hidden:
            hidden.add(words)
            decks_.append({"id": None, "title": words, "link": None})
    return {**gap, "decks": decks_}


def _seen_text(text, sees, records):
    """Whether a decks-side warning ("casual/x can't be read: ...") may be shown: its first
    word names a deck the viewer may see, or one of home's product files and it sees home's
    records, or no deck or file at all (library.visible_place)."""
    from .library import visible_place
    first = str(text).split(" ", 1)[0].rstrip(":")
    return visible_place(first, sees, records)


# ---- save

def _request_sha(value):
    if value is None or isinstance(value, str) and common._SHA_RE.fullmatch(value):
        return value
    raise ApiError(400, "sha256 must be the 64-character hash /api/tokens gave (null before the list exists)")


def _row_input(value, what="row"):
    """A request's row: an object of tokens.csv's columns (a subset), text
    except quantity, which may be a whole number."""
    if not isinstance(value, dict):
        raise ApiError(400, f"{what} must be an object")
    unknown = sorted(set(value) - set(tokens.FIELDS))
    if unknown:
        raise ApiError(400, f"Unknown {what} key {unknown[0]!r}; a {what} takes: {', '.join(tokens.FIELDS)}")
    for key, item in value.items():
        if key == "quantity":
            if isinstance(item, bool) or not isinstance(item, (int, str)):
                raise ApiError(400, "quantity must be a whole number")
        elif not isinstance(item, str):
            raise ApiError(400, f"{key} must be text")
    return value


def _base_input(value):
    """The row as the page loaded it: all ten columns, as text."""
    _row_input(value, "base")
    missing = [key for key in tokens.FIELDS if key not in value]
    if missing:
        raise ApiError(400, f"base needs every column; it lacks {missing[0]}")
    return {key: str(value[key]) for key in tokens.FIELDS}


def _card(row):
    """The printing a row names, without its details: what a row someone
    else edited still has (a blank printing leaves just the faces)."""
    return tuple(row[k] for k in ("front", "back", "set", "front_collector_number",
                                  "back_collector_number", "finish"))


def _find_base(rows, base):
    """(state, index): where the page's base row is in rows now. state is
    "unchanged" (a row equal to base), "changed" (no equal row, but one
    naming the same card: the same token_identity, else the same faces and
    printing) or "deleted" (index None)."""
    want = token_ops.match_key(base)
    for i, row in enumerate(rows):
        if token_ops.match_key(row) == want:
            return "unchanged", i
    for same in (rules.token_identity, _card):
        identity = same(base)
        at = next((i for i, row in enumerate(rows) if same(row) == identity), None)
        if at is not None:
            return "changed", at
    return "deleted", None


def _audit_conflict(space, deleted):
    """The 409 for a change the database's audit trail records: who last changed the space's
    token cards and when (subject: that change's message)."""
    found = None
    backend = inventory.backend()
    try:
        if hasattr(backend, "last_change"):         # the files backend (tests) keeps no history
            found = backend.last_change("token_card", {"space_id": space})
    except Exception as e:      # the answer is still a 409, just without who
        common._log(f"Can't ask the audit trail who changed the tokens list: {e}")
    conflict = {"reason": "deleted" if deleted else "changed", "by": None, "deck_lab": False, "when": None,
                "subject": None}
    if found:
        moment = found["at"] if found["at"].tzinfo else found["at"].replace(tzinfo=timezone.utc)
        web = found["source"] == "web"
        conflict.update(by=found["name"], deck_lab=web, when=moment.isoformat(), subject=found["message"])
        if deleted:
            detail = f"{found['name']} removed every card {_when(moment)} (\"{found['message']}\")"
        elif web:
            detail = f"{found['name']} saved it in Deck Lab {_when(moment)}"
        else:
            detail = f"{found['name']} changed it {_when(moment)} (\"{found['message']}\")"
    else:
        detail = "it was emptied" if deleted else "someone changed it"
    what = "was deleted" if deleted else "changed"
    error = ApiError(409, f"{_TITLE} {what} after you opened it: {detail}. Your changes weren't saved.",
                     conflict=conflict)
    error.title = _TITLE
    return error


def _changed_error(space, deleted):
    """The 409 for a space's tokens.csv that changed since the page loaded it, saying who
    changed it from the audit trail (the files backend, the tests', keeps no history: who is
    left out)."""
    return _audit_conflict(space, deleted)


def _conflict_error(inv, sha, base=None, space=spaces.HOME):
    """The 409 for a list that changed since the page loaded it (or whose
    base row has gone), with the view as it is now. inv is tokens.read() of
    the inventory that refused the save. With a base, conflict also gets
    base_state ("unchanged", "changed" or "deleted", from _find_base) and
    current ({index, row} of that row now, quantity an int; None when
    deleted), and reason is "deleted" only when the space's tokens or every
    row naming that card have gone. A base missing from a list that still
    has the page's sha is said as such, not as a change to the list."""
    file_deleted = sha is not None and inv.sha256 is None
    error = _changed_error(space, file_deleted)
    if base is not None:
        state, at = _find_base(inv.rows, base)
        conflict = error.extra["conflict"]
        conflict["base_state"] = state
        conflict["current"] = None if at is None else {
            "index": at, "row": {**inv.rows[at], "quantity": int(inv.rows[at]["quantity"])}}
        if state == "deleted":
            conflict["reason"] = "deleted"
        if inv.sha256 == sha:
            message = (NOT_LISTED if state == "deleted" else NOT_AS_SENT)
            error = ApiError(409, message, **error.extra)
    error.extra["latest"] = _tokens_view(space)
    return error


def save_token(body):
    """POST /api/tokens/save {"profile", "space"? (home by default: whose
    token cards; a person's are magic/people/<id>/tokens.csv), "action": "add" | "edit" | "remove",
    "sha256", "base"? (edit, remove: the row's ten values as the page loaded
    them), "row"? (add, edit: the columns; quantity a number or text; an
    edit keeps the columns left out), "separate"? (add, edit: keep it apart
    from a row naming the same card), "reason"? (remove: up to 200
    characters, for the audit trail)}.

    Names are checked against Scryfall's token, emblem and reminder faces
    when the card index is ready (and fixed to their exact spelling).
    Returns {saved, index (the row's place in the new list; None after a
    remove), data (tokens_view of that space; None, with a VIEW_FAILED
    warning, when the saved list can't be read back), warnings}. A person's
    tokens are saved as "<action> token <Front> // <Back> (User2's
    tokens)". Needs tokens.edit on the space (guard.py: its own profiles only, home's
    Matt and User1, after the read rule: require_space_write)."""
    data = _parse_body(body, MAX_SAVE_BODY)
    profile = _writer(data)
    space = _space(data.get("space"))
    guard.require_space_write(profile, "tokens.edit", space)
    action = data.get("action")
    if action not in token_ops.KINDS:
        raise ApiError(400, "action must be add, edit or remove")
    required = {"add": ("row",), "edit": ("base", "row"), "remove": ("base",)}[action]
    optional = ("reason",) if action == "remove" else ("separate",)
    _keys(data, ("profile", "action", "sha256", *required), (*optional, "space"))
    sha = _request_sha(data["sha256"])
    base = _base_input(data["base"]) if "base" in data else None
    row_in = _row_input(data["row"]) if "row" in data else None
    separate = data.get("separate", False)
    if not isinstance(separate, bool):
        raise ApiError(400, "separate must be true or false")
    reason = data.get("reason", "")
    if not isinstance(reason, str) or len(reason) > MAX_REASON:
        raise ApiError(400, f"reason must be text of at most {MAX_REASON} characters")
    reason = decks.clean_title(reason)
    warnings = []
    try:
        before = tokens.read(space=space)   # the operation checks again, under the inventory's lock
    except ValueError as e:                 # the inventory can't be read
        raise ApiError(409, f"The tokens list can't be read: {_public(e)}") from None
    if before.sha256 != sha:
        raise _conflict_error(before, sha, base, space)
    old = None
    if base is not None:
        want = token_ops.match_key(base)
        old = next((row for row in before.rows if token_ops.match_key(row) == want), None)
        if old is None:
            raise _conflict_error(before, sha, base, space)
    new = None
    if action != "remove":
        fields = {key: "" for key in tokens.FIELDS}
        fields.update(old or {})
        fields.update({k: str(v) if k == "quantity" else v for k, v in row_in.items()})
        try:
            new = tokens.validate_row(fields)
            new, found = tokens.check_names(new)
        except ValueError as e:
            raise ApiError(400, f"The token card can't be saved: {e}") from None
        warnings += found
        if not new["back"] and not _SINGLE.search(new["notes"]):
            warnings.append(BLANK_BACK)
    params = {"space": space, "sha256": sha}
    if base is not None:
        params["base"] = base
    if new is not None:
        params.update(row=new, separate=separate)
    shown = new or old
    name = shown["front"] + (f" // {shown['back']}" if shown["back"] else "")
    message = f"{action} token {name}{_whose(space)}"
    try:
        # saving._save_lock first (the foundation's lock order), so a save waits for another
        # page's save in this server.
        with saving.inventory_write_lock():
            after, summary = inventory.apply(Op(f"tokens.{action}", params), _web_actor(profile), message,
                                             reason=reason or None)
    except token_ops.Stale as e:
        with inventory.pinned(e.inv):
            raise _conflict_error(tokens.read(space=space), sha, base, space) from None
    except token_ops.SameRow as e:
        raise ApiError(409, str(e), same_row=e.same_row) from None
    except token_ops.Broken as e:
        raise ApiError(500, str(e)) from None
    except inventory.Unavailable:
        raise ApiError(503, common.DATABASE_DOWN, reason="database") from None
    except inventory.Invalid as e:
        raise ApiError(400, str(e)) from None
    except inventory.Conflict as e:
        raise ApiError(409, str(e)) from None
    extra = summary.extra or {}
    now = after.token_set(space)
    written = (inventory_files.rendered_sha256(now) if now.exists else None) != sha
    if extra.get("resorted") and written:
        warnings.append(f"{tokens.label_for(space)} wasn't in the standard order; this save sorted it "
                        "(no other row changed)")
    view = _view_after_save(warnings, space)
    return {"saved": True, "index": extra.get("index"), "data": view,
            "warnings": _unique(_scrub(warnings))}


def _view_after_save(warnings, space=spaces.HOME):
    """_tokens_view(space) for a write that has succeeded, or None with a warning
    when the list can't be shown again (the page reloads it)."""
    try:
        return _tokens_view(space)
    except ApiError as e:
        warnings.append(f"{VIEW_FAILED} ({e.message})")
    except Exception:
        common._log(f"Couldn't show the tokens list after a save:\n{traceback.format_exc()}")
        warnings.append(f"{VIEW_FAILED}; the server log says why")
    return None
