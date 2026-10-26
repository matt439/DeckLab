"""The database's commands: `python -m decklab.db <command>` (the system python finds .venv's
psycopg through lib/venv.py; .venv\\Scripts\\python works as well).

  setup            make the roles, their pgpass lines, the database, migrations and profiles
  migrate          apply pending migrations
  status           migrations, profiles and backups at a glance
  sync-profiles    copy config.json's profiles into the database
  sql              run a read-only query (argument or stdin), --csv for CSV
  backup           pg_dump to the staging folder, then to the NAS (--dest DIR instead)
  prune            delete dumps outside the 14-daily / 8-weekly retention
  restore-check    restore the newest dump into a scratch database and compare row counts and contents
  export           write the tables as CSV into the export repo, commit and push
  check            check the data: the rule checks, the decks' invariants and a files round trip
                   (--history: the recent runs)
  nightly          what the scheduled task runs: backup, prune, visits' prune, export, check, restore check
  visits           who has visited Deck Lab and what they opened (read-only; visits.py)
  schedule         manage the nightly Task Scheduler task, or preview systemd user units
  wishlist         list or change a profile's wishlist: list, add, set, remove (wishlist_cli.py)

The inventory's commands (phase 3) come from decklab/db/inv_<area>.py modules, found and
registered here without editing this file: each module has register(subparsers), which adds
its parsers with set_defaults(func=fn), fn(args) returning the exit code. Every command runs
inside inventory.pinned(), so it reads one snapshot of the inventory however often it looks.

The backup, export, check, nightly and schedule modules are imported only by their own commands.
Exit codes: 0 done, 1 failed, 2 the database can't be reached (or psycopg is missing).
"""
import argparse
import importlib
import pkgutil
import sys

from decklab.lib import venv

venv.activate()                   # so the system python finds .venv's psycopg too (lib/venv.py)

from decklab.db import conn as db  # noqa: E402

INVENTORY_PREFIX = "inv_"           # decklab/db/inv_<area>.py: the inventory's command modules


def _setup(args):
    from decklab.db import setup
    return setup.run(dbname=args.dbname)


def _migrate(args):
    from decklab.db import migrate
    done = migrate.apply(dbname=args.dbname, say=print)
    if not done:
        print("No migrations were pending.")
    return 0


def _status(args):
    from decklab.db import migrate
    s = db.settings()
    name = args.dbname or s["name"]
    state = migrate.status(dbname=name)
    print(f"Database {name} on {s['host']}:{s['port']}.")
    if state["applied"]:
        last = state["applied"][-1]
        print(f"Migrations: {len(state['applied'])} applied, the last {last['version']:04d}_{last['name']} "
              f"on {last['applied_at']:%Y-%m-%d %H:%M}.")
    else:
        print("Migrations: none applied yet.")
    for f in state["pending"]:
        print(f"  pending: {f['path'].name}")
    with db.connect("ro", dbname=name, autocommit=True) as c:
        profiles = c.execute("select count(*) from profile").fetchone()[0]
        spaces = c.execute("select count(*) from space").fetchone()[0]
        changes = c.execute("select count(*), max(at) from audit.change_set").fetchone()
    last = f", the last on {changes[1]:%Y-%m-%d %H:%M}" if changes[1] else ""
    print(f"Profiles: {profiles} in {spaces} space(s). Change sets: {changes[0]}{last}.")
    print(_personal_state(name))
    from decklab.db import inv_inventory
    print(inv_inventory.status_line(name))
    print(inv_inventory.decks_line(name))
    try:
        # import_module, not `from decklab.db import backup`: that turns a missing module
        # into a plain ImportError, which can't be told apart from one inside backup.py.
        backup = importlib.import_module("decklab.db.backup")
    except ModuleNotFoundError as e:
        if e.name != "decklab.db.backup":
            raise                   # backup.py is there but broken: say so, don't hide it
        print("Backups: unknown (decklab/db/backup.py isn't there).")
        return 0
    result = backup.status(dbname=name)
    for line in result.splitlines() if isinstance(result, str) else result:
        print(line)
    return 0


