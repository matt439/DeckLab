"""Optional AUD unit-price market targets, separate from retailer observations and spending."""
import re
from decimal import Decimal

FIELD = "buy_under_aud"
MIGRATE = "Buy-under targets need the database's migration 0026 (python -m decklab.db migrate on the PC)"


def normalize(value):
    """Canonical cents as text, or None for unset. No rounding or currency conversion."""
    if value is None or isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("The buy-under target must be an AUD unit amount, or blank")
    text = str(value).strip()
    if not re.fullmatch(r"\d{1,9}(?:\.\d{1,2})?", text):
        raise ValueError("The buy-under target must be 0 to 999999999.99 AUD, with at most two decimal places")
    return format(Decimal(text).quantize(Decimal("0.01")), ".2f")


def reached(target, quote):
    """A dated stock observation meets the target, or None without usable evidence."""
    amount = normalize(target)
    if amount is None or quote.get("status") != "in_stock" or quote.get("carried") \
            or type(quote.get("stock")) is not int or quote["stock"] <= 0:
        return None
    try:
        price = normalize(quote.get("price_aud"))
    except ValueError:
        return None
    return Decimal(price) <= Decimal(amount) if price is not None else None
