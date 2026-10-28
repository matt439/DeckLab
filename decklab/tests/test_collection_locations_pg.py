"""Storage locations (E8-S22) in a disposable PostgreSQL database, never the live one: migration
0016's collection_card.location, one audited change per edit, the export's locations.csv, Undo on
rows that have a location, and the schema before 0016 (readers and other writes keep working, a
location is refused until the migration is applied)."""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.db import export, migrate
from decklab.lib import config, inventory
from decklab.lib.inventory import Op, files, rules
from decklab.lib.inventory.undo import UndoUnsupported
from decklab.lib.state import Invalid
from decklab.tests import db_support
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_precon_tokens_pg as pg_fixture

ACTOR = pg_fixture.ACTOR


class CollectionLocationsPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-locations-pg-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Location integration requires a guarded disposable test database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    setUp = pg_fixture.PreconTokensPgTests.setUp
    fresh = pg_fixture.PreconTokensPgTests.fresh
    sql = pg_fixture.PreconTokensPgTests.sql
    persisted = pg_fixture.PreconTokensPgTests.persisted_state

    def card(self):
        return next(row.as_dict() for row in self.fresh().collection("home").rows if row.name == "Llanowar Elves")

    def edit(self, location=None, **changes):
        row = self.card()
        params = {"space": "home", "original": list(rules.ident(row)), "row": {**row, **changes}}
        if location is not None:
            params["location"] = location
        return inventory.apply(Op("collection.edit", params), ACTOR, "Fixture location edit")

    def latest_rows(self):
        return self.sql("select table_name, op, after->>'location' from audit.row_change where change_set_id="
                        "(select max(id) from audit.change_set) order by id")

    def test_a_location_is_one_audited_row_update_and_exported_as_its_file(self):
        sets = len(self.sql("select id from audit.change_set"))
        self.edit(location="Row 2, B")
        self.assertEqual(len(self.sql("select id from audit.change_set")), sets + 1)
        self.assertEqual(self.latest_rows(), [("collection_card", "UPDATE", "Row 2, B")])
        key = tuple(self.card()[k] for k in ("set", "collector_number", "finish"))
        self.assertEqual(self.fresh().locations_of("home"), {key: "Row 2, B"})
        self.assertTrue(self.fresh().locations_ready)
        with self.connect("owner") as c:
            found = export.inventory_files(c)
        self.assertIn(b'"Row 2, B"', found["magic/locations.csv"])
        self.assertEqual(files.build(found).locations_of("home"), {key: "Row 2, B"})
        # A quantity edit leaves it; the row's removal takes it.
        self.edit(quantity=str(int(self.card()["quantity"]) + 1))
        self.assertEqual(self.fresh().locations_of("home"), {key: "Row 2, B"})
        with self.assertRaises(Invalid):
            self.edit(location="=bad")

    def test_undo_still_reviews_quantity_changes_and_leaves_location_changes_alone(self):
        self.edit(location="Binder")
        location_change = self.sql("select max(id) from audit.change_set")[0][0]
        with self.assertRaises(UndoUnsupported):
            inventory.undo_review(location_change, "home")
        self.edit(quantity=str(int(self.card()["quantity"]) + 2))
        quantity_change = self.sql("select max(id) from audit.change_set")[0][0]
        plan = inventory.undo_review(quantity_change, "home")
        self.assertEqual(plan["kind"], "collection")

    def test_before_migration_0016_readers_and_other_writes_work_and_a_location_is_refused(self):
        self.assertTrue(self.dbname.startswith(db_support.PREFIX))
        self.addCleanup(migrate.apply, dbname=self.dbname)
        with self.connect("owner") as c:
            c.execute("alter table collection_card drop column location")
            c.execute("delete from schema_migration where version>=16")
        old = self.fresh()
        self.assertFalse(old.locations_ready)
        self.assertEqual(old.locations_of("home"), {})
        before = self.persisted()
        with self.assertRaisesRegex(Invalid, "migration 0016"):
            self.edit(location="Row 1")
        self.assertEqual(self.persisted(), before)
        self.edit(notes="Still editable")
        self.assertEqual(self.card()["notes"], "Still editable")
        with self.connect("owner") as c:
            self.assertNotIn("magic/locations.csv", export.inventory_files(c))
        migrate.apply(dbname=self.dbname)
        self.assertTrue(self.fresh().locations_ready)
        self.edit(location="Row 1")
        self.assertEqual(list(self.fresh().locations_of("home").values()), ["Row 1"])


if __name__ == "__main__":
    import unittest
    unittest.main()
