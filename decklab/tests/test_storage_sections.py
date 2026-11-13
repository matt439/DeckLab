"""Sections from the rule (E8-S25 slice 7, decklab/design/storage-setting.md 2.3): a colour-type
container's holds say which section holds creatures, spells, lands and token cards; home's built-in
box carries Row 1 creatures, Row 2 spells, Row 3 lands, Row 4 token cards. The record's rules, the
in-memory store, the storage show command, storage_setting's place and card groups, Where these go's
and Receive delivery's storage_groups, Build decks' storage_order sections and the CLI merge guide.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_storage_sections
"""
import unittest
from unittest import mock

from decklab.lib import inventory, state, storage_setting
from decklab.lib.api import receipts
from decklab.lib.state import Invalid, space_storage as rules
from decklab.lib.state.memory import MemoryStore
from decklab.tests import test_collection_edit as edit_tests, test_collection_locations as location_tests
from decklab.tests import test_api_permissions as permission_tests, test_receipts_api as receipt_tests
from decklab.tests.test_receive_order import setUpModule, tearDownModule  # noqa: F401 (the receipt tree's card data)

HOME_SECTIONS = location_tests.HOME_SECTIONS
ACTOR = state.Actor("matt", "Matt", "home")
ROWS = ["Row 1", "Row 2", "Row 3", "Row 4"]
BOX = {"id": "box", "name": "Storage box", "kind": "box", "capacity": 2400, "sections": ROWS, "order": "colour-type"}
BINDER = {"id": "binder", "name": "Binder", "kind": "binder", "capacity": 360, "sections": [], "order": "set",
          "sleeved": True}
CARDS = {"Llanowar Elves": {"type_line": "Creature — Elf Druid"},
         "Dryad Arbor": {"type_line": "Land Creature — Forest Dryad"},
         "Fire // Ice": {"type_line": "Instant // Instant"},
         "Ornithopter": {"type_line": "Artifact Creature — Thopter"},
         "Sol Ring": {"type_line": "Artifact"}}


class RuleTests(unittest.TestCase):
    def test_holds_are_kept_in_section_order_matching_sections_ignoring_case(self):
        record = rules.normalize({"containers": [dict(BOX, holds={"row 3": "lands", "Row 1": "creatures",
                                                                  "Row 2": "", "Row 4": None})]})
        self.assertEqual(record["containers"][0]["holds"], {"Row 1": "creatures", "Row 3": "lands"})
        self.assertEqual(list(record["containers"][0]["holds"]), ["Row 1", "Row 3"])
        self.assertEqual(rules.normalize(record), record)                # the saved form is a fixed point

    def test_no_holds_is_none_and_another_order_drops_them(self):
        self.assertEqual(rules.normalize([BOX])["containers"][0]["holds"], {})
        dropped = rules.normalize([dict(BOX, order="set", holds={"Row 1": "creatures", "Nowhere": "lands"})])
        self.assertEqual(dropped["containers"][0]["holds"], {})
        self.assertEqual(rules.group_sections(dict(BOX, order="set", holds={"Row 1": "creatures"})), {})
        self.assertEqual(rules.group_sections(dict(BOX)), {})            # a record saved before slice 7

    def test_bad_holds_are_refused(self):
        for bad in ({"Row 5": "creatures"},                            # not one of its sections
                    {"Row 1": "lands", "Row 2": "lands"},              # a group twice
                    {"Row 1": "artifacts"},                            # not a group
                    {"Row 1": "creatures", "row 1": "spells"},         # a section twice
                    ["Row 1", "creatures"]):                           # not a mapping
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                rules.normalize([dict(BOX, holds=bad)])

    def test_homes_built_in_box_holds_its_rows_groups(self):
        box = rules.builtin_home()["containers"][0]
        self.assertEqual(box["holds"], rules.HOME_ROW_GROUPS)
        self.assertEqual(rules.group_sections(box), HOME_SECTIONS)
        self.assertEqual(rules.normalize(rules.builtin_home()), rules.builtin_home())

    def test_a_cards_group_comes_from_its_front_type_line(self):
        self.assertEqual([rules.card_group(card["type_line"]) for card in CARDS.values()],
                         ["creatures", "lands", "spells", "creatures", "spells"])
        self.assertIsNone(rules.card_group(""))
        self.assertIsNone(rules.card_group(None))

    def test_the_memory_store_saves_and_reads_holds(self):
        store = MemoryStore()
        store.space_storage_put("user2", {"default": "box", "containers": [dict(BOX, holds={"Row 4": "tokens"})]},
                                0, ACTOR, "Row 4 holds token cards")
        self.assertEqual(store.space_storage("user2")["storage"]["containers"][0]["holds"], {"Row 4": "tokens"})


