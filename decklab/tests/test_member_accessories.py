"""E8-S26: a member (a person with their own space) records their own sleeves, deck boxes and
playmats and chooses them for their own decks, and nobody else's kit crosses between spaces.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_member_accessories
"""
import json
import unittest
from unittest import mock

from decklab.lib import access, accessories, config, inventory, permissions
from decklab.lib.api import accessories as api_acc, guard
from decklab.lib.api.common import ApiError
from decklab.tests.test_api_accessories import AccessoriesApiTestCase, BLACK, BOX_ROW, SLEEVES
from decklab.tests.test_accessories import PROFILES, deck_md
from decklab.tests.test_accessory_fetch import png

ELVES = "user2/casual/elves"
USER3 = {"id": "user3", "name": "User3", "role": "member", "space": "user3"}
WITH_USER3 = {"profiles": PROFILES["profiles"] + [USER3]}
BY_ID = {p["id"]: p for p in WITH_USER3["profiles"]}
HIS = {**SLEEVES, "owner": "user2", "brand": "KMC", "name": "Hyper Matte", "colour": "green", "quantity": 50}
HIS_ID = "user2-kmc-hyper-matte-green"


def member_deck(title, **kwargs):
    """A deck in User2's own space: no Played by line (it's his by where it's kept)."""
    return deck_md(title, **kwargs).replace("- **Played by:** either\n", "")


