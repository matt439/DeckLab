"""Optional same-snapshot row targeting for newly authored arrival checks."""
from decklab.lib import inventory
from decklab.lib.inventory import check_links


def supported():
    store = inventory.backend()
    if getattr(store, "name", None) != "db":
        return True
    try:
        probe = getattr(store, "supports_check_links", None)
        return callable(probe) and probe() is True
    except Exception:
        return False


def projection(component, rows, fields, available):
    checks = list(component.checks or [])
    result = {"check_targets": [None] * len(checks),
              "check_targeting": {"available": False, "payload_sha256": None, "row_sha256s": []}}
    if not available or component.kind not in ("cards", "tokens") or component.status != "pending":
        return result
    try:
        payload = check_links.digest(rows, fields)
        proofs = [check_links.row_digest(row, fields) for row in rows]
    except (TypeError, ValueError, UnicodeError):
        return result
    result["check_targets"] = check_links.project(component, rows, fields)
    result["check_targeting"] = {"available": bool(rows), "payload_sha256": payload if rows else None,
                                  "row_sha256s": proofs}
    return result
