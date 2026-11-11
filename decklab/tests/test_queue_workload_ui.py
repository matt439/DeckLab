"""Anonymous queue workload through the real shared formatter and waiting renderers.

The deterministic DOM runner loads the page scripts without a server or Forge games.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = r"""
  state.profile={id:'user2',name:'User2',space:'user2',role:'member'};
  state.may={admin:false,runs:false};
  const sides=[{id:'user2/casual/a',title:'A',version:'target'},
    {id:'user2/casual/b',title:'B',version:'target'}];
  const work=(games=1200,unknown=0,approximate=false)=>({games,unknown,approximate});
  const waiting=(extra={})=>({key:'opaque',status:'queued',ahead:2,done:0,total:200,
    sides,title:'A v B',link:'#/matchup?key=opaque',wins:[0,0],may_stop:false,
    mode:'fixed',ahead_work:work(),...extra});
  const textParts=parts=>parts.flat(Infinity).filter(Boolean).map(n=>n.textContent).join('');
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class QueueWorkloadUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_exact_upper_bound_partial_and_unknown_work_keep_their_meaning(self):
        self.run_js(r"""
          assert.equal(runAheadWork(waiting()),'1,200 games remaining in this queue');
          assert.equal(runAheadWork(waiting({ahead_work:work(1200,0,true)})),
            'up to 1,200 games remaining in this queue');
          assert.equal(runAheadWork(waiting({ahead_work:work(1200,1,false)})),
            'at least 1,200 games remaining in this queue; some run sizes are unknown');
          assert.equal(runAheadWork(waiting({ahead_work:work(1200,1,true)})),
            'known work: up to 1,200 games remaining in this queue; some run sizes are unknown');
          assert.equal(runAheadWork(waiting({ahead_work:work(0,2,false)})),
            'size of the work ahead is not known yet');
          assert.equal(runAheadWork(waiting({ahead_work:work(0)})),'0 games remaining in this queue');
          assert.equal(runAheadWork(waiting({ahead_work:work(1)})),'1 game remaining in this queue');
          // Only numeric aggregate fields are used, even if a malformed server adds private details.
          assert.equal(runAheadWork(waiting({ahead_work:{...work(),title:'private deck',by:'private person'}})),
            '1,200 games remaining in this queue');
        """)

    def test_missing_malformed_and_nonqueued_answers_add_no_summary(self):
        self.run_js(r"""
          for(const value of [undefined,null,{},[],2,'private error',work(-1),work(1.5),work('1200'),
              work(NaN),work(Infinity),work(Number.MAX_SAFE_INTEGER+1),work(3,-1),work(3,1.5),
              work(3,3),work(3,0,'yes'),{games:3,unknown:0}]){
            assert.equal(runAheadWork(waiting({ahead_work:value})),null,JSON.stringify(value));
          }
          for(const status of ['running','done','error',undefined])
            assert.equal(runAheadWork(waiting({status})),null,status);
          for(const ahead of [0,-1,1.5,'2',null,undefined])
            assert.equal(runAheadWork(waiting({ahead})),null,String(ahead));
          assert.equal(runAheadWork(null),null);
        """)

    def test_matchup_progress_updates_work_then_removes_it_when_playing(self):
        self.run_js(r"""
          const live=liveBox({});
          live.update({sides,job:waiting()});
          const played=live.node.querySelector('.mu-played');
          assert(played.textContent.includes('2 other runs are ahead of this one'));
          assert(played.textContent.includes('1,200 games remaining in this queue.'));
          live.update({sides,job:waiting({ahead:1,ahead_work:work(450,0,true)})});
          assert(played.textContent.includes('1 other run is ahead of this one'));
          assert(played.textContent.includes('Up to 450 games remaining in this queue.'));
          assert(!played.textContent.includes('1,200'));
          live.update({sides,job:waiting({status:'running',done:30})});
          assert.equal(played.textContent,'30 of 200 games played.');
          live.update({sides,job:waiting({ahead_work:undefined})});
          assert.equal(played.textContent,'2 other runs are ahead of this one; it starts as soon as they\'re done.');
        """)

    def test_overview_rows_and_top_bar_details_show_only_the_aggregate(self):
        self.run_js(r"""
          const queued=waiting(),coordinator=waiting({sides:null,title:'My field run',kind:'field'});
          for(const run of [queued,coordinator]){
            const row=runningRow(run),details=textParts(runDetailsParts([run]));
            assert(row.textContent.includes('2 runs ahead of it'));
            assert(row.textContent.includes('1,200 games remaining in this queue'));
            assert(details.includes('2 runs ahead · 1,200 games remaining in this queue'));
            assert(!details.includes('min'));
            assert.equal(row.querySelectorAll('button').length,0);
          }
          const old=waiting({ahead:0,ahead_work:undefined});
          assert(textParts(runDetailsParts([old])).includes('next'));
          assert(!textParts(runDetailsParts([old])).includes('remaining in this queue'));
          const next=textParts(runDetailsParts([waiting({ahead:1,ahead_work:work(0,1)})]));
          assert(next.includes('1 run ahead · size of the work ahead is not known yet'));
        """)

    def test_field_group_and_popular_decks_panels_scope_the_work_to_the_queue(self):
        self.run_js(r"""
          for(const draw of [fvLive,grLive,gtLive]){
            const a={status:'queued',job:waiting({ahead_work:work(1800,0,true)})};
            const words=textParts(draw({},a));
            assert(words.includes('Waiting: 2 runs ahead of it · up to 1,800 games remaining in this queue'));
            assert(!words.includes('min'));
            const playing=textParts(draw({},{...a,status:'running'}));
            assert(!playing.includes('remaining in this queue'));
            const old=textParts(draw({},{...a,job:waiting({ahead_work:undefined})}));
            assert(old.includes('Waiting: 2 runs ahead of it'));
            assert(!old.includes('remaining in this queue'));
          }
        """)

    def test_variant_panel_keeps_unknown_and_upper_bound_work_explicit(self):
        self.run_js(r"""
          const a={status:'queued',job:waiting({ahead_work:work(3200,1,true)})};
          const words=vtLivePanel({},a).textContent;
          assert(words.includes('2 test or field runs ahead of it.'));
          assert(words.includes('Known work: up to 3,200 games remaining in this queue; some run sizes are unknown.'));
          assert(!words.includes('At least'));
          const playing=vtLivePanel({},{...a,status:'running'}).textContent;
          assert(!playing.includes('remaining in this queue'));
          const old=vtLivePanel({},{...a,job:waiting({ahead_work:undefined})}).textContent;
          assert(old.includes('2 test or field runs ahead of it.'));
          assert(!old.includes('remaining in this queue'));
        """)
