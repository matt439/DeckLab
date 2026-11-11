"""Failed field and popular-deck runs through the real sections and polling controls.

Every API answer and timer is deterministic; no server, database or Forge run is used.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + """
  clear(main);editor=null;state.may=null;
  const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
  const failure='No games could be played. Every matchup that needed games failed; the server log says why.';
  const deck={id:'commander/precon-trial',version:'target',title:'Precon trial',card_sha:'a'.repeat(64)};
  const opponent={id:'commander/other',version:'target',title:'Other deck',games:0,rate:null,
    lead:null,residual:null,not_meaningful:false,problem:null};
  const base=(kind)=>({deck,format:kind==='field'?'Commander':'commander',opponents:[opponent],
    average:null,rating:null,coverage:{with_floor:0,of:1},last_run:null,notes:[],field_lists:[],
    forge:{ready:true},default_budget:kind==='field'?'standard':'fixed:100',budgets:{},
    status:'none',job:null,notice:null,error:null,games:0,groups:{},
    catalogue:{playable:1},sample:{id:'sample:0123456789ab',size:20,decks:1,filters:{tiers:['core']}},
    options:{sizes:[20],styles:['aggro'],tiers:['core']},default_size:20});
  toast=()=>{throw new Error('A completed failed run must keep its error in the section.');};
  syncRunsPill=()=>{};

  async function failedRun(kind){
    const initial=base(kind),calls=[],writes=[];
    const live={...initial,status:'running',job:{status:'running',done:0,total:100,ahead:0,may_stop:true,
      pairs:{pair:{opponent,done:0,total:100,playing:true}}}};
    const failed={...initial,status:'error',error:failure,
      opponents:[{...opponent,problem:'Forge could not play this matchup.'}]};
    api=async path=>{calls.push(path);return structuredClone(calls.length===1?initial:failed);};
    apiWrite=async(path,body)=>{writes.push({path,body});return structuredClone(live);};
    location.hash=deckHref(deck.id)+'&tab=matchups';
    const data={summary:{id:deck.id,title:deck.title,kind:'commander',trial:'precon-fixture'},version:'target'};
    const section=kind==='field'?fieldSection(data):gauntletSection(data);
    main.append(section);await settle();
    const playText=kind==='field'?'Play the field':'Play them';
    const play=buttonText(section,playText);assert(play&&!play.disabled);
    assert.equal(calls.length,1);assert.equal(writes.length,0);
    play.click();await settle();
    assert.equal(writes.length,1);assert.equal(writes[0].path,`/api/${kind==='field'?'field':'gauntlet'}/run`);
    assert.equal(writes[0].body.id,deck.id);
    const playing=kind==='field'?'Playing the field':'Playing popular decks';
    assert(section.querySelectorAll('h3').some(n=>n.textContent.includes(playing)));
    assert(buttonText(section,'Stop'));assert(!buttonText(section,playText));

    flushTimers();await settle();
    assert.equal(calls.length,2);
    const error=section.querySelector('.box-crit');assert(error);assert.equal(error.textContent,failure);
    assert(!section.querySelectorAll('h3').some(n=>n.textContent.includes(playing)));
    const retry=buttonText(section,playText);assert(retry&&!retry.disabled);
    assert(!buttonText(section,'Stop'));
    flushTimers();await settle();flushTimers();await settle();
    assert.equal(calls.length,2,'A terminal failure must stop polling.');
    assert.equal(writes.length,1,'A terminal failure must not retry automatically.');
    assert.equal(section.querySelector('.box-crit').textContent,failure);
  }
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SimulationFailureUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_field_failure_remains_visible_after_running_progress_disappears(self):
        self.run_js("await failedRun('field');")

    def test_popular_decks_failure_remains_visible_after_running_progress_disappears(self):
        self.run_js("await failedRun('popular');")
