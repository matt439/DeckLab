"""Ranking identity reads use fixtures only and cannot deploy, set up or persist caches."""
import contextlib
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from decklab.lib.forge import common, engine, field, install, overrides, saved, simjar, views

REAL_USER_DIR_FOR = overrides.user_dir_for
REAL_INTENDED = overrides._intended


class ReadOnlyEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.forge = self.root / "forge"
        self.forge.mkdir()
        (self.forge / "fixture.jar").write_bytes(b"fixture jar, never executed")
        (self.forge / install.SCRIPTS_ZIP).parent.mkdir(parents=True)
        (self.forge / install.SCRIPTS_ZIP).write_bytes(b"fixture scripts")
        self.user = self.data / "user"
        cards = self.user / overrides.CUSTOM_CARDS
        cards.mkdir(parents=True)
        (cards / "fixture.txt").write_text("Name:Fixture Card\nA:fixture\n", encoding="utf-8")
        self.source = self.root / "fixture-source.txt"
        self.source.write_bytes((cards / "fixture.txt").read_bytes())
        self.settings = {"forge_dir": str(self.forge), "forge_java": "fixture-java", "forge_clock_s": 120,
                         "forge_workers": 2}
        self.ready = {"ready": True, "problem": None}
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for patch in (
                mock.patch.object(common, "DATA_DIR", self.data),
                mock.patch.object(common, "_settings", lambda: dict(self.settings)),
                mock.patch.object(install, "_find_jar", return_value=("fixture.jar", "fixture-v")),
                mock.patch.object(install, "find_java", return_value=self.root / "fixture-java"),
                mock.patch.object(simjar, "forge_build", return_value="fixture-build"),
                mock.patch.object(simjar, "readiness", side_effect=lambda *args: dict(self.ready)),
                mock.patch.object(engine, "_read_ai", return_value=({"Default": "d" * 64}, {"Default": "d" * 64})),
                mock.patch.object(engine, "_jar_patches", return_value=["fixture-game-patch"]),
                mock.patch.object(engine, "_recall", return_value={"ai": {"Default": "d" * 64},
                                                                  "game_patches": ["remembered-patch"]}),
                mock.patch.object(overrides, "adopted", return_value=["fixture-set"]),
                mock.patch.object(overrides, "_intended", return_value=(
                    {"fixture.txt": (self.source, "Fixture Card")}, [], [])),
                mock.patch.object(install, "_setup", side_effect=AssertionError("setup during read")),
                mock.patch.object(install, "status", side_effect=AssertionError("status during read")),
                mock.patch.object(install, "_run_user_dir", side_effect=AssertionError("run folder during read")),
                mock.patch.object(install, "_remember_version", side_effect=AssertionError("version cache write")),
                mock.patch.object(engine, "_remember", side_effect=AssertionError("engine cache write")),
                mock.patch.object(overrides, "ensure_deployed", side_effect=AssertionError("deployment during read")),
                mock.patch.object(overrides, "user_dir_for", side_effect=AssertionError("folder creation during read")),
                mock.patch.object(common, "_write_atomic", side_effect=AssertionError("persistent write during read"))):
            stack.enter_context(patch)

    def contents(self):
        return {p.relative_to(self.root).as_posix(): (p.stat().st_mtime_ns, p.read_bytes())
                for p in self.root.rglob("*") if p.is_file()}

    def test_actual_decklab_identity_reads_existing_deployment_without_writes(self):
        before = self.contents()
        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("mkdir during read")):
            found = engine.read_only_today()
        self.assertEqual(found["kind"], engine.KIND_DECKLAB)
        self.assertTrue(found["complete"])
        self.assertEqual(found["forge"], "fixture-v")
        self.assertEqual(found["game_patches"], ["fixture-game-patch"])
        self.assertIn("Fixture Card", found["deployed"]["index"])
        self.assertEqual(self.contents(), before)
        self.assertFalse((self.data / engine.REMEMBERED).exists())
        self.assertFalse((self.data / install.VERSION_FILE).exists())

    def test_actual_plain_kind_is_used_when_card_log_is_not_ready(self):
        self.ready["ready"] = False
        found = engine.read_only_today()
        self.assertEqual(found["kind"], engine.KIND_PLAIN)
        self.assertTrue(found["complete"])
        self.assertEqual(found["game_patches"], [])

    def test_missing_java_or_scripts_never_claims_card_log_readiness(self):
        with mock.patch.object(install, "find_java", return_value=None), \
                mock.patch.object(simjar, "readiness", side_effect=AssertionError("no runnable Forge")):
            self.assertEqual(engine.read_only_today()["kind"], engine.KIND_PLAIN)
        (self.forge / install.SCRIPTS_ZIP).unlink()
        with mock.patch.object(simjar, "readiness", side_effect=AssertionError("no runnable Forge")):
            self.assertEqual(engine.read_only_today()["kind"], engine.KIND_PLAIN)

    def test_game_patch_knob_is_respected_without_changing_actual_kind(self):
        self.settings["forge_game_patches"] = False
        found = engine.read_only_today()
        self.assertEqual(found["kind"], engine.KIND_DECKLAB)
        self.assertEqual(found["game_patches"], [])

    def test_missing_performance_folder_is_unknown_and_never_uses_real_folder(self):
        self.settings["forge_performance_mode"] = False
        before = self.contents()
        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("mkdir during read")):
            found = engine.read_only_today()
        self.assertFalse(found["complete"])
        self.assertEqual(found["deployed"], {"user_dir": "", "index": {}, "hash": engine.UNREADABLE_OVERRIDES})
        self.assertEqual(self.contents(), before)
        self.assertFalse((self.data / overrides.USERS).exists())

    def test_existing_performance_folder_requires_its_exact_manifest(self):
        self.settings["forge_performance_mode"] = False
        want = {"sets": ["fixture-set"], "performance_mode": False}
        folder = self.data / overrides.USERS / f"exp-{engine._sha(want)[:12]}"
        folder.mkdir(parents=True)
        manifest = folder / overrides.MANIFEST
        manifest.write_text(json.dumps(want), encoding="utf-8")
        before = self.contents()
        with mock.patch.object(overrides, "load_sets", return_value={"sets": {"fixture-set": {}}}):
            self.assertEqual(REAL_USER_DIR_FOR(want["sets"], performance_mode=False), folder)
        with mock.patch.object(overrides, "_intended", return_value=({}, [], [])):
            found = engine.read_only_today()
        self.assertTrue(found["complete"])
        self.assertFalse(found["performance_mode"])
        self.assertEqual(found["deployed"]["user_dir"], str(folder))
        self.assertEqual(found["deployed"]["index"], {})
        self.assertEqual(self.contents(), before)
        manifest.write_text(json.dumps({**want, "sets": ["different"]}), encoding="utf-8")
        self.assertFalse(engine.read_only_today()["complete"])

    def test_absent_default_folder_is_unknown_without_creation(self):
        with mock.patch.object(common, "_user_dir", return_value=self.data / "missing-user"):
            found = engine.read_only_today()
        self.assertFalse(found["complete"])
        self.assertFalse((self.data / "missing-user").exists())

    def test_unreadable_patches_use_read_only_remembered_identity(self):
        with mock.patch.object(engine, "_jar_patches", return_value=None):
            found = engine.read_only_today()
        self.assertEqual(found["game_patches"], ["remembered-patch"])
        self.assertTrue(found["complete"])
        with mock.patch.object(engine, "_jar_patches", return_value=None), \
                mock.patch.object(engine, "_recall", return_value={}):
            self.assertFalse(engine.read_only_today()["complete"])

    def test_version_read_only_option_does_not_update_disk_or_memory(self):
        known = {}
        with mock.patch.object(install, "_known", known):
            self.assertEqual(install.forge_version(remember=False), "fixture-v")
        self.assertEqual(known, {})
        self.assertFalse((self.data / install.VERSION_FILE).exists())
        # The established default still opts into remembering a newly found version.
        with mock.patch.object(install, "_remember_version") as remember:
            self.assertEqual(install.forge_version(), "fixture-v")
            remember.assert_called_once_with("fixture-v")

    def assert_identity_unknown_without_writes(self, words):
        before = self.contents()
        found = engine.read_only_today()
        self.assertFalse(found["complete"])
        self.assertIn(words, found["identity_problem"])
        self.assertNotIn(str(self.root), found["identity_problem"])
        self.assertEqual(self.contents(), before)

    def test_pending_adoption_is_unknown_until_its_physical_override_is_deployed(self):
        (self.user / overrides.CUSTOM_CARDS / "fixture.txt").unlink()
        self.assert_identity_unknown_without_writes("files differ")

    def test_changed_physical_override_is_unknown_without_repairing_it(self):
        (self.user / overrides.CUSTOM_CARDS / "fixture.txt").write_text("Name:Fixture Card\nA:changed\n", encoding="utf-8")
        self.assert_identity_unknown_without_writes("contents differ")

    def test_extra_physical_override_is_unknown_because_next_deploy_removes_it(self):
        (self.user / overrides.CUSTOM_CARDS / "extra.txt").write_text("Name:Another Card\n", encoding="utf-8")
        self.assert_identity_unknown_without_writes("files differ")

    def test_identical_contents_under_a_different_filename_are_not_current(self):
        folder = self.user / overrides.CUSTOM_CARDS
        (folder / "fixture.txt").rename(folder / "other.txt")
        self.assert_identity_unknown_without_writes("files differ")

    def test_missing_intended_source_is_unknown_without_guessing(self):
        self.source.unlink()
        self.assert_identity_unknown_without_writes("sources could not be read")

    def test_unknown_upstream_source_prevents_a_complete_identity(self):
        with mock.patch.object(overrides, "_intended", return_value=({}, [], ["Fixture Card"])):
            self.assert_identity_unknown_without_writes("source scripts could not be confirmed")

    def test_unreadable_intended_sets_are_an_explicit_identity_problem(self):
        with mock.patch.object(overrides, "_intended", side_effect=ValueError("private absolute path")):
            self.assert_identity_unknown_without_writes("sets could not be read")

    def test_upstream_check_reads_new_source_without_remembering_disk_or_memory(self):
        raw = b"Name:Fixture Card\nA:upstream\n"
        with zipfile.ZipFile(self.forge / install.SCRIPTS_ZIP, "w") as bundle:
            bundle.writestr("f/fixture.txt", raw)
        cached = {"versions": {"fixture-v": {"last": "fixture-build", "builds": {"fixture-build": {}}}}}
        before = json.dumps(cached, sort_keys=True)
        with mock.patch.object(overrides, "_upstream_data", return_value=cached), \
                mock.patch.object(overrides, "_note_upstream", side_effect=AssertionError("upstream cache write")):
            shas, unknown = overrides._upstream({"Fixture Card": "fixture.txt"}, remember=False)
        self.assertEqual(shas, {"Fixture Card": hashlib.sha256(raw).hexdigest()})
        self.assertEqual(unknown, [])
        self.assertEqual(json.dumps(cached, sort_keys=True), before)
        self.assertFalse((self.data / overrides.UPSTREAM_FILE).exists())

    def test_stale_upstream_excludes_intended_override_but_retained_file_is_not_current(self):
        raw = b"Name:Fixture Card\nA:upstream\n"
        with zipfile.ZipFile(self.forge / install.SCRIPTS_ZIP, "w") as bundle:
            bundle.writestr("f/fixture.txt", raw)
        chosen = {"Fixture Card": ("fixture-set", "fixture.txt", {"upstream_sha256": "0" * 64})}
        with mock.patch.object(overrides, "_chosen", return_value=chosen), \
                mock.patch.object(overrides, "_upstream_data", return_value={"versions": {}}), \
                mock.patch.object(overrides, "_note_upstream", side_effect=AssertionError("upstream cache write")):
            intended = REAL_INTENDED(["fixture-set"], remember=False)
        self.assertEqual(intended, ({}, ["Fixture Card"], []))
        with mock.patch.object(overrides, "_intended", return_value=intended):
            self.assert_identity_unknown_without_writes("files differ")
            (self.user / overrides.CUSTOM_CARDS / "fixture.txt").unlink()
            self.assertTrue(engine.read_only_today()["complete"])

    def test_default_intended_and_upstream_calls_keep_existing_argument_patterns(self):
        with mock.patch.object(overrides, "_chosen", return_value={}), \
                mock.patch.object(overrides, "_upstream", return_value=({}, [])) as upstream:
            self.assertEqual(REAL_INTENDED([]), ({}, [], []))
            upstream.assert_called_once_with({})
        raw = b"Name:Fixture Card\n"
        with mock.patch.object(overrides, "_upstream_data", return_value={"versions": {}}), \
                mock.patch.object(overrides, "_zip_scripts", return_value={"fixture.txt": ("Fixture Card", raw)}), \
                mock.patch.object(overrides, "_note_upstream") as remember:
            overrides._upstream({"Fixture Card": "fixture.txt"})
            remember.assert_called_once()


