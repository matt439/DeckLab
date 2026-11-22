"""Store rules for the evidence from a physical collection section count."""
import re

from . import Invalid, Unavailable

MAX_COUNT = 9_007_199_254_740_991
SUMMARY = ("digest", "expected", "observed", "missing", "surplus", "extra", "mismatch_rows", "differences")
_ROW_TEXT = ("name", "set", "collector_number", "finish")
_ROW_KEYS = {*_ROW_TEXT, "expected", "observed"}
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
    for row in differences:
        if not isinstance(row, dict) or row.keys() - {"description"} != _ROW_KEYS:
            raise Invalid(INVALID)
        labels = [*(row[key] for key in _ROW_TEXT), row.get("description", "")]
        if any(not isinstance(label, str) or "\0" in label for label in labels) or not row["name"]:
            raise Invalid(INVALID)
        expected, observed = _count(row["expected"]), _count(row["observed"])
        if expected == observed:
            raise Invalid(INVALID)
        listed_expected += expected
        missing += max(0, expected - observed)
        surplus += max(0, observed - expected)
    if (missing != summary["missing"] or surplus != summary["surplus"] or listed_expected > summary["expected"]
            or summary["expected"] - missing + surplus + summary["extra"] != summary["observed"]):
        raise Invalid(INVALID)
