"""Pure HOME field-policy syntax, incarnation isolation and revision transitions.

Fixtures contain no records from the household. They use no store, configuration,
inventory provider, database, engine, server or selector. Run through the guarded
scripts/test_fixtures.py entry point, never an unguarded unittest invocation.
"""
import copy
import json
import unittest

from decklab.lib.state import Conflict, Invalid, field_policy as policy

_DEFAULT = object()


def epoch(deck_id="casual/fixture", revision=1, kind="creation"):
    return {"kind": kind, "deck_id": deck_id, "revision": revision}


def rule(mode="include", version="target", *, anchor=_DEFAULT):
    out = {"epoch": copy.deepcopy(epoch() if anchor is _DEFAULT else anchor), "mode": mode}
    if mode == "include":
        out["version"] = version
    return out


def snapshot(*rules, revision=1, fmt="Constructed"):
    return {"v": 1, "format": fmt, "revision": revision, "rules": list(copy.deepcopy(rules))}


class PolicyValidationTests(unittest.TestCase):
    def assertInvalid(self, callback):
        with self.assertRaises(Invalid) as caught:
            callback()
        self.assertEqual(str(caught.exception), policy.INVALID)

    def test_empty_policies_are_exact_independent_and_format_specific(self):
        for fmt in ("Constructed", "Commander"):
            with self.subTest(fmt=fmt):
                self.assertEqual(policy.empty(fmt), {"v": 1, "format": fmt, "revision": 0, "rules": []})
                first, second = policy.empty(fmt), policy.empty(fmt)
                first["rules"].append(rule())
                self.assertEqual(second["rules"], [])
                self.assertEqual(policy.normalize(second), second)

    def test_schema_and_complete_object_keys_are_strict(self):
        valid = snapshot()
        invalid = [None, [], "private-schema-sentinel", {}, {**valid, "v": True}, {**valid, "v": 1.0},
                   {**valid, "v": 2}, {**valid, "unknown": "private-extra-sentinel"}]
        invalid.extend({key: value for key, value in valid.items() if key != missing} for missing in valid)
        for value in invalid:
            with self.subTest(value=value):
                self.assertInvalid(lambda: policy.normalize(value))

    def test_only_exact_format_names_are_accepted(self):
        for fmt in (None, [], {}, True, "constructed", " Commander", "Modern", "private-format-sentinel"):
            with self.subTest(fmt=fmt):
                self.assertInvalid(lambda: policy.empty(fmt))
                self.assertInvalid(lambda: policy.normalize(snapshot(fmt=fmt)))

    def test_policy_revisions_fit_postgres_bigint_and_reject_boolean_or_numeric_coercion(self):
        for revision in (0, 1, policy.MAX_REVISION):
            self.assertEqual(policy.normalize(snapshot(revision=revision))["revision"], revision)
        for revision in (None, True, False, "1", 1.0, -1, policy.MAX_REVISION + 1):
            with self.subTest(revision=revision):
                self.assertInvalid(lambda: policy.normalize(snapshot(revision=revision)))

    def test_zero_revision_cannot_contain_intent_but_positive_empty_state_is_valid(self):
        self.assertInvalid(lambda: policy.normalize(snapshot(rule("rules"), revision=0)))
        self.assertEqual(policy.normalize(snapshot(revision=7)), snapshot(revision=7))

    def test_rule_array_must_be_a_plain_list(self):
        for values in (None, {}, (), "private-rules-sentinel", iter([])):
            self.assertInvalid(lambda: policy.normalize({**snapshot(), "rules": values}))

    def test_all_modes_round_trip_with_exact_keys(self):
        for value in (rule("include", "target"), rule("include", "owned"), rule("exclude"), rule("rules")):
            with self.subTest(value=value):
                self.assertEqual(policy.normalize(snapshot(value)), snapshot(value))

    def test_rule_shapes_versions_modes_and_unknown_fields_fail_closed(self):
        invalid = [None, [], {}, {"epoch": epoch()}, {"mode": "rules"},
                   {"epoch": epoch(), "mode": None}, {"epoch": epoch(), "mode": {}},
                   {"epoch": epoch(), "mode": True}, {"epoch": epoch(), "mode": "automatic"},
                   {"epoch": epoch(), "mode": "include"}, {**rule(), "version": None},
                   {**rule(), "version": True}, {**rule(), "version": ["target"]},
                   {**rule(), "version": "TARGET"}, {**rule(), "version": "private-version-sentinel"},
                   {**rule(), "reason": "private-reason-sentinel"},
                   {**rule("exclude"), "version": None}, {**rule("rules"), "version": "target"}]
        for value in invalid:
            with self.subTest(value=value):
                self.assertInvalid(lambda: policy.normalize(snapshot(value)))

    def test_epoch_shapes_kinds_and_revision_bounds_are_strict(self):
        invalid = [None, [], {}, {**epoch(), "kind": "unknown"}, {**epoch(), "kind": True},
                   {**epoch(), "kind": []}, {**epoch(), "extra": "private-anchor-sentinel"},
                   epoch(revision=0), epoch(revision=10_001), epoch(revision=True), epoch(revision=1.0),
                   epoch(revision="1"), epoch(revision=None), epoch(revision=2, kind="baseline")]
        valid = epoch()
        invalid.extend({key: value for key, value in valid.items() if key != missing} for missing in valid)
        for anchor in invalid:
            with self.subTest(anchor=anchor):
                self.assertInvalid(lambda: policy.normalize(snapshot(rule(anchor=anchor))))
        for anchor in (epoch(kind="baseline"), epoch(revision=1), epoch(revision=10_000)):
            self.assertEqual(policy.lookup(snapshot(rule(anchor=anchor)), anchor)["epoch"], anchor)

    def test_epochs_only_accept_safe_home_house_origin_ids(self):
        for deck_id in (None, True, [], "", "fixture", "user2/casual/fixture", "product/fixture",
                        "pairing/a+b", "casual/", "casual/.hidden", "casual/fixture/child", "casual/a\\b",
                        "casual/a:b", "casual/ padded", "casual/padded ", "casual/a\n", "casual/a\x7f",
                        "casual/\ud800", "casual/" + "x" * 194):
            with self.subTest(deck_id=repr(deck_id)):
                self.assertInvalid(lambda: policy.normalize(snapshot(rule(anchor=epoch(deck_id)))))
        boundary = "casual/" + "x" * 193
        self.assertEqual(len(boundary), 200)
        self.assertEqual(policy.lookup(snapshot(rule(anchor=epoch(boundary))), epoch(boundary))["epoch"]["deck_id"], boundary)

    def test_epoch_origin_kind_must_match_its_policy_format(self):
        commander = rule(anchor=epoch("commander/fixture"))
        self.assertEqual(policy.normalize(snapshot(commander, fmt="Commander"))["rules"], [commander])
        self.assertInvalid(lambda: policy.normalize(snapshot(commander)))
        self.assertInvalid(lambda: policy.normalize(snapshot(rule(), fmt="Commander")))
        self.assertInvalid(lambda: policy.lookup(policy.empty("Commander"), epoch()))
        self.assertInvalid(lambda: policy.transition(policy.empty("Commander"), 0, rule()))

    def test_duplicate_full_epochs_are_refused_including_identical_intent(self):
        for first, second in ((rule(), rule()), (rule(), rule("exclude")),
                              (rule("rules"), rule("rules"))):
            self.assertInvalid(lambda: policy.normalize(snapshot(first, second)))

    def test_different_kinds_revisions_and_origins_are_distinct_sorted_keys(self):
        values = [rule(anchor=epoch("casual/z", 9)), rule(anchor=epoch("casual/a", 8)),
                  rule(anchor=epoch("casual/a", 1, "baseline")), rule(anchor=epoch("casual/a", 1))]
        expected = [values[index] for index in (2, 3, 1, 0)]
        self.assertEqual(policy.normalize(snapshot(*values))["rules"], expected)
        self.assertEqual(policy.normalize(snapshot(*reversed(values)))["rules"], expected)
        self.assertEqual(json.loads(json.dumps(policy.normalize(snapshot(*values)))), snapshot(*expected))

    def test_invalid_errors_never_relay_supplied_private_fields_or_values(self):
        for value in (snapshot(fmt="PRIVATE-SECRET"), snapshot({"PRIVATE-SECRET": "PRIVATE-SECRET"}),
                      snapshot(rule(anchor=epoch("PRIVATE-SECRET")))):
            with self.assertRaises(Invalid) as caught:
                policy.normalize(value)
            self.assertEqual(str(caught.exception), policy.INVALID)
            self.assertNotIn("PRIVATE-SECRET", str(caught.exception))


