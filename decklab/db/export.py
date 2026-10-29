"""The database as plain files: each table in TABLES written as CSV into the export repo
(C:\\VSProjects\\DeckLabData unless config.json says otherwise), committed, and pushed when the
repo has a remote called origin. It's the readable, diffable history beside the pg_dump
backups: git shows what changed from night to night, and the files open without PostgreSQL.

Each table goes to tables/<schema>.<table>.csv: UTF-8 without a byte-order mark, LF line
endings, a header row, rows sorted by the table's order-by columns, and every value as
PostgreSQL writes it as text (timestamps in UTC, so the files don't change with the PC's time
zone). NULL is an empty field. A CSV in tables/ for a table no longer listed is deleted.

The wishlists are also written as wishlists/<profile>.json, in the format the repo's
magic/wishlists/*.json files had before phase 2 moved them into the database, so they read
(and diff) as they always did. That folder is rebuilt at each export: one file for each
profile with at least one card, and no file for one without.

The inventory (phase 3, migration 0004) is also written as magic/, the files the repo's magic/
folder held before the database: collection.csv, tokens.csv, watchlist.csv, products/ (with
status.csv), orders/ (payloads in their folders, records/), people/<id>/ and each space's raw
imports/, byte for byte as Deck Lab wrote them (inventory/files.render, from the database's
snapshot read in the same transaction as the tables), and (phase 4, migration 0006, once the
decks are imported) every space's deck files, accessories.csv and its pictures, LF and byte for
byte (deck_parts). That folder is rebuilt at each export:
a file the database no longer has (a payload a receipt moved to received/, say) is deleted, and
so is a folder left empty. `python -m decklab.db inventory export DIR` writes the same files
into any folder, for reading or for going back to the files (a rollback). Until the inventory
is imported, magic/ is left as it is.

Later phases add tables (and today's CSV and Markdown formats): add a line to TABLES.
"""
import csv
import io
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from decklab.db import backup, conn as db

# (schema.table, the columns its rows are sorted by). The order-by columns must make each
# row's place unique, so an export of unchanged data is byte-for-byte the same.
TABLES = [
    ("public.space", ("id",)),
    ("public.profile", ("position", "id")),
    ("public.profile_email", ("profile_id", "email")),
    ("audit.change_set", ("id",)),
    ("public.wishlist_entry", ("profile_id", "position")),
    ("public.profile_setting", ("profile_id", "key")),
    ("public.simulation_mode", ("id",)),
    ("public.play_record", ("kind", "id")),
    ("public.packing_tick", ("id",)),
    ("public.commander_night", ("id",)),
    ("public.visibility", ("owner", "thing")),
    ("public.space_departure", ("space_id",)),
    ("public.field_policy", ("format",)),
    # Migration 0004's: the inventory. collection_import_content (whole files) isn't a CSV: the
    # raw imports are under magic/ instead.
    ("public.inventory_revision", ("id",)),
    ("public.collection_card", ("space_id", "set_code", "collector_number", "finish")),
    ("public.collection_import", ("id",)),
    ("public.token_card", ("space_id", "position", "id")),
    ("public.product", ("stem",)),
    ("public.product_item", ("product_stem", "position")),
    ("public.product_status", ("position", "file")),
    ("public.purchase_order", ("id",)),
    ("public.order_component", ("order_id", "position", "id")),
    ("public.order_card_item", ("order_id", "component_id", "position")),
    ("public.order_token_item", ("order_id", "component_id", "position")),
    ("public.watchlist_item", ("position", "id")),
    # Migration 0006's: the decks and accessories. The texts now (deck_text), the pictures
    # (accessory_image) and the rows derived from the texts (deck_line) aren't CSVs: the deck
    # files, accessories.csv and its pictures are under magic/ instead. Every deck's history is
    # (deck_revision, its texts included, since phase 5), so the off-PC copy holds it too.
    ("public.decks_revision", ("id",)),
    ("public.deck", ("id",)),
    ("public.deck_revision", ("deck_id", "revision")),
    ("public.deck_alias", ("alias_id",)),
    ("public.accessory", ("id",)),
]
DECK_TABLES = {"public.decks_revision", "public.deck", "public.deck_revision", "public.deck_alias", "public.accessory"}
INVENTORY_TABLES = {name for name, _ in TABLES[TABLES.index(("public.inventory_revision", ("id",))):]} - DECK_TABLES
# Tables a database not yet migrated may lack (0003, 0004, 0006, 0010-0013 and 0017). Until it's
# migrated they're skipped, a CSV already written for one is kept and the wishlists (or magic)
# folder is left as it is (without 0006 no deck file is exported), so the nightly export still
# works between updating the code and running migrate.
UNTIL_MIGRATED = {"public.wishlist_entry", "public.profile_setting", "public.simulation_mode",
                  "public.play_record", "public.packing_tick", "public.commander_night", "public.visibility",
                  "public.space_departure", "public.field_policy"} | INVENTORY_TABLES | DECK_TABLES
