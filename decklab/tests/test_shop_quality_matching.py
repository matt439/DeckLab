"""One household preference reaches matching, stock mixtures, plans and historical lows."""
import copy
import contextlib
import io
from types import SimpleNamespace
from unittest import mock

from decklab.lib import access, listing_preference, pricing_setting, shops, state
from decklab.lib.api import pricing_setting as pricing_api, shop_baskets, shop_missing_prices, shop_prices
from decklab.lib.shops import history
from decklab.tests import test_pricing_setting as pricing_fixture
from decklab.tests.test_pricing_setting import MATT, _Fresh, configured
from decklab.tests.test_shop_baskets import entry, listing, mtgmate, row
from decklab.tests.test_shops import entry as page_entry, page

PREFERENCE = {"minimum_condition": "LP", "english_only": True}


def offer(price, condition, language, *, stock=1, number="227", suffix=""):
    item = listing(price, stock, number=number)
    item.update(condition=condition, language=language)
    if suffix:
        item["url"] += "-" + suffix
    return item


def sample():
    return mtgmate({"Llanowar Elves": entry(offer("1.00", "Damaged", "ja", stock=10),
        offer("3.00", "NM", "en", stock=1), offer("4.00", "LP", "en", stock=2, suffix="lp"),
        offer("2.00", "NM", "", stock=5, suffix="unknown"))})


class QualityMatchingTests(_Fresh):
    def preference(self, value=PREFERENCE):
        store = self.install()
        store.pricing_setting_put({"currency": None, "shops": None, "listing_preferences": value}, 0, MATT, "Set synthetic quality preference")
        return store

    def test_default_pick_stays_unchanged_and_metadata_names_low_grade_and_non_english(self):
        self.install()
        data = sample()
        before = copy.deepcopy(data)
        shown = shops.match(row("Llanowar Elves", 1), data)
        self.assertEqual((shown["price_aud"], shown["condition"], shown["language"]), ("1.00", "Damaged", "Japanese"))
        self.assertNotIn("skipped_cheaper", shown)
        self.assertEqual(data, before)
        raw = page_entry("Llanowar Elves", "fdn", "227", "3.00", 1, condition="Near Mint")
        raw["language"] = "JA"
        parsed = shops.mtgmate.parse_name_page(page(raw), "Llanowar Elves")
        self.assertEqual(parsed[0]["language"], "JA")

    def test_preference_filters_picks_basket_remaining_copies_and_fewest_shops_plan(self):
        self.preference()
        data = sample()
        asked = row("Llanowar Elves", 1, quantity="3", printing="exact", set="fdn", collector_number="227", finish="nonfoil")
        chosen = shops.match(asked, data)
        self.assertEqual((chosen["price_aud"], chosen["condition"], chosen["language"]), ("3.00", "Near Mint", "English"))
        self.assertTrue(chosen["skipped_cheaper"])
        with configured():
            baskets = shop_baskets.build([asked], {"mtgmate": data}, adapters=[shops.ADAPTER], rules={"mtgmate": {"postage_aud": "0"}})
        line = baskets["shops"][0]["rows"][0]
        self.assertEqual((line["copies"], line["line_aud"], line["short"]), (3, "11.00", False))
        self.assertEqual(line["listing"]["condition"], "Near Mint")
        self.assertEqual([(item["condition"], item["language"], item["copies"]) for item in line["more"]], [("Lightly Played", "English", 2)])
        self.assertEqual(baskets["plan"]["recommended"]["cards_aud"], "11.00")

    def test_history_lowest_and_strict_deck_projection_follow_the_same_preference(self):
        self.preference()
        data = sample()
        readings = {"Llanowar Elves": [
            {"on": "2026-11-01", "at": "2026-11-01T12:00:00Z", "listings": [offer("0.50", "DMG", "en"), offer("5.00", "NM", "en")]},
            {"on": "2026-11-02", "at": "2026-11-02T12:00:00Z", "listings": [offer("4.00", "LP", "en")]},
            {"on": "2026-11-03", "at": "2026-11-03T12:00:00Z", "listings": [offer("0.25", "NM", "")]}]}
        shown = history.report("Llanowar Elves", [(shops.ADAPTER, {"history": readings})], shops.pick, details=shops.selection_reader())
        self.assertEqual([day["lowest"] for day in shown["shops"][0]["days"]], [False, True, False])
        self.assertTrue(shown["shops"][0]["days"][0]["skipped_cheaper"])
        self.assertTrue(shown["shops"][0]["days"][2]["preference_excluded"])
        projected = shop_missing_prices.Projection(data, lambda name: name).for_row({"name": "Llanowar Elves"})
        self.assertEqual((projected["price_aud"], projected["condition"], projected["language"]), ("3.00", "Near Mint", "English"))
        self.assertTrue(projected["skipped_cheaper"])
        self.assertNotIn("listing_preferences", projected)  # public unit-price facts don't publish home settings

    def test_a_capture_pins_the_preference_for_both_lines_and_baskets(self):
        store = self.install()
        captured = shop_prices.Captured({"mtgmate": sample()})
        store.pricing_setting_put({"listing_preferences": PREFERENCE}, 0, MATT, "Change after the capture")
        pricing_setting.forget()
        asked = row("Llanowar Elves", 1)
        with configured(shops=["mtgmate"]):
            answer = shop_prices.enrich({"to_buy": [dict(asked)]}, data=captured)
            baskets = shop_baskets.build([asked], captured, rules={})
        self.assertEqual(answer["to_buy"][0]["shop_snapshot"]["price_aud"], "1.00")
        self.assertEqual(baskets["shops"][0]["rows"][0]["listing"]["price_aud"], "1.00")
        self.assertEqual(shops.match(asked, sample())["price_aud"], "3.00")

    def test_no_qualifying_listing_is_distinct_from_not_listed_or_wrong_printing(self):
        self.preference()
        data = mtgmate({"Llanowar Elves": entry(offer("1.00", "NM", ""))})
        self.assertEqual(shops.match(row("Llanowar Elves", 1), data)["status"], "not_eligible")
        exact = row("Llanowar Elves", 1, printing="exact", set="m19", collector_number="314", finish="nonfoil")
        self.assertEqual(shops.match(exact, data)["status"], "not_matched")

    def test_unreadable_preference_with_no_verified_fallback_never_claims_cheap_qualifying_stock(self):
        store = mock.Mock()
        store.pricing_setting.side_effect = state.Unavailable("Synthetic unavailable setting")
        store.pricing_setting_cached.return_value = None
        self.install(store)
        shown = shops.match(row("Llanowar Elves", 1), sample())
        self.assertEqual(shown["status"], "unknown")
        self.assertTrue(shown["preference_unknown"])
        self.assertIsNone(shown["price_aud"])
        self.assertIs(listing_preference.current(), listing_preference.UNAVAILABLE)

    def test_a_saved_preference_remains_in_force_during_a_temporary_store_failure(self):
        store = self.preference()
        self.assertEqual(listing_preference.current(), PREFERENCE)
        store.down = True
        self.assertEqual(shops.match(row("Llanowar Elves", 1), sample())["price_aud"], "3.00")

    def test_standalone_cli_lazily_uses_the_default_store_and_saved_preference_before_matching(self):
        from decklab.lib.state import memory, pg
        default_store = memory.MemoryStore()
        default_store.pricing_setting_put({"listing_preferences": PREFERENCE}, 0, MATT, "Seed a synthetic default provider")
        output = io.StringIO()
        # Substitute only state.py's environment facade and PgStore factory.
        # The real fixture environment/DB/network guards stay installed.
        with mock.patch.object(state, "os", SimpleNamespace(environ={})), \
                mock.patch.object(state, "_default", None), mock.patch.object(state, "_active", []), \
                mock.patch.object(pg, "PgStore", return_value=default_store) as factory, \
                configured(shops=["mtgmate"]), mock.patch.object(shops, "load", return_value=sample()), \
                mock.patch.object(shops, "_queue", return_value=[row("Llanowar Elves", 1)]), \
                contextlib.redirect_stdout(output):
            self.assertEqual(shops.main(["show"]), 0)
        factory.assert_called_once_with()
        self.assertIn("A$3.00", output.getvalue())
        self.assertIn("Near Mint, English", output.getvalue())
        self.assertNotIn("A$1.00", output.getvalue())

    def test_nonfixture_provider_bootstrap_error_is_unavailable_and_explicit_none_stays_pure(self):
        asked = row("Llanowar Elves", 1)
        with mock.patch.object(listing_preference, "os", SimpleNamespace(environ={})), \
                mock.patch.object(state, "store", side_effect=RuntimeError("Synthetic bootstrap failure")):
            self.assertIs(listing_preference.current(), listing_preference.UNAVAILABLE)
            self.assertEqual(shops.match(asked, sample())["status"], "unknown")
        with mock.patch.object(state, "store", side_effect=AssertionError("Pure matching must not read state")):
            choice, _ = shops.pick(asked, sample()["cards"]["Llanowar Elves"]["listings"], preference=None)
            self.assertEqual(choice["price"], "1.00")


