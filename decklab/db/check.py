"""The nightly check of the database's data: `python -m decklab.db check`, and a step of the
nightly task after the export (nightly.py), so a failure here never stops a backup or an export.

Everything is read in ONE snapshot: a read-only, repeatable-read connection as decklab_ro, the
inventory loaded on it (PgInventory.load(conn=...)) and pinned (inventory.pinned), so every
sub-check sees the same revisions, and the SQL ones the same rows. The sub-checks, each recorded
as {name, ok, warning, detail, seconds}:

- accessories: what `accessories check` reports (lib/accessories.check);
- tokens (<space>): what `tokens check` reports, for EVERY space in config.json, not only home
  (a name check skipped while the card data isn't loaded is a warning);
- orders and queue: what `python -m decklab.lib.purchases --check` validates;
- deck tables: what `deck tables --check` reports, across every space, as a WARNING only (tables
  are expected to go stale after a collection merge or a token edit until "Update their
  tables"); a refresh that can't be worked out (no card data, an incomplete pool while a forced
  order is on the way, an unknown card) is a warning too, saying why: the decks' own
  invariants below fail for a deck whose text is missing or wrong;
- printings in box: built home decks whose Printings in box line can't all be true (a card the
  box no longer holds, a printing the collection no longer has enough copies of), as a WARNING
  only: a collection edit may make a record stale, and the deck page says so until it's fixed;
- the decks' invariants, in SQL and Python: aliases are flat, keep one space and kind, refer
  to historical identities and never replace a current deck; revisions are unique throughout
  each alias lineage; every deck's revision is its lineage's newest deck_revision,
  its deck_text is that revision's text, its deck_line rows are what its text parses to, and
  its title, status and played_by are its text's header's;
- revision rows: inventory_revision and decks_revision each hold exactly one row;
- audit trail: every audit.row_change belongs to an audit.change_set;
- Commander-night notes: the optional household record has a valid revision and complete,
  dated notes (or a retained empty tombstone), using the same value rules as a save;
- field policy: each format's revision and complete policy are valid and canonical,
  retaining obsolete deck-incarnation rules without looking up current decks;
- visibility: Public switches belong to a configured space or one of the home's kit owners;
- files round trip: the export's files (the inventory's, the raw imports and the deck parts:
  export.inventory_files, read on the same connection), built with inventory.files.build, give
  the same snapshot PgInventory gives for the same revisions (the "raw first" design: both
  backends make the same snapshot from the same data), so the off-PC export can be read back.
  The files can't carry the products' names, so those are taken from the database's snapshot
  before comparing. Alias metadata comes from the table CSV in the same export snapshot.

Each run is one ops.backup_run row, kind 'check' (migration 0007), ok when no sub-check failed;
its detail is JSON: {"revision", "decks_revision", "checks": [...]}. Each sub-check's outcome is
also a line in decklab/data/logs/db.log. `check --history` prints the recent runs. `status`
shows the last one, and the footer warns an admin when it failed or is old (lib/dbstatus.py).

Exit codes: 0 every sub-check passed (warnings allowed), 1 one failed (or the run couldn't be
recorded), 2 the database can't be reached.
"""
import csv
import dataclasses
import io
import json
import time
from datetime import date, datetime

from decklab.db import backup, conn as db

KIND = "check"                  # ops.backup_run's kind for a run (migration 0007)
HISTORY_LIMIT = 14              # runs --history prints by default: two weeks of nights
SHOWN = 5                       # problems a sub-check's detail names before "and N more"


def _listed(items, shown=SHOWN):
    """Up to shown items joined by "; ", and how many more there are."""
    items = list(items)
    text = "; ".join(str(i) for i in items[:shown])
    if len(items) > shown:
        text += f"; and {len(items) - shown} more"
    return text


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


