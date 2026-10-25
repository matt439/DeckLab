"""Retiring a real disposable-db deck preserves reads of its actual saved result JSON."""
import json
from unittest import mock

from decklab.lib import api, decks, inventory
from decklab.lib import forge as real_forge
from decklab.lib.api import retirement
from decklab.tests import db_support, test_deck_retirement as support, test_forge
from decklab.tests import test_inventory_contract as contract


class RetiredSavedMatchupTests(support._Fixture, db_support.DbTestCase):
    def setUp(self):
        super().setUp()
        from decklab.db import profiles_sync
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        self.put("casual/building", support.deck_text("Building", "building", "wife").replace("4 Opt", "4 Llanowar Elves"))
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=self.dbname)
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(contract.adapt(self.backend.load()), contract.CLAUDE, "Saved-matchup fixture",
                       contents={}, dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))
        self.folder = self.root / "forge"
        self.results = self.folder / "results"
        self.results.mkdir(parents=True)
        for patcher in (
                mock.patch.object(api.forge_runs, "_forge_module", return_value=real_forge),
                mock.patch.object(real_forge.common, "DATA_DIR", self.folder),
                mock.patch.object(real_forge, "status", return_value={"ready": False, "problem": "Fixture only"}),
                mock.patch.object(real_forge.engine, "is_current", return_value=False),
                mock.patch.object(real_forge.engine, "today", side_effect=AssertionError("No engine setup in fixture")),
                mock.patch.object(real_forge.ai, "side_ai", return_value={"cannot_play": []}),
                mock.patch.object(real_forge.views, "_side_cards_or_none", return_value=None),
                mock.patch.object(api.forge_runs, "_estimates", return_value=None),
                mock.patch.object(real_forge.runner, "run", side_effect=AssertionError("No Forge games"))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_saved_key_and_captured_sides_remain_readable_after_retirement_and_restore(self):
        result = test_forge.stored([(0, "win", 0), (1, "win", 1)])
        for side, deck_id in zip(result["sides"], (support.DECK_ID, "casual/building")):
            sections = decks.load_deck(deck_id, "target")
            side["card_sha"] = real_forge.card_sha(sections, "constructed")
            side["cards"] = real_forge.lists._section_cards(sections)
            side["card_count"] = sum(line.quantity for lines in sections.values() for line in lines)
            side["seen_as"] = [{"id": deck_id, "version": "target", "title": "Captured " + deck_id,
                                "when": "2026-10-01T10:00:00"}]
        path = self.results / (result["key"] + ".json")
        path.write_text(json.dumps(result), encoding="utf-8")
        original = path.read_bytes()
        self.assertIsNotNone(real_forge.load(result["key"]))
        before = api.matchup(key=result["key"])
        self.assertTrue(all(side["current"] for side in before["sides"]))
        retirement.retire_deck(self.body())
        deleted = inventory.last_revision(support.DECK_ID).revision
        listed = next(item for item in api.matchups()["results"] if item["key"] == result["key"])
        captured = next(side for side in listed["sides"] if side["id"] == support.DECK_ID)
        self.assertFalse(captured["current"])
        self.assertEqual(captured["title"], "Captured " + support.DECK_ID)
        read = api.matchup(key=result["key"])
        self.assertEqual((read["key"], read["status"], read["result"]["games"]), (result["key"], "done", 2))
        self.assertEqual({side["id"] for side in read["sides"]}, {support.DECK_ID, "casual/building"})
        self.assertFalse(next(side for side in read["sides"] if side["id"] == support.DECK_ID)["current"])
        retirement.restore_deck(json.dumps({"profile": "matt", "id": support.DECK_ID,
                                           "retired_revision": deleted}).encode("utf-8"))
        restored = api.matchup(key=result["key"])
        self.assertTrue(next(side for side in restored["sides"] if side["id"] == support.DECK_ID)["current"])
        self.assertEqual(path.read_bytes(), original)
