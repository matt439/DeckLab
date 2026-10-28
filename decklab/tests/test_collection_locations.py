"""Storage locations on collection rows (E8-S22) and the storage box's count (E8-S19), on the files
backend: the rule, the operations (a location set, kept, moved with its row and gone with it), the
Collection page's answers and card-sheet save, Build decks' storage_locations, and the command
line's collection edit --location and collection locations. The database's column (migration
0016), and the schema before it, are test_collection_locations_pg's.

Run from the repo root: python -m unittest decklab.tests.test_collection_locations
"""
import contextlib
import io
from types import SimpleNamespace
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.api import assembly_locations, collection_edit as ce, collection_locations as places
from decklab.lib.inventory import rules
from decklab.tests.test_collection_edit import CollectionEditTestCase

ELVES = {"set": "fdn", "collector_number": "227", "finish": "nonfoil"}


class LocationRuleTests(CollectionEditTestCase):

    def test_clean_location_tidies_and_refuses(self):
        self.assertEqual(rules.clean_location("  Row 2,   B "), "Row 2, B")
        self.assertEqual(rules.clean_location(""), "")
        self.assertEqual(rules.clean_location(None), "")
        for bad in ("x" * 41, "Row\t2", "Row\n2", "=SUM(A1)", "@home", 3):
            with self.assertRaises(ValueError, msg=repr(bad)):
                rules.clean_location(bad)


class LocationOpTests(CollectionEditTestCase):

    def edit(self, location=None, **row):
        current = next(r for r in self.rows()["rows"] if r["set"] == "fdn" and r["collector_number"] == "227")
        body = {"action": "edit", "row": {**current, **row}, "original": ELVES}
        if location is not None:
            body["location"] = location
        return self.save(**body)

    def test_a_location_is_saved_beside_the_row_and_keeps_the_rows_sha(self):
        before = self.edit(location="Row 1")         # the fixture's file is rewritten in Deck Lab's order first
        self.writes.clear()
        answer = self.edit(location=" Row 2,  B ")
        self.assertEqual(answer["locations"], {"ready": True, "rows": {"fdn|227|nonfoil": "Row 2, B"}})
        self.assertEqual(answer["sha256"], before["sha256"])         # the eight columns didn't change
        self.assertEqual((self.box.magic / "locations.csv").read_text(encoding="utf-8"),
                         'set,collector_number,finish,location\nfdn,227,nonfoil,"Row 2, B"\n')
        self.assertEqual(self.last_write()[0], "edit card Llanowar Elves (FDN 227) in the home collection")
        self.assertEqual(self.extra(), ["Storage location: Row 2, B."])
        self.assertEqual(len(self.writes), 1)                        # one change

    def test_an_edit_without_a_location_keeps_it_and_a_new_printing_takes_it(self):
        self.edit(location="Binder")
        self.edit(quantity="3")
        self.assertEqual(self.rows()["locations"]["rows"], {"fdn|227|nonfoil": "Binder"})
        self.edit(finish="foil")
        self.assertEqual(self.rows()["locations"]["rows"], {"fdn|227|foil": "Binder"})

    def test_clearing_and_removing(self):
        self.edit(location="Row 1")
        self.edit(location="")
        self.assertEqual(self.rows()["locations"]["rows"], {})
        self.assertFalse((self.box.magic / "locations.csv").exists())
        lotus = {"set": "lea", "collector_number": "232", "finish": "nonfoil"}
        self.save(action="edit", original=lotus, location="Row 4", row={"name": "Black Lotus", **lotus,
                  "quantity": "1", "condition": "NM", "language": "en", "notes": ""})
        self.assertEqual(self.rows()["locations"]["rows"], {"lea|232|nonfoil": "Row 4"})
        try:
            self.save(action="remove", original=lotus, reason="traded")
        except ce.ApiError as e:                                    # held by a built deck: confirmed
            self.save(action="remove", original=lotus, reason="traded", confirm_in_use=e.extra["confirm_in_use"])
        self.assertEqual(self.rows()["locations"]["rows"], {})
        self.assertFalse((self.box.magic / "locations.csv").exists())

    def test_a_merge_keeps_locations(self):
        self.edit(location="Row 3, C")
        self.save(action="add", row={"name": "Llanowar Elves", "set": "fdn", "collector_number": "227",
                                     "finish": "nonfoil", "quantity": "1"})
        self.assertEqual(self.rows()["locations"]["rows"], {"fdn|227|nonfoil": "Row 3, C"})

    def test_an_add_may_set_its_location(self):
        self.save(action="add", location="Binder", row={"name": "Llanowar Elves", "set": "fdn",
                                                         "collector_number": "227", "finish": "foil", "quantity": "1"})
        self.assertEqual(self.rows()["locations"]["rows"], {"fdn|227|foil": "Binder"})

    def test_a_bad_location_is_refused_with_nothing_saved(self):
        before = self.magic_files()
        self.assertApiError(400, self.edit, location="=1+1", contains="formula")
        self.assertApiError(400, self.edit, location="x" * 41, contains="40")
        self.assertEqual(self.magic_files(), before)

    def test_without_the_migration_the_page_still_works_and_a_location_is_refused(self):
        loaded = self.backend.load

        def old_schema():
            return loaded().replace(locations_ready=False)
        with mock.patch.object(self.backend, "load", old_schema):
            view = self.rows()
            self.assertEqual(view["locations"], {"ready": False, "rows": {}})
            self.assertApiError(409, self.edit, location="Row 1", contains="migration 0016")
            self.edit(quantity="5")                                   # other edits go on
            self.edit(location="")                                    # a blank one isn't a location
        self.assertEqual(self.rows()["rows"][1]["quantity"], "5")

    def test_another_space_cant_read_or_set_home_locations(self):
        with self.as_("user2"):
            self.assertApiError(403, self.rows, "home")
            self.assertApiError(403, self.edit, location="Row 1")


