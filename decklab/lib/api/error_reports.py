"""Enum-only diagnostic ingestion and a named home-admin operational view."""
from decklab.lib import error_references, permissions
from . import guard
from .common import ApiError, _keys, _parse_body

MAX_BODY = 2048


def report(body):
    """Normal same-origin transport checks apply; metadata is bounded, not inventory authority."""
    data = _parse_body(body, MAX_BODY)
    _keys(data, ("reference", "page", "type"), ("profile",))
    if not isinstance(data["reference"], str) or not error_references.REF.fullmatch(data["reference"]) \
            or not isinstance(data["page"], str) or data["page"] not in error_references.PAGES \
            or not isinstance(data["type"], str) or data["type"] not in error_references.TYPES:
        raise ApiError(400, "Error reports take only a reference, page kind and supported error type.")
    _, result = error_references.record(data["page"], data["type"], data["reference"])
    if result == "limited":
        raise ApiError(429, "Too many error reports were received. Try again later.")
    if result == "unavailable":
        raise ApiError(503, "The error report could not be kept right now.", reason="diagnostics")
    return {"accepted": True}


def view():
    profile = guard.viewer()
    if not profile or profile.get("role") != "admin" or permissions._space_of(profile) != permissions.HOME:
        raise ApiError(403, "Page-error references are for a home admin.")
    events, ready = error_references.read()
    return {"ready": ready, "events": list(reversed(events)),
            "message": None if ready else "Error references cannot be read; check the server log on the PC."}
