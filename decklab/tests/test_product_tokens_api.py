"""Guarded product token picker over disposable records and HTTP route dispatch."""
import json
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import product_tokens as api, settings
from decklab.lib.api.common import ApiError
from decklab.tests.test_assembly_completion import PROFILES
from decklab.tests.test_product_tokens import PACKED, STEM, ProductTokensCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401
from decklab.tests import test_server as server


class ProductTokensApiTests(ProductTokensCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(settings, "_config_profiles", return_value=PROFILES)
        patch.start()
        self.addCleanup(patch.stop)

    def body(self, **changes):
        snapshot = inventory.current()
        return {"profile": "matt", "stem": STEM, "expect": api.status_sha256(snapshot),
                "tokens_sha256": self.op(snapshot=snapshot).params["tokens_sha256"],
                "cards": [{"row": 0, "quantity": 2}], **changes}

    def save(self, **changes):
        return api.save_product_tokens(json.dumps(self.body(**changes)))

    def test_picker_saves_one_record_noop_and_clear_with_receipts(self):
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            found = self.save()
        self.assertEqual(apply.call_count, 1)
        self.assertTrue(found["saved"])
        self.assertEqual(found["token_cards"], PACKED)
        self.assertEqual(found["status_sha256"], api.status_sha256(inventory.current()))
        self.assertFalse(self.save()["saved"])
        self.assertEqual(self.save(cards=[])["token_cards"], "")
        self.assertEqual(self.row().text("notes"), "Keep this note")

    def test_stale_rows_product_or_token_receipts_do_not_apply(self):
        for change in ({"expect": "a" * 64}, {"tokens_sha256": "b" * 64}):
            with self.subTest(change=change), mock.patch.object(inventory, "apply") as apply:
                with self.assertRaises(ApiError) as caught:
                    self.save(**change)
                self.assertEqual(caught.exception.status, 409)
                apply.assert_not_called()

    def test_row_shapes_and_quantity_bounds_are_validated(self):
        for cards in (None, {}, [{"row": True, "quantity": 1}], [{"row": 999, "quantity": 1}],
                      [{"row": 0, "quantity": -1}], [{"row": 0, "quantity": 10000}], [{"row": 0, "quantity": 1, "extra": 1}]):
            with self.subTest(cards=cards), self.assertRaises(ApiError) as caught:
                self.save(cards=cards)
            self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.row().text("token_cards"), "")

    def test_malformed_receipt_types_and_short_hashes_refuse_before_row_lookup(self):
        for key in ("expect", "tokens_sha256"):
            for value in (False, 1, {}, "a" * 12, "A" * 64):
                with self.subTest(key=key, value=value), mock.patch.object(api.ops_products, "product_row",
                        side_effect=AssertionError("validate receipt first")):
                    with self.assertRaises(ApiError) as caught:
                        self.save(**{key: value})
                    self.assertEqual(caught.exception.status, 400)

    def test_home_read_and_product_permissions_run_before_product_read(self):
        body = self.body()
        for who in ("user1", "user2"):
            with self.subTest(who=who), access.using({"profile": who, "email": "", "remote": True}), \
                    mock.patch.object(api.ops_products, "product_row", side_effect=AssertionError("guard first")):
                with self.assertRaises(ApiError) as caught:
                    api.save_product_tokens(json.dumps({**body, "profile": who}))
                self.assertEqual(caught.exception.status, 403)

    def test_null_token_receipt_clears_only_while_sheet_remains_absent(self):
        self.save()
        (self.magic / "tokens.csv").unlink()
        self.assertEqual(self.save(cards=[], tokens_sha256=None)["token_cards"], "")
        self.assertIsNone(self.save(cards=[], tokens_sha256=None)["tokens_sha256"])


class ProductTokensHttpTests(server.ServerTestCase):
    def test_route_uses_same_origin_method_and_query_guards(self):
        body = b'{"profile":"matt","fixture":true}'
        with mock.patch.object(api, "save_product_tokens", return_value={"saved": True}) as save:
            self.assertEqual(self.get_json("/api/product/token-cards", method="POST", body=body,
                headers=dict(server.WRITE, Origin=f"http://127.0.0.1:{self.port}")), {"saved": True})
            save.assert_called_once_with(body)
            save.reset_mock()
            self.assertError("/api/product/token-cards", 403, method="POST", body=b"{}", headers={"Content-Type": "application/json"})
            self.assertError("/api/product/token-cards?extra=1", 400, method="POST", body=body, headers=server.WRITE)
            for method in ("GET", "HEAD", "PUT", "DELETE"):
                code, _, _ = self.request(method, "/api/product/token-cards")
                self.assertEqual(code, 405)
            save.assert_not_called()
