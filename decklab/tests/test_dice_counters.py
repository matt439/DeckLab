"""Owned dice and counters (E7-S24's second slice): the rows' rules, the inventory operations on the
files backend, the database rows (as table_rows and pg_snapshot make them, with no database),
migration 0020 before it's applied, whether they cover a deck's counter needs, the API's privacy and
writes, the command line, and the Activity rows. The same on a real database is in
test_dice_counters_pg.py (it skips without one).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_dice_counters
"""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.db import migrate
from decklab.lib import inventory
from decklab.lib.inventory import (Op, dice_rules, files, model, ops_dice, paths, pg_dice, pg_snapshot, rules,
                                   table_rows)
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state import Actor, Conflict, Invalid
from decklab.lib.tokens import counters, dice_cover

ACTOR = Actor("claude", "Claude", source="cli")
D20 = {"type": "die", "size": "d20", "kind": "", "design": "red", "quantity": "2", "notes": ""}
POISON = {"type": "counter", "size": "", "kind": "poison", "design": "", "quantity": "5", "notes": ""}
GENERIC = {"type": "counter", "size": "", "kind": "", "design": "glass beads", "quantity": "30", "notes": ""}


def tree():
    """A temp magic/ with an empty status list and purchase queue: the files backend's least."""
    root = Path(tempfile.mkdtemp(prefix="decklab-dice-"))
    (root / "magic" / "products").mkdir(parents=True)
    (root / "magic" / "products" / "status.csv").write_bytes(rules.csv_bytes([], rules.STATUS_FIELDS))
    (root / "magic" / "watchlist.csv").write_bytes(rules.csv_bytes([], model.QUEUE_FIELDS))
    return root


class RulesTests(unittest.TestCase):

    def test_a_row_is_tidied_and_checked(self):
        self.assertEqual(dice_rules.clean_row({"type": " Counter ", "kind": "+1/+1 Counters", "quantity": 3}),
                         {"type": "counter", "size": "", "kind": "+1/+1", "design": "", "quantity": "3", "notes": ""})
        self.assertEqual(dice_rules.clean_row({"type": "counter", "kind": "−1/−1", "quantity": "0"})["kind"], "-1/-1")
        self.assertEqual(dice_rules.clean_row({"type": "die", "size": "Spindown", "design": "  blue  swirl ",
                                               "quantity": "1"}),
                         {"type": "die", "size": "spindown", "kind": "", "design": "blue swirl", "quantity": "1", "notes": ""})
        for bad, words in (({"type": "bead", "quantity": 1}, "die or counter"),
                           ({"type": "die", "quantity": 1}, "size"),
                           ({"type": "die", "size": "d7", "quantity": 1}, "size"),
                           ({"type": "die", "size": "d6", "kind": "poison", "quantity": 1}, "any kind"),
                           ({"type": "counter", "size": "d6", "quantity": 1}, "Only a die"),
                           ({"type": "counter", "quantity": 10000}, "0 to 9999"),
                           ({"type": "counter", "quantity": -1}, "0 to 9999"),
                           ({"type": "counter", "quantity": True}, "whole number"),
                           ({"type": "counter", "kind": "+lots", "quantity": 1}, "P/T"),
                           ({"type": "counter", "design": "=HYPERLINK()", "quantity": 1}, "can't start"),
                           ({"type": "counter", "notes": "two\nlines", "quantity": 1}, "one line"),
                           ({"type": "counter", "colour": "red", "quantity": 1}, "Unknown column")):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, words):
                dice_rules.clean_row(bad)

    def test_the_order_and_the_names(self):
        rows = [GENERIC, POISON, D20, {**D20, "size": "d6", "design": ""}]
        self.assertEqual([dice_rules.label(r) for r in sorted(rows, key=dice_rules.sort_key)],
                         ["d6", "d20 (red)", "counter (glass beads)", "poison counter"])
        self.assertEqual(dice_rules.identity({**D20, "design": "RED", "quantity": "9"}), dice_rules.identity(D20))


