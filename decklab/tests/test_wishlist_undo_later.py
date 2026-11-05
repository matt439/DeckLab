"""Undo of a wishlist removal after later changes to the same list (E11-S08), over the pure
kernel, the audited memory adapter and the owner-only API, without PostgreSQL."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, state
from decklab.lib.api import wishlist_undo as api
from decklab.lib.api.common import ApiError
from decklab.lib.state import rules, wishlist_undo as undo, wishlist_undo_later as later
from decklab.tests import household_config, test_api, wishlist_undo_support as support

NOTE = "Secret café note\r\nline two"
MATT = state.Actor("matt", "Matt", via="tunnel")
WEB = state.Actor("matt", "Matt", source="web", via="tunnel")


def entry(name, notes=""):
    return {"name": name, "set": "", "number": "", "notes": notes, "source": ""}


def seed(store, pid="matt", names=("Opt", "Forest", "Island", "Plains")):
    """names at 0.., then Forest (position 1, with a private note) removed."""
    store.seed_wishlist(pid, [entry(name, NOTE if name == "Forest" else "") for name in names])
    actor = state.Actor(pid, "Matt" if pid == "matt" else pid.title(), via="tunnel")
    store.wishlist_remove(pid, "Forest", actor, "Fixture removed a wishlist entry")
    return store.changes()[-1]["id"]


def layout(store, pid="matt"):
    return [(row["name"], row["position"]) for row in store.raw_entries(pid)]


class KernelTests(unittest.TestCase):
    def setUp(self):
        self.store = support.AuditWishlistMemory()
        self.change_id = seed(self.store)
        self.source = self.store.raw_source(self.change_id)

    def later_changes(self):
        self.store.wishlist_add("matt", entry("Swamp"), MATT, "Later addition")
        self.store.wishlist_remove("matt", "Plains", MATT, "Later removal")
        self.store.wishlist_set("matt", "Island", MATT, "Later edit", notes="Edited")

    def review(self, **overrides):
        args = {"change_id": self.change_id, "pid": "matt", "source_rows": self.source,
                "later_rows": self.store.later_rows("matt", self.source[0]["id"]), "raw_entries": self.store.raw_entries("matt"),
                "latest_target": self.store.latest("matt", 1), "latest_owner": self.store.latest("matt"), **overrides}
        return later.review(**args)

    def refused(self, kind, **overrides):
        with self.assertRaises(kind) as caught:
            self.review(**overrides)
        self.assertNotIn("café", str(caught.exception))
        return str(caught.exception)

    def test_plan_puts_the_entry_back_at_its_old_position_and_leaves_later_changes(self):
        self.later_changes()
        plan = self.review()
        self.assertEqual((plan["action"], plan["label"], plan["later"], plan["insert_at"]), ("wishlist_add", "Forest", 3, 1))
        self.assertEqual((plan["current"], plan["restored"]), (None, entry("Forest", NOTE)))
        self.assertEqual(plan["raw_restore"], self.source[0]["before"])
        self.assertEqual([(row["name"], row["position"], row["notes"]) for row in plan["raw_after"]],
                         [("Opt", 0, ""), ("Forest", 1, NOTE), ("Island", 2, "Edited"), ("Swamp", 4, "")])
        self.assertEqual(plan["sha256"], undo.list_sha(plan["raw_after"]))
        self.assertEqual(plan["latest_owner"], self.store.latest("matt"))
        # The evidence is bound in the expect hash: one more later change gives another.
        self.store.wishlist_set("matt", "Opt", MATT, "One more", notes="x")
        self.assertNotEqual(self.review()["expect"], plan["expect"])

    def test_still_latest_removal_stays_on_the_plain_path(self):
        plan = self.store.wishlist_undo_review(self.change_id, "matt")
        self.assertNotIn("later", plan)
        self.assertEqual(plan["expect"], undo.list_sha([self.change_id, self.source, self.store.raw_entries("matt"),
                                                        self.source[0]["id"], self.source[0]["id"]]))
        with self.assertRaises(undo.UndoConflict):
            self.review()  # this kernel is only for a removal the list has moved on from

    def test_later_rows_bound_is_counted_and_never_cut_short(self):
        for index in range(later.MAX_LATER):
            self.store.wishlist_set("matt", "Island", MATT, "Later edit", notes=f"n{index}")
        self.assertEqual(self.review()["later"], later.MAX_LATER)
        self.store.wishlist_set("matt", "Island", MATT, "Later edit", notes="one more")
        rows = self.store.later_rows("matt", self.source[0]["id"])
        self.assertEqual(len(rows), later.MAX_LATER + 1)
        self.assertIn("200", self.refused(later.Unsupported, later_rows=rows))
        self.assertEqual(self.store.wishlist_undo_review(self.change_id, "matt").get("available", None), None) \
            if False else None
        with self.assertRaises(later.Unsupported):
            self.store.wishlist_undo_review(self.change_id, "matt")

    def test_the_card_touched_again_since_is_refused_with_a_fixed_reason(self):
        self.store.wishlist_add("matt", entry("FOREST"), MATT, "Later re-add in another case")
        self.store.wishlist_remove("matt", "forest", MATT, "Later removal again")
        self.assertEqual(self.refused(later.Unsupported), later.AGAIN)
        # Casefold, not lower(): ß and SS are the same card name.
        rows = self.store.later_rows("matt", self.source[0]["id"])
        source = copy.deepcopy(self.source)
        source[0]["before"]["name"] = "Straße"
        for row in rows:
            for side in ("before", "after"):
                if row[side] is not None and row[side]["name"] == "FOREST":
                    row[side]["name"] = "STRASSE"
        self.assertEqual(self.refused(later.Unsupported, source_rows=source, later_rows=rows), later.AGAIN)

    def test_a_present_card_or_a_later_row_at_its_position_is_refused(self):
        self.later_changes()
        present = self.store.raw_entries("matt") + [dict(self.source[0]["before"], name="forest", position=9)]
        self.assertEqual(self.refused(later.Unsupported, raw_entries=present), later.AGAIN)
        rows = self.store.later_rows("matt", self.source[0]["id"])
        rows[0] = copy.deepcopy(rows[0])
        rows[0]["key"]["position"] = 1
        self.assertEqual(self.refused(later.Unsupported, later_rows=rows), later.AGAIN)
        self.refused(undo.UndoConflict, latest_target=self.store.latest("matt"))

    def test_put_back_and_removed_again_at_its_old_index_conflicts_on_the_position(self):
        self.store.wishlist_add("matt", entry("Swamp"), MATT, "Later put at index 1", at=1)
        self.assertIn(("Swamp", 1), layout(self.store))
        self.store.wishlist_remove("matt", "Swamp", MATT, "Later removal")
        with self.assertRaises(undo.UndoConflict):
            self.store.wishlist_undo_review(self.change_id, "matt")

    def test_a_slot_the_ordinary_rules_no_longer_give_is_refused(self):
        self.store.wishlist_remove("matt", "Island", MATT, "Neighbour removed too")
        self.assertIn("old place", self.refused(later.Unsupported))
        self.assertEqual(layout(self.store), [("Opt", 0), ("Plains", 3)])

    def test_a_full_list_is_refused(self):
        store = support.AuditWishlistMemory()
        change = seed(store, names=["Opt", "Forest"] + [f"Card {index}" for index in range(rules.MAX_ENTRIES - 2)])
        store.wishlist_add("matt", entry("Swamp"), MATT, "Fills the list")
        with self.assertRaises(later.Unsupported) as caught:
            store.wishlist_undo_review(change, "matt")
        self.assertIn(str(rules.MAX_ENTRIES), str(caught.exception))

    def test_malformed_later_rows_are_refused_without_values(self):
        self.later_changes()
        rows = self.store.later_rows("matt", self.source[0]["id"])
        bad = [rows[:-1], list(reversed(rows)), [], "x", rows[:1] + rows[:1] + rows[1:],
               [dict(rows[0], table="watchlist_item")] + rows[1:], [dict(rows[0], change=None)] + rows[1:],
               [dict(rows[0], after=dict(rows[0]["after"], profile_id="user1"))] + rows[1:],
               [dict(rows[0], op="UPDATE")] + rows[1:], [dict(rows[0], id=self.source[0]["id"])] + rows[1:]]
        for value in bad:
            with self.subTest(value=value):
                self.assertEqual(self.refused(later.Unsupported, later_rows=value), "The later wishlist changes cannot be checked.")

    def test_other_profiles_or_non_removal_sources_are_missing(self):
        self.later_changes()
        for pid in ("user1", "bad id"):
            with self.subTest(pid=pid):
                self.refused(undo.UndoMissing, pid=pid)
        insert = [dict(self.source[0], op="INSERT", before=None, after=self.source[0]["before"])]
        self.refused(undo.UndoMissing, source_rows=insert)
        self.refused(undo.UndoMissing, source_rows=self.source + self.source)


class ApiTests(test_api.ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = support.AuditWishlistMemory()
        self.addCleanup(state.use(self.store))
        self.change_id = seed(self.store)
        self.store.wishlist_add("matt", entry("Swamp", NOTE), MATT, "Later addition")
        self.store.wishlist_set("matt", "Island", MATT, "Later edit", notes=NOTE)
        self.enterContext(self.identity("matt"))

    @staticmethod
    def identity(pid):
        return access.using({"profile": pid, "email": pid + "@example.com", "remote": True})

    def refused(self, status, function, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        self.assertNotIn("café", caught.exception.message)
        return caught.exception

    def apply(self, expect, change_id=None, profile="matt"):
        body = {"profile": profile, "id": self.change_id if change_id is None else change_id, "expect": expect}
        return api.apply_wishlist_undo(json.dumps(body).encode())

    def unchanged(self):
        return copy.deepcopy((self.store._wishlists, self.store.changes()))

    def test_preview_then_save_restores_the_entry_as_one_new_change(self):
        before = self.unchanged()
        source = self.store.raw_source(self.change_id)
        preview = api.wishlist_undo_view(id=self.change_id)
        self.assertEqual(set(preview), {"available", "id", "expect", "kind", "action", "profile", "label", "current", "restored", "later"})
        self.assertEqual((preview["action"], preview["later"], preview["restored"]), ("wishlist_add", 2, entry("Forest", NOTE)))
        self.assertEqual(self.unchanged(), before)
        result = self.apply(preview["expect"])
        self.assertEqual((result["saved"], result["restored"]), (True, entry("Forest", NOTE)))
        self.assertEqual(result["summary"], f"Undo change #{self.change_id}: restore a removed wishlist entry")
        self.assertEqual(layout(self.store), [("Opt", 0), ("Forest", 1), ("Island", 2), ("Plains", 3), ("Swamp", 4)])
        history = self.store.changes()
        self.assertEqual(history[:-1], before[1])
        self.assertEqual(history[-1]["rows"], [{"table": "wishlist_entry", "op": "INSERT", "key": source[0]["key"],
                                               "before": None, "after": source[0]["before"]}])
        self.assertEqual(history[-1]["message"], f"Undo wishlist change {self.change_id}")
        self.assertEqual(result["sha256"], undo.list_sha(self.store.raw_entries("matt")))
        self.assertEqual(result["revision"], str(self.store.latest("matt")))
        self.assertEqual(self.store.raw_source(self.change_id), source)
        # Put back once: the source can't be put back again.
        after = self.unchanged()
        self.refused(409, self.apply, preview["expect"])
        self.assertEqual(self.unchanged(), after)

    def test_owner_only_everyone_else_sees_a_missing_change(self):
        other = seed(self.store, "user1")
        self.store.wishlist_add("user1", entry("Swamp"), state.Actor("user1", "User1", via="tunnel"), "Later")
        before = self.unchanged()
        for viewer, change in (("matt", other), ("user1", self.change_id), ("user2", self.change_id)):
            with self.subTest(viewer=viewer), self.identity(viewer):
                self.assertEqual(self.refused(404, api.wishlist_undo_view, id=change).message, api.NO_CHANGE)
                self.assertEqual(self.refused(404, self.apply, "a" * 64, change, viewer).message, api.NO_CHANGE)
        with access.using(None), access.viewing(None):
            self.refused(404, api.wishlist_undo_view, id=self.change_id)
        self.assertEqual(self.unchanged(), before)

    def test_a_change_between_review_and_save_conflicts_without_writing(self):
        preview = api.wishlist_undo_view(id=self.change_id)
        for change in (lambda: self.store.wishlist_set("matt", "Opt", MATT, "Between", notes="x"),
                       lambda: self.store.wishlist_add("matt", entry("Mountain"), MATT, "Between")):
            change()
            before = self.unchanged()
            self.assertEqual(self.refused(409, self.apply, preview["expect"]).message, api.CHANGED)
            self.assertEqual(self.unchanged(), before)
            preview = api.wishlist_undo_view(id=self.change_id)
        self.assertEqual(preview["later"], 4)

    def test_a_failed_receipt_rolls_back(self):
        preview = api.wishlist_undo_view(id=self.change_id)
        before = self.unchanged()
        self.store.fail_receipt = True
        self.refused(409, self.apply, preview["expect"])
        self.assertEqual(self.unchanged(), before)

    def test_unsupported_shapes_explain_themselves_with_counts_only(self):
        self.store.wishlist_remove("matt", "Island", MATT, "Neighbour removed too")
        result = api.wishlist_undo_view(id=self.change_id)
        self.assertFalse(result["available"])
        self.assertTrue(result["reason"].startswith(api.UNSUPPORTED))
        self.assertIn("old place", result["reason"])
        self.assertNotIn("café", json.dumps(result))

    def test_projection_accepts_later_only_on_a_restore_within_its_bound(self):
        plan = self.store.wishlist_undo_review(self.change_id, "matt")
        self.assertEqual(api._project(plan, self.change_id, "matt")["later"], 2)
        for value in (0, later.MAX_LATER + 1, "2", True, 2.0, None):
            with self.subTest(value=value), self.assertRaises(ApiError) as caught:
                api._project({**plan, "later": value}, self.change_id, "matt")
            self.assertEqual(caught.exception.status, 503)
        removal = support.AuditWishlistMemory()
        removal.seed_wishlist("matt", [entry("Opt")])
        removal.wishlist_add("matt", entry("Forest"), MATT, "Added")
        added = removal.changes()[-1]["id"]
        remove_plan = removal.wishlist_undo_review(added, "matt")
        with self.assertRaises(ApiError):
            api._project({**remove_plan, "later": 1}, added, "matt")
        with mock.patch.object(self.store, "wishlist_undo_review", return_value={**plan, "later": 0}):
            self.refused(503, api.wishlist_undo_view, id=self.change_id)


if __name__ == "__main__":
    unittest.main()
