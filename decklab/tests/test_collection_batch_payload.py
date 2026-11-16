"""Pure fixture checks for production batch metadata validation."""
import copy
import unittest

from decklab.lib.state import Invalid
from decklab.lib.state.pg_collection_batches import content
from decklab.tests.test_collection_batch_postgres import VALUE


class PayloadTests(unittest.TestCase):
    def test_detached_absolute_count(self):
        value = copy.deepcopy(VALUE)
        saved = content(value)
        value["rows"][0]["quantity"] = 9
        self.assertEqual(saved["rows"][0]["quantity"], 3)

    def test_no_blob_or_unknown_metadata(self):
        for key in ("photo", "ocr", "paid", "other"):
            value = copy.deepcopy(VALUE)
            value["rows"][0][key] = "not allowed"
            with self.assertRaises(Invalid):
                content(value)

    def test_count_bounds_and_types(self):
        for quantity in (True, 0, -1, 10000, 1.2, "2"):
            value = copy.deepcopy(VALUE)
            value["rows"][0]["quantity"] = quantity
            with self.assertRaises(Invalid):
                content(value)

    def test_repeat_same_metadata_groups_must_combine(self):
        value = copy.deepcopy(VALUE)
        value["rows"].append(copy.deepcopy(value["rows"][0]))
        with self.assertRaises(Invalid):
            content(value)

    def test_batch_and_ambiguity_bounds(self):
        for field, over in (("label", "x" * 81), ("rows", [{}] * 201),
                            ("unresolved", ["x"] * 31), ("unresolved", ["x" * 161])):
            value = copy.deepcopy(VALUE)
            value[field] = over
            with self.assertRaises(Invalid):
                content(value)

    def test_distinct_metadata_and_unknown_groups_stay_separate(self):
        value = copy.deepcopy(VALUE)
        base = value["rows"][0]
        value["rows"] = [{**base, "condition": condition, "language": language}
                         for condition, language in (("NM", "en"), ("LP", "en"), ("NM", "ja"), ("", ""))]
        self.assertEqual(content(value), value)
        value["rows"].append(copy.deepcopy(value["rows"][-1]))
        with self.assertRaises(Invalid):
            content(value)
