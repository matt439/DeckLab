"""The household's price settings (E11-S53): the currency estimates are in and the price-check shops,
a home admin's choice on Settings' Prices panel. One record, saved whole with a revision, as the
shops' postage is (migration 0022):

    {"v": 1, "currency": "EUR" | None, "shops": ["mtgmate", ...] | None}

Version 2 additionally keeps listing_preferences (E5-S34): a minimum condition
and English-only switch. Neutral choices remain version 1; no config field is
added. The nullable choice means every listing, including unreported facts.

None means "use config.json's" (and then the default): lib/pricing_setting.py lays a saved field
over config.json. A currency is one of lib/currency.ECB_CODES, upper case; shops are lib/shops'
adapter keys in its order, without repeats, [] turning the nightly shop check off. The rules are
currency.valid() and shops.normalize_keys(), so the page, the store and `db check` agree with the
readers.
"""
from . import Invalid

FIELDS = ("currency", "shops", "listing_preferences")
EMPTY = {"v": 1, "currency": None, "shops": None}
CHANGED = "The price settings changed. Reload them before saving."
MIGRATE = "Price settings need the database migration 0022: python -m decklab.db migrate"
PREFERENCES_MIGRATE = "Listing preferences need the database migration 0025: python -m decklab.db migrate"
BAD_CURRENCY = "Choose a currency the ECB publishes a USD rate for"


def expectation(value):
    """The complete record's optimistic revision (0 before anything was saved)."""
    if type(value) is not int or value < 0:
        raise Invalid("expect must be a whole-number revision of 0 or above")
    return value


def _currency(value):
    from decklab.lib import currency
    if value is None:
        return None
    code = currency.valid(value)
    if code is None:
        raise Invalid(f"{BAD_CURRENCY} ({', '.join(currency.ECB_CODES)}), or none to use config.json's")
    return code


def _shops(value):
    from decklab.lib import shops
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(key, str) for key in value):
        raise Invalid("shops must be a list of shop keys, or none to use config.json's")
    if len(value) > 20:
        raise Invalid("At most 20 shops can be listed")
    for key in value:
        if key.strip().lower() not in shops.ADAPTERS:
            raise Invalid(f"Unknown shop: {key.strip()[:40]}")
    return list(shops.normalize_keys(value))


def normalize(value):
    """Canonical v1/v2 record. Legacy currency/shops-only objects stay v1;
    a non-neutral listing preference needs v2. Invalid for unknown fields."""
    if not isinstance(value, dict):
        raise Invalid("The price settings must be an object of currency and shops")
    fields = dict(value)
    version = None
    if "v" in fields:
        version = fields.pop("v")
        if type(version) is not int or version not in (1, 2):
            raise Invalid("Unknown price settings record version")
        if version == 1 and "listing_preferences" in fields:
            raise Invalid("Listing preferences need a version 2 price settings record")
        if version == 2 and "listing_preferences" not in fields:
            raise Invalid("Version 2 price settings need listing_preferences")
    if set(fields) - set(FIELDS):
        raise Invalid("The price settings have only currency, shops and listing_preferences")
    from decklab.lib.shops import listing_preferences
    try:
        preference = listing_preferences.normalize(fields.get("listing_preferences"))
    except ValueError as error:
        raise Invalid(str(error)) from None
    record = {"v": 1, "currency": _currency(fields.get("currency")), "shops": _shops(fields.get("shops"))}
    if preference is not None or version == 2:
        record.update(v=2, listing_preferences=preference)
    return record
