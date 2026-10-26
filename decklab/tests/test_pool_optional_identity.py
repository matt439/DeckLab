"""Damaged optional Planned colours do not invalidate real physical pool or Shopping counts."""
import contextlib
import copy
import json
import unittest
from collections import Counter
from unittest import mock

from decklab.lib import access, cards, config, decks, inventory, pool
from decklab.lib.api import carddata, collection_edit as ce
from decklab.tests import test_collection_holder_colors as color_fixtures
from decklab.tests import test_collection_sources as source_fixtures
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_shopping_missing import _Fixture as MissingFixture


_MISSING = object()
_UNKNOWN = object()


def pool_facts(supply):
    """Everything physical and its provenance, excluding only the optional Planned decoration."""
    facts = copy.deepcopy(vars(supply))
    facts["in_use"] = [{key: copy.deepcopy(value) for key, value in vars(holder).items() if key != "planned_colors"}
                       for holder in supply.in_use]
    facts["free"] = pool.free_copies(supply)
    return facts


@contextlib.contextmanager
def damaged_identity(name, value):
    data = copy.deepcopy(cards._get().data)  # Only the already loaded fixture index; never a real cache read.
    exact = cards.resolve(name)
    assert exact is not None
    if value is _UNKNOWN:
        del data["cards"][exact]
    elif value is _MISSING:
        data["cards"][exact].pop("color_identity", None)
    else:
        data["cards"][exact]["color_identity"] = value
    with mock.patch.object(cards, "_index", cards._prepare(data)):
        yield


class BuiltPoolOptionalIdentityTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(config, "REPO", self.box.root))
        self.enterContext(mock.patch.object(config, "DATA", self.box.data))
        _write(self.box.root / "config.json", json.dumps(source_fixtures.ROLES))

    def as_(self, who="matt"):
        return access.using({"profile": who, "email": "", "remote": True})

    def make_owned_assembly(self, *, product=False):
        return color_fixtures.PlannedColorsPoolTests.make_owned_assembly(self, product=product)

    def test_damaged_prepared_planned_identity_keeps_real_built_counts_printings_and_named_hints(self):
        rows = self.make_owned_assembly()
        demand = decks.parse_decklist("Deck\n1 Llanowar Elves\n1 Murderous Rider\n")
        with self.as_(), inventory.pinned():
            before = pool.load_pool()
            before_missing = pool.compare(demand, before, prices=False)
        self.assertEqual(before.owned, Counter({source_fixtures.NAME: 1}))
        self.assertEqual(next(holder for holder in before.in_use if holder.id == "casual/owned-color").planned_colors, ["B"])

        for value in (_MISSING, None, "B", [["B"]], ["not a colour"]):
            with self.subTest(identity=value), damaged_identity("Murderous Rider", value), self.as_(), \
                    mock.patch.object(self.box.inventory, "load", wraps=self.box.inventory.load) as read, \
                    mock.patch.object(decks, "load_deck", side_effect=AssertionError("no target reload")), \
                    mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("no history read")), \
                    inventory.pinned():
                self.assertIsNone(carddata._require_cards())
                actual = pool.load_pool()
                self.assertEqual(pool_facts(actual), pool_facts(before))
                self.assertEqual(pool.compare(demand, actual, prices=False), before_missing)
                holder = next(item for item in actual.in_use if item.id == "casual/owned-color")
                self.assertIsNone(holder.planned_colors)
                self.assertEqual((holder.cards, holder.printings, holder.printing_version),
                                 (Counter({source_fixtures.NAME: 1}), Counter({source_fixtures.hint(): 1}), "owned"))
                with mock.patch.object(pool, "load_pool", return_value=actual):
                    storage = ce._storage("home", rows, {"rows": {}})
                self.assertEqual(storage, {"rows": {source_fixtures.KEY: {"held": 1, "guess": False, "unattributed": 0,
                    "listed_holders": [{"id": holder.id, "title": holder.title, "quantity": 1, "version": "owned"}]}}, "error": None})
                self.assertEqual(read.call_count, 1)

    def test_damaged_prepared_intact_product_identity_keeps_its_physical_counts_and_target_hint(self):
        rows = self.make_owned_assembly(product=True)
        with self.as_(), inventory.pinned():
            before = pool.load_pool()
        with damaged_identity(source_fixtures.MYSTIC, None), self.as_(), \
                mock.patch.object(self.box.inventory, "load", wraps=self.box.inventory.load) as read, inventory.pinned():
            self.assertIsNone(carddata._require_cards())
            actual = pool.load_pool()
            self.assertEqual(pool_facts(actual), pool_facts(before))
            holder = next(item for item in actual.in_use if item.id == "product/source-box")
            self.assertIsNone(holder.planned_colors)
            self.assertEqual((holder.cards, holder.printing_version), (Counter({source_fixtures.MYSTIC: 1}), "target"))
            self.assertEqual(next(item for item in actual.in_use if item.id == "casual/owned-color").planned_colors, ["B"])
            with mock.patch.object(pool, "load_pool", return_value=actual):
                storage = ce._storage("home", rows, {"rows": {}})
            self.assertEqual(storage["rows"]["cmm|648|nonfoil"]["listed_holders"],
                             [{"id": holder.id, "title": holder.title, "quantity": 1, "version": "target"}])
        self.assertEqual(read.call_count, 1)

    def test_known_planned_colourless_and_unknown_identity_are_distinct_without_changing_physical_pool(self):
        self.make_owned_assembly()
        with self.as_(), inventory.pinned():
            before = pool.load_pool()
        for value, expected in ((["B"], ["B"]), ([], []), (_UNKNOWN, None)):
            with self.subTest(identity=value), damaged_identity("Murderous Rider", value), self.as_(), inventory.pinned():
                actual = pool.load_pool()
                holder = next(item for item in actual.in_use if item.id == "casual/owned-color")
                self.assertEqual(holder.planned_colors, expected)
                self.assertEqual(pool_facts(actual), pool_facts(before))

    def test_actual_identity_lookup_programmer_faults_still_propagate_from_built_pool(self):
        self.make_owned_assembly()
        exact = cards.resolve("Murderous Rider")
        for lookup in ("resolve", "card"):
            real = getattr(cards, lookup)
            for failure in (KeyError("color_identity"), TypeError("fixture lookup fault"),
                            ValueError("fixture lookup fault"), AssertionError("fixture lookup invariant")):
                def lookup_card(name, *, error=failure, original=real):
                    if name in ("Murderous Rider", exact):
                        raise error
                    return original(name)
                with self.subTest(lookup=lookup, error=type(failure).__name__), self.as_(), \
                        mock.patch.object(cards, lookup, side_effect=lookup_card), inventory.pinned(), \
                        self.assertRaises(type(failure)) as caught:
                    pool.load_pool()
                self.assertIs(caught.exception, failure)


