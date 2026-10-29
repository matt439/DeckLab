"""No inventory file is read outside decklab/lib/inventory (the phase 3 design review, ops/high:
"the gate can't detect a reader that was never ported and still reads the CSVs").

Every reader of the collections, tokens, orders, products and the watchlist works from
inventory.current(). A reader that still builds a path to one of those files would read the live
file with the files backend and silently find nothing with the database backend, and the gate,
which runs with the files present, couldn't tell. So this test greps decklab/lib, decklab/db,
decklab/server.py (SCANNED) for code that names such a file:
a path joined with "collection.csv", "status.csv", "watchlist.csv", "tokens.csv", "orders" or
"products" (by /, joinpath or os.path.join); any string naming one of those files,
"orders/records", "magic/orders" or "magic/products"; the products or orders folder constants and
STATUS_NAME; a Space's file paths. decklab/lib/inventory/ is the one place allowed to.

Each line that matches must be listed, by a fragment of its text, in one of these lists:
- MESSAGES: lines that only name a file in words (an error message, a label, help text) or
  that point old code at a tree (the gate's pointed()). These stay.
- NOT_YET_PORTED: lines other areas of phase 3 are still porting, with what they read. Each area
  removes its entries as it ports them.
- EXPORT_OUTPUTS: names written into a new export, never read as inventory input.
The test fails for a matching line no entry covers, and for an entry that no longer matches any
line (so neither list can go stale).

EntryCommandTests: the command lines that read the inventory run in inventory.entry.command()
(the venv activated, one pinned snapshot, the stale note on stderr, exit 2 when the database
can't be used).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_inventory_reads
"""
import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.tests import db_support

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "decklab" / "lib"
SCANNED = ("decklab/lib", "decklab/db", "decklab/server.py")
PATTERNS = (
    re.compile(r"""/\s*f?["'][^"'\n]*(collection\.csv|status\.csv|watchlist\.csv|tokens\.csv|orders|products)"""),
    re.compile(r"""["'][^"'\n]*(collection\.csv|status\.csv|watchlist\.csv|tokens\.csv|orders/records|"""
               r"""magic/orders|magic/products)"""),
    re.compile(r"""(joinpath|os\.path\.join)\([^)]*["'][^"'\n]*(orders|products|magic)"""),
    re.compile(r"\b(PRODUCTS_DIR|ORDERS_DIR|COLLECTION|STATUS_NAME)\b"),
    # A Space's file paths (spaces.Space.collection, .tokens, .imports).
    re.compile(r"(spaces\.get\([^)]*\)|\bspace|\bhome|\bs)\.(collection|tokens|imports)\b(?!\s*\()"),
)
# (file, a fragment of the line): words only, never a read.
MESSAGES = {
    ("decklab/lib/accessories.py", '_STATUS_STRAY = f"products/{pool.STATUS_NAME}"'): "a stray's label",
    ("decklab/db/inv_collection.py", 'for folder in ("magic/orders", "magic/products")'):
        "refuses a recorded order's or product's file as merge input; reads nothing",
    ("decklab/lib/forge/field.py", "f\"products/status.csv can't be read"): "a message",
    ("decklab/lib/pool.py", 'STATUS_NAME = "status.csv"'): "how messages name status.csv",
    ("decklab/lib/pool.py", 'f"{STATUS_NAME} line {n}: {file} has'): "messages",
    ("decklab/lib/pool.py", "isn't in products/{STATUS_NAME}"): "a message",
    ("decklab/lib/pool.py", 'f"products/{STATUS_NAME} lists {name}'): "a message",
    ("decklab/lib/purchases.py", 'prefix = "magic/products" if kind == "product" else "magic/orders"'):
        "a component's path as Shopping names it",
    ("decklab/lib/purchases.py", 'value = "magic/products/" + row["file"]'): "a product's path as messages name it",
}
# (file, a fragment of the line): still read as files, until their area ports them. Empty since
# every area of phase 3 merged; kept so a reader ported later has its place.
NOT_YET_PORTED = {}
# Member export renders this space's database rows into a fresh external directory. These
# two output keys are the complete exception; source inventory still comes from its snapshot.
EXPORT_OUTPUTS = {
    ("decklab/db/space_export.py", 'files = {"collection.csv": rules.csv_bytes(cards, rules.FIELDS),'):
        "member collection export output, not an inventory file read",
    ("decklab/db/space_export.py", '"tokens.csv": rules.csv_bytes(tokens, rules.TOKEN_FIELDS)}'):
        "member token export output, not an inventory file read",
}


