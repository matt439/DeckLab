"""Unused own/Shared ownership recovery in disposable PostgreSQL databases."""
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
from decklab.lib.inventory import Op, accessory_undo as undo, pg
from decklab.lib.state import Actor
from decklab.lib.state import pg as state_pg
from decklab.tests import accessory_undo_support as fixture, db_support, household_config

ACTOR = Actor("matt", "Matt", source="web", via="tunnel")
TABLES = (*db_support.INVENTORY_TABLES, "collection_import_content", "inventory_revision", "decks_revision",
          "visibility", "audit.change_set", "audit.row_change")
OMIT = object()


class AccessoryOwnerUndoPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-accessory-owner-undo-pg-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Owner recovery needs a disposable database")
        db_support.seed_membership(cls.dbname, household_config.PROFILES)

    def setUp(self):
        db_support.reset(self.dbname, (*db_support.INVENTORY_TABLES, "visibility"))
        initial = fixture.snapshot().replace(imports={})
        deck = initial.deck("casual/fixture")
        initial = initial.with_deck(replace(deck, text=deck.text.replace("- **Sleeves:** a-sleeves\n", "")))
        pg.write_model(initial, ACTOR, "Seed unused photographed ownership fixture", contents={}, dbname=self.dbname,
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
            "sha256": accessories.view_sha256(listing, owners)}), ACTOR, "Correct disposable accessory sharing")
        return self.sql("select max(id) from audit.change_set")[0][0]

    def add(self, kind, quantity):
        from decklab.tests.test_accessory_fetch import jpeg
        listing = accessories.from_sheet(self.fresh().accessories, strict=True)
        _, summary = inventory.apply(Op("accessory.add", {"row": {"kind": kind, "owner": "matt",
            "name": "Ownership fixture " + kind, "quantity": quantity, "capacity": "100" if kind == "deck_box" else ""},
            "owners": fixture.OWNERS, "image": jpeg(), "sha256": accessories.view_sha256(listing, fixture.OWNERS)}),
            ACTOR, "Add unused photographed ownership fixture")
        return summary.extra["id"]

    def apply(self, cid, preview, confirm_owner=True, **extra):
        body = {"profile": "matt", "id": cid, "expect": preview["expect"], **extra}
        if confirm_owner is not OMIT:
            body["confirm_owner"] = confirm_owner
        return api.apply_accessory_undo(json.dumps(body).encode())

    def kit(self, rid):
        deck = self.fresh().deck("casual/fixture")
        return inventory.apply(Op("kit.set", {"holders": [{"id": deck.id, "expected": deck.sha256}],
            "changes": [{"holder": deck.id, "field": "sleeves", "value": rid}], "owners": fixture.OWNERS}),
            ACTOR, "Assign a disposable kit fixture")

    def assert_other_data(self, before, snapshot):
        after = self.persisted()
        for table in TABLES:
            if table not in ("accessory", "decks_revision", "audit.change_set", "audit.row_change"):
                self.assertEqual(after[table], before[table], table)
        self.assertEqual(self.fresh().accessory_images, snapshot.accessory_images)

    def test_both_directions_all_kinds_zero_and_mixed_details_keep_photos_stock_and_public_switches(self):
        switches = state_pg.PgStore(dbname=self.dbname, breaker=state_pg.Breaker())
        switches.visibility_set("matt", "accessories", True, ACTOR, "Synthetic current owner visibility")
        switches.visibility_set("shared", "accessories", False, ACTOR, "Synthetic shared visibility")
        for kind, quantity in (("sleeves", 100), ("deck_box", 0), ("playmat", 1)):
            rid = "a-sleeves" if kind == "sleeves" else self.add(kind, quantity)
            for owner, historical in (("shared", "matt"), ("matt", "shared")):
                cid = self.edit({"owner": owner, "notes": "Changed sharing " + owner,
                                 **({"capacity": "40"} if kind == "deck_box" else {})}, rid)
                source, before, snapshot = self.backend.undo_audit(cid), self.persisted(), self.fresh()
                preview = api.accessory_undo_view(cid)
                self.assertEqual((preview["action"], preview["owner_confirmation_required"]), ("accessory_owner_update", True))
                self.assertEqual(preview["fields"][0], {"field": "owner", "before": owner, "after": historical})
                self.assertEqual(preview["current"]["quantity"], preview["restored"]["quantity"])
                self.assertEqual(len(preview["restored"]), 11)
                receipt = self.apply(cid, preview)
                self.assertEqual(receipt["restored"], undo.stock_meta(source[0]["before"]))
                actual = self.backend.undo_audit(self.sql("select max(id) from audit.change_set")[0][0])
                self.assertEqual(len(actual), 1)
                self.assertEqual((actual[0]["op"], actual[0]["before"], actual[0]["after"]),
                                 ("UPDATE", source[0]["after"], source[0]["before"]))
                self.assertEqual(receipt["revision"], str(actual[0]["id"]))
                self.assertEqual(self.backend.undo_audit(cid), source)
                self.assert_other_data(before, snapshot)
                # The inverse restored the old owner. Produce the other direction normally.
                if owner == "shared":
                    self.edit({"owner": "shared"}, rid)

    def test_target_kit_race_refuses_but_known_unrelated_kit_edit_keeps_preview_usable(self):
        cid = self.edit({"owner": "shared"})
        preview = api.accessory_undo_view(cid)
        self.kit("b-shared")
        self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
        known = self.fresh()
        self.apply(cid, preview)
        self.assertEqual(self.fresh().decks, known.decks)
        cid = self.edit({"owner": "shared"})
        preview = api.accessory_undo_view(cid)
        self.kit("a-sleeves")
        before = self.persisted()
        with self.assertRaises(api.ApiError) as error:
            self.apply(cid, preview)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        with self.assertRaises(api.ApiError) as held:
            api.accessory_undo_view(cid)
        self.assertEqual(held.exception.status, 409)

    def test_flags_are_exact_action_specific_and_hidden_source_precedes_invalid_confirmation(self):
        cid = self.edit({"owner": "shared"})
        preview, before = api.accessory_undo_view(cid), self.persisted()
        for value in (OMIT, None, False, 1, "true", [], {}):
            with self.subTest(consent=value), self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, confirm_owner=value)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        for extra in ({"reason": None}, {"confirm_restore": None}, {"confirm_restore": True},
                      {"confirm_stock": None}, {"confirm_stock": True}):
            with self.subTest(extra=extra), self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, **extra)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}), \
                self.assertRaises(api.ApiError) as hidden:
            api.apply_accessory_undo(json.dumps({"profile": "user1", "id": cid, "expect": "bad", "confirm_owner": None}).encode())
        self.assertEqual((hidden.exception.status, hidden.exception.message), (404, api.NO_CHANGE))
        self.assertEqual(self.persisted(), before)
        cid = self.edit({"notes": "Metadata only"})
        preview, before = api.accessory_undo_view(cid), self.persisted()
        for value in (True, False, None):
            with self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, confirm_owner=value)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)

    def test_scripts_cannot_transfer_between_profiles_or_restore_nonhome_or_orphan_owners(self):
        for historical, current in (("matt", "user1"), ("user2", "shared"), ("orphan", "shared")):
            for owner in (historical, current):
                with self.connect() as connection, db.change(ACTOR.id, ACTOR.source, "Synthetic unsupported owner history",
                                                            conn=connection, via=ACTOR.via) as (cur, cid):
                    pg._take_lock(cur)
                    cur.execute("update accessory set owner=%s where id='a-sleeves'", (owner,))
                    cur.execute("update decks_revision set revision=revision+1")
            before = self.persisted()
            with self.subTest(historical=historical), self.assertRaises(inventory.Invalid):
                self.backend.accessory_undo_review(cid, None)
            with self.assertRaises(inventory.Invalid):
                self.backend.accessory_undo_apply(cid, None, "bad", ACTOR, "Refused synthetic owner recovery",
                                                  confirm_owner=True)
            self.assertEqual(self.persisted(), before)

    def test_wrong_actual_owner_and_direct_unreviewed_audit_reason_roll_back_before_same_preview_retry(self):
        cid = self.edit({"owner": "shared"})
        preview, before, snapshot = api.accessory_undo_view(cid), self.persisted(), self.fresh()
        original = undo.verify_saved
        def wrong(old, after, plan, actual):
            actual = copy.deepcopy(actual)
            actual[0]["after"]["owner"] = "shared"
            return original(old, after, plan, actual)
        with mock.patch.object(undo, "verify_saved", side_effect=wrong), self.assertRaises(api.ApiError) as error:
            self.apply(cid, preview)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.fresh(), snapshot)
        operation = undo.MetadataRestore(cid, fixture.OWNERS, preview["expect"], store=self.backend, confirm_owner=True)
        with self.assertRaises(inventory.Conflict):
            inventory.apply(operation, ACTOR, "Direct disposable owner recovery", reason="Unreviewed fixture reason")
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.fresh(), snapshot)
        self.assertEqual(self.apply(cid, preview)["restored"], preview["restored"])
        self.assertEqual(self.sql("select reason from audit.change_set order by id desc limit 1"), [(None,)])

    def test_scoped_hidden_changes_pass_visible_edits_stale_and_owner_aba_is_refused(self):
        cid = self.edit({"owner": "shared"})
        preview = api.accessory_undo_view(cid)
        self.edit({"notes": "Private unrelated correction"}, "c-hidden", frozenset({"user1", "shared"}))
        self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
        self.edit({"notes": "Shared correction"}, "b-shared")
        before = self.persisted()
        with self.assertRaises(api.ApiError) as stale:
            self.apply(cid, preview)
        self.assertEqual(stale.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        self.edit({"owner": "matt"})
        self.edit({"owner": "shared"})
        before = self.persisted()
        with self.assertRaises(api.ApiError) as aba:
            api.accessory_undo_view(cid)
        self.assertEqual(aba.exception.status, 409)
        self.assertEqual(self.persisted(), before)
