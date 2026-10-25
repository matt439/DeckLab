"""Read-only rankings API boundaries with isolated service and card-cache fixtures."""
import unittest
from unittest import mock

from decklab.lib.api import rankings as api
from decklab.lib.api.common import ApiError
from decklab.lib.forge import rankings as model


class RankingsApiTests(unittest.TestCase):
    def setUp(self):
        for module, name in ((api, "_require_cards"), (api.forge_runs, "_forge_module")):
            patcher = mock.patch.object(module, name)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def test_formats_reach_the_read_service_with_the_deck_visibility_policy(self):
        for format in model.FORMATS:
            with self.subTest(format=format):
                answer = {"format": format, "rows": [], "groups": [], "notes": [], "error": None}
                profile = {"id": "member", "space": "member", "role": "member", "name": "Member"}
                reader = lambda deck_id: deck_id.startswith("member/") or deck_id.startswith("casual/")
                with mock.patch.object(model, "view", return_value=answer) as read, \
                        mock.patch.object(api.guard, "viewer", return_value=profile), \
                        mock.patch.object(api.guard, "script", return_value=False), \
                        mock.patch.object(api.guard, "public_deck_spaces", return_value={"home"}), \
                        mock.patch.object(api.guard, "deck_reader", return_value=reader):
                    self.assertEqual(api.rankings_view(format), answer)
                    read.assert_called_once()
                    self.assertEqual(read.call_args.args, (format,))
                    options = read.call_args.kwargs
                    self.assertEqual(set(options), {"visible", "keep", "field_options"})
                    self.assertIs(options["visible"], reader)
                    field = options["field_options"]
                    self.assertEqual(set(field), {"space", "public", "visible", "product_notes"})
                    self.assertEqual(field["space"], "member")
                    self.assertFalse(field["product_notes"])
                    self.assertIs(field["visible"], reader)
                    self.assertTrue(field["public"]("home"))
                    self.assertFalse(field["public"]("other"))
                    own = {"seen_as": [{"id": "member/casual/own", "version": "target"}]}
                    hidden = {"seen_as": [{"id": "other/casual/private", "version": "target"}]}
                    self.assertTrue(options["keep"]({"sides": [own, own]}))
                    self.assertFalse(options["keep"]({"sides": [own, hidden]}))

    def test_bad_formats_are_refused_before_any_cache_or_service_read(self):
        with mock.patch.object(model, "view") as read:
            for format in ("", "casual", "Legacy", "commander", "../../results", None):
                with self.subTest(format=format), self.assertRaises(ApiError) as caught:
                    api.rankings_view(format)
                self.assertEqual(caught.exception.status, 400)
        self._require_cards.assert_not_called()
        self._forge_module.assert_not_called()
        read.assert_not_called()

    def test_unavailable_card_data_is_an_explicit_error_before_ranking(self):
        self._require_cards.side_effect = ApiError(503, "Fixture card data is unavailable")
        with mock.patch.object(model, "view") as read, self.assertRaises(ApiError) as caught:
            api.rankings_view()
        self.assertEqual(caught.exception.status, 503)
        read.assert_not_called()

    def test_service_failure_is_explicit_and_never_exposes_private_diagnostics(self):
        with mock.patch.object(model, "view", side_effect=RuntimeError("private-fixture-path-and-deck")), \
                mock.patch.object(api.common, "_log") as log:
            answer = api.rankings_view("Commander")
        self.assertEqual(answer["format"], "Commander")
        self.assertTrue(answer["error"])
        self.assertEqual(answer["rows"], [])
        self.assertNotIn("private-fixture", str(answer))
        log.assert_called_once()

    def test_partial_evidence_and_uncertainty_are_preserved_by_the_api(self):
        answer = {"format": "Constructed", "rows": [{"id": "casual/fixture", "rating": None,
                  "unsettled": True, "reasons": ["No current games"]}], "groups": [],
                  "notes": ["The engine cannot be confirmed"], "error": None}
        with mock.patch.object(model, "view", return_value=answer):
            self.assertEqual(api.rankings_view(), answer)
