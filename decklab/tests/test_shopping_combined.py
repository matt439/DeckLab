"""Shopping's decks built together (E5-S28): the combined shortfall over real fixture pool reads,
the read guard and the HTTP route. Run with python scripts/test_fixtures.py decklab.tests.test_shopping_combined.

The fixture (test_shopping_missing.missing_tree): 3 Llanowar Elves owned and 1 on the way, of which
the intact Beginner Box holds 2 and the built Holding deck 1; 1 Elvish Mystic owned and 1 on the way;
1 Murderous Rider. Alpha (building) wants 5 Elves, 3 Mystic and 3 Rider; Beta (idea) 3 Elves,
1 Mystic and 1 Rider; Holding (built) 1 Elves."""
import contextlib
import http.client
import json
import threading
import unittest
import urllib.parse
from unittest import mock

from decklab.lib import access, inventory, pool, server_http
from decklab.lib.api import shopping_combined
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.tests.test_shopping_missing import RIDER, _Fixture


class _Combined(_Fixture):
    def combined(self, *ids, profile="matt"):
        with access.using({"profile": profile, "email": "", "remote": True}):
            return shopping_combined.combined_view(",".join(ids))

    def refused(self, *ids, profile="matt", value=None):
        with self.assertRaises(ApiError) as caught, access.using({"profile": profile, "email": "", "remote": True}):
            shopping_combined.combined_view(",".join(ids) if value is None else value)
        return caught.exception


def by_name(answer):
    return {row["name"]: row for row in answer["rows"]}


class CombinedShortfallTests(_Combined, unittest.TestCase):
    def test_competing_decks_count_each_free_copy_once_and_exceed_the_single_deck_sum(self):
        before = self.backend.load()
        with mock.patch.object(inventory, "apply", side_effect=AssertionError("read only")):
            answer = self.combined("casual/alpha", "casual/beta")
        self.assertTrue(answer["ready"], answer)
        rows = by_name(answer)
        self.assertEqual({name: (row["need"], row["available"], row["missing"], row["missing_alone"])
                          for name, row in rows.items()},
                         {"Llanowar Elves": (8, 1, 7, 6), "Elvish Mystic": (4, 2, 2, 1), RIDER: (4, 1, 3, 2)})
        self.assertEqual(answer["totals"], {"cards": 3, "copies": 12, "copies_alone": 9, "on_the_way": 2})
        self.assertEqual([(deck["id"], deck["missing_alone"]) for deck in answer["decks"]],
                         [("casual/alpha", 7), ("casual/beta", 2)])
        # Each card names the chosen decks that share it, with each deck's need and own shortfall.
        self.assertEqual([(deck["id"], deck["need"], deck["missing_alone"]) for deck in rows[RIDER]["decks"]],
                         [("casual/alpha", 3, 2), ("casual/beta", 1, 0)])
        self.assertEqual(rows["Llanowar Elves"]["card"]["name"], "Llanowar Elves")
        self.assertEqual(files.render(self.backend.load(), decks=True), files.render(before, decks=True))

    def test_copies_on_the_way_count_as_available_and_are_labelled(self):
        rows = by_name(self.combined("casual/alpha", "casual/beta"))
        self.assertEqual(rows["Elvish Mystic"]["on_the_way"], [{"source": "order incoming", "copies": 1}])
        self.assertEqual(rows["Llanowar Elves"]["on_the_way"], [{"source": "order incoming", "copies": 1}])
        self.assertEqual(rows[RIDER]["on_the_way"], [])

    def test_other_built_decks_and_intact_products_hold_their_copies(self):
        rows = by_name(self.combined("casual/alpha", "casual/beta"))
        self.assertEqual(sorted((held["title"], held["copies"]) for held in rows["Llanowar Elves"]["held_elsewhere"]),
                         [("Cats (Foundations Beginner Box)", 1), ("Elves (Foundations Beginner Box)", 1), ("Holding", 1)])

    def test_a_chosen_built_deck_counts_its_own_copies(self):
        answer = self.combined("casual/alpha", "casual/holding")
        rows = by_name(answer)
        # Holding's one Elves is its own: 4 owned less the product's 2 leaves 2 for 6 wanted. Alone,
        # each deck is counted against that same pool, so Alpha alone misses 3 and Holding none:
        # together it's one more, the copy Holding keeps.
        elves = rows["Llanowar Elves"]
        self.assertEqual((elves["need"], elves["available"], elves["missing"], elves["missing_alone"]), (6, 2, 4, 3))
        self.assertEqual([(deck["id"], deck["missing_alone"]) for deck in elves["decks"]],
                         [("casual/alpha", 3), ("casual/holding", 0)])
        self.assertNotIn("Holding", [held["title"] for held in elves["held_elsewhere"]])
        self.assertEqual((answer["totals"]["copies"], answer["totals"]["copies_alone"]), (7, 6))

    def test_the_combined_total_is_never_below_the_single_deck_sum(self):
        # Built Owned-only, its Play-now list holds the only Rider, which its Planned list doesn't
        # want; together with Beta, which wants a Rider, that copy is free for Beta. Both want Mystic.
        self.case.deck("owned-only", "Owned Only", "built", "Deck\n2 Elvish Mystic\n",
                       owned=f"Deck\n1 {RIDER}\n", built_version="owned-only")
        answer = self.combined("casual/owned-only", "casual/beta")
        self.assertTrue(answer["ready"], answer)
        rows = by_name(answer)
        self.assertNotIn(RIDER, rows)
        self.assertEqual({name: (row["missing"], row["missing_alone"]) for name, row in rows.items()},
                         {"Llanowar Elves": (2, 2), "Elvish Mystic": (1, 0)})
        self.assertEqual([(deck["id"], deck["missing_alone"]) for deck in answer["decks"]],
                         [("casual/owned-only", 0), ("casual/beta", 2)])
        self.assertEqual((answer["totals"]["copies"], answer["totals"]["copies_alone"]), (3, 2))

    def test_basic_lands_are_left_out_and_the_pool_is_read_once_without_prices(self):
        with mock.patch.object(pool, "load_pool", wraps=pool.load_pool) as load, \
                mock.patch.object(pool.cards, "price_aud", side_effect=AssertionError("no prices")):
            answer = self.combined("casual/alpha", "casual/beta", "commander/gamma")
        load.assert_called_once()
        self.assertNotIn("Forest", by_name(answer))
        self.assertEqual(by_name(answer)["Pick Your Poison"]["decks"][0]["id"], "commander/gamma")

    def test_an_unknown_card_makes_the_whole_answer_unready(self):
        real = pool.compare

        def unknown(sections, supply, exclude=(), prices=True, listed=False):
            result = real(sections, supply, exclude, prices, listed)
            alone = not any(isinstance(key, tuple) for key in sections)
            if alone and any(getattr(line, "name", None) == RIDER for lines in sections.values() for line in lines):
                result["unresolved"] = [("Not A Card", "decklist")]
            return result
        with mock.patch.object(pool, "compare", side_effect=unknown):
            answer = self.combined("casual/alpha", "casual/beta")
        self.assertFalse(answer["ready"])
        self.assertEqual(answer["rows"], [])
        self.assertIn("Not A Card", json.dumps(answer["errors"]))

    def test_choice_validation(self):
        for value in ("", "casual/alpha", "casual/alpha,", ",".join(["casual/alpha"] * 13)):
            with self.subTest(value=value):
                self.assertEqual(self.refused(value=value).status, 400)
        self.assertEqual(self.refused("casual/alpha", "casual/alpha").status, 400)
        self.assertEqual(self.refused("casual/alpha", "product/fdn-beginner-box/elves").status, 400)
        missing = self.refused("casual/alpha", "casual/nothing-here")
        self.assertEqual((missing.status, str(missing)), (404, "No deck 'casual/nothing-here'"))


