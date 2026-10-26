"""Invalid-profile diagnostics stay local; request readers retain their permitted roster."""
import json
from unittest import mock

from decklab.lib import api, config, profiles
from decklab.lib.api import settings
from decklab.tests import test_roster_privacy as roster


class ProfileDiagnosticsPrivacyTests(roster.RosterTestCase):
    def test_invalid_entries_add_no_diagnostics_or_hidden_roster_to_any_viewer(self):
        invalid = {"id": "private@example.com", "name": "Private submitted name", "space": "private-space",
                   "emails": ["private-email@example.com"]}
        contexts = [lambda: roster.home("matt"), lambda: roster.home("user1"),
                    lambda: roster.home(), lambda: roster.tunnel("user2"), lambda: roster.tunnel("user5")]
        for context in contexts:
            with context():
                expected = settings.profiles()
                with mock.patch.object(config, "load", return_value={"profiles": [*roster.PROFILES, invalid]}), \
                        mock.patch.object(profiles, "read_checked", side_effect=AssertionError("strict reader on request path")):
                    actual = settings.profiles()
                self.assertEqual(actual, expected)
                serialized = json.dumps(actual)
                for private in (*invalid.values(), "diagnostics", "invalid_id", "issues"):
                    if isinstance(private, str):
                        self.assertNotIn(private, serialized)
                self.assertNotIn("private-email@example.com", serialized)

    def test_card_status_does_not_expose_diagnostics_or_call_strict_reader(self):
        expected = api.status()
        with mock.patch.object(config, "load", return_value={"profiles": [None]}), \
                mock.patch.object(profiles, "read_checked", side_effect=AssertionError("strict reader on status path")):
            actual = api.status()
        self.assertEqual(actual, expected)
        self.assertTrue(set(actual).isdisjoint({"profiles", "profile_issues", "diagnostics", "issues"}))