class OpsTests(unittest.TestCase):

    def setUp(self):
        self.root = tree()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(inventory.use(FileInventory(self.root)))

    def sha(self, space="home"):
        sheet = inventory.current().dice_set(space)
        return files.rendered_sha256(sheet) if sheet.exists else None

    def apply(self, kind, **params):
        return inventory.apply(Op(f"dice.{kind}", params), ACTOR, f"{kind} dice")

    def test_add_edit_and_remove_keep_the_file_sorted_and_apart_from_the_tokens(self):
        _, summary = self.apply("add", space="home", sha256=None, row=POISON)
        self.assertEqual(summary.text, "Added poison counter ×5 to the home dice and counters")
        _, summary = self.apply("add", space="home", sha256=self.sha(), row=D20)
        self.assertEqual((summary.extra["index"], summary.counts), (0, {"items": 7}))
        path = self.root / "magic" / "dice.csv"
        self.assertEqual(path.read_text(encoding="utf-8"),
                         "type,size,kind,design,quantity,notes\ndie,d20,,red,2,\ncounter,,poison,,5,\n")
        self.assertFalse((self.root / "magic" / "tokens.csv").exists())
        _, summary = self.apply("edit", space="home", sha256=self.sha(), base=POISON, row={**POISON, "quantity": "0"})
        self.assertEqual(summary.text, "Changed poison counter ×0 in the home dice and counters")
        self.assertIn("counter,,poison,,0,", path.read_text(encoding="utf-8"))   # 0 keeps the row
        after, summary = self.apply("remove", space="home", sha256=self.sha(), base={**POISON, "quantity": "0"})
        self.assertEqual([r.as_dict() for r in after.dice_set("home").rows], [D20])
        self.apply("remove", space="home", sha256=self.sha(), base=D20)
        self.assertFalse(path.exists())                 # no rows: no file
        self.assertEqual(inventory.current().spaces(), ["home"])

    def test_refusals(self):
        self.apply("add", space="home", sha256=None, row=D20)
        sha = self.sha()
        with self.assertRaises(ops_dice.SameItem) as same:
            self.apply("add", space="home", sha256=sha, row={**D20, "design": "Red", "quantity": "1"})
        self.assertEqual(same.exception.index, 0)
        with self.assertRaises(ops_dice.Stale):
            self.apply("add", space="home", sha256=None, row=POISON)
        with self.assertRaises(ops_dice.Stale):
            self.apply("edit", space="home", sha256=sha, base={**D20, "quantity": "3"}, row=D20)
        with self.assertRaisesRegex(Invalid, "can't be saved"):
            self.apply("add", space="home", sha256=sha, row={**POISON, "quantity": "lots"})
        # A person's space is its own list.
        self.apply("add", space="user2", sha256=None, row=POISON)
        self.assertTrue((self.root / "magic" / "people" / "user2" / "dice.csv").exists())
        self.assertEqual(self.sha(), sha)

    def test_nothing_is_recorded_before_migration_0020(self):
        before = inventory.current().replace(dice_ready=False)
        with self.assertRaisesRegex(Invalid, "migration 0020"):
            ops_dice.add(before, space="home", sha256=None, row=D20)

    def test_a_list_with_rows_it_cant_read_is_not_rewritten(self):
        (self.root / "magic" / "dice.csv").write_text("type,size,kind,design,quantity,notes\ndie,d7,,,1,\n",
                                                      encoding="utf-8")
        sheet = inventory.current().dice_set("home")
        self.assertEqual(sheet.problems[0][:30], "Row 1 of the home dice and cou")
        with self.assertRaises(Conflict):
            self.apply("add", space="home", sha256=files.rendered_sha256(sheet), row=POISON)
        self.assertIn("the home dice and counters", table_rows.reasons(inventory.current())[paths.dice("home")][0])


class RowsTests(unittest.TestCase):
    """dice.csv as the database's rows, and the rows back as a snapshot (no database)."""

    def snapshot(self, dice=(), ready=True):
        data = {table: [] for table in pg_snapshot.SELECTS}
        data.update({"product_status": [], "dice_ready": ready, pg_dice.TABLE: list(dice)})
        return pg_snapshot.snapshot(data, 7)

    def test_the_rows_go_both_ways_with_their_ids(self):
        inv = self.snapshot([(41, "home", 2048, "counter", "", "poison", "", 5, ""),
                             (40, "home", 1024, "die", "d20", "", "red", 2, ""),
                             (50, "user2", 1024, "die", "d6", "", "", 1, "")])
        self.assertEqual([(r.id, r.as_dict()) for r in inv.dice_set("home").rows], [(40, D20), (41, POISON)])
        self.assertEqual(inv.spaces(), ["home", "user2"])
        self.assertEqual(table_rows.tables(inv)["dice_counter"],
                         [(40, "home", "die", "d20", "", "red", 2, ""), (41, "home", "counter", "", "poison", "", 5, ""),
                          (50, "user2", "die", "d6", "", "", 1, "")])
        self.assertEqual(table_rows.DICE_COLUMNS[:3], ("item_type", "die_size", "counter_kind"))

    def test_before_migration_0020_every_space_has_none_and_a_write_refuses(self):
        inv = self.snapshot(ready=False)
        self.assertFalse(inv.dice_ready)
        self.assertEqual(dict(inv.dice), {})
        t = table_rows.tables(inv)
        self.assertEqual(pg_dice.compatible(t, False)["dice_counter"], [])
        with self.assertRaisesRegex(Invalid, "migration 0020"):
            pg_dice.compatible({**t, "dice_counter": [(0, "home", "die", "d6", "", "", 1, "")]}, False)

    def test_the_schema_probe_and_its_read(self):
        class Connection:
            def __init__(self, ready):
                self.ready, self.sql = ready, []

            def execute(self, sql, *args):
                self.sql.append(sql)
                rows = [[self.ready]] if "to_regclass" in sql else [(1, "home", 1024, "die", "d6", "", "", 1, "")]
                return mock.Mock(fetchone=lambda: rows[0], fetchall=lambda: rows)
        old = Connection(False)
        self.assertEqual(pg_dice.rows(old, pg_dice.ready(old)), [])
        self.assertFalse(any("from dice_counter" in sql for sql in old.sql))
        new = Connection(True)
        self.assertEqual(len(pg_dice.rows(new, pg_dice.ready(new))), 1)


