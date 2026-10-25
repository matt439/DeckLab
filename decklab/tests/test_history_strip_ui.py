"""The History page's picture strip as one row (history.js historyStripFit): as many pictures as fit the column,
then a "+N" tile for the rest, so "+N" always ends the first row.

Loads every page script into the event/DOM double (fixtures/workspace_ui_runner.js): no browser or server.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SCENARIO = r"""
  // A phone (327 px column, 60 px tiles, 8 px gaps): 4 slots, 3 pictures and "+N".
  same(historyStripFit(327, 60, 8, 12, 55), { shown: 3, more: 52 });
  // A MacBook (910 px, 72 px tiles): 11 slots, 10 pictures and "+N".
  same(historyStripFit(910, 72, 8, 12, 55), { shown: 10, more: 45 });
  // QHD (781 px, 88 px tiles): 8 slots.
  same(historyStripFit(781, 88, 8, 12, 55), { shown: 7, more: 48 });
  // Everything fits: no tile.
  same(historyStripFit(910, 72, 8, 5, 5), { shown: 5, more: 0 });
  // Every picture fits but some changes have none: the tile still ends the row.
  same(historyStripFit(910, 72, 8, 5, 7), { shown: 5, more: 2 });
  // Exactly full without a tile; one more change makes room for it.
  same(historyStripFit(320, 72, 8, 4, 4), { shown: 4, more: 0 });
  same(historyStripFit(320, 72, 8, 4, 5), { shown: 3, more: 2 });
  // Too narrow for even a picture: just the tile.
  same(historyStripFit(50, 72, 8, 4, 5), { shown: 0, more: 5 });
  // The tile is made whenever the strip could open the sheet, so the fit can show it at any width.
  const card = (name) => ({ name, img_small: `/img/${name}/small` });
  const entries = [1, 2, 3].map((i) => ({ list: "target", section: "Deck", name: `C${i}`, delta: 1, card: card(`C${i}`) }));
  const strip = historyPictures(entries, "g", 0, () => {});
  assert(strip.querySelector(".history-pic-more-item"));
  assert.equal(strip.getAttribute("data-total"), "3");
  assert.equal(historyPictures(entries, "g", 0, null).querySelector(".history-pic-more-item"), null);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class HistoryStripTests(unittest.TestCase):
    def test_one_row_with_its_more_tile(self):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SCENARIO, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
