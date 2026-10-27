"""Owned-product storage changes over fixtures and disposable PostgreSQL only."""
import contextlib
import json
from unittest import mock

from decklab.lib import access, accessories, config, decks, inventory, pool
from decklab.lib.api import products as api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, orders, refresh, rules
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_inventory_orders import CLAUDE, component, record_json
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401
from decklab.tests.test_server import ServerTestCase, WRITE

STEM = "owned-test"
TABLE = "| Llanowar Elves | 4 | 4 | 2 | | | Keep the table note |\n"
ACCESSORIES = (",".join(accessories.FIELDS) + "\n"
               "private-sleeves,sleeves,user1,Private,Secret,pink,100,,,,,,\n"
               "shared-sleeves,sleeves,shared,DS,Matte,black,100,,,,,,\n"
               "shared-box,deck_box,shared,UG,Boulder,black,1,100,,,,,\n")


class _ProductFixture:
    def setUp(self):
        super().setUp()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(config, "CONFIG_FILE", self.magic.parent / "config.json"))
        config.CONFIG_FILE.write_text(json.dumps(ROLES), encoding="utf-8")
        self.stack.enter_context(access.using({"profile": "matt", "email": "", "remote": True}))
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.product(f"{STEM}.csv", ("deck", "Llanowar Elves", 2), ("deck", "Forest", 20), column="section")
        self.set_status("yes")
        self.deck("a", "A", "idea", "Deck\n4 Llanowar Elves\n20 Forest\n", table=TABLE)
        self.write("accessories.csv", ACCESSORIES)
        (self.magic / "orders/records").mkdir(parents=True, exist_ok=True)
        self.write(f"orders/records/{STEM}.json", record_json(STEM, "Recorded shop", "2026-10-01", [
            component(STEM, "product", f"magic/products/{STEM}.csv", "received", "2026-10-02",
                      checks=["Inspect the physical tokens"])]))
        api._previews.clear()
        self.addCleanup(api._previews.clear)

    def set_status(self, intact, *, status="owned", sleeves="shared-sleeves", box="shared-box"):
        self.write("products/status.csv", ",".join(rules.STATUS_FIELDS) + "\n"
                   + f"{STEM}.csv,{status},{intact},{sleeves},{box},Keep product notes,\n")

    def state(self):
        return api.product_state(STEM)

    def request(self, **changes):
        return {"profile": "matt", "stem": STEM, "intact": "no", "fingerprint": self.state()["fingerprint"],
                **changes}

    def preview(self, **changes):
        return api.preview_storage(json.dumps(self.request(**changes)))

    def save(self, token, **changes):
        return api.apply_storage(json.dumps({"profile": "matt", "preview": token, **changes}))

    def row(self, snapshot=None):
        return next(row for row in (snapshot or inventory.current()).status.rows if row.text("file") == f"{STEM}.csv")

    def assert_refused(self, code, function, *args):
        before = files.render(inventory.current())
        with self.assertRaises(ApiError) as caught:
            function(*args)
        self.assertEqual(caught.exception.status, code, caught.exception.message)
        self.assertEqual(files.render(inventory.current()), before)
        return caught.exception


