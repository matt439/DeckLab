"""One member's cards and exact deck texts, from one read-only database snapshot.

This is deliberately separate from export.inventory_files: that export reads all
spaces and home-only data. Here every data query is scoped before rendering. The
artifact holds collection.csv, tokens.csv (header-only for empty lists), imports/,
decks/<kind>/<slug>.md and retired/decks/<kind>/<slug>.md (the last saved text).

manifest.json binds those files to a deterministic, space-scoped database SHA.
The SHA also covers histories, aliases, wishlist, settings, switches and related
play records, without putting their contents in the artifact. It excludes global
revision counters and audit rows, so another space's unrelated save doesn't make
it stale. A v2 manifest also fingerprints own-only Forge artifacts; their raw
contents never enter the export. Removal remains a separate operation.
"""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from decklab.db import conn as db
from decklab.lib import config, profiles
from decklab.lib.inventory import rules

VERSION = 2
MANIFEST = "manifest.json"
# SQL fragments are fixed code, never caller-supplied identifiers. JSON keeps
# every column (including future metadata) in the fingerprint, with UTC times.
_QUERIES = {
    "space": "select to_jsonb(r) from space r where id = %s",
    "profiles": "select to_jsonb(r) from profile r where space_id = %s",
    "emails": "select to_jsonb(e) from profile_email e join profile p on p.id = e.profile_id where p.space_id = %s",
    "collection": "select to_jsonb(r) from collection_card r where space_id = %s",
    "tokens": "select to_jsonb(r) from token_card r where space_id = %s",
    "imports": "select to_jsonb(r) from collection_import r where space_id = %s",
    "decks": "select to_jsonb(r) from deck r where space_id = %s",
    "texts": "select to_jsonb(t) from deck_text t join deck d on d.id = t.deck_id where d.space_id = %s",
    "lines": "select to_jsonb(t) from deck_line t join deck d on d.id = t.deck_id where d.space_id = %s",
    "history": "select to_jsonb(r) from deck_revision r where split_part(deck_id, '/', 1) = %s",
    "aliases": "select to_jsonb(r) from deck_alias r where split_part(alias_id, '/', 1) = %s",
    "wishlist": "select to_jsonb(r) from wishlist_entry r where profile_id = %s",
    "settings": "select to_jsonb(r) from profile_setting r where profile_id = %s",
    "play_records": "select to_jsonb(r) from play_record r where content->>'space' = %s or exists "
                    "(select 1 from unnest(r.deck_ids) d where split_part(d, '/', 1) = %s)",
    "visit_days": "select to_jsonb(v) from ops.visit_day v where profile_id = %s",
    "visit_pages": "select to_jsonb(v) from ops.visit_page v where profile_id = %s",
}


def member_space(space):
    """Refuse home, malformed ids and path-like input before any database read."""
    if not profiles.valid_id(space) or space in profiles.RESERVED_SPACES | profiles.RESERVED_IDS:
        raise ValueError("space export needs a member space id, not home")
    return space


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _relative(rel):
    if not isinstance(rel, str):
        raise ValueError("the member export contains an unsafe file path")
    path = PurePosixPath(rel)
    parts = rel.split("/")
    if path.is_absolute() or not path.parts or any(
            p in ("", ".", "..") or p.endswith((".", " ")) or any(ord(ch) < 32 or ch in '\\:<>"|?*' for ch in p)
            or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p) for p in parts):
        raise ValueError("the member export contains an unsafe file path")
    return path


def _deck_path(space, deck_id, retired=False):
    pieces = deck_id.split("/")
    if len(pieces) != 3 or pieces[0] != space or pieces[1] not in ("casual", "commander"):
        raise ValueError("the member export contains an invalid deck id")
    return str(_relative(("retired/" if retired else "") + f"decks/{pieces[1]}/{pieces[2]}.md"))


