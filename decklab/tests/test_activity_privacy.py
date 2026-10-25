"""E10-S34: own-space Activity, admin system rows and all-rows-readable words.

Synthetic audit rows run through the same MemoryStore filtering, cap and projection as the
web API. These tests never connect to the live inventory or change its data.
"""
import json
import unittest
from unittest import mock

from decklab.lib import permissions
from decklab.lib.api import activity, guard
from decklab.lib.state import rules
from decklab.tests.test_activity import (
    ADMIN, ALL, BY_ID, EMAIL_ROW, FUTURE_ROW, HOME, PROFILE_ROW, USER2S, SPACE_ROW,
    _Store, _card_row, _change, _deck, _row,
)


class ActivityPrivacyTests(_Store):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(activity, "row_cards", return_value={}),
                        mock.patch.object(activity, "_load_orders", return_value={})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def seed(self, *changes):
        self.store._changes = list(changes)       # fixture-only rows shaped like PostgreSQL audit

    def test_public_collections_and_decks_never_widen_activity(self):
        cards = _card_row("user2", "Private card", 1)
        deck = _row("deck", "INSERT", {"id": "user2/casual/a"},
                    after=_deck("user2", "user2/casual/a", title="Private deck"))
        self.seed(_change([cards, deck], actor="claude", source="cli", message="Private import"))
        with mock.patch.object(permissions, "inventory_spaces", return_value=None), \
                mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})):
            for viewer in ("matt", "user1"):
                self.assertEqual(self.view(viewer)["changes"], [], viewer)
            own = self.view("user2")["changes"][0]
            self.assertEqual({r["table"] for r in own["rows"]}, {"collection_card", "deck"})
            script = self.view()
            self.assertTrue(script["everything"])
            self.assertEqual(script["changes"][0]["message"], "Private import")

    def test_admin_system_rows_and_genuinely_empty_changes_remain_visible(self):
        self.seed(_change([SPACE_ROW, PROFILE_ROW, EMAIL_ROW, FUTURE_ROW], change_id=1),
                  _change([], message="System maintenance", change_id=2))
        admin = self.view("matt")
        self.assertFalse(admin["everything"])
        self.assertEqual(len(admin["changes"]), 2)
        self.assertEqual(admin["changes"][0]["message"], "System maintenance")
        rows = admin["changes"][1]["rows"]
        self.assertEqual({r["table"] for r in rows}, {"space", "profile", "profile_email", "deck_line"})
        self.assertNotIn("example.com", json.dumps(admin))
        for viewer in ("user1", "user2"):
            self.assertEqual(self.view(viewer)["changes"], [], viewer)

    def test_a_filtered_whole_change_is_not_an_empty_system_change(self):
        self.seed(_change([_card_row("user2", "Private card", 1)], actor="claude", source="cli"))
        self.assertEqual(self.view("matt")["changes"], [])
        self.assertEqual(len(self.view()["changes"]), 1)

    def test_web_and_cli_mixed_messages_and_reasons_are_hidden_even_from_actor_and_admin(self):
        rows = [_card_row("home", "Opt", 1), _card_row("user2", "Secret card", 2)]
        for source in ("web", "cli"):
            for actor in ("matt", "user1", "user2", "claude"):
                with self.subTest(source=source, actor=actor):
                    self.seed(_change(rows, actor, source, "Opt and Secret card", "Private reason"))
                    for viewer in ("matt", "user1", "user2"):
                        change = self.view(viewer)["changes"][0]
                        self.assertEqual((change["message"], change["reason"]), (None, None), viewer)
                        self.assertEqual(len(change["rows"]), 1)
                    script = self.view()["changes"][0]
                    self.assertEqual((script["message"], script["reason"]),
                                     ("Opt and Secret card", "Private reason"))

    def test_a_mixed_update_all_masks_titles_from_web_and_cli(self):
        rows = [_row("deck", "UPDATE", {"id": deck_id},
                     before=_deck(space, deck_id, title=title),
                     after=_deck(space, deck_id, title=title, revision=2))
                for space, deck_id, title in (("home", "casual/a", "Visible deck"),
                                               ("user2", "user2/casual/a", "Private deck"))]
        for source in ("web", "cli"):
            with self.subTest(source=source):
                self.seed(_change(rows, "matt", source, "Update Visible deck and Private deck", "Both tables"))
                shown = self.view("matt")["changes"][0]
                self.assertEqual((shown["message"], shown["reason"]), (None, None))
                self.assertNotIn("Private deck", json.dumps(shown))
                self.assertEqual(len(shown["rows"]), 1)

    def test_visible_capped_rows_and_groups_count_towards_the_whole_change(self):
        payload = [_row("order_card_item", "INSERT", {"order_id": "o", "component_id": "cards", "position": i},
                        after={"quantity": 1}) for i in range(3)]
        home = [_card_row("home", f"Card {i}", i) for i in range(3)]
        with mock.patch.object(activity, "ROW_CAP", 1):
            for extra in ([], [_card_row("user2", "Private card", 9)]):
                self.seed(_change(home + payload + extra, "matt", "web", "Words", "Reason"))
                shown = self.view("matt")["changes"][0]
                self.assertEqual((shown["message"], shown["reason"]),
                                 (None, None) if extra else ("Words", "Reason"))
                self.assertTrue(any(r["summary"] == "and 2 more" for r in shown["rows"]))
                self.assertTrue(any("3 card rows" in r["summary"] for r in shown["rows"]))

    def test_admin_system_access_cannot_open_an_orphan_setting(self):
        orphan = _row("profile_setting", "INSERT", {},
                      after={"profile_id": "removed", "key": "theme", "value": "dark"})
        self.seed(_change([orphan], actor="removed", source="web"))
        self.assertEqual(self.view("matt")["changes"], [])
        self.assertEqual(len(self.view()["changes"]), 1)


