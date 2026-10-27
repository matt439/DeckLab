"""Packing's intact-product links require same-snapshot source evidence; no real data changes."""
from collections import Counter
import copy
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest import mock

from decklab.lib import decks, inventory, pool
from decklab.lib.api import assembly, assembly_products, guard
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401
from decklab.tests.test_product_storage import _ProductFixture, STEM as STORAGE_STEM


ELF = "Llanowar Elves"
STEM = "fixture-precon"
ROUTE = f"product/{STEM}"


class AssemblyProductSourcesTests(PreparationCase):
    def setUp(self):
        super().setUp()
        self.cards_csv("collection.csv", (ELF, "fdn", "227", "nonfoil", 2),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 1))
        self.product(f"{STEM}.csv", ("deck", ELF, 2), ("deck", "Forest", 20), column="section")
        self.status((f"{STEM}.csv", "owned", "yes"))
        self.deck("recipient", "Recipient", "building", f"Deck\n2 {ELF}\n20 Forest\n")

    def plan(self):
        return self.preview(("recipient", "target"))

    def source(self, result):
        row = next(row for row in result["rows"] if row["name"] == ELF)
        return row["held_elsewhere"][0]

    def test_owned_intact_product_has_an_actual_readable_route_without_changing_allocation(self):
        before = files.render(inventory.current())
        plan = self.plan()
        holder = self.source(plan)
        self.assertEqual(holder["intact_product"],
                         {"id": STEM, "title": "Fixture Precon", "deck_id": ROUTE})
        self.assertEqual((holder["id"], holder["quantity"]), (ROUTE, 2))
        self.assertEqual(decks.find_summary(holder["intact_product"]["deck_id"])["versions"], ["target"])
        self.assertEqual(plan["totals"]["missing"], 2)
        self.assertEqual(plan["totals"]["transfers"], 0)
        self.assertFalse(plan["ready"])
        self.assertEqual(files.render(inventory.current()), before)
        with mock.patch.object(assembly_products, "annotate", side_effect=lambda plan, *_: plan):
            original = self.plan()
        del holder["intact_product"]
        self.assertEqual(plan, original)

    def test_multi_deck_product_links_each_real_subdeck_instead_of_a_nonexistent_root(self):
        self.product(f"{STEM}.csv", ("First Deck", ELF, 2), ("Second Deck", "Elvish Mystic", 1))
        self.deck("recipient", "Recipient", "building", f"Deck\n2 {ELF}\n1 Elvish Mystic\n")
        plan = self.plan()
        actual = {item["id"] for item in decks._product_decks()}
        self.assertNotIn(ROUTE, actual)
        for row in plan["rows"]:
            source = row["held_elsewhere"][0]["intact_product"]
            self.assertEqual(source["id"], STEM)
            self.assertIn(source["deck_id"], actual)
            self.assertNotEqual(source["deck_id"], ROUTE)
            self.assertTrue(decks.load_deck(source["deck_id"], "target"))

    def test_direct_preview_uses_one_inventory_snapshot_for_pool_sources_and_fingerprint(self):
        with mock.patch.object(self.inventory, "load", wraps=self.inventory.load) as load:
            plan = self.plan()
        self.assertEqual(load.call_count, 1)
        self.assertIn("intact_product", self.source(plan))

    def test_id_prefixes_and_unverified_or_mismatched_holders_never_create_a_source(self):
        snapshot = inventory.current()
        for deck_id, why, quantity in ((ROUTE, "built", 2), ("product/absent", "intact product", 2),
                                       (ROUTE, "intact product", 99)):
            with self.subTest(deck_id=deck_id, why=why, quantity=quantity):
                p = SimpleNamespace(in_use=[pool.InUse(deck_id, "Fixture holder", why, Counter({ELF: quantity}))])
                plan = {"rows": [{"name": ELF, "held_elsewhere": [
                    {"id": deck_id, "title": "Fixture holder", "quantity": quantity}]}]}
                self.assertEqual(assembly_products.annotate(plan, p, snapshot), plan)

    def test_changed_ambiguous_or_unreadable_product_state_withholds_stale_source_hints(self):
        p = pool.load_pool()
        plan = {"rows": [{"name": ELF, "held_elsewhere": [{"id": ROUTE, "title": "Fixture", "quantity": 2}]}]}
        for status, intact in (("owned", "no"), ("owned", ""), ("ordered", "yes"),
                                ("preordered", "yes"), ("cancelled", "yes")):
            with self.subTest(status=status, intact=intact):
                self.status((f"{STEM}.csv", status, intact))
                self.assertEqual(assembly_products.annotate(plan, p, inventory.current()), plan)
        self.status((f"{STEM}.csv", "owned", "yes"), (f"{STEM}.csv", "owned", "yes"))
        self.assertEqual(assembly_products.annotate(plan, p, inventory.current()), plan)
        self.status((f"{STEM}.csv", "owned", "yes"))
        self.write(f"products/{STEM}.csv", "section,name\ndeck,Unreadable fixture\n")
        self.assertEqual(assembly_products.annotate(plan, p, inventory.current()), plan)

    def test_hidden_routes_and_unavailable_visibility_leave_counts_and_inputs_unchanged(self):
        snapshot, p = inventory.current(), pool.load_pool()
        plan = {"rows": [{"name": ELF, "missing": 2, "held_elsewhere": [
            {"id": ROUTE, "title": "Fixture", "quantity": 2}]}]}
        before = copy.deepcopy(plan)
        with mock.patch.object(guard, "deck_reader", return_value=lambda _: False):
            self.assertEqual(assembly_products.annotate(plan, p, snapshot), before)
        with mock.patch.object(guard, "deck_reader", side_effect=inventory.Unavailable("Fixture visibility")), \
                mock.patch.object(assembly_products.common, "_log") as logged:
            self.assertEqual(assembly_products.annotate(plan, p, snapshot), before)
            logged.assert_called_once()
        self.assertEqual(plan, before)
        bad_status = replace(snapshot, status=replace(snapshot.status, strict_error="Fixture bad status"))
        self.assertEqual(assembly_products.annotate(plan, p, bad_status), before)

    def test_ambiguous_generated_routes_or_product_relations_do_not_select_a_winner(self):
        snapshot, p = inventory.current(), pool.load_pool()
        plan = {"rows": [{"name": ELF, "held_elsewhere": [{"id": ROUTE, "title": "Fixture", "quantity": 2}]}]}
        generated = decks._product_decks()
        with mock.patch.object(decks, "_product_decks", return_value=generated + generated):
            self.assertEqual(assembly_products.annotate(plan, p, snapshot), plan)
        with mock.patch.object(decks, "_product_decks", return_value=[dict(generated[0], product="absent")]):
            self.assertEqual(assembly_products.annotate(plan, p, snapshot), plan)

    def test_missing_or_malformed_optional_relation_and_failed_diagnostic_leave_plan_unchanged(self):
        snapshot, p = inventory.current(), pool.load_pool()
        plan = {"rows": [{"name": ELF, "missing": 2, "held_elsewhere": [
            {"id": ROUTE, "title": "Fixture", "quantity": 2}]}]}
        before = copy.deepcopy(plan)
        generated = decks._product_decks()[0]
        missing_relation = dict(generated)
        del missing_relation["product"]
        for malformed in (missing_relation, dict(generated, product=[]), {},
                          dict(generated, sections=None), dict(generated, source="other.csv")):
            with self.subTest(malformed=malformed), \
                    mock.patch.object(decks, "_product_decks", return_value=[malformed]), \
                    mock.patch.object(assembly_products.common, "_log", side_effect=OSError("Fixture log failure")):
                self.assertEqual(assembly_products.annotate(plan, p, snapshot), before)
        self.assertEqual(plan, before)

    def test_optional_source_failure_and_failed_diagnostic_leave_core_preview_counts_unchanged(self):
        with mock.patch.object(assembly_products, "annotate", side_effect=lambda plan, *_: plan):
            original = self.plan()
        with mock.patch.object(assembly_products, "_sources", side_effect=TypeError("Fixture malformed relation")), \
                mock.patch.object(assembly_products.common, "_log", side_effect=OSError("Fixture log failure")):
            self.assertEqual(self.plan(), original)

    def test_other_spaces_are_refused_before_optional_product_sources_are_read(self):
        with mock.patch.object(guard, "require_sees_home_records", side_effect=ApiError(403, "Private")), \
                mock.patch.object(assembly_products, "annotate", side_effect=AssertionError("No product read")):
            with self.assertRaises(ApiError) as caught:
                self.plan()
        self.assertEqual(caught.exception.status, 403)