class SettingTests(unittest.TestCase):
    def test_place_has_sections_only_when_the_rule_maps_groups(self):
        self.assertEqual(storage_setting.place(rules.builtin_home())["sections"], HOME_SECTIONS)
        plain = rules.normalize({"default": "box", "containers": [BOX]})
        self.assertNotIn("sections", storage_setting.place(plain))

    def test_card_groups_read_the_card_data_and_never_raise(self):
        with mock.patch("decklab.lib.cards.card", side_effect=CARDS.get):
            self.assertEqual(storage_setting.card_groups(["Llanowar Elves", "Dryad Arbor", "Fire // Ice", "Not A Card", ""]),
                             {"Llanowar Elves": "creatures", "Dryad Arbor": "lands", "Fire // Ice": "spells"})
        with mock.patch("decklab.lib.cards.card", side_effect=RuntimeError("no card data")):
            self.assertEqual(storage_setting.card_groups(["Llanowar Elves"]), {})

    def test_with_groups_adds_them_only_beside_sections(self):
        with mock.patch("decklab.lib.cards.card", side_effect=CARDS.get):
            answer = storage_setting.with_groups({"storage_default": {"name": "Box", "sections": {"lands": "Row 3"}}},
                                                 {"Dryad Arbor"})
            self.assertEqual(answer["storage_groups"], {"Dryad Arbor": "lands"})
            for place in (None, {"name": "Binder", "kind": "binder", "sleeved": True}):
                self.assertNotIn("storage_groups", storage_setting.with_groups({"storage_default": place}, {"Dryad Arbor"}))

    def test_with_groups_names_only_the_cards_its_default_container_holds(self):
        record = rules.normalize({"default": "box", "containers": [dict(BOX, holds=rules.HOME_ROW_GROUPS), BINDER]})
        names = {"Llanowar Elves", "Sol Ring", "Dryad Arbor", "Ornithopter"}
        places = {"Llanowar Elves": ["Binder p3"],              # filed in the binder: no section
                  "Sol Ring": ["Row 2, B"],                      # the box's own row
                  "Ornithopter": ["Attic"]}                      # somewhere else: no section
        with mock.patch("decklab.lib.cards.card", side_effect=CARDS.get):
            answer = storage_setting.with_groups({"storage_default": storage_setting.place(record)}, names,
                                                 record=record, places=places)
            self.assertEqual(answer["storage_groups"], {"Sol Ring": "spells", "Dryad Arbor": "lands"})
            failed = storage_setting.with_groups({"storage_default": storage_setting.place(record)}, names,
                                                 record=record, places=None)
            self.assertEqual(failed["storage_groups"], {})       # the lookup failed: no section is claimed


class StorageCliTests(unittest.TestCase):
    def test_show_lists_what_each_section_holds(self):
        from decklab.db import storage_cli
        view = {"space": "home", "revision": None, "ready": True, "source": "default", "storage": rules.builtin_home()}
        lines = storage_cli.describe(view)
        self.assertIn("      holds: Row 1 creatures, Row 2 spells, Row 3 lands, Row 4 token cards", lines)
        view["storage"] = rules.normalize({"default": "box", "containers": [BOX]})
        self.assertFalse(any("holds:" in line for line in storage_cli.describe(view)))

    def test_the_merge_guide_says_each_cards_section(self):
        from decklab.db import inv_collection
        guide = {"storage_default": {"name": "Storage box", "sections": HOME_SECTIONS},
                 "storage_groups": {"Llanowar Elves": "creatures"}}
        self.assertEqual(inv_collection._merge_section(guide, "Llanowar Elves"), " in Row 1 (creatures)")
        self.assertEqual(inv_collection._merge_section(guide, "Sol Ring"), "")
        self.assertEqual(inv_collection._merge_section({"storage_default": None}, "Llanowar Elves"), "")


