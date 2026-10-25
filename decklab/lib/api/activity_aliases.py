"""Permissioned audit projections for durable old deck links."""
from decklab.lib import spaces


def _record(value):
    return value if isinstance(value, dict) else {}


def deck_space(deck_id):
    """A recorded deck's space, with no home fallback for malformed ids."""
    try:
        return spaces.split_deck_id(deck_id)[0]
    except ValueError:
        return None


def _identity(value):
    if not isinstance(value, str) or not 3 <= len(value) <= 200:
        return None
    try:
        space, kind, slug = spaces.split_deck_id(value)
    except ValueError:
        return None
    if (kind not in ("casual", "commander") or not slug or slug.startswith(".")
            or any(char in slug for char in "/\\:") or any(ord(char) < 32 or ord(char) == 127 for char in slug)):
        return None
    return space, kind


def row(raw, allowed_spaces):
    """One alias row's exact id fields, only when both endpoints have one visible owner.

    Never default a malformed or incomplete alias to the home space. The audit
    table carries no kit or captured text; unrelated keys never reach the page.
    """
    if any(raw.get(key) is not None and not isinstance(raw[key], dict) for key in ("before", "after")):
        return None
    before, after = (_record(raw.get(key)) for key in ("before", "after"))
    records = [item for item in (before, after) if item]
    if not records:
        return None
    identities = [_identity(item.get(key)) for item in records for key in ("alias_id", "deck_id")]
    if any(value is None for value in identities) or len(set(identities)) != 1:
        return None
    if allowed_spaces is not None and identities[0][0] not in allowed_spaces:
        return None
    current = after or before
    verb = {"INSERT": "Kept", "DELETE": "Removed"}.get(raw.get("op"), "Updated")
    summary = f"{verb} old deck link {current['alias_id']} to {current['deck_id']}"
    return {"table": "deck_alias", "op": raw.get("op"), "summary": summary,
            "before": {key: before[key] for key in ("alias_id", "deck_id") if key in before} or None,
            "after": {key: after[key] for key in ("alias_id", "deck_id") if key in after} or None}


def unchanged_header(row):
    """Only a same-id save can be a text/table save rather than a rename."""
    return _record(row.get("before")).get("id") == _record(row.get("after")).get("id")


def rename_words(before, after, before_title, after_title):
    if before_title == after_title and before.get("id") != after.get("id"):
        return f"renamed the id of {after_title} from {before.get('id')} to {after.get('id')}"
    return f"renamed {before_title} to {after_title}"
