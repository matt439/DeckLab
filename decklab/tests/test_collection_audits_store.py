"""Collection audit evidence, optimistic saves and disposable database integration."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from decklab.db import conn as db, migrate, space_export, space_remove
from decklab.lib import access, cards, config, inventory, state
from decklab.lib.api import collection_storage_map
from decklab.lib.api.activity_home import collection_audit_row
from decklab.lib.api.common import ApiError
from decklab.lib.inventory.pg import PgInventory, _take_lock
from decklab.lib.state import Actor, Conflict, Invalid, collection_audits, pg, pg_collection_audits
from decklab.lib.state.memory import MemoryStore
from decklab.tests import db_support

ACTOR = Actor("test", "Test", source="cli")
SECTION = "box:white-creatures"
SUMMARY = {"digest": "c" * 64, "expected": 5, "observed": 4, "missing": 2, "surplus": 0, "extra": 1, "mismatch_rows": 1,
           "differences": [{"name": "Savannah Lions", "set": "dmr", "collector_number": "23", "finish": "nonfoil",
                            "expected": 5, "observed": 3}]}


class AuditEvidenceTests(unittest.TestCase):
    def test_audit_read_validates_differences_and_totals(self):
        collection_audits.validate(SUMMARY)
        collection_audits.validate({**SUMMARY, "differences": [dict(SUMMARY["differences"][0], description="Flying")]})
        for bad in ({"missing": 1}, {"observed": 3}, {"mismatch_rows": 0}, {"extra": -1}, {"digest": "fake"},
                    {"differences": [dict(SUMMARY["differences"][0], observed=True)]}):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                collection_audits.validate({**SUMMARY, **bad})

    def test_named_extras_are_part_of_unlisted_total(self):
        known = {"key": "dmr|23|foil", "name": "Savannah Lions", "set": "dmr", "collector_number": "23",
                 "finish": "foil", "expected": 0, "observed": 1, "estimated": False}
        summary = {**SUMMARY, "differences": [*SUMMARY["differences"], known], "mismatch_rows": 2}
        collection_audits.validate(summary)
        self.assertEqual(collection_audits.identified_extra(summary["differences"]), 1)
        for bad in ({"observed": 2}, {"estimated": 0}, {"key": "wrong"}):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                collection_audits.validate({**summary, "differences": [*SUMMARY["differences"], {**known, **bad}]})

    def test_activity_only_shows_a_summary_to_the_collection_space(self):
        row = {"key": {"space_id": "user2"}, "op": "UPDATE", "after": {"space_id": "user2", **SUMMARY}}
        self.assertIsNone(collection_audit_row(row, ["home"]))
        self.assertEqual(collection_audit_row(row, ["user2"]),
                         {"table": "collection_section_audit", "op": "UPDATE", "summary": "Collection audit recorded"})

    def test_memory_store_rechecks_and_keeps_latest_own_space_count(self):
        store, fresh = MemoryStore(), object()

        def review(snapshot, setup):
            self.assertIs(snapshot, fresh)
            self.assertEqual(setup["storage"]["containers"][0]["order"], "colour-type")
            return SUMMARY

        with patch.object(inventory, "backend", return_value=SimpleNamespace(load=lambda: fresh)):
            saved = store.collection_audit_record("home", SECTION, 0, review, ACTOR, "Record collection audit")
            self.assertEqual(saved["revision"], 1)
            with self.assertRaises(Conflict):
                store.collection_audit_record("home", SECTION, 0, review, ACTOR, "Record collection audit")
            updated = store.collection_audit_record("home", SECTION, 1, review, ACTOR, "Record collection audit")
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(store.collection_audits("home"), {"ready": True, "sections": {SECTION: updated}})
        self.assertEqual(store.collection_audits("user2"), {"ready": True, "sections": {}})


class AuditEvidenceDbTests(db_support.DbTestCase):
    def setUp(self):
        db_support.reset(self.dbname, db_support.STATE_TABLES + db_support.INVENTORY_TABLES)
        db_support.seed_membership(self.dbname)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())
        with self.connect("owner") as c, db.change("test", "test", "Add audit fixture", conn=c) as (cur, _):
            cur.execute("insert into inventory_revision (revision) values (1)")
            cur.execute("insert into collection_card (space_id, set_code, collector_number, finish, name, quantity) "
                        "values ('user2', 'dmr', '23', 'nonfoil', 'Savannah Lions', 5)")

    def test_committed_count_is_scoped_and_exported_with_discrepancies(self):
        setup = self.store.space_storage_put("user2", [{"name": "Box", "order": "colour-type"}], 0, ACTOR, "Set up box")

        def review(snapshot, storage):
            self.assertEqual(snapshot.collection("user2").rows[0].qty, 5)
            self.assertEqual(storage["storage"], setup["storage"])
            with self.connect("app") as contender, contender.transaction():
                for claim in ("inventory", "space-storage:user2"):
                    available = contender.execute("select pg_try_advisory_xact_lock(hashtext(%s))", (claim,)).fetchone()
                    self.assertEqual(available, (False,))
            return SUMMARY

        saved = self.store.collection_audit_record("user2", SECTION, 0, review, ACTOR, "Record collection audit")
        self.assertEqual(self.store.collection_audits("user2")["sections"][SECTION], saved)
        self.assertEqual(self.store.collection_audits("guest")["sections"], {})
        files, _, data = space_export.database_snapshot("user2", self.dbname, details=True)
        self.assertEqual(json.loads(files["collection-audits.json"])[0]["differences"], SUMMARY["differences"])
        rows, _ = space_remove.row_plan("user2", data)
        self.assertIn({"table": "collection_section_audit", "key": {"space_id": "user2", "section_id": SECTION},
                       "action": "delete"}, rows)
        with self.connect("ro") as c:
            self.assertEqual(pg_collection_audits.check(c), (True, False, "1 saved collection section audits"))
            self.assertEqual(c.execute("select revision from inventory_revision").fetchone(), (1,))
            self.assertEqual(c.execute("select count(*) from audit.row_change where table_name = 'collection_section_audit'")
                             .fetchone(), (1,))

    def test_storage_map_record_rebuilds_current_loose_cards_under_claim(self):
        from decklab.tests.test_api import BULK_DATES, FIXTURES

        with self.connect("owner") as c, db.change("test", "test", "Use indexed fixture", conn=c) as (cur, _):
            cur.execute("update collection_card set name = 'Llanowar Elves', set_code = 'fdn', collector_number = '227' "
                        "where space_id = 'user2'")
        record = {"default": "Box", "containers": [{"name": "Box", "order": "colour-type", "sections": ["Row 1"],
                                                   "holds": {"Row 1": "creatures"}}]}
        self.store.space_storage_put("user2", record, 0, ACTOR, "Set up box")
        settings = db.settings()
        scope = {"database": {"host": settings["host"], "port": settings["port"]},
                 "profiles": [{"id": "user2", "name": "User2", "role": "member", "space": "user2"}]}
        index = cards.build_index(FIXTURES / "default_cards.jsonl", FIXTURES / "oracle_tags.jsonl", BULK_DATES,
                                  log=lambda *_: None)
        backend = PgInventory(dbname=self.dbname, breaker=pg.Breaker())
        with (patch.object(config, "load", return_value=scope), patch.object(cards, "_index", cards._prepare(index)),
              state.use(self.store), inventory.use(backend), access.using({"profile": "user2", "remote": True})):
            overview = collection_storage_map.view("user2")
            section, = [item for item in overview["sections"] if item["label"] == "Green creatures"]
            self.assertEqual((section["quantity"], section["place"], section["audit"]), (5, "Row 1", None))
            ident = section["id"]
            detail = collection_storage_map.view("user2", ident)
            row, = detail["rows"]
            body = {"profile": "user2", "space": "user2", "section": ident, "expect": detail["expect"],
                    "counts": {row["key"]: 3}, "extra": 1,
                    "unlisted": [{"set": "fdn", "collector_number": "227", "finish": "foil", "quantity": 2}]}
            with inventory.pinned(backend.load()):
                with self.connect("owner") as c, db.change("test", "test", "Collection changed", conn=c) as (cur, _):
                    _take_lock(cur)
                    cur.execute("update collection_card set quantity = 6 where space_id = 'user2'")
                    cur.execute("update inventory_revision set revision = revision + 1")
                with self.assertRaises(ApiError) as caught:
                    collection_storage_map.record(json.dumps(body))
                self.assertEqual(caught.exception.status, 409)
            detail = collection_storage_map.view("user2", ident)
            saved = collection_storage_map.record(json.dumps({**body, "expect": detail["expect"]}))["section"]["audit"]
            self.assertEqual((saved["expected"], saved["observed"], saved["missing"], saved["extra"],
                              saved["unidentified_extra"]), (6, 6, 3, 3, 1))
            self.assertEqual(saved["differences"][-1]["key"], "fdn|227|foil")
            self.assertEqual(collection_storage_map.view("user2", ident)["section"]["audit"], saved)
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select quantity from collection_card where space_id = 'user2'").fetchone(), (6,))

    def test_failed_review_and_missing_schema_leave_no_audit(self):
        def stale(_snapshot, _storage):
            raise Conflict("Stale snapshot")

        with self.assertRaisesRegex(Conflict, "Stale snapshot"):
            self.store.collection_audit_record("user2", SECTION, 0, stale, ACTOR, "Record collection audit")
        self.assertEqual(self.store.collection_audits("user2")["sections"], {})
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select count(*) from audit.change_set where message = 'Record collection audit'")
                             .fetchone(), (0,))
        with self.connect("owner") as c:
            db_support.roll_back_schema(c, 30)
        try:
            self.assertEqual(self.store.collection_audits("user2"), {"ready": False, "sections": {}})
            with self.assertRaises(collection_audits.MissingSchema):
                self.store.collection_audit_record("user2", SECTION, 0, stale, ACTOR, "Record collection audit")
        finally:
            migrate.apply(dbname=self.dbname, say=lambda *_: None)