class FilingTests(edit_tests.CollectionEditTestCase):
    """Where these go's storage_groups and Build decks' storage_order sections, from the space's own setup."""
    setup = location_tests.StorageSetupTests.setup

    def guide(self, space, names=("Llanowar Elves",)):
        from decklab.lib.api import collection_filing
        added = [{"name": name} for name in names]
        destinations = [{"kind": "storage", "row": n, "quantity": 1} for n in range(len(added))]
        with mock.patch("decklab.lib.cards.card", side_effect=CARDS.get):
            return collection_filing._with_locations({"added": added, "destinations": destinations},
                                                     inventory.current(), space)

    def test_homes_built_in_box_gives_each_storage_card_its_group(self):
        answer = self.guide("home", ("Llanowar Elves", "Sol Ring", "Not A Card"))
        self.assertEqual(answer["storage_default"]["sections"], HOME_SECTIONS)
        self.assertEqual(answer["storage_groups"], {"Llanowar Elves": "creatures", "Sol Ring": "spells"})

    def test_a_setup_without_holds_or_a_member_space_adds_nothing(self):
        self.assertNotIn("storage_groups", self.guide("user2"))
        self.setup("user2", default="box", containers=[dict(BOX, name="Shoebox", holds={"Row 2": "creatures"})])
        member = self.guide("user2")
        self.assertEqual(member["storage_default"]["sections"], {"creatures": "Row 2"})
        self.assertEqual(self.guide("home")["storage_default"]["sections"], HOME_SECTIONS)   # never another space's
        self.setup(default="box", containers=[BOX])
        home = self.guide("home")
        self.assertNotIn("sections", home["storage_default"])
        self.assertNotIn("storage_groups", home)

    locate = location_tests.StorageSetupTests.locate

    def test_a_card_filed_in_another_container_gets_no_section(self):
        self.setup(default="box", containers=[dict(BOX, holds=rules.HOME_ROW_GROUPS), BINDER])
        self.assertEqual(self.guide("home", ("Llanowar Elves", "Sol Ring"))["storage_groups"],
                         {"Llanowar Elves": "creatures", "Sol Ring": "spells"})
        self.locate("Binder p3")
        answer = self.guide("home", ("Llanowar Elves", "Sol Ring"))
        self.assertEqual(answer["storage_groups"], {"Sol Ring": "spells"})
        self.assertEqual(answer["storage_locations"]["cards"]["Llanowar Elves"]["places"], ["Binder p3"])
        self.locate("Row 1")
        self.assertEqual(self.guide("home")["storage_groups"], {"Llanowar Elves": "creatures"})
        from decklab.lib.api import storage_places
        with mock.patch.object(storage_places, "by_name", side_effect=RuntimeError("lookup failed")):
            self.assertEqual(self.guide("home")["storage_groups"], {})      # unknown: no section claimed

    def test_build_decks_storage_order_carries_the_sections(self):
        from decklab.lib.api import assembly_locations
        self.assertEqual(assembly_locations.storage_order(inventory.current(), set())["sections"], HOME_SECTIONS)
        self.setup(default="box", containers=[dict(BOX, holds={"Row 3": "lands"})])
        self.assertEqual(assembly_locations.storage_order(inventory.current(), set())["sections"], {"lands": "Row 3"})
        self.setup(default="box", containers=[BOX])
        self.assertNotIn("sections", assembly_locations.storage_order(inventory.current(), set()))


class StorageApiTests(permission_tests.PermissionTestCase):
    def test_holds_save_and_read_back_and_bad_ones_are_a_400(self):
        from decklab.lib import access
        from decklab.lib.api import storage as storage_api
        with access.using(None):
            home = storage_api.view()
            self.assertEqual(home["storage"]["containers"][0]["holds"], rules.HOME_ROW_GROUPS)
            self.assertEqual(home["groups"], ["creatures", "spells", "lands", "tokens"])
        with access.using({"profile": "user2", "email": "", "remote": True}):
            body = lambda storage, expect=0: self.body("user2", space="user2", expect=expect, storage=storage)  # noqa: E731
            shoebox = dict(BOX, name="Shoebox", holds={"Row 1": "lands"})
            saved = storage_api.change(body({"default": "box", "containers": [shoebox]}))
            self.assertEqual(saved["storage"]["containers"][0]["holds"], {"Row 1": "lands"})
            self.assertEqual(storage_api.view("user2")["storage"]["containers"][0]["holds"], {"Row 1": "lands"})
            self.assertApiError(400, lambda: storage_api.change(body({"containers": [dict(shoebox, holds={"Row 9": "lands"})]}, 1)))
            self.assertApiError(400, lambda: storage_api.preview(body({"containers": [dict(shoebox, holds={"Row 1": "x"})]})))


class ReceiptTests(receipt_tests.FilesReceiptCase):
    def test_the_view_gives_the_cards_groups_beside_homes_sections(self):
        view = receipts.receipt_view("test")
        self.assertEqual(view["storage_default"]["sections"], HOME_SECTIONS)
        self.assertEqual(view["storage_groups"], {"Llanowar Elves": "creatures"})   # the cards component's names
        binder = {"name": "Binder", "kind": "binder", "sleeved": True}
        with mock.patch.object(receipts.storage_setting, "default_place", return_value=binder):
            self.assertNotIn("storage_groups", receipts.receipt_view("test"))

    def test_a_card_filed_in_another_container_gets_no_section(self):
        record = rules.normalize({"default": "box", "containers": [dict(BOX, holds=rules.HOME_ROW_GROUPS), BINDER]})
        with mock.patch.object(receipts.storage_setting, "default_record", return_value=record),                 mock.patch.object(receipts.storage_places, "by_name", return_value={"Llanowar Elves": ["Binder p3"]}):
            self.assertEqual(receipts.receipt_view("test")["storage_groups"], {})
        with mock.patch.object(receipts.storage_places, "by_name", side_effect=RuntimeError("lookup failed")):
            self.assertEqual(receipts.receipt_view("test")["storage_groups"], {})


if __name__ == "__main__":
    unittest.main()