class ExplicitRankingEngineTests(unittest.TestCase):
    def setUp(self):
        self.eng = engine._engine(engine.KIND_DECKLAB, "fixture-v", 120, [],
                                  {"user_dir": "fixture", "index": {}, "hash": "none"},
                                  {"Default": "d" * 64}, True)
        self.sides = [{"card_sha": n * 64, "kind": "constructed", "ai": "Default",
                       "cards": {"Commander": [], "Main": [[1, f"Card {n}"]]}} for n in ("a", "b")]
        for side in self.sides:
            side["engine_id"] = engine.entry_side_id(side, eng=self.eng)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(engine, "today", side_effect=AssertionError("today during explicit read")))
        stack.enter_context(mock.patch.object(engine, "is_current", side_effect=AssertionError("is_current during explicit read")))
        stack.enter_context(mock.patch.object(views, "_not_meaningful", return_value=False))
        stack.enter_context(mock.patch.object(field, "_games", side_effect=lambda r: r["games"]))

    def result(self, **changes):
        result = {"format": "Constructed", "engine": engine._fields(self.eng), "sides": self.sides, "run_version": 2,
                  "key": engine.key(*self.sides, self.eng),
                  "games": [{"w": 0, "first": 0}, {"w": 1, "first": 1}, {"w": None, "first": 0}]}
        result.update(changes)
        return result

    def test_explicit_snapshot_counts_only_matching_current_engine(self):
        current = self.result()
        old = self.result(key=engine.key(*self.sides, {**self.eng, "clock_s": 90}))
        wrong_format = self.result(format="Commander")
        paired = self.result(kind="paired")
        mirror = self.result(sides=[self.sides[0], self.sides[0]])
        with mock.patch.object(saved, "_stored", return_value=[current, old, wrong_format, paired, mirror]):
            data = field._bt_data("Constructed", None, current_engine=self.eng)
        self.assertEqual(sum(v[1] for v in data.values()), 2)
        self.assertEqual(sum(v[0] for v in data.values()), 1)

    def test_incomplete_or_plain_snapshot_never_reads_results(self):
        with mock.patch.object(saved, "_stored", side_effect=AssertionError("not a usable decklab identity")):
            for eng in ({**self.eng, "complete": False}, {**self.eng, "kind": engine.KIND_PLAIN}):
                self.assertEqual(field._bt_data("Constructed", None, current_engine=eng), {})

    def test_default_legacy_path_still_uses_is_current(self):
        with mock.patch.object(saved, "_stored", return_value=[self.result()]), \
                mock.patch.object(engine, "is_current", return_value=True) as current:
            data = field._bt_data("Constructed", None)
        self.assertEqual(sum(v[1] for v in data.values()), 2)
        current.assert_called_once()


if __name__ == "__main__":
    unittest.main()
