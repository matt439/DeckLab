"""Unused image-free accessory INSERT inverses in disposable PostgreSQL only."""
import copy
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import accessories, cards, config, inventory
from decklab.lib.api import accessory_undo as api
from decklab.lib.inventory import Op, accessory_undo as undo, model, pg
from decklab.lib.state import Invalid, Unavailable
from decklab.tests import accessory_undo_support as fixture, db_support, household_config
from decklab.tests import test_accessory_undo_pg as existing

OMIT = object()


class AccessoryInsertUndoPgTests(db_support.DbTestCase):
    setUp = existing.AccessoryUndoPgTests.setUp
    sql = existing.AccessoryUndoPgTests.sql
    fresh = existing.AccessoryUndoPgTests.fresh
    persisted = existing.AccessoryUndoPgTests.persisted
    edit = existing.AccessoryUndoPgTests.edit

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-accessory-insert-undo-pg-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Accessory INSERT Undo needs a disposable test database")
        db_support.seed_membership(cls.dbname, household_config.PROFILES)

    def seed(self, *, only=False, orphan=False, mixed=False):
        if only:
            initial = fixture.snapshot().replace(imports={}, accessories=model.Sheet("magic/accessories.csv"),
                                                 accessory_images={}, decks={})
            pg.write_model(initial, existing.ACTOR, "Fresh disposable home without kit", contents={},
                           dbname=self.dbname, decks=True, images={}, replace=True)
        current = accessories.from_sheet(self.fresh().accessories, strict=True)
        row = {"kind": "deck_box", "owner": "matt", "brand": "Fixture", "name": "Unused box", "colour": "blue",
               "quantity": 2, "capacity": 100, "link": "https://example.com/record", "notes": "New unused fixture"}
        class Addition:
            kind = "fixture.accessory-addition"
            def run(inner, snapshot):
                after, summary = Op("accessory.add", {"row": row, "sha256": accessories.view_sha256(current, fixture.OWNERS),
                    "owners": fixture.OWNERS, "image": None}).run(snapshot)
                if orphan:
                    after = after.with_image(summary.extra["id"] + ".jpg", b"Unaudited orphan fixture picture")
                if mixed:
                    after = after.with_accessories([{**item, "notes": "Mixed private change"} if item["id"] == "c-hidden"
                                                    else item for item in undo.raw_rows(after)])
                return after, summary
        inventory.apply(Addition(), existing.ACTOR, "Add unused disposable accessory")
        cid = self.sql("select max(id) from audit.change_set")[0][0]
        source = self.backend.undo_audit(cid)
        self.rid = next(item["after"]["id"] for item in source if item["op"] == "INSERT")
        return cid

    def apply(self, cid, preview=None, reason="  Correct\n accidental addition.  "):
        preview = api.accessory_undo_view(cid) if preview is None else preview
        data = {"profile": "matt", "id": cid, "expect": preview["expect"]}
        if reason is not OMIT:
            data["reason"] = reason
        return api.apply_accessory_undo(json.dumps(data).encode())

    def kit(self, rid, *, field="deck_box"):
        deck = self.fresh().deck("casual/fixture")
        return inventory.apply(Op("kit.set", {"holders": [{"id": deck.id, "expected": deck.sha256}],
            "changes": [{"holder": deck.id, "field": field, "value": rid}], "owners": fixture.OWNERS}),
            existing.ACTOR, "Disposable kit choice")

    def test_actual_one_delete_reason_receipt_and_all_unrelated_physical_data_preserved(self):
        cid = self.seed()
        source, before = self.backend.undo_audit(cid), self.persisted()
        preview = api.accessory_undo_view(cid)
        self.assertEqual((preview["action"], preview["current"], preview["restored"], preview["reason_required"]),
                         ("accessory_remove", source[0]["after"], None, True))
        with mock.patch.object(cards, "resolve", side_effect=AssertionError("No card index")), \
                mock.patch.object(inventory, "image", side_effect=AssertionError("No image bytes")):
            receipt = self.apply(cid, preview)
        self.assertEqual((receipt["removed_id"], receipt["restored"]), (self.rid, None))
        new_id = self.sql("select max(id) from audit.change_set")[0][0]
        actual = self.backend.undo_audit(new_id)
        self.assertEqual(actual, [{"id": int(receipt["revision"]), "table": "accessory", "op": "DELETE",
                                  "key": {"id": self.rid}, "before": source[0]["after"], "after": None}])
        self.assertEqual(self.sql("select actor,source,via,reason from audit.change_set where id=%s", (new_id,)),
                         [("matt", "web", "tunnel", "Correct accidental addition.")])
        self.assertEqual(receipt["sha256"], undo.list_sha(undo.raw_rows(self.fresh()), fixture.OWNERS))
        self.assertEqual(self.backend.undo_audit(cid), source)
        after = self.persisted()
        for table in existing.TABLES:
            if table not in ("accessory", "decks_revision", "audit.change_set", "audit.row_change"):
                self.assertEqual(after[table], before[table], table)

    def test_fresh_empty_home_last_accessory_becomes_canonical_missing_sheet(self):
        cid = self.seed(only=True)
        initial = self.fresh()
        self.assertFalse(initial.products or initial.status.rows or initial.decks)
        self.assertEqual(len(undo.raw_rows(initial)), 1)
        receipt = self.apply(cid)
        self.assertIsNone(receipt["restored"])
        self.assertEqual(receipt["sha256"], undo.list_sha([], fixture.OWNERS))
        saved = self.fresh()
        self.assertEqual(saved.accessories, model.Sheet("magic/accessories.csv"))
        self.assertEqual(undo.raw_rows(saved, allow_empty=True), [])

    def test_kit_race_refuses_but_known_unrelated_kit_change_does_not_invalidate(self):
        cid = self.seed()
        preview = api.accessory_undo_view(cid)
        self.kit(self.rid)
        before = self.persisted()
        with self.assertRaises(api.ApiError) as caught:
            self.apply(cid, preview)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.persisted(), before)
        self.kit(None)
        self.kit("b-shared", field="sleeves")
        current = self.fresh()
        self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
        self.apply(cid, preview)
        self.assertEqual(self.fresh().decks, current.decks)

    def test_hidden_owner_edit_passes_but_target_aba_and_replay_refuse(self):
        cid = self.seed()
        preview = api.accessory_undo_view(cid)
        self.edit({"notes": "Hidden owner's current note"}, "c-hidden", frozenset({"user1", "shared"}))
        self.assertEqual(api.accessory_undo_view(cid)["expect"], preview["expect"])
        self.apply(cid, preview)
        written = self.persisted()
        with self.assertRaises(api.ApiError) as repeated:
            self.apply(cid, preview)
        self.assertEqual(repeated.exception.status, 409)
        self.assertEqual(self.persisted(), written)
        cid = self.seed()
        for note in ("Away", "New unused fixture"):
            self.edit({"notes": note}, self.rid)
        with self.assertRaises(api.ApiError) as aba:
            api.accessory_undo_view(cid)
        self.assertEqual(aba.exception.status, 409)

    def test_complete_mixed_source_and_unaudited_orphan_picture_are_not_removable(self):
        for kwargs, status in (({"mixed": True}, 404), ({"orphan": True}, None)):
            cid = self.seed(**kwargs)
            before = self.persisted()
            if status:
                with self.assertRaises(api.ApiError) as caught:
                    api.accessory_undo_view(cid)
                self.assertEqual(caught.exception.status, status)
            else:
                self.assertIs(api.accessory_undo_view(cid)["available"], False)
            self.assertEqual(self.persisted(), before)

    def test_reason_required_normalized_and_supplied_only_for_remove_before_any_commit(self):
        cid = self.seed()
        preview, before = api.accessory_undo_view(cid), self.persisted()
        for reason in (OMIT, None, "", " \n ", "x" * 201, "bad\0reason", 3):
            with self.subTest(reason=reason), self.assertRaises(api.ApiError) as caught:
                self.apply(cid, preview, reason)
            self.assertEqual(caught.exception.status, 400)
            self.assertEqual(self.persisted(), before)
        self.apply(cid, preview)
        # Normal UPDATE refuses even an explicitly null reason.
        self.edit({"notes": "Update fixture"}, "b-shared")
        update_id = self.sql("select max(id) from audit.change_set")[0][0]
        before = self.persisted()
        with self.assertRaises(api.ApiError) as caught:
            self.apply(update_id, reason=None)
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.persisted(), before)

    def test_late_actual_delete_or_reason_failure_rolls_back_rows_and_audit(self):
        cid = self.seed(only=True)
        preview, before = api.accessory_undo_view(cid), self.persisted()
        original = undo.verify_saved
        for mode in ("wrong-before", "after-missing", "wrong-removed-id"):
            def corrupt(old, after, plan, actual):
                actual = copy.deepcopy(actual)
                if mode == "wrong-before":
                    actual[0]["before"]["quantity"] = "1"
                elif mode == "after-missing":
                    del actual[0]["after"]
                else:
                    actual[0]["key"] = {"id": "another"}
                return original(old, after, plan, actual)
            with self.subTest(mode=mode), mock.patch.object(undo, "verify_saved", side_effect=corrupt), \
                    self.assertRaises(api.ApiError) as caught:
                self.apply(cid, preview)
            self.assertEqual(caught.exception.status, 409)
            self.assertEqual(self.persisted(), before)
        # Direct trusted callers must also record the reviewed canonical reason.
        op = undo.MetadataRestore(cid, fixture.OWNERS, preview["expect"], store=self.backend, reason="Test fixture")
        with self.assertRaises(inventory.Conflict):
            inventory.apply(op, existing.ACTOR, "Omitted audit reason fixture")
        self.assertEqual(self.persisted(), before)
        self.apply(cid, preview)

    def test_lost_reply_after_delete_is_not_retried_or_acknowledged(self):
        cid = self.seed()
        preview, original = api.accessory_undo_view(cid), self.backend._call
        calls = []
        def lost(work):
            calls.append(1)
            result = original(work)
            # The first call is immutable-source preflight; lose only the committing reply.
            if len(calls) == 2:
                raise Unavailable("Synthetic lost DELETE reply")
            return result
        with mock.patch.object(self.backend, "_call", side_effect=lost), self.assertRaises(api.ApiError) as caught:
            self.apply(cid, preview)
        self.assertEqual((caught.exception.status, len(calls)), (503, 2))
        self.assertNotIn(self.rid, {row["id"] for row in undo.raw_rows(self.fresh())})
        before = self.persisted()
        with self.assertRaises(api.ApiError) as stale:
            self.apply(cid, preview)
        self.assertEqual(stale.exception.status, 409)
        self.assertEqual(self.persisted(), before)
