"""Home field-policy audit privacy, using only synthetic change rows."""
import copy
import json
import unittest

from decklab.lib import permissions
from decklab.lib.api import activity


PROFILES = {
    "matt": {"id": "matt", "name": "Matt", "space": "home", "role": "admin"},
    "user1": {"id": "user1", "name": "User1", "space": "home", "role": "member"},
    "user2": {"id": "user2", "name": "User2", "space": "user2", "role": "member"},
    "user3": {"id": "user3", "name": "User3", "space": "user3", "role": "admin"},
}
PRIVATE = "PRIVATE-POLICY-SENTINEL"


def policy_row(fmt="Constructed", op="INSERT"):
    record = {"format": fmt, "revision": 1,
              "content": {"v": 1, "rules": [{"epoch": {"kind": "creation", "deck_id": PRIVATE,
                                                       "revision": 1}, "mode": "exclude"}]}}
    return {"table": "field_policy", "op": op, "key": {"format": fmt},
            "before": record if op == "DELETE" else None,
            "after": record if op != "DELETE" else None}


def change(rows):
    return {"id": 1, "at": "2026-10-29T00:00:00+00:00", "actor": "matt", "source": "web", "via": "home",
            "message": "Reviewed fixture field choice", "reason": "Private fixture exclusion reason", "rows": rows}


def view(rows, viewer):
    scope = permissions.activity_scope(PROFILES.get(viewer), script=viewer is None)
    return activity.visible_change(change(rows), scope, PROFILES, me=viewer, orders={})


class FieldPolicyActivityTests(unittest.TestCase):
    def test_home_profiles_receive_only_fixed_summary_and_settings_category(self):
        for viewer in ("matt", "user1"):
            with self.subTest(viewer=viewer):
                shown = view([policy_row()], viewer)
                self.assertEqual(shown["rows"], [{"table": "field_policy", "op": "INSERT",
                                                   "summary": "Constructed field membership updated"}])
                self.assertEqual(shown["kinds"], ["settings"])
                self.assertNotIn(PRIVATE, json.dumps(shown))
                self.assertEqual(shown["reason"], "Private fixture exclusion reason")

    def test_outside_members_and_admins_receive_no_policy_change(self):
        for viewer in ("user2", "user3"):
            for op in ("INSERT", "UPDATE", "DELETE"):
                with self.subTest(viewer=viewer, op=op):
                    self.assertIsNone(view([policy_row(op=op)], viewer))

    def test_legacy_all_scope_never_overrides_named_viewer_space(self):
        for viewer in ("user2", "user3", "unknown"):
            with self.subTest(viewer=viewer):
                self.assertIsNone(activity.visible_change(change([policy_row()]), "all", PROFILES,
                                                         me=viewer, orders={}))
        for viewer in (None, "matt", "user1"):
            with self.subTest(viewer=viewer):
                shown = activity.visible_change(change([policy_row()]), "all", PROFILES, me=viewer, orders={})
                self.assertEqual(shown["rows"][0]["summary"], "Constructed field membership updated")
                self.assertNotIn(PRIVATE, json.dumps(shown))

    def test_mixed_change_hides_home_words_and_reasons_from_outsider_admin(self):
        mode = {"table": "simulation_mode", "op": "INSERT", "key": {"id": True}, "before": None,
                "after": {"id": True, "mode": "admins", "set_by_name": "Matt"}}
        shown = view([policy_row(), mode], "user3")
        self.assertEqual([row["table"] for row in shown["rows"]], ["simulation_mode"])
        self.assertIsNone(shown["message"])
        self.assertIsNone(shown["reason"])
        self.assertNotIn("field membership", json.dumps(shown))
        self.assertNotIn(PRIVATE, json.dumps(shown))

    def test_changed_actor_never_gives_ownership_access_to_home_policy(self):
        supplied = change([policy_row()])
        supplied["actor"] = "user3"
        self.assertIsNone(activity.visible_change(supplied, permissions.activity_scope(PROFILES["user3"]),
                                                 PROFILES, me="user3", orders={}))

    def test_summary_uses_only_allowlisted_format_words_for_all_operations(self):
        for fmt, label in (("Commander", "Commander"), ("Constructed", "Constructed"),
                           (PRIVATE, "Home"), ([PRIVATE], "Home")):
            for op in ("INSERT", "UPDATE", "DELETE"):
                with self.subTest(fmt=fmt, op=op):
                    shown = view([policy_row(fmt, op)], "matt")
                    verb = "removed" if op == "DELETE" else "updated"
                    self.assertEqual(shown["rows"][0]["summary"], f"{label} field membership {verb}")
                    self.assertNotIn(PRIVATE, json.dumps(shown))

    def test_projection_does_not_mutate_private_input(self):
        supplied = change([policy_row()])
        before = copy.deepcopy(supplied)
        activity.visible_change(supplied, permissions.activity_scope(PROFILES["matt"]), PROFILES,
                                me="matt", orders={})
        self.assertEqual(supplied, before)


if __name__ == "__main__":
    raise SystemExit("Use scripts/test_fixtures.py for protected fixture checks.")