class _Run:
    """One run's sub-checks, in order."""

    def __init__(self, say):
        self.say = say
        self.checks = []

    def sub(self, name, func, conn=None):
        """Run func() -> (ok, warning, detail) as the sub-check called name; one that raises
        fails with what it raised. conn: the connection it reads, its work run in a savepoint so
        a statement that fails leaves the snapshot's transaction usable for the next. Logged at
        once (one line each)."""
        start = time.monotonic()
        try:
            if conn is None:
                ok, warning, detail = func()
            else:
                with conn.transaction():
                    ok, warning, detail = func()
        except Exception as e:                      # noqa: BLE001 (the next sub-check still runs)
            ok, warning, detail = False, False, f"{type(e).__name__}: {e}"
        seconds = round(time.monotonic() - start, 2)
        self.checks.append({"name": name, "ok": bool(ok), "warning": bool(warning) and bool(ok),
                            "detail": detail or "", "seconds": seconds})
        state = "FAILED" if not ok else "warning" if warning else "ok"
        self.say(f"Check: {name}: {state}" + (f": {detail}" if detail else "") + f" ({seconds:.1f} s)")

    @property
    def failed(self):
        return [c["name"] for c in self.checks if not c["ok"]]


# ------------------------------------------------------------------ the rule checks

def _accessories():
    from decklab.lib import accessories
    # Deck Lab warns about these rather than blocking (too few sleeves, a deck box used too often, ...),
    # so they're a warning here too, as the deck tables' are.
    problems = accessories.check()
    return True, bool(problems), _listed(problems) if problems else "no problems"


def _tokens(space):
    def work():
        from decklab.lib import tokens
        notes = []
        problems = tokens.check(notes=notes, space=space)
        if problems:
            return False, False, _listed(problems)
        return True, bool(notes), _listed(notes) if notes else "no problems"
    return work


def _orders():
    from decklab.lib import purchases
    data = purchases.overview()
    return True, False, f"{_plural(len(data['orders']), 'order')}, {_plural(len(data['to_buy']), 'queued purchase')}"


def _deck_tables():
    from decklab.db import inv_decks
    try:
        planned = inv_decks.plan_tables()
    except (ValueError, OSError, RuntimeError) as e:
        # The refresh's refusals (an incomplete pool, an unknown card, a deck it can't read: ValueError,
        # DeckFileError, OSError) and the card index's (none, or an old one): each says why.
        return True, True, f"not checked: the tables can't be worked out ({e})"
    if planned:
        return True, True, (f"{_plural(len(planned), 'deck')} with an out-of-date table: "
                            + _listed(deck_id for deck_id, *_ in planned)
                            + " (python -m decklab.db deck tables --apply)")
    return True, False, "every table is up to date"


def _printings_in_box():
    from decklab.lib import pool
    try:
        in_use = pool.load_pool().in_use
    except (ValueError, OSError, RuntimeError) as e:
        return True, True, f"not checked: the pool can't be read ({e})"
    stale = [f"{item.title}: {why}" for item in in_use for why in item.recorded_stale]
    if stale:
        return True, True, f"{_plural(len(stale), 'part')} out of date: " + _listed(stale)
    return True, False, "every record can be true"


# ------------------------------------------------------------------ the database's invariants

def _aliases_ready(c):
    return c.execute("select to_regclass('public.deck_alias') is not null").fetchone()[0]


def _history_sql(c):
    """A revision's canonical ID, leaving its immutable historical deck_id untouched."""
    if _aliases_ready(c):
        return ("with history as (select coalesce(a.deck_id, r.deck_id) canonical_id, r.* "
                "from deck_revision r left join deck_alias a on a.alias_id = r.deck_id) ")
    return "with history as (select deck_id canonical_id, r.* from deck_revision r) "


def _deck_aliases(c):
    def work():
        if not _aliases_ready(c):
            return True, False, "rename aliases unavailable until migration 0010"
        aliases = dict(c.execute("select alias_id, deck_id from deck_alias order by alias_id"))
        active = {row[0] for row in c.execute("select id from deck")}
        history = {}
        for deck_id, revision, op in c.execute("select deck_id, revision, op from deck_revision"):
            history.setdefault(deck_id, []).append((revision, op))
        wrong = []
        for alias, target in aliases.items():
            if alias == target or alias.rsplit("/", 1)[0] != target.rsplit("/", 1)[0]:
                wrong.append(f"{alias} changes its space or kind, or names itself")
            if alias in active:
                wrong.append(f"{alias} is both an alias and a current deck")
            if target in aliases:
                wrong.append(f"{alias} points to another alias ({target})")
            for deck_id in (alias, target):
                if deck_id not in history:
                    wrong.append(f"{deck_id} has no deck history")
        lineages = {}
        for deck_id, rows in history.items():
            target = aliases.get(deck_id, deck_id)
            numbered = lineages.setdefault(target, {})
            for revision, op in rows:
                if revision in numbered:
                    wrong.append(f"{target} has revision {revision} under several IDs")
                numbered[revision] = op
        for target in sorted(set(aliases.values())):
            rows = lineages.get(target, {})
            if target not in active and rows and rows[max(rows)] != "D":
                wrong.append(f"{target} is missing its current deck without a retirement")
        return not wrong, False, (_listed(wrong) if wrong
                                  else f"deck lineages remain separate ({_plural(len(aliases), 'alias')})")
    return work


