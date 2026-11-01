"""The post-install smoke test's runner and pure helpers (decklab/smoke.py). Its real
steps need the real config, database, server and Forge, so they aren't run here."""
import contextlib
import io
import json
import types
import unittest

from decklab import smoke


def _args(**over):
    base = {"json": False, "offline": False, "no_forge": False, "no_server": False}
    base.update(over)
    return types.SimpleNamespace(**base)


class HelperTests(unittest.TestCase):
    def test_pinned_reads_the_requirement(self):
        text = "# comment\npsycopg[binary]==3.3.6\nother==1.0\n"
        self.assertEqual(smoke.pinned(text, "psycopg"), "3.3.6")
        self.assertEqual(smoke.pinned("psycopg==3.2 # why\n", "psycopg"), "3.2")
        self.assertIsNone(smoke.pinned("psycopg-pool==1.0\n", "psycopg"))
        self.assertIsNone(smoke.pinned("", "psycopg"))

    def test_major_version(self):
        self.assertEqual(smoke.major_version("pg_dump (PostgreSQL) 18.1"), 18)
        self.assertEqual(smoke.major_version("pg_restore (PostgreSQL) 16.4 (Ubuntu 16.4-1)"), 16)
        self.assertIsNone(smoke.major_version("not a version"))
        self.assertIsNone(smoke.major_version(None))

    def test_page_assets_keeps_own_files_only(self):
        html = ('<link rel="stylesheet" href="/app.css?v=abc">'
                '<script src="app.js?v=abc"></script><script src="https://cdn.example/x.js"></script>'
                '<link rel="icon" href="/icons/icon.svg"><script src="/app.js?v=abc"></script>'
                '<a href="#/decks">Decks</a>')
        self.assertEqual(smoke.page_assets(html), ["/app.css?v=abc", "/app.js?v=abc", "/icons/icon.svg"])

    def test_homenet_findings_takes_warn_and_problem_entries(self):
        out = ("Deck Lab status, 2026-11-01 (port 8642)\n\n"
               "OK      Server: Running since 2026-10-31.\n"
               "WARN    Server: Deck Lab's code changed after this server started,\n"
               "        so it's still running the old code.\n"
               "        Fix: python -m decklab.lib.homenet restart\n"
               "PROBLEM Service: decklab.service isn't installed.\n"
               "OK      Tunnel: connected.\n")
        self.assertEqual(smoke.homenet_findings(out), [
            "WARN Server: Deck Lab's code changed after this server started,",
            "PROBLEM Service: decklab.service isn't installed."])
        self.assertEqual(smoke.homenet_findings("OK      Server: fine\n"), [])

    def test_schedule_finding(self):
        self.assertIsNone(smoke.schedule_finding(0, "Nightly task: next run 2026-11-02 03:30\n"
                                                    "Last run: 2026-11-01 03:30, it succeeded.\n"))
        self.assertIn("isn't installed", smoke.schedule_finding(0, "The nightly task isn't registered.\n"))
        self.assertIn("isn't installed", smoke.schedule_finding(1, ""))
        self.assertIn("it failed", smoke.schedule_finding(0, "Last run: 2026-11-01 03:30, it failed (exit 1).\n"))
        self.assertIn("Note: systemd runs", smoke.schedule_finding(
            0, "Note: systemd runs your units only while you're logged in.\n"))
        self.assertIn("WARNING", smoke.schedule_finding(0, "  WARNING: the task is disabled.\n"))

    def test_result_keeps_its_worst_status(self):
        r = smoke.Result("x", "X")
        r.note(smoke.PASS, "a")
        r.note(smoke.WARN, "b")
        r.note(smoke.PASS, "c")
        self.assertEqual(r.status, smoke.WARN)
        r.note(smoke.FAIL, "d")
        r.note(smoke.WARN, "e")
        self.assertEqual(r.status, smoke.FAIL)


class RunnerTests(unittest.TestCase):
    def steps(self):
        def ok(r, ctx):
            ctx["seen"] = True
            r.note(smoke.PASS, "fine")

        def warns(r, ctx):
            r.note(smoke.WARN, "careful")

        def skips(r, ctx):
            raise smoke.Skip("not here")

        def crashes(r, ctx):
            raise RuntimeError("boom\nsecond line")

        def reads_ctx(r, ctx):
            r.note(smoke.PASS if ctx.get("seen") else smoke.FAIL, "saw the first step")

        return (("ok", "OK", ok), ("warns", "Warns", warns), ("skips", "Skips", skips),
                ("crashes", "Crashes", crashes), ("ctx", "Context", reads_ctx))

    def test_each_step_has_a_result_and_a_crash_is_a_failure(self):
        results = smoke.run(_args(), self.steps())
        self.assertEqual([r.status for r in results],
                         [smoke.PASS, smoke.WARN, smoke.SKIP, smoke.FAIL, smoke.PASS])
        self.assertIn("RuntimeError: second line", results[3].lines[0][1])
        self.assertEqual(results[2].lines, [(smoke.SKIP, "not here")])
        self.assertEqual(smoke.exit_code(results), 1)
        self.assertEqual(smoke.exit_code(results[:3]), 0)

    def test_text_output_and_exit_code(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = smoke.main([], steps=self.steps()[:3])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("PASS OK", text)
        self.assertIn("  warn careful", text)
        self.assertIn("SKIP Skips", text)
        self.assertIn("Smoke test passed", text)

    def test_json_output(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = smoke.main(["--json"], steps=self.steps())
        self.assertEqual(code, 1)
        report = json.loads(out.getvalue())
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual([r["id"] for r in report["results"]], ["ok", "warns", "skips", "crashes", "ctx"])
        self.assertEqual(report["results"][3]["status"], "fail")

    def test_switches_skip_their_steps(self):
        ctx = {"args": _args(offline=True, no_forge=True, no_server=True)}
        for fn in (smoke.step_network, smoke.step_forge, smoke.step_server):
            with self.assertRaises(smoke.Skip):
                fn(smoke.Result("x", "X"), ctx)

    def test_steps_needing_the_doctor_skip_without_it(self):
        ctx = {"args": _args(), "doctor": {"database": "needs_setup", "cards": "ready", "config": "ready"}}
        for fn in (smoke.step_database, smoke.step_backups):
            with self.assertRaises(smoke.Skip):
                fn(smoke.Result("x", "X"), ctx)
        ctx["doctor"]["cards"] = "needs_setup"
        with self.assertRaises(smoke.Skip):
            smoke.step_server(smoke.Result("x", "X"), ctx)

    def test_forge_skips_when_it_isnt_installed(self):
        ctx = {"args": _args(), "doctor": {"config": "ready", "forge": "needs_setup"}}
        with self.assertRaises(smoke.Skip):
            smoke.step_forge(smoke.Result("x", "X"), ctx)

    def test_bad_usage_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            smoke.main(["--nope"], steps=())
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
