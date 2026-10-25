"""Read-only printing evidence on inventory-visible buying rows.

Reprints describe the dated local card snapshot. They never change purchase
intent, observed shop prices or a row's last price-check date.
"""
from decklab.lib import reprints as catalogue

from . import common
from .shopping_missing import is_token


def evidence(row, *, queued=False, cache=None):
    """Actionable printing information, or None for a quiet ordinary card row.

    Waiting rows always retain uncertainty and the manual review offer. Other
    cards get a notice only when the snapshot identifies an upcoming reprint.
    A token printing must not borrow a playable card's same-name history.
    """
    if row.get("is_token") or is_token(row):
        return None
    waiting = queued and row.get("state") == "waiting_for_reprint"
    checked = row.get("checked") if queued else None
    key = (row.get("name"), checked, waiting)
    if cache is not None and key in cache:
        return cache[key]
    try:
        result = catalogue.for_card(row.get("name", ""), checked=checked, waiting=waiting)
    except Exception as error:  # optional evidence must not turn an already-saved queue change into a failure
        common._log(f"Reprint evidence could not be prepared: {type(error).__name__}: {error}")
        result = None
    if result is None:
        return None
    shown = result if waiting or result.get("upcoming") or result.get("released") else None
    if cache is not None:
        cache[key] = shown
    return shown


def enrich(rows, *, queued=False, cache=None):
    """Decorate only queued cards or positive missing-card rows, without writes."""
    cache = {} if cache is None else cache
    for row in rows:
        if not queued and not (row.get("missing") or 0) > 0:
            continue
        found = evidence(row, queued=queued, cache=cache)
        if found is not None:
            row["reprints"] = found
    return rows
