"""Reconcile physical copies within the scanner sheet, using fixture observations only."""
import json
import subprocess
import unittest

from decklab.tests.test_collection_scan_ui import FIXTURE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CardAuditResultTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = """
          draw();
          const writes = [];
          apiWrite = async (...args) => { writes.push(args); throw Error('Unexpected write'); };
          const open = (mode, rows, extras = {}) => startCardAudit({
            title: 'Audit test', instructions: 'Count the physical cards.', space: 'home',
            current: () => true, scan: {available: false}, mode, rows, ...extras});
          const count = (ctx, p, copies) => { for (let i=0; i<copies; i++) addScanCard(ctx, p); };
          const finish = ctx => foot(ctx, 'finish').click();
          const words = ctx => ctx.sheet.body.textContent;
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + setup + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_wrong_finish_does_not_net_against_expected_copy_or_untracked_basic(self):
        self.run_js("""
          const elves = ELVES.proposals[0];
          const ctx = open('section', [{...elves, quantity:2, estimated:true}], {excludedNames:['Forest']});
          count(ctx, {...elves, finish:'foil'}, 2);
          count(ctx, proposal('Forest', 'tst', '01', 'name and number'), 3);
          finish(ctx);
          assert(words(ctx).includes('2 counted · 2 expected'));
          assert(words(ctx).includes('Missing (2)') && words(ctx).includes('Extra (2)'));
          assert(words(ctx).includes('Non-foil') && words(ctx).includes('Foil') && words(ctx).includes('2 expected (estimate)'));
          assert(words(ctx).includes('Outside this audit') && words(ctx).includes('3 × Forest'));
          assert(!words(ctx).includes('No extras.'));
          foot(ctx, 'back').click();
          assert.equal(ctx.pending.reduce((n,row)=>n+row.quantity,0),5);
          same(writes, []);
        """)

    def test_deck_combines_editions_and_sections_and_counts_basics_and_markers(self):
        self.run_js("""
          const marker = 'Unspecified stand-in for Opt';
          const ctx = open('deck', [{name:'Llanowar Elves', quantity:2}, {name:'Forest', quantity:1},
            {name:marker, quantity:1, manual:true}]);
          count(ctx, ELVES.proposals[0], 1); count(ctx, {...ELVES.proposals[1], finish:'foil'}, 1);
          count(ctx, proposal('Forest', 'tst', '01', 'name and number'), 1);
          finish(ctx);
          assert(!foot(ctx,'done'));
          const hand = ctx.sheet.body.querySelector('[aria-label="Counted for Unspecified stand-in for Opt"]');
          assert.equal(document.activeElement, hand);
          hand.value = '1'; finish(ctx);
          assert(words(ctx).includes('4 counted · 4 expected'));
          assert(words(ctx).includes('All expected cards accounted for. No extras.'));
          foot(ctx,'back').click(); assert.equal(hand.value, '1');
          hand.value='0'; finish(ctx);
          assert(words(ctx).includes('Missing (1)') && words(ctx).includes(marker));
          foot(ctx,'done').click(); assert(ctx.sheet.closed); same(writes, []);
        """)

    def test_empty_stack_reports_entire_expected_list_and_equal_counts_disclose_skipped_photos(self):
        self.run_js("""
          const ctx = open('deck', [{name:'Llanowar Elves', quantity:3}]);
          finish(ctx);
          assert(words(ctx).includes('Missing (3)') && words(ctx).includes('0 counted · 3 expected'));
          foot(ctx,'back').click();
          count(ctx, ELVES.proposals[0], 3);
          drawScanResult(ctx, {proposals:[], message:'Unreadable'});
          finish(ctx); assert(!foot(ctx,'done'));
          button(ctx.sheet.body,'Skip this photo').click(); finish(ctx);
          assert(words(ctx).includes('1 photo skipped') && !words(ctx).includes('All expected cards accounted for.'));
          const done = foot(ctx,'done');
          as('user2', MAY.user2); done.click(); assert(!ctx.sheet.closed);
          same(writes, []);
        """)
