"""Private saved shop evidence on deck needs, using disposable file inventory and supplied caches.

Run: python scripts/test_fixtures.py decklab.tests.test_deck_shop_prices
No configured collection, shop cache, network or database is accessed.
"""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, cards, inventory, shops
from decklab.lib.api import deck_page, guard, shop_prices
from decklab.tests.test_api import _write
from decklab.tests.test_api_permissions import PermissionTestCase
from decklab.tests.test_shop_missing_prices import AT, listing, record, snapshot

DECK = "casual/gruul-test"


class DeckShopPricesTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        self.saved = snapshot({"Llanowar Elves": record(listing("9.00", 3),
            listing("0.10", 0, set_code="m19", number="314"),
            listing("0.25", 1, set_code="cmm", number="648")),
            "Elvish Mystic": record(listing("0.50", 7, set_code="cmm", number="648"))})
        patcher = mock.patch.object(shops, "load", return_value=self.saved)
        self.load = patcher.start()
        self.addCleanup(patcher.stop)
        for owner, name in ((shops, "_fetch"), (shops, "_write"), (inventory, "apply"), (cards, "update")):
            patcher = mock.patch.object(owner, name, side_effect=AssertionError("Saved evidence must not fetch or write"))
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def view(who="matt", deck=DECK, version="target"):
        with access.using({"profile": who, "email": "", "remote": True}):
            return deck_page.deck_view(deck, version, omit={"matchups"})

    def test_home_admin_and_member_get_one_capture_only_on_actual_missing_rows(self):
        for who in ("matt", "user1"):
            with self.subTest(who=who):
                self.load.reset_mock()
                answer = self.view(who)
                self.load.assert_called_once()
                rows = answer["owned"]["rows"]
                self.assertTrue(any(row["missing"] > 0 for row in rows))
                for row in rows:
                    self.assertEqual("shop_snapshot" in row, row["missing"] > 0)
                elves = next(row for row in rows if row["name"] == "Llanowar Elves")
                self.assertEqual((elves["shop_snapshot"]["price_aud"], elves["shop_snapshot"]["stock"]), ("0.25", 1))
                self.assertEqual(elves["shop_snapshot"]["scope"], "nonfoil")
                self.assertEqual(elves["shop_snapshot"]["fetched_at"], AT)

    def test_estimates_rate_counts_and_sections_are_unchanged_by_optional_evidence(self):
        with mock.patch.object(deck_page, "_saved_shop_prices"):
            baseline = self.view()
        answer = self.view()
        for row in answer["owned"]["rows"]:
            row.pop("shop_snapshot", None)
        self.assertEqual(answer["owned"], baseline["owned"])
        self.assertEqual(answer["sections"], baseline["sections"])
        self.assertEqual(answer["version"], baseline["version"])

    def test_public_deck_does_not_open_inventory_or_shop_cache(self):
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})):
            answer = self.view("user2")
        self.assertNotIn("owned", answer)
        self.assertNotIn("shop_snapshot", json.dumps(answer))
        self.load.assert_not_called()

    def test_public_home_collection_allows_counts_without_household_cache_coverage(self):
        with mock.patch.object(guard, "public_spaces", side_effect=lambda thing: frozenset({"home"})
                               if thing in ("decks", "collection") else frozenset()):
            answer = self.view("user2")
        self.assertIn("owned", answer)
        self.assertTrue(answer["owned"]["rows"])
        self.assertTrue(all("shop_snapshot" not in row for row in answer["owned"]["rows"]))
        self.load.assert_not_called()

    def test_member_own_deck_and_admin_read_of_public_member_deck_never_use_home_cache(self):
        self.view("user2", "user2/casual/r-elves")
        with mock.patch.object(guard, "public_spaces", return_value=frozenset({"user2"})):
            answer = self.view("matt", "user2/casual/r-elves")
        self.assertTrue(all("shop_snapshot" not in row for row in answer.get("owned", {}).get("rows", [])))
        self.load.assert_not_called()

    def test_ordinary_anonymous_request_reads_no_cache_even_for_a_public_deck(self):
        with access.using({"profile": None, "email": "", "remote": False}), access.answering(False), \
                mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})):
            try:
                answer = deck_page.deck_view(DECK, omit={"matchups"})
            except deck_page.ApiError as error:
                self.assertEqual(error.status, 404)
            else:
                self.assertNotIn("owned", answer)
        self.load.assert_not_called()

    def test_trusted_script_keeps_existing_full_read_rule(self):
        with access.using(None), access.viewing(None), access.answering(True):
            answer = deck_page.deck_view(DECK, omit={"matchups"})
        self.assertTrue(any("shop_snapshot" in row for row in answer["owned"]["rows"]))
        self.load.assert_called_once()

    def test_hidden_and_missing_decks_are_refused_before_any_capture(self):
        for deck in (DECK, "casual/not-present"):
            with self.subTest(deck=deck), self.assertRaises(deck_page.ApiError) as failure:
                self.view("user2", deck)
            self.assertEqual(failure.exception.status, 404)
        self.load.assert_not_called()

    def test_hidden_raw_alias_resolving_to_home_skips_optional_cache_without_changing_deck_view(self):
        from decklab.lib import decks
        real = decks.find_summary
        hidden_alias = "user2/casual/old-alias"
        def resolved(deck_id):
            return real(DECK if deck_id == hidden_alias else deck_id)
        with mock.patch.object(decks, "find_summary", side_effect=resolved):
            answer = self.view("matt", hidden_alias)
        self.assertEqual(answer["summary"]["id"], DECK)
        self.assertTrue(answer["owned"]["rows"])
        self.assertTrue(all("shop_snapshot" not in row for row in answer["owned"]["rows"]))
        self.load.assert_not_called()

    def test_failed_owned_and_fully_covered_version_skip_capture(self):
        with mock.patch.object(deck_page, "_load_pool", return_value=None):
            self.assertIsNone(self.view()["owned"])
        self.load.assert_not_called()
        real_compare = deck_page.pool.owned_vs_needed
        def covered(*args, **kwargs):
            result = real_compare(*args, **kwargs)
            for row in result["rows"]:
                row["missing"] = 0
            result["totals"]["missing"] = 0
            return result
        with mock.patch.object(deck_page.pool, "owned_vs_needed", side_effect=covered) as compare:
            self.view(version="owned")
        self.assertTrue(compare.called)
        self.load.assert_not_called()

    def test_absent_capture_is_explicit_and_does_not_invoke_default_reload_matchers(self):
        self.load.return_value = None
        with mock.patch.object(shop_prices, "for_row", side_effect=AssertionError("Implicit reload")), \
                mock.patch.object(shops, "match", side_effect=AssertionError("Exact queue intent")):
            answer = self.view()
        self.load.assert_called_once()
        self.assertTrue(all(row["shop_snapshot"]["status"] == "not_checked"
                            for row in answer["owned"]["rows"] if row["missing"] > 0))

    def test_cache_read_failure_is_optional_and_raw_details_never_enter_answer(self):
        self.load.side_effect = OSError("PRIVATE household cache path")
        answer = self.view()
        self.load.assert_called_once()
        self.assertTrue(answer["owned"])
        self.assertNotIn("PRIVATE", json.dumps(answer))
        self.assertTrue(all(row["shop_snapshot"]["status"] == "not_checked"
                            for row in answer["owned"]["rows"] if row["missing"] > 0))

    def test_exact_foil_deck_line_keeps_its_intent_beside_generic_nonfoil_evidence(self):
        path = self.box.magic / "decks" / "casual" / "gruul-test.md"
        text = path.read_text(encoding="utf-8").replace("4 Llanowar Elves (FDN) 227", "4 Llanowar Elves (FDN) 227 *F*")
        _write(path, text)
        answer = self.view()
        line = next(line for line in answer["sections"]["Deck"] if line["name"] == "Llanowar Elves" and line["qty"] == 4)
        self.assertEqual((line["set"], line["number"], line["finish"]), ("fdn", "227", "foil"))
        row = next(row for row in answer["owned"]["rows"] if row["name"] == "Llanowar Elves")
        self.assertEqual((row["shop_snapshot"]["set"], row["shop_snapshot"]["finish"]), ("cmm", "nonfoil"))