MAGIC = "magic"                     # the export repo's folder of inventory files

README = """# Deck Lab data export

Deck Lab's PostgreSQL database, written out as CSV by `python -m decklab.db export`
(the nightly task in the TradingCardCollection repo runs it). Each commit is one export;
git's history shows what changed between them.

- `tables/<schema>.<table>.csv`: one file per table. UTF-8, LF line endings, a header row,
  rows sorted by the table's key, values as PostgreSQL writes them as text (times in UTC).
  An empty field is NULL.
- `wishlists/<profile>.json`: each profile's wishlist (only profiles with at least one card),
  in the format the TradingCardCollection repo's `magic/wishlists/<profile>.json` files had:
  `{"version": 1, "entries": [...]}`, the cards in list order, `set` and `number` empty for
  no particular printing.
- `magic/`: the inventory (collections, tokens, raw imports, products, orders, the watchlist)
  as the files the TradingCardCollection repo's `magic/` folder held before the database,
  byte for byte in their formats: `collection.csv`, `tokens.csv`, `watchlist.csv`,
  `products/<stem>.csv` and `products/status.csv`, `orders/` (records in `orders/records/`),
  and `people/<id>/` for each person's space; and the decks the same way: `decks/<kind>/<slug>.md`
  (a person's under `people/<id>/decks/`), `accessories.csv` and its pictures in
  `accessories/images/`. Every deck's earlier revisions, texts included, are in
  `tables/public.deck_revision.csv`. Former deck IDs and their current (or retired) targets
  are retained in `tables/public.deck_alias.csv`, so old links and history keep their identity.
  The household's dated Commander-night notes and their revision (also after clearing) are
  retained in `tables/public.commander_night.csv`.
  Public switches and their audit metadata are in `tables/public.visibility.csv`;
  an absent owner/thing row means Private.
  Departed member IDs and their removal operation/change identity are retained in
  `tables/public.space_departure.csv` to refuse stale writes; it holds no member contents.

Don't edit these files: the next export overwrites them. The database (and its pg_dump
backups on the NAS) is the source; this repo is a readable copy.
"""

# Git stores and checks out every file byte for byte, whatever core.autocrlf says, so the CSVs
# stay LF in any clone and an unchanged export never looks changed.
GITATTRIBUTES = "* -text\n"

GIT_TIMEOUT = 300                 # seconds for one git command (a push over a slow line)
_SPAWN = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def table_csv(c, name, order_by):
    """One table as CSV bytes (see the module docstring). c: a connection whose time zone is UTC."""
    from psycopg import sql
    schema, table = name.split(".", 1)
    columns = [r[0] for r in c.execute(
        "select column_name from information_schema.columns where table_schema = %s and table_name = %s "
        "order by ordinal_position", (schema, table)).fetchall()]
    if not columns:
        raise ValueError(f"the export lists {name}, but the database has no such table")
    query = sql.SQL("select {} from {}.{} order by {}").format(
        sql.SQL(", ").join(sql.SQL("{}::text").format(sql.Identifier(col)) for col in columns),
        sql.Identifier(schema), sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(col) for col in order_by))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in c.execute(query):
        writer.writerow("" if v is None else v for v in row)
    return out.getvalue().encode("utf-8")


