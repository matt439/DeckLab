"""Owned dice and counters (E7-S24) on a disposable database: before migration 0020 every space reads as
having none and a write is refused with nothing changed; once a throwaway copy has 0020, the writes are
audited dice_counter rows that keep their ids. Skips without a test database (db_support.require_db):
never the live one. Running it against a database is a separate, authorized qualification, not a
default fixture check.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.db import conn as db, migrate, profiles_sync, setup
from decklab.lib import config, inventory
from decklab.lib.inventory import Op, files, model, ops_dice, paths, pg, rules  # noqa: F401  (registers dice.*)
from decklab.lib.state import Actor, Invalid
from decklab.lib.state import pg as state_pg
from decklab.tests import db_support, household_config

ACTOR = Actor("claude", "Claude", source="cli")
D20 = {"type": "die", "size": "d20", "kind": "", "design": "red", "quantity": "2", "notes": ""}


class DiceCountersPgTests(unittest.TestCase):

    def test_before_and_after_migration_0020(self):
        folder = tempfile.TemporaryDirectory(prefix="decklab-dice-pg-")
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        config_path = root / "config.json"
        config_path.write_text(json.dumps({"profiles": household_config.PROFILES}), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", config_path),
                        mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            self.addCleanup(patcher.stop)
        db_support.require_db(self)
        name = db_support.create_empty_database("dice19")
        self.addCleanup(db_support.drop_database, name)
        self.assertTrue(name.startswith(db_support.PREFIX))
        early = root / "migrations"
        early.mkdir()
        for item in migrate.available():
            if item["version"] <= 19:
                shutil.copy(item["path"], early / Path(item["path"]).name)
        migrate.apply(dbname=name, directory=early)
        setup.secure_database(name)
        profiles_sync.sync(listed=[{**profile, "plays_as": profile.get("plays_as")}
                                  for profile in household_config.PROFILES], dbname=name)
        initial = files.build({paths.STATUS: rules.csv_bytes([], rules.STATUS_FIELDS),
                               paths.WATCHLIST: rules.csv_bytes([], model.QUEUE_FIELDS)})
        pg.write_model(initial, ACTOR, "Empty fixture", dbname=name)
        backend = pg.PgInventory(dbname=name, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(backend))

        def revision():
            with db.connect("ro", dbname=name) as c:
                return c.execute("select revision from inventory_revision").fetchone()[0]
        loaded = backend.load()
        self.assertFalse(loaded.dice_ready)
        self.assertEqual(dict(loaded.dice), {})
        before = revision()
        with self.assertRaisesRegex(Invalid, "migration 0020"):
            inventory.apply(Op("dice.add", {"space": "home", "sha256": None, "row": D20}), ACTOR, "Too early")
        self.assertEqual(revision(), before)

        migrate.apply(dbname=name)          # only this disposable database gains 0020
        self.assertTrue(backend.load().dice_ready)
        after, _ = inventory.apply(Op("dice.add", {"space": "home", "sha256": None, "row": D20}), ACTOR, "Our d20s")
        row = after.dice_set("home").rows[0]
        self.assertTrue(row.id)
        sha = files.rendered_sha256(after.dice_set("home"))
        again, _ = inventory.apply(Op("dice.edit", {"space": "home", "sha256": sha, "base": D20,
                                                    "row": {**D20, "quantity": "3"}}), ACTOR, "One more")
        self.assertEqual(again.dice_set("home").rows[0].id, row.id)          # edited in place
        with db.connect("ro", dbname=name) as c:
            stored = c.execute("select space_id, item_type, die_size, design, quantity from dice_counter").fetchall()
            audited = c.execute("select op from audit.row_change where table_name = 'dice_counter' order by id").fetchall()
        self.assertEqual(stored, [("home", "die", "d20", "red", 3)])
        self.assertEqual([r[0] for r in audited], ["INSERT", "UPDATE"])
        with db.connect("app", dbname=name) as c, self.assertRaises(Exception):
            c.execute("insert into dice_counter (space_id, position, item_type, die_size, quantity) "
                      "values ('home', 1, 'counter', 'd6', 1)")           # a counter has no size
