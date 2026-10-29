"""Editor drafts kept for later (E2-S16, migration 0018): one profile's unsaved edit of one list
of one deck, kept on the PC so the same profile can pick it up on another device.

Each (profile, deck, version) has one row with a revision that only grows: saving a draft
needs the revision last read (0 for none), and discarding one leaves a tombstone (content
None) with the next revision, so an older device can never silently overwrite a draft saved
or discarded since. The content is the editor's own draft object (editor-drafts.js's
saveDraft shape), checked here only for its envelope and size: the editor rebases it onto the
deck as it is when it's resumed, and a deck save checks every line again.

Drafts are scratch work, like the browser's drafts: no change set, no audit rows (their lists
never reach Activity), not exported. The stores grant no request access: lib/api/deck_drafts.py
answers only the draft's own profile and rechecks the deck's privacy on every read and write.

A database without migration 0018 raises MissingSchema (an Unavailable), which the API turns
into "not available here" so the editor behaves exactly as before: drafts on this device only.
"""
import copy
import json
from datetime import datetime, timezone

from . import Conflict, Invalid, Unavailable, rules
from .rules import CONTROL

VERSIONS = ("target", "owned")
MAX_CONTENT = 480 * 1024            # bytes of a draft's JSON (two full lists, their bases and the write-up)
MAX_DEVICE = 60                     # characters naming the device it was saved on
MAX_DECK_ID = 200                   # api/library.check_deck_id's
MAX_REVISION = 2 ** 53 - 1          # the page reads it as a JavaScript number
REQUIRED = ("lists", "fields", "base")      # editor-drafts.js readDraft's test of a draft

CHANGED = ("This draft was saved or discarded on another device since this one read it. "
           "Nothing was changed: look at it again first.")
MIGRATE = "Drafts kept for later need the database migration: python -m decklab.db migrate"
INDEPENDENT = "A draft kept for later is never part of a change set."
BAD_CONTENT = "The draft must be the editor's draft: an object with lists, fields and base"


class MissingSchema(Unavailable):
    """Migration 0018 isn't applied: there's no draft table to read or write."""


def missing_schema(error):
    return isinstance(error, MissingSchema)


def key(profile_id, deck_id, version):
    """(profile id, deck id, version) checked; Invalid otherwise."""
    pid = rules.profile_id(profile_id)
    if not isinstance(deck_id, str) or not 3 <= len(deck_id) <= MAX_DECK_ID or CONTROL.search(deck_id) \
            or deck_id != deck_id.strip() or " " in deck_id:
        raise Invalid("Bad deck ID")
    if version not in VERSIONS:
        raise Invalid("version must be target or owned")
    return pid, deck_id, version


def expectation(value):
    """The revision the device last read: a whole number from 0 (none yet)."""
    if type(value) is not int or not 0 <= value <= MAX_REVISION:
        raise Invalid("expect must be the draft's revision, a whole number of 0 or more")
    return value


def device(value):
    """A short, optional name for the device ("iPad", "PC"), shown with the draft."""
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MAX_DEVICE or CONTROL.search(value):
        raise Invalid(f"device must be text of at most {MAX_DEVICE} characters, with no control characters")
    return value.strip()


def content(value):
    """The draft as saved (a JSON round trip of it), or None for a discard; Invalid when it
    isn't the editor's draft object or is too big."""
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("v") != 1 \
            or any(not isinstance(value.get(name), dict) for name in REQUIRED):
        raise Invalid(BAD_CONTENT)
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise Invalid(BAD_CONTENT) from None
    if len(text.encode("utf-8")) > MAX_CONTENT:
        raise Invalid(f"The draft is limited to {MAX_CONTENT // 1024} KiB")
    return json.loads(text)


def stamp(when=None):
    """saved_at as both stores give it: UTC, ISO 8601 to the second."""
    when = when or datetime.now(timezone.utc)
    return when.astimezone(timezone.utc).isoformat(timespec="seconds")


def view(row):
    """{"revision": n, "draft": {saved_at, device, content} or None}: revision 0 and no draft
    when there's no row; a tombstone keeps its revision with no draft."""
    if row is None:
        return {"revision": 0, "draft": None}
    if row["content"] is None:
        return {"revision": row["revision"], "draft": None}
    return {"revision": row["revision"],
            "draft": {"saved_at": row["saved_at"], "device": row["device"], "content": copy.deepcopy(row["content"])}}


def transition(row, expected, new_content, new_device, at):
    """The row after a put, or None when nothing changes (discarding what's already gone).
    Conflict when the revision isn't the one expected."""
    revision = row["revision"] if row else 0
    if revision != expected:
        raise Conflict(CHANGED)
    if new_content is None and (row is None or row["content"] is None):
        return None
    if revision >= MAX_REVISION:
        raise Invalid("This draft can't be saved again")
    return {"revision": revision + 1, "saved_at": at, "device": new_device if new_content is not None else "",
            "content": new_content}
