"""Whole product-only kit source and exact precommit proof on disposable PostgreSQL."""
import copy
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import access, config, inventory
from decklab.lib.api import product_kit_undo as api
from decklab.lib.inventory import Op, Summary, kit, pg, product_kit_undo as undo
from decklab.lib.state import Actor, pg as state_pg
from decklab.tests import db_support, household_config, product_kit_undo_support as fixture
from decklab.tests.test_goldfish import setUpModule, tearDownModule  # noqa: F401

ACTOR = Actor("matt", "Matt", source="web", via="tunnel")
TABLES = (*db_support.INVENTORY_TABLES, "inventory_revision", "decks_revision", "audit.change_set", "audit.row_change")


class ProductKitUndoPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-product-kit-undo-pg-"); cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start(); cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Product-kit recovery needs a disposable database")
        db_support.seed_membership(cls.dbname, household_config.PROFILES)

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(fixture.snapshot(), ACTOR, "Seed synthetic product-kit records", contents={}, dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))
        self.enterContext(access.using({"profile": "matt", "email": "matt@example.com", "remote": True}))

    def sql(self, statement, args=()):
        with self.connect("ro") as connection:
            return connection.execute(statement, args).fetchall()

    def persisted(self):
        return {table: self.sql(f"select row_to_json(t)::text from {table} t order by 1") for table in TABLES}

    def assign(self, swap):
        snapshot = self.backend.load()
        token = kit.status_sha256(snapshot)
        holders = [{"id": "product/" + stem, "expected": token} for stem in ("alpha", "beta")]
        changes = [{"holder": "product/" + stem, "field": field, "value": "shared-" + ("sleeves-" if field == "sleeves" else "box-") + letter}
                   for stem, letter in (("alpha", "a" if swap else "b"), ("beta", "b" if swap else "a")) for field in kit.FIELDS]
        inventory.apply(Op("kit.set", {"holders": holders, "changes": changes, "owners": fixture.OWNERS}), ACTOR, "Move synthetic shared product kit")
        return self.sql("select max(id) from audit.change_set")[0][0]

    def source(self):
        self.assign(True)
        return self.assign(False)

    def test_pre_0014_audit_rows_restore_with_the_known_blank_token_default(self):
        with self.connect("owner") as connection:
            db_support.roll_back_schema(connection, 13)
        source = self.source()
        old_rows = self.backend.undo_audit_batch(source)
        self.assertTrue(old_rows)
        self.assertTrue(all("token_cards" not in row["before"] and "token_cards" not in row["after"] for row in old_rows))
        preview = api.view(str(source))
        result = self.apply(source, preview)
        self.assertTrue(result["saved"])
        self.assertEqual(self.backend.undo_audit_batch(source), old_rows)

    def apply(self, cid, preview, **extra):
        return api.apply(json.dumps({"profile": "matt", "id": cid, "expect": preview["expect"], "confirm_kit": True, **extra}))

    def test_two_product_swap_restores_only_status_kit_with_exact_new_opposite_audit_rows(self):
        cid = self.source()
        before, source = self.persisted(), self.backend.undo_audit_batch(cid)
        preview = api.view(cid)
        result = self.apply(cid, preview)
        self.assertEqual(result["row_count"], 2)
        actual = self.backend.undo_audit_batch(self.sql("select max(id) from audit.change_set")[0][0])
        self.assertEqual(len(actual), 2)
        original = {row["key"]["file"]: row for row in source}
        self.assertTrue(all(row["id"] > max(item["id"] for item in source) for row in actual))
        for row in actual:
            old = original[row["key"]["file"]]
            self.assertEqual((row["table"], row["op"], row["before"], row["after"]), (undo.TABLE, "UPDATE", old["after"], old["before"]))
        after = self.persisted()
        for table in TABLES:
            if table not in (undo.TABLE, "inventory_revision", "audit.change_set", "audit.row_change"):
                self.assertEqual(before[table], after[table], table)
        self.assertEqual(self.sql("select reason from audit.change_set order by id desc limit 1"), [(None,)])

    def test_older_product_set_kit_source_is_supported_when_recognised_and_owned(self):
        snapshot = self.backend.load()
        inventory.apply(Op(kit.KIND, {"sha256": kit.status_sha256(snapshot), "hold": "alpha", "changes": [
            {"stem": "alpha", "field": "sleeves", "value": "shared-sleeves-a"}]}), ACTOR, "Correct one legacy synthetic kit record")
        cid = self.sql("select max(id) from audit.change_set")[0][0]
        preview = api.view(cid)
        self.assertEqual(preview["row_count"], 1)
        self.apply(cid, preview)

    def test_changed_later_even_if_returned_to_same_kit_or_unchecked_consent_refuses(self):
        cid = self.source(); preview = api.view(cid); before = self.persisted()
        for value in (False, None, 1):
            with self.assertRaises(api.ApiError) as refused:
                self.apply(cid, preview, confirm_kit=value)
            self.assertEqual(refused.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        self.assign(True); self.assign(False)
        before = self.persisted()
        with self.assertRaises(api.ApiError) as changed:
            api.view(cid)
        self.assertEqual(changed.exception.status, 409)
        self.assertEqual(self.persisted(), before)

    def test_wrong_uncommitted_audit_reason_row_or_source_id_rolls_back_whole_inverse(self):
        cid = self.source(); preview = api.view(cid); before = self.persisted(); original = undo.confirm
        for mode in ("row", "id", "reason", "partial"):
            def changed(old, saved, summary, actual, reason):
                actual = copy.deepcopy(actual)
                if mode == "row": actual[0]["after"]["notes"] = "Unexpected"
                if mode == "id": actual[0]["id"] = 1
                if mode == "partial": actual.pop()
                return original(old, saved, summary, actual, "Unexpected" if mode == "reason" else reason)
            with self.subTest(mode=mode), mock.patch.object(undo, "confirm", side_effect=changed), self.assertRaises(api.ApiError) as refused:
                self.apply(cid, preview)
            self.assertEqual(refused.exception.status, 409)
            self.assertEqual(self.persisted(), before)

    def test_mixed_other_table_source_never_allows_partial_status_inverse(self):
        owner = self
        class Mixed:
            kind = "fixture.product-kit-mixed"
            def run(self, snapshot):
                after, summary = Op(kit.KIND, {"changes": [{"stem": "alpha", "field": "sleeves", "value": "shared-sleeves-a"}]}).run(snapshot)
                rows = [{**row.as_dict(), "notes": "Other audit row"} if row.accessory_id == "shared-sleeves-a" else row.as_dict()
                        for row in after.accessories.rows]
                return after.with_accessories(rows), Summary("Mixed synthetic kit source", summary.counts, summary.changed)
        inventory.apply(Mixed(), ACTOR, "Mixed synthetic source")
        cid = self.sql("select max(id) from audit.change_set")[0][0]
        before = owner.persisted()
        with self.assertRaises(api.ApiError) as refused:
            api.view(cid)
        self.assertEqual(refused.exception.status, 404)
        self.assertEqual(self.persisted(), before)
