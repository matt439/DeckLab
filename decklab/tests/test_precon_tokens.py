"""Optional precon tokens use explicit source quantities and one atomic inventory operation."""
import copy
import unittest
from unittest import mock

from decklab.lib import cards, inventory, precon_tokens
from decklab.lib.api import precons as api
from decklab.lib.inventory import Op, files, ops_decks, rules
from decklab.lib.inventory.model import Inventory
from decklab.lib.state import Actor, Invalid
from decklab.lib.tokens import names, ops as token_ops
from decklab.tests import test_precons as fixtures


class PreconTokenCandidateTests(unittest.TestCase):
    def setUp(self):
        for target, attr, value in ((names, "_ready", mock.Mock(return_value=True)),
                                    (cards, "token_face", mock.Mock(side_effect=lambda name: {
                                        "rabbit": "Rabbit", "dinosaur": "Dinosaur", "ambiguous": "Rabbit // Rabbit"}.get(name.lower()))),
                                    (cards, "token_face_names", mock.Mock(return_value=["Rabbit", "Dinosaur"]))):
            patcher = mock.patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_source_rows_and_declared_counts_stay_separate_with_every_unknown_field_blank(self):
        data = {"tokens": [{"name": "dinosaur", "count": 3, "setCode": "TST", "number": "1", "isFoil": True},
                           {"name": "Dinosaur", "count": 1}, {"name": "Rabbit", "count": 2}]}
        before = copy.deepcopy(data)
        result = precon_tokens.candidates(data, "Fixture_TST")
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["cards"], 6)
        self.assertEqual([(item["source_row"], item["row"]["front"], item["row"]["quantity"]) for item in result["rows"]],
                         [(1, "Dinosaur", "3"), (2, "Dinosaur", "1"), (3, "Rabbit", "2")])
        for item in result["rows"]:
            row = item["row"]
            self.assertEqual(set(row), set(rules.TOKEN_FIELDS))
            for field in ("back", "set", "front_collector_number", "back_collector_number", "finish", "front_details", "back_details"):
                self.assertEqual(row[field], "")
            self.assertIn(f"token entry {item['source_row']}", row["notes"])
            self.assertIn("printing and reverse face unconfirmed", row["notes"])
            self.assertNotIn("single-sided verified", row["notes"])
            self.assertFalse(rules.token_known(row))
        self.assertEqual(data, before)

    def test_missing_null_and_empty_token_lists_mean_none(self):
        for data in ({}, {"tokens": None}, {"tokens": []}):
            self.assertEqual(precon_tokens.candidates(data, "Fixture_TST"), {"rows": [], "cards": 0, "problems": []})

    def test_no_missing_malformed_or_out_of_range_count_is_guessed(self):
        for value in (None, True, False, 0, -1, 1.5, "2", 251):
            result = precon_tokens.candidates({"tokens": [{"name": "Rabbit", "count": value}]}, "Fixture_TST")
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["cards"], 0)
            self.assertIn("physical quantity is unknown", result["problems"][0]["message"])
        result = precon_tokens.candidates({"tokens": [{"name": "Rabbit"}]}, "Fixture_TST")
        self.assertTrue(result["problems"])

    def test_malformed_combined_unknown_or_unchecked_names_are_optional_batch_problems(self):
        for raw in ([None], [{"name": "Rabbit // Dinosaur", "count": 2}], [{"name": "ambiguous", "count": 1}],
                    [{"name": "Unknown fixture token", "count": 1}], [{"name": "", "count": 1}],
                    [{"name": "x" * 81, "count": 1}], "not a list", {}):
            result = precon_tokens.candidates({"tokens": raw}, "Fixture_TST")
            self.assertTrue(result["problems"])
            self.assertEqual(result["rows"], [])
        with mock.patch.object(names, "_ready", return_value=False):
            result = precon_tokens.candidates({"tokens": [{"name": "Rabbit", "count": 1}]}, "Fixture_TST")
        self.assertEqual(result["rows"], [])
        self.assertIn("cannot be checked", result["problems"][0]["message"])

    def test_source_row_bound_and_mixed_invalid_batch_remain_explicit(self):
        result = precon_tokens.candidates({"tokens": [{"name": "Rabbit", "count": 1}] * (precon_tokens.MAX_ROWS + 1)}, "Fixture_TST")
        self.assertTrue(result["problems"])
        self.assertEqual(result["rows"], [])
        result = precon_tokens.candidates({"tokens": [{"name": "Rabbit", "count": 2}, {"name": "Rabbit"}]}, "Fixture_TST")
        self.assertEqual(result["cards"], 2)
        self.assertEqual(result["rows"][0]["source_row"], 1)
        self.assertEqual(result["problems"][0]["line"], 2)

    def test_late_optional_name_index_failure_is_static_and_refuses_only_the_candidates(self):
        for error in (RuntimeError("private fixture path"), ValueError("private fixture path")):
            with self.subTest(error=type(error).__name__), mock.patch.object(names, "check_names", side_effect=error):
                result = precon_tokens.candidates({"tokens": [{"name": "Rabbit", "count": 2}]}, "Fixture_TST")
                self.assertEqual(result["rows"], [])
                self.assertIn("cannot be checked", result["problems"][0]["message"])
                self.assertNotIn("private fixture path", str(result))


