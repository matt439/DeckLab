"""Four-seat coordinator visibility and the shared Forge activity/Stop path; no games."""
import json
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab.lib import jobs
from decklab.lib.api import forge_runs, guard


class PodActivityTests(unittest.TestCase):
    def setUp(self):
        self.profile = {"id": "user2", "name": "User2", "role": "member", "space": "user2"}
        self.sides = [{"id": f"user2/commander/deck-{i}", "version": "target", "title": f"Deck {i}"}
                      for i in range(4)]
        self.job = SimpleNamespace(key="pods:" + "a" * 64, fn=SimpleNamespace(
            kind="pods", entry=self.sides[0], chosen=self.sides[1:], sides=self.sides,
            by="User2", by_id="user2"))
        self.snap = {"status": jobs.RUNNING, "progress": {"done": 4, "total": 16}, "ahead": 0,
                     "detail": {"deck": self.sides[0]}}
        self.coordinators = mock.Mock()
        self.coordinators.active.return_value = [self.job]
        self.coordinators.snapshot.return_value = self.snap
        self.coordinators.get.return_value = self.job
        self.coordinators.cancel.return_value = False
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(forge_runs, "COORD_JOBS", self.coordinators).start()
        mock.patch.object(forge_runs.FORGE_JOBS, "active", return_value=[]).start()
        mock.patch.object(guard, "script", return_value=False).start()
        mock.patch.object(forge_runs, "_config_profiles", return_value=[self.profile]).start()

    def seen(self, profile=None, visible=None):
        seen = forge_runs._Seen(profile or self.profile)
        allowed = set(visible if visible is not None else [side["id"] for side in self.sides])
        seen.deck = lambda deck_id: deck_id in allowed
        seen._current_ids = allowed
        return seen

    def test_four_seat_job_is_in_the_global_pill_and_links_to_its_pod(self):
        item, = forge_runs._running_items(seen=self.seen())
        self.assertEqual((item["kind"], item["done"], item["total"]), ("pods", 4, 16))
        self.assertEqual(item["link"], "#/forge-pods?key=" + "a" * 64)
        self.assertEqual(item["title"], "Four-player Commander pod")
        self.assertIsNone(item["sides"])  # Generic coordinator UI never formats a two-seat score.
        self.assertTrue(item["may_stop"])

    def test_revoking_any_one_side_hides_the_entire_job_from_a_member(self):
        for hidden in range(4):
            with self.subTest(hidden=hidden):
                visible = [side["id"] for i, side in enumerate(self.sides) if i != hidden]
                self.assertEqual(forge_runs._running_items(seen=self.seen(visible=visible)), [])

    def test_hidden_admin_controls_are_anonymous_after_privacy_changes(self):
        admin = {"id": "matt", "name": "Matt", "role": "admin", "space": "home"}
        item, = forge_runs._running_items(seen=self.seen(admin, visible=[]))
        self.assertTrue(item["hidden"])
        self.assertTrue(item["may_stop"])
        self.assertIsNone(item["link"])
        self.assertNotIn("Deck 0", json.dumps(item))
        self.assertIsNone(item["sides"])
        self.assertEqual(item["by"], "someone")

    def test_shared_stop_accepts_pod_coordinator_keys_and_checks_all_sides(self):
        seen = self.seen()
        payload = json.dumps({"profile": "user2", "key": self.job.key}).encode()
        with mock.patch.object(forge_runs, "_writer", return_value=self.profile), \
                mock.patch.object(forge_runs, "_Seen", return_value=seen):
            answer = forge_runs.stop_matchup(payload)
        self.assertEqual(answer, {"key": self.job.key, "stopped": False, "hidden": False})
        self.coordinators.cancel.assert_called_once_with(self.job.key, by="User2")
        self.job.fn.sides[-1] = {"id": "user3/commander/fourth"}
        self.assertIn("user3", seen.stop_target(self.job, True)["spaces"])