def wishlist_files(c):
    """Every profile's wishlist as the bytes of its old repo file ({profile id: bytes}), from
    one query on c: {"version": 1, "entries": [...]} with indent 2, non-ASCII kept, a trailing
    newline, the entries in list order and "" for no printing. Profiles with no cards have
    none."""
    entries = {}
    for pid, name, set_code, number, notes, source in c.execute(
            "select profile_id, name, set_code, collector_number, notes, source from public.wishlist_entry "
            "order by profile_id, position"):
        entries.setdefault(pid, []).append({"name": name, "set": set_code or "", "number": number or "",
                                            "notes": notes, "source": source})
    return {pid: (json.dumps({"version": 1, "entries": rows}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            for pid, rows in entries.items()}


def inventory_files(c):
    """The inventory as today's files ({repo-relative path under magic/: bytes}), from the
    database's snapshot read on c (in c's transaction, so it agrees with whatever else c reads):
    every source inventory/files.render gives, plus each space's raw imports from
    collection_import_content, and once the decks are in the database (migration 0006 and their
    import: a decks_revision row) every deck file, accessories.csv and its pictures, byte for
    byte as Deck Lab writes them (deck_parts). None when the inventory hasn't been imported."""
    from decklab.lib.inventory import files, paths
    from decklab.lib.inventory.pg import NotImported, PgInventory
    try:
        inv = PgInventory().load(conn=c)
    except NotImported:
        return None
    out = files.render(inv)
    for space, name, content in c.execute(
            "select i.space_id, i.file_name, c.content from collection_import i "
            "join collection_import_content c on c.import_id = i.id order by i.space_id, i.file_name"):
        out[f"{paths.imports_dir(space)}/{name}"] = bytes(content)
    out.update(deck_parts(c, inv) or {})
    return dict(sorted(out.items()))


def deck_parts(c, inv=None):
    """Every deck file, accessories.csv and its pictures as files ({path: bytes}) from the
    database on c (in c's transaction), or None while it doesn't hold the decks (no 0006 tables,
    or never imported: the working tree's files are never exported in their place). inv: the
    snapshot already read on c."""
    from decklab.lib.inventory import files, paths, pg_decks
    from decklab.lib.inventory.pg import PgInventory
    if pg_decks.decks_key(c, None) is None:
        return None
    inv = inv if inv is not None else PgInventory().load(conn=c)
    out = {rel: data for rel, data in files.render(inv, decks=True).items() if paths.is_deck_part(rel)}
    for name, content in c.execute("select file_name, content from accessory_image order by file_name"):
        out[paths.image(name)] = bytes(content)
    return out


def write_inventory(folder, files):
    """Make folder hold exactly files ({path under magic/: bytes}, as inventory_files gives):
    each written only when its bytes differ, every other file under folder deleted, and the
    folders left empty removed. folder is the magic/ folder itself."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    wanted = set()
    for rel, data in files.items():
        parts = rel.split("/")
        if parts[0] != MAGIC or len(parts) < 2 or any(p in ("", ".", "..") for p in parts):
            raise ValueError(f"{rel} isn't a path under {MAGIC}/")
        path = folder.joinpath(*parts[1:])
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_changed(path, data)
        wanted.add(path.resolve())
    for path in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_file() and path.resolve() not in wanted:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def write_tables(repo, dbname=None):
    """Write every table in TABLES into repo/tables, each wishlist into repo/wishlists and the
    inventory's files into repo/magic (only files whose bytes changed), delete the files there
    for tables no longer listed, wishlists no longer holding any card and inventory files the
    database no longer has, and write README.md when it isn't this module's.
    Returns the CSVs' total size in bytes. A table in UNTIL_MIGRATED that the database doesn't
    have yet is skipped (its file, if any, kept)."""
    repo = Path(repo)
    folder = repo / "tables"
    folder.mkdir(parents=True, exist_ok=True)
    from psycopg import IsolationLevel
    outputs = {}
    # Every table is read in one read-only snapshot, so the files agree with each other (no
    # profile_email row for a profile a write in between removed), as backup.dump does.
    with db.connect("ro", dbname=dbname) as c:
        c.isolation_level = IsolationLevel.REPEATABLE_READ
        c.read_only = True
        c.execute("set local timezone = 'UTC'")
        missing = {name for name in UNTIL_MIGRATED
                   if c.execute("select to_regclass(%s) is null", (name,)).fetchone()[0]}
        for name, order_by in TABLES:
            if name in missing:
                old = folder / f"{name}.csv"
                if old.is_file():
                    outputs[old.name] = old.read_bytes()
                continue
            outputs[f"{name}.csv"] = table_csv(c, name, order_by)
        wishlists = None
        if "public.wishlist_entry" not in missing:
            wishlists = {f"{pid}.json": data for pid, data in wishlist_files(c).items()}
        magic = None if missing & INVENTORY_TABLES else inventory_files(c)
        c.rollback()
    total = sum(len(data) for data in outputs.values())
    _write_folder(folder, outputs, "*.csv")
    if wishlists is not None:
        _write_folder(repo / "wishlists", wishlists, "*.json")
    if magic is not None:
        write_inventory(repo / MAGIC, magic)
    _write_changed(repo / "README.md", README.encode("utf-8"))
    _write_once(repo / ".gitattributes", GITATTRIBUTES)
    return total


def _write_folder(folder, files, pattern):
    """Make folder hold exactly files ({name: bytes}) among the names matching pattern: each
    written only when its bytes differ, the others unlinked."""
    folder.mkdir(parents=True, exist_ok=True)
    for filename, data in files.items():
        _write_changed(folder / filename, data)
    for path in folder.glob(pattern):
        if path.name not in files:
            path.unlink()


def _write_changed(path, data):
    if not path.is_file() or path.read_bytes() != data:
        path.write_bytes(data)


def _write_once(path, text):
    if not path.exists():
        path.write_bytes(text.encode("utf-8"))


def git(repo, *args):
    """Run git in repo with no window; (exit code, output text). Git's own variables from the
    calling environment (a hook's GIT_DIR, say) are left out so it acts on repo alone. Git
    never asks for credentials (no terminal prompt, no Credential Manager sign-in window at
    night): a push that needs them fails at once, and the failure is recorded."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY")}
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    try:
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=GIT_TIMEOUT, env=env, **_SPAWN)
    except subprocess.TimeoutExpired:
        return None, f"git {args[0]} didn't finish within {GIT_TIMEOUT} seconds"
    except OSError as e:
        return None, f"git can't run: {e}"
    text = (done.stdout + done.stderr).decode("utf-8", "replace").strip()
    return done.returncode, text