def _code(line):
    """The line without a trailing comment (a # outside quotes)."""
    quote = None
    for i, c in enumerate(line):
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#":
            return line[:i]
    return line


def _matches(path):
    """[(line number, stripped line)] of path's code lines that match PATTERNS."""
    found = []
    in_docstring = False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        # Docstrings and comments name the files freely; only code counts.
        quotes = stripped.count('"""') + stripped.count("'''")
        if in_docstring or (quotes and stripped.startswith(('"""', "'''", 'r"""'))):
            if quotes % 2 == 1:
                in_docstring = not in_docstring
            continue
        code = _code(line)
        if any(p.search(code) for p in PATTERNS):
            found.append((n, stripped))
    return found


def _scanned():
    """(repo-relative path, Path) of every SCANNED Python file outside decklab/lib/inventory/."""
    for rel in SCANNED:
        path = ROOT / rel
        for found in (sorted(path.rglob("*.py")) if path.is_dir() else [path]):
            rel_path = found.relative_to(ROOT).as_posix()
            if not rel_path.startswith("decklab/lib/inventory/"):
                yield rel_path, found


class NoFileReadsTests(unittest.TestCase):

    def test_no_reader_outside_the_inventory_builds_an_inventory_path(self):
        allowed = {**MESSAGES, **NOT_YET_PORTED, **EXPORT_OUTPUTS}
        used, unexpected = set(), []
        for rel, path in _scanned():
            for n, line in _matches(path):
                keys = [key for key in allowed if key[0] == rel and key[1] in line]
                if keys:
                    used.update(keys)
                else:
                    unexpected.append(f"{rel}:{n}: {line}")
        self.assertEqual(unexpected, [], "read these through decklab.lib.inventory.current() instead "
                                         "(or list a line that only names a file in MESSAGES)")
        stale = sorted(set(allowed) - used)
        self.assertEqual(stale, [], "these lines are gone or ported now: remove them from the lists")

    def test_the_guard_sees_the_ways_a_path_is_built(self):
        for line in ('x = root.joinpath("magic", "orders")', 'p = os.path.join(base, "products")',
                     'p = Path("magic/collection.csv")', 'p = folder / pool.STATUS_NAME',
                     'with open("magic/watchlist.csv") as f:', 'records = base / "magic/orders/records"'):
            with self.subTest(line):
                self.assertTrue(any(p.search(_code(line)) for p in PATTERNS))

    def test_the_command_lines_that_read_the_inventory_start_with_entry_command(self):
        # Q4: each activates the venv (the database backend needs psycopg) and pins one snapshot.
        root = ROOT
        for rel in ("decklab/lib/forge/__main__.py", "decklab/lib/goldfish/__main__.py",
                    "decklab/lib/stats/__main__.py", "decklab/lib/pool.py", "decklab/lib/purchases.py"):
            with self.subTest(rel):
                self.assertIn("with entry.command():", (root / rel).read_text(encoding="utf-8"))

    def test_the_ported_readers_have_no_path_constants(self):
        from decklab.lib import pool
        for name in ("COLLECTION", "ORDERS_DIR", "MAGIC"):
            self.assertFalse(hasattr(pool, name), name)
        import decklab.lib.purchases as purchases
        source = Path(purchases.__file__).read_text(encoding="utf-8")
        self.assertNotIn('root / "magic', source)


class EntryCommandTests(unittest.TestCase):
    """inventory.entry.command(): the venv, one pinned snapshot, the stale note on stderr."""

    def setUp(self):
        from decklab.tests import test_pool
        self.case = test_pool.PoolTestCase()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_one_snapshot_the_venv_and_the_stale_note(self):
        from decklab.lib import inventory, venv
        from decklab.lib.inventory import entry
        stale = self.case.inventory.load().replace(stale="inventory as of 2026-10-12 09:00: the database isn't reachable")
        backend = mock.Mock(load=mock.Mock(return_value=stale))
        err = io.StringIO()
        with mock.patch.object(venv, "activate") as activate, inventory.use(backend), \
                contextlib.redirect_stderr(err):
            with entry.command():
                self.assertTrue(inventory.is_pinned())
                self.assertIs(inventory.current(), inventory.current())
        activate.assert_called_once_with()
        self.assertEqual(backend.load.call_count, 1)
        self.assertEqual(err.getvalue(), f"Note: {stale.stale}.\n")

    def test_purchases_check_runs_in_one_pinned_snapshot(self):
        from decklab.lib import inventory, purchases
        self.case.write("watchlist.csv", ",".join(purchases.QUEUE_FIELDS) + "\n")
        seen = []
        real = purchases.read_queue

        def read_queue():
            seen.append(inventory.is_pinned())
            return real()
        out = io.StringIO()
        with mock.patch.object(purchases, "read_queue", read_queue), contextlib.redirect_stdout(out), \
                mock.patch.object(purchases.config, "REPO", self.case.inventory.root):
            self.assertEqual(purchases.main(["--check"]), 0)
        self.assertEqual(seen, [True])
        self.assertEqual(out.getvalue(), "Shopping records valid: 0 orders, 0 queued purchases.\n")

    def test_the_database_down_is_exit_2(self):
        from decklab.lib import inventory, pool, purchases
        backend = mock.Mock(load=mock.Mock(side_effect=inventory.Unavailable("the database isn't reachable")))
        with inventory.use(backend), contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO(), "utf-8")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(purchases.main(["--check"]), 2)
            self.assertEqual(pool.main([]), 2)


