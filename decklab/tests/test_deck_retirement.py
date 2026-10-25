"""Deck retirement and exact restoration over temporary files and a disposable database."""
import contextlib
import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import access, config, decks, inventory
from decklab.lib.api import retirement
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.lib.inventory.files import FileInventory
from decklab.lib.inventory.rules import STATUS_FIELDS
from decklab.tests import db_support, test_inventory_contract as contract


DECK_ID = "casual/retire-me"
REASON = "This deck idea is no longer in the plan."


def deck_text(title="Retirement fixture", status="idea", player="user"):
    played = f"- **Played by:** {player}\n" if player else ""
    return (f"# {title}\n\n- **Format:** Casual 60-card, 1v1\n{played}- **Status:** {status}\n\n"
            "## Decklist\n\n```\nDeck\n4 Opt\n56 Island\n```\n\n"
            "## Notes\n\nPreserve this exact prose and these line endings.\n")


class _Fixture:
    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.magic = self.root / "magic"
        self.put(DECK_ID, deck_text())
        self.put("casual/building", deck_text("Building", "building", "wife"))
        self.put("casual/built", deck_text("Built without kit", "built"))
        self.put("user2/casual/private", deck_text("Personal fixture", player=None))
        status = self.magic / "products" / "status.csv"
        status.parent.mkdir(parents=True)
        status.write_text(",".join(STATUS_FIELDS) + "\n", encoding="utf-8")
        self.result_file = self.root / "saved-results" / "record.json"
        self.result_file.parent.mkdir()
        self.result_file.write_bytes(b'{"deck":"casual/retire-me","games":[1,2,3]}\n')
        listed = copy.deepcopy(contract.FIXTURE_PROFILES)
        next(profile for profile in listed if profile["id"] == "user1")["role"] = "member"
        self.config_file = self.root / "config.json"
        self.config_file.write_text(json.dumps({"profiles": listed}), encoding="utf-8")
        self.backend = FileInventory(self.root)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(config, "CONFIG_FILE", self.config_file))
        stack.enter_context(mock.patch.dict(os.environ, {config.EXTRA_ENV: ""}))
        stack.enter_context(mock.patch.object(decks, "DECKS_DIR", self.magic / "decks"))
        stack.enter_context(mock.patch.object(access, "viewer", return_value="matt"))
        stack.enter_context(inventory.use(self.backend))

    def put(self, deck_id, text):
        parts = deck_id.split("/")
        if len(parts) == 2:
            path = self.magic / "decks" / parts[0] / (parts[1] + ".md")
        else:
            path = self.magic / "people" / parts[0] / "decks" / parts[1] / (parts[2] + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def body(self, **changes):
        current = self.backend.load().deck(DECK_ID)
        values = {"profile": "matt", "id": DECK_ID, "sha256": current.sha256,
                  "revision": max(1, current.revision), "reason": REASON}
        values.update(changes)
        return json.dumps(values).encode("utf-8")

    def retire(self, **changes):
        return retirement.retire_deck(self.body(**changes))

    def restore(self, number, *, deck_id=DECK_ID, profile="matt"):
        return retirement.restore_deck(json.dumps({"profile": profile, "id": deck_id,
                                                   "retired_revision": number}).encode("utf-8"))

    def assert_api_error(self, status, function, *args, **kwargs):
        with self.assertRaises(ApiError) as error:
            function(*args, **kwargs)
        self.assertEqual(error.exception.status, status, error.exception.message)
        return error.exception

    def assert_unchanged(self, before):
        after = self.backend.load()
        self.assertEqual(files.render(after, decks=True), files.render(before, decks=True))
        self.assertEqual((after.revision, after.decks_revision), (before.revision, before.decks_revision))


class FileRetirementTests(_Fixture, unittest.TestCase):
    def test_preview_explains_missing_durable_history_and_built_refusal(self):
        for deck_id in (DECK_ID, "casual/building", "casual/built"):
            with self.subTest(deck_id=deck_id):
                answer = retirement.retirement_view(deck_id)
                self.assertEqual(answer["id"], deck_id)
                self.assertEqual(answer["sha256"], self.backend.load().deck(deck_id).sha256)
                self.assertFalse(answer["may_retire"])
                self.assertTrue(answer["why_not"])

    def test_no_durable_history_means_no_deletion_or_saved_result_changes(self):
        before = self.backend.load()
        result = self.result_file.read_bytes()
        self.assert_api_error(503, self.retire)
        self.assert_unchanged(before)
        self.assertEqual(self.result_file.read_bytes(), result)

    def test_reason_sha_and_integer_revision_are_required_without_writes(self):
        before = self.backend.load()
        for values, status in (({"reason": " "}, 400), ({"reason": None}, 400), ({"reason": 3}, 400),
                               ({"reason": "line\nbreak"}, 400), ({"reason": "tab\twhy"}, 400),
                               ({"reason": "why\x7f"}, 400),
                               ({"sha256": ""}, 400),
                               ({"revision": True}, 400), ({"revision": "1"}, 400), ({"revision": 0}, 400)):
            with self.subTest(values=values):
                self.assert_api_error(status, self.retire, **values)
                self.assert_unchanged(before)

    def test_built_deck_without_kit_cannot_be_retired(self):
        before = self.backend.load()
        self.assert_api_error(409, self.retire, id="casual/built", sha256=before.deck("casual/built").sha256)
        self.assert_unchanged(before)

    def test_unbuilt_deck_with_held_kit_cannot_be_retired(self):
        self.put(DECK_ID, deck_text().replace("- **Status:** idea\n", "- **Status:** idea\n- **Sleeves:** old red\n"))
        before = self.backend.load()
        self.assert_api_error(409, self.retire)
        self.assert_unchanged(before)

    def test_member_permissions_apply_on_the_home_network_and_to_preview(self):
        before = self.backend.load()
        with mock.patch.object(access, "viewer", return_value="user1"):
            preview = retirement.retirement_view(DECK_ID)
            self.assertFalse(preview["may_retire"])
            self.assertTrue(preview["why_not"])
            self.assert_api_error(403, self.retire, profile="user1")
        self.assert_unchanged(before)

    def test_own_personal_deck_still_requires_durable_history(self):
        personal = self.backend.load().deck("user2/casual/private")
        with mock.patch.object(access, "viewer", return_value="user2"):
            self.assert_api_error(503, self.retire, profile="user2", id=personal.id, sha256=personal.sha256)
        self.assertIsNotNone(self.backend.load().deck(personal.id))
        self.assertIsNotNone(self.backend.load().deck(DECK_ID))

    def test_products_pairings_and_malformed_ids_are_not_saved_deck_retirements(self):
        before = self.backend.load()
        for deck_id in ("product/anything", "pairing/cats+elves", "casual/../secret", "", None):
            with self.subTest(deck_id=deck_id):
                self.assert_api_error(400, retirement.retirement_view, deck_id)
        self.assert_unchanged(before)

    def test_legacy_read_only_deck_name_is_refused_before_any_retirement_write(self):
        deck_id = "casual/Legacy_Name"
        self.put(deck_id, deck_text("Legacy read-only fixture"))
        before = self.backend.load()
        with mock.patch.object(inventory, "apply") as apply:
            self.assert_api_error(400, retirement.retirement_view, deck_id)
            self.assert_api_error(400, self.retire, id=deck_id, sha256=before.deck(deck_id).sha256, revision=1)
        apply.assert_not_called()
        self.assert_unchanged(before)


class PgRetirementTests(_Fixture, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(contract.adapt(self.backend.load()), contract.CLAUDE, "Import retirement fixture",
                       contents={}, dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def count(self):
        with self.connect() as connection:
            return connection.execute("select count(*) from audit.change_set").fetchone()[0]

    def retired(self):
        before = self.backend.load().deck(DECK_ID)
        answer = self.retire()
        self.assertEqual(answer, {"retired": True, "id": DECK_ID, "title": "Retirement fixture",
                                  "history": "#/history?id=casual%2Fretire-me"})
        return before, inventory.last_revision(DECK_ID).revision

    def test_stale_sha_and_revision_are_refused_without_new_audit_or_deletion(self):
        before, count = self.backend.load(), self.count()
        for changes in ({"sha256": "0" * 64}, {"revision": before.deck(DECK_ID).revision + 1}):
            with self.subTest(changes=changes):
                self.assert_api_error(409, self.retire, **changes)
                self.assert_unchanged(before)
                self.assertEqual(self.count(), count)

    def test_retire_and_restore_preserve_exact_text_history_results_and_audit_reason(self):
        before, count = self.backend.load(), self.count()
        text, result = before.deck(DECK_ID).text, self.result_file.read_bytes()
        preview = retirement.retirement_view(DECK_ID)
        self.assertTrue(preview["may_retire"])
        self.assertEqual(preview["revision"], before.deck(DECK_ID).revision)
        _, retired_number = self.retired()
        self.assertEqual(self.count(), count + 1)
        deleted = inventory.last_revision(DECK_ID)
        self.assertEqual(deleted.op, "D")
        self.assertIsNone(inventory.deck_revision(DECK_ID, retired_number).text)
        self.assertEqual(inventory.deck_revision(DECK_ID, retired_number - 1).text, text)
        with self.connect() as connection:
            actor, reason = connection.execute("select actor, reason from audit.change_set order by id desc limit 1").fetchone()
        self.assertEqual((actor, reason), ("matt", REASON))
        answer = self.restore(retired_number)
        self.assertTrue(answer["restored"])
        after = self.backend.load()
        self.assertEqual(after.deck(DECK_ID).text, text)
        self.assertNotEqual(after.decks_revision, before.decks_revision)
        self.assertEqual(self.count(), count + 2)
        self.assertEqual([(rev.revision, rev.op) for rev in inventory.deck_revisions(DECK_ID)],
                         [(retired_number + 1, "A"), (retired_number, "D"), (retired_number - 1, "A")])
        self.assertEqual(self.result_file.read_bytes(), result)

    def test_restore_requires_permission_on_the_retired_text(self):
        _, number = self.retired()
        before, count = self.backend.load(), self.count()
        with mock.patch.object(access, "viewer", return_value="user1"):
            self.assert_api_error(403, self.restore, number, profile="user1")
        self.assert_unchanged(before)
        self.assertEqual(self.count(), count)
        self.restore(number)
        self.assertIsNotNone(self.backend.load().deck(DECK_ID))

    def test_restore_refuses_a_case_insensitive_slug_now_taken_in_another_kind(self):
        old, number = self.retired()

        class LegacyName:
            # New names are lowercase, but stored legacy names can have mixed case.
            kind, params = "deck.create", {}

            def run(self, snapshot):
                legacy = old.replace(kind="commander", slug="RETIRE-ME")
                return snapshot.with_deck(legacy), inventory.Summary("Fixture legacy namespace reuse")

        inventory.apply(LegacyName(), contract.CLAUDE, "Concurrent legacy namespace reuse")
        before, count = self.backend.load(), self.count()
        self.assert_api_error(409, self.restore, number)
        self.assert_unchanged(before)
        self.assertEqual(self.count(), count)

    def test_members_can_retire_and_restore_their_building_or_personal_deck(self):
        for deck_id, profile in (("casual/building", "user1"), ("user2/casual/private", "user2")):
            with self.subTest(deck_id=deck_id), mock.patch.object(access, "viewer", return_value=profile):
                old = self.backend.load().deck(deck_id)
                preview = retirement.retirement_view(deck_id)
                self.assertTrue(preview["may_retire"])
                answer = self.retire(profile=profile, id=deck_id, sha256=old.sha256, revision=old.revision)
                self.assertTrue(answer["retired"])
                self.assertIsNone(self.backend.load().deck(deck_id))
                number = inventory.last_revision(deck_id).revision
                self.restore(number, deck_id=deck_id, profile=profile)
                self.assertEqual(self.backend.load().deck(deck_id).text, old.text)

    def test_restore_database_failure_keeps_retirement_and_its_history_unchanged(self):
        from decklab.lib.inventory import pg
        _, number = self.retired()
        before, count, diff = self.backend.load(), self.count(), pg._diff

        def fail(*args):
            diff(*args)
            raise RuntimeError("Injected restoration row-write failure")

        with mock.patch.object(pg, "_diff", side_effect=fail) as write, \
                self.assertRaisesRegex(Exception, "Injected restoration row-write failure"):
            self.restore(number)
        write.assert_called_once()
        self.assert_unchanged(before)
        self.assertEqual(self.count(), count)
        self.assertEqual((inventory.last_revision(DECK_ID).revision, inventory.last_revision(DECK_ID).op), (number, "D"))

    def test_restore_refuses_bad_or_stale_retirement_revision_and_existing_identity(self):
        _, number = self.retired()
        before, count = self.backend.load(), self.count()
        for invalid in (0, -1, True, "2", None, number - 1):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ApiError):
                    self.restore(invalid)
                self.assert_unchanged(before)
        self.restore(number)
        self.assert_api_error(409, self.restore, number)
        self.assertEqual(self.count(), count + 1)

    def test_retirement_database_failure_rolls_back_text_revision_and_audit(self):
        from decklab.lib.inventory import pg
        before, count, diff = self.backend.load(), self.count(), pg._diff

        def fail(*args):
            diff(*args)
            raise RuntimeError("Injected retirement row-write failure")

        with mock.patch.object(pg, "_diff", side_effect=fail) as write, \
                self.assertRaisesRegex(Exception, "Injected retirement row-write failure"):
            self.retire()
        write.assert_called_once()
        self.assert_unchanged(before)
        self.assertEqual(self.count(), count)
        self.assertEqual(inventory.last_revision(DECK_ID).op, "A")

    def test_restore_rechecks_retirement_history_after_a_delete_recreate_delete_race(self):
        old, number = self.retired()
        original_apply = self.backend.apply
        raced = False

        def race(op, actor, message, **kwargs):
            nonlocal raced
            if not raced:
                raced = True
                original_apply(inventory.Op("deck.create", {"space": old.space, "kind": old.kind, "slug": old.slug,
                               "text": old.text, "owners": None}), contract.CLAUDE, "Concurrent recreate")
                fresh = self.backend.load().deck(DECK_ID)
                original_apply(inventory.Op("deck.delete", {"deck_id": DECK_ID, "base_sha256": fresh.sha256}),
                               contract.CLAUDE, "Concurrent second retirement")
            return original_apply(op, actor, message, **kwargs)

        count = self.count()
        with mock.patch.object(self.backend, "apply", side_effect=race):
            self.assert_api_error(409, self.restore, number)
        self.assertTrue(raced)
        self.assertIsNone(self.backend.load().deck(DECK_ID))
        self.assertEqual(self.count(), count + 2)
        self.assertEqual(inventory.last_revision(DECK_ID).revision, number + 2)


if __name__ == "__main__":
    unittest.main()
