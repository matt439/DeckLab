"""Tests for the nightly check of the database's data (decklab/db/check.py, `python -m decklab.db
check`): every sub-check over one snapshot of a throwaway database holding a test tree's inventory
and decks, a broken invariant failing its sub-check (and the run), the deck tables as a warning,
the run recorded in ops.backup_run (kind 'check', migration 0007) and --history. They skip
without a database (db_support.py); db.log goes to a temporary file (decklab/tests/__init__.py).

Run from the repo root: python -m unittest decklab.tests.test_db_check
"""
import io
import json
from contextlib import redirect_stdout
from datetime import datetime
from unittest import mock

from decklab.db import backup, check, conn as db, inv_decks
from decklab.lib import config, spaces, tokens
from decklab.tests.test_inventory_contract import WATCH_HEADER, _tokens
from decklab.tests.test_inventory_pg_decks import _Db


class CheckTests(_Db):

    def tree(self):
        """_Db's tree with token cards and a queue the rule checks pass: single-sided tokens that
        say so, and queued cards whose source is a deck that exists."""
        case = super().tree()
        _tokens(case, "tokens.csv", *((name, "", "tltc", n, "", "nonfoil", "1", "", "", "single-sided verified")
                                      for name, n in (("Treasure", "14"), ("Zombie", "20"))))
        case.write("watchlist.csv", WATCH_HEADER + "".join(
            f"{name},dom,{n},nonfoil,1,Test,any,,,,,,long_term,magic/decks/casual/test.md\n"
            for n, name in enumerate(("Opt", "Shock"), 1)))
        return case

    def setUp(self):
        super().setUp()
        # Token names are checked only with the card index, which a worktree may not have: never here.
        patcher = mock.patch.object(tokens, "_ready", lambda: False)
        patcher.start()
        self.addCleanup(patcher.stop)
        with self.connect("owner") as c:
            c.execute("delete from ops.backup_run")
        self.said = []
        # The deck tables need the card index, which a worktree may not have: judged here by hand.
        self.planned = []
        patcher = mock.patch.object(inv_decks, "plan_tables", lambda *a, **k: list(self.planned))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_check(self):
        code = check.run(dbname=self.dbname, say=self.said.append)
        rows = self.rows("select ok, detail from ops.backup_run where kind = 'check' order by id")
        ok, detail = rows[-1]
        data = json.loads(detail)
        self.assertEqual(ok, code == 0)
        return code, data, {c["name"]: c for c in data["checks"]}

    def test_a_consistent_database_passes_every_sub_check(self):
        inv, _ = self.import_tree()
        code, data, checks = self.run_check()
        self.assertEqual(code, 0, self.said)
        self.assertEqual((data["revision"], data["decks_revision"]), ("1", "1"))
        expected = (["accessories"] + [f"tokens ({s})" for s in spaces.space_ids()]
                    + ["orders and queue", "deck tables", "deck aliases", "deck revisions", "deck texts", "deck lines",
                       "deck headers", "revision rows", "audit trail", "Commander-night notes", "visibility",
                       "member departures", "files round trip"])
        self.assertEqual(list(checks), expected)
        failed = {name: c["detail"] for name, c in checks.items() if not c["ok"]}
        self.assertEqual(failed, {})
        # The token names weren't checked (no card index): a warning, not a failure.
        warned = {name for name, c in checks.items() if c["warning"]}
        self.assertEqual(warned, {"tokens (home)"})
        self.assertIn("Names weren't checked", checks["tokens (home)"]["detail"])
        self.assertEqual(checks["orders and queue"]["detail"], "4 orders, 2 queued purchases")
        for c in checks.values():
            self.assertEqual(set(c), {"name", "ok", "warning", "detail", "seconds"})
            self.assertIsInstance(c["seconds"], float)
        self.assertFalse(checks["deck tables"]["warning"])
        self.assertIn("give the database's snapshot", checks["files round trip"]["detail"])
        self.assertEqual(checks["deck lines"]["detail"], "the lines of 2 decks match their texts")
        self.assertEqual(self.said[-1], f"Check passed (inventory revision 1, decks revision 1): {len(expected)} "
                                        "sub-checks, 1 warning.")
        self.assertTrue(any(line.startswith("Check: deck lines: ok: ") for line in self.said), self.said)
        self.assertEqual(len(self.said), len(expected) + 1)            # one line per sub-check, then the result
        lines = check.history(dbname=self.dbname)
        self.assertRegex(lines[0], r"^\d{4}-\d\d-\d\d \d\d:\d\d passed \(1 warning\) "
                                   r"\(inventory revision 1, decks revision 1\)$")
        self.assertEqual(lines[1], "    warning tokens (home): Names weren't checked: the card data isn't loaded "
                                   "(python -m decklab.lib.cards update)")

    def test_each_sub_check_is_a_line_in_db_log(self):
        self.import_tree()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(check.run(dbname=self.dbname), 0)
        self.assertNotEqual(db.LOG_FILE, config.DATA / "logs" / "db.log")    # never the real log (tests/__init__.py)
        log = db.LOG_FILE.read_text(encoding="utf-8")
        self.assertIn("Check: files round trip: ok: ", log)
        self.assertIn("Check passed (inventory revision 1, decks revision 1)", log)

    def test_a_rename_passes_the_nightly_check_with_its_old_purchase_sources(self):
        from decklab.lib.inventory import ops_rename  # noqa: F401 (registers rename)
        _, backend = self.import_tree()
        held = backend.load().deck("casual/test")
        self.apply(backend, "deck.rename", deck_id=held.id, new_slug="renamed", title="Renamed",
                   base_sha256=held.sha256, revision=held.revision)
        code, data, checks = self.run_check()
        self.assertEqual(code, 0, self.said)
        self.assertEqual((data["revision"], data["decks_revision"]), ("1", "2"))
        self.assertTrue(checks["deck aliases"]["ok"])
        self.assertEqual(checks["orders and queue"]["detail"], "4 orders, 2 queued purchases")
        self.assertTrue(checks["files round trip"]["ok"])

    def test_stale_deck_tables_are_a_warning_not_a_failure(self):
        self.import_tree()
        self.planned = [("casual/test", "Test", "old", "new", None)]
        code, _, checks = self.run_check()
        self.assertEqual(code, 0, self.said)
        self.assertTrue(checks["deck tables"]["ok"])
        self.assertTrue(checks["deck tables"]["warning"])
        self.assertIn("1 deck with an out-of-date table: casual/test", checks["deck tables"]["detail"])
        lines = check.history(dbname=self.dbname)
        self.assertIn("passed (2 warnings)", lines[0])
        self.assertIn("    warning deck tables: 1 deck with an out-of-date table: casual/test", "\n".join(lines))

    def test_a_deck_table_refresh_that_cant_be_worked_out_is_a_warning_saying_why(self):
        # A forced order leaves the pool incomplete until it arrives (AGENTS.md, "Placing an order"):
        # a legitimate state, so never a failure. Nor is a missing card index, or a refusal of the deck.
        self.import_tree()
        for error in (ValueError("Cannot refresh from an incomplete card pool: Unknown card: Opt"),
                      FileNotFoundError("No card index at x. Run: python -m decklab.lib.cards update"),
                      FileNotFoundError("test.md is missing")):
            with self.subTest(error=str(error)):
                with mock.patch.object(inv_decks, "plan_tables", side_effect=error):
                    code, _, checks = self.run_check()
                self.assertEqual(code, 0, self.said)
                self.assertTrue(checks["deck tables"]["ok"])
                self.assertTrue(checks["deck tables"]["warning"])
                self.assertEqual(checks["deck tables"]["detail"],
                                 f"not checked: the tables can't be worked out ({error})")

    def test_broken_invariants_fail_their_sub_checks(self):
        self.import_tree()
        with self.connect("owner") as c:
            # Derived rows and the deck's summary out of step with its text; the history left as it is.
            c.execute("update deck_line set quantity = quantity + 1 where deck_id = 'casual/test' and position = 0 "
                      "and version = 'target' and section = 'Deck'")
            with db.change("test", "test", "break a deck's summary", conn=c) as (cur, _):
                cur.execute("update deck set title = 'Not the title' where id = 'commander/other'")
            c.execute("update deck_text set text = text || E'\\nMore.\\n' where deck_id = 'commander/other'")
        code, _, checks = self.run_check()
        self.assertEqual(code, 1)
        failed = {name: c["detail"] for name, c in checks.items() if not c["ok"]}
        self.assertEqual(set(failed), {"deck texts", "deck lines", "deck headers"})
        self.assertIn("casual/test", failed["deck lines"])
        self.assertIn("commander/other (title)", failed["deck headers"])
        self.assertIn("commander/other's text isn't its newest revision's", failed["deck texts"])
        self.assertTrue(self.said[-1].startswith("Check FAILED"))
        self.assertIn("deck texts, deck lines, deck headers.", self.said[-1])
        lines = backup.status()
        self.assertTrue(any(l.startswith("  last check: ") and "FAILED: deck texts" in l for l in lines), lines)

    def test_a_deck_ahead_of_its_history_fails(self):
        self.import_tree()
        with self.connect("owner") as c:
            with db.change("test", "test", "move a deck ahead of its history", conn=c) as (cur, _):
                cur.execute("update deck set revision = revision + 1 where id = 'casual/test'")
        code, _, checks = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(checks["deck revisions"]["detail"], "casual/test is at revision 2, its newest is 1")
        self.assertEqual([n for n, c in checks.items() if not c["ok"]], ["deck revisions"])

    def test_a_database_with_nothing_imported_fails_and_still_checks_the_rest(self):
        code, _, checks = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("the inventory can't be loaded", checks["snapshot"]["detail"])
        self.assertEqual(checks["revision rows"]["detail"], "inventory_revision has 0 rows; decks_revision has 0 rows")
        self.assertTrue(checks["deck lines"]["ok"])
        self.assertNotIn("files round trip", checks)

    def test_the_round_trip_compares_snapshots_part_by_part(self):
        inv, _ = self.import_tree()
        self.assertEqual(check.differences(inv, inv), [])
        other = inv.replace(decks={k: v for k, v in inv.decks.items() if k != "casual/test"},
                            decks_revision="2")
        self.assertEqual(check.differences(inv, other), ["decks_revision", "decks[casual/test]"])

    def test_an_unrecorded_run_fails(self):
        from psycopg import errors
        self.import_tree()
        with mock.patch.object(backup, "record", side_effect=errors.CheckViolation("violates check constraint")):
            self.assertEqual(check.run(dbname=self.dbname, say=self.said.append), 1)
        self.assertIn("is migration 0007 applied?", self.said[-1])
        with mock.patch.object(backup, "record", side_effect=RuntimeError("something else")):
            self.assertEqual(check.run(dbname=self.dbname, say=self.said.append), 1)
        self.assertTrue(self.said[-1].endswith("(RuntimeError: something else)"), self.said[-1])

    def test_a_connection_lost_before_the_run_is_recorded_is_unreachable(self):
        import psycopg
        self.import_tree()
        with mock.patch.object(backup, "record", side_effect=psycopg.OperationalError("server closed")):
            with self.assertRaises(db.DbUnavailable):
                check.run(dbname=self.dbname, say=self.said.append)

    def test_history_without_runs(self):
        self.assertEqual(check.history(dbname=self.dbname), ["No check has run yet (python -m decklab.db check)."])
        backup.record("check", datetime.now(), False, detail="not JSON")
        self.assertRegex(check.history(dbname=self.dbname)[0], r" FAILED: not JSON$")