class PreconTokensTestCase(fixtures.PreconTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(cards, "token_face", side_effect=lambda name: "Dinosaur" if cards.fold(name) == "dinosaur" else None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def offer(self, space="user2"):
        return api.precon_preview("TestDinos_TST", space)["token_import"]

    def add_tokens(self, **extra):
        offer = self.offer()
        extra.setdefault("tokens_sha256", offer["sha256"])
        extra.setdefault("tokens_source_sha256", offer["source_sha256"])
        return self.add(add_tokens=True, **extra)


class PreconTokenApiTests(PreconTokensTestCase):
    def test_preview_reports_declared_separate_rows_without_saving(self):
        before = self.writes_made()
        offer = self.offer()
        self.assertTrue(offer["editable"])
        self.assertTrue(offer["ready"])
        self.assertEqual(offer["cards"], 4)
        self.assertEqual([(r["front"], r["quantity"], r["source_row"]) for r in offer["rows"]],
                         [("Dinosaur", 3, 1), ("Dinosaur", 1, 2)])
        self.assertEqual(self.writes_made(), before)

    def test_opt_in_adds_collection_deck_and_token_rows_in_one_change_with_independent_counts(self):
        before = self.writes_made()
        answer = self.add_tokens()
        self.assertEqual(answer["tokens"], {"cards": 4, "rows": 2})
        self.assertEqual(answer["collection"]["added"], {"cards": 5, "rows": 3})
        self.assertEqual(self.writes_made(), before + 1)
        rows = inventory.current().token_set("user2").rows
        self.assertEqual([(r["front"], r["quantity"]) for r in rows], [("Dinosaur", "3"), ("Dinosaur", "1")])
        self.assertTrue(all(not r["back"] and not r["set"] and not r["finish"] for r in rows))
        self.assertTrue(all("reverse face unconfirmed" in r["notes"] for r in rows))
        self.assertIn("add 4 token cards", self.last_write()[0])
        self.assertTrue(inventory.current().deck(answer["deck"]["id"]))
        text = inventory.current().deck(answer["deck"]["id"]).text
        self.assertIn("were recorded as separate token rows", text)
        self.assertNotIn("before recording them", text)

    def test_default_opt_out_never_reads_or_writes_tokens_and_keeps_response_shape(self):
        with mock.patch.object(Inventory, "token_set", side_effect=AssertionError("token state read on opt-out")):
            answer = self.add(title="Playable only")
        self.assertNotIn("tokens", answer)

    def test_invalid_or_ambiguous_optional_source_blocks_only_opt_in(self):
        for raw in ([{"name": "Dinosaur"}], [{"name": "Dinosaur // Dinosaur", "count": 1}], [{"name": "Unknown", "count": 2}], {}):
            with self.subTest(raw=raw):
                self.seed("decks/TestDinos_TST.json", {"data": dict(fixtures.DINOS["data"], tokens=raw)})
                offer = self.offer()
                self.assertFalse(offer["ready"])
                self.assertTrue(offer["problems"])
                before = self.writes_made()
                error = self.assertApiError(400, self.add_tokens)
                self.assertTrue(error.extra["token_problems"])
                self.assertEqual(self.writes_made(), before)
                made = api.plan_add("user2", "TestDinos_TST", "Valid playable only", None, None, "Claude")
                self.assertNotIn("token_rows", made["op"].params)

    def test_strict_opt_in_and_explicit_nullable_full_token_hash(self):
        for value in (None, 1, "true", [], {}):
            self.assertApiError(400, self.add, add_tokens=value)
        self.assertApiError(400, self.add, add_tokens=True)
        for value in (False, 3, "", "a" * 12, "A" * 64):
            self.assertApiError(400, self.add, add_tokens=True, tokens_sha256=value)
            self.assertApiError(400, self.add, add_tokens=True, tokens_sha256=None, tokens_source_sha256=value)
        self.assertApiError(400, self.add, add_tokens=True, tokens_sha256=None)
        self.assertEqual(self.writes_made(), 0)

    def test_changed_public_source_quantity_requires_a_fresh_review_before_any_apply(self):
        reviewed = self.offer()
        data = copy.deepcopy(fixtures.DINOS)
        data["data"]["tokens"][0]["count"] = 2
        self.seed("decks/TestDinos_TST.json", data)
        before, snapshot = self.writes_made(), files.render(inventory.current())
        with mock.patch.object(self.backend, "apply", side_effect=AssertionError("unreviewed source reached apply")):
            error = self.assertApiError(409, self.add, add_tokens=True, tokens_sha256=reviewed["sha256"],
                                       tokens_source_sha256=reviewed["source_sha256"])
        self.assertEqual(error.extra, {"token_conflict": True})
        self.assertNotEqual(self.offer()["source_sha256"], reviewed["source_sha256"])
        self.assertEqual(self.writes_made(), before)
        self.assertEqual(files.render(inventory.current()), snapshot)

    def test_stale_token_hash_has_unique_conflict_shape_and_no_writes(self):
        error = self.assertApiError(409, self.add_tokens, tokens_sha256="0" * 64)
        self.assertEqual(error.extra, {"token_conflict": True})
        self.assertNotIn("sha256", error.extra)
        self.assertNotIn("rows", error.extra)
        self.assertEqual(self.writes_made(), 0)

    def test_token_permission_is_checked_before_token_state_or_source_access(self):
        original = api.guard.allowed
        def allowed(profile, action, target=None):
            return False if action == "tokens.edit" else original(profile, action, target)
        with mock.patch.object(api.guard, "allowed", side_effect=allowed), \
                mock.patch.object(Inventory, "token_set", side_effect=AssertionError("private token state read")):
            offer = self.offer()
            self.assertFalse(offer["editable"])
            self.assertNotIn("sha256", offer)
        with self.as_("matt"), mock.patch.object(Inventory, "token_set", side_effect=AssertionError("private token state read")):
            self.assertApiError(403, api.precon_preview, "TestDinos_TST", "user2")
            self.assertApiError(403, self.add, profile="matt", add_tokens=True, tokens_sha256=None)
        require = api.guard.require_space_write
        def no_tokens(profile, action, space):
            if action == "tokens.edit":
                raise api.ApiError(403, "Fixture token permission denied")
            return require(profile, action, space)
        with mock.patch.object(api.guard, "require_space_write", side_effect=no_tokens), \
                mock.patch.object(api, "_entry", side_effect=AssertionError("source accessed before token permission")), \
                mock.patch.object(Inventory, "token_set", side_effect=AssertionError("token state read before permission")):
            self.assertApiError(403, self.add, title="Fixture no token permission", add_tokens=True,
                                tokens_sha256=None, tokens_source_sha256="0" * 64)

    def test_existing_unconfirmed_row_stays_separate_and_other_space_unchanged(self):
        row = {key: "" for key in rules.TOKEN_FIELDS}
        row.update(front="Dinosaur", quantity="2", notes="Existing printing unconfirmed")
        inventory.apply(Op("tokens.add", {"space": "user2", "sha256": self.offer()["sha256"], "row": row, "separate": True}),
                        Actor("claude", "Claude", source="cli"), "Fixture existing tokens")
        elsewhere = inventory.current().token_set("home")
        before = inventory.current().token_set("user2").rows
        answer = self.add_tokens()
        self.assertEqual(answer["tokens"], {"cards": 4, "rows": 2})
        after = inventory.current().token_set("user2").rows
        self.assertEqual(len(after), len(before) + 2)
        self.assertIn(before[0], after)
        self.assertEqual(inventory.current().token_set("home"), elsewhere)

    def test_token_edit_between_plan_and_apply_refuses_whole_precon(self):
        made = api.plan_add("user2", "TestDinos_TST", None, None, None, "Claude", add_tokens=True)
        row = made["op"].params["token_rows"][0]
        inventory.apply(Op("tokens.add", {"space": "user2", "sha256": made["op"].params["tokens_sha256"], "row": row}),
                        Actor("claude", "Claude", source="cli"), "Fixture concurrent token edit")
        before, snapshot = self.writes_made(), files.render(inventory.current())
        with self.assertRaises(token_ops.Stale) as caught:
            inventory.apply(made["op"], Actor("claude", "Claude", source="cli"), "Fixture precon")
        self.assertEqual(made["refused"](caught.exception).extra, {"token_conflict": True})
        self.assertEqual(self.writes_made(), before)
        self.assertEqual(files.render(inventory.current()), snapshot)

    def test_late_token_or_deck_failure_rolls_back_raw_import_collection_tokens_and_deck(self):
        original = token_ops.add
        def fail_second(inv, **kwargs):
            if "entry 2" in kwargs["row"]["notes"]:
                raise Invalid("Fixture second token failure")
            return original(inv, **kwargs)
        for target, name, value in ((token_ops, "add", fail_second), (ops_decks, "create", mock.Mock(side_effect=Invalid("Fixture deck failure")))):
            before, snapshot = self.writes_made(), files.render(inventory.current())
            with mock.patch.object(target, name, value):
                self.assertApiError(400, self.add_tokens)
            self.assertEqual(self.writes_made(), before)
            self.assertEqual(files.render(inventory.current()), snapshot)

    def test_token_conflict_after_plan_has_unique_response_shape(self):
        original = token_ops.add
        with mock.patch.object(token_ops, "add", side_effect=inventory.Conflict("Fixture token list cannot be rewritten")):
            error = self.assertApiError(409, self.add_tokens)
        self.assertEqual(error.extra, {"token_conflict": True})
        self.assertEqual(self.writes_made(), 0)
        self.assertIs(token_ops.add, original)
