"""Conditional storage advice over disposable immutable snapshots, with no live readers."""
from collections import Counter
import json
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab.lib import cards, config, decks, inventory, pool, purchases
from decklab.lib.api import collection_edit as ce, collection_forecast as forecast
from decklab.lib.inventory import files, paths, receive, receive_partial, rules
from decklab.lib.inventory.model import CardRow, Component, Deck, Inventory, LocationRow, Order, Product, ProductItem, Sheet, StatusRow, TokenRow


BOX = {"cards": 100, "capacity": 110, "over": False, "not_counted": 0, "elsewhere": 0}


def card(name="Llanowar Elves", quantity=4, number="227", finish="nonfoil"):
    return CardRow.make(name=name, set="fdn", collector_number=number, finish=finish, quantity=quantity)


def fixture(rows=None):
    component = Component.build("cards", "cards", "arrival.csv")
    order = Order.build("arrival", seller="Fixture shop", ordered_on="2026-10-01", components=[component],
                        sources=["magic/buylists/missing-fixture.md"])
    return Inventory("fixture-r1", collections={"home": Sheet(paths.collection("home"), tuple(rules.FIELDS),
                     (card(quantity=1),), True)}, orders=(order,), payloads={component.path:
                     Sheet(component.path, tuple(rules.FIELDS), tuple(rows if rows is not None else [card()]), True)})