class MigrationTests(unittest.TestCase):

    def test_0020_follows_0019_and_is_audited_per_space(self):
        found = migrate.available()
        self.assertEqual([(f["version"], f["name"]) for f in found[18:20]],
                         [(19, "new_deck_drafts"), (20, "dice_counters")])
        sql = found[19]["sql"] if "sql" in found[19] else Path(found[19]["path"]).read_text(encoding="utf-8")
        self.assertIn("create table public.dice_counter", sql)
        self.assertIn("space_id text not null", sql)
        self.assertIn("quantity int not null check (quantity between 0 and 9999)", sql)
        self.assertIn("audit.log_row('id')", sql)
        self.assertIn("audit.refuse_truncate()", sql)
        for size in dice_rules.SIZES:
            self.assertIn(f"'{size}'", sql)
        self.assertNotIn("references", sql)          # a space's rows, as token_card's

    def test_the_export_and_member_removal_know_the_table_only_once_it_exists(self):
        from decklab.db import export, space_apply, space_remove
        self.assertIn(("public.dice_counter", ("space_id", "position", "id")), export.TABLES)
        self.assertIn("public.dice_counter", export.UNTIL_MIGRATED)
        self.assertIn("public.dice_counter", space_apply.OPTIONAL_TABLES)
        self.assertLess(space_apply.DELETE_ORDER.index("dice_counter"), space_apply.DELETE_ORDER.index("space"))
        self.assertEqual(space_remove._TABLE_KEYS["dice"], ("dice_counter", ("id",)))

    def test_the_export_writes_magic_before_the_table_exists(self):
        """Before migration 0020 the export skips dice_counter's CSV but still writes the
        inventory's files (the snapshot reads no dice), as it did before the table existed."""
        import sys
        import types
        from decklab.db import export

        class Cursor:
            def __init__(self, value):
                self.value = value

            def fetchone(self):
                return (self.value,)

        class Conn:
            isolation_level = read_only = None

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=()):
                return Cursor(bool(params) and params[0] == "public.dice_counter")

            def rollback(self):
                pass

        psycopg = types.ModuleType("psycopg")
        psycopg.IsolationLevel = types.SimpleNamespace(REPEATABLE_READ="rr")
        repo = Path(tempfile.mkdtemp(prefix="decklab-dice-export-"))
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        written = []
        with mock.patch.dict(sys.modules, {"psycopg": psycopg}),                 mock.patch.object(export.db, "connect", return_value=Conn()),                 mock.patch.object(export, "table_csv", side_effect=lambda c, name, order_by: name.encode()),                 mock.patch.object(export, "wishlist_files", return_value={}),                 mock.patch.object(export, "inventory_files", return_value={"collection.csv": b"x"}),                 mock.patch.object(export, "write_inventory", side_effect=lambda folder, files: written.append(files)):
            export.write_tables(repo)
        self.assertEqual(written, [{"collection.csv": b"x"}])
        tables = {path.name for path in (repo / "tables").glob("*.csv")}
        self.assertIn("public.collection_card.csv", tables)
        self.assertNotIn("public.dice_counter.csv", tables)


