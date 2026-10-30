"""forge-trial/card_audit.py's collect(): the decks come from the inventory (the database since
phase 4's cutover deleted the deck files), with both names of the substitute list's heading.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_card_audit
"""
import contextlib
import importlib.util
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from decklab.lib import inventory
from decklab.lib.inventory.files import FileInventory

HERE = Path(__file__).resolve().parents[1] / "forge-trial"
DECK = ("# Green\n\n- **Status:** idea\n\n## Decklist\n\n```\nDeck\n4 Llanowar Elves (FDN) 227\n```\n\n"
        "### Substitute version (owned and incoming cards)\n\n```\nDeck\n4 Elvish Mystic (CMM) 648\n```\n")
OLD = ("# Red\n\n- **Status:** idea\n\n## Decklist\n\n```\nDeck\n4 Shock (M19) 156\n```\n\n"
       "### Owned-only version\n\n```\nDeck\n4 Lightning Bolt (M10) 146\n```\n")


def load():
    spec = importlib.util.spec_from_file_location("card_audit_under_test", HERE / "card_audit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CollectTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "magic").mkdir()
        (self.root / "magic" / "collection.csv").write_text(
            "name,set,collector_number,finish,quantity,condition,language,notes\n", encoding="utf-8")
        self.audit = load()

    def collect(self):
        err = io.StringIO()
        with inventory.use(FileInventory(self.root)), contextlib.redirect_stderr(err):
            uses = self.audit.collect(Path(tempfile.gettempdir()) / "no-such-repo")    # never read
        return uses, err.getvalue()

    def test_the_decks_are_the_inventory_s(self):
        for rel, text in (("casual/green.md", DECK), ("casual/red.md", OLD)):
            path = self.root / "magic" / "decks" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        uses, err = self.collect()
        self.assertEqual(uses["Llanowar Elves"], [{"group": "deck", "source": "casual/green", "list": "target",
                                                   "section": "Main", "qty": 4}])
        self.assertEqual([u["list"] for u in uses["Elvish Mystic"]], ["owned"])      # Substitute version
        self.assertEqual([u["list"] for u in uses["Lightning Bolt"]], ["owned"])     # Owned-only version
        self.assertEqual(err, "")

    def test_no_decks_is_said(self):
        uses, err = self.collect()
        self.assertFalse([u for found in uses.values() for u in found if u["group"] == "deck"])
        self.assertIn("the inventory has no decks", err)


if __name__ == "__main__":
    unittest.main()
