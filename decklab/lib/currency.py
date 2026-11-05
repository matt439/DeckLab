"""The currency Deck Lab's price estimates are in (E11-S53): config.json's "currency", an ISO 4217
code. Unset means AUD, so a household that never sets it sees nothing change.

Scryfall gives USD; lib/cards.usd_to_aud() converts with the ECB reference rate (Frankfurter) for
this code, and the deck tables' header and rate statement name it (lib/decks). Only the currencies
the ECB publishes a USD rate for can be chosen (ECB_CODES), plus USD itself (a rate of 1). A value
Deck Lab can't use is said once on stderr and AUD is used.

    from decklab.lib import currency
    currency.code()          # "AUD"
    currency.symbol("EUR")   # "€"
    currency.money(12.5)     # "A$12.50"
"""
import re
import sys

from decklab.lib import config

SETTING = "currency"
DEFAULT = "AUD"
# The ECB's reference-rate currencies (the ones Frankfurter converts USD into), and USD itself.
ECB_CODES = ("AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP", "HKD", "HUF", "IDR", "ILS",
             "INR", "ISK", "JPY", "KRW", "MXN", "MYR", "NOK", "NZD", "PHP", "PLN", "RON", "SEK", "SGD",
             "THB", "TRY", "USD", "ZAR")
# How an amount is written in words and labels ("A$12.50"); a code without one is written "SEK 12.50".
SYMBOLS = {"AUD": "A$", "USD": "US$", "CAD": "C$", "NZD": "NZ$", "SGD": "S$", "HKD": "HK$", "EUR": "€",
           "GBP": "£", "JPY": "¥", "INR": "₹", "KRW": "₩", "ILS": "₪"}
# The deck table's price cells ("~$0.40"): the header names the currency, so a dollar is just "$".
_CELL_SYMBOLS = {"EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥", "INR": "₹", "KRW": "₩", "ILS": "₪"}
_DOLLARS = {"AUD", "USD", "CAD", "NZD", "SGD", "HKD", "MXN"}
_CODE_RE = re.compile(r"[A-Za-z]{3}")
_said = set()


def _say_once(text):
    if text not in _said:
        _said.add(text)
        print(text, file=sys.stderr, flush=True)


def code(settings=None):
    """The configured currency's upper-case code: config.json's "currency", or DEFAULT when it isn't
    set. A value that isn't one of ECB_CODES counts as unset, said once. settings: config.load()'s."""
    value = (config.load() if settings is None else settings).get(SETTING)
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT
    wanted = value.strip().upper() if isinstance(value, str) else None
    if wanted and _CODE_RE.fullmatch(wanted) and wanted in ECB_CODES:
        return wanted
    _say_once(f'config.json\'s "{SETTING}" ({value!r}) isn\'t a currency the ECB publishes a USD rate for '
              f"({', '.join(ECB_CODES)}), so prices stay in {DEFAULT}.")
    return DEFAULT


def symbol(currency=None):
    """"A$" for AUD, "€" for EUR; a code without its own sign is written as the code and a space."""
    currency = currency or code()
    return SYMBOLS.get(currency, f"{currency} ")


def money(amount, currency=None):
    """"A$12.50": an amount in the currency, for words and labels."""
    return f"{symbol(currency)}{amount:.2f}"


def cell(amount, currency=DEFAULT):
    """A deck table's price cell: "~$0.40" (AUD, as always, and the other dollars), "~€0.40",
    or "~0.40" for a currency without a sign (its header names it)."""
    sign = "$" if currency in _DOLLARS else _CELL_SYMBOLS.get(currency, "")
    return f"~{sign}{amount:,.2f}"


def describe(settings=None):
    """{"code", "symbol", "default"}: what the Settings page and /api/status say."""
    current = code(settings)
    return {"code": current, "symbol": symbol(current), "default": current == DEFAULT}
