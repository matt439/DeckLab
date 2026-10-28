"""Strict missing-card shop evidence from supplied data and disposable Shopping fixtures.

Run: python scripts/test_fixtures.py decklab.tests.test_shop_missing_prices
No real shop cache, shop request, configured database or collection is read.
"""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, cards, inventory, shops
from decklab.lib.api import common, shop_missing_prices as missing, shop_prices, shopping, shopping_missing
from decklab.tests import test_shopping_missing as fixtures

AT = "2026-10-20T12:34:56+00:00"
NOW = "2026-10-28T12:34:56+00:00"
RIDER = fixtures.RIDER


def listing(price="1.25", stock=2, finish="nonfoil", set_code="fdn", number="227", **extra):
    return {"price": price, "stock": stock, "finish": finish, "set": set_code, "number": number,
            "condition": "Regular", "url": f"{shops.SITE}/cards/Llanowar_Elves/{set_code.upper()}/{number}", **extra}


def record(*items, status="ok", at=AT, **extra):
    return {"status": status, "at": at, "listings": list(items), **extra}


def snapshot(entries=None, **extra):
    return {"version": 1, "shop": shops.SHOP, "site": shops.SITE, "fetched_at": NOW,
            "cards": entries if entries is not None else {"Llanowar Elves": record(listing())}, **extra}


def resolve(name):
    return RIDER if name.casefold() in ("murderous rider", RIDER.casefold()) else name


