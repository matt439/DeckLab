"""S40 operational departure markers: maintenance in disposable databases only."""
import csv
import io
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from decklab.db import backup, check, conn as db, export, migrate, setup
from decklab.tests import db_support


class DepartureMaintenanceTests(db_support.DbTestCase):
    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES + db_support.STATE_TABLES)
        with self.connect("owner") as c:
            c.execute("delete from ops.visit_day")
            with db.change("test", "test", "Clear corrupted membership fixture", conn=c) as (cur, _):
                cur.execute("delete from profile where id='former'")
                cur.execute("delete from space where id='former'")
            c.execute("delete from audit.row_change")
            c.execute("delete from audit.change_set")

    def marker(self, space="former"):
        operation = uuid.uuid4()
        with self.connect("owner") as c:
            with db.change("test", "test", "Remove fixture member", conn=c) as (cur, change_id):
                cur.execute("insert into space_departure (space_id, operation, change_set_id) values (%s,%s,%s)",
                            (space, operation, change_id))
        return operation, change_id

    def invariant(self):
        with self.connect("ro") as c:
            return check._space_departures(c)()

    def test_migration_starts_empty_and_marker_contains_only_operational_identity(self):
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select * from space_departure").fetchall(), [])
            columns = c.execute("select column_name from information_schema.columns "
                                "where table_schema='public' and table_name='space_departure' "
                                "order by ordinal_position").fetchall()
            self.assertEqual(columns, [("space_id",), ("operation",), ("change_set_id",)])
            self.assertEqual(c.execute("select name from schema_migration where version=13").fetchone(),
                             ("space_departure",))
        self.assertEqual(self.invariant(), (True, False, "0 departed members; no current data remains"))
        self.marker()
        self.assertEqual(self.invariant(), (True, False, "1 departed members; no current data remains"))

    def test_owner_insertion_is_audited_and_app_and_ro_have_read_only_access(self):
        import psycopg
        operation, change_id = self.marker()
        for role in ("app", "ro"):
            with self.subTest(role=role), self.connect(role) as c:
                self.assertEqual(c.execute("select space_id, operation, change_set_id from space_departure").fetchall(),
                                 [("former", operation, change_id)])
                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    self.assertFalse(c.execute("select has_table_privilege(current_user, 'space_departure', %s)",
                                               (privilege,)).fetchone()[0])
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    c.execute("delete from space_departure")
        with self.connect("ro") as c:
            row = c.execute("select op, row_key, after from audit.row_change "
                            "where change_set_id=%s and table_name='space_departure'", (change_id,)).fetchone()
            self.assertEqual(row, ("INSERT", {"space_id": "former"},
                                   {"space_id": "former", "operation": str(operation), "change_set_id": change_id}))
        with self.connect("owner") as c:
            with self.assertRaisesRegex(psycopg.Error, "every write needs a change set"):
                c.execute("insert into space_departure (space_id, operation, change_set_id) values ('another',%s,%s)",
                          (uuid.uuid4(), change_id))
            with self.assertRaisesRegex(psycopg.Error, "truncate isn't audited"):
                c.execute("truncate space_departure")
            with self.assertRaises(psycopg.errors.CheckViolation):
                with db.change("test", "test", "Invalid home departure", conn=c) as (cur, next_id):
                    cur.execute("insert into space_departure (space_id, operation, change_set_id) values ('home',%s,%s)",
                                (uuid.uuid4(), next_id))

    def test_export_is_sorted_deterministic_and_backup_digest_detects_identity_changes(self):
        with self.connect("ro") as c:
            empty = backup.digest_rows(c)["public.space_departure"]
        self.marker("z-last")
        self.marker("a-first")
        folder = Path(tempfile.mkdtemp(prefix="decklab-departure-export-"))
        self.addCleanup(shutil.rmtree, folder)
        export.write_tables(folder, dbname=self.dbname)
        file = folder / "tables/public.space_departure.csv"
        before = file.read_bytes()
        rows = list(csv.DictReader(io.StringIO(before.decode("utf-8"))))
        self.assertEqual([row["space_id"] for row in rows], ["a-first", "z-last"])
        export.write_tables(folder, dbname=self.dbname)
        self.assertEqual(file.read_bytes(), before)
        self.assertNotIn("public.space_departure", export.INVENTORY_TABLES)
        with self.connect("ro") as c:
            self.assertEqual(backup.count_rows(c)["public.space_departure"], 2)
            full = backup.digest_rows(c)["public.space_departure"]
        self.assertNotEqual(empty, full)
        with self.connect("owner") as c:
            with db.change("test", "test", "Corrupt operation fixture", conn=c) as (cur, _):
                cur.execute("update space_departure set operation=%s where space_id='a-first'", (uuid.uuid4(),))
        with self.connect("ro") as c:
            changed = backup.digest_rows(c)["public.space_departure"]
        self.assertNotEqual(full, changed)
        self.assertIn("without their removal audit", self.invariant()[2])

    def test_check_flags_resurrection_without_reporting_member_contents(self):
        self.marker()
        with self.connect("owner") as c:
            with db.change("test", "test", "Corrupt retained-data fixture", conn=c) as (cur, _):
                cur.execute("insert into space (id) values ('former') on conflict do nothing")
                cur.execute("insert into profile (id,name,role,space_id,position) "
                            "values ('former','Private display name','member','former',0) on conflict do nothing")
                cur.execute("insert into collection_card (space_id,set_code,collector_number,finish,name,quantity) "
                            "values ('former','fdn','227','nonfoil','Private card name',2)")
                cur.execute("insert into wishlist_entry (profile_id,position,name,notes) "
                            "values ('former',0,'Private wish','Private note')")
                cur.execute("insert into profile_setting (profile_id,key,value) values ('former','theme','dark')")
                cur.execute("insert into visibility (owner,thing,set_by,set_by_name) "
                            "values ('former','decks','test','Test')")
            c.execute("insert into ops.visit_day (profile_id,day,channel,first_at,last_at) "
                      "values ('former',current_date,'home',now(),now())")
        ok, warning, detail = self.invariant()
        self.assertFalse(ok)
        self.assertFalse(warning)
        for table in ("space", "profile", "collection_card", "wishlist_entry", "profile_setting"):
            self.assertIn(f"{table}: 1 current rows", detail)
        self.assertIn("and 2 more", detail)
        for private in ("Private display name", "Private card name", "Private wish", "Private note", "former"):
            self.assertNotIn(private, detail)

    def test_a_reset_removes_marker_before_its_audit_foreign_key_even_for_inventory_only(self):
        self.marker()
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select count(*) from space_departure").fetchone()[0], 0)
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone()[0], 0)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class BeforeDepartureMigrationTests(unittest.TestCase):
    def test_check_and_export_work_before_0013_and_preserve_existing_marker_csv(self):
        name = db_support.create_empty_database("pre_departure")
        self.addCleanup(db_support.drop_database, name)
        folder = Path(tempfile.mkdtemp(prefix="decklab-pre-departure-"))
        self.addCleanup(shutil.rmtree, folder)
        for item in migrate.available():
            if item["version"] < 13:
                shutil.copy(item["path"], folder / item["path"].name)
        migrate.apply(dbname=name, directory=folder)
        setup.secure_database(name)
        output = folder / "export"
        (output / "tables").mkdir(parents=True)
        file = output / "tables/public.space_departure.csv"
        file.write_bytes(b"prior marker export\n")
        export.write_tables(output, dbname=name)
        self.assertEqual(file.read_bytes(), b"prior marker export\n")
        with db.connect("ro", dbname=name) as c:
            self.assertEqual(check._space_departures(c)(),
                             (True, False, "member departure markers unavailable until migration 0013"))


if __name__ == "__main__":
    unittest.main()