class ShoppingBuiltPoolIdentityTests(MissingFixture, unittest.TestCase):
    def read_with_pool(self):
        built = []
        real = pool.load_pool
        def load(*args, **kwargs):
            result = real(*args, **kwargs)
            built.append(result)
            return result
        with mock.patch.object(self.backend, "load", wraps=self.backend.load) as inventory_read, \
                mock.patch.object(pool, "load_pool", side_effect=load) as pool_read:
            answer = self.overview()
        self.assertEqual(inventory_read.call_count, 1)
        self.assertEqual(pool_read.call_count, 1)
        return answer, built[0]

    def test_real_shopping_missing_counts_stay_ready_with_damaged_built_planned_identity(self):
        before_answer, before_pool = self.read_with_pool()
        self.expected_baseline(before_answer)
        self.assertTrue(any(holder.id == "casual/holding" for holder in before_pool.in_use))
        for value in (_MISSING, None, [["G"]]):
            with self.subTest(identity=value), damaged_identity(source_fixtures.NAME, value):
                self.assertIsNone(carddata._require_cards())
                answer, supply = self.read_with_pool()
            self.assertEqual(pool_facts(supply), pool_facts(before_pool))
            self.assertIsNone(next(holder for holder in supply.in_use if holder.id == "casual/holding").planned_colors)
            result = answer["missing_cards"]
            self.assertEqual((result["ready"], result["warnings"], result["errors"]), (True, [], []))
            self.assertEqual(result["totals"], before_answer["missing_cards"]["totals"])
            self.assertEqual({row["name"]: row["missing"] for row in result["rows"]},
                             {row["name"]: row["missing"] for row in before_answer["missing_cards"]["rows"]})
            self.assertEqual(answer["queue_revision"], before_answer["queue_revision"])
            self.assertEqual([row["queue_row"] for row in answer["to_buy"]], [row["queue_row"] for row in before_answer["to_buy"]])
            for old, current in zip(before_answer["to_buy"], answer["to_buy"]):
                self.assertEqual({key: value for key, value in current.items() if key not in ("card", "deck", "reprints")},
                                 {key: value for key, value in old.items() if key not in ("card", "deck", "reprints")})
                if old["deck"] is not None:
                    self.assertEqual({key: current["deck"][key] for key in ("id", "title")},
                                     {key: old["deck"][key] for key in ("id", "title")})


if __name__ == "__main__":
    unittest.main()
