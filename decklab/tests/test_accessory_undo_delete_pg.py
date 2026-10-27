"""Exact ordinary Add restoration in a guarded disposable PostgreSQL database."""
import copy
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import accessories, cards, config, inventory
from decklab.lib.api import accessory_undo as api
from decklab.lib.inventory import Op, Summary, accessory_undo as undo, model
from decklab.lib.state import Unavailable
from decklab.tests import accessory_undo_support as fixture, db_support, household_config
from decklab.tests import test_accessory_undo_pg as base, test_accessory_undo_insert_pg as additions

OMIT = object()


class AccessoryDeleteUndoPgTests(db_support.DbTestCase):
    setUp = base.AccessoryUndoPgTests.setUp
    sql = base.AccessoryUndoPgTests.sql
    fresh = base.AccessoryUndoPgTests.fresh
    persisted = base.AccessoryUndoPgTests.persisted
    edit = base.AccessoryUndoPgTests.edit

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-accessory-delete-undo-pg-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Accessory DELETE Undo needs a disposable database")
        db_support.seed_membership(cls.dbname, household_config.PROFILES)

    def delete(self, rid=None, owners=fixture.OWNERS):
        rid = self.rid if rid is None else rid
        listing = accessories.from_sheet(self.fresh().accessories, strict=True)
        inventory.apply(Op("accessory.remove", {"id": rid, "owners": owners,
            "sha256": accessories.view_sha256(listing, owners)}), base.ACTOR, "Delete disposable accessory record")
        return self.sql("select max(id) from audit.change_set")[0][0]

    def seed(self, *, only=False, quantity=None, renamed=False):
        additions.AccessoryInsertUndoPgTests.seed(self, only=only)
        if quantity is not None:
            self.edit({"quantity": quantity}, self.rid)
        if renamed:
            self.edit({"name": "Renamed old record"}, self.rid)
        return self.delete()

    def apply(self, cid, preview=None, confirmation=True, **extra):
        preview = api.accessory_undo_view(cid) if preview is None else preview
        data = {"profile": "matt", "id": cid, "expect": preview["expect"], **extra}
        if confirmation is not OMIT:
            data["confirm_restore"] = confirmation
        return api.apply_accessory_undo(json.dumps(data).encode())

    def test_one_actual_insert_exact_full_row_id_and_no_other_physical_or_audit_changes(self):
        cid = self.seed()
        original, before = self.backend.undo_audit(cid), self.persisted()
        old = original[0]["before"]
        preview = api.accessory_undo_view(cid)
        self.assertEqual((preview["action"], preview["current"], preview["restored"], preview["confirmation_required"]),
                         ("accessory_add", None, old, True))
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("No URL fetch")), \
                mock.patch.object(cards, "resolve", side_effect=AssertionError("No card lookup")), \
                mock.patch.object(inventory, "image", side_effect=AssertionError("No image bytes")):
            receipt = self.apply(cid, preview)
        self.assertEqual((receipt["added_id"], receipt["restored"]), (self.rid, old))
        latest = self.sql("select max(id) from audit.change_set")[0][0]
        self.assertEqual(self.backend.undo_audit(latest), [{"id": int(receipt["revision"]), "table": "accessory",
            "op": "INSERT", "key": {"id": self.rid}, "before": None, "after": old}])
        self.assertEqual(self.sql("select actor,source,via,reason from audit.change_set where id=%s", (latest,)),
                         [("matt", "web", "tunnel", None)])
        self.assertEqual(receipt["sha256"], undo.list_sha(undo.raw_rows(self.fresh()), fixture.OWNERS))
        self.assertEqual(self.backend.undo_audit(cid), original)
        after = self.persisted()
        for table in base.TABLES:
            if table not in ("accessory", "decks_revision", "audit.change_set", "audit.row_change"):
                self.assertEqual(after[table], before[table], table)

    def test_empty_current_namespace_restores_exact_zero_or_positive_record_with_confirmation(self):
        for quantity in (0, 2):
            cid = self.seed(only=True, quantity=quantity)
            snapshot = self.fresh()
            self.assertEqual(snapshot.accessories, model.Sheet("magic/accessories.csv"))
            self.assertFalse(snapshot.decks or snapshot.products or snapshot.status.rows)
            receipt = self.apply(cid)
            self.assertEqual(receipt["restored"]["quantity"], str(quantity))
            self.assertEqual(receipt["restored"], undo.raw_rows(self.fresh())[0])

    def test_suffix_derives_exactly_but_changed_private_namespace_and_renamed_record_refuse_generically(self):
        additions.AccessoryInsertUndoPgTests.seed(self)
        base_id = self.rid
        self.edit({"owner": "user1"}, base_id, owners=None)
        additions.AccessoryInsertUndoPgTests.seed(self)
        self.assertEqual(self.rid, base_id + "-2")
        cid = self.delete()
        receipt = self.apply(cid)
        self.assertEqual(receipt["added_id"], base_id + "-2")
        cid = self.delete()
        self.delete(base_id, owners=None)
        before = self.persisted()
        unavailable = api.accessory_undo_view(cid)
        self.assertEqual(unavailable, {"available": False, "id": cid, "reason": api.UNSUPPORTED})
        self.assertNotIn(base_id, json.dumps(unavailable))
        self.assertEqual(self.persisted(), before)
        cid = self.seed(renamed=True)
        self.assertIs(api.accessory_undo_view(cid)["available"], False)

    def test_dangling_target_reference_blocks_reattachment_and_unrelated_current_kit_is_preserved(self):
        cid = self.seed()
        preview = api.accessory_undo_view(cid)
        original = self.fresh().deck("casual/fixture")
        rid = self.rid
        class KitFixture:
            kind = "fixture.kit-reference"
            def __init__(inner, text):
                inner.text = text
            def run(inner, snapshot):
                return snapshot.with_deck(original.replace(text=inner.text)), Summary("Disposable kit reference")
        text = original.text.replace("- **Built version:** target", "- **Built version:** target\n- **Deck box:** " + rid)
        inventory.apply(KitFixture(text), base.ACTOR, "Dangling disposable kit reference")
        before = self.persisted()
        with self.assertRaises(api.ApiError) as refused:
            self.apply(cid, preview)
        self.assertEqual(refused.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        inventory.apply(KitFixture(original.text.replace("a-sleeves", "b-shared")), base.ACTOR, "Other linked kit choice")
        current = self.fresh()
        self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
        self.apply(cid, preview)
        self.assertEqual(self.fresh().decks, current.decks)

    def test_hidden_owner_edits_do_not_bind_expect_but_target_recreate_delete_aba_and_replay_refuse(self):
        cid = self.seed()
        preview = api.accessory_undo_view(cid)
        self.edit({"notes": "Hidden current metadata"}, "c-hidden", frozenset({"user1", "shared"}))
        self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
        self.apply(cid, preview)
        with self.assertRaises(api.ApiError) as repeated:
            self.apply(cid, preview)
        self.assertEqual(repeated.exception.status, 409)
        self.delete()
        before = self.persisted()
        with self.assertRaises(api.ApiError) as aba:
            api.accessory_undo_view(cid)
        self.assertEqual(aba.exception.status, 409)
        self.assertEqual(self.persisted(), before)

    def test_historical_and_orphan_pictures_or_global_mixed_deletes_are_unavailable(self):
        from decklab.tests.test_accessory_fetch import jpeg
        additions.AccessoryInsertUndoPgTests.seed(self)
        inventory.apply(Op("image.put", {"name": self.rid + ".jpg", "content": jpeg()}), base.ACTOR, "Disposable photo")
        cid = self.delete()
        self.assertIs(api.accessory_undo_view(cid)["available"], False)
        cid = self.seed()
        rid = self.rid
        class Orphan:
            kind = "fixture.orphan-photo"
            def run(inner, snapshot):
                return snapshot.with_image(rid + ".jpg", jpeg()), Summary("Disposable orphan photo")
        inventory.apply(Orphan(), base.ACTOR, "Orphaned disposable picture")
        self.assertIs(api.accessory_undo_view(cid)["available"], False)
        additions.AccessoryInsertUndoPgTests.seed(self)
        listing = accessories.from_sheet(self.fresh().accessories, strict=True)
        rid = self.rid
        class Mixed:
            kind = "fixture.mixed-removal"
            def run(inner, snapshot):
                after, summary = Op("accessory.remove", {"id": rid, "owners": fixture.OWNERS,
                    "sha256": accessories.view_sha256(listing, fixture.OWNERS)}).run(snapshot)
                return after.with_accessories([{**row, "notes": "Other private update"} if row["id"] == "c-hidden"
                                               else row for row in undo.raw_rows(after)]), summary
        inventory.apply(Mixed(), base.ACTOR, "Mixed disposable deletion")
        cid = self.sql("select max(id) from audit.change_set")[0][0]
        before = self.persisted()
        with self.assertRaises(api.ApiError) as mixed:
            self.apply(cid, {"expect": "bad"}, confirmation=False)
        self.assertEqual(mixed.exception.status, 404)
        self.assertEqual(self.persisted(), before)

    def test_confirmation_and_cross_action_fields_and_actual_insert_failures_roll_back(self):
        cid = self.seed(only=True)
        preview, before = api.accessory_undo_view(cid), self.persisted()
        for confirmation in (OMIT, None, False, 1, "true"):
            with self.subTest(confirmation=confirmation), self.assertRaises(api.ApiError) as refused:
                self.apply(cid, preview, confirmation=confirmation)
            self.assertEqual(refused.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        for reason in (None, "", "Not for ADD"):
            with self.subTest(reason=reason), self.assertRaises(api.ApiError) as refused:
                self.apply(cid, preview, reason=reason)
            self.assertEqual(refused.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        original = undo.verify_saved
        def wrong(old, after, plan, actual):
            actual = copy.deepcopy(actual)
            actual[0]["after"]["quantity"] = "3"
            return original(old, after, plan, actual)
        with mock.patch.object(undo, "verify_saved", side_effect=wrong), self.assertRaises(api.ApiError) as refused:
            self.apply(cid, preview)
        self.assertEqual(refused.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        direct = undo.MetadataRestore(cid, fixture.OWNERS, preview["expect"], store=self.backend)
        with self.assertRaises(inventory.Invalid):
            inventory.apply(direct, base.ACTOR, "Missing direct confirmation")
        direct = undo.MetadataRestore(cid, fixture.OWNERS, preview["expect"], store=self.backend, confirm_restore=True)
        with self.assertRaises(inventory.Conflict):
            inventory.apply(direct, base.ACTOR, "Unexpected direct ADD reason", reason="Unexpected")
        self.assertEqual(self.persisted(), before)
        self.apply(cid, preview)

    def test_lost_insert_reply_is_not_retried_and_cannot_add_a_second_record(self):
        cid = self.seed()
        preview, original = api.accessory_undo_view(cid), self.backend._call
        calls = []
        def lost(work):
            calls.append(1)
            result = original(work)
            if len(calls) == 2:
                raise Unavailable("Synthetic lost INSERT reply")
            return result
        with mock.patch.object(self.backend, "_call", side_effect=lost), self.assertRaises(api.ApiError) as refused:
            self.apply(cid, preview)
        self.assertEqual((refused.exception.status, len(calls)), (503, 2))
        self.assertEqual(len([row for row in undo.raw_rows(self.fresh()) if row["id"] == self.rid]), 1)
        before = self.persisted()
        with self.assertRaises(api.ApiError) as stale:
            self.apply(cid, preview)
        self.assertEqual(stale.exception.status, 409)
        self.assertEqual(self.persisted(), before)