class QualityPreferenceApiTests(pricing_fixture.PricingApiTests):
    def test_home_admin_preference_is_audited_shared_and_an_old_client_preserves_it(self):
        with access.viewing("matt"):
            saved = self.save(listing_preferences=PREFERENCE)
            self.assertEqual(saved["listing_preferences"]["effective"], PREFERENCE)
            old_client = self.save(expect=1, currency_code="GBP")
            self.assertEqual(old_client["listing_preferences"]["effective"], PREFERENCE)
            self.assertEqual(old_client["currency"]["effective"], "GBP")
            self.assertApiError(409, lambda: self.save(expect=1, listing_preferences=None))
        with access.viewing("user1"):
            self.assertEqual(pricing_api.view()["listing_preferences"]["effective"], PREFERENCE)
            self.assertApiError(403, lambda: self.save(profile="user1", expect=2, listing_preferences=None))
        self.assertEqual(len(self.box.state.changes()), 2)
        self.assertEqual((self.box.root / "config.json").read_bytes(), self.config_bytes)

    def test_explicit_neutral_preference_clears_it_without_changing_currency_or_shop_choices(self):
        with access.viewing("matt"):
            self.save(listing_preferences=PREFERENCE)
            result = self.save(expect=1, listing_preferences=None)
        self.assertIsNone(result["listing_preferences"]["effective"])
        self.assertEqual(self.box.state.pricing_setting()["pricing"]["v"], 1)

    def test_old_client_cannot_use_a_stale_cached_read_to_drop_an_existing_preference(self):
        with access.viewing("matt"):
            self.save(listing_preferences=PREFERENCE)
            with mock.patch.object(self.box.state, "pricing_setting", return_value={"revision": 0, "pricing": {"v": 1, "currency": None, "shops": None}}):
                self.assertApiError(409, lambda: self.save(expect=1, currency_code="GBP"))
        self.assertEqual(self.box.state.pricing_setting()["pricing"]["listing_preferences"], PREFERENCE)
        self.assertEqual(len(self.box.state.changes()), 1)
