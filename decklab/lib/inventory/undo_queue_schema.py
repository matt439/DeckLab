"""Legacy/current watchlist audit images, preserving optional AUD targets exactly."""
from decimal import Decimal

from .model import QUEUE_FIELDS
from .table_rows import WATCH_COLUMNS
from .watchlist_targets import FIELD, normalize

COLUMN = dict(zip(QUEUE_FIELDS, WATCH_COLUMNS))
FIELDS = {"id", "position", *WATCH_COLUMNS}


def valid(image):
    if not isinstance(image, dict) or set(image) not in (FIELDS, FIELDS - {FIELD}):
        return False
    if (type(image.get("id")) is not int or not 1 <= image["id"] < 10 ** 18
            or type(image.get("position")) is not int or not 0 <= image["position"] < 2 ** 31
            or type(image.get("quantity")) is not int or not 1 <= image["quantity"] < 2 ** 31
            or not all(isinstance(image[column], str) for column in WATCH_COLUMNS if column not in ("quantity", FIELD))):
        return False
    value = image.get(FIELD)
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float, Decimal))):
        return False
    try:
        normalize(value)
    except ValueError:
        return False
    return True


def row(image):
    return {field: normalize(image.get(FIELD)) or "" if field == FIELD
            else str(image["quantity"]) if field == "quantity" else image[COLUMN[field]] for field in QUEUE_FIELDS}


def same(first, second):
    """Only the additive nullable target differs between legacy/current audit schemas."""
    if not valid(first) or not valid(second):
        return False
    def normalized(image):
        return {**image, FIELD: normalize(image.get(FIELD))}
    return normalized(first) == normalized(second)


def market_receipt(restores):
    """Historical targets are explicit intent, reviewed against a fresh cache/policy context.
    No lookup or fetch is required; unchanged targets never need a market input read."""
    changed = [restored for current, restored in restores if restored is not None
               and restored.get(FIELD, "") != (current or {}).get(FIELD, "")]
    if not changed:
        return None
    from decklab.lib import shop_reference_source
    from .undo import UndoConflict
    try:
        source = shop_reference_source.context(fresh=True)
        return [shop_reference_source.receipt(restored, source) for restored in changed]
    except ValueError:
        raise UndoConflict("The market-target source or household preference couldn't be confirmed. Nothing was undone.") from None
