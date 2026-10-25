"""Plain, dated household Commander-night notes; no bracket or house-rule enforcement."""
import re
from datetime import date

from . import Invalid
from .rules import CONTROL, NOTES_CONTROL

KEYS = ("name", "venue", "target_bracket", "published_min", "published_max", "house_rules", "checked_on")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
CHANGED = "The Commander-night notes changed. Reload them before saving."


def expectation(value):
    """The complete record's optimistic revision, including an empty tombstone."""
    if type(value) is not int or value < 0:
        raise Invalid("expect must be a whole-number revision of 0 or above")
    return value


def _text(value, key, maximum, *, multiline=False):
    controls = NOTES_CONTROL if multiline else CONTROL
    if not isinstance(value, str) or len(value) > maximum or controls.search(value):
        raise Invalid(f"{key} must be text of at most {maximum} characters, with no control characters")
    return value.strip()


def normalize(value, *, today=None):
    """A complete note object, or None to clear it. Unknown facts stay blank or None.

    today, when given by a web save, refuses a future checked date. The store checks the
    calendar form only, so rereading old state never depends on the machine's clock.
    Saving never stamps a date or fills a bracket from current guidance.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise Invalid("night must be a Commander-night object, or null to clear it")
    unknown = set(value) - set(KEYS)
    if unknown:
        raise Invalid("Unknown Commander-night fields: " + ", ".join(sorted(map(str, unknown))))
    out = {"name": _text(value.get("name", ""), "name", 120),
           "venue": _text(value.get("venue", ""), "venue", 120)}
    if not out["name"]:
        raise Invalid("Give the Commander night a name")
    for key in ("target_bracket", "published_min", "published_max"):
        bracket = value.get(key)
        if bracket is not None and (type(bracket) is not int or not 1 <= bracket <= 5):
            raise Invalid(f"{key} must be a bracket from 1 to 5, or null when unknown")
        out[key] = bracket
    low, high = out["published_min"], out["published_max"]
    if (low is None) != (high is None):
        raise Invalid("Give both ends of the published bracket range, or leave both unknown")
    if low is not None and low > high:
        raise Invalid("The published bracket range must go from the lower bracket to the higher one")
    out["house_rules"] = _text(value.get("house_rules", ""), "house_rules", 1500, multiline=True)
    checked = _text(value.get("checked_on", ""), "checked_on", 10)
    if checked:
        try:
            if not DATE.fullmatch(checked):
                raise ValueError
            when = date.fromisoformat(checked)
        except ValueError:
            raise Invalid("checked_on must be a date in YYYY-MM-DD form, or blank when unknown") from None
        if today is not None and when > today:
            raise Invalid("The date checked cannot be in the future")
    out["checked_on"] = checked
    return out


def clear_reason(value):
    """A short, intentional explanation for clearing the saved notes."""
    reason = _text(value, "reason", 500, multiline=True)
    if not reason:
        raise Invalid("Give a reason for clearing the Commander-night notes")
    return reason
