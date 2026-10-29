"""Pure reviewed-list qualification, using supplied synthetic capture evidence."""
import contextlib
import copy
import hashlib
import unittest
from unittest import mock

from decklab.lib import cards, config, decks, gitops, inventory, state
from decklab.lib.forge import lists
from decklab.lib.inventory import deck_epoch
from decklab.lib.state import field_policy as policy
from decklab.lib.state import field_policy_source as source

CURRENT = "casual/fixture"
TARGET = "Deck\n4 Llanowar Elves\n20 Forest\n"
OWNED = "Deck\n2 Llanowar Elves\n22 Forest\n"


def text(target=TARGET, owned=OWNED):
    result = ("# Fixture deck\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** either\n"
              "- **Status:** building\n\n")
    if target is not None:
        result += f"## Decklist\n\n```\n{target}```\n"
    if owned is not None:
        result += f"\n## Substitutes\n\n### Owned-only version\n\n```\n{owned}```\n"
    return result


def capture(*, content=None, deck_id=CURRENT, history=None, aliases=None):
    rows = ([{"deck_id": deck_id, "revision": 1, "op": "A", "change_set_id": 1}]
            if history is None else copy.deepcopy(history))
    content = text() if content is None else content
    revision = len(rows)
    return {"backend": "db", "persisted": True, "stale": None, "complete": True,
            "requested_id": deck_id, "current": {"id": deck_id, "revision": revision, "text": content},
            "current_ids": [deck_id], "aliases": dict(aliases or {}), "history": rows,
            "latest": {"deck_id": deck_id, "revision": revision, "text": content}}