class PolicyLookupTests(unittest.TestCase):
    def test_absent_rule_and_explicit_use_rules_are_distinct(self):
        self.assertIsNone(policy.lookup(policy.empty("Constructed"), epoch()))
        self.assertEqual(policy.lookup(snapshot(rule("rules")), epoch()), rule("rules"))

    def test_new_incarnation_does_not_inherit_older_intent_for_the_same_id(self):
        older = epoch(revision=2)
        newer = epoch(revision=8)
        saved = snapshot(rule("exclude", anchor=older))
        self.assertIsNone(policy.lookup(saved, newer))
        self.assertEqual(policy.lookup(saved, older), rule("exclude", anchor=older))

    def test_rename_uses_the_immutable_origin_not_the_current_deck_name(self):
        original = epoch("casual/original", 3)
        saved = snapshot(rule("rules", anchor=original))
        self.assertEqual(policy.lookup(saved, original), rule("rules", anchor=original))
        self.assertIsNone(policy.lookup(saved, epoch("casual/renamed", 3)))

    def test_lookup_checks_the_whole_snapshot_before_returning_a_matching_entry(self):
        saved = snapshot(rule(), rule(anchor=epoch("casual/unrelated", 3)))
        saved["rules"][1]["mode"] = "PRIVATE-DAMAGED"
        with self.assertRaises(Invalid) as caught:
            policy.lookup(saved, epoch())
        self.assertEqual(str(caught.exception), policy.INVALID)

    def test_outputs_never_alias_input_nested_nodes_or_other_calls(self):
        supplied = snapshot(rule())
        anchor = epoch()
        original, original_anchor = copy.deepcopy(supplied), copy.deepcopy(anchor)
        normalized = policy.normalize(supplied)
        first, second = policy.lookup(supplied, anchor), policy.lookup(supplied, anchor)
        normalized["rules"][0]["epoch"]["deck_id"] = "casual/normalized-change"
        normalized["rules"].append(rule("exclude"))
        first["epoch"]["deck_id"] = "casual/lookup-change"
        self.assertEqual(supplied, original)
        self.assertEqual(anchor, original_anchor)
        self.assertEqual(second, rule())


