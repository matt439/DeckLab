"""Token-plan receipts protect every deck participant under the write lock.

FileInventory gives inventory and deck parts separate revisions. These fixtures
change only disposable deck files after API planning, immediately before apply.
"""
from unittest import mock

from decklab.lib import cards, inventory, tokens
from decklab.lib.api import token_plan
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import Op, ops_decks
from decklab.lib.state import Actor
from decklab.tests import household_config
from decklab.tests import test_api_tokens as token_fixture
from decklab.tests import test_token_reservation as reservation_fixture


class TokenPlanRevisionsTests(token_fixture.TokensApiTestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = cards._prepare(cards.build_index(token_fixture.FIXTURES / "tokens_cards.jsonl",
                                                      token_fixture.FIXTURES / "oracle_tags.jsonl", {}, log=lambda *a: None))

    def index(self):
        return self.loaded

    def setUp(self):
        household_config.use(self)
        super().setUp()

    def built(self, slug, packed=None):
        return self.write(f"decks/casual/{slug}.md", reservation_fixture.built(slug.upper(), packed=packed))

    def race_before_apply(self, change):
        """Exercise API receipt forwarding and the real lock-time op validation."""
        preview = token_plan.plan_view()
        self.assertGreater(preview["changes"], 0)
        original = token_plan.apply_op
        raced = {}

        def apply_after_change(*args, **kwargs):
            before = self.inventory.load()
            change()
            after = self.inventory.load()
            self.assertEqual(after.revision, before.revision)
            self.assertNotEqual(after.decks_revision, before.decks_revision)
            raced["files"] = self.magic_files()
            return original(*args, **kwargs)

        with mock.patch.object(token_plan, "apply_op", side_effect=apply_after_change) as applied:
            with self.assertRaises(ApiError) as caught:
                self.call(token_plan.apply_plan, sha256=preview["sha256"])
        self.assertEqual(applied.call_count, 1)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(str(caught.exception), token_plan.CHANGED)
        self.assertEqual(self.magic_files(), raced["files"])

    def test_unchanged_participant_changed_after_recompute_blocks_every_write(self):
        self.built("a", "4 Zombie // Zombie Knight")
        self.built("b")
        plan = {item["id"]: item for item in tokens.plan_token_cards()["decks"]}
        self.assertFalse(plan["casual/a"]["changed"])
        self.assertTrue(plan["casual/b"]["changed"])
        self.race_before_apply(lambda: self.built("a", "8 Zombie // Zombie Knight"))

    def test_new_built_deck_after_recompute_blocks_every_write(self):
        self.built("a")
        self.race_before_apply(lambda: self.built("new", "8 Zombie // Zombie Knight"))
        self.assertTrue((self.magic / "decks/casual/new.md").exists())

    def test_deleted_unchanged_participant_after_recompute_blocks_every_write(self):
        self.built("a", "4 Zombie // Zombie Knight")
        self.built("b")
        self.race_before_apply(lambda: (self.magic / "decks/casual/a.md").unlink())
        self.assertFalse((self.magic / "decks/casual/a.md").exists())

    def test_receipt_covers_deck_revision_when_planned_lines_are_identical(self):
        self.built("a", "8 Zombie // Zombie Knight")
        first = tokens.plan_token_cards()
        path = self.magic / "decks/casual/queen.md"
        path.write_bytes(path.read_bytes().replace(b"Queen Deck", b"Queen Deck revised"))
        second = tokens.plan_token_cards()
        self.assertEqual(first["inventory_revision"], second["inventory_revision"])
        self.assertNotEqual(first["decks_revision"], second["decks_revision"])
        self.assertEqual([(item["id"], item["sha256"], item["after"]) for item in first["decks"]],
                         [(item["id"], item["sha256"], item["after"]) for item in second["decks"]])
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_unchanged_receipts_save_normally_and_fresh_api_noop_changes_nothing(self):
        self.built("a")
        preview = token_plan.plan_view()
        self.assertEqual(self.call(token_plan.apply_plan, sha256=preview["sha256"]),
                         {"saved": 1, "decks": ["casual/a"]})
        before = self.magic_files()
        again = token_plan.plan_view()
        self.assertEqual(again["changes"], 0)
        self.assertEqual(self.call(token_plan.apply_plan, sha256=again["sha256"]), {"saved": 0, "decks": []})
        self.assertEqual(self.magic_files(), before)

    def test_empty_operation_accepts_unchanged_deck_revision_without_writes(self):
        self.built("a", "8 Zombie // Zombie Knight")
        snapshot = self.inventory.load()
        before = self.magic_files()
        after, _ = inventory.apply(Op("deck.token_cards", {"items": [],
                                  "expected_inventory_revision": snapshot.revision,
                                  "expected_decks_revision": snapshot.decks_revision}),
                                  Actor("matt", "Matt", "home"), "No-op disposable token plan")
        self.assertEqual(after.decks_revision, snapshot.decks_revision)
        self.assertEqual(self.magic_files(), before)

    def test_empty_operation_still_rejects_stale_deck_revision(self):
        self.built("a", "8 Zombie // Zombie Knight")
        snapshot = self.inventory.load()
        self.built("new", "")
        self.assertEqual(self.inventory.load().revision, snapshot.revision)
        before = self.magic_files()
        with self.assertRaises(ops_decks.DeckRefused) as caught:
            inventory.apply(Op("deck.token_cards", {"items": [],
                            "expected_inventory_revision": snapshot.revision,
                            "expected_decks_revision": snapshot.decks_revision}),
                            Actor("matt", "Matt", "home"), "Stale no-op disposable token plan")
        self.assertEqual(caught.exception.reason, "changed")
        self.assertEqual(self.magic_files(), before)