def rule(expected, mode="include"):
    result = {"epoch": copy.deepcopy(expected["epoch"]), "mode": mode}
    if mode == "include":
        result["version"] = expected["version"]
    return result


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SourceQualificationTests(unittest.TestCase):
    def test_target_and_owned_bind_exact_text_and_different_playable_cards(self):
        raw = capture()
        target = source.qualify(raw, "target", "Constructed")
        owned = source.qualify(raw, "owned", "Constructed")
        self.assertEqual(target, {"epoch": {"kind": "creation", "deck_id": CURRENT, "revision": 1},
                                  "receipt": {"deck_id": CURRENT, "revision": 1,
                                              "sha256": sha(raw["current"]["text"])},
                                  "version": "target", "card_sha": sha("[Main]\n20 Forest\n4 Llanowar Elves\n")})
        self.assertEqual(owned["receipt"], target["receipt"])
        self.assertEqual(owned["epoch"], target["epoch"])
        self.assertEqual(owned["version"], "owned")
        self.assertEqual(owned["card_sha"], sha("[Main]\n22 Forest\n2 Llanowar Elves\n"))

    def test_commander_uses_commander_hashing_with_explicit_home_parse(self):
        raw = capture(content=text("Commander\n1 Fixture Leader\n\nDeck\n99 Forest\n"),
                      deck_id="commander/fixture")
        parse = decks.parse_deck
        with mock.patch.object(decks, "parse_deck", wraps=parse) as called:
            checked = source.qualify(raw, "target", "Commander")
        self.assertEqual(checked["card_sha"], sha("[Commander]\n1 Fixture Leader\n[Main]\n99 Forest\n"))
        self.assertEqual(called.call_args.kwargs, {"slug": "fixture", "kind": "commander", "space": "home"})

    def test_rename_retains_epoch_and_binds_new_current_identity(self):
        old = "casual/old"
        raw = capture(history=[{"deck_id": old, "revision": 1, "op": "A", "change_set_id": 1},
                               {"deck_id": CURRENT, "revision": 2, "op": "M", "change_set_id": 2}],
                      aliases={old: CURRENT})
        result = source.qualify(raw, "target", "Constructed")
        self.assertEqual(result["epoch"], {"kind": "creation", "deck_id": old, "revision": 1})
        self.assertEqual(result["receipt"]["deck_id"], CURRENT)
        self.assertEqual(result["receipt"]["revision"], 2)

    def test_imported_baseline_and_recreation_use_checked_history(self):
        initial = {"deck_id": CURRENT, "revision": 1, "op": "M", "change_set_id": None}
        first = source.qualify(capture(history=[initial]), "target", "Constructed")
        self.assertEqual(first["epoch"]["kind"], "baseline")
        recreated = capture(history=[initial,
                                    {"deck_id": CURRENT, "revision": 2, "op": "D", "change_set_id": 2},
                                    {"deck_id": CURRENT, "revision": 3, "op": "A", "change_set_id": 3}])
        self.assertEqual(source.qualify(recreated, "target", "Constructed")["epoch"],
                         {"kind": "creation", "deck_id": CURRENT, "revision": 3})

    def test_no_target_block_is_unavailable_even_when_owned_exists(self):
        for version in ("target", "owned"):
            with self.subTest(version=version), self.assertRaisesRegex(state.Unavailable, source.UNAVAILABLE):
                source.qualify(capture(content=text(None)), version, "Constructed")

    def test_owned_requires_a_nonempty_played_section(self):
        for owned in (None, "", "Deck\n", "Sideboard\n1 Forest\n"):
            with self.subTest(owned=owned), self.assertRaisesRegex(state.Unavailable, source.UNAVAILABLE):
                source.qualify(capture(content=text(owned=owned)), "owned", "Constructed")
        # An explicit empty target fence is representable and has a stable hash.
        self.assertEqual(source.qualify(capture(content=text("", None)), "target", "Constructed")["card_sha"],
                         sha("[Main]\n"))

    def test_card_identity_is_pure_and_ignores_sideboard_prose_and_printing(self):
        raw = capture(content=text("Deck\n4 Llanowar Elves (FDN) 227\n20 Forest\n\nSideboard\n1 Swamp\n"))
        with contextlib.ExitStack() as stack:
            for module, name in ((config, "load"), (inventory, "current"), (inventory, "backend"),
                                 (state, "store"), (cards, "_get"), (cards, "resolve"),
                                 (lists, "entry"), (lists, "_source"), (gitops, "run")):
                stack.enter_context(mock.patch.object(module, name, side_effect=AssertionError("forbidden IO")))
            checked = source.qualify(raw, "target", "Constructed")
        self.assertEqual(checked["card_sha"], sha("[Main]\n20 Forest\n4 Llanowar Elves\n"))

    def test_uncertain_source_evidence_never_becomes_a_review_proof(self):
        for key, value in (("backend", "files"), ("persisted", False), ("stale", "private error"),
                           ("complete", False), ("history", []), ("aliases", {CURRENT: None})):
            raw = capture()
            raw[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(state.Unavailable, source.UNAVAILABLE):
                source.qualify(raw, "target", "Constructed")
        for raw in (None, [], {}, capture(content="private malformed text")):
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(state.Unavailable) as caught:
                source.qualify(raw, "target", "Constructed")
            self.assertEqual(str(caught.exception), source.UNAVAILABLE)

    def test_wrong_format_and_unsupported_house_identity_are_unavailable(self):
        for raw, fmt in ((capture(), "Commander"), (capture(deck_id="commander/fixture"), "Constructed"),
                         (capture(deck_id="user2/casual/private"), "Constructed"),
                         (capture(deck_id="product/fixture"), "Constructed")):
            with self.subTest(fmt=fmt), self.assertRaises(state.Unavailable):
                source.qualify(raw, "target", fmt)

    def test_bad_version_or_format_is_invalid_intent(self):
        for version, fmt in (("default", "Constructed"), (True, "Constructed"), ([], "Commander"),
                             ("target", "constructed"), ("target", None), ("target", {})):
            with self.subTest(version=version, fmt=fmt), self.assertRaisesRegex(state.Invalid, source.INVALID):
                source.qualify(capture(), version, fmt)

    def test_errors_are_fixed_and_do_not_relay_capture_or_parser_details(self):
        for module, name in ((deck_epoch, "resolve"), (decks, "parse_deck"), (lists, "card_sha")):
            with self.subTest(name=name), mock.patch.object(module, name, side_effect=ValueError("PRIVATE text")):
                with self.assertRaises(state.Unavailable) as caught:
                    source.qualify(capture(), "target", "Constructed")
                self.assertEqual(str(caught.exception), source.UNAVAILABLE)

    def test_input_capture_and_return_values_are_detached(self):
        raw = capture()
        before = copy.deepcopy(raw)
        first = source.qualify(raw, "target", "Constructed")
        first["epoch"]["deck_id"] = "casual/changed"
        first["receipt"]["revision"] = 99
        self.assertEqual(raw, before)
        second = source.qualify(raw, "target", "Constructed")
        self.assertEqual(second["epoch"]["deck_id"], CURRENT)
        self.assertEqual(second["receipt"]["revision"], 1)


class ReviewIntentTests(unittest.TestCase):
    def setUp(self):
        self.raw = capture()
        self.expected = source.qualify(self.raw, "target", "Constructed")

    def invalid(self, value, fmt="Constructed"):
        with self.assertRaises(state.Invalid) as caught:
            source.proof(value, fmt)
        self.assertEqual(str(caught.exception), source.INVALID)

    def test_proof_requires_exact_key_sets_and_typed_lowercase_hashes(self):
        for path in ((), ("epoch",), ("receipt",)):
            for action in ("extra", "missing"):
                value = copy.deepcopy(self.expected)
                nested = value
                for key in path:
                    nested = nested[key]
                if action == "extra":
                    nested["reason"] = "PRIVATE"
                else:
                    nested.pop(next(iter(nested)))
                with self.subTest(path=path, action=action):
                    self.invalid(value)
        for key, bad in (("card_sha", "A" * 64), ("card_sha", "a" * 63), ("card_sha", True),
                         ("card_sha", "a" * 64 + "\n"), ("version", []), ("version", "owned-only")):
            value = copy.deepcopy(self.expected)
            value[key] = bad
            with self.subTest(key=key, bad=bad):
                self.invalid(value)

    def test_epoch_and_receipt_are_strict_home_format_qualified_and_bounded(self):
        for path, key, bad in (("epoch", "kind", "oldest"), ("epoch", "revision", True),
                               ("epoch", "revision", 0), ("epoch", "revision", deck_epoch.MAX_HISTORY + 1),
                               ("receipt", "revision", True), ("receipt", "revision", 0),
                               ("receipt", "revision", deck_epoch.MAX_HISTORY + 1),
                               ("receipt", "sha256", "B" * 64), ("receipt", "sha256", 1),
                               ("receipt", "deck_id", "user2/casual/private"),
                               ("receipt", "deck_id", "product/precon"),
                               ("receipt", "deck_id", "commander/fixture"),
                               ("epoch", "deck_id", "commander/fixture")):
            value = copy.deepcopy(self.expected)
            value[path][key] = bad
            with self.subTest(path=path, key=key, bad=bad):
                self.invalid(value)
        value = copy.deepcopy(self.expected)
        value["epoch"].update(kind="baseline", revision=2)
        value["receipt"]["revision"] = 2
        self.invalid(value)
        value["epoch"]["kind"] = "creation"
        value["receipt"]["revision"] = 1
        self.invalid(value)

    def test_all_modes_bind_the_reviewed_epoch_and_include_binds_version(self):
        for mode in ("include", "exclude", "rules"):
            desired = rule(self.expected, mode)
            wanted, checked = source.intent(self.expected, desired, "Constructed")
            self.assertEqual(wanted, self.expected)
            self.assertEqual(checked, desired)
            checked["epoch"]["deck_id"] = "casual/changed"
            wanted["receipt"]["revision"] = 99
            self.assertEqual(desired["epoch"]["deck_id"], CURRENT)
            self.assertEqual(self.expected["receipt"]["revision"], 1)
        mismatch = rule(self.expected)
        mismatch["version"] = "owned"
        with self.assertRaises(state.Invalid):
            source.intent(self.expected, mismatch, "Constructed")

    def test_bad_rule_consistency_fails_before_any_fresh_source_work(self):
        cases = [None, {"epoch": self.expected["epoch"], "mode": "include"},
                 {"epoch": self.expected["epoch"], "mode": "rules", "reason": "PRIVATE"}]
        for mode in ("include", "exclude", "rules"):
            value = rule(self.expected, mode)
            value["epoch"]["deck_id"] = "casual/other"
            cases.append(value)
        with mock.patch.object(source, "qualify", side_effect=AssertionError("must preflight first")) as called:
            for desired in cases:
                with self.subTest(desired=desired), self.assertRaisesRegex(state.Invalid, source.INVALID):
                    source.recheck(None, self.expected, desired, "Constructed")
            called.assert_not_called()

    def test_recheck_returns_detached_fresh_proof_for_each_mode_and_owned_review(self):
        for version in ("target", "owned"):
            expected = source.qualify(self.raw, version, "Constructed")
            for mode in ("include", "exclude", "rules"):
                with self.subTest(version=version, mode=mode):
                    checked = source.recheck(self.raw, expected, rule(expected, mode), "Constructed")
                    self.assertEqual(checked, expected)
                    self.assertIsNot(checked, expected)
                    self.assertIsNot(checked["receipt"], expected["receipt"])

    def test_same_cards_with_changed_prose_still_conflict_on_exact_text_receipt(self):
        changed = capture(content=text() + "\n## Notes\nPrivate fixture note\n")
        self.assertEqual(source.qualify(changed, "target", "Constructed")["card_sha"], self.expected["card_sha"])
        with self.assertRaises(state.Conflict) as caught:
            source.recheck(changed, self.expected, rule(self.expected), "Constructed")
        self.assertEqual(str(caught.exception), source.CHANGED)

    def test_every_full_proof_component_is_compared(self):
        for key, replacement in (("epoch", {"kind": "creation", "deck_id": "casual/old", "revision": 1}),
                                  ("receipt", {"deck_id": "casual/renamed", "revision": 1, "sha256": "0" * 64}),
                                  ("card_sha", "0" * 64), ("version", "owned")):
            value = copy.deepcopy(self.expected)
            value[key] = replacement
            with (self.subTest(key=key), mock.patch.object(source, "qualify", return_value=value),
                  self.assertRaisesRegex(state.Conflict, source.CHANGED)):
                source.recheck(self.raw, self.expected, rule(self.expected), "Constructed")

    def test_recheck_is_required_even_when_policy_transition_is_noop(self):
        desired = rule(self.expected)
        saved = policy.transition(policy.empty("Constructed"), 0, desired)["snapshot"]
        self.assertFalse(policy.transition(saved, 1, desired)["changed"])
        changed = capture(content=text(TARGET.replace("4 Llanowar", "3 Llanowar")))
        with self.assertRaises(state.Conflict):
            source.recheck(changed, self.expected, desired, "Constructed")

    def test_uncertain_fresh_capture_is_unavailable_instead_of_changed_or_ready(self):
        self.raw["complete"] = False
        with self.assertRaises(state.Unavailable) as caught:
            source.recheck(self.raw, self.expected, rule(self.expected), "Constructed")
        self.assertEqual(str(caught.exception), source.UNAVAILABLE)


class ExclusionReasonTests(unittest.TestCase):
    def test_exclude_requires_a_bounded_stripped_private_reason(self):
        self.assertEqual(source.exclusion_reason(" \n Not suitable\tfor this field\n today \t", "exclude"),
                         "Not suitable\tfor this field\n today")
        self.assertEqual(source.exclusion_reason(" " + "x" * 1000 + " ", "exclude"), "x" * 1000)
        for value in (None, "", " \t\n", "x" * 1001, True, [], "private\x00", "private\rline",
                      "private\x7f", "private\ud800", "\rprivate", "private\f"):
            with self.subTest(value=repr(value)), self.assertRaises(state.Invalid) as caught:
                source.exclusion_reason(value, "exclude")
            self.assertEqual(str(caught.exception), source.INVALID_REASON)

    def test_optional_reasons_follow_the_same_validation_and_never_enter_proof_or_policy(self):
        for mode in ("include", "rules"):
            self.assertIsNone(source.exclusion_reason(None, mode))
            self.assertIsNone(source.exclusion_reason(" \n\t ", mode))
            self.assertEqual(source.exclusion_reason(" PRIVATE audit only ", mode), "PRIVATE audit only")
            with self.assertRaisesRegex(state.Invalid, source.INVALID_REASON):
                source.exclusion_reason("private\x01", mode)
        expected = source.qualify(capture(), "target", "Constructed")
        wanted, desired = source.intent(expected, rule(expected, "exclude"), "Constructed")
        self.assertNotIn("reason", wanted)
        self.assertNotIn("reason", desired)

    def test_unknown_modes_and_errors_do_not_echo_private_input(self):
        for mode in (None, [], "delete", True):
            with self.subTest(mode=mode), self.assertRaises(state.Invalid) as caught:
                source.exclusion_reason("PRIVATE value", mode)
            self.assertEqual(str(caught.exception), source.INVALID_REASON)
