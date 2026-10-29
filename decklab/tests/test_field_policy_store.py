"""Memory field-policy transactions with explicit locked synthetic deck captures.

No configured inventory, database, server, cache, credentials or Forge is used.
Run only through scripts/test_fixtures.py so protection precedes imports.
"""
import copy
import threading
import unittest
from contextlib import contextmanager
from unittest import mock

from decklab.lib import state
from decklab.lib.state import field_policy as policy, field_policy_source as source
from decklab.lib.state.memory import MemoryStore

ACTOR = state.Actor("matt", "Matt", "home")
TEXT = ("# Fixture deck\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** either\n"
        "- **Status:** building\n\n## Decklist\n\n```\nDeck\n4 Llanowar Elves\n20 Forest\n```\n\n"
        "## Substitutes\n\n### Owned-only version\n\n```\nDeck\n2 Llanowar Elves\n22 Forest\n```\n")
PRIVATE = "PRIVATE-FIXTURE-ONLY"


def capture(deck_id="casual/fixture", *, revision=1, history=None, text=TEXT, aliases=None):
    rows = history if history is not None else [
        {"deck_id": deck_id, "revision": index, "op": "A" if index == 1 else "M", "change_set_id": index}
        for index in range(1, revision + 1)]
    return {"backend": "db", "persisted": True, "stale": None, "complete": True,
            "requested_id": deck_id, "current": {"id": deck_id, "revision": revision, "text": text},
            "current_ids": [deck_id], "aliases": dict(aliases or {}), "history": copy.deepcopy(rows),
            "latest": {"deck_id": deck_id, "revision": revision, "text": text}}


class FixtureSource:
    """Only this supplied dictionary is readable, under one retained fixture lock."""

    def __init__(self, value=None):
        self.value = copy.deepcopy(value if value is not None else capture())
        self.lock = threading.RLock()
        self.attempted = threading.Event()
        self.entered = threading.Event()
        self.owner = None
        self.before_yield = None
        self.exit_error = None
        self.suppress = False
        self.entries = []

    @contextmanager
    def locked(self, deck_id):
        self.attempted.set()
        with self.lock:
            self.owner = threading.get_ident()
            self.entries.append(deck_id)
            self.entered.set()
            try:
                if self.before_yield is not None:
                    self.before_yield()
                try:
                    yield copy.deepcopy(self.value)
                except state.StateError:
                    if not self.suppress:
                        raise
            finally:
                self.owner = None
                if self.exit_error is not None:
                    raise self.exit_error


