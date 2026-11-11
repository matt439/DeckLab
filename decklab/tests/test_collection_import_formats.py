"""New offline CSV/text layouts keep identity, unknown facts and original source evidence."""
import csv
import io
import json
from unittest import mock

from decklab.lib import cards
from decklab.lib.api import collection_edit as edits, collection_import as imports
from decklab.tests import test_collection_edit as support


def csv_file(columns, rows, *, separator=",", prefix=""):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, columns, delimiter=separator, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return prefix + out.getvalue()


ARCHI = csv_file(["Quantity", "Name", "Finish", "Condition", "Date Added", "Language", "Purchase Price", "Tags",
                  "Edition Name", "Edition Code", "Multiverse Id", "Scryfall ID", "Collector Number", "Price (TCG Player)"],
    [{"Quantity": 2, "Name": "Llanowar Elves", "Finish": "Foil", "Condition": "", "Language": "",
      "Edition Name": "Foundations", "Edition Code": "FDN", "Collector Number": "227",
      "Purchase Price": "PRIVATE PAID CANARY", "Tags": "PRIVATE FOLDER CANARY"}])
DRAGON = csv_file(["Folder Name", "Quantity", "Trade Quantity", "Card Name", "Set Code", "Set Name", "Card Number",
                   "Condition", "Printing", "Language", "Price Bought", "Date Bought", "LOW", "MID", "MARKET"],
    [{"Folder Name": "PRIVATE FOLDER CANARY", "Quantity": 3, "Trade Quantity": 1, "Card Name": "Llanowar Elves",
      "Set Code": "FDN", "Set Name": "Foundations", "Card Number": "227", "Condition": "NearMint",
      "Printing": "Normal", "Language": "Japanese", "Price Bought": "PRIVATE PAID CANARY"}], prefix='\ufeff"sep=,"\r\n')
DELVER = csv_file(["Quantity", "Name", "Set", "Collector Number", "Foil", "Condition", "Language", "Price Paid"],
    [{"Quantity": 2, "Name": "Elvish Mystic", "Set": "CMM", "Collector Number": "648", "Foil": "false",
      "Condition": "not reported", "Language": "not reported", "Price Paid": "PRIVATE PAID CANARY"}])
TCG = csv_file(["TCGplayer Id", "Product Line", "Set Name", "Product Name", "Title", "Number", "Rarity", "Condition",
                "TCG Market Price", "Total Quantity", "Add to Quantity", "TCG Marketplace Price", "Photo URL"],
    [{"TCGplayer Id": "123", "Product Line": "Magic: The Gathering", "Set Name": "Foundations", "Product Name": "Llanowar Elves",
      "Number": "227", "Condition": "Near Mint Foil", "Total Quantity": 2, "Add to Quantity": 99,
      "TCG Marketplace Price": "PRIVATE PAID CANARY", "Photo URL": "https://example.com/no-fetch"}])