class MissingPriceProjectionTests(unittest.TestCase):
    def project(self, data=None, *, name="Llanowar Elves", resolver=resolve):
        rows = [{"name": name, "missing": 3, "queue": [{"printing": "exact", "finish": "foil"}]}]
        missing.enrich(rows, data, resolver)
        return rows[0]["shop_snapshot"]

    def test_cheapest_stocked_nonfoil_is_independent_of_generic_row_quantity_or_queue_intent(self):
        data = snapshot({"Llanowar Elves": record(listing("0.10", 0), listing("1.50", 3),
            listing("1.20", 1, set_code="cmm", number="648"), listing("0.05", 50, finish="foil"))})
        shown = self.project(data)
        self.assertEqual((shown["status"], shown["price_aud"], shown["stock"]), ("in_stock", "1.20", 1))
        self.assertEqual((shown["set"], shown["collector_number"], shown["finish"]), ("cmm", "648", "nonfoil"))
        self.assertEqual(shown["in_stock_printings"], 2)
        self.assertFalse(shown["back_in_stock"] or shown["newly_in_stock"])
        self.assertEqual(shown["scope"], "nonfoil")

    def test_stocked_foil_never_replaces_an_out_of_stock_nonfoil(self):
        shown = self.project(snapshot({"Llanowar Elves": record(listing("1.50", 0),
            listing("0.10", 99, finish="foil"), listing("2.00", 0, set_code="cmm"))}))
        self.assertEqual((shown["status"], shown["price_aud"], shown["stock"], shown["finish"]),
                         ("out_of_stock", "1.50", 0, "nonfoil"))
        self.assertEqual(shown["in_stock_printings"], 0)

    def test_foil_only_or_proven_empty_listings_mean_not_listed_in_the_nonfoil_scope(self):
        for entry in (record(listing(finish="foil")), record(status="not_listed"), record()):
            with self.subTest(entry=entry):
                shown = self.project(snapshot({"Llanowar Elves": entry}))
                self.assertEqual((shown["status"], shown["scope"], shown["fetched_at"]),
                                 ("not_listed", "nonfoil", AT))
                self.assertIsNone(shown["price_aud"])
                self.assertIsNone(shown["stock"])

    def test_absent_names_and_absent_capture_are_not_checked_without_a_global_date(self):
        for data in (None, snapshot({"Other": record(listing())}), snapshot({})):
            shown = self.project(data)
            self.assertEqual(shown["status"], "not_checked")
            self.assertIsNone(shown["fetched_at"])

    def test_bad_relevant_price_cannot_be_skipped_to_claim_another_listing_is_cheapest(self):
        for value in (None, 0, "0.00", -1, "-1.00", True, "NaN", float("inf"), "1.234", "1e100", " secret "):
            with self.subTest(value=value):
                shown = self.project(snapshot({"Llanowar Elves": record(listing(price=value),
                                                                              listing("10.00", 5))}))
                self.assertEqual(shown["status"], "unknown")
                self.assertIsNone(shown["price_aud"])
                json.dumps(shown, allow_nan=False)

    def test_stock_must_be_a_bounded_nonnegative_exact_integer(self):
        for stock in (None, True, False, -1, "2", 2.0, float("nan"), 10 ** 100):
            with self.subTest(stock=stock):
                shown = self.project(snapshot({"Llanowar Elves": record(listing(stock=stock))}))
                self.assertEqual(shown["status"], "unknown")
                self.assertIsNone(shown["stock"])

    def test_invalid_finish_printing_or_unsafe_link_is_unknown(self):
        invalid = [listing(finish="unknown"), listing(set_code="FDN"), listing(set_code="bad set"),
                   listing(number=""), listing(number="1\nsecret"), listing(number="../2"),
                   listing(url="https://example.com/cards/card"), listing(url="javascript:alert(1)"),
                   listing(url="https://www.mtgmate.com.au.evil/cards/a"),
                   listing(url="https://user@www.mtgmate.com.au/cards/a"),
                   listing(url="https://www.mtgmate.com.au:443/cards/a"),
                   listing(url="https://www.mtgmate.com.au/cards/../admin"),
                   listing(url="https://www.mtgmate.com.au/cards/%2e%2e/admin"),
                   listing(url="https://www.mtgmate.com.au/cards/a?redirect=bad"), None]
        for item in invalid:
            with self.subTest(item=item):
                shown = self.project(snapshot({"Llanowar Elves": record(item)}))
                self.assertEqual(shown["status"], "unknown")
                self.assertIsNone(shown["url"])

    def test_known_foil_scope_can_be_ignored_without_trusting_its_other_facts(self):
        shown = self.project(snapshot({"Llanowar Elves": record(
            {"finish": "foil", "price": "untrusted", "stock": "untrusted"}, listing())}))
        self.assertEqual((shown["status"], shown["price_aud"]), ("in_stock", "1.25"))

    def test_per_entry_date_is_preserved_for_carried_records_and_never_rejuvenated(self):
        shown = self.project(snapshot({"Llanowar Elves": record(listing(), carried=True)}))
        self.assertEqual(shown["fetched_at"], AT)
        self.assertTrue(shown["carried"])
        for at in (None, "", "2026-10-20", "2026-02-30T00:00:00+00:00", "2026-10-20T12:34:56",
                   "2026-10-20T12:34:56+01:99", "2026-10-20T12:34:56+24:00"):
            with self.subTest(at=at):
                shown = self.project(snapshot({"Llanowar Elves": record(listing(), at=at, carried=True)}))
                self.assertEqual(shown["status"], "unknown")
                self.assertIsNone(shown["fetched_at"])

    def test_unpaired_surrogates_and_invalid_utf8_urls_cannot_enter_the_projection(self):
        for data, name in ((snapshot({"Bad\ud800": record(listing())}), "Llanowar Elves"),
                           (snapshot(), "Bad\ud800"),
                           (snapshot({"Llanowar Elves": record(listing(number="1\ud800"))}), "Llanowar Elves"),
                           (snapshot({"Llanowar Elves": record(listing(url=shops.SITE + "/cards/Bad\ud800"))}), "Llanowar Elves"),
                           (snapshot({"Llanowar Elves": record(listing(url=shops.SITE + "/cards/%ED%A0%80"))}), "Llanowar Elves")):
            with self.subTest(name=repr(name)):
                shown = self.project(data, name=name)
                self.assertEqual(shown["status"], "unknown")
                json.dumps(shown, ensure_ascii=False, allow_nan=False).encode("utf-8")

    def test_historical_front_only_cache_uses_proven_full_canonical_identity(self):
        data = snapshot({"Murderous Rider": record(listing())})
        shown = self.project(data, name=RIDER)
        self.assertEqual(shown["status"], "in_stock")
        self.assertEqual(shown["fetched_at"], AT)
        self.assertEqual(self.project(data, name=RIDER, resolver=None)["status"], "unknown")

    def test_exact_canonical_key_does_not_require_loading_an_index(self):
        shown = self.project(snapshot({RIDER: record(listing())}), name=RIDER, resolver=None)
        self.assertEqual(shown["status"], "in_stock")

    def test_ambiguous_or_conflicting_alias_records_are_unknown_instead_of_false_absence(self):
        data = snapshot({"Murderous Rider": record(listing())})
        self.assertEqual(self.project(data, name=RIDER, resolver=lambda name: name)["status"], "unknown")
        data["cards"][RIDER] = record(listing("2.00"), at=NOW)
        self.assertEqual(self.project(data, name=RIDER)["status"], "unknown")
        self.assertEqual(self.project(snapshot({RIDER: record(listing())}), name=RIDER,
                                      resolver=lambda name: None)["status"], "unknown")

    def test_failed_or_unsupported_snapshot_evidence_has_only_fixed_errors(self):
        secret = "C:/private/household.json: private detail"
        invalid = [snapshot(shop="Other shop"), snapshot(site="https://example.com"), snapshot(version=True),
                   snapshot(version=2), {"version": 1, "cards": {}}, [], "bad",
                   snapshot({"Llanowar Elves": record(status="error", error=secret)}),
                   snapshot({"Llanowar Elves": record(listing(), status="not_listed")}),
                   snapshot({"Llanowar Elves": record(listing(), carried="yes")})]
        for data in invalid:
            with self.subTest(data=data):
                shown = self.project(data)
                self.assertEqual(shown["status"], "unknown")
                self.assertEqual(shown["error"], missing.UNKNOWN)
                self.assertNotIn(secret, json.dumps(shown))
                self.assertIsNone(shown["price_aud"])

    def test_caps_and_resolver_failures_never_publish_partial_evidence(self):
        with mock.patch.object(missing, "MAX_NAMES", 1):
            shown = self.project(snapshot({"Llanowar Elves": record(listing()), "Other": record()}))
            self.assertEqual(shown["status"], "unknown")
        with mock.patch.object(missing, "MAX_LISTINGS", 1):
            self.assertEqual(self.project(snapshot({"Llanowar Elves": record(listing(), listing())}))["status"], "unknown")
        with mock.patch.object(missing, "MAX_ROWS", 1):
            rows = [{"name": "Llanowar Elves"}, {"name": "Llanowar Elves"}]
            missing.enrich(rows, snapshot(), resolve)
            self.assertEqual([row["shop_snapshot"]["status"] for row in rows], ["in_stock", "unknown"])
        self.assertEqual(self.project(snapshot(), resolver=mock.Mock(side_effect=ValueError("private")))["status"], "unknown")

    def test_alias_resolution_is_cached_and_inputs_and_nested_queue_facts_are_preserved(self):
        data = snapshot()
        rows = [{"name": "Llanowar Elves", "missing": 7, "queue": [{"name": "Llanowar Elves", "quantity": "9"}]}]
        before_data, before_rows = copy.deepcopy(data), copy.deepcopy(rows)
        resolver = mock.Mock(side_effect=resolve)
        missing.enrich(rows, data, resolver)
        self.assertEqual(data, before_data)
        self.assertEqual({key: value for key, value in rows[0].items() if key != "shop_snapshot"}, before_rows[0])
        resolver.assert_called_once_with("Llanowar Elves")


