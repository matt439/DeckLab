"""Field-policy DDL, export gating and nightly checks without a database.

Run from the repo root:
python scripts/test_fixtures.py decklab.tests.test_field_policy_db_registration
Only static migration reads, fake connections and disposable export folders are used.
"""
import ast
import copy
import re
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from decklab.db import check, export, migrate
from decklab.lib.state import field_policy

TABLE = "public.field_policy"
INVALID = (False, False, "the field policy has an invalid saved record")


def rule(mode="rules", *, deck="casual/retired", kind="baseline", revision=1, version="target"):
    value = {"epoch": {"kind": kind, "deck_id": deck, "revision": revision}, "mode": mode}
    if mode == "include":
        value["version"] = version
    return value


def row(fmt="Constructed", revision=1, rules=None):
    return fmt, revision, {"v": 1, "rules": [] if rules is None else rules}


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return copy.deepcopy(self.rows)


class FakeConn:
    def __init__(self, rows=(), *, missing=False, error=None):
        self.rows = copy.deepcopy(rows)
        self.missing = missing
        self.error = error
        self.calls = []
        self.rolled_back = False
        self.transactions = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def transaction(self):
        self.transactions += 1
        return nullcontext()

    def rollback(self):
        self.rolled_back = True

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.error is not None:
            raise self.error
        if sql == "select to_regclass('public.field_policy') is null":
            return Result([(self.missing,)])
        if sql == "select format, revision, content from field_policy order by format":
            return Result(self.rows)
        if sql == "select to_regclass(%s) is null":
            return Result([(self.missing and params == (TABLE,),)])
        if sql == "set local timezone = 'UTC'":
            return Result([])
        raise AssertionError("Unexpected fixture query")


class MigrationRegistrationTests(unittest.TestCase):
    def test_new_migration_follows_collection_locations_without_duplicate_versions(self):
        files = migrate.available()
        # Later migrations (0018's editor drafts, E2-S16) follow without gaps or duplicates.
        self.assertEqual([f["version"] for f in files], list(range(1, len(files) + 1)))
        self.assertEqual([(f["version"], f["name"]) for f in files[15:17]],
                         [(16, "collection_locations"), (17, "field_policy")])

    def sql(self):
        path = migrate.MIGRATIONS / "0017_field_policy.sql"
        return re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8")).lower()

    def test_ddl_is_schema_only_and_limits_the_three_column_envelope(self):
        sql = " ".join(self.sql().split())
        self.assertIn("create table public.field_policy ( format text primary key", sql)
        self.assertIn("check (format in ('constructed', 'commander'))", sql)
        self.assertIn("revision bigint not null check (revision >= 1)", sql)
        self.assertIn("content jsonb not null check (", sql)
        self.assertIn("jsonb_typeof(content) = 'object'", sql)
        self.assertIn("content ?& array['v', 'rules']", sql)
        self.assertIn("content - array['v', 'rules'] = '{}'::jsonb", sql)
        self.assertIn("jsonb_typeof(content -> 'v') = 'number'", sql)
        self.assertIn("content ->> 'v' = '1'", sql)
        self.assertIn("jsonb_typeof(content -> 'rules') = 'array'", sql)
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        self.assertEqual(len(statements), 3)
        self.assertTrue(all(s.startswith(("create table ", "create trigger ")) for s in statements))

    def test_audit_and_truncate_triggers_match_existing_state_tables(self):
        sql = " ".join(self.sql().split())
        self.assertIn("create trigger audit_row after insert or update or delete on public.field_policy "
                      "for each row execute function audit.log_row('format')", sql)
        self.assertIn("create trigger audit_no_truncate before truncate on public.field_policy "
                      "for each statement execute function audit.refuse_truncate()", sql)
        # The owner-run migration inherits the same table privileges as commander_night.
        foundation = " ".join((migrate.MIGRATIONS / "0001_foundation.sql").read_text(
            encoding="utf-8").lower().split())
        self.assertIn("alter default privileges for role decklab_owner in schema public "
                      "grant select, insert, update, delete on tables to decklab_app", foundation)
        self.assertIn("alter default privileges for role decklab_owner in schema public, audit, ops "
                      "grant select on tables to decklab_ro", foundation)
        self.assertNotRegex(sql, r"\bgrant\b|\btruncate\s+table\b")

    def test_export_registers_policy_before_inventory_without_reordering_old_tables(self):
        names = [name for name, _ in export.TABLES]
        self.assertEqual(names.count(TABLE), 1)
        self.assertEqual(dict(export.TABLES)[TABLE], ("format",))
        self.assertLess(names.index(TABLE), names.index("public.inventory_revision"))
        self.assertEqual([name for name in names if name != TABLE], [
            "public.space", "public.profile", "public.profile_email", "audit.change_set",
            "public.wishlist_entry", "public.profile_setting", "public.simulation_mode",
            "public.play_record", "public.packing_tick", "public.commander_night", "public.visibility",
            "public.space_departure", "public.inventory_revision", "public.collection_card",
            "public.collection_import", "public.token_card", "public.dice_counter", "public.product",
            "public.product_item", "public.product_status", "public.purchase_order", "public.order_component", "public.order_card_item",
            "public.order_token_item", "public.watchlist_item", "public.decks_revision", "public.deck",
            "public.deck_revision", "public.deck_alias", "public.accessory"])
        self.assertIn(TABLE, export.UNTIL_MIGRATED)
        self.assertNotIn(TABLE, export.INVENTORY_TABLES | export.DECK_TABLES)
        self.assertIn("public.collection_card", export.INVENTORY_TABLES)
        self.assertIn("public.deck", export.DECK_TABLES)

    def test_nightly_run_registers_a_distinct_policy_subcheck_on_the_same_connection(self):
        tree = ast.parse(Path(check.__file__).read_text(encoding="utf-8"))
        run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
        subs = [node for node in ast.walk(run) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "sub"
                and node.args and isinstance(node.args[0], ast.Constant)]
        labels = [node.args[0].value for node in subs]
        self.assertEqual(labels.count("field policy"), 1)
        self.assertLess(labels.index("Commander-night notes"), labels.index("field policy"))
        self.assertLess(labels.index("field policy"), labels.index("visibility"))
        call = next(node for node in subs if node.args[0].value == "field policy")
        self.assertEqual(ast.unparse(call), "result.sub('field policy', _field_policy(c), c)")