def snapshot(c, space, *, details=False):
    """({relative path: bytes}, SHA) on the caller's read-only snapshot connection.

    The member must exist in the database. Never consult a cached inventory or
    fall back to source files when the database cannot be read.
    """
    member_space(space)
    if not c.execute("select 1 from space where id = %s", (space,)).fetchone():
        raise ValueError(f"No member space {space!r} in the database")
    data = {key: sorted((r[0] for r in c.execute(query, (space, space) if key == "play_records" else (space,))), key=_json)
            for key, query in _QUERIES.items()}
    if c.execute("select to_regclass('public.visibility') is not null").fetchone()[0]:
        data["visibility"] = sorted((r[0] for r in c.execute(
            "select to_jsonb(r) from visibility r where owner = %s "
            "and thing in ('collection', 'decks', 'games')", (space,))), key=_json)
    else:
        data["visibility"] = []
    cards = [{("set" if key == "set_code" else key): value for key, value in row.items()
              if key != "space_id"} for row in data["collection"]]
    cards.sort(key=rules.sort_key)
    # Storage locations (E8-S22, migration 0016) stay in the JSON rows; the CSV keeps its eight
    # columns, and the rows with one are also written as locations.csv, as the inventory export does.
    places = [{key: card[key] for key in rules.LOCATION_FIELDS} for card in cards if card.get("location")]
    cards = [{key: card[key] for key in rules.FIELDS} for card in cards]
    tokens = [{("set" if key == "set_code" else key): value for key, value in row.items()
               if key not in ("id", "space_id", "position")}
              for row in sorted(data["tokens"], key=lambda r: (r["position"], r["id"]))]
    files = {"collection.csv": rules.csv_bytes(cards, rules.FIELDS),
             "tokens.csv": rules.csv_bytes(tokens, rules.TOKEN_FIELDS)}
    if places:
        files["locations.csv"] = rules.csv_bytes(places, rules.LOCATION_FIELDS)
    imports = []
    for name, content in c.execute(
            "select i.file_name, c.content from collection_import i "
            "join collection_import_content c on c.import_id = i.id where i.space_id = %s "
            "order by i.file_name", (space,)):
        rel = str(_relative(f"imports/{name}"))
        content = bytes(content)
        files[rel] = content
        imports.append({"file": name, "sha256": _sha(content)})
    data["import_contents"] = imports
    if len(imports) != len(data["imports"]):
        raise ValueError("A member raw import has no saved content; export refused")
    texts = {r["deck_id"]: r["text"] for r in data["texts"]}
    if texts.keys() != {r["id"] for r in data["decks"]}:
        raise ValueError("A member deck has no saved text; export refused")
    for deck_id, text in texts.items():
        files[_deck_path(space, deck_id)] = text.encode("utf-8")
    # Aliases are old names of a current/retired deck, not separate retired decks.
    aliases = {r["alias_id"] for r in data["aliases"]}
    retired = {}
    for row in sorted(data["history"], key=lambda r: r["revision"]):
        if row["deck_id"] not in texts and row["deck_id"] not in aliases and row["text"] is not None:
            retired[row["deck_id"]] = row["text"]
    for deck_id, text in retired.items():
        files[_deck_path(space, deck_id, retired=True)] = text.encode("utf-8")
    if len({path.casefold() for path in files}) != len(files):
        raise ValueError("The member export has file names that collide on Windows")
    fingerprint = {"version": VERSION, "space": space, "data": data,
                   "files": {rel: _sha(content) for rel, content in sorted(files.items())}}
    found = dict(sorted(files.items())), _sha(_json(fingerprint))
    if details:
        from decklab.db import space_forge
        # Transient hashes affect only which Forge files are preserved. Never
        # put another space's hashes, cards or identifiers in the member export.
        data["_other_list_hashes"] = space_forge.other_list_hashes(c, space)
    return (*found, data) if details else found


def database_snapshot(space, dbname=None, *, details=False):
    """Read one repeatable-read, read-only snapshot; no DB write or operational log."""
    member_space(space)
    from psycopg import IsolationLevel
    with db.connect("ro", dbname=dbname) as c:
        c.isolation_level = IsolationLevel.REPEATABLE_READ
        c.read_only = True
        c.execute("set local timezone = 'UTC'")
        found = snapshot(c, space, details=details)
        c.rollback()
    return found


