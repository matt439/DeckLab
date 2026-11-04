"""Queue these (E5-S28): what to buy to build chosen home decks together, put on the purchase queue
in one reviewed change. Run with python scripts/test_fixtures.py decklab.tests.test_shopping_queue_combined.

The fixture is test_shopping_missing.missing_tree: its queue already holds 7 Llanowar Elves and
10 Elvish Mystic for Alpha and a Murderous Rider for Beta (by source), so Alpha and Beta together
still want 2 Riders; Beta and Gamma together want 3 Elves, none queued for them."""
import contextlib
import http.client
import json
import threading
import unittest
from unittest import mock

from decklab.lib import access, inventory, server_http
from decklab.lib.api import shopping_combined, shopping_queue, shopping_queue_combined as sqc, shopping_queue_missing as sqm
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.tests.test_shopping_missing import RIDER, _Fixture

ALPHA_BETA = ["casual/alpha", "casual/beta"]
BETA_GAMMA = ["casual/beta", "commander/gamma"]


class _Queue(_Fixture):
    def review(self, decks, profile="matt"):
        with access.using({"profile": profile, "email": "", "remote": True}):
            return sqc.review_combined(json.dumps({"profile": profile, "decks": decks}))

    def save(self, review, decks, profile="matt", state="ready", cards=None):
        if cards is None:
            cards = [{"name": row["name"], "copies": row["copies"], "joins": row["joins"]}
                     for row in review["rows"] if row["copies"]]
        data = {"profile": profile, "action": "add_combined", "expect": review["revision"], "decks": decks,
                "state": state, "cards": cards}
        with access.using({"profile": profile, "email": "", "remote": True}):
            return shopping_queue.save_queue_state(json.dumps(data))

    def refused(self, status, call):
        before = files.render(self.backend.load())
        with self.assertRaises(ApiError) as caught:
            call()
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        self.assertEqual(files.render(self.backend.load()), before)
        return caught.exception

    def queued(self, purpose):
        return [{key: row.text(key) for key in ("name", "quantity", "state", "for", "source", "printing", "finish", "notes")}
                for row in self.backend.load().watchlist.rows if row.text("for") == purpose]


def counts(review):
    return {row["name"]: (row["missing"], row["queued"], row["copies"]) for row in review["rows"]}