class OfflineFormatTests(support.CollectionEditTestCase):
    def preview(self, text, *, space="user2", profile="user2", filename="offline.csv"):
        return self.call(edits.import_preview, profile, space=space, filename=filename, text=text)

    def apply(self, shown, **extra):
        return self.call(edits.import_apply, "user2", space="user2", token=shown["token"],
                         sha256=self.rows("user2")["sha256"], **extra)

    def test_vendor_layouts_keep_exact_identity_and_never_invent_condition_or_language(self):
        for text, fmt, expected in ((ARCHI, "archidekt", ("fdn", "227", "foil", "2", "", "")),
                                    (DRAGON, "dragonshield", ("fdn", "227", "nonfoil", "3", "NM", "ja")),
                                    (DELVER, "delver", ("cmm", "648", "nonfoil", "2", "", "")),
                                    (TCG, "tcgplayer", ("fdn", "227", "foil", "2", "NM", ""))):
            with self.subTest(fmt=fmt), mock.patch.object(cards, "_get_json", side_effect=AssertionError("network lookup")):
                found, rows, problems, dropped = imports.read_upload(text)
                self.assertEqual((found, problems, dropped), (fmt, [], 0))
                row = rows[0]
                self.assertEqual(tuple(row[key] for key in ("set", "collector_number", "finish", "quantity", "condition", "language")), expected)
                self.assertEqual(row["notes"], "")
                self.assertNotIn("PRIVATE", json.dumps(rows))

    def test_separator_preamble_and_optional_delimiters_preserve_original_source_line_numbers(self):
        review = imports.read_review(DRAGON)
        self.assertEqual(review["source_rows"][0]["line"], 3)
        self.assertEqual(review["groups"][0]["lines"], [3])
        for separator in ("\t", ";"):
            text = csv_file(["Quantity", "Name", "Edition Code", "Collector Number", "Finish"],
                [{"Quantity": 1, "Name": "Llanowar Elves", "Edition Code": "fdn", "Collector Number": "227", "Finish": "Normal"}],
                separator=separator, prefix=f"sep={separator}\r\n")
            review = imports.read_review(text)
            self.assertEqual((review["format"], review["problems"], review["source_rows"][0]["line"]), ("archidekt", [], 3))
        self.assertEqual(imports._norm("cOlLeCtOr_nUmBeR"), "collector number")
        self.assertEqual(imports._norm("CardNumber"), "card number")

    def test_delver_named_site_presets_use_the_existing_layouts_and_unknown_facts_stay_blank(self):
        fmt, rows, _, _ = imports.read_upload(support.MOXFIELD)
        self.assertEqual(fmt, "moxfield")
        self.assertTrue(rows)
        unknown = DRAGON.replace("NearMint", "LightPlayed").replace("Japanese", "Unknown language")
        row = imports.read_upload(unknown)[1][0]
        self.assertEqual((row["condition"], row["language"]), ("", ""))

    def test_plain_text_keeps_faces_finish_and_source_lines_and_can_review_bad_lines_explicitly(self):
        text = '\n# Source comment\nCommander\n1 Ghalta, Primal Hunger (RIX) 130 *F* #Leader\n\nDeck\n2 Llanowar Elves (FDN) 227 #Ramp\nnot a card line\n'
        shown = self.preview(text, filename="cards.txt")
        self.assertEqual(shown["format"], "text")
        self.assertEqual([row["line"] for row in shown["source_rows"]], [4, 7, 8])
        self.assertEqual(shown["problems"][0]["line"], 8)
        self.assertEqual(shown["rows"][0]["finish"], "foil")
        self.assertTrue(all(not row["condition"] and not row["language"] for row in shown["rows"]))
        self.assertEqual(len(self.writes), 0)
        self.assertApiError(400, self.apply, shown)
        self.apply(shown, skip_problems=True)
        self.assertEqual(len(self.writes), 1)
        raw = self.box.magic / "people/user2/imports/2026-10-10-cards.csv"
        self.assertEqual(raw.read_bytes(), text.encode("utf-8"))

    def test_vendor_raw_bytes_are_kept_only_after_explicit_apply_and_source_metadata_has_no_paid_fields(self):
        shown = self.preview(DRAGON)
        self.assertEqual(len(self.writes), 0)
        self.assertNotIn("PRIVATE PAID CANARY", json.dumps(shown))
        self.assertNotIn("PRIVATE FOLDER CANARY", json.dumps(shown))
        self.assertEqual(shown["groups"][0]["code"], "fdn")
        self.apply(shown)
        raw = self.box.magic / "people/user2/imports/2026-10-10-offline.csv"
        self.assertEqual(raw.read_bytes(), DRAGON.encode("utf-8"))
        self.assertEqual(len(self.writes), 1)

    def test_tcgplayer_id_only_backups_and_other_games_are_explicit_review_problems_not_lookups(self):
        text = csv_file(["Collection Name", "Created At", "Product ID", "Condition", "Language", "Variant", "Quantity"],
            [{"Collection Name": "user1", "Product ID": "123", "Variant": "Normal", "Quantity": 1}])
        shown = self.preview(text)
        self.assertEqual(shown["format"], "tcgplayer")
        self.assertIn("ID-only export", shown["problems"][0]["message"])
        self.assertEqual(shown["adds"]["cards"], 0)
        other = self.preview(TCG.replace("Magic: The Gathering", "Pokemon"))
        self.assertIn("Magic cards only", other["problems"][0]["message"])

    def test_tcgplayer_condition_finish_is_explicit_and_conflicting_columns_never_guess(self):
        for condition, expected in (("NearMintFoil", "foil"), ("NMFOIL", "foil"), ("Near Mint Non Foil", "nonfoil")):
            text = TCG.replace("Near Mint Foil", condition)
            fmt, rows, problems, _ = imports.read_upload(text)
            self.assertEqual((fmt, problems), ("tcgplayer", []))
            self.assertEqual((rows[0]["condition"], rows[0]["finish"]), ("NM", expected))
        text = csv_file(["Quantity", "Simple Name", "Set Code", "Card Number", "Printing", "Condition"],
            [{"Quantity": 1, "Simple Name": "Llanowar Elves", "Set Code": "fdn", "Card Number": "227",
              "Printing": "Normal", "Condition": "Near Mint Foil"}])
        self.assertIn("disagree about finish", imports.read_upload(text)[2][0]["message"])

    def test_finish_categories_and_row_limits_keep_the_original_parser_and_owner_contract(self):
        with mock.patch.object(edits, "match", side_effect=lambda row, set_name: (row, None)):
            _, rows, problems, _ = imports.read_upload("1 Sol Ring (CMM) 410 *E* #Ramp\n")
        self.assertEqual(problems, [])
        self.assertEqual(rows[0]["finish"], "etched")
        self.assertEqual(rows[0]["notes"], "")
        with mock.patch.object(edits, "MAX_IMPORT_ROWS", 1):
            self.assertApiError(400, imports.read_upload, "1 Elvish Mystic (CMM) 648\n1 Llanowar Elves (FDN) 227\n", contains="more than 1")

    def test_unknown_layout_names_every_accepted_layout_and_private_spaces_refuse_before_parsing(self):
        for text in ("a,b,c\n1,2,3\n", "https://example.com/a-deck\n", "Product ID,Quantity\n123,1\n"):
            error = self.assertApiError(400, imports.read_upload, text)
            for name in ("ManaBox", "Moxfield", "Deckbox", "Deck Lab", "Archidekt", "Dragon Shield", "Delver Lens", "TCGplayer", "plain text"):
                self.assertIn(name, error.message)
        with self.as_("matt"), mock.patch.object(edits, "read_review", side_effect=AssertionError("private source parsed")):
            self.assertApiError(403, self.preview, ARCHI, profile="matt")
