"""Scan throughput uses the saved import receipt and the whole session's elapsed time."""
import unittest

from decklab.tests import test_collection_scan_ui as scan_ui


@unittest.skipUnless(scan_ui.NODE, "Node.js is not installed")
class ScanRateTests(unittest.TestCase):
    def run_js(self, scenario):
        scan_ui.CollectionScanUiTests.run_js(self, r"""
          const start = Date.UTC(2026, 10, 20, 9);
          let now = start, receipt;
          Date.now = () => now;
          colReload = (_view, words) => { receipt = words; };
          const preview = { token: 't'.repeat(32), format:'collection', rows:[], problems:[],
            adds:{rows:1, cards:4}, dropped_basics:2, sha256:'s1', repeat_imports:[] };
          const applied = {ok:true, added:{cards:4, rows:1}, skipped:1, sha256:'s2'};
          let lastImport;
          const makeImport = openImportSheet;
          openImportSheet = view => (lastImport = makeImport(view));
        """ + scenario)

    def test_start_survives_review_back_and_stale_preview_retry(self):
        self.run_js(r"""
          let attempts = 0;
          apiWrite = async path => {
            if (path.endsWith('/preview')) return preview;
            assert.equal(path, '/api/collection/import/apply');
            if (++attempts === 1) throw new ApiError(409, 'Repeat imports changed', {repreview_required:true});
            return applied;
          };
          const ctx = openScanSheet(draw());
          // Six copies staged. Only the four the server actually saved count towards the rate.
          for (let i=0;i<6;i++) drawScanResult(ctx, ELVES);
          now += 30000;
          reviewScan(ctx); await flush();
          assert.equal(receipt, undefined);
          assert(lastImport.area.textContent.includes('2 plain basic lands left out'), lastImport.area.textContent);
          lastImport.sheet.foot.querySelector('[data-action="back"]').click();
          now += 30000;
          const reopened = [...colSheets].at(-1);
          reopened.foot.querySelector('[data-action="review"]').click(); await flush();
          await applyImport(lastImport, false);
          assert.equal(receipt, undefined);
          now += 60000;
          button(lastImport.sheet.foot,'Preview again').click(); await flush();
          await applyImport(lastImport, false);
          assert(receipt.includes('Imported 4 cards'), receipt);
          assert(receipt.includes('2 min (120 saved copies/hour)'), receipt);
          assert(receipt.includes('1 row with problems skipped'), receipt);
        """)

    def test_replacing_scan_with_file_does_not_report_scanner_pace(self):
        self.run_js(r"""
          apiWrite = async path => path.endsWith('/preview') ? preview : applied;
          const ctx = openScanSheet(draw());
          drawScanResult(ctx, ELVES);
          reviewScan(ctx); await flush();
          const input = lastImport.input;
          input.files = [{name:'scan-2026-11-20.csv', size:16, text:async () => 'a different source'}];
          input.fire('change'); await flush();
          now += 60000;
          await applyImport(lastImport, false);
          assert(receipt.includes('Imported 4 cards'), receipt);
          assert(!receipt.includes('copies/hour'), receipt);
          assert(!receipt.includes('Scan to import'), receipt);
        """)

    def test_missing_count_or_clock_reversal_never_claims_a_rate(self):
        self.run_js(r"""
          assert.equal(colScanImportRate(start + 1000, applied), '');
          assert.equal(colScanImportRate(start, applied), '');
          now += 60000;
          for (const added of [undefined, {}, {cards:0}, {cards:'4'}, {cards:-1}]) {
            assert.equal(colScanImportRate(start, {ok:true, added}), '');
          }
          assert.equal(colScanImportRate(null, applied), '');
        """)