class FilesBackendReadTests(unittest.TestCase):
    """What the files backend's reads add for readers: a page writer's files seen after its write
    (inventory.invalidate), missing files named under the tree read, upper-case .CSV files reported."""

    def setUp(self):
        from decklab.tests import test_pool
        self.case = test_pool.PoolTestCase()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_invalidate_drops_the_requests_snapshot(self):
        from decklab.lib import inventory
        from decklab.lib.inventory import files
        self.case.cards_csv("collection.csv", ("Opt", "dom", "60", "nonfoil", 1))
        with inventory.pinned():
            self.assertEqual(len(inventory.current().collection("home").rows), 1)
            files.atomic_write(self.case.magic / "collection.csv",
                               b"name,set,collector_number,finish,quantity,condition,language,notes\n"
                               b"Opt,dom,60,nonfoil,1,,,\nShock,m19,156,nonfoil,1,,,\n")
            inventory.invalidate()
            self.assertEqual(len(inventory.current().collection("home").rows), 2)
            given = inventory.current()
            with inventory.pinned(given):           # a preview's snapshot stays
                files.atomic_write(self.case.magic / "tokens.csv", b"")
                inventory.invalidate()
                self.assertIs(inventory.current(), given)
            (self.case.magic / "collection.csv").unlink()
            inventory.invalidate()
            self.assertFalse(inventory.current().collection("home").exists)

    def test_a_missing_file_is_named_under_the_tree_read(self):
        from decklab.lib import inventory
        from decklab.lib.inventory import unreadable
        with inventory.pinned():
            error = unreadable.missing("magic/watchlist.csv")
        self.assertEqual(Path(error.filename), self.case.inventory.root / "magic/watchlist.csv")

    def test_an_upper_case_csv_is_unreadable_not_left_out(self):
        self.case.cards_csv("orders/2026-10-01-shout.csv", ("Opt", "dom", "60", "nonfoil", 1))
        (self.case.magic / "orders/2026-10-01-shout.csv").rename(self.case.magic / "orders/2026-10-01-SHOUT.CSV")
        unreadable = self.case.inventory.load().unreadable
        self.assertEqual(list(unreadable), ["magic/orders/2026-10-01-SHOUT.csv"])
        self.assertIn("rename it to 2026-10-01-SHOUT.csv", unreadable["magic/orders/2026-10-01-SHOUT.csv"])


