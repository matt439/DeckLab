"""Explicit physical quantities/fronts resolve public token source entries without guessing."""
import copy
import unittest
from unittest import mock

from decklab.lib import cards, precon_tokens, precons
from decklab.lib.inventory import rules
from decklab.lib.tokens import names

SOURCE = "Fixture_TST"


class PreconTokenChoicesTests(unittest.TestCase):
    def setUp(self):
        faces = {"rabbit": "Rabbit", "dinosaur": "Dinosaur", "beast": "Beast",
                 "ambiguous": "Rabbit // Rabbit"}
        for target, attr, value in ((names, "_ready", mock.Mock(return_value=True)),
                                    (cards, "token_face", mock.Mock(side_effect=lambda name: faces.get(cards.fold(name)))),
                                    (cards, "token_face_names", mock.Mock(return_value=["Rabbit", "Dinosaur", "Beast"]))):
            patch = mock.patch.object(target, attr, value)
            patch.start()
            self.addCleanup(patch.stop)

    def candidate(self, entries, source=SOURCE):
        return precon_tokens.candidates({"tokens": entries}, source)

    def choice(self, source_row=1, front="Rabbit", quantity=1):
        return {"source_row": source_row, "front": front, "quantity": quantity}

    def test_explicit_count_legacy_rows_and_new_ordered_options_agree(self):
        candidate = self.candidate([{"name": "rabbit", "count": 2}, {"name": "Dinosaur", "count": 3}])
        self.assertEqual(candidate["problems"], [])
        self.assertEqual(candidate["cards"], 5)
        self.assertTrue(candidate["choices_ready"])
        self.assertEqual(candidate["choice_problems"], [])
        self.assertEqual(candidate["options"], [
            {"source_row": 1, "source_name": "rabbit", "fronts": ["Rabbit"], "quantity": 2},
            {"source_row": 2, "source_name": "Dinosaur", "fronts": ["Dinosaur"], "quantity": 3}])
        self.assertIn("declared quantity 2", candidate["rows"][0]["row"]["notes"])
        self.assertNotIn("user-confirmed", candidate["rows"][0]["row"]["notes"])

    def test_unknown_counts_are_confirmable_without_a_default_physical_card(self):
        for count in (None, True, False, 0, -1, 1.5, "2", precons.MAX_COUNT + 1):
            with self.subTest(count=count):
                candidate = self.candidate([{"name": "Rabbit", "count": count}])
                self.assertEqual((candidate["rows"], candidate["cards"]), ([], 0))
                self.assertTrue(candidate["problems"])
                self.assertEqual(candidate["options"][0]["quantity"], None)
                self.assertTrue(candidate["choices_ready"])
                self.assertEqual(candidate["choice_problems"], [])
        self.assertIsNone(self.candidate([{"name": "Rabbit"}])["options"][0]["quantity"])

    def test_mixed_known_and_unknown_counts_preserve_legacy_subset_and_all_choices(self):
        candidate = self.candidate([{"name": "Rabbit", "count": 2}, {"name": "Dinosaur"}])
        self.assertEqual(candidate["cards"], 2)
        self.assertEqual([item["source_row"] for item in candidate["rows"]], [1])
        self.assertEqual([item["quantity"] for item in candidate["options"]], [2, None])
        self.assertTrue(candidate["choices_ready"])

    def test_combined_source_name_offers_front_choices_for_one_physical_entry(self):
        candidate = self.candidate([{"name": "rabbit // dinosaur", "count": 2}])
        self.assertEqual((candidate["rows"], candidate["cards"]), ([], 0))
        self.assertTrue(candidate["problems"])
        self.assertEqual(candidate["options"], [{"source_row": 1, "source_name": "rabbit // dinosaur",
                                               "fronts": ["Rabbit", "Dinosaur"], "quantity": 2}])
        resolved = precon_tokens.resolve(candidate, SOURCE, [self.choice(front="Dinosaur")])
        self.assertEqual(resolved["cards"], 1)
        self.assertEqual([(item["source_row"], item["row"]["front"], item["row"]["quantity"])
                          for item in resolved["rows"]], [(1, "Dinosaur", "1")])

    def test_face_name_narrows_only_to_an_offered_checked_front(self):
        candidate = self.candidate([{"name": "Rabbit // Dinosaur", "faceName": "dinosaur"}])
        self.assertEqual(candidate["options"][0]["fronts"], ["Dinosaur"])
        self.assertTrue(candidate["choices_ready"])
        for value in ("Beast", "Rabbit // Dinosaur", True, 1, {}):
            with self.subTest(faceName=value):
                bad = self.candidate([{"name": "Rabbit // Dinosaur", "faceName": value}])
                self.assertFalse(bad["choices_ready"])
                self.assertTrue(bad["choice_problems"])

    def test_same_face_combined_or_local_full_name_never_creates_extra_entries(self):
        for name in ("Rabbit // Rabbit", "ambiguous"):
            with self.subTest(name=name):
                candidate = self.candidate([{"name": name}])
                self.assertEqual(len(candidate["options"]), 1)
                self.assertEqual(candidate["options"][0]["fronts"], ["Rabbit"])
                resolved = precon_tokens.resolve(candidate, SOURCE, [self.choice(quantity=2)])
                self.assertEqual((len(resolved["rows"]), resolved["cards"]), (1, 2))

    def test_duplicate_face_entries_need_explicit_skip_or_count_and_are_not_merged(self):
        candidate = self.candidate([{"name": "Rabbit"}, {"name": "Rabbit"}])
        with self.assertRaises(ValueError):
            precon_tokens.resolve(candidate, SOURCE, [self.choice()])
        resolved = precon_tokens.resolve(candidate, SOURCE,
            [self.choice(source_row=2, front="", quantity=0), self.choice()])
        self.assertEqual([(item["source_row"], item["row"]["quantity"]) for item in resolved["rows"]], [(1, "1")])
        both = precon_tokens.resolve(candidate, SOURCE, [self.choice(source_row=2), self.choice()])
        self.assertEqual([item["source_row"] for item in both["rows"]], [1, 2])
        self.assertEqual(both["cards"], 2)
        self.assertEqual(len(both["rows"]), 2)

    def test_confirmed_rows_leave_every_unknown_physical_fact_blank_and_label_provenance(self):
        candidate = self.candidate([{"name": "Rabbit", "count": 3, "setCode": "TST", "number": "9", "isFoil": True},
                                    {"name": "Dinosaur"}])
        resolved = precon_tokens.resolve(candidate, SOURCE, [self.choice(quantity=2), self.choice(2, "Dinosaur", 1)])
        self.assertEqual(resolved["cards"], 3)
        self.assertEqual(resolved["problems"], [])
        for item in resolved["rows"]:
            row = item["row"]
            self.assertEqual(set(row), set(rules.TOKEN_FIELDS))
            for field in ("back", "set", "front_collector_number", "back_collector_number", "finish", "front_details", "back_details"):
                self.assertEqual(row[field], "")
            self.assertFalse(rules.token_known(row))
            self.assertIn(f"token entry {item['source_row']}", row["notes"])
            self.assertIn(f"user-confirmed physical quantity {row['quantity']}", row["notes"])
            self.assertIn("printing and reverse face unconfirmed; check physical pairing", row["notes"])
        self.assertIn("source-declared quantity 3", resolved["rows"][0]["row"]["notes"])
        self.assertIn("source physical quantity unknown", resolved["rows"][1]["row"]["notes"])

    def test_quantity_bounds_and_types_are_strict_for_user_choices(self):
        candidate = self.candidate([{"name": "Rabbit"}])
        for quantity in (None, True, False, -1, 1.5, "1", precons.MAX_COUNT + 1, {}, []):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                precon_tokens.resolve(candidate, SOURCE, [self.choice(quantity=quantity)])
        self.assertEqual(precon_tokens.resolve(candidate, SOURCE, [self.choice(quantity=precons.MAX_COUNT)])["cards"],
                         precons.MAX_COUNT)

    def test_every_source_row_is_required_once_with_exact_choice_fields(self):
        candidate = self.candidate([{"name": "Rabbit"}, {"name": "Rabbit"}])
        first, second = self.choice(), self.choice(2)
        bad = (None, {}, (), [first], [first, first], [first, self.choice(3)], [first, self.choice(True)],
               [first, self.choice("2")], [first, self.choice(2.0)], [first, None],
               [first, {"source_row": 2, "quantity": 0}], [first, {**second, "extra": True}])
        for choices in bad:
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                precon_tokens.resolve(candidate, SOURCE, choices)

    def test_positive_quantity_requires_exact_offered_front_and_zero_is_explicit_skip(self):
        candidate = self.candidate([{"name": "Rabbit // Dinosaur"}, {"name": "Rabbit"}])
        for front in ("", "rabbit", "Beast", "Rabbit // Dinosaur", None, True):
            with self.subTest(front=front), self.assertRaises(ValueError):
                precon_tokens.resolve(candidate, SOURCE, [self.choice(front=front), self.choice(2)])
        result = precon_tokens.resolve(candidate, SOURCE, [self.choice(front="", quantity=0), self.choice(2)])
        self.assertEqual([item["source_row"] for item in result["rows"]], [2])

    def test_all_zero_choices_require_opt_out_instead_of_an_empty_token_write(self):
        candidate = self.candidate([{"name": "Rabbit"}])
        with self.assertRaisesRegex(ValueError, "Leave token cards unchecked"):
            precon_tokens.resolve(candidate, SOURCE, [self.choice(front="", quantity=0)])

    def test_fatal_metadata_or_name_errors_cannot_be_confirmed_or_skipped_past(self):
        for entry in (None, {}, {"name": ""}, {"name": "Rabbit //"}, {"name": "Rabbit // Dinosaur // Beast"},
                      {"name": "Unlisted token"}, {"name": "x" * 81}, {"name": "Rabbit\n"}, {"name": ["Rabbit"]}):
            with self.subTest(entry=entry):
                candidate = self.candidate([{"name": "Rabbit", "count": 1}, entry])
                self.assertFalse(candidate["choices_ready"])
                self.assertTrue(candidate["choice_problems"])
                self.assertEqual([item["source_row"] for item in candidate["options"]], [1, 2])
                with self.assertRaises(ValueError):
                    precon_tokens.resolve(candidate, SOURCE, [self.choice(), self.choice(2, "", 0)])

    def test_absent_lists_remain_no_offer_and_malformed_lists_or_excess_entries_are_blocked(self):
        for data in ({}, {"tokens": None}, {"tokens": []}):
            self.assertEqual(precon_tokens.candidates(data, SOURCE), {"rows": [], "cards": 0, "problems": []})
        for raw in ("not a list", {}, [{"name": "Rabbit"}] * (precon_tokens.MAX_ROWS + 1)):
            candidate = self.candidate(raw)
            self.assertFalse(candidate["choices_ready"])
            self.assertTrue(candidate["choice_problems"])
        maximum = self.candidate([{"name": "Rabbit"}] * precon_tokens.MAX_ROWS)
        self.assertTrue(maximum["choices_ready"])
        self.assertEqual(len(maximum["options"]), precon_tokens.MAX_ROWS)

    def test_index_failures_and_late_resolution_errors_never_relay_private_paths(self):
        for error in (RuntimeError("private fixture path"), ValueError("private fixture path"),
                      OSError("private fixture path"), KeyError("private fixture path")):
            with self.subTest(error=type(error).__name__), mock.patch.object(names, "check_names", side_effect=error):
                candidate = self.candidate([{"name": "Rabbit", "count": 2}])
                self.assertFalse(candidate["choices_ready"])
                self.assertNotIn("private fixture path", str(candidate))
                self.assertIn("cannot be checked", candidate["choice_problems"][0]["message"])
        candidate = self.candidate([{"name": "Rabbit"}])
        with mock.patch.object(names, "check_names", side_effect=ValueError("private fixture path")):
            with self.assertRaises(ValueError) as caught:
                precon_tokens.resolve(candidate, SOURCE, [self.choice()])
        self.assertNotIn("private fixture path", str(caught.exception))
        with mock.patch.object(names, "_ready", return_value=False):
            self.assertFalse(self.candidate([{"name": "Rabbit"}])["choices_ready"])

    def test_source_receipt_binds_unknown_entries_file_order_and_ignored_raw_provenance(self):
        entries = [{"name": "Rabbit"}, {"name": "Dinosaur", "count": 2}]
        candidate = self.candidate(entries)
        digest = precon_tokens.source_sha256(candidate)
        variants = ((entries, "Different_TST"), (list(reversed(entries)), SOURCE),
                    ([{"name": "Rabbit", "count": 1}, entries[1]], SOURCE),
                    ([{"name": "Rabbit", "faceName": "Rabbit"}, entries[1]], SOURCE),
                    ([{"name": "Rabbit", "uuid": "changed-public-source"}, entries[1]], SOURCE))
        for raw, source in variants:
            with self.subTest(raw=raw, source=source):
                self.assertNotEqual(precon_tokens.source_sha256(self.candidate(raw, source)), digest)
        self.assertEqual(precon_tokens.source_sha256(self.candidate(copy.deepcopy(entries))), digest)

    def test_resolution_preserves_source_receipt_and_never_mutates_source_or_candidate(self):
        entries = [{"name": "Rabbit // Dinosaur", "count": 2}]
        original = copy.deepcopy(entries)
        candidate = self.candidate(entries)
        before = copy.deepcopy(candidate)
        resolved = precon_tokens.resolve(candidate, SOURCE, [self.choice(front="Dinosaur")])
        self.assertEqual(candidate, before)
        self.assertEqual(entries, original)
        self.assertEqual(precon_tokens.source_sha256(candidate), precon_tokens.source_sha256(resolved))
        with self.assertRaises(ValueError):
            precon_tokens.resolve(candidate, "Different_TST", [self.choice()])
