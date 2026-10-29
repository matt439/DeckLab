"""HOME's saved field choices laid over disposable field selectors (E3-S23).

Run: python scripts/test_fixtures.py decklab.tests.test_field_policy_overlay

Fixture trees, stub stores and fake PostgreSQL objects only: no live database,
configured connector, card index or Forge game.
"""
import hashlib
import json
import types
import unittest
from unittest import mock

from decklab.lib import decks, inventory, state
from decklab.lib.forge import engine, field, field_exclusions as counts, field_membership, field_policy_overlay as overlay
from decklab.lib.forge import lists, rankings
from decklab.lib.inventory import deck_epoch
from decklab.lib.inventory.model import Deck, Inventory
from decklab.lib.inventory.pg import PgInventory
from decklab.lib.state import field_policy, pg_field_policy
from decklab.lib.state.memory import MemoryStore
from decklab.tests import test_forge_field as fixtures
from decklab.tests import test_pg_deck_epoch as pg_fixtures


def _epoch(deck_id, revision=1, kind="creation"):
    return {"kind": kind, "deck_id": deck_id, "revision": revision}


def _policy(fmt, *rules):
    return field_policy.normalize({"v": 1, "format": fmt, "revision": len(rules) or 0, "rules": list(rules)})


class Store:
    """A stub state store: field_policy(fmt) answers from a dict, or raises."""

    def __init__(self, policies=None, error=None):
        self.policies = policies or {}
        self.error = error
        self.reads = []

    def field_policy(self, fmt):
        self.reads.append(fmt)
        if self.error is not None:
            raise self.error
        return self.policies.get(fmt, field_policy.empty(fmt))


