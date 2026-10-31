"""The Tokens page's dice and counters API (E7-S24): GET /api/dice and POST /api/dice/save, with
the token cards' privacy (only the space's own people read or change them, no admin override), and
the deck page's counter needs marked covered or not. Runs in test_api_permissions' sandbox (the files
backend, a roles config with User2's space).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_dice_counters_api
"""
import contextlib
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import deck_page, dice
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import dice_rules
from decklab.lib.state import Invalid
from decklab.tests import test_api_permissions as permission_tests

D20 = {"type": "die", "size": "d20", "design": "red", "quantity": 2}
POISON = {"type": "counter", "kind": "poison", "quantity": 5}


class DiceApiTests(permission_tests.PermissionTestCase):
    READERS = ("matt", "user1", "user2", "stranger", "local", "local:user1", "local:user2")
    HOME = {"matt", "user1", "local", "local:user1"}
    USER2 = {"user2", "local", "local:user2"}

    def as_(self, who):
        stack = contextlib.ExitStack()
        if who.startswith("local"):
            named = who.partition(":")[2] or None
            stack.enter_context(access.using(None))
            stack.enter_context(access.viewing(named))
            return stack
        stack.enter_context(access.using({"profile": who, "email": "", "remote": True}))
        return stack

    def readable(self, call, allowed):
        got = {}
        for who in self.READERS:
            with self.as_(who):
                try:
                    call()
                    got[who] = True
                except ApiError as e:
                    got[who] = e.status != 403
        self.assertEqual(got, {who: who in allowed for who in self.READERS})

    def save(self, profile, **body):
        return dice.save_dice(self.body(profile, **body))

    def test_reading_follows_the_spaces_inventory(self):
        self.readable(lambda: dice.dice_view(), self.HOME)
        self.readable(lambda: dice.dice_view("user2"), self.USER2)
        with self.as_("matt"):
            error = self.assertApiError(403, dice.dice_view, "user2")
            self.assertEqual(error.message, "That collection isn't public.")      # names no one

    def test_writing_needs_tokens_edit_on_the_space(self):
        self.check(lambda p: self.save(p, action="add", sha256=None, row=D20), {"matt", "user1", "local", "script"})
        self.check(lambda p: self.save(p, space="user2", action="add", sha256=None, row=POISON), {"user2"})

    def test_add_edit_conflict_and_remove(self):
        with access.using(None):
            view = dice.dice_view()
            self.assertEqual((view["ready"], view["rows"], view["sha256"]), (True, [], None))
            answer = self.save("matt", action="add", sha256=None, row=D20)
            self.assertEqual((answer["index"], answer["data"]["items"]), (0, 2))
            row = answer["data"]["rows"][0]
            self.assertEqual((row["label"], row["quantity"]), ("d20 (red)", 2))
            sha = answer["data"]["sha256"]
            base = {key: str(row[key]) for key in dice_rules.DICE_FIELDS}
            # A stale list answers 409 with the list as it is now.
            stale = self.assertApiError(409, lambda: self.save("matt", action="add", sha256=None, row=POISON))
            self.assertEqual(stale.extra["latest"]["sha256"], sha)
            same = self.assertApiError(409, lambda: self.save("matt", action="add", sha256=sha, row={**D20, "quantity": 1}))
            self.assertEqual(same.extra["same_index"], 0)
            self.assertApiError(400, lambda: self.save("matt", action="add", sha256=sha, row={**D20, "size": "d7"}))
            edited = self.save("matt", action="edit", sha256=sha, base=base, row={"quantity": 4})
            self.assertEqual(edited["data"]["rows"][0]["quantity"], 4)
            removed = self.save("matt", action="remove", sha256=edited["data"]["sha256"],
                                base={**base, "quantity": "4"}, reason="lost")
            self.assertEqual((removed["index"], removed["data"]["rows"]), (None, []))
            # Token cards and the collection are untouched.
            self.assertFalse((self.box.magic / "dice.csv").exists())

    def test_before_migration_0020_the_view_says_so_and_writes_refuse(self):
        current = inventory.current

        def not_ready():
            return current().replace(dice_ready=False)
        with access.using(None), mock.patch.object(inventory, "current", not_ready):
            view = dice.dice_view()
            self.assertEqual((view["ready"], view["note"]), (False, dice_rules.DICE_REQUIRED))
        with access.using(None), mock.patch.object(inventory, "apply", side_effect=Invalid(dice_rules.DICE_REQUIRED)):
            error = self.assertApiError(409, lambda: self.save("matt", action="add", sha256=None, row=D20))
            self.assertEqual(error.extra["reason"], "migration")

    def test_the_deck_pages_counter_needs_are_marked(self):
        with access.using(None):
            self.save("matt", action="add", sha256=None, row=POISON)
        needs = {"needs": [{"key": "poison", "group": "player"}, {"key": "lore", "group": "permanent"}], "note": ""}
        found = deck_page._with_dice({"needs": [], "counters": needs}, "home")
        self.assertEqual([n["cover"]["state"] for n in found["counters"]["needs"]], ["named", "none"])
        self.assertNotIn("cover", needs["needs"][0])
        # Another space's owned items never reach it.
        other = deck_page._with_dice({"counters": needs}, "user2")
        self.assertEqual(other["counters"]["owned"]["counters"], 0)
        self.assertEqual(deck_page._with_dice({"error": "x"}, "home"), {"error": "x"})
