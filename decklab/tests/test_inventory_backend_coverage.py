"""Inventory coverage guard; actual database writes are proven by test_db's final ledger."""
import ast
import importlib
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import pg
from decklab.tests import db_support
from decklab.tests import inventory_backend_coverage as coverage


class InventoryBackendCoverageTests(unittest.TestCase):
    def test_every_registered_kind_has_a_db_owner_or_a_known_shrinking_gap(self):
        kinds = coverage.registered()
        self.assertFalse(coverage.missing_claims(kinds))
        self.assertFalse(set(coverage.CLAIMS) & set(coverage.GAPS))
        self.assertFalse((set(coverage.CLAIMS) | set(coverage.GAPS)) - kinds)
        self.assertLessEqual(set(coverage.GAPS), coverage.INITIAL_GAPS)
        self.assertTrue(all(isinstance(reason, str) and reason.strip() for reason in coverage.GAPS.values()))
        self.assertEqual(coverage.missing_claims(kinds | {"new.production.operation"}), {"new.production.operation"})
        for module in sorted(set(coverage.CLAIMS.values())):
            with self.subTest(module=module):
                loaded = importlib.import_module(module)
                cases = [value for value in vars(loaded).values() if isinstance(value, type)
                         and value.__module__ == module and issubclass(value, db_support.DbTestCase)
                         and unittest.TestLoader().loadTestsFromTestCase(value).countTestCases()]
                self.assertTrue(cases, "A coverage claim needs actual DbTestCase tests")

    def test_ledger_is_shard_scoped_and_a_declaration_alone_never_passes(self):
        module = coverage.CLAIMS["dice.add"]
        self.assertIn("dice.add", coverage.unmet([module], {}))
        self.assertNotIn("dice.add", coverage.unmet([module], {module: {"dice.add"}}))
        self.assertEqual(coverage.unmet([], {}), {})

    def test_reader_module_docs_describe_the_database_without_live_inventory_file_paths(self):
        for relative in ("decks/__init__.py", "tokens/__init__.py", "accessories.py", "pool.py", "purchases.py"):
            with self.subTest(module=relative):
                doc = ast.get_docstring(ast.parse((coverage.ROOT / "lib" / relative).read_text(encoding="utf-8")))
                self.assertIn("PostgreSQL", doc)
                self.assertNotIn("magic/", doc)

    def test_observer_counts_changed_disposable_writes_only_after_a_passing_method(self):
        self.enterContext(mock.patch.object(coverage, "_observed", {}))
        coverage.reset()
        backend = object.__new__(pg.PgInventory)
        backend.dbname = db_support.PREFIX + "coverage_fixture"
        module = coverage.CLAIMS["dice.add"]
        op = inventory.Op("dice.add")
        before = SimpleNamespace(revision="1", decks_revision="1")
        after = SimpleNamespace(revision="2", decks_revision="1")
        self.enterContext(mock.patch.object(pg.PgInventory, "load", return_value=before))
        with mock.patch.object(pg.PgInventory, "apply", return_value=(after, inventory.Summary(changed={"dice": []}))):
            with coverage.observe(module, backend.dbname):
                backend.apply(op, None, "fixture")
        self.assertNotIn("dice.add", coverage.unmet([module]))
        coverage.reset()
        with mock.patch.object(pg.PgInventory, "apply", return_value=(before, inventory.Summary())):
            with coverage.observe(module, backend.dbname):
                backend.apply(op, None, "noop")
        self.assertIn("dice.add", coverage.unmet([module]))
        with mock.patch.object(pg.PgInventory, "apply", return_value=(after, inventory.Summary(changed={"dice": []}))):
            with self.assertRaises(AssertionError), coverage.observe(module, backend.dbname):
                backend.apply(op, None, "fixture")
                raise AssertionError("failed test")
        self.assertIn("dice.add", coverage.unmet([module]))