class MemoryFieldPolicyTests(unittest.TestCase):
    def setUp(self):
        self.provider = FixtureSource()
        self.store = MemoryStore(field_source=self.provider)
        self.proof = source.qualify(self.provider.value, "target", "Constructed")

    def intent(self, mode="include", version="target", *, proof=None):
        reviewed = proof if proof is not None else self.proof
        desired = {"epoch": copy.deepcopy(reviewed["epoch"]), "mode": mode}
        if mode == "include":
            desired["version"] = version
        return desired

    def apply(self, mode="include", *, expect=0, proof=None, version="target", reason=None, store=None):
        reviewed = proof if proof is not None else self.proof
        return (store or self.store).field_policy_apply(
            "Constructed", expect, reviewed, self.intent(mode, version, proof=reviewed), ACTOR,
            "Save fixture field choice", reason)

    def assertClean(self, snapshot=None):
        self.assertEqual(self.store.field_policy("Constructed"), snapshot or policy.empty("Constructed"))
        self.assertEqual(self.store.activity()["changes"], [])

    def start(self, callback):
        outcome = []

        def run():
            try:
                outcome.append(("ok", callback()))
            except BaseException as error:
                outcome.append(("error", error))
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, outcome

    def finish(self, thread, outcome):
        thread.join(3)
        self.assertFalse(thread.is_alive(), "fixture worker did not finish")
        self.assertEqual(len(outcome), 1)
        return outcome[0]

    def test_constructor_keeps_mode_positional_and_provider_keyword_only(self):
        self.assertEqual(MemoryStore("paused").simulation_mode()["mode"], "paused")
        with self.assertRaises(TypeError):
            MemoryStore("paused", self.provider)

    def test_explicit_memory_reader_starts_empty_without_a_provider_or_audit(self):
        store = MemoryStore()
        for fmt in ("Constructed", "Commander"):
            self.assertEqual(store.field_policy(fmt), policy.empty(fmt))
        self.assertEqual(store.activity()["changes"], [])
        first = store.field_policy("Constructed")
        first["rules"].append(self.intent())
        self.assertEqual(store.field_policy("Constructed"), policy.empty("Constructed"))

    def test_no_provider_refuses_write_without_inventory_fallback(self):
        store = MemoryStore()
        with mock.patch.object(source, "recheck", side_effect=AssertionError("no source is available")) as checked:
            with self.assertRaises(state.Unavailable) as caught:
                self.apply(store=store)
        self.assertEqual(str(caught.exception), source.UNAVAILABLE)
        checked.assert_not_called()
        self.assertEqual(store.field_policy("Constructed"), policy.empty("Constructed"))
        self.assertEqual(store.activity()["changes"], [])

    def test_one_change_has_exact_row_shape_actor_and_detached_snapshot(self):
        reviewed, desired = copy.deepcopy(self.proof), self.intent()
        result = self.store.field_policy_apply("Constructed", 0, reviewed, desired, ACTOR, "Save fixture")
        expected = {"v": 1, "format": "Constructed", "revision": 1, "rules": [self.intent()]}
        self.assertEqual(result, {"changed": True, "snapshot": expected})
        change, = self.store.activity()["changes"]
        self.assertEqual((change["actor"], change["source"], change["via"], change["message"]),
                         ("matt", "web", "home", "Save fixture"))
        row, = change["rows"]
        self.assertEqual(row, {"table": "field_policy", "op": "INSERT", "key": {"format": "Constructed"},
                               "before": None, "after": {"format": "Constructed", "revision": 1,
                                                         "content": {"v": 1, "rules": [self.intent()]}}})
        reviewed["epoch"]["deck_id"] = "casual/changed-input"
        desired["epoch"]["deck_id"] = "casual/changed-rule"
        result["snapshot"]["rules"][0]["mode"] = "rules"
        row["after"]["content"]["rules"][0]["mode"] = "exclude"
        read = self.store.field_policy("Constructed")
        self.assertEqual(read, expected)
        read["rules"][0]["epoch"]["deck_id"] = "casual/changed-read"
        self.assertEqual(self.store.field_policy("Constructed"), expected)
        self.assertEqual(self.provider.entries, [self.proof["receipt"]["deck_id"]])

    def test_reason_is_private_audit_only_and_exclude_requires_valid_text(self):
        for reason in (None, "", " ", True, 1, "x" * 1001, "x\0", "x\x7f", "\ud800"):
            with self.subTest(reason=repr(reason)), self.assertRaises(state.Invalid) as caught:
                self.apply("exclude", reason=reason)
            self.assertEqual(str(caught.exception), source.INVALID_REASON)
        self.assertEqual(self.provider.entries, [])
        self.assertClean()
        result = self.apply("exclude", reason="  " + PRIVATE + "\nreason\taccepted  ")
        self.assertNotIn("reason", result["snapshot"]["rules"][0])
        self.assertNotIn(PRIVATE, str(result))
        change, = self.store.activity()["changes"]
        self.assertEqual(change["reason"], PRIVATE + "\nreason\taccepted")
        self.assertNotIn(PRIVATE, str(change["rows"]))

    def test_matching_noop_rechecks_current_proof_under_source_lock_without_audit(self):
        saved = self.apply()["snapshot"]
        before = self.store.activity()
        original = source.recheck

        def checked(*args):
            self.assertEqual(self.provider.owner, threading.get_ident())
            return original(*args)
        with mock.patch.object(source, "recheck", side_effect=checked) as rechecked:
            result = self.apply(expect=1)
        rechecked.assert_called_once()
        self.assertEqual(result, {"changed": False, "snapshot": saved})
        self.assertEqual(self.store.activity(), before)
        result["snapshot"]["rules"][0]["mode"] = "rules"
        self.assertEqual(self.store.field_policy("Constructed"), saved)

    def test_stale_identical_intent_conflicts_before_source_recheck(self):
        self.apply()
        before = self.store.activity()
        with mock.patch.object(source, "recheck", side_effect=AssertionError("CAS must come first")) as checked:
            with self.assertRaises(state.Conflict) as caught:
                self.apply()
        self.assertEqual(str(caught.exception), policy.CHANGED)
        checked.assert_not_called()
        self.assertEqual(self.store.activity(), before)

    def test_current_text_drift_refuses_a_matching_noop_without_revision_or_audit(self):
        saved = self.apply()["snapshot"]
        before = self.store.activity()
        self.provider.value = capture(revision=2, text=TEXT + "\nChanged fixture prose.\n")
        with self.assertRaises(state.Conflict) as caught:
            self.apply(expect=1)
        self.assertEqual(str(caught.exception), source.CHANGED)
        self.assertEqual(self.store.field_policy("Constructed"), saved)
        self.assertEqual(self.store.activity(), before)

    def test_unknown_or_uncertain_current_source_never_returns_successful_noop(self):
        saved = self.apply()["snapshot"]
        before = self.store.activity()
        self.provider.value["complete"] = False
        with self.assertRaises(state.Unavailable) as caught:
            self.apply(expect=1)
        self.assertEqual(str(caught.exception), source.UNAVAILABLE)
        self.assertEqual(self.store.field_policy("Constructed"), saved)
        self.assertEqual(self.store.activity(), before)

    def test_rule_or_proof_mismatch_refuses_before_provider_entry(self):
        for modify in (lambda proof, desired: desired["epoch"].update(revision=2),
                       lambda proof, desired: desired.update(version="owned"),
                       lambda proof, desired: proof.update(card_sha="bad"),
                       lambda proof, desired: proof["receipt"].update(deck_id="user2/casual/private")):
            reviewed, desired = copy.deepcopy(self.proof), self.intent()
            modify(reviewed, desired)
            with self.assertRaises(state.Invalid):
                self.store.field_policy_apply("Constructed", 0, reviewed, desired, ACTOR, "Save fixture")
        self.assertEqual(self.provider.entries, [])
        self.assertClean()

    def test_invalid_revisions_actor_message_and_format_never_enter_provider(self):
        for expected in (None, True, "0", -1, policy.MAX_REVISION + 1):
            with self.subTest(expected=expected), self.assertRaises(state.Invalid):
                self.apply(expect=expected)
        for actor, message in ((None, "Save fixture"), (ACTOR, ""), (ACTOR, " ")):
            with self.assertRaises(ValueError):
                self.store.field_policy_apply("Constructed", 0, self.proof, self.intent(), actor, message)
        with self.assertRaises(state.Invalid):
            self.store.field_policy_apply("Commander", 0, self.proof, self.intent(), ACTOR, "Save fixture")
        self.assertEqual(self.provider.entries, [])
        self.assertClean()

    def test_use_rules_is_retained_and_obsolete_epochs_are_not_reused_or_evicted(self):
        first = self.apply("rules")["snapshot"]
        self.assertEqual(first["rules"], [self.intent("rules")])
        history = [{"deck_id": "casual/fixture", "revision": number, "op": op, "change_set_id": number}
                   for number, op in ((1, "A"), (2, "D"), (3, "A"))]
        self.provider.value = capture(revision=3, history=history)
        current = source.qualify(self.provider.value, "target", "Constructed")
        self.assertIsNone(policy.lookup(first, current["epoch"]))
        result = self.apply("exclude", expect=1, proof=current, reason="New fixture incarnation")
        self.assertEqual(len(result["snapshot"]["rules"]), 2)
        self.assertEqual(policy.lookup(result["snapshot"], self.proof["epoch"]), self.intent("rules"))
        self.assertEqual(policy.lookup(result["snapshot"], current["epoch"])["mode"], "exclude")
        self.assertEqual(len(self.store.activity()["changes"]), 2)

    def test_rename_keeps_epoch_and_writes_under_current_receipt_identity(self):
        old = self.proof["receipt"]["deck_id"]
        renamed = "casual/renamed"
        history = [{"deck_id": old, "revision": 1, "op": "A", "change_set_id": 1},
                   {"deck_id": renamed, "revision": 2, "op": "M", "change_set_id": 2}]
        self.provider.value = capture(renamed, revision=2, history=history, aliases={old: renamed})
        reviewed = source.qualify(self.provider.value, "target", "Constructed")
        self.assertEqual(reviewed["epoch"], self.proof["epoch"])
        result = self.apply("rules", proof=reviewed)
        self.assertEqual(result["snapshot"]["rules"], [self.intent("rules")])
        self.assertEqual(self.provider.entries, [renamed])

    def test_owned_include_qualifies_its_explicit_reviewed_version(self):
        reviewed = source.qualify(self.provider.value, "owned", "Constructed")
        result = self.apply(proof=reviewed, version="owned")
        self.assertEqual(result["snapshot"]["rules"][0]["version"], "owned")
        self.assertNotEqual(reviewed["card_sha"], self.proof["card_sha"])

    def test_source_lock_is_retained_through_mutation_and_audit_append(self):
        original = self.store._log

        def logged(*args):
            self.assertEqual(self.provider.owner, threading.get_ident())
            self.assertEqual(self.store.field_policy("Constructed")["revision"], 1)
            return original(*args)
        with mock.patch.object(self.store, "_log", side_effect=logged):
            self.apply()
        self.assertIsNone(self.provider.owner)

    def test_provider_entry_and_exit_failures_are_generic_and_leave_no_write(self):
        broken = mock.Mock()
        broken.locked.side_effect = RuntimeError(PRIVATE)
        self.store._field_source = broken
        with self.assertRaises(state.Unavailable) as entered:
            self.apply()
        self.assertEqual(str(entered.exception), source.UNAVAILABLE)
        self.assertClean()
        self.store._field_source = self.provider
        self.provider.exit_error = RuntimeError(PRIVATE)
        with self.assertRaises(state.Unavailable) as exited:
            self.apply()
        self.assertEqual(str(exited.exception), source.UNAVAILABLE)
        self.assertClean()

    def test_provider_context_cannot_swallow_a_failed_proof_and_report_success(self):
        self.provider.value["complete"] = False
        self.provider.suppress = True
        with self.assertRaises(state.Unavailable) as caught:
            self.apply()
        self.assertEqual(str(caught.exception), source.UNAVAILABLE)
        self.assertClean()

    def test_provider_entry_state_errors_are_unavailable_without_private_text(self):
        for error_type in (state.Invalid, state.Conflict, state.Unavailable):
            with self.subTest(error_type=error_type):
                broken = mock.Mock()
                broken.locked.side_effect = error_type(PRIVATE)
                self.store._field_source = broken
                with self.assertRaises(state.Unavailable) as caught:
                    self.apply()
                self.assertEqual(str(caught.exception), source.UNAVAILABLE)
                self.assertNotIn(PRIVATE, str(caught.exception))
                self.assertClean()

    def test_provider_exit_state_errors_roll_back_policy_and_new_audit(self):
        for error_type in (state.Invalid, state.Conflict, state.Unavailable):
            with self.subTest(error_type=error_type):
                self.provider.exit_error = error_type(PRIVATE)
                with self.assertRaises(state.Unavailable) as caught:
                    self.apply()
                self.assertEqual(str(caught.exception), source.UNAVAILABLE)
                self.assertNotIn(PRIVATE, str(caught.exception))
                self.assertClean()

    def test_body_conflict_keeps_the_exact_exception_and_existing_state(self):
        saved = self.apply()["snapshot"]
        before = self.store.activity()
        expected = state.Conflict(source.CHANGED)
        with mock.patch.object(source, "recheck", side_effect=expected):
            with self.assertRaises(state.Conflict) as caught:
                self.apply("rules", expect=1)
        self.assertIs(caught.exception, expected)
        self.assertEqual(self.store.field_policy("Constructed"), saved)
        self.assertEqual(self.store.activity(), before)

    def test_provider_replacement_of_body_conflict_is_not_mistaken_for_same_exception(self):
        saved = self.apply()["snapshot"]
        before = self.store.activity()
        body_error = state.Conflict(source.CHANGED)
        self.provider.exit_error = state.Conflict(source.CHANGED)
        self.assertIsNot(self.provider.exit_error, body_error)
        with mock.patch.object(source, "recheck", side_effect=body_error):
            with self.assertRaises(state.Unavailable) as caught:
                self.apply("rules", expect=1)
        self.assertEqual(str(caught.exception), source.UNAVAILABLE)
        self.assertEqual(self.store.field_policy("Constructed"), saved)
        self.assertEqual(self.store.activity(), before)

    def test_provider_locked_attribute_failure_is_generic_before_capture_or_write(self):
        class BrokenProvider:
            @property
            def locked(self):
                raise state.Unavailable(PRIVATE)
        self.store._field_source = BrokenProvider()
        with self.assertRaises(state.Unavailable) as caught:
            self.apply()
        self.assertEqual(str(caught.exception), source.UNAVAILABLE)
        self.assertClean()

    def test_audit_append_failure_rolls_back_policy_and_the_partial_audit_append(self):
        original = self.store._append

        def broken(*args):
            original(*args)
            raise RuntimeError(PRIVATE)
        with mock.patch.object(self.store, "_append", side_effect=broken):
            with self.assertRaises(state.Unavailable) as caught:
                self.apply()
        self.assertEqual(str(caught.exception), source.UNAVAILABLE)
        self.assertClean()

    def test_failures_preserve_existing_policy_and_earlier_audit_history(self):
        saved = self.apply()["snapshot"]
        before = self.store.activity()
        self.provider.exit_error = RuntimeError(PRIVATE)
        with self.assertRaises(state.Unavailable):
            self.apply("rules", expect=1)
        self.assertEqual(self.store.field_policy("Constructed"), saved)
        self.assertEqual(self.store.activity(), before)

    def test_down_store_is_rechecked_after_waiting_for_provider(self):
        release = threading.Event()
        self.provider.before_yield = lambda: release.wait(2)
        thread, outcome = self.start(lambda: self.apply())
        try:
            self.assertTrue(self.provider.entered.wait(2))
            with self.store._lock:
                self.store.down = True
        finally:
            release.set()
        status, error = self.finish(thread, outcome)
        self.assertEqual(status, "error")
        self.assertIsInstance(error, state.Unavailable)
        self.store.down = False
        self.assertClean()

    def test_same_thread_batch_refuses_before_source_and_rolls_back_unrelated_batch_changes(self):
        with self.assertRaises(state.Invalid):
            with self.store.batch(ACTOR, "Fixture batch"):
                self.store.settings_put("matt", {"theme": "dark"}, ACTOR, "Fixture theme")
                self.apply()
        self.assertEqual(self.provider.entries, [])
        self.assertEqual(self.store.settings("matt"), {})
        self.assertClean()

    def test_waiting_for_source_does_not_hold_store_lock_or_block_readers(self):
        with self.provider.lock:
            writer, written = self.start(lambda: self.apply())
            self.assertTrue(self.provider.attempted.wait(2))
            reader, read = self.start(lambda: self.store.field_policy("Constructed"))
            status, value = self.finish(reader, read)
            self.assertEqual((status, value), ("ok", policy.empty("Constructed")))
        self.assertEqual(self.finish(writer, written)[0], "ok")

    def test_batch_refusal_does_not_invert_an_already_held_source_lock(self):
        release = threading.Event()
        self.provider.before_yield = lambda: release.wait(2)
        writer, written = self.start(lambda: self.apply())
        try:
            self.assertTrue(self.provider.entered.wait(2))
            with self.store.batch(ACTOR, "Fixture batch"):
                before = len(self.provider.entries)
                with self.assertRaises(state.Invalid):
                    self.apply()
                self.assertEqual(len(self.provider.entries), before)
                release.set()
        finally:
            release.set()
        self.assertEqual(self.finish(writer, written)[0], "ok")
        self.assertEqual(len(self.store.activity()["changes"]), 1)

    def test_two_concurrent_identical_writers_have_one_change_and_one_stale_conflict(self):
        start = threading.Barrier(3)

        def write():
            start.wait(2)
            return self.apply()
        first, one = self.start(write)
        second, two = self.start(write)
        start.wait(2)
        results = [self.finish(first, one), self.finish(second, two)]
        self.assertEqual(sorted(status for status, _ in results), ["error", "ok"])
        error = next(value for status, value in results if status == "error")
        self.assertIsInstance(error, state.Conflict)
        self.assertEqual(str(error), policy.CHANGED)
        self.assertEqual(self.store.field_policy("Constructed")["revision"], 1)
        self.assertEqual(len(self.store.activity()["changes"]), 1)

    def test_inputs_are_detached_before_waiting_for_current_source(self):
        reviewed, desired = copy.deepcopy(self.proof), self.intent()
        with self.provider.lock:
            worker, outcome = self.start(lambda: self.store.field_policy_apply(
                "Constructed", 0, reviewed, desired, ACTOR, "Save fixture"))
            self.assertTrue(self.provider.attempted.wait(2))
            reviewed["epoch"]["deck_id"] = "casual/changed-outside"
            desired["mode"] = "rules"
        status, result = self.finish(worker, outcome)
        self.assertEqual(status, "ok")
        self.assertEqual(result["snapshot"]["rules"], [self.intent()])

    def test_corrupt_rows_are_unavailable_without_repair_or_audit(self):
        valid = {"format": "Constructed", "revision": 1, "content": {"v": 1, "rules": [self.intent()]}}
        malformed = [None, {}, {**valid, "revision": 0}, {**valid, "revision": True},
                     {**valid, "format": "Commander"}, {**valid, "content": None},
                     {**valid, "extra": PRIVATE}, {**valid, "content": {**valid["content"], "extra": PRIVATE}}]
        unsorted = copy.deepcopy(valid)
        other = self.intent()
        other["epoch"]["deck_id"] = "casual/aaa"
        unsorted["content"]["rules"].append(other)
        malformed.append(unsorted)
        for row in malformed:
            with self.subTest(row=row):
                self.store._field_policies["Constructed"] = copy.deepcopy(row)
                original = copy.deepcopy(row)
                with self.assertRaises(state.Unavailable) as caught:
                    self.store.field_policy("Constructed")
                self.assertEqual(str(caught.exception), source.UNAVAILABLE)
                with self.assertRaises(state.Unavailable):
                    self.apply(expect=1)
                self.assertEqual(self.store._field_policies["Constructed"], original)
                self.assertEqual(self.store.activity()["changes"], [])

    def test_bigint_overflow_is_quiet_and_matching_maximum_noop_still_checks_source(self):
        self.apply()
        self.store._field_policies["Constructed"]["revision"] = policy.MAX_REVISION
        saved, before = self.store.field_policy("Constructed"), self.store.activity()
        with mock.patch.object(source, "recheck", wraps=source.recheck) as checked:
            self.assertFalse(self.apply(expect=policy.MAX_REVISION)["changed"])
        checked.assert_called_once()
        with self.assertRaises(state.Invalid):
            self.apply("rules", expect=policy.MAX_REVISION)
        self.assertEqual(self.store.field_policy("Constructed"), saved)
        self.assertEqual(self.store.activity(), before)

    def test_capacity_never_evicts_older_epochs_but_existing_entry_can_change(self):
        self.apply()
        values = [self.intent()]
        values.extend({"epoch": {"kind": "creation", "deck_id": f"casual/obsolete-{index:04d}", "revision": 1},
                       "mode": "rules"} for index in range(policy.MAX_RULES - 1))
        canonical = policy.normalize({"v": 1, "format": "Constructed", "revision": 1, "rules": values})
        self.store._field_policies["Constructed"]["content"]["rules"] = canonical["rules"]
        result = self.apply("rules", expect=1)
        self.assertEqual(len(result["snapshot"]["rules"]), policy.MAX_RULES)
        self.assertEqual(policy.lookup(result["snapshot"], self.proof["epoch"])["mode"], "rules")
        history = [{"deck_id": "casual/fixture", "revision": number, "op": op, "change_set_id": number}
                   for number, op in ((1, "A"), (2, "D"), (3, "A"))]
        self.provider.value = capture(revision=3, history=history)
        fresh = source.qualify(self.provider.value, "target", "Constructed")
        before = self.store.activity()
        with self.assertRaises(state.Invalid):
            self.apply("rules", expect=2, proof=fresh)
        self.assertEqual(self.store.field_policy("Constructed"), result["snapshot"])
        self.assertEqual(self.store.activity(), before)
