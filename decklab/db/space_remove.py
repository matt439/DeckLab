"""Member-removal preview and pure mixed-record transformations.

The preview verifies a matching v2 export and enumerates exact row keys and
own-only Forge file hashes. space_apply handles its separately guarded audited
change and durable recovery journal.
"""
import copy

from decklab.db import space_export
from decklab.lib import spaces
from decklab.lib.state import Invalid, pods
from decklab.lib.state.play import REMOVED_DECK, is_removed_deck

APPLY_GATE = ("Apply requires a matching export, a cooperative Forge runtime and exclusive lifecycle/database locks; "
              "interrupted operations require journal recovery before another write.")
REMOVED = REMOVED_DECK
_TABLE_KEYS = {
    "space": ("space", ("id",)),
    "profiles": ("profile", ("id",)),
    "emails": ("profile_email", ("profile_id", "email")),
    "collection": ("collection_card", ("space_id", "set_code", "collector_number", "finish")),
    "tokens": ("token_card", ("id",)),
    "imports": ("collection_import", ("id",)),
    "decks": ("deck", ("id",)),
    "texts": ("deck_text", ("deck_id",)),
    "lines": ("deck_line", ("deck_id", "version", "section", "position")),
    "history": ("deck_revision", ("deck_id", "revision")),
    "aliases": ("deck_alias", ("alias_id",)),
    "wishlist": ("wishlist_entry", ("profile_id", "position")),
    "settings": ("profile_setting", ("profile_id", "key")),
    "visibility": ("visibility", ("owner", "thing")),
    "drafts": ("deck_draft", ("profile_id", "deck_id", "version")),
    "visit_days": ("ops.visit_day", ("profile_id", "day", "channel")),
    "visit_pages": ("ops.visit_page", ("profile_id", "day", "channel", "route", "deck_id")),
}


def _owner(side):
    if not isinstance(side, dict):
        raise ValueError("A related play record has a damaged deck snapshot")
    if is_removed_deck(side):
        return None             # cannot collide with a real member named "removed"
    try:
        return spaces.split_deck_id(side["id"])[0]
    except (KeyError, ValueError, TypeError):
        raise ValueError("A related play record has a damaged deck snapshot") from None


def transformed_record(space, row):
    """Proposed retained row, or None for deletion. Inputs are never mutated.

    The removed side keeps no id, list, player, mulligans or plan. Another
    space's side stays byte-for-byte. A removed recorder's notes and ownership
    are cleared, while date and outcome survive as facts of the retained game.
    A plan belongs to its deck; only its removed opponent is tombstoned.
    The guarded apply validates the shape through the tombstone-aware readers.
    """
    space_export.member_space(space)
    out = copy.deepcopy(row)
    content = out.get("content")
    if not isinstance(content, dict):
        raise ValueError("A related play record has damaged content")
    if row.get("kind") == "games":
        try:
            if pods.mode(content) == "pod":
                ids = pods.record_deck_ids(content)
                if row.get("deck_ids") != ids:
                    raise Invalid("The pod's recorded decks do not match its seats")
                # Every selected deck belongs to its recording space. External
                # seats have no independent record to retain after its removal.
                return None if content["space"] == space else out
        except Invalid:
            raise ValueError("A related pod game has damaged content or ownership") from None
        sides = content.get("sides")
        if not isinstance(sides, list) or len(sides) != 2:
            raise ValueError("A related game needs two recorded sides")
        owners = [_owner(side) for side in sides]
        if all(owner in (space, None) for owner in owners):
            return None
        content["sides"] = [copy.deepcopy(REMOVED) if owner == space else side
                            for owner, side in zip(owners, sides)]
        recorder = content.get("space")
        if recorder is None:
            recorder = "home" if "home" in owners else owners[0]
        if recorder == space:
            content["notes"] = ""
            content["space"] = ""       # no real space owns the removed recorder's result
        out["deck_ids"] = [side["id"] for side in content["sides"] if not is_removed_deck(side)]
    elif row.get("kind") == "sideboards":
        if _owner(content.get("deck")) == space:
            return None
        if _owner(content.get("opponent")) == space:
            content["opponent"] = copy.deepcopy(REMOVED)
        out["deck_ids"] = [side["id"] for side in (content["deck"], content["opponent"]) if not is_removed_deck(side)]
    else:
        raise ValueError("A related play record has an unknown kind")
    out["updated_by"] = "someone"
    return out


def row_plan(space, data):
    """Exact row actions and proposed retained mixed records for one scoped DB snapshot."""
    rows, retained = [], []
    for area, (table, keys) in _TABLE_KEYS.items():
        for row in data.get(area, []):
            rows.append({"table": table, "key": {key: row[key] for key in keys}, "action": "delete"})
    for row in data.get("imports", []):
        rows.append({"table": "collection_import_content", "key": {"import_id": row["id"]}, "action": "delete"})
    for row in data.get("play_records", []):
        after = transformed_record(space, row)
        rows.append({"table": "play_record", "key": {"kind": row["kind"], "id": row["id"]},
                     "action": "delete" if after is None else "redact"})
        if after is not None:
            retained.append(after)
    rows.sort(key=lambda row: (row["table"], space_export._json(row["key"])))
    return rows, retained


def preview(space, export_dir, expected_sha, *, dbname=None, results_dir=None):
    """Verify export then build a fresh matching plan, with no filesystem or DB writes."""
    space_export.matching_export(space, export_dir, expected_sha, dbname, results_dir)
    _, sha, forge, data = space_export.complete_snapshot(space, dbname, results_dir, details=True)
    if sha != expected_sha:
        raise ValueError("The member snapshot changed during the preview; export it again")
    rows, retained = row_plan(space, data)
    return {"space": space, "snapshot_sha256": sha, "rows": rows, "retained_records": retained,
            "maintenance": [{"table": "space_departure", "key": {"space_id": space}, "action": "insert"},
                            {"table": "inventory_revision", "action": "increment"},
                            {"table": "decks_revision", "action": "increment"}],
            "forge_files": [{"path": path, **info, "action": "delete"}
                            for path, info in forge["selected"].items()],
            "preserved_related_forge_files": forge["preserved_related"],
            "preserved_unknown_forge_files": forge["unknown"],
            "gates": [APPLY_GATE],
            "reminders": ["Remove this member's exact email address from Cloudflare Access's policy.",
                          "Remove this member's profile from decklab/config.json, then sync profiles."]}