class CombinedPermissionTests(_Combined, unittest.TestCase):
    def test_both_home_profiles_read_the_same_answer(self):
        self.assertEqual(self.combined("casual/alpha", "casual/beta", profile="matt"),
                         self.combined("casual/alpha", "casual/beta", profile="user1"))

    def test_a_person_space_viewer_is_refused_before_any_deck_or_inventory_read(self):
        for profile in ("user2", "user3", "user4"):
            with self.subTest(profile=profile), \
                    mock.patch.object(inventory, "current", side_effect=AssertionError("guard first")), \
                    mock.patch.object(shopping_combined, "_combined", side_effect=AssertionError("guard first")):
                self.assertEqual(self.refused("casual/alpha", "casual/beta", profile=profile).status, 403)
            with self.subTest(profile=profile, own=True), \
                    mock.patch.object(shopping_combined, "_combined", side_effect=AssertionError("guard first")):
                self.assertEqual(self.refused("casual/alpha", "user2/casual/private", profile=profile).status, 403)

    def test_a_deck_the_viewer_cannot_see_answers_as_a_missing_deck(self):
        refused = self.refused("casual/alpha", "user2/casual/private")
        self.assertEqual((refused.status, str(refused)), (404, "No deck 'user2/casual/private'"))
        self.assertNotIn("User2 secret", str(refused))


class CombinedHttpTests(_Combined, unittest.TestCase):
    def setUp(self):
        super().setUp()
        web = self.root / "web"
        web.mkdir()
        patches = contextlib.ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(mock.patch.object(server_http, "log", self.logs.append))
        patches.enter_context(mock.patch.object(server_http.visits, "recorder", return_value=mock.Mock()))
        self.httpd = server_http.make_server("127.0.0.1", 0, web_dir=web)
        self.addCleanup(self.httpd.server_close)
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.httpd.shutdown)

    def request(self, profile, query, method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        try:
            connection.request(method, "/api/shopping/combined?" + query, headers={access.VIEWER_HEADER: profile})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_get_answers_home_profiles_and_refuses_others_and_bad_queries(self):
        query = urllib.parse.urlencode({"decks": "casual/alpha,casual/beta"})
        for profile in ("matt", "user1"):
            with self.subTest(profile=profile):
                status, body = self.request(profile, query)
                self.assertEqual(status, 200, body)
                self.assertEqual(json.loads(body)["totals"]["copies"], 12)
        status, body = self.request("user2", query)
        self.assertEqual(status, 403, body)
        status, body = self.request("matt", query + "&other=1")
        self.assertEqual(status, 400, body)
        status, body = self.request("matt", query, method="POST")
        self.assertIn(status, (403, 405), body)


if __name__ == "__main__":
    unittest.main()