class AssemblyProductStorageTransitionTests(_ProductFixture, PreparationCase):
    def packing_plan(self):
        return assembly.assembly_preview(json.dumps({"profile": "matt", "decks": [
            {"id": "casual/a", "version": "target"}]}))

    def test_cancelled_break_up_preview_keeps_source_until_fixture_apply_frees_actual_counts(self):
        before = inventory.current()
        original = self.packing_plan()
        source = original["rows"][0]["held_elsewhere"][0]
        self.assertEqual(source["intact_product"]["id"], STORAGE_STEM)
        self.assertEqual((original["totals"]["from_storage"], original["totals"]["missing"]), (2, 2))
        preview = self.preview()
        self.assertTrue(preview["ready"])
        # Closing/cancelling the preview makes no apply call and cannot free reserved cards.
        self.assertEqual(self.packing_plan(), original)
        self.assertEqual(files.render(inventory.current(), decks=True), files.render(before, decks=True))
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            saved = self.save(preview["preview"])
        self.assertTrue(saved["saved"])
        self.assertEqual(apply.call_count, 1)
        fresh = self.packing_plan()
        self.assertEqual((fresh["totals"]["from_storage"], fresh["totals"]["missing"],
                          fresh["totals"]["transfers"]), (4, 0, 0))
        self.assertEqual(fresh["rows"][0]["held_elsewhere"], [])
        self.assertEqual(inventory.current().collection(), before.collection())
        self.assertNotEqual(inventory.current().revision, before.revision)
