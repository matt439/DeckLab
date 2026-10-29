"""Pure member-removal previews: no database, service, real Forge or live data."""
import copy
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from decklab.db import space_export, space_forge, space_remove

SPACE = "sample"
SECRET = "OTHER-SPACE-PRIVATE-SENTINEL"


def side(deck_id):
    return {"id": deck_id, "version": "target", "title": deck_id, "sections": {"Deck": [{"name": deck_id}]},
            "sha256": "a" * 64, "player": deck_id, "mulligans": 1, "plan_id": "b" * 32}


def row(kind="games", own=True, recorder="home"):
    return {"kind": kind, "id": "a" * 32, "revision": 1, "updated_by": "Member", "deck_ids": [],
            "content": {"sides": [side("sample/casual/own"), side("casual/other" if own else "sample/casual/second")],
                        "space": recorder, "notes": SECRET, "result": "a", "date": "2026-10-18"}}


def forge_result(key, a="sample/casual/one", b="sample/casual/two"):
    return {"key": key, "format": "Constructed", "batches": [], "runs": [],
            "sides": [{"card_sha": "c" * 64, "dck": "", "kind": "constructed", "card_count": 60,
                       "seen_as": [{"id": deck_id}]} for deck_id in (a, b)]}


class RecordTransformTests(unittest.TestCase):
    def test_mixed_game_keeps_other_side_exactly_and_removes_every_member_side_field(self):
        before = row()
        original = copy.deepcopy(before)
        after = space_remove.transformed_record(SPACE, before)
        self.assertEqual(before, original)
        self.assertEqual(after["content"]["sides"][0], space_remove.REMOVED)
        self.assertEqual(after["content"]["sides"][1], before["content"]["sides"][1])
        self.assertEqual(after["content"]["notes"], SECRET)
        self.assertEqual(after["content"]["space"], "home")
        self.assertEqual(after["deck_ids"], ["casual/other"])
        self.assertEqual(after["updated_by"], "someone")

    def test_removed_recorders_notes_go_but_date_and_result_survive(self):
        before = row(recorder=SPACE)
        after = space_remove.transformed_record(SPACE, before)
        self.assertEqual(after["content"]["notes"], "")
        self.assertEqual(after["content"]["space"], "")
        self.assertEqual(after["content"]["date"], before["content"]["date"])
        self.assertEqual(after["content"]["result"], before["content"]["result"])

    def test_old_recording_space_rule_preserves_home_notes(self):
        before = row()
        before["content"].pop("space")
        self.assertEqual(space_remove.transformed_record(SPACE, before)["content"]["notes"], SECRET)
        before["content"]["sides"][1] = side("other/casual/keep")
        self.assertEqual(space_remove.transformed_record(SPACE, before)["content"]["notes"], "")

    def test_own_only_game_and_own_plan_are_deleted(self):
        self.assertIsNone(space_remove.transformed_record(SPACE, row(own=False)))
        plan = row(kind="sideboards")
        plan["content"] = {"deck": side("sample/casual/own"), "opponent": side("casual/other")}
        self.assertIsNone(space_remove.transformed_record(SPACE, plan))

    def test_sequential_removal_deletes_the_game_when_its_final_side_goes(self):
        first = space_remove.transformed_record(SPACE, row())
        # The final side is home in this fixture; use another member so the
        # pure helper still observes the member-only removal boundary.
        first["content"]["sides"][1] = side("other/casual/last")
        self.assertIsNone(space_remove.transformed_record("other", first))

    def test_a_member_literally_named_removed_is_distinct_from_a_tombstone(self):
        before = row()
        before["content"]["sides"][1] = side("removed/casual/keep")
        after = space_remove.transformed_record(SPACE, before)
        self.assertIsNotNone(after)
        self.assertEqual(after["deck_ids"], ["removed/casual/keep"])

    def test_other_owners_plan_keeps_deck_moves_notes_and_after_only_opponent_is_removed(self):
        plan = row(kind="sideboards")
        plan["content"] = {"deck": side("casual/other"), "opponent": side("sample/casual/own"),
                           "in": [{"qty": 1, "name": "Opt"}], "out": [{"qty": 1, "name": "Shock"}],
                           "after": {"Deck": [{"qty": 1, "name": "Opt"}]}, "notes": SECRET}
        after = space_remove.transformed_record(SPACE, plan)
        self.assertEqual(after["content"]["opponent"], space_remove.REMOVED)
        for key in ("deck", "in", "out", "after", "notes"):
            self.assertEqual(after["content"][key], plan["content"][key])

    def test_damaged_records_are_refused(self):
        for value in ({"kind": "future", "content": {}}, {"kind": "games", "content": {}},
                      {"kind": "games", "content": {"sides": [{}, {}]}}):
            with self.assertRaises(ValueError):
                space_remove.transformed_record(SPACE, value)

    def test_row_plan_enumerates_child_rows_and_redaction_separately(self):
        data = {"imports": [{"id": 3}], "decks": [{"id": "sample/casual/own"}],
                "texts": [{"deck_id": "sample/casual/own"}],
                "history": [{"deck_id": "sample/casual/own", "revision": 1}],
                "play_records": [row()]}
        rows, retained = space_remove.row_plan(SPACE, data)
        self.assertEqual({r["table"] for r in rows},
                         {"collection_import", "collection_import_content", "deck", "deck_text", "deck_revision", "play_record"})
        self.assertEqual(next(r for r in rows if r["table"] == "play_record")["action"], "redact")
        self.assertEqual(len(retained), 1)

    def test_drafts_kept_for_later_are_listed_by_key_without_their_contents(self):
        draft = {"profile_id": SPACE, "deck_id": "sample/casual/own", "version": "target", "revision": 2,
                 "device": "iPad", "content": {"notes": SECRET}}
        rows, _ = space_remove.row_plan(SPACE, {"drafts": [draft]})
        self.assertEqual(rows, [{"table": "deck_draft", "action": "delete",
                                 "key": {"profile_id": SPACE, "deck_id": "sample/casual/own", "version": "target"}}])

    def test_every_table_hanging_off_a_profile_or_deck_is_locked_and_deleted_explicitly(self):
        # A cascade alone would delete a member's rows outside the export, the preview and the locks.
        from decklab.db import migrate, space_apply
        found = set()
        for path in sorted(migrate.MIGRATIONS.glob("*.sql")):
            sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
            for name, body in re.findall(r"(?is)create table\s+([\w.]+)\s*\((.*?)\n\);", sql):
                if re.search(r"(?i)references\s+(profile|deck)\b(?!_)", body):
                    found.add(name if "." in name else f"public.{name}")
            for name in re.findall(r"(?i)alter table\s+([\w.]+)\s+add foreign key[^;]*references\s+(?:profile|deck)\b(?!_)", sql):
                found.add(name if "." in name else f"public.{name}")
        self.assertIn("public.deck_draft", found)
        self.assertLessEqual(found, set(space_apply.LOCK_TABLES))
        tables = {table for table, _ in space_remove._TABLE_KEYS.values()}
        for table in found:
            with self.subTest(table=table):
                bare = table.removeprefix("public.")
                self.assertIn(bare, tables)
                self.assertIn(bare, space_apply.DELETE_ORDER)
        order = space_apply.DELETE_ORDER
        self.assertLess(order.index("deck_draft"), order.index("deck"))
        self.assertLess(order.index("deck_draft"), order.index("profile"))


class ForgeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="decklab-space-forge-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, rel, value):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def result(self, key, a="sample/casual/one", b="sample/casual/two"):
        return forge_result(key, a, b)

    def test_only_wholly_member_results_are_selected_all_seen_as_entries_count(self):
        own, mixed, unknown, alias = [ch * 64 for ch in "abcd"]
        self.write(own + ".json", self.result(own))
        self.write(mixed + ".json", self.result(mixed, b="casual/home"))
        self.write(unknown + ".json", {"key": unknown})
        value = self.result(alias)
        value["sides"][0]["seen_as"].append({"id": "other/casual/old"})
        self.write(alias + ".json", value)
        files, meta = space_forge.snapshot(SPACE, self.root)
        self.assertEqual(set(files), {own + ".json"})
        self.assertEqual(set(meta["selected"]), set(files))
        self.assertEqual(meta["preserved_related"], 2)
        self.assertEqual(meta["unknown"], 1)

    def test_member_variants_and_scoped_fields_require_own_opponents(self):
        key = "a" * 64
        self.write(key + ".json", self.result(key))
        note = {"runs": [{"deck": {"id": "sample/casual/one"}, "per_opponent": {key: 5}}]}
        self.write("field/sha-Constructed-sample.json", note)
        self.write("field/sha-Constructed.json", note)
        self.write("field/mixed-Constructed-sample.json", {"runs": [
            {"deck": {"id": "sample/casual/one"}, "per_opponent": {"b" * 64: 2}}]})
        variant = {"test": "c" * 64, "version": 1, "base": {"id": "sample/casual/one"},
                   "opponents": [{"id": "sample/casual/two"}], "against": "field:sample:Constructed"}
        self.write("paired/tests/" + "c" * 64 + ".json", variant)
        files, _ = space_forge.snapshot(SPACE, self.root)
        self.assertEqual(set(files), {key + ".json", "field/sha-Constructed-sample.json",
                                     "paired/tests/" + "c" * 64 + ".json"})
        variant["opponents"].append({"id": "other/casual/shared"})
        self.write("paired/tests/" + "c" * 64 + ".json", variant)
        self.assertNotIn("paired/tests/" + "c" * 64 + ".json", space_forge.snapshot(SPACE, self.root)[0])

    def test_variant_side_prefix_is_owned_but_empty_provenance_is_unknown(self):
        key = "a" * 64
        self.write("paired/" + key + ".json", self.result(key, a="variant:sample/casual/one"))
        self.assertEqual(len(space_forge.snapshot(SPACE, self.root)[0]), 1)
        value = self.result(key)
        value["sides"][0]["seen_as"] = []
        self.write("paired/" + key + ".json", value)
        self.assertEqual(space_forge.snapshot(SPACE, self.root)[0], {})

    def test_future_result_kind_is_preserved_as_unknown(self):
        key = "a" * 64
        self.write(key + ".json", dict(self.result(key), kind="future"))
        files, meta = space_forge.snapshot(SPACE, self.root)
        self.assertEqual(files, {})
        self.assertEqual(meta["unknown"], 1)

    def test_unrecorded_current_list_consumers_preserve_results_and_dependent_field_notes(self):
        key = "a" * 64
        value = self.result(key)
        value["sides"][0]["card_sha"] = "d" * 64
        self.write(key + ".json", value)
        self.write("field/sha-Constructed-sample.json", {"runs": [
            {"deck": {"id": "sample/casual/one"}, "per_opponent": {key: 5}}]})
        files, meta = space_forge.snapshot(SPACE, self.root, other_hashes={"d" * 64})
        self.assertEqual(files, {})
        self.assertEqual(meta["preserved_related"], 2)
        self.assertNotIn("d" * 64, json.dumps(meta))

    def test_shared_hash_reader_returns_no_identity_and_matches_forge_canonicalization(self):
        from decklab.lib.forge import lists
        class Cursor:
            def execute(self, sql, params=()):
                if "deck_line" in sql:
                    return [("casual", [["Deck", 4, "Opt"], ["Deck", 56, "Island"]])]
                return [(["name", "quantity", "section"], [["Opt", "4", ""], ["Island", "56", " DeCk: "]], False)]
        expected = lists._list_text({"Main": [[4, "Opt"], [56, "Island"]]}, "constructed")[1]
        self.assertEqual(space_forge.other_list_hashes(Cursor(), SPACE), {expected})

    def test_future_variant_summary_is_preserved(self):
        key = "c" * 64
        self.write("paired/tests/" + key + ".json", {"test": key, "version": 999,
                   "base": {"id": "sample/casual/one"}, "opponents": [{"id": "sample/casual/two"}],
                   "against": "field:sample:Constructed"})
        files, meta = space_forge.snapshot(SPACE, self.root)
        self.assertEqual(files, {})
        self.assertEqual(meta["unknown"], 1)


class PreviewContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="decklab-removal-preview-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.results = self.root / "results"
        self.results.mkdir()
        self.dest = self.root / "export"
        self.data = {"space": [{"id": SPACE}], "play_records": [row()]}
        self.files = {"collection.csv": b"name,set\n", "tokens.csv": b"front,back\n"}
        patcher = mock.patch.object(space_export, "database_snapshot", side_effect=lambda space, dbname=None, details=False:
                                    (self.files, "a" * 64, self.data) if details else (self.files, "a" * 64))
        patcher.start()
        self.addCleanup(patcher.stop)

    def export(self):
        return space_export.export_to(SPACE, self.dest, results_dir=self.results)

    def test_manifest_has_only_forge_hashes_not_raw_json_or_other_metadata(self):
        key = "f" * 64
        raw = dict(forge_result(key), by=SECRET)
        (self.results / (key + ".json")).write_text(json.dumps(raw))
        manifest = self.export()
        self.assertEqual(set(manifest["forge_files"]), {key + ".json"})
        for path in self.dest.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET, path.read_text())
        self.assertEqual(set(manifest["files"]), set(self.files))

    def test_preview_is_read_only_exact_and_refuses_changed_forge_snapshot(self):
        manifest = self.export()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        plan = space_remove.preview(SPACE, self.dest, manifest["snapshot_sha256"], results_dir=self.results)
        self.assertEqual(len(plan["rows"]), 2)
        self.assertEqual(plan["gates"], [space_remove.APPLY_GATE])
        self.assertEqual({p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}, before)
        key = "e" * 64
        (self.results / (key + ".json")).write_text(json.dumps(forge_result(key)))
        with self.assertRaisesRegex(ValueError, "snapshot has changed"):
            space_remove.preview(SPACE, self.dest, manifest["snapshot_sha256"], results_dir=self.results)

    def test_cli_dry_run_lists_keys_without_surviving_private_contents_and_runtime_refusal_is_reported(self):
        from decklab.db.__main__ import main
        from decklab.db import space_apply
        manifest = self.export()
        args = ["space", "remove", SPACE, "--export", str(self.dest), "--expect", manifest["snapshot_sha256"],
                "--results-dir", str(self.results), "-m", "Preview member departure", "--reason", "Member requested"]
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main(args + ["--dry-run", "--json"]), 0)
            with mock.patch.object(space_apply, "apply", side_effect=ValueError("fixture runtime adoption refused")):
                self.assertEqual(main(args), 1)
        shown = json.loads(output.getvalue())
        self.assertNotIn("retained_records", shown)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertIn("runtime adoption refused", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