class FieldPolicyCheckTests(unittest.TestCase):
    def invariant(self, rows=(), **kwargs):
        conn = FakeConn(rows, **kwargs)
        answer = check._field_policy(conn)()
        self.assertLessEqual(len(conn.calls), 2)
        return answer

    def test_schema_ready_empty_state_is_not_configured(self):
        self.assertEqual(self.invariant(), (True, False, "not configured"))

    def test_old_schema_is_explicitly_migration_related_and_never_queries_missing_table(self):
        conn = FakeConn(missing=True)
        self.assertEqual(check._field_policy(conn)(),
                         (True, False, "field policy unavailable until migration 0017"))
        self.assertEqual(len(conn.calls), 1)

    def test_saved_empty_policy_and_bigint_max_revision_are_valid(self):
        for fmt in ("Constructed", "Commander"):
            for revision in (1, field_policy.MAX_REVISION):
                with self.subTest(fmt=fmt, revision=revision):
                    self.assertEqual(self.invariant([row(fmt, revision)]),
                                     (True, False, "valid policy for 1 format"))

    def test_both_formats_retain_obsolete_epochs_and_each_intent(self):
        constructed = [rule("include", deck="casual/a", version="owned"),
                       rule("exclude", deck="casual/b", kind="creation", revision=10_000),
                       rule("rules", deck="casual/c", kind="creation", revision=4)]
        commander = [rule("include", deck="commander/retired", version="target")]
        rows = [row("Commander", 12, commander), row("Constructed", 30, constructed)]
        original = copy.deepcopy(rows)
        self.assertEqual(self.invariant(rows), (True, False, "valid policy for 2 formats"))
        self.assertEqual(rows, original)

    def test_malformed_columns_and_envelopes_fail_without_echoing_any_value(self):
        broken = [None, (), ("Constructed",), ("Constructed", 1, {}, "private marker"),
                  row("private marker"), row("constructed"), row(None), row(["Constructed"])]
        broken += [row(revision=value) for value in (None, True, False, 0, -1, 1.0, "1",
                                                    field_policy.MAX_REVISION + 1)]
        broken += [("Constructed", 1, value) for value in (None, [], "private marker", {},
                   {"v": 1}, {"rules": []}, {"v": True, "rules": []}, {"v": 1.0, "rules": []},
                   {"v": "1", "rules": []}, {"v": 2, "rules": []}, {"v": 1, "rules": {}},
                   {"v": 1, "rules": [], "reason": "private marker"},
                   {"v": 1, "rules": [], "format": "Commander"},
                   {"v": 1, "rules": [], "revision": 100})]
        for value in broken:
            with self.subTest(value=value):
                self.assertEqual(self.invariant([value]), INVALID)

    def test_duplicate_format_rows_fail_even_when_individually_valid(self):
        self.assertEqual(self.invariant([row(), row(revision=2)]), INVALID)

    def test_duplicate_structured_epochs_fail(self):
        self.assertEqual(self.invariant([row(rules=[rule("exclude"), rule("rules")])]), INVALID)

    def test_different_incarnations_of_the_same_origin_are_distinct(self):
        rules = [rule(), rule(kind="creation"), rule(kind="creation", revision=2)]
        self.assertEqual(self.invariant([row(rules=rules)]), (True, False, "valid policy for 1 format"))

    def test_cross_format_and_non_household_epochs_fail(self):
        for fmt, deck in (("Commander", "casual/private-marker"), ("Constructed", "commander/private-marker"),
                          ("Constructed", "user2/casual/private-marker"), ("Commander", "product/private-marker")):
            with self.subTest(fmt=fmt, deck=deck):
                self.assertEqual(self.invariant([row(fmt, rules=[rule(deck=deck)])]), INVALID)

    def test_rule_unknown_fields_versions_modes_and_epoch_types_fail(self):
        wrong = [dict(rule(), reason="private marker"), dict(rule(), mode="private marker"),
                 dict(rule(), version="target"), dict(rule("include"), version="private marker"),
                 dict(rule(), epoch={"kind": "baseline", "deck_id": "casual/a", "revision": 2}),
                 dict(rule(), epoch={"kind": "creation", "deck_id": "casual/a", "revision": True}),
                 dict(rule(), epoch={"kind": "creation", "deck_id": "casual/a", "revision": 10_001}),
                 dict(rule(), epoch={"kind": "creation", "deck_id": "casual/a", "revision": 2, "extra": 1})]
        for value in wrong:
            with self.subTest(value=value):
                self.assertEqual(self.invariant([row(rules=[value])]), INVALID)

    def test_noncanonical_rule_order_is_not_silently_rewritten(self):
        self.assertEqual(self.invariant([row(rules=[rule(deck="casual/z"), rule(deck="casual/a")])]),
                         (False, False, "the field policy is not in its complete saved form"))

    def test_policy_capacity_is_validated_without_pruning_old_epochs(self):
        with mock.patch.object(field_policy, "MAX_RULES", 1):
            self.assertEqual(self.invariant([row(rules=[rule(deck="casual/a"), rule(deck="casual/b")])]), INVALID)

    def test_database_error_and_logged_outcome_never_quote_raw_error_or_saved_inputs(self):
        conn = FakeConn(error=RuntimeError("private marker: SQL or policy data"))
        said = []
        run = check._Run(said.append)
        run.sub("field policy", check._field_policy(conn), conn)
        self.assertEqual(conn.transactions, 1)
        self.assertEqual(run.failed, ["field policy"])
        self.assertEqual(run.checks[0]["detail"], "the field policy could not be checked")
        self.assertNotIn("private marker", "\n".join(said))