class QueueTheseTests(_Queue, unittest.TestCase):
    def test_review_takes_off_what_is_queued_for_any_chosen_deck_and_writes_nothing(self):
        before = files.render(self.backend.load())
        with mock.patch.object(inventory, "apply", side_effect=AssertionError("read only")):
            review = self.review(ALPHA_BETA)
        self.assertTrue(review["ready"], review)
        self.assertEqual(review["for"], "Alpha + Beta")
        self.assertEqual(review["decks"], [{"id": "casual/alpha", "title": "Alpha"}, {"id": "casual/beta", "title": "Beta"}])
        self.assertEqual(review["states"], ["ready", "long_term"])
        self.assertEqual(review["revision"], self.backend.load().revision)
        # Alpha's queued Elves and Mystic cover the combined shortfall; Beta's Rider (by source) counts.
        self.assertEqual(counts(review), {RIDER: (3, 1, 2), "Elvish Mystic": (2, 10, 0), "Llanowar Elves": (7, 7, 0)})
        self.assertEqual(review["rows"][0]["decks"], ["Alpha", "Beta"])
        self.assertEqual(review["rows"][0]["card"]["name"], RIDER)
        self.assertEqual(review["totals"], {"cards": 1, "copies": 2})
        self.assertEqual(files.render(self.backend.load()), before)

    def test_save_adds_one_change_with_for_naming_the_decks_and_a_new_review_has_nothing_left(self):
        review = self.review(BETA_GAMMA)
        self.assertEqual(counts(review)["Llanowar Elves"], (3, 0, 3))
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            result = self.save(review, BETA_GAMMA, state="long_term")
        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[0].kind, "watchlist.add_many")
        self.assertEqual(apply.call_args.kwargs["expected_revision"], review["revision"])
        self.assertEqual((result["saved"], result["cards"], result["copies"], result["for"], result["decks"]),
                         (True, 1, 3, "Beta + Gamma", BETA_GAMMA))
        self.assertEqual(result["revision"], self.backend.load().revision)
        self.assertEqual(self.queued("Beta + Gamma"), [{
            "name": "Llanowar Elves", "quantity": "3", "state": "long_term", "for": "Beta + Gamma", "source": "",
            "printing": "any", "finish": "nonfoil", "notes": "Decks built together: casual/beta, commander/gamma"}])
        self.assertEqual(self.review(BETA_GAMMA)["totals"], {"cards": 0, "copies": 0})
        # The label doesn't depend on the order the decks were chosen in.
        self.assertEqual(self.review(list(reversed(BETA_GAMMA)))["totals"], {"cards": 0, "copies": 0})

    def test_one_decks_queue_missing_counts_a_decks_together_row_naming_it(self):
        self.save(self.review(BETA_GAMMA), BETA_GAMMA)
        with access.using({"profile": "matt", "email": "", "remote": True}):
            alone = sqm.review_missing(json.dumps({"profile": "matt", "deck": "casual/beta"}))
        elves = next(row for row in alone["rows"] if row["name"] == "Llanowar Elves")
        self.assertEqual(elves["queued"], 3)
        self.assertTrue(sqm.names_title("Beta + Gamma", "gamma"))
        self.assertFalse(sqm.names_title("Beta + Gamma", "Gam"))

    def test_an_identical_request_is_raised_and_keeps_its_state(self):
        review = self.review(BETA_GAMMA)
        self.save(review, BETA_GAMMA, state="long_term", cards=[{"name": "Llanowar Elves", "copies": 3, "joins": None}])
        # Gamma gains a card nobody queued; the existing Elves row is unchanged.
        self.case.deck("gamma", "Gamma", "idea", "Commander\n1 Ghalta, Primal Hunger\nDeck\n5 Llanowar Elves\n"
                       "1 Pick Your Poison\n", kind="commander")
        again = self.review(BETA_GAMMA)
        elves = next(row for row in again["rows"] if row["name"] == "Llanowar Elves")
        self.assertEqual((elves["queued"], elves["copies"], elves["joins"]), (3, 4, "long_term"))
        self.save(again, BETA_GAMMA, state="ready")
        self.assertEqual([(row["quantity"], row["state"]) for row in self.queued("Beta + Gamma")], [("7", "long_term")])

    def test_a_stale_or_changed_review_saves_nothing(self):
        review = self.review(ALPHA_BETA)
        with access.using({"profile": "matt", "email": "", "remote": True}):
            shopping_queue.save_queue_state(json.dumps({"profile": "matt", "action": "add", "expect": review["revision"],
                                                        "values": {"name": "Ghalta, Primal Hunger"}}))
        self.assertEqual(self.refused(409, lambda: self.save(review, ALPHA_BETA)).message, sqc.CHANGED)
        fresh = self.review(ALPHA_BETA)
        self.refused(409, lambda: self.save(fresh, ALPHA_BETA, cards=[{"name": RIDER, "copies": 3, "joins": None}]))
        self.refused(409, lambda: self.save(fresh, BETA_GAMMA))

    def test_bad_requests_are_refused(self):
        review = self.review(ALPHA_BETA)
        self.refused(400, lambda: self.save(review, ALPHA_BETA, state="deferred"))
        self.refused(400, lambda: self.save(review, "casual/alpha,casual/beta"))
        self.refused(400, lambda: self.save(review, ["casual/alpha"]))
        self.refused(400, lambda: self.save(review, ALPHA_BETA, cards=[]))
        self.refused(400, lambda: self.review(["casual/alpha", "casual/alpha"]))
        self.refused(400, lambda: self.review(["casual/alpha", "product/fdn-beginner-box/elves"]))
        self.refused(400, lambda: self.review(["casual/alpha,casual/beta"]))
        missing = self.refused(404, lambda: self.review(["casual/alpha", "user2/casual/private"]))
        self.assertNotIn("User2 secret", str(missing))

    def test_an_uncountable_set_is_not_ready_and_offers_nothing(self):
        with mock.patch.object(shopping_combined, "_combined", return_value=shopping_combined._unavailable(
                "Missing cards cannot be counted until the home card pool is complete.",
                [{"id": "casual/alpha", "title": "Alpha"}, {"id": "casual/beta", "title": "Beta"}],
                warnings=["Unknown cards in the home pool: Not A Card"])):
            review = self.review(ALPHA_BETA)
        self.assertFalse(review["ready"])
        self.assertIn("Not A Card", review["reason"])
        self.assertNotIn("rows", review)

    def test_a_person_space_viewer_is_refused_before_any_read(self):
        for profile in ("user2", "user3"):
            with self.subTest(profile=profile), \
                    mock.patch.object(shopping_combined, "_combined", side_effect=AssertionError("guard first")):
                self.refused(403, lambda: self.review(ALPHA_BETA, profile=profile))
        review = self.review(ALPHA_BETA)
        self.refused(403, lambda: self.save(review, ALPHA_BETA, profile="user2"))


class QueueTheseHttpTests(_Queue, unittest.TestCase):
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

    def post(self, profile, path, body):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        try:
            connection.request("POST", path, body=json.dumps({"profile": profile, **body}),
                               headers={access.VIEWER_HEADER: profile, "Content-Type": "application/json",
                                        server_http.WRITE_HEADER[0]: server_http.WRITE_HEADER[1]})
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b"null")
        finally:
            connection.close()

    def test_review_then_save_over_http(self):
        status, review = self.post("matt", "/api/shopping/queue/combined", {"decks": BETA_GAMMA})
        self.assertEqual(status, 200, review)
        self.assertEqual(review["totals"], {"cards": 1, "copies": 3})
        cards = [{"name": row["name"], "copies": row["copies"], "joins": row["joins"]} for row in review["rows"] if row["copies"]]
        status, saved = self.post("matt", "/api/shopping/queue", {"action": "add_combined", "expect": review["revision"],
                                                                  "decks": BETA_GAMMA, "state": "ready", "cards": cards})
        self.assertEqual(status, 200, saved)
        self.assertEqual((saved["cards"], saved["copies"]), (1, 3))
        status, body = self.post("user2", "/api/shopping/queue/combined", {"decks": BETA_GAMMA})
        self.assertEqual(status, 403, body)


if __name__ == "__main__":
    unittest.main()
