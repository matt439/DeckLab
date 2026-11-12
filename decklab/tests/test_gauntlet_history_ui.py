"""The Testing tab's Earlier lists (E3-S50, web/gauntlet.js gtHistory) through the real renderers over an isolated
Node DOM: asked for only when Show earlier lists is pressed, each list's date, figure, range and opponents, a
muted list without a figure, the steps' cards and same-opponent comparison, and the bound's note. Every answer is
a fixture; no live server, network, configuration, database or simulation is used.

Run with python scripts/test_fixtures.py decklab.tests.test_gauntlet_history_ui.
"""
import json
import subprocess
import unittest

from decklab.tests.test_gauntlet_ui import DAY, SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

HISTORY = DAY + """
  const std={id:'sample:0123456789ab',size:24,tiers:['hard','medium']};
  const view=base({standard:std,is_standard:true});
  const hrow=(extra)=>({current:false,saved:day,state:'tested',rate:.5,low:.4,high:.6,played:3,of:3,games:300,
    updated:day,older:null,...extra});
  const hist={deck:{id:'casual/test',version:'target'},format:'constructed',state:'listed',sample:std,
    lists:[hrow({current:true,rate:.6,low:.5,high:.7,played:2}),
      hrow({state:'older',rate:null,low:null,high:null,games:0,updated:null,
        older:{reason:'pilot',opponents:2,of:3,updated:day}}),
      hrow({rate:.41,low:.33,high:.49})],
    steps:[{added:[[1,'Sol Ring']],removed:[[2,'Opt']],more_added:0,more_removed:3,compare:null,uncompared:'no_figure'},
      {added:[[3,'Forest']],removed:[],more_added:0,more_removed:0,uncompared:null,
        compare:{same:2,before:{rate:.41,low:.33,high:.49},now:{rate:.6,low:.5,high:.7},moved:1}}],
    complete:false,notes:["Not every earlier list was looked at, so this isn't every list."],max_lists:8};
  const reads=[];let historyAnswer=hist;
  api=async(path)=>{reads.push(path);if(path.startsWith('/api/gauntlet/history?')){
    if(historyAnswer instanceof Error)throw historyAnswer;return structuredClone(historyAnswer);}
    return structuredClone(view);};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class GauntletHistoryUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + HISTORY + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_asked_for_only_when_shown(self):
        self.run_js("""
          const node=await draw();
          assert(!reads.some((p)=>p.startsWith('/api/gauntlet/history')));
          buttonText(node,'Show earlier lists').click();await settle();
          same(reads.filter((p)=>p.startsWith('/api/gauntlet/history')),
            ['/api/gauntlet/history?id=casual%2Ftest&version=target&profile=matt']);
          assert(!buttonText(node,'Show earlier lists'));
          assert(node.querySelector('.gt-history').querySelector('h3').textContent==='Earlier lists');
        """)

    def test_each_list_and_step(self):
        self.run_js("""
          const node=await draw();
          buttonText(node,'Show earlier lists').click();await settle();
          const rows=[...node.querySelectorAll('.gt-history-row')];
          assert.equal(rows.length,3);
          assert(rows[0].textContent.startsWith('This list (saved 2 Nov): 60% (50–70) against 2 of 3 opponents, tested 2 Nov.'),
            rows[0].textContent);
          assert(rows[1].textContent.includes('Saved 2 Nov: Tested only with another AI pilot, so no figure today.'));
          assert(hasClass(rows[1],'gt-muted'));assert(!rows[1].textContent.includes('%'));
          assert(rows[2].textContent.includes('41% (33–49) against 3 of 3 opponents'));
          assert(rows[2].querySelector('.gt-before-bar'));
          const steps=[...node.querySelectorAll('.gt-history-step')];
          assert.equal(steps.length,2);
          assert.equal(steps[0].textContent,'Added 1 Sol Ring · Taken out 2 Opt and 3 more');
          assert(steps[1].textContent.includes('Added 3 Forest'));
          assert(steps[1].textContent.includes('Same 2 opponents: 41% (33–49) before, 60% (50–70) after. 1 opponent moved'));
          assert(node.querySelector('.gt-history-note').textContent.includes("this isn't every list"));
        """)

    def test_no_shared_opponents_and_no_earlier_list(self):
        self.run_js("""
          historyAnswer={...hist,lists:[hist.lists[0],hist.lists[2]],complete:true,notes:[],
            steps:[{added:[],removed:[],more_added:0,more_removed:0,compare:null,uncompared:'no_shared'}]};
          let node=await draw();
          buttonText(node,'Show earlier lists').click();await settle();
          const step=node.querySelector('.gt-history-step').textContent;
          assert(step.includes('No played card changed.'));
          assert(step.includes('No opponent tested against both lists'));
          assert(!node.querySelector('.gt-history-note'));
          historyAnswer={...hist,state:'none',lists:[hist.lists[0]],steps:[],complete:true,notes:[]};
          clear(main);node=await draw();
          buttonText(node,'Show earlier lists').click();await settle();
          assert(node.textContent.includes('No earlier list of this deck has results against the standard sample.'));
          assert(!node.querySelector('.gt-history-list'));
        """)

    def test_a_failure_offers_try_again_and_another_sample_has_none(self):
        self.run_js("""
          historyAnswer=Object.assign(new Error('down'),{status:500});
          const node=await draw();
          buttonText(node,'Show earlier lists').click();await settle();
          assert(node.querySelector('.gt-history').querySelector('.load-failed'));
          historyAnswer=hist;
          buttonText(node,'Try again').click();await settle();
          assert.equal(node.querySelectorAll('.gt-history-row').length,3);
          const other=base({standard:std,is_standard:false,sample:{id:'sample:aaaaaaaaaaaa',size:24,filters:{},decks:3,saved:true}});
          api=async()=>structuredClone(other);
          clear(main);const again=await draw();
          assert(!again.querySelector('.gt-history'));
        """)


if __name__ == "__main__":
    unittest.main()