def _personal_state(name):
    """The status line for migration 0003's tables: how many rows each holds."""
    with db.connect("ro", dbname=name, autocommit=True) as c:
        if c.execute("select to_regclass('public.play_record') is null").fetchone()[0]:
            return "Personal state: not in the database yet (migration 0003 is pending)."
        cards, lists = c.execute("select count(*), count(distinct profile_id) from wishlist_entry").fetchone()
        settings, people = c.execute("select count(*), count(distinct profile_id) from profile_setting").fetchone()
        mode = c.execute("select mode from simulation_mode").fetchone()
        games, plans = c.execute("select count(*) filter (where kind = 'games'), "
                                 "count(*) filter (where kind = 'sideboards') from play_record").fetchone()
    return (f"Personal state: {cards} wishlist card(s) on {lists} list(s), {settings} setting(s) of "
            f"{people} profile(s), simulations {mode[0] if mode else 'not set (the default applies)'}, "
            f"{games} game(s) and {plans} sideboard plan(s).")


def _sync(args):
    from decklab.db import profiles_sync
    summary = profiles_sync.sync(dbname=args.dbname)
    print(f"Profiles {profiles_sync.describe(summary)}.")
    return 0


def _sql(args):
    from decklab.db import sql
    return sql.run(args.query, csv_out=args.csv, dbname=args.dbname)


def _backup(args):
    from decklab.db import backup
    return backup.run_backup(dest=args.dest)


def _prune(args):
    from decklab.db import backup
    return backup.run_prune()


def _restore_check(args):
    from decklab.db import backup
    return backup.run_restore_check()


def _export(args):
    from decklab.db import export
    return export.run_export(repo=args.repo, push=not args.no_push)


def _check(args):
    from decklab.db import check
    if args.history:
        for line in check.history(limit=args.limit):
            print(line)
        return 0
    return check.run()


def _visits(args):
    from decklab.db import visits
    from decklab.lib import profiles
    if not 1 <= args.days <= visits.MAX_DAYS:
        raise ValueError(f"--days must be from 1 to {visits.MAX_DAYS}")
    try:
        names = {p["id"]: p["name"] for p in profiles.read()}
    except (OSError, ValueError):
        names = {}
    if args.profile is not None and names and args.profile not in names:
        raise ValueError(f"No profile {args.profile!r} in config.json")
    if args.profile is not None:
        names = {args.profile: names.get(args.profile, args.profile)}
    from psycopg import errors
    try:
        people = visits.summary(args.days, args.profile, dbname=args.dbname)
    except errors.UndefinedTable:
        print("Visits aren't in the database yet (migration 0008 is pending): python -m decklab.db migrate",
              file=sys.stderr)
        return 1
    try:                            # the decks' titles, as the Settings page names them
        from decklab.lib import decks
        titles = {s["id"]: s.get("title") or s["id"] for s in decks.list_decks()}
    except Exception:
        titles = {}
    for line in visits.lines(people, args.days, names, titles):
        print(line)
    return 0


def _nightly(args):
    from decklab.db import nightly
    return nightly.run()


def _schedule(args):
    from decklab.db import schedule
    if args.action == "preview-systemd":
        # A piped Windows stdout may otherwise replace target-path characters with '?'.
        # Unit files are UTF-8; keep their text exact without changing other commands.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="strict", newline="\n")
        return schedule.preview_systemd(getattr(args, "unit", None), getattr(args, "python", None),
                                        getattr(args, "workdir", None), getattr(args, "at", None))
    if any(getattr(args, name, None) is not None for name in ("unit", "python", "workdir", "at")):
        raise ValueError("--unit, --python, --workdir and --at are only for schedule preview-systemd.")
    if args.action == "install":
        return schedule.install()
    if args.action == "remove":
        return schedule.remove()
    result = schedule.status()
    if isinstance(result, (list, tuple)):
        for line in result:
            print(line)
        return 0
    return result


def inventory_modules():
    """The names of the decklab/db/inv_*.py modules, sorted (the inventory's commands)."""
    from decklab import db as package
    return sorted(m.name for m in pkgutil.iter_modules(package.__path__)
                  if m.name.startswith(INVENTORY_PREFIX) and not m.ispkg)


def register_inventory(sub, modules=None):
    """Add each inventory command module's parsers to sub (modules: names, by default every
    inv_*.py there is). A module that can't be imported, or has no register(), fails loudly:
    a command that silently vanished would be worse."""
    for name in inventory_modules() if modules is None else modules:
        module = importlib.import_module(f"decklab.db.{name}")
        register = getattr(module, "register", None)
        if not callable(register):
            raise ImportError(f"decklab/db/{name}.py has no register(subparsers)")
        register(sub)


