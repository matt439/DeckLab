"""The packing endpoint: shared home progress, scoped responses and private task storage."""
import hashlib
import json

from decklab.lib import access
from decklab.lib.api import activity, assembly_ticks
from decklab.tests.test_api_permissions import PermissionTestCase

TASK = '["casual/a","target","pull|Opt",2]'
OTHER = '["casual/b","target","pack|User1 private box"]'


class AssemblyTicksTests(PermissionTestCase):
    def read(self, ids, profile=None):
        data = {"ids": ids}
        if profile:
            data["profile"] = profile
        return assembly_ticks.packing_ticks(json.dumps(data))

    def patch(self, ids, changes, profile="matt"):
        return assembly_ticks.packing_ticks(self.body(profile, ids=ids, changes=changes))

    def test_both_home_people_share_ticks_and_hidden_ids_never_come_back(self):
        self.patch([TASK, OTHER], [{"id": TASK, "done": True}, {"id": OTHER, "done": True}])
        with access.using({"profile": "user1", "email": "", "remote": True}):
            self.assertEqual(self.read([TASK]), {"ticks": [TASK]})
            self.assertEqual(self.patch([TASK], [{"id": TASK, "done": False}], "user1"), {"ticks": []})
        self.assertEqual(self.read([OTHER]), {"ticks": [OTHER]})
        # Auditing and persistence do not keep private kit labels or task semantics.
        trail = json.dumps(self.box.state.changes())
        self.assertNotIn("User1 private box", trail)
        self.assertNotIn("casual/b", trail)
        self.assertEqual(self.box.state.packing_ticks([hashlib.sha256(OTHER.encode()).hexdigest()]),
                         [hashlib.sha256(OTHER.encode()).hexdigest()])

    def test_reads_need_no_profile_and_never_write(self):
        self.assertEqual(self.read([TASK]), {"ticks": []})
        self.assertEqual(self.box.state.changes(), [])

    def test_activity_names_home_progress_without_exposing_task_ids(self):
        self.patch([TASK, OTHER], [{"id": TASK, "done": True}, {"id": OTHER, "done": True}])
        for who in ("matt", "user1"):
            with access.using(None), access.viewing(who):
                change, = activity.activity_view()["changes"]
                self.assertEqual(change["rows"], [{"table": "packing_tick", "op": "INSERT",
                                                  "summary": "Packing progress updated"}])
                self.assertEqual(change["headline"], "Matt updated packing progress")
                self.assertEqual(change["kinds"], ["decks"])
                self.assertNotIn(hashlib.sha256(TASK.encode()).hexdigest(), json.dumps(change))
                self.assertNotIn(TASK, json.dumps(change))
        with access.using(None), access.viewing("user2"):
            self.assertEqual(activity.activity_view()["changes"], [])

    def test_person_space_cannot_read_or_write_home_ticks(self):
        self.check(lambda p: self.read([TASK], p), {"matt", "user1", "local", "script"})
        self.check(lambda p: self.patch([TASK], [{"id": TASK, "done": True}], p),
                   {"matt", "user1", "local", "script"})
        with access.using(None), access.viewing("user2"):
            self.assertApiError(403, self.read, [TASK])

    def test_writer_must_match_the_home_chooser(self):
        with access.using(None), access.viewing("user1"):
            self.assertApiError(403, self.patch, [TASK], [{"id": TASK, "done": True}], "matt")
            self.assertEqual(self.patch([TASK], [{"id": TASK, "done": True}], "user1"), {"ticks": [TASK]})

    def test_changes_require_a_known_actor_and_exact_scope(self):
        self.assertApiError(403, self.patch, [TASK], [], "unknown")
        self.assertApiError(400, self.patch, [TASK], [{"id": OTHER, "done": True}])
        self.assertApiError(400, self.patch, [TASK], [{"id": TASK, "done": 1}])
        self.assertApiError(400, self.patch, [TASK], [{"id": TASK, "done": True}] * 2)
        self.assertEqual(self.read([TASK]), {"ticks": []})

    def test_ids_and_limits_are_checked(self):
        for ids in ("x", [""], [None], ["x\x00"], ["x" * 1001], [TASK] * 2001):
            with self.subTest(ids=repr(ids)[:80]):
                self.assertApiError(400, self.read, ids)

    def test_database_outage_is_reported_without_a_false_success(self):
        self.box.state.down = True
        self.assertApiError(503, self.read, [TASK])
        self.assertApiError(503, self.patch, [TASK], [{"id": TASK, "done": True}])

    def test_large_multi_deck_task_scope_fits_the_endpoint_limit(self):
        ids = [f'{TASK}:{i}:' + "x" * 200 for i in range(1200)]
        body = json.dumps({"ids": ids}).encode()
        self.assertGreater(len(body), 256 * 1024)
        self.assertEqual(assembly_ticks.packing_ticks(body), {"ticks": []})
