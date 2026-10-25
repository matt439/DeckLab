"""Rename identity, bytes and revision contracts against snapshots and disposable PostgreSQL."""
import json
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import ops_decks, ops_rename, pg, pg_aliases, paths, rules
from decklab.lib.inventory.model import Deck, Sheet, QUEUE_FIELDS
from decklab.lib.state import Invalid, Unavailable
from decklab.tests import db_support
from decklab.tests.test_inventory_contract import CLAUDE, FIXTURE_PROFILES, MATT

OLD, NEW = "casual/old-title", "casual/new-title"
TEXT = ("\ufeff# Old title\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** built\n"
        "- **Played by:** user\n- **Built version:** target\n- **Sleeves:** old red\n"
        "- **Deck box:** old box\n\n## Decklist\n\n```\nDeck\n60 Island\n\nSideboard\n1 Opt\n```\n\n"
        "## Notes\n\nDo not rewrite  this prose.\n")


def snapshot():
    return inventory.Inventory("1", decks_revision="1", decks={OLD: Deck("home", "casual", "old-title", TEXT,
                                                                       revision=1)}, aliases_ready=True,
                               deck_history_ids=(OLD,))


def operation(inv, title="New title", deck_id=OLD, **changes):
    from decklab.lib import decks
    held = inv.deck(deck_id)
    params = {"deck_id": deck_id, "new_slug": decks.title_slug(title), "title": title,
              "base_sha256": held.sha256, "revision": held.revision}
    params.update(changes)
    return inventory.Op("deck.rename", params)


