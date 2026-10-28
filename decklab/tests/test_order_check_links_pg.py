"""Arrival-check row proofs and old schemas in guarded disposable databases only."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.db import conn as db, migrate
from decklab.lib import config, inventory
from decklab.lib.api import receipts, shopping, shopping_order_changes as api
from decklab.lib.inventory import Op, Summary, check_links, files, orders, pg, rules
from decklab.lib.state import Invalid
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests import test_shopping_order_changes as fixture
from decklab.tests.test_order_check_links import OrderCheckLinksTests
from decklab.tests.test_inventory_orders import CLAUDE


class CheckLinksPgBase(db_support.DbTestCase):
    setUp = fixture.PgOrderChangeApiTests.setUp
    start = fixture.OrderChangeApiTests.start
    request = fixture.OrderChangeApiTests.request
    checks = fixture.OrderChangeApiTests.checks
    save = fixture.OrderChangeApiTests.save
    refused = fixture.OrderChangeApiTests.refused

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        folder = tempfile.TemporaryDirectory(prefix="decklab-check-links-pg-", dir=root)
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": contract.FIXTURE_PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Arrival-check tests require a disposable database")
        db_support.seed_membership(cls.dbname, contract.FIXTURE_PROFILES)


class PgOrderCheckLinksContractTests(OrderCheckLinksTests, CheckLinksPgBase):
    """The sixteen new API/lifecycle cases over actual PostgreSQL storage."""


class OrderCheckLinksPgTests(CheckLinksPgBase):
    def component(self):
        return orders._component(self.backend.load(), fixture.ORDER, "cards")[1]

    def rows(self):
        component = self.component()
        return [{key: row.text(key) for key in rules.FIELDS} for row in self.backend.load().payloads[component.path].rows]

    def target(self, row=1):
        return {"row": row, "payload_sha256": check_links.digest(self.rows(), rules.FIELDS)}

    def link(self, text="Inspect this exact row", row=1):
        return self.save(self.checks(component="cards", add=[text], target=self.target(row))["preview"])

    def state(self):
        with self.connect("ro") as c:
            tables = (*pg.INVENTORY_TABLES, "deck", "deck_text", "deck_revision", "inventory_revision", "decks_revision", "audit.change_set", "audit.row_change")
            return {table: c.execute(f"select row_to_json(t)::text from {table} t order by 1").fetchall() for table in tables}

    def test_targeted_web_write_is_one_component_audit_and_exact_roundtrip_export(self):
        before, stock = self.state(), self.rows()
        saved = self.link(row=2)
        metadata = self.component().check_links
        self.assertEqual(saved["targeted_check"], {"component": "cards", "check": 3, "text": "Inspect this exact row",
            "row": 2, "row_sha256": check_links.row_digest(stock[1], rules.FIELDS),
            "payload_sha256": check_links.digest(stock, rules.FIELDS)})
        self.assertEqual(self.component().checks, ["Record conditions", "Check languages", "Inspect this exact row"])
        self.assertEqual(self.rows(), stock)
        with self.connect("ro") as c:
            actual = c.execute("select checks,check_links from order_component where order_id=%s and id='cards'", (fixture.ORDER,)).fetchone()
            self.assertEqual(actual, (self.component().checks, metadata))
            self.assertEqual(c.execute("select actor,source,via from audit.change_set order by id desc limit 1").fetchone(), ("matt", "web", "tunnel"))
            audit = c.execute("select table_name,op from audit.row_change where change_set_id=(select max(id) from audit.change_set)").fetchall()
            self.assertEqual(audit, [("order_component", "UPDATE")])
            from decklab.db import export
            exported = export.inventory_files(c)
        record = json.loads(exported[f"magic/orders/records/{fixture.ORDER}.json"])
        self.assertEqual(record["components"][0]["check_links"], metadata)
        written = self.state()
        for table in before:
            if table not in {"order_component", "inventory_revision", "audit.change_set", "audit.row_change"}:
                self.assertEqual(written[table], before[table], table)
        self.assertNotEqual(receipts.fingerprint(self.backend.load().revision), receipts.fingerprint(saved["revision"] + "old"))

    def test_preview_and_apply_stale_guards_and_late_sql_failure_leave_everything_unchanged(self):
        preview = self.checks(component="cards", add=["Inspect target"], target=self.target())
        self.save(self.checks(component="cards", add=["Unrelated general check"])["preview"])
        before = self.state()
        with self.assertRaises(api.ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.state(), before)
        preview = self.checks(component="cards", add=["Inspect target"], target=self.target())
        original = pg._diff
        def late(*args):
            original(*args)
            raise Invalid("Synthetic late check-link SQL failure")
        before = self.state()
        with mock.patch.object(pg, "_diff", side_effect=late), self.assertRaises(api.ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.state(), before)
        self.assertTrue(self.save(preview["preview"])["saved"])

    def test_source_and_capability_queries_reuse_applying_connection_and_withdraw_reindexes_duplicates(self):
        self.link(text="Duplicate check")
        self.link(text="Duplicate check", row=2)
        old = self.component()
        self.assertEqual([link["check"] for link in old.check_links["links"]], [3, 4])
        preview = self.checks(component="cards", add=["Third target"], target=self.target())
        original = self.backend._call
        def no_nested(work):
            self.assertIsNone(getattr(self.backend._applying, "connection", None), "Target check opened a nested connection")
            return original(work)
        with mock.patch.object(self.backend, "_call", side_effect=no_nested):
            self.save(preview["preview"])
        self.save(self.checks(component="cards", withdraw=[3])["preview"])
        component = self.component()
        self.assertEqual(component.checks[2:], ["Duplicate check", "Third target"])
        self.assertEqual([link["check"] for link in component.check_links["links"]], [3, 4])
        self.assertEqual(component.check_links["links"][0]["row"], 2)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_malformed_unknown_metadata_stays_general_and_keeps_check_strings(self):
        original = list(self.component().checks)
        with self.connect("owner") as c:
            with db.change("claude", "test", "Fixture future check metadata", conn=c) as (cur, _):
                cur.execute("update order_component set check_links=%s::jsonb where order_id=%s and id='cards'", ('{"version":99,"links":["opaque"]}', fixture.ORDER))
                cur.execute("update inventory_revision set revision=revision+1")
        shown = shopping.shopping_overview()
        component = next(c for o in shown["orders"] if o["id"] == fixture.ORDER for c in o["components"] if c["id"] == "cards")
        self.assertEqual(component["check_targets"], [None, None])
        self.assertNotIn("check_links", component)
        board = receipts.receipt_view(fixture.ORDER)
        self.assertEqual(board["components"][0]["check_targets"], [None, None])
        self.assertNotIn("check_links", board["components"][0])
        self.save(self.checks(component="cards", add=["Another general check"])["preview"])
        self.assertEqual(self.component().checks, [*original, "Another general check"])
        self.assertIsNone(self.component().check_links)

    def test_schema14_general_io_survives_and_targeted_write_refuses_until_migrated(self):
        self.legacy_schema(14)

    def test_schema13_general_io_survives_and_targeted_write_refuses_until_migrated(self):
        self.legacy_schema(13)

    def legacy_schema(self, version):
        self.assertTrue(self.dbname.startswith(db_support.PREFIX))
        self.addCleanup(migrate.apply, dbname=self.dbname)
        with self.connect("owner") as c:
            c.execute("alter table order_component drop column check_links")
            c.execute("alter table collection_card drop column location")      # 0016 comes after too
            if version == 13:
                c.execute("alter table product_status drop column token_cards")
            c.execute("delete from schema_migration where version>%s", (version,))
        self.assertFalse(self.backend.supports_check_links())
        self.save(self.checks(component="cards", add=["General legacy check"])["preview"])
        self.assertIn("General legacy check", self.component().checks)
        self.assertIsNone(self.component().check_links)
        board = receipts.receipt_view(fixture.ORDER)
        self.assertFalse(board["components"][0]["check_targeting"]["available"])
        self.assertEqual(board["components"][0]["check_targets"], [None] * len(self.component().checks))
        before = self.state()
        with self.assertRaises(api.ApiError) as caught:
            self.checks(component="cards", add=["Target unavailable"], target=self.target())
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("migration 0015", caught.exception.message)
        self.assertEqual(self.state(), before)
        component, rows = self.component(), self.rows()
        metadata = check_links.append(component, rows, rules.FIELDS, "Bypass fixture", self.target())
        class Mixed:
            kind = "fixture.check-links-preflight"
            def run(self, snapshot):
                after = snapshot.update_component(fixture.ORDER, "cards", checks=[*component.checks, "Bypass fixture"], check_links=metadata)
                collection = [dict(row.as_dict(), notes="Should roll back") for row in snapshot.collection("home").rows]
                return after.with_collection("home", collection), Summary("Fixture unsupported mixed write")
        with self.assertRaisesRegex(Invalid, "migration 0015"):
            inventory.apply(Mixed(), CLAUDE, "Unsupported mixed metadata fixture")
        self.assertEqual(self.state(), before)
        with self.connect("owner") as c:
            from decklab.db import export
            self.assertIn(f"magic/orders/records/{fixture.ORDER}.json", export.inventory_files(c))
        migrate.apply(dbname=self.dbname)
        self.assertTrue(self.backend.supports_check_links())
        self.assertTrue(self.link()["saved"])