class OverlayTests(fixtures.FieldTestCase):
    def setUp(self):
        super().setUp()
        original = decks.list_decks
        patcher = mock.patch.object(decks, "list_decks", side_effect=lambda: [
            summary for summary in original() if not summary.get("error")])
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(field, "_side_id", side_effect=lambda entry, eng: "side-" + entry["card_sha"])
        patcher.start()
        self.addCleanup(patcher.stop)
        # Every current fixture deck is proved at its first creation unless a test says otherwise.
        self.unproved = set()
        self.epochs = mock.patch.object(overlay, "_epochs", side_effect=lambda ids: {
            deck_id: ("creation", deck_id, 1) for deck_id in ids if deck_id not in self.unproved})
        self.proving = self.epochs.start()
        self.addCleanup(self.epochs.stop)

    def configure(self, *, add=(), remove=()):
        fixtures._write(self.simulation, json.dumps({"field": {"Constructed": {
            "add": list(add), "remove": list(remove)}}}))

    def legacy(self, **options):
        with state.use(MemoryStore()):
            return field._field("Constructed", **options)

    def selected(self, store, fmt="Constructed", **options):
        observer = counts.Observation(options.get("visible"))
        with state.use(store):
            result = field._field(fmt, exclusions=observer, **options)
        return result, counts.count(observer)

    # ---------------------------------------------------------------- unchanged fields

    def test_no_store_installed_keeps_the_legacy_field_without_identity_reads(self):
        self.configure(remove=["casual/alpha"])
        before = self.legacy()
        observer = counts.Observation()
        self.assertEqual(field._field("Constructed", exclusions=observer), before)
        self.assertEqual(counts.count(observer), 1)
        self.proving.assert_not_called()

    def test_missing_migration_is_todays_field_exactly(self):
        self.configure(remove=["casual/alpha"])
        before = self.legacy()
        store = Store(error=pg_field_policy._MissingSchema(pg_field_policy.MIGRATE))
        after, number = self.selected(store)
        self.assertEqual(after, before)
        self.assertEqual(number, 1)
        self.assertEqual(store.reads, ["Constructed"])
        self.proving.assert_not_called()

    def test_empty_policy_and_a_store_without_policies_keep_the_legacy_field(self):
        self.configure(remove=["casual/beta"])
        before = self.legacy()
        self.assertEqual(self.selected(MemoryStore())[0], before)
        self.assertEqual(self.selected(types.SimpleNamespace())[0], before)
        self.proving.assert_not_called()

    def test_member_fields_never_read_home_policy(self):
        store = Store({"Constructed": _policy("Constructed", {"epoch": _epoch("casual/alpha"), "mode": "exclude"})})
        with state.use(store):
            field._field("Constructed", space="user2", public=lambda owner: owner == "home")
        self.assertEqual(store.reads, [])

    def test_another_formats_policy_does_not_touch_this_field(self):
        before = self.legacy()
        store = Store({"Commander": _policy("Commander", {"epoch": _epoch("commander/cmdr"), "mode": "exclude"})})
        self.assertEqual(self.selected(store)[0], before)
        commander, _ = self.selected(store, "Commander")
        self.assertNotIn("commander/cmdr", {entry["id"] for entry in commander[0]})

    # ---------------------------------------------------------------- saved choices

    def test_exclude_takes_the_deck_out_and_counts_as_a_manual_exclusion(self):
        store = Store({"Constructed": _policy("Constructed", {"epoch": _epoch("casual/alpha"), "mode": "exclude"})})
        (selected, notes), number = self.selected(store)
        self.assertNotIn("casual/alpha", {entry["id"] for entry in selected})
        self.assertEqual(number, 1)
        self.assertEqual(notes, self.legacy()[1])
        legacy_ids = {entry["id"] for entry in self.legacy()[0]}
        self.assertEqual({entry["id"] for entry in selected}, legacy_ids - {"casual/alpha"})

    def test_a_memory_stores_saved_row_is_the_policy_the_field_follows(self):
        store = MemoryStore()
        store._field_policies["Constructed"] = {"format": "Constructed", "revision": 1, "content": {
            "v": 1, "rules": [{"epoch": _epoch("casual/beta"), "mode": "include", "version": "target"}]}}
        (selected, _), number = self.selected(store)
        self.assertIn("casual/beta@target", self.names(selected))
        self.assertNotIn("casual/beta@owned", self.names(selected))
        self.assertEqual(number, 0)
        store._field_policies["Constructed"]["content"]["rules"] = [{"bad": True}]
        (_, notes), number = self.selected(store)
        self.assertIn(overlay.UNREADABLE, notes)  # a corrupt row is unavailable, never empty
        self.assertIsNone(number)

    def test_exclude_masks_a_legacy_addition_of_the_same_deck(self):
        self.configure(add=["casual/alpha@target"])
        store = Store({"Constructed": _policy("Constructed", {"epoch": _epoch("casual/alpha"), "mode": "exclude"})})
        (selected, _), number = self.selected(store)
        self.assertNotIn("casual/alpha", {entry["id"] for entry in selected})
        self.assertEqual(number, 1)

    def test_include_pins_a_list_and_masks_a_legacy_removal(self):
        self.configure(remove=["casual/gamma", "casual/alpha"])
        store = Store({"Constructed": _policy("Constructed", {"epoch": _epoch("casual/gamma"), "mode": "include",
                                                               "version": "owned"})})
        (selected, _), number = self.selected(store)
        names = self.names(selected)
        self.assertIn("casual/gamma@owned", names)
        self.assertNotIn("casual/gamma@target", names)
        self.assertNotIn("casual/alpha@target", names)
        self.assertEqual(number, 1)  # only the file's alpha removal remains

    def test_use_field_rules_masks_old_directives_and_restores_the_automatic_list(self):
        self.configure(add=["casual/beta@target"], remove=["casual/alpha"])
        store = Store({"Constructed": _policy(
            "Constructed", {"epoch": _epoch("casual/alpha"), "mode": "rules"},
            {"epoch": _epoch("casual/beta"), "mode": "rules"})})
        (selected, _), number = self.selected(store)
        names = self.names(selected)
        self.assertIn("casual/alpha@target", names)
        self.assertIn("casual/beta@owned", names)  # its Built version, not the file's @target
        self.assertEqual(number, 0)

    def test_include_of_a_list_the_deck_no_longer_has_follows_the_rules_with_a_note(self):
        store = Store({"Constructed": _policy("Constructed", {"epoch": _epoch("casual/alpha"), "mode": "include",
                                                               "version": "owned"})})
        (selected, notes), _ = self.selected(store)
        self.assertIn("casual/alpha@target", self.names(selected))
        self.assertIn(overlay.MISSING_VERSION.format(title="Alpha", label="Play-now"), notes)

    def test_a_recreated_deck_does_not_inherit_its_predecessors_choice(self):
        before = self.legacy()
        store = Store({"Constructed": _policy("Constructed", {"epoch": _epoch("casual/alpha", 1), "mode": "exclude"})})
        self.epochs.stop()
        with mock.patch.object(overlay, "_epochs", side_effect=lambda ids: {
                deck_id: ("creation", deck_id, 3 if deck_id == "casual/alpha" else 1) for deck_id in ids}):
            (selected, notes), number = self.selected(store)
        self.epochs.start()
        self.assertEqual((selected, notes), before)
        self.assertEqual(number, 0)

    def test_a_renamed_deck_keeps_its_choice_through_its_historical_origin(self):
        store = Store({"Constructed": _policy("Constructed", {"epoch": _epoch("casual/former"), "mode": "exclude"})})
        self.epochs.stop()
        with mock.patch.object(overlay, "_epochs", side_effect=lambda ids: {
                deck_id: ("creation", "casual/former" if deck_id == "casual/alpha" else deck_id, 1)
                for deck_id in ids}):
            (selected, _), number = self.selected(store)
        self.epochs.start()
        self.assertNotIn("casual/alpha", {entry["id"] for entry in selected})
        self.assertEqual(number, 1)

    # ---------------------------------------------------------------- failures never look empty

    def test_a_failed_policy_read_keeps_legacy_selection_but_says_so(self):
        self.configure(remove=["casual/alpha"])
        before_selected, before_notes = self.legacy()
        for error in (state.Unavailable("private database words"), ValueError("private"),
                      state.Invalid("corrupt")):
            with self.subTest(error=type(error).__name__):
                (selected, notes), number = self.selected(Store(error=error))
                self.assertEqual(selected, before_selected)
                self.assertEqual(notes, [*before_notes, overlay.UNREADABLE])
                self.assertIsNone(number)
                self.assertNotIn("private", " ".join(notes))
        with state.use(Store(error=state.Unavailable("down"))):
            view = field_membership.view(self.entry("casual/beta"))
        self.assertFalse(view["complete"])
        self.assertIsNone(view["counts"])

    def test_an_unproved_incarnation_keeps_legacy_selection_and_marks_the_count_unknown(self):
        self.configure(remove=["casual/alpha"])
        self.unproved = {"casual/alpha"}
        store = Store({"Constructed": _policy(
            "Constructed", {"epoch": _epoch("casual/alpha"), "mode": "include", "version": "target"},
            {"epoch": _epoch("casual/gamma"), "mode": "exclude"})})
        (selected, notes), number = self.selected(store)
        names = self.names(selected)
        self.assertNotIn("casual/alpha@target", names)  # the file's removal still applies to it
        self.assertNotIn("casual/gamma@target", names)  # gamma's proved choice still applies
        self.assertIn(overlay.UNPROVED, notes)
        self.assertIsNone(number)
        self.assertNotIn("Alpha", overlay.UNPROVED)

    def test_rules_present_but_none_matching_is_today_field(self):
        self.configure(remove=["casual/alpha"])
        before = self.legacy()
        store = Store({"Constructed": _policy("Constructed", {"epoch": _epoch("casual/gone"), "mode": "exclude"})})
        self.assertEqual(self.selected(store), (before, 1))

    # ---------------------------------------------------------------- the readers that follow it

    def test_membership_and_rankings_explain_a_saved_exclusion_as_a_manual_one(self):
        store = Store({"Constructed": _policy(
            "Constructed", {"epoch": _epoch("casual/alpha"), "mode": "exclude"},
            {"epoch": _epoch("casual/gamma"), "mode": "include", "version": "owned"})})
        with state.use(store):
            view = field_membership.view(self.entry("casual/beta"))
            observer = counts.Observation()
            with lists.one_snapshot():
                rows, _ = rankings._catalog("Constructed", eng={"kind": engine.KIND_DECKLAB}, exclusions=observer)
        reasons = {(row["id"], row["version"]): row["reason"] for row in view["rows"]}
        self.assertEqual(reasons[("casual/alpha", "target")], "configured_remove")
        self.assertEqual(reasons[("casual/gamma", "owned")], "configured_add")
        self.assertEqual(reasons[("casual/gamma", "target")], "other_version")
        self.assertEqual(view["counts"]["manual_excluded"], 1)
        alpha = next(row for row in rows if row["id"] == "casual/alpha")
        self.assertEqual(alpha["exclusion"], "Left out by the field configuration.")
        self.assertEqual(counts.count(observer), 1)

    def test_a_field_runs_opponents_follow_the_saved_choice(self):
        store = Store({"Constructed": _policy("Constructed", {"epoch": _epoch("casual/gamma"), "mode": "exclude"})})
        with state.use(store):
            opponents = field.opponents(self.entry("casual/alpha"))
        self.assertNotIn("casual/gamma", {entry["id"] for entry in opponents})


