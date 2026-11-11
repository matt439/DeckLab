"""Explicit home-admin reviews save only dated observations/market targets, atomically."""
import json
from unittest import mock

from decklab.lib import inventory, pricing_setting, shop_references, shop_reference_source, shops
from decklab.lib.api import shopping_queue, shopping_references, shop_reference_annotations, shop_prices
from decklab.lib.inventory import Op, files, orders, rules
from decklab.lib.inventory.model import QUEUE_FIELDS
from decklab.lib.state import Actor, Invalid
from decklab.tests import test_collection_edit as fixture
from decklab.tests.test_api import _write
from decklab.tests.test_shop_quality_matching import PREFERENCE, sample

ACTOR = Actor("matt", "Matt", source="test")


class _ReferenceFixture(fixture.CollectionEditTestCase):
    def setUp(self):
        super().setUp()
        self.requests = []
        self.snapshot = sample()
        self.snapshot["cards"]["Llanowar Elves"]["at"] = "2026-11-11T12:00:00Z"
        values = {**dict.fromkeys(QUEUE_FIELDS, ""), "name": "Llanowar Elves", "quantity": "3", "for": "Fixture deck",
                  "printing": "exact", "set": "fdn", "collector_number": "227", "finish": "nonfoil", "state": "ready",
                  "listed_aud": "0.50", "listed_at": "Fixture shop", "in_stock": "no", "checked": "2026-11-01"}
        _write(self.box.magic / "watchlist.csv", rules.csv_bytes([values], QUEUE_FIELDS).decode())
        self.box.state.pricing_setting_put({"listing_preferences": PREFERENCE}, 0, ACTOR, "Synthetic listing preference")
        pricing_setting.forget()
        self.addCleanup(pricing_setting.forget)
        fixture.ce._require_cards()       # the current Shopping page already prepared this fixture index
        self.enterContext(mock.patch.object(shops, "load", side_effect=lambda adapter=None, **kwargs: self.snapshot if adapter.key == "mtgmate" else None))
        self.enterContext(mock.patch.object(shops, "_fetch", side_effect=AssertionError("No shop request")))
        shopping_references._previews.clear()
        self.addCleanup(shopping_references._previews.clear)

    def current(self):
        return self.backend.load()

    def request(self, number=1):
        row = {key: self.current().watchlist.rows[number - 1].text(key) for key in QUEUE_FIELDS}
        quote = shop_references.observation(row, self.snapshot, shops.ADAPTER, preference=PREFERENCE,
                                            confirm_printing=shop_reference_source.confirm_printing)
        return {"row": number, "shop": "mtgmate", "receipt": quote["receipt"]}

    def preview(self, requests=None, *, kind="reference", **extra):
        return self.call(shopping_queue.save_queue_state, "matt", action=kind + "_preview", expect=self.current().revision,
                         requests=requests if requests is not None else [self.request()], **extra)

    def apply(self, shown, *, kind="reference", profile="matt"):
        return self.call(shopping_queue.save_queue_state, profile, action=kind + "_apply", preview=shown["preview"])