class RenameOperationTests(unittest.TestCase):
    def test_title_replacement_keeps_existing_boms_and_crlf_outside_heading(self):
        text = "\ufeff\ufeff# Old title\r\n\r\nOriginal  prose.\r\n"
        self.assertEqual(ops_rename.title_text(text, "New title"),
                         "\ufeff\ufeff# New title\r\n\r\nOriginal  prose.\r\n")

    def test_changes_only_h1_and_exact_identity_preserving_kit_and_cards(self):
        before = snapshot()
        after, summary = operation(before).run(before)
        self.assertIsNone(after.deck(OLD))
        self.assertEqual(after.deck(NEW).text, TEXT.replace("# Old title\n", "# New title\n", 1))
        self.assertEqual(after.deck(NEW).rename_version, 1)
        self.assertEqual(after.deck_aliases, {OLD: NEW})
        self.assertEqual(summary.extra["renamed"], {"from": OLD, "to": NEW})
        self.assertEqual(inventory.resolve_deck_id(OLD, after), NEW)
        self.assertEqual(inventory.deck_lineage(OLD, after), (NEW, OLD))
        self.assertTrue(inventory.same_deck_id(OLD, NEW, after))
        self.assertFalse(inventory.same_deck_id(OLD, "casual/other", after))
        self.assertIsNone(after.deck(OLD))                 # writes never resolve aliases
        with self.assertRaises(TypeError):
            after.deck_aliases[OLD] = "casual/other"

    def test_title_only_change_and_exact_noop(self):
        before = snapshot()
        renamed, _ = operation(before, "Old Title").run(before)
        self.assertEqual(renamed.deck(OLD).text, TEXT.replace("Old title", "Old Title", 1))
        self.assertEqual(renamed.deck_aliases, {})
        same, summary = operation(before, "Old title").run(before)
        self.assertIs(same, before)
        self.assertEqual(summary.text, "Nothing to change")

    def test_reverse_rename_flattens_the_entire_lineage(self):
        initial = snapshot()
        second, _ = operation(initial).run(initial)
        second = second.with_deck(second.deck(NEW).replace(revision=2))
        third, _ = operation(second, "Third title", NEW).run(second)
        third_id = "casual/third-title"
        self.assertEqual(third.deck_aliases, {OLD: third_id, NEW: third_id})
        third = third.with_deck(third.deck(third_id).replace(revision=3))
        reverted, _ = operation(third, "Old title", third_id).run(third)
        self.assertEqual(reverted.deck_aliases, {NEW: OLD, third_id: OLD})
        self.assertEqual(inventory.resolve_deck_id(NEW, reverted), OLD)
        self.assertEqual(reverted.deck(OLD).text, TEXT)
        self.assertEqual(reverted.deck(OLD).rename_version, 3)

    def test_rejects_stale_revision_sha_and_invalid_names(self):
        before = snapshot()
        for changes, error in (({"revision": 2}, ops_decks.DeckRefused), ({"revision": True}, Invalid),
                               ({"revision": 0}, Invalid), ({"base_sha256": "0" * 64}, ops_decks.DeckRefused),
                               ({"new_slug": "other"}, Invalid), ({"new_slug": "con", "title": "con"}, Invalid),
                               ({"title": " space "}, Invalid), ({"title": "Bad\nTitle"}, Invalid),
                               ({"title": "x" * 101}, Invalid), ({"title": "Bad\x7fTitle"}, Invalid)):
            with self.subTest(changes=changes), self.assertRaises(error):
                operation(before, **changes).run(before)
        self.assertEqual(before, snapshot())

    def test_refuses_unrelated_active_alias_and_retired_history_namespace(self):
        for claimed in (NEW, "commander/new-title", "commander/NEW-TITLE"):
            with self.subTest(claimed=claimed):
                before = snapshot().replace(deck_history_ids=(OLD, claimed))
                with self.assertRaises(ops_decks.DeckRefused):
                    operation(before).run(before)
        before = snapshot().replace(deck_aliases={NEW: "casual/another"})
        with self.assertRaises(ops_decks.DeckRefused):
            operation(before).run(before)

    def test_former_slug_cannot_be_created_in_either_kind(self):
        renamed, _ = operation(snapshot()).run(snapshot())
        for kind in ("casual", "commander"):
            with self.subTest(kind=kind), self.assertRaises(ops_decks.DeckRefused):
                ops_decks.create(renamed, space="home", kind=kind, slug="old-title", text=TEXT)

    def test_absent_capability_is_a_clear_refusal_and_other_saves_still_work(self):
        before = snapshot().replace(aliases_ready=False)
        with self.assertRaisesRegex(Unavailable, "migration"):
            operation(before).run(before)
        saved, _ = ops_decks.save(before, deck_id=OLD, text=TEXT + "More.\n", base_sha256=before.deck(OLD).sha256)
        self.assertTrue(saved.deck(OLD).text.endswith("More.\n"))

    def test_same_personal_space_and_prior_legacy_headers_are_preserved(self):
        personal = Deck("user2", "casual", "old-title", TEXT, revision=1)
        before = snapshot().replace(decks={personal.id: personal}, deck_history_ids=(personal.id,))
        after, _ = operation(before, deck_id=personal.id).run(before)
        self.assertEqual(after.deck("user2/casual/new-title").text, TEXT.replace("# Old title", "# New title", 1))

    def test_helpers_use_pinned_snapshot_and_leave_unknown_ids_unchanged(self):
        renamed, _ = operation(snapshot()).run(snapshot())
        with inventory.pinned(renamed):
            self.assertEqual(inventory.resolve_deck_id(OLD), NEW)
            self.assertEqual(inventory.deck_lineage(NEW), (NEW, OLD))
            self.assertTrue(inventory.same_deck_id(OLD, NEW))
            self.assertEqual(inventory.resolve_deck_id("product/fixture"), "product/fixture")


class RenameDatabaseTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        # An inventory and deck fixture, no connection ever addresses the real database.
        fixture = snapshot().replace(deck_aliases={}, status=Sheet(paths.STATUS, tuple(rules.STATUS_FIELDS), (), True),
                                     watchlist=Sheet(paths.WATCHLIST, QUEUE_FIELDS, (), True))
        pg.write_model(fixture, CLAUDE, "Import rename fixture", dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname)

    def rows(self, query, params=()):
        with self.connect() as c:
            return c.execute(query, params).fetchall()

    def apply_rename(self, title="New title", deck_id=OLD):
        before = self.backend.load()
        return self.backend.apply(operation(before, title, deck_id), MATT, f"Rename fixture to {title}")[0]

    def test_one_audited_change_preserves_history_kit_text_and_derived_lines(self):
        before = self.backend.load()
        original_rows = self.rows("select * from deck_revision order by deck_id, revision")
        kit = self.rows("select kit_version from deck where id = %s", (OLD,))[0][0]
        after = self.apply_rename()
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(int(after.decks_revision), int(before.decks_revision) + 1)
        self.assertEqual(after.deck(NEW).revision, 2)
        self.assertEqual(after.deck(NEW).rename_version, 1)
        self.assertIsNone(after.deck(OLD))
        self.assertEqual(self.rows("select kit_version from deck where id = %s", (NEW,)), [(kit,)])
        self.assertEqual(self.rows("select * from deck_revision where deck_id = %s order by revision", (OLD,)), original_rows)
        self.assertEqual(self.rows("select distinct deck_id from deck_line"), [(NEW,)])
        self.assertEqual(self.rows("select deck_id from deck_text"), [(NEW,)])
        revisions = self.backend.deck_revisions(OLD)
        self.assertEqual([(r.deck_id, r.revision, r.op, r.kit) for r in revisions],
                         [(NEW, 2, "M", False), (OLD, 1, "A", True)])
        self.assertEqual(self.backend.deck_revision(NEW, 1).text, TEXT)
        self.assertEqual(self.backend.last_revision(OLD).deck_id, NEW)
        self.assertEqual(self.rows("select count(*) from audit.change_set"), [(2,)])
        self.assertEqual(self.rows("select op from audit.row_change where table_name='deck' "
                                  "and change_set_id=(select max(id) from audit.change_set)"), [("UPDATE",)])

    def test_multiple_reverse_renames_normal_save_retirement_and_restore_keep_numbers(self):
        after = self.apply_rename()
        after = self.apply_rename("Third title", NEW)
        after = self.apply_rename("Old title", "casual/third-title")
        held = after.deck(OLD)
        after, _ = self.backend.apply(inventory.Op("deck.save", {"deck_id": OLD, "text": TEXT + "After.\n",
                                      "base_sha256": held.sha256}), MATT, "Edit after reverse rename")
        self.assertEqual(after.deck(OLD).revision, 5)
        # Use the same backend lifecycle primitive; kit cleared only in this disposable fixture.
        class Drop:
            kind, params = "test.drop", {}
            def run(self, inv):
                return inv.without_deck(OLD), inventory.Summary("Retire fixture")
        self.backend.apply(Drop(), MATT, "Retire fixture")
        after, _ = self.backend.apply(inventory.Op("deck.create", {"space": "home", "kind": "casual", "slug": "old-title",
                                      "text": TEXT, "owners": None}), MATT, "Restore fixture")
        self.assertEqual(after.deck(OLD).revision, 7)
        history = self.backend.deck_revisions_with_text(NEW, 20)
        self.assertEqual([r.revision for r in history], list(range(7, 0, -1)))
        self.assertEqual([r.op for r in history], ["A", "D", "M", "M", "M", "M", "A"])
        self.assertEqual({r.deck_id for r in history}, {OLD, NEW, "casual/third-title"})

    def test_failure_rolls_back_deck_alias_revisions_cascades_and_audit(self):
        before = self.backend.load()
        with mock.patch.object(pg_aliases, "write", side_effect=RuntimeError("Injected alias failure")):
            with self.assertRaisesRegex(RuntimeError, "Injected"):
                self.apply_rename()
        self.assertEqual(self.backend.load(), before)
        self.assertEqual(self.rows("select count(*) from audit.change_set"), [(1,)])
        self.assertEqual(self.rows("select count(*) from deck_revision"), [(1,)])
        self.assertEqual(self.rows("select count(*) from deck_alias"), [(0,)])
        self.assertEqual(self.rows("select distinct deck_id from deck_line"), [(OLD,)])

    def test_retired_unrelated_destination_is_refused_and_not_merged(self):
        before = self.backend.load()
        rival = Deck("home", "casual", "new-title", TEXT.replace("Old title", "New title"))
        class Add:
            kind, params = "test.add", {}
            def run(self, inv):
                return inv.with_deck(rival), inventory.Summary("Rival")
        class Drop:
            kind, params = "test.drop", {}
            def run(self, inv):
                return inv.without_deck(rival.id), inventory.Summary("Retire rival")
        self.backend.apply(Add(), MATT, "Create unrelated destination")
        self.backend.apply(Drop(), MATT, "Retire unrelated destination")
        with self.assertRaises(ops_decks.DeckRefused):
            self.apply_rename()
        self.assertEqual(self.backend.load().deck(OLD).text, before.deck(OLD).text)
        self.assertEqual([r.op for r in self.backend.deck_revisions(NEW)], ["D", "A"])

    def test_stale_revision_blocks_aba_even_when_text_is_back_to_original(self):
        original = self.backend.load()
        self.apply_rename()
        self.apply_rename("Old title", NEW)
        self.assertEqual(self.backend.load().deck(OLD).sha256, original.deck(OLD).sha256)
        with self.assertRaises(ops_decks.DeckRefused):
            self.backend.apply(operation(original), MATT, "Stale rename")
        self.assertEqual(self.rows("select count(*) from audit.change_set"), [(3,)])

    def test_destination_taken_after_preview_is_refused_under_the_writer_lock(self):
        preview = self.backend.load()
        # A different client creates the destination after the preview was rendered.
        self.backend.apply(inventory.Op("deck.create", {"space": "home", "kind": "casual", "slug": "new-title",
                           "text": TEXT, "owners": None}), MATT, "Concurrent destination")
        with self.assertRaises(ops_decks.DeckRefused):
            self.backend.apply(operation(preview), MATT, "Stale destination preview")
        self.assertEqual(self.rows("select count(*) from audit.change_set"), [(2,)])
        self.assertEqual(self.rows("select count(*) from deck_alias"), [(0,)])
        self.assertIsNotNone(self.backend.load().deck(OLD))

    def test_reversed_name_remains_the_latest_edit_and_noop_adds_no_revision(self):
        original = self.backend.load()
        same, _ = self.backend.apply(operation(original, "Old title"), MATT, "No change")
        self.assertIs(same, original)
        self.assertEqual(self.rows("select count(*) from audit.change_set"), [(1,)])
        self.apply_rename()
        final = self.apply_rename("Old title", NEW)
        newest = self.backend.last_revision(OLD)
        self.assertEqual(self.backend.deck_edited()[OLD], newest.at)
        self.assertEqual(final.deck(OLD).revision, 3)

    def test_rename_version_advances_for_title_only_and_reverse_but_not_normal_save(self):
        before = self.backend.load()
        self.assertEqual(before.deck(OLD).rename_version, 0)
        renamed = self.apply_rename("Old Title")                 # same slug, changed title
        self.assertEqual(renamed.deck(OLD).rename_version, 1)
        held = renamed.deck(OLD)
        saved, _ = self.backend.apply(inventory.Op("deck.save", {"deck_id": OLD, "text": held.text + "Edit.\n",
                                      "base_sha256": held.sha256}), MATT, "Ordinary save")
        self.assertEqual(saved.deck(OLD).rename_version, 1)
        held = saved.deck(OLD)
        with inventory.pinned(saved):
            preview, _ = inventory.preview(operation(saved))
        self.assertEqual(preview.deck(NEW).rename_version, 2)
        renamed = self.apply_rename()
        self.assertEqual(renamed.deck(NEW).rename_version, 2)
        reversed_deck = self.apply_rename("Old title", NEW)
        self.assertEqual(reversed_deck.deck(OLD).rename_version, 3)
        unchanged, _ = self.backend.apply(operation(reversed_deck, "Old title"), MATT, "No-op rename")
        self.assertEqual(unchanged.deck(OLD).rename_version, 3)

    def test_former_id_cannot_be_recreated_after_renamed_deck_is_retired(self):
        self.apply_rename()
        class Drop:
            kind, params = "test.drop", {}
            def run(self, inv):
                return inv.without_deck(NEW), inventory.Summary("Retire renamed fixture")
        self.backend.apply(Drop(), MATT, "Retire renamed fixture")
        for kind in ("casual", "commander"):
            with self.subTest(kind=kind), self.assertRaises(ops_decks.DeckRefused):
                self.backend.apply(inventory.Op("deck.create", {"space": "home", "kind": kind, "slug": "old-title",
                                   "text": TEXT, "owners": None}), MATT, "Reuse former id")
        self.assertEqual([(r.revision, r.op) for r in self.backend.deck_revisions(OLD)],
                         [(3, "D"), (2, "M"), (1, "A")])

    def test_retirement_restoration_starts_fresh_packing_epoch_and_next_rename_advances(self):
        from decklab.lib import access
        from decklab.lib.api import guard, retirement, settings
        first, second = "casual/lifecycle-a", "casual/lifecycle-b"
        text = ("# Lifecycle a\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** idea\n"
                "- **Played by:** user\n\n## Decklist\n\n```\nDeck\n60 Island\n```\n")
        created, _ = self.backend.apply(inventory.Op("deck.create", {"space": "home", "kind": "casual",
                                      "slug": "lifecycle-a", "text": text, "owners": None}), MATT, "Create lifecycle fixture")
        self.assertEqual(created.deck(first).rename_version, 0)
        self.apply_rename("Lifecycle b", first)
        renamed = self.apply_rename("Lifecycle a", second)
        self.assertEqual(renamed.deck(first).rename_version, 2)
        held = renamed.deck(first)
        with inventory.use(self.backend), mock.patch.object(guard, "viewer", return_value=FIXTURE_PROFILES[0]), \
                mock.patch.object(access, "viewer", return_value="matt"), \
                mock.patch.object(settings, "_config_profiles", return_value=FIXTURE_PROFILES):
            answer = retirement.retire_deck(json.dumps({"profile": "matt", "id": first,
                "sha256": held.sha256, "revision": held.revision, "reason": "Retire lifecycle fixture."}).encode())
            self.assertTrue(answer["retired"])
            deleted = self.backend.last_revision(first)
            answer = retirement.restore_deck(json.dumps({"profile": "matt", "id": first,
                                                          "retired_revision": deleted.revision}).encode())
            self.assertTrue(answer["restored"])
        restored = self.backend.load().deck(first)
        self.assertEqual(restored.rename_version, restored.revision)
        self.assertGreater(restored.rename_version, 2)
        self.assertEqual(restored.text, text)
        following = self.apply_rename("Lifecycle b", first).deck(second)
        self.assertEqual(following.rename_version, restored.rename_version + 1)
        self.assertLessEqual(following.rename_version, following.revision)

    def test_old_schema_keeps_reads_saves_and_detects_new_capability_without_cache_clear(self):
        with self.connect("owner") as c:
            c.execute("drop table deck_alias")
            c.execute("alter table deck drop column rename_version")
        backend = pg.PgInventory(dbname=self.dbname)
        before = backend.load()
        self.assertFalse(before.aliases_ready)
        self.assertEqual(before.deck(OLD).rename_version, 0)
        with self.assertRaises(Unavailable):
            backend.apply(operation(before), MATT, "Cannot rename yet")
        saved, _ = backend.apply(inventory.Op("deck.save", {"deck_id": OLD, "text": TEXT + "Older schema.\n",
                                    "base_sha256": before.deck(OLD).sha256}), MATT, "Save on old schema")
        self.assertEqual(saved.deck(OLD).revision, 2)
        # Ordinary deck creation remains usable without the new column, too.
        created, _ = backend.apply(inventory.Op("deck.create", {"space": "home", "kind": "casual",
                                     "slug": "legacy-created", "text": TEXT, "owners": None}),
                                   MATT, "Create on old schema")
        self.assertEqual(created.deck("casual/legacy-created").rename_version, 0)
        # Recreate only this disposable table. No schema change touches production.
        with self.connect("owner") as c:
            migration = Path(__file__).parents[1] / "db/migrations/0010_deck_aliases.sql"
            c.execute(migration.read_text(encoding="utf-8"))
        fresh = backend.load()
        self.assertTrue(fresh.aliases_ready)
        self.assertIsNot(fresh, saved)
        after, _ = backend.apply(operation(fresh), MATT, "Rename after migration")
        self.assertEqual(after.deck(NEW).revision, 3)


if __name__ == "__main__":
    unittest.main()
