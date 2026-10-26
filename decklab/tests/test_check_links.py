"""Pure explicit check-to-row proofs; no inventory backend or data access."""
import copy
import hashlib
import json
import unittest

from decklab.lib.inventory import check_links, rules
from decklab.lib.inventory.model import Component
from decklab.lib.state import Invalid


FIELDS = tuple(rules.FIELDS)
ROWS = [dict(zip(FIELDS, ("Llanowar Elves", "fdn", "227", "nonfoil", "2", "", "", ""))),
        dict(zip(FIELDS, ("Elvish Mystic", "m15", "173", "nonfoil", "1", "LP", "en", "Keep this note")))]


def component(checks=("Inspect printing", "Inspect printing"), metadata=None, *, kind="cards", status="pending"):
    data = Component.build("cards", kind, "fixture.csv", status=status, checks=checks).record()
    if metadata is not None:
        data["check_links"] = copy.deepcopy(metadata)
    return Component(data)


def target(row=1, rows=ROWS):
    return {"row": row, "payload_sha256": check_links.digest(rows, FIELDS)}


def link(check=1, row=1, *, checks=("Inspect printing", "Inspect printing"), rows=ROWS):
    return {"check": check, "text": checks[check - 1], "payload_sha256": check_links.digest(rows, FIELDS),
            "row": row, "row_sha256": check_links.row_digest(rows[row - 1], FIELDS)}


def metadata(*links):
    return {"version": 1, "links": list(links)}


