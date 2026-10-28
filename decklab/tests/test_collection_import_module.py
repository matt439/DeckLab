"""The extracted upload reader retains the Collection API's patch owners."""
import subprocess
import sys
import unittest
from unittest import mock

from decklab.lib.api import collection_edit as edits, collection_import as imports
from decklab.lib.api.common import ApiError


HEADER = "name,set,collector_number,finish,quantity,condition,language,notes\n"
ROW = "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n"


class CollectionImportModuleTests(unittest.TestCase):
    def test_either_module_can_be_imported_first(self):
        for module in ("collection_edit", "collection_import"):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-c", f"from decklab.lib.api import {module}; "
                     "from decklab.lib.api import collection_edit as e, collection_import as i; "
                     "assert e.read_upload is i.read_upload"],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_parser_entry_points_are_the_extracted_functions(self):
        for name in ("_norm", "detect", "_condition", "_language", "_finish", "_too_many_rows",
                     "_source_rows", "read_upload"):
            with self.subTest(name=name):
                self.assertIs(getattr(edits, name), getattr(imports, name))

    def test_both_upload_entry_points_use_the_current_matching_owner(self):
        for reader in (edits.read_upload, imports.read_upload):
            with self.subTest(reader=reader), mock.patch.object(edits, "match") as match:
                match.side_effect = lambda row, set_name: ({**row, "name": "Matched card"}, None)
                fmt, rows, problems, dropped = reader(HEADER + ROW)
                self.assertEqual((fmt, problems, dropped), ("collection", [], 0))
                self.assertEqual((rows[0]["name"], rows[0]["line"]), ("Matched card", 2))
                match.assert_called_once()

    def test_both_upload_entry_points_observe_changed_row_limit(self):
        for reader in (edits.read_upload, imports.read_upload):
            with self.subTest(reader=reader), mock.patch.object(edits, "MAX_IMPORT_ROWS", 1):
                with self.assertRaises(ApiError) as caught:
                    reader(HEADER + ROW + ROW)
                self.assertEqual(caught.exception.status, 400)
                self.assertEqual(caught.exception.message,
                                 "That file has more than 1 rows of cards, and an import is limited to "
                                 "1: split it into smaller files and import each one.")

    def test_upload_conversion_uses_the_current_shared_validation_limits(self):
        with mock.patch.object(edits, "MAX_QUANTITY", 1):
            _, rows, problems, _ = imports.read_upload(HEADER + ROW)
        self.assertEqual(rows[0]["line"], 2)
        self.assertEqual(problems, [{"line": 2, "message": "quantity '2' isn't a whole number from 1 to 1"}])