class ProductStorageTests(_ProductFixture, PreparationCase):
    def test_state_needs_no_card_index_and_normalizes_unknown_intact_honestly(self):
        with mock.patch.object(api, "_require_cards", side_effect=AssertionError("metadata only")):
            state = self.state()
        self.assertEqual((state["status"], state["intact"], state["has_decks"], state["can_change"]),
                         ("owned", "yes", True, True))
        self.assertEqual(state["kit"], {"sleeves": "shared-sleeves", "deck_box": "shared-box"})
        for value in ("", "unknown"):
            self.set_status(value)
            self.assertIsNone(self.state()["intact"])

    def test_state_is_read_only_for_member_and_refused_before_home_data_for_other_member(self):
        with access.using({"profile": "user1", "email": "", "remote": True}):
            state = self.state()
        self.assertFalse(state["can_change"])
        self.assertTrue(state["why_not"])
        with access.using({"profile": "user2", "email": "", "remote": True}), \
                mock.patch.object(inventory, "current", side_effect=AssertionError("inventory hidden")):
            with self.assertRaises(ApiError) as caught:
                self.state()
            self.assertEqual(caught.exception.status, 403)

    def test_break_preview_matches_shared_operation_without_writing_then_saves_once(self):
        before = inventory.current()
        with inventory.pinned(before):
            expected, summary = inventory.preview(inventory.Op("product.set_intact", {"stem": STEM, "intact": "no"}))
        answer = self.preview()
        self.assertTrue(answer["ready"])
        self.assertTrue(answer["kit_cleared"])
        self.assertEqual((answer["before"], answer["after"]), ({"intact": "yes"}, {"intact": "no"}))
        self.assertEqual(answer["changes"], inventory.changed_labels(before, expected))
        self.assertEqual(answer["tables"], summary.extra["tables"])
        self.assertEqual(files.render(inventory.current()), files.render(before))
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            result = self.save(answer["preview"])
        self.assertEqual(apply.call_count, 1)
        operation, actor, _ = apply.call_args.args
        self.assertEqual((operation.kind, dict(operation.params), actor.id, actor.via),
                         ("product.set_intact", {"stem": STEM, "intact": "no"}, "matt", "tunnel"))
        self.assertEqual(apply.call_args.kwargs["expected_revision"], before.revision)
        self.assertTrue(result["saved"])
        after = inventory.current()
        self.assertEqual(files.render(after), files.render(expected))
        self.assertEqual([self.row(after).text(field) for field in ("intact", "sleeves", "deck_box", "notes")],
                         ["no", "", "", "Keep product notes"])
        self.assertEqual((after.collection(), after.tokens, after.orders, after.products, after.watchlist),
                         (before.collection(), before.tokens, before.orders, before.products, before.watchlist))
        parsed = decks.parse_deck(after.deck("casual/a").data, "a", "casual")
        self.assertIn("Keep the table note", parsed.text)
        self.assertFalse(any(holder.id.startswith("product/") for holder in pool.load_pool().in_use))

    def test_keep_intact_reserves_cards_without_adding_to_collection_or_restoring_old_kit(self):
        self.save(self.preview()["preview"])
        before = inventory.current()
        answer = self.preview(intact="yes")
        self.assertFalse(answer["kit_cleared"])
        self.save(answer["preview"])
        after = inventory.current()
        self.assertEqual(after.collection(), before.collection())
        self.assertEqual([self.row(after).text(field) for field in ("intact", "sleeves", "deck_box")], ["yes", "", ""])
        held = next(holder for holder in pool.load_pool().in_use if holder.id.startswith("product/"))
        self.assertEqual(held.cards["Llanowar Elves"], 2)

    def test_no_op_has_no_token_card_check_or_audit(self):
        before = inventory.current()
        with mock.patch.object(api, "_require_cards", side_effect=AssertionError("no card change")), \
                mock.patch.object(inventory, "preview", side_effect=AssertionError("no mutation preview")):
            answer = self.preview(intact="yes")
        self.assertFalse(answer["ready"])
        self.assertTrue(answer["unchanged"])
        self.assertNotIn("preview", answer)
        self.assertEqual((answer["changes"], answer["kit_cleared"], api._previews), ([], False, {}))
        self.assertEqual(inventory.current(), before)

    def test_private_old_kit_is_masked_and_admin_cannot_clear_it(self):
        self.set_status("yes", sleeves="private-sleeves")
        state = self.state()
        self.assertIsNone(state["kit"])
        self.assertFalse(state["can_change"])
        text = json.dumps(state)
        for secret in ("private-sleeves", "Private", "Secret", "pink"):
            self.assertNotIn(secret, text)
        with mock.patch.object(api, "_require_cards", side_effect=AssertionError("owner permission first")):
            self.assert_refused(403, self.preview)

    def test_private_inactive_kit_cannot_be_reactivated_or_cleared_but_no_op_stays_harmless(self):
        owners = frozenset({"matt", "shared"})
        for previous, target in (("no", "yes"), ("", "yes"), ("unknown", "yes"), ("", "no")):
            with self.subTest(previous=previous, target=target):
                self.set_status(previous, sleeves="private-sleeves")
                state = self.state()
                self.assertIsNone(state["kit"])
                self.assertFalse(state["can_change"])
                for secret in ("private-sleeves", "Private", "Secret", "pink"):
                    self.assertNotIn(secret, json.dumps(state))
                with mock.patch.object(api, "_require_cards", side_effect=AssertionError("permission first")):
                    self.assert_refused(403, lambda: self.preview(intact=target))
                snapshot = inventory.current()
                with self.assertRaises(ApiError) as caught:
                    api._StorageChange(snapshot, STEM, target, owners).run(snapshot)
                self.assertEqual(caught.exception.status, 403)
        self.set_status("no", sleeves="private-sleeves")
        with mock.patch.object(api, "_require_cards", side_effect=AssertionError("no-op")):
            self.assertTrue(self.preview(intact="no")["unchanged"])

    def test_keep_intact_refuses_visible_unusable_legacy_kit(self):
        self.write("accessories.csv", ACCESSORIES + "mine,sleeves,matt,DS,Matte,blue,100,,,,,,\n")
        for sleeves, box in (("mine", ""), ("shared-box", ""), ("", "shared-sleeves")):
            with self.subTest(sleeves=sleeves, box=box):
                self.set_status("no", sleeves=sleeves, box=box)
                self.assertFalse(self.state()["can_change"])
                with mock.patch.object(api, "_require_cards", side_effect=AssertionError("kit first")):
                    self.assert_refused(400, lambda: self.preview(intact="yes"))
                snapshot = inventory.current()
                with self.assertRaises(ApiError) as caught:
                    api._StorageChange(snapshot, STEM, "yes", frozenset({"matt", "shared"})).run(snapshot)
                self.assertEqual(caught.exception.status, 400)

    def test_keep_intact_preserves_valid_shared_kit_and_unchecked_legacy_free_text(self):
        for sleeves, box in (("shared-sleeves", "shared-box"), ("old blue", "old box")):
            with self.subTest(sleeves=sleeves, box=box):
                self.set_status("no", sleeves=sleeves, box=box)
                self.assertTrue(self.state()["can_change"])
                self.save(self.preview(intact="yes")["preview"])
                self.assertEqual((self.row().text("intact"), self.row().text("sleeves"), self.row().text("deck_box")),
                                 ("yes", sleeves, box))

    def test_legacy_shared_free_text_can_be_freed(self):
        self.set_status("yes", sleeves="old blue", box="old box")
        self.assertEqual(self.state()["kit"], {"sleeves": "old blue", "deck_box": "old box"})
        self.save(self.preview()["preview"])
        self.assertEqual((self.row().text("sleeves"), self.row().text("deck_box")), ("", ""))

    def test_pending_products_and_keeping_a_reference_only_list_are_refused(self):
        self.set_status("no", status="ordered", sleeves="", box="")
        self.assertFalse(self.state()["can_change"])
        self.assert_refused(400, self.preview)
        self.set_status("no", sleeves="", box="")
        self.cards_csv(f"products/{STEM}.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        self.assertFalse(self.state()["has_decks"])
        self.assertFalse(self.state()["can_change"])
        data = self.request(intact="yes")
        self.assert_refused(400, api.preview_storage, json.dumps(data))

    def test_invalid_stems_states_fingerprints_and_extra_apply_fields_are_refused(self):
        for stem in (None, "../owned-test", "status", "Owned", 3):
            with self.subTest(stem=stem):
                self.assert_refused(400, api.product_state, stem)
        self.assert_refused(404, api.product_state, "missing-product")
        for changes in ({"intact": True}, {"intact": ""}, {"fingerprint": "bad"}, {"extra": "ignored?"}):
            with self.subTest(changes=changes):
                self.assert_refused(400, api.preview_storage, json.dumps(self.request(**changes)))
        token = self.preview()["preview"]
        self.assert_refused(400, api.apply_storage, json.dumps({"profile": "matt", "preview": token, "intact": "yes"}))
        for token in (None, 3, "bad", "z" * 32):
            with self.subTest(token=token):
                self.assert_refused(400, self.save, token)

    def test_write_permissions_precede_payload_inventory_and_card_checks(self):
        for who in ("user1", "user2"):
            with self.subTest(who=who), access.using({"profile": who, "email": "", "remote": True}), \
                    mock.patch.object(api, "_require_cards", side_effect=AssertionError("permission first")), \
                    mock.patch.object(inventory, "current", side_effect=AssertionError("permission first")):
                with self.assertRaises(ApiError) as caught:
                    api.preview_storage(json.dumps({"profile": who}))
                self.assertEqual(caught.exception.status, 403)
                with self.assertRaises(ApiError) as caught:
                    api.apply_storage(json.dumps({"profile": who, "preview": "bad"}))
                self.assertEqual(caught.exception.status, 403)

    def test_preview_is_bound_to_person_listener_expiry_and_consumed_once(self):
        token = self.preview()["preview"]
        roles = json.loads(json.dumps(ROLES))
        roles["profiles"][1]["role"] = "admin"
        config.CONFIG_FILE.write_text(json.dumps(roles), encoding="utf-8")
        with access.using({"profile": "user1", "email": "", "remote": True}):
            self.assert_refused(409, api.apply_storage, json.dumps({"profile": "user1", "preview": token}))
        with access.using(None):
            self.assert_refused(409, self.save, token)
        created = api._previews[token]["created"]
        with mock.patch.object(api.time, "monotonic", return_value=created + api.PREVIEW_LIFETIME + 1):
            self.assert_refused(409, self.save, token)
        self.save(token)
        self.assert_refused(409, self.save, token)

    def test_concurrent_duplicate_apply_is_refused(self):
        token = self.preview()["preview"]
        apply = self.inventory.apply

        def duplicate(*args, **kwargs):
            self.assert_refused(409, self.save, token)
            return apply(*args, **kwargs)

        with mock.patch.object(self.inventory, "apply", side_effect=duplicate):
            self.save(token)
        self.assertEqual(self.row().text("intact"), "no")

    def test_both_revision_counters_are_required_before_preview_and_under_apply_lock(self):
        request = self.request()
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 5))
        self.assert_refused(409, api.preview_storage, json.dumps(request))
        token = self.preview()["preview"]
        self.write("accessories.csv", ACCESSORIES.replace("black,100", "black,99"))
        self.assert_refused(409, self.save, token)
        snapshot = inventory.current()
        operation = api._StorageChange(snapshot, STEM, "no", frozenset({"matt", "shared"}))
        for changed in (snapshot.replace(revision=snapshot.revision + "new"),
                        snapshot.replace(decks_revision=snapshot.decks_revision + "new")):
            with self.subTest(revision=changed.revision), self.assertRaises(inventory.Conflict):
                operation.run(changed)

    def test_deck_race_after_validation_saves_no_status_or_kit(self):
        token = self.preview()["preview"]
        apply = self.inventory.apply

        def race(*args, **kwargs):
            deck = self.magic / "decks/casual/a.md"
            deck.write_text(deck.read_text(encoding="utf-8") + "\nConcurrent note.\n", encoding="utf-8", newline="\n")
            return apply(*args, **kwargs)

        before = self.row()
        with mock.patch.object(self.inventory, "apply", side_effect=race), self.assertRaises(ApiError) as caught:
            self.save(token)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.row(), before)

    def test_new_incomplete_pool_is_refused_but_existing_table_failure_is_reported(self):
        self.set_status("no", sleeves="", box="")
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n", table=TABLE)
        self.product(f"{STEM}.csv", ("deck", "Unknown Fixture Card", 2), column="section")
        request = self.request(intact="yes")
        self.assert_refused(400, api.preview_storage, json.dumps(request))
        self.product(f"{STEM}.csv", ("deck", "Llanowar Elves", 2), column="section")
        self.set_status("yes")
        self.deck("a", "A", "idea", "Deck\n1 Unknown Fixture Card\n", table=TABLE)
        answer = self.preview()
        self.assertTrue(answer["ready"])
        self.assertIsNotNone(answer["tables"]["error"])
        saved = self.save(answer["preview"])
        self.assertTrue(saved["saved"])
        self.assertIsNotNone(saved["tables"]["error"])

    def test_unexpected_apply_table_failure_reports_saved_storage_state(self):
        token = self.preview()["preview"]
        before = inventory.current().deck("casual/a")
        with mock.patch.object(refresh, "plan_texts", side_effect=ValueError("Fixture table failure")):
            answer = self.save(token)
        self.assertTrue(answer["saved"])
        self.assertIn("Fixture table failure", answer["tables"]["error"])
        self.assertEqual(self.row().text("intact"), "no")
        self.assertEqual(inventory.current().deck("casual/a"), before)


