"""The Tokens page's Scan token cards (E7-S32): one photo of one token card, read on the PC and
answered with the token, emblem or reminder faces it may be, and the scanned list added as one
change. Imported when first needed, by feature_routes.dispatch.

    POST /api/tokens/scan       scan_token(body): read a photo, propose token faces; nothing is written
    POST /api/tokens/scan/add   add_scanned(body): the reviewed list added as one change

Both need tokens.edit on the body's space (guard.require_space_write, as POST /api/tokens/save:
only the space's own people, home's Matt and User1, a member's only that member, and no admin
override), so anyone else gets the same 403 a hidden token list gets, before the photo or the rows
are looked at.

A scan's body is {"profile", "space"?, "photo"}, the photo as the Collection page's Scan cards
sends it (collection_scan._photo: a JPEG or PNG of at most 4 MiB). It's written to a temporary
folder only while OCR reads it (collection_scan._read_photo, with this module's OCR, which the
tests replace), then deleted; nothing is kept and nothing in the inventory or the audit trail
changes. One photo is read at a time across both scanners (collection_scan._scan_lock: 429 while
another is). The answer is {ok, space, lines, read ({name, numbers, sets, foil, language}, or
null), proposals [{front, faces, set, collector_number, set_name, how, img_small}] best first
(scan.propose_tokens's: a printing only when the bottom line read one, never guessed from the
name, and nothing proposed for the back of the card), message and unread (true when the OCR
engine couldn't read the photo at all)}.

An add's body is {"profile", "space"?, "sha256" (the token list's, as GET /api/tokens gave it;
null before the space has any), "rows": [{front, back?, set?, front_collector_number?,
back_collector_number?, quantity, single_sided?}]} of 1 to token_ops.MAX_BATCH rows. Each row's
names are checked against Scryfall's token faces (and fixed to their exact spelling), its printing
against its faces; its finish and details stay blank (unknown, never guessed), and its notes say it
was added from a scan, and with a blank back either "single-sided verified" (single_sided: the
person holding it ticked it) or "reverse face unconfirmed", so the page's "To check" finds it.
Two rows naming the same card are refused (the page joins them first). The rows are saved as one
tokens.add_many operation, each kept apart from a row already naming that card (never merged),
as one change set ("add N scanned token cards"). A list that changed since the page loaded it
answers 409 with "conflict" and "latest", as POST /api/tokens/save does. The answer is {saved,
added {rows, cards}, data (tokens_view of the space, or None with a warning), warnings}.
"""
from decklab.lib import cards, inventory, scan, tokens
from decklab.lib.inventory import Op, rules
from decklab.lib.tokens import ops as token_ops

from . import collection_scan, common, guard, saving
from . import tokens as api_tokens
from .card_lookup import image_url
from .carddata import _require_cards
from .collection import space_param
from .common import ApiError, _keys, _parse_body, _public, _scrub, _unique
from .settings import _web_actor, _writer

OCR = scan.ocr                                  # path -> lines read; the tests replace it
MAX_ADD_BODY = 64 * 1024                        # bytes: up to MAX_BATCH short rows
ROW_KEYS = ("front", "back", "set", "front_collector_number", "back_collector_number", "quantity", "single_sided")
SCANNED = "Added from a scan"
SINGLE = "single-sided verified"
NO_BACK = "reverse face unconfirmed"
BLANK_BACKS = ("{n} of them have no back recorded: when a card has one, edit its row to add it; when it's "
               "single-sided, tick 'Single-sided (checked)'")


def _proposals(found):
    """scan.propose_tokens's proposals with each printing's small picture (None without a printing)."""
    out = []
    for p in found:
        printing = cards.printing(p["set"], p["collector_number"]) if p["set"] else None
        out.append({**p, "img_small": image_url(p["set"], p["collector_number"], "small")
                    if printing and printing.get("image_small") else None})
    return out


def scan_token(body):
    """POST /api/tokens/scan: see the module docstring. Nothing is written."""
    data = _parse_body(body, collection_scan.MAX_SCAN_BODY)
    profile = _writer(data)
    space = space_param(data.get("space"))
    guard.require_space_write(profile, "tokens.edit", space)
    _keys(data, ("profile", "photo"), ("space",))
    photo, ext = collection_scan._photo(data["photo"])
    _require_cards()
    if not collection_scan._scan_lock.acquire(blocking=False):
        raise ApiError(429, "Another photo is being read right now; try again in a moment.")
    try:
        try:
            lines = collection_scan._read_photo(photo, ext, OCR)
        except scan.OcrUnavailable as e:
            return {"ok": True, "space": space, "lines": [], "read": None, "proposals": [],
                    "message": _public(e).replace("the card's name", "the token's name"), "unread": True}
        except OSError as e:
            raise ApiError(500, f"The photo couldn't be read on the PC: {_public(e)}") from None
        lines = [str(line)[:collection_scan.MAX_LINE] for line in list(lines)[:collection_scan.MAX_LINES]]
        try:
            answer = scan.propose_tokens(lines)
        except (FileNotFoundError, RuntimeError):
            _require_cards()
            raise ApiError(503, "The card data couldn't be read; try again shortly.") from None
    finally:
        collection_scan._scan_lock.release()
    read = answer["read"]
    return {"ok": True, "space": space, "lines": lines,
            "read": {k: read[k] for k in ("name", "numbers", "sets", "foil", "language")},
            "proposals": _proposals(answer["proposals"]), "message": answer["message"], "unread": False}


