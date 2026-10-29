"""Shared saved-target counting and unchanged Shopping adapter boundaries, with fakes."""
import copy
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

from decklab.lib import buying_needs as needs
from decklab.lib import cards, config, inventory
from decklab.lib.api import common
from decklab.lib.api import shopping_missing as web


def summary(deck_id="casual/alpha", title="Alpha", *, status="building", target=True):
    return {"id": deck_id, "title": title, "kind": "casual", "player": "either", "status": status,
            "versions": ["target", "owned"] if target else ["owned"]}


def counted_row(name, missing, *, waiting=0):
    return {"name": name, "missing": missing, "waiting": waiting}


def result(*rows, warnings=(), unresolved=()):
    return {"rows": list(rows), "warnings": list(warnings), "unresolved": list(unresolved)}


class BuyingNeedsTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.supply = SimpleNamespace(warnings=[], unresolved={})
        self.load = self.stack.enter_context(mock.patch.object(needs.pool, "load_pool", return_value=self.supply))
        self.compare = self.stack.enter_context(mock.patch.object(needs.pool, "owned_vs_needed", return_value=result()))
        self.labels = self.stack.enter_context(mock.patch.object(
            needs.pool, "row_labels", side_effect=lambda row: {"on_the_way": [("Fixture order", row["waiting"])]}))
        self.stack.enter_context(mock.patch.object(config, "load", side_effect=AssertionError("no config read")))
        self.stack.enter_context(mock.patch.object(cards, "_get", side_effect=AssertionError("no card-index read")))
        self.canonical = mock.Mock(side_effect=lambda name: name)
        self.public = mock.Mock(side_effect=lambda value: f"public({value})")
        self.logs = []

    def count(self, summaries, **kwargs):
        return needs.count(summaries, canonical=self.canonical, public=self.public, log=self.logs.append, **kwargs)

    def test_no_targets_does_not_load_pool_resolve_names_or_invent_unavailability(self):
        out = self.count([])
        self.assertEqual((out.phase, out.status), ("no_targets", "ready"))
        self.assertEqual((out.rows, out.decks, out.errors, out.warnings, out.message), ([], [], [], [], None))
        self.load.assert_not_called()
        self.compare.assert_not_called()
        self.canonical.assert_not_called()

    def test_missing_targets_retain_prior_errors_without_mutating_the_callers_list(self):
        errors = [{"message": "Earlier enumeration failure"}]
        before = copy.deepcopy(errors)
        out = self.count([summary(target=False)], errors=errors)
        self.assertEqual((out.phase, out.status), ("no_targets", "partial"))
        self.assertEqual(out.errors, [*before, {"id": "casual/alpha", "title": "Alpha",
                                             "message": "This deck has no planned list to count."}])
        self.assertEqual(errors, before)
        self.assertIsNot(out.errors, errors)
        self.load.assert_not_called()

    def test_successful_empty_count_is_distinct_from_no_targets(self):
        out = self.count([summary()])
        self.assertEqual((out.phase, out.status, out.rows, out.decks), ("counted", "ready", [], []))
        self.load.assert_called_once_with()
        self.compare.assert_called_once_with("casual/alpha", "target", pool=self.supply, prices=False)

    def test_every_deck_uses_one_shared_pool_and_target_without_prices(self):
        self.count([summary(), summary("commander/beta", "Beta")])
        self.load.assert_called_once_with()
        self.assertEqual(self.compare.call_args_list, [
            mock.call("casual/alpha", "target", pool=self.supply, prices=False),
            mock.call("commander/beta", "target", pool=self.supply, prices=False)])

    def test_pool_failure_keeps_exact_logging_and_public_error_message(self):
        self.load.side_effect = ValueError("fixture pool problem")
        prior = [{"message": "Earlier failure"}]
        out = self.count([summary()], errors=prior)
        self.assertEqual((out.phase, out.status), ("unavailable", "unavailable"))
        self.assertEqual(out.message, "The home card pool could not be read: public(fixture pool problem)")
        self.assertEqual(out.errors, prior)
        self.assertEqual(self.logs, ["Shopping missing cards: the pool could not be read: fixture pool problem"])
        self.compare.assert_not_called()

    def test_unavailable_pool_propagates_instead_of_becoming_an_ordinary_partial_result(self):
        self.load.side_effect = inventory.Unavailable("fixture unavailable")
        with self.assertRaisesRegex(inventory.Unavailable, "fixture unavailable"):
            self.count([summary()])
        self.assertEqual(self.logs, [])
        self.public.assert_not_called()

    def test_any_global_pool_warning_invalidates_all_comparisons(self):
        self.supply.warnings = ["Fixture warning"]
        self.supply.unresolved = {"Zeta": "source", "Alpha": "source"}
        out = self.count([summary()])
        self.assertEqual((out.phase, out.status), ("unavailable", "unavailable"))
        self.assertEqual(out.warnings, ["public(Fixture warning)", "Unknown cards in the home pool: Alpha, Zeta"])
        self.assertEqual(out.message, "Missing cards cannot be counted until the home card pool is complete.")
        self.compare.assert_not_called()
        self.canonical.assert_not_called()

    def test_canonical_aliases_merge_before_cross_deck_quantities_are_summed(self):
        self.canonical.side_effect = lambda name: "Front // Back" if name in ("Front", "Front // Back") else name
        self.compare.side_effect = [result(counted_row("Front", 2, waiting=1), counted_row("Front // Back", 1),
                                           counted_row("Zero", 0), counted_row("Surplus", -2)),
                                    result(counted_row("Front // Back", 4, waiting=2), counted_row("Other", 1))]
        out = self.count([summary(), summary("casual/beta", "Beta", status="idea")])
        self.assertEqual([(row["name"], row["missing"]) for row in out.rows], [("Front // Back", 7), ("Other", 1)])
        self.assertEqual([(deck["id"], deck["missing"]) for deck in out.rows[0]["decks"]],
                         [("casual/alpha", 3), ("casual/beta", 4)])
        self.assertEqual([(deck["missing"], deck["on_the_way"]) for deck in out.decks], [(3, 1), (5, 2)])
        self.assertNotIn("queue", out.rows[0])
        self.assertNotIn("card", out.rows[0])
        self.assertNotIn(mock.call("Zero"), self.canonical.call_args_list)

    def test_one_bad_deck_preserves_other_proven_needs_with_partial_status(self):
        self.compare.side_effect = [ValueError("fixture deck problem"), result(counted_row("Proven", 2))]
        out = self.count([summary(), summary("casual/beta", "Beta")])
        self.assertEqual((out.phase, out.status), ("counted", "partial"))
        self.assertEqual([row["name"] for row in out.rows], ["Proven"])
        self.assertEqual(out.errors, [{"id": "casual/alpha", "title": "Alpha",
                                      "message": "This deck could not be counted: public(fixture deck problem)"}])
        self.assertEqual(self.logs, ["Shopping missing cards: casual/alpha could not be counted: fixture deck problem"])

    def test_per_deck_warning_and_unknown_cards_never_produce_partially_guessed_rows(self):
        self.compare.side_effect = [result(counted_row("Unproven", 99), warnings=["Fixture warning"],
                                           unresolved=[("Zeta", "source"), ("Alpha", "source"), ("Zeta", "other")]),
                                    result(counted_row("Proven", 1))]
        out = self.count([summary(), summary("casual/beta", "Beta")])
        self.assertEqual([row["name"] for row in out.rows], ["Proven"])
        self.assertEqual(out.errors[0]["message"],
                         "This deck could not be fully counted: public(Fixture warning); Unknown cards: Alpha, Zeta")
        self.assertEqual(self.logs, [])

    def test_inventory_unavailability_during_one_deck_still_propagates(self):
        self.compare.side_effect = inventory.Unavailable("fixture changed availability")
        with self.assertRaisesRegex(inventory.Unavailable, "fixture changed availability"):
            self.count([summary()])
        self.assertEqual(self.logs, [])

    def test_canonical_failure_does_not_leak_earlier_rows_of_that_deck(self):
        self.compare.return_value = result(counted_row("Good", 1), counted_row("Bad", 2))
        self.canonical.side_effect = ["Good", ValueError("fixture canonical problem")]
        out = self.count([summary()])
        self.assertEqual((out.rows, out.decks, out.status), ([], [], "partial"))
        self.assertEqual(out.errors[0]["message"],
                         "This deck could not be counted: public(fixture canonical problem)")

    def test_label_calculation_failure_preserves_existing_per_deck_error_boundary(self):
        self.compare.return_value = result(counted_row("Good", 1))
        self.labels.side_effect = ValueError("fixture labels problem")
        out = self.count([summary()])
        self.assertEqual((out.rows, out.decks, out.status), ([], [], "partial"))
        self.assertEqual(out.errors[0]["message"], "This deck could not be counted: public(fixture labels problem)")

    def test_counting_does_not_mutate_summaries_results_or_an_existing_pin(self):
        found = summary()
        compared = result(counted_row("Card", 1))
        before = copy.deepcopy((found, compared))
        self.compare.return_value = compared
        with mock.patch.object(inventory, "pinned", side_effect=AssertionError("new pin")):
            self.count([found])
        self.assertEqual((found, compared), before)

    def test_optional_adapter_callbacks_keep_existing_problem_and_incomplete_seams(self):
        problem = mock.Mock(side_effect=lambda deck, message: {"where": deck["id"], "why": message})
        incomplete = mock.Mock(return_value="Adapter's explanation")
        out = self.count([summary()], problem_for=problem, incomplete_for=incomplete)
        self.assertEqual(out.errors, [{"where": "casual/alpha",
                                      "why": "This deck could not be fully counted: Adapter's explanation"}])
        incomplete.assert_called_once_with(self.compare.return_value)

    def test_fixed_status_never_requires_a_consumer_to_relay_error_contents(self):
        for phase, errors, expected in (("no_targets", [], "ready"), ("no_targets", [{}], "partial"),
                                        ("counted", [], "ready"), ("counted", [{}], "partial"),
                                        ("unavailable", [], "unavailable")):
            with self.subTest(phase=phase, errors=errors):
                self.assertEqual(needs.CountedNeeds(phase, errors=errors).status, expected)


class ShoppingCountingAdapterTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.logs = []
        self.stack.enter_context(mock.patch.object(common, "_log", self.logs.append))
        self.supply = SimpleNamespace(warnings=[], unresolved={})
        self.stack.enter_context(mock.patch.object(web.pool, "load_pool", return_value=self.supply))
        self.compare = self.stack.enter_context(mock.patch.object(web.pool, "owned_vs_needed", return_value=result()))
        self.stack.enter_context(mock.patch.object(web.pool, "row_labels", return_value={"on_the_way": []}))
        self.canonical = self.stack.enter_context(mock.patch.object(web, "_canonical", side_effect=lambda name: name))
        self.stack.enter_context(mock.patch.object(web, "is_token", return_value=False))
        self.picture = mock.Mock(return_value=None)

    def test_existing_pool_patch_seam_is_the_same_library_module(self):
        self.assertIs(web.pool, needs.pool)

    def test_no_target_return_does_not_newly_examine_queue_or_pictures(self):
        out, legacy = web.gather([], [{"name": "Queued"}], self.picture)
        self.assertEqual(out, {"ready": True, "rows": [], "warnings": [], "errors": [],
                               "totals": {"cards": 0, "copies": 0}})
        self.assertEqual(legacy, [])
        self.canonical.assert_not_called()
        self.picture.assert_not_called()

    def test_unavailable_pool_return_keeps_exact_packet_and_avoids_queue_work(self):
        self.supply.warnings = ["Fixture warning"]
        prior = [{"message": "Earlier failure"}]
        out, legacy = web.gather([summary()], [{"name": "Queued"}], self.picture, errors=prior)
        self.assertEqual(out, {"ready": False, "rows": [], "warnings": ["Fixture warning"],
                               "errors": [*prior, {"message":
                                   "Missing cards cannot be counted until the home card pool is complete."}],
                               "totals": {"cards": 0, "copies": 0}})
        self.assertEqual(legacy, [])
        self.canonical.assert_not_called()
        self.picture.assert_not_called()

    def test_valid_zero_needs_still_runs_legacy_queue_matching_and_its_error_boundary(self):
        self.canonical.side_effect = ValueError("fixture queue problem")
        out, legacy = web.gather([summary()], [{"name": "Queued"}], self.picture)
        self.assertEqual(out, {"ready": False, "rows": [], "warnings": [],
                               "errors": [{"message": "Queued cards could not be matched: fixture queue problem"}],
                               "totals": {"cards": 0, "copies": 0}})
        self.assertEqual(legacy, [])
        self.assertEqual(self.logs, ["Shopping missing cards: queue matching failed: fixture queue problem"])

    def test_queue_copies_only_annotate_counts_and_presentation_order_stays_identical(self):
        self.compare.side_effect = [result(counted_row("Beta", 2), counted_row("Alpha", 1)),
                                    result(counted_row("Alpha", 2))]
        queued = {"name": "Alpha", "quantity": "99", "state": "deferred", "notes": "Fixture note"}
        out, legacy = web.gather([summary("casual/z", "Zulu"), summary("casual/a", "Able", status="idea")],
                                 [queued], self.picture)
        self.assertEqual([(row["name"], row["missing"]) for row in out["rows"]], [("Alpha", 3), ("Beta", 2)])
        self.assertEqual(out["totals"], {"cards": 2, "copies": 5})
        self.assertEqual([deck["title"] for deck in out["rows"][0]["decks"]], ["Able", "Zulu"])
        self.assertEqual(out["rows"][0]["queue"], [queued])
        self.assertIsNot(out["rows"][0]["queue"][0], queued)
        self.assertEqual([deck["title"] for deck in legacy], ["Zulu", "Able"])
        self.assertEqual(list(out["rows"][0]), ["name", "missing", "decks", "queue", "card"])
        self.assertEqual(self.picture.call_args_list, [mock.call("Alpha"), mock.call("Beta")])

    def test_existing_canonical_and_incomplete_monkeypatches_still_control_the_adapter(self):
        self.compare.return_value = result(counted_row("Alias", 2))
        self.canonical.side_effect = None
        self.canonical.return_value = "Canonical"
        with mock.patch.object(web, "_incomplete", return_value="Adapter warning") as incomplete:
            out, _ = web.gather([summary()], [], self.picture)
        self.assertEqual(out["errors"][0]["message"], "This deck could not be fully counted: Adapter warning")
        incomplete.assert_called_once_with(self.compare.return_value)
        self.canonical.assert_not_called()
        out, _ = web.gather([summary()], [], self.picture)
        self.assertEqual(out["rows"][0]["name"], "Canonical")
