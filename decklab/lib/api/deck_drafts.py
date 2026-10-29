"""GET and POST /api/deck/draft: an editor draft kept for later on the PC (E2-S16), so the same
profile can pick it up on another device (state/deck_drafts.py has the store's rules).

A draft is one profile's: only that profile reads or writes it, a named viewer on the page
(the tunnel's login, or at home the profile the chooser picked). Nobody else, an admin or a
script naming nobody included, can read, replace or discard it, and nothing is said of
whether another profile has one. The deck's privacy is checked again on every read and write
(a deck the viewer may not see answers as a missing one, before anything of the draft is
read), and keeping a draft needs deck.edit on it, as saving it would; discarding one needs
only that the deck can be seen, so a draft can always be cleared away. Only a saved deck's
lists have drafts here: a product deck or pairing is read-only, and a new deck keeps its
draft on the device as before.

Without migration 0018 the read answers {"available": false} and the editor behaves as before
(drafts on that device only); a save or discard then answers 503 with the migration's words.
Neither keeps an audit row: a draft isn't a change to Deck Lab's data, and publishing it is
still the editor's ordinary reviewed Save.

Each draft says which saved revision of the deck it started from: on a save, when the draft's
sha256 (the deck text it was opened on) is the deck's text now, the server records that
revision in the draft as deck_revision (a value the page sent is never kept), and a read says
whether the draft still starts from the deck as saved now ("started": {revision, current}).
"""
from decklab.lib import decks, inventory, spaces, state
from decklab.lib.state import deck_drafts as rules

from . import deck_aliases, guard
from .common import ApiError, _keys, _parse_body, state_errors
from .library import _find_summary, check_deck_id
from .settings import _writer

MAX_BODY = rules.MAX_CONTENT + 16 * 1024        # the draft and its envelope
NOBODY = "Choose who you are first: a draft kept for later belongs to one person."
OWN_ONLY = "You can only keep your own drafts."
ONLY_SAVED = "Only a saved deck's changes can be kept for later. A product deck's changes are saved as a new deck."


def _owner():
    """The viewer whose drafts these are; 403 for nobody (a login not set up raises its own)."""
    profile = guard.viewer()
    if profile is None:
        raise ApiError(403, NOBODY)
    return profile


def _version(value):
    if value not in rules.VERSIONS:
        raise ApiError(400, "version must be target or owned")
    return value


def _summary(deck_id, profile):
    """The deck's library summary, seen by profile; the missing deck's 404 when it may not."""
    check_deck_id(deck_id)
    guard.require_sees_deck(deck_id, profile)       # a hidden deck answers as a missing one, first
    summary = _find_summary(deck_id)
    guard.require_sees_deck(summary, profile, deck_id=deck_id)
    if spaces.split_deck_id(summary["id"])[1] not in decks.KINDS:
        raise ApiError(400, ONLY_SAVED)
    return summary


def _deck_now(deck_id):
    """(the deck text's sha256, its revision or None when unknown) in this request's snapshot."""
    with state_errors():
        found = inventory.current().deck(deck_id)
    if found is None or found.text is None:
        return None, None
    return found.sha256, found.revision or None


def _answer(summary, version, saved):
    sha, revision = _deck_now(summary["id"])
    out = {"available": True, "id": summary["id"], "version": version, "deck_revision": revision, **saved}
    if out["draft"] is not None:
        content = out["draft"]["content"]
        started = content.get("deck_revision")
        out["draft"]["started"] = {"revision": started if type(started) is int else None,
                                   "current": sha is not None and content.get("sha256") == sha}
    return out


def _stamped(content, deck_id):
    """The draft to keep, with deck_revision the server's: the revision of the deck text it
    started from when that is the deck's text now, else none."""
    if not isinstance(content, dict):
        return content
    content = {key: value for key, value in content.items() if key != "deck_revision"}
    sha, revision = _deck_now(deck_id)
    if revision is not None and sha is not None and content.get("sha256") == sha:
        content["deck_revision"] = revision
    return content


def draft_view(deck_id=None, version=None):
    """GET /api/deck/draft?id=<deck id>&version=target|owned: the viewer's own draft of that
    list, {available, id, version, revision, deck_revision (the deck's now, None when unknown),
    draft: {saved_at, device, content, started: {revision, current}} or None}. revision is 0
    with no draft yet; send it back as expect. available False (and nothing
    else of a draft) before migration 0018."""
    profile = _owner()
    if deck_id is None:
        raise ApiError(400, "Which deck? Give its id")
    version = _version(version or "target")
    summary = _summary(deck_id, profile)
    with state_errors():
        try:
            saved = state.store().deck_draft(profile["id"], summary["id"], version)
        except rules.MissingSchema:
            return {"available": False, "id": summary["id"], "version": version}
    return _answer(summary, version, saved)


def save_draft(body):
    """POST /api/deck/draft {profile, id, version, expect, draft, device?}: keep the editor's
    draft (an object) for later, or discard it (draft null). expect is the revision last read;
    another answers 409 and changes nothing, so two devices never silently overwrite each
    other's draft. Answers as draft_view does, with the new revision."""
    data = _parse_body(body, MAX_BODY)
    _keys(data, ("profile", "id", "version", "expect", "draft"), ("device",))
    profile = _writer(data)
    viewer = _owner()
    if viewer["id"] != profile["id"]:
        raise ApiError(403, OWN_ONLY)
    version = _version(data["version"])
    keeping = data["draft"] is not None
    if keeping:
        deck_aliases.reject_alias(data["id"], profile)     # an old id after a rename: 409, reload first
    summary = _summary(data["id"], profile)
    if keeping:
        guard.require(profile, "deck.edit", summary)
    content = _stamped(data["draft"], summary["id"])
    with state_errors():
        try:
            saved = state.store().deck_draft_put(profile["id"], summary["id"], version, content,
                                                 data["expect"], device=data.get("device"))
        except rules.MissingSchema:
            raise ApiError(503, rules.MIGRATE, reason="drafts") from None
    return _answer(summary, version, saved)