class CollectionForecastTests(unittest.TestCase):
    def setUp(self):
        self.sees = self.enterContext(mock.patch.object(forecast.guard, "sees_home_records", return_value=True))
        self.enterContext(mock.patch.object(cards, "resolve", side_effect=lambda name:
                                          None if name == "Unresolved fixture" else "Front // Back" if name == "Front" else name))
        self.enterContext(mock.patch.object(decks, "is_basic_land", side_effect=lambda name: name in {"Forest", "Island"}))
        self.supply = pool.Pool(Counter({"Llanowar Elves": 999}), {},
                               [SimpleNamespace(cards=Counter({"Llanowar Elves": 3}))])
        self.load = self.enterContext(mock.patch.object(pool, "load_pool", return_value=self.supply))
        self.forbidden = [self.enterContext(mock.patch.object(owner, name, side_effect=AssertionError(name)))
                          for owner, name in ((inventory, "apply"), (config, "load"),
                                              (purchases, "overview"), (purchases, "source_exists"))]

    def tearDown(self):
        for call in self.forbidden:
            call.assert_not_called()

    def build(self, inv=None, box=BOX, space="home"):
        inv = inv if inv is not None else fixture()
        before = files.render(inv, decks=True)
        with inventory.pinned(inv):
            answer = forecast.build(space, [], box)
        self.assertEqual(files.render(inv, decks=True), before)
        if answer is not None:
            json.dumps(answer)
        return answer

    def product(self, inv, *, state="ordered", intact="", quantity=60, add_order=True):
        component = Component.build("kit", "product", "kit.csv")
        product = Product("kit", tuple(rules.FIELDS), (ProductItem.make(card(quantity=quantity).as_dict(), columns=rules.FIELDS),))
        status = StatusRow.make(file="kit.csv", status=state, intact=intact)
        order = Order.build("product", components=[component])
        return inv.replace(products=(product,), status=Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS), (status,), True),
                           orders=(*inv.orders, order) if add_order else inv.orders)

    def test_known_scenario_is_conditional_and_shortfall_is_not_deducted(self):
        answer = self.build()
        self.assertEqual((answer["known_loose_cards"], answer["box_candidates"], answer["cards_if_candidates_filed"]),
                         (4, 4, 104))
        self.assertEqual(answer["possible_current_holder_shortfall"], 2)  # physical1 vs held3; pool.owned999 is irrelevant
        self.assertEqual((answer["status"], answer["basis"], answer["over_if_candidates_filed"]),
                         ("ready", "known_pending_loose_cards", False))
        self.assertEqual(answer["sources"][0]["rows"][0]["disposition"], "box")

    def test_capacity_crossing_describes_only_the_known_scenario(self):
        answer = self.build(fixture([card(quantity=12)]))
        self.assertEqual(answer["cards_if_candidates_filed"], 112)
        self.assertTrue(answer["over_if_candidates_filed"])

    def test_all_basic_lands_including_foil_are_excluded(self):
        answer = self.build(fixture([card("Forest", 20, "280"), card("Island", 3, "271", "foil"), card(quantity=2)]))
        self.assertEqual((answer["known_loose_cards"], answer["basic_excluded"], answer["box_candidates"]), (25, 23, 2))
        self.assertEqual(answer["sources"][0]["known_cards"], 25)

    def test_existing_binder_location_is_a_separate_exclusion_not_a_new_assignment(self):
        inv = fixture()
        located = LocationRow.make(set="fdn", collector_number="227", finish="nonfoil", location="Binder")
        inv = inv.replace(locations={"home": Sheet(paths.locations("home"), LocationRow.COLUMNS, (located,), True)})
        answer = self.build(inv)
        self.assertEqual((answer["box_candidates"], answer["recorded_elsewhere"], answer["cards_if_candidates_filed"]), (0, 4, 100))
        self.assertEqual(answer["sources"][0]["rows"][0]["location"], "Binder")
        self.assertEqual(inv.locations_of("home"), {("fdn", "227", "nonfoil"): "Binder"})

    def test_row_location_policy_is_shared_with_current_box(self):
        for location in ("", "Row 2, B", "row3"):
            with self.subTest(location=location):
                row = LocationRow.make(set="fdn", collector_number="227", finish="nonfoil", location=location)
                inv = fixture().replace(locations={"home": Sheet(paths.locations("home"), LocationRow.COLUMNS, (row,), True)})
                self.assertEqual(self.build(inv)["box_candidates"], 4)

    def test_unknown_location_capability_or_invalid_source_never_means_no_locations(self):
        bad = LocationRow.make(set="fdn", collector_number="999", finish="nonfoil", location="Binder")
        for inv in (fixture().replace(locations_ready=False), fixture().replace(locations={"home":
                    Sheet(paths.locations("home"), LocationRow.COLUMNS, (bad,), True)}),
                    fixture().replace(locations={"home": Sheet(paths.locations("home"), exists=True, error="PRIVATE_LOCATION")})):
            with self.subTest(inv=inv.revision):
                answer = self.build(inv)
                self.assertEqual(answer["known_loose_cards"], 4)
                self.assertIsNone(answer["box_candidates"])
                self.assertIsNone(answer["cards_if_candidates_filed"])
                self.assertIn("locations_unavailable", answer["problems"])
                self.assertNotIn("PRIVATE_LOCATION", json.dumps(answer))

    def test_no_baseline_keeps_incoming_facts_without_projected_total(self):
        answer = self.build(box=None)
        self.assertEqual(answer["known_loose_cards"], 4)
        self.assertIsNone(answer["current_cards"])
        self.assertIsNone(answer["cards_if_candidates_filed"])
        self.assertIsNone(answer["over_if_candidates_filed"])
        self.assertIn("baseline_unavailable", answer["problems"])

    def test_stale_snapshot_is_explicit_and_has_no_current_fit_claim(self):
        answer = self.build(fixture().replace(stale="PRIVATE_BACKEND_DETAIL"))
        self.assertTrue(answer["stale"])
        self.assertEqual(answer["status"], "partial")
        self.assertIsNone(answer["cards_if_candidates_filed"])
        self.assertNotIn("PRIVATE_BACKEND_DETAIL", json.dumps(answer))

    def test_capped_stale_projection_keeps_both_unknown_reasons(self):
        with mock.patch.object(forecast, "MAX_ROWS", 0):
            answer = self.build(fixture().replace(stale="PRIVATE_STALE"))
        self.assertEqual(answer["status"], "unknown")
        self.assertTrue(answer["stale"])
        self.assertEqual(answer["problems"], ["work_limit", "snapshot_stale"])
        self.assertIsNone(answer["cards_if_candidates_filed"])

    def test_partial_receipt_uses_only_the_exact_current_pending_remainder(self):
        inv = fixture([card(quantity=5)])
        after, arrived, _ = receive_partial.prepare(inv, "arrival", "cards", [card(quantity=5).as_dict()],
                                                   [{"row": 1, "quantity": 2}])
        after = after.move_component("arrival", arrived.id, "received", "2026-10-15")
        answer = self.build(after)
        self.assertEqual(answer["known_loose_cards"], 3)
        self.assertEqual(answer["sources"][0]["component_id"], "cards")
        self.assertEqual(sum(row.qty for sheet in after.payloads.values() for row in sheet.rows), 5)

    def test_cancelled_and_received_components_do_not_count(self):
        for state in ("cancelled", "received"):
            with self.subTest(state=state):
                inv = fixture().move_component("arrival", "cards", state)
                answer = self.build(inv)
                self.assertEqual((answer["known_loose_cards"], answer["box_candidates"], answer["sources"]), (0, 0, []))

    def test_extra_copy_acknowledgement_does_not_remove_physical_incoming(self):
        inv = fixture()
        data = inv.orders[0].record()
        data["audit_notes"] = "Extra copies of owned printings: cards."
        self.assertEqual(self.build(inv.replace(orders=(Order("arrival.json", data),)))["known_loose_cards"], 4)

    def test_pending_product_intact_field_is_not_a_future_storage_choice(self):
        for intact in ("", "yes", "no"):
            with self.subTest(intact=intact):
                answer = self.build(self.product(fixture(), intact=intact))
                self.assertEqual(answer["pending_products"], {"count": 1, "known_reference_cards": 60, "unknown_contents": 0})
                self.assertEqual((answer["box_candidates"], answer["cards_if_candidates_filed"]), (4, 104))
                source = next(s for s in answer["sources"] if s["kind"] == "product")
                self.assertEqual((source["problem"], source["known_cards"]), ("product_choice", 60))

    def test_tokens_are_physical_quantities_but_excluded_from_playable_box_scenario(self):
        inv = fixture()
        component = Component.build("tokens", "tokens", "tokens.csv")
        sheet = Sheet(component.path, TokenRow.COLUMNS, (TokenRow.make(front="Goblin", back="Dragon", quantity=2),), True)
        inv = inv.replace(orders=(*inv.orders, Order.build("tokens", components=[component])),
                          payloads={**inv.payloads, component.path: sheet})
        answer = self.build(inv)
        self.assertEqual(answer["tokens_excluded"], {"known_cards": 2, "unknown_components": 0})
        self.assertEqual(answer["box_candidates"], 4)

    def test_bad_quantities_and_card_fields_are_unknown_sources_not_zero_counts(self):
        rows = [card(quantity=q) for q in (0, -1, "", "many", "2.5")]
        rows += [card().replace(set="bad set"), card().replace(finish="shiny"),
                 card().replace(collector_number="1" * 41), card("Unresolved fixture")]
        for row in rows:
            with self.subTest(row=row.values):
                answer = self.build(fixture([row]))
                self.assertEqual(answer["unknown_sources"], 1)
                self.assertIsNone(answer["sources"][0]["known_cards"])
                self.assertEqual(answer["sources"][0]["problem"], "invalid_cards")

    def test_dfc_front_alias_is_canonicalized_for_shortfall_and_details(self):
        self.supply.in_use = [SimpleNamespace(cards=Counter({"Front // Back": 2}))]
        answer = self.build(fixture([card("Front", 3, "99")]))
        self.assertEqual(answer["sources"][0]["rows"][0]["name"], "Front // Back")
        self.assertEqual(answer["possible_current_holder_shortfall"], 2)

    def test_same_order_repeated_path_is_ambiguous_not_deduplicated_or_doubled(self):
        inv = fixture()
        other = Component.build("second", "cards", "arrival.csv")
        order = Order.build("arrival", components=[*inv.orders[0].components, other])
        answer = self.build(inv.replace(orders=(order,)))
        self.assertEqual(answer["unknown_sources"], 1)
        self.assertIsNone(answer["box_candidates"])
        self.assertIsNone(answer["cards_if_candidates_filed"])

    def test_orphan_pending_payload_and_raw_incoming_product_status_are_unknown(self):
        inv = fixture().replace(orders=())
        answer = self.build(self.product(inv, add_order=False))
        self.assertEqual(answer["unknown_sources"], 2)
        self.assertTrue(all(s["problem"] == "missing_order" for s in answer["sources"]))
        self.assertIsNone(answer["box_candidates"])

    def test_duplicate_or_invalid_raw_status_provenance_never_disappears(self):
        inv = fixture().replace(orders=(), payloads={})
        for statuses in ((StatusRow.make(file="kit.csv", status="ordered"),) * 2,
                         (StatusRow.make(file="kit.csv", status="unknown"),),
                         (StatusRow.make(file="../kit.csv", status="ordered"),)):
            with self.subTest(statuses=statuses):
                answer = self.build(inv.replace(status=Sheet(paths.STATUS, StatusRow.COLUMNS, statuses, True)))
                self.assertGreater(answer["unknown_sources"], 0)
                self.assertIsNone(answer["cards_if_candidates_filed"])

    def test_missing_product_status_or_unreadable_content_is_explicit(self):
        inv = self.product(fixture())
        for bad in (inv.replace(status=Sheet(paths.STATUS)), inv.replace(products=(Product("kit", error="PRIVATE_PRODUCT"),))):
            answer = self.build(bad)
            self.assertEqual(answer["pending_products"]["unknown_contents"], 1)
            self.assertNotIn("PRIVATE_PRODUCT", json.dumps(answer))

    def test_received_product_with_incoming_status_is_an_unknown_graph_not_a_hidden_delivery(self):
        inv = self.product(fixture())
        inv = inv.move_component("product", "kit", "received", "2026-10-15")
        answer = self.build(inv)
        self.assertEqual(answer["pending_products"]["count"], 0)
        self.assertEqual(answer["unknown_sources"], 1)
        self.assertIsNone(answer["cards_if_candidates_filed"])
        self.assertEqual(answer["sources"][-1]["kind"], "unknown")

    def test_empty_payload_is_unknown_contents_and_not_a_confirmed_zero_delivery(self):
        answer = self.build(fixture([]))
        self.assertEqual(answer["unknown_sources"], 1)
        self.assertIsNone(answer["sources"][0]["known_cards"])

    def test_existing_printing_with_a_different_card_name_is_not_a_valid_receipt_scenario(self):
        answer = self.build(fixture([card("Elvish Mystic")]))
        self.assertEqual(answer["unknown_sources"], 1)
        self.assertEqual(answer["sources"][0]["problem"], "invalid_cards")

    def test_raw_component_cap_is_checked_before_record_validation(self):
        inv = fixture()
        data = inv.orders[0].record()
        data["components"] *= 4
        with mock.patch.object(forecast, "MAX_COMPONENTS", 3), mock.patch.object(receive, "record") as record:
            answer = self.build(inv.replace(orders=(Order("arrival.json", data),)))
        record.assert_not_called()
        self.assertEqual((answer["status"], answer["problems"]), ("unknown", ["work_limit"]))

    def test_row_and_byte_work_caps_never_return_a_complete_zero(self):
        for limit, value in (("MAX_ROWS", 0), ("MAX_BYTES", 1)):
            with self.subTest(limit=limit), mock.patch.object(forecast, limit, value):
                answer = self.build()
            self.assertEqual(answer["status"], "unknown")
            self.assertIsNone(answer["box_candidates"])

    def test_oversized_cell_is_refused_before_any_csv_renderer_allocation(self):
        inv = fixture([card().replace(notes="x" * 501)])
        with inventory.pinned(inv), mock.patch.object(forecast, "MAX_BYTES", 500), \
                mock.patch.object(files, "render_sheet", side_effect=AssertionError("must not serialize")) as render:
            answer = forecast.build("home", [], BOX)
        render.assert_not_called()
        self.assertEqual(answer["problems"], ["work_limit"])

    def test_capped_holder_input_skips_optional_pool_load_without_losing_arrival_facts(self):
        with mock.patch.object(forecast, "MAX_HOLDER_DECKS", -1):
            answer = self.build()
        self.load.assert_not_called()
        self.assertIsNone(answer["possible_current_holder_shortfall"])
        self.assertEqual((answer["box_candidates"], answer["known_loose_cards"]), (4, 4))
        self.assertIn("holder_shortfall_unknown", answer["problems"])

    def test_foreign_deck_text_is_never_read_or_supplied_to_optional_home_pool(self):
        class ForeignDeck:
            space = "user2"

            @property
            def text(self):
                raise AssertionError("foreign recipe must stay unread")

        inv = fixture().replace(decks={"user2/casual/private": ForeignDeck()})

        def home_pool(space):
            self.assertEqual(space, "home")
            self.assertEqual(dict(inventory.current().decks), {})
            return self.supply

        with inventory.pinned(inv), mock.patch.object(pool, "load_pool", side_effect=home_pool):
            answer = forecast.build("home", [], BOX)
        self.assertEqual(answer["possible_current_holder_shortfall"], 2)
        self.assertNotIn("holder_shortfall_unknown", answer["problems"])

    def test_hidden_deck_count_cannot_trip_home_holder_caps_or_change_answer(self):
        home = Deck("home", "casual", "fixture", "fixture recipe")
        inv = fixture().replace(decks={home.id: home})
        with mock.patch.object(forecast, "MAX_HOLDER_DECKS", 1):
            before = self.build(inv)
            foreign = {f"user2/casual/private-{n}": Deck("user2", "casual", f"private-{n}", "x" * 100)
                       for n in range(20)}
            after = self.build(inv.replace(decks={**inv.decks, **foreign}))
        self.assertEqual(after, before)

    def test_output_caps_keep_full_totals_and_explicit_omission_counts(self):
        inv = fixture([card(quantity=2), card("Elvish Mystic", 3, "648")])
        with mock.patch.object(forecast, "MAX_DETAILS", 1):
            answer = self.build(inv)
        self.assertEqual((answer["known_loose_cards"], answer["sources"][0]["omitted_rows"]), (5, 1))
        with mock.patch.object(forecast, "MAX_OUTPUT_SOURCES", 0):
            answer = self.build(inv)
        self.assertEqual((answer["known_loose_cards"], answer["sources"], answer["omitted_sources"]), (5, [], 1))

    def test_bad_holder_facts_leave_shortfall_unknown_without_deducting_candidates(self):
        self.supply.warnings = ["PRIVATE_DECK"]
        answer = self.build()
        self.assertIsNone(answer["possible_current_holder_shortfall"])
        self.assertEqual(answer["box_candidates"], 4)
        self.assertNotIn("PRIVATE_DECK", json.dumps(answer))

    def test_permission_gate_precedes_any_projection_snapshot_read(self):
        with mock.patch.object(inventory, "current", side_effect=AssertionError("No private snapshot")) as current:
            self.assertIsNone(forecast.build("user2", [], BOX))
            self.sees.return_value = False
            self.assertIsNone(forecast.build("home", [], BOX))
            self.sees.side_effect = RuntimeError("PRIVATE_AUTH")
            self.assertIsNone(forecast.build("home", [], BOX))
        current.assert_not_called()

    def test_snapshot_failure_is_fixed_optional_unknown(self):
        with mock.patch.object(inventory, "current", side_effect=RuntimeError("PRIVATE_DB")):
            answer = forecast.build("home", [], BOX)
        self.assertEqual(answer["problems"], ["sources_unavailable"])
        self.assertNotIn("PRIVATE_DB", json.dumps(answer))

    def test_extras_preserves_existing_storage_box_shape_and_adds_separate_sibling(self):
        with mock.patch.object(ce, "_prices", return_value={}), mock.patch.object(ce, "_storage", return_value={}), \
                mock.patch.object(forecast.places, "storage_box", return_value=BOX), \
                mock.patch.object(forecast.places, "locations", return_value={}), \
                mock.patch.object(forecast, "build", return_value={"status": "unknown"}) as build:
            answer = ce._extras("home", [])
        self.assertIs(answer["storage_box"], BOX)
        self.assertEqual(set(answer["storage_box"]), {"cards", "capacity", "over", "not_counted", "elsewhere"})
        build.assert_called_once_with("home", [], BOX)
        self.assertEqual(answer["storage_forecast"], {"status": "unknown"})
