"""A real disposable-database rename preserves saved matchup and variant JSON."""
import json
from unittest import mock

from decklab.lib import api, decks, inventory
from decklab.lib import forge as real_forge
from decklab.tests import db_support, test_deck_retirement as support, test_forge
from decklab.tests import test_inventory_contract as contract


class RenamedSavedMatchupTests(support._Fixture, db_support.DbTestCase):
    def setUp(self):
        super().setUp()
        from decklab.db import profiles_sync
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        self.put("casual/building", support.deck_text("Building", "building", "wife").replace("4 Opt", "4 Llanowar Elves"))
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=self.dbname)
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(contract.adapt(self.backend.load()), contract.CLAUDE, "Saved-result rename fixture",
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
                mock.patch.object(real_forge.engine, "today", side_effect=AssertionError("No engine setup")),
                mock.patch.object(real_forge.ai, "side_ai", return_value={"cannot_play": []}),
                mock.patch.object(real_forge.views, "_side_cards_or_none", return_value=None),
                mock.patch.object(api.forge_runs, "_estimates", return_value=None),
                mock.patch.object(real_forge.runner, "run", side_effect=AssertionError("No Forge games"))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_real_rename_keeps_saved_keys_hashes_and_captures_with_current_links(self):
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
        test_id = "a" * 64
        summary = {"test": test_id, "base": {"id": support.DECK_ID, "version": "target"}, "opponents": [],
                   "created": "2026-10-01"}
        tests = real_forge.variants._tests_dir(self.results)
        tests.mkdir(parents=True)
        test_path = tests / (test_id + ".json")
        test_path.write_text(json.dumps(summary), encoding="utf-8")
        test_original = test_path.read_bytes()
        initial_revision = api.matchups()["decks_revision"]
        before = self.backend.load().deck(support.DECK_ID)
        inventory.apply(inventory.Op("deck.rename", {"deck_id": support.DECK_ID, "new_slug": "renamed-fixture",
                                                     "title": "Renamed fixture", "base_sha256": before.sha256,
                                                     "revision": before.revision}),
                        contract.CLAUDE, "Rename the saved-result fixture")
        canonical = "casual/renamed-fixture"
        self.assertEqual(inventory.resolve_deck_id(support.DECK_ID), canonical)
        listed = api.matchups()
        # The viewer's, as the library gives it (E10-S30), so the Matchups page can compare the two.
        from decklab.lib.api import guard, library
        self.assertEqual(listed["decks_revision"],
                         library.viewer_decks_revision(guard.visible_decks(decks.list_decks())))
        self.assertNotEqual(listed["decks_revision"], initial_revision)
        for answer in (api.matchup(key=result["key"]),
                       next(item for item in listed["results"] if item["key"] == result["key"])):
            side = next(side for side in answer["sides"] if side["id"] == canonical)
            self.assertEqual(side["title"], "Renamed fixture")
            self.assertTrue(side["current"])
            self.assertEqual(side["card_sha"], result["sides"][0]["card_sha"])
        tests_for = real_forge.variants.tests_for(canonical, "target", self.results)
        self.assertEqual([found["test"] for found in tests_for], [test_id])
        self.assertEqual(tests_for[0]["base"]["id"], support.DECK_ID)
        self.assertEqual((path.read_bytes(), test_path.read_bytes()), (original, test_original))
