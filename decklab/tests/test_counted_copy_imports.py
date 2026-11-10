"""Copy marks and counted merge evidence use the existing review and atomic write path."""
import io
import json

from decklab.lib.api import collection_edit as edits, collection_import as imports
from decklab.lib.inventory import rules
from decklab.tests import test_collection_edit as support
from decklab.tests.test_collection_import_formats import csv_file


MANABOX = csv_file(["Name", "Set code", "Collector number", "Foil", "Quantity", "Condition", "Language",
                    "Misprint", "Altered", "Purchase price"], [
    {"Name": "Llanowar Elves", "Set code": "FDN", "Collector number": "227", "Foil": "normal", "Quantity": 2,
     "Condition": "near_mint", "Language": "en", "Misprint": "true", "Altered": "false", "Purchase price": "PAID CANARY"},
    {"Name": "Llanowar Elves", "Set code": "FDN", "Collector number": "227", "Foil": "normal", "Quantity": 1,
     "Condition": "", "Language": "ja", "Misprint": "false", "Altered": "true", "Purchase price": "PAID CANARY"}])
DECKBOX = csv_file(["Count", "Name", "Edition", "Edition Code", "Card Number", "Condition", "Language", "Foil", "Signed",
                    "Altered Art", "Misprint", "My Price"], [
    {"Count": 2, "Name": "Llanowar Elves", "Edition": "Foundations", "Edition Code": "FDN", "Card Number": "227",
     "Condition": "Near Mint", "Language": "English", "Signed": "signed", "Altered Art": "yes", "Misprint": "0",
     "My Price": "PAID CANARY"}])


class CountedCopyImportTests(support.CollectionEditTestCase):
    def preview(self, text, filename="counted.csv"):
        return self.call(edits.import_preview, "user2", space="user2", filename=filename, text=text)

    def apply(self, shown, **extra):
        return self.call(edits.import_apply, "user2", space="user2", token=shown["token"], sha256=shown["sha256"], **extra)

    def test_manabox_preview_and_apply_keep_exact_counts_source_facts_and_raw_bytes(self):
        shown = self.preview(MANABOX)
        self.assertEqual(shown["problems"], [])
        self.assertEqual(shown["rows"][0]["notes"], "Copies: condition 2 NM, 1 not recorded; "
                         "Copies: language 2 en, 1 ja; Copies: 2 misprint; Copies: 1 altered")
        self.assertEqual([source["row"]["notes"] for source in shown["source_rows"]],
                         ["Copies: 2 misprint", "Copies: 1 altered"])
        self.assertNotIn("PAID CANARY", json.dumps(shown))
        self.assertEqual(len(self.writes), 0)
        self.apply(shown)
        actual = self.rows("user2")["rows"][0]
        self.assertEqual((actual["quantity"], actual["condition"], actual["language"]), ("5", "", ""))
        self.assertEqual(actual["notes"], "Copies: condition 4 NM, 1 not recorded; "
                         "Copies: language 4 en, 1 ja; Copies: 2 misprint; Copies: 1 altered")
        self.assertEqual(len(self.writes), 1)
        self.assertEqual((self.box.magic / "people/user2/imports/2026-10-10-counted.csv").read_bytes(), MANABOX.encode())

    def test_deckbox_signed_and_altered_marks_are_counts_never_new_identity_columns(self):
        shown = self.preview(DECKBOX)
        self.assertEqual(shown["problems"], [])
        self.assertEqual(shown["rows"][0]["notes"], "Copies: 2 altered; Copies: 2 signed")
        self.apply(shown)
        actual = self.rows("user2")["rows"][0]
        self.assertEqual(actual["quantity"], "4")
        self.assertEqual(actual["notes"], "Copies: 2 altered; Copies: 2 signed")
        self.assertEqual(set(actual), set(rules.FIELDS))

    def test_unfamiliar_positive_mark_requires_review_and_refusal_keeps_cards_and_raw_imports_unchanged(self):
        shown = self.preview(MANABOX.replace("true", "uncertain", 1))
        self.assertIn("misprint mark isn't a known yes/no", shown["problems"][0]["message"])
        before = self.rows("user2")
        self.assertApiError(400, self.apply, shown)
        self.assertEqual(self.rows("user2"), before)
        self.assertEqual(len(self.writes), 0)
        self.assertFalse((self.box.magic / "people/user2/imports").exists())
        self.apply(shown, skip_problems=True)
        actual = self.rows("user2")["rows"][0]
        self.assertIn("Copies: 1 altered", actual["notes"])
        self.assertNotIn("misprint", actual["notes"])

    def test_exported_count_notes_longer_than_prose_limit_roundtrip_and_remain_editable(self):
        source = dict(zip(rules.FIELDS, ["Llanowar Elves", "fdn", "227", "nonfoil", "2", "", "en",
                                        "x" * 500 + "; Copies: condition 1 NM, 1 not recorded; Copies: 1 signed"]))
        text = rules.collection_csv_bytes([source]).decode()
        incoming = imports.read_upload(text)[1][0]
        self.assertEqual(incoming["notes"], source["notes"])
        self.assertEqual(edits._row_input(source)["notes"], source["notes"])
        self.apply(self.preview(text))
        actual = self.rows("user2")["rows"][0]
        self.assertIn("Copies: condition 3 NM, 1 not recorded", actual["notes"])
        # The unchanged eight-column writer can feed another preview without count loss.
        exported = rules.collection_csv_bytes([actual]).decode()
        again = imports.read_upload(exported)[1][0]
        self.assertEqual(again["notes"], actual["notes"])
        self.assertEqual(len(rules.parse_cards(io.StringIO(exported), "synthetic", existing=True)), 1)

    def test_stale_apply_keeps_all_counted_facts_and_raw_upload_unwritten(self):
        shown = self.preview(MANABOX)
        old = self.rows("user2")
        self.call(edits.save_card, "user2", space="user2", sha256=old["sha256"], action="add",
                  row=dict(zip(rules.FIELDS, ["Sol Ring", "ecc", "57", "nonfoil", "1", "", "", ""])))
        before = self.rows("user2")
        self.assertApiError(409, self.apply, shown)
        self.assertEqual(self.rows("user2"), before)
        self.assertEqual(len(self.writes), 1)
        self.assertFalse((self.box.magic / "people/user2/imports").exists())

    def test_counted_notes_never_expand_the_prose_limit_or_silently_clip_saved_counts(self):
        source = dict(zip(rules.FIELDS, ["Llanowar Elves", "fdn", "227", "nonfoil", "2", "", "en",
                                        "x" * 501 + "; Copies: condition 1 NM, 1 not recorded"]))
        shown = self.preview(rules.collection_csv_bytes([source]).decode())
        self.assertIn("too long to keep their counted copy details", shown["problems"][0]["message"])
        self.assertApiError(400, self.apply, shown)
        self.assertEqual(len(self.writes), 0)
        self.assertApiError(400, edits._row_input, source)
