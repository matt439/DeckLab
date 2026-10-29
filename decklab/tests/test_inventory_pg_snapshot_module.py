"""The extracted snapshot reader (E11-S39) keeps pg.py's names and its conversion unchanged."""
import subprocess
import sys
import unittest

from decklab.lib.inventory import paths, pg, pg_snapshot
from decklab.lib.inventory.table_rows import STATUS_COLUMNS
from decklab.lib.state import Invalid


MOVED = ("SELECTS", "_render", "_select", "_status_columns", "_status_tables", "snapshot")


def rows():
    """Every table _select reads, empty but for a few rows."""
    data = {table: [] for table in pg_snapshot.SELECTS}
    data["collection_card"] = [("home", "fdn", "227", "nonfoil", "Llanowar Elves", 2, "NM", "en", "", "Row 2, B"),
                               ("home", "fdn", "1", "nonfoil", "Ajani's Pridemate", 1, "", "", "", "")]
    data["token_card"] = [(41, "home", 2048, "Dog", "Beast", "", "", "", "", 1, "", "3/3", ""),
                          (40, "home", 1024, "Treasure", "", "", "", "", "", 2, "", "", "")]
    data["watchlist_item"] = [(7, 1024, "Clifftop Retreat", "", "", "", 2, "Deck", "any", None, "", "", "",
                               "", "ready", "")]
    return data


class PgSnapshotModuleTests(unittest.TestCase):
    def test_either_module_can_be_imported_first(self):
        for module in ("pg", "pg_snapshot"):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-c", f"from decklab.lib.inventory import {module}; "
                     "from decklab.lib.inventory import pg, pg_snapshot as s; "
                     "assert pg.snapshot is s.snapshot and pg._select is s._select"],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_pg_names_are_the_extracted_objects(self):
        for name in MOVED:
            with self.subTest(name=name):
                self.assertIs(getattr(pg, name), getattr(pg_snapshot, name))

    def test_the_snapshot_module_never_reads_pg(self):
        self.assertFalse(hasattr(pg_snapshot, "pg"))
        self.assertFalse(hasattr(pg_snapshot, "PgInventory"))

    def test_a_multiline_cell_moves_the_next_rows_line(self):
        self.assertEqual(pg._render(("a", "b"), [("x", "two\nlines"), (None, 3)]),
                         (b'a,b\nx,"two\nlines"\n,3\n', [2, 4]))

    def test_rows_become_the_canonical_snapshot_with_hidden_ids(self):
        inv = pg.snapshot(rows(), 12)
        self.assertEqual((inv.revision, inv.backend, inv.locations_ready), ("12", "db", True))
        self.assertEqual([(r.id, r.line, r.front) for r in inv.tokens["home"].rows],
                         [(40, 2, "Treasure"), (41, 3, "Dog")])
        self.assertEqual([(r.id, r.line) for r in inv.watchlist.rows], [(7, 2)])
        self.assertEqual([r.name for r in inv.collections["home"].rows], ["Ajani's Pridemate", "Llanowar Elves"])
        self.assertEqual(inv.locations["home"].path, paths.locations("home"))
        self.assertEqual([r.line for r in inv.locations["home"].rows], [2])

    def test_an_old_schema_takes_blank_packing_and_refuses_a_recorded_one(self):
        columns = tuple(c for c in STATUS_COLUMNS if c != "token_cards")
        blank = {"product_status": {"a.csv": (1, "owned", "yes", "", "", "", "")}}
        self.assertEqual(pg._status_tables(blank, columns)["product_status"],
                         {"a.csv": (1, "owned", "yes", "", "", "")})
        self.assertIs(pg._status_tables(blank, STATUS_COLUMNS), blank)
        recorded = {"product_status": {"a.csv": (1, "owned", "yes", "", "", "", "2 Treasure")}}
        with self.assertRaises(Invalid):
            pg._status_tables(recorded, columns)


if __name__ == "__main__":
    unittest.main()
