"""A saved sideboard plan's Forge tests (web/sideboard-preview.js, E4-S16) over fake API promises and Node
DOM: Start in the preview, the simulations setting's reason beside it, and the plan's tests with their
verdicts and older-list marks. No server, game or real write."""
import json
import subprocess
import unittest

from decklab.tests.test_sideboard_preview_ui import SETUP as PREVIEW
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PREVIEW + """
  const testId='e'.repeat(64),older='f'.repeat(64);
  const started=(over={})=>({version:1,plan:{id:planId,sha256:shaD},test:testId,link:`#/variant?test=${testId}`,
    status:'queued',verdict:null,words:null,...over});
  const tests=(over={})=>({version:1,plan:{id:planId,sha256:shaD},current:true,tests:[
    {test:testId,link:`#/variant?test=${testId}`,verdict:'better',words:'Better against Other Deck: +2.4 points of win rate',
      older_list:false,running:false,games_per_opponent:400,done:null,total:null,changes:null,against:'Other Deck'},
    {test:older,link:`#/variant?test=${older}`,verdict:'worse',words:'Worse against Other Deck',older_list:true,
      running:false,games_per_opponent:200,done:null,total:null}],...over});
  const startButtons=sheet=>[buttonText(sheet.body,'Start quick check'),buttonText(sheet.body,'Start play until ahead')];
  const testsSheet=async(saved=entry())=>{const host=mount(saved);buttonText(host,'Tests of this plan').click();await settle();return sheets.at(-1);};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SideboardTestUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_start_posts_the_plan_and_its_mode_then_links_the_test(self):
        self.run_js("""
          apiWrite=async(...args)=>{writes.push(args);return started();};
          const sheet=await preview();const [quick,ahead]=startButtons(sheet);assert(quick&&ahead);
          assert.equal(writes.length,0);
          quick.click();await settle();
          same(writes,[['/api/play/sideboard-test',{id:planId,sha256:shaD,mode:'quick'}]]);
          assert(sheet.body.textContent.includes('The test is playing on the PC'));
          assert.equal(sheet.body.querySelector('a').getAttribute('href'),`#/variant?test=${testId}`);
          assert(sheet.body.textContent.includes('A test of this plan was started'));
          assert(!quick.disabled);ahead.click();await settle();assert.equal(writes[1][1].mode,'ahead');
        """)

    def test_a_settled_verdict_shows_its_words(self):
        self.run_js("""
          apiWrite=async(...args)=>{writes.push(args);return started({status:'done',verdict:'little_difference',
            words:'Makes little difference: within 2 points of win rate'});};
          const sheet=await preview();startButtons(sheet)[0].click();await settle();
          assert(sheet.body.textContent.includes('Makes little difference'));
        """)

    def test_the_simulations_setting_disables_start_with_its_reason(self):
        self.run_js("""
          state.simulations={may_start:false,why_not:'Only an admin can start simulations right now.'};
          const sheet=await preview();const [quick,ahead]=startButtons(sheet);
          assert(quick.disabled&&ahead.disabled);
          assert(sheet.body.textContent.includes('Only an admin can start simulations right now.'));
          quick.click();await settle();assert.equal(writes.length,0);
        """)

    def test_a_refusal_shows_the_settings_reason_but_never_a_raw_error(self):
        self.run_js("""
          apiWrite=async(...args)=>{writes.push(args);throw new ApiError(403,'Only an admin can start simulations right now.');};
          let sheet=await preview();startButtons(sheet)[0].click();await settle();
          assert(sheet.body.textContent.includes('Only an admin can start simulations right now.'));sheet.close();
          apiWrite=async(...args)=>{writes.push(args);throw new ApiError(409,'PRIVATE OPPONENT changed');};
          sheet=await preview();startButtons(sheet)[0].click();await settle();
          assert(sheet.body.textContent.includes("The test couldn't be started"));
          assert(!sheet.body.textContent.includes('PRIVATE'));
          apiWrite=async(...args)=>{writes.push(args);return {...started(),test:'PRIVATE'};};
          startButtons(sheet)[0].click();await settle();assert(sheet.body.textContent.includes("The test couldn't be started"));
          assert.equal(sheet.body.querySelectorAll('a').length,0);
        """)

    def test_no_start_without_one_verified_format(self):
        self.run_js("""
          const value=answer();
          value.game_plan={status:'unavailable',reason:'format_mismatch',modes:[],cached_work:'not_checked',remaining_games:null,execution:'not_performed'};
          api=async()=>value;const sheet=await preview();
          assert(!buttonText(sheet.body,'Start quick check'));assert(!sheet.body.textContent.includes('Test this plan'));
        """)

    def test_a_late_start_answer_after_the_sheet_closes_is_ignored(self):
        self.run_js("""
          const waiting=deferred();apiWrite=(...args)=>{writes.push(args);return waiting.promise;};
          const sheet=await preview();const [quick]=startButtons(sheet);quick.click();quick.click();
          assert.equal(writes.length,1);sheet.close();waiting.resolve(started());await settle();
          assert(!sheet.body.textContent.includes('Open the test'));
        """)

    def test_tests_list_verdicts_and_older_list_marks(self):
        self.run_js("""
          api=async path=>{calls.push(path);return tests();};
          const sheet=await testsSheet();
          same(calls,[`/api/play/sideboard-tests?id=${planId}&sha256=${shaD}`]);
          assert(sheet.body.textContent.includes('Better against Other Deck'));
          assert(sheet.body.textContent.includes('Worse against Other Deck'));
          const items=sheet.body.querySelectorAll('li');assert.equal(items.length,2);
          assert(!items[0].textContent.includes('For an older list'));assert(items[1].textContent.includes('For an older list'));
          assert(items[0].textContent.includes('400 games a deck'));
          same(sheet.body.querySelectorAll('a').map(node=>node.getAttribute('href')),[`#/variant?test=${testId}`,`#/variant?test=${older}`]);
          assert(!sheet.body.textContent.includes('has changed since it was saved'));assert.equal(writes.length,0);
        """)

    def test_a_test_ended_not_settled_is_listed_with_the_others(self):
        self.run_js("""
          const value=tests();value.tests[0].verdict='not_settled';
          value.tests[0].words='Not settled against Other Deck after 200 games';api=async()=>value;
          const sheet=await testsSheet();
          assert(!sheet.body.textContent.includes("This plan's tests couldn't be loaded"));
          assert(sheet.body.textContent.includes('Not settled against Other Deck'));
          assert(sheet.body.textContent.includes('Worse against Other Deck'));
          assert.equal(sheet.body.querySelectorAll('li').length,2);
        """)

    def test_a_stale_plan_and_a_running_test(self):
        self.run_js("""
          api=async()=>tests({current:false,tests:[{test:testId,link:`#/variant?test=${testId}`,verdict:null,words:null,
            older_list:true,running:true,games_per_opponent:0,done:50,total:400}]});
          const sheet=await testsSheet();
          assert(sheet.body.textContent.includes('has changed since it was saved'));
          assert(sheet.body.textContent.includes('Playing on the PC.'));assert(sheet.body.textContent.includes('50 of 400 games played'));
          sheet.close();api=async()=>tests({tests:[]});const empty=await testsSheet();
          assert(empty.body.textContent.includes('No test of this plan yet'));
        """)

    def test_a_damaged_tests_answer_is_rejected_whole(self):
        self.run_js("""
          const mutations=[a=>a.plan.id='2'.repeat(32),a=>a.plan.sha256=shaA,a=>a.current='yes',
            a=>a.tests[0].link='#/elsewhere',a=>a.tests[0].verdict='PRIVATE',a=>a.tests[1].older_list=null,
            a=>a.tests[0].test='bad',a=>a.tests[0].words='x'.repeat(501),a=>a.version=2];
          for(const mutate of mutations){const value=tests();mutate(value);api=async()=>value;const sheet=await testsSheet();
            assert(sheet.body.textContent.includes("This plan's tests couldn't be loaded"));
            assert.equal(sheet.body.querySelectorAll('a').length,0);sheet.close();}
          api=async()=>{throw Error('PRIVATE DECK');};const sheet=await testsSheet();
          assert(!sheet.body.textContent.includes('PRIVATE'));assert(buttonText(sheet.foot,'Try again'));
        """)
