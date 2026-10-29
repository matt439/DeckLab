"""Buying evidence reads saved variant recipes and disposable inventory; no games or external I/O."""
from collections import Counter
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest import mock

from decklab.lib import api, cards, decks, inventory, pool, purchases
from decklab.lib.api import carddata, guard, variant_buying, variant_page
from decklab.lib.inventory.model import Deck
from decklab.tests import test_variant_api as support


GROWTH = "Giant Growth"
AVAILABILITY_FIELDS = ("need", "free_now", "free_including_incoming", "ready_added", "incoming_added", "missing_added")


class VariantBuyingTests(support.VariantApiCase):
    def setUp(self):
        super().setUp()
        self.supply = pool.Pool(Counter(), {}, [])
        self.pool_read = self.patch(pool, "load_pool", return_value=self.supply)
        self.queue_read = self.patch(purchases, "read_queue", return_value=[])
        self.cached_rate = self.patch(carddata, "_cached_rate", return_value={"rate": 2.0, "date": "2026-10-27"})
        self.cheapest = self.patch(cards, "cheapest_usd", return_value=(0.25, "war", "162", "nonfoil"))
        self.patch(cards, "price_date", return_value="2026-10-28")
        self.forbidden = [self.patch(owner, name, side_effect=AssertionError("No external or execution path"))
                          for owner, name in [(cards, "usd_to_aud"), (cards, "price_aud"), (cards, "_get_json"),
                                              (cards, "_download"), (support.real_forge.engine, "today"),
                                              (support.real_forge.variants, "run_test")]]

    def tearDown(self):
        for forbidden in self.forbidden:
            forbidden.assert_not_called()
        super().tearDown()

    def patch(self, owner, name, **options):
        patcher = mock.patch.object(owner, name, **options)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def summary(self, text=support.SWAPPED, deck_id=support.GREEN_ID, version="target", changes=None):
        forge_lists = support.real_forge.lists
        base = forge_lists._section_cards(decks.load_deck(deck_id, version))
        variant = forge_lists._section_cards(decks.parse_decklist(text))
        kind = "commander" if deck_id.startswith("commander/") else "constructed"
        if changes is None:
            def counted(sections):
                result = Counter()
                for section in sections.values():
                    for quantity, name in section:
                        result[support.real_forge.common.forge_name(name)] += quantity
                return result
            before, after = counted(base), counted(variant)
            changes = {"add": [[quantity, name] for name, quantity in (after - before).items()],
                       "remove": [[quantity, name] for name, quantity in (before - after).items()]}
        return {"test": "a" * 64,
                "base": {"id": deck_id, "version": version, "kind": kind,
                         "card_sha": forge_lists._list_text(base, kind)[1]},
                "variant": {"cards": variant, "card_sha": forge_lists._list_text(variant, kind)[1], "changes": changes}}

    def write_current(self, text, deck_id=support.GREEN_ID):
        support._write(self.box.magic / "decks" / f"{deck_id}.md", support.deck_file("Fixture Deck", text))

    def one(self, result, name=GROWTH):
        return next(row for row in result["rows"] if row["name"] == name)

    def assert_unknown(self, result):
        self.assertFalse(result["availability_ready"])
        self.assertTrue(result["availability_problem"])
        self.assertTrue(all(row[field] is None for row in result["rows"] for field in AVAILABILITY_FIELDS))

    def saved_view(self):
        test = self.summary()
        test.update(looks=[{}], outcome="better", against={"id": support.RED_ID})
        saved = {"test": test, "opponents": [], "verdict": "better", "words": "Fixture verdict"}
        seen = SimpleNamespace(deck=lambda deck_id: True, sides=lambda sides: True, mask=lambda answer: answer,
                               coordinator=lambda job: True, can_stop=lambda job, visible: True)
        return saved, seen

    def test_additions_reserve_the_full_recipe_before_dividing_ready_incoming_and_missing(self):
        current = support.test_forge.GREEN + "\nCompanion\n1 Giant Growth\n"
        current = current.replace("2 Lightning Bolt", "2 Giant Growth")
        self.write_current(current)
        variant = current.replace("1 Fiery Annihilation\n", "").replace("2 Overrun\n", "").replace("2 Giant Growth\n", "5 Giant Growth\n", 1)
        test = self.summary(variant)
        self.supply.owned[GROWTH] = 8
        self.supply.on_the_way[GROWTH] = [("Fixture delivery", 1)]
        self.supply.in_use.extend([pool.InUse(support.GREEN_ID, "This deck", "built", Counter({GROWTH: 99})),
                                   pool.InUse("product/fixture", "Another box", "intact product", Counter({GROWTH: 1}))])
        compare = pool.compare
        with mock.patch.object(pool, "compare", wraps=compare) as compared:
            result = variant_buying.build(test)
        self.assertTrue(result["ready"])
        row = self.one(result)
        self.assertEqual({field: row[field] for field in ("added", *AVAILABILITY_FIELDS)},
                         {"added": 3, "need": 8, "free_now": 6, "free_including_incoming": 7,
                          "ready_added": 1, "incoming_added": 1, "missing_added": 1})
        self.assertEqual(row["ready_added"] + row["incoming_added"] + row["missing_added"], row["added"])
        compared.assert_called_once()
        self.assertFalse(compared.call_args.kwargs["prices"])
        self.assertIn(support.GREEN_ID, compared.call_args.args[2])

    def test_queue_intent_never_becomes_physical_or_incoming_supply(self):
        self.queue_read.return_value = [{"name": GROWTH, "quantity": 50, "state": "ready", "for": "Fixture deck", "printing": "any"}]
        result = variant_buying.build(self.summary())
        row = self.one(result)
        self.assertEqual((row["ready_added"], row["incoming_added"], row["missing_added"]), (0, 0, 1))
        self.assertEqual(row["queued"][0]["quantity"], 50)

    def test_saved_add_and_remove_entries_are_net_canonical_card_changes(self):
        test = self.summary(changes={"add": [[2, "giant growth"]],
                                     "remove": [[1, GROWTH], [1, "Fiery Annihilation"]]})
        result = variant_buying.build(test)
        self.assertEqual([(row["name"], row["added"]) for row in result["rows"]], [(GROWTH, 1)])

    def test_current_saved_variant_is_accepted_without_counting_the_addition_twice(self):
        test = self.summary()
        self.write_current(support.SWAPPED)
        result = variant_buying.build(test)
        self.assertTrue(result["availability_ready"])
        self.assertEqual((self.one(result)["added"], self.one(result)["need"]), (1, 3))
        self.assertEqual(test["variant"]["changes"], {"add": [[1, GROWTH]], "remove": [[1, "Fiery Annihilation"]]})

    def test_renamed_deck_uses_its_current_identity_for_lookup_and_self_exclusion(self):
        test = self.summary()
        snapshot = inventory.current()
        old = snapshot.deck(support.GREEN_ID)
        current_id = "casual/renamed-green"
        snapshot = snapshot.without_deck(support.GREEN_ID).with_deck(Deck("home", "casual", "renamed-green", old.text))
        snapshot = snapshot.replace(deck_aliases={support.GREEN_ID: current_id}, aliases_ready=True)
        self.supply.owned[GROWTH] = 3
        self.supply.in_use.append(pool.InUse(current_id, "Renamed deck", "built", Counter({GROWTH: 3})))
        with inventory.pinned(snapshot):
            result = variant_buying.build(test)
        self.assertTrue(result["availability_ready"])
        self.assertEqual((self.one(result)["ready_added"], self.one(result)["missing_added"]), (1, 0))
        self.assertEqual(test["base"]["id"], support.GREEN_ID)

    def test_play_now_uses_its_own_recipe_and_preserves_its_sideboard(self):
        path = self.box.magic / "decks" / f"{support.GREEN_ID}.md"
        parsed = decks.parse_deck(path.read_bytes(), "green-test", "casual")
        owned = decks.parse_decklist(support.test_forge.GREEN.replace("2 Lightning Bolt", "2 Giant Growth"))
        decks.apply_edit(parsed, owned=owned)
        support._write(path, decks.render_deck_file(parsed))
        test = self.summary(version="owned")
        result = variant_buying.build(test)
        self.assertTrue(result["availability_ready"])
        self.assertEqual(self.one(result)["need"], 5)
        self.assertEqual(self.one(result)["added"], 1)

    def test_double_faced_forge_names_resolve_to_one_full_card_name(self):
        variant = support.test_forge.RED.replace("4 Lightning Bolt", "3 Lightning Bolt").replace("2 Fire // Ice", "3 Fire // Ice")
        test = self.summary(variant, support.RED_ID)
        self.assertEqual(test["variant"]["changes"]["add"], [[1, "Fire"]])
        result = variant_buying.build(test)
        self.assertEqual([(row["name"], row["added"], row["need"]) for row in result["rows"]], [("Fire // Ice", 1, 3)])

    def test_commander_recipe_keeps_its_commander_in_the_complete_demand(self):
        deck_id = "commander/fixture-gisa"
        text = support.deck_file("Fixture Gisa", support.test_forge.GISA).replace("Casual 60-card, 1v1", "Commander")
        support._write(self.box.magic / "decks" / f"{deck_id}.md", text)
        variant = support.test_forge.GISA.replace("4 Murderous Rider // Swift End", "3 Murderous Rider // Swift End\n1 Giant Growth")
        compare = pool.compare
        with mock.patch.object(pool, "compare", wraps=compare) as compared:
            result = variant_buying.build(self.summary(variant, deck_id))
        self.assertTrue(result["availability_ready"])
        self.assertEqual(self.one(result)["need"], 1)
        self.assertEqual(compared.call_args.args[0]["Commander"], [decks.DeckLine(1, "Ghoulcaller Gisa")])

    def test_added_basic_lands_are_separate_from_buying_rows(self):
        variant = support.test_forge.GREEN.replace("1 Fiery Annihilation\n", "").replace("6 Forest", "7 Forest")
        result = variant_buying.build(self.summary(variant))
        self.assertTrue(result["availability_ready"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["basic_added"], [{"name": "Forest", "added": 1}])
        self.cheapest.assert_not_called()

    def test_changed_or_deleted_current_deck_keeps_queue_evidence_but_marks_availability_unknown(self):
        test = self.summary()
        self.write_current(support.test_forge.GREEN.replace("2 Giant Growth", "4 Giant Growth"))
        self.queue_read.return_value = [{"name": GROWTH, "quantity": 2, "state": "deferred", "for": "Later", "printing": "any"}]
        changed = variant_buying.build(test)
        self.assert_unknown(changed)
        self.assertTrue(changed["queue_ready"])
        self.assertEqual(self.one(changed)["queued"][0]["quantity"], 2)
        (self.box.magic / "decks" / f"{support.GREEN_ID}.md").unlink()
        self.assert_unknown(variant_buying.build(test))

    def test_missing_tampered_or_malformed_saved_recipe_never_claims_availability(self):
        original = self.summary()
        examples = []
        for edit in (lambda test: test["variant"].pop("cards"),
                     lambda test: test["variant"].update(card_sha="0" * 64),
                     lambda test: test["base"].update(card_sha="not-a-hash"),
                     lambda test: test["variant"]["cards"]["Main"].append([True, GROWTH]),
                     lambda test: test["variant"]["cards"].update(Sideboard=[])):
            test = deepcopy(original)
            edit(test)
            examples.append(test)
        for test in examples:
            with self.subTest(test=test):
                result = variant_buying.build(test)
                self.assert_unknown(result)
                self.assertEqual(self.one(result)["added"], 1)

    def test_bounded_saved_changes_must_reconstruct_the_recipe_from_a_matching_base(self):
        test = self.summary(changes={"add": [[2, GROWTH]], "remove": [[2, "Overrun"]]})
        self.queue_read.return_value = [{"name": GROWTH, "quantity": 2, "state": "deferred", "for": "Fixture deck", "printing": "any"}]
        result = variant_buying.build(test)
        self.assert_unknown(result)
        self.pool_read.assert_not_called()
        self.assertTrue(result["queue_ready"])
        self.assertEqual(self.one(result)["added"], 2)
        self.assertEqual(self.one(result)["queued"][0]["quantity"], 2)

    def test_impossible_saved_removal_cannot_be_hidden_by_adding_the_same_card_back(self):
        test = self.summary(changes={"add": [[2, GROWTH], [1, "Fiery Annihilation"]],
                                     "remove": [[1, GROWTH], [2, "Fiery Annihilation"]]})
        self.queue_read.return_value = [{"name": GROWTH, "quantity": 1, "state": "ready", "for": "Fixture deck", "printing": "any"}]
        result = variant_buying.build(test)
        self.assert_unknown(result)
        self.pool_read.assert_not_called()
        self.assertTrue(result["queue_ready"])
        self.assertEqual(self.one(result)["added"], 1)
        self.assertEqual(self.one(result)["queued"][0]["quantity"], 1)

    def test_pool_warnings_or_unresolved_cards_make_every_availability_field_unknown(self):
        for field, value in (("warnings", ["An incomplete fixture source"]), ("unresolved", {"Unknown": {"fixture"}})):
            with self.subTest(field=field):
                supply = pool.Pool(Counter({GROWTH: 100}), {}, [], **{field: value})
                self.pool_read.return_value = supply
                self.assert_unknown(variant_buying.build(self.summary()))

    def test_denied_home_records_refuses_before_any_inventory_queue_or_price_reader(self):
        test = self.summary()
        with mock.patch.object(guard, "sees_home_records", return_value=False), \
                mock.patch.object(inventory, "current", side_effect=AssertionError("No private snapshot")) as current:
            self.assertApiError(403, variant_buying.build, test)
            current.assert_not_called()
        for reader in (self.pool_read, self.queue_read, self.cached_rate, self.cheapest):
            reader.assert_not_called()

    def test_failed_snapshot_entry_returns_optional_unavailability_before_any_reader(self):
        test = self.summary()
        snapshot = mock.MagicMock()
        snapshot.__enter__.side_effect = RuntimeError("Fixture snapshot entry failed")
        with mock.patch.object(inventory, "is_pinned", return_value=False), \
                mock.patch.object(inventory, "pinned", return_value=snapshot):
            result = variant_buying.build(test)
        self.assertFalse(result["ready"])
        self.assertFalse(result["availability_ready"])
        self.assertFalse(result["queue_ready"])
        self.assertEqual(result["rows"], [])
        for reader in (self.pool_read, self.queue_read, self.cached_rate, self.cheapest):
            reader.assert_not_called()

    def test_recorded_reference_prices_keep_zero_aud_and_all_queue_context_but_exclude_foil_references(self):
        shared = {"name": GROWTH, "quantity": 2, "printing": "any", "set": "", "collector_number": "",
                  "listed_at": "Fixture shop", "checked": "2026-10-26"}
        self.queue_read.return_value = [dict(shared, finish="", state="ready", listed_aud="0", **{"for": "Deck A"}),
                                        dict(shared, finish="foil", state="waiting_for_stock", listed_aud="1", **{"for": "Deck B"}),
                                        dict(shared, finish="nonfoil", state="long_term", listed_aud="2.50", **{"for": "Future"})]
        result = variant_buying.build(self.summary())
        row = self.one(result)
        self.assertEqual([(item["quantity"], item["state"], item["purpose"], item["finish"]) for item in row["queued"]],
                         [(2, "ready", "Deck A", ""), (2, "waiting_for_stock", "Deck B", "foil"), (2, "long_term", "Future", "nonfoil")])
        self.assertEqual([(ref["aud"], ref["shop"], ref["checked"], ref["finish"]) for ref in row["references"]],
                         [(0.0, "Fixture shop", "2026-10-26", ""), (2.5, "Fixture shop", "2026-10-26", "nonfoil")])
        self.assertIsNone(row["estimate"])
        self.cheapest.assert_not_called()

    def test_exact_printing_queue_context_retains_requested_finish_and_remaining_states(self):
        self.queue_read.return_value = [{"name": GROWTH, "quantity": 3, "state": "waiting_for_reprint", "for": "Specific printing",
                                         "printing": "exact", "set": "war", "collector_number": "162", "finish": "nonfoil",
                                         "listed_aud": "0.75", "listed_at": "Exact shop", "checked": "2026-10-26"},
                                        {"name": GROWTH, "quantity": 1, "state": "deferred", "for": "Special copy",
                                         "printing": "exact", "set": "war", "collector_number": "162", "finish": "foil"}]
        row = self.one(variant_buying.build(self.summary()))
        self.assertEqual(row["queued"], [{"quantity": 3, "state": "waiting_for_reprint", "purpose": "Specific printing",
                                          "printing": "exact", "set": "war", "collector_number": "162", "finish": "nonfoil"},
                                         {"quantity": 1, "state": "deferred", "purpose": "Special copy",
                                          "printing": "exact", "set": "war", "collector_number": "162", "finish": "foil"}])
        self.assertEqual(row["references"], [{"aud": 0.75, "shop": "Exact shop", "checked": "2026-10-26",
                                             "printing": "exact", "set": "war", "collector_number": "162", "finish": "nonfoil"}])

    def test_positive_token_classification_excludes_a_same_name_queue_row(self):
        self.queue_read.return_value = [{"name": GROWTH, "quantity": 5, "state": "ready", "printing": "exact",
                                         "set": "ttsr", "collector_number": "12", "finish": "nonfoil"}]
        with mock.patch.object(variant_buying.shopping_missing, "is_token", return_value=True) as classifier:
            row = self.one(variant_buying.build(self.summary()))
        classifier.assert_called_once()
        self.assertEqual((row["queued"], row["references"]), ([], []))

    def test_cached_estimate_includes_printing_and_both_dates_without_fetching_or_writing(self):
        before = deepcopy(self.summary())
        with mock.patch.object(inventory, "apply", side_effect=AssertionError("No inventory write")) as write, \
                mock.patch.object(cards, "_write_json", side_effect=AssertionError("No cache refresh")) as refresh:
            result = variant_buying.build(before)
        self.assertEqual(self.one(result)["estimate"], {"aud": 0.5, "set": "war", "collector_number": "162", "finish": "nonfoil",
                                                       "price_date": "2026-10-28", "rate": 2.0, "rate_date": "2026-10-27"})
        self.assertEqual(before, self.summary())
        write.assert_not_called()
        refresh.assert_not_called()

    def test_absent_or_invalid_cached_rates_leave_estimates_explicitly_absent(self):
        for rate in (None, {"rate": True, "date": "2026-10-27"}, {"rate": float("nan"), "date": "2026-10-27"},
                     {"rate": 2, "date": "2026-99-99"}):
            with self.subTest(rate=rate):
                self.cached_rate.return_value = rate
                self.assertIsNone(self.one(variant_buying.build(self.summary()))["estimate"])
        self.cheapest.assert_not_called()

    def test_unusable_reference_dates_or_nonfinite_conversion_do_not_replace_an_estimate(self):
        shared = {"name": GROWTH, "quantity": 1, "state": "ready", "printing": "any", "finish": "nonfoil",
                  "listed_at": "Fixture shop", "checked": "2026-10-26"}
        self.queue_read.return_value = [dict(shared, listed_aud="1e10000"),
                                        dict(shared, listed_aud="0.25", checked="2026-99-99")]
        result = variant_buying.build(self.summary())
        self.assertEqual(self.one(result)["references"], [])
        self.assertEqual(self.one(result)["estimate"]["aud"], 0.5)
        json.dumps(result, allow_nan=False)

    def test_output_limits_report_omitted_rows_queue_context_and_distinct_references(self):
        variant = support.SWAPPED.replace("2 Overrun", "1 Overrun").replace("6 Forest", "1 Lightning Bolt\n6 Forest")
        shared = {"name": GROWTH, "quantity": 1, "state": "ready", "printing": "any", "finish": "nonfoil",
                  "listed_aud": "0.25", "checked": "2026-10-26"}
        self.queue_read.return_value = [dict(shared, listed_at=f"Fixture shop {number}") for number in range(3)]
        with mock.patch.multiple(variant_buying, MAX_ROWS=1, MAX_QUEUE=1, MAX_REFERENCES=1):
            result = variant_buying.build(self.summary(variant))
        self.assertEqual([row["name"] for row in result["rows"]], [GROWTH])
        self.assertEqual((len(self.one(result)["queued"]), len(self.one(result)["references"])), (1, 1))
        self.assertEqual(result["omitted"], {"rows": 1, "queued": 2, "references": 2, "basic_added": 0})

    def test_overlong_otherwise_applicable_references_are_counted_as_omitted(self):
        shared = {"name": GROWTH, "quantity": 1, "state": "ready", "printing": "any", "finish": "nonfoil",
                  "listed_aud": "0.25", "listed_at": "Fixture shop", "checked": "2026-10-26"}
        self.queue_read.return_value = [dict(shared, listed_at="S" * (variant_buying.MAX_TEXT + 1)),
                                        dict(shared, listed_aud="0." + "0" * variant_buying.MAX_TEXT)]
        result = variant_buying.build(self.summary())
        row = self.one(result)
        self.assertEqual(row["references"], [])
        self.assertEqual(len(row["queued"]), 2)
        self.assertEqual((result["omitted"]["references"], result["omitted"]["queued"]), (2, 0))
        self.assertEqual(row["estimate"]["aud"], 0.5)

    def test_basic_land_output_limit_is_explicit(self):
        variant = support.test_forge.GREEN.replace("1 Fiery Annihilation\n", "").replace("2 Overrun", "1 Overrun")
        variant = variant.replace("6 Forest", "7 Forest\n1 Mountain")
        with mock.patch.object(variant_buying, "MAX_ROWS", 1):
            result = variant_buying.build(self.summary(variant))
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["basic_added"], [{"name": "Forest", "added": 1}])
        self.assertEqual(result["omitted"]["basic_added"], 1)

    def test_unreadable_queue_does_not_hide_known_availability_or_reuse_partial_references(self):
        self.queue_read.return_value = [{"name": GROWTH, "quantity": 1, "state": "ready", "printing": "any",
                                         "listed_aud": "0.25", "listed_at": "Fixture shop", "checked": "2026-10-26"},
                                        {"name": GROWTH}]
        result = variant_buying.build(self.summary())
        self.assertFalse(result["ready"])
        self.assertTrue(result["availability_ready"])
        self.assertFalse(result["queue_ready"])
        self.assertTrue(result["queue_problem"])
        self.assertEqual((self.one(result)["queued"], self.one(result)["references"]), ([], []))
        self.assertEqual((result["omitted"]["queued"], result["omitted"]["references"]), (0, 0))

    def test_variant_view_keeps_buying_absent_for_viewers_without_home_records(self):
        saved, seen = self.saved_view()
        with mock.patch.object(support.real_forge.variants, "view", return_value=saved), \
                mock.patch.object(guard, "sees_home_records", return_value=False), \
                mock.patch.object(variant_buying, "build", side_effect=AssertionError("No buying reader")) as buying:
            result = variant_page._view(support.real_forge, saved["test"]["test"], seen)
        self.assertNotIn("buying", result)
        self.assertEqual(result["words"], "Fixture verdict")
        buying.assert_not_called()

    def test_finished_home_view_enriches_the_visible_saved_summary_without_changing_its_verdict(self):
        saved, seen = self.saved_view()
        original = deepcopy(saved)
        with mock.patch.object(support.real_forge.variants, "view", return_value=saved), \
                mock.patch.object(variant_buying, "build", wraps=variant_buying.build) as buying:
            result = variant_page._view(support.real_forge, saved["test"]["test"], seen)
        buying.assert_called_once_with(result["test"])
        self.assertEqual((result["status"], result["verdict"], result["words"]), ("done", "better", "Fixture verdict"))
        self.assertTrue(result["buying"]["ready"])
        self.assertEqual(self.one(result["buying"])["added"], 1)
        self.assertEqual(saved, original)

    def test_running_or_queued_views_never_build_optional_buying_evidence(self):
        saved, seen = self.saved_view()
        job = SimpleNamespace(fn=object())
        coordinator = api.forge_runs.COORD_JOBS
        for status in (support.jobs.QUEUED, support.jobs.RUNNING):
            with self.subTest(status=status), \
                    mock.patch.object(support.real_forge.variants, "view", return_value=saved), \
                    mock.patch.object(coordinator, "get", return_value=job), \
                    mock.patch.object(coordinator, "snapshot", return_value={"status": status}), \
                    mock.patch.object(variant_page, "_job_json", return_value={"pairs": {}}), \
                    mock.patch.object(variant_buying, "build", side_effect=AssertionError("No active-job enrichment")) as buying:
                result = variant_page._view(support.real_forge, saved["test"]["test"], seen)
                self.assertEqual(result["status"], status)
                self.assertNotIn("buying", result)
                buying.assert_not_called()

    def test_finished_nonhome_view_keeps_buying_absent_even_for_a_home_viewer(self):
        saved, seen = self.saved_view()
        saved["test"]["base"]["id"] = "user2/casual/green-test"
        with mock.patch.object(support.real_forge.variants, "view", return_value=saved), \
                mock.patch.object(guard, "sees_home_records", return_value=True), \
                mock.patch.object(variant_buying, "build", side_effect=AssertionError("No other-space enrichment")) as buying:
            result = variant_page._view(support.real_forge, saved["test"]["test"], seen)
        self.assertEqual((result["status"], result["words"]), ("done", "Fixture verdict"))
        self.assertNotIn("buying", result)
        buying.assert_not_called()

    def test_failed_optional_enrichment_keeps_the_finished_saved_verdict(self):
        saved, seen = self.saved_view()
        with mock.patch.object(support.real_forge.variants, "view", return_value=saved), \
                mock.patch.object(variant_buying, "build", side_effect=RuntimeError("Internal fixture detail")):
            result = variant_page._view(support.real_forge, saved["test"]["test"], seen)
        self.assertEqual((result["status"], result["verdict"], result["words"]), ("done", "better", "Fixture verdict"))
        self.assertFalse(result["buying"]["ready"])
        self.assertEqual(result["buying"]["rows"], [])
        self.assertNotIn("Internal fixture detail", json.dumps(result))
