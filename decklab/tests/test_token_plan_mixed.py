"""Mixed automatic token plans save only disposable decks and actual product boxes."""
import copy
import csv
import io
from unittest import mock

from decklab.lib import access, cards, decks, inventory, tokens
from decklab.lib.api import guard, token_plan as api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, kit, ops_decks, ops_products, ops_token_plan, rules
from decklab.lib.state import Actor
from decklab.lib.tokens import plan_products, products
from decklab.tests import household_config
from decklab.tests import test_api_tokens as fixture, test_token_reservation as reservation

ACTOR = Actor("matt", "Matt", "home", "web")
STEMS = ("mixed-box-a", "mixed-box-b")


class MixedPlanCase(fixture.TokensApiTestCase):
    loaded = None

    @classmethod
    def setUpClass(cls):
        cls.loaded = cards._prepare(cards.build_index(fixture.FIXTURES / "tokens_cards.jsonl",
            fixture.FIXTURES / "oracle_tags.jsonl", {}, log=lambda *args: None))

    def index(self):
        return self.loaded

    def setUp(self):
        household_config.use(self)
        super().setUp()
        for stem in STEMS:
            self.write(f"products/{stem}.csv", "section,name,set,collector_number,finish,quantity\n"
                       "deck,Army of the Damned,c13,69,nonfoil,1\n")
        self.write("products/mixed-box-a.csv", "deck,section,name,set,collector_number,finish,quantity\n"
                   "One,deck,Army of the Damned,c13,69,nonfoil,1\n"
                   "Two,deck,Army of the Damned,c13,69,nonfoil,1\n")
        rows = [{"file": f"{stem}.csv", "status": "owned", "intact": "yes", "notes": f"Keep {stem}"}
                for stem in STEMS]
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=rules.STATUS_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        self.write("products/status.csv", out.getvalue())
        self.write("decks/casual/a.md", reservation.built("A Deck"))

    def preview(self, space=None):
        with inventory.pinned():
            return api.plan_view(space)

    def operation(self, space="home"):
        with inventory.pinned():
            result, _ = api._plan(space)
        items = []
        for item in result["decks"]:
            if not item["changed"]:
                continue
            decks.set_token_cards(item["parsed"], decks.parse_token_cards(item["after"]))
            items.append({"id": item["id"], "text": decks.render_deck_file(item["parsed"]),
                          "base_sha256": item["sha256"]})
        return result, inventory.Op(ops_token_plan.KIND, {"space": space, "items": items,
            "products": [{"stem": p["stem"], "token_cards": p["after"]} for p in result["products"] if p["changed"]],
            "expected_inventory_revision": result["inventory_revision"], "expected_decks_revision": result["decks_revision"],
            "expected_status_sha256": result["status_sha256"], "tokens_sha256": result["tokens_sha256"]})


class MixedTokenPlanApiTests(MixedPlanCase):
    def test_preview_has_actual_boxes_child_needs_and_public_projection_only(self):
        plan = self.preview()
        self.assertEqual((plan["changes"], plan["product_changes"]), (1, 2))
        self.assertEqual([p["stem"] for p in plan["products"]], list(STEMS))
        first, second = plan["products"]
        self.assertIsNone(first["link"])
        self.assertEqual(second["link"], f"product/{STEMS[1]}")
        self.assertEqual([d["id"] for d in first["decks"]], [f"product/{STEMS[0]}/one", f"product/{STEMS[0]}/two"])
        for product in plan["products"]:
            self.assertTrue(product["editable"])
            self.assertEqual(set(product), {"stem", "holder", "title", "link", "before", "after", "lines", "changed", "decks", "editable"})
            self.assertEqual(product["before"], "")
            for child in product["decks"]:
                self.assertEqual(set(child), {"id", "title", "packs", "short", "spares"})
                for pack in child["packs"]:
                    self.assertEqual(set(pack), {"token", "card", "side", "verdict"})

    def test_apply_is_one_operation_and_preserves_unrelated_records_and_legacy_noop_response(self):
        plan = self.preview()
        before = inventory.current()
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            answer = self.call(api.apply_plan, sha256=plan["sha256"])
        self.assertEqual(answer, {"saved": 1, "decks": ["casual/a"], "saved_products": 2, "products": list(STEMS)})
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(apply.call_args.args[0].kind, ops_token_plan.KIND)
        after = inventory.current()
        self.assertEqual(after.tokens, before.tokens)
        self.assertEqual(after.products, before.products)
        for product in plan["products"]:
            row = ops_products.product_row(after, product["stem"])
            self.assertEqual(row.text("token_cards"), product["after"])
            self.assertEqual(row.text("notes"), f"Keep {product['stem']}")
        again = self.preview()
        self.assertEqual((again["changes"], again["product_changes"]), (0, 0))
        self.assertEqual(self.call(api.apply_plan, sha256=again["sha256"]), {"saved": 0, "decks": []})

    def test_missing_product_permission_refuses_every_write(self):
        path = self.magic / "decks/casual/a.md"
        path.write_text(path.read_text().replace("Played by:** either", "Played by:** wife"), encoding="utf-8")
        with access.using({"profile": "user1", "email": "", "remote": True}):
            plan = self.preview()
            self.assertTrue(all(not p["editable"] for p in plan["products"]))
            before = self.magic_files()
            with mock.patch.object(inventory, "apply") as apply:
                with self.assertRaises(ApiError) as caught:
                    self.call(api.apply_plan, profile="user1", sha256=plan["sha256"])
                self.assertEqual(caught.exception.status, 403)
                apply.assert_not_called()
            self.assertEqual(self.magic_files(), before)

    def test_tokens_write_permission_runs_before_plan_read_on_both_routes(self):
        with mock.patch.object(guard, "require_space_write", side_effect=ApiError(403, "private")), \
                mock.patch.object(api, "_plan", side_effect=AssertionError("permission first")):
            with self.assertRaises(ApiError):
                self.preview()
            with self.assertRaises(ApiError):
                self.call(api.apply_plan, sha256="a" * 64)

    def test_member_plan_never_reads_home_products_and_keeps_old_deck_only_response(self):
        self.write("people/user2/decks/casual/own.md", reservation.built("Own").replace("- **Played by:** either\n", ""))
        self.write("people/user2/tokens.csv", fixture.ROWS)
        with access.using({"profile": "user2", "email": "", "remote": True}), \
                mock.patch.object(plan_products, "gather", side_effect=AssertionError("home products read")), \
                mock.patch.object(products, "records", side_effect=AssertionError("home records read")), \
                mock.patch.object(kit, "status_sha256", side_effect=AssertionError("home status read")), \
                mock.patch.object(ops_products, "product_row", side_effect=AssertionError("product lookup")):
            plan = self.preview("user2")
            self.assertEqual(plan["products"], [])
            self.assertEqual(plan["product_changes"], 0)
            answer = self.call(api.apply_plan, profile="user2", space="user2", sha256=plan["sha256"])
            self.assertEqual(answer, {"saved": 1, "decks": ["user2/casual/own"]})


