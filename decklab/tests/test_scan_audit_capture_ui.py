"""Physical audits use the real scanner without sending a batch to collection import."""
import unittest

from decklab.tests import test_collection_scan_live_ui as live_ui
from decklab.tests import test_collection_scan_ui as scan_ui


@unittest.skipUnless(scan_ui.NODE, "Node.js isn't installed")
class AuditCaptureTests(unittest.TestCase):
    def run_js(self, scenario):
        fixture = """
          as('matt', MAY.admin);
          let current = true;
          const results = [];
          const target = {title: 'Audit this stack', instructions: 'Scan the entire stack.', space: 'home',
            current: () => current, finish: (cards, skipped, ctx) => {
              results.push({cards, skipped});
              ctx.auditReview = true;
              sheetActions(ctx.sheet, [{text: 'Audit result', value: 'result'}]);
            }};
        """
        scan_ui.CollectionScanUiTests.run_js(self, live_ui.CAMERA + fixture + scenario)

    def test_live_count_tracks_each_presentation_and_reports_explicit_skips_without_import(self):
        self.run_js("""
          const ctx = openAuditScan(target), calls = [], replies = [ELVES, ELVES, GHALTA];
          apiWrite = async (path, body) => { calls.push([path, body.space]); return replies.shift(); };
          await start(ctx);
          for (let presentation = 0; presentation < 3; presentation++) {
            await frames(card, 12);
            await frames(mat, 6);
          }
          assert.equal(foot(ctx, 'finish'), null);
          clickText(ctx.sheet.body, 'Stop camera');
          assert(hardware.track.stops > 0);
          assert.equal(foot(ctx, 'download'), null);
          foot(ctx, 'finish').click();
          assert.equal(results.length, 0);
          assert.equal(document.activeElement, ctx.checks);
          button(ctx.checks, 'Skip this photo').click();
          foot(ctx, 'finish').click();
          same(results[0].cards.map(row => [row.name, row.quantity]), [['Llanowar Elves', 2]]);
          assert.equal(results[0].skipped, 1);
          assert(!ctx.sheet.closed);
          same(calls, Array(3).fill(['/api/collection/scan', 'home']));
          results[0].cards[0].choices[0].set = 'changed';
          assert.equal(ctx.pending[0].choices[0].set, 'fdn');
          drawScanFoot(ctx);
          assert(foot(ctx, 'result'));
          ctx.name.value = 'Llanowar Elves';
          api = () => { throw new Error('No lookup during report'); };
          await findScanName(ctx);
          await scanPhoto(ctx, {});
          assert.equal(calls.length, 3);
          ctx.auditReview = false; drawScanFoot(ctx);
          assert(foot(ctx, 'finish'));
        """)

    def test_empty_and_manual_audits_can_finish_on_a_server_without_ocr(self):
        self.run_js("""
          let manual = false;
          const ctx = openAuditScan({...target, scan: {available: false},
            manualDescription: () => manual ? 'Discard your hand count?' : ''});
          assert(!ctx.live && !ctx.grid);
          assert(ctx.sheet.body.textContent.includes("type each card's name"));
          foot(ctx, 'finish').click();
          same(results[0], {cards: [], skipped: 0});
          ctx.auditReview = false; drawScanFoot(ctx);
          manual = true;
          foot(ctx, 'cancel').click();
          assert(ctx.sheet.dialog.textContent.includes('Discard your hand count?'));
          button(ctx.sheet.dialog, 'Keep scanning').click();
          ctx.name.value = 'Llanowar Elves';
          api = async () => ({name: 'Llanowar Elves', printings: [
            {set: 'fdn', set_name: 'Foundations', collector_number: '227', finishes: ['nonfoil', 'foil']} ]});
          await findScanName(ctx);
          ctx.result.querySelector('button').click();
          const finish = foot(ctx, 'finish');
          const count = pick(ctx, 'Copies of Llanowar Elves');
          count.value = '3'; count.fire('change');
          assert.equal(foot(ctx, 'finish'), finish, 'Quantity blur keeps the pressed Finish button mounted');
          finish.click();
          same(results[1].cards.map(row => [row.set, row.quantity]), [['fdn', 3]]);
        """)

    def test_capture_and_completion_stay_with_the_original_audit_owner(self):
        self.run_js("""
          assert.equal(openAuditScan({...target, space: 'user2'}), null);
          const ctx = openAuditScan(target), calls = [];
          let resolve, signal;
          apiWrite = (path, body, method, options) => {
            calls.push(path); signal = options.signal; return new Promise(r => { resolve = r; });
          };
          await start(ctx); await frames(card, 12);
          assert.equal(calls.length, 1);
          current = false;
          await frames(card, 6);
          assert(signal.aborted);
          assert(hardware.track.stops > 0);
          resolve(ELVES); await flush();
          same(ctx.pending, []);
          current = true;
          const finish = foot(ctx, 'finish');
          const hash = location.hash;
          location.hash = '#/other'; finish?.click(); reviewScan(ctx);
          location.hash = hash; state.profile = PROFILES[1]; finish?.click(); reviewScan(ctx);
          assert.equal(results.length, 0);
          state.profile = PROFILES[0]; ctx.sheet.close(); finish?.click(); reviewScan(ctx);
          assert.equal(results.length, 0);
          same(calls, ['/api/collection/scan']);
        """)

    def test_deck_counts_confirmed_names_across_printings_and_can_correct_one_copy(self):
        self.run_js("""
          const ctx = openAuditScan({...target, mode: 'deck'});
          const forest = {read: {name: 'Forest', name_exact: true}, proposals: [
            proposal('Forest // Forest', 'rex', '1', 'name', {canonical_name: 'Forest'}),
            proposal('Forest', 'fdn', '2', 'name', {canonical_name: 'Forest'})]};
          assert.equal(drawScanResult(ctx, forest), 'added');
          assert.equal(drawScanResult(ctx, forest), 'added');
          same(ctx.pending, [{name: 'Forest', quantity: 2}]);
          assert(!ctx.list.querySelector('select'));
          assert(!ctx.list.textContent.includes('REX'));
          foot(ctx, 'finish').click();
          ctx.auditReview = false; drawScanFoot(ctx);
          button(ctx.result, 'Correct this scan').click();
          same(ctx.pending, [{name: 'Forest', quantity: 1}]);
          assert.equal(ctx.unsure.length, 1);
          ctx.name.value = 'Island';
          api = async () => ({name: 'Island', printings: [
            {set: 'fdn', collector_number: '3', finishes: ['nonfoil']},
            {set: 'eld', collector_number: '4', finishes: ['nonfoil']} ]});
          await findScanName(ctx);
          button(ctx.result, 'Island').click();
          assert.equal(ctx.unsure.length, 0);
          same(ctx.pending, [{name: 'Forest', quantity: 1}, {name: 'Island', quantity: 1}]);
          const dfc = {proposals: [proposal('Day // Night', 'mid', '21', 'name and number',
            {canonical_name: 'Day // Night'})]};
          assert.equal(drawScanResult(ctx, dfc), 'added');
          assert.equal(ctx.pending[2].name, 'Day // Night');
        """)

    def test_deck_refuses_fuzzy_name_number_only_and_conflicts_beyond_display_limit(self):
        self.run_js("""
          const ctx = openAuditScan({...target, mode: 'deck'});
          const base = {read: {name: 'Forest', name_exact: false}, proposals: [proposal('Forest', 'fdn', '1', 'name')]};
          assert.equal(drawScanResult(ctx, base), 'review');
          assert.equal(drawScanResult(ctx, {proposals: [proposal('Forest', 'eld', '4', 'number')]}), 'review');
          const many = Array.from({length: 12}, (_, i) => proposal('Forest', 'eld', String(i), 'name'));
          many.push(proposal('Island', 'fdn', '1', 'number'));
          assert.equal(drawScanResult(ctx, {read: {name: 'Forest', name_exact: true}, proposals: many}), 'review');
          same(ctx.pending, []);
          assert.equal(ctx.result.querySelectorAll('.col-scan-pick').length, 2);
          button(ctx.result, 'Island').click();
          same(ctx.pending, [{name: 'Island', quantity: 1}]);
          assert.equal(ctx.unsure.length, 2);
        """)

    def test_section_retains_canonical_names_and_printing_choices_across_report(self):
        self.run_js("""
          const ctx = openAuditScan({...target, mode: 'section'});
          const raw = 'Forest // Forest';
          const first = proposal(raw, 'rex', '1', 'name and number', {canonical_name: 'Forest'});
          const second = proposal(raw, 'a25', '2', 'name', {canonical_name: 'Forest'});
          drawScanResult(ctx, {proposals: [first, second]});
          foot(ctx, 'finish').click();
          assert.equal(results[0].cards[0].canonical_name, 'Forest');
          assert.equal(results[0].cards[0].name, raw);
          ctx.auditReview = false; drawScanFoot(ctx);
          ctx.result.querySelector('.col-scan-pick').click();
          assert.equal(ctx.pending[0].set, 'a25');
          assert.equal(ctx.pending[0].canonical_name, 'Forest');
          drawScanResult(ctx, {read: {name: 'Forest', name_exact: true}, proposals: [{...first, how: 'name'}, second]});
          assert.equal(ctx.unsure.length, 1);
        """)
