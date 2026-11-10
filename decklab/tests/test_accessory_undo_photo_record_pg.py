"""Combined recorded facts/crop are one exact inverse on a guarded disposable database."""
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import access, config, inventory
from decklab.lib.api import accessory_undo as api
from decklab.lib.inventory import Op, accessory_undo as undo
from decklab.tests import db_support, household_config
from decklab.tests import test_accessory_undo_crop_pg as crop_pg
from decklab.tests.test_accessory_fetch import jpeg


class AccessoryPhotoRecordPgTests(db_support.DbTestCase):
    setUp = crop_pg.AccessoryCropUndoPgTests.setUp
    sql = crop_pg.AccessoryCropUndoPgTests.sql
    persisted = crop_pg.AccessoryCropUndoPgTests.persisted
    fresh = crop_pg.AccessoryCropUndoPgTests.fresh
    edit = crop_pg.AccessoryCropUndoPgTests.edit
    replace_photo = crop_pg.AccessoryCropUndoPgTests.replace_photo
    assert_other_data = crop_pg.AccessoryCropUndoPgTests.assert_other_data

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-accessory-photo-record-pg-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start(); cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Combined photo recovery requires a disposable database")
        db_support.seed_membership(cls.dbname, household_config.PROFILES)

    def apply(self, cid, preview, **options):
        return api.apply_accessory_undo(json.dumps({"profile": "matt", "id": cid, "expect": preview["expect"], **options}))

    def source(self):
        return self.edit({"crop": "0.1,0.1,0.8,0.8", "notes": "Current <img> literal note", "quantity": "80"})

    def test_held_crop_notes_and_count_save_one_actual_opposite_row_with_photo_pinned_on_same_connection(self):
        cid = self.source()
        source = self.backend.undo_audit(cid)
        before, snapshot = self.persisted(), self.fresh()
        seen, original = [], self.backend.accessory_undo_photo
        def photo(*args):
            connection = getattr(self.backend._applying, "connection", None)
            self.assertIsNotNone(connection); seen.append(connection)
            return original(*args)
        with mock.patch.object(self.backend, "accessory_undo_photo", side_effect=photo):
            preview = api.accessory_undo_view(cid)
        self.assertTrue(seen)
        self.assertEqual(preview["action"], "accessory_photo_record_update")
        seen.clear()
        with mock.patch.object(self.backend, "accessory_undo_photo", side_effect=photo):
            result = self.apply(cid, preview, confirm_photo=True, confirm_record=True)
        self.assertGreaterEqual(len(seen), 2)
        self.assertTrue(all(connection is seen[0] for connection in seen))
        self.assertEqual((result["restored"], result["photo"]), (source[0]["before"], preview["photo"]))
        actual = self.backend.undo_audit(self.sql("select max(id) from audit.change_set")[0][0])
        self.assertEqual((len(actual), actual[0]["op"], actual[0]["before"], actual[0]["after"]),
                         (1, "UPDATE", source[0]["after"], source[0]["before"]))
        self.assertEqual(self.backend.undo_audit(cid), source)
        self.assert_other_data(before, snapshot)

    def test_unused_kind_owner_count_details_and_crop_reverse_as_a_whole(self):
        deck = self.fresh().deck("casual/fixture")
        inventory.apply(Op("kit.set", {"holders": [{"id": deck.id, "expected": deck.sha256}],
            "changes": [{"holder": deck.id, "field": "sleeves", "value": None}], "owners": crop_pg.fixture.OWNERS}),
            crop_pg.ACTOR, "Clear disposable accessory kit")
        self.edit({"kind": "deck_box", "owner": "shared", "quantity": "2", "capacity": "100", "crop": "0,0,1,1"})
        cid = self.edit({"kind": "playmat", "owner": "matt", "quantity": "0", "capacity": "", "crop": "0.1,0.1,0.8,0.8",
                         "notes": "Corrected record", "link": "https://example.com/record"})
        before, snapshot = self.persisted(), self.fresh()
        preview = api.accessory_undo_view(cid)
        self.assertEqual((preview["restored"]["kind"], preview["restored"]["owner"], preview["restored"]["quantity"]), ("deck_box", "shared", "2"))
        self.apply(cid, preview, confirm_photo=True, confirm_record=True)
        self.assert_other_data(before, snapshot)

    def test_both_flags_exact_true_and_hidden_source_have_no_write(self):
        cid = self.source()
        preview, before = api.accessory_undo_view(cid), self.persisted()
        for options in ({}, {"confirm_photo": True}, {"confirm_record": True}, {"confirm_photo": 1, "confirm_record": True},
                        {"confirm_photo": True, "confirm_record": False}, {"confirm_photo": True, "confirm_record": True, "confirm_stock": True}):
            with self.subTest(options=options), self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, **options)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}), \
                mock.patch.object(self.backend, "accessory_undo_photo", side_effect=AssertionError("Hidden photo")):
            with self.assertRaises(api.ApiError) as hidden:
                api.accessory_undo_view(cid)
            self.assertEqual(hidden.exception.status, 404)
        self.assertEqual(self.persisted(), before)

    def test_same_name_photo_race_stales_review_without_recovering_historical_bytes(self):
        cid = self.source()
        preview = api.accessory_undo_view(cid)
        self.replace_photo(jpeg(320, 160))
        before = self.persisted()
        with self.assertRaises(api.ApiError) as changed:
            self.apply(cid, preview, confirm_photo=True, confirm_record=True)
        self.assertEqual(changed.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        new = api.accessory_undo_view(cid)
        self.assertNotEqual(new["expect"], preview["expect"])
        current_bytes = self.fresh().accessory_images
        self.apply(cid, new, confirm_photo=True, confirm_record=True)
        self.assertEqual(self.fresh().accessory_images, current_bytes)

    def test_uncommitted_photo_bytes_or_wrong_actual_record_audit_roll_back_everything(self):
        cid = self.source()
        preview, before, snapshot = api.accessory_undo_view(cid), self.persisted(), self.fresh()
        original = undo.verify_saved
        for mode in ("bytes", "notes", "crop", "quantity"):
            def changed(old, after, plan, actual, *, store=None):
                if mode == "bytes":
                    data = jpeg(360, 180)
                    self.backend._applying.connection.execute("update accessory_image set content=%s,size=%s,sha256=%s where file_name=%s",
                        (data, len(data), hashlib.sha256(data).hexdigest(), "a-sleeves.jpg"))
                else:
                    actual = copy.deepcopy(actual); actual[0]["after"][mode] = "unexpected"
                return original(old, after, plan, actual, store=store)
            with self.subTest(mode=mode), mock.patch.object(undo, "verify_saved", side_effect=changed), self.assertRaises(api.ApiError) as error:
                self.apply(cid, preview, confirm_photo=True, confirm_record=True)
            self.assertEqual(error.exception.status, 409)
            self.assertEqual(self.persisted(), before)
            self.assertEqual(self.fresh(), snapshot)
        operation = undo.MetadataRestore(cid, crop_pg.fixture.OWNERS, preview["expect"], store=self.backend,
                                         confirm_photo=True, confirm_record=True)
        with self.assertRaises(inventory.Conflict):
            inventory.apply(operation, crop_pg.ACTOR, "Direct disposable correction", reason="Unreviewed reason")
        self.assertEqual(self.persisted(), before)
