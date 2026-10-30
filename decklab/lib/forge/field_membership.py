"""Explain the existing field selector without reading results or starting games.

Only the optional trace owns presentation rows; field._field remains the owner of
selection. No raw configuration names, diagnostic notes, product records or global
revisions are returned. A bounded failure has no partial membership totals.
"""
from decklab.lib import decks, spaces

from . import field, lists

MAX_ROWS = 1000
UNAVAILABLE = "Current field membership could not be read completely. Try again later."
TOO_LARGE = "There are too many visible lists to show complete field membership here."
CHOICES_UNREADABLE = ("Home's saved field choices can't be read now, so who's in the field can't be shown "
                      "and field runs wait until they can be read. Try again later.")
VERSIONS = ("target", "owned")


class _TooManyLists(Exception):
    pass


def unavailable(entry, message=UNAVAILABLE, *, choices_unreadable=False):
    """A safe unknown answer, never a successful-looking empty field. choices_unreadable: home's
    saved field choices couldn't be read, so field runs are refused too (E3-S23)."""
    return {"deck": {key: entry[key] for key in ("id", "version", "card_sha")},
            "format": lists.fmt_for(entry["kind"]), "rows": [], "counts": None,
            "complete": False, "error": message, "choices_unreadable": choices_unreadable}


class _Trace:
    def __init__(self, visible, product_notes):
        self.visible = visible
        self.product_notes = product_notes
        self.rows = {}
        self.complete = True

    def unavailable(self):
        self.complete = False

    def candidate(self, summary, selected, reason):
        """Current canonical versions only, after the selector's visibility gates."""
        deck_id = summary["id"]
        if self.visible is not None and not self.visible(deck_id):
            return
        versions = [version for version in summary.get("versions", []) if version in VERSIONS]
        if not versions and summary.get("error"):
            versions = ["target"]  # the unreadable current target, not a made-up saved list
        for version in versions:
            key = (deck_id, version)
            if key not in self.rows and len(self.rows) >= MAX_ROWS:
                raise _TooManyLists
            self.rows[key] = {"id": deck_id, "title": (summary.get("title") or deck_id)[:200],
                              "kind": summary.get("kind") or spaces.split_deck_id(deck_id)[1],
                              "version": version, "card_sha": None, "in_field": False,
                              "opponent": False,
                              "reason": "other_version" if selected and version != selected else reason}

    def product(self, summary, status):
        reason = "product_not_selected"
        if self.product_notes:
            reason = ("product_status_missing" if status is None else
                      "product_status" if status.status not in field.FIELD_STATUSES else
                      "product_not_intact")
        self.candidate(summary, None, reason)

    def pairings(self, fmt, space, public, visible):
        """Pairings are not default members; a configured add can select one later."""
        if fmt != "Constructed" or (space != "home" and not (public and public("home"))):
            return
        # The already-filtered halves bound the quadratic pairing reader before it
        # parses or constructs all recipes. Current deck visibility covers the whole box.
        halves = {row["id"] for row in self.rows.values()
                  if row["reason"] == "beginner_half"}
        if len(halves) < 2:
            return
        if len(halves) * (len(halves) - 1) // 2 > MAX_ROWS - len(self.rows):
            raise _TooManyLists
        for summary in decks.beginner_box_pairings():
            deck_id = summary["id"]
            if visible is not None and not visible(deck_id):
                continue
            owner = summary.get("space") or spaces.space_of(deck_id)
            if (space == "home" and owner != "home") or (
                    space != "home" and owner != space and not (public and public(owner))):
                continue
            if field._fmt_of(summary) == fmt:
                self.candidate(summary, None, "unreadable" if summary.get("error") else "pairing")

    def removed(self, summary, version):
        row = self.rows.get((summary["id"], version))
        if row is not None:
            row["reason"] = "configured_remove"

    def failed(self, summary, version):
        row = self.rows.get((summary["id"], version))
        if row is not None:
            row["reason"] = "unreadable"

    def answer(self, entry, selected):
        for item in selected:
            if self.visible is not None and not self.visible(item["id"]):
                continue
            row = self.rows[(item["id"], item["version"])]
            row.update(in_field=True, card_sha=item["card_sha"],
                       opponent=not field._same_id(item["id"], entry["id"]))
        rows = [row for row in self.rows.values()
                if self.visible is None or self.visible(row["id"])]
        for row in rows:
            if not row["in_field"] and row["reason"] in ("default", "configured_add"):
                row["reason"] = "not_selected"
        rows.sort(key=lambda row: (row["title"].casefold(), row["id"], row["version"]))
        return {"deck": {key: entry[key] for key in ("id", "version", "card_sha")},
                "format": lists.fmt_for(entry["kind"]), "rows": rows,
                "counts": {"included": sum(row["in_field"] for row in rows),
                           "opponents": sum(row["opponent"] for row in rows),
                           "manual_excluded": sum(row["reason"] == "configured_remove" for row in rows)},
                "complete": True, "error": None, "choices_unreadable": False}


def view(entry, *, space="home", public=None, visible=None, product_notes=True):
    """Exact membership and reasons in one snapshot; never read games or engine status."""
    trace, refused = _Trace(visible, product_notes), []
    with lists.one_snapshot():
        try:
            selected, _notes = field._field(lists.fmt_for(entry["kind"]), space=space, public=public,
                                           visible=visible, product_notes=product_notes, trace=trace,
                                           refused=refused)
        except _TooManyLists:
            return unavailable(entry, TOO_LARGE)
        if refused:
            return unavailable(entry, CHOICES_UNREADABLE, choices_unreadable=True)
        if not trace.complete:
            return unavailable(entry)
        return trace.answer(entry, selected)
