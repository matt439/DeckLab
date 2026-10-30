"""Read-only field membership API and routing fixtures; no server, Forge or real data reads."""
import contextlib
import copy
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib import feature_routes
from decklab.lib.api import field_membership as api, field_page
from decklab.lib.api.common import ApiError


class FieldMembershipApiTests(unittest.TestCase):

    def setUp(self):
        self.entry = {"id": "user2/casual/base", "version": "target", "title": "Base",
                      "kind": "casual", "card_sha": "a" * 64}
        self.summary = {"id": self.entry["id"], "space": "user2", "kind": "casual", "title": "Base"}
        self.answer = self.success()
        self.events, self.depth, self.public = [], 0, set()
        self.seen = SimpleNamespace(space="user2", everything=False,
                                    deck=lambda ident: ident.startswith("user2/"), result=mock.Mock())
        self.forge = SimpleNamespace(status=mock.Mock(side_effect=AssertionError("readiness probe")),
                    field=SimpleNamespace(run_field=mock.Mock(side_effect=AssertionError("Forge run"))))
        for target, name, value in (
            (api.guard, "require_sees_deck", mock.Mock(side_effect=self.require)),
            (api.guard, "public_deck_spaces", mock.Mock(side_effect=lambda: set(self.public))),
            (api.forge_runs, "_forge_module", mock.Mock(return_value=self.forge)),
            (api.forge_runs, "_Seen", mock.Mock(side_effect=lambda: self.seen)),
            (api, "_field_entry", mock.Mock(side_effect=self.field_entry)),
            (api, "_field_options", mock.Mock(side_effect=self.field_options)),
            (api.lists, "one_snapshot", mock.Mock(side_effect=self.snapshot)),
            (api.membership, "view", mock.Mock(side_effect=self.read)),
            (api.common, "_log", mock.Mock()),
            (api.field_choices, "editable", mock.Mock(return_value=False)),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def success(self):
        return {"deck": {key: self.entry[key] for key in ("id", "version", "card_sha")},
                "format": "Commander" if self.entry["kind"] == "commander" else "Constructed",
                "rows": [{"id": "user2/casual/other", "title": "Other", "kind": "casual", "version": "target",
                          "card_sha": "b" * 64, "in_field": True, "opponent": True, "reason": "Included by the rules."}],
                "counts": {"included": 1, "opponents": 1, "manual_excluded": 0}, "complete": True, "error": None,
                "can_edit": False}

    def require(self, deck_id):
        self.assertEqual(self.depth, 1)
        self.events.append(("guard", deck_id))

    @contextlib.contextmanager
    def snapshot(self):
        self.events.append(("enter",))
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1
            self.events.append(("exit",))

    def field_entry(self, forge, deck_id, version):
        self.assertEqual(self.depth, 1)
        self.assertIn(("guard", deck_id), self.events)
        self.assertIs(forge, self.forge)
        self.events.append(("entry", deck_id))
        return self.summary, self.entry

    def field_options(self, forge, entry, seen):
        self.assertEqual(self.depth, 1)
        self.assertIs(entry, self.entry)
        self.assertIs(seen, self.seen)
        return field_page._field_options(forge, entry, seen)

    def read(self, entry, **options):
        self.assertEqual(self.depth, 1)
        self.assertIs(entry, self.entry)
        self.assertEqual(set(options), {"space", "public", "visible", "product_notes"})
        self.assertIs(options["visible"], self.seen.deck)
        self.events.append(("read",))
        answer = copy.deepcopy(self.answer)
        answer.pop("can_edit", None)     # added by the API, never by the membership model
        return answer

    def test_raw_alias_is_guarded_before_resolution_and_every_read_uses_one_snapshot(self):
        raw = "user2/casual/former"
        self.entry["version"] = "owned"
        self.answer = self.success()
        answer = api.membership_view(raw, "owned")
        self.assertEqual(answer, self.answer)
        self.assertEqual(answer["deck"]["id"], "user2/casual/base")
        api.guard.require_sees_deck.assert_called_once_with(raw)
        api._field_entry.assert_called_once_with(self.forge, raw, "owned")
        api.lists.one_snapshot.assert_called_once_with()
        self.assertLess(self.events.index(("guard", raw)), self.events.index(("entry", raw)))
        self.assertEqual(self.depth, 0)
        self.forge.status.assert_not_called()
        self.forge.field.run_field.assert_not_called()
        json.dumps(answer, allow_nan=False)

    def test_hidden_and_missing_base_have_the_same_404_before_any_membership_work(self):
        raw = "user2/casual/not-visible"
        message = f"No deck {raw!r}"
        api.guard.require_sees_deck.side_effect = ApiError(404, message)
        with self.assertRaises(ApiError) as hidden:
            api.membership_view(raw)
        api._field_entry.assert_not_called()
        api.forge_runs._forge_module.assert_not_called()
        api.membership.view.assert_not_called()
        api.guard.require_sees_deck.side_effect = self.require
        api._field_entry.side_effect = ApiError(404, message)
        with self.assertRaises(ApiError) as missing:
            api.membership_view(raw)
        self.assertEqual((hidden.exception.status, hidden.exception.message),
                         (missing.exception.status, missing.exception.message))
        api.membership.view.assert_not_called()
        api.common._log.assert_not_called()

    def test_existing_base_id_and_version_refusals_preserve_their_normal_semantics(self):
        for status in (400, 404):
            error = ApiError(status, "Fixture base refusal", hint="Fixture normal refusal detail")
            with self.subTest(status=status):
                api._field_entry.side_effect = error
                with self.assertRaises(ApiError) as caught:
                    api.membership_view(self.entry["id"], "owned")
                self.assertIs(caught.exception, error)
                self.assertEqual(self.depth, 0)
        api.membership.view.assert_not_called()
        api.common._log.assert_not_called()

    def test_base_server_errors_keep_their_status_without_paths_parse_errors_or_extras(self):
        for status in (500, 503):
            error = ApiError(status, "private fixture path and parse details", source="private fixture source")
            with self.subTest(status=status):
                api._field_entry.side_effect = error
                with self.assertRaises(ApiError) as caught:
                    api.membership_view(self.entry["id"], "owned")
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(caught.exception.message, api.membership.UNAVAILABLE)
                self.assertEqual(caught.exception.extra, {})
                self.assertNotIn("private fixture", str(caught.exception))
                self.assertEqual(self.depth, 0)
        api.membership.view.assert_not_called()

    def test_home_member_public_base_and_script_options_follow_existing_field_rules(self):
        cases = [("casual/base", "home", False, True),
                 ("user2/casual/base", "user2", False, False),
                 ("user3/casual/base", "user2", False, False),
                 ("casual/base", "user2", False, False),
                 ("casual/base", None, True, True)]
        for base_id, viewer_space, script, product_notes in cases:
            with self.subTest(base_id=base_id, viewer_space=viewer_space, script=script):
                self.entry["id"] = base_id
                self.answer = self.success()
                self.seen = SimpleNamespace(space=viewer_space, everything=script,
                                            deck=lambda ident: True, result=mock.Mock())
                self.public = {"home", "user3"}
                answer = api.membership_view(base_id)
                options = api.membership.view.call_args.kwargs
                self.assertEqual(options["space"], "user3" if base_id.startswith("user3/") else
                                 "user2" if base_id.startswith("user2/") else "home")
                self.assertEqual(options["product_notes"], product_notes)
                self.assertTrue(options["public"]("home"))
                self.assertTrue(options["public"]("user3"))
                self.assertFalse(options["public"]("user2"))
                self.assertEqual(answer, self.answer)
                self.seen.result.assert_not_called()

    def test_new_request_freezes_current_public_rights_instead_of_reusing_an_earlier_set(self):
        self.public = {"user3"}
        api.membership_view(self.entry["id"])
        first = api.membership.view.call_args.kwargs
        self.public.clear()
        api.membership_view(self.entry["id"])
        second = api.membership.view.call_args.kwargs
        self.assertTrue(first["public"]("user3"))
        self.assertFalse(second["public"]("user3"))
        self.assertEqual(api.guard.public_deck_spaces.call_count, 2)
        self.assertEqual(api.membership.view.call_count, 2)

    def test_model_failure_is_explicit_incomplete_and_never_exposes_private_diagnostics(self):
        for error in (RuntimeError("private fixture path and title"), ValueError("private fixture path and title"),
                      ApiError(500, "private fixture path and title")):
            with self.subTest(error=error):
                api.membership.view.side_effect = error
                answer = api.membership_view(self.entry["id"])
                self.assertEqual(answer["deck"], self.answer["deck"])
                self.assertEqual(answer["format"], "Constructed")
                self.assertEqual(answer["rows"], [])
                self.assertIsNone(answer["counts"])
                self.assertFalse(answer["complete"])
                self.assertEqual(answer["error"], api.membership.UNAVAILABLE)
                self.assertNotIn("private fixture", json.dumps(answer))
                self.assertEqual(self.depth, 0)
        self.assertEqual(api.common._log.call_count, 3)
        self.forge.status.assert_not_called()
        self.forge.field.run_field.assert_not_called()

    def test_commander_success_preserves_unavailable_rows_and_explicit_exclusion_counts(self):
        self.entry.update(id="user2/commander/base", kind="commander")
        self.answer = self.success()
        self.answer["rows"] = [{"id": "user2/commander/other", "title": "Other", "kind": "commander",
                               "version": "target", "card_sha": None, "in_field": False, "opponent": False,
                               "reason": "This current list cannot be read."}]
        self.answer["counts"] = {"included": 0, "opponents": 0, "manual_excluded": 1}
        answer = api.membership_view(self.entry["id"])
        self.assertEqual(answer, self.answer)
        self.assertEqual(answer["format"], "Commander")
        self.assertTrue(answer["complete"])


    def test_can_edit_is_asked_for_the_fields_space_and_relayed_on_success_and_failure(self):
        for base_id, space in (("casual/base", "home"), ("user2/casual/base", "user2")):
            with self.subTest(base_id=base_id):
                self.entry["id"] = base_id
                self.answer = self.success()
                api.field_choices.editable.reset_mock()
                api.field_choices.editable.return_value = space == "home"
                answer = api.membership_view(base_id)
                api.field_choices.editable.assert_called_once_with(space)
                self.assertIs(answer["can_edit"], space == "home")
        api.membership.view.side_effect = RuntimeError("private fixture")
        api.field_choices.editable.return_value = True
        self.entry["id"] = "casual/base"
        answer = api.membership_view("casual/base")
        self.assertFalse(answer["complete"])
        self.assertIs(answer["can_edit"], True)


class FixtureHandler:
    """Only the dispatch protocol; no sockets, server thread, request or data store."""

    def __init__(self, command="GET"):
        self.command, self.allowed, self.names, self.sent = command, None, None, None

    def _allow(self, *methods):
        self.allowed = methods
        if self.command not in methods:
            raise ApiError(405, "Method not allowed")

    def _query(self, query, names):
        self.names = names
        if any(name not in names or len(values) != 1 for name, values in query.items()):
            raise ApiError(400, "Unexpected or repeated query")
        return {name: values[0] for name, values in query.items()}

    def _deck_id(self, params):
        return params["id"]

    def _send_json(self, status, answer):
        self.sent = status, answer

    def _write_body(self, *args):
        raise AssertionError("Read-only route must not read a write body")


class FieldMembershipRouteTests(unittest.TestCase):

    def test_get_and_head_route_only_id_and_version_without_a_server(self):
        answer = {"complete": True, "rows": []}
        for method, query, expected in (("GET", {"id": ["casual/base"]}, {"deck_id": "casual/base"}),
                                        ("HEAD", {"id": ["user2/casual/base"], "version": ["owned"]},
                                         {"deck_id": "user2/casual/base", "version": "owned"})):
            with self.subTest(method=method), mock.patch.object(api, "membership_view", return_value=answer) as read:
                handler = FixtureHandler(method)
                self.assertTrue(feature_routes.dispatch(handler, ["field", "membership"], query))
                self.assertEqual(handler.allowed, ("GET", "HEAD"))
                self.assertEqual(set(handler.names), {"id", "version"})
                self.assertEqual(handler.sent, (200, answer))
                read.assert_called_once_with(**expected)

    def test_query_expansion_or_repetition_is_refused_before_membership(self):
        for query in ({"id": ["casual/base"], "profile": ["matt"]},
                      {"id": ["casual/base", "casual/other"]},
                      {"id": ["casual/base"], "version": ["target", "owned"]}):
            with self.subTest(query=query), mock.patch.object(api, "membership_view") as read:
                with self.assertRaises(ApiError) as caught:
                    feature_routes.dispatch(FixtureHandler(), ["field", "membership"], query)
                self.assertEqual(caught.exception.status, 400)
                read.assert_not_called()

    def test_write_methods_are_refused_before_query_body_or_membership(self):
        for method in ("POST", "PUT", "DELETE"):
            with self.subTest(method=method), mock.patch.object(api, "membership_view") as read:
                handler = FixtureHandler(method)
                with self.assertRaises(ApiError) as caught:
                    feature_routes.dispatch(handler, ["field", "membership"], {"id": ["casual/base"]})
                self.assertEqual(caught.exception.status, 405)
                self.assertEqual(handler.allowed, ("GET", "HEAD"))
                self.assertIsNone(handler.names)
                self.assertIsNone(handler.sent)
                read.assert_not_called()