def _deck_revisions(c):
    def work():
        rows = c.execute(_history_sql(c) +
                         "select d.id, d.revision, m.top from deck d left join (select canonical_id, max(revision) top "
                         "from history group by canonical_id) m on m.canonical_id = d.id "
                         "where m.top is distinct from d.revision order by d.id").fetchall()
        return not rows, False, (_listed(f"{i} is at revision {r}, its newest is {t}" for i, r, t in rows)
                                 if rows else "every deck is at its newest revision")
    return work


def _deck_texts(c):
    def work():
        rows = c.execute(_history_sql(c) +
                         "select d.id, t.deck_id is null from deck d left join deck_text t on t.deck_id = d.id "
                         "left join history r on r.canonical_id = d.id and r.revision = "
                         "(select max(x.revision) from history x where x.canonical_id = d.id) "
                         "where t.deck_id is null or r.text is distinct from t.text order by d.id").fetchall()
        return not rows, False, (_listed(f"{i} has no text" if missing else f"{i}'s text isn't its newest revision's"
                                         for i, missing in rows)
                                 if rows else "every text is its newest revision's")
    return work


def _texts(c):
    """{deck id: (title, status, played_by, text)} of every deck with a text."""
    return {i: (title, status, played_by, text) for i, title, status, played_by, text in c.execute(
        "select d.id, d.title, d.status, d.played_by, t.text from deck d join deck_text t on t.deck_id = d.id "
        "order by d.id")}


def _deck_lines(c):
    def work():
        from decklab.lib.inventory import pg_decks
        stored = {}
        for row in c.execute("select deck_id, version, section, position, quantity, name, set_code, "
                             "collector_number, finish from deck_line"):
            stored.setdefault(row[0], []).append(tuple(row))
        wrong = []
        texts = _texts(c)
        for deck_id, (_, _, _, text) in texts.items():
            derived = sorted(pg_decks.lines(deck_id, pg_decks.parsed(deck_id, text)))
            if derived != sorted(stored.get(deck_id, [])):
                wrong.append(deck_id)
        wrong += sorted(set(stored) - set(texts))
        return not wrong, False, (f"lines that aren't what the text says: {_listed(wrong)}" if wrong
                                  else f"the lines of {_plural(len(texts), 'deck')} match their texts")
    return work


def _deck_headers(c):
    def work():
        from decklab.lib.inventory import pg_decks
        wrong = []
        for deck_id, (title, status, played_by, text) in _texts(c).items():
            said = pg_decks.summary(pg_decks.parsed(deck_id, text))[:3]
            if said != (title, status, played_by):
                fields = [f for f, a, b in zip(("title", "status", "played_by"), said, (title, status, played_by))
                          if a != b]
                wrong.append(f"{deck_id} ({', '.join(fields)})")
        return not wrong, False, (f"rows that don't match the text's header: {_listed(wrong)}" if wrong
                                  else "every deck row matches its text's header")
    return work


def _revision_rows(c):
    def work():
        counts = {table: c.execute(f"select count(*) from {table}").fetchone()[0]
                  for table in ("inventory_revision", "decks_revision")}
        wrong = [f"{table} has {n} rows" for table, n in counts.items() if n != 1]
        return not wrong, False, _listed(wrong) if wrong else "one row each"
    return work


def _audit_trail(c):
    def work():
        orphans = c.execute("select count(*) from audit.row_change r where not exists "
                            "(select 1 from audit.change_set s where s.id = r.change_set_id)").fetchone()[0]
        return not orphans, False, (f"{_plural(orphans, 'row change')} without a change set" if orphans
                                    else "every row change has its change set")
    return work