class DeckShopProjectionBoundaryTests(unittest.TestCase):
    def enrich(self, rows, data, *, inventory_visible=True, home_records=True, space="home", raw_visible=True):
        owned = {"rows": rows, "totals": {"missing": 12}, "rate": 1.43}
        with mock.patch.object(guard, "sees_deck", return_value=raw_visible), \
                mock.patch.object(guard, "sees_inventory", return_value=inventory_visible), \
                mock.patch.object(guard, "sees_home_records", return_value=home_records), \
                mock.patch.object(shop_prices, "capture", return_value=data) as capture, \
                mock.patch.object(shop_prices, "_loaded_resolver", return_value=lambda name: name):
            deck_page._saved_shop_prices(owned, space, DECK)
        return owned, capture

    def test_both_read_rules_and_home_space_precede_capture(self):
        for kwargs in ({"raw_visible": False}, {"inventory_visible": False}, {"home_records": False}, {"space": "user2"}):
            rows = [{"name": "Llanowar Elves", "missing": 2}]
            owned, capture = self.enrich(rows, snapshot(), **kwargs)
            capture.assert_not_called()
            self.assertNotIn("shop_snapshot", owned["rows"][0])

    def test_only_positive_exact_integer_needs_are_annotated(self):
        rows = [{"name": "Llanowar Elves", "missing": value} for value in (True, "2", 1.5, 0, -1, None, 2)]
        before = copy.deepcopy(rows)
        owned, capture = self.enrich(rows, snapshot())
        capture.assert_called_once()
        self.assertTrue(all("shop_snapshot" not in row for row in rows[:-1]))
        self.assertIn("shop_snapshot", rows[-1])
        rows[-1].pop("shop_snapshot")
        self.assertEqual(rows, before)
        self.assertEqual(owned["totals"], {"missing": 12})

    def test_carried_date_and_malformed_cache_facts_keep_fixed_statuses(self):
        cases = [(snapshot({"Llanowar Elves": record(listing(), carried=True)}), "in_stock"),
                 (snapshot({"Llanowar Elves": record(listing(stock=True))}), "unknown"),
                 (snapshot({"Llanowar Elves": record(listing(), at="2026-02-30T01:00:00Z")}), "unknown"),
                 (snapshot({"Llanowar Elves": record(status="not_listed")}), "not_listed")]
        for data, expected in cases:
            with self.subTest(expected=expected):
                owned, _ = self.enrich([{"name": "Llanowar Elves", "missing": 12}], data)
                evidence = owned["rows"][0]["shop_snapshot"]
                self.assertEqual(evidence["status"], expected)
                if evidence.get("carried"):
                    self.assertEqual(evidence["fetched_at"], AT)

    def test_projection_reuses_supplied_resolver_without_loading_index(self):
        captured = snapshot({"Murderous Rider": record(listing())})
        rows = [{"name": "Murderous Rider // Swift End", "missing": 1}]
        resolve = lambda name: "Murderous Rider // Swift End" if name.startswith("Murderous Rider") else name
        with mock.patch.object(guard, "sees_deck", return_value=True), \
                mock.patch.object(guard, "sees_inventory", return_value=True), \
                mock.patch.object(guard, "sees_home_records", return_value=True), \
                mock.patch.object(shop_prices, "capture", return_value=captured), \
                mock.patch.object(shop_prices, "_loaded_resolver", return_value=resolve), \
                mock.patch.object(cards, "_get", side_effect=AssertionError("Index load")):
            deck_page._saved_shop_prices({"rows": rows}, "home", DECK)
        self.assertEqual(rows[0]["shop_snapshot"]["status"], "in_stock")

    def test_no_missing_or_failed_owned_does_not_load_snapshot_or_resolver(self):
        with mock.patch.object(guard, "sees_deck", return_value=True), \
                mock.patch.object(guard, "sees_inventory", return_value=True), \
                mock.patch.object(guard, "sees_home_records", return_value=True), \
                mock.patch.object(shop_prices, "capture") as capture, \
                mock.patch.object(shop_prices, "_loaded_resolver") as resolver:
            for owned in (None, {}, {"rows": None}, {"rows": {}}, {"rows": []}, {"rows": [{"name": "A", "missing": 0}]}):
                deck_page._saved_shop_prices(owned, "home", DECK)
        capture.assert_not_called()
        resolver.assert_not_called()

    def test_projection_does_not_change_snapshot_inputs(self):
        data = snapshot()
        before = copy.deepcopy(data)
        self.enrich([{"name": "Llanowar Elves", "missing": 2}], data)
        self.assertEqual(data, before)
