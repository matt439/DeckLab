"""Member-only personal copies and stateless card needs; never home/departure/queue operations."""
import hashlib
import json
import tempfile
import threading
import zipfile
from datetime import datetime, timezone

from decklab.lib import decks, inventory, pool, spaces
from . import guard
from .carddata import _require_cards
from .common import ApiError, DATABASE_DOWN, Download

MAX_FILES = 10000
MAX_BYTES = 128 * 1024 * 1024
_downloads = threading.BoundedSemaphore(2)
REFUSAL = "That collection isn't public."


def own_space(requested=None):
    """Self-service only, even when a different member's collection is Public."""
    try:
        viewer = guard.viewer()
    except ApiError:
        raise ApiError(403, REFUSAL) from None
    space = (viewer or {}).get("space")
    if (not viewer or not space or space == spaces.HOME or viewer.get("id") != space
            or requested is not None and requested != space):
        raise ApiError(403, REFUSAL)
    guard.require_sees_inventory(space)
    return space


def download_view(space=None):
    """One read-only repeatable-read snapshot to a private, bounded temporary zip."""
    space = own_space(space)
    if not _downloads.acquire(blocking=False):
        raise ApiError(429, "Personal downloads are busy. Try again shortly.")
    stream = None
    held = True
    try:
        from decklab.db import space_export
        from decklab.db.conn import DbUnavailable
        try:
            files, _ = space_export.database_snapshot(space, personal=True)
        except DbUnavailable:
            raise ApiError(503, DATABASE_DOWN, reason="database") from None
        except (ValueError, OSError, UnicodeError):
            raise ApiError(503, "Your personal copy couldn't be built safely. Try again later.") from None
        # Empty sections remain explicit; the eight-column card format is unchanged.
        from decklab.lib.inventory import dice_rules, rules
        files = {**files}
        files.setdefault("locations.csv", rules.csv_bytes([], rules.LOCATION_FIELDS))
        files.setdefault("dice.csv", rules.csv_bytes([], dice_rules.DICE_FIELDS))
        if len(files) > MAX_FILES or sum(len(value) for value in files.values()) > MAX_BYTES:
            raise ApiError(413, "This space is too large for one page download. Ask its operator for a local personal copy.")
        now = datetime.now(timezone.utc)
        manifest = {"version": 1, "purpose": "personal-copy", "departure_export": False,
                    "space": space, "saved_at": now.isoformat(timespec="seconds"),
                    "files": {name: {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
                              for name, value in sorted(files.items())}}
        stream = tempfile.TemporaryFile(mode="w+b")
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in sorted(files.items()):
                rel = space_export._relative(name)
                if not (name in {"collection.csv", "tokens.csv", "dice.csv", "locations.csv", "loans.csv"}
                        or rel.parts[0] == "imports" or name.startswith(("decks/", "retired/decks/")) and name.endswith(".md")):
                    raise ApiError(503, "Your personal copy contains an unsupported section; nothing was downloaded.")
                _write_member_file(archive, name, value)
            _write_member_file(archive, "manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n")
            _write_member_file(archive, "PERSONAL-COPY.txt", "This is your personal card and deck-text copy, not a departure export.\n"
                             "It contains no sign-in configuration, wishlist, settings, audit or other spaces' records.\n"
                             "It may be out of date after the saved time in manifest.json. Keep it privately.\n")
        size = stream.tell()
        stream.seek(0)
        found = Download(stream, f"decklab-{space}-{now.date().isoformat()}-personal.zip", size,
                         release=_downloads.release)
        stream = None
        held = False
        return found
    finally:
        if stream is not None:
            stream.close()
        if held:
            _downloads.release()


def _write_member_file(archive, name, value):
    info = zipfile.ZipInfo(name)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, value)


def needed_view(space=None):
    """All own ordinary saved Planned decks together, with no prices, queue or external reads."""
    space = own_space(space)
    _require_cards()
    try:
        with inventory.pinned():
            inv = inventory.current()
            if inv.stale:
                raise inventory.Unavailable("No fresh inventory")
            return _needed(space)
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except (OSError, ValueError, inventory.StateError):
        raise ApiError(503, "Your decks' missing cards couldn't be counted safely. Try again later.") from None


def _needed(space):
    summaries = [row for row in decks.list_decks(only_space=space) if row.get("space", spaces.HOME) == space
                 and row.get("kind") in ("casual", "commander") and not row.get("trial")]
    summaries.sort(key=lambda row: (row.get("title", "").casefold(), row["id"]))
    chosen = [{key: row[key] for key in ("id", "title")} for row in summaries]
    if not chosen:
        return {"ready": True, "decks": [], "rows": []}
    if any(row.get("error") or "target" not in row.get("versions", []) for row in summaries):
        return {"ready": False, "decks": chosen, "rows": [],
                "reason": "Every saved deck needs a readable Planned list before this combined list can be counted."}
    supply = pool.load_pool(space)
    if supply.warnings or supply.unresolved:
        return {"ready": False, "decks": chosen, "rows": [], "reason": "Your collection needs checking before missing cards can be counted."}
    lists = {row["id"]: decks.load_deck(row["id"], "target") for row in summaries}
    excluded = set().union(*(pool.self_ids(row["id"]) for row in summaries))
    results = {deck_id: pool.compare(sections, supply, excluded, prices=False) for deck_id, sections in lists.items()}
    merged = {(deck_id, section): lines for deck_id, sections in lists.items() for section, lines in sections.items()}
    combined = pool.compare(merged, supply, excluded, prices=False)
    if combined.get("unresolved") or any(result.get("unresolved") for result in results.values()):
        return {"ready": False, "decks": chosen, "rows": [], "reason": "Some deck cards aren't recognized, so this list cannot be counted completely."}
    rows = []
    for row in combined["rows"]:
        if row["missing"] > 0:
            wanting = [{**deck, "need": next((part["need"] for part in results[deck["id"]]["rows"]
                                             if part["name"] == row["name"]), 0)} for deck in chosen]
            rows.append({"name": row["name"], "quantity": row["missing"], "decks": [deck for deck in wanting if deck["need"]]})
    return {"ready": True, "decks": chosen, "rows": sorted(rows, key=lambda row: row["name"].casefold())}
