"""Narrow historical comparison of an absent shop check, never production cache access."""
import copy
import unittest
from unittest import mock

from decklab.tests import golden_dump, golden_p4, golden_shop_prices

DEFAULT = golden_shop_prices.ABSENT_MISSING_SNAPSHOT
PROFILES = {
    "matt": {"id": "matt", "space": "home", "role": "admin", "plays_as": "user"},
    "user1": {"id": "user1", "space": "home", "role": "member", "plays_as": "wife"},
    "user2": {"id": "user2", "space": "user2", "role": "admin"},
}


def answer(missing=2, snapshot=None):
    return {"summary": {"id": "casual/a", "space": "home"}, "owned": {
        "rows": [{"name": "Fixture card", "need": 4, "owned": 2, "missing": missing,
                  "shop_snapshot": copy.deepcopy(DEFAULT if snapshot is None else snapshot)}],
        "totals": {"need": 4, "missing": 2}, "warnings": ["Keep this warning"]}}


def page(*, selector="casual/a@target", missing=2, snapshot=None):
    view = answer(missing, snapshot)
    if isinstance(selector, str) and "@" in selector:
        view["summary"]["id"] = selector.rsplit("@", 1)[0]
    return {"deck_view": {selector: view}}


class ShopPriceGoldenTests(unittest.TestCase):
    def normalise(self, dump, *, profiles=PROFILES):
        # Isolate this boundary: old hidden_inventory may intentionally remove a whole
        # outside viewer's owned parent. That cannot establish this helper's privacy rule.
        with mock.patch.object(golden_p4, "_profiles", return_value=profiles), \
                mock.patch.object(golden_p4, "EXPECTED_P4", ()), \
                mock.patch.object(golden_p4, "EXPECTED_P5", (("absent-shop-prices", golden_p4.absent_shop_prices),)):
            return golden_p4.normalise(dump)

    @staticmethod
    def row(dump, selector="casual/a@target"):
        return dump["deck_view"][selector]["owned"]["rows"][0]

    def test_default_is_registered_as_one_explicit_historical_difference(self):
        self.assertIn(("absent-shop-prices", golden_p4.absent_shop_prices), golden_p4.EXPECTED_P5)
        self.assertEqual(len(DEFAULT), 15)
        self.assertIs(type(DEFAULT["in_stock_printings"]), int)
        for field in ("back_in_stock", "newly_in_stock", "carried"):
            self.assertIs(type(DEFAULT[field]), bool)

    def test_only_exact_authorized_script_and_home_profile_contexts_are_normalized(self):
        original = {**page(), "by_viewer": {viewer: page() for viewer in
                    ("(local)", "matt", "user1", "user2", "unknown", "local", "(anonymous)")}}
        actual = self.normalise(original)
        self.assertNotIn("shop_snapshot", self.row(actual))
        for viewer in ("(local)", "matt", "user1"):
            self.assertNotIn("shop_snapshot", self.row(actual["by_viewer"][viewer]))
        for viewer in ("user2", "unknown", "local", "(anonymous)"):
            self.assertEqual(self.row(actual["by_viewer"][viewer])["shop_snapshot"], DEFAULT)

    def test_mismatched_or_malformed_profile_metadata_never_grants_a_home_context(self):
        for profiles in ({}, None, {"unknown": {"id": "matt", "space": "home"}},
                         {"unknown": {"id": "unknown", "space": "user2", "role": "admin"}},
                         {"unknown": "home"}, {None: {"id": None, "space": "home"}}):
            key = None if isinstance(profiles, dict) and None in profiles else "unknown"
            original = {"by_viewer": {key: page()}}
            with self.subTest(profiles=profiles):
                self.assertEqual(self.normalise(original, profiles=profiles), original)

    def test_safe_home_casual_commander_product_and_pairing_selectors_are_in_scope(self):
        for deck_id in ("casual/a", "commander/a", "product/precon", "product/precon/deck", "pairing/cats+elves"):
            for version in ("target", "owned"):
                selector = f"{deck_id}@{version}"
                with self.subTest(selector=selector):
                    self.assertNotIn("shop_snapshot", self.row(self.normalise(page(selector=selector)), selector))

    def test_member_unsupported_and_malformed_selector_paths_remain_comparable(self):
        selectors = ("user2/casual/private@target", "user2/commander/private@owned", "home/commander/a@target",
                     "collection/a@target", "casual/a", "casual/a@other", "casual/a@target@owned",
                     "casual/ @target", "casual/ a@target", "casual/a @target", "product/a/ @owned",
                     "casual/a/b@target", "product/a/b/c@target", "pairing/a/b@target", "casual/.hidden@target",
                     "casual/a\\b@target", "casual/a:b@target", "casual/a\n@target", "casual/\ud800@target", "@target")
        for selector in selectors:
            original = page(selector=selector)
            with self.subTest(selector=repr(selector)):
                self.assertEqual(self.normalise(original), original)

    def test_only_positive_exact_integer_shortfalls_are_eligible(self):
        for missing in (0, -1, False, True, 1.0, float("inf"), "1", None):
            original = page(missing=missing)
            with self.subTest(missing=missing):
                self.assertEqual(self.normalise(original), original)
        self.assertNotIn("shop_snapshot", self.row(self.normalise(page(missing=1))))

    def test_contradictory_summary_space_identity_or_version_stays_comparable(self):
        changes = (lambda value: value.update(summary=None),
                   lambda value: value.update(summary={}),
                   lambda value: value["summary"].update(space="user2"),
                   lambda value: value["summary"].update(id="user2/casual/private"),
                   lambda value: value["summary"].update(id="casual/another"),
                   lambda value: value.update(version="owned"))
        for change in changes:
            original = page()
            change(original["deck_view"]["casual/a@target"])
            with self.subTest(change=change):
                self.assertEqual(self.normalise(original), original)
        original = page()
        original["deck_view"]["casual/a@target"].pop("summary")
        self.assertNotIn("shop_snapshot", self.row(self.normalise(original)))

    def test_every_default_value_type_is_exact_even_when_python_values_compare_equal(self):
        class String(str):
            pass
        class Integer(int):
            pass
        for field, value in DEFAULT.items():
            replacements = ([0] if type(value) is bool else [False, 0.0, Integer(0)] if type(value) is int
                            else [String(value)] if type(value) is str else [False, 0, ""])
            for replacement in replacements:
                changed = {**DEFAULT, field: replacement}
                with self.subTest(field=field, replacement=repr(replacement)):
                    actual = self.row(self.normalise(page(snapshot=changed)))["shop_snapshot"]
                    self.assertIs(type(actual[field]), type(replacement))
                    self.assertEqual(actual, changed)

    def test_missing_or_extra_default_keys_and_malformed_containers_remain_evidence(self):
        for field in DEFAULT:
            changed = dict(DEFAULT)
            changed.pop(field)
            with self.subTest(missing=field):
                self.assertEqual(self.row(self.normalise(page(snapshot=changed)))["shop_snapshot"], changed)
        for changed in ({**DEFAULT, "new_field": None}, {**DEFAULT, 0: False}, [], "not checked", False):
            with self.subTest(changed=changed):
                self.assertEqual(self.row(self.normalise(page(snapshot=changed)))["shop_snapshot"], changed)
        original = page()
        self.row(original)["shop_snapshot"] = None
        self.assertEqual(self.normalise(original), original)

    def test_rich_price_stock_error_carried_and_dated_facts_still_compare(self):
        base = self.normalise(page())
        changes = ({"price_aud": "1.00"}, {"stock": 1}, {"fetched_at": "2026-10-29T03:00:00+10:00"},
                   {"error": "Fixture unavailable"}, {"carried": True}, {"status": "unknown"},
                   {"status": "not_listed"}, {"set": "abc", "collector_number": "1", "finish": "nonfoil"},
                   {"url": "https://example.com/fixture"}, {"back_in_stock": True}, {"newly_in_stock": True},
                   {"in_stock_printings": 1}, {"scope": "foil"}, {"shop": "Another fixture shop"})
        for change in changes:
            snapshot = {**DEFAULT, **change}
            with self.subTest(change=change):
                actual = self.normalise(page(snapshot=snapshot))
                self.assertEqual(self.row(actual)["shop_snapshot"], snapshot)
                self.assertIsNotNone(golden_dump.first_difference(base, actual))

    def test_unrelated_paths_nested_rows_and_fields_are_not_recursively_stripped(self):
        unrelated = {"owned": {"rows": [{"missing": 1, "shop_snapshot": copy.deepcopy(DEFAULT)}]}}
        original = {**page(), "shopping": copy.deepcopy(unrelated), "edit_view": {"casual/a": copy.deepcopy(unrelated)},
                    "nested": {"deck_view": {"casual/a@target": copy.deepcopy(unrelated)}}}
        original["deck_view"]["casual/a@target"]["other"] = copy.deepcopy(unrelated)
        actual = self.normalise(original)
        self.assertNotIn("shop_snapshot", self.row(actual))
        for key in ("shopping", "edit_view", "nested"):
            self.assertEqual(actual[key], original[key])
        self.assertEqual(actual["deck_view"]["casual/a@target"]["other"], unrelated)

    def test_counts_warnings_and_all_other_legacy_fields_continue_to_compare(self):
        base = page()
        for change in (lambda value: self.row(value).update(missing=3),
                       lambda value: self.row(value).update(need=5),
                       lambda value: value["deck_view"]["casual/a@target"]["owned"].update(warnings=[]),
                       lambda value: self.row(value).update(name="Changed fixture card")):
            changed = copy.deepcopy(base)
            change(changed)
            self.assertIsNotNone(golden_dump.first_difference(self.normalise(base), self.normalise(changed)))

    def test_malformed_view_shapes_are_unchanged_and_do_not_raise(self):
        for original in ({"deck_view": []}, {"deck_view": {"casual/a@target": None}},
                         {"deck_view": {"casual/a@target": {"owned": []}}},
                         {"deck_view": {"casual/a@target": {"owned": {"rows": {"missing": 2}}}}},
                         {"by_viewer": []}, {"by_viewer": {"matt": None}}):
            with self.subTest(original=original):
                self.assertEqual(self.normalise(original), original)

    def test_public_normalise_copies_input_and_does_not_touch_configured_resources(self):
        original = {**page(), "by_viewer": {"matt": page()}}
        untouched = copy.deepcopy(original)
        with mock.patch.object(golden_p4, "_profiles", return_value=PROFILES), \
                mock.patch.object(golden_p4.config, "load", side_effect=AssertionError("no configured reads")):
            actual = golden_p4.normalise(original)
        self.assertIsNot(actual, original)
        self.assertEqual(original, untouched)
        self.assertNotIn("shop_snapshot", self.row(actual))
        self.assertNotIn("shop_snapshot", self.row(actual["by_viewer"]["matt"]))
