"""Shopping's token add-ons beside the baskets (E5-S38): the token cards home's built decks make
but have no card for, as names to look for, home-records readers only.

Run: python scripts/test_fixtures.py decklab.tests.test_shopping_token_addons
Every deck, token list and snapshot is a fixture; nothing is written, queued or fetched.
"""
import copy
import unittest
from unittest import mock

from decklab.lib import access, inventory, shops, tokens
from decklab.lib.api import common, shop_baskets, shopping, shopping_token_addons
from decklab.tests import test_shop_baskets as basket_fixtures
from decklab.tests import test_shopping_missing as fixtures
from decklab.tests import test_tokens as token_fixtures


class BuiltGapsTests(token_fixtures.IndexTestCase):
    """tokens.built_gaps over the token tests' holders: a building deck, a built deck and an intact product."""

    def setUp(self):
        super().setUp()
        # test_tokens.HolderTests' holders.
        self.tokens_csv(token_fixtures.REAL_TOKENS)
        self.deck("queen", "Queen Deck", deck="1 Hornet Queen\n1 Gisa, the Hellraiser\n")
        self.deck("built", "Built Deck", status="built", deck="1 Fountainport\n", owned="1 Army of the Damned\n",
                  built_version="owned-only")
        self.deck("idea", "Idea Deck", status="idea", deck="1 Prideful Parent\n")
        self.write("products/test-product.csv", "deck,section,name,quantity,finish,set,collector_number\n"
                                                ",deck,\"Gisa, the Hellraiser\",1,nonfoil,potj,89s\n")
        self.write("products/status.csv", "file,status,intact,sleeves,deck_box,notes\n"
                                          "test-product.csv,owned,yes,,,\n")

    def names(self, incoming=()):
        return [(gap["name"], [deck["id"] for deck in gap["decks"]])
                for gap in tokens.built_gaps(tokens.read(), list(incoming), [])]

    def test_only_built_holders_count_and_a_deck_being_built_does_not(self):
        # The Tokens page's gaps name the building Queen Deck too; the add-ons only the intact product.
        self.assertEqual(self.names(token_fixtures.INCOMING), [("Zombie Rogue", ["product/test-product"])])
        self.deck("queen", "Queen Deck", status="built", deck="1 Hornet Queen\n1 Gisa, the Hellraiser\n")
        self.assertEqual(self.names(token_fixtures.INCOMING),
                         [("Zombie Rogue", ["casual/queen", "product/test-product"])])

    def test_a_token_on_order_is_not_listed(self):
        self.deck("built", "Built Deck", status="built", deck="1 Fountainport\n")
        on_order = {g["name"]: g["state"] for g in tokens.gaps(tokens.read(), token_fixtures.INCOMING, [])}
        self.assertEqual(on_order.get("Fish"), "incoming")
        self.assertNotIn("Fish", [name for name, _ in self.names(token_fixtures.INCOMING)])
        self.assertIn(("Fish", ["casual/built"]), self.names(()))       # with nothing on order it's wanted

    def test_a_token_only_the_opponent_gets_is_left_out_and_either_side_stays(self):
        real = tokens.cached_deck_tokens

        def sided(side):
            def patched(*args, **kwargs):
                result = real(*args, **kwargs)
                for need in result["needs"]:
                    if need["name"] == "Zombie Rogue":
                        need["side"] = side
                return result
            return patched

        with mock.patch.object(tokens, "cached_deck_tokens", sided("opponent")):
            self.assertEqual(self.names(), [])
        with mock.patch.object(tokens, "cached_deck_tokens", sided("either")):
            self.assertEqual(self.names(), [("Zombie Rogue", ["product/test-product"])])

    def test_a_deck_listed_once_and_nothing_written(self):
        before = self.inventory.load()
        gaps = tokens.built_gaps(tokens.read(), [], [])
        self.assertEqual(set(gaps[0]), {"key", "name", "kind", "decks"})
        self.assertEqual(gaps[0]["kind"], "token")
        self.assertEqual(self.inventory.load(), before)

    def test_without_the_card_index_it_raises_as_the_reader_does(self):
        with mock.patch.object(tokens.cards, "_index", None), \
                mock.patch.object(tokens.cards, "INDEX_FILE", self.root / "missing.json.gz"):
            with self.assertRaises(RuntimeError):
                tokens.built_gaps(tokens.read(), [], [])


class SummariseTests(unittest.TestCase):
    def test_names_merge_decks_count_once_and_the_most_wanted_come_first(self):
        gaps = [{"key": "a", "name": "Treasure", "kind": "token", "decks": [{"id": "casual/a", "title": "A"}]},
                {"key": "b", "name": "Beast", "kind": "token",
                 "decks": [{"id": "casual/a", "title": "A"}, {"id": "casual/b", "title": "B"}]},
                {"key": "c", "name": "treasure", "kind": "token",
                 "decks": [{"id": "casual/a", "title": "A"}, {"id": "product/x", "title": "X"}]},
                {"key": "d", "name": "The Monarch", "kind": "reminder", "decks": [{"id": "casual/c", "title": "C"}]},
                {"key": "e", "name": "  ", "kind": "token", "decks": [{"id": "casual/c", "title": "C"}]},
                {"key": "f", "name": "Nobody", "kind": "token", "decks": []}]
        before = copy.deepcopy(gaps)
        self.assertEqual(shopping_token_addons.summarise(gaps), [
            {"name": "Beast", "kind": "token", "decks": 2},
            {"name": "Treasure", "kind": "token", "decks": 2},
            {"name": "The Monarch", "kind": "reminder", "decks": 1}])
        self.assertEqual(gaps, before)

    def test_no_deck_id_or_title_is_passed_on(self):
        out = shopping_token_addons.summarise([{"name": "Clue", "kind": "token",
                                                "decks": [{"id": "casual/secret", "title": "Secret Deck"}]}])
        self.assertNotIn("Secret", repr(out))
        self.assertNotIn("casual/secret", repr(out))

    def test_empty(self):
        self.assertEqual(shopping_token_addons.summarise(None), [])
        self.assertEqual(shopping_token_addons.summarise([]), [])


