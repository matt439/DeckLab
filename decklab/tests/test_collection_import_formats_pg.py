"""Offline format review/apply retains raw bytes atomically in a guarded disposable database."""
import json
import os
from pathlib import Path
import tempfile
from unittest import mock

from decklab.lib import config
from decklab.lib.api import collection_edit as edits
from decklab.tests import db_support
from decklab.tests import test_collection_edit as roles
from decklab.tests import test_collection_import_formats as sources
from decklab.tests import test_precon_tokens_pg as pg_fixture


class OfflineFormatsPgTests(db_support.DbTestCase):
    setUp = pg_fixture.PreconTokensPgTests.setUp
    fresh = pg_fixture.PreconTokensPgTests.fresh
    sql = pg_fixture.PreconTokensPgTests.sql
    persisted_state = pg_fixture.PreconTokensPgTests.persisted_state

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-format-pg-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(roles.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Offline format integration requires a disposable test database")
        db_support.seed_membership(cls.dbname, roles.ROLES["profiles"])

    def preview(self, text, filename="offline.csv"):
        return self.case.call(edits.import_preview, "user2", space="user2", filename=filename, text=text)

    def apply(self, shown, **options):
        return self.case.call(edits.import_apply, "user2", space="user2", token=shown["token"], sha256=shown["sha256"], **options)

    def test_each_vendor_keeps_its_original_raw_content_and_one_change_without_any_deck_rows(self):
        home = self.fresh().collection("home")
        for number, text in enumerate((sources.ARCHI, sources.DRAGON, sources.DELVER, sources.TCG)):
            before = self.persisted_state()
            shown = self.preview(text, f"offline-{number}.csv")
            self.assertEqual(self.persisted_state(), before)
            self.assertEqual(shown["problems"], [])
            answer = self.apply(shown)
            self.assertTrue(answer["ok"])
            after = self.persisted_state()
            self.assertEqual(len(after["audit.change_set"]), len(before["audit.change_set"]) + 1)
            for table in ("deck", "deck_text", "deck_line", "deck_revision", "decks_revision"):
                self.assertEqual(after[table], before[table], table)
            raw = self.sql("select content from collection_import_content order by import_id desc limit 1")[0][0]
            self.assertEqual(bytes(raw), text.encode("utf-8"))
            self.assertNotIn("PRIVATE PAID CANARY", json.dumps(answer))
        self.assertEqual(self.fresh().collection("home"), home)

    def test_bad_text_requires_explicit_problem_selection_and_the_refusal_changes_no_rows(self):
        text = "2 Llanowar Elves (FDN) 227\nnot a card line\n"
        shown = self.preview(text, "offline.txt")
        before = self.persisted_state()
        self.case.assertApiError(400, self.apply, shown)
        self.assertEqual(self.persisted_state(), before)
        self.assertTrue(self.apply(shown, skip_problems=True)["ok"])
        raw = self.sql("select content from collection_import_content order by import_id desc limit 1")[0][0]
        self.assertEqual(bytes(raw), text.encode("utf-8"))
