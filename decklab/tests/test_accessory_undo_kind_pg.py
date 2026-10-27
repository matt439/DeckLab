"""Unused accessory-kind recovery in guarded disposable PostgreSQL fixtures."""
import copy
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import mock

from decklab.db import conn as db
from decklab.lib import access, accessories, config, inventory
from decklab.lib.api import accessory_undo as api
from decklab.lib.inventory import Op, accessory_undo as undo, pg, rules
from decklab.lib.state import Actor
from decklab.lib.state import pg as state_pg
from decklab.tests import accessory_undo_support as fixture, db_support, household_config

ACTOR = Actor("matt", "Matt", source="web", via="tunnel")
TABLES = (*db_support.INVENTORY_TABLES, "collection_import_content", "inventory_revision", "decks_revision",
          "visibility", "audit.change_set", "audit.row_change")
OMIT = object()


class AccessoryKindUndoPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-accessory-kind-undo-pg-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Kind recovery needs a disposable database")
        db_support.seed_membership(cls.dbname, household_config.PROFILES)

    def setUp(self):
        db_support.reset(self.dbname, (*db_support.INVENTORY_TABLES, "visibility"))
        initial = fixture.snapshot().replace(imports={})
        deck = initial.deck("casual/fixture")
        initial = initial.with_deck(replace(deck, text=deck.text.replace("- **Sleeves:** a-sleeves\n", "")))
        pg.write_model(initial, ACTOR, "Seed unused photographed kind fixture", contents={}, dbname=self.dbname,
                       decks=True, images={"a-sleeves.jpg": b"synthetic fixture picture",
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
            "sha256": accessories.view_sha256(listing, owners)}), ACTOR, "Correct a disposable accessory kind")
        return self.sql("select max(id) from audit.change_set")[0][0]

    def add(self, kind, quantity=1, name=None):
        from decklab.tests.test_accessory_fetch import jpeg
        listing = accessories.from_sheet(self.fresh().accessories, strict=True)
        _, summary = inventory.apply(Op("accessory.add", {"row": {"kind": kind, "owner": "matt",
            "name": name or "Kind fixture " + kind, "quantity": quantity, "capacity": "100" if kind == "deck_box" else "",
            "crop": "0.1,0.1,0.8,0.8", "notes": "Historical kind note"},
            "owners": fixture.OWNERS, "image": jpeg(), "sha256": accessories.view_sha256(listing, fixture.OWNERS)}),
            ACTOR, "Add unused photographed kind fixture")
        return summary.extra["id"]

    def apply(self, cid, preview, confirm_kind=True, **extra):
        body = {"profile": "matt", "id": cid, "expect": preview["expect"], **extra}
        if confirm_kind is not OMIT:
            body["confirm_kind"] = confirm_kind
        return api.apply_accessory_undo(json.dumps(body).encode())

    def kit(self, rid, field="sleeves"):
        deck = self.fresh().deck("casual/fixture")
        return inventory.apply(Op("kit.set", {"holders": [{"id": deck.id, "expected": deck.sha256}],
            "changes": [{"holder": deck.id, "field": field, "value": rid}], "owners": fixture.OWNERS}),
            ACTOR, "Assign a disposable kit fixture")

    def assert_other_data(self, before, snapshot):
        after = self.persisted()
        for table in TABLES:
            if table not in ("accessory", "decks_revision", "audit.change_set", "audit.row_change"):
                self.assertEqual(after[table], before[table], table)
        self.assertEqual(self.fresh().accessory_images, snapshot.accessory_images)

    def test_all_six_directed_kind_pairs_sort_full_stock_and_preserve_photos_crop_and_zero_quantities(self):
        self.add("deck_box", name="A box survivor")
        self.add("playmat", name="A playmat survivor")
        for historical in accessories.KINDS:
            for current in accessories.KINDS:
                if current == historical:
                    continue
                quantity = 0 if historical == "deck_box" or current == "sleeves" else 100
                rid = self.add(historical, quantity, "Middle " + historical + " to " + current)
                cid = self.edit({"kind": current, "capacity": "40" if current == "deck_box" else "",
                                 "notes": "Changed kind note"}, rid)
                source, before, snapshot = self.backend.undo_audit(cid), self.persisted(), self.fresh()
                preview = api.accessory_undo_view(cid)
                self.assertEqual((preview["action"], preview["kind_confirmation_required"]), ("accessory_kind_update", True))
                self.assertEqual(preview["fields"][0], {"field": "kind", "before": current, "after": historical})
                self.assertEqual((preview["current"]["quantity"], preview["restored"]["quantity"]), (str(quantity), str(quantity)))
                self.assertEqual(len(preview["restored"]), 11)
                receipt = self.apply(cid, preview)
                self.assertEqual(receipt["restored"], undo.stock_meta(source[0]["before"]))
                expected = sorted([source[0]["before"] if row["id"] == rid else row for row in undo.raw_rows(snapshot)],
                                  key=rules.accessory_sort_key)
                self.assertEqual(undo.raw_rows(self.fresh()), expected)
                self.assertEqual({row["id"]: row for row in undo.raw_rows(self.fresh()) if row["id"] != rid},
                                 {row["id"]: row for row in undo.raw_rows(snapshot) if row["id"] != rid})
                actual = self.backend.undo_audit(self.sql("select max(id) from audit.change_set")[0][0])
                self.assertEqual(len(actual), 1)
                self.assertEqual((actual[0]["op"], actual[0]["before"], actual[0]["after"]),
                                 ("UPDATE", source[0]["after"], source[0]["before"]))
                self.assertEqual(receipt["revision"], str(actual[0]["id"]))
                self.assertEqual(self.backend.undo_audit(cid), source)
                self.assert_other_data(before, snapshot)

    def test_target_kit_race_refuses_but_unrelated_known_kit_edit_preserves_preview(self):
        rid = self.add("playmat")
        cid = self.edit({"kind": "deck_box", "capacity": "100"}, rid)
        preview = api.accessory_undo_view(cid)
        self.kit("b-shared")
        self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
        known = self.fresh()
        self.apply(cid, preview)
        self.assertEqual(self.fresh().decks, known.decks)
        cid = self.edit({"kind": "deck_box", "capacity": "100"}, rid)
        preview = api.accessory_undo_view(cid)
        self.kit(rid, "deck_box")
        before = self.persisted()
        with self.assertRaises(api.ApiError) as error:
            self.apply(cid, preview)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        with self.assertRaises(api.ApiError) as held:
            api.accessory_undo_view(cid)
        self.assertEqual(held.exception.status, 409)

    def test_exact_kind_consent_and_cross_action_flags_refuse_before_writes_with_owner_privacy(self):
        cid = self.edit({"kind": "playmat"})
        preview, before = api.accessory_undo_view(cid), self.persisted()
        for value in (OMIT, None, False, 1, "true", [], {}):
            with self.subTest(consent=value), self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, confirm_kind=value)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        for flag in ("reason", "confirm_restore", "confirm_stock", "confirm_owner"):
            for value in (None, True):
                with self.subTest(flag=flag, value=value), self.assertRaises(api.ApiError) as error:
                    self.apply(cid, preview, **{flag: value})
                self.assertEqual(error.exception.status, 400)
                self.assertEqual(self.persisted(), before)
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}), \
                self.assertRaises(api.ApiError) as hidden:
            api.apply_accessory_undo(json.dumps({"profile": "user1", "id": cid, "expect": "bad", "confirm_kind": None}).encode())
        self.assertEqual((hidden.exception.status, hidden.exception.message), (404, api.NO_CHANGE))
        self.assertEqual(self.persisted(), before)
        cid = self.edit({"notes": "Metadata only"})
        preview, before = api.accessory_undo_view(cid), self.persisted()
        for value in (True, False, None):
            with self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, confirm_kind=value)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)

    def test_mixed_owner_or_quantity_and_noncanonical_historical_capacity_never_restore_partly(self):
        for fields in ({"kind": "playmat", "quantity": "99"},
                       {"kind": "deck_box", "capacity": "100", "owner": "shared"}):
            cid = self.edit(fields)
            before = self.persisted()
            self.assertIs(api.accessory_undo_view(cid)["available"], False)
            with self.assertRaises(api.ApiError) as error:
                self.apply(cid, {"expect": "bad"})
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        for invalid in ("0", "01", " 40 ", "+40", "10000"):
            with self.connect() as connection, db.change(ACTOR.id, ACTOR.source, "Malformed disposable kind history",
                                                        conn=connection, via=ACTOR.via) as (cur, _):
                pg._take_lock(cur)
                cur.execute("update accessory set kind='deck_box',capacity=%s where id='a-sleeves'", (invalid,))
                cur.execute("update decks_revision set revision=revision+1")
            with self.connect() as connection, db.change(ACTOR.id, ACTOR.source, "Current disposable kind history",
                                                        conn=connection, via=ACTOR.via) as (cur, cid):
                pg._take_lock(cur)
                cur.execute("update accessory set kind='playmat',capacity='' where id='a-sleeves'")
                cur.execute("update decks_revision set revision=revision+1")
            before = self.persisted()
            self.assertIs(api.accessory_undo_view(cid)["available"], False)
            with self.assertRaises(api.ApiError) as error:
                self.apply(cid, {"expect": "bad"})
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)

    def test_wrong_actual_kind_and_unreviewed_audit_reason_roll_back_then_same_preview_saves(self):
        cid = self.edit({"kind": "playmat"})
        preview, before, snapshot = api.accessory_undo_view(cid), self.persisted(), self.fresh()
        original = undo.verify_saved
        def wrong(old, after, plan, actual):
            actual = copy.deepcopy(actual)
            actual[0]["after"]["kind"] = "playmat"
            return original(old, after, plan, actual)
        with mock.patch.object(undo, "verify_saved", side_effect=wrong), self.assertRaises(api.ApiError) as error:
            self.apply(cid, preview)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.fresh(), snapshot)
        operation = undo.MetadataRestore(cid, fixture.OWNERS, preview["expect"], store=self.backend, confirm_kind=True)
        with self.assertRaises(inventory.Conflict):
            inventory.apply(operation, ACTOR, "Direct disposable kind recovery", reason="Unreviewed fixture reason")
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.fresh(), snapshot)
        self.assertEqual(self.apply(cid, preview)["restored"], preview["restored"])
        self.assertEqual(self.sql("select reason from audit.change_set order by id desc limit 1"), [(None,)])

    def test_hidden_owner_sort_movement_does_not_stale_but_visible_change_and_target_aba_do(self):
        cid = self.edit({"kind": "playmat"})
        preview = api.accessory_undo_view(cid)
        self.edit({"kind": "playmat"}, "c-hidden", frozenset({"user1", "shared"}))
        self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
        self.edit({"kind": "deck_box", "capacity": "100"}, "b-shared")
        before = self.persisted()
        with self.assertRaises(api.ApiError) as stale:
            self.apply(cid, preview)
        self.assertEqual(stale.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        self.edit({"kind": "sleeves"})
        self.edit({"kind": "playmat"})
        before = self.persisted()
        with self.assertRaises(api.ApiError) as aba:
            api.accessory_undo_view(cid)
        self.assertEqual(aba.exception.status, 409)
        self.assertEqual(self.persisted(), before)
