"""Reviewed saved-test queue writes use only a disposable files inventory and saved fixture summaries."""
from collections import Counter
from copy import deepcopy
import csv
import io
import json
from types import SimpleNamespace
from unittest import mock

from decklab.lib import access, cards, config, feature_routes, inventory, pool, purchases
from decklab.lib.api import carddata, guard, variant_buying, variant_page, variant_queue
from decklab.lib.inventory import files
from decklab.lib.inventory.model import Deck
from decklab.tests import test_collection_edit as role_support
from decklab.tests import test_variant_api as support
from decklab.tests import test_variant_buying as buying_support


GROWTH = "Giant Growth"


class VariantQueueTests(support.VariantApiCase):
    def setUp(self):
        super().setUp()
        roles = deepcopy(role_support.ROLES)
        roles["profiles"].append({"id": "other-admin", "name": "Other admin", "role": "admin", "space": "home", "plays_as": "user"})
        support._write(config.CONFIG_FILE, json.dumps(roles))
        self.profile = roles["profiles"][0]
        self.patch(config, "REPO", self.box.root)
        self.enterContext(access.using({"profile": "matt", "email": "", "remote": True}))
        self.supply = pool.Pool(Counter(), {}, [])
        self.pool_read = self.patch(pool, "load_pool", return_value=self.supply)
        self.patch(carddata, "_cached_rate", return_value={"rate": 2.0, "date": "2026-10-27"})
        self.patch(cards, "price_date", return_value="2026-10-28")
        self.patch(cards, "cheapest_usd", return_value=(0.25, "war", "162", "nonfoil"))
        self.patch(variant_queue, "_reviews", {})
        self.now = 1000.0
        self.patch(variant_queue, "time", SimpleNamespace(monotonic=lambda: self.now))
        self.saved = self.summary()
        self.saved.update(looks=[{}], outcome="better", opponents=[], against={"id": support.RED_ID, "version": "target"})
        self.load = self.patch(support.real_forge.variants, "load_summary",
                               side_effect=lambda test_id: deepcopy(self.saved) if test_id == self.saved["test"] else None)
        self.job = self.patch(support.api.forge_runs.COORD_JOBS, "get", return_value=None)
        self.forbidden = [self.patch(owner, name, side_effect=AssertionError("No external or execution path"))
                          for owner, name in ((cards, "usd_to_aud"), (cards, "price_aud"), (cards, "_get_json"),
                                              (cards, "_download"), (support.real_forge.engine, "today"),
                                              (support.real_forge.variants, "run_test"))]
        self.write_queue([])

    def tearDown(self):
        for forbidden in self.forbidden:
            forbidden.assert_not_called()
        super().tearDown()

    def patch(self, owner, name, value=None, **options):
        patcher = mock.patch.object(owner, name, value) if value is not None else mock.patch.object(owner, name, **options)
        changed = patcher.start()
        self.addCleanup(patcher.stop)
        return changed

    def summary(self, *args, **kwargs):
        return buying_support.VariantBuyingTests.summary(self, *args, **kwargs)

    def write_queue(self, rows):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=purchases.QUEUE_FIELDS, lineterminator="\n")
        writer.writeheader()
        for values in rows:
            writer.writerow({**dict.fromkeys(purchases.QUEUE_FIELDS, ""), "name": GROWTH, "quantity": "1",
                             "printing": "any", "finish": "nonfoil", "state": "ready", **values})
        support._write(self.box.magic / "watchlist.csv", stream.getvalue())

    def preview(self, **changes):
        data = {"profile": "matt", "test": self.saved["test"], "name": GROWTH, **changes}
        return variant_queue.preview_queue(support.body(**data))

    def apply(self, preview, **changes):
        data = {"profile": "matt", "preview": preview["preview"], **changes}
        return variant_queue.apply_queue(support.body(**data))

    def assert_unchanged(self, before):
        after = self.box.inventory.load()
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(files.render(after), files.render(before))

    def test_preview_is_read_only_and_apply_adds_exactly_one_audited_default_request(self):
        before = self.box.inventory.load()
        real = self.box.inventory.apply
        with mock.patch.object(self.box.inventory, "apply", wraps=real) as applied:
            preview = self.preview()
            self.assertTrue(preview["ready"])
            self.assertEqual((preview["added"], preview["missing_added"]), (1, 1))
            self.assertEqual(preview["proposal"], {"name": GROWTH, "quantity": "1", "state": "ready", "for": "Green Test",
                                                   "source": "magic/decks/casual/green-test.md",
                                                   "notes": f"Saved test #/variant?test={self.saved['test']}",
                                                   "printing": "any", "set": "", "collector_number": "", "finish": "nonfoil"})
            applied.assert_not_called()
            self.assert_unchanged(before)
            result = self.apply(preview)
            applied.assert_called_once()
        call = applied.call_args
        self.assertEqual((call.args[0].kind, call.args[1].id, call.args[1].via), ("watchlist.set", "matt", "tunnel"))
        self.assertTrue(call.args[2].strip())
        self.assertEqual(call.kwargs["expected_revision"], before.revision)
        after = self.box.inventory.load()
        self.assertTrue(result["saved"])
        self.assertEqual((result["quantity"], result["revision"]), (1, after.revision))
        self.assertEqual(len(after.watchlist.rows), 1)
        row = after.watchlist.rows[0]
        self.assertEqual((row.name, row.quantity, row.printing, row.finish), (GROWTH, "1", "any", "nonfoil"))
        self.assertTrue(all(row.text(field) == "" for field in ("listed_aud", "listed_at", "in_stock", "checked")))
        for path, content in files.render(before).items():
            if path != "magic/watchlist.csv":
                self.assertEqual(files.render(after)[path], content)

    def test_both_post_routes_delegate_through_method_query_and_body_guards_without_http(self):
        body = b'{"profile":"matt","fixture":true}'
        for route, name in ((["variant", "queue", "preview"], "preview_queue"), (["variant", "queue"], "apply_queue")):
            with self.subTest(route=route):
                handler = SimpleNamespace(command="POST", _allow=mock.Mock(), _no_query=mock.Mock(),
                                          _write_body=mock.Mock(return_value=body), _send_json=mock.Mock())
                query = {}
                response = {"fixture": name}
                with mock.patch.object(variant_queue, name, return_value=response) as endpoint:
                    self.assertTrue(feature_routes.dispatch(handler, route, query))
                handler._allow.assert_called_once_with("POST")
                handler._no_query.assert_called_once_with(query)
                handler._write_body.assert_called_once_with(None)
                endpoint.assert_called_once_with(body)
                handler._send_json.assert_called_once_with(200, response)

    def test_review_queues_only_missing_added_copies_after_reserving_existing_demand(self):
        variant = support.test_forge.GREEN.replace("1 Fiery Annihilation\n", "").replace("2 Overrun\n", "")
        variant = variant.replace("2 Giant Growth", "5 Giant Growth")
        self.saved = self.summary(variant)
        self.saved.update(looks=[{}], outcome="better", opponents=[], against={"id": support.RED_ID})
        self.supply.owned[GROWTH] = 3
        preview = self.preview()
        self.assertEqual((preview["added"], preview["missing_added"], preview["proposal"]["quantity"]), (3, 2, "2"))
        self.apply(preview)
        self.assertEqual(self.box.inventory.load().watchlist.rows[0].quantity, "2")

    def test_explicit_exact_foil_choice_is_preserved_and_validated_again_at_apply(self):
        choice = {"printing": "exact", "set": "war", "collector_number": "162", "finish": "foil"}
        preview = self.preview(choice=choice)
        self.assertEqual({key: preview["proposal"][key] for key in choice}, choice)
        self.apply(preview)
        row = self.box.inventory.load().watchlist.rows[0]
        self.assertEqual((row.set, row.collector_number, row.finish, row.printing), ("war", "162", "foil", "exact"))

    def test_exact_printing_finish_is_rechecked_when_the_card_cache_changes_after_review(self):
        preview = self.preview(choice={"printing": "exact", "set": "war", "collector_number": "162", "finish": "foil"})
        before = self.box.inventory.load()
        printing = cards.printing

        def no_longer_foil(set_code, number):
            found = printing(set_code, number)
            return {**found, "finishes": ["nonfoil"]} if (set_code, number) == ("war", "162") else found

        with mock.patch.object(cards, "printing", side_effect=no_longer_foil):
            self.assertApiError(400, lambda: self.apply(preview))
        self.assert_unchanged(before)

    def test_invalid_choice_or_client_quantity_and_source_fields_never_write(self):
        before = self.box.inventory.load()
        bad_choices = [[], {"printing": "exact"}, {"printing": "any", "set": "war", "collector_number": "162"},
                       {"printing": "exact", "set": "war", "collector_number": "999999"},
                       {"printing": "exact", "set": "war", "collector_number": "162", "finish": "etched"},
                       {"quantity": 20}, {"finish": True}, {"finish": ""}]
        for choice in bad_choices:
            with self.subTest(choice=choice):
                self.assertApiError(400, lambda: self.preview(choice=choice))
        for name, value in (("quantity", 99), ("source", "magic/buylists/invented.md"), ("for", "Different deck")):
            with self.subTest(field=name):
                self.assertApiError(400, lambda: self.preview(**{name: value}))
        self.assert_unchanged(before)

    def test_every_existing_playable_queue_state_and_other_purpose_or_finish_blocks_new_intent(self):
        for state in purchases.STATES:
            with self.subTest(state=state):
                self.write_queue([{"name": "giant growth", "quantity": "3", "state": state, "for": "Another deck",
                                   "printing": "exact", "set": "war", "collector_number": "162", "finish": "foil"}])
                before = self.box.inventory.load()
                answer = self.preview()
                self.assertFalse(answer["ready"])
                self.assertNotIn("preview", answer)
                self.assertEqual((answer["existing"][0]["quantity"], answer["existing"][0]["state"], answer["existing"][0]["finish"]),
                                 (3, state, "foil"))
                self.assert_unchanged(before)

    def test_selected_overlong_existing_context_blocks_but_unrelated_omission_does_not(self):
        self.saved = self.summary(support.SWAPPED.replace("2 Overrun", "1 Overrun").replace("6 Forest", "1 Lightning Bolt\n6 Forest"))
        self.saved.update(looks=[{}], outcome="better", opponents=[], against={"id": support.RED_ID})
        self.write_queue([{"name": "Lightning Bolt", "for": "L" * (variant_buying.MAX_TEXT + 1)}])
        self.assertTrue(self.preview()["ready"])
        self.write_queue([{"for": "L" * (variant_buying.MAX_TEXT + 1)}])
        answer = self.preview()
        self.assertFalse(answer["ready"])
        self.assertEqual((answer["existing"], answer["omitted"]), ([], 1))

    def test_covered_incoming_or_unknown_additions_cannot_create_purchase_intent(self):
        before = self.box.inventory.load()
        for incoming in (False, True):
            with self.subTest(incoming=incoming):
                self.supply.owned[GROWTH] = 3
                self.supply.on_the_way = {GROWTH: [("Fixture delivery", 1)]} if incoming else {}
                self.assertApiError(409, self.preview, contains="No confirmed missing")
        self.supply.warnings = ["Fixture supply is incomplete"]
        self.assertApiError(409, self.preview)
        self.assert_unchanged(before)

    def test_unfinished_hidden_nonhome_or_missing_saved_tests_never_write(self):
        before = self.box.inventory.load()
        original = deepcopy(self.saved)
        self.saved.update(looks=[], outcome=None)
        self.assertApiError(409, self.preview)
        self.saved = deepcopy(original)
        self.assertApiError(404, lambda: self.preview(test="b" * 64))
        with mock.patch.object(variant_page, "_sees_test", return_value=False):
            self.assertApiError(404, self.preview)
        self.saved["base"]["id"] = "user2/casual/member-deck"
        with mock.patch.object(variant_page, "_sees_test", return_value=True):
            self.assertApiError(400, self.preview)
        self.assert_unchanged(before)

    def test_running_or_queued_saved_tests_are_refused_without_discovering_an_engine(self):
        self.job.return_value = SimpleNamespace(fn=None)
        for status in (support.jobs.RUNNING, support.jobs.QUEUED):
            with self.subTest(status=status), \
                    mock.patch.object(support.api.forge_runs.COORD_JOBS, "snapshot", return_value={"status": status}):
                self.assertApiError(409, self.preview)

    def test_a_test_started_again_after_review_is_refused_inside_the_fresh_operation(self):
        preview = self.preview()
        before = self.box.inventory.load()
        self.job.return_value = SimpleNamespace(fn=None)
        with mock.patch.object(support.api.forge_runs.COORD_JOBS, "snapshot", return_value={"status": support.jobs.RUNNING}):
            self.assertApiError(409, lambda: self.apply(preview))
        self.assert_unchanged(before)

    def test_permission_and_actor_spoofing_fail_before_inventory_or_saved_test_readers(self):
        for profile in ("user1", "user2"):
            with self.subTest(profile=profile), access.using({"profile": profile, "email": "", "remote": True}), \
                    mock.patch.object(inventory, "current", side_effect=AssertionError("No private read")) as current:
                self.assertApiError(403, lambda: self.preview(profile=profile))
                self.assertApiError(403, self.preview)
                self.assertApiError(403, lambda: variant_queue.apply_queue(support.body(profile=profile, preview="a" * 32)))
                current.assert_not_called()
        self.load.assert_not_called()

    def test_apply_reauthorizes_the_current_actor_after_admin_permission_is_removed(self):
        preview = self.preview()
        before = self.box.inventory.load()
        roles = deepcopy(role_support.ROLES)
        roles["profiles"][0]["role"] = "member"
        support._write(config.CONFIG_FILE, json.dumps(roles))
        with mock.patch.object(inventory, "current", side_effect=AssertionError("No private read after denial")) as current:
            self.assertApiError(403, lambda: self.apply(preview))
            current.assert_not_called()
        self.assert_unchanged(before)

    def test_returned_preview_mutations_cannot_change_the_stored_proposal(self):
        preview = self.preview()
        preview["proposal"].update(quantity="999", name="Lightning Bolt", source="", listed_aud="400")
        preview["deck"].update(title="Changed response", id=support.RED_ID)
        result = self.apply(preview)
        row = self.box.inventory.load().watchlist.rows[0]
        self.assertEqual((result["quantity"], row.name, row.quantity, row.source, row.listed_aud),
                         (1, GROWTH, "1", "magic/decks/casual/green-test.md", ""))

    def test_apply_rejects_extra_fields_bad_tokens_and_replayed_receipts(self):
        preview = self.preview()
        before = self.box.inventory.load()
        self.assertApiError(400, lambda: self.apply(preview, quantity=3))
        for token in (None, True, "", "x" * 32):
            with self.subTest(token=token):
                self.assertApiError(400, lambda: variant_queue.apply_queue(support.body(profile="matt", preview=token)))
        self.assert_unchanged(before)
        self.apply(preview)
        committed = self.box.inventory.load()
        self.assertApiError(409, lambda: self.apply(preview))
        self.assert_unchanged(committed)

    def test_receipt_binds_both_actor_and_listener(self):
        preview = self.preview()
        before = self.box.inventory.load()
        with access.using({"profile": "other-admin", "email": "", "remote": True}):
            self.assertApiError(409, lambda: self.apply(preview, profile="other-admin"))
        with access.using(None), access.viewing("matt"):
            self.assertApiError(409, lambda: self.apply(preview))
        self.assert_unchanged(before)
        self.apply(preview)

    def test_expired_and_busy_receipts_are_refused_without_writing(self):
        preview = self.preview()
        before = self.box.inventory.load()
        variant_queue._reviews[preview["preview"]]["busy"] = True
        self.assertApiError(409, lambda: self.apply(preview))
        variant_queue._reviews[preview["preview"]]["busy"] = False
        self.now += variant_queue.PREVIEW_TTL + 1
        self.assertApiError(409, lambda: self.apply(preview))
        self.assert_unchanged(before)

    def test_expiry_while_waiting_to_write_is_checked_inside_the_fresh_operation(self):
        preview = self.preview()
        before = self.box.inventory.load()
        real = self.box.inventory.apply

        def delayed(*args, **kwargs):
            self.now += variant_queue.PREVIEW_TTL + 1
            return real(*args, **kwargs)

        with mock.patch.object(self.box.inventory, "apply", side_effect=delayed):
            self.assertApiError(409, lambda: self.apply(preview))
        self.assert_unchanged(before)

    def test_receipt_cache_is_bounded_and_never_evicts_an_inflight_review(self):
        with mock.patch.object(variant_queue, "MAX_PREVIEWS", 1):
            first = self.preview()
            variant_queue._reviews[first["preview"]]["busy"] = True
            self.assertApiError(503, self.preview)
            variant_queue._reviews[first["preview"]]["busy"] = False
            self.now += 1
            second = self.preview()
            self.assertEqual(len(variant_queue._reviews), 1)
            self.assertApiError(409, lambda: self.apply(first))
            self.apply(second)

    def test_backend_failure_releases_busy_receipt_for_a_safe_retry(self):
        preview = self.preview()
        before = self.box.inventory.load()
        with mock.patch.object(inventory, "apply", side_effect=inventory.Unavailable("Fixture unavailable")):
            self.assertApiError(503, lambda: self.apply(preview))
        self.assertFalse(variant_queue._reviews[preview["preview"]]["busy"])
        self.assert_unchanged(before)
        self.apply(preview)

    def test_fresh_operation_checks_both_revisions_and_deck_sha_before_recomputing(self):
        preview = self.preview()
        record = deepcopy(variant_queue._reviews[preview["preview"]]["record"])
        operation = variant_queue._ReviewedQueue(record, self.profile)
        original = self.box.inventory.load()
        stored = original.deck(support.GREEN_ID)
        changed_deck = original.with_deck(Deck("home", "casual", "green-test", stored.text + "\nFixture deck changed.\n"))
        examples = [original.replace(revision="different inventory"), original.replace(decks_revision="different decks"), changed_deck]
        with mock.patch.object(variant_queue, "_proposal", side_effect=AssertionError("No stale recomputation")) as proposal:
            for snapshot in examples:
                with self.subTest(revision=snapshot.revision, decks=snapshot.decks_revision), self.assertRaises(inventory.Conflict):
                    operation.run(snapshot)
            proposal.assert_not_called()
        self.assert_unchanged(original)

    def test_raw_saved_recipe_change_is_rechecked_inside_the_inventory_operation(self):
        preview = self.preview()
        before = self.box.inventory.load()
        self.saved["base"]["title"] = "Changed captured title"
        with mock.patch.object(self.box.inventory, "apply", wraps=self.box.inventory.apply) as applied:
            self.assertApiError(409, lambda: self.apply(preview))
            applied.assert_called_once()
        self.assert_unchanged(before)

    def test_verdict_only_saved_summary_change_invalidates_the_review(self):
        preview = self.preview()
        before = self.box.inventory.load()
        self.saved["outcome"] = "worse"
        self.assertApiError(409, lambda: self.apply(preview))
        self.assert_unchanged(before)

    def test_missing_quantity_facts_are_recomputed_even_when_fixture_revisions_stay_the_same(self):
        preview = self.preview()
        before = self.box.inventory.load()
        self.supply.owned[GROWTH] = 3
        self.assertApiError(409, lambda: self.apply(preview), contains="No confirmed missing")
        self.assert_unchanged(before)

    def test_fresh_operation_ignores_an_outer_pinned_preview_after_a_deck_edit(self):
        preview = self.preview()
        before = self.box.inventory.load()
        path = self.box.magic / "decks" / f"{support.GREEN_ID}.md"
        support._write(path, path.read_text(encoding="utf-8") + "\nAn independent fixture edit.\n")
        latest = self.box.inventory.load()
        with inventory.pinned(before):
            self.assertApiError(409, lambda: self.apply(preview))
        self.assert_unchanged(latest)

    def test_queue_change_after_preview_is_refused_without_losing_the_new_existing_intent(self):
        preview = self.preview()
        self.write_queue([{"quantity": "4", "for": "Concurrent fixture request", "state": "deferred"}])
        latest = self.box.inventory.load()
        self.assertApiError(409, lambda: self.apply(preview))
        self.assert_unchanged(latest)

    def test_exact_choice_cannot_select_a_same_name_token_and_token_intent_does_not_block_a_playable_card(self):
        combined = self.box.data / "combined-cards.jsonl"
        combined.write_text((support.test_forge.FIXTURES / "default_cards.jsonl").read_text(encoding="utf-8") + "\n" +
                            (support.test_forge.HERE / "forge_cards.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        index = cards.build_index(combined, support.test_forge.TAGS_FILE, {"default_cards": "2026-10-28"}, log=lambda *args: None)
        cards.write_index(index, cards.INDEX_FILE)
        cards._index = None
        variant = support.test_forge.GREEN.replace("1 Fiery Annihilation\n", "").replace("2 Llanowar Elves (FDN) 227", "3 Llanowar Elves (FDN) 227")
        self.saved = self.summary(variant)
        self.saved.update(looks=[{}], outcome="better", opponents=[], against={"id": support.RED_ID})
        before = self.box.inventory.load()
        self.assertApiError(400, lambda: self.preview(name="Llanowar Elves", choice={"printing": "exact", "set": "ttsr",
                                                                                   "collector_number": "12", "finish": "nonfoil"}))
        self.assert_unchanged(before)
        self.write_queue([{"name": "Llanowar Elves", "printing": "exact", "set": "ttsr", "collector_number": "12", "finish": "nonfoil"}])
        preview = self.preview(name="Llanowar Elves")
        self.assertTrue(preview["ready"])
        self.apply(preview)
        rows = self.box.inventory.load().watchlist.rows
        self.assertEqual([(row.name, row.printing, row.set) for row in rows], [("Llanowar Elves", "exact", "ttsr"), ("Llanowar Elves", "any", "")])
