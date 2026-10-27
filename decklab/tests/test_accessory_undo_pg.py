"""Accessory text Undo in a guarded disposable PostgreSQL database only."""
import copy
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.db import conn as db
from decklab.lib import access, accessories, cards, config, inventory
from decklab.lib.api import accessory_undo as api
from decklab.lib.inventory import Op, accessory_undo as undo, pg, rules
from decklab.lib.state import Actor, Invalid, Unavailable
from decklab.lib.state import pg as state_pg
from decklab.tests import accessory_undo_support as fixture, db_support, household_config

ACTOR = Actor("matt", "Matt", source="web", via="tunnel")
TABLES = (*db_support.INVENTORY_TABLES, "collection_import_content", "inventory_revision", "decks_revision",
          "audit.change_set", "audit.row_change")


class AccessoryUndoPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-accessory-undo-pg-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Accessory Undo needs a disposable test database")
        db_support.seed_membership(cls.dbname, household_config.PROFILES)

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        initial = fixture.snapshot().replace(imports={})
        pg.write_model(initial, ACTOR, "Seed disposable accessories", contents={}, dbname=self.dbname,
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
        current = accessories.from_sheet(self.fresh().accessories, strict=True)
        return inventory.apply(Op("accessory.edit", {"id": rid, "row": fields, "image": "keep", "owners": owners,
                                                     "sha256": accessories.view_sha256(current, owners)}),
                               ACTOR, "Disposable accessory edit")

    def source(self):
        self.edit({"brand": "Changed brand", "name": "Changed sleeves", "colour": "green", "notes": "Changed note"})
        return self.sql("select change_set_id from audit.row_change where table_name='accessory' order by id desc limit 1")[0][0]

    def apply(self, cid, preview=None):
        preview = api.accessory_undo_view(cid) if preview is None else preview
        return api.apply_accessory_undo(json.dumps({"profile": "matt", "id": cid, "expect": preview["expect"]}).encode())

    def test_actual_metadata_receipt_one_new_audit_keeps_stock_kit_photos_and_original(self):
        cid = self.source()
        original = self.backend.undo_audit(cid)
        before, snapshot = self.persisted(), self.fresh()
        with mock.patch.object(cards, "resolve", side_effect=AssertionError("No card index")), \
                mock.patch.object(inventory, "image", side_effect=AssertionError("No image bytes")):
            preview = api.accessory_undo_view(cid)
            receipt = self.apply(cid, preview)
        actual = self.backend.undo_audit(int(self.sql("select max(id) from audit.change_set")[0][0]))
        self.assertEqual(len(actual), 1)
        self.assertEqual((actual[0]["table"], actual[0]["op"], actual[0]["before"], actual[0]["after"]),
                         ("accessory", "UPDATE", original[0]["after"], original[0]["before"]))
        self.assertEqual(receipt["revision"], str(actual[0]["id"]))
        self.assertEqual(receipt["restored"], preview["restored"])
        self.assertEqual(receipt["sha256"], undo.list_sha(undo.raw_rows(self.fresh()), fixture.OWNERS))
        self.assertEqual(self.backend.undo_audit(cid), original)
        written = self.persisted()
        for table in TABLES:
            if table not in ("accessory", "decks_revision", "audit.change_set", "audit.row_change"):
                self.assertEqual(written[table], before[table], table)
        self.assertEqual(self.fresh().accessory_images, snapshot.accessory_images)
        self.assertEqual(self.sql("select actor,source,via,reason from audit.change_set order by id desc limit 1"),
                         [("matt", "web", "tunnel", None)])

    def test_hidden_owner_and_unrelated_stock_changes_do_not_invalidate_scoped_receipt(self):
        cid, owners = self.source(), frozenset({"user1", "shared"})
        preview = api.accessory_undo_view(cid)
        self.edit({"notes": "Other owner's private edit"}, "c-hidden", owners)
        row = self.fresh().collection("home").rows[0].as_dict()
        inventory.apply(Op("collection.edit", {"space": "home", "original": list(rules.ident(row)),
                                               "row": {**row, "notes": "Unrelated stock correction"}}),
                        ACTOR, "Disposable stock edit")
        latest = self.fresh()
        self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
        self.apply(cid, preview)
        self.assertEqual(self.fresh().collection("home"), latest.collection("home"))
        self.assertEqual(next(row for row in undo.raw_rows(self.fresh()) if row["id"] == "c-hidden")["notes"],
                         "Other owner's private edit")

    def test_visible_list_change_stales_preview_and_target_aba_cannot_be_reauthorized(self):
        cid = self.source()
        preview = api.accessory_undo_view(cid)
        self.edit({"notes": "Shared row changed"}, "b-shared")
        before = self.persisted()
        with self.assertRaises(api.ApiError) as stale:
            self.apply(cid, preview)
        self.assertEqual(stale.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        # A fresh preview may account for a visible unrelated row; target ABA never does.
        self.assertNotEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
        for note in ("Away", "Changed note"):
            self.edit({"notes": note})
        with self.assertRaises(api.ApiError) as aba:
            api.accessory_undo_view(cid)
        self.assertEqual(aba.exception.status, 409)

    def test_global_mixed_source_and_immutable_photo_change_refuse_without_partial_save(self):
        current = accessories.from_sheet(self.fresh().accessories, strict=True)
        class Mixed:
            kind = "fixture.mixed"
            def run(inner, snapshot):
                after, summary = Op("accessory.edit", {"id": "a-sleeves", "row": {"notes": "Mixed"}, "owners": fixture.OWNERS,
                    "sha256": accessories.view_sha256(current, fixture.OWNERS), "image": "keep"}).run(snapshot)
                return after.with_accessories([{**row, "notes": "Other"} if row["id"] == "c-hidden" else row
                                               for row in undo.raw_rows(after)]), summary
        inventory.apply(Mixed(), ACTOR, "Mixed disposable owners")
        cid = self.sql("select max(id) from audit.change_set")[0][0]
        before = self.persisted()
        with self.assertRaises(api.ApiError) as hidden:
            api.accessory_undo_view(cid)
        self.assertEqual(hidden.exception.status, 404)
        self.assertEqual(self.persisted(), before)
        self.edit({"crop": "0,0,1,1", "notes": "Photo crop and text"})
        cid = self.sql("select max(id) from audit.change_set")[0][0]
        self.assertIs(api.accessory_undo_view(cid)["available"], False)

    def test_same_file_unaudited_image_replacement_is_preserved_by_text_only_inverse(self):
        from decklab.tests.test_accessory_fetch import jpeg
        current = accessories.from_sheet(self.fresh().accessories, strict=True)
        class PhotoText:
            kind = "fixture.photo-text"
            def run(inner, snapshot):
                after, _ = Op("image.put", {"name": "a-sleeves.jpg", "content": jpeg()}).run(snapshot)
                return Op("accessory.edit", {"id": "a-sleeves", "row": {"notes": "New photo and text",
                    "image_source": "https://example.com/current-photo"},
                    "sha256": accessories.view_sha256(current, fixture.OWNERS), "owners": fixture.OWNERS, "image": "keep"}).run(after)
        inventory.apply(PhotoText(), ACTOR, "Same-file disposable picture and text")
        cid = self.sql("select max(id) from audit.change_set")[0][0]
        self.assertEqual(len(self.backend.undo_audit(cid)), 1)
        photos = self.sql("select file_name,sha256,content from accessory_image order by file_name")
        receipt = self.apply(cid)
        self.assertEqual(receipt["restored"]["image_source"], fixture.row()["image_source"])
        self.assertEqual(self.sql("select file_name,sha256,content from accessory_image order by file_name"), photos)

    def test_preview_and_apply_use_one_locked_connection_and_preview_writes_no_audit(self):
        cid = self.source()
        before = self.persisted()
        original = self.backend._call
        with mock.patch.object(self.backend, "_call", wraps=original) as calls:
            preview = api.accessory_undo_view(cid)
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(self.persisted(), before)
        with mock.patch.object(self.backend, "_call", wraps=original) as calls, \
                mock.patch.object(self.backend, "load", side_effect=AssertionError("No second snapshot")):
            self.apply(cid, preview)
        self.assertEqual(calls.call_count, 1)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))

    def test_postwrite_audit_snapshot_and_late_sql_faults_roll_back_everything(self):
        cid = self.source()
        preview = api.accessory_undo_view(cid)
        before = self.persisted()
        original = undo.verify_saved
        def wrong_audit(old, after, plan, actual):
            actual = copy.deepcopy(actual)
            actual[0]["after"]["quantity"] = "99"
            return original(old, after, plan, actual)
        def wrong_snapshot(old, after, plan, actual):
            return original(old, after.replace(accessory_images={}), plan, actual)
        for function in (wrong_audit, wrong_snapshot):
            with self.subTest(fault=function.__name__), mock.patch.object(undo, "verify_saved", side_effect=function), \
                    self.assertRaises(api.ApiError) as refused:
                self.apply(cid, preview)
            self.assertEqual(refused.exception.status, 409)
            self.assertEqual(self.persisted(), before)
        original_diff = pg.pg_decks.write_diff
        def late(*args, **kwargs):
            original_diff(*args, **kwargs)
            raise Invalid("Synthetic late accessory SQL failure")
        with mock.patch.object(pg.pg_decks, "write_diff", side_effect=late), self.assertRaises(api.ApiError) as refused:
            self.apply(cid, preview)
        self.assertEqual(refused.exception.status, 400)
        self.assertEqual(self.persisted(), before)
        self.assertIsNone(getattr(self.backend._applying, "connection", None))
        self.apply(cid, preview)

    def test_lost_reply_is_not_retried_or_acknowledged_and_original_cannot_repeat(self):
        cid = self.source()
        preview = api.accessory_undo_view(cid)
        original = self.backend._call
        calls = []
        def lost(work):
            calls.append(1)
            original(work)
            raise Unavailable("Synthetic reply lost after commit")
        with mock.patch.object(self.backend, "_call", side_effect=lost), self.assertRaises(api.ApiError) as refused:
            self.apply(cid, preview)
        self.assertEqual((refused.exception.status, len(calls)), (503, 1))
        self.assertEqual(undo.meta(next(row for row in undo.raw_rows(self.fresh()) if row["id"] == "a-sleeves")),
                         preview["restored"])
        before = self.persisted()
        with self.assertRaises(api.ApiError) as stale:
            self.apply(cid, preview)
        self.assertEqual(stale.exception.status, 409)
        self.assertEqual(self.persisted(), before)

    def test_failed_verifier_does_not_cache_dirty_revision_reused_by_another_backend(self):
        cid = self.source()
        preview = api.accessory_undo_view(cid)
        before = self.persisted()
        with mock.patch.object(undo, "verify_saved", side_effect=Invalid("Synthetic final verification failure")), \
                self.assertRaises(api.ApiError):
            self.apply(cid, preview)
        self.assertEqual(self.persisted(), before)
        separate = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        with inventory.use(separate):
            self.edit({"notes": "Other backend's committed private metadata"}, "c-hidden",
                      frozenset({"user1", "shared"}))
        committed, actual = separate.load(), self.backend.load()
        self.assertEqual(actual, committed)
        self.assertEqual(undo.meta(next(row for row in undo.raw_rows(actual) if row["id"] == "a-sleeves")),
                         preview["current"])
        self.assertEqual(next(row for row in undo.raw_rows(actual) if row["id"] == "c-hidden")["notes"],
                         "Other backend's committed private metadata")

    def test_each_recorded_url_blank_boundary_and_mixed_text_restore_without_fetch(self):
        cases = [({"link": "https://example.com/" + "p" * (500 - len("https://example.com/"))}, {"link": ""}),
                 ({"image_source": "https://example.com/" + "s" * (2000 - len("https://example.com/"))}, {"image_source": ""}),
                 ({"link": "", "image_source": ""}, {"link": "https://example.com/new", "image_source": "http://example.com/new"}),
                 ({"link": "https://example.com/旧記録?q=é", "image_source": "https://example.com/旧画像", "notes": "Original URL facts"},
                  {"link": "https://example.com/current", "image_source": "https://example.com/current-image", "notes": "Edited URL facts"})]
        for historical, edited in cases:
            with self.subTest(fields=historical):
                self.edit(historical)
                self.edit(edited)
                cid = self.sql("select max(id) from audit.change_set")[0][0]
                source, before = self.backend.undo_audit(cid), self.persisted()
                photos = self.sql("select file_name,content,sha256 from accessory_image order by file_name")
                with mock.patch("urllib.request.urlopen", side_effect=AssertionError("No URL fetch")), \
                        mock.patch.object(inventory, "image", side_effect=AssertionError("No image bytes")):
                    preview, receipt = api.accessory_undo_view(cid), self.apply(cid)
                for field, value in historical.items():
                    self.assertEqual(receipt["restored"][field], value)
                self.assertEqual(receipt["restored"], preview["restored"])
                self.assertEqual(self.backend.undo_audit(cid), source)
                self.assertEqual(self.sql("select file_name,content,sha256 from accessory_image order by file_name"), photos)
                after = self.persisted()
                for table in TABLES:
                    if table not in ("accessory", "decks_revision", "audit.change_set", "audit.row_change"):
                        self.assertEqual(after[table], before[table], table)

    def test_actual_invalid_historical_urls_refuse_before_any_inverse_or_normalization(self):
        # Deliberately imperfect historical TEXT rows in this disposable fixture only.
        # The production inverse never issues SQL to restore or normalize these facts.
        for field, limit in (("link", 500), ("image_source", 2000)):
            for invalid in ("javascript:alert(1)", "ftp://example.com/item", " https://example.com/space ",
                            "https://example.com/" + "x" * limit):
                with self.subTest(field=field, invalid=invalid[:30]):
                    for value in (invalid, "https://example.com/current"):
                        with self.connect() as connection, db.change(ACTOR.id, ACTOR.source, "Imperfect disposable URL history",
                                                                    conn=connection, via=ACTOR.via) as (cur, cid):
                            pg._take_lock(cur)
                            cur.execute(f"update accessory set {field}=%s where id='a-sleeves'", (value,))
                            cur.execute("update decks_revision set revision=revision+1")
                    self.assertEqual(self.backend.undo_audit(cid)[0]["before"][field], invalid)
                    before = self.persisted()
                    self.assertIs(api.accessory_undo_view(cid)["available"], False)
                    with self.assertRaises(api.ApiError) as refused:
                        self.apply(cid, {"expect": "bad"})
                    self.assertEqual(refused.exception.status, 400)
                    self.assertEqual(self.persisted(), before)

    def test_wrong_actual_restored_url_rolls_back_row_and_entire_audit(self):
        self.edit({"link": "https://example.com/changed-link", "image_source": "https://example.com/changed-source"})
        cid = self.sql("select max(id) from audit.change_set")[0][0]
        preview, before = api.accessory_undo_view(cid), self.persisted()
        original = undo.verify_saved
        for field in ("link", "image_source"):
            def wrong(old, after, plan, actual):
                actual = copy.deepcopy(actual)
                actual[0]["after"][field] = "https://example.com/unreviewed"
                return original(old, after, plan, actual)
            with self.subTest(field=field), mock.patch.object(undo, "verify_saved", side_effect=wrong), \
                    self.assertRaises(api.ApiError) as refused:
                self.apply(cid, preview)
            self.assertEqual(refused.exception.status, 409)
            self.assertEqual(self.persisted(), before)
        self.apply(cid, preview)
