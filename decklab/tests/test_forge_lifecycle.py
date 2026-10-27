"""Disposable OS-claim and durable-guard checks; never starts Forge."""
import json
import inspect
import stat
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from decklab.lib.forge import lifecycle
from decklab.lib.forge import adaptive, cli_results, experiment, field, runner, variants
from decklab.tests.test_forge_runhooks import KEY, assert_lock_given_up, v2_result


CHILD = """
import sys
from decklab.lib.forge import lifecycle
try:
    with getattr(lifecycle, sys.argv[2])(sys.argv[1]):
        print('claimed', flush=True)
        if len(sys.argv) > 3:
            sys.stdin.readline()
except lifecycle.LifecycleError as error:
    print(str(error), flush=True)
"""


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "results"

    def child(self, mode, root=None):
        done = subprocess.run([sys.executable, "-c", CHILD, str(root or self.root), mode],
                              capture_output=True, text=True, timeout=15)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def departed(self, spaces):
        with lifecycle.maintenance(self.root) as claim:
            (claim.control_dir / "departed.json").write_text(
                json.dumps({"version": 1, "spaces": spaces}), encoding="utf-8")

    def test_capability_is_canonical_and_read_only(self):
        value = lifecycle.capability(self.root / ".." / "results")
        self.assertEqual(value, {"version": 1, "root": str(self.root.resolve())})
        self.assertFalse(self.root.exists())
        self.assertFalse(self.root.with_name(".results-lifecycle").exists())

    def test_shared_claims_coexist_but_exclude_maintenance_across_processes(self):
        with lifecycle.writer(self.root):
            self.assertEqual(self.child("writer"), "claimed")
            self.assertEqual(self.child("maintenance"), lifecycle.BUSY)
        self.assertEqual(self.child("maintenance"), "claimed")

    def test_maintenance_excludes_both_modes_across_processes(self):
        with lifecycle.maintenance(self.root):
            self.assertEqual(self.child("writer"), lifecycle.BUSY)
            self.assertEqual(self.child("maintenance"), lifecycle.BUSY)

    def test_crashed_writer_releases_os_claim(self):
        child = subprocess.Popen([sys.executable, "-c", CHILD, str(self.root), "writer", "hold"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "claimed")
            self.assertEqual(self.child("maintenance"), lifecycle.BUSY)
        finally:
            child.terminate()
            child.communicate(timeout=15)
        self.assertEqual(self.child("maintenance"), "claimed")

    def test_reentrant_canonical_claims_release_only_outermost_handle(self):
        with lifecycle.writer(self.root) as outer:
            with lifecycle.writer(self.root / ".." / "results") as inner:
                self.assertIs(inner, outer)
            self.assertEqual(self.child("maintenance"), lifecycle.BUSY)
            with self.assertRaisesRegex(lifecycle.LifecycleError, "in use"):
                with lifecycle.maintenance(self.root):
                    self.fail("shared claims cannot upgrade")
        with lifecycle.maintenance(self.root) as outer:
            with lifecycle.maintenance(self.root) as inner:
                self.assertIs(inner, outer)
            with lifecycle.writer(self.root) as inner:
                self.assertIs(inner, outer)

    def test_threads_share_read_claims_and_conflict_with_exclusive(self):
        def attempt(mode):
            try:
                with mode(self.root):
                    return "claimed"
            except lifecycle.LifecycleError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with lifecycle.writer(self.root):
                self.assertEqual(pool.submit(attempt, lifecycle.writer).result(), "claimed")
                self.assertEqual(pool.submit(attempt, lifecycle.maintenance).result(), lifecycle.BUSY)

    def test_exception_releases_claim(self):
        with self.assertRaisesRegex(RuntimeError, "stopped"):
            with lifecycle.writer(self.root):
                raise RuntimeError("stopped")
        self.assertEqual(self.child("maintenance"), "claimed")

    def test_pending_journal_blocks_every_writer_but_not_recovery(self):
        with lifecycle.maintenance(self.root) as claim:
            pending = claim.control_dir / "pending"
            pending.mkdir()
            (pending / "interrupted.json").write_text("invalid or incomplete", encoding="utf-8")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "recovery"):
            with lifecycle.writer(self.root):
                self.fail("pending operation must fail closed")
        with lifecycle.maintenance(self.root) as claim:
            self.assertEqual(claim.root, self.root.resolve())

    def test_departed_inputs_and_variant_or_versioned_aliases_refuse(self):
        self.departed(["user2"])
        for deck_id in ("user2/casual/elves", "variant:user2/casual/elves",
                        "user2/casual/elves@1234"):
            with self.subTest(deck_id=deck_id), self.assertRaisesRegex(
                    lifecycle.LifecycleError, "removed member"):
                with lifecycle.writer(self.root, deck_ids=[deck_id]):
                    self.fail("cached or queued removed inputs must refuse")
        with lifecycle.writer(self.root, deck_ids=["casual/elves", "user3/casual/elves"]):
            pass

    def test_malformed_departed_file_fails_closed(self):
        self.departed(["home"])
        with self.assertRaisesRegex(lifecycle.LifecycleError, "checked safely"):
            with lifecycle.writer(self.root):
                pass

    def test_results_and_control_must_be_ordinary_directories(self):
        self.root.write_text("file", encoding="utf-8")
        with self.assertRaises(lifecycle.LifecycleError):
            with lifecycle.writer(self.root):
                pass
        self.root.unlink()
        self.root.with_name(".results-lifecycle").write_text("file", encoding="utf-8")
        with self.assertRaises(lifecycle.LifecycleError):
            with lifecycle.writer(self.root):
                pass

    def test_links_are_checked_before_dotdot_can_hide_them(self):
        raw = self.root / "linked" / ".." / "results"
        with mock.patch.object(lifecycle, "_ordinary", side_effect=lifecycle.LifecycleError(lifecycle.UNSAFE)) as check:
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.root_path(raw)
        check.assert_called_once_with(raw)
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with mock.patch.object(Path, "lstat", return_value=info), self.assertRaises(lifecycle.LifecycleError):
            lifecycle.root_path(self.root)

    def test_provenance_does_not_traverse_card_or_game_evidence(self):
        result = {"sides": [{"seen_as": [{"id": "casual/a"}]},
                             {"seen_as": [{"id": "user2/casual/b"}]}],
                  "games": [{"id": "card-evidence"}], "cards": [{"id": "oracle-id"}]}
        self.assertEqual(lifecycle.references(result), {"casual/a", "user2/casual/b"})

    def test_operation_wrapper_keeps_signature_and_spans_reads_through_writes(self):
        @lifecycle.writing("entry", save="save")
        def operation(entry, *, results_dir=None, save=True):
            return self.child("maintenance")
        self.assertEqual(list(inspect.signature(operation).parameters),
                         ["entry", "results_dir", "save"])
        self.assertEqual(operation({"id": "casual/a"}, results_dir=self.root), lifecycle.BUSY)
        self.assertEqual(operation({"id": "casual/a"}, results_dir=self.root, save=False), "claimed")
        self.departed(["user2"])
        with self.assertRaisesRegex(lifecycle.LifecycleError, "removed member"):
            operation({"id": "user2/casual/a"}, results_dir=self.root)

    def test_all_run_and_note_entrypoints_refuse_pending_before_work(self):
        with lifecycle.maintenance(self.root) as claim:
            pending = claim.control_dir / "pending"
            pending.mkdir()
            (pending / "prepared.json").write_text("{}", encoding="utf-8")
        entry = {"id": "casual/a"}
        calls = [lambda: runner.run(entry, entry, 1, by="Test", results_dir=self.root),
                 lambda: adaptive.run_adaptive(entry, entry, "ahead", by="Test", results_dir=self.root),
                 lambda: field.run_field(entry, by="Test", results_dir=self.root),
                 lambda: variants.run_test(entry, {}, entry, by="Test", results_dir=self.root),
                 lambda: field._append_note(entry, self.root, {"deck": entry}),
                 lambda: variants._write_summary({"base": entry}, self.root),
                 lambda: runner.update_result(KEY, self.root, lambda value: self.fail("callback ran")),
                 lambda: adaptive._update_result(KEY, self.root, lambda value: self.fail("callback ran"))]
        for index, call in enumerate(calls):
            with self.subTest(entrypoint=index), self.assertRaisesRegex(lifecycle.LifecycleError, "recovery"):
                call()

    def test_experiment_claims_before_engine_and_staged_move_before_plan(self):
        with lifecycle.maintenance(self.root) as claim:
            pending = claim.control_dir / "pending"
            pending.mkdir()
            (pending / "prepared.json").write_text("{}", encoding="utf-8")
        spec = {"name": "fixture", "pairs": [["casual/a", "casual/b"]], "arms": {"one": {}},
                "control": {"results_dir": None, "logs_dir": None}}
        with mock.patch.object(experiment, "_spec", return_value=spec), \
                mock.patch.object(experiment, "_run_engine") as engine, \
                self.assertRaisesRegex(lifecycle.LifecycleError, "recovery"):
            experiment.run(spec, by="Test", results_dir=self.root)
        engine.assert_not_called()
        source = Path(self.temp.name) / "staged"
        source.mkdir()
        args = SimpleNamespace(source=source, to=self.root, dry_run=False)
        with mock.patch.object(cli_results, "_staged_plan") as plan, \
                self.assertRaisesRegex(lifecycle.LifecycleError, "recovery"):
            cli_results._cmd_staged_move(args)
        plan.assert_not_called()

    def test_update_keeps_historical_mixed_aliases_but_cannot_add_departed_alias(self):
        self.root.mkdir()
        result = v2_result()
        result["sides"][0]["seen_as"] = [{"id": "user2/casual/old"}]
        path = self.root / f"{KEY}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        self.departed(["user2"])

        def update(value):
            self.assertEqual(self.child("maintenance"), lifecycle.BUSY)
            value["note"] = "survivor's retained result"
        out = runner.update_result(KEY, self.root, update)
        self.assertEqual(out["note"], "survivor's retained result")
        before = path.read_bytes()

        def introduce(value):
            value["sides"][1]["seen_as"] = [{"id": "user2/casual/new"}]
        for updater in (runner.update_result, adaptive._update_result):
            with self.subTest(updater=updater.__name__), self.assertRaisesRegex(
                    lifecycle.LifecycleError, "removed member"):
                updater(KEY, self.root, introduce)
            self.assertEqual(path.read_bytes(), before)
            assert_lock_given_up(self, self.root, KEY)

    def test_cached_departed_inputs_never_reach_runner_or_note_work(self):
        self.departed(["user2"])
        entry = {"id": "user2/casual/old"}
        calls = [lambda: runner.run(entry, entry, 1, by="Test", results_dir=self.root),
                 lambda: adaptive.run_adaptive(entry, entry, "ahead", by="Test", results_dir=self.root),
                 lambda: field.run_field(entry, by="Test", results_dir=self.root),
                 lambda: variants.run_test(entry, {}, entry, by="Test", results_dir=self.root),
                 lambda: field._append_note({"id": "casual/a"}, self.root,
                                            {"per_opponent": {entry["id"]: {}}}),
                 lambda: variants._write_summary({"base": entry}, self.root)]
        for index, call in enumerate(calls):
            with self.subTest(entrypoint=index), self.assertRaisesRegex(lifecycle.LifecycleError, "removed member"):
                call()

    def test_experiment_holds_all_actual_result_roots_until_final_report(self):
        control = Path(self.temp.name) / "external-controls"
        spec = {"name": "fixture", "pairs": [["casual/a", "casual/b"]], "arms": {"one": {}},
                "control": {"results_dir": str(control), "logs_dir": None}}

        def finish(*args, **kwargs):
            for root in (self.root, self.root / experiment.CONTROL, self.root / "one", control):
                self.assertEqual(self.child("maintenance", root), lifecycle.BUSY)
            return {"finished": True}
        with mock.patch.object(experiment, "_spec", return_value=spec), \
                mock.patch.object(experiment, "_run_claimed", side_effect=finish):
            self.assertEqual(experiment.run(spec, by="Test", results_dir=self.root), {"finished": True})
        self.assertEqual(self.child("maintenance", control), "claimed")

    def test_staged_import_validates_whole_batch_before_first_move(self):
        from decklab.lib.forge import overrides
        source = Path(self.temp.name) / "staged"
        source.mkdir()
        self.departed(["user2"])
        good, bad = v2_result(), v2_result()
        bad["sides"][0]["seen_as"] = [{"id": "user2/casual/old"}]
        (source / "good.json").write_text(json.dumps(good), encoding="utf-8")
        (source / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
        plan = {"move": [{"file": "good.json"}, {"file": "bad.json"}], "notes": []}
        args = SimpleNamespace(source=source, to=self.root, dry_run=False, hold=None)
        with mock.patch.object(cli_results, "_staged_plan", return_value=plan), \
                mock.patch.object(overrides, "ensure_deployed"), \
                mock.patch.object(cli_results.shared.engine, "today"), \
                mock.patch.object(cli_results.shared.pool, "services", return_value=[]), \
                mock.patch.object(cli_results, "_staged_move_file") as move, \
                self.assertRaisesRegex(lifecycle.LifecycleError, "removed member"):
            cli_results._cmd_staged_move(args)
        move.assert_not_called()
        self.assertTrue((source / "good.json").exists())


if __name__ == "__main__":
    unittest.main()