class EpochTests(unittest.TestCase):
    """overlay._epochs ties each proof to the pinned snapshot and caches only ready proofs."""

    TEXT = "# Fixture\n\n## Decklist\n\n```\nDeck\n4 Opt\n```\n"

    def setUp(self):
        overlay.clear_cache()
        self.addCleanup(overlay.clear_cache)
        self.backend = object.__new__(PgInventory)
        self.snapshot = Inventory("7", backend="db", decks_revision="11", aliases_ready=True, decks={
            "casual/alpha": Deck("home", "casual", "alpha", self.TEXT, revision=2),
            "casual/beta": Deck("home", "casual", "beta", self.TEXT, revision=1)})
        sha = hashlib.sha256(self.TEXT.encode()).hexdigest()
        self.found = {
            "casual/alpha": deck_epoch.Resolution("ready", deck_epoch.Epoch("creation", "casual/old", 1),
                                                  deck_epoch.Receipt("casual/alpha", 2, sha)),
            "casual/beta": deck_epoch.Resolution("ready", deck_epoch.Epoch("baseline", "casual/beta", 1),
                                                 deck_epoch.Receipt("casual/beta", 1, sha))}
        self.reads = mock.patch("decklab.lib.inventory.pg_deck_epoch.read_many",
                                side_effect=lambda backend, ids: {i: self.found[i] for i in ids if i in self.found})
        self.read_many = self.reads.start()
        self.addCleanup(self.reads.stop)

    def epochs(self, ids=("casual/alpha", "casual/beta")):
        with mock.patch.object(inventory, "backend", return_value=self.backend), inventory.pinned(self.snapshot):
            return overlay._epochs(list(ids))

    def test_ready_proofs_matching_the_snapshot_and_one_read_per_revision(self):
        self.assertEqual(self.epochs(), {"casual/alpha": ("creation", "casual/old", 1),
                                         "casual/beta": ("baseline", "casual/beta", 1)})
        self.assertEqual(self.epochs(), {"casual/alpha": ("creation", "casual/old", 1),
                                         "casual/beta": ("baseline", "casual/beta", 1)})
        self.read_many.assert_called_once()
        self.assertIs(self.read_many.call_args[0][0], self.backend)

    def test_a_receipt_from_another_revision_or_text_is_unproved(self):
        self.snapshot = self.snapshot.replace(decks={
            **self.snapshot.decks,
            "casual/alpha": Deck("home", "casual", "alpha", self.TEXT, revision=3),
            "casual/beta": Deck("home", "casual", "beta", self.TEXT + "x", revision=1)})
        self.assertEqual(self.epochs(), {})

    def test_unavailable_proofs_are_left_out_and_not_cached(self):
        self.found["casual/beta"] = deck_epoch.UNAVAILABLE
        self.assertEqual(set(self.epochs()), {"casual/alpha"})
        self.epochs()
        self.assertEqual(self.read_many.call_args_list[1][0][1], ["casual/beta"])

    def test_files_stale_and_preview_snapshots_prove_nothing(self):
        for changed in (dict(backend="files"), dict(stale="old"), dict(revision="7~preview")):
            with self.subTest(changed=changed):
                overlay.clear_cache()
                original = self.snapshot
                self.snapshot = original.replace(**changed)
                self.assertEqual(self.epochs(), {})
                self.snapshot = original
        self.read_many.assert_not_called()