class PgProductStorageTests(_ProductFixture, db_support.DbTestCase, PreparationCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(contract.adapt(self.inventory.load()), CLAUDE, "Import product storage fixtures",
                       dbname=self.dbname, decks=True)
        self.inventory = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.inventory))

    def test_status_kit_and_tables_save_in_one_audit_with_receipt_checks_untouched(self):
        before = inventory.current()
        with self.connect() as conn:
            count = conn.execute("select count(*) from audit.change_set").fetchone()[0]
        answer = self.preview()
        self.save(answer["preview"])
        after = inventory.current()
        self.assertEqual(after.collection(), before.collection())
        self.assertEqual(after.orders, before.orders)
        self.assertEqual([self.row(after).text(field) for field in ("intact", "sleeves", "deck_box")], ["no", "", ""])
        self.assertNotEqual(after.revision, before.revision)
        self.assertNotEqual(after.decks_revision, before.decks_revision)
        self.assertEqual(after.deck("casual/a").revision, before.deck("casual/a").revision + 1)
        with self.connect() as conn:
            self.assertEqual(conn.execute("select count(*) from audit.change_set").fetchone()[0], count + 1)
            self.assertEqual(conn.execute("select actor, message from audit.change_set order by id desc limit 1").fetchone(),
                             ("matt", f"Break up product {STEM}"))

    def test_concurrent_deck_revision_under_transaction_refuses_product_change(self):
        token = self.preview()["preview"]
        before = inventory.current()
        apply = self.inventory.apply

        def race(op, actor, message, **kwargs):
            held = before.deck("casual/a")
            apply(inventory.Op("deck.save", {"deck_id": held.id, "base_sha256": held.sha256,
                                             "text": held.text + "\nConcurrent fixture note.\n"}),
                  CLAUDE, "Concurrent fixture edit")
            return apply(op, actor, message, **kwargs)

        with mock.patch.object(self.inventory, "apply", side_effect=race), self.assertRaises(ApiError) as caught:
            self.save(token)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.row(), self.row(before))
        self.assertEqual(inventory.current().revision, before.revision)
        with self.connect() as conn:
            self.assertEqual(conn.execute("select message from audit.change_set order by id desc limit 1").fetchone(),
                             ("Concurrent fixture edit",))


