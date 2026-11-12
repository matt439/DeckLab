"""Whether Scryfall's card data and the exchange rate are still refreshing (E11-S85).

The server checks the card data every CHECK_EVERY (lib/server_run.py), downloads Scryfall's bulk
files once they're cards.MAX_BULK_AGE old, and fetches the rate at most once a day; a failure is
retried quietly. judge() is pure: it says a date is too old only past its update interval plus
RETRY_GRACE, so a day or two of retries never trips it, and an unknown, malformed or future date
has an unknown age, which counts as not refreshing. The warning is one fixed sentence naming
COMMAND; it never quotes an error, a path or a URL.

check() reads only small files on the PC, never the index itself and never the network: the date
of Scryfall's data the index was built from (bulk.json's "index" stamp, written by cards.update)
and the day the rate was last fetched (cards.fx_file). The admin's status (lib/api/carddata.py),
homenet status (lib/homenet/checks.py) and the nightly's "card data" step (decklab/db/nightly.py)
all use it.

parse_date is the one parser of these index dates: lib/stats/commander.py reads its source dates
with it too.
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

CHECK_EVERY = timedelta(days=1)         # how often the server checks the card data and the rate
RETRY_GRACE = timedelta(days=2)         # failed checks tolerated before a warning
FX_INTERVAL = timedelta(days=1)         # cards.usd_to_aud fetches at most once a day
PUBLISH_LAG = timedelta(days=1)         # Scryfall publishes its bulk files about daily
COMMAND = "python -m decklab.lib.cards update"
MAX_META_BYTES = 64 * 1024


def parse_date(value):
    """An index or receipt date (an ISO date, or an ISO timestamp whose calendar date counts) as a
    date, or None for anything else (missing, malformed, not text)."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value).date()
    except ValueError:
        return None


def card_limit():
    """How old Scryfall's data may get before it counts as not refreshing: the age at which it's
    downloaded again, how old Scryfall's file may be when it is, one check interval, and the grace
    for failed retries (11 days with a weekly download)."""
    from decklab.lib import cards
    return cards.MAX_BULK_AGE + PUBLISH_LAG + CHECK_EVERY + RETRY_GRACE


def fx_limit():
    """The rate is fetched on the first check of each day: a day, and the grace (3 days)."""
    return FX_INTERVAL + RETRY_GRACE


def _age(day, today):
    """Whole days from day to today; None when day is unknown or more than a day in the future
    (time zones apart, a later date than today is a wrong clock or a wrong file)."""
    if day is None or day > today + timedelta(days=1):
        return None
    return max(0, (today - day).days)


def _part(day, today, limit):
    age = _age(day, today)
    return {"date": day.isoformat() if day else None, "age_days": age, "limit_days": limit.days,
            "stale": age is None or age > limit.days}


def judge(cards_date, fx_date, today, *, fx_needed=True, card_limit_days=None, fx_limit_days=None):
    """cards_date: the date of Scryfall's data in the index; fx_date: the day the rate was last
    fetched (either a date, an ISO string or None); today: a date. fx_needed is False when prices
    are in USD (no rate to fetch). Returns {"cards", "fx" (None when not needed): {"date",
    "age_days" (None: unknown), "limit_days", "stale"}, "stale", "warning" (the one sentence, or
    None)}."""
    if not isinstance(cards_date, date):
        cards_date = parse_date(cards_date)
    if not isinstance(fx_date, date):
        fx_date = parse_date(fx_date)
    climit = timedelta(days=card_limit_days) if card_limit_days is not None else card_limit()
    flimit = timedelta(days=fx_limit_days) if fx_limit_days is not None else fx_limit()
    found = {"cards": _part(cards_date, today, climit),
             "fx": _part(fx_date, today, flimit) if fx_needed else None}
    words = []
    if found["cards"]["stale"]:
        age = found["cards"]["age_days"]
        words.append("the card data's age is unknown" if age is None else f"the card data is {_days(age)} old")
    if found["fx"] is not None and found["fx"]["stale"]:
        age = found["fx"]["age_days"]
        words.append("the exchange rate's age is unknown" if age is None
                     else f"the exchange rate was last fetched {_days(age)} ago")
    found["stale"] = bool(words)
    found["warning"] = (f"Card data may have stopped refreshing: {' and '.join(words)}; on the server PC "
                        f"run {COMMAND}.") if words else None
    return found


def _days(n):
    return "1 day" if n == 1 else f"{n} days"


def _small_json(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_META_BYTES + 1)
        if len(raw) > MAX_META_BYTES:
            return None
        return json.loads(raw)
    except (OSError, ValueError, RecursionError):
        return None


def card_date_on_disk(meta_file=None):
    """The date of Scryfall's data the index on the PC was built from (bulk.json's index stamp),
    or None when there's no index stamp or it can't be read."""
    from decklab.lib import cards
    meta = _small_json(meta_file or cards.BULK_META_FILE)
    stamp = meta.get("index") if isinstance(meta, dict) else None
    return parse_date(stamp.get("default_cards")) if isinstance(stamp, dict) else None


def fx_fetched_on(code, fx_file=None):
    """The day the rate for code was last fetched (cards.usd_to_aud's fetched_on), or None."""
    from decklab.lib import cards
    data = _small_json(fx_file or cards.fx_file(code))
    if not isinstance(data, dict) or data.get("to", "AUD") != code:
        return None
    return parse_date(data.get("fetched_on"))


def check(today=None, code=None, *, meta_file=None, fx_file=None):
    """judge() from the files on the PC. code: the price currency (read from the settings when not
    given; USD needs no rate)."""
    if code is None:
        from decklab.lib import currency
        code = currency.code()
    today = today or date.today()
    needed = code != "USD"
    return judge(card_date_on_disk(meta_file), fx_fetched_on(code, fx_file) if needed else None, today,
                 fx_needed=needed)
