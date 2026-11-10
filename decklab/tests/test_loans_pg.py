"""Loan records, inventory revision and audit commit/rollback together in disposable PostgreSQL."""
import json
import os
from pathlib import Path
import tempfile
from unittest import mock

from decklab.db import check, export, space_export, space_remove
from decklab.lib import config, inventory, pool
from decklab.lib.api import collection_loans as loans
from decklab.lib.inventory import files, ops_loans, pg, pg_loans
from decklab.tests import db_support
from decklab.tests import test_collection_edit as support
from decklab.tests import test_precon_tokens_pg as fixture
from decklab.tests.test_loans import facts


class LoanPgTests(db_support.DbTestCase):
    setUp = fixture.PreconTokensPgTests.setUp
    fresh = fixture.PreconTokensPgTests.fresh
    sql = fixture.PreconTokensPgTests.sql

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-loans-pg-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(support.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Loans integration requires a disposable test database")
        db_support.seed_membership(cls.dbname, support.ROLES["profiles"])

    def persisted(self):
        with self.connect("ro") as connection:
            return {table: connection.execute(f"select row_to_json(t)::text from {table} t order by 1").fetchall()
                    for table in ("card_loan", "collection_card", "inventory_revision", "decks_revision", "deck", "deck_text",
                                  "deck_revision", "deck_line", "audit.change_set", "audit.row_change")}

    def lend(self):
        return self.case.call(loans.lend, "user2", space="user2", row=facts(), sha256=self.case.rows("user2")["sha256"])

    def returned(self, made):
        return self.case.call(loans.return_loan, "user2", space="user2", loan_id=made["loan"]["id"], returned_on="2026-11-12")

    def test_lend_and_return_save_one_audit_each_keep_ownership_and_roundtrip_private_export(self):
        before, snapshot = self.persisted(), self.fresh()
        made = self.lend()
        after = self.persisted()
        self.assertEqual(len(after["audit.change_set"]), len(before["audit.change_set"]) + 1)
        self.assertEqual(after["collection_card"], before["collection_card"])
        self.assertEqual(self.fresh().collection("home"), snapshot.collection("home"))
        for table in ("deck", "deck_text", "deck_revision", "deck_line", "decks_revision"):
            self.assertEqual(after[table], before[table], table)
        self.assertEqual(self.sql("select distinct table_name from audit.row_change where change_set_id = "
                                  "(select max(id) from audit.change_set)"), [("card_loan",)])
        with inventory.pinned(self.fresh()):
            self.assertEqual(pool.free_copies(pool.load_pool("user2"))["Llanowar Elves"], 1)
        with self.connect("ro") as connection:
            exported = export.inventory_files(connection)
            self.assertIn("magic/people/user2/loans.csv", exported)
            self.assertEqual(files.build(exported).loans, self.fresh().loans)
            self.assertTrue(check._round_trip(connection, self.fresh())()[0])
            member_files, _, data = space_export.snapshot(connection, "user2", details=True)
            self.assertIn("loans.csv", member_files)
            self.assertEqual(len(data["loans"]), 1)
            keys = space_remove._TABLE_KEYS["loans"]
            self.assertEqual(keys, ("card_loan", ("space_id", "id")))
        result = self.returned(made)
        self.assertTrue(result["ok"])
        final = self.persisted()
        self.assertEqual(len(final["audit.change_set"]), len(before["audit.change_set"]) + 2)
        self.assertEqual(final["collection_card"], before["collection_card"])
        with inventory.pinned(self.fresh()):
            self.assertEqual(pool.free_copies(pool.load_pool("user2"))["Llanowar Elves"], 2)
        self.assertFalse((self.case.box.magic / "people/user2/loans.csv").exists())

    def test_injected_late_database_failure_rolls_back_lend_and_return_records_revision_and_audit(self):
        original = pg._diff
        def fail(*args):
            original(*args)
            raise RuntimeError("Injected loan transaction failure")
        before = self.persisted()
        with mock.patch.object(pg, "_diff", side_effect=fail), self.assertRaisesRegex(Exception, "Injected loan transaction"):
            self.lend()
        self.assertEqual(self.persisted(), before)
        made = self.lend()
        before = self.persisted()
        with mock.patch.object(pg, "_diff", side_effect=fail), self.assertRaisesRegex(Exception, "Injected loan transaction"):
            self.returned(made)
        self.assertEqual(self.persisted(), before)

    def test_old_schema_compatibility_refuses_records_instead_of_dropping_them(self):
        self.assertFalse(pg_loans.compatible({"card_loan": {}}, False)["card_loan"])
        with self.assertRaisesRegex(inventory.Invalid, "migration 0024"):
            pg_loans.compatible({"card_loan": {("user2", "a" * 32): ()}}, False)
        before = self.fresh()
        with self.assertRaisesRegex(inventory.Invalid, "migration 0024"):
            ops_loans.op("lend", space="user2", row=facts()).run(before.replace(loans_ready=False))
        self.assertEqual(self.fresh(), before)

    def test_collection_reduction_refusal_preserves_loan_revision_and_audit(self):
        made = self.lend()
        before = self.persisted()
        with self.assertRaisesRegex(inventory.Invalid, "still lent out"):
            inventory.apply(inventory.Op("collection.remove", {"space": "user2", "original": ["fdn", "227", "nonfoil"]}),
                            fixture.ACTOR, "Refuse removing a lent printing")
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.fresh().loan_set("user2").rows[0].get("id"), made["loan"]["id"])
