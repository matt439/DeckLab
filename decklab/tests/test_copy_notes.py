"""Counted notes survive ordinary CSV/CLI/receipt merges without adding copy identities."""
import copy
import io
import unittest

from decklab.lib.inventory import copy_notes, rules


def row(quantity="1", condition="NM", language="en", notes="", **extra):
    return dict(name="Llanowar Elves", set="fdn", collector_number="227", finish="nonfoil",
                quantity=quantity, condition=condition, language=language, notes=notes, **extra)


class CopyNotesTests(unittest.TestCase):
    def merged(self, *rows):
        before = copy.deepcopy(rows)
        result, counts = rules.merge_rows([], [("synthetic.csv", list(rows))])
        self.assertEqual(rows, before)
        self.assertEqual(counts["cards"], sum(int(value["quantity"]) for value in rows))
        self.assertEqual(set(result[0]), set(rules.FIELDS))
        return result[0]

    def test_counted_breakdowns_keep_each_known_and_unreported_contribution(self):
        merged = self.merged(row("2"), row(condition="LP", language="ja"), row(condition="", language=""))
        self.assertEqual((merged["quantity"], merged["condition"], merged["language"]), ("4", "", ""))
        self.assertEqual(merged["notes"], "Copies: condition 2 NM, 1 LP, 1 not recorded; "
                         "Copies: language 2 en, 1 ja, 1 not recorded")

    def test_save_export_reimport_and_a_later_merge_add_counts_rather_than_deduplicate_them(self):
        merged = self.merged(row("2"), row(condition="", notes=copy_notes.flag_notes(1, "signed")))
        exported = rules.collection_csv_bytes([merged]).decode("utf-8")
        parsed = rules.parse_cards(io.StringIO(exported), "synthetic export", existing=True)[0]
        merged = self.merged(parsed, parsed, row(condition="LP", notes=copy_notes.flag_notes(1, "signed", "altered")))
        self.assertEqual(merged["quantity"], "7")
        self.assertEqual(merged["notes"], "Copies: condition 4 NM, 1 LP, 2 not recorded; "
                         "Copies: 1 altered; Copies: 3 signed")

    def test_unknowns_and_old_general_notes_never_invent_a_previous_condition(self):
        old = "Merged copies have differing or unreported condition"
        merged = self.merged(row("3", condition="", notes=old), row("2"))
        self.assertEqual(merged["notes"], old + "; Copies: condition 2 NM, 3 not recorded")
        self.assertEqual(self.merged(row(condition="", language=""), row(condition="", language=""))["notes"], "")

    def test_bulk_explicit_field_takes_precedence_over_the_historical_note_left_in_place(self):
        merged = self.merged(row("3", condition="LP", notes="Copies: condition 2 NM, 1 not recorded"), row())
        self.assertEqual(merged["notes"], "Copies: condition 1 NM, 3 LP")

    def test_stale_or_malformed_breakdowns_remain_prose_and_are_not_trusted(self):
        for note in ("Copies: condition 99 NM", "Copies: condition 0 NM, 2 LP", "Copies: condition 1 NM, 1 NM"):
            with self.subTest(note=note):
                merged = self.merged(row("2", condition="", notes=note), row())
                self.assertIn(note, merged["notes"])
                self.assertTrue(merged["notes"].endswith("Copies: condition 1 NM, 2 not recorded"))
        hostile = "Copies: condition " + "9" * 20000 + " NM"
        self.assertFalse(copy_notes.has_counts(hostile, 2))
        self.assertEqual(copy_notes.note_limit(hostile, 2, 500), 500)

    def test_flags_are_independent_positive_counts_and_prose_is_kept(self):
        merged = self.merged(row("2", notes="from a trade; " + copy_notes.flag_notes(2, "signed", "misprint")),
                             row(notes="from a trade; " + copy_notes.flag_notes(1, "signed", "altered")))
        self.assertEqual(merged["notes"], "from a trade; Copies: 2 misprint; Copies: 1 altered; Copies: 3 signed")
        self.assertEqual(copy_notes.flag_notes(2), "")

    def test_legacy_free_text_values_with_delimiters_are_counted_and_roundtrip_safely(self):
        merged = self.merged(row(condition='Near; mint, "checked"'), row(condition=""))
        self.assertIn(r'Near\u003b mint\u002c \"checked\"', merged["notes"])
        again = self.merged(merged, row(condition='Near; mint, "checked"'))
        self.assertIn(r'condition 2 "Near\u003b mint\u002c \"checked\"", 1 not recorded', again["notes"])

    def test_differing_printings_and_finish_never_merge(self):
        rows, _ = rules.merge_rows([], [("synthetic", [row(), dict(row(), finish="foil"), dict(row(), collector_number="228")])])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(value["notes"] == "" for value in rows))

    def test_counted_evidence_has_an_extra_allowance_but_arbitrary_prose_stays_bounded(self):
        merged = self.merged(row(notes="x" * 500), row(condition=""))
        self.assertGreater(len(merged["notes"]), 500)
        self.assertEqual(copy_notes.note_limit(merged["notes"], 2, 500), len(merged["notes"]))
        self.assertEqual(copy_notes.note_limit("x" * 501, 2, 500), 500)
        self.assertEqual(copy_notes.note_limit("x" * 500 + "; Copies: 99 signed", 2, 500), 500)

    def test_vendor_marks_need_explicit_positive_values_and_unknown_marks_are_review_problems(self):
        self.assertEqual(copy_notes.source_flags({"misprint": "TRUE", "altered": "true"}, "manabox", "2"),
                         ("Copies: 2 misprint; Copies: 2 altered", None))
        self.assertEqual(copy_notes.source_flags({"signed": "signed", "altered art": "yes"}, "deckbox", "1"),
                         ("Copies: 1 altered; Copies: 1 signed", None))
        for negative in ("", "false", "no", "0"):
            self.assertEqual(copy_notes.source_flags({"signed": negative}, "deckbox", "3"), ("", None))
        self.assertIn("known yes/no value", copy_notes.source_flags({"signed": "perhaps"}, "deckbox", "1")[1])
        self.assertEqual(copy_notes.source_flags({"signed": "true"}, "collection", "1"), ("", None))

    def test_partial_split_cannot_allocate_mixed_condition_or_some_copy_marks(self):
        for notes in ("Copies: condition 2 NM, 1 LP", "Copies: 2 signed", "Copies: condition 99 NM"):
            with self.subTest(notes=notes), self.assertRaisesRegex(ValueError, "actual copy facts"):
                copy_notes.split_notes(row("3", condition="", notes=notes), 1)
        uniform = row("3", notes="Copies: 3 signed; Copies: condition 3 NM")
        self.assertEqual(copy_notes.split_notes(uniform, 1), "Copies: 1 signed; Copies: condition 1 NM")
        self.assertEqual(copy_notes.split_notes(uniform, 3), uniform["notes"])