class CoverTests(unittest.TestCase):
    NEEDS = {"needs": [{"key": "+1/+1", "group": "permanent"}, {"key": "loyalty", "group": "permanent"},
                       {"key": "poison", "group": "player"}, {"key": "d20", "group": "die"},
                       {"key": "d6", "group": "die"}], "note": counters.NOTE}

    def states(self, rows):
        found = dice_cover.cover(self.NEEDS, rows)
        return [need["cover"]["state"] for need in found["needs"]], found["owned"]

    def test_a_named_kind_first_then_one_generic_item_each(self):
        states, owned = self.states([POISON, {**D20, "quantity": "1"}])
        # poison by its own counters; the d20 covers the roll and stands for +1/+1; loyalty is left.
        self.assertEqual(states, ["generic", "none", "named", "named", "none"])
        self.assertEqual((owned["dice"], owned["counters"], owned["generic"]), (1, 5, 1))
        states, _ = self.states([GENERIC])
        self.assertEqual(states, ["generic", "generic", "generic", "none", "none"])
        states, _ = self.states([{**D20, "size": "spindown", "quantity": "1"}, {**POISON, "quantity": "0"}])
        # 0 owned poison counters are none; the one spindown stands for +1/+1 and is a d20.
        self.assertEqual(states, ["generic", "none", "none", "named", "none"])

    def test_nothing_owned_and_not_ready(self):
        states, owned = self.states([])
        self.assertEqual(set(states), {"none"})
        self.assertEqual(owned["words"], dice_cover.NONE_RECORDED)
        found = dice_cover.cover(self.NEEDS, [D20], ready=False)
        self.assertEqual(found["owned"]["ready"], False)
        self.assertNotIn("cover", found["needs"][0])
        self.assertNotIn("cover", self.NEEDS["needs"][0])          # the needs given aren't changed

    def test_a_size_the_records_lack_says_it_cant_be_recorded(self):
        found = dice_cover.cover({"needs": [{"key": "d100", "group": "die"}]}, [D20, {**D20, "size": "d10"}])
        cover = found["needs"][0]["cover"]
        self.assertEqual(cover["state"], "none")
        self.assertEqual(cover["words"], "Deck Lab doesn't record d100s (it records d4 to d20 and spindowns)")
        self.assertEqual(counters.text_kinds("Roll a d100."), ["d100"])     # the cards can still call for one


class ActivityTests(unittest.TestCase):

    def test_rows_are_worded_and_kept_in_their_space(self):
        from decklab.lib.api import activity_summaries as summaries
        from decklab.lib.state import rules as state_rules
        self.assertIn("dice_counter", summaries.SPACE_TABLES)
        self.assertNotIn("notes", summaries.INVENTORY_FIELDS["dice_counter"])
        row = {"space_id": "home", "item_type": "counter", "die_size": "", "counter_kind": "poison", "design": "",
               "quantity": 5}
        say = summaries.INVENTORY_SUMMARIES["dice_counter"]
        self.assertEqual(say("INSERT", None, row, "the home"), "Added 5 × poison counter to the home dice and counters")
        self.assertEqual(say("UPDATE", row, {**row, "quantity": 3}, "the home"),
                         "Changed poison counter in the home dice and counters: quantity 5 → 3")
        change = {"rows": [{"table": "dice_counter", "op": "INSERT", "key": {"id": 1}, "after": {**row, "space_id": "user2"}}]}
        spec = {"tables": ("dice_counter",), "items": (), "spaces": ("home",), "cap": 10}
        self.assertEqual(state_rules.inventory_rows(change, spec)["rows"], [])


class CliTests(unittest.TestCase):

    def setUp(self):
        self.root = tree()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(inventory.use(FileInventory(self.root)))
        notices = mock.patch("decklab.db.read_notices.Reporter.space")      # no visibility read
        notices.start()
        self.addCleanup(notices.stop)

    def run_cli(self, *argv):
        from decklab.db import __main__ as cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_list_add_edit_and_remove(self):
        code, out, err = self.run_cli("dice", "add", "--type", "die", "--size", "d20", "--design", "red",
                                      "--quantity", "2", "--expect", "none", "-m", "Our d20s")
        self.assertEqual(code, 0, err)
        self.assertIn("Added d20 (red) ×2", out)
        code, out, _ = self.run_cli("dice", "list", "--json")
        listed = json.loads(out)
        self.assertEqual((listed["ready"], listed["rows"]), (True, [D20]))
        sha = listed["sha256"]
        code, out, err = self.run_cli("dice", "edit", "1", "--expect", sha[:12], "--quantity", "3", "--dry-run", "-m", "x")
        self.assertEqual(code, 0, err)
        self.assertIn("Nothing saved", out)
        code, _, err = self.run_cli("dice", "edit", "1", "--expect", "0" * 12, "--quantity", "3", "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("changed since", err)
        code, _, err = self.run_cli("dice", "add", "--type", "die", "--size", "d20", "--design", "Red", "--quantity", "1",
                                    "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("already listed", err)
        code, out, err = self.run_cli("dice", "remove", "1", "--expect", sha, "-m", "Lost", "--reason", "Lost them")
        self.assertEqual(code, 0, err)
        self.assertFalse((self.root / "magic" / "dice.csv").exists())


if __name__ == "__main__":
    unittest.main()
