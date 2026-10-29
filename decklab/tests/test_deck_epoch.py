"""Pure incarnation proofs from captured metadata, with no readers or connections."""
import copy
import hashlib
import unittest
from dataclasses import FrozenInstanceError, asdict
from unittest import mock

from decklab.lib.inventory import deck_epoch as epoch

CURRENT = "casual/current"
TEXT = "# Fixture deck\n\nDeck\n1 Forest\n"


def row(number=1, op="A", *, deck_id=CURRENT, change_set_id=1):
    return {"deck_id": deck_id, "revision": number, "op": op, "change_set_id": change_set_id}


def capture(rows=None, *, current=CURRENT, requested=None, aliases=None):
    history = [row()] if rows is None else copy.deepcopy(rows)
    number = max(item["revision"] for item in history)
    last = next(item for item in history if item["revision"] == number)
    return {"backend": "db", "persisted": True, "stale": None, "complete": True,
            "requested_id": current if requested is None else requested,
            "current": {"id": current, "revision": number, "text": TEXT}, "current_ids": [current],
            "aliases": {} if aliases is None else dict(aliases), "history": history,
            "latest": {"deck_id": last["deck_id"], "revision": number, "text": TEXT}}


class HomeIdentityTests(unittest.TestCase):
    def test_safe_home_house_ids_need_no_configuration_or_slug_normalization(self):
        for value in ("casual/a", "commander/a", "casual/Gruul_Ramp", "casual/A deck", "casual/Élan"):
            with self.subTest(value=value):
                self.assertTrue(epoch.home_id(value))
        for value in (None, True, [], "a", "user2/casual/a", "product/precon", "pairing/a+b", "home/casual/a",
                      "casual/", "casual/ ", "casual/ a", "casual/a ", "casual/.a", "casual/a/b",
                      "casual/a\\b", "casual/a:b", "casual/a\x00", "casual/a\x7f", "casual/\ud800", "casual/" + "a" * 200):
            with self.subTest(value=repr(value)):
                self.assertFalse(epoch.home_id(value))

    def test_current_or_former_identity_resolves_only_to_one_current_home_record(self):
        aliases = {"casual/old": CURRENT, "casual/older": CURRENT}
        self.assertEqual(epoch.identity(CURRENT, [CURRENT], aliases), CURRENT)
        self.assertEqual(epoch.identity("casual/old", [CURRENT], aliases), CURRENT)
        self.assertIsNone(epoch.identity("casual/unknown", [CURRENT], aliases))

    def test_unrelated_member_aliases_and_retired_home_targets_do_not_invent_lineage(self):
        aliases = {"user2/casual/old": "user2/casual/new", "casual/retired-old": "casual/retired",
                   "commander/retired-old": "commander/retired", "casual/sentinel": None,
                   "user3/casual/sentinel": None}
        self.assertEqual(epoch.identity(CURRENT, [CURRENT], aliases), CURRENT)
        self.assertIsNone(epoch.identity("casual/retired-old", [CURRENT], aliases))
        self.assertIsNone(epoch.identity("casual/sentinel", [CURRENT], aliases))

    def test_home_cross_scope_edges_chains_cycles_and_current_collisions_fail_closed(self):
        invalid = ({"casual/old": "user2/casual/private"}, {"user2/casual/old": CURRENT},
                   {"casual/old": "commander/current"}, {"casual/old": "product/precon"},
                   {"casual/old": "casual/middle", "casual/middle": CURRENT},
                   {"casual/old": "casual/middle", "casual/middle": "casual/old"},
                   {"casual/old": "casual/old"}, {CURRENT: "casual/other"}, {CURRENT: None},
                   {"casual/.unsafe": CURRENT}, {"casual/old": []})
        for aliases in invalid:
            with self.subTest(aliases=aliases):
                self.assertIsNone(epoch.identity(CURRENT, [CURRENT], aliases))

    def test_collision_with_another_current_home_identity_is_not_ignored(self):
        self.assertIsNone(epoch.identity(CURRENT, [CURRENT, "casual/another"], {"casual/another": CURRENT}))

    def test_identity_caps_bad_collections_and_duplicates_are_rejected(self):
        for current in ([], [CURRENT, CURRENT], ["user2/casual/private"], "casual/current", [None],
                        [CURRENT] * (epoch.MAX_CURRENT_IDS + 1)):
            with self.subTest(current_type=type(current).__name__):
                self.assertIsNone(epoch.identity(CURRENT, current, {}))
        oversized = {f"casual/old-{index}": CURRENT for index in range(epoch.MAX_ALIASES + 1)}
        self.assertIsNone(epoch.identity(CURRENT, [CURRENT], oversized))
        for aliases in (None, [], {None: CURRENT}, {"casual/old": 1}):
            with self.subTest(aliases=aliases):
                self.assertIsNone(epoch.identity(CURRENT, [CURRENT], aliases))


