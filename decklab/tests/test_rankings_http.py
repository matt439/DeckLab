"""Rankings routing over a temporary local server; no real Forge or saved results."""
from unittest import mock

from decklab.lib.api import rankings
from decklab.lib.api.common import ApiError
from decklab.tests import test_server as support


class RankingsHttpTests(support.ServerTestCase):
    def setUp(self):
        self.answer = {"format": "Constructed", "rows": [], "groups": [], "notes": [], "error": None}
        patcher = mock.patch.object(rankings, "rankings_view", return_value=self.answer)
        self.view = patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_routes_the_optional_format_without_starting_games(self):
        self.assertEqual(self.get_json("/api/rankings"), self.answer)
        self.view.assert_called_once_with()
        self.view.reset_mock()
        self.assertEqual(self.get_json("/api/rankings?format=Commander"), self.answer)
        self.view.assert_called_once_with(format="Commander")
        self.assertFalse(self.box.forge.runs)

    def test_head_uses_the_same_read_route_and_sends_no_body(self):
        code, headers, body = self.request("HEAD", "/api/rankings?format=Constructed")
        self.assertEqual(code, 200)
        self.assertEqual(body, b"")
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertGreater(int(headers["Content-Length"]), 0)
        self.view.assert_called_once_with(format="Constructed")

    def test_unknown_and_repeated_parameters_are_refused_before_aggregation(self):
        for query in ("x=1", "format=Commander&format=Constructed", "format=Commander&profile=matt"):
            with self.subTest(query=query):
                self.assertError("/api/rankings?" + query, 400)
        self.view.assert_not_called()

    def test_write_methods_are_refused_without_aggregation_or_games(self):
        for method in ("POST", "PUT", "DELETE"):
            with self.subTest(method=method):
                code, headers, _ = self.request(method, "/api/rankings", b"{}")
                self.assertEqual(code, 405)
                self.assertEqual(headers["Allow"], "GET, HEAD")
        self.view.assert_not_called()
        self.assertFalse(self.box.forge.runs)

    def test_api_failures_remain_explicit_instead_of_becoming_an_empty_ranking(self):
        for code in (400, 500, 503):
            with self.subTest(code=code):
                self.view.side_effect = ApiError(code, "Fixture rankings are unavailable")
                self.assertEqual(self.assertError("/api/rankings?format=Commander", code),
                                 "Fixture rankings are unavailable")