class StorageBoxTests(CollectionEditTestCase):

    def test_home_gets_the_box_count_and_a_person_doesnt(self):
        box = self.rows()["storage_box"]
        self.assertEqual(set(box), {"cards", "capacity", "over", "not_counted", "elsewhere"})
        self.assertEqual(box["capacity"], 2400)
        with self.as_("user2"):
            self.assertIsNone(self.rows("user2")["storage_box"])

    def test_count_leaves_out_held_copies_and_basic_lands(self):
        rows = [{"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil", "quantity": "4"},
                {"name": "Forest", "set": "fdn", "collector_number": "280", "finish": "foil", "quantity": "3"}]
        storage = {"error": None, "rows": {"fdn|227|nonfoil": {"held": 1, "guess": False},
                                           "fdn|280|foil": {"held": None, "guess": False}}}
        box = places.storage_box("home", rows, storage, ce._picture_key)
        self.assertEqual(box, {"cards": 3, "capacity": 2400, "over": False, "not_counted": 3, "elsewhere": 0})
        with mock.patch.object(config, "load", return_value={"storage_box_capacity": 2}):
            self.assertTrue(places.storage_box("home", rows, storage, ce._picture_key)["over"])
        with mock.patch.object(config, "load", return_value={"storage_box_capacity": "lots"}):
            self.assertEqual(places.capacity(), 2400)
        self.assertIsNone(places.storage_box("home", rows, {"error": "no pool", "rows": {}}, ce._picture_key))


    def test_copies_kept_outside_the_box_rows_arent_in_its_count(self):
        self.assertTrue(places.in_box("") and places.in_box("Row 2, B") and places.in_box("row3"))
        self.assertFalse(places.in_box("Binder") or places.in_box("Trade box, row 1"))
        held = self.rows()["storage"]["rows"][ce._picture_key(ELVES)]["held"] or 0
        row = next(r for r in self.rows()["rows"] if r["set"] == "fdn" and r["collector_number"] == "227")
        free = int(row["quantity"]) - held
        self.assertGreater(free, 0)
        before = self.rows()["storage_box"]
        for place, moved in (("Row 2, B", 0), ("Binder", free)):
            with self.subTest(place=place):
                self.save(action="edit", original=ELVES, location=place, row=row)
                box = self.rows()["storage_box"]
                self.assertEqual((box["cards"], box["elsewhere"]), (before["cards"] - moved, moved))


class PackingPlanTests(CollectionEditTestCase):

    def test_pulled_and_returned_cards_name_their_locations(self):
        self.save(action="edit", original=ELVES, location="Row 2, B",
                  row={"name": "Llanowar Elves", **ELVES, "quantity": "2", "condition": "", "language": "", "notes": ""})
        answer = {"rows": [{"name": "Llanowar Elves", "from_storage": 1}, {"name": "Black Lotus", "from_storage": 0}],
                  "decks": [{"returns": [{"name": "Elvish Mystic", "quantity": 1}]}]}
        with inventory.pinned():
            assembly_locations.annotate(answer, inventory.current())
        self.assertEqual(answer["storage_locations"], {"ready": True, "cards": {"Llanowar Elves": ["Row 2, B"]}})

    def test_nothing_recorded(self):
        answer = {"rows": [], "decks": []}
        assembly_locations.annotate(answer, SimpleNamespace(locations_of=lambda space: {}, locations_ready=False))
        self.assertEqual(answer["storage_locations"], {"ready": False, "cards": {}})


class CommandLineTests(CollectionEditTestCase):

    def run_cli(self, *argv):
        from decklab.db import inv_collection
        import argparse
        parser = argparse.ArgumentParser()
        inv_collection.register(parser.add_subparsers(dest="cmd"))
        args = parser.parse_args(["collection", *argv])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = args.func(args)
        return code, out.getvalue(), err.getvalue()

    def test_edit_location_then_list_them(self):
        expect = self.rows()["sha256"][:12]
        code, out, _ = self.run_cli("edit", "fdn", "227", "nonfoil", "--location", "Row 1, A", "--expect", expect,
                                    "-m", "Shelve the elves")
        self.assertEqual(code, 0)
        self.assertIn("location (blank) -> Row 1, A", out)
        self.assertEqual(self.writes[-1][0], "Shelve the elves")
        code, out, err = self.run_cli("locations")
        self.assertEqual(out, "set,collector_number,finish,name,location\nfdn,227,nonfoil,Llanowar Elves,\"Row 1, A\"\n")
        self.assertIn("1 of 3 rows have a storage location", err)
        expect = self.rows()["sha256"][:12]
        code, out, _ = self.run_cli("edit", "fdn", "227", "nonfoil", "--location", "Row 1, A", "--expect", expect,
                                    "-m", "Again")
        self.assertIn("Nothing to change", out)
        with self.assertRaisesRegex(ValueError, "formula"):
            self.run_cli("edit", "fdn", "227", "nonfoil", "--location=-x", "--expect", expect, "-m", "Bad")

    def test_list_csv_stays_eight_columns(self):
        self.save(action="edit", original=ELVES, location="Binder",
                  row={"name": "Llanowar Elves", **ELVES, "quantity": "2", "condition": "", "language": "", "notes": ""})
        _, out, _ = self.run_cli("list")
        self.assertEqual(out.splitlines()[0], ",".join(rules.FIELDS))
        self.assertNotIn("Binder", out)


if __name__ == "__main__":
    import unittest
    unittest.main()
