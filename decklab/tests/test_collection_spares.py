"""Spare copies protect all same-space plans while keeping physical-printing uncertainty explicit."""
from collections import Counter
import json
import unittest
from unittest import mock

from decklab.lib import access, inventory, pool, state
from decklab.lib.api import collection, collection_spares as spare
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import model, paths, rules
from decklab.tests import test_inventory_contract as contract
from decklab.tests.test_collection_edit import CollectionEditTestCase

ELVES = "Llanowar Elves"
MYSTIC = "Elvish Mystic"


def record(slug, text, *, status="idea", considering="", space="home", trial=False):
    data = (f"# PRIVATE {slug}\n- **Status:** {status}\n" + ("- **Trial:** precon Test_TST\n" if trial else "")
            + f"\n## Decklist\n\n```\nDeck\n{text}\n```\n"
            + (f"\n## Considering\n\n```\n{considering}\n```\n" if considering else ""))
    return model.Deck(space, "casual", slug, data)


def owned(name=ELVES, quantity=8, code="fdn", number="227", finish="nonfoil"):
    return model.CardRow.make(name=name, set=code, collector_number=number, finish=finish, quantity=quantity)


def world(rows=None, records=(), holders=(), *, space="home", incoming=0):
    rows = rows if rows is not None else [owned()]
    inv = model.Inventory("spare-fixture", collections={space: model.Sheet(paths.collection(space), tuple(rules.FIELDS), tuple(rows), True)},
                          decks={deck.id: deck for deck in records})
    counts = Counter()
    for row in rows:
        counts[row.name] += row.qty
    counts[ELVES] += incoming
    supply = pool.Pool(counts, {ELVES: [("incoming", incoming)]} if incoming else {}, list(holders), space=space)
    return inv, supply


def holder(quantity=2, *, recorded=True, product=False):
    key = (ELVES, "fdn", "227", "nonfoil")
    return pool.InUse("product/box/a" if product else "casual/built", "PRIVATE HOLDER", "intact product" if product else "built",
                      Counter({ELVES: quantity}), printings=Counter({key: quantity}),
                      recorded=Counter({key: quantity}) if recorded else Counter())


class SpareCountingTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(contract.fixture_world())

    def test_all_unbuilt_plans_sum_with_holders_and_considering_and_trials_are_excluded(self):
        records = [record("idea", "2 Llanowar Elves"), record("building", "1 Llanowar Elves", status="building", considering="1 Llanowar Elves"),
                   record("trial", "90 Llanowar Elves", considering="90 Llanowar Elves", trial=True)]
        inv, supply = world(records=records, holders=[holder()], incoming=200)
        result = spare.analyze(inv, supply, "home")
        self.assertTrue(result["ready"], result)
        facts = result["rows"][ELVES]
        self.assertEqual((facts["planned"], facts["considering"], facts["spare"]), (3, 1, 2))
        self.assertIn("8 owned, 2 in built decks or intact products, 3 wanted", facts["reason"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        copied = spare.export([{"name": ELVES, "spares": facts}])["text"]
        self.assertEqual(copied, "2 Llanowar Elves (FDN) 227\n")
        for forbidden in ("200", "$", "Total", "PRIVATE"):
            self.assertNotIn(forbidden, copied)

    def test_recorded_holds_are_preserved_and_unconfirmed_multiple_printings_have_no_guessed_tag(self):
        rows = [owned(quantity=4), owned(quantity=3, finish="foil")]
        inv, supply = world(rows, holders=[holder(recorded=False)])
        facts = spare.analyze(inv, supply, "home")["rows"][ELVES]
        self.assertEqual(facts["spare"], 5)
        self.assertTrue(facts["printing_uncertain"])
        self.assertEqual(facts["printings"], [])
        copied = spare.export([{"name": ELVES, "spares": facts}])["text"]
        self.assertIn("unconfirmed", copied)
        self.assertTrue(copied.endswith("5 Llanowar Elves\n"))
        self.assertNotIn("(FDN)", copied)
        confirmed = spare.analyze(inv, world(rows, holders=[holder()])[1], "home")["rows"][ELVES]
        self.assertFalse(confirmed["printing_uncertain"])
        self.assertEqual(confirmed["printings"], [{"set": "fdn", "collector_number": "227", "finish": "foil", "quantity": 3},
                                                {"set": "fdn", "collector_number": "227", "finish": "nonfoil", "quantity": 2}])

    def test_a_single_printing_is_proven_by_conservation_and_intact_product_printings_are_respected(self):
        for held in (holder(recorded=False), holder(recorded=False, product=True)):
            inv, supply = world(holders=[held])
            facts = spare.analyze(inv, supply, "home")["rows"][ELVES]
            self.assertEqual(facts["spare"], 6)
            self.assertFalse(facts["printing_uncertain"])

    def test_own_wishlist_protects_one_total_copy_without_double_counting_existing_protections(self):
        inv, supply = world()
        self.assertEqual(spare.analyze(inv, supply, "home", [{"name": ELVES}])["rows"][ELVES]["spare"], 7)
        protected, supply = world(records=[record("idea", "2 Llanowar Elves")])
        facts = spare.analyze(protected, supply, "home", [{"name": ELVES}])["rows"][ELVES]
        self.assertEqual((facts["wishlist"], facts["spare"]), (0, 6))

    def test_other_spaces_never_consume_copies_and_ordinary_basics_are_not_spare(self):
        inv, supply = world([owned(quantity=5), owned("Forest", 20, "fdn", "280")],
            records=[record("mine", "2 Llanowar Elves", space="user2"), record("other", "999 Llanowar Elves", space="home")], space="user2")
        facts = spare.analyze(inv, supply, "user2")
        self.assertEqual(set(facts["rows"]), {ELVES})
        self.assertEqual(facts["rows"][ELVES]["spare"], 3)

    def test_unreadable_or_unresolved_protected_sources_withhold_the_claim_without_contents(self):
        for deck in (model.Deck("home", "casual", "broken", error="PRIVATE ERROR"),
                     record("unknown", "1 SECRET UNKNOWN CARD")):
            inv, supply = world(records=[deck])
            result = spare.analyze(inv, supply, "home")
            self.assertFalse(result["ready"])
            self.assertEqual(result["rows"], {})
            self.assertNotIn("PRIVATE", json.dumps(result))
            self.assertNotIn("SECRET", json.dumps(result))
        for issue in ("warnings", "unresolved", "recorded"):
            inv, supply = world(holders=[holder()])
            if issue == "warnings":
                supply.warnings = ["PRIVATE ORDER ERROR"]
            elif issue == "unresolved":
                supply.unresolved = {"SECRET CARD": ["PRIVATE SOURCE"]}
            else:
                supply.in_use[0].recorded_stale = ["PRIVATE PHYSICAL ERROR"]
            result = spare.analyze(inv, supply, "home")
            self.assertFalse(result["ready"])
            self.assertNotIn("PRIVATE", json.dumps(result))

    def test_digital_only_records_do_not_become_physical_spare_offers(self):
        inv, supply = world([owned("Oracle of the Alpha", 2, "ymid", "1")])
        result = spare.analyze(inv, supply, "home")
        self.assertFalse(result["ready"])


class SpareApiTests(CollectionEditTestCase):
    def setUp(self):
        super().setUp()
        rows = [owned(), owned(MYSTIC, 3, "cmm", "648"), owned("Aerie Mystics", 1, "con", "1"), owned("Rhystic Study", 2, "wot", "25")]
        self.inv, self.supply = world(rows, [record("a", "2 Llanowar Elves", considering="1 Elvish Mystic"),
                                           record("b", "1 Llanowar Elves", status="building")], [holder()])
        self.box.state.seed_wishlist("matt", [{"name": "Rhystic Study", "set": "", "number": "", "notes": "PRIVATE MATT NOTE"}])
        self.box.state.seed_wishlist("user1", [{"name": "Aerie Mystics", "set": "", "number": "", "notes": "PRIVATE OTHER NOTE"}])

    def read(self, profile="matt", **query):
        with self.as_(profile), inventory.pinned(self.inv), mock.patch.object(pool, "load_pool", return_value=self.supply):
            return collection.collection_view(availability="spare", **query)

    def test_only_the_viewers_wishlist_is_read_and_copy_contains_all_filtered_pages_without_prices(self):
        original = self.box.state.wishlist
        with mock.patch.object(self.box.state, "wishlist", wraps=original) as wish:
            answer = self.read(limit="1")
        wish.assert_called_once_with("matt")
        self.assertEqual(answer["total"], 4)
        self.assertEqual(len(answer["cards"]), 1)
        text = answer["spares"]["copy"]["text"]
        self.assertIn("1 Aerie Mystics (CON) 1\n", text)
        self.assertIn("2 Elvish Mystic (CMM) 648\n", text)
        self.assertIn("3 Llanowar Elves (FDN) 227\n", text)
        self.assertIn("1 Rhystic Study (WOT) 25\n", text)
        for forbidden in ("PRIVATE", "$", "Total", "AUD"):
            self.assertNotIn(forbidden, text)
        self.assertNotIn("PRIVATE OTHER NOTE", json.dumps(answer))
        filtered = self.read(q="t:enchantment mv=3", color="U")
        self.assertEqual(filtered["spares"]["copy"]["text"], "1 Rhystic Study (WOT) 25\n")
        self.assertEqual(len(self.writes), 0)

    def test_public_collection_alone_cannot_expose_private_plan_counts_and_is_invariant_under_edits(self):
        self.box.state.visibility_set("home", "collection", True, state.Actor("matt", "Matt", source="cli"), "Publish synthetic collection")
        with self.as_("user2"), mock.patch.object(pool, "load_pool", side_effect=AssertionError("private pool read")), \
                mock.patch.object(self.box.state, "wishlist", side_effect=AssertionError("private wishlist read")):
            with inventory.pinned(self.inv):
                first = collection.collection_view(availability="spare")
            changed = self.inv.with_deck(record("hidden", "999 Llanowar Elves", considering="999 Rhystic Study"))
            with inventory.pinned(changed):
                second = collection.collection_view(availability="spare")
        self.assertEqual(first, second)
        self.assertFalse(first["spares"]["ready"])
        self.assertIsNone(first["spares"]["copy"])
        self.assertEqual(first["cards"], [])

    def test_hidden_inventory_has_the_existing_refusal_and_wishlist_failure_is_explicit(self):
        with self.as_("user2"):
            with self.assertRaises(ApiError) as caught:
                collection.collection_view(availability="spare")
        self.assertEqual((caught.exception.status, caught.exception.message), (403, "That collection isn't public."))
        with mock.patch.object(self.box.state, "wishlist", side_effect=RuntimeError("PRIVATE NOTE")):
            result = self.read()
        self.assertFalse(result["spares"]["ready"])
        self.assertIsNone(result["spares"]["copy"])
        self.assertNotIn("PRIVATE NOTE", json.dumps(result))

    def test_normal_filters_never_read_wishlists_or_change_collection_location_state(self):
        before = self.inv.location_sheet("home")
        with self.as_("matt"), inventory.pinned(self.inv), mock.patch.object(pool, "load_pool", return_value=self.supply), \
                mock.patch.object(self.box.state, "wishlist", side_effect=AssertionError("unneeded wishlist read")):
            free = collection.collection_view(availability="free")
        self.assertNotIn("spares", free)
        self.assertEqual(self.inv.location_sheet("home"), before)
