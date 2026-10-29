"""Guarded, audited member removal and journal recovery.

Lock order: runtime adoption check, exclusive Forge lifecycle claim, inventory
advisory transaction lock, then fixed-order table locks. Every affected row and
file is re-read under those locks. Quarantine is durable before SQL changes;
the immutable audit change id, not an in-memory success flag, decides recovery.
This is application/process-crash recovery, not a distributed hardware or
power-loss transaction across the database and filesystem.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from decklab.db import conn as db, space_export, space_journal, space_remove

LOCK_TABLES = tuple(sorted({
    "public.space", "public.profile", "public.profile_email", "public.collection_card",
    "public.collection_import", "public.collection_import_content", "public.token_card",
    "public.deck", "public.deck_text", "public.deck_line", "public.deck_revision", "public.deck_alias",
    "public.wishlist_entry", "public.profile_setting", "public.play_record", "public.visibility",
    "public.product", "public.product_item", "public.inventory_revision", "public.decks_revision",
    "ops.visit_day", "ops.visit_page", "public.space_departure", "public.deck_draft",
}))
# Locked only once their migration is applied (deck_draft: 0018); a database without one has no rows.
OPTIONAL_TABLES = frozenset({"public.deck_draft"})
DELETE_ORDER = ("ops.visit_page", "ops.visit_day", "deck_draft", "profile_email", "collection_import_content",
                "collection_import", "collection_card", "token_card", "deck_line", "deck_text",
                "deck_revision", "deck_alias", "deck", "wishlist_entry", "profile_setting",
                "visibility", "profile", "space")
OPTIONS = "-c lock_timeout=2000 -c statement_timeout=15000"


def _runtime(root):
    from decklab.db import space_runtime
    space_runtime.require_ready(root)


def _database(dbname):
    settings = db.settings()
    return {"host": str(settings["host"]), "port": int(settings["port"]), "name": dbname or settings["name"]}


def _locks(c):
    from psycopg import sql
    c.execute("select pg_advisory_xact_lock(hashtext(%s))", ("inventory",))
    for table in LOCK_TABLES:
        schema, name = table.split(".")
        if table in OPTIONAL_TABLES and not c.execute("select to_regclass(%s) is not null", (table,)).fetchone()[0]:
            continue
        c.execute(sql.SQL("lock table {}.{} in share row exclusive mode").format(
            sql.Identifier(schema), sql.Identifier(name)))
    c.execute("set local timezone = 'UTC'")


def _locked_snapshot(c, space, root):
    return space_export.complete_snapshot(space, results_dir=root, details=True, conn=c)


def _matching_artifact(space, folder, expected_sha, files, sha, forge):
    """Recheck the artifact itself while the DB/Forge snapshot is locked."""
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("A full exported snapshot SHA is required")
    folder = space_journal._ordinary(Path(folder).absolute())
    try:
        manifest = json.loads((folder / space_export.MANIFEST).read_bytes())
        wanted = {rel: {"sha256": space_export._sha(content), "bytes": len(content)}
                  for rel, content in files.items()}
        if not isinstance(manifest, dict) or manifest.get("version") != space_export.VERSION \
                or manifest.get("space") != space or manifest.get("snapshot_sha256") != expected_sha \
                or expected_sha != sha or manifest.get("files") != wanted \
                or manifest.get("forge_files") != forge["selected"]:
            raise ValueError("The member snapshot changed or its export does not match; export it again")
        actual = set()
        for path in folder.rglob("*"):
            space_journal._ordinary(path)
            if path.is_file():
                actual.add(path.relative_to(folder).as_posix())
        if actual != set(files) | {space_export.MANIFEST}:
            raise ValueError("The member export files no longer match its manifest")
        for rel, content in files.items():
            path = space_journal._ordinary(folder.joinpath(*space_export._relative(rel).parts))
            if path.read_bytes() != content:
                raise ValueError("The member export files no longer match its manifest")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("A complete matching member export is required") from exc


def _delete_rows(cur, rows):
    from psycopg import sql
    for table in DELETE_ORDER:
        selected = [row for row in rows if row["table"] == table and row["action"] == "delete"]
        if not selected:
            continue
        schema, name = table.split(".") if "." in table else ("public", table)
        keys = tuple(selected[0]["key"])
        statement = sql.SQL("delete from {}.{} where {}").format(
            sql.Identifier(schema), sql.Identifier(name),
            sql.SQL(" and ").join(sql.SQL("{} = %s").format(sql.Identifier(key)) for key in keys))
        cur.executemany(statement, [tuple(row["key"][key] for key in keys) for row in selected])


def _write_records(cur, data, actor):
    from psycopg.types.json import Jsonb
    from decklab.lib.state import rules
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    for row in data["play_records"]:
        retained = space_remove.transformed_record(data["space"][0]["id"], row)
        if retained is None:
            cur.execute("delete from play_record where kind = %s and id = %s", (row["kind"], row["id"]))
            continue
        record = {**retained["content"], "version": 1, "kind": row["kind"], "id": row["id"],
                  "revision": row["revision"] + 1, "created_on": row["created_on"], "updated_on": now,
                  "updated_by": actor.name}
        header, content, deck_ids = rules.split_record(row["kind"], record)
        cur.execute("update play_record set revision = %s, updated_on = %s, updated_by = %s, "
                    "deck_ids = %s, content = %s where kind = %s and id = %s",
                    (header["revision"], header["updated_on"], header["updated_by"], deck_ids, Jsonb(content),
                     row["kind"], row["id"]))


def _mutate(cur, data, rows, actor, operation, change_id):
    _write_records(cur, data, actor)
    _delete_rows(cur, rows)
    cur.execute("insert into space_departure (space_id, operation, change_set_id) values (%s,%s,%s)",
                (data["space"][0]["id"], operation, change_id))
    # Existing processes cache by these counters. A space's removal must change
    # both even when its collection or current deck list happened to be empty.
    for table in ("inventory_revision", "decks_revision"):
        cur.execute(f"update {table} set revision = revision + 1")
        if cur.rowcount != 1:
            raise ValueError("The database has no imported revision counters; removal refused")


def _outcome(c, journal):
    row = c.execute("select actor, source, message from audit.change_set where id = %s",
                    (journal["change_set_id"],)).fetchone()
    if row is None:
        if c.execute("select 1 from space_departure where space_id = %s", (journal["space"],)).fetchone():
            raise ValueError("A departure marker has no matching removal audit; recovery refused")
        return False
    if row[0] != journal["actor"] or row[1] != "cli" \
            or hashlib.sha256(row[2].encode()).hexdigest() != journal["message_sha256"] \
            or not row[2].endswith(f"Member removal operation: {journal['operation']}"):
        raise ValueError("The removal audit identity does not match; keep the quarantine for recovery")
    marker = c.execute("select operation::text, change_set_id from space_departure where space_id = %s",
                       (journal["space"],)).fetchone()
    if marker != (journal["operation"], journal["change_set_id"]):
        raise ValueError("The departure marker differs from its removal audit; recovery refused")
    return True


def _recover_locked(claim, operation, *, dbname=None, fault=None):
    from decklab.lib.forge import lifecycle
    journal = space_journal.load(claim, operation)
    if journal["database"] != _database(dbname):
        raise ValueError("The journal belongs to a different database; recovery refused")
    with db.connect("owner", dbname=dbname, autocommit=True, options=OPTIONS) as c:
        from psycopg import IsolationLevel
        c.isolation_level = IsolationLevel.READ_COMMITTED
        with c.transaction():
            _locks(c)
            committed = _outcome(c, journal)
    if journal["state"] == ("rolled_back" if committed else "committed"):
        raise ValueError("The journal state contradicts its database outcome; keep all files for recovery")
    if not committed and journal["space"] in lifecycle._departed(claim):
        raise ValueError("The departed marker contradicts an uncommitted removal; recovery refused")
    if operation in space_journal.pending(claim):
        if committed:
            space_journal.finish(claim, journal, fault=fault)
        else:
            space_journal.restore(claim, journal, fault=fault)
    elif journal["state"] != ("committed" if committed else "rolled_back"):
        raise ValueError("The completed journal differs from its database outcome; recovery refused")
    elif committed:
        space_journal.finish(claim, journal, fault=fault)
    return {"operation": operation, "space": journal["space"],
            "state": "committed" if committed else "rolled_back", "files": len(journal["entries"])}


def recover(operation, *, dbname=None, results_dir=None, fault=None):
    """Resolve a pending journal only after querying its exact audited outcome."""
    from decklab.lib.forge import lifecycle
    space_journal._operation(operation)
    root = lifecycle.root_path(results_dir)
    _runtime(root)
    with lifecycle.maintenance(root) as claim:
        _runtime(root)
        return _recover_locked(claim, operation, dbname=dbname, fault=fault)


def apply(space, export_dir, expected_sha, actor, message, reason, *, dbname=None, results_dir=None, fault=None):
    """Remove one member in one audited DB change, with recoverable file staging.

    fault is a disposable-test hook; BaseException simulates process death and
    deliberately leaves the durable pending journal for a separate recovery.
    """
    from decklab.lib.forge import lifecycle
    space_export.member_space(space)
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("A full exported snapshot SHA is required")
    if not isinstance(message, str) or not message.strip() or not isinstance(reason, str) or not reason.strip():
        raise ValueError("Removal needs a non-blank message and reason")
    root = lifecycle.root_path(results_dir)
    _runtime(root)
    operation = str(uuid.uuid4())
    audit_message = f"{message.strip()}\nMember removal operation: {operation}"
    journal, rows = None, []
    with lifecycle.maintenance(root) as claim:
        _runtime(root)
        if space_journal.pending(claim):
            raise ValueError("A removal needs recovery before another removal can start")
        lifecycle.check_decks(claim, [f"{space}/casual/member-removal"])
        try:
            with db.connect("owner", dbname=dbname, autocommit=True, options=OPTIONS) as c:
                from psycopg import IsolationLevel
                c.isolation_level = IsolationLevel.READ_COMMITTED
                with db.change(actor.id or "claude", "cli", audit_message, reason=reason.strip(), conn=c) as (cur, change_id):
                    _locks(c)
                    files, sha, forge, data = _locked_snapshot(c, space, root)
                    _matching_artifact(space, export_dir, expected_sha, files, sha, forge)
                    rows, _ = space_remove.row_plan(space, data)
                    entries = [{"path": path, **info} for path, info in forge["selected"].items()]
                    journal = space_journal.prepare(claim, operation, space, _database(dbname), change_id,
                                actor.id or "claude", hashlib.sha256(audit_message.encode()).hexdigest(), sha, entries)
                    if fault:
                        fault("prepared", None)
                    space_journal.stage(claim, journal, fault=fault)
                    _mutate(cur, data, rows, actor, operation, change_id)
                    if fault:
                        fault("sql_done", None)
                if fault:
                    fault("committed", None)
            space_journal.finish(claim, journal, fault=fault)
        except Exception as exc:
            # A failed COMMIT may have reached PostgreSQL. Never infer rollback
            # from the exception: query the immutable audit identity afresh.
            if operation in space_journal.pending(claim):
                try:
                    recovered = _recover_locked(claim, operation, dbname=dbname)
                except Exception as recovery:
                    raise ValueError(f"Removal outcome needs recovery for operation {operation}; "
                                     "the pending journal and quarantined files were kept") from recovery
                if recovered["state"] == "committed":
                    return dict(recovered, rows=len(rows), recovered=True)
            raise exc
    return {"operation": operation, "space": space, "state": "committed", "rows": len(rows),
            "files": len(journal["entries"]), "recovered": False}
