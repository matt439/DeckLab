"""Nullable target roundtrip, legacy CSV preservation and guarded CLI/source writes."""
import argparse
import contextlib
import io

from decklab.db import inv_orders
from decklab.lib import inventory
from decklab.lib.inventory import Op, files, orders, ops_shop_references, pg_snapshot, pg_targets, rules, table_rows
from decklab.lib.state import Conflict, Invalid
from decklab.tests import test_inventory_pg_snapshot_module as snapshot_fixture
from decklab.tests import test_shop_reference_api as fixture


class WatchlistTargetBackendTests(fixture._ReferenceFixture):
    def command(self, *words):
        parser = argparse.ArgumentParser()
        inv_orders.register(parser.add_subparsers())
        args = parser.parse_args(["watchlist", *words])
        output = io.StringIO()
        with contextlib.redirect_stdout(output), inventory.pinned():
            self.assertEqual(args.func(args), 0)
        return output.getvalue()

    def test_cli_target_has_an_explicit_aud_flag_dry_run_and_one_audited_write(self):
        before = files.render(self.current(), decks=True)
        text = self.command("set", "#1", "--buy-under-aud", "2.50", "-m", "Set an AUD market target", "--dry-run")
        self.assertIn("Dry run: nothing saved", text)
        self.assertEqual(files.render(self.current(), decks=True), before)
        self.command("set", "#1", "--buy-under-aud", "2.50", "-m", "Set an AUD market target")
        self.assertEqual(self.current().watchlist.rows[0].buy_under_aud, "2.50")
        self.assertEqual(len(self.writes), 1)
        self.assertEqual((self.current().watchlist.rows[0].state, self.current().watchlist.rows[0].quantity), ("ready", "3"))

    def test_legacy_csv_keeps_a_newer_target_and_explicit_blank_clears_it(self):
        self.command("set", "#1", "--buy-under-aud", "2.50", "-m", "Set an AUD market target")
        row = self.current().watchlist.rows[0].as_dict()
        legacy = {key: value for key, value in row.items() if key != "buy_under_aud"}
        legacy["state"] = "long_term"
        path = self.box.root / "legacy-queue.csv"
        path.write_bytes(rules.csv_bytes([legacy], orders.QUEUE_FIELDS[:-1]))
        self.command("apply", "--csv", str(path), "-m", "Edit legacy queue intent")
        self.assertEqual(self.current().watchlist.rows[0].buy_under_aud, "2.50")
        current = self.current().watchlist.rows[0].as_dict()
        current["buy_under_aud"] = ""
        path.write_bytes(rules.csv_bytes([current], orders.QUEUE_FIELDS))
        self.command("apply", "--csv", str(path), "-m", "Clear the market target explicitly")
        self.assertEqual(self.current().watchlist.rows[0].buy_under_aud, "")

    def test_prepared_cli_target_refuses_changed_queue_or_source_without_partial_writes(self):
        before = self.current()
        original = Op("watchlist.set", {"select": "#1", "values": {"buy_under_aud": "2.50"}, "repo": str(self.box.root)})
        prepared = ops_shop_references.guard_cli(original, before)
        self.snapshot["cards"]["Llanowar Elves"]["at"] = "2026-11-11T13:00:00Z"
        with self.assertRaises(Conflict):
            inventory.apply(prepared, fixture.ACTOR, "Refuse a changed source")
        self.assertEqual(files.render(self.current(), decks=True), files.render(before, decks=True))
        prepared = ops_shop_references.guard_cli(original, self.current())
        inventory.apply(Op("watchlist.set", {"select": "#1", "values": {"notes": "Changed queue"}, "repo": str(self.box.root)}),
                        fixture.ACTOR, "Change the queue")
        with self.assertRaises(Conflict):
            inventory.apply(prepared, fixture.ACTOR, "Refuse stale target edit")
        self.assertEqual(self.current().watchlist.rows[0].buy_under_aud, "")

    def test_optional_column_old_schema_refuses_chosen_values_and_synthesizes_blank_reads(self):
        before = self.current()
        with self.assertRaisesRegex(Invalid, "migration 0026"):
            Op("watchlist.set", {"select": "#1", "values": {"buy_under_aud": "2.50"}, "repo": str(self.box.root)}).run(
                before.replace(targets_ready=False))
        self.assertEqual(files.render(self.current()), files.render(before))
        full = table_rows.tables(before)
        old = pg_targets.compatible(full, False)
        self.assertEqual(len(old["watchlist_item"][0]), len(table_rows.WATCH_COLUMNS))
        after, _ = Op("watchlist.set", {"select": "#1", "values": {"buy_under_aud": "2.50"}, "repo": str(self.box.root)}).run(before)
        with self.assertRaisesRegex(Invalid, "migration 0026"):
            pg_targets.compatible(table_rows.tables(after), False)
        data = snapshot_fixture.rows()
        data["targets_ready"] = False
        rebuilt = pg_snapshot.snapshot(data, "legacy-target-schema")
        self.assertFalse(rebuilt.targets_ready)
        self.assertEqual(rebuilt.watchlist.rows[0].buy_under_aud, "")