def _visibility(c):
    def work():
        from decklab.lib import spaces
        from decklab.lib.state import Invalid, visibility
        if c.execute("select to_regclass('public.visibility') is null").fetchone()[0]:
            return True, False, "visibility unavailable until migration 0012"
        known = set(spaces.space_ids())
        rows = c.execute("select owner, thing from visibility order by owner, thing").fetchall()
        wrong = []
        for owner, thing in rows:
            try:
                visibility.key(owner, thing)
            except Invalid as error:
                wrong.append(f"{owner}/{thing}: {error}")
                continue
            if thing != "accessories" and owner not in known:
                wrong.append(f"{owner}/{thing}: owner is not a configured space")
        return not wrong, False, (_listed(wrong) if wrong else f"{len(rows)} Public switches; all owners valid")
    return work


def _commander_night(c):
    def work():
        from decklab.lib.state import Invalid, commander_night
        if c.execute("select to_regclass('public.commander_night') is null").fetchone()[0]:
            return True, False, "Commander-night notes unavailable until migration 0011"
        rows = c.execute("select id, revision, content from commander_night").fetchall()
        if not rows:
            return True, False, "not configured"
        if len(rows) != 1:
            return False, False, "expected at most one Commander-night record"
        key, revision, content = rows[0]
        if key is not True or type(revision) is not int or revision < 1:
            return False, False, "invalid Commander-night record identity or revision"
        try:
            # A saved historical date remains valid when restored under a different clock.
            normalized = commander_night.normalize(content, today=date.max)
        except Invalid as e:
            return False, False, str(e)
        if normalized != content:
            return False, False, "the Commander-night notes are not in their complete saved form"
        return True, False, f"{'cleared' if content is None else 'valid notes'} at revision {revision}"
    return work


def _field_policy(c):
    """Validate stored policy only; old incarnation rules are intentional tombstones."""
    def work():
        from decklab.lib.state import Invalid, field_policy
        try:
            if c.execute("select to_regclass('public.field_policy') is null").fetchone()[0]:
                return True, False, "field policy unavailable until migration 0017"
            rows = c.execute("select format, revision, content from field_policy order by format").fetchall()
        except Exception:                          # noqa: BLE001 (never quote database or policy contents)
            return False, False, "the field policy could not be checked"
        if not rows:
            return True, False, "not configured"
        invalid = (False, False, "the field policy has an invalid saved record")
        seen = set()
        for row in rows:
            if type(row) not in (tuple, list) or len(row) != 3:
                return invalid
            fmt, revision, content = row
            if (type(fmt) is not str or fmt in seen or type(revision) is not int or revision < 1
                    or type(content) is not dict or content.keys() != {"v", "rules"}):
                return invalid
            seen.add(fmt)
            snapshot = {"format": fmt, "revision": revision, **content}
            try:
                normalized = field_policy.normalize(snapshot)
            except Invalid:
                return invalid
            if normalized != snapshot:
                return False, False, "the field policy is not in its complete saved form"
        return True, False, f"valid policy for {_plural(len(rows), 'format')}"
    return work


