"""Each shop's postage rules (E5-S27), a home admin's setting on the Settings page.

    GET /api/shop-postage   home's record readers (permissions.sees_home_records), anyone else 403
                            before any read: {"revision", "shops": [{key, shop, site,
                            postage_aud, free_over_aud}], "can_edit"}, one entry for each
                            price-check shop (lib/shops.SNAPSHOT_ADAPTERS), None when not known
    PUT /api/shop-postage   {"profile", "expect": revision, "shops": {key: {postage_aud,
                            free_over_aud}}}: postage.edit (a home admin); the whole record is
                            replaced after checking its revision (409 when it changed since)

Shopping's Baskets read the same record (rules(), quietly unknown when it can't be read).
"""
from decklab.lib import permissions, shops, state
from decklab.lib.state import shop_postage as rules_postage

from . import guard
from .common import ApiError, _load_json, state_errors
from .settings import _web_actor

MAX_BODY = 8192
PRIVATE = "The shops' postage is private to home."


def _sees():
    return permissions.sees_home_records(guard.viewer(), script=guard.script())


def adapters():
    """The shops whose postage can be set: the price-check shops, in their order."""
    enabled = getattr(shops, "enabled_adapters", None)
    return list(enabled()) if callable(enabled) else list(shops.SNAPSHOT_ADAPTERS)


def _answer(saved):
    record = saved["postage"]
    return {"revision": saved["revision"],
            "shops": [{"key": adapter.key, "shop": adapter.name, "site": adapter.site,
                       **rules_postage.rules_for(record, adapter.key)} for adapter in adapters()],
            "can_edit": guard.allowed(guard.viewer(), "postage.edit")}


def view():
    """GET /api/shop-postage."""
    if not _sees():
        raise ApiError(403, PRIVATE)
    with state_errors():
        return _answer(state.store().shop_postage())


def change(body):
    """PUT /api/shop-postage: the whole record, after checking its revision."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    if len(body) > MAX_BODY:
        raise ApiError(413, f"The shops' postage is limited to {MAX_BODY} bytes")
    data = _load_json(body, "The shops' postage")
    if not isinstance(data, dict):
        raise ApiError(400, "The shops' postage must be a JSON object")
    profile = guard.writer(data, "postage.edit")
    if not _sees():
        raise ApiError(403, PRIVATE)
    if set(data) - {"profile", "expect", "shops"} or "shops" not in data:
        raise ApiError(400, "The postage request must have expect and shops, and nothing else")
    known = {adapter.key for adapter in shops.ADAPTERS.values()}
    with state_errors():
        expect = rules_postage.expectation(data.get("expect"))
        postage = rules_postage.normalize(data["shops"], known)
        saved = state.store().shop_postage_put(postage, expect, _web_actor(profile), "Set the shops' postage", known=known)
        return _answer(saved)


def rules():
    """{key: {postage_aud, free_over_aud}} for Shopping's Baskets, or None when it can't be read
    (a database that's down or not migrated, or no store): then every shop's postage is unknown."""
    try:
        record = state.store().shop_postage()["postage"]
    except (state.StateError, RuntimeError) as error:     # RuntimeError: no store installed (a test's)
        from . import common
        common._log(f"The shops' postage could not be read: {type(error).__name__}")
        return None
    return {adapter.key: rules_postage.rules_for(record, adapter.key) for adapter in shops.ADAPTERS.values()}