class MemberAccessoryTests(AccessoriesApiTestCase):

    def setUp(self):
        super().setUp()
        (self.root / "config.json").write_text(json.dumps(WITH_USER3), encoding="utf-8")
        patcher = mock.patch.object(api_acc, "_writer", lambda data: dict(BY_ID[data.get("profile")]))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(config.CONFIG_FILE, self.root / "config.json")
        self.write("people/user2/decks/casual/elves.md", member_deck("Elves"))
        self.add()                                              # home's shared black sleeves, by Matt

    def as_user2(self, function, **data):
        with access.viewing("user2"):
            return self.call(function, profile="user2", **data)

    def add_his(self, row=HIS):
        return self.as_user2(api_acc.save_accessory, sha256=self.view("user2")["sha256"], action="add", row=row)

    def his_sha(self):
        return inventory.current().deck(ELVES).sha256

    def test_a_member_records_his_own_kit_seen_only_by_him(self):
        self.assertEqual(self.view("user2")["owners"], [{"id": "user2", "name": "User2"}])
        self.assertEqual(self.view("user2")["items"], [])               # none of home's rows
        answer = self.add_his()
        self.assertEqual(answer["changed_id"], HIS_ID)
        mine = self.view("user2")
        self.assertEqual([(i["id"], i["editable"]) for i in mine["items"]], [(HIS_ID, True)])
        self.assertEqual([o["id"] for o in mine["holders_options"]], [ELVES])
        for who in ("matt", "user1"):
            self.assertNotIn(HIS_ID, [i["id"] for i in self.view(who)["items"]], who)
            self.assertNotIn(ELVES, [o["id"] for o in self.view(who)["holders_options"]], who)

    def test_a_member_cant_give_a_row_to_the_shared_kit_or_anyone_else(self):
        for owner in ("shared", "matt", "user1"):
            with self.subTest(owner=owner), access.viewing("user2"), self.assertRaises(ApiError):
                self.call(api_acc.save_accessory, profile="user2", sha256=self.view("user2")["sha256"],
                          action="add", row={**HIS, "owner": owner})
        with access.viewing("user2"), self.assertRaises(ApiError):     # home's row: as if it weren't there
            self.call(api_acc.save_accessory, profile="user2", sha256=self.view("user2")["sha256"],
                      action="edit", id=BLACK, row={"quantity": 1})

    def test_his_deck_takes_his_own_kit_and_is_checked_as_homes(self):
        self.add_his()
        self.as_user2(api_acc.assign_accessory, holder=ELVES, field="sleeves", id=HIS_ID,
                      holder_sha256=self.his_sha())
        self.assertIn(f"- **Sleeves:** {HIS_ID}", inventory.current().deck(ELVES).text)
        kit = accessories.kit(ELVES)
        self.assertEqual((kit["owner"], kit["need"], kit["short"]), ("user2", 60, 10))
        self.assertTrue(any("Not enough sleeves" in w for w in kit["warnings"]))
        label = accessories.label(accessories.read().rows_by_id[HIS_ID])
        self.assertEqual(accessories.check(), [f"Elves needs 60 sleeves and {label} has 50"])
        with access.viewing("user2"):
            self.assertTrue(guard.sees_kit(ELVES))
        with access.viewing("matt"):
            self.assertFalse(guard.sees_kit(ELVES))

    def test_his_deck_never_takes_homes_kit_nor_home_decks_his(self):
        self.add_his()
        with access.viewing("user2"), self.assertRaises(ApiError) as caught:
            self.call(api_acc.assign_accessory, profile="user2", holder=ELVES, field="sleeves", id=BLACK,
                      holder_sha256=self.his_sha())
        self.assertIn(caught.exception.status, (400, 403, 404))
        with access.viewing("matt"), self.assertRaises(ApiError) as caught:
            self.assign("casual/gruul", HIS_ID)
        self.assertIn(caught.exception.status, (400, 403, 404))
        with access.viewing("matt"), self.assertRaises(ApiError) as caught:
            self.call(api_acc.assign_accessory, holder=ELVES, field="sleeves", id=BLACK, holder_sha256=self.his_sha())
        self.assertEqual(caught.exception.status, 404)                 # his deck isn't Matt's to see
        self.assertNotIn("Sleeves", inventory.current().deck(ELVES).text)

    def test_check_flags_shared_or_home_kit_on_a_members_deck(self):
        self.write("people/user2/decks/casual/elves.md", member_deck("Elves", sleeves=BLACK))
        self.assertEqual(accessories.check(), [
            "Elves: Sleeves Dragon Shield Matte (black) are shared: User2's deck uses only User2's own."])

    def test_his_deck_box_counts_only_against_his_own_box(self):
        self.as_user2(api_acc.save_accessory, sha256=self.view("user2")["sha256"], action="add",
                      row={**BOX_ROW, "owner": "user2"})
        box = next(i["id"] for i in self.view("user2")["items"] if i["kind"] == "deck_box")
        self.as_user2(api_acc.assign_accessory, holder=ELVES, field="deck_box", id=box, holder_sha256=self.his_sha())
        self.assertIn(f"- **Deck box:** {box}", inventory.current().deck(ELVES).text)
        self.assertEqual(accessories.check(), [])

    def test_his_kit_is_private_from_home_and_other_members(self):
        # His sleeves with a photo, on his deck: Matt (an admin), User1 and User3 (another member) see no
        # trace of them, the row, its picture, his deck or its kit, in any answer that lists accessories.
        self.as_user2(api_acc.save_accessory, sha256=self.view("user2")["sha256"], action="add", row=HIS,
                      image=self.staged(png()))
        self.as_user2(api_acc.assign_accessory, holder=ELVES, field="sleeves", id=HIS_ID,
                      holder_sha256=self.his_sha())
        mine = next(i for i in self.view("user2")["items"] if i["id"] == HIS_ID)
        self.assertTrue(mine["image_url"])
        self.assertEqual([u["holder"] for u in mine["used_by"]], [ELVES])
        name, version = mine["image_url"].split("/accessory-img/")[1].split("#")[0].split("?v=")
        with access.viewing("user2"), inventory.pinned():
            self.assertTrue(api_acc.image_file(name, version)[0])
        for who in ("matt", "user1", "user3"):
            with self.subTest(who=who):
                seen = json.dumps(self.view(who))
                for words in (HIS_ID, "Hyper Matte", "KMC", "User2", "user2", "Elves", name):
                    self.assertNotIn(words, seen)
                with access.viewing(who), inventory.pinned(), self.assertRaises(ApiError) as caught:
                    api_acc.image_file(name, version)
                self.assertEqual(caught.exception.status, 404)
                with access.viewing(who):
                    self.assertFalse(guard.sees_kit(ELVES))
                # Changing it, choosing it, or taking it off his deck: answered as for a row that isn't there.
                with access.viewing(who), self.assertRaises(ApiError) as caught:
                    self.call(api_acc.save_accessory, profile=who, sha256=self.view(who)["sha256"],
                              action="edit", id=HIS_ID, row={"quantity": 1})
                self.assertIn(caught.exception.status, (403, 404))
                self.assertNotIn("Hyper Matte", str(caught.exception))
                with access.viewing(who), self.assertRaises(ApiError) as caught:
                    self.call(api_acc.assign_accessory, profile=who, holder=ELVES, field="sleeves", id=None,
                              holder_sha256=self.his_sha())
                self.assertEqual(caught.exception.status, 404)
        # User3 has his own, empty list, and gets none of home's shared rows either.
        self.assertEqual(self.view("user3")["items"], [])
        self.assertEqual(self.view("user3")["owners"], [{"id": "user3", "name": "User3"}])
        self.assertIn(f"- **Sleeves:** {HIS_ID}", inventory.current().deck(ELVES).text)

    def test_the_same_product_gets_no_hint_of_anothers_row(self):
        # His row and then Matt's and User3's of the same product: each id starts with its owner's, so no
        # one's comes back with a -2 that would tell them someone else has one.
        self.add_his()
        matt = self.add({**HIS, "owner": "matt"})["changed_id"]
        with access.viewing("user3"):
            his_neighbour = self.call(api_acc.save_accessory, profile="user3", sha256=self.view("user3")["sha256"],
                                      action="add", row={**HIS, "owner": "user3"})["changed_id"]
        shared = self.add({**HIS, "owner": "shared"})["changed_id"]
        self.assertEqual((matt, his_neighbour, shared),
                         ("matt-kmc-hyper-matte-green", "user3-kmc-hyper-matte-green", "kmc-hyper-matte-green"))
        self.assertEqual(accessories.new_id({**HIS, "owner": "matt"}, {matt}), "matt-kmc-hyper-matte-green-2")

    def test_owner_rules(self):
        member = {"id": "user2", "space": "user2", "role": "member"}
        self.assertEqual(permissions.accessory_owners(member), {"user2"})
        self.assertTrue(permissions.can(member, "accessories.edit"))
        self.assertEqual(accessories.deck_owner("user2", None), "user2")
        self.assertEqual(accessories.uses_words("user2"), "only User2's own")
        self.assertEqual(accessories.uses_words("user1"), "only User1's or shared ones")


if __name__ == "__main__":
    unittest.main()
