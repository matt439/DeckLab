"""Bounded optional evidence; pure validation uses no database or photos."""
import copy
import unittest

from decklab.lib.state import Invalid
from decklab.lib.state.pg_collection_batches import content
from decklab.tests.test_collection_batch_inventory import VALUE


def value_with_evidence(ambiguous=True):
    value = copy.deepcopy(VALUE)
    candidate = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
                 "finishes": ["nonfoil", "foil"], "how": "name", "language": ""}
    value["unresolved"] = ["Unresolved scan 7"] if ambiguous else []
    value["evidence"] = {"version": 1, "next_scan_id": 8,
                         "provenance": [{"input_index": 0, "row_index": 0, "quantity": 3,
                                         "origin": "not recorded by existing pending state", "choices": [candidate]}],
                         "ambiguities": [{"source_id": 7, "label": "Unresolved scan 7", "language": "",
                                          "proposals": [copy.deepcopy(candidate)]}] if ambiguous else []}
    return value


class EvidenceTests(unittest.TestCase):
    def test_old_payload_unchanged_and_new_evidence_detached(self):
        self.assertEqual(content(VALUE), VALUE)
        value = value_with_evidence()
        saved = content(value)
        value["evidence"]["ambiguities"][0]["proposals"][0]["name"] = "Changed"
        self.assertEqual(saved["evidence"]["ambiguities"][0]["proposals"][0]["name"], "Llanowar Elves")

    def test_photos_ocr_unknown_provenance_and_bad_counts_refused(self):
        for target in ("root", "source", "candidate", "ambiguity"):
            value = value_with_evidence()
            evidence = value["evidence"]
            node = {"root": evidence, "source": evidence["provenance"][0],
                    "candidate": evidence["ambiguities"][0]["proposals"][0], "ambiguity": evidence["ambiguities"][0]}[target]
            node["photo"] = "not retained"
            with self.assertRaises(Invalid):
                content(value)
        for field, invalid in (("quantity", 2), ("row_index", 1), ("input_index", True), ("origin", "assumed scan")):
            value = value_with_evidence()
            value["evidence"]["provenance"][0][field] = invalid
            with self.assertRaises(Invalid):
                content(value)

    def test_ids_labels_versions_and_size_fail_closed(self):
        for key, invalid in (("next_scan_id", 7), ("version", True), ("version", 2)):
            value = value_with_evidence()
            value["evidence"][key] = invalid
            with self.assertRaises(Invalid):
                content(value)
        value = value_with_evidence()
        value["unresolved"] = []
        with self.assertRaises(Invalid):
            content(value)
        value = value_with_evidence()
        value["evidence"]["provenance"][0]["choices"] = [{"name": "x" * 160, "set_name": "x" * 160}] * 200
        with self.assertRaises(Invalid):
            content(value)
