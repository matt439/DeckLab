"""Undo of a wishlist addition that moved other entries along (E11-S08), over the pure kernel,
an audited memory adapter and the owner-only API, without PostgreSQL."""
import copy
import json
import unittest

from decklab.lib import access, state
from decklab.lib.api import activity_undo, wishlist_undo as api
from decklab.lib.api.common import ApiError
from decklab.lib.state import wishlist_undo as undo, wishlist_undo_moved as moved
from decklab.tests import household_config, test_api, wishlist_undo_support as support

NOTE = "Secret café note\r\nline two"


def entry(name, notes=""):
    return {"name": name, "set": "", "number": "", "notes": notes, "source": ""}


class MovedMemory(support.AuditWishlistMemory):
    """The audited memory fixture, reading whole sources and saving the moved inverse as
    pg_wishlist_undo_moved does (delete, then each entry back, lowest first)."""

    def raw_source(self, change_id):
        found = next((change for change in self._changes if change["id"] == change_id), None)
        return [] if found is None else [{**copy.deepcopy(row), "id": self._audit_ids[(change_id, index)]}
                                        for index, row in enumerate(found["rows"])]

    def _undo_plan(self, change_id, pid):
        raw = self.raw_source(change_id)
        if len(raw) > 1:
            if pid in self.inactive:
                raise undo.UndoMissing()
            return moved.review(change_id, pid, raw, self.raw_entries(pid), self.latest(pid), len(raw))
        return super()._undo_plan(change_id, pid)

    def wishlist_undo_apply(self, change_id, pid, expect, actor, message):
        with self._lock:
            if len(self.raw_source(change_id)) < 2:
                return super().wishlist_undo_apply(change_id, pid, expect, actor, message)
            self._check()
            self.calls.append(("apply", change_id, pid, expect, actor))
            if actor.id != pid or actor.source != "web":
                raise undo.UndoMissing()
            plan = self._undo_plan(change_id, pid)
            if not isinstance(expect, str) or not undo.SHA.fullmatch(expect):
                raise undo.UndoUnsupported("Review required")
            if expect != plan["expect"]:
                raise undo.UndoConflict()
            saved = copy.deepcopy((self._wishlists, self._changes, self._audit_ids))
            try:
                rows = self._wishlists[pid]
                gone = next(row for row in rows if row["position"] == plan["raw_current"]["position"])
                rows.remove(gone)
                changes = [("wishlist_entry", "DELETE", ("profile_id", "position"), gone, None)]
                for after, before in plan["raw_moves"]:
                    index = next(i for i, row in enumerate(rows) if row["position"] == after["position"])
                    old = rows[index]
                    rows[index] = dict(old, position=before["position"])
                    changes.append(("wishlist_entry", "UPDATE", ("profile_id", "position"), old, rows[index]))
                rows.sort(key=lambda row: row["position"])
                self._log(actor, message, None, changes)
                result = moved.receipt(plan, self.raw_entries(pid), self.raw_source(self._changes[-1]["id"]), self.latest(pid))
            except Exception:
                self._wishlists, self._changes, self._audit_ids = saved
                raise
            return {"review": plan, **result}


def seed(store, pid="matt", at=1):
    """[Opt, Forest, Island] at 0-2, then Llanowar Elves added at index at, moving the rest."""
    actor = state.Actor(pid, "Matt" if pid == "matt" else pid.title(), via="tunnel")
    store.seed_wishlist(pid, [entry("Opt", NOTE), entry("Forest"), entry("Island")])
    store.wishlist_add(pid, entry("Llanowar Elves", NOTE), actor, "Fixture put back at its place", at=at)
    return store.changes()[-1]["id"]