class ExportGatingTests(unittest.TestCase):
    def write(self, folder, conn):
        psycopg = SimpleNamespace(IsolationLevel=SimpleNamespace(REPEATABLE_READ="fixture-read"))
        def csv(c, name, order):
            if name == TABLE:
                self.assertFalse(conn.missing, "must not query a missing policy table")
                self.assertEqual(order, ("format",))
                return b'format,revision,content\nConstructed,1,"{""v"":1,""rules"":[]}"\n'
            return b"fixture\n"
        with mock.patch.dict(sys.modules, {"psycopg": psycopg}), \
                mock.patch.object(export.db, "connect", return_value=conn) as connect, \
                mock.patch.object(export, "table_csv", side_effect=csv) as tables, \
                mock.patch.object(export, "wishlist_files", return_value={}), \
                mock.patch.object(export, "inventory_files", return_value={}) as inventory, \
                mock.patch.object(export, "write_inventory") as write_inventory:
            export.write_tables(folder)
        connect.assert_called_once_with("ro", dbname=None)
        inventory.assert_called_once_with(conn)
        write_inventory.assert_called_once_with(folder / export.MAGIC, {})
        self.assertTrue(conn.read_only)
        self.assertTrue(conn.rolled_back)
        return tables

    def test_absent_migration_keeps_prior_policy_csv_without_disabling_inventory_export(self):
        with tempfile.TemporaryDirectory(prefix="decklab-policy-export-") as tmp:
            folder = Path(tmp)
            saved = folder / "tables/public.field_policy.csv"
            saved.parent.mkdir()
            prior = b"fixture prior policy export\n"
            saved.write_bytes(prior)
            tables = self.write(folder, FakeConn(missing=True))
            self.assertEqual(saved.read_bytes(), prior)
            self.assertNotIn(TABLE, [call.args[1] for call in tables.call_args_list])
            self.assertTrue((folder / "tables/public.collection_card.csv").is_file())

    def test_absent_migration_does_not_invent_an_empty_policy_csv(self):
        with tempfile.TemporaryDirectory(prefix="decklab-policy-export-") as tmp:
            folder = Path(tmp)
            self.write(folder, FakeConn(missing=True))
            self.assertFalse((folder / "tables/public.field_policy.csv").exists())

    def test_ready_table_is_exported_deterministically_in_the_same_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="decklab-policy-export-") as tmp:
            folder = Path(tmp)
            self.write(folder, FakeConn())
            saved = folder / "tables/public.field_policy.csv"
            first = saved.read_bytes()
            self.assertIn(b"Constructed,1,", first)
            self.write(folder, FakeConn())
            self.assertEqual(saved.read_bytes(), first)
