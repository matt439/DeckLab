"""Operational reference UI with fake APIs and DOM: no real reports or records."""
import json
import subprocess
import unittest

from decklab.tests.test_shell_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ErrorReferenceUiTests(unittest.TestCase):
    def run_js(self, source):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + source, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_browser_reports_only_fixed_metadata_and_preserves_known_api_guidance(self):
        self.run_js(r'''
          location.hash='#/deck?id=PRIVATE_DECK&name=PRIVATE_NAME';
          const sent=[];fetch=async(path,options)=>{sent.push({path,options});return {ok:true};};
          const error=new TypeError('PRIVATE_MESSAGE /private/file.js');
          const failure=pageFailure(error);assert(await failure.sent);
          assert.equal(pageFailure(error),failure,'the same error has one reference');
          assert.equal(sent.length,1);same(Object.keys(JSON.parse(sent[0].options.body)).sort(),['page','reference','type']);
          const data=JSON.parse(sent[0].options.body);assert.equal(data.page,'deck');assert.equal(data.type,'TypeError');
          assert(/^[a-f0-9]{32}$/.test(data.reference));assert.equal(sent[0].path,'/api/errors/report');
          assert.equal(sent[0].options.headers['X-Deck-Lab'],'1');assert.equal(sent[0].options.credentials,'same-origin');
          assert(!JSON.stringify(sent).includes('PRIVATE'));assert(!failure.message.includes('PRIVATE'));
          for(const status of [0,400,403,404,409,503]){
            const known=pageFailure(new ApiError(status,'Actionable setup or refusal'));
            assert.equal(known.message,'Actionable setup or refusal');assert.equal(known.reference,null);
          }
          for(let i=0;i<6;i++)await pageFailure(new Error('PRIVATE')).sent;
          assert.equal(sent.length,6,'client reports have a six-per-minute cap');
        ''')

    def test_page_errors_hide_raw_browser_message_and_failed_delivery_is_honest(self):
        self.run_js(r'''
          document.body.append(el('div',{id:'page-errors'}));fetch=async()=>{throw Error('PRIVATE_TRANSPORT');};
          window.fire('error',{message:'PRIVATE_MESSAGE',filename:'/private/file.js',lineno:10,error:new Error('PRIVATE_MESSAGE')});
          await flush();const host=byId('page-errors');assert(host.textContent.includes('Reference '));
          assert(!host.textContent.includes('PRIVATE'));assert(!host.textContent.includes('file.js'));
          assert(host.textContent.includes('only on this device'));
          for(let i=0;i<5;i++)showPageError(new Error('PRIVATE'));
          await flush();assert.equal(host.children.length,3,'panels cannot grow without a bound');
          assert(!loadFailed('A panel',new Error('PRIVATE')).textContent.includes('PRIVATE'));
          assert(!errorBox('A panel',new Error('PRIVATE'),null).textContent.includes('PRIVATE'));
        ''')

    def test_settings_named_home_admin_only_and_late_answers_keep_their_original_page(self):
        self.run_js(r'''
          as('user1',false);assert.equal(settingsErrorReferences(),null);
          as('user2');state.profile={...state.profile,role:'admin'};assert.equal(settingsErrorReferences(),null);
          as('matt',false);location.hash='#/settings';let reads=0,finish;
          api=async path=>{assert.equal(path,'/api/settings/errors');reads++;return await new Promise(done=>{finish=done;});};
          const panel=settingsErrorReferences();main.append(panel);assert.equal(reads,0);
          panel.querySelector('button').click();await flush();assert.equal(reads,1);
          const old=panel.textContent;routeToken++;
          finish({ready:true,events:[{reference:'a'.repeat(32),page:'deck',type:'TypeError',at:'2026-11-11T01:00:00Z'}]});
          await flush();assert.equal(panel.textContent,old,'a late answer cannot overwrite another route');
          clear(main);const fresh=settingsErrorReferences();main.append(fresh);
          api=async()=>({ready:true,events:[{reference:'b'.repeat(32),page:'deck',type:'TypeError',at:'2026-11-11T01:00:00Z'}]});
          fresh.querySelector('button').click();await flush();assert(fresh.textContent.includes('b'.repeat(32)));
          assert(fresh.textContent.includes('deck · TypeError'));assert(!fresh.textContent.includes('PRIVATE'));
          api=async()=>({ready:false,events:[],message:'Error references cannot be read.'});
          fresh.querySelector('button').click();await flush();assert(fresh.textContent.includes('cannot be read'));
          assert(!fresh.textContent.includes('No page errors'));
        ''')
