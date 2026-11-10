"""Pure source/printing/policy receipts and conservative same-scope retained lows."""
import copy
from datetime import datetime, timezone
import unittest
from unittest import mock

from decklab.lib import shop_references as refs, shops
from decklab.lib.shops import rows
from decklab.tests.test_shop_quality_matching import PREFERENCE, offer
from decklab.tests.test_shop_baskets import entry, mtgmate, row

AT = "2026-11-11T12:00:00+00:00"
NOW = datetime(2026, 11, 11, 14, tzinfo=timezone.utc)


def asked(**changes):
    return {**row("Llanowar Elves", 1), "finish": "nonfoil", "quantity": "3", "listed_aud": "0.50", "listed_at": "Fixture shop",
            "in_stock": "no", "checked": "2026-11-01", **changes}


def snapshot():
    return mtgmate({"Llanowar Elves": entry(offer("1.00", "Damaged", "ja", stock=9), offer("3.00", "NM", "en"), at=AT)})


def proof(name, code, number, finish):
    if rows.fold_set(code) == "fdn" and rows.fold_number(number) == "227" and finish == "nonfoil":
        return {"name": name, "set": "fdn", "collector_number": "227", "finish": finish}
    return None


def reading(on, *listings, **extra):
    return {"on": on, "at": on + "T12:00:00+00:00", "listings": list(listings), **extra}


class ShopReferenceRulesTests(unittest.TestCase):
    def quote(self, row=None, data=None, **changes):
        return refs.observation(row or asked(), data or snapshot(), shops.ADAPTER,
                                preference=changes.get("preference", PREFERENCE), confirm_printing=changes.get("confirm_printing", proof))

    def test_review_contains_only_dated_observation_fields_and_canonical_printing_without_any_io(self):
        data, request = snapshot(), asked()
        before = copy.deepcopy((data, request))
        with mock.patch.object(shops, "load", side_effect=AssertionError("No file read")), \
                mock.patch.object(shops, "listing_preference", side_effect=AssertionError("No implicit setting read")):
            quote = self.quote(request, data)
        self.assertEqual(quote["fields"], {"listed_aud": "3.00", "listed_at": "MTGMate", "in_stock": "yes", "checked": "2026-11-11"})
        self.assertEqual(quote["printing"], proof("Llanowar Elves", "fdn", "227", "nonfoil"))
        self.assertEqual((quote["source"]["condition"], quote["source"]["language"]), ("Near Mint", "English"))
        self.assertRegex(quote["receipt"], r"^[0-9a-f]{64}$")
        self.assertEqual((data, request), before)

    def test_receipt_binds_whole_source_scope_row_intent_and_frozen_preference(self):
        original = self.quote()["receipt"]
        changed = snapshot()
        changed["cards"]["Llanowar Elves"]["listings"][0]["price"] = "0.75"
        self.assertNotEqual(self.quote(data=changed)["receipt"], original)
        self.assertNotEqual(self.quote(asked(quantity="4"))["receipt"], original)
        self.assertNotEqual(self.quote(preference={"minimum_condition": "NM", "english_only": True})["receipt"], original)

    def test_carried_unread_malformed_or_unconfirmed_printing_never_produces_a_reference(self):
        for change in ({"carried": True}, {"status": "error"}, {"at": "2026-02-30T12:00:00Z"}, {"at": "2026-11-11"}):
            data = snapshot()
            data["cards"]["Llanowar Elves"].update(change)
            with self.subTest(change=change), self.assertRaises(refs.Unconfirmed):
                self.quote(data=data)
        with self.assertRaisesRegex(refs.Unconfirmed, "printing couldn't be confirmed"):
            self.quote(confirm_printing=lambda *args: None)
        with self.assertRaises(refs.Unconfirmed):
            self.quote(asked(is_token=True))
        with self.assertRaisesRegex(refs.Unconfirmed, "finish requested"):
            self.quote(asked(finish="foil"))

    def test_out_of_stock_observation_can_be_reviewed_and_external_or_unpriced_listing_cannot(self):
        data = snapshot()
        data["cards"]["Llanowar Elves"]["listings"][1]["stock"] = 0
        quote = self.quote(data=data)
        self.assertEqual((quote["fields"]["in_stock"], quote["fields"]["listed_aud"]), ("no", "3.00"))
        for change in ({"price": None}, {"url": "https://example.com/not-the-shop"}, {"stock": True}, {"price": "NaN"}):
            bad = snapshot()
            bad["cards"]["Llanowar Elves"]["listings"][1].update(change)
            with self.subTest(change=change), self.assertRaises(refs.Unconfirmed):
                self.quote(data=bad)

    def test_today_low_uses_the_same_finish_and_preference_and_needs_an_earlier_reading(self):
        data = snapshot()
        quote = self.quote(data=data)
        history = {"history": {"Llanowar Elves": [reading("2026-11-10", offer("4.00", "NM", "en")),
            reading("2026-11-09", offer("0.50", "DMG", "ja"))]}}
        low = refs.lowest_kept(asked(), quote, data, history, shops.ADAPTER, preference=PREFERENCE, now=NOW)
        self.assertEqual((low["days"], low["readings"]), (90, 2))
        history["history"]["Llanowar Elves"].append(reading("2026-11-08", offer("2.00", "LP", "en")))
        self.assertIsNone(refs.lowest_kept(asked(), quote, data, history, shops.ADAPTER, preference=PREFERENCE, now=NOW))
        self.assertIsNone(refs.lowest_kept(asked(), quote, data, {}, shops.ADAPTER, preference=PREFERENCE, now=NOW))

    def test_partial_malformed_stale_or_future_history_does_not_invent_a_low(self):
        data, quote = snapshot(), self.quote()
        for history in ({"history": {"Llanowar Elves": [reading("2026-11-10", offer("1.00", "NM", "en"), partial=True)]}},
                        {"history": {"Llanowar Elves": [{"on": "not a date", "listings": []}]}},
                        {"history": {"Llanowar Elves": [reading("2026-01-01", offer("5.00", "NM", "en"))]}}):
            with self.subTest(history=history):
                self.assertIsNone(refs.lowest_kept(asked(), quote, data, history, shops.ADAPTER, preference=PREFERENCE, now=NOW))
