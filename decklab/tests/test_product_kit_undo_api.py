"""Home-only complete product-kit projection, explicit consent and exact save receipts."""
import json
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import activity_undo, product_kit_undo as api
from decklab.tests import household_config, product_kit_undo_support as fixture
from decklab.tests.test_api import ApiTestCase


class ProductKitApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = fixture.Store()
        self.addCleanup(inventory.use(self.store))
        self.enterContext(self.identity("matt"))

    def identity(self, profile):
        return access.using({"profile": profile, "email": profile + "@example.com", "remote": True})

    def view(self):
        return api.view(fixture.CID)

    def apply(self, **extra):
        body = {"profile": "matt", "id": fixture.CID, "expect": self.view()["expect"], "confirm_kit": True, **extra}
        return api.apply(json.dumps(body))

    def test_whole_source_hint_and_preview_only_show_reviewed_kit_facts(self):
        rows = self.store.undo_audit_batch(fixture.CID)
        change = {"id": fixture.CID, "rows": rows, "total": 2}
        self.assertEqual(activity_undo.review_hint(change, {"id": fixture.CID}, {"id": "matt", "space": "home", "role": "admin"}),
                         {"review": True, "kind": "product_kit"})
        value = self.view()
        self.assertEqual(set(value), {"available", "id", "kind", "action", "label", "expect", "row_count", "rows", "kit_confirmation_required"})
        self.assertEqual(value["row_count"], 2)
        self.assertEqual(set(value["rows"][0]), {"file", "title", "current", "restored"})
        self.assertEqual(set(value["rows"][0]["current"]), {"sleeves", "deck_box"})
        self.assertNotIn("Keep alpha", json.dumps(value))
        self.assertIsNone(api.hint({**change, "more": 1}, {"id": fixture.CID}, {"id": "matt", "space": "home"}))

    def test_home_partner_can_review_and_apply_shared_kit_as_one_inverse(self):
        with self.identity("user1"):
            preview = self.view()
            result = api.apply(json.dumps({"profile": "user1", "id": fixture.CID, "expect": preview["expect"], "confirm_kit": True}))
        self.assertIs(result["saved"], True)
        self.assertEqual(result["rows"], preview["rows"])
        self.assertEqual(len(self.store.writes), 1)
        self.assertEqual(len(self.store.writes[0][-1]), 2)

    def test_outsiders_refuse_before_bad_id_body_or_product_labels(self):
        with self.identity("user2"), mock.patch.object(self.store, "product_kit_undo_review", side_effect=AssertionError("No home reads")):
            self.assertApiError(403, api.view, "bad")
            self.assertApiError(403, api.apply, "not json")
        self.assertEqual(self.store.writes, [])

    def test_stale_review_unchecked_or_nonboolean_kit_consent_never_writes(self):
        for value in (False, None, 1, "true"):
            self.assertApiError(400, lambda: self.apply(confirm_kit=value))
        self.assertApiError(409, lambda: self.apply(expect="0" * 64))
        self.assertApiError(400, lambda: self.apply(reason="Not a removal"))
        self.assertEqual(self.store.writes, [])

    def test_mixed_deck_or_changed_nonkit_source_never_yields_a_partial_preview(self):
        self.store.audit[fixture.CID].append({"id": 103, "table": "deck", "op": "UPDATE"})
        self.assertApiError(404, self.view)
        self.store = fixture.Store()
        self.addCleanup(inventory.use(self.store))
        self.store.audit[fixture.CID][0]["before"]["notes"] = "Changed beyond kit"
        result = self.view()
        self.assertIs(result["available"], False)
        self.assertEqual(self.store.writes, [])

    def test_forged_preview_or_extra_private_save_values_are_not_projected(self):
        plan = self.store.product_kit_undo_review(fixture.CID, fixture.OWNERS)
        for key, value in (("change_id", 44), ("owners", ["user2"]), ("expect", "bad"), ("row_count", 1)):
            with self.subTest(key=key), mock.patch.object(self.store, "product_kit_undo_review", return_value={**plan, key: value}):
                self.assertApiError(503, self.view)
        original = self.store.apply
        def extra(*args, **kwargs):
            after, summary = original(*args, **kwargs)
            summary.extra["product_kit_undo"]["PRIVATE"] = "Unexpected diagnostic"
            return after, summary
        with mock.patch.object(self.store, "apply", side_effect=extra):
            self.assertApiError(503, self.apply)
        self.assertEqual(len(self.store.writes), 1)