def _space_departures(c):
    """Operational tombstones must have their audit and no resurrected current rows.

    Config may deliberately still name a departed member until its owner edits it;
    only the database's current data is checked. Details name tables/counts, never
    the departed member's contents. Immutable audit history is retained by design.
    """
    def work():
        from decklab.lib import profiles
        if c.execute("select to_regclass('public.space_departure') is null").fetchone()[0]:
            return True, False, "member departure markers unavailable until migration 0013"
        ids = [row[0] for row in c.execute("select space_id from space_departure").fetchall()]
        invalid = sum(not profiles.valid_id(sid) or sid in profiles.RESERVED_SPACES | profiles.RESERVED_IDS
                      for sid in ids)
        wrong = [f"{invalid} invalid member departure identities"] if invalid else []
        unaudited = c.execute(
            "select count(*) from space_departure d where not exists "
            "(select 1 from audit.row_change r where r.change_set_id = d.change_set_id "
            "and r.table_name = 'space_departure' and r.op = 'INSERT' "
            "and r.row_key->>'space_id' = d.space_id and r.after->>'operation' = d.operation::text)"
        ).fetchone()[0]
        if unaudited:
            wrong.append(f"{unaudited} departure markers without their removal audit")
        references = (
            ("space", "t.id = d.space_id"),
            ("profile", "t.space_id = d.space_id or t.id = d.space_id"),
            ("profile_email", "t.profile_id = d.space_id"),
            ("collection_card", "t.space_id = d.space_id"),
            ("collection_import", "t.space_id = d.space_id"),
            ("token_card", "t.space_id = d.space_id"),
            ("deck", "t.space_id = d.space_id or starts_with(t.id, d.space_id || '/')"),
            ("deck_text", "starts_with(t.deck_id, d.space_id || '/')"),
            ("deck_line", "starts_with(t.deck_id, d.space_id || '/')"),
            ("deck_revision", "starts_with(t.deck_id, d.space_id || '/')"),
            ("deck_alias", "starts_with(t.alias_id, d.space_id || '/') or starts_with(t.deck_id, d.space_id || '/')"),
            ("wishlist_entry", "t.profile_id = d.space_id"),
            ("profile_setting", "t.profile_id = d.space_id"),
            ("visibility", "t.owner = d.space_id"),
            ("play_record", "t.content->>'space' = d.space_id or exists "
                            "(select 1 from unnest(t.deck_ids) i where starts_with(i, d.space_id || '/'))"),
            ("ops.visit_day", "t.profile_id = d.space_id"),
            ("ops.visit_page", "t.profile_id = d.space_id or starts_with(t.deck_id, d.space_id || '/')"),
        )
        if c.execute("select to_regclass('public.dice_counter') is not null").fetchone()[0]:     # migration 0020
            references += (("dice_counter", "t.space_id = d.space_id"),)
        if ids:
            for table, condition in references:
                count = c.execute(f"select count(*) from {table} t where exists "
                                  f"(select 1 from space_departure d where {condition})").fetchone()[0]
                if count:
                    wrong.append(f"{table}: {count} current rows refer to a departed member")
        return not wrong, False, (_listed(wrong) if wrong else f"{len(ids)} departed members; no current data remains")
    return work


# ------------------------------------------------------------------ files against the database

def differences(a, b):
    """The parts in which two Inventory snapshots differ, as words: a field's name, or for a
    mapping (collections, tokens, decks ...) "field[key]" for each key that differs."""
    out = []
    for f in dataclasses.fields(a):
        if not f.compare:
            continue
        x, y = getattr(a, f.name), getattr(b, f.name)
        if x == y:
            continue
        if f.name in a.MAPPINGS:
            out += [f"{f.name}[{key}]" for key in sorted(set(x) | set(y)) if x.get(key) != y.get(key)]
        else:
            out.append(f.name)
    return out


def _round_trip(c, inv):
    def work():
        from decklab.db import export
        from decklab.lib.inventory import files
        found = export.inventory_files(c)
        if found is None:
            return False, False, "the database holds no inventory to write out as files"
        built = files.build(found, revision=inv.revision, backend=inv.backend, decks_revision=inv.decks_revision)
        names = {p.stem: (p.name, p.format) for p in inv.products}
        built = built.replace(products=tuple(
            dataclasses.replace(p, name=names[p.stem][0], format=names[p.stem][1]) if p.stem in names else p
            for p in built.products))
        if _aliases_ready(c):
            # Aliases have no old file equivalent: verify the exported table CSV too, rather
            # than copying inv.deck_aliases and concealing an export or snapshot regression.
            rows = csv.DictReader(io.StringIO(export.table_csv(c, "public.deck_alias", ("alias_id",)).decode("utf-8")))
            built = built.replace(deck_aliases={row["alias_id"]: row["deck_id"] for row in rows})
        wrong = differences(built, inv)
        if wrong:
            return False, False, f"the files give a different snapshot: {_listed(wrong)}"
        return True, False, f"the files ({len(found)}) give the database's snapshot"
    return work


# ------------------------------------------------------------------ the command

