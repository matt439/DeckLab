"""Private Collection storage map and physical section audits."""
from contextlib import nullcontext
import re

from decklab.lib import cards, decks, inventory, state, storage_setting
from decklab.lib.state import collection_audits as audits

from . import collection_storage_sections as sections, guard
from .carddata import _require_cards
from .collection import scan_flag, space_choices, space_param
from .collection_edit import FINISHES, _picture_key, _printing_problem
from .common import NUMBER_RE, SET_RE, ApiError, _keys, _parse_body, state_errors
from .settings import _web_actor, _writer

MAX_BODY = 3 * 1024 * 1024
MAX_UNLISTED = 2000
_ID = re.compile(r"[0-9a-f]{64}")
_EXPECT = re.compile(r"(0|[1-9][0-9]{0,15}):([0-9a-f]{64})")
_STALE = "The expected cards in this section have changed. Open it again to check the latest list."
_UNPLACED = "Use Storage setup or the Card list to assign these cards to a storage section before auditing them."
_PRINTING = ("set", "collector_number", "finish")
_CARD_DISPLAY = ("name", *_PRINTING)
_EVIDENCE_FIELDS = (*_CARD_DISPLAY, "key", "estimated", "description", "location", "manualLabel", "token")
_UNLISTED = "Choose an exact paper card printing and finish for each named unlisted card."


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
    # The key already identifies both token faces. Labels and the token fields used by the
    # correction link do not change existing expectation receipts.
    rows = [{k: v for k, v in row.items() if k not in ("manualLabel", "token")} for row in section["rows"]]
    return sections.digest([1, space, section["id"], section["container"], section["place"], rows])


def _historical_differences(differences, rows):
    if all("key" in row for row in differences):
        return differences
    # The original result stored display fields only. A unique exact current playing row
    # proves its edit key; a token display name does not prove the physical pair.
    def display(row):
        return tuple(row[field] for field in _CARD_DISPLAY)

    exact = {}
    for row in rows:
        identity = display(row)
        exact[identity] = row["key"] if identity not in exact and "token" not in row else None
    return [{**row, "key": exact[display(row)]} if "key" not in row and exact.get(display(row)) else row
            for row in differences]


def _public(space, section, saved, *, detail=False):
    answer = {key: value for key, value in section.items() if key != "rows"}
    if saved is None:
        return {**answer, "audit": None}
    audit = {key: saved[key] for key in ("audited_at", "revision", "expected", "observed", "mismatch_rows",
                                        "extra", "missing", "surplus")}
    audit["current"] = saved["digest"] == _digest(space, section)
    audit["needs_review"] = bool(saved["mismatch_rows"] or saved["extra"])
    if detail:
        audit["differences"] = _historical_differences(saved["differences"], section["rows"])
        audit["unidentified_extra"] = saved["extra"] - audits.identified_extra(saved["differences"])
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


def _unlisted(value):
    if not isinstance(value, list) or len(value) > MAX_UNLISTED:
        raise ApiError(400, f"Enter up to {MAX_UNLISTED:,} named unlisted printings.")
    result = {}
    for item in value:
        if not isinstance(item, dict):
            raise ApiError(400, _UNLISTED)
        _keys(item, (*_PRINTING, "quantity"))
        if not all(isinstance(item[field], str) for field in _PRINTING):
            raise ApiError(400, _UNLISTED)
        row = {field: item[field].strip() for field in _PRINTING}
        row["set"] = row["set"].lower()
        if (not SET_RE.fullmatch(row["set"]) or not NUMBER_RE.fullmatch(row["collector_number"])
                or row["finish"] not in FINISHES):
            raise ApiError(400, _UNLISTED)
        if not _number(item["quantity"]) or item["quantity"] == 0:
            raise ApiError(400, "Enter a positive whole count for each named unlisted printing.")
        key = _picture_key(row)
        if key in result:
            raise ApiError(400, "Combine the counts for each unlisted printing and finish into one entry.")
        result[key] = {**row, "key": key, "expected": 0, "observed": item["quantity"], "estimated": False}
    return result


def _named_differences(unlisted):
    if unlisted:
        _require_cards()
    for row in unlisted.values():
        set_code, number = row["set"], row["collector_number"]
        printing = cards.printing(set_code, number)
        if printing is None or cards.printing_card(set_code, number) is None or _printing_problem(printing, row):
            raise ApiError(400, _UNLISTED)
        name = cards.resolve(printing["name"])
        if name is None:
            raise ApiError(400, _UNLISTED)
        if name in decks.BASIC_LANDS:
            raise ApiError(400, "Set basic lands aside. Their loose copies are outside this audit.")
        yield {**row, "name": name}


def _count_result(selected, counts, extra, unlisted, digest):
    rows = selected["rows"]
    if counts.keys() != {row["key"] for row in rows}:
        raise ApiError(400, "Enter the observed count for every listed row in this section.")
    if not counts.keys().isdisjoint(unlisted):
        raise ApiError(400, "Enter a listed printing's count on its existing row.")
    differences = []
    missing = surplus = 0
    for row in rows:
        expected, observed = row["quantity"], counts[row["key"]]
        if observed != expected:
            difference = {field: row[field] for field in _EVIDENCE_FIELDS if field in row}
            differences.append({**difference, "expected": expected, "observed": observed})
            missing += max(0, expected - observed)
            surplus += max(0, observed - expected)
    differences.extend(_named_differences(unlisted))
    extra += sum(row["observed"] for row in unlisted.values())
    return {"digest": digest, "expected": selected["quantity"], "observed": sum(counts.values()) + extra,
            "extra": extra, "missing": missing, "surplus": surplus, "mismatch_rows": len(differences),
            "differences": differences}


def record(body):
    """POST /api/collection/storage-map records observations only after checking the current section."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    space = space_param(data.get("space"))
    _private(space, profile)
    _keys(data, ("profile", "section", "expect", "counts", "extra"), ("space", "unlisted"))
    ident = _section_id(data["section"])
    expect = _EXPECT.fullmatch(data["expect"]) if isinstance(data["expect"], str) else None
    if not expect:
        raise ApiError(400, "Open the section again before recording its count.")
    counts, extra = data["counts"], data["extra"]
    if not isinstance(counts, dict) or not _number(extra) or not all(_number(count) for count in counts.values()):
        raise ApiError(400, "Enter observed counts as whole numbers of zero or more.")
    unlisted = _unlisted(data.get("unlisted", []))

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
        return _count_result(selected, counts, extra, unlisted, current)

    with state_errors():
        try:
            saved = state.store().collection_audit_record(space, ident, int(expect[1]), review, _web_actor(profile),
                                                          "Record a collection storage audit")
        except audits.MissingSchema:
            raise ApiError(409, audits.MIGRATE, reason="migration") from None
    return {"section": _public(space, selected, saved, detail=True), "expect": f"{saved['revision']}:{saved['digest']}"}
