"""The Collection page's Scan cards (E7-S32): one photo of one card, read on the PC, answered with
the printings it may be. Imported when first needed, by feature_routes.dispatch.

    POST /api/collection/scan   scan_photo(body): read a photo, propose printings; nothing is written

The body is {"profile", "space"?, "photo"}: photo is the picture's base64 bytes, a JPEG or PNG of
at most 4 MiB (the page shrinks a phone's photo on a canvas to at most 2000 pixels on its long side
and sends it as a JPEG, decklab/design/scanning-spike.md). It needs collection.edit on the space
(guard.require_space_write, as the Collection page's other edits and its import: only the space's
own people, home's Matt and User1, a member's only that member, and no admin override), so the
refusal for anyone else is the same 403 a hidden collection gets, before the photo is looked at.

The photo is written to a temporary folder only while OCR reads it (lib/scan.py: Windows' own
engine, else Tesseract), then deleted; it's never kept, and nothing in the inventory, the audit
trail or the raw imports changes. OCR is the engine, scan.ocr; the tests replace it, so they never
run Windows' engine (CI is Linux). One photo is read at a time (429 while another is).

The answer is {ok, space, lines (what was read, at most MAX_LINES lines of MAX_LINE characters),
read ({name, numbers, sets, foil, language}, or null when nothing could be read), proposals
[{name, set, collector_number, set_name, finish, language, how, img_small, owned}] best first
(scan.propose's, with the printing's small picture and the copies of that printing and finish the
space's collection has now), message (one plain sentence) and unread (true when the OCR engine
couldn't read the photo at all: missing on this host, too slow, or not a picture it can open;
the page then offers the card's name typed in instead)}. Unknown condition stays blank: it's the
person holding the card who says. The page adds a chosen proposal to its pending list, and its
Review sends the list to POST /api/collection/import/preview as a collection-columns import, so
the scan is saved as an import is: previewed, then one change with its raw import kept.
"""
import base64
import binascii
import tempfile
import threading
from pathlib import Path

from decklab.lib import accessory_fetch, accessory_upload, cards, scan
from decklab.lib.inventory import rules

from . import guard
from .card_lookup import image_url
from .carddata import _require_cards
from .collection import space_param
from .collection_edit import _read
from .common import ApiError, _keys, _parse_body, _public
from .settings import _writer

MAX_PHOTO = accessory_fetch.MAX_IMAGE           # bytes of a photo (4 MiB), as the Sleeves & boxes page's
MAX_SCAN_BODY = accessory_upload.MAX_BASE64 + 4096
MAX_SIDE = 10000                                # pixels a side: Windows' engine reads no bigger
MAX_LINES = 60                                  # lines read that are answered and proposed from
MAX_LINE = 200                                  # characters of each
OCR = scan.ocr                                  # path -> lines read; the tests replace it
TOO_BIG = "That photo is more than 4 MiB. Take it again, or choose a smaller one (JPEG or PNG)."
NOT_A_PHOTO = "That isn't a JPEG or PNG photo, or it's incomplete. Take it again."

_scan_lock = threading.Lock()


def _photo(value):
    """(bytes, "jpg"|"png") of the request's photo: strict base64 of a complete JPEG or PNG."""
    if not isinstance(value, str) or not value:
        raise ApiError(400, "photo must be the photo's base64 bytes")
    if len(value) > accessory_upload.MAX_BASE64:
        raise ApiError(413, TOO_BIG)
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ApiError(400, "The photo didn't arrive whole (it isn't valid base64). Take it again.") from None
    if len(data) > MAX_PHOTO:
        raise ApiError(413, TOO_BIG)
    ext = accessory_fetch.sniff(data)
    complete = accessory_upload._jpeg(data) if ext == "jpg" else accessory_upload._png(data) if ext == "png" else False
    if not complete:
        raise ApiError(400, NOT_A_PHOTO)
    size = accessory_fetch.dimensions(data, ext)
    if size is None or not all(16 <= side <= MAX_SIDE for side in size):
        raise ApiError(400, f"That photo can't be read: photos of 16 to {MAX_SIDE:,} pixels a side can be.")
    return data, ext


def _read_photo(data, ext):
    """The lines OCR reads in the photo, written to a temporary folder only while it's read."""
    with tempfile.TemporaryDirectory(prefix="decklab-scan-") as folder:
        path = Path(folder) / f"card.{ext}"
        path.write_bytes(data)
        return OCR(path)


def _proposals(found, space):
    """scan.propose's proposals with each printing's small picture and the copies the space has."""
    rows, _ = _read(space)
    owned = {}
    for row in rows:
        key = rules.ident(row)
        owned[key] = owned.get(key, 0) + int(row["quantity"] or 0)
    out = []
    for p in found:
        printing = cards.printing(p["set"], p["collector_number"]) or {}
        out.append({**p, "img_small": image_url(p["set"], p["collector_number"], "small")
                    if printing.get("image_small") else None,
                    "owned": owned.get((p["set"], p["collector_number"], p["finish"]), 0)})
    return out


def scan_photo(body):
    """POST /api/collection/scan: see the module docstring. Nothing is written."""
    data = _parse_body(body, MAX_SCAN_BODY)
    profile = _writer(data)
    space = space_param(data.get("space"))
    guard.require_space_write(profile, "collection.edit", space)
    _keys(data, ("profile", "photo"), ("space",))
    photo, ext = _photo(data["photo"])
    _require_cards()
    if not _scan_lock.acquire(blocking=False):
        raise ApiError(429, "Another photo is being read right now; try again in a moment.")
    try:
        try:
            lines = _read_photo(photo, ext)
        except scan.OcrUnavailable as e:
            return {"ok": True, "space": space, "lines": [], "read": None, "proposals": [],
                    "message": _public(e), "unread": True}
        except OSError as e:
            raise ApiError(500, f"The photo couldn't be read on the PC: {_public(e)}") from None
        lines = [str(line)[:MAX_LINE] for line in list(lines)[:MAX_LINES]]
        try:
            answer = scan.propose(lines)
        except (FileNotFoundError, RuntimeError):
            _require_cards()
            raise ApiError(503, "The card data couldn't be read; try again shortly.") from None
    finally:
        _scan_lock.release()
    read = answer["read"]
    return {"ok": True, "space": space, "lines": lines,
            "read": {k: read[k] for k in ("name", "numbers", "sets", "foil", "language")},
            "proposals": _proposals(answer["proposals"], space), "message": answer["message"], "unread": False}
