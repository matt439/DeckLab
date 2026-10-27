"""Crop recovery bound to actual current-photo bytes in disposable PostgreSQL."""
import copy
import hashlib
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import mock

from decklab.lib import access, accessories, config, inventory
from decklab.lib.api import accessory_undo as api
from decklab.lib.inventory import Op, accessory_undo as undo, pg
from decklab.lib.state import Actor
from decklab.lib.state import pg as state_pg
from decklab.tests import accessory_undo_support as fixture, db_support, household_config
from decklab.tests.test_accessory_fetch import jpeg

ACTOR = Actor("matt", "Matt", source="web", via="tunnel")
TABLES = (*db_support.INVENTORY_TABLES, "collection_import_content", "inventory_revision", "decks_revision",
          "visibility", "audit.change_set", "audit.row_change")
OMIT = object()


class AccessoryCropUndoPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-accessory-crop-undo-pg-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Photo recovery needs a disposable database")
        db_support.seed_membership(cls.dbname, household_config.PROFILES)

    def setUp(self):
        db_support.reset(self.dbname, (*db_support.INVENTORY_TABLES, "visibility"))
        pictures = {"a-sleeves.jpg": jpeg(), "c-hidden.jpg": jpeg(400, 200)}
        initial = fixture.snapshot().replace(imports={})
        for name, data in pictures.items():
            initial = initial.with_image(name, data)
        pg.write_model(initial, ACTOR, "Seed current photographed crop fixtures", contents={}, dbname=self.dbname,
                       decks=True, images=pictures)
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

    def edit(self, fields, rid="a-sleeves"):
        listing = accessories.from_sheet(self.fresh().accessories, strict=True)
        inventory.apply(Op("accessory.edit", {"id": rid, "row": fields, "image": "keep", "owners": fixture.OWNERS,
            "sha256": accessories.view_sha256(listing, fixture.OWNERS)}), ACTOR, "Correct a disposable accessory crop")
        return self.sql("select max(id) from audit.change_set")[0][0]

    def source(self):
        return self.edit({"crop": "0.2,0,0.8,1"})

    def replace_photo(self, data, name="a-sleeves.jpg"):
        inventory.apply(Op("image.put", {"name": name, "content": data}), ACTOR, "Replace an unaudited current fixture photo")

    def apply(self, cid, preview, confirm_photo=True, **extra):
        body = {"profile": "matt", "id": cid, "expect": preview["expect"], **extra}
        if confirm_photo is not OMIT:
            body["confirm_photo"] = confirm_photo
        return api.apply_accessory_undo(json.dumps(body).encode())

    def assert_other_data(self, before, snapshot):
        after = self.persisted()
        for table in TABLES:
            if table not in ("accessory", "decks_revision", "audit.change_set", "audit.row_change"):
                self.assertEqual(after[table], before[table], table)
        self.assertEqual(self.fresh().accessory_images, snapshot.accessory_images)

    def test_three_kinds_and_held_sleeves_box_keep_current_bytes_stock_kit_and_one_actual_crop_audit(self):
        targets = ["a-sleeves"]
        for kind in ("deck_box", "playmat"):
            listing = accessories.from_sheet(self.fresh().accessories, strict=True)
            _, summary = inventory.apply(Op("accessory.add", {"row": {"kind": kind, "owner": "matt",
                "name": "Crop fixture " + kind, "quantity": 0 if kind == "playmat" else 1,
                "capacity": "100" if kind == "deck_box" else ""}, "owners": fixture.OWNERS,
                "image": jpeg(), "sha256": accessories.view_sha256(listing, fixture.OWNERS)}), ACTOR, "Add a disposable crop fixture")
            rid = summary.extra["id"]
            targets.append(rid)
            if kind == "deck_box":
                deck = self.fresh().deck("casual/fixture")
                inventory.apply(Op("kit.set", {"holders": [{"id": deck.id, "expected": deck.sha256}],
                    "changes": [{"holder": deck.id, "field": "deck_box", "value": rid}], "owners": fixture.OWNERS}),
                    ACTOR, "Use a photographed disposable crop fixture")
        for rid in targets:
            for historical in ("", "0.1,0.1,0.8,0.8"):
                self.edit({"crop": historical}, rid)
                cid = self.edit({"crop": "0,0,1,1"}, rid)
                source, before, snapshot = self.backend.undo_audit(cid), self.persisted(), self.fresh()
                preview = api.accessory_undo_view(cid)
                self.assertEqual((preview["action"], preview["photo_confirmation_required"]), ("accessory_crop_update", True))
                self.assertEqual((len(preview["current"]), len(preview["restored"])), (13, 13))
                self.assertEqual(preview["fields"], [{"field": "crop", "before": "0,0,1,1", "after": historical}])
                self.assertEqual(preview["photo"]["name"], preview["current"]["image"])
                self.assertEqual(preview["photo"]["version"], accessories.image_version(snapshot.image_meta(preview["photo"]["name"])))
                receipt = self.apply(cid, preview)
                self.assertEqual((receipt["restored"], receipt["photo"]), (source[0]["before"], preview["photo"]))
                actual = self.backend.undo_audit(self.sql("select max(id) from audit.change_set")[0][0])
                self.assertEqual(len(actual), 1)
                self.assertEqual((actual[0]["op"], actual[0]["before"], actual[0]["after"]),
                                 ("UPDATE", source[0]["after"], source[0]["before"]))
                self.assertEqual(receipt["revision"], str(actual[0]["id"]))
                self.assertEqual(self.backend.undo_audit(cid), source)
                self.assert_other_data(before, snapshot)

    def test_preview_locked_candidate_and_actual_verifier_share_one_connection_and_reader_has_no_fallback(self):
        cid = self.source()
        original = self.backend.accessory_undo_photo
        seen = []
        def photo(*args):
            connection = getattr(self.backend._applying, "connection", None)
            self.assertIsNotNone(connection)
            seen.append(connection)
            return original(*args)
        with mock.patch.object(self.backend, "accessory_undo_photo", side_effect=photo), \
                mock.patch.object(self.backend, "_call", wraps=self.backend._call) as calls:
            preview = api.accessory_undo_view(cid)
            self.assertEqual(calls.call_count, 1)
        self.assertGreaterEqual(len(seen), 1)
        self.assertTrue(all(connection is seen[0] for connection in seen))
        seen.clear()
        with mock.patch.object(self.backend, "accessory_undo_photo", side_effect=photo), \
                mock.patch.object(self.backend, "_call", wraps=self.backend._call) as calls:
            self.apply(cid, preview)
            # The immutable owner/source preflight has its own read; all photo
            # proof reads belong to the single subsequent inventory transaction.
            self.assertEqual(calls.call_count, 2)
        self.assertGreaterEqual(len(seen), 2)
        self.assertTrue(all(connection is seen[0] for connection in seen))
        self.assertIsNone(getattr(self.backend._applying, "connection", None))
        with self.assertRaises(inventory.Invalid):
            original(preview["photo"]["name"], preview["photo"]["sha256"], preview["photo"]["size"])

    def test_same_filename_replacement_before_preview_is_current_but_after_preview_stales_without_row_audit(self):
        cid = self.source()
        source = self.backend.undo_audit(cid)
        replacement = jpeg(320, 160)
        self.replace_photo(replacement)
        self.assertEqual(self.backend.undo_latest("accessory", {"id": "a-sleeves"}), source[0]["id"])
        preview = api.accessory_undo_view(cid)
        self.assertEqual(preview["photo"]["sha256"], hashlib.sha256(replacement).hexdigest())
        before, snapshot = self.persisted(), self.fresh()
        self.apply(cid, preview)
        self.assert_other_data(before, snapshot)
        cid = self.source()
        source, preview = self.backend.undo_audit(cid), api.accessory_undo_view(cid)
        self.replace_photo(jpeg(340, 170))
        self.assertEqual(self.backend.undo_latest("accessory", {"id": "a-sleeves"}), source[0]["id"])
        before = self.persisted()
        with self.assertRaises(api.ApiError) as error:
            self.apply(cid, preview)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.backend.undo_audit(cid), source)
        self.assertNotEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])

    def test_private_other_owner_photo_replacement_does_not_stale_or_read_that_photo(self):
        cid = self.source()
        preview = api.accessory_undo_view(cid)
        self.replace_photo(jpeg(500, 250), "c-hidden.jpg")
        before, snapshot = self.persisted(), self.fresh()
        original, names = self.backend.accessory_undo_photo, []
        def photo(name, *args):
            names.append(name)
            return original(name, *args)
        with mock.patch.object(self.backend, "accessory_undo_photo", side_effect=photo):
            self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
            self.apply(cid, preview)
        self.assertTrue(names)
        self.assertEqual(set(names), {"a-sleeves.jpg"})
        self.assert_other_data(before, snapshot)

    def test_actual_uncommitted_bytes_equal_metadata_content_and_audit_reason_faults_all_roll_back(self):
        cid = self.source()
        preview, before, snapshot = api.accessory_undo_view(cid), self.persisted(), self.fresh()
        original = undo.verify_saved
        wrong_bytes = jpeg(360, 180)
        for mode in ("actual-bytes", "excluded-content", "actual-crop"):
            def wrong(old, after, plan, actual, *, store=None):
                if mode == "actual-bytes":
                    connection = self.backend._applying.connection
                    self.assertIsNotNone(connection)
                    connection.execute("update accessory_image set content=%s,size=%s,sha256=%s where file_name=%s",
                                       (wrong_bytes, len(wrong_bytes), hashlib.sha256(wrong_bytes).hexdigest(), "a-sleeves.jpg"))
                    self.assertEqual(after.accessory_images, old.accessory_images)
                elif mode == "excluded-content":
                    meta = after.image_meta("a-sleeves.jpg")
                    altered = replace(meta, content=wrong_bytes)
                    self.assertEqual(altered, meta)  # ImageMeta equality intentionally excludes content.
                    after = after.replace(accessory_images={**after.accessory_images, "a-sleeves.jpg": altered})
                else:
                    actual = copy.deepcopy(actual)
                    actual[0]["after"]["crop"] = "0,0,1,1"
                return original(old, after, plan, actual, store=store)
            with self.subTest(mode=mode), mock.patch.object(undo, "verify_saved", side_effect=wrong), self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview)
            self.assertEqual(error.exception.status, 409)
            self.assertEqual(self.persisted(), before)
            self.assertEqual(self.fresh(), snapshot)
            self.assertIsNone(getattr(self.backend._applying, "connection", None))
        operation = undo.MetadataRestore(cid, fixture.OWNERS, preview["expect"], store=self.backend, confirm_photo=True)
        with self.assertRaises(inventory.Conflict):
            inventory.apply(operation, ACTOR, "Direct disposable crop recovery", reason="Unreviewed fixture reason")
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.fresh(), snapshot)
        self.assertEqual(self.apply(cid, preview)["photo"], preview["photo"])
        self.assertEqual(self.sql("select reason from audit.change_set order by id desc limit 1"), [(None,)])

    def test_invalid_current_image_dimensions_are_not_treated_as_a_reviewed_photo(self):
        cid = self.source()
        for bad in (jpeg(8, 8), jpeg(6001, 100)):
            self.replace_photo(bad)
            before = self.persisted()
            self.assertIs(api.accessory_undo_view(cid)["available"], False)
            with self.assertRaises(api.ApiError) as error:
                self.apply(cid, {"expect": "bad"})
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)

    def test_photo_consent_flags_owner_privacy_and_older_metadata_protocol_do_not_gain_photo_reads(self):
        cid = self.source()
        preview, before = api.accessory_undo_view(cid), self.persisted()
        for value in (OMIT, None, False, 1, "true", [], {}):
            with self.subTest(consent=value), self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, confirm_photo=value)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        for flag in ("reason", "confirm_restore", "confirm_stock", "confirm_owner", "confirm_kind", "confirm_record"):
            with self.subTest(flag=flag), self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, **{flag: None})
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}), \
                mock.patch.object(self.backend, "accessory_undo_photo", side_effect=AssertionError("No private photo read")), \
                self.assertRaises(api.ApiError) as hidden:
            api.apply_accessory_undo(json.dumps({"profile": "user1", "id": cid, "expect": "bad", "confirm_photo": None}).encode())
        self.assertEqual((hidden.exception.status, hidden.exception.message), (404, api.NO_CHANGE))
        self.assertEqual(self.persisted(), before)
        cid = self.edit({"notes": "Metadata only"})
        with mock.patch.object(self.backend, "accessory_undo_photo", side_effect=AssertionError("No photo read for metadata")):
            preview = api.accessory_undo_view(cid)
            self.assertEqual(preview["action"], "accessory_update")
            self.assertNotIn("photo", preview)
            self.replace_photo(jpeg(380, 190))
            self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
            receipt = self.apply(cid, preview, confirm_photo=OMIT)
        self.assertNotIn("photo", receipt)
