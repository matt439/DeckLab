"""Recorded-count recovery against guarded disposable PostgreSQL fixtures only."""
import copy
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.db import conn as db
from decklab.lib import access, accessories, cards, config, inventory
from decklab.lib.api import accessory_undo as api
from decklab.lib.inventory import Op, accessory_undo as undo, pg
from decklab.lib.state import Actor
from decklab.lib.state import pg as state_pg
from decklab.tests import accessory_undo_support as fixture, db_support, household_config

ACTOR = Actor("matt", "Matt", source="web", via="tunnel")
TABLES = (*db_support.INVENTORY_TABLES, "collection_import_content", "inventory_revision", "decks_revision",
          "audit.change_set", "audit.row_change")
OMIT = object()


class AccessoryQuantityUndoPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-accessory-count-undo-pg-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Quantity Undo needs a disposable database")
        db_support.seed_membership(cls.dbname, household_config.PROFILES)

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(fixture.snapshot().replace(imports={}), ACTOR, "Seed disposable recorded counts",
                       contents={}, dbname=self.dbname, decks=True,
                       images={"a-sleeves.jpg": b"synthetic fixture picture",
                               "c-hidden.jpg": b"synthetic private picture"})
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))
        self.enterContext(access.using({"profile": "matt", "email": "matt@example.com", "remote": True}))

    def sql(self, statement, args=()):
        with self.connect("ro") as c:
            return c.execute(statement, args).fetchall()

    def persisted(self):
        return {table: self.sql(f"select row_to_json(t)::text from {table} t order by 1") for table in TABLES}

    def fresh(self):
        return pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker()).load()

    def edit(self, fields, rid="a-sleeves", owners=fixture.OWNERS):
        listing = accessories.from_sheet(self.fresh().accessories, strict=True)
        inventory.apply(Op("accessory.edit", {"id": rid, "row": fields, "image": "keep", "owners": owners,
            "sha256": accessories.view_sha256(listing, owners)}), ACTOR, "Correct a disposable recorded count")
        return self.sql("select max(id) from audit.change_set")[0][0]

    def add(self, kind, quantity=1):
        from decklab.tests.test_accessory_fetch import jpeg
        listing = accessories.from_sheet(self.fresh().accessories, strict=True)
        _, summary = inventory.apply(Op("accessory.add", {"row": {"kind": kind, "owner": "matt",
            "name": "Quantity fixture " + kind, "quantity": quantity, "capacity": "100" if kind == "deck_box" else ""},
            "owners": fixture.OWNERS, "image": jpeg(), "sha256": accessories.view_sha256(listing, fixture.OWNERS)}),
            ACTOR, "Add a photographed disposable count fixture")
        return summary.extra["id"]

    def apply(self, cid, preview, confirm_stock=True, **extra):
        body = {"profile": "matt", "id": cid, "expect": preview["expect"], **extra}
        if confirm_stock is not OMIT:
            body["confirm_stock"] = confirm_stock
        return api.apply_accessory_undo(json.dumps(body).encode())

    def assert_other_data(self, before, snapshot):
        after = self.persisted()
        for table in TABLES:
            if table not in ("accessory", "decks_revision", "audit.change_set", "audit.row_change"):
                self.assertEqual(after[table], before[table], table)
        self.assertEqual(self.fresh().accessory_images, snapshot.accessory_images)

    def test_held_sleeves_restore_shortage_without_moving_kit_or_fetching_photographs(self):
        self.edit({"quantity": "40"})
        cid = self.edit({"quantity": "100"})
        source, before, snapshot = self.backend.undo_audit(cid), self.persisted(), self.fresh()
        with inventory.pinned(snapshot):
            self.assertEqual(accessories.kit("casual/fixture", owners=fixture.OWNERS)["sleeves"]["id"], "a-sleeves")
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("No remote image")), \
                mock.patch.object(cards, "resolve", side_effect=AssertionError("No card enrichment")):
            preview = api.accessory_undo_view(cid)
            receipt = self.apply(cid, preview)
        self.assertEqual((preview["action"], preview["stock_confirmation_required"]), ("accessory_stock_update", True))
        self.assertEqual(preview["fields"], [{"field": "quantity", "before": "100", "after": "40"}])
        self.assertEqual(receipt["restored"], undo.stock_meta(source[0]["before"]))
        with inventory.pinned(self.fresh()):
            kit = accessories.kit("casual/fixture", owners=fixture.OWNERS)
        self.assertEqual((kit["need"], kit["short"], kit["sleeves"]["id"]), (60, 20, "a-sleeves"))
        self.assertTrue(any("40" in warning and "20" in warning for warning in kit["warnings"]))
        actual = self.backend.undo_audit(self.sql("select max(id) from audit.change_set")[0][0])
        self.assertEqual(len(actual), 1)
        self.assertEqual((actual[0]["table"], actual[0]["op"], actual[0]["before"], actual[0]["after"]),
                         ("accessory", "UPDATE", source[0]["after"], source[0]["before"]))
        self.assertEqual(receipt["revision"], str(actual[0]["id"]))
        self.assertEqual(self.backend.undo_audit(cid), source)
        self.assert_other_data(before, snapshot)

    def test_held_box_zero_count_remains_assigned_and_all_kinds_restore_zero_and_maximum(self):
        rid = self.add("deck_box", 0)
        cid = self.edit({"quantity": "1"}, rid)
        deck = self.fresh().deck("casual/fixture")
        inventory.apply(Op("kit.set", {"holders": [{"id": deck.id, "expected": deck.sha256}],
            "changes": [{"holder": deck.id, "field": "deck_box", "value": rid}], "owners": fixture.OWNERS}),
            ACTOR, "Assign a disposable counted box")
        before, snapshot = self.persisted(), self.fresh()
        receipt = self.apply(cid, api.accessory_undo_view(cid))
        self.assertEqual(receipt["restored"]["quantity"], "0")
        with inventory.pinned(self.fresh()):
            kit = accessories.kit("casual/fixture", owners=fixture.OWNERS)
        self.assertEqual((kit["deck_box"]["id"], kit["deck_box"]["quantity"]), (rid, 0))
        self.assertTrue(any("0 are recorded" in warning for warning in kit["warnings"]))
        self.assert_other_data(before, snapshot)
        for kind in ("sleeves", "deck_box", "playmat"):
            target = "a-sleeves" if kind == "sleeves" else rid if kind == "deck_box" else self.add(kind)
            for historical in ("0", "9999", "1"):
                self.edit({"quantity": historical, "notes": "Historical count note"}, target)
                cid = self.edit({"quantity": "2", "notes": "Changed count note"}, target)
                source, before, snapshot = self.backend.undo_audit(cid), self.persisted(), self.fresh()
                preview = api.accessory_undo_view(cid)
                self.assertEqual([field["field"] for field in preview["fields"]], ["notes", "quantity"])
                self.assertEqual(self.apply(cid, preview)["restored"], undo.stock_meta(source[0]["before"]))
                self.assert_other_data(before, snapshot)

    def test_consent_is_exact_action_specific_and_owner_proof_precedes_bad_flags(self):
        cid = self.edit({"quantity": "99"})
        preview, before = api.accessory_undo_view(cid), self.persisted()
        for value in (OMIT, None, False, 1, "true", [], {}):
            with self.subTest(consent=value), self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, confirm_stock=value)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        for extra in ({"reason": None}, {"reason": "Count correction"}, {"confirm_restore": True}, {"confirm_restore": None}):
            with self.subTest(extra=extra), self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, **extra)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}), \
                self.assertRaises(api.ApiError) as hidden:
            api.apply_accessory_undo(json.dumps({"profile": "user1", "id": cid, "expect": "bad", "confirm_stock": None}).encode())
        self.assertEqual((hidden.exception.status, hidden.exception.message), (404, api.NO_CHANGE))
        self.assertEqual(self.persisted(), before)
        cid = self.edit({"notes": "Only metadata"})
        preview, before = api.accessory_undo_view(cid), self.persisted()
        for value in (True, None, False):
            with self.subTest(metadata_consent=value), self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, confirm_stock=value)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)

    def test_noncanonical_historical_quantities_are_not_normalized_or_saved(self):
        for invalid in ("00", "01", " 40 ", "+40", "-1", "10000", "unknown"):
            for quantity in (invalid, "100"):
                with self.connect() as connection, db.change(ACTOR.id, ACTOR.source, "Imperfect disposable count history",
                                                            conn=connection, via=ACTOR.via) as (cur, cid):
                    pg._take_lock(cur)
                    cur.execute("update accessory set quantity=%s where id='a-sleeves'", (quantity,))
                    cur.execute("update decks_revision set revision=revision+1")
            before = self.persisted()
            self.assertIs(api.accessory_undo_view(cid)["available"], False)
            with self.assertRaises(api.ApiError) as error:
                self.apply(cid, {"expect": "bad"})
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)

    def test_wrong_actual_quantity_rolls_back_stock_and_audit_then_same_review_can_save(self):
        cid = self.edit({"quantity": "80", "notes": "Changed count"})
        preview, before, snapshot = api.accessory_undo_view(cid), self.persisted(), self.fresh()
        original = undo.verify_saved
        def wrong(old, after, plan, actual):
            actual = copy.deepcopy(actual)
            actual[0]["after"]["quantity"] = "9999"
            return original(old, after, plan, actual)
        with mock.patch.object(undo, "verify_saved", side_effect=wrong), self.assertRaises(api.ApiError) as error:
            self.apply(cid, preview)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.fresh(), snapshot)
        self.assertEqual(self.apply(cid, preview)["restored"], preview["restored"])

    def test_direct_stock_operation_with_unreviewed_audit_reason_rolls_back_before_normal_retry(self):
        cid = self.edit({"quantity": "80"})
        preview, before, snapshot = api.accessory_undo_view(cid), self.persisted(), self.fresh()
        operation = undo.MetadataRestore(cid, fixture.OWNERS, preview["expect"], store=self.backend, confirm_stock=True)
        with self.assertRaises(inventory.Conflict):
            inventory.apply(operation, ACTOR, "Direct disposable stock recovery", reason="Unreviewed fixture reason")
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.fresh(), snapshot)
        self.assertEqual(self.apply(cid, preview)["restored"], preview["restored"])
        self.assertEqual(self.sql("select reason from audit.change_set order by id desc limit 1"), [(None,)])

    def test_scoped_preview_survives_hidden_owner_edit_but_not_visible_change_or_target_aba(self):
        cid = self.edit({"quantity": "80"})
        preview = api.accessory_undo_view(cid)
        self.edit({"quantity": "3"}, "c-hidden", frozenset({"user1", "shared"}))
        self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
        self.edit({"notes": "Shared visible correction"}, "b-shared")
        before = self.persisted()
        with self.assertRaises(api.ApiError) as stale:
            self.apply(cid, preview)
        self.assertEqual(stale.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        fresh_preview = api.accessory_undo_view(cid)
        self.assertNotEqual(fresh_preview["expect"], preview["expect"])
        self.edit({"quantity": "79"})
        self.edit({"quantity": "80"})
        before = self.persisted()
        with self.assertRaises(api.ApiError) as aba:
            self.apply(cid, fresh_preview)
        self.assertEqual(aba.exception.status, 409)
        self.assertEqual(self.persisted(), before)
