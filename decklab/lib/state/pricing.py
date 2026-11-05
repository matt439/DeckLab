"""The household's price settings (E11-S53): the currency estimates are in and the price-check shops,
a home admin's choice on Settings' Prices panel. One record, saved whole with a revision, as the
shops' postage is (migration 0022):

    {"v": 1, "currency": "EUR" | None, "shops": ["mtgmate", ...] | None}

None means "use config.json's" (and then the default): lib/pricing_setting.py lays a saved field
over config.json. A currency is one of lib/currency.ECB_CODES, upper case; shops are lib/shops'
adapter keys in its order, without repeats, [] turning the nightly shop check off. The rules are
currency.valid() and shops.normalize_keys(), so the page, the store and `db check` agree with the
readers.
"""
from . import Invalid

FIELDS = ("currency", "shops")
EMPTY = {"v": 1, "currency": None, "shops": None}
CHANGED = "The price settings changed. Reload them before saving."
MIGRATE = "Price settings need the database migration 0022: python -m decklab.db migrate"
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
    """{"v": 1, "currency", "shops"} from the record, or from an object of currency and shops alone
    (either may be left out, meaning None). Invalid for anything else."""
    if not isinstance(value, dict):
        raise Invalid("The price settings must be an object of currency and shops")
    fields = dict(value)
    if "v" in fields:
        version = fields.pop("v")
        if type(version) is not int or version != 1:
            raise Invalid("Unknown price settings record version")
    if set(fields) - set(FIELDS):
        raise Invalid("The price settings have only currency and shops")
    return {"v": 1, "currency": _currency(fields.get("currency")), "shops": _shops(fields.get("shops"))}
