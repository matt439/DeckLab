"""Recovery buttons are explicit owner-bound requests; fake promises/DOM only."""
import json
import subprocess
import unittest

from decklab.tests.test_shell_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

PREPARE = "const realRecoveryPoll=pollRunRecovery;\n" + SETUP + r'''
  pollRunRecovery=realRecoveryPoll;as('matt',false);location.hash='#/deck?id=casual/test';routeToken++;
  const offer=()=>({id:'a'.repeat(32),kind:'field',title:'Unfinished field run: Fixture deck',created:'2026-11-11T01:00:00Z',
    may_resume:true,why_not:null,link:'#/deck?id=casual%2Ftest'});
  const body=el('div');document.body.append(body);runsPill.details={body,hash:location.hash,close(){body.remove();}};
  runsPill.unfinished=[offer()];runsPill.running=[];runsPill.recoveryAvailable=true;
  const paint=()=>clear(body).append(...runRecoveryParts());
  const buttons=()=>body.querySelectorAll('button');let writes=[],reads=[],toasts=[];
  toast=message=>toasts.push(message);syncRunsPill=()=>{};drawRunsPill=()=>{};fillRunDetails=()=>{};
  api=async(path,options)=>{reads.push({path,options});return {available:true,unfinished:[]};};
  apiWrite=async(path,data,method,options)=>{writes.push({path,data,method,options});return {resumed:true};};
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class RecoveryUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), PREPARE + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr[-5000:])
        self.assertEqual(result.stdout.strip(), "ok")

    def test_offer_render_is_read_only_and_buttons_send_only_the_opaque_id_on_explicit_click(self):
        self.run_js(r'''
          const draft={typed:['KEEP']};editor=draft;paint();assert.equal(writes.length,0);assert.equal(reads.length,0);
          assert(body.textContent.includes('Play the rest'));assert(body.textContent.includes('Dismiss'));
          buttons()[0].click();await flush();assert.equal(writes.length,1);assert.equal(writes[0].path,'/api/forge/resume');
          same(writes[0].data,{id:'a'.repeat(32)});assert.equal(writes[0].method,'POST');
          assert.equal(writes[0].options.wakeHop,false);assert(writes[0].options.signal);assert.equal(editor,draft);
          same(editor.typed,['KEEP']);assert.equal(runsPill.unfinished.length,0);assert(toasts.length);
          assert(reads.every(row=>row.options.poll===true&&row.options.wakeHop===false));
        ''')

    def test_disabled_changed_plan_cannot_resume_and_dismiss_never_reloads_or_starts_work(self):
        self.run_js(r'''
          runsPill.unfinished[0].may_resume=false;runsPill.unfinished[0].why_not='Saved lists changed.';paint();
          assert(buttons()[0].disabled);buttons()[0].click();await flush();assert.equal(writes.length,0);
          let navigations=0;route=()=>{navigations++;};buttons()[1].click();await flush();
          assert.equal(writes.length,1);assert.equal(writes[0].path,'/api/forge/dismiss');assert.equal(navigations,0);
        ''')

    def test_delayed_completion_or_old_button_cannot_repaint_another_profile_route_or_details(self):
        self.run_js(r'''
          paint();const old=buttons()[0];let finish;
          apiWrite=async(path,data,method,options)=>{writes.push(path);return await new Promise(done=>{finish=done;});};
          old.click();await flush();const successor=el('div',{},'KEEP_SUCCESSOR');document.body.append(successor);
          runsPill.details={body:successor,hash:'#/collection',close(){}};location.hash='#/collection';routeToken++;
          finish({resumed:true});await flush();assert.equal(successor.textContent,'KEEP_SUCCESSOR');assert.equal(toasts.length,0);
          old.click();await flush();assert.equal(writes.length,1);
          as('user2');resetRunRecovery();assert.equal(runsPill.unfinished.length,0);
        ''')

    def test_hidden_tabs_do_not_poll_and_old_profile_answers_are_ignored_unknown_is_not_healthy_empty(self):
        self.run_js(r'''
          let finish,options;api=async(path,opts)=>{reads.push(path);options=opts;return await new Promise(done=>{finish=done;});};
          document.visibilityState='hidden';pollRunRecovery();assert.equal(reads.length,0);
          document.visibilityState='visible';pollRunRecovery();await flush();assert.equal(reads[0],'/api/forge/unfinished');
          assert.equal(options.poll,true);assert.equal(options.wakeHop,false);
          resetRunRecovery(false);assert(options.signal.aborted);finish({available:true,unfinished:[offer()]});await flush();
          assert.equal(runsPill.unfinished.length,1,'an aborted response does not replace the last known own state');
          resetRunRecovery();runsPill.recoveryAt=null;pollRunRecovery();await flush();as('user2');resetRunRecovery();
          finish({available:true,unfinished:[offer()]});await flush();assert.equal(runsPill.unfinished.length,0);
          api=async()=>({available:false,unfinished:[]});pollRunRecovery(true);await flush();
          assert.equal(runsPill.recoveryAvailable,false);paint();assert(body.textContent.includes("can't be checked"));
          assert.equal(writes.length,0);
        ''')

    def test_buttons_behind_another_modal_or_detached_from_the_original_body_do_not_send_requests(self):
        self.run_js(r'''
          paint();const button=buttons()[0],modal=el('dialog');modal.open=true;document.body.append(modal);
          button.click();await flush();assert.equal(writes.length,0);modal.remove();
          document.body.append(button);button.click();await flush();assert.equal(writes.length,0);
        ''')
