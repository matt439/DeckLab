"""Settings' Data sources panel (E11-S85): each downloaded source's last good fetch and last
failure, for an admin.

    GET /api/settings/data-sources

    {"readable": bool (False: the receipt file is damaged, so nothing in it is shown),
     "sources": [{"key", "label", "last_ok", "last_failure" (UTC ISO times or None),
                  "state": "ok" | "failing" | "never" | "stale"}],
     "card_data": {"stale", "warning"} (card_freshness's judgement, or None when it couldn't be read)}

Scryfall's card data and the exchange rate are "stale" when card_freshness says they stopped
refreshing, even when their newest fetch worked. An admin by role, or a script naming nobody (as
the reference facts); anyone else gets 403. Reading changes nothing and fetches nothing: the
receipts (lib/source_health.py) and the dates card_freshness reads are small files on the PC, and
they hold only fixed source keys and times, never an error's words.
"""
from decklab.lib import card_freshness, source_health

from .common import ApiError

ADMINS_ONLY = "Data sources are for admins."


def _require_admin():
    from . import guard
    profile = guard.viewer()
    if profile is None and guard.script():
        return
    if profile is None or profile.get("role") != "admin":
        raise ApiError(403, ADMINS_ONLY)


def answer(receipts, freshness):
    """The view's answer from source_health.view() and card_freshness.check() (or None)."""
    rows = []
    for row in receipts["sources"]:
        row = dict(row)
        part = (freshness or {}).get({"scryfall": "cards", "fx": "fx"}.get(row["key"], ""))
        if isinstance(part, dict) and part.get("stale"):
            row["state"] = "stale"
        rows.append(row)
    card_data = {"stale": freshness["stale"], "warning": freshness["warning"]} if freshness else None
    return {"readable": receipts["readable"], "sources": rows, "card_data": card_data}


def data_sources_view():
    """GET /api/settings/data-sources (the module docstring)."""
    _require_admin()
    try:
        freshness = card_freshness.check()
    except Exception:       # noqa: BLE001 (the receipts still show)
        freshness = None
    return answer(source_health.view(), freshness)
