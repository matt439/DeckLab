"""Date-only box checks use guarded ordinary deck saves in disposable PostgreSQL data."""
import json
import os
import re
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.api import box_check
from decklab.lib.decks import boxcheck
from decklab.lib.inventory import Op, model, paths, pg, rules
from decklab.lib.state import Actor
from decklab.lib.state import pg as state_pg
from decklab.tests import db_support, household_config
from decklab.tests import test_box_check_api as fixture
from decklab.tests import test_pool as pool_fixture

setUpModule = pool_fixture.setUpModule
tearDownModule = pool_fixture.tearDownModule

ACTOR = Actor("matt", "Matt", source="cli")
TABLES = ("collection_card", "token_card", "product_status", "deck", "deck_text", "deck_line", "deck_revision",
          "inventory_revision", "decks_revision", "audit.change_set", "audit.row_change")


class BoxCheckPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-boxcheck-pg-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Box-check integration requires a disposable test database")
        db_support.seed_membership(cls.dbname, household_config.PROFILES)

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = fixture.BoxCheckCase()
        self.addCleanup(case.doCleanups)
        case.setUp()
        self.case = case
        source = case.inventory.load()
        sheet = source.collection("home")
        collection = model.Sheet(sheet.path, sheet.columns, tuple(sorted(sheet.rows, key=rules.sort_key)), sheet.exists)
        initial = model.Inventory("boxcheck-pg-fixture", collections={"home": collection},
            status=model.Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS), (), True),
            watchlist=model.Sheet(paths.WATCHLIST, tuple(model.QUEUE_FIELDS), (), True),
            decks={"casual/a": source.deck("casual/a")})
        pg.write_model(initial, ACTOR, "Seed disposable box-check deck", contents={}, dbname=self.dbname, decks=True, images={})
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def fresh(self):
        return pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker()).load()

    def sql(self, query, params=()):
        with self.connect("ro") as connection:
            return connection.execute(query, params).fetchall()

    def persisted(self):
        with self.connect("ro") as connection:
            return {table: connection.execute(f"select row_to_json(t)::text from {table} t order by 1").fetchall()
                    for table in TABLES}

    def test_only_date_changes_in_one_audited_revision_while_observations_stay_transient(self):
        before, text = self.persisted(), self.fresh().deck("casual/a").text
        body = self.case.payload()
        body["rows"][0]["quantity"] -= 1
        body["extras"] = [{"section": "Deck", "name": fixture.POISON, "quantity": 2}]
        answer = self.case.save(body)
        after = self.persisted()
        self.assertTrue(answer["saved"])
        self.assertTrue(answer["missing"])
        self.assertEqual(answer["extra"], [{"section": "Deck", "kind": "card", "name": fixture.POISON, "for": None, "quantity": 2}])
        self.assertEqual((answer["expected_cards"], answer["found_cards"]), (26, 27))
        self.assertEqual(len(after["audit.change_set"]), len(before["audit.change_set"]) + 1)
        self.assertEqual(len(after["deck_revision"]), len(before["deck_revision"]) + 1)
        for table in ("collection_card", "token_card", "product_status", "deck_line", "inventory_revision"):
            self.assertEqual(after[table], before[table], table)
        saved = self.fresh().deck("casual/a")
        self.assertEqual(re.sub(r"^- \*\*Box checked:\*\* .*\n", "", saved.text, flags=re.M), text)
        self.assertNotIn(fixture.POISON, saved.text)
        self.assertEqual((answer["sha256"], answer["revision"]), (saved.sha256, saved.revision))
        self.assertEqual(self.sql("select message from audit.change_set order by id desc limit 1"), [("Record a box check for A",)])
        self.assertEqual(self.sql("select message from deck_revision where deck_id='casual/a' order by revision desc limit 1"),
                         [("Record a box check for A",)])

    def test_same_day_noop_still_checks_receipt_without_audit_or_revision(self):
        self.case.save()
        before = self.persisted()
        answer = self.case.save()
        self.assertFalse(answer["saved"])
        self.assertEqual(answer["checked_on"], fixture.WHEN)
        self.assertEqual(self.persisted(), before)

    def test_underlock_race_during_same_day_recheck_preserves_concurrent_text_and_all_other_tables(self):
        self.case.save()
        body = self.case.payload()
        captured = []
        original = box_check.apply_op
        def concurrent_change(op, *args, **kwargs):
            held = self.fresh().deck("casual/a")
            inventory.apply(Op("deck.save", {"deck_id": held.id, "base_sha256": held.sha256,
                                               "text": held.text.replace("# A\n", "# Concurrent A\n", 1)}),
                            ACTOR, "Fixture concurrent edit")
            captured.append(self.persisted())
            return original(op, *args, **kwargs)
        with mock.patch.object(box_check, "apply_op", side_effect=concurrent_change):
            self.case.refused(409, body)
        self.assertEqual(self.persisted(), captured[0])
        self.assertIn("# Concurrent A\n", self.fresh().deck("casual/a").text)
        self.assertEqual(boxcheck.checked_on(self.case.parsed()), fixture.WHEN)
