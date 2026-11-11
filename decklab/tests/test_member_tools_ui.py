"""Member-only personal controls preserve page/profile ownership and make no saved plan."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class MemberToolsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_home_and_other_public_space_have_no_personal_download(self):
        self.run_js("""
          as('matt',MAY.admin);assert.equal(memberOwnSpace(),false);
          as('user2',MAY.user2);assert.equal(memberOwnSpace(),true);
          const cv={space:'home',editable:false,kind:'find',data:{},query:new URLSearchParams(),profile:'user2',token:routeToken};
          assert(!colHead(cv,new URLSearchParams()).map(x=>x?.textContent||'').join('').includes('Download my space'));
          let calls=0;api=async()=>{calls++;};await downloadMemberSpace(cv);assert.equal(calls,0);
          as('matt',MAY.admin);await openMemberNeeds();assert.equal(calls,0);
        """)

    def test_own_needs_show_only_names_quantities_own_decks_and_copy_text(self):
        self.run_js("""
          as('user2',MAY.user2);const calls=[],copies=[];
          api=async(path)=>{calls.push(path);return {ready:true,decks:[{id:'user2/casual/a',title:'My plan'}],rows:[
            {name:'Llanowar Elves',quantity:3,decks:[{id:'user2/casual/a',title:'My plan'}]}]};};
          apiWrite=()=>{throw new Error('No saved plan or queue');};navigator.clipboard={writeText:async text=>copies.push(text)};
          const sheet=await openMemberNeeds();assert(sheet.body.textContent.includes('3 Llanowar Elves'));
          assert(sheet.body.textContent.includes('My plan'));assert(sheet.body.textContent.includes("isn't saved"));
          assert(sheet.body.querySelector('a').getAttribute('href').includes('user2'));
          button(sheet.foot,'Copy list').click();await flush();same(copies,['3 Llanowar Elves']);
          assert.equal(calls.length,1);assert(calls[0].startsWith('/api/space/needed?space=user2'));
          state.profile=PROFILES[0];button(sheet.foot,'Copy list').click();await flush();assert.equal(copies.length,1);
        """)

    def test_late_needs_and_downloads_do_not_cross_profile_or_route(self):
        self.run_js("""
          as('user2',MAY.user2);let resolve;api=()=>new Promise(done=>resolve=done);
          const loading=openMemberNeeds(),sheet=openDialog();state.profile=PROFILES[0];
          resolve({ready:true,rows:[{name:'PRIVATE_OLD_CARD',quantity:1,decks:[]}]});await loading;
          assert(!sheet.textContent.includes('PRIVATE_OLD_CARD'));
          as('user2',MAY.user2);const cv={space:'user2',profile:'user2',token:routeToken,message:el('div')};
          let downloaded=0;URL.createObjectURL=()=>{downloaded++;return 'blob:synthetic';};
          const pending=downloadMemberSpace(cv);routeToken++;resolve({});await pending;
          assert.equal(downloaded,0);assert.equal(cv.personalBusy,false);
        """)

    def test_partial_or_empty_counts_never_offer_a_copy_of_incomplete_rows(self):
        self.run_js("""
          as('user2',MAY.user2);api=async()=>({ready:false,reason:'Your collection needs checking.',rows:[{name:'Unproven',quantity:1}]});
          let sheet=await openMemberNeeds();assert(sheet.body.textContent.includes('needs checking'));assert(!button(sheet.foot,'Copy list'));
          sheet.close();api=async()=>({ready:true,rows:[],decks:[]});sheet=await openMemberNeeds();
          assert(sheet.body.textContent.includes('no saved Planned decks'));assert(!button(sheet.foot,'Copy list'));
        """)