class MixedTokenPlanOperationTests(MixedPlanCase):
    def test_duplicate_product_or_late_invalid_record_refuses_before_staging(self):
        _, op = self.operation()
        before = self.magic_files()
        for changes in ([op.params["products"][0], op.params["products"][0]],
                        [op.params["products"][0], {"stem": STEMS[1], "token_cards": "Broken record"}]):
            with self.subTest(changes=changes), mock.patch.object(ops_decks, "token_cards", side_effect=AssertionError("validate all first")):
                with self.assertRaises(inventory.Invalid):
                    inventory.apply(inventory.Op(op.kind, {**op.params, "products": changes}), ACTOR, "Refuse mixed fixture")
        self.assertEqual(self.magic_files(), before)

    def test_failure_after_staging_first_product_still_writes_nothing(self):
        _, op = self.operation()
        before = self.magic_files()
        real = ops_products.set_tokens

        def fail_second(snapshot, **kwargs):
            if kwargs["stem"] == STEMS[1]:
                raise inventory.Invalid("Disposable second product refused")
            return real(snapshot, **kwargs)

        with mock.patch.object(ops_products, "set_tokens", side_effect=fail_second):
            with self.assertRaises(inventory.Invalid):
                inventory.apply(op, ACTOR, "Refuse staged mixed fixture")
        self.assertEqual(self.magic_files(), before)

    def test_every_original_receipt_is_checked_even_for_empty_changed_lists(self):
        _, op = self.operation()
        for key, value in (("expected_inventory_revision", "stale"), ("expected_decks_revision", "stale"),
                           ("expected_status_sha256", "a" * 64), ("tokens_sha256", "b" * 64)):
            params = {**op.params, "items": [], "products": [], key: value}
            with self.subTest(key=key), self.assertRaises(ops_token_plan.PlanChanged):
                inventory.apply(inventory.Op(op.kind, params), ACTOR, "Refuse stale no-op fixture")

    def test_added_deck_and_changed_unwritten_participant_invalidate_old_plan(self):
        _, op = self.operation()
        self.write("decks/casual/new.md", reservation.built("New"))
        with self.assertRaises(ops_token_plan.PlanChanged):
            inventory.apply(op, ACTOR, "Refuse new participant race")
        _, op = self.operation()
        path = self.magic / "decks/casual/queen.md"
        path.write_text(path.read_text() + "\nNew unrelated notes.\n", encoding="utf-8")
        with self.assertRaises(ops_token_plan.PlanChanged):
            inventory.apply(op, ACTOR, "Refuse changed participant race")

    def test_member_operation_rejects_products_without_reading_home_status(self):
        _, op = self.operation()
        params = {**op.params, "space": "user2", "items": [], "expected_status_sha256": None,
                  "tokens_sha256": None}
        with mock.patch.object(kit, "status_sha256", side_effect=AssertionError("home status read")), \
                mock.patch.object(ops_products, "product_row", side_effect=AssertionError("home product read")):
            with self.assertRaises(inventory.Invalid):
                inventory.apply(inventory.Op(op.kind, params), ACTOR, "Refuse nonhome products")

    def test_multiple_products_merge_status_labels_and_do_not_mutate_input(self):
        _, op = self.operation()
        before = inventory.current()
        untouched = files.render(before)
        after, summary = op.run(before)
        self.assertEqual(summary.counts, {"decks": 1, "products": 2})
        self.assertEqual(summary.extra, {"decks": ["casual/a"], "products": list(STEMS)})
        self.assertEqual(summary.changed["magic/products/status.csv"], [f"token cards of {stem}" for stem in STEMS])
        self.assertEqual(files.render(before), untouched)
        self.assertNotEqual(files.render(after), untouched)