class MissingPriceShoppingTests(fixtures._Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.saved = snapshot({"Llanowar Elves": record(listing("9.00", 3),
            listing("1.00", 1, set_code="cmm", number="648")), "Murderous Rider": record(listing())})
        for owner, name in ((shops, "_fetch"), (shops, "_write"), (inventory, "apply"), (cards, "update")):
            patcher = mock.patch.object(owner, name, side_effect=AssertionError("Optional prices must only read supplied evidence"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_one_capture_enriches_queue_before_copying_and_generic_needs_afterward(self):
        with mock.patch.object(shops, "load", return_value=self.saved) as load:
            answer = self.overview()
        load.assert_called_once()
        rows = self.expected_baseline(answer)
        elves = rows["Llanowar Elves"]
        self.assertEqual((elves["shop_snapshot"]["price_aud"], elves["shop_snapshot"]["stock"]), ("1.00", 1))
        exact = next(row for row in answer["to_buy"] if row["name"] == "Llanowar Elves" and row["printing"] == "exact"
                     and row["set"] == "fdn")
        self.assertEqual((exact["shop_snapshot"]["price_aud"], exact["shop_snapshot"]["stock"]), ("9.00", 3))
        self.assertNotIn("scope", exact["shop_snapshot"])
        self.assertEqual(rows[RIDER]["shop_snapshot"]["status"], "in_stock")
        for row in rows.values():
            expected = [queued for queued in answer["to_buy"] if cards.resolve(queued["name"]) == row["name"]
                        and not queued.get("is_token")]
            self.assertEqual(row["queue"], expected)

    def test_captured_absence_does_not_reload_through_any_default_matcher(self):
        with mock.patch.object(shops, "load", return_value=None) as load, \
                mock.patch.object(shop_prices, "for_row", side_effect=AssertionError("Implicit snapshot reload")):
            answer = self.overview()
        load.assert_called_once()
        self.expected_baseline(answer)
        self.assertNotIn("shop_snapshot", answer)
        self.assertTrue(all("shop_snapshot" not in row for row in answer["to_buy"]))
        self.assertTrue(all(row["shop_snapshot"]["status"] == "not_checked" for row in answer["missing_cards"]["rows"]))

    def test_optional_capture_failure_does_not_break_missing_counts_or_reveal_errors(self):
        detail = "C:/private/config.json: household detail"
        with mock.patch.object(shops, "load", side_effect=ValueError(detail)) as load:
            answer = self.overview()
        load.assert_called_once()
        self.expected_baseline(answer)
        self.assertNotIn(detail, json.dumps(answer))

    def test_malformed_optional_data_keeps_the_game_and_buying_facts_usable(self):
        with mock.patch.object(shops, "load", return_value={"version": 1, "cards": "bad"}):
            answer = self.overview()
        self.expected_baseline(answer)
        self.assertTrue(all(row["shop_snapshot"]["status"] == "unknown" for row in answer["missing_cards"]["rows"]))

    def test_captured_identity_maps_survive_global_index_invalidation_without_loading(self):
        self.assertEqual(cards.resolve("Murderous Rider"), RIDER)
        resolver = shop_prices._loaded_resolver()
        with mock.patch.object(cards, "_index", None), \
                mock.patch.object(cards, "_get", side_effect=AssertionError("Optional index load")), \
                mock.patch.object(cards, "_read_index", side_effect=AssertionError("Optional index file read")):
            rows = [{"name": RIDER}]
            missing.enrich(rows, self.saved, resolver)
        self.assertEqual(rows[0]["shop_snapshot"]["status"], "in_stock")

    def test_hidden_profiles_and_anonymous_requests_are_refused_before_any_data_reader(self):
        for identity in ({"profile": "user2", "email": "", "remote": True},
                         {"profile": "user3", "email": "", "remote": True},
                         {"profile": None, "email": "", "remote": False}):
            with self.subTest(identity=identity), access.using(identity), \
                    mock.patch.object(shops, "load", side_effect=AssertionError("Private shop reader")) as load, \
                    mock.patch.object(shopping_missing, "gather", side_effect=AssertionError("Private missing reader")) as gather, \
                    mock.patch.object(shopping.purchases, "overview", side_effect=AssertionError("Private purchases")) as records:
                with self.assertRaises(common.ApiError) as error:
                    shopping.shopping_overview()
                self.assertEqual(error.exception.status, 403)
                load.assert_not_called()
                gather.assert_not_called()
                records.assert_not_called()