def _git_ok(repo, *args):
    code, text = git(repo, *args)
    if code != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {' '.join(text.split()) or f'exit code {code}'}")
    return text


def ensure_repo(repo):
    """Make repo a git repository (git init, branch main) when it isn't one yet. Returns True
    when it was made. Only ever local: making a remote is left to the owner.

    The export runs `git add -A`, commits and pushes, so it must never point at a working
    repo: a folder in the TradingCardCollection repo is refused (ValueError), and so is an
    existing repo that isn't an export repo (one with commits, or other files, but no
    README.md starting with this module's heading)."""
    from decklab.lib import config
    repo = Path(repo)
    resolved = repo.resolve()
    home = Path(config.REPO).resolve()
    if resolved == home or home in resolved.parents:
        raise ValueError(f"the export repo {repo} is inside the Deck Lab repo {home}; "
                         "set database.export_repo in config.json to a folder of its own")
    repo.mkdir(parents=True, exist_ok=True)
    code, text = git(repo, "rev-parse", "--show-toplevel")
    if code == 0 and Path(text.splitlines()[-1]).resolve() == resolved:
        if not _is_export_repo(repo):
            raise ValueError(f"{repo} is a git repo, but not a Deck Lab export (its README.md doesn't start "
                             f"with \"{README.splitlines()[0]}\"); the export won't commit into it")
        return False
    _git_ok(repo, "init", "-b", "main")
    return True


def _is_export_repo(repo):
    """True when repo's README.md is this module's, or the repo is still empty: no commits,
    and nothing in the folder but .git and what write_tables makes."""
    try:
        with open(repo / "README.md", encoding="utf-8") as f:
            if f.readline().rstrip("\r\n") == README.splitlines()[0]:
                return True
    except OSError:
        pass
    code, _ = git(repo, "rev-parse", "--verify", "-q", "HEAD")
    if code == 0:
        return False
    return all(p.name in (".git", "tables", "wishlists", MAGIC, ".gitattributes") for p in repo.iterdir())


def commit(repo, when=None):
    """git add -A and commit "Deck Lab export YYYY-MM-DD HH:MM" when anything changed.
    Returns the new commit's short hash, or None when there was nothing to commit."""
    _git_ok(repo, "add", "-A")
    if not _git_ok(repo, "status", "--porcelain"):
        return None
    _git_ok(repo, "commit", "-q", "-m", f"Deck Lab export {(when or datetime.now()):%Y-%m-%d %H:%M}")
    return _git_ok(repo, "rev-parse", "--short", "HEAD").splitlines()[-1]


def has_origin(repo):
    return "origin" in _git_ok(repo, "remote").split()


def _psycopg_errors():
    """(psycopg.Error,) when psycopg is installed, else (): a query failing while the server is
    up (a table ro can't read, say) is recorded like any failed export. DbUnavailable isn't a
    psycopg.Error, so it still goes up: with no database there's nowhere to record anything."""
    try:
        import psycopg
    except ImportError:
        return ()
    return (psycopg.Error,)


def run_export(repo=None, push=True, say=backup.say):
    """The export command. Returns 0, or 1 when writing, committing or pushing failed
    (recorded in ops.backup_run either way)."""
    repo = Path(repo or db.settings()["export_repo"])
    started = datetime.now()
    size, made = None, None
    try:
        made = ensure_repo(repo)
        size = write_tables(repo)
        sha = commit(repo, started)
        pushed = None
        if push and has_origin(repo):
            _git_ok(repo, "push", "-q", "origin", "HEAD")
            pushed = True
    except (OSError, RuntimeError, ValueError, *_psycopg_errors()) as e:
        backup.record("export", started, False, repo, size, str(e))
        say(f"Export failed: {e}")
        return 1
    parts = [f"committed {sha}" if sha else "no changes"]
    if pushed:
        parts.append("pushed to origin")
    elif push:
        parts.append("no origin to push to")
    if made:
        parts.insert(0, "made the repo")
    detail = ", ".join(parts)
    backup.record("export", started, True, repo, size, detail)
    say(f"Export to {repo}: {len(TABLES)} tables, {detail}.")
    return 0