class KernelTests(unittest.TestCase):
    def setUp(self):
        self.store = MovedMemory()
        self.change_id = seed(self.store)
        self.source = self.store.raw_source(self.change_id)
        self.entries = self.store.raw_entries("matt")

    def review(self, **overrides):
        args = {"change_id": self.change_id, "pid": "matt", "source_rows": self.source, "raw_entries": self.entries,
                "latest_owner": self.store.latest("matt"), "total": len(self.source), **overrides}
        return moved.review(**args)

    def test_plan_removes_the_entry_and_puts_each_moved_entry_back(self):
        self.assertEqual([row["op"] for row in self.source], ["UPDATE", "UPDATE", "INSERT"])
        plan = self.review()
        self.assertEqual((plan["action"], plan["label"], plan["moved"], plan["restored"]), ("wishlist_remove", "Llanowar Elves", 2, None))
        self.assertEqual(plan["current"], entry("Llanowar Elves", NOTE))
        self.assertEqual([(a["position"], b["position"]) for a, b in plan["raw_moves"]], [(2, 1), (3, 2)])
        self.assertEqual([(row["name"], row["position"]) for row in plan["raw_after"]], [("Opt", 0), ("Forest", 1), ("Island", 2)])

    def test_another_profiles_or_mixed_source_is_missing_before_any_value(self):
        for rows in (self.source[:1], [], "x", self.source[:-1] + [dict(self.source[-1], table="watchlist_item")],
                     [dict(self.source[0], after=dict(self.source[0]["after"], profile_id="user1"))] + self.source[1:]):
            with self.subTest(rows=rows), self.assertRaises(undo.UndoMissing):
                self.review(source_rows=rows)
        with self.assertRaises(undo.UndoMissing):
            self.review(pid="user1")

    def test_unsupported_shapes_say_why_without_quoting_notes(self):
        two = self.source[:-1] + [dict(self.source[-1], op="UPDATE", before=self.source[-1]["after"])]
        skipped = [dict(self.source[0], after=dict(self.source[0]["after"], position=9), key={"profile_id": "matt", "position": 9})] + self.source[1:]
        edited = [dict(self.source[0], after=dict(self.source[0]["after"], notes="x"))] + self.source[1:]
        for rows in (two, skipped, edited, list(reversed(self.source))):
            with self.subTest(rows=rows), self.assertRaises(undo.UndoUnsupported) as caught:
                self.review(source_rows=rows)
            self.assertNotIn("café", str(caught.exception))
        with self.assertRaises(undo.UndoUnsupported) as caught:
            self.review(total=moved.MAX_MOVED + 2)
        self.assertIn("50", str(caught.exception))

    def test_any_later_change_or_edited_entry_conflicts(self):
        with self.assertRaises(undo.UndoConflict):
            self.review(latest_owner=self.store.latest("matt") + 1)
        for index, change in ((1, {"notes": "Edited"}), (2, {"source": "magic/x.md"}), (3, {"name": "Plains"})):
            rows = copy.deepcopy(self.entries)
            rows[index].update(change)
            with self.subTest(index=index), self.assertRaises(undo.UndoConflict):
                self.review(raw_entries=rows)
        with self.assertRaises(undo.UndoConflict):
            self.review(raw_entries=[row for row in self.entries if row["name"] != "Island"])

    def test_receipt_requires_exactly_the_delete_then_the_moves_back(self):
        plan = self.review()
        actor = state.Actor("matt", "Matt", source="web", via="tunnel")
        self.store.wishlist_undo_apply(self.change_id, "matt", plan["expect"], actor, "Undo")
        actual = self.store.raw_source(self.store.changes()[-1]["id"])
        self.assertEqual([row["op"] for row in actual], ["DELETE", "UPDATE", "UPDATE"])
        latest = self.store.latest("matt")
        entries = self.store.raw_entries("matt")
        self.assertEqual(moved.receipt(plan, entries, actual, latest)["removed_name"], "Llanowar Elves")
        for bad in (actual[:-1], actual[:1] + actual[:0:-1], [dict(actual[0], op="UPDATE")] + actual[1:]):
            with self.subTest(bad=bad), self.assertRaises(undo.UndoConflict):
                moved.receipt(plan, entries, bad, latest)
        with self.assertRaises(undo.UndoConflict):
            moved.receipt(plan, entries, actual, latest + 1)
        with self.assertRaises(undo.UndoConflict):
            moved.receipt(plan, entries[:-1], actual, latest)


