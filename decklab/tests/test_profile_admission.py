"""New-member admission uses temporary Forge roots; no database or real config."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from decklab.db import profile_admission as admission
from decklab.lib.forge import lifecycle
from decklab.lib.profile_config import InvalidProfileEdit, PendingProfileEdit, StaleProfileEdit


LOCAL_TEMP = (Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp"
              if os.name == "nt" else Path(tempfile.gettempdir()))
MEMBER = "user6"
KEY = "a" * 64


class MemberAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="decklab-admission-", dir=LOCAL_TEMP)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "results"

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def check(self):
        with admission.forge_claim(MEMBER, self.root):
            pass

    def test_new_identity_name_rules_and_email_validation_remain_separate(self):
        self.assertEqual(admission.validate(MEMBER, "  User6  ", object()), "User6")
        self.assertEqual(admission.validate(MEMBER, "X" * 120), "X" * 120)
        for member in (None, "home", "casual", "commander", "product", "pairing", "people", "claude",
                       "system", "test", "User6", "user--6", "../user6", "x" * 41):
            with self.subTest(member=member), self.assertRaises(InvalidProfileEdit):
                admission.validate(member, "User6")
        for name in (None, "", " ", "X" * 121, "User\n6", "User\x7f6"):
            with self.subTest(name=name), self.assertRaises(InvalidProfileEdit):
                admission.validate(MEMBER, name)

    def test_missing_results_root_needs_no_installation_and_leaves_root_absent(self):
        with admission.forge_claim(MEMBER, self.root) as claim:
            self.assertEqual(claim.root, self.root)
            self.assertFalse(self.root.exists())
        self.assertFalse(self.root.exists())

    def test_parsed_unrelated_legacy_objects_pass_without_file_changes(self):
        paths = [self.write(KEY + ".json", {"legacy": {"id": "superuser6/casual/old"}, "unknown": True}),
                 self.write("paired/" + KEY + ".json", {"sides": [{"seen_as": [{"id": "casual/home"}]}]}),
                 self.write("paired/tests/" + KEY + ".json", {"base": {"id": "user2/casual/old"}}),
                 self.write("field/old-Constructed-user2.json", {"runs": [{"deck": {"id": "user2/casual/old"}}]}),
                 self.write("field/old-Constructed-other-user6.json", {"runs": []})]
        before = {path: path.read_bytes() for path in paths}
        self.check()
        self.assertEqual({path: path.read_bytes() for path in paths}, before)

    def test_supported_result_and_mixed_provenance_refuse_without_changes(self):
        candidates = [
            (KEY + ".json", {"sides": [{"seen_as": [{"id": "user6/casual/old"}]},
                                        {"seen_as": [{"id": "casual/other"}]}]}),
            ("paired/" + KEY + ".json", {"variant": {"id": "variant:user6/casual/old@owned"}}),
            ("paired/tests/" + KEY + ".json", {"base": {"id": "user2/casual/old"},
                                                     "opponents": [{"id": "user6/commander/old"}]}),
            ("field/old-Constructed-user2.json", {"runs": [{"deck": {"id": "user6/casual/old"}}]}),
        ]
        for relative, value in candidates:
            with self.subTest(relative=relative):
                path = self.write(relative, value)
                before = path.read_bytes()
                with self.assertRaisesRegex(InvalidProfileEdit, "existing Forge records"):
                    self.check()
                self.assertEqual(path.read_bytes(), before)
                path.unlink()

    def test_legacy_unknown_target_namespace_and_scoped_field_filename_refuse(self):
        cases = [(KEY + ".json", {"future_provenance": {"owner": "user6/casual/old"}}),
                 (KEY + ".json", {"future_provenance": {"owner": "user6"}}),
                 ("field/old-Constructed-user6.json", {"runs": []}),
                 ("paired/tests/" + KEY + ".json", {"against": "field:user6:Constructed"})]
        for relative, value in cases:
            with self.subTest(relative=relative):
                path = self.write(relative, value)
                with self.assertRaises(InvalidProfileEdit):
                    self.check()
                path.unlink()

    def test_malformed_readable_result_cannot_prove_absence(self):
        path = self.write(KEY + ".json", {})
        path.write_bytes(b"{invalid JSON")
        with self.assertRaisesRegex(InvalidProfileEdit, "could not be checked safely"):
            self.check()
        self.assertEqual(path.read_bytes(), b"{invalid JSON")

    def test_non_readable_root_json_name_is_not_mistaken_for_a_result(self):
        path = self.write("notes.json", {})
        path.write_bytes(b"not a saved-result filename")
        self.check()
        self.assertTrue(path.exists())

    def test_unused_nested_tree_is_not_traversed_and_metadata_reads_are_bounded(self):
        path = self.write("logs/nested/private.json", {})
        path.write_bytes(b"not part of a readable result")
        self.check()
        oversized = self.write(KEY + ".json", {})
        with oversized.open("wb") as stream:
            stream.seek(admission.MAX_METADATA)
            stream.write(b"x")
        with self.assertRaisesRegex(InvalidProfileEdit, "could not be checked safely"):
            self.check()
        self.assertEqual(oversized.stat().st_size, admission.MAX_METADATA + 1)

    def test_excessive_json_or_provenance_nesting_is_a_static_refusal(self):
        path = self.write(KEY + ".json", {})
        path.write_text('{"future":' + "[" * 2000 + "0" + "]" * 2000 + "}", encoding="utf-8")
        with self.assertRaisesRegex(InvalidProfileEdit, "could not be checked safely"):
            self.check()

    def test_departed_namespace_and_any_pending_removal_are_typed_refusals(self):
        control = self.root.with_name("." + self.root.name + "-lifecycle")
        control.mkdir()
        departed = control / "departed.json"
        departed.write_text(json.dumps({"version": 1, "spaces": [MEMBER]}), encoding="utf-8")
        with self.assertRaises(InvalidProfileEdit):
            self.check()
        departed.write_text(json.dumps({"version": 1, "spaces": ["user2"]}), encoding="utf-8")
        pending = control / "pending" / ("1" * 8 + "-1111-4111-8111-" + "1" * 12 + ".json")
        pending.parent.mkdir()
        pending.write_text("{}", encoding="utf-8")
        with self.assertRaises(PendingProfileEdit):
            self.check()
        self.assertEqual(pending.read_text(encoding="utf-8"), "{}")

    def test_unsafe_or_busy_claim_errors_are_static_and_do_not_disclose_paths(self):
        for failure, expected in ((lifecycle.LifecycleError(lifecycle.BUSY), PendingProfileEdit),
                                  (OSError("private-path@example.com"), InvalidProfileEdit),
                                  (ValueError("private-path@example.com"), InvalidProfileEdit)):
            with self.subTest(failure=type(failure).__name__), \
                    mock.patch.object(lifecycle, "maintenance", side_effect=failure):
                with self.assertRaises(expected) as caught:
                    self.check()
                self.assertNotIn("private-path", str(caught.exception))

    def test_caller_errors_are_not_masked_as_a_forge_inspection_failure(self):
        failure = StaleProfileEdit("Reviewed membership changed")
        with self.assertRaises(StaleProfileEdit) as caught:
            with admission.forge_claim(MEMBER, self.root):
                raise failure
        self.assertIs(caught.exception, failure)
        self.check()                    # the exceptional caller released its claim