def parser():
    p = argparse.ArgumentParser(prog="python -m decklab.db",
                                description="Deck Lab's PostgreSQL database.")
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    def command(name, func, help_text, dbname=False):
        sp = sub.add_parser(name, help=help_text, description=help_text)
        sp.set_defaults(func=func)
        if dbname:
            sp.add_argument("--dbname", help="the database to use instead of the settings' one (tests)")
        return sp

    command("setup", _setup, "Make the roles, the database, apply migrations and sync profiles "
                             "(safe to run again).", dbname=True)
    command("migrate", _migrate, "Apply pending migrations.", dbname=True)
    command("status", _status, "Show migrations, profiles and backups.", dbname=True)
    command("sync-profiles", _sync, "Copy config.json's profiles into the database.", dbname=True)
    sp = command("sql", _sql, "Run a read-only query, given as an argument or on stdin.", dbname=True)
    sp.add_argument("query", nargs="?", help='the query ("-" or none reads stdin)')
    sp.add_argument("--csv", action="store_true", help="print CSV instead of a table")
    sp = command("backup", _backup, "Dump the database to the staging folder, then copy it to the NAS.")
    sp.add_argument("--dest", metavar="DIR", help="copy the dump here instead of the NAS folder")
    command("prune", _prune, "Delete dumps outside the daily and weekly retention.")
    command("restore-check", _restore_check, "Restore the newest dump into a scratch database and "
                                             "compare row counts and contents.")
    sp = command("export", _export, "Write the tables as CSV into the export repo, commit and push.")
    sp.add_argument("--repo", metavar="DIR", help="the export repo to use instead of the settings' one")
    sp.add_argument("--no-push", action="store_true", help="commit but don't push")
    sp = command("check", _check, "Check the data in one snapshot: accessories, every space's token cards, the "
                                  "orders and queue, the deck tables, the decks' invariants and a files round "
                                  "trip; recorded in ops.backup_run.")
    sp.add_argument("--history", action="store_true", help="print the recent runs instead of checking")
    sp.add_argument("--limit", type=int, default=14, metavar="N", help="with --history: how many runs (default 14)")
    command("nightly", _nightly, "Backup, prune, the visits' prune, export, check and (monthly) a restore check.")
    sp = command("visits", _visits, "Show who has visited Deck Lab and what they opened (read-only).", dbname=True)
    sp.add_argument("--days", type=int, default=30, metavar="N",
                    help="the window for days visited and the pages opened most (1-366, default 30)")
    sp.add_argument("--profile", metavar="P", help="only this profile's visits")
    sp = command("schedule", _schedule, "Manage the nightly Task Scheduler task, or print a systemd user "
                                      "unit preview without installing anything.")
    sp.add_argument("action", choices=("install", "remove", "status", "preview-systemd"))
    sp.add_argument("--unit", choices=("service", "timer"), help="which systemd user unit to print")
    sp.add_argument("--python", metavar="PATH", help="preview: absolute POSIX path to the target Python")
    sp.add_argument("--workdir", metavar="DIR", help="preview: absolute POSIX path to the target repo")
    sp.add_argument("--at", metavar="HH:MM", help="preview: daily local time (default 03:30)")
    from decklab.db import wishlist_cli
    wishlist_cli.add_parser(sub)
    from decklab.db import visibility_cli
    visibility_cli.add_parser(sub)
    register_inventory(sub)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")   # names and messages a cp1252 pipe can't show
    from decklab.db import migrate
    from decklab.lib import inventory
    try:
        if hasattr(args, "actor"):
            from decklab.db import cli_actor
            cli_actor.resolve(args)        # refuse unknown actors before reading files or data
        with inventory.pinned():            # lazy: a command that never reads it loads nothing
            code = args.func(args) or 0
            stale = inventory.pinned_stale()
            if stale:
                print(f"Note: {stale}.", file=sys.stderr)
            return code
    except (db.DbUnavailable, inventory.Unavailable) as e:
        print(f"The database isn't available: {e}", file=sys.stderr)
        return 2
    except (inventory.Invalid, inventory.Conflict) as e:
        print(str(e), file=sys.stderr)
        return 1
    except (migrate.MigrationError, FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    except Exception as e:
        psycopg = sys.modules.get("psycopg")
        if psycopg is not None and isinstance(e, psycopg.Error):
            print(f"The database refused it: {str(e).strip()}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
