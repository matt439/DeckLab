"""Reasoned game removal in disposable stores, with recorder privacy and transaction receipts."""
import copy
from contextlib import contextmanager
from unittest import mock

from decklab.lib import access, inventory, state
from decklab.lib.api import activity, play_records as play
from decklab.lib.state import pg, rules
from decklab.tests.test_api import ApiTestCase
from decklab.tests.test_play_records import MixedFixture, encoded


class PlayDeletionTests(MixedFixture, ApiTestCase):
    def body(self, record_id, profile="matt", **changes):
        previous = self.box.state.play_get("games", record_id)
        return encoded({"profile": profile, "id": record_id, "sha256": rules.record_sha(previous),
                        "reason": "Duplicate fixture game", "confirmed": True, **changes})

    def test_delete_is_one_audited_change_and_leaves_decks_and_inventory_alone(self):
        from decklab.lib.inventory import files
        before = files.render(inventory.current(), decks=True)
        count = len(self.box.state.changes())
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            body = self.body(self.home)
            self.assertEqual(play.delete_game(body), {"deleted": True, "id": self.home})
            self.assertApiError(404, play.delete_game, body)
        self.assertIsNone(self.box.state.play_get("games", self.home))
        changes = self.box.state.changes()
        self.assertEqual(len(changes), count + 1)
        self.assertEqual((changes[-1]["actor"], changes[-1]["reason"]), ("matt", "Duplicate fixture game"))
        self.assertEqual([(row["table"], row["op"]) for row in changes[-1]["rows"]], [("play_record", "DELETE")])
        self.assertEqual(files.render(inventory.current(), decks=True), before)

    def test_hidden_game_is_missing_and_visible_other_recorder_cannot_delete_even_with_stale_hash(self):
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.assertApiError(404, play.delete_game, self.body(self.home, "user2", sha256="0" * 64))
            self.assertApiError(403, play.delete_game, self.body(self.mixed, "user2", sha256="0" * 64))
        self.assertIsNotNone(self.box.state.play_get("games", self.home))
        self.assertIsNotNone(self.box.state.play_get("games", self.mixed))

    def test_blank_reason_missing_confirmation_and_changed_game_are_refused_without_deletion(self):
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            for change, code in (({"reason": " "}, 400), ({"confirmed": False}, 400), ({"sha256": "0" * 64}, 409)):
                with self.subTest(change=change):
                    self.assertApiError(code, play.delete_game, self.body(self.home, **change))
        self.assertIsNotNone(self.box.state.play_get("games", self.home))

    def test_member_deletes_only_its_recording_space_and_positive_rights_are_explicit(self):
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            record = self.box.state.play_get("games", self.members_game)
            self.assertTrue(play._rights("games", record, play.guard.viewer())["delete"])
            self.assertFalse(play._rights("games", self.box.state.play_get("games", self.mixed), play.guard.viewer())["delete"])
            play.delete_game(self.body(self.members_game, "user2"))
        self.assertIsNone(self.box.state.play_get("games", self.members_game))

    def test_mixed_game_deletion_reason_never_leaves_recording_space_even_when_decks_are_public(self):
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            play.delete_game(self.body(self.mixed, reason="Private removal reason"))
        change = self.box.state.changes()[-1]
        from decklab.tests.test_activity import BY_ID
        scope = {"profile": "user2", "space": "user2", "system": False}
        with mock.patch.object(activity.guard, "public_deck_spaces", return_value={"home", "user2"}):
            shown = activity.visible_change(change, scope, BY_ID, me="user2")
        self.assertIsNotNone(shown)
        self.assertIsNone(shown["reason"])
        self.assertIsNone(shown["message"])
        self.assertNotIn("Private removal reason", str(shown))
        self.assertNotIn("A private note", str(shown))

    def test_store_rechecks_changed_record_under_its_write_lock(self):
        store = self.box.state
        record = store.play_get("games", self.home)
        original = rules.record_sha(record)
        revised = {**record, "revision": record["revision"] + 1, "notes": "A concurrent fixture correction"}
        store.play_put("games", revised, original, state.Actor("matt", "Matt"), "Correct fixture")
        count = len(store.changes())
        with self.assertRaises(state.Conflict):
            store.play_delete("games", self.home, original, state.Actor("matt", "Matt"), "Delete fixture", "Duplicate")
        self.assertEqual(store.play_get("games", self.home), revised)
        self.assertEqual(len(store.changes()), count)

    def test_postgresql_path_checks_fresh_receipt_after_membership_and_record_lock(self):
        before = self.box.state.play_get("games", self.home)
        for changed in (False, True):
            with self.subTest(changed=changed):
                current = {**copy.deepcopy(before), "revision": before["revision"] + int(changed)}
                store = mock.Mock(spec=pg.PgStore)
                store.play_get.return_value = before
                store._record.side_effect = lambda kind, row: row
                events = []
                cursor = mock.Mock()
                cursor.execute.side_effect = lambda sql, args=(): events.append((sql, args))
                cursor.fetchone.return_value = current
                store._lock = mock.Mock(side_effect=lambda cur, key: events.append(("lock", key)))
                @contextmanager
                def change(conn, actor, message, reason, **scope):
                    self.assertEqual(scope["space_ids"], {"home"})
                    yield cursor, 1
                store._change.side_effect = change
                store._call.side_effect = lambda work: work(object())
                call = lambda: pg.PgStore.play_delete(store, "games", before["id"], rules.record_sha(before),
                    state.Actor("matt", "Matt"), "Delete fixture", "Duplicate")
                if changed:
                    with self.assertRaises(state.Conflict):
                        call()
                    self.assertFalse(any(sql.startswith("delete ") for sql, _ in events))
                else:
                    self.assertTrue(call())
                    self.assertEqual(events[0], ("lock", f"play:games:{before['id']}"))
                    self.assertTrue(events[-1][0].startswith("delete from play_record"))
