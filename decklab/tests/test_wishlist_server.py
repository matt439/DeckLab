"""Wishlist routes use the existing home-network write protections, and a
wishlist is read only by its owner (the page names its viewer in
X-Deck-Lab-Viewer)."""
import json

from decklab.tests.test_server import ServerTestCase, WRITE
from decklab.tests.test_wishlists import body


VIEWER = {"X-Deck-Lab-Viewer": "user1"}


class WishlistServerTests(ServerTestCase):
    def setUp(self):
        # ServerTestCase shares one sandbox (and its in-memory store) across
        # methods; each starts with an empty list and a store that's up.
        self.box.state.down = False
        self.box.state.seed_wishlist("user1", [])

    def get_json(self, path, status=200, method="GET", body=None, headers=None):
        """A GET or HEAD as User1's page sends it (her profile chosen) unless headers are given."""
        if headers is None and method in ("GET", "HEAD"):
            headers = VIEWER
        return super().get_json(path, status, method, body, headers)

    def test_only_the_owner_reads_it(self):
        path = "/api/profiles/user1/wishlist"
        self.assertEqual(self.get_json(path)["entries"], [])
        for headers in ({"X-Deck-Lab-Viewer": "matt"}, {"X-Deck-Lab-Viewer": "user2"}, {}):
            with self.subTest(headers=headers):
                self.assertIn("private", self.assertError(path, 403, headers=headers))

    def test_get_add_remove_and_head(self):
        path = "/api/profiles/user1/wishlist"
        self.assertEqual(self.get_json(path)["entries"], [])
        answer = self.get_json(path, method="POST", body=body(set="fdn", number="227"))
        self.assertTrue(answer["saved"])
        self.assertTrue(answer["changed"])
        self.assertNotIn("commit", answer)
        self.assertEqual(answer["entries"][0]["name"], "Llanowar Elves")
        self.assertEqual(self.request("HEAD", path, headers=VIEWER)[2], b"")
        self.assertEqual(self.get_json(path, method="POST", body=body("remove"))["entries"], [])
        self.assertError(path, 400, method="POST", body=body("retry"))

    def test_write_security_profile_isolation_and_body_limits(self):
        path = "/api/profiles/user1/wishlist"
        self.assertError(path, 403, method="POST", body=body(), headers={"Content-Type": "application/json"})
        self.assertError(path, 415, method="POST", body=body(), headers={"X-Deck-Lab": "1"})
        self.assertError(path, 403, method="POST", body=body(), headers={**WRITE, "Origin": "https://elsewhere.test"})
        self.assertError(path, 403, method="POST", body=body(profile="matt"))
        self.assertError(path, 413, method="POST", body=b" " * 4097)
        self.assertEqual(self.get_json(path)["entries"], [])

    def test_route_methods_queries_unknown_profiles_and_traversal(self):
        path = "/api/profiles/user1/wishlist"
        self.assertError(path, 405, method="PUT", body=body())
        self.assertError(path + "?other=1", 400)
        # Someone else's list and a profile that doesn't exist answer alike (E10-S38).
        self.assertIn("private", self.assertError("/api/profiles/nobody/wishlist", 403))
        self.assertError("/api/profiles/%2e%2e%2fcasey/wishlist", 403)     # not hers, so refused first
        code, headers, _ = self.request("OPTIONS", path)
        self.assertEqual(code, 405)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_offline_get_and_remove_stay_available(self):
        path = "/api/profiles/user1/wishlist"
        self.get_json(path, method="POST", body=body())
        with self.box.no_index():
            self.assertIsNone(self.get_json(path)["entries"][0]["card"])
            self.assertEqual(self.get_json(path, method="POST", body=body("remove"))["entries"], [])

    def test_a_database_that_is_down_is_a_503_with_its_reason(self):
        path = "/api/profiles/user1/wishlist"
        self.box.state.down = True
        for method, data in (("GET", None), ("POST", body())):
            with self.subTest(method=method):
                code, _, raw = self.request(method, path, data, VIEWER if method == "GET" else None)
                self.assertEqual(code, 503)
                self.assertEqual(json.loads(raw)["reason"], "database")
