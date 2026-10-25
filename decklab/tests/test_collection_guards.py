"""Collection reduction advice against immutable fixture snapshots and the real pool reader."""
import json
from unittest import mock

from decklab.lib import config, inventory, pool
from decklab.lib.api import collection_guards as guards
from decklab.lib.inventory import ops_collection, paths, rules
from decklab.lib.inventory.model import Deck, Sheet
from decklab.tests import test_collection_edit as collection_tests
from decklab.tests import test_pool as pool_tests
from decklab.tests.test_api import ApiTestCase, _write


def card(name="Llanowar Elves", quantity=4, set_code="fdn", number="227", finish="nonfoil", **extra):
    return {"name": name, "set": set_code, "collector_number": number, "finish": finish,
            "quantity": str(quantity), "condition": "", "language": "", "notes": "", **extra}


class ReductionGuardTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(collection_tests.ROLES))
        patcher = mock.patch.object(config, "REPO", self.box.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fixture = self.box.inventory.load()
        self.base = self.fixture.replace(decks={}, products=(), orders=(), payloads={}, collections={},
                                         status=Sheet(paths.STATUS, rules.STATUS_FIELDS, exists=True))

    def deck(self, inv, slug="held", qty=4, space="home", target=None, owned=None, built_version=None, status="built"):
        text = pool_tests.deck_md(slug.title(), status, target or f"Deck\n{qty} Llanowar Elves\n",
                                  owned=owned, built_version=built_version)
        if space != "home":
            text = text.replace("- **Played by:** either\n", "")
        deck = Deck(space, "casual", slug, text)
        return inv.replace(decks={**inv.decks, deck.id: deck})

    def change(self, before, rows, space="home"):
        return guards.reduction_warnings(before, before.with_collection(space, rows), space)

    def test_reduction_below_a_built_decks_demand_names_it(self):
        before = self.deck(self.base.with_collection("home", [card()]))
        self.assertEqual(self.change(before, [card(quantity=3)]), [{
            "name": "Llanowar Elves", "before": 4, "after": 3, "in_use": 4, "shortage": 1,
            "holders": [{"id": "casual/held", "title": "Held", "qty": 4}]}])

    def test_all_printings_and_finishes_share_the_physical_total(self):
        rows = [card(quantity=2), card(quantity=1, finish="foil"), card(quantity=2, set_code="m19", number="314")]
        before = self.deck(self.base.with_collection("home", rows))
        self.assertEqual(self.change(before, rows[1:]), [{
            "name": "Llanowar Elves", "before": 5, "after": 3, "in_use": 4, "shortage": 1,
            "holders": [{"id": "casual/held", "title": "Held", "qty": 4}]}])
        self.assertEqual(self.change(before, [card(quantity=1), *rows[1:]]), [])

    def test_renaming_the_row_removes_old_copies_even_when_quantity_increases(self):
        before = self.deck(self.base.with_collection("home", [card()]))
        renamed = card("Elvish Mystic", 8, "cmm", "648")
        [warning] = self.change(before, [renamed])
        self.assertEqual((warning["before"], warning["after"], warning["shortage"]), (4, 0, 4))

    def test_printing_finish_and_metadata_corrections_do_not_load_demand(self):
        before = self.deck(self.base.with_collection("home", [card()]))
        with mock.patch.object(pool, "load_pool", side_effect=AssertionError("no physical reduction")):
            self.assertEqual(self.change(before, [card(set_code="m19", number="314", finish="foil", notes="corrected")]), [])
            self.assertEqual(self.change(before, [card(quantity=5)]), [])

    def test_alias_correction_preserves_the_canonical_total(self):
        before = self.deck(self.base.with_collection("home", [card("Fire", 2, "apc", "128")]),
                           target="Deck\n2 Fire // Ice\n")
        self.assertEqual(self.change(before, [card("Fire // Ice", 2, "apc", "128")]), [])

    def test_an_existing_shortage_is_warned_about_when_it_grows(self):
        before = self.deck(self.base.with_collection("home", [card(quantity=2)]))
        [warning] = self.change(before, [card(quantity=1)])
        self.assertEqual((warning["before"], warning["after"], warning["shortage"]), (2, 1, 3))

    def test_sideboard_commander_and_deck_are_all_held(self):
        before = self.deck(self.base.with_collection("home", [card()]),
                           target="Commander\n1 Llanowar Elves\n\nDeck\n2 Llanowar Elves\n\nSideboard\n1 Llanowar Elves\n")
        [warning] = self.change(before, [])
        self.assertEqual((warning["in_use"], warning["shortage"]), (4, 4))

    def test_built_version_selects_the_list_that_is_held(self):
        before = self.base.with_collection("home", [card(quantity=2)])
        before = self.deck(before, target="Deck\n4 Llanowar Elves\n", owned="Deck\n1 Llanowar Elves\n",
                           built_version="owned-only")
        self.assertEqual(self.change(before, [card(quantity=1)]), [])
        [warning] = self.change(before, [])
        self.assertEqual(warning["in_use"], 1)

    def test_built_version_fallback_keeps_established_pool_behavior(self):
        before = self.deck(self.base.with_collection("home", [card(quantity=2)]),
                           target="Deck\n4 Llanowar Elves\n", owned="Deck\n1 Llanowar Elves\n")
        [warning] = self.change(before, [])
        self.assertEqual(warning["in_use"], 1)

    def test_other_spaces_and_unbuilt_decks_do_not_hold_the_spaces_copies(self):
        before = self.base.with_collection("home", [card()]).with_collection("user2", [card()])
        before = self.deck(before, "home", space="home")
        before = self.deck(before, "own", qty=2, space="user2")
        before = self.deck(before, "idea", qty=4, space="user2", status="idea")
        self.assertEqual(self.change(before, [card(quantity=2)], "user2"), [])
        [warning] = self.change(before, [], "user2")
        self.assertEqual(warning["holders"], [{"id": "user2/casual/own", "title": "Own", "qty": 2}])

    def test_owned_intact_products_count_each_physical_deck_once(self):
        product = next(p for p in self.fixture.products if p.stem == "fdn-beginner-box")
        before = self.base.replace(products=(product,)).with_status_rows([
            {"file": product.file, "status": "owned", "intact": "yes"}]).with_collection("home", [card(quantity=2)])
        [warning] = self.change(before, [card(quantity=1)])
        self.assertEqual((warning["in_use"], len(warning["holders"])), (2, 2))
        self.assertTrue(all(holder["id"].startswith("product/fdn-beginner-box/") for holder in warning["holders"]))
        for status, intact in (("owned", "no"), ("ordered", "yes")):
            loose = before.with_status_rows([{"file": product.file, "status": status, "intact": intact}])
            self.assertEqual(self.change(loose, []), [])

    def test_incoming_cards_never_cover_removed_physical_copies(self):
        _write(self.box.magic / "orders" / "incoming.csv", collection_tests.HEADER
               + "Llanowar Elves,m19,314,nonfoil,8,,,\n")
        incoming = self.box.inventory.load().payloads
        before = self.deck(self.base.replace(payloads=incoming).with_collection("home", [card()]))
        with inventory.pinned(before):
            self.assertGreater(pool.load_pool().owned["Llanowar Elves"], 4)
        [warning] = self.change(before, [])
        self.assertEqual((warning["before"], warning["after"], warning["shortage"]), (4, 0, 4))

    def test_basic_lands_are_not_allocated_even_when_special_printings_are_tracked(self):
        before = self.deck(self.base.with_collection("home", [card("Forest", 2, "fdn", "280", "foil")]),
                           target="Deck\n20 Forest\n")
        self.assertEqual(self.change(before, []), [])

    def test_pool_reads_the_supplied_snapshot_and_restores_the_callers_snapshot(self):
        before = self.deck(self.base.with_collection("home", [card()]))
        with inventory.pinned(self.base):
            [warning] = self.change(before, [])
            self.assertIs(inventory.current(), self.base)
        self.assertEqual(warning["in_use"], 4)
        self.assertEqual(ops_collection.rows_of(before.collection("home")), [card()])

    def test_unreadable_built_deck_is_unknown_demand_not_no_demand(self):
        before = self.base.with_collection("home", [card()])
        broken = Deck("home", "casual", "broken", error="C:/private/path can't be read")
        before = before.replace(decks={broken.id: broken})
        with self.assertRaises(guards.ReductionCheckError) as caught:
            self.change(before, [])
        self.assertNotIn("private", str(caught.exception))
        self.assertIn("couldn't be checked", str(caught.exception))

    def test_unresolved_held_card_is_unknown_demand(self):
        before = self.deck(self.base.with_collection("home", [card()]), target="Deck\n4 Made Up Elves\n")
        with self.assertRaises(guards.ReductionCheckError):
            self.change(before, [])

    def test_unreadable_other_space_deck_does_not_prevent_the_check(self):
        before = self.deck(self.base.with_collection("home", [card()]))
        broken = Deck("user2", "casual", "broken", error="fixture unreadable")
        before = before.replace(decks={**before.decks, broken.id: broken})
        [warning] = self.change(before, [])
        self.assertEqual(warning["in_use"], 4)

    def test_intact_product_without_deck_lists_is_unknown_demand(self):
        product = next(p for p in self.fixture.products if p.stem == "fdc-test-precon")
        product = product.__class__(product.stem, columns=("name", "quantity"), items=product.items)
        before = self.base.replace(products=(product,)).with_status_rows([
            {"file": product.file, "status": "owned", "intact": "yes"}]).with_collection("home", [card()])
        with self.assertRaises(guards.ReductionCheckError):
            self.change(before, [])

    def test_missing_intact_product_is_unknown_demand_even_with_no_product_lists(self):
        before = self.base.with_status_rows([
            {"file": "missing.csv", "status": "owned", "intact": "yes"}]).with_collection("home", [card()])
        with self.assertRaises(guards.ReductionCheckError):
            self.change(before, [])

    def test_unreadable_product_that_is_not_kept_intact_does_not_hold_cards(self):
        product = next(p for p in self.fixture.products if p.stem == "fdn-beginner-box")
        product = product.__class__(product.stem, error="fixture unreadable")
        before = self.base.replace(products=(product,)).with_status_rows([
            {"file": product.file, "status": "owned", "intact": "no"}]).with_collection("home", [card()])
        self.assertEqual(self.change(before, []), [])

    def test_unreadable_idea_list_with_known_status_does_not_hold_cards(self):
        text = pool_tests.deck_md("Idea", "idea", "Deck\n4 Llanowar Elves\n").replace("## Decklist", "## Deck list")
        deck = Deck("home", "casual", "idea", text)
        before = self.base.replace(decks={deck.id: deck}).with_collection("home", [card()])
        self.assertEqual(self.change(before, []), [])

    def test_unchanged_or_increased_totals_do_not_require_a_card_index(self):
        before = self.base.with_collection("home", [card()])
        with self.box.no_index():
            self.assertEqual(self.change(before, [card(notes="a correction")]), [])
            self.assertEqual(self.change(before, [card(quantity=5)]), [])

    def test_missing_card_index_is_an_advisory_check_error_on_reduction(self):
        before = self.deck(self.base.with_collection("home", [card()]))
        with self.box.no_index(), self.assertRaises(guards.ReductionCheckError):
            self.change(before, [])
