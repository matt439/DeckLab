"""Private Collection storage map and physical section audits."""
from contextlib import nullcontext
import re

from decklab.lib import decks, inventory, state, storage_setting
from decklab.lib.state import collection_audits as audits

from . import collection_storage_sections as sections, guard
from .collection import scan_flag, space_choices, space_param
from .common import ApiError, _keys, _parse_body, state_errors
from .settings import _web_actor, _writer

MAX_BODY = 3 * 1024 * 1024
_ID = re.compile(r"[0-9a-f]{64}")
_EXPECT = re.compile(r"(0|[1-9][0-9]{0,15}):([0-9a-f]{64})")
_STALE = "The expected cards in this section have changed. Open it again to check the latest list."
_UNPLACED = "Use Storage setup or the Card list to assign these cards to a storage section before auditing them."


def _private(space, profile):
    # The storage map and physical audit evidence stay private when a collection is published.
    if not guard.allowed(profile, "collection.edit", space) or not guard.sees_inventory(space, profile):
        raise ApiError(403, guard.COLLECTION_HIDDEN)


def _section_id(ident):
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        raise ApiError(400, "Open a storage section from the map.")
    return ident


def _section(found, ident, *, stale=False):
    for section in found:
        if section["id"] == ident:
            return section
    if stale:
        raise state.Conflict(_STALE)
    raise ApiError(404, "That storage section couldn't be found. Return to the map to see the current sections.")


def _digest(space, section):
    # The token key already identifies both faces. Its UI label is outside the saved receipt.
    rows = [{k: v for k, v in row.items() if k != "manualLabel"} for row in section["rows"]]
    return sections.digest([1, space, section["id"], section["container"], section["place"], rows])


def _public(space, section, saved, *, detail=False):
    answer = {key: value for key, value in section.items() if key != "rows"}
    if saved is None:
        return {**answer, "audit": None}
    audit = {key: saved[key] for key in ("audited_at", "revision", "expected", "observed", "mismatch_rows",
                                        "extra", "missing", "surplus")}
    audit["current"] = saved["digest"] == _digest(space, section)
    if detail:
        audit["differences"] = saved["differences"]
    return {**answer, "audit": audit}


def view(space=None, section=None):
    """GET /api/collection/storage-map, with an optional section ID for the count sheet."""
    space = space_param(space)
    _private(space, guard.viewer())
    ident = _section_id(section) if section is not None else None
    with state_errors(), nullcontext() if inventory.is_pinned() else inventory.pinned():
        saved = state.store().collection_audits(space)
        setup = storage_setting.read(space, seed=False)
        found, excluded = sections.build(space, setup, saved["sections"])
        ready = saved["ready"] and setup["ready"]
        stale = inventory.pinned_stale()
    result = {"space": space, "spaces": space_choices(), "editable": True, "ready": ready and not stale}
    if not ready:
        result["message"] = "Deck Lab's database needs updating before you can record an audit."
    elif stale:
        result["message"] = "Deck Lab is showing its last available collection. Reload before recording an audit."
    if ident is None:
        result["containers"] = [{"name": container["name"], "sections": container["sections"]}
                                for container in setup["storage"]["containers"]]
        result.update(sections=[_public(space, item, saved["sections"].get(item["id"])) for item in found], excluded=excluded)
        if any(row["estimated"] for item in found for row in item["rows"]):
            result["notice"] = "Some counts are estimated where Deck Lab can't identify exactly which copies are in deck boxes."
        return result
    selected = _section(found, ident)
    summary = saved["sections"].get(ident)
    editable = result["ready"] and selected["auditable"]
    version = summary["revision"] if summary else 0
    result.update(section=_public(space, selected, summary, detail=True), rows=selected["rows"],
                  editable=editable, expect=f"{version}:{_digest(space, selected)}" if editable else None)
    # The comparison needs fresh loose counts. Only recording an audit needs its history table.
    if setup["ready"] and not stale and selected["auditable"]:
        result["scan"] = scan_flag()
        result["excluded_names"] = sorted(decks.BASIC_LANDS)
    if not selected["auditable"]:
        result["message"] = selected.get("message", _UNPLACED)
    return result


def _number(value):
    return type(value) is int and 0 <= value <= audits.MAX_COUNT


def _count_result(selected, counts, extra, digest):
    rows = selected["rows"]
    if counts.keys() != {row["key"] for row in rows}:
        raise ApiError(400, "Enter the observed count for every listed row in this section.")
    differences = []
    missing = surplus = 0
    for row in rows:
        expected, observed = row["quantity"], counts[row["key"]]
        if observed != expected:
            difference = {field: row[field] for field in ("name", "set", "collector_number", "finish")}
            if row.get("description"):
                difference["description"] = row["description"]
            differences.append({**difference, "expected": expected, "observed": observed})
            missing += max(0, expected - observed)
            surplus += max(0, observed - expected)
    return {"digest": digest, "expected": selected["quantity"], "observed": sum(counts.values()) + extra,
            "extra": extra, "missing": missing, "surplus": surplus, "mismatch_rows": len(differences),
            "differences": differences}


def record(body):
    """POST /api/collection/storage-map records observations only after checking the current section."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    space = space_param(data.get("space"))
    _private(space, profile)
    _keys(data, ("profile", "section", "expect", "counts", "extra"), ("space",))
    ident = _section_id(data["section"])
    expect = _EXPECT.fullmatch(data["expect"]) if isinstance(data["expect"], str) else None
    if not expect:
        raise ApiError(400, "Open the section again before recording its count.")
    counts, extra = data["counts"], data["extra"]
    if not isinstance(counts, dict) or not _number(extra) or not all(_number(count) for count in counts.values()):
        raise ApiError(400, "Enter observed counts as whole numbers of zero or more.")

    selected = None

    def review(snapshot, setup):
        nonlocal selected
        if not setup["ready"]:
            raise audits.MissingSchema(audits.MIGRATE)
        with inventory.pinned(snapshot):
            found, _ = sections.build(space, setup, {ident} if int(expect[1]) > 0 else ())
        selected = _section(found, ident, stale=True)
        current = _digest(space, selected)
        if not selected["auditable"] or current != expect[2]:
            raise state.Conflict(_STALE)
        return _count_result(selected, counts, extra, current)

    with state_errors():
        try:
            saved = state.store().collection_audit_record(space, ident, int(expect[1]), review, _web_actor(profile),
                                                          "Record a collection storage audit")
        except audits.MissingSchema:
            raise ApiError(409, audits.MIGRATE, reason="migration") from None
    return {"section": _public(space, selected, saved, detail=True)}