class CheckLinkTests(unittest.TestCase):
    def test_digest_is_canonical_full_text_and_ordered_without_input_mutation(self):
        rows = copy.deepcopy(ROWS)
        expected = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(check_links.digest(rows, FIELDS), expected)
        self.assertEqual(check_links.digest([dict(reversed(list(row.items()))) for row in rows], FIELDS), expected)
        self.assertNotEqual(check_links.digest(list(reversed(rows)), FIELDS), expected)
        changed = copy.deepcopy(rows)
        changed[1]["notes"] += "!"
        self.assertNotEqual(check_links.digest(changed, FIELDS), expected)
        self.assertEqual(rows, ROWS)

    def test_digest_requires_every_field_as_text(self):
        for row in ({key: value for key, value in ROWS[0].items() if key != "notes"},
                    ROWS[0] | {"future": "field"}, ROWS[0] | {"quantity": 2}, ROWS[0] | {"notes": None}):
            with self.subTest(row=row), self.assertRaises(ValueError):
                check_links.digest([row], FIELDS)
        for fields in (None, "name", (), ("name", "name")):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                check_links.digest([], fields)

    def test_duplicate_texts_are_attached_by_explicit_check_index(self):
        item = component(metadata=metadata(link(2, 2)))
        self.assertEqual(check_links.project(item, ROWS, FIELDS),
                         [None, {"row": 2, "row_sha256": check_links.row_digest(ROWS[1], FIELDS)}])

    def test_same_names_and_duplicate_full_rows_keep_the_explicit_row_number(self):
        for rows in ([ROWS[0], {**ROWS[0], "set": "m15", "collector_number": "195"}],
                     [ROWS[0], dict(ROWS[0])]):
            item = component(metadata=metadata(link(2, 2, rows=rows)))
            with self.subTest(rows=rows):
                self.assertEqual(check_links.project(item, rows, FIELDS),
                                 [None, {"row": 2, "row_sha256": check_links.row_digest(rows[1], FIELDS)}])

    def test_general_legacy_or_similar_named_checks_do_not_infer_any_row(self):
        for checks in (("Check Llanowar Elves condition",), ("Elvish Mystic",), ("Inspect every card",)):
            with self.subTest(checks=checks):
                self.assertEqual(check_links.project(component(checks), ROWS, FIELDS), [None])

    def test_whole_payload_changes_and_reordering_invalidate_placement(self):
        item = component(metadata=metadata(link(1, 1)))
        changed = copy.deepcopy(ROWS)
        changed[1]["notes"] += " corrected"
        for rows in (changed, list(reversed(ROWS)), ROWS[:1], ROWS + [dict(ROWS[0])]):
            with self.subTest(rows=rows):
                self.assertEqual(check_links.project(item, rows, FIELDS), [None, None])

    def test_stale_row_hash_is_not_made_current_by_a_matching_payload_hash(self):
        bad = link(1, 1) | {"row_sha256": "0" * 64}
        item = component(metadata=metadata(bad, link(2, 2)))
        self.assertEqual(check_links.project(item, ROWS, FIELDS),
                         [None, {"row": 2, "row_sha256": check_links.row_digest(ROWS[1], FIELDS)}])

    def test_malformed_or_future_metadata_invalidates_every_entry(self):
        good = link(1, 1)
        bad_metadata = [[], "private raw text", {"version": 2, "links": [good]},
                        {"version": True, "links": [good]}, metadata(good) | {"future": 1},
                        {"version": 1, "links": {}}, metadata(good, good), metadata(good | {"extra": "x"})]
        for change in ({"check": True}, {"check": 0}, {"check": 3}, {"text": "Other text"},
                       {"row": True}, {"row": 0}, {"payload_sha256": "A" * 64},
                       {"row_sha256": "x" * 64}, {"row_sha256": None}):
            bad_metadata.append(metadata(good, link(2, 2) | change))
        bad_metadata.append(metadata(*(good | {"check": number} for number in range(1, 102))))
        for saved in bad_metadata:
            with self.subTest(saved=saved):
                self.assertEqual(check_links.project(component(metadata=saved), ROWS, FIELDS), [None, None])

    def test_product_received_cancelled_and_unreadable_payloads_never_project(self):
        for kind, status in (("product", "pending"), ("cards", "received"), ("tokens", "cancelled")):
            with self.subTest(kind=kind, status=status):
                self.assertEqual(check_links.project(component(metadata=metadata(link()), kind=kind, status=status),
                                                     ROWS, FIELDS), [None, None])
        self.assertEqual(check_links.project(component(metadata=metadata(link())), [{"name": "cut off"}], FIELDS),
                         [None, None])

    def test_append_computes_proof_for_the_explicit_new_check_without_mutating_inputs(self):
        item = component(metadata=metadata(link(2, 2)))
        original, rows, selected = copy.deepcopy(item.record()), copy.deepcopy(ROWS), target()
        selected_before = dict(selected)
        saved = check_links.append(item, rows, FIELDS, "Inspect printing", selected)
        self.assertEqual(saved, metadata(link(2, 2), link(3, 1, checks=(*item.checks, "Inspect printing"))))
        self.assertEqual((item.record(), rows, selected), (original, ROWS, selected_before))
        self.assertEqual(check_links.project(component((*item.checks, "Inspect printing"), saved), rows, FIELDS)[2],
                         {"row": 1, "row_sha256": check_links.row_digest(ROWS[0], FIELDS)})

    def test_append_general_check_retains_only_current_old_links(self):
        item = component(metadata=metadata(link(1, 1) | {"row_sha256": "0" * 64}, link(2, 2)))
        self.assertEqual(check_links.append(item, ROWS, FIELDS, "General check"), metadata(link(2, 2)))
        self.assertIsNone(check_links.append(component(), ROWS, FIELDS, "Llanowar Elves condition"))
        self.assertIsNone(check_links.append(component(metadata={"version": 99}), ROWS, FIELDS, "General check"))

    def test_append_rejects_stale_ambiguous_or_wrong_kind_targets_with_static_errors(self):
        invalid = [{}, {"row": 1}, target() | {"extra": "x"}, target() | {"row": True},
                   target() | {"row": "1"}, target(0), target(3), target() | {"payload_sha256": "A" * 64},
                   target() | {"payload_sha256": "0" * 64}, [], "private target"]
        for selected in invalid:
            with self.subTest(selected=selected), self.assertRaises(Invalid) as caught:
                check_links.append(component(), ROWS, FIELDS, "Check", selected)
            self.assertEqual(str(caught.exception), check_links._INVALID)
        for kind, status in (("product", "pending"), ("cards", "received")):
            with self.subTest(kind=kind, status=status), self.assertRaises(Invalid):
                check_links.append(component(kind=kind, status=status), ROWS, FIELDS, "Check", target())
        with self.assertRaises(Invalid) as caught:
            check_links.append(component(), [{"name": "private cut-off row"}], FIELDS, "Check", target())
        self.assertEqual(str(caught.exception), check_links._INVALID)
        for text in ("", "  ", None, 1):
            with self.subTest(text=text), self.assertRaises(Invalid):
                check_links.append(component(), ROWS, FIELDS, text)

    def test_token_payload_proofs_preserve_every_face_and_metadata_value(self):
        fields = tuple(rules.TOKEN_FIELDS)
        rows = [{**{key: "" for key in fields}, "front": "Angel", "back": "The Monarch", "quantity": "2",
                 "notes": "Paired faces verified"}]
        item = component(("Inspect pairing",), kind="tokens")
        saved = check_links.append(item, rows, fields, "Check reverse", {"row": 1,
                                    "payload_sha256": check_links.digest(rows, fields)})
        self.assertEqual(check_links.project(component((*item.checks, "Check reverse"), saved, kind="tokens"), rows, fields),
                         [None, {"row": 1, "row_sha256": check_links.row_digest(rows[0], fields)}])
        changed = [{**rows[0], "back": "Treasure"}]
        self.assertEqual(check_links.project(component((*item.checks, "Check reverse"), saved, kind="tokens"), changed, fields),
                         [None, None])

    def test_one_hundred_unique_links_are_supported_and_the_next_is_refused(self):
        checks = tuple("Inspect printing" for _ in range(100))
        saved = metadata(*(link(number, 1, checks=checks) for number in range(1, 101)))
        item = component(checks, saved)
        self.assertEqual(sum(value is not None for value in check_links.project(item, ROWS, FIELDS)), 100)
        self.assertEqual(check_links.append(item, ROWS, FIELDS, "General check"), saved)
        with self.assertRaisesRegex(Invalid, "At most 100"):
            check_links.append(item, ROWS, FIELDS, "Linked check", target())

    def test_withdrawal_removes_the_exact_duplicate_and_shifts_later_links(self):
        checks = ("Duplicate", "Duplicate", "Final")
        item = component(checks, metadata(link(1, 1, checks=checks), link(2, 2, checks=checks), link(3, 1, checks=checks)))
        original = copy.deepcopy(item.record())
        saved = check_links.remap(item, ["Duplicate", "Final"], removedindex=1)
        self.assertEqual(saved, metadata(link(1, 2, checks=("Duplicate", "Final")),
                                         link(2, 1, checks=("Duplicate", "Final"))))
        self.assertEqual(item.record(), original)
        self.assertNotEqual(saved, check_links.remap(item, ["Duplicate", "Final"], removedindex=2))

    def test_clear_or_unrelated_check_changes_drop_proof_without_inference(self):
        item = component(metadata=metadata(link(1, 1), link(2, 2)))
        for changed, removed in (([], None), (["Inspect printing"], None), (["Other", "Inspect printing"], None),
                                 (["Inspect printing"], True), (["Inspect printing"], 3), (["Other"], 1)):
            with self.subTest(changed=changed, removed=removed):
                self.assertIsNone(check_links.remap(item, changed, removed))
        self.assertEqual(check_links.remap(item, list(item.checks)), item.data["check_links"])
        self.assertIsNone(check_links.remap(component(metadata={"version": 2}), ["Inspect printing"], 1))


if __name__ == "__main__":
    unittest.main()
