"""Each shop's postage rules (E5-S27): a flat postage and a free-postage threshold, in AUD.

One household record, saved whole with a revision, as the Commander-night notes are:

    {"v": 1, "shops": {"mtgmate": {"postage_aud": "8.50", "free_over_aud": "100.00"}, ...}}

A shop key is a price-check shop's key (lib/shops' adapters: mtgmate, gamesportal), a value
either a decimal of at most two places from 0 to 9999.99, as text, or None when it isn't known.
A shop with nothing known is left out. Postage "0.00" means it always posts free; a threshold
None means no free postage is known (the flat postage always applies). Nothing is ever filled in
from a shop's site: these are what an admin typed in Settings, never a price paid.
"""
import re
from decimal import Decimal, InvalidOperation

from . import Invalid

FIELDS = ("postage_aud", "free_over_aud")
KEY = re.compile(r"[a-z][a-z0-9_-]{0,39}")
AMOUNT = re.compile(r"\d{1,4}(?:\.\d{1,2})?")
MAX_SHOPS = 20
CHANGED = "The shops' postage changed. Reload it before saving."


def expectation(value):
    """The complete record's optimistic revision (0 before anything was saved)."""
    if type(value) is not int or value < 0:
        raise Invalid("expect must be a whole-number revision of 0 or above")
    return value


def amount(value, what):
    """A money amount as "12.50" text, or None for unknown (None or blank)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise Invalid(f"{what} must be an amount in AUD such as 8.50, or blank when unknown")
    text = str(value).strip()
    if not text:
        return None
    if not AMOUNT.fullmatch(text):
        raise Invalid(f"{what} must be an amount in AUD from 0 to 9999.99, with at most two decimal places")
    try:
        return f"{Decimal(text).quantize(Decimal('0.01'))}"
    except InvalidOperation:
        raise Invalid(f"{what} must be an amount in AUD") from None


def normalize(value, known=None):
    """{"v": 1, "shops": {key: {postage_aud, free_over_aud}}}, shops with nothing known left out.

    value is the record, or its "shops" object alone. known, when given (the configured shops'
    keys), refuses any other key; the store checks the key's form only, so rereading an old record
    never depends on which shops are configured now.
    """
    if isinstance(value, dict) and set(value) == {"v", "shops"}:
        if value.get("v") != 1:
            raise Invalid("Unknown postage record version")
        value = value["shops"]
    if not isinstance(value, dict):
        raise Invalid("shops must be an object of each shop's postage")
    if len(value) > MAX_SHOPS:
        raise Invalid(f"At most {MAX_SHOPS} shops' postage can be saved")
    out = {}
    for key in sorted(value):
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise Invalid("A shop key must be lowercase letters, digits, - or _")
        if known is not None and key not in known:
            raise Invalid(f"Unknown shop: {key}")
        rules = value[key]
        if not isinstance(rules, dict) or set(rules) - set(FIELDS):
            raise Invalid(f"{key}'s postage must be an object of postage_aud and free_over_aud")
        shown = {field: amount(rules.get(field), field) for field in FIELDS}
        if any(item is not None for item in shown.values()):
            out[key] = shown
    return {"v": 1, "shops": out}


def rules_for(record, key):
    """One shop's {postage_aud, free_over_aud}, each None when not known."""
    shops = (record or {}).get("shops") or {}
    rules = shops.get(key) or {}
    return {field: rules.get(field) for field in FIELDS}