class CommandLineDbTests(db_support.DbTestCase):
    """The command lines on the database backend (review item ops/medium): each prints what it
    prints on the files backend for the same inventory, exits 2 for a database whose inventory
    hasn't been imported, and the purchases check runs as its own process on the system python
    on the database backend (lib/venv.py finds psycopg)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests.test_inventory_contract import FIXTURE_PROFILES
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        self.pg = pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())

    @staticmethod
    def commands():
        """{name: () -> exit code} of the command lines, run in this process."""
        from decklab.lib import pool, purchases
        from decklab.lib.forge import cli
        from decklab.db import __main__ as db_cli
        from decklab.lib.inventory import entry

        def forge_field():
            with entry.command(), tempfile.TemporaryDirectory() as results:
                return cli.main(["field", "casual/elves", "--show", "--json", "--results-dir", results])
        return {"pool": lambda: pool.main(["--no-prices"]),
                "pool deck": lambda: pool.main(["casual/elves", "--no-prices"]),
                "pool product": lambda: pool.main(["product/fdn-beginner-box/elves", "--no-prices"]),
                "purchases --check": lambda: purchases.main(["--check"]),
                "purchases": lambda: purchases.main([]),
                "deck tables --check": lambda: db_cli.main(["deck", "tables", "--check"]),
                "forge field --show": forge_field}

    @staticmethod
    def run_command(fn):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(out, "reconfigure",
                                                                                                create=True):
            code = fn()
        return code, out.getvalue(), err.getvalue()

    def both(self, builder):
        """{command name: (exit code, stdout, stderr)} on the files backend, then on the database
        holding the same inventory and decks (the inventory files deleted first, so nothing can
        read them; the database backend never reads deck files)."""
        from decklab.lib import inventory
        from decklab.lib.inventory import files
        from decklab.lib.inventory.files import FileInventory
        from decklab.tests import test_inventory_contract as contract
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        with contract.scenario(builder, adapted=True) as case:
            root = case.inventory.root
            with inventory.use(FileInventory(root)):
                expected = {name: self.run_command(fn) for name, fn in self.commands().items()}
            on_files = FileInventory(root)
            loaded = on_files.load()
            self.pg.write_model(loaded, contract.CLAUDE, "Import", contents=contract.import_contents(root),
                                dbname=self.dbname, decks=True,
                                images={name: on_files.image(name) for name in loaded.accessory_images})
            for rel in files.tree_files(root):
                (root / rel).unlink()
            with inventory.use(self.backend):
                got = {name: self.run_command(fn) for name, fn in self.commands().items()}
        return expected, got

    def test_the_command_lines_print_the_same_on_both_backends(self):
        from decklab.tests import test_inventory_contract as contract
        for builder in (contract.built_decks_and_kits, contract.recorded_orders):
            expected, got = self.both(builder)
            for name in expected:
                with self.subTest(builder=builder.__name__, command=name):
                    self.assertEqual(got[name], expected[name])
            if builder is contract.built_decks_and_kits:
                self.assertEqual(expected["pool deck"][0], 0)
                self.assertIn("casual/elves (target list)", expected["pool deck"][1])
                # The intact product with no list makes the pool incomplete: refused alike.
                self.assertEqual(expected["deck tables --check"][0], 1)
                self.assertIn("lists lost-precon.csv", expected["deck tables --check"][2])
                self.assertEqual(expected["forge field --show"][0], 0)
                self.assertIn('"id": "casual/idea"', expected["forge field --show"][1])
            else:
                self.assertEqual(expected["purchases --check"][0], 0)
                self.assertRegex(expected["purchases --check"][1], r"\AShopping records valid: [1-9]\d* orders")

    def test_a_database_with_no_inventory_is_exit_2(self):
        from decklab.lib import inventory
        with inventory.use(self.backend):
            for name in ("pool", "purchases --check", "deck tables --check"):
                with self.subTest(name):
                    code, out, err = self.run_command(self.commands()[name])
                    self.assertEqual(code, 2)
                    self.assertIn(self.pg.NOT_IMPORTED, out + err)

    def test_purchases_check_as_a_process_on_the_system_python(self):
        import subprocess
        import sys
        from decklab.lib import venv
        from decklab.tests import test_inventory_contract as contract
        if not venv.VENV.is_dir():
            self.skipTest(f"this checkout has no {venv.VENV} for the system python to find psycopg in")
        python = Path(sys.base_prefix) / ("python.exe" if os.name == "nt" else "bin/python3")
        with tempfile.TemporaryDirectory() as temp:
            extra = Path(temp) / "extra.json"
            extra.write_text('{"inventory": {"backend": "db"}}', encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != "DECKLAB_STATE_EXPLICIT"}
            env.update({"DECKLAB_CONFIG_EXTRA": str(extra), "DECKLAB_DB_NAME": self.dbname,
                        "PYTHONIOENCODING": "utf-8"})

            def run():
                return subprocess.run([str(python), "-m", "decklab.lib.purchases", "--check"], cwd=ROOT, env=env,
                                      capture_output=True, text=True, encoding="utf-8", timeout=120,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            done = run()
            self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
            self.assertIn(self.pg.NOT_IMPORTED, done.stdout)
            inv, contents = contract.build_scenario(contract.recorded_orders)
            self.pg.write_model(contract.adapt(inv), contract.CLAUDE, "Import", contents=contents,
                                dbname=self.dbname)
            done = run()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertRegex(done.stdout, r"\AShopping records valid: \d+ orders, \d+ queued purchases\.\n\Z")


if __name__ == "__main__":
    unittest.main()
