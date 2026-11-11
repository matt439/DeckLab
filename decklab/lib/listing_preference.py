"""One verified household listing preference, with the price setting's last-good fallback."""
import os

from decklab.lib import pricing_setting, state
from decklab.lib.shops import listing_preferences

UNAVAILABLE = object()
UNKNOWN = "The household's listing preference couldn't be confirmed. Try again when the price settings can be read."


def current():
    try:
        state.store()
    except RuntimeError:
        # Only protected fixtures may have no provider. Production store() lazily
        # creates PgStore; a bootstrap failure must not relax a saved restriction.
        return None if os.environ.get(state.EXPLICIT_ENV) else UNAVAILABLE
    except Exception:
        return UNAVAILABLE
    record = pricing_setting.saved()      # includes its bounded retry and last-good cached record
    if record is None:
        return UNAVAILABLE
    try:
        return listing_preferences.normalize(record.get("listing_preferences"))
    except ValueError:
        return UNAVAILABLE
