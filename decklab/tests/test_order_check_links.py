"""Arrival-check associations through ordinary APIs and disposable inventory files.

OrderCheckLinksTests is a tests-only mixin reusable with a disposable PG backend.
The file-backed class is the only runnable class in this module.
"""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import receipts, shopping_orders
from decklab.lib.api import shopping_order_changes as api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import check_links, files, receive, rules
from decklab.lib.inventory.files import FileInventory
from decklab.lib.inventory.model import Order
from decklab.lib.state import Invalid
from decklab.tests import test_shopping_order_changes as fixture
from decklab.tests import test_shopping_orders as order_fixture

ORDER = fixture.ORDER
CLAUDE = order_fixture.CLAUDE


class OrderCheckLinksTests:
    request = fixture.OrderChangeApiTests.request
    checks = fixture.OrderChangeApiTests.checks
    save = fixture.OrderChangeApiTests.save
    refused = fixture.OrderChangeApiTests.refused

    def start(self, case):
        fixture.OrderChangeApiTests.start(self, case)
        shopping_orders._previews.clear()
        self.addCleanup(shopping_orders._previews.clear)

    def component(self, cid="cards", order=ORDER, snapshot=None):
        snapshot = self.backend.load() if snapshot is None else snapshot
        return next(item for item in snapshot.order(order).components if item.id == cid)

    def payload(self, cid="cards", order=ORDER):
        snapshot = self.backend.load()
        component = self.component(cid, order, snapshot)
        fields = rules.TOKEN_FIELDS if component.kind == "tokens" else rules.FIELDS
        return [{key: row.text(key) for key in fields} for row in snapshot.payloads[component.path].rows], fields

    def target(self, row=1, cid="cards", order=ORDER):
        rows, fields = self.payload(cid, order)
        return {"row": row, "payload_sha256": check_links.digest(rows, fields)}

    def board(self, order=ORDER):
        # Card pictures are unrelated to the association; no cache or download is needed.
        with mock.patch.object(receipts, "_index_info", return_value=(None, None)), \
                mock.patch.object(receipts, "_receipt_today", return_value="2026-10-08"):
            return receipts.receipt_view(order)

    def board_component(self, cid="cards", order=ORDER):
        return next(item for item in self.board(order)["components"] if item["id"] == cid)

    def add_link(self, text="Inspect printing", row=1, cid="cards", order=ORDER):
        preview = self.checks(component=cid, order=order, add=[text], target=self.target(row, cid, order))
        return preview, self.save(preview["preview"])

    def change(self, action, component="cards", **changes):
        data = self.request(action=action, component=component, **changes)
        data.pop("values")
        return api.preview_order_change(json.dumps(data))

    def unchanged(self, before):
        after = self.backend.load()
        self.assertEqual(files.render(after, decks=True), files.render(before, decks=True))
        self.assertEqual((after.revision, after.decks_revision), (before.revision, before.decks_revision))

    def test_targeted_preview_is_read_only_and_save_keeps_duplicate_check_ordinals(self):
        before = self.backend.load()
        rows, fields = self.payload()
        text = self.component().checks[0]
        selected = self.target(2)
        with mock.patch.object(api, "_require_cards", side_effect=AssertionError("check authoring needs no card index")):
            preview = self.checks(add=[text], target=selected)
            self.unchanged(before)
            saved = self.save(preview["preview"])
        expected = {"component": "cards", "check": 3, "text": text, "row": 2,
                    "row_sha256": check_links.row_digest(rows[1], fields), **{"payload_sha256": selected["payload_sha256"]}}
        self.assertEqual(preview["targeted_check"], expected)
        self.assertEqual(saved["targeted_check"], expected)
        component = self.component()
        self.assertEqual(component.checks, ["Record conditions", "Check languages", "Record conditions"])
        self.assertEqual(component.check_links["links"][0]["check"], 3)
        self.assertEqual((component.status, component.verified_checks), ("pending", None))
        self.assertEqual(self.payload(), (rows, fields))
        self.assertEqual(self.backend.load().order(ORDER).audit_notes, before.order(ORDER).audit_notes)
        self.assertNotIn("check_links", json.dumps(saved))

    def test_receipt_board_projects_authoritative_proofs_and_never_raw_metadata(self):
        self.add_link(row=2)
        before = self.backend.load()
        part = self.board_component()
        rows, fields = self.payload()
        self.assertEqual(part["check_targets"], [None, None, {"row": 2,
                         "row_sha256": check_links.row_digest(rows[1], fields)}])
        self.assertEqual(part["check_targeting"], {"available": True,
                         "payload_sha256": check_links.digest(rows, fields),
                         "row_sha256s": [check_links.row_digest(row, fields) for row in rows]})
        self.assertEqual(part["checks"], self.component().checks)
        self.assertNotIn("check_links", json.dumps(part))
        self.unchanged(before)

    def test_token_check_target_uses_all_ten_authoritative_columns(self):
        preview, saved = self.add_link("Inspect front and reverse", cid="tokens")
        rows, fields = self.payload("tokens")
        expected = {"component": "tokens", "check": 1, "text": "Inspect front and reverse", "row": 1,
                    "payload_sha256": check_links.digest(rows, fields),
                    "row_sha256": check_links.row_digest(rows[0], fields)}
        self.assertEqual(preview["targeted_check"], expected)
        self.assertEqual(saved["targeted_check"], expected)
        part = self.board_component("tokens")
        self.assertEqual(part["check_targets"], [{"row": 1, "row_sha256": expected["row_sha256"]}])
        self.assertEqual(part["rows"], rows)
        self.assertIsNone(self.component("tokens").verified_checks)

    def test_malformed_and_stale_target_proofs_refuse_without_writes(self):
        current = self.target()
        bad = [None, [], "private target", {}, {"row": 1}, current | {"extra": "ignored"},
               current | {"row": True}, current | {"row": 0}, current | {"row": 3}, current | {"row": "1"},
               current | {"payload_sha256": "A" * 64}, current | {"payload_sha256": "0" * 64}]
        for selected in bad:
            data = self.request(action="checks", component="cards", add=["Inspect printing"], target=selected)
            data.pop("values")
            with self.subTest(target=selected):
                self.refused(400, data)
        data = self.request(action="checks", component="cards", withdraw=[1], target=current)
        data.pop("values")
        self.refused(400, data)

    def test_a_saved_preview_cannot_attach_to_a_later_revision(self):
        preview = self.checks(add=["Inspect printing"], target=self.target())
        self.save(self.checks(add=["A later general check"])["preview"])
        before = self.backend.load()
        with self.assertRaises(ApiError) as caught:
            self.save(preview["preview"])
        self.assertEqual(caught.exception.status, 409)
        self.unchanged(before)
        self.assertIsNone(self.component().check_links)

    def test_legacy_and_new_general_checks_keep_their_text_without_row_inference(self):
        before = self.component().checks
        self.assertEqual(self.board_component()["check_targets"], [None] * len(before))
        for text in ("Inspect Elvish Mystic", "Check every card", "Record conditions"):
            preview = self.checks(add=[text])
            self.assertNotIn("targeted_check", preview)
            self.save(preview["preview"])
        part = self.board_component()
        self.assertEqual(part["checks"], before + ["Inspect Elvish Mystic", "Check every card", "Record conditions"])
        self.assertEqual(part["check_targets"], [None] * len(part["checks"]))
        self.assertIsNone(self.component().check_links)

    def test_new_order_checks_are_general_until_explicitly_authored_against_a_row(self):
        data = order_fixture.OrderApiTests.request(self, fulfils=[])
        data["record"]["id"] = "2026-10-15-unscoped"
        data["cards"]["checks"] = ["Inspect Elvish Mystic"]
        preview = shopping_orders.preview_order(json.dumps(data))
        saved = shopping_orders.apply_order(json.dumps({"profile": "matt", "preview": preview["preview"]}))
        self.assertTrue(saved["saved"])
        component = self.component(order=data["record"]["id"])
        self.assertEqual(component.checks, ["Inspect Elvish Mystic"])
        self.assertIsNone(component.check_links)
        self.assertEqual(self.board_component(order=data["record"]["id"])["check_targets"], [None])

    def test_product_checks_remain_general_and_cannot_target_rows(self):
        order = "2026-10-02-precon"
        preview = self.checks(component="precon", order=order, add=["Inspect product tokens"])
        self.assertNotIn("targeted_check", preview)
        self.save(preview["preview"])
        part = self.board_component("precon", order)
        self.assertEqual(part["checks"], ["Inspect product tokens"])
        self.assertEqual(part["check_targets"], [None])
        self.assertFalse(part["check_targeting"]["available"])
        data = self.request(action="checks", order=order, component="precon", add=["Inspect"], target=self.target())
        data.pop("values")
        self.refused(400, data)

    def test_withdrawal_reindexes_the_exact_duplicate_and_removing_target_clears_only_its_link(self):
        self.add_link("Record conditions", row=2)
        proof = self.board_component()["check_targets"][2]
        self.save(self.checks(withdraw=[1])["preview"])
        self.assertEqual(self.component().checks, ["Check languages", "Record conditions"])
        self.assertEqual(self.component().check_links["links"][0]["check"], 2)
        self.assertEqual(self.board_component()["check_targets"], [None, proof])
        self.save(self.checks(withdraw=[2])["preview"])
        self.assertEqual(self.component().checks, ["Check languages"])
        self.assertIsNone(self.component().check_links)
        self.assertIsNone(self.component().verified_checks)

    def test_payload_correction_clears_links_while_preserving_every_check_and_verification_state(self):
        self.add_link(row=2)
        before = self.component()
        rows, _ = self.payload()
        rows[0]["notes"] = "Corrected recorded facts"
        preview = self.change("edit", rows=rows)
        self.save(preview["preview"])
        after = self.component()
        self.assertEqual((after.checks, after.verified_checks, after.status),
                         (before.checks, before.verified_checks, "pending"))
        self.assertIsNone(after.check_links)
        self.assertEqual(self.board_component()["check_targets"], [None] * len(after.checks))

    def test_explicit_split_copies_checks_as_general_without_transferring_row_positions(self):
        self.add_link(row=1)
        before = self.component()
        preview = self.change("split", new_id="cards-split", take=[{"row": 1, "quantity": 1}])
        self.save(preview["preview"])
        for cid in ("cards", "cards-split"):
            part = self.component(cid)
            self.assertEqual((part.checks, part.verified_checks, part.status), (before.checks, None, "pending"))
            self.assertIsNone(part.check_links)
            self.assertEqual(self.board_component(cid)["check_targets"], [None] * len(part.checks))

    def test_row_target_never_bypasses_the_whole_component_physical_verification_guard(self):
        self.add_link(row=1)
        before = self.backend.load()
        operation = receive.op(ORDER, [{"id": "cards", "verified": False}], "2026-10-08")
        with self.assertRaises(Invalid):
            inventory.preview(operation)
        self.unchanged(before)
        self.assertIsNone(self.component().verified_checks)

    def test_full_receipt_archives_checks_as_strings_and_drops_actionable_row_links(self):
        self.add_link(row=2)
        checks = list(self.component().checks)
        operation = receive.op(ORDER, [{"id": "cards", "verified": True}], "2026-10-08")
        inventory.apply(operation, CLAUDE, "Receive synthetic checked cards")
        part = self.component()
        self.assertEqual((part.status, part.checks, part.verified_checks), ("received", [], checks))
        self.assertIsNone(part.check_links)

    def test_partial_receipt_keeps_remainder_checks_and_verified_history_without_row_links(self):
        self.add_link(row=1)
        checks = list(self.component().checks)
        operation = receive.op(ORDER, [{"id": "cards", "verified": True,
                                       "take": [{"row": 1, "quantity": 1}]}], "2026-10-08")
        inventory.apply(operation, CLAUDE, "Receive one synthetic checked copy")
        pending, arrived = self.component(), self.component("cards-received-1")
        self.assertEqual((pending.status, pending.checks, pending.verified_checks), ("pending", checks, None))
        self.assertEqual((arrived.status, arrived.checks, arrived.verified_checks), ("received", [], checks))
        self.assertIsNone(pending.check_links)
        self.assertIsNone(arrived.check_links)

    def test_future_or_stale_raw_metadata_stays_private_and_checks_remain_general(self):
        self.add_link(row=1)
        before = self.backend.load()
        for raw in ({"version": 99, "links": [{"private": "synthetic raw association marker"}]},
                    {"version": 1, "links": [{**self.component().check_links["links"][0],
                                              "row_sha256": "0" * 64}]}):
            record = before.order(ORDER).record()
            record["components"][0]["check_links"] = copy.deepcopy(raw)
            snapshot = before.with_order(Order(before.order(ORDER).file, record))
            with self.subTest(metadata=raw), mock.patch.object(inventory, "current", return_value=snapshot):
                part = self.board_component()
            self.assertEqual(part["checks"], self.component().checks)
            self.assertEqual(part["check_targets"], [None] * len(part["checks"]))
            self.assertNotIn("check_links", json.dumps(part))
            self.assertNotIn("synthetic raw association marker", json.dumps(part))
        self.unchanged(before)

    def test_non_home_member_cannot_read_targets_or_author_checks_before_inventory_access(self):
        data = self.request(action="checks", component="cards", add=["Inspect"], target=self.target())
        data.pop("values")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}), \
                mock.patch.object(inventory, "current", side_effect=AssertionError("private inventory read")):
            for call in (lambda: api.preview_order_change(json.dumps(data)), lambda: self.board()):
                with self.assertRaises(ApiError) as caught:
                    call()
                self.assertEqual(caught.exception.status, 403)


class FileOrderCheckLinksTests(OrderCheckLinksTests, unittest.TestCase):
    def setUp(self):
        case = fixture.contract.build_tree(fixture.changes_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)


if __name__ == "__main__":
    unittest.main()