class EnrichTests(unittest.TestCase):
    LIST = [{"name": "Treasure", "kind": "token", "decks": 2}]

    def setUp(self):
        self.logs = []
        patcher = mock.patch.object(common, "_log", self.logs.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def enrich(self, answer, *, sees=True, ready=True, gather=None):
        with mock.patch.object(shopping_token_addons.guard, "sees_home_records", return_value=sees), \
                mock.patch.object(shopping_token_addons, "gather", gather or (lambda: list(self.LIST))) as called:
            return shopping_token_addons.enrich(answer, cards_ready=ready), called

    def test_beside_baskets_for_a_home_records_reader(self):
        answer, _ = self.enrich({"baskets": {"shops": []}})
        self.assertEqual(answer["token_addons"], self.LIST)

    def test_left_out_without_baskets_card_data_or_home_records(self):
        for answer, sees, ready in (({}, True, True), ({"baskets": {}}, False, True), ({"baskets": {}}, True, False)):
            with self.subTest(answer=answer, sees=sees, ready=ready):
                gather = mock.Mock(side_effect=AssertionError("must not read the tokens"))
                result, _ = self.enrich(dict(answer), sees=sees, ready=ready, gather=gather)
                self.assertNotIn("token_addons", result)
                gather.assert_not_called()

    def test_a_failing_token_reader_leaves_the_baskets_as_they_were(self):
        for error in (RuntimeError("index loading"), ValueError("tokens.csv broken"), OSError("disk")):
            with self.subTest(error=type(error).__name__):
                answer = {"baskets": {"shops": [{"key": "mtgmate"}]}}
                before = copy.deepcopy(answer)
                result, _ = self.enrich(answer, gather=mock.Mock(side_effect=error))
                self.assertEqual(result, before)
        self.assertEqual(len(self.logs), 2)          # the index still loading isn't a fault worth logging


class ShoppingTokenAddonsTests(fixtures._Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        for owner, name in ((shops, "_fetch"), (shops, "_write"), (inventory, "apply")):
            patcher = mock.patch.object(owner, name, side_effect=AssertionError("Token add-ons only read"))
            patcher.start()
            self.addCleanup(patcher.stop)
        saved = basket_fixtures.mtgmate({"Llanowar Elves": basket_fixtures.entry(basket_fixtures.listing("0.50", 9))})
        patcher = mock.patch.object(shops, "load",
                                    side_effect=lambda adapter=None, **_: saved if adapter.key == "mtgmate" else None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_answer_carries_the_list_beside_its_baskets_and_queues_nothing(self):
        before = self.backend.load()
        listed = [{"name": "Treasure", "kind": "token", "decks": 1}]
        with mock.patch.object(shopping_token_addons, "gather", return_value=listed):
            answer = self.overview()
        self.assertIn("baskets", answer)
        self.assertEqual(answer["token_addons"], listed)
        self.assertNotIn("Treasure", [row["name"] for row in answer["to_buy"]])
        for basket in answer["baskets"]["shops"]:
            self.assertNotIn("Treasure", [row["name"] for key in ("rows", "add_ons") for row in basket[key]])
        self.assertEqual(self.backend.load(), before)

    def test_the_real_reader_answers_a_list_from_the_fixture_inventory(self):
        answer = self.overview()
        self.assertIsInstance(answer["token_addons"], list)
        for item in answer["token_addons"]:
            self.assertEqual(set(item), {"name", "kind", "decks"})

    def test_a_failing_token_reader_still_answers_the_baskets(self):
        with mock.patch.object(tokens, "built_gaps", side_effect=ValueError("broken")):
            answer = self.overview()
        self.assertIn("baskets", answer)
        self.assertNotIn("token_addons", answer)

    def test_without_baskets_nothing_is_worked_out(self):
        with mock.patch.object(shops, "load", return_value=None), \
                mock.patch.object(shopping_token_addons, "gather", side_effect=AssertionError("no baskets")):
            answer = self.overview()
        self.assertNotIn("token_addons", answer)

    def test_viewers_outside_home_records_get_nothing(self):
        for identity in ({"profile": "user2", "email": "", "remote": True},
                         {"profile": None, "email": "", "remote": False}):
            with self.subTest(identity=identity), access.using(identity), \
                    mock.patch.object(shopping_token_addons, "gather", side_effect=AssertionError("private")) as gather, \
                    mock.patch.object(shop_baskets, "build", side_effect=AssertionError("private")):
                with self.assertRaises(common.ApiError) as error:
                    shopping.shopping_overview()
                self.assertEqual(error.exception.status, 403)
                gather.assert_not_called()


if __name__ == "__main__":
    unittest.main()