def _row(value, at):
    """(row, warnings): a scanned row as the token list keeps it: the columns given (names checked and
    fixed), finish and details blank, and notes saying where it came from and what's unconfirmed."""
    if not isinstance(value, dict):
        raise ApiError(400, f"Token card {at} must be an object")
    unknown = sorted(set(value) - set(ROW_KEYS))
    if unknown:
        raise ApiError(400, f"Token card {at} has an unknown key {unknown[0]!r}; a scanned row takes: "
                            f"{', '.join(ROW_KEYS)}")
    if "front" not in value or "quantity" not in value:
        raise ApiError(400, f"Token card {at} needs its front name and quantity")
    for key, item in value.items():
        if key == "quantity":
            if isinstance(item, bool) or not isinstance(item, (int, str)):
                raise ApiError(400, f"Token card {at}: quantity must be a whole number")
        elif key == "single_sided":
            if not isinstance(item, bool):
                raise ApiError(400, f"Token card {at}: single_sided must be true or false")
        elif not isinstance(item, str):
            raise ApiError(400, f"Token card {at}: {key} must be text")
    single = value.get("single_sided", False)
    fields = {key: "" for key in tokens.FIELDS}
    fields.update({key: str(item) for key, item in value.items() if key != "single_sided"})
    if single and fields["back"].strip():
        raise ApiError(400, f"Token card {at} has a back, so it isn't single-sided")
    fields["notes"] = SCANNED if fields["back"].strip() else f"{SCANNED}; {SINGLE if single else NO_BACK}"
    try:
        row = tokens.validate_row(fields)
        return tokens.check_names(row)
    except ValueError as e:
        raise ApiError(400, f"Token card {at} can't be added: {e}") from None


def add_scanned(body):
    """POST /api/tokens/scan/add: see the module docstring."""
    data = _parse_body(body, MAX_ADD_BODY)
    profile = _writer(data)
    space = space_param(data.get("space"))
    guard.require_space_write(profile, "tokens.edit", space)
    _keys(data, ("profile", "sha256", "rows"), ("space",))
    sha = api_tokens._request_sha(data["sha256"])
    given = data["rows"]
    if not isinstance(given, list) or not 1 <= len(given) <= token_ops.MAX_BATCH:
        raise ApiError(400, f"rows must list 1 to {token_ops.MAX_BATCH} token cards")
    rows, warnings, seen = [], [], {}
    for at, value in enumerate(given, 1):
        row, said = _row(value, at)
        identity = rules.token_identity(row)
        if identity in seen:
            raise ApiError(400, f"Token cards {seen[identity]} and {at} are the same card: list it once with "
                                "both quantities")
        seen[identity] = at
        rows.append(row)
        warnings += said
    try:
        before = tokens.read(space=space)   # the operation checks again, under the inventory's lock
    except ValueError as e:
        raise ApiError(409, f"The tokens list can't be read: {_public(e)}") from None
    if before.sha256 != sha:
        raise api_tokens._conflict_error(before, sha, None, space)
    count = sum(int(row["quantity"]) for row in rows)
    message = f"add {count} scanned token card{'' if count == 1 else 's'}{api_tokens._whose(space)}"
    try:
        with saving.inventory_write_lock():
            _, summary = inventory.apply(Op("tokens.add_many", {"space": space, "sha256": sha, "rows": rows}),
                                         _web_actor(profile), message)
    except token_ops.Stale as e:
        with inventory.pinned(e.inv):
            raise api_tokens._conflict_error(tokens.read(space=space), sha, None, space) from None
    except token_ops.Broken as e:
        raise ApiError(500, str(e)) from None
    except inventory.Unavailable:
        raise ApiError(503, common.DATABASE_DOWN, reason="database") from None
    except inventory.Invalid as e:
        raise ApiError(400, str(e)) from None
    except inventory.Conflict as e:
        raise ApiError(409, str(e)) from None
    unpaired = sum(1 for row in rows if not row["back"] and SINGLE not in row["notes"])
    if unpaired:
        warnings.append(BLANK_BACKS.format(n=unpaired))
    if (summary.extra or {}).get("resorted"):
        warnings.append(f"{tokens.title_for(space)} weren't in the standard order; this save sorted them "
                        "(no other row changed)")
    view = api_tokens._view_after_save(warnings, space)
    return {"saved": True, "added": {"rows": len(rows), "cards": summary.counts.get("added_cards", count)},
            "data": view, "warnings": _unique(_scrub(warnings))}
