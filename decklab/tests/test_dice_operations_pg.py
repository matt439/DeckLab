"""The dice operation mixin against disposable PostgreSQL, with persisted/audited rows."""
import json
import os
from pathlib import Path
import tempfile
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.inventory import files, pg
from decklab.lib.state import pg as state_pg
from decklab.tests import db_support
from decklab.tests.test_collection_edit import ROLES
from decklab.tests import test_dice_counters as shared


class DiceOperationsPgTests(shared.DiceOperationCases, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="decklab-dice-operation-config-")
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(ROLES), encoding="utf-8")
        for patch in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patch.start()
            cls.addClassCleanup(patch.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Dice coverage requires a disposable database")
        db_support.seed_membership(cls.dbname, ROLES["profiles"])

    def setUp(self):
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        root = shared.tree()
        import shutil
        self.addCleanup(shutil.rmtree, root, True)
        initial = files.FileInventory(root).load()
        pg.write_model(initial, shared.ACTOR, "Seed disposable dice operations", contents={}, dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def dice_text(self, space="home"):
        # New backend forces a database read; no mutable fixture model can satisfy it.
        snapshot = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker()).load()
        content = files.render(snapshot).get(shared.paths.dice(space))
        return content.decode("utf-8") if content is not None else None

    def test_each_actual_write_is_audited_and_unchanged_or_refused_writes_are_not(self):
        self.apply("add", space="home", sha256=None, row=shared.D20)
        self.apply("edit", space="home", sha256=self.sha(), base=shared.D20, row={**shared.D20, "quantity": "3"})
        self.apply("remove", space="home", sha256=self.sha(), base={**shared.D20, "quantity": "3"})
        with self.connect("ro") as connection:
            rows = connection.execute("select op from audit.row_change where table_name='dice_counter' order by id").fetchall()
            self.assertEqual(rows, [("INSERT",), ("UPDATE",), ("DELETE",)])
            self.assertEqual(connection.execute("select count(*) from dice_counter").fetchone()[0], 0)
