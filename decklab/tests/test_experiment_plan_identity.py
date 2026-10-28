"""Explicit read-only experiment identities from fake fork metadata only.

Use scripts/test_fixtures.py; no Java, configured folders, deployment or persistence.
The normal identity is compared with write-producing helpers replaced by recorders.
"""
import contextlib
import json
import unittest
from unittest import mock

from decklab.lib.forge import common, engine, install, overrides, simjar
from decklab.tests import test_forge_rankings_engine as fixtures

JAR = "forge-gui-desktop-2.0.15-jar-with-dependencies.jar"


class ExplicitPlanIdentityTests(unittest.TestCase):
    setUp = fixtures.ReadOnlyEngineTests.setUp
    contents = fixtures.ReadOnlyEngineTests.contents

    def metadata(self, text=None):
        path = self.forge / install.BUILD_FILE
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text, encoding="utf-8")
        # The fake folder's parser cache must follow each stand-in metadata value.
        with install._build_infos_lock:
            install._build_infos.pop(str(path), None)

    def normal(self, kind=engine.KIND_DECKLAB):
        with mock.patch.object(install, "_remember_version") as version, \
                mock.patch.object(engine, "_remember") as remember, \
                mock.patch.object(install, "_run_user_dir", return_value=self.user) as folder:
            found = engine.today(kind)
        version.assert_called_once()
        remember.assert_called_once()
        folder.assert_called_once_with(self.settings.get("forge_performance_mode", True))
        return found

    def pair(self):
        return [{"card_sha": letter * 64, "kind": "constructed",
                 "cards": {"Main": [[1, "Fixture Card"]], "Commander": []},
                 "pilot": {"profile": "Default", "switches": []}}
                for letter in ("a", "b")]

    def preview(self, kind=engine.KIND_DECKLAB):
        before = self.contents()
        with mock.patch("pathlib.Path.mkdir", side_effect=AssertionError("No preview mkdir")), \
                mock.patch.object(simjar, "readiness", side_effect=AssertionError("No readiness probe")), \
                mock.patch.object(engine, "_todays_kind", side_effect=AssertionError("Explicit kind only")):
            found = engine.today(kind, read_only=True)
        self.assertEqual(self.contents(), before)
        self.assertFalse((self.data / engine.REMEMBERED).exists())
        self.assertFalse((self.data / install.VERSION_FILE).exists())
        return found

    def test_stock_resource_fork_and_legacy_fork_match_normal_release_and_control_keys(self):
        examples = [(None, "2.0.15"),
                    ("build=fixture-resource-build\nbase=forge-2.0.15\nres_sha256=" + "1a" * 32 + "\n",
                     "2.0.15+res." + "1a" * 6),
                    ("build=fixture-legacy-fork\n", "fixture-legacy-fork")]
        for text, expected in examples:
            with self.subTest(release=expected), \
                    mock.patch.object(install, "_find_jar", return_value=(JAR, "fixture-v")):
                self.metadata(text)
                normal = self.normal()
                preview = self.preview()
                self.assertTrue(preview["complete"])
                self.assertEqual(preview, normal)
                self.assertEqual(preview["forge"], expected)
                a, b = self.pair()
                self.assertEqual(engine.key(a, b, preview), engine.key(a, b, normal))
                self.assertEqual(engine.key(b, a, preview), engine.key(a, b, normal))

    def test_explicit_decklab_kind_does_not_follow_unavailable_runtime_readiness(self):
        self.metadata("build=fixture-fork\n")
        found = self.preview()
        self.assertTrue(found["complete"])
        self.assertEqual(found["kind"], engine.KIND_DECKLAB)
        self.assertEqual(found["seeds"], engine.seeds.SCHEME)
        self.assertEqual(found["game_patches"], ["fixture-game-patch"])

    def test_explicit_plain_kind_and_disabled_game_patches_keep_normal_keys(self):
        self.metadata("build=fixture-fork\n")
        self.settings["forge_game_patches"] = False
        for kind in (engine.KIND_DECKLAB, engine.KIND_PLAIN):
            with self.subTest(kind=kind):
                normal = self.normal(kind)
                found = self.preview(kind)
                self.assertEqual(found, normal)
                self.assertEqual(found["game_patches"], [])
                self.assertEqual(engine.key(*self.pair(), found), engine.key(*self.pair(), normal))

    def test_no_implicit_kind_can_trigger_readiness_or_settings_reads(self):
        with mock.patch.object(common, "_settings", side_effect=AssertionError("No settings for bad mode")):
            for kind in (None, "unknown", "", False):
                with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "explicit engine kind"):
                    engine.today(kind, read_only=True)

    def test_normal_held_memo_cannot_hide_a_pending_deployment_from_preview(self):
        self.metadata("build=fixture-fork\n")
        with engine.held():
            cached = self.normal()
            (self.user / overrides.CUSTOM_CARDS / "fixture.txt").write_text(
                "Name:Fixture Card\nA:changed\n", encoding="utf-8")
            preview = self.preview()
            self.assertFalse(preview["complete"])
            self.assertIn("contents differ", preview["identity_problem"])
            self.assertIs(engine.today(engine.KIND_DECKLAB), cached)

    def test_missing_performance_folder_is_unknown_without_using_or_creating_real_folder(self):
        self.metadata("build=fixture-fork\n")
        self.settings["forge_performance_mode"] = False
        found = self.preview()
        self.assertFalse(found["complete"])
        self.assertFalse(found["performance_mode"])
        self.assertEqual(found["deployed"], {"user_dir": "", "index": {}, "hash": engine.UNREADABLE_OVERRIDES})
        self.assertNotIn(str(self.root), found["identity_problem"])
        self.assertFalse((self.data / overrides.USERS).exists())

    def test_existing_exact_performance_manifest_is_read_without_a_creator(self):
        self.metadata("build=fixture-fork\n")
        self.settings["forge_performance_mode"] = False
        want = {"sets": ["fixture-set"], "performance_mode": False}
        folder = self.data / overrides.USERS / f"exp-{engine._sha(want)[:12]}"
        cards = folder / overrides.CUSTOM_CARDS
        cards.mkdir(parents=True)
        (folder / overrides.MANIFEST).write_text(json.dumps(want), encoding="utf-8")
        (cards / "fixture.txt").write_bytes(self.source.read_bytes())
        found = self.preview()
        self.assertTrue(found["complete"])
        self.assertEqual(found["deployed"]["user_dir"], str(folder))
        with mock.patch.object(install, "_remember_version"), mock.patch.object(engine, "_remember"), \
                mock.patch.object(install, "_run_user_dir", return_value=folder):
            normal = engine.today(engine.KIND_DECKLAB)
        self.assertEqual(found, normal)

    def test_known_offline_release_uses_read_only_remembered_metadata_without_refreshing_it(self):
        known = {"ai": {"Default": "d" * 64}, "game_patches": ["remembered-patch"],
                 "engine_forge": "2.0.15+res." + "f" * 12}
        with mock.patch.object(install, "forge_version", return_value="offline-fixture") as version, \
                mock.patch.object(install, "_find_jar", return_value=(None, None)), \
                mock.patch.object(engine, "_recall", return_value=known):
            found = self.preview()
        version.assert_called_once_with(remember=False)
        self.assertTrue(found["complete"])
        self.assertEqual(found["forge"], known["engine_forge"])
        self.assertEqual(found["ai_sha"], known["ai"])
        self.assertEqual(found["game_patches"], known["game_patches"])

    def test_unknown_release_upstream_or_deployment_never_claims_complete_identity(self):
        self.metadata("build=fixture-fork\n")
        cases = [((engine, "_recall", {}), (install, "engine_forge", None)),
                 ((overrides, "_intended", ({}, [], ["Fixture Card"])),),
                 ((engine, "_deployed", {"user_dir": str(self.user), "index": {},
                                          "hash": engine.UNREADABLE_OVERRIDES}),)]
        for patches in cases:
            with self.subTest(patches=[name for _, name, _ in patches]), contextlib.ExitStack() as stack:
                for owner, name, value in patches:
                    stack.enter_context(mock.patch.object(owner, name, return_value=value))
                found = self.preview()
                self.assertFalse(found["complete"])
                self.assertTrue(found["identity_problem"])
                self.assertNotIn(str(self.root), found["identity_problem"])