class ProductStorageHttpTests(ServerTestCase):
    def test_get_head_and_both_post_routes_dispatch_through_existing_guards(self):
        with mock.patch.object(api, "product_state", return_value={"read": True}) as read:
            self.assertEqual(self.get_json(f"/api/product?stem={STEM}"), {"read": True})
            read.assert_called_once_with(stem=STEM)
            code, _, body = self.request("HEAD", f"/api/product?stem={STEM}")
            self.assertEqual((code, body), (200, b""))
        body = b'{"profile":"matt","fixture":true}'
        for suffix, name in (("preview", "preview_storage"), ("apply", "apply_storage")):
            with self.subTest(suffix=suffix), mock.patch.object(api, name, return_value={"write": True}) as write:
                self.assertEqual(self.get_json(f"/api/product/intact/{suffix}", method="POST", body=body,
                                              headers=dict(WRITE, Origin=f"http://127.0.0.1:{self.port}")), {"write": True})
                write.assert_called_once_with(body)

    def test_routes_reject_unknown_queries_wrong_methods_and_foreign_origins(self):
        self.assertError(f"/api/product?stem={STEM}&extra=yes", 400)
        self.assertError(f"/api/product?stem={STEM}&stem={STEM}", 400)
        self.assertError("/api/product", 405, method="POST", body=b"{}", headers=WRITE)
        for suffix in ("preview", "apply"):
            self.assertError(f"/api/product/intact/{suffix}", 405)
            self.assertError(f"/api/product/intact/{suffix}", 403, method="POST", body=b"{}",
                             headers=dict(WRITE, Origin="http://untrusted.example"))
