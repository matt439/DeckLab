"""Reusable review tooling over disposable data; no browser or download is needed."""

import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlsplit


class ReviewRunnerTests(unittest.TestCase):
    def test_card_and_deck_proof_reads_stay_on_the_owned_origin_and_exact_allowlist(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is needed for the fixture proof guard")
        script = r'''
const assert=require('node:assert/strict');const {Review}=require('./decklab/ui_review/common.js');
(async()=>{
  const calls=[],review={origin:'http://127.0.0.1:18643',checkCancelled:()=>{}};
  const context={request:{get:async(url,options)=>{calls.push({url,options});return {ok:()=>true,status:()=>200,json:async()=>({synthetic:true})};}}};
  for(const path of ['/api/deck?id=commander%2Ffixture','/api/cards/lookup?name=Fixture'])
    assert.deepEqual(await Review.prototype.readFixture.call(review,context,path),{synthetic:true});
  for(const path of ['/api/deck/save','/api/collection','//example.com/api/deck','https://example.com/api/deck'])
    await assert.rejects(()=>Review.prototype.readFixture.call(review,context,path));
  assert.equal(calls.length,2);assert(calls.every(call=>call.options.maxRedirects===0&&new URL(call.url).origin===review.origin));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[2],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_telemetry_is_answered_inside_the_browser_guard_without_permitting_writes(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is needed for the browser guard check")
        script = r'''
const assert = require('node:assert/strict');
const {Review} = require('./decklab/ui_review/common.js');
(async () => {
  let handler;
  const context = {on:() => {}, route:async (pattern, value) => {handler = value;}};
  const review = {contexts:new Set(), origin:'http://127.0.0.1:18643',
    report:{network:{blocked:[],allowed_reads:0,dry_checks:0}}, safeUrl:value => new URL(value).pathname};
  await Review.prototype.guardContext.call(review, context);
  async function request(method, url) {
    const events = [];
    await handler({request:() => ({url:() => url,method:() => method}),
      fulfill:async response => events.push(['fulfill',response.status]),
      abort:async reason => events.push(['abort',reason]), continue:async () => events.push(['continue'])});
    return events;
  }
  assert.deepEqual(await request('POST',review.origin+'/api/visit'), [['fulfill',204]]);
  assert.equal(review.report.network.blocked[0].category,'expected_fixture_telemetry');
  assert.deepEqual(await request('POST',review.origin+'/api/collection'), [['abort','blockedbyclient']]);
  assert.deepEqual(await request('POST','https://example.com/api/visit'), [['abort','blockedbyclient']]);
  assert.deepEqual(await request('GET',review.origin+'/app.js'), [['continue']]);
  assert.deepEqual(await request('POST',review.origin+'/api/deck/check'), [['continue']]);
  assert.deepEqual(await request('POST',review.origin+'/api/deck/cuts'), [['continue']]);
  assert.deepEqual(await request('POST',review.origin+'/api/deck/cuts/save'), [['abort','blockedbyclient']]);
  assert.deepEqual(await request('POST',review.origin+'/api/deck/bracket-replacements'), [['continue']]);
  assert.deepEqual(await request('POST',review.origin+'/api/deck/bracket-replacements/save'), [['abort','blockedbyclient']]);
  assert.equal(review.report.network.dry_checks,3);
  assert.equal(review.report.network.allowed_reads,1);
})().catch(error => {console.error(error);process.exitCode=1;});
'''
        result = subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[2],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_strict_console_mode_records_errors_without_relaxing_page_errors(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is needed for the browser observer check")
        script = r'''
const assert = require('node:assert/strict');
const {Review, argumentsFor} = require('./decklab/ui_review/common.js');
for (const strictConsole of [false, true]) {
  const handlers = {}, errors = [];
  const page = {on:(name, callback) => {handlers[name] = callback;}};
  const review = {options:{strictConsole}, safeText: value => value};
  Review.prototype.observe.call(review, page, errors, []);
  handlers.pageerror({message:'Uncaught synthetic failure'});
  assert.deepEqual(errors, ['Uncaught synthetic failure']);
  if (strictConsole) {
    handlers.console({type:() => 'warning', text:() => 'Warning'});
    assert.equal(errors.length, 1);
    handlers.console({type:() => 'error', text:() => 'Synthetic resource or console failure'});
    assert.deepEqual(errors, ['Uncaught synthetic failure', 'Console error: Synthetic resource or console failure']);
  } else assert.equal(handlers.console, undefined);
}
const args = ['--runtime','runtime','--output','output','--run-id','a'.repeat(32),'--browser','browser'];
assert.equal(argumentsFor([...args,'--strict-console']).strictConsole, true);
assert.throws(() => argumentsFor([...args,'--strict-console','--strict-console']));
'''
        result = subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[2],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_spawn_marks_every_supported_browser_for_cleanup_audit(self):
        from decklab.ui_review import runner

        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            with mock.patch.object(runner.subprocess, "Popen") as spawn:
                for suite in runner.SUITES:
                    runner._spawn(["unused-node"], runtime, suite)
                    self.assertTrue((runtime / f"browser-{suite}.started").is_file(), suite)
                runner._spawn(["unused-python"], runtime, "fixture")
            self.assertEqual(spawn.call_count, len(runner.SUITES) + 1)
            self.assertFalse((runtime / "browser-fixture.started").exists())

    def test_replaced_zoom_browsers_require_every_cleanup_proof(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is needed for the browser-helper lifecycle check")
        script = r'''
const assert = require('node:assert/strict');
const path = require('node:path');
const {Review} = require('./decklab/ui_review/common.js');
(async () => {
  for (const [replacements, expected] of [
    [undefined, true], [[{started:true, closed:true}], true],
    [[{started:true, closed:false}, {started:true, closed:true}], false],
    [[{started:false, closed:true}], false],
  ]) {
    process.exitCode = 0;
    const review = {suite:'zoom', contexts:new Set(), browser:{isConnected:() => false, close:async () => {}},
      config:{profileControl:path.join(process.argv[1],'profile.txt'),
        caseControl:path.join(process.argv[1],'case.txt')},
      originalProfile:'matt', originalCase:'complete', save:() => {},
      report:{completed:true, zoomBrowsers:replacements, cleanup:{cancelled:false}}};
    await Review.prototype.finish.call(review);
    assert.equal(review.report.browser_closed, expected);
    assert.equal(review.report.completed, expected);
    assert.equal(process.exitCode, expected ? 0 : 1);
  }
  process.exitCode = 0;
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
        with tempfile.TemporaryDirectory() as runtime:
            result = subprocess.run([node, "-e", script, runtime],
                                    cwd=Path(__file__).resolve().parents[2],
                                    text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_source_fingerprint_failure_never_leaves_a_private_runtime(self):
        from decklab.ui_review import runner

        created = []
        real_mkdtemp = tempfile.mkdtemp

        def track_runtime(*args, **kwargs):
            path = Path(real_mkdtemp(*args, **kwargs))
            created.append(path)
            self.addCleanup(shutil.rmtree, path, True)
            return str(path)

        with tempfile.TemporaryDirectory() as outer:
            output = runner.prepare_output(Path(outer) / "evidence")
            with mock.patch.object(runner.tempfile, "mkdtemp", side_effect=track_runtime), \
                    mock.patch.object(runner, "_source_state", side_effect=OSError("Synthetic source read failed")), \
                    mock.patch.object(runner, "_spawn") as spawned:
                try:
                    runner.run_review(output, "unused-browser", "unused-node")
                except OSError:
                    pass
            spawned.assert_not_called()
            self.assertFalse(any(path.exists() for path in created), "Source failure leaked its private runtime")

    def test_startup_readiness_failure_still_stops_owned_worker(self):
        from decklab.ui_review import runner

        with tempfile.TemporaryDirectory() as outer:
            output = runner.prepare_output(Path(outer) / "evidence")
            source = {"commit": "synthetic", "dirty": False, "digest": "stable-test-digest", "files": {}}
            with mock.patch.object(runner, "_wait_ready", side_effect=runner.ReviewError("Synthetic missing ready")), \
                    mock.patch.object(runner, "_run_browser") as browser, \
                    mock.patch.object(runner, "_source_state", return_value=source):
                report = runner.run_review(output, "unused-browser", "unused-node", timeout=15)
            browser.assert_not_called()
            self.assertFalse(report["completed"])
            self.assertTrue(report["cleanup"]["fixture_exited"], report)
            self.assertTrue(report["cleanup"]["runtime_removed"], report)
            self.assertTrue(report["cleanup"]["complete"], report)

    def test_forced_owned_process_cleanup_is_not_reported_as_cooperative(self):
        from decklab.ui_review import runner

        with tempfile.TemporaryDirectory() as outer:
            runtime = Path(outer)
            owned = mock.Mock()
            owned.poll.return_value = None
            owned.wait.side_effect = subprocess.TimeoutExpired("synthetic owned helper", .01)
            with mock.patch.object(runner, "_force_owned_tree") as forced:
                self.assertFalse(runner._stop_owned(owned, runtime, "capture", grace=.01))
            forced.assert_called_once_with(owned)
            self.assertTrue((runtime / "cancel-file").is_file())

    def test_an_exited_helper_does_not_cancel_the_next_suite(self):
        from decklab.ui_review import runner

        with tempfile.TemporaryDirectory() as outer:
            runtime = Path(outer)
            finished = mock.Mock()
            finished.poll.return_value = 0
            with mock.patch.object(runner, "_force_owned_tree") as forced:
                self.assertTrue(runner._stop_owned(finished, runtime, "capture"))
                self.assertFalse((runtime / "cancel-file").exists())
                self.assertTrue(runner._stop_owned(finished, runtime, "editor"))
            self.assertFalse((runtime / "cancel-file").exists())
            finished.wait.assert_not_called()
            forced.assert_not_called()

    def test_posix_fallback_kills_only_descendants_still_owned_by_this_helper(self):
        from decklab.ui_review import runner

        original = "100 1\n101 100\n102 101\n103 102\n104 100\n200 1\n201 200\n"
        moved = "100 1\n101 100\n102 201\n103 102\n104 100\n200 1\n201 200\n"
        for current, expected in ((original, [103, 102, 104, 101]), (moved, [104, 101])):
            with self.subTest(expected=expected):
                owned = mock.Mock(pid=100)
                owned.poll.return_value = None
                with mock.patch.object(runner.os, "name", "posix"), \
                        mock.patch.object(runner.subprocess, "check_output", side_effect=[original, current]), \
                        mock.patch.object(runner.os, "kill") as kill, \
                        mock.patch.object(runner.os, "killpg", create=True) as kill_group, \
                        mock.patch.object(runner.signal, "SIGKILL", 9, create=True):
                    runner._force_owned_tree(owned)
                self.assertEqual(kill.call_args_list, [mock.call(pid, 9) for pid in expected])
                kill_group.assert_called_once_with(100, 9)
                owned.wait.assert_called_once_with(timeout=10)

    def test_started_browser_requires_positive_cleanup_proof(self):
        from decklab.ui_review import runner

        for suite, proof in ((suite, proof) for suite in runner.SUITES for proof in (None, False, True)):
            with self.subTest(suite=suite, browser_closed=proof), tempfile.TemporaryDirectory() as outer:
                output = runner.prepare_output(Path(outer) / "evidence")

                def failed_browser(node, browser, suite, runtime, output, run_id, smoke, deadline):
                    (runtime / f"browser-{suite}.started").touch()
                    if proof is not None:
                        suite_output = output / suite
                        suite_output.mkdir()
                        (suite_output / "summary.json").write_text(json.dumps({
                            "completed": False, "browser_closed": proof}), encoding="utf-8")
                    raise runner.ReviewError("Synthetic browser exit")

                source = {"commit": "synthetic", "dirty": True, "digest": "stable-test-digest", "files": {}}
                # This matrix tests cleanup evidence, not fixture startup. Readiness and
                # real child cleanup have dedicated tests below; no process or socket is
                # needed to prove missing/negative browser-close receipts fail closed.
                finished = mock.Mock(pid=123, returncode=0)
                finished.poll.return_value = 0
                with mock.patch.object(runner, "_spawn", return_value=finished) as spawn, \
                        mock.patch.object(runner, "_wait_ready", return_value={}) as ready, \
                        mock.patch.object(runner, "_run_browser", side_effect=failed_browser) as browser, \
                        mock.patch.object(runner, "_source_state", return_value=source):
                    report = runner.run_review(output, "unused-browser", "unused-node", suite=suite, timeout=15)
                spawn.assert_called_once()
                ready.assert_called_once()
                browser.assert_called_once()
                self.assertFalse(report["completed"])
                self.assertEqual(report["cleanup"]["browsers_closed"], proof is True, report)
                self.assertEqual(report["cleanup"]["complete"], proof is True, report)
                self.assertTrue(report["cleanup"]["runtime_removed"], report)
                self.assertTrue(report["cleanup"]["fixture_exited"], report)

    def test_posix_fallback_stops_if_its_owned_helper_has_exited(self):
        from decklab.ui_review import runner

        owned = mock.Mock(pid=100)
        owned.poll.side_effect = [None, 0]
        snapshot = "100 1\n101 100\n200 1\n"
        with mock.patch.object(runner.os, "name", "posix"), \
                mock.patch.object(runner.subprocess, "check_output", side_effect=[snapshot, snapshot]), \
                mock.patch.object(runner.os, "kill") as kill, \
                mock.patch.object(runner.os, "killpg", create=True) as kill_group, \
                mock.patch.object(runner.signal, "SIGKILL", 9, create=True):
            runner._force_owned_tree(owned)
        kill.assert_not_called()
        kill_group.assert_not_called()
        owned.wait.assert_not_called()

    def test_owned_fixture_is_cleaned_after_browser_failure_or_interruption(self):
        from decklab.ui_review import runner

        for failure in (runner.ReviewError("Synthetic browser failure"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as outer:
                output = runner.prepare_output(Path(outer) / "evidence")
                observed = {}

                def fail_browser(node, browser, suite, runtime, output, run_id, smoke, deadline):
                    ready = json.loads((runtime / "ready.json").read_text(encoding="utf-8"))
                    observed.update(runtime=runtime, root=Path(ready["root"]), address=urlsplit(ready["base_url"]))
                    self.assertTrue(observed["root"].exists())
                    self.assertTrue(observed["root"].is_relative_to(runtime))
                    raise failure

                source = {"commit": "synthetic", "dirty": True, "digest": "stable-test-digest", "files": {}}
                with mock.patch.object(runner, "_run_browser", side_effect=fail_browser), \
                        mock.patch.object(runner, "_source_state", return_value=source):
                    report = runner.run_review(output, "unused-browser", "unused-node", suite="capture", timeout=15)
                self.assertIn("root", observed, report)
                self.assertFalse(report["completed"])
                self.assertEqual(report["interrupted"], isinstance(failure, KeyboardInterrupt))
                self.assertTrue(report["cleanup"]["fixture_exited"], report)
                self.assertTrue(report["cleanup"]["complete"], report)
                self.assertTrue(report["cleanup"]["fixture_temporary_data_removed"], report)
                self.assertFalse(observed["runtime"].exists())
                self.assertFalse(observed["root"].exists())
                self.assertEqual(json.loads((output / "run.json").read_text(encoding="utf-8")), report)
                self.assertTrue((output / "README.md").is_file())
                public = json.dumps(report)
                self.assertNotIn(str(observed["runtime"]), public)
                self.assertNotIn(str(observed["root"]), public)
                address = observed["address"]
                probe = http.client.HTTPConnection(address.hostname, address.port, timeout=1)
                try:
                    with self.assertRaises(OSError):
                        probe.connect()
                finally:
                    probe.close()

    def test_output_never_reuses_prior_evidence_or_a_file(self):
        from decklab.ui_review.runner import ReviewError, prepare_output

        with tempfile.TemporaryDirectory() as outer:
            root = Path(outer).resolve()
            output = root / "fresh"
            self.assertEqual(prepare_output(output), output)
            self.assertEqual(prepare_output(output), output)
            evidence = output / "existing.png"
            evidence.write_bytes(b"preserve existing evidence")
            with self.assertRaises(ReviewError):
                prepare_output(output)
            self.assertEqual(evidence.read_bytes(), b"preserve existing evidence")
            with self.assertRaises(ReviewError):
                prepare_output(evidence)

    def test_output_refuses_a_linked_directory_or_parent(self):
        from decklab.ui_review.runner import ReviewError, prepare_output

        with tempfile.TemporaryDirectory() as outer:
            root = Path(outer).resolve()
            output = root / "fresh"
            output.mkdir()
            linked = root / "linked"
            try:
                linked.symlink_to(output, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"this account cannot create a directory symlink: {error}")
            with self.assertRaises(ReviewError):
                prepare_output(linked / "new")
            with self.assertRaises(ReviewError):
                prepare_output(linked)

    def test_incomplete_or_unclosed_browser_summary_is_a_failure(self):
        from decklab.ui_review.runner import ReviewError, _read_browser_summary

        with tempfile.TemporaryDirectory() as outer:
            summary = Path(outer) / "summary.json"
            for completed, closed in ((False, True), (True, False), (False, False)):
                summary.write_text(json.dumps({"completed": completed, "browser_closed": closed}), encoding="utf-8")
                with self.subTest(completed=completed, closed=closed), self.assertRaises(ReviewError):
                    _read_browser_summary(summary)
            summary.write_text(json.dumps({"completed": True, "browser_closed": True}), encoding="utf-8")
            self.assertEqual(_read_browser_summary(summary)["completed"], True)
            for malformed in ("not JSON", "[]", "null"):
                summary.write_text(malformed, encoding="utf-8")
                with self.subTest(malformed=malformed), self.assertRaises(ReviewError):
                    _read_browser_summary(summary)

    def test_ready_accepts_only_owned_loopback_worker_and_runtime_paths(self):
        from decklab.ui_review.runner import ReviewError, validate_ready

        with tempfile.TemporaryDirectory() as outer:
            runtime = Path(outer).resolve()
            data = {"fixture_type": "decklab-ui-review-v1", "run_id": "unit-review-test-token", "pid": os.getpid(),
                    "base_url": "http://127.0.0.1:53197", "root": str(runtime / "inventory"),
                    "profile_control": str(runtime / "profile.txt"), "case_control": str(runtime / "case.txt"),
                    "stop_file": str(runtime / "stop"), "editor_conflict_control": str(runtime / "conflict")}
            self.assertIsInstance(validate_ready(data, runtime, "unit-review-test-token", os.getpid()), dict)
            bad = (("run_id", "other"), ("pid", os.getpid() + 1), ("fixture_type", "other"),
                   ("base_url", "http://127.0.0.1:8642"), ("base_url", "https://127.0.0.1:53197"),
                   ("base_url", "http://example.com:53197"), ("base_url", "http://127.0.0.1:53197/path"),
                   ("profile_control", str(runtime.parent / "outside-profile.txt")))
            for field, value in bad:
                with self.subTest(field=field, value=value), self.assertRaises(ReviewError):
                    validate_ready({**data, field: value}, runtime, "unit-review-test-token", os.getpid())


class ReviewFixtureTests(unittest.TestCase):
    def runtime(self, parent, run_id="unit-review-test-token"):
        runtime = Path(parent) / "runtime"
        runtime.mkdir()
        (runtime / "owner.json").write_text(json.dumps({
            "fixture_type": "decklab-ui-review-v1", "run_id": run_id}), encoding="utf-8")
        return runtime

    def request(self, fixture, path, *, method="GET", payload=None, status=200, extra_headers=None):
        address = urlsplit(fixture.base_url)
        conn = http.client.HTTPConnection(address.hostname, address.port, timeout=5)
        headers = {"Connection": "close", "X-Deck-Lab": "1", "Content-Type": "application/json"}
        headers.update(extra_headers or {})
        try:
            conn.request(method, path, None if payload is None else json.dumps(payload), headers)
            response = conn.getresponse()
            content = response.read()
            self.assertEqual(response.status, status, content[:1000])
            if response.headers.get_content_type() == "application/json":
                return json.loads(content)
            return content
        finally:
            conn.close()

    def test_fresh_seed_dry_run_and_every_write_boundary(self):
        from decklab.ui_review.fixture import HOME, review_fixture
        from decklab.db import conn
        from decklab.lib import cards, config

        old_config = config.CONFIG_FILE
        with tempfile.TemporaryDirectory() as parent, \
                mock.patch.object(conn, "connect", side_effect=AssertionError("real database")) as db, \
                mock.patch.object(cards, "update", side_effect=AssertionError("card download")) as download:
            runtime = self.runtime(parent)
            with review_fixture(runtime, "unit-review-test-token") as fixture:
                root = fixture.root
                address = urlsplit(fixture.base_url)
                self.assertEqual(address.hostname, "127.0.0.1")
                self.assertNotEqual(address.port, 8642)
                self.assertNotEqual(root, Path(__file__).resolve().parents[2])
                self.assertEqual(config.CONFIG_FILE, root / "config.json")
                # The fixture resolves Windows 8.3 aliases (and macOS /var).
                # Compare canonical paths, as the production ownership guard does.
                self.assertTrue(root.is_relative_to(runtime.resolve()))
                self.request(fixture, "/_ui_review/ready", status=403)
                identity = self.request(fixture, "/_ui_review/ready", extra_headers={
                    "X-DeckLab-Review-Run": "unit-review-test-token"})
                self.assertEqual(identity, {"fixture_type": "decklab-ui-review-v1",
                                            "run_id": "unit-review-test-token", "isolated": True})
                before = self.request(fixture, f"/api/deck/edit?id={HOME}")
                self.assertEqual(sum(row["qty"] for row in before["lists"]["target"]["Deck"]), 60)
                kept = self.request(fixture, f"/api/deck/draft?id={HOME}&version=target")
                self.assertIsNotNone(kept["draft"], "Every run must seed its own resumable draft")
                checked = self.request(fixture, "/api/deck/check", method="POST", payload={
                    "profile": "matt", "id": HOME, "sha256": before["sha256"], "lists": before["lists"]})
                self.assertIn("ok", checked)
                commander = self.request(fixture, "/api/deck/edit?id=commander/woodland-council")
                cut_sections = {key: [{name: row[name] for name in ("name", "qty", "set", "number", "finish", "category") if name in row}
                                      for row in rows] for key, rows in commander["lists"]["target"].items() if key in {"Commander", "Deck", "Companion"}}
                # An ordinary singleton Commander list exceeds the settings body's 4 KiB bound.
                cut_sections["Deck"] += [dict(cut_sections["Deck"][0]) for _ in range(100)]
                self.assertGreater(len(json.dumps(cut_sections)), 4096)
                cuts = self.request(fixture, "/api/deck/cuts", method="POST", payload={"profile": "matt", "id": "commander/woodland-council", "sections": cut_sections})
                self.assertTrue(cuts["cuts"] and cuts["source"]["available"])
                self.assertEqual(self.request(fixture, "/api/deck/edit?id=commander/woodland-council"), commander)
                for method, path in (("POST", "/api/deck/save"), ("PUT", "/api/deck/draft"),
                                     ("POST", "/api/matchup/run"), ("POST", "/api/variant/run"),
                                     ("DELETE", "/api/decks"), ("PATCH", "/api/profiles/matt/settings"),
                                     ("OPTIONS", "/api/deck/check")):
                    with self.subTest(method=method, path=path):
                        self.request(fixture, path, method=method, payload={}, status=403)
                self.request(fixture, f"/api/goldfish?id={HOME}", status=403)
                self.assertEqual(self.request(fixture, f"/api/deck/edit?id={HOME}"), before)
                self.assertEqual(self.request(fixture, f"/api/deck/draft?id={HOME}&version=target"), kept)
            self.assertFalse(root.exists())
            conn_test = http.client.HTTPConnection(address.hostname, address.port, timeout=1)
            try:
                with self.assertRaises(OSError):
                    conn_test.connect()
            finally:
                conn_test.close()
            self.assertEqual(config.CONFIG_FILE, old_config)
            db.assert_not_called()
            download.assert_not_called()

    def test_controlled_adapter_states_and_profile_stay_synthetic(self):
        from decklab.ui_review.fixture import HOME_TEST, MEMBER_TEST, review_fixture

        with tempfile.TemporaryDirectory() as parent:
            runtime = self.runtime(parent)
            (runtime / "fixture.log").write_text("Owned startup log", encoding="utf-8")
            with review_fixture(runtime, "unit-review-test-token") as fixture:
                complete = self.request(fixture, f"/api/variant?test={HOME_TEST}")
                self.assertNotEqual(complete["status"], "running")
                self.assertTrue(complete["may_edit"])
                wished = self.request(fixture, "/api/profiles/matt/wishlist")
                self.assertEqual(wished["entries"][0]["have"], {"owned": 3, "on_the_way": 1})
                self.assertEqual(wished["entries"][1]["have"], {"owned": 0, "on_the_way": 0})
                case = Path(fixture.ready["case_control"])
                case.write_text("unknown-counts", encoding="utf-8")
                unknown = self.request(fixture, "/api/profiles/matt/wishlist")
                self.assertTrue(all(entry["have"] == {"owned": None, "on_the_way": None}
                                    for entry in unknown["entries"]))
                self.request(fixture, "/api/profiles/matt/wishlist", method="POST", payload={}, status=403)
                case.write_text("running", encoding="utf-8")
                running = self.request(fixture, f"/api/variant?test={HOME_TEST}")
                self.assertEqual(running["status"], "running")
                self.assertEqual(running["job"]["status"], "running")
                case.write_text("failed", encoding="utf-8")
                self.request(fixture, "/api/gauntlet/board?format=commander", status=503)
                case.write_text("complete", encoding="utf-8")
                Path(fixture.ready["profile_control"]).write_text("user2", encoding="utf-8")
                member = self.request(fixture, f"/api/variant?test={MEMBER_TEST}")
                self.assertEqual(member["test"]["base"]["id"], "user2/casual/member-fixture")
                self.assertTrue(member["may_edit"])
                self.assertFalse(self.request(fixture, f"/api/variant?test={HOME_TEST}")["may_edit"])
                self.request(fixture, "/api/profiles/matt/wishlist", status=403)
                self.assertEqual(self.request(fixture, "/api/me")["profile"], "user2")

    def test_populated_composition_uses_real_deck_and_game_readers(self):
        from decklab.ui_review.fixture import HOME, review_fixture
        from decklab.ui_review.composition_data import COMMANDER, EMPTY

        with tempfile.TemporaryDirectory() as parent:
            runtime = self.runtime(parent)
            with review_fixture(runtime, "unit-review-test-token") as fixture:
                commander = self.request(fixture, f"/api/deck?id={COMMANDER}&omit=matchups")
                self.assertEqual(commander["summary"]["kind"], "commander")
                self.assertEqual(sum(line["qty"] for rows in commander["sections"].values() for line in rows), 100)
                self.assertEqual(commander["played"]["games"], 3)
                self.assertEqual(commander["played"]["last"], "2000-01-05")
                self.assertEqual(commander["played"]["since"]["changes"], [])
                self.assertGreaterEqual(len(commander["guide"]["sections"]), 2)
                casual = self.request(fixture, f"/api/deck?id={HOME}&omit=matchups")
                self.assertEqual(casual["played"]["games"], 0)
                empty = self.request(fixture, f"/api/deck?id={EMPTY}&omit=matchups")
                self.assertFalse(any(empty["sections"].values()))
                index = self.request(fixture, "/api/decks")
                self.assertGreaterEqual(len(index["decks"]), 4)
                self.assertTrue(all(not d.get("error") for d in index["decks"]))
                Path(fixture.ready["case_control"]).write_text("library-failed", encoding="utf-8")
                self.request(fixture, "/api/decks", status=503)
                self.request(fixture, "/api/deck/save", method="POST", payload={}, status=403)

    def test_page_family_records_and_admin_adapters_remain_disposable(self):
        from decklab.ui_review.fixture import review_fixture

        with tempfile.TemporaryDirectory() as parent:
            runtime = self.runtime(parent)
            with review_fixture(runtime, "unit-review-test-token") as fixture:
                tokens = self.request(fixture, "/api/tokens")
                self.assertEqual(len(tokens["rows"]), 2)
                kit = self.request(fixture, "/api/accessories")
                self.assertEqual(len(kit["items"]), 3)
                self.assertTrue(all(row["owner"] in {"matt", "shared"} for row in kit["items"]))
                activity = self.request(fixture, "/api/activity")
                self.assertEqual(len(activity["changes"]), 4)
                self.assertTrue(self.request(fixture, "/api/settings/maintenance")["available"])
                members = self.request(fixture, "/api/settings/members")
                self.assertEqual(members["members"][0]["emails"], ["user2@example.com"])
                for path in ("/api/tokens/save", "/api/accessories/save", "/api/settings/members"):
                    self.request(fixture, path, method="POST", payload={}, status=403)

    def test_owner_nonce_is_required_before_fixture_start(self):
        from decklab.ui_review.fixture import review_fixture

        with tempfile.TemporaryDirectory() as parent:
            runtime = self.runtime(parent)
            for run_id in ("different-review", ""):
                with self.subTest(run_id=run_id), self.assertRaises((ValueError, RuntimeError)):
                    with review_fixture(runtime, run_id):
                        self.fail("An unowned fixture must never start")

    def test_runtime_requires_a_fresh_exact_ownership_marker(self):
        from decklab.ui_review.fixture import review_fixture
        from decklab.safari.fixture import FixtureServer

        with tempfile.TemporaryDirectory() as parent, mock.patch.object(FixtureServer, "_start") as start:
            runtime = self.runtime(parent)
            marker = runtime / "owner.json"
            good = marker.read_bytes()
            for bad in (b"not JSON", b'{}', good + b" extra"):
                marker.write_bytes(bad)
                with self.assertRaises(ValueError):
                    with review_fixture(runtime, "unit-review-test-token"):
                        self.fail("An invalid marker must never start a fixture")
            marker.write_bytes(good)
            (runtime / "prior-evidence.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                with review_fixture(runtime, "unit-review-test-token"):
                    self.fail("A nonempty reused runtime must never start a fixture")
            (runtime / "prior-evidence.json").unlink()
            log = runtime / "fixture.log"
            log.mkdir()
            with self.assertRaises(ValueError):
                with review_fixture(runtime, "unit-review-test-token"):
                    self.fail("The owned log name must be a regular file")
            log.rmdir()
            try:
                log.symlink_to(marker)
            except (OSError, NotImplementedError):
                pass
            else:
                with self.assertRaises(ValueError):
                    with review_fixture(runtime, "unit-review-test-token"):
                        self.fail("A linked log must never be accepted")
            start.assert_not_called()

    def test_dedicated_worker_audit_denies_external_network_and_children(self):
        # Audit hooks cannot be removed. Install one only in this dedicated child,
        # then exercise actual Python socket/process APIs, without making a connection.
        script = '''
import socket, subprocess, sys
from decklab.ui_review.fixture import install_worker_audit
install_worker_audit()
def refused(action):
    try:
        action()
    except RuntimeError:
        return
    raise AssertionError("worker audit did not refuse an external side effect")
with socket.socket() as sock:
    refused(lambda: sock.connect(("203.0.113.1", 9)))
with socket.socket() as sock:
    refused(lambda: sock.bind(("0.0.0.0", 0)))
with socket.socket(type=socket.SOCK_DGRAM) as sock:
    refused(lambda: sock.sendto(b"synthetic", ("203.0.113.1", 9)))
refused(lambda: socket.getaddrinfo("example.com", 80))
refused(lambda: socket.gethostbyaddr("203.0.113.1"))
refused(lambda: subprocess.Popen([sys.executable, "-c", "raise AssertionError('must not launch')"]))
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
print("worker-audit-ok")
'''
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([sys.executable, "-c", script], cwd=root,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("worker-audit-ok", result.stdout)

    def test_audit_installation_fails_closed_when_registration_is_refused(self):
        from decklab.ui_review.fixture import install_worker_audit

        with mock.patch.object(sys, "addaudithook", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "guard|audit"):
                install_worker_audit()


if __name__ == "__main__":
    unittest.main()
