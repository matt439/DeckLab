"""Explicit physical choices persist atomically in one guarded disposable PostgreSQL DB."""
import copy
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.tokens import ops as token_ops
from decklab.tests import db_support
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_precon_tokens_pg as pg_fixture
from decklab.tests import test_precons as sources


class PreconTokenChoicesPgTests(db_support.DbTestCase):
    # Reuse setup helpers without inheriting/discovering the earlier module's test methods.
    setUp = pg_fixture.PreconTokensPgTests.setUp
    fresh = pg_fixture.PreconTokensPgTests.fresh
    sql = pg_fixture.PreconTokensPgTests.sql
    persisted_state = pg_fixture.PreconTokensPgTests.persisted_state

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-token-choices-pg-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Explicit precon choices require a disposable test database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def test_unknown_source_quantity_and_skip_save_confirmed_rows_with_one_audit_set(self):
        data = copy.deepcopy(sources.DINOS)
        data["data"]["tokens"] = [{"name": "Dinosaur"}, {"name": "Dinosaur", "count": 5}]
        path = self.case.seed("decks/TestDinos_TST.json", data)
        source = path.read_bytes()
        home = self.fresh().collection("home")
        before = self.sql("select id from audit.change_set order by id")
        answer = self.case.add_tokens(tokens_choices=[{"source_row": 1, "front": "Dinosaur", "quantity": 2},
                                                     {"source_row": 2, "front": "", "quantity": 0}])
        after = self.sql("select id from audit.change_set order by id")
        self.assertEqual(len(after), len(before) + 1)
        change_set = after[-1][0]
        touched = {row[0] for row in self.sql("select distinct table_name from audit.row_change where change_set_id=%s", (change_set,))}
        self.assertTrue({"collection_card", "collection_import", "token_card", "deck"} <= touched)
        self.assertEqual(answer["tokens"], {"cards": 2, "rows": 1})
        self.assertEqual(answer["collection"]["added"], {"cards": 5, "rows": 3})
        saved = self.fresh()
        rows = saved.token_set("user2").rows
        self.assertEqual([(row["front"], row["quantity"]) for row in rows], [("Dinosaur", "2")])
        self.assertIn("user-confirmed physical quantity 2", rows[0]["notes"])
        self.assertIn("source physical quantity unknown", rows[0]["notes"])
        self.assertTrue(rows[0].id > 0)
        self.assertEqual(saved.collection("home"), home)
        self.assertIn("Tokens page): 2 Dinosaur.", saved.deck(answer["deck"]["id"]).text)
        self.assertEqual(self.sql("select revision,op,change_set_id from deck_revision where deck_id=%s", (answer["deck"]["id"],)),
                         [(1, "A", change_set)])
        self.assertEqual(path.read_bytes(), source)

    def test_late_confirmed_row_failure_rolls_back_inventory_import_deck_and_audit(self):
        before = self.persisted_state()
        original = token_ops.add
        def fail_second(inv, **params):
            if "entry 2;" in params["row"]["notes"]:
                raise inventory.Invalid("Fixture late confirmed token failure")
            return original(inv, **params)
        with mock.patch.object(token_ops, "add", side_effect=fail_second):
            self.case.assertApiError(400, self.case.add_tokens,
                                     tokens_choices=[{"source_row": 1, "front": "Dinosaur", "quantity": 2},
                                                     {"source_row": 2, "front": "Dinosaur", "quantity": 1}])
        self.assertEqual(self.persisted_state(), before)
        self.assertFalse(self.fresh().token_set("user2").exists)