class PolicyTransitionTests(unittest.TestCase):
    def test_first_use_rules_is_a_real_write_and_stays_a_tombstone(self):
        supplied = policy.empty("Constructed")
        result = policy.transition(supplied, 0, rule("rules"))
        self.assertEqual(result, {"changed": True, "snapshot": snapshot(rule("rules"))})
        self.assertEqual(supplied, policy.empty("Constructed"))
        self.assertEqual(policy.lookup(result["snapshot"], epoch())["mode"], "rules")

    def test_repeated_intent_is_a_noop_but_stale_identical_intent_conflicts_first(self):
        for desired in (rule("include", "target"), rule("include", "owned"), rule("exclude"), rule("rules")):
            saved = snapshot(desired, revision=7)
            self.assertEqual(policy.transition(saved, 7, desired), {"changed": False, "snapshot": saved})
            with self.assertRaises(Conflict) as caught:
                policy.transition(saved, 6, desired)
            self.assertEqual(str(caught.exception), policy.CHANGED)

    def test_expected_revisions_are_strict_and_stale_different_intent_is_unchanged(self):
        saved = snapshot(rule(), revision=3)
        original = copy.deepcopy(saved)
        for expected in (None, True, "3", 3.0, -1, policy.MAX_REVISION + 1):
            with self.subTest(expected=expected), self.assertRaises(Invalid) as caught:
                policy.transition(saved, expected, rule("exclude"))
            self.assertEqual(str(caught.exception), policy.INVALID)
        for expected in (0, 2, 4, policy.MAX_REVISION):
            with self.subTest(expected=expected), self.assertRaises(Conflict) as caught:
                policy.transition(saved, expected, rule("exclude"))
            self.assertEqual(str(caught.exception), policy.CHANGED)
        self.assertEqual(saved, original)

    def test_include_versions_and_exclude_use_rules_replace_exactly_one_epoch(self):
        unrelated = rule(anchor=epoch("casual/unrelated", 2))
        saved = snapshot(unrelated, rule("exclude"))
        for desired in (rule("include", "owned"), rule("include", "target"), rule("exclude"), rule("rules")):
            before = copy.deepcopy(saved)
            result = policy.transition(saved, saved["revision"], desired)
            self.assertTrue(result["changed"])
            self.assertEqual(result["snapshot"]["revision"], saved["revision"] + 1)
            self.assertEqual(policy.lookup(result["snapshot"], epoch()), desired)
            self.assertEqual(policy.lookup(result["snapshot"], epoch("casual/unrelated", 2)), unrelated)
            self.assertEqual(len(result["snapshot"]["rules"]), 2)
            self.assertEqual(saved, before)
            saved = result["snapshot"]

    def test_recreated_deck_adds_its_new_epoch_without_replacing_obsolete_entries(self):
        old = rule("rules", anchor=epoch(revision=2))
        fresh = rule("exclude", anchor=epoch(revision=7))
        saved = snapshot(old)
        result = policy.transition(saved, 1, fresh)
        self.assertEqual(result["snapshot"], snapshot(old, fresh, revision=2))
        self.assertEqual(policy.lookup(result["snapshot"], old["epoch"]), old)
        self.assertEqual(policy.lookup(result["snapshot"], fresh["epoch"]), fresh)
        self.assertIsNone(policy.lookup(result["snapshot"], epoch(revision=8)))

    def test_transition_results_are_detached_even_for_noop_and_sorted_input(self):
        supplied = snapshot(rule(anchor=epoch("casual/z")), rule(anchor=epoch("casual/a")))
        desired = rule("rules", anchor=epoch("casual/m"))
        original, original_desired = copy.deepcopy(supplied), copy.deepcopy(desired)
        changed = policy.transition(supplied, 1, desired)
        second = policy.transition(supplied, 1, desired)
        changed["snapshot"]["rules"][0]["epoch"]["deck_id"] = "casual/output-change"
        self.assertEqual(supplied, original)
        self.assertEqual(desired, original_desired)
        self.assertEqual(second["snapshot"]["rules"], [supplied["rules"][1], desired, supplied["rules"][0]])
        noop = policy.transition(supplied, 1, supplied["rules"][0])
        self.assertFalse(noop["changed"])
        noop["snapshot"]["rules"][0]["epoch"]["deck_id"] = "casual/noop-output-change"
        self.assertEqual(supplied, original)

    def test_overflow_refuses_changes_but_allows_matching_noop_at_maximum(self):
        saved = snapshot(rule(), revision=policy.MAX_REVISION)
        original = copy.deepcopy(saved)
        self.assertEqual(policy.transition(saved, policy.MAX_REVISION, rule()),
                         {"changed": False, "snapshot": saved})
        for desired in (rule("exclude"), rule(anchor=epoch("casual/another"))):
            with self.assertRaises(Invalid) as caught:
                policy.transition(saved, policy.MAX_REVISION, desired)
            self.assertEqual(str(caught.exception), policy.INVALID)
        with self.assertRaises(Conflict) as caught:
            policy.transition(saved, policy.MAX_REVISION - 1, rule())
        self.assertEqual(str(caught.exception), policy.CHANGED)
        self.assertEqual(saved, original)

    def test_exact_5000_rule_limit_allows_updates_but_never_evicts_an_old_epoch(self):
        self.assertEqual(policy.MAX_RULES, 5000)
        values = [rule("exclude", anchor=epoch(f"casual/fixture-{i:04d}")) for i in range(policy.MAX_RULES)]
        saved = snapshot(*values, revision=12)
        self.assertEqual(len(policy.normalize(saved)["rules"]), 5000)
        update = rule("rules", anchor=values[2345]["epoch"])
        result = policy.transition(saved, 12, update)
        self.assertTrue(result["changed"])
        self.assertEqual(len(result["snapshot"]["rules"]), 5000)
        self.assertEqual(policy.lookup(result["snapshot"], update["epoch"]), update)
        self.assertEqual(policy.lookup(result["snapshot"], values[-1]["epoch"]), values[-1])
        extra = rule(anchor=epoch("casual/new-incarnation", 3))
        with self.assertRaises(Invalid) as caught:
            policy.transition(saved, 12, extra)
        self.assertEqual(str(caught.exception), policy.INVALID)
        with self.assertRaises(Invalid):
            policy.normalize(snapshot(*values, extra))
        self.assertEqual(saved, snapshot(*values, revision=12))

    def test_formats_have_independent_revision_and_intent(self):
        constructed = policy.transition(policy.empty("Constructed"), 0, rule("rules"))["snapshot"]
        commander_rule = rule("exclude", anchor=epoch("commander/fixture"))
        commander = policy.transition(policy.empty("Commander"), 0, commander_rule)["snapshot"]
        self.assertEqual(constructed, snapshot(rule("rules")))
        self.assertEqual(commander, snapshot(commander_rule, fmt="Commander"))
        self.assertEqual(constructed["revision"], commander["revision"])
        self.assertEqual(policy.lookup(constructed, epoch())["mode"], "rules")
        self.assertEqual(policy.lookup(commander, commander_rule["epoch"])["mode"], "exclude")