class ShopReferenceApiTests(_ReferenceFixture):
    def test_unchanged_review_has_no_save_token_and_expired_or_wrong_kind_tokens_refuse_without_writes(self):
        shown = self.preview()
        self.assertApiError(409, self.apply, shown, kind="target")
        with mock.patch.object(shopping_references.time, "monotonic", return_value=shopping_references._previews[shown["preview"]]["at"] + 1801):
            self.assertApiError(409, self.apply, shown)
        self.assertEqual(len(self.writes), 0)
        self.apply(self.preview())
        same = self.preview()
        self.assertEqual((same["changed"], same["preview"]), (0, None))
        self.assertEqual(len(self.writes), 1)

    def test_malformed_or_duplicate_batch_selection_cannot_partly_save(self):
        for requests in ([{**self.request(), "shop": {}}], [self.request(), self.request()], [self.request()] * 101):
            with self.subTest(requests=len(requests)):
                self.assertApiError(400 if len(requests) != 2 else 409, self.preview, requests)
        self.assertEqual(len(self.writes), 0)

    def test_preview_is_read_only_and_confirmation_saves_four_fields_once_without_touching_cards_or_intent(self):
        before = self.current()
        shown = self.preview()
        self.assertEqual(files.render(self.current(), decks=True), files.render(before, decks=True))
        self.assertEqual(len(self.writes), 0)
        self.assertEqual(shown["changes"][0]["old"], {"listed_aud": "0.50", "listed_at": "Fixture shop", "in_stock": "no", "checked": "2026-11-01"})
        self.assertEqual(shown["changes"][0]["new"], {"listed_aud": "3.00", "listed_at": "MTGMate", "in_stock": "yes", "checked": "2026-11-11"})
        self.assertTrue(self.apply(shown)["saved"])
        self.assertEqual(len(self.writes), 1)
        after = self.current()
        changed = after.watchlist.rows[0]
        self.assertEqual((changed.quantity, changed.state, changed.for_deck), ("3", "ready", "Fixture deck"))
        self.assertEqual(after.collections, before.collections)
        self.assertEqual(after.decks, before.decks)
        self.assertApiError(409, self.apply, shown)
        self.assertEqual(len(self.writes), 1)

    def test_source_or_policy_changes_after_review_save_nothing_even_when_selected_price_stays_the_same(self):
        shown = self.preview()
        self.snapshot["cards"]["Llanowar Elves"]["listings"][0]["price"] = "0.75"
        self.assertApiError(409, self.apply, shown)
        self.assertEqual(self.current().watchlist.rows[0].listed_aud, "0.50")
        self.assertEqual(len(self.writes), 0)
        shown = self.preview()
        self.box.state.pricing_setting_put({"listing_preferences": {"minimum_condition": "NM", "english_only": True}},
                                           1, ACTOR, "Change synthetic policy")
        self.assertApiError(409, self.apply, shown)
        self.assertEqual(len(self.writes), 0)

    def test_queue_change_after_page_or_preview_prevents_overwriting_any_row(self):
        old = self.current()
        request = self.request()
        shown = self.preview([request])
        inventory.apply(Op("watchlist.set", {"select": "#1", "values": {"notes": "Changed fixture intent"}, "repo": str(self.box.root)}),
                        ACTOR, "Change synthetic queue")
        self.assertApiError(409, self.apply, shown)
        self.assertApiError(409, self.call, shopping_queue.save_queue_state, "matt", action="reference_preview", expect=old.revision, requests=[request])
        self.assertEqual(self.current().watchlist.rows[0].listed_aud, "0.50")
        self.assertEqual(len(self.writes), 1)

    def test_carried_unread_or_unconfirmed_printing_on_confirmation_never_changes_the_queue(self):
        for change in ({"carried": True}, {"status": "error"}):
            shown = self.preview()
            entry = self.snapshot["cards"]["Llanowar Elves"]
            old = dict(entry)
            entry.update(change)
            self.assertApiError(409, self.apply, shown)
            entry.clear(); entry.update(old)
        shown = self.preview()
        with mock.patch.object(shop_reference_source, "confirm_printing", return_value=None):
            self.assertApiError(409, self.apply, shown)
        self.assertEqual(len(self.writes), 0)

    def test_home_member_and_other_members_are_refused_before_source_or_token_lookup(self):
        shown = self.preview()
        for who in ("user1", "user2", "user3"):
            with self.subTest(who=who), self.as_(who), \
                    mock.patch.object(shop_reference_source, "context", side_effect=AssertionError("Private source read")):
                self.assertApiError(403, self.call, shopping_queue.save_queue_state, who, action="reference_preview", expect="bad", requests=[])
                self.assertApiError(403, self.apply, shown, profile=who)
                self.assertApiError(403, self.call, shopping_queue.save_queue_state, who, action="target_preview", expect="bad", requests=[])
        self.assertEqual(len(self.writes), 0)

    def test_target_can_be_reviewed_without_a_shop_quote_and_changes_no_reference_state_or_quantity(self):
        self.snapshot = None
        shown = self.preview([{"row": 1, "value": "2.50"}], kind="target")
        self.assertEqual(shown["changes"][0]["old"], {"buy_under_aud": ""})
        self.assertEqual(shown["changes"][0]["new"], {"buy_under_aud": "2.50"})
        self.apply(shown, kind="target")
        row = self.current().watchlist.rows[0]
        self.assertEqual((row.buy_under_aud, row.listed_aud, row.state, row.quantity), ("2.50", "0.50", "ready", "3"))
        self.assertEqual(len(self.writes), 1)
        cleared = self.preview([{"row": 1, "value": None}], kind="target")
        self.apply(cleared, kind="target")
        self.assertEqual(self.current().watchlist.rows[0].buy_under_aud, "")

    def test_target_policy_context_change_requires_a_new_review_and_invalid_amounts_write_nothing(self):
        shown = self.preview([{"row": 1, "value": "2.50"}], kind="target")
        self.snapshot["cards"]["Llanowar Elves"]["at"] = "2026-11-11T13:00:00Z"
        self.assertApiError(409, self.apply, shown, kind="target")
        for value in (True, "1.005", "NaN"):
            self.assertApiError(400, self.preview, [{"row": 1, "value": value}], kind="target")
        self.assertEqual(len(self.writes), 0)

    def test_bulk_review_is_one_change_and_a_late_failure_keeps_the_whole_queue_unchanged(self):
        first = self.current().watchlist.rows[0].as_dict()
        second = {**first, "for": "Another fixture deck"}
        _write(self.box.magic / "watchlist.csv", rules.csv_bytes([first, second], QUEUE_FIELDS).decode())
        shown = self.preview([self.request(1), self.request(2)])
        before = files.render(self.current(), decks=True)
        real, calls = orders.set_queue, []
        def fail_late(*args, **kwargs):
            calls.append(kwargs["select"])
            if len(calls) == 2:
                raise Invalid("Injected second reference failure")
            return real(*args, **kwargs)
        with mock.patch.object(orders, "set_queue", side_effect=fail_late):
            self.assertApiError(400, self.apply, shown)
        self.assertEqual(files.render(self.current(), decks=True), before)
        self.assertEqual(len(self.writes), 0)
        self.assertTrue(self.apply(shown)["saved"])
        self.assertEqual(len(self.writes), 1)
        self.assertEqual([row.listed_aud for row in self.current().watchlist.rows], ["3.00", "3.00"])

    def test_queue_annotations_use_one_history_read_and_home_members_get_no_write_receipts(self):
        from datetime import datetime, timezone
        first = self.current().watchlist.rows[0].as_dict()
        first["buy_under_aud"] = "3.00"
        _write(self.box.magic / "watchlist.csv", rules.csv_bytes([first, {**first, "for": "Another fixture deck"}], QUEUE_FIELDS).decode())
        past = {"Llanowar Elves": [{"on": "2026-11-10", "at": "2026-11-10T12:00:00Z",
                                    "listings": [{**self.snapshot["cards"]["Llanowar Elves"]["listings"][1], "price": "4.00"}]}]}
        def page():
            shown = {"to_buy": [{**row.as_dict(), "queue_row": number} for number, row in enumerate(self.current().watchlist.rows, 1)]}
            captured = shop_prices.Captured({"mtgmate": self.snapshot})
            shop_prices.enrich(shown, data=captured)
            return shop_reference_annotations.enrich(shown, captured)
        with mock.patch.object(shop_reference_annotations, "_now", return_value=datetime(2026, 11, 11, 14, tzinfo=timezone.utc)), \
                mock.patch.object(shops, "load_history", return_value=past) as history:
            with self.as_("matt"):
                shown = page()
            self.assertEqual(history.call_count, 1)
            snap = shown["to_buy"][0]["shop_snapshot"]
            self.assertEqual(snap["lowest_kept"]["readings"], 2)
            self.assertTrue(snap["target_comparison"]["at_or_below"])
            self.assertRegex(snap["reference_receipt"], r"^[0-9a-f]{64}$")
            with self.as_("user1"):
                member = page()
            self.assertNotIn("reference_receipt", member["to_buy"][0]["shop_snapshot"])
