"""Bulk packing progress cannot replace final physical-build validation (fixture data only)."""
import json
from unittest import mock

from decklab.lib import state
from decklab.lib.api import assembly, assembly_completion, assembly_ticks, settings
from decklab.lib.api.common import ApiError
from decklab.lib.state.memory import MemoryStore
from decklab.tests.test_assembly_completion import PROFILES, TABLE
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


def task(slug, name, quantity, kind="pull"):
    return json.dumps([f"casual/{slug}:target", f"{kind}|{name}", quantity, ""])


class BulkPackingSafeguardsTests(PreparationCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(state.use(MemoryStore()))
        patch = mock.patch.object(settings, "_config_profiles", return_value=PROFILES)
        patch.start()
        self.addCleanup(patch.stop)
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves\n20 Forest\n", table=TABLE)
        self.ids = [task("a", "Llanowar Elves", 4), task("a", "Forest", 20, kind="basic")]

    def preview(self):
        return assembly.assembly_preview(json.dumps({
            "profile": "matt", "decks": [{"id": "casual/a", "version": "target"}]}))

    def tick_all(self, profile="matt"):
        return assembly_ticks.packing_ticks(json.dumps({
            "profile": profile, "ids": self.ids,
            "changes": [{"id": key, "done": True} for key in self.ids]}))

    def build(self, plan, **changes):
        body = {"profile": "matt", "decks": [{"id": "casual/a", "version": "target"}],
                "fingerprint": plan["completion"]["fingerprint"], "confirmed": True, **changes}
        return assembly_completion.mark_built(json.dumps(body))

    def assert_refused(self, status, plan, **changes):
        with self.assertRaises(ApiError) as caught:
            self.build(plan, **changes)
        self.assertEqual(caught.exception.status, status)
        self.assertIn("- **Status:** building", (self.magic / "decks/casual/a.md").read_text())

    def test_one_bulk_patch_only_saves_progress_and_final_confirmation_stays_separate(self):
        plan = self.preview()
        before = {path: path.read_bytes() for path in self.magic.rglob("*") if path.is_file()}
        other = task("other", "Elvish Mystic", 2)
        assembly_ticks.packing_ticks(json.dumps({"profile": "user1", "ids": [other],
                                                "changes": [{"id": other, "done": True}]}))
        with mock.patch.object(self.inventory, "apply", wraps=self.inventory.apply) as apply:
            progress = self.tick_all()
            self.assertEqual(progress["ticks"], self.ids)
            self.assertEqual(progress["activity"]["checks"], len(self.ids))
            self.assertEqual(self.preview()["completion"], plan["completion"])
            self.assert_refused(400, plan, confirmed=False)
            apply.assert_not_called()
        self.assertEqual(before, {path: path.read_bytes() for path in self.magic.rglob("*") if path.is_file()})
        self.assertEqual(assembly_ticks.packing_ticks(json.dumps({"ids": [other]}))["ticks"], [other])

    def test_checked_available_cards_do_not_hide_missing_or_incoming_sideboard(self):
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves\n20 Forest\n\nSideboard\n1 Elvish Mystic\n",
                  table=TABLE)
        for incoming in (False, True):
            with self.subTest(incoming=incoming):
                if incoming:
                    self.cards_csv("orders/arrival.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 1))
                plan = self.preview()
                self.tick_all()
                self.assertFalse(plan["ready"])
                self.assertFalse(plan["completion"]["can_mark_built"])
                with mock.patch.object(self.inventory, "apply", wraps=self.inventory.apply) as apply:
                    self.assert_refused(409, plan)
                    apply.assert_not_called()

    def test_bulk_progress_keeps_writer_permissions_and_stale_build_refusal(self):
        with self.assertRaises(ApiError) as caught:
            self.tick_all("user2")
        self.assertEqual(caught.exception.status, 403)
        # User1 may share the pulling, but this fixture's deck is Matt's to finish.
        path = self.magic / "decks/casual/a.md"
        path.write_text(path.read_text().replace("- **Played by:** either", "- **Played by:** user"),
                        encoding="utf-8")
        plan = self.preview()
        self.tick_all("user1")
        self.assert_refused(403, plan, profile="user1")
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 3))
        self.assert_refused(409, plan)
