"""Second-simulator controls through the real UI with isolated DOM/API doubles.

These checks exercise delayed reads/writes and page ownership; they do not run a browser or games.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  clear(main);deckScreen=null;editor=null;state.profile={id:'matt',name:'Matt'};
  location.hash='#/deck?id=casual%2Ftest&v=target&tab=matchups';
  const calls=[],writes=[];let answers=[],readImpl=null,writeImpl=null;
  const settle=async()=>{for(let i=0;i<16;i++)await Promise.resolve();};
  api=async(path)=>{calls.push(path);if(readImpl)return readImpl(path);
    const next=answers.length>1?answers.shift():answers[0];if(next instanceof Error)throw next;return structuredClone(next);};
  apiWrite=async(path,body)=>{writes.push({path,body});return writeImpl?writeImpl(path,body):structuredClone(answers[0]);};
  const sha='b'.repeat(64),otherSha='c'.repeat(64),test='d'.repeat(64);
  const choices=[{id:'casual/blue',version:'target',title:'Blue Deck'},
    {id:'user2/casual/elves',version:'owned',title:'Elves'}];
  const base=(extra={})=>({deck:{id:'casual/test',version:'target',title:'Test Deck',card_sha:sha},
    opponent:null,choices,games_choices:[10,20,50],default_games:10,ready:true,may_start:true,why_not:null,
    engines:{forge:{ready:true,version:'1'},xmage:{ready:true,version:'2'}},
    note:'These are 1v1 games; each simulator keeps its own score.',test:null,status:'none',job:null,result:null,...extra});
  const chosen=(extra={})=>base({opponent:{id:'casual/blue',version:'target',title:'Blue Deck',card_sha:otherSha},...extra});
  const running=()=>chosen({test,status:'running',job:{test,status:'running',done:3,total:20,may_stop:true}});
  const counts=(rate)=>({asked:10,completed:8,wins:4,losses:3,draws:1,failed:1,timeouts:1,cancelled:0,unplayed:0,
    win_rate:rate,win_rate_interval:{low:rate-20,high:rate+20,confidence:.95}});
  const result=(extra={})=>({id:'e'.repeat(64),status:'partial',current:true,has_variant:false,
    decks:{baseline:{id:'casual/test'},opponent:{id:'casual/blue',title:'Blue Deck'}},
    agreement:{text:'Compare the scores separately.'},engines:{forge:{baseline:counts(50)},xmage:{baseline:counts(25)}},...extra});
  const mount=()=>{const node=crosscheckSection({summary:{id:'casual/test'},version:'target'});main.append(node);return node;};
  const load=async(answer=base())=>{answers=[answer];const node=mount();
    buttonText(node,'Choose a deck to test against').click();await settle();return node;};
  const pick=async(node,answer=chosen())=>{answers=[answer];const select=node.querySelector('#cc-opponent');
    select.value='casual/blue';select.fire('change');await settle();};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CrosscheckUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_testing_does_not_read_or_start_before_opening_the_part(self):
        self.run_js("""
          const node=mount();same(calls,[]);same(writes,[]);
          answers=[base()];buttonText(node,'Choose a deck to test against').click();await settle();
          assert(calls[0].startsWith('/api/crosscheck?id=casual%2Ftest&version=target'));
          assert(buttonText(node,'Run both simulators').disabled);same(writes,[]);
        """)

    def test_selecting_an_opponent_uses_both_saved_fingerprints_on_start(self):
        self.run_js("""
          const node=await load();await pick(node);
          assert(calls.at(-1).includes('opponent=casual%2Fblue'));
          const games=node.querySelector('#cc-games');games.value='20';games.fire('change');
          answers=[running()];buttonText(node,'Run both simulators').click();await settle();
          same(writes,[{path:'/api/crosscheck/run',body:{id:'casual/test',version:'target',opponent:'casual/blue',
            opponent_version:'target',games:20,expected_card_sha:sha,expected_opponent_card_sha:otherSha}}]);
          assert(node.textContent.includes('3 of 20 games processed'));
          assert(buttonText(node,'Run both simulators').disabled);assert(buttonText(node,'Stop check'));
        """)

    def test_unavailable_and_paused_states_disable_start(self):
        self.run_js("""
          const node=await load(chosen({ready:false,engines:{forge:{ready:true},xmage:{ready:false,problem:'XMage needs setup.'}}}));
          assert(node.textContent.includes('XMage needs setup.'));buttonText(node,'Run both simulators').click();same(writes,[]);
          answers=[chosen({may_start:false,why_not:'Simulations are paused.'})];
          buttonText(node,'Refresh check').click();await settle();
          assert(node.textContent.includes('Simulations are paused.'));assert(buttonText(node,'Run both simulators').disabled);
        """)

    def test_scores_ranges_and_failures_remain_separate(self):
        self.run_js("""
          const saved=result();saved.engines.xmage.missing_cards=['New Card'];
          const node=await load(chosen({result:saved,status:'partial'}));
          const rows=node.querySelector('tbody').children;
          same(rows.map(row=>row.children.map(cell=>cell.textContent)),[
            ['Forge','8','50.0%','30.0–70.0%','2'],['XMage','8','25.0%','5.0–45.0%','2']]);
          assert(node.textContent.includes('XMage does not support: New Card.'));
          assert(node.textContent.includes('no combined win rate'));
          assert(!node.textContent.includes('37.5%'));
        """)

    def test_old_results_warn_and_missing_rates_are_not_zero(self):
        self.run_js("""
          const saved=result({current:false});saved.engines.xmage.baseline.win_rate=null;
          const node=await load(chosen({result:saved,status:'partial'}));
          assert(node.textContent.includes('A saved list has changed since this check'));
          assert.equal(node.querySelector('tbody').children[1].children[2].textContent,'—');
        """)

    def test_cancelled_games_are_not_counted_twice_as_unfinished(self):
        self.run_js("""
          const saved=result();for(const engine of Object.values(saved.engines))
            Object.assign(engine.baseline,{asked:10,completed:3,failed:0,timeouts:0,cancelled:7,unplayed:7});
          const node=await load(chosen({result:saved,status:'cancelled'}));
          for(const row of node.querySelector('tbody').children) assert.equal(row.children.at(-1).textContent,'7');
        """)

    def test_failed_loading_offers_retry_and_never_an_empty_success(self):
        self.run_js("""
          const node=await load(new ApiError(503,'fixture server unavailable'));
          assert(node.textContent.includes('fixture server unavailable'));assert(buttonText(node,'Try again'));
          assert(!node.querySelector('#cc-opponent'));answers=[base()];
          buttonText(node,'Try again').click();await settle();assert(node.querySelector('#cc-opponent'));same(writes,[]);
        """)

    def test_unexpected_read_failure_keeps_its_private_message_out_of_the_page(self):
        self.run_js("""
          const node=await load(new Error('PRIVATE fixture diagnostic'));
          assert(!node.textContent.includes('PRIVATE'));assert(/Reference [a-f0-9]{32}/.test(node.textContent));
          assert(buttonText(node,'Try again'));assert(!node.querySelector('#cc-opponent'));
          answers=[base()];buttonText(node,'Try again').click();await settle();assert(node.querySelector('#cc-opponent'));same(writes,[]);
        """)

    def test_late_reads_do_not_attach_after_page_profile_hash_or_connection_changes(self):
        for change in ("routeToken++", "state.profile={id:'user1'}", "location.hash='#/library'", "node.remove()"):
            with self.subTest(change=change):
                self.run_js("""
                  let resolve;readImpl=()=>new Promise(done=>resolve=done);const node=mount();
                  buttonText(node,'Choose a deck to test against').click();await settle();
                  const before=node.textContent;
                """ + change + ";resolve(base());await settle();assert.equal(node.textContent,before);same(writes,[]);")

    def test_an_older_opponent_reply_cannot_replace_a_newer_choice(self):
        self.run_js("""
          const node=await load();const pending=[];readImpl=()=>new Promise(done=>pending.push(done));
          let select=node.querySelector('#cc-opponent');select.value='casual/blue';select.fire('change');await settle();
          // Choices stay connected while another read is pending; the latest choice owns its reply.
          select.value='user2/casual/elves';select.fire('change');await settle();
          pending[1](base({opponent:{id:'user2/casual/elves',version:'owned',title:'Elves',card_sha:otherSha}}));await settle();
          pending[0](chosen());await settle();
          assert.equal(node.querySelector('#cc-opponent').value,'user2/casual/elves');same(writes,[]);
        """)

    def test_a_pending_start_is_not_sent_twice_and_late_success_cannot_redraw(self):
        self.run_js("""
          const node=await load(chosen());let resolve;writeImpl=()=>new Promise(done=>resolve=done);
          const start=buttonText(node,'Run both simulators');start.click();start.click();await settle();
          assert.equal(writes.length,1);const before=node.textContent;state.profile={id:'user1'};
          resolve(running());await settle();assert.equal(node.textContent,before);
        """)

    def test_a_replaced_start_control_cannot_submit_the_latest_check(self):
        self.run_js("""
          const node=await load(chosen());const old=buttonText(node,'Run both simulators');
          answers=[chosen()];buttonText(node,'Refresh check').click();await settle();
          assert(!old.isConnected);old.click();await settle();same(writes,[]);
        """)

    def test_lost_start_response_requires_a_read_before_another_start(self):
        self.run_js("""
          const node=await load(chosen());writeImpl=()=>Promise.reject(new Error('connection lost'));
          buttonText(node,'Run both simulators').click();await settle();
          assert(node.textContent.includes('Refresh this check before trying again'));
          assert(buttonText(node,'Run both simulators').disabled);assert.equal(writes.length,1);
          answers=[running()];buttonText(node,'Refresh check').click();await settle();
          assert(node.textContent.includes('The simulator check is playing'));assert.equal(writes.length,1);
        """)

    def test_stop_is_explicit_and_rechecks_original_page_before_writing(self):
        self.run_js("""
          const node=await load(running());let resolve;ask=()=>new Promise(done=>resolve=done);
          buttonText(node,'Stop check').click();await settle();state.profile={id:'user1'};
          resolve('stop');await settle();same(writes,[]);
        """)

    def test_confirmed_stop_submits_only_the_run_id_and_preserves_results(self):
        self.run_js("""
          const node=await load(running());ask=async()=> 'stop';
          answers=[chosen({status:'error',job:{test,status:'error',error:'stopped',may_stop:false},result:result()})];
          buttonText(node,'Stop check').click();await settle();
          same(writes,[{path:'/api/crosscheck/stop',body:{test}}]);
          assert(node.textContent.includes('The check was stopped'));assert(node.textContent.includes('Saved check against Blue Deck'));
        """)