class ApiTests(test_api.ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = MovedMemory()
        self.addCleanup(state.use(self.store))
        self.change_id = seed(self.store)
        self.enterContext(self.identity("matt"))

    @staticmethod
    def identity(pid):
        return access.using({"profile": pid, "email": pid + "@example.com", "remote": True})

    def refused(self, status, function, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception

    def apply(self, expect, change_id=None, profile="matt"):
        body = {"profile": profile, "id": self.change_id if change_id is None else change_id, "expect": expect}
        return api.apply_wishlist_undo(json.dumps(body).encode())

    def test_preview_then_save_restores_the_list_exactly_as_one_new_change(self):
        before = copy.deepcopy(self.store.changes()[:-1])
        original = self.store.raw_entries("matt")
        preview = api.wishlist_undo_view(id=self.change_id)
        self.assertEqual(set(preview), {"available", "id", "expect", "kind", "action", "profile", "label", "current", "restored", "moved"})
        self.assertEqual((preview["action"], preview["moved"], preview["restored"]), ("wishlist_remove", 2, None))
        self.assertEqual(self.store.raw_entries("matt"), original)
        result = self.apply(preview["expect"])
        self.assertEqual((result["saved"], result["removed_name"], result["restored"]), (True, "Llanowar Elves", None))
        self.assertEqual(result["summary"], f"Undo change #{self.change_id}: remove an added wishlist entry")
        self.assertEqual([(row["name"], row["position"]) for row in self.store.raw_entries("matt")], [("Opt", 0), ("Forest", 1), ("Island", 2)])
        history = self.store.changes()
        self.assertEqual(history[:len(before)], before)
        self.assertEqual(history[-1]["message"], f"Undo wishlist change {self.change_id}")
        self.assertNotIn("café", history[-1]["message"])
        self.assertEqual(result["sha256"], undo.list_sha(self.store.raw_entries("matt")))
        # The original is no longer the latest change: a second save conflicts and writes nothing.
        after = copy.deepcopy(self.store.changes())
        self.assertEqual(self.refused(409, self.apply, preview["expect"]).message, api.CHANGED)
        self.assertEqual(self.store.changes(), after)

    def test_owner_only_everyone_else_sees_a_missing_change(self):
        other = seed(self.store, "user1")
        before = copy.deepcopy(self.store.changes())
        for viewer, change in (("matt", other), ("user1", self.change_id), ("user2", self.change_id)):
            with self.subTest(viewer=viewer), self.identity(viewer):
                self.assertEqual(self.refused(404, api.wishlist_undo_view, id=change).message, api.NO_CHANGE)
                self.assertEqual(self.refused(404, self.apply, "a" * 64, change, viewer).message, api.NO_CHANGE)
        self.assertEqual(self.store.changes(), before)

    def test_stale_review_or_later_edit_conflicts_without_writing(self):
        preview = api.wishlist_undo_view(id=self.change_id)
        self.assertEqual(self.refused(409, self.apply, "b" * 64).message, api.CHANGED)
        actor = state.Actor("matt", "Matt", via="tunnel")
        self.store.wishlist_set("matt", "Forest", actor, "Later edit", notes="Changed")
        before = copy.deepcopy((self.store._wishlists, self.store.changes()))
        self.assertEqual(self.refused(409, api.wishlist_undo_view, id=self.change_id).message, api.CHANGED)
        self.assertEqual(self.refused(409, self.apply, preview["expect"]).message, api.CHANGED)
        self.assertEqual(copy.deepcopy((self.store._wishlists, self.store.changes())), before)

    def test_unsupported_shape_explains_itself_with_counts_only(self):
        actor = state.Actor("matt", "Matt", via="tunnel")
        with self.store.batch(actor, "Two additions"):
            self.store.wishlist_add("matt", entry("Plains", NOTE), actor, "x")
            self.store.wishlist_add("matt", entry("Swamp", NOTE), actor, "x")
        change = self.store.changes()[-1]["id"]
        result = api.wishlist_undo_view(id=change)
        reason = f"{api.UNSUPPORTED} Only one added wishlist entry and the entries it moved can be undone here."
        self.assertEqual(result, {"available": False, "id": change, "reason": reason})
        self.assertNotIn("café", json.dumps(result))
        self.assertEqual(self.refused(400, self.apply, "a" * 64, change).message, reason)

    def test_activity_offers_review_only_to_the_owner_of_a_whole_shown_change(self):
        change = {"id": self.change_id, "rows": self.store.raw_source(self.change_id), "total": 3}
        matt = {"id": "matt", "role": "admin", "space": "home"}
        self.assertEqual(activity_undo.review_hint(change, {"id": self.change_id}, matt), {"review": True, "kind": "wishlist"})
        self.assertEqual(api.hint(change, {"id": self.change_id}, matt), {"review": True, "kind": "wishlist"})
        for other in ({"id": "user1", "role": "member", "space": "home"}, None):
            self.assertIsNone(api.hint(change, {"id": self.change_id}, other))
        self.assertIsNone(api.hint(dict(change, more=1), {"id": self.change_id}, matt))
        self.assertIsNone(api.hint(dict(change, total=4), {"id": self.change_id}, matt))
        self.assertIsNone(api.hint(change, {"id": self.change_id + 1}, matt))


if __name__ == "__main__":
    unittest.main()
