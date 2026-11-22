"""Store rules for the evidence from a physical collection section count."""
from hashlib import sha256
import json
import re

from ..inventory.rules import TOKEN_ID_FIELDS, token_identity
from . import Invalid, Unavailable

MAX_COUNT = 9_007_199_254_740_991
SUMMARY = ("digest", "expected", "observed", "missing", "surplus", "extra", "mismatch_rows", "differences")
_ROW_TEXT = ("name", "set", "collector_number", "finish")
_ROW_KEYS = {*_ROW_TEXT, "expected", "observed"}
_OPTIONAL_TEXT = ("description", "location", "manualLabel")
_ROW_EXTRAS = {*_OPTIONAL_TEXT, "key", "token", "estimated"}
INVALID = "The collection audit counts are invalid."
CHANGED = "Someone recorded an audit for this section while it was open. Open the section again."
MIGRATE = "Collection audits need the database's migration 0031 (python -m decklab.db migrate on the PC)."
UNAVAILABLE = "The stored collection audit could not be read."
INDEPENDENT = "A collection audit needs an independent save."


class MissingSchema(Unavailable):
    """A count cannot be saved before migration 0031."""


def section_key(value):
    if not isinstance(value, str) or not value or len(value) > 200 or not value.isprintable():
        raise Invalid("The collection audit section is invalid.")
    return value


def expectation(value):
    if type(value) is not int or not 0 <= value < MAX_COUNT:
        raise Invalid("The collection audit revision is invalid.")
    return value


def _count(value):
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise Invalid(INVALID)
    return value


def _valid_text(value):
    return isinstance(value, str) and "\0" not in value


def token_key(row):
    """Identify the physical pair consistently in the section and its saved differences."""
    identity = json.dumps(token_identity(row), ensure_ascii=True, separators=(",", ":"))
    return "token-" + sha256(identity.encode()).hexdigest()


def _validate_identity(row):
    key = row.get("key")
    if "estimated" in row and type(row["estimated"]) is not bool:
        raise Invalid(INVALID)
    if "key" not in row and "token" not in row:
        return  # 0031 initially stored the display fields alone.
    if not _valid_text(key) or not key:
        raise Invalid(INVALID)
    if "token" not in row:
        if key != "|".join(row[field].lower() for field in _ROW_TEXT[1:]):
            raise Invalid(INVALID)
        return
    token = row["token"]
    if (not isinstance(token, dict) or token.keys() != set(TOKEN_ID_FIELDS)
            or not all(_valid_text(value) for value in token.values()) or key != token_key(token)
            or not token["front"] or token["set"] != row["set"] or token["finish"] != row["finish"]
            or token["front_collector_number"] != row["collector_number"]):
        raise Invalid(INVALID)


def identified_extra(differences):
    """Recognized unlisted copies are a subset of the separate extra total."""
    return sum(row["observed"] for row in differences if row["expected"] == 0 and "key" in row)


def validate(summary):
    """Check that the differences explain the totals, including unlisted extras."""
    if not isinstance(summary, dict) or summary.keys() != set(SUMMARY):
        raise Invalid(INVALID)
    digest = summary["digest"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise Invalid(INVALID)
    for key in SUMMARY[1:-1]:
        _count(summary[key])
    differences = summary["differences"]
    if not isinstance(differences, list) or len(differences) != summary["mismatch_rows"]:
        raise Invalid(INVALID)
    missing = surplus = listed_expected = 0
    keys = set()
    for row in differences:
        if not isinstance(row, dict) or row.keys() - _ROW_EXTRAS != _ROW_KEYS:
            raise Invalid(INVALID)
        labels = [*(row[key] for key in _ROW_TEXT), *(row.get(key, "") for key in _OPTIONAL_TEXT)]
        if not all(_valid_text(label) for label in labels) or not row["name"]:
            raise Invalid(INVALID)
        expected, observed = _count(row["expected"]), _count(row["observed"])
        if expected == observed:
            raise Invalid(INVALID)
        _validate_identity(row)
        if "key" in row:
            if row["key"] in keys:
                raise Invalid(INVALID)
            keys.add(row["key"])
            if expected == 0:
                continue
        listed_expected += expected
        missing += max(0, expected - observed)
        surplus += max(0, observed - expected)
    if (missing != summary["missing"] or surplus != summary["surplus"] or listed_expected > summary["expected"]
            or identified_extra(differences) > summary["extra"]
            or summary["expected"] - missing + surplus + summary["extra"] != summary["observed"]):
        raise Invalid(INVALID)
