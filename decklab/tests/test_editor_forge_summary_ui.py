"""Saved Forge numbers require exact version/baseline evidence and current async ownership."""
import unittest

from decklab.tests import test_editor_panes_ui as panes
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, 'Node.js is not installed')
class EditorForgeSummaryTests(unittest.TestCase):
    def run_js(self, scenario):
        panes.EditorPanesUiTests.run_js(self, r'''
          const fingerprint='a'.repeat(64),sha='b'.repeat(64),reads=[];
          let respond;api=path=>{reads.push(path);return new Promise(resolve=>{respond=resolve;});};
          const numbers={version:'target',card_sha:fingerprint,rate:{value:.61,low:.55,high:.67},
            games:400,tested:'2026-10-20T10:00:00Z',partial:true,counted:2,of:3};
          const evidenceView=()=>({sha256:sha,forge_lists:{target:fingerprint,owned:'c'.repeat(64)}});
          async function answer(ed,value=numbers){respond({decks:{[ed.id]:value},error:null});await Promise.resolve();}
        ''' + scenario)

    def test_matching_saved_evidence_is_labelled_partial_and_retains_the_original_test_action(self):
        self.run_js(r'''
          const ed=full(evidenceView()),context=ed.dom.forgeSummary,row=ed.dom.forgeTest,action=row.vt.button;
          assert(context.root.hidden);assert(ed.dom.forge.hidden);assert.equal(reads.length,1);
          await answer(ed);assert(!context.root.hidden&&!ed.dom.forge.hidden&&row.hidden);
          assert(context.root.textContent.includes(`saved ${listName('target',true)}`));
          assert(context.root.textContent.includes('2 of 3 opponents counted'));
          assert(context.root.querySelector('.wr'));assert(context.root.querySelector('.range-bar'));
          const before=JSON.stringify(draftBody()),history=ed.history.length;
          ed.dirty=true;drawBar();assert(context.root.textContent.includes('for the saved list'));
          assert(ed.dom.forgeTest===row&&row.vt.button===action&&action.isConnected);
          ed.dirty=false;drawBar();assert(!ed.dom.forge.hidden&&row.hidden);
          assert.equal(JSON.stringify(draftBody()),before);assert.equal(ed.history.length,history);assert.equal(reads.length,1);
        ''')

    def test_wrong_version_fingerprint_missing_or_malformed_evidence_never_supplies_numbers(self):
        self.run_js(r'''
          for(const bad of [null,{...numbers,version:'owned'},{...numbers,card_sha:'d'.repeat(64)},
            {...numbers,card_sha:undefined},{...numbers,rate:null},{...numbers,games:0},
            {...numbers,rate:{value:.7,low:.8,high:.9}}]) {
            const ed=full(evidenceView());await answer(ed,bad);
            assert(ed.dom.forgeSummary.root.hidden);assert(!ed.dom.forgeSummary.root.querySelector('.wr'));
          }
          const ed=full(evidenceView());respond({decks:{[ed.id]:numbers},error:'Unavailable'});await Promise.resolve();
          assert(ed.dom.forgeSummary.root.hidden);
        ''')

    def test_async_answer_cannot_reach_a_replaced_page_profile_route_version_or_baseline(self):
        self.run_js(r'''
          for(const change of [ed=>{routeToken++;},ed=>{state.profile={id:'other'};},ed=>{ed.version='owned';},
            ed=>{ed.space='other';},ed=>{ed.mode='new';},ed=>{ed.view={...ed.view};},
            ed=>{ed.view.sha256='f'.repeat(64);},ed=>{drawEditor();},ed=>{ed.leaving=true;}]) {
            state.profile={id:'matt',plays_as:'user'};const ed=full(evidenceView()),old=ed.dom.forgeSummary,resolve=respond;
            change(ed);resolve({decks:{[ed.id]:numbers},error:null});await Promise.resolve();
            assert(old.root.hidden);assert(!old.root.querySelector('.wr'));
          }
        ''')

    def test_new_copy_quick_commander_unstarted_and_older_views_make_no_evidence_read(self):
        self.run_js(r'''
          full();assert.equal(reads.length,0);
          full({...evidenceView(),kind:'commander'});assert.equal(reads.length,0);
          full({...evidenceView(),lists:{target:structuredClone(list),owned:null}},{version:'owned'});assert.equal(reads.length,0);
          startEditor({mode:'new',kind:'casual',restoreDraft:false});assert.equal(reads.length,0);
          startEditor({mode:'new',from:'casual/source',view:view({...evidenceView(),new_deck:{kind:'casual',title:'Copy'}}),restoreDraft:false});
          assert.equal(reads.length,0);
          window.matchMedia('(min-width: 600px)').matches=false;begin(evidenceView(),{restoreDraft:false});
          assert(editor.quick);assert.equal(reads.length,0);
        ''')
