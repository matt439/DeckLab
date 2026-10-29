"""Source-set import reviews over disposable collections and the fixture card index."""
import json
from unittest import mock

from decklab.lib.api import collection_edit as edits, collection_import as imports
from decklab.tests import test_collection_edit as support


MIXED = (support.HEADER
         + "Llanowar Elves,fdn,227,nonfoil,2,NM,en,keep source facts\n"
         + "Unknown FDN card,fdn,999,nonfoil,1,,,\n"
         + "Aerie Mystics,con,1,foil,3,LP,ja,\n"
         + "Unknown CON card,con,999,nonfoil,1,,,\n"
         + "Unknown card,,,nonfoil,1,,,\n"
         + "Sol Ring,ecc,57,nonfoil,1,,,\n"
         + "Forest,fdn,280,nonfoil,5,,,\n")

DECKBOX_SHARED = (
    "Count,Name,Edition,Edition Code,Card Number,Condition,Language,Foil\n"
    "2,Llanowar Elves,Foundations,FDN,227,Near Mint,English,\n"
    "3,Llanowar Elves,Foundations,,227,Near Mint,Japanese,\n")


class CollectionImportGroupsTests(support.CollectionEditTestCase):
    def preview(self, text=MIXED, space="user2", filename="groups.csv", profile=None):
        return self.call(edits.import_preview, profile or space, space=space, filename=filename, text=text)

    def apply(self, preview, space="user2", profile=None, **options):
        options.setdefault("sha256", self.rows(space)["sha256"])
        return self.call(edits.import_apply, profile or space, space=space, token=preview["token"], **options)

    def group(self, preview, code="", name=None):
        return next(group for group in preview["groups"]
                    if group["code"] == code and (name is None or group["name"] == name))

    def ids(self, preview, *codes):
        return [self.group(preview, code)["id"] for code in codes]

    def preview_file(self, profile="user2"):
        return self.box.data / "collection-imports" / f"{profile}.json"

    def record(self, profile="user2"):
        return json.loads(self.preview_file(profile).read_text(encoding="utf-8"))

    def test_preview_groups_original_source_rows_with_explicit_valid_and_problem_counts(self):
        before = self.magic_files()
        preview = self.preview()
        fdn = self.group(preview, "fdn")
        self.assertEqual((fdn["rows"], fdn["problem_rows"], fdn["valid_rows"], fdn["valid_cards"],
                          fdn["dropped_basics"], fdn["lines"]), (3, 1, 1, 2, 5, [2, 3, 8]))
        con = self.group(preview, "con")
        self.assertEqual((con["rows"], con["problem_rows"], con["valid_rows"], con["valid_cards"]), (2, 1, 1, 3))
        unknown = self.group(preview)
        self.assertEqual((unknown["label"], unknown["problem_rows"], unknown["lines"]), ("Unknown set", 1, [6]))
        self.assertEqual(len({group["id"] for group in preview["groups"]}), 4)
        self.assertEqual(sorted(line for group in preview["groups"] for line in group["lines"]), list(range(2, 9)))
        by_line = {row["line"]: row for row in preview["source_rows"]}
        self.assertEqual(by_line[2]["source_set"], {"code": "fdn", "name": ""})
        self.assertEqual(by_line[2]["group"], fdn["id"])
        self.assertEqual(set(by_line[2]["row"]), set(edits.FIELDS))
        self.assertIsNone(by_line[2]["problem"])
        self.assertTrue(by_line[8]["dropped_basic"])
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])

    def test_original_parser_tuple_stays_identical_to_richer_review(self):
        review = imports.read_review(MIXED)
        self.assertEqual(edits.read_upload(MIXED),
                         (review["format"], review["rows"], review["problems"], review["dropped_basics"]))
        self.assertEqual(len(edits.read_upload(MIXED)), 4)

    def test_selected_sets_exclude_valid_copies_too_and_keep_original_upload_bytes(self):
        text = "\ufeff" + MIXED.replace("\n", "\r\n")
        preview = self.preview(text, filename="Original Groups.csv")
        result = self.apply(preview, skip_groups=self.ids(preview, "fdn", "con", ""))
        self.assertEqual(result["added"]["cards"], 1)
        self.assertEqual(result["skipped"], 3)
        quantities = {row["name"]: row["quantity"] for row in result["rows"]}
        self.assertEqual(quantities, {"Llanowar Elves": "2", "Sol Ring": "1"})
        self.assertEqual((self.box.root / result["raw"]).read_bytes(), text.encode("utf-8"))
        self.assertTrue(result["excluded_groups"])
        self.assertEqual(len(self.writes), 1)
        self.assertFalse(self.preview_file().exists())
        audit = "\n".join(self.extra())
        self.assertIn("fdn", audit.lower())
        self.assertIn("con", audit.lower())
        message = self.last_write()[0]
        self.assertIn("deliberately left out 3 source sets: 6 source rows, including 2 valid rows (5 cards)", message)
        self.assertIn("source lines 2-6, 8", message)

    def test_unselected_problem_groups_still_block_without_mutating_any_collection(self):
        preview = self.preview()
        before = self.magic_files()
        error = self.assertApiError(400, self.apply, preview, skip_groups=self.ids(preview, "fdn"))
        self.assertEqual({problem["line"] for problem in error.extra["problems"]}, {5, 6})
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])
        self.assertTrue(self.preview_file().exists())
        self.assertTrue(self.apply(preview, skip_groups=self.ids(preview, "fdn", "con", ""))["ok"])

    def test_same_final_printing_retains_only_copies_from_unselected_source_set(self):
        preview = self.preview(DECKBOX_SHARED)
        self.assertEqual(len(preview["rows"]), 1)
        self.assertEqual(preview["rows"][0]["quantity"], "5")
        coded = self.group(preview, "fdn")
        named = self.group(preview, "", "Foundations")
        self.assertNotEqual(coded["id"], named["id"])
        self.assertEqual([row["row"]["set"] for row in preview["source_rows"]], ["fdn", "fdn"])
        result = self.apply(preview, skip_groups=[coded["id"]])
        self.assertEqual(result["added"]["cards"], 3)
        [elves] = result["rows"]
        self.assertEqual(elves["quantity"], "5")
        self.assertEqual(result["skipped"], 0)
        self.assertTrue(result["excluded_groups"])
        self.assertEqual((self.box.root / result["raw"]).read_text(encoding="utf-8"), DECKBOX_SHARED)

    def test_retained_rows_are_remerged_without_rematching_saved_source_facts(self):
        review = imports.read_review(DECKBOX_SHARED)
        coded = self.group(review, "fdn")
        evidence = json.dumps(review["source_rows"], sort_keys=True)
        with mock.patch.object(edits, "match", side_effect=AssertionError("review must not match again")):
            all_rows, _, _ = imports.review_rows(review["source_rows"])
            rows, problems, dropped = imports.review_rows(review["source_rows"], [coded["id"]])
        self.assertEqual((all_rows[0]["quantity"], all_rows[0]["language"]), ("5", ""))
        self.assertEqual((problems, dropped), ([], 0))
        self.assertEqual([(row["quantity"], row["language"], row["line"]) for row in rows], [("3", "ja", 3)])
        self.assertEqual(json.dumps(review["source_rows"], sort_keys=True), evidence)

    def test_group_selection_rejects_malformed_duplicate_and_unknown_ids(self):
        preview = self.preview()
        known = self.ids(preview, "fdn")[0]
        before = self.magic_files()
        for selected in (None, False, "g1", {}, [False], [1], [[]], [""], ["unknown"], ["g99999"], [known, known]):
            with self.subTest(selected=selected):
                self.assertApiError(400, self.apply, preview, skip_groups=selected)
                self.assertEqual(self.magic_files(), before)
                self.assertEqual(self.writes, [])
        self.assertApiError(400, self.apply, preview, skip_groups=[known], skip_problems=True)

    def test_all_groups_excluded_refuses_without_keeping_an_empty_import(self):
        preview = self.preview()
        before = self.magic_files()
        self.assertApiError(400, self.apply, preview, skip_groups=[group["id"] for group in preview["groups"]],
                            contains="nothing to import")
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])
        self.assertTrue(self.preview_file().exists())

    def test_group_selection_caps_ids_at_the_source_row_limit(self):
        self.preview()
        selected = [f"g{number}" for number in range(1, edits.MAX_IMPORT_ROWS + 2)]
        before = self.magic_files()
        self.assertApiError(400, edits._selected_import, self.record(), selected, contains="at most 20,000")
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])

    def test_twenty_thousand_reviewed_ids_fit_the_bounded_apply_body(self):
        preview = self.preview()
        example = preview["groups"][0]
        selected = [f"g{number}" for number in range(1, edits.MAX_IMPORT_ROWS + 1)]
        record = {**self.record(), "source_rows": [],
                  "groups": [{**example, "id": ident, "rows": 0, "problem_rows": 0, "valid_rows": 0,
                              "valid_cards": 0, "dropped_basics": 0, "lines": []} for ident in selected]}
        body = json.dumps({"profile": "user2", "space": "user2", "token": preview["token"],
                           "sha256": preview["sha256"], "skip_groups": selected}).encode("utf-8")
        self.assertGreater(len(body), edits.MAX_SAVE_BODY)
        self.assertLess(len(body), edits.MAX_IMPORT_APPLY_BODY)
        self.assertLessEqual(edits.MAX_IMPORT_APPLY_BODY, edits.common.MAX_EDIT_BODY)
        parsed = edits._parse_body(body, edits.MAX_IMPORT_APPLY_BODY)
        before = self.magic_files()
        reviewed, problems = edits._selected_import(record, parsed["skip_groups"])
        self.assertEqual((reviewed["good"], problems), ([], []))
        self.assertEqual(len(reviewed["excluded_groups"]), edits.MAX_IMPORT_ROWS)
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])

    def test_group_selection_cannot_be_used_on_an_older_flat_preview(self):
        preview = self.preview()
        record = self.record()
        record["version"] = 3
        record.pop("groups")
        record.pop("source_rows")
        self.preview_file().write_text(json.dumps(record), encoding="utf-8")
        before = self.magic_files()
        error = self.assertApiError(409, self.apply, preview, skip_groups=self.ids(preview, "fdn"))
        self.assertTrue(error.extra["repreview_required"])
        self.assertEqual(self.magic_files(), before)
        self.assertTrue(self.apply(preview, skip_problems=True)["ok"])

    def test_group_selection_preserves_collection_sha_conflicts(self):
        preview = self.preview()
        before = self.magic_files()
        self.assertApiError(409, self.apply, preview, sha256="0" * 64,
                            skip_groups=self.ids(preview, "fdn", "con", ""))
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])
        self.assertTrue(self.apply(preview, skip_groups=self.ids(preview, "fdn", "con", ""))["ok"])

    def test_changed_repeat_imports_require_new_review_before_group_selection_applies(self):
        preview = self.preview()
        support._write(self.box.magic / "people" / "user2" / "imports" / "new-copy.csv", MIXED)
        before = self.magic_files()
        error = self.assertApiError(409, self.apply, preview, skip_groups=self.ids(preview, "fdn", "con", ""))
        self.assertTrue(error.extra["repreview_required"])
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])
        fresh = self.preview()
        self.assertEqual(len(fresh["repeat_imports"]), 1)
        self.assertTrue(self.apply(fresh, skip_groups=self.ids(fresh, "fdn", "con", ""))["ok"])
        self.assertIn("intentional repeat import", self.last_write()[0])

    def test_newer_preview_replaces_selected_group_meanings_and_expiry_still_applies(self):
        first = self.preview()
        self.preview(support.OWN_COLUMNS)
        self.assertApiError(410, self.apply, first, skip_groups=self.ids(first, "fdn", "con", ""))
        fresh = self.preview()
        with mock.patch.object(edits, "IMPORT_TTL", -1):
            self.assertApiError(410, self.apply, fresh, skip_groups=self.ids(fresh, "fdn", "con", ""))
        self.assertEqual(self.writes, [])

    def test_group_review_stays_bound_to_its_profile_and_space(self):
        preview = self.preview()
        before = self.magic_files()
        with self.as_("user3"):
            self.assertApiError(403, self.apply, preview, profile="user3",
                                skip_groups=self.ids(preview, "fdn", "con", ""))
        self.assertApiError(400, edits._load_preview, preview["token"], "home", {"id": "user2"})
        self.assertApiError(410, self.apply, preview, space="user3", profile="user3",
                            skip_groups=self.ids(preview, "fdn", "con", ""))
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])

    def test_five_thousand_source_rows_are_grouped_before_any_write(self):
        text = support.HEADER + "".join(
            ("Llanowar Elves,fdn,227,nonfoil,1,,,\n", "Unknown card,old,1,nonfoil,1,,,\n")[index % 2]
            for index in range(5000))
        before = self.magic_files()
        preview = self.preview(text)
        self.assertEqual(len(preview["source_rows"]), 5000)
        self.assertEqual([group["rows"] for group in preview["groups"]], [2500, 2500])
        self.assertEqual(sum(group["problem_rows"] for group in preview["groups"]), 2500)
        self.assertEqual(preview["adds"], {"rows": 1, "cards": 2500})
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.record()["text"], text)
