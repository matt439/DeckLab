"""Manual field exclusions observe disposable selectors, never live records or games.

Run: python scripts/test_fixtures.py decklab.tests.test_field_exclusion_counts
"""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib import decks, inventory
from decklab.lib.api import field_page
from decklab.lib.forge import engine, field, field_exclusions as counts, lists, rankings
from decklab.tests import test_forge_field as fixtures


class ActualExclusionTests(fixtures.FieldTestCase):
    def setUp(self):
        super().setUp()
        original = decks.list_decks
        patcher = mock.patch.object(decks, "list_decks", side_effect=lambda: [
            summary for summary in original() if not summary.get("error")])
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(field, "_side_id", side_effect=lambda entry, eng: "side-" + entry["card_sha"])
        patcher.start()
        self.addCleanup(patcher.stop)

    def configure(self, *, add=(), remove=()):
        fixtures._write(self.simulation, json.dumps({"field": {"Constructed": {
            "add": list(add), "remove": list(remove)}}}))

    def observed(self, observer=None, **options):
        observer = counts.Observation(options.get("visible")) if observer is None else observer
        result = field._field("Constructed", exclusions=observer, **options)
        return result, counts.count(observer)

    def assert_legacy(self, observer=None, **options):
        before = field._field("Constructed", **options)
        after, count = self.observed(observer, **options)
        self.assertEqual(before, after)
        return after, count

    def test_missing_configuration_is_a_proven_zero_without_pairing_enumeration(self):
        with mock.patch.object(decks, "beginner_box_pairings", side_effect=AssertionError("Extra enumeration")):
            _, number = self.assert_legacy()
        self.assertEqual(number, 0)

    def test_duplicate_wildcard_version_and_noop_removals_count_actual_choices(self):
        self.configure(remove=["casual/alpha@target", "casual/alpha", "casual/alpha@target",
                               "casual/beta@target", "casual/missing", "casual/gamma@target"])
        (selected, _), number = self.assert_legacy()
        self.assertEqual(number, 2)
        self.assertEqual({entry["id"] for entry in selected}, {"product/aggro", "casual/beta"})

    def test_added_reversed_pairing_is_counted_by_current_identity_once(self):
        self.configure(add=["pairing/elves+cats"], remove=["pairing/elves+cats", "pairing/cats+elves"])
        _, number = self.assert_legacy()
        self.assertEqual(number, 1)

    def test_resolved_missing_wrong_format_and_missing_version_additions_are_definite_noops(self):
        self.configure(add=["casual/missing", "commander/cmdr", "casual/alpha@absent"])
        _, number = self.assert_legacy()
        self.assertEqual(number, 0)

    def test_known_alias_removal_uses_existing_predicate_calls_without_extra_resolution(self):
        self.configure(remove=["casual/former", "casual/alpha"])
        original = field._same_id
        def same(first, second):
            return original("casual/alpha" if first == "casual/former" else first,
                            "casual/alpha" if second == "casual/former" else second)
        with mock.patch.object(field, "_same_id", side_effect=same) as match:
            before = field._field("Constructed")
            legacy_calls = match.call_args_list[:]
            match.reset_mock()
            after, number = self.observed()
            self.assertEqual(match.call_args_list, legacy_calls)
        self.assertEqual((after, number), (before, 1))

    def test_hidden_raw_alias_removes_visible_list_without_publishing_a_count(self):
        self.configure(remove=["casual/former"])
        def same(first, second):
            return first == second or {first, second} == {"casual/alpha", "casual/former"}
        with mock.patch.object(field, "_same_id", side_effect=same):
            (selected, _), number = self.assert_legacy(visible=lambda name: name != "casual/former")
        self.assertNotIn("casual/alpha", {entry["id"] for entry in selected})
        self.assertEqual(number, 0)

    def test_hidden_canonical_summary_cannot_enter_the_count_via_a_visible_alias(self):
        self.configure(remove=["casual/former"])
        with mock.patch.object(field, "_same_id", side_effect=lambda first, second:
                               first == second or {first, second} == {"casual/alpha", "casual/former"}):
            _, number = self.assert_legacy(visible=lambda name: name != "casual/alpha")
        self.assertEqual(number, 0)

    def test_distinct_current_lists_with_identical_simulation_cards_count_before_hash_collapse(self):
        fixtures._write(self.root / "magic" / "decks" / "casual" / "same.md", fixtures.DECK.format(
            title="Same", status="built", extra="- **Built version:** owned-only", cards="4 Opt\n4 Forest",
            owned=fixtures.OWNED.format(card="Opt")))
        fixtures._write(self.root / "magic" / "decks" / "casual" / "same-other.md", fixtures.DECK.format(
            title="Same Other", status="building", extra="", cards="4 Opt\n4 Forest", owned=""))
        self.assertEqual(self.entry("casual/same", "owned")["card_sha"],
                         self.entry("casual/same-other")["card_sha"])
        self.configure(remove=["casual/same@target", "casual/same@owned", "casual/same-other"])
        _, number = self.assert_legacy()
        self.assertEqual(number, 2)

    def test_parser_failure_keeps_legacy_fallback_and_marks_unknown(self):
        fixtures._write(self.simulation, "{broken")
        _, number = self.assert_legacy()
        self.assertIsNone(number)

    def test_falsey_malformed_shapes_and_values_do_not_become_known_zero(self):
        malformed = [[], {"field": []}, *({"field": {"Constructed": value}}
                      for value in ([], False, 0, "", "bad", 1)),
                     {"field": {"Constructed": {"remove": "casual/alpha"}}},
                     {"field": {"Constructed": {"add": [None], "remove": []}}}]
        for value in malformed:
            with self.subTest(value=value):
                fixtures._write(self.simulation, json.dumps(value))
                _, number = self.assert_legacy()
                self.assertIsNone(number)

    def test_malformed_truthy_root_preserves_original_exception_type(self):
        for value in ({"field": 1}, {"field": "bad"}, {"field": {"Constructed": {"remove": 3}}}):
            with self.subTest(value=value):
                fixtures._write(self.simulation, json.dumps(value))
                try:
                    field._field("Constructed")
                except Exception as error:
                    expected = type(error)
                else:
                    self.fail("Fixture must exercise a legacy selector exception")
                observer = counts.Observation()
                with self.assertRaises(expected):
                    field._field("Constructed", exclusions=observer)
                self.assertIsNone(counts.count(observer))

    def test_status_and_selected_list_failures_are_unknown_without_changing_selection(self):
        with mock.patch.object(field.card_pool, "read_status", side_effect=ValueError("fixture-private-path")):
            _, number = self.assert_legacy()
            self.assertIsNone(number)
        original = field._entry
        def broken(summary, version):
            if summary["id"] == "casual/alpha":
                raise ValueError("fixture-private-path")
            return original(summary, version)
        with mock.patch.object(field, "_entry", side_effect=broken):
            _, number = self.assert_legacy()
        self.assertIsNone(number)

    def test_visible_unreadable_product_and_configured_addition_are_unknown(self):
        original = decks.list_decks
        def summaries():
            return [*original(), {"id": "product/unreadable", "title": "Unreadable", "error": "fixture-path"}]
        with mock.patch.object(decks, "list_decks", side_effect=summaries):
            _, number = self.assert_legacy()
        self.assertIsNone(number)
        self.configure(add=["casual/unreadable"])
        with mock.patch.object(decks, "find_summary", return_value={"id": "casual/unreadable", "error": "fixture"}):
            _, number = self.assert_legacy()
        self.assertIsNone(number)

    def test_hidden_unreadable_additions_are_gated_before_lookup_and_metadata(self):
        self.configure(add=["casual/private"])
        with mock.patch.object(decks, "find_summary", side_effect=AssertionError("Hidden lookup")):
            _, number = self.assert_legacy(visible=lambda name: name != "casual/private")
        self.assertEqual(number, 0)

    def test_observer_callback_failures_change_neither_results_nor_notes(self):
        self.configure(remove=["casual/alpha"])
        for method in ("begin", "configuration", "removed", "finish"):
            with self.subTest(method=method):
                observer = counts.Observation()
                with mock.patch.object(observer, method, side_effect=RuntimeError("metadata failure")):
                    _, number = self.assert_legacy(observer)
                self.assertIsNone(number)

    def test_cancellation_is_not_swallowed_by_metadata_dispatch(self):
        observer = counts.Observation()
        with mock.patch.object(observer, "begin", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            field._field("Constructed", exclusions=observer)

    def test_one_configuration_read_and_private_names_reused_for_existing_prose(self):
        self.configure(remove=["casual/alpha"])
        observer = counts.Observation()
        with lists.one_snapshot(), mock.patch.object(field, "_simulation_edits", wraps=field._simulation_edits) as read, \
                mock.patch.object(field, "_field", wraps=field._field) as select:
            rows, _ = rankings._catalog("Constructed", eng={"kind": engine.KIND_DECKLAB}, exclusions=observer)
        read.assert_called_once()
        select.assert_called_once()
        alpha = next(row for row in rows if row["id"] == "casual/alpha")
        self.assertEqual(alpha["exclusion"], "Left out by the field configuration.")
        self.assertEqual(counts.count(observer), 1)

    def test_mixed_legacy_configuration_retains_exclusion_prose_with_unknown_count(self):
        fixtures._write(self.simulation, json.dumps({"field": {"Constructed": {
            "remove": ["casual/alpha", 4]}}}))
        observer = counts.Observation()
        with lists.one_snapshot():
            rows, _ = rankings._catalog("Constructed", eng={}, exclusions=observer)
        alpha = next(row for row in rows if row["id"] == "casual/alpha")
        self.assertEqual(alpha["exclusion"], "Left out by the field configuration.")
        self.assertIsNone(counts.count(observer))

    def test_ranking_visibility_gates_counts_even_without_field_options(self):
        self.configure(remove=["casual/alpha", "casual/gamma"])
        observer = counts.Observation(lambda name: name != "casual/gamma")
        with lists.one_snapshot():
            rows, _ = rankings._catalog("Constructed", observer.visible,
                                        eng={"kind": engine.KIND_DECKLAB}, exclusions=observer)
        self.assertNotIn("casual/gamma", {row["id"] for row in rows})
        self.assertEqual(counts.count(observer), 1)

    def test_ignored_selector_observer_has_unknown_count_and_no_second_config_read(self):
        observer = counts.Observation()
        with mock.patch.object(field, "_field", return_value=([], [])) as select, \
                mock.patch.object(field, "_simulation_edits", side_effect=AssertionError("Second read")), \
                lists.one_snapshot():
            rows, _ = rankings._catalog("Constructed", eng={}, exclusions=observer)
        select.assert_called_once()
        self.assertIsNone(counts.count(observer))
        self.assertTrue(all(row["exclusion"] != "Left out by the field configuration." for row in rows))

    def test_field_rating_adds_count_in_a_copy_only_when_a_rating_exists(self):
        self.configure(remove=["casual/gamma"])
        original_rating = {"value": 1000, "rank": 1, "of": 2}
        with mock.patch.object(field, "_rating", return_value=(original_rating, {})):
            answer = field.view(self.entry("casual/alpha"))
        self.assertEqual(answer["rating"], {**original_rating, "manual_excluded": 1})
        self.assertNotIn("manual_excluded", original_rating)
        self.assertNotIn("manual_excluded", answer)
        with mock.patch.object(field, "_rating", return_value=(None, {})):
            self.assertIsNone(field.view(self.entry("casual/alpha"))["rating"])

    def test_factory_and_property_errors_keep_field_and_rankings_results_usable(self):
        with mock.patch.object(counts, "Observation", side_effect=ValueError("constructor")), \
                mock.patch.object(field, "_rating", return_value=({"value": 1000}, {})):
            self.assertIsNone(field.view(self.entry("casual/alpha"))["rating"]["manual_excluded"])
        class BrokenProperties:
            @property
            def count(self):
                raise ValueError("property")
            @property
            def removals(self):
                raise ValueError("property")
        self.assertIsNone(counts.count(BrokenProperties()))
        self.assertEqual(counts.removals(BrokenProperties()), ())
        for value in (True, -1, 1001, "2", float("nan")):
            self.assertIsNone(counts.count(type("BrokenValue", (), {"count": value})()))
        with mock.patch.object(rankings, "_catalog", return_value=([], [])), \
                mock.patch.object(field, "_bt_data", return_value={}), \
                mock.patch.object(rankings, "_historical", return_value={}), \
                mock.patch.object(engine, "read_only_today", return_value={"kind": engine.KIND_DECKLAB, "complete": True}):
            self.assertIsNone(rankings._view("Constructed", None, None)["manual_excluded"])


class BoundedExclusionTests(unittest.TestCase):
    def test_hidden_opponent_removes_rating_and_its_manual_count_together(self):
        seen = SimpleNamespace(deck=lambda name: name == "casual/visible", historical=lambda name: True)
        original = {"opponents": [{"id": "casual/visible", "games": 200}, {"id": "casual/hidden"}],
                    "rating": {"rank": 1, "manual_excluded": 3}, "average": {"value": 0.5},
                    "notes": ["Hidden details"], "last_run": None}
        answer, fields, whole = field_page._seen_field(original, original["opponents"], seen)
        self.assertFalse(whole)
        self.assertIsNone(answer["rating"])
        self.assertNotIn("manual_excluded", json.dumps(answer))
        self.assertEqual([row["id"] for row in fields], ["casual/visible"])
        self.assertEqual(original["rating"]["manual_excluded"], 3)

    def test_broken_unavailable_and_fallback_cannot_escape_metadata_dispatch(self):
        class BrokenObserver:
            __slots__ = ()
            def begin(self):
                raise ValueError("begin")
            def unavailable(self):
                raise ValueError("unavailable")
        counts.notify(BrokenObserver(), "begin")
        with mock.patch.object(counts, "Observation", new=object()):
            counts.notify(BrokenObserver(), "begin")

    def test_exact_bound_and_overflow_do_not_change_the_selected_field(self):
        for size in (1000, 1001):
            with self.subTest(size=size):
                observer = counts.Observation()
                summaries = [{"id": f"casual/deck-{number}", "title": str(number), "kind": "casual",
                              "versions": ["target"]}
                             for number in range(size)]
                def configuration(fmt, **options):
                    remove = [summary["id"] for summary in summaries]
                    counts.notify(options.get("exclusions"), "configuration", remove)
                    return [], remove
                with mock.patch.object(inventory, "is_pinned", return_value=True), \
                        mock.patch.object(decks, "list_decks", return_value=summaries), \
                        mock.patch.object(field.card_pool, "read_status", return_value={}), \
                        mock.patch.object(field, "_simulation_edits", side_effect=configuration), \
                        mock.patch.object(field, "_same_id", new=lambda a, b: a == b):
                    before = field._field("Constructed")
                    after = field._field("Constructed", exclusions=observer)
                self.assertEqual((before, after), (([], []), ([], [])))
                self.assertEqual(counts.count(observer), size if size == 1000 else None)
                self.assertLessEqual(len(observer._keys), counts.MAX_LISTS)

    def test_duplicate_directives_cannot_inflate_or_overflow_the_distinct_choice_count(self):
        observer = counts.Observation()
        observer.begin()
        observer.configuration(["casual/a"] * 2000)
        for _ in range(2000):
            observer.removed({"id": "casual/a"}, "target", "casual/a", None)
        observer.finish()
        self.assertEqual(observer.count, 1)

    def test_unobserved_or_unfinished_selectors_never_claim_zero(self):
        observer = counts.Observation()
        self.assertIsNone(observer.count)
        observer.begin()
        observer.finish()
        self.assertIsNone(observer.count)
        observer.configuration([])
        self.assertEqual(observer.count, 0)
        observer.begin()
        self.assertIsNone(observer.count)