class ReadManyTests(unittest.TestCase):
    """pg_deck_epoch.read_many: one owned read-only transaction and one snapshot load."""

    def setUp(self):
        self.case = pg_fixtures.PgDeckEpochTests("test_one_explicit_connection_and_readonly_repeatable_read")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.reader = pg_fixtures.reader

    def test_several_decks_share_one_transaction_and_snapshot(self):
        result = self.reader.read_many(self.case.backend, [pg_fixtures.ID, "casual/unknown", pg_fixtures.ID])
        self.assertEqual(set(result), {pg_fixtures.ID, "casual/unknown"})
        self.assertEqual(result[pg_fixtures.ID].status, "ready")
        self.assertEqual(result["casual/unknown"].status, "unavailable")
        self.case.backend._call.assert_called_once()
        self.case.backend.load.assert_called_once_with(conn=self.case.conn)
        self.assertEqual(self.case.conn.events, ["begin", "end"])

    def test_wrong_backend_bad_ids_and_failures_are_unavailable(self):
        self.assertEqual(self.reader.read_many(self.case.backend, "casual/x"), {})
        self.assertEqual(self.reader.read_many(self.case.backend, [3]), {})
        self.assertEqual(self.reader.read_many(self.case.backend, ["user2/casual/x", "../x"]), {})
        self.assertEqual(self.reader.read_many(object(), [pg_fixtures.ID])[pg_fixtures.ID].status, "unavailable")
        self.case.conn.fail = "from deck_revision"
        result = self.reader.read_many(self.case.backend, [pg_fixtures.ID])
        self.assertEqual(result[pg_fixtures.ID].status, "unavailable")
        self.assertNotIn("private", repr(result))

    def test_a_reader_transaction_that_isnt_repeatable_read_proves_nothing(self):
        self.case.conn.isolation = "read committed"
        result = self.reader.read_many(self.case.backend, [pg_fixtures.ID])
        self.assertEqual(result[pg_fixtures.ID].status, "unavailable")
        self.case.backend.load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