class EpochResolutionTests(unittest.TestCase):
    def ready(self, value):
        found = epoch.resolve(value)
        self.assertEqual(found.status, "ready")
        return found

    def unavailable(self, value):
        self.assertIs(epoch.resolve(value), epoch.UNAVAILABLE)
        self.assertEqual(asdict(epoch.resolve(value)), {"status": "unavailable", "epoch": None, "receipt": None})

    def test_recorded_creation_and_ordinary_changes_keep_one_immutable_anchor(self):
        first = self.ready(capture())
        changed = self.ready(capture([row(1), row(2, "M"), row(3, "M")]))
        self.assertEqual(first.epoch, epoch.Epoch("creation", CURRENT, 1))
        self.assertEqual(changed.epoch, first.epoch)
        self.assertEqual(changed.receipt, epoch.Receipt(CURRENT, 3, hashlib.sha256(TEXT.encode()).hexdigest()))
        with self.assertRaises(FrozenInstanceError):
            changed.epoch.revision = 99
        with self.assertRaises(FrozenInstanceError):
            changed.receipt.deck_id = "casual/another"

    def test_initial_imported_M_is_explicit_database_baseline_not_historical_birth(self):
        found = self.ready(capture([row(1, "M", change_set_id=None), row(2, "M", change_set_id=None), row(3, "M")]))
        self.assertEqual(found.epoch, epoch.Epoch("baseline", CURRENT, 1))
        for op, change in (("M", 1), ("M", True), ("D", None)):
            with self.subTest(op=op, change=change):
                self.unavailable(capture([row(1, op, change_set_id=change)]))

    def test_imported_A_still_proves_recorded_creation(self):
        found = self.ready(capture([row(1, "A", change_set_id=None), row(2, "M")]))
        self.assertEqual(found.epoch.kind, "creation")

    def test_rename_keeps_historical_creation_anchor_and_current_receipt_separate(self):
        old = "casual/first-name"
        before = self.ready(capture([row(1, deck_id=old), row(2, "M", deck_id=old)], current=old))
        rows = [row(1, deck_id=old), row(2, "M", deck_id=old), row(3, "M")]
        after = self.ready(capture(rows, requested=old, aliases={old: CURRENT}))
        self.assertEqual(before.epoch, after.epoch)
        self.assertEqual(after.epoch.deck_id, old)
        self.assertEqual(after.receipt.deck_id, CURRENT)

    def test_renames_preserve_imported_baseline_with_a_flattened_family(self):
        old, middle = "commander/first", "commander/middle"
        current = "commander/current"
        rows = [row(1, "M", deck_id=old, change_set_id=None), row(2, "M", deck_id=middle),
                row(3, "M", deck_id=current)]
        found = self.ready(capture(rows, current=current, requested=old, aliases={old: current, middle: current}))
        self.assertEqual(found.epoch, epoch.Epoch("baseline", old, 1))

    def test_delete_and_recreate_same_slug_creates_new_epoch_instead_of_inheriting(self):
        original = self.ready(capture())
        recreated = self.ready(capture([row(1), row(2, "M"), row(3, "D"), row(4, "A"), row(5, "M")]))
        self.assertEqual(recreated.epoch, epoch.Epoch("creation", CURRENT, 4))
        self.assertNotEqual(original.epoch, recreated.epoch)

    def test_baseline_delete_and_recreate_selects_a_new_creation_anchor(self):
        found = self.ready(capture([row(1, "M", change_set_id=None), row(2, "D"), row(3, "A"), row(4, "M")]))
        self.assertEqual(found.epoch, epoch.Epoch("creation", CURRENT, 3))

    def test_retained_nonnull_alias_after_rename_delete_and_recreate_proves_new_A(self):
        old = "casual/first"
        for initial, change in (("A", 1), ("M", None)):
            rows = [row(1, initial, deck_id=old, change_set_id=change), row(2, "M"), row(3, "D"), row(4, "A")]
            with self.subTest(initial=initial):
                found = self.ready(capture(rows, requested=old, aliases={old: CURRENT}))
                self.assertEqual(found.epoch, epoch.Epoch("creation", CURRENT, 4))
        missing_prefix = capture(rows, aliases={old: None})
        self.unavailable(missing_prefix)  # A supplied sentinel cannot reconstruct absent lineage proof.

    def test_invalid_state_transitions_never_guess_a_birth(self):
        sequences = (("M", "A"), ("A", "A"), ("A", "D"), ("A", "D", "M"),
                     ("A", "D", "D"), ("A", "D", "A", "A"), ("D", "A"))
        for ops in sequences:
            rows = [row(index, op, change_set_id=None if index == 1 and op == "M" else 1)
                    for index, op in enumerate(ops, 1)]
            with self.subTest(ops=ops):
                self.unavailable(capture(rows))

    def test_unique_contiguous_history_is_required_but_capture_order_is_not_significant(self):
        value = capture([row(3, "M"), row(1), row(2, "M")])
        self.assertEqual(self.ready(value).epoch, epoch.Epoch("creation", CURRENT, 1))
        for rows in ([row(2, "M")], [row(1), row(3, "M")], [row(1), row(2, "M"), row(2, "M")]):
            value = capture(rows)
            value["current"]["revision"] = 3
            with self.subTest(rows=rows):
                self.unavailable(value)

    def test_missing_old_alias_prefix_cannot_be_replaced_by_an_oldest_visible_row(self):
        old = "casual/first"
        value = capture([row(1, deck_id=old), row(2, "M")])
        self.unavailable(value)  # complete history lacks the identity edge to its old row
        value["aliases"] = {old: CURRENT}
        self.assertEqual(self.ready(value).epoch, epoch.Epoch("creation", old, 1))

    def test_history_cannot_merge_an_unrelated_home_or_member_record(self):
        for other in ("casual/unrelated", "user2/casual/private", "product/precon"):
            with self.subTest(other=other):
                self.unavailable(capture([row(1, deck_id=other), row(2, "M")]))

    def test_latest_identity_revision_and_exact_text_must_match_current(self):
        changes = (lambda value: value["latest"].update(deck_id="casual/other"),
                   lambda value: value["latest"].update(revision=2),
                   lambda value: value["latest"].update(revision=True),
                   lambda value: value["latest"].update(text=TEXT + "Changed\n"),
                   lambda value: value["current"].update(id="casual/other"),
                   lambda value: value["current"].update(revision=True))
        for change in changes:
            value = capture()
            change(value)
            with self.subTest(change=change):
                self.unavailable(value)

    def test_latest_historical_name_cannot_stand_in_for_missing_current_revision(self):
        old = "casual/old"
        self.unavailable(capture([row(1, deck_id=old)], aliases={old: CURRENT}))

    def test_fresh_persisted_database_proof_is_required(self):
        for key, change in (("backend", "files"), ("persisted", False), ("persisted", 1),
                            ("complete", False), ("complete", 1), ("stale", "old"), ("stale", False)):
            value = capture()
            value[key] = change
            with self.subTest(key=key, change=change):
                self.unavailable(value)

    def test_caps_and_complete_history_flags_fail_before_materializing_a_prefix(self):
        value = capture()
        value["current"]["revision"] = epoch.MAX_HISTORY + 1
        value["history"] = object()
        self.unavailable(value)
        value = capture()
        value["history"] *= epoch.MAX_HISTORY + 1
        self.unavailable(value)
        value = capture()
        value["complete"] = False
        self.unavailable(value)

    def test_text_is_bounded_valid_database_text_and_never_normalized(self):
        for text in (None, b"bytes", "bad\x00text", "bad\r\ntext", "bad\ud800", "x" * (epoch.MAX_TEXT_BYTES + 1),
                     "🐉" * (epoch.MAX_TEXT_BYTES // 4 + 1)):
            value = capture()
            value["current"]["text"] = value["latest"]["text"] = text
            with self.subTest(text_type=type(text).__name__):
                self.unavailable(value)

    def test_strict_metadata_types_keys_and_unknown_fields_fail_without_relay(self):
        for key, value in (("revision", True), ("op", "a"), ("op", 1), ("change_set_id", False),
                           ("change_set_id", 0), ("change_set_id", "1")):
            found = capture()
            found["history"][0][key] = value
            with self.subTest(key=key, value=value):
                self.unavailable(found)
        for location in ("history", "latest", "current", "capture"):
            found = capture()
            target = found["history"][0] if location == "history" else found if location == "capture" else found[location]
            target["actor_or_private_note"] = "DO NOT RELAY"
            with self.subTest(location=location):
                self.unavailable(found)

    def test_minimal_immutable_output_has_no_historical_text_actor_note_or_kit(self):
        value = capture([row(1, "M", change_set_id=None), row(2, "M")])
        untouched = copy.deepcopy(value)
        found = self.ready(value)
        self.assertEqual(asdict(found), {"status": "ready", "epoch": {
            "kind": "baseline", "deck_id": CURRENT, "revision": 1}, "receipt": {
            "deck_id": CURRENT, "revision": 2, "sha256": hashlib.sha256(TEXT.encode()).hexdigest()}})
        self.assertEqual(value, untouched)
        self.assertNotIn(TEXT, repr(found))
        with self.assertRaises(FrozenInstanceError):
            found.status = "unavailable"

    def test_resolver_uses_no_reader_or_configuration_and_handles_missing_shapes(self):
        value = capture()
        with mock.patch("builtins.open", side_effect=AssertionError("pure resolver opened a file")):
            self.ready(value)
        for bad in (None, [], {}, {**value, "history": None}, {**value, "current": []}):
            with self.subTest(bad_type=type(bad).__name__):
                self.unavailable(bad)