def run(dbname=None, say=backup.say):
    """The check command (see the module docstring). Returns 0 when every sub-check passed,
    1 when one failed or the run couldn't be recorded. DbUnavailable goes up (exit 2)."""
    import psycopg
    from psycopg import IsolationLevel

    from decklab.lib import inventory, spaces
    from decklab.lib.inventory.pg import PgInventory
    started = datetime.now()
    result = _Run(say)
    revision = decks_revision = None
    with db.connect("ro", dbname=dbname) as c:
        c.isolation_level = IsolationLevel.REPEATABLE_READ
        c.read_only = True
        backend = PgInventory(dbname=dbname)
        try:
            inv = backend.load(conn=c)
        except Exception as e:                      # noqa: BLE001 (NotImported, a broken row: recorded)
            inv, reason = None, f"the inventory can't be loaded: {e}"
            result.sub("snapshot", lambda: (False, False, reason))
            c.rollback()                            # a failed statement mustn't stop the SQL checks
            c.execute("select 1")                   # their snapshot: one transaction from here
        if inv is not None:
            revision, decks_revision = inv.revision, inv.decks_revision
            with inventory.use(backend), inventory.pinned(inv):
                result.sub("accessories", _accessories)
                for space in spaces.space_ids():
                    result.sub(f"tokens ({space})", _tokens(space))
                result.sub("orders and queue", _orders)
                result.sub("deck tables", _deck_tables)
                result.sub("printings in box", _printings_in_box)
        result.sub("deck aliases", _deck_aliases(c), c)
        result.sub("deck revisions", _deck_revisions(c), c)
        result.sub("deck texts", _deck_texts(c), c)
        result.sub("deck lines", _deck_lines(c), c)
        result.sub("deck headers", _deck_headers(c), c)
        result.sub("revision rows", _revision_rows(c), c)
        result.sub("audit trail", _audit_trail(c), c)
        result.sub("Commander-night notes", _commander_night(c), c)
        result.sub("field policy", _field_policy(c), c)
        result.sub("visibility", _visibility(c), c)
        result.sub("member departures", _space_departures(c), c)
        if inv is not None:
            result.sub("files round trip", _round_trip(c, inv), c)
        c.rollback()
    failed = result.failed
    detail = json.dumps({"revision": revision, "decks_revision": decks_revision, "checks": result.checks},
                        ensure_ascii=False)
    try:
        backup.record(KIND, started, not failed, None, None, detail, dbname=dbname)
    except db.DbUnavailable:
        raise
    except psycopg.OperationalError as e:           # the connection went away: exit 2, as at the start
        raise db.DbUnavailable(f"the check's run couldn't be recorded: {e}") from None
    except Exception as e:                          # noqa: BLE001 (recorded nowhere else: say so)
        from psycopg import errors
        hint = ("; is migration 0007 applied? (python -m decklab.db migrate)"
                if isinstance(e, errors.CheckViolation) else "")
        say(f"Check: the run couldn't be recorded in ops.backup_run ({type(e).__name__}: {e}){hint}")
        return 1
    warned = sum(1 for c in result.checks if c["warning"])
    at = f"inventory revision {revision}, decks revision {decks_revision}"
    if failed:
        say(f"Check FAILED ({at}): {', '.join(failed)}.")
        return 1
    say(f"Check passed ({at}): {_plural(len(result.checks), 'sub-check')}"
        + (f", {_plural(warned, 'warning')}" if warned else "") + ".")
    return 0


def history(limit=HISTORY_LIMIT, dbname=None):
    """The recent runs, newest first, as lines: when, the result and the revisions, then each
    sub-check that failed or warned, indented."""
    with db.connect("ro", dbname=dbname, autocommit=True) as c:
        rows = c.execute("select started_at, ok, detail from ops.backup_run where kind = %s "
                         "order by id desc limit %s", (KIND, int(limit))).fetchall()
    if not rows:
        return ["No check has run yet (python -m decklab.db check)."]
    lines = []
    for started, ok, detail in rows:
        run = {"ok": ok, "detail": detail}
        try:
            data = json.loads(detail or "")
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
        at = ""
        if data.get("revision") is not None:
            at = f" (inventory revision {data['revision']}, decks revision {data.get('decks_revision')})"
        lines.append(f"{started.astimezone():%Y-%m-%d %H:%M} {backup.check_summary(run)}{at}")
        for sub in data.get("checks") or []:
            if isinstance(sub, dict) and (not sub.get("ok") or sub.get("warning")):
                lines.append(f"    {'FAILED' if not sub.get('ok') else 'warning'} {sub.get('name')}: {sub.get('detail')}")
    return lines
