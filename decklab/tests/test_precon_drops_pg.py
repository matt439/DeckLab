"""Cards-only drops persist without deck/history rows in a guarded disposable database."""
import copy
import json
import os
from pathlib import Path
import tempfile
from unittest import mock

from decklab.lib import config, sealed
from decklab.lib.api import precons as api
from decklab.lib.tokens import ops as token_ops
from decklab.tests import db_support
from decklab.tests import test_collection_edit as collection_fixture
from decklab.tests import test_precon_drops as drop_fixture
from decklab.tests import test_precon_tokens_pg as pg_fixture


class PreconDropsPgTests(db_support.DbTestCase):
    fresh = pg_fixture.PreconTokensPgTests.fresh
    sql = pg_fixture.PreconTokensPgTests.sql
    persisted_state = pg_fixture.PreconTokensPgTests.persisted_state

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-drop-pg-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(collection_fixture.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Drop integration requires a disposable test database")
        db_support.seed_membership(cls.dbname, collection_fixture.ROLES["profiles"])

    def setUp(self):
        pg_fixture.PreconTokensPgTests.setUp(self)
        self.case.seed("decks/SomeDrop_SLD.json", drop_fixture.DROP)
        sealed.contents.return_value = copy.deepcopy(drop_fixture.CONTENT)

    def add_drop(self, **extra):
        view = api.precon_preview("SomeDrop_SLD", "user2")
        return self.case.add("SomeDrop_SLD", "user2", title=view["title"], sha256=view["sha256"],
            bonus_choices=[1], bonus_source_sha256=view["bonus_import"]["source_sha256"], add_tokens=True,
            tokens_sha256=view["token_import"]["sha256"], tokens_source_sha256=view["token_import"]["source_sha256"], **extra)

    def test_drop_cards_bonus_raw_content_and_tokens_are_one_audit_set_with_no_deck_rows(self):
        before = self.persisted_state()
        answer = self.add_drop()
        after = self.persisted_state()
        self.assertTrue(answer["cards_only"])
        self.assertIsNone(answer["deck"])
        self.assertEqual(answer["collection"]["added"], {"cards": 4, "rows": 2})
        self.assertEqual(answer["tokens"], {"cards": 2, "rows": 1})
        self.assertEqual(len(after["audit.change_set"]), len(before["audit.change_set"]) + 1)
        for table in ("deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
            self.assertEqual(after[table], before[table], table)
        self.assertEqual(self.sql("select count(*) from collection_import_content"), [(1,)])
        current = self.fresh()
        bonus = next(row for row in current.collection("user2").rows if row["name"] == "Pick Your Poison")
        self.assertEqual((bonus["set"], bonus["collector_number"], bonus["finish"], bonus["quantity"]), ("mkm", "170", "foil", "1"))
        self.assertEqual((bonus["condition"], bonus["language"]), ("", ""))
        self.assertEqual(current.token_set("user2").rows[0]["quantity"], "2")

    def test_late_token_failure_leaves_every_persisted_table_unchanged(self):
        before = self.persisted_state()
        with mock.patch.object(token_ops, "add", side_effect=RuntimeError("Synthetic drop failure")):
            with self.assertRaises(RuntimeError):
                self.add_drop()
        self.assertEqual(self.persisted_state(), before)