class VisibilityActivityTests(unittest.TestCase):
    def change(self, owner, thing, op="INSERT", **extra):
        record = {"owner": owner, "thing": thing, "set_by": "matt", "set_by_name": "Matt", "since": "yesterday"}
        row = _row("visibility", op, {"owner": owner, "thing": thing},
                   **{"before" if op == "DELETE" else "after": record})
        return _change([row], "matt", "web", "Switch changed", **extra)

    def test_only_the_switch_space_sees_it_even_for_an_admin(self):
        change = self.change("user2", "decks")
        self.assertIsNone(activity.visible_change(change, ADMIN, BY_ID))
        self.assertIsNone(activity.visible_change(change, HOME, BY_ID))
        own = activity.visible_change(change, USER2S, BY_ID)
        self.assertEqual(own["rows"][0]["summary"], "Made your decks public")
        self.assertEqual(own["rows"][0]["after"],
                         {"owner": "user2", "thing": "decks", "set_by_name": "Matt"})
        self.assertEqual(own["kinds"], ["settings"])
        script = activity.visible_change(change, ALL, BY_ID)
        self.assertEqual(script["rows"][0]["summary"], "Made User2's decks public")

    def test_home_space_and_every_accessory_flip_belong_to_home(self):
        for owner, thing in (("home", "collection"), ("home", "games"), ("home", "decks"),
                             ("matt", "accessories"), ("user1", "accessories"), ("shared", "accessories")):
            for op, state in (("INSERT", "public"), ("DELETE", "private")):
                change = self.change(owner, thing, op)
                with self.subTest(owner=owner, thing=thing, op=op):
                    for scope in (ADMIN, HOME, ALL):
                        shown = activity.visible_change(change, scope, BY_ID)
                        self.assertTrue(shown["rows"][0]["summary"].endswith(state))
                    self.assertIsNone(activity.visible_change(change, USER2S, BY_ID))

    def test_mixed_switch_and_private_rows_hide_messages(self):
        change = self.change("home", "decks", reason="Private reason")
        change["rows"].append(_card_row("user2", "Secret card", 1))
        shown = activity.visible_change(change, ADMIN, BY_ID)
        self.assertEqual((shown["message"], shown["reason"]), (None, None))
        self.assertEqual(len(shown["rows"]), 1)


class ModuleSplitTests(unittest.TestCase):
    """activity.py's summaries and headlines live in activity_summaries and activity_headlines;
    the names the tests patch on activity must have no second binding there."""

    def test_patched_names_have_one_home(self):
        from decklab.lib.api import activity_headlines, activity_summaries
        for name in ("row_cards", "_load_orders", "ROW_CAP", "OrderFacts"):
            self.assertIn(name, vars(activity), name)
            self.assertNotIn(name, vars(activity_summaries), name)
            self.assertNotIn(name, vars(activity_headlines), name)
        self.assertIs(activity.OrderFacts.__init__.__globals__, vars(activity))

    def test_callers_names_stay_importable(self):
        for name in ("activity_view", "visible_change", "inventory_spec", "scope_spaces", "describe", "KINDS",
                     "ACTOR_NAMES", "SOMEONE", "INVENTORY_FIELDS", "ITEM_TABLES", "card_key"):
            self.assertTrue(hasattr(activity, name), name)


if __name__ == "__main__":
    unittest.main()
