"""Local simulation settings override shipped defaults without modifying tracked files."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from decklab.lib.forge import field, pilots


class LocalSimulationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="decklab-simulation-local-")
        self.addCleanup(folder.cleanup)
        self.file = Path(folder.name) / "simulation.json"
        self.local = self.file.with_name("simulation.local.json")
        self.enterContext(mock.patch.object(pilots, "SIMULATION_FILE", self.file))
        self.enterContext(mock.patch.object(pilots, "_loaded", {}))
        self.enterContext(mock.patch.object(pilots, "_logged", set()))
        self.enterContext(mock.patch.object(pilots, "available", return_value={
            "profiles": ["Default", "Cautious", "Reckless"], "switches": []}))
        self.enterContext(mock.patch.object(pilots.deck_identity, "lineage", side_effect=lambda deck: [deck]))

    def write(self, lists, default="Default"):
        self.file.write_text(json.dumps({"version": 1, "pilots": {
            "default": {"profile": default}, "lists": lists}, "field": {}}), encoding="utf-8")

    def local_settings(self, profile="Reckless", remove=None):
        self.local.write_text(json.dumps({"version": 1, "pilots": {"default": {"profile": profile}},
                              "field": {"Constructed": {"remove": remove or [], "add": []}}}), encoding="utf-8-sig")

    def test_local_file_replaces_both_pilots_and_field_without_touching_defaults(self):
        self.write({"casual/a": {"profile": "Cautious"}})
        original = self.file.read_bytes()
        self.local_settings(remove=["casual/a"])
        self.assertEqual(pilots.pilot_for("casual/a", "target"), {"profile": "Reckless", "switches": []})
        self.assertEqual(field._simulation_edits("Constructed"), ([], ["casual/a"]))
        self.assertEqual(pilots.problems(), [])
        self.assertEqual(self.file.read_bytes(), original)

    def test_cache_notices_local_creation_edit_and_removal(self):
        self.write({}, default="Cautious")
        self.assertEqual(pilots.load()["default"]["profile"], "Cautious")
        # The same size/time as the default must not reuse its cached answer.
        self.local.write_bytes(self.file.read_bytes().replace(b"Cautious", b"Reckless"))
        os.utime(self.local, ns=(self.file.stat().st_atime_ns, self.file.stat().st_mtime_ns))
        self.assertEqual(pilots.load()["default"]["profile"], "Reckless")
        self.local_settings("Default")
        self.assertEqual(pilots.load()["default"]["profile"], "Default")
        self.local.unlink()
        self.assertEqual(pilots.load()["default"]["profile"], "Cautious")

    def test_bad_local_file_reports_failure_without_restoring_shipped_choices(self):
        self.write({"casual/a": {"profile": "Cautious"}})
        self.local.write_text('{"private": "PRIVATE_VALUE",', encoding="utf-8")
        with mock.patch.object(pilots.common, "_log"), mock.patch.object(field.common, "_log"):
            loaded = pilots.load()
            self.assertEqual(loaded["lists"], {})
            self.assertEqual(loaded["default"]["profile"], "Default")
            self.assertTrue(loaded["problems"])
            self.assertNotIn("PRIVATE_VALUE", json.dumps(loaded))
            observer = mock.Mock()
            field._simulation_edits("Constructed", exclusions=observer)
            observer.unavailable.assert_called_once_with()

    def test_unreadable_override_does_not_fall_back(self):
        self.write({"casual/a": {"profile": "Cautious"}})
        self.local.mkdir()
        with mock.patch.object(pilots.common, "_log"):
            self.assertEqual(pilots.load()["lists"], {})
            self.assertTrue(pilots.problems())

    def test_the_shipped_example_has_no_deck_choices_or_experimental_switches(self):
        example = Path(__file__).resolve().parents[1] / "simulation.example.json"
        settings = json.loads(example.read_text(encoding="utf-8"))
        self.assertEqual(settings["pilots"], {"default": {"profile": "Default"}, "lists": {}})
        self.assertEqual(settings["field"], {name: {"add": [], "remove": []}
                                          for name in ("Constructed", "Commander")})

    def test_local_file_lost_after_selection_leaves_field_metadata_unavailable(self):
        self.write({})
        self.local_settings(remove=["casual/a"])
        observer, trace = mock.Mock(), mock.Mock()
        with mock.patch("builtins.open", side_effect=FileNotFoundError("private path")), \
                mock.patch.object(field.common, "_log"):
            self.assertEqual(field._simulation_edits("Constructed", trace=trace, exclusions=observer), ([], []))
        trace.unavailable.assert_called_once_with()
        observer.unavailable.assert_called_once_with()
        observer.configuration.assert_not_called()
