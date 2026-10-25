"""Space-scoped fields and viewer-filtered numbers; all Forge games/results are fake."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from decklab.lib import decks, inventory, spaces
from decklab.lib.forge import common, engine, field, lists, runner, saved
from decklab.tests.test_forge_field import FakeField

HIDDEN = "Hidden private title"


class FieldPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="decklab-field-privacy-")
        self.addCleanup(self.tmp.cleanup)
        self.results = Path(self.tmp.name)
        self.fake = FakeField()
        self.summaries = [self.summary(deck_id) for deck_id in (
            "casual/home", "casual/second", "sample/casual/own", "sample/casual/second",
            "public/casual/shared", "private/casual/hidden", "product/owned", "product/ordered")]
        self.summaries[-3]["title"] = HIDDEN
        self.public_spaces = set()
        self.visible_ids = {s["id"] for s in self.summaries if s["id"].startswith("sample/")}
        self.patches = [
            mock.patch.object(inventory, "is_pinned", return_value=True),
            mock.patch.object(decks, "list_decks", side_effect=lambda: self.summaries),
            mock.patch.object(decks, "find_summary", side_effect=self.summary_for),
            mock.patch.object(field, "_entry", side_effect=self.entry),
            mock.patch.object(field, "_simulation_edits", return_value=([], [])),
            mock.patch.object(field.card_pool, "read_status", return_value={
                "owned.csv": SimpleNamespace(status="owned", intact=True),
                "ordered.csv": SimpleNamespace(status="ordered", intact=True)}),
            mock.patch.object(lists, "matchup_key", self.fake.key),
            mock.patch.object(saved, "load", self.fake.load),
            mock.patch.object(saved, "_stored", self.fake.stored),
            mock.patch.object(runner, "run", self.fake.run),
            mock.patch.object(engine, "today", return_value={"kind": engine.KIND_DECKLAB}),
            mock.patch.object(engine, "is_current", return_value=True),
            mock.patch.object(engine, "kind_of", return_value=engine.KIND_DECKLAB),
            mock.patch.object(field, "_side_id", side_effect=lambda e, eng: "id-" + e["id"]),
            mock.patch.object(common, "_log"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def summary(self, deck_id):
        return {"id": deck_id, "space": spaces.space_of(deck_id), "title": deck_id,
                "kind": "product" if deck_id.startswith("product/") else "casual",
                "format": "Constructed", "versions": ["target", "owned"], "status": "building"}

    def summary_for(self, deck_id):
        return next((s for s in self.summaries if s["id"] == deck_id), None)

    def entry(self, summary, version="target"):
        if isinstance(summary, str):
            summary = self.summary_for(summary)
        return {"id": summary["id"], "title": summary["title"], "version": version,
                "kind": "casual", "card_sha": hashlib.sha256((summary["id"] + version).encode()).hexdigest()}

    def kwargs(self, space="sample"):
        return {"space": space, "public": lambda owner: owner in self.public_spaces,
                "visible": lambda deck_id: deck_id in self.visible_ids, "product_notes": False}

    def ids(self, entries):
        return {e["id"] for e in entries}

    def test_cli_default_is_still_homes_field_even_for_a_members_entry(self):
        self.assertEqual(self.ids(field.field_lists("Constructed")),
                         {"casual/home", "casual/second", "product/owned", "product/ordered"})
        self.assertEqual(self.ids(field.opponents(self.entry("sample/casual/own"))),
                         {"casual/home", "casual/second", "product/owned", "product/ordered"})

    def test_members_field_has_own_and_public_spaces_but_home_field_does_not_auto_add_them(self):
        self.public_spaces = {"public", "home"}
        self.visible_ids |= {"public/casual/shared", "casual/home", "casual/second", "product/owned"}
        found = field.field_lists("Constructed", **self.kwargs())
        self.assertEqual(self.ids(found), self.visible_ids)
        self.assertNotIn("sample/casual/own", self.ids(field.opponents(self.entry("sample/casual/own"),
                                                                            **self.kwargs())))
        home = field.field_lists("Constructed", **self.kwargs("home"))
        self.assertEqual(self.ids(home), {"casual/home", "casual/second", "product/owned"})

    def test_built_version_and_formats_apply_to_members_too(self):
        own = self.summary_for("sample/casual/second")
        own.update(status="built", built_version="owned")
        self.assertEqual(next(e for e in field.field_lists("Constructed", **self.kwargs())
                              if e["id"] == own["id"])["version"], "owned")
        self.assertEqual(field.field_lists("Commander", **self.kwargs()), [])

    def test_hidden_additions_have_generic_notes_without_looking_up_hidden_decks(self):
        with mock.patch.object(field, "_simulation_edits", return_value=([
                "private/casual/hidden", "missing/casual/hidden"], [])), \
                mock.patch.object(decks, "find_summary", side_effect=AssertionError("hidden lookup")):
            notes = field.field_notes("Constructed", **self.kwargs())
        self.assertEqual(notes, ["A simulation.json field addition isn't visible and was skipped."] * 2)

    def test_simulation_add_must_be_in_the_base_space_or_a_public_space(self):
        # A viewer's private deck still doesn't belong in someone else's field.
        with mock.patch.object(field, "_simulation_edits", return_value=(["sample/casual/own"], [])):
            self.assertEqual(field.field_lists("Constructed", **self.kwargs("home")), [])
            self.assertEqual(len(field.field_notes("Constructed", **self.kwargs("home"))), 1)

    def test_hidden_errors_and_product_provenance_notes_do_not_reach_outsiders(self):
        self.summary_for("private/casual/hidden")["error"] = HIDDEN
        with mock.patch.object(field.card_pool, "read_status", side_effect=ValueError(HIDDEN)):
            self.assertEqual(field.field_notes("Constructed", **self.kwargs()), [])
            self.assertIn(HIDDEN, " ".join(field.field_notes("Constructed")))
        self.visible_ids.add("product/owned")
        self.public_spaces.add("home")
        with mock.patch.object(field, "_simulation_edits", return_value=(["product/owned@bad"], [])):
            self.assertEqual(field.field_notes("Constructed", **self.kwargs()), [])

    def test_plan_and_view_drop_hidden_results_before_counts_and_average(self):
        own, second = self.entry("sample/casual/own"), self.entry("sample/casual/second")
        self.fake.add_games(own, second, 200, rate=0.9)
        kwargs = dict(self.kwargs(), keep=lambda result: False)
        planned = field.plan(own, "quick", self.results, **kwargs)
        self.assertEqual(planned["new_games"], 200)
        self.assertEqual(planned["pairs"][0]["have"], 0)
        shown = field.view(own, self.results, **kwargs)
        self.assertEqual(shown["opponents"][0]["games"], 0)
        self.assertIsNone(shown["average"])
        self.assertIsNone(shown["rating"])

    def test_rating_uses_only_visible_field_members_and_excludes_hidden_bridge(self):
        own, second = self.entry("sample/casual/own"), self.entry("sample/casual/second")
        hidden = self.entry("private/casual/hidden")
        self.fake.add_games(own, hidden, 200)
        self.fake.add_games(hidden, second, 200)
        # keep alone accepts all saved results: field membership must still stop
        # the private bridge from linking two otherwise unconnected lists.
        shown = field.view(own, self.results, **dict(self.kwargs(), keep=lambda result: True))
        self.assertIsNone(shown["rating"])
        self.assertNotIn(HIDDEN, json.dumps(shown))
        self.fake.add_games(own, second, 200)
        shown = field.view(own, self.results, **dict(self.kwargs(), keep=lambda result: True))
        self.assertIsNotNone(shown["rating"])
        self.assertEqual(shown["rating"]["connected"], 2)

    def test_note_namespaces_and_home_only_legacy_fallback(self):
        own = self.entry("sample/casual/own")
        folder = self.results / "field"
        folder.mkdir()
        legacy = folder / f"{own['card_sha']}-Constructed.json"
        legacy.write_text(json.dumps({"runs": [{"by": "legacy", "deck": field._who(own)}]}))
        self.assertEqual(field.last_note(own, self.results)["by"], "legacy")
        self.assertIsNone(field.last_note(own, self.results, space="sample"))
        field._append_note(own, self.results, {"by": "member", "deck": field._who(own)}, space="sample")
        self.assertEqual(field.last_note(own, self.results, space="sample")["by"], "member")
        self.assertEqual(field.last_note(own, self.results)["by"], "legacy")
        self.assertTrue(field._notes_path(own, self.results, space="sample").name.endswith("-sample.json"))

    def test_stored_note_is_refiltered_after_a_space_becomes_private(self):
        own, second = self.entry("sample/casual/own"), self.entry("sample/casual/second")
        visible = self.fake.add_games(own, second, 20)
        hidden = self.fake.add_games(own, self.entry("private/casual/hidden"), 20)
        field._append_note(own, self.results, {"deck": field._who(own), "planned": 40, "played": 40,
                           "wall_s": 4, "error": HIDDEN,
                           "per_opponent": {visible["key"]: 20, hidden["key"]: 20},
                           "dropped": {hidden["key"]: HIDDEN}}, space="sample")
        note = field.last_note(own, self.results, space="sample", keep=lambda result: result != hidden)
        self.assertEqual(note["per_opponent"], {visible["key"]: 20})
        self.assertEqual(note["dropped"], {})
        for key in ("planned", "played", "wall_s", "error"):
            self.assertNotIn(key, note)
        self.assertNotIn(HIDDEN, json.dumps(note))
        self.assertEqual(len(field.last_note(own, self.results, space="sample")["per_opponent"]), 2)

    def test_run_uses_member_opponents_and_writes_member_note_without_real_forge(self):
        own = self.entry("sample/casual/own")
        note = field.run_field(own, budget=2, by="Member", pool=object(), results_dir=self.results,
                               **self.kwargs())
        self.assertEqual(note["played"], 2)
        self.assertEqual([call[0] for call in self.fake.calls], ["sample/casual/second"])
        self.assertEqual(field.last_note(own, self.results, space="sample"), note)
        self.assertIsNone(field.last_note(own, self.results))


if __name__ == "__main__":
    unittest.main()
