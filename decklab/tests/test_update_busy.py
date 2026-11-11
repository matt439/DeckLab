"""Only bounded busy types/counts leave the synthetic restart preview; no HTTP connection opens."""
import json
from unittest import mock
import unittest

from decklab.lib import update_busy

SETTINGS = {"port": 12345, "profiles": [{"id": "matt", "name": "Matt", "plays_as": "user", "space": "home", "role": "admin"}]}


class BusyPreviewTests(unittest.TestCase):
    def read(self, value, code=200):
        conn = mock.Mock()
        conn.getresponse.return_value.status = code
        conn.getresponse.return_value.read.return_value = value if isinstance(value, bytes) else json.dumps(value).encode()
        factory = mock.Mock(return_value=conn)
        with mock.patch.object(update_busy.config, "load", return_value=SETTINGS):
            answer = update_busy.busy_work(connection=factory)
        return answer, conn, factory

    def test_existing_named_admin_preview_is_poll_marked_read_only_and_returns_no_decks_or_actors(self):
        answer, conn, factory = self.read({"busy": ["2 Forge matchups playing or waiting", "1 field run or variant test",
                                                   "1 practice-hand run", "1 simulator check playing or waiting"],
                                          "ignored_private_field": "PRIVATE_DECK_NAME"})
        self.assertEqual(answer, ["2 Forge matchups", "1 field run or variant test", "1 practice-hand run", "1 simulator check"])
        factory.assert_called_once_with("127.0.0.1", 12345, timeout=update_busy.TIMEOUT)
        args, options = conn.request.call_args
        self.assertEqual(args, ("GET", "/api/server/restart"))
        self.assertEqual(options["headers"]["X-Deck-Lab-Viewer"], "matt")
        self.assertEqual(options["headers"]["X-Deck-Lab-Poll"], "1")
        self.assertNotIn("X-Deck-Lab-Script", options["headers"])
        self.assertNotIn("PRIVATE", str(answer))
        conn.close.assert_called_once()

    def test_empty_is_confirmed_only_with_a_good_schema_and_unknown_never_relays_source_text(self):
        self.assertEqual(self.read({"busy": []})[0], [])
        for value, code in (({"busy": ["PRIVATE_DECK_NAME"]}, 200), ({}, 200), ({"busy": []}, 403),
                            (b"x" * (update_busy.MAX_BYTES + 1), 200), (b"{PRIVATE_ERROR", 200)):
            with self.subTest(code=code), self.assertRaises(update_busy.BusyUnverified) as failed:
                self.read(value, code)
            self.assertNotIn("PRIVATE", str(failed.exception))

    def test_no_usable_home_admin_never_opens_a_connection(self):
        factory = mock.Mock()
        with mock.patch.object(update_busy.config, "load", return_value={"profiles": []}), \
                self.assertRaises(update_busy.BusyUnverified):
            update_busy.busy_work(connection=factory)
        factory.assert_not_called()
