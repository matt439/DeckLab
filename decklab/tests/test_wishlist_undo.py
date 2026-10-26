"""Pure wishlist UPDATE Undo proof and saved-receipt tests, with no store or I/O.

Wishlist privacy follows the profile, including two profiles sharing home. All
raw rows and globally unfiltered audit replies here are explicit test values.
"""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import cards, inventory, state
from decklab.lib.state import rules
from decklab.lib.state import wishlist_undo as undo


CHANGE_ID = 17
ROW_ID = 101
OWNER_VERSION = 109
NEW_ROW_ID = 110
PROFILE = "matt"


def raw(name="Opt", position=4, **extra):
    return {"profile_id": PROFILE, "position": position, "name": name, "set_code": None,
            "collector_number": None, "notes": "Current note", "source": "Current source", **extra}


def dto(row):
    return {"name": row["name"], "set": row["set_code"] or "", "number": row["collector_number"] or "",
            "notes": row["notes"], "source": row["source"]}


class WishlistUndoTests(unittest.TestCase):
    def setUp(self):
        self.seed()

    def seed(self):
        current = raw()
        restored = current | {"notes": "Original note", "source": "Original source"}
        self.source_rows = [{"id": ROW_ID, "table": "wishlist_entry", "op": "UPDATE",
                             "key": {"profile_id": PROFILE, "position": 4},
                             "before": restored, "after": copy.deepcopy(current)}]
        self.raw_entries = [raw("Forest", 0, notes="Keep first", source=""), current,
                            raw("Island", 9, notes="Keep last", source="")]
        self.latest_target, self.latest_owner = ROW_ID, OWNER_VERSION
        return self.source_rows

    def source(self):
        return self.source_rows[0]

    def review(self, **overrides):
        return undo.review(**{"change_id": CHANGE_ID, "pid": PROFILE, "source_rows": self.source_rows,
                              "raw_entries": self.raw_entries, "latest_target": self.latest_target,
                              "latest_owner": self.latest_owner, **overrides})

    @staticmethod
    def expected_raw(plan):
        return copy.deepcopy(plan["raw_after"])

    @staticmethod
    def actual_source(plan, id=NEW_ROW_ID):
        return [{"id": id, "table": "wishlist_entry", "op": "UPDATE",
                 "key": {"profile_id": plan["profile"], "position": plan["raw_current"]["position"]},
                 "before": copy.deepcopy(plan["raw_current"]), "after": copy.deepcopy(plan["raw_restore"])}]

    def saved(self, plan=None, **overrides):
        plan = self.review() if plan is None else plan
        return undo.receipt(**{"plan": plan, "actual_raw_entries": self.expected_raw(plan),
                               "actual_new_source_rows": self.actual_source(plan), "latest_owner": NEW_ROW_ID,
                               **overrides})

    def test_review_proves_exact_single_own_profile_row_and_preserves_all_inputs(self):
        inputs = copy.deepcopy((self.source_rows, self.raw_entries))
        plan = self.review()
        self.assertEqual((plan["change_id"], plan["profile"], plan["row_change_id"], plan["latest_owner"]),
                         (CHANGE_ID, PROFILE, ROW_ID, OWNER_VERSION))
        self.assertTrue(isinstance(plan["label"], str) and plan["label"].strip())
        self.assertEqual(plan["current"], dto(self.source()["after"]))
        self.assertEqual(plan["restored"], dto(self.source()["before"]))
        self.assertEqual(plan["fields"], [{"field": "notes", "before": "Current note", "after": "Original note"},
                                          {"field": "source", "before": "Current source", "after": "Original source"}])
        self.assertEqual(plan["raw_current"], self.source()["after"])
        self.assertEqual(plan["raw_restore"], self.source()["before"])
        expected = copy.deepcopy(self.raw_entries)
        expected[1] = copy.deepcopy(self.source()["before"])
        self.assertEqual(plan["raw_after"], expected)
        self.assertEqual(plan["sha256"], undo.list_sha(expected))
        self.assertRegex(plan["expect"], r"^[a-f0-9]{64}$")
        self.assertEqual((self.source_rows, self.raw_entries), inputs)

    def test_notes_only_or_source_only_lists_only_the_changed_field(self):
        for field in ("notes", "source"):
            self.seed()
            self.source()["before"] = copy.deepcopy(self.source()["after"])
            self.source()["before"][field] = "Original " + field
            with self.subTest(field=field):
                plan = self.review()
                self.assertEqual(plan["fields"], [{"field": field, "before": self.source()["after"][field],
                                                   "after": self.source()["before"][field]}])
                self.assertEqual(self.saved(plan)["restored"], dto(self.source()["before"]))

    def test_sql_null_printing_and_real_printing_roundtrip_without_normalization(self):
        for set_code, number in ((None, None), ("fdn", "227")):
            self.seed()
            for row in (self.source()["before"], self.source()["after"], self.raw_entries[1]):
                row.update(set_code=set_code, collector_number=number)
            with self.subTest(set=set_code):
                plan = self.review()
                self.assertEqual((plan["current"]["set"], plan["current"]["number"]), (set_code or "", number or ""))
                self.assertEqual((plan["raw_restore"]["set_code"], plan["raw_restore"]["collector_number"]), (set_code, number))
                self.assertEqual(self.saved(plan)["restored"], plan["restored"])

    def test_valid_notes_whitespace_linebreaks_tabs_quotes_and_unicode_stay_exact(self):
        notes = '  First, "gift"; repeated; repeated\r\nNext\tline - caf\u00e9 <b>literal</b>  '
        self.source()["before"].update(notes=notes, source="  Original source \u2014 caf\u00e9  ")
        plan = self.review()
        self.assertEqual(plan["restored"]["notes"], notes)
        result = self.saved(plan)
        self.assertEqual(result["restored"], dto(self.source()["before"]))

    def test_empty_metadata_and_maximum_lengths_restore_exactly(self):
        for notes, source in (("", ""), ("n" * rules.MAX_NOTES, "s" * rules.MAX_SOURCE)):
            self.source()["before"].update(notes=notes, source=source)
            with self.subTest(lengths=(len(notes), len(source))):
                plan = self.review()
                self.assertEqual(self.saved(plan)["restored"], plan["restored"])

    def test_nontext_overlong_or_disallowed_control_metadata_is_unsupported(self):
        cases = [("notes", value) for value in (None, 1, True, [], {}, "a\0b", "bell\x07", "delete\x7f", "x" * 2001)]
        cases += [("source", value) for value in (None, 1, "two\nlines", "a\tb", "s" * 301)]
        for field, value in cases:
            self.seed()
            self.source()["before"][field] = value
            with self.subTest(field=field, type=type(value).__name__), self.assertRaises(undo.UndoUnsupported):
                self.review()

    def test_name_position_owner_and_nonupdate_changes_remain_excluded(self):
        for changed in ({"name": "Another name"}, {"position": 3}):
            self.seed()
            self.source()["before"].update(changed)
            with self.subTest(changed=changed), self.assertRaises(undo.UndoUnsupported):
                self.review()
        self.seed()
        self.source()["before"]["profile_id"] = "user1"
        with self.assertRaises(undo.UndoMissing):
            self.review()
        for op, missing in (("INSERT", "before"), ("DELETE", "after")):
            self.seed()
            self.source()["op"], self.source()[missing] = op, None
            with self.subTest(op=op), self.assertRaises(undo.UndoMissing):
                self.review()

    def test_added_printing_preference_can_be_undone_to_sql_null_pair(self):
        self.source()["before"] = copy.deepcopy(self.source()["after"])
        for row in (self.source()["after"], self.raw_entries[1]):
            row.update(set_code="fdn", collector_number="227")
        before = copy.deepcopy((self.source_rows, self.raw_entries))
        plan = self.review()
        self.assertEqual(plan["fields"], [{"field": "set", "before": "fdn", "after": ""},
                                          {"field": "number", "before": "227", "after": ""}])
        self.assertEqual((plan["raw_restore"]["set_code"], plan["raw_restore"]["collector_number"]), (None, None))
        self.assertEqual(self.saved(plan)["restored"], dto(self.source()["before"]))
        self.assertEqual(plan["raw_after"][0], self.raw_entries[0])
        self.assertEqual(plan["raw_after"][2], self.raw_entries[2])
        self.assertEqual((self.source_rows, self.raw_entries), before)

    def test_cleared_printing_preference_restores_exact_historical_pair(self):
        self.source()["before"] = copy.deepcopy(self.source()["after"])
        self.source()["before"].update(set_code="fdn", collector_number="227")
        plan = self.review()
        self.assertEqual(plan["fields"], [{"field": "set", "before": "", "after": "fdn"},
                                          {"field": "number", "before": "", "after": "227"}])
        self.assertEqual((plan["raw_current"]["set_code"], plan["raw_current"]["collector_number"]), (None, None))
        self.assertEqual((plan["restored"]["set"], plan["restored"]["number"]), ("fdn", "227"))
        result = self.saved(plan)
        self.assertEqual(result["restored"], dto(self.source()["before"]))
        self.assertEqual(result["sha256"], undo.list_sha(plan["raw_after"]))
        self.assertEqual(result["revision"], str(NEW_ROW_ID))

    def test_replaced_unknown_historical_printing_and_metadata_restore_without_card_index(self):
        self.source()["before"].update(set_code="zzold", collector_number="007a",
                                        notes="  Old note\r\nsecond\tline  ", source="  Old source  ")
        for row in (self.source()["after"], self.raw_entries[1]):
            row.update(set_code="future7", collector_number="A-19")
        inputs = copy.deepcopy((self.source_rows, self.raw_entries))
        with mock.patch.object(cards, "resolve", side_effect=AssertionError("No card index lookup")), \
                mock.patch.object(cards, "printing", side_effect=AssertionError("No printing lookup")), \
                mock.patch.object(cards, "printing_card", side_effect=AssertionError("No printing card lookup")), \
                mock.patch.object(inventory, "current", side_effect=AssertionError("No inventory lookup")):
            plan = self.review()
            result = self.saved(plan)
        self.assertEqual(plan["fields"], [{"field": field, "before": dto(self.source()["after"])[field],
                                           "after": dto(self.source()["before"])[field]}
                                          for field in ("set", "number", "notes", "source")])
        self.assertEqual(result["restored"], dto(self.source()["before"]))
        self.assertEqual(plan["raw_after"][1], self.source()["before"])
        self.assertEqual((self.source_rows, self.raw_entries), inputs)

    def test_malformed_halfpair_types_controls_and_nonexact_raw_printing_still_refuse(self):
        invalid = (("", ""), (None, "227"), ("fdn", None), ("fdn", ""), ("", "227"),
                   ("FDN", "227"), (" fdn", "227"), (False, None), (None, False),
                   (1, "227"), ("fdn", 227), ([], None), (None, {}),
                   ("fdn", "227\0"), ("fdn", "two\nlines"), ("fdn", "x" * 17))
        for side in ("before", "after"):
            for set_code, number in invalid:
                self.seed()
                self.source()[side].update(set_code=set_code, collector_number=number)
                if side == "after":
                    self.raw_entries[1].update(set_code=set_code, collector_number=number)
                with self.subTest(side=side, printing=(set_code, number)), self.assertRaises(undo.UndoUnsupported):
                    self.review()

    def test_a_noop_source_is_not_an_undoable_update(self):
        self.source()["before"] = copy.deepcopy(self.source()["after"])
        with self.assertRaises(undo.UndoUnsupported):
            self.review()

    def test_global_missing_hidden_and_mixed_sources_share_one_generic_refusal_before_validation(self):
        sources = [[], None, [None], [self.source(), copy.deepcopy(self.source())]]
        hidden = copy.deepcopy(self.source())
        hidden["before"]["profile_id"] = hidden["after"]["profile_id"] = "user1"
        hidden["before"]["notes"] = "Hidden household wishlist note"
        malformed_own = copy.deepcopy(self.source())
        malformed_own["before"]["unsupported_schema"] = "Own detail"
        sources += [[hidden], [malformed_own, hidden], [{**self.source(), "table": "profile_setting"}]]
        messages = []
        for source_rows in sources:
            with self.subTest(source=source_rows), mock.patch.object(rules, "entry", side_effect=AssertionError("private entry validated")), \
                    self.assertRaises(undo.UndoMissing) as caught:
                self.review(source_rows=source_rows)
            messages.append(str(caught.exception))
        self.assertEqual(len(set(messages)), 1)
        self.assertNotIn("Hidden household wishlist", messages[0])
        self.assertNotIn("user1", messages[0])

    def test_raw_source_requires_exact_schema_key_types_and_update_operation(self):
        for mode in ("missing-field", "extra-field", "bad-key", "float-key", "boolean-key", "boolean-position", "negative-position", "bad-id", "insert", "delete"):
            self.seed()
            row = self.source()
            if mode == "missing-field":
                del row["before"]["source"]
            elif mode == "extra-field":
                row["after"]["future"] = "Unsupported"
            elif mode == "bad-key":
                row["key"]["position"] = 9
            elif mode == "float-key":
                row["key"]["position"] = 4.0
            elif mode == "boolean-key":
                row["before"]["position"] = row["after"]["position"] = self.raw_entries[1]["position"] = 1
                row["key"]["position"] = True
            elif mode in ("boolean-position", "negative-position"):
                value = True if mode == "boolean-position" else -1
                row["before"]["position"] = row["after"]["position"] = row["key"]["position"] = value
            elif mode == "bad-id":
                row["id"] = True
            elif mode == "insert":
                row["op"], row["before"] = "INSERT", None
            else:
                row["op"], row["after"] = "DELETE", None
            with self.subTest(mode=mode), self.assertRaises((undo.UndoMissing, undo.UndoUnsupported)):
                self.review()

    def test_current_full_raw_row_must_match_at_its_original_position(self):
        for mode in ("notes", "source", "printing", "position", "missing"):
            self.seed()
            if mode == "missing":
                self.raw_entries.pop(1)
            elif mode == "position":
                self.raw_entries[1]["position"] = 5
            elif mode == "printing":
                self.raw_entries[1].update(set_code="fdn", collector_number="227")
            else:
                self.raw_entries[1][mode] = "Changed after source"
            with self.subTest(mode=mode), self.assertRaises(undo.UndoConflict):
                self.review()

    def test_current_layout_is_ordered_unambiguous_and_entirely_owned(self):
        for mode in ("duplicate-position", "duplicate-name", "reordered", "boolean-position", "foreign-owner", "missing-field"):
            self.seed()
            if mode == "duplicate-position":
                self.raw_entries[-1]["position"] = 4
            elif mode == "duplicate-name":
                self.raw_entries[-1]["name"] = "OPT"
            elif mode == "reordered":
                self.raw_entries.reverse()
            elif mode == "boolean-position":
                self.raw_entries[0]["position"] = False
            elif mode == "foreign-owner":
                self.raw_entries[-1]["profile_id"] = "user1"
            else:
                del self.raw_entries[0]["notes"]
            error = (undo.UndoConflict, undo.UndoUnsupported) if mode in ("boolean-position", "foreign-owner", "missing-field") else undo.UndoConflict
            with self.subTest(mode=mode), self.assertRaises(error):
                self.review()

    def test_latest_target_audit_proof_blocks_same_value_aba(self):
        for latest in (ROW_ID + 2, None, False, str(ROW_ID)):
            with self.subTest(latest=latest), self.assertRaises(undo.UndoConflict):
                self.review(latest_target=latest)

    def test_owner_version_full_list_and_source_change_id_bind_the_opaque_receipt(self):
        plan = self.review()
        self.assertNotEqual(self.review(latest_owner=OWNER_VERSION + 1)["expect"], plan["expect"])
        self.raw_entries[0]["notes"] = "Another own entry changed"
        self.assertNotEqual(self.review()["expect"], plan["expect"])
        self.seed()
        self.assertNotEqual(self.review(change_id=CHANGE_ID + 1)["expect"], plan["expect"])
        for latest in (None, False, "109", ROW_ID - 1):
            with self.subTest(latest=latest), self.assertRaises(undo.UndoConflict):
                self.review(latest_owner=latest)

    def test_list_sha_is_canonical_and_covers_every_field_and_the_ordered_layout(self):
        before = copy.deepcopy(self.raw_entries)
        sha = undo.list_sha(self.raw_entries)
        self.assertRegex(sha, r"^[a-f0-9]{64}$")
        self.assertEqual(undo.list_sha([dict(reversed(list(row.items()))) for row in self.raw_entries]), sha)
        self.assertNotEqual(undo.list_sha(list(reversed(self.raw_entries))), sha)
        for field, value in (("notes", "Different"), ("source", "Different"), ("position", 1),
                             ("set_code", "fdn"), ("name", "Plains")):
            changed = copy.deepcopy(self.raw_entries)
            changed[0][field] = value
            with self.subTest(field=field):
                self.assertNotEqual(undo.list_sha(changed), sha)
        self.assertEqual(self.raw_entries, before)

    def test_saved_receipt_exposes_only_actual_dto_hash_and_decimal_owner_revision(self):
        plan = self.review()
        original = copy.deepcopy((plan, self.source_rows, self.raw_entries))
        result = self.saved(plan)
        self.assertEqual(set(result), {"restored", "sha256", "revision"})
        self.assertEqual(result["restored"], plan["restored"])
        self.assertEqual(result["sha256"], undo.list_sha(plan["raw_after"]))
        self.assertEqual(result["revision"], str(NEW_ROW_ID))
        self.assertNotIn("profile_id", json.dumps(result))
        self.assertNotIn("position", result["restored"])
        self.assertEqual((plan, self.source_rows, self.raw_entries), original)

    def test_saved_receipt_requires_one_fresh_exact_own_update_and_no_mixed_audit_rows(self):
        plan = self.review()
        for mode in ("missing", "extra", "table", "operation", "key", "float-key", "owner", "before", "after",
                     "before-position", "after-position", "old-id", "boolean-id"):
            rows = self.actual_source(plan)
            if mode == "missing":
                rows = []
            elif mode == "extra":
                rows += [{"id": NEW_ROW_ID + 1, "table": "profile_setting", "op": "UPDATE", "key": {}, "before": {}, "after": {}}]
            elif mode == "table":
                rows[0]["table"] = "profile_setting"
            elif mode == "operation":
                rows[0]["op"] = "INSERT"
            elif mode == "key":
                rows[0]["key"]["position"] = 0
            elif mode == "float-key":
                rows[0]["key"]["position"] = 4.0
            elif mode == "owner":
                rows[0]["after"]["profile_id"] = "user1"
            elif mode in ("before", "after"):
                rows[0][mode]["notes"] += " changed"
            elif mode.endswith("-position"):
                rows[0][mode.removesuffix("-position")]["position"] = 4.0
            else:
                rows[0]["id"] = ROW_ID if mode == "old-id" else True
            with self.subTest(mode=mode), self.assertRaises(undo.UndoConflict):
                self.saved(plan, actual_new_source_rows=rows)

    def test_saved_receipt_requires_exact_complete_actual_list_including_untouched_entries(self):
        plan = self.review()
        for mode in ("target", "other", "missing", "added", "order", "printing"):
            rows = self.expected_raw(plan)
            if mode == "target":
                rows[1]["notes"] += " changed"
            elif mode == "other":
                rows[0]["source"] = "Unexpected other-entry change"
            elif mode == "missing":
                rows.pop(0)
            elif mode == "added":
                rows.append(raw("Plains", 12))
            elif mode == "order":
                rows.reverse()
            else:
                rows[1].update(set_code="fdn", collector_number="227")
            with self.subTest(mode=mode), self.assertRaises(undo.UndoConflict):
                self.saved(plan, actual_raw_entries=rows)

    def test_saved_owner_version_must_be_the_only_new_audit_row_and_strictly_newer(self):
        plan = self.review()
        for version in (None, True, 0, str(NEW_ROW_ID), float(NEW_ROW_ID), OWNER_VERSION, NEW_ROW_ID + 1):
            with self.subTest(version=version), self.assertRaises(undo.UndoConflict):
                self.saved(plan, latest_owner=version)
        with self.assertRaises(undo.UndoConflict):
            self.saved(plan, actual_new_source_rows=self.actual_source(plan, OWNER_VERSION), latest_owner=OWNER_VERSION)

    def test_kernel_needs_no_inventory_store_card_index_or_external_lookup(self):
        with mock.patch.object(inventory, "current", side_effect=AssertionError("inventory read")), \
                mock.patch.object(state, "store", side_effect=AssertionError("state store read")), \
                mock.patch.object(cards, "resolve", side_effect=AssertionError("card lookup")), \
                mock.patch.object(cards, "printing", side_effect=AssertionError("printing lookup")), \
                mock.patch.object(cards, "printing_card", side_effect=AssertionError("printing lookup")), \
                mock.patch.object(cards, "update", side_effect=AssertionError("network update")):
            plan = self.review()
            self.assertEqual(self.saved(plan)["restored"], plan["restored"])


if __name__ == "__main__":
    unittest.main()
