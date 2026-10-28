"""Feature routes must reject methods even on their first disposable request."""
import builtins
import sys
import types
import unittest
from contextlib import contextmanager
from unittest import mock

from decklab.lib import feature_routes
from decklab.lib.api.common import ApiError
from decklab.tests.test_server import ServerTestCase


@contextmanager
def field_adapter(adapter):
    """Replace only this module; keep other modules loaded during dispatch."""
    absent = object()
    previous = sys.modules.get(adapter.__name__, absent)
    sys.modules[adapter.__name__] = adapter
    try:
        yield
    finally:
        if previous is absent:
            sys.modules.pop(adapter.__name__, None)
        else:
            sys.modules[adapter.__name__] = previous


class FeatureRouteImportTests(ServerTestCase):
    def test_post_only_route_methods_are_rejected_without_import_failure(self):
        original = builtins.__import__

        def unrelated_import(name, globals=None, locals=None, fromlist=(), level=0):
            if (name == "decklab.lib.api.field_membership"
                    or name == "decklab.lib.api" and "field_membership" in fromlist):
                raise AssertionError("An unrelated method refusal loaded the field adapter")
            return original(name, globals, locals, fromlist, level)

        # Remain effective even when earlier discovery preloaded the adapter.
        with mock.patch.object(builtins, "__import__", unrelated_import):
            for method in ("GET", "HEAD", "PUT", "DELETE"):
                with self.subTest(method=method):
                    response = self.request(method, "/api/shopping/check")
                    self.assertEqual(response[0], 405, "\n".join(self.log))


class DeferredFieldRouteTests(unittest.TestCase):
    def test_allowed_field_route_uses_the_adapter_with_validated_selector(self):
        adapter = types.ModuleType("decklab.lib.api.field_membership")
        adapter.membership_view = mock.Mock(return_value={"fixture": True})
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"id": "casual/former", "version": "owned"}
        handler._deck_id.return_value = "casual/current"
        with field_adapter(adapter):
            self.assertTrue(feature_routes.dispatch(handler, ["field", "membership"], {"fixture": ["query"]}))
        handler._allow.assert_called_once_with("GET", "HEAD")
        adapter.membership_view.assert_called_once_with(deck_id="casual/current", version="owned")
        handler._send_json.assert_called_once_with(200, {"fixture": True})

    def test_field_method_refusal_never_calls_its_adapter(self):
        adapter = types.ModuleType("decklab.lib.api.field_membership")
        adapter.membership_view = mock.Mock(side_effect=AssertionError("Unexpected field read"))
        handler = mock.Mock(command="PUT")
        handler._allow.side_effect = ApiError(405, "Method not allowed")
        with field_adapter(adapter), self.assertRaises(ApiError) as caught:
            feature_routes.dispatch(handler, ["field", "membership"], {})
        self.assertEqual(caught.exception.status, 405)
        adapter.membership_view.assert_not_called()
        handler._query.assert_not_called()
