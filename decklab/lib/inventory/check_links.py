"""Explicit arrival-check row links, separate from the ordered check strings.

Proofs bind a selected row to its complete ordered payload. A missing, malformed
or stale proof leaves the ordinary check visible without a row association.
Everything here is pure; no row is selected from its name or the check's words.
"""
import hashlib
import json
import re
from collections.abc import Mapping

from decklab.lib.state import Invalid

MAX_LINKS = 100
_HASH = re.compile(r"[0-9a-f]{64}")
_FIELDS = {"check", "text", "payload_sha256", "row", "row_sha256"}
_INVALID = "Choose an existing row from the current pending component for this check."


def _fields(fields):
    if not isinstance(fields, (list, tuple)) or not fields or any(not isinstance(key, str) for key in fields) \
            or len(set(fields)) != len(fields):
        raise ValueError("A check proof needs complete text rows and their unique fields.")


def _row(row, fields):
    _fields(fields)
    if not isinstance(row, Mapping) or set(row) != set(fields) or any(not isinstance(row[key], str) for key in fields):
        raise ValueError("A check proof needs complete text rows and their unique fields.")
    return {key: row[key] for key in fields}


def _sha(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def digest(rows, fields):
    """SHA-256 of every complete text row, preserving the payload's row order."""
    if not isinstance(rows, (list, tuple)):
        raise ValueError("A check proof needs an ordered list of complete text rows.")
    # Validate fields even for an empty payload; an empty field list proves nothing.
    _fields(fields)
    return _sha([_row(row, fields) for row in rows])


def row_digest(row, fields):
    """SHA-256 of one complete text row, without changing any value."""
    return _sha(_row(row, fields))


def _checks(component):
    values = component.checks
    return list(values) if isinstance(values, (list, tuple)) else []


def _eligible(component):
    return component.kind in ("cards", "tokens") and component.status == "pending"


def _hash(value):
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _links(component, checks):
    raw = component.data.get("check_links") if isinstance(component.data, Mapping) else None
    if raw is None:
        return []
    if not isinstance(raw, dict) or set(raw) != {"version", "links"} or type(raw["version"]) is not int \
            or raw["version"] != 1 or not isinstance(raw["links"], list) or len(raw["links"]) > MAX_LINKS \
            or any(not isinstance(text, str) or not text.strip() for text in checks):
        return None
    seen, out = set(), []
    for link in raw["links"]:
        if not isinstance(link, dict) or set(link) != _FIELDS:
            return None
        number, row = link["check"], link["row"]
        if type(number) is not int or not 1 <= number <= len(checks) or number in seen \
                or type(row) is not int or row < 1 or not isinstance(link["text"], str) \
                or link["text"] != checks[number - 1] or not _hash(link["payload_sha256"]) \
                or not _hash(link["row_sha256"]):
            return None
        seen.add(number)
        out.append(dict(link))
    return out


def project(component, rows, fields):
    """One None or proven {row, row_sha256} per check; never return check text."""
    checks = _checks(component)
    out = [None] * len(checks)
    links = _links(component, checks)
    if not _eligible(component) or not links:
        return out
    try:
        payload_sha256 = digest(rows, fields)
        for link in links:
            index = link["row"] - 1
            if link["payload_sha256"] == payload_sha256 and index < len(rows) \
                    and link["row_sha256"] == row_digest(rows[index], fields):
                out[link["check"] - 1] = {"row": link["row"], "row_sha256": link["row_sha256"]}
    except (TypeError, ValueError, UnicodeError):
        return [None] * len(checks)
    return out


def append(component, rows, fields, text, target=None):
    """Metadata after appending text, optionally linked to an explicit current row.

    Old associations survive only while their proofs still project. The caller
    saves the returned metadata and appends the ordinary check string together.
    """
    checks = _checks(component)
    if not isinstance(text, str) or not text.strip():
        raise Invalid("An arrival check needs non-blank text.")
    projected = project(component, rows, fields)
    kept = []
    try:
        payload_sha256 = digest(rows, fields) if target is not None or any(projected) else None
        for index, proof in enumerate(projected, 1):
            if proof is not None:
                kept.append({"check": index, "text": checks[index - 1], "payload_sha256": payload_sha256,
                             "row": proof["row"], "row_sha256": proof["row_sha256"]})
        if target is not None:
            if not _eligible(component) or not isinstance(target, dict) or set(target) != {"row", "payload_sha256"} \
                    or type(target["row"]) is not int or not 1 <= target["row"] <= len(rows) \
                    or not _hash(target["payload_sha256"]) or target["payload_sha256"] != payload_sha256:
                raise Invalid(_INVALID)
            kept.append({"check": len(checks) + 1, "text": text, "payload_sha256": payload_sha256,
                         "row": target["row"], "row_sha256": row_digest(rows[target["row"] - 1], fields)})
    except (TypeError, ValueError, UnicodeError):
        raise Invalid(_INVALID) from None
    if len(kept) > MAX_LINKS:
        raise Invalid("At most 100 arrival checks may have row associations.")
    return {"version": 1, "links": kept} if kept else None


def remap(component, newchecks, removedindex=None):
    """Preserve proof across one explicitly numbered removal; invalidate other edits."""
    checks = _checks(component)
    if not isinstance(newchecks, (list, tuple)) or not newchecks or not _eligible(component):
        return None
    links = _links(component, checks)
    if not links:
        return None
    if removedindex is None:
        return {"version": 1, "links": links} if list(newchecks) == checks else None
    if type(removedindex) is not int or not 1 <= removedindex <= len(checks) \
            or list(newchecks) != checks[:removedindex - 1] + checks[removedindex:]:
        return None
    kept = [{**link, "check": link["check"] - (link["check"] > removedindex)}
            for link in links if link["check"] != removedindex]
    return {"version": 1, "links": kept} if kept else None