def complete_snapshot(space, dbname=None, results_dir=None, *, details=False, conn=None):
    """Bind the scoped DB snapshot and stable own-only Forge file hashes.

    This is read-only. Apply rechecks under an exclusive lifecycle claim;
    merely holding this fingerprint does not stop a queued Forge writer.
    """
    from decklab.db import space_forge
    from decklab.lib.forge.common import _results_dir
    found = snapshot(conn, space, details=True) if conn is not None else database_snapshot(space, dbname, details=True)
    files, db_sha = found[:2]
    _, forge = space_forge.snapshot(space, _results_dir(results_dir), other_hashes=found[2].get("_other_list_hashes", ()))
    sha = _sha(_json({"version": VERSION, "space": space, "database_sha256": db_sha,
                      "forge_files": forge["selected"]}))
    return (files, sha, forge, found[2]) if details else (files, sha, forge)


def _destination(folder):
    folder = Path(folder)
    resolved = folder.resolve()
    if resolved.is_relative_to(Path(config.REPO).resolve()):
        raise ValueError("Export into a new scratch folder outside the source repository")
    if folder.exists():
        raise ValueError("The export folder already exists; choose a new folder")
    return folder


def export_to(space, folder, dbname=None, results_dir=None):
    """Write a new export with manifest last. Never overwrite or remove an artifact."""
    member_space(space)
    folder = _destination(folder)
    files, sha, forge = complete_snapshot(space, dbname, results_dir)
    manifest = {"version": VERSION, "space": space, "snapshot_sha256": sha,
                "scope": "member-database-and-card-files", "forge_results_included": False,
                "forge_files": forge["selected"],
                "files": {rel: {"sha256": _sha(content), "bytes": len(content)}
                          for rel, content in files.items()}}
    folder.mkdir(parents=True, exist_ok=False)
    for rel, content in files.items():
        path = folder.joinpath(*_relative(rel).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
    with (folder / MANIFEST).open("xb") as stream:
        stream.write(_json(manifest))
    return manifest


def matching_export(space, folder, expected_sha, dbname=None, results_dir=None):
    """Verify this artifact and a fresh scoped snapshot still match expected_sha.

    This is a guard for a later removal preview, not permission to remove data.
    It refuses incomplete, changed or extra files, symlinks and wrong-space exports.
    """
    member_space(space)
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("A full snapshot SHA is required")
    folder = Path(folder)
    try:
        if folder.is_symlink() or folder.is_junction() or (folder / MANIFEST).is_symlink():
            raise ValueError("The export contains a linked path")
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("The export manifest is invalid")
        if manifest.get("version") != VERSION or manifest.get("space") != space \
                or manifest.get("snapshot_sha256") != expected_sha:
            raise ValueError("The export does not match this member snapshot")
        expected = manifest["files"]
        if not isinstance(expected, dict):
            raise ValueError("The export manifest is invalid")
        actual = set()
        for path in folder.rglob("*"):
            if path.is_symlink() or path.is_junction():
                raise ValueError("The export contains a linked path")
            if path.is_file():
                actual.add(path.relative_to(folder).as_posix())
        if actual != set(expected) | {MANIFEST}:
            raise ValueError("The export files no longer match the manifest")
        for rel, info in expected.items():
            content = folder.joinpath(*_relative(rel).parts).read_bytes()
            if info != {"sha256": _sha(content), "bytes": len(content)}:
                raise ValueError("The export files no longer match the manifest")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as e:
        raise ValueError("A complete matching member export is required") from e
    files, current, forge = complete_snapshot(space, dbname, results_dir)
    if current != expected_sha or set(files) != set(expected) \
            or manifest.get("forge_files") != forge["selected"] \
            or any(info != {"sha256": _sha(files[rel]), "bytes": len(files[rel])}
                   for rel, info in expected.items()):
        raise ValueError("The member snapshot has changed; export it again")
    return manifest
