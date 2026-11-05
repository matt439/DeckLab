"""The price settings (E11-S53): the currency estimates are in and the price-check shops, a home
admin's choice on Settings' Prices panel, saved in the database over config.json's.

    GET /api/pricing-setting   home's record readers (permissions.sees_home_records), anyone else
                               403 before any read: {"revision",
                                 "currency": {saved, config, effective, symbol, source},
                                 "shops": {saved, config, effective, choices: [{key, name, site}], source},
                                 "currencies": ECB_CODES with their symbols, "can_edit"}
                               saved is the Settings choice (None: config.json's applies), config
                               config.json's (None when unset), effective what Deck Lab uses now and
                               source "saved", "config" or "default"
    PUT /api/pricing-setting   {"profile", "expect": revision, "currency": code or None,
                                "shops": [key] or None}: pricing.edit (a home admin); the whole
                               record is replaced after checking its revision (409 when it changed)

Why not config.json: lib/pricing_setting.py. No restart: the server's cache takes the saved value
at once, and other processes within the store's minute. Before migration 0022 both answer 503 with
the migration's words (state.pricing.MIGRATE), and config.json applies.
"""
from contextlib import contextmanager

from decklab.lib import config, currency, permissions, pricing_setting, shops, state
from decklab.lib.state import pricing as rules_pricing

from . import guard
from .common import ApiError, _load_json, state_errors
from .settings import _web_actor

MAX_BODY = 4096
PRIVATE = "The price settings are private to home."
MESSAGE = "Set the price settings"


def _sees():
    return permissions.sees_home_records(guard.viewer(), script=guard.script())


def _config():
    try:
        return config.load()
    except Exception:          # an unreadable config.json: the defaults, as /api/status
        return {}


def _answer(saved):
    record = rules_pricing.normalize(saved["pricing"])
    base = _config()
    merged = pricing_setting.overlay(base, record)
    config_code = currency.valid(base.get(currency.SETTING))
    config_shops = (None if base.get(shops.SETTING) is None
                    else [adapter.key for adapter in shops.enabled_adapters(base)])
    effective = currency.code(merged)
    return {
        "revision": saved["revision"],
        "currency": {"saved": record["currency"], "config": config_code, "effective": effective,
                     "symbol": currency.symbol(effective),
                     "source": pricing_setting.source(currency.SETTING, base, record)},
        "shops": {"saved": record["shops"], "config": config_shops,
                  "effective": [adapter.key for adapter in shops.enabled_adapters(merged)],
                  "choices": [{"key": adapter.key, "name": adapter.name, "site": adapter.site}
                              for adapter in shops.SNAPSHOT_ADAPTERS],
                  "source": pricing_setting.source(shops.SETTING, base, record)},
        "currencies": [{"code": code, "symbol": currency.symbol(code)} for code in currency.ECB_CODES],
        "can_edit": guard.allowed(guard.viewer(), "pricing.edit"),
    }


@contextmanager
def _store_errors():
    """state_errors(), but before migration 0022 the 503 says so (the panel shows it)."""
    with state_errors():
        try:
            yield
        except state.Unavailable as error:
            if str(error) == rules_pricing.MIGRATE:
                raise ApiError(503, rules_pricing.MIGRATE, reason="database") from None
            raise


def view():
    """GET /api/pricing-setting."""
    if not _sees():
        raise ApiError(403, PRIVATE)
    with _store_errors():
        return _answer(state.store().pricing_setting())


def change(body):
    """PUT /api/pricing-setting: the whole record, after checking its revision."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    if len(body) > MAX_BODY:
        raise ApiError(413, f"The price settings are limited to {MAX_BODY} bytes")
    data = _load_json(body, "The price settings")
    if not isinstance(data, dict):
        raise ApiError(400, "The price settings must be a JSON object")
    profile = guard.writer(data, "pricing.edit")
    if not _sees():
        raise ApiError(403, PRIVATE)
    if set(data) - {"profile", "expect", "currency", "shops"} or not {"currency", "shops"} <= set(data):
        raise ApiError(400, "The price settings request must have expect, currency and shops, and nothing else")
    with _store_errors():
        expect = rules_pricing.expectation(data.get("expect"))
        record = rules_pricing.normalize({"currency": data["currency"], "shops": data["shops"]})
        saved = state.store().pricing_setting_put(record, expect, _web_actor(profile), MESSAGE)
        pricing_setting.forget()
        return _answer(saved)
