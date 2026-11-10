"""Cuts use cached evidence and ordinary drafts, with scope fences and a real Undo step."""
import json
import subprocess
import unittest

from decklab.tests import test_deck_edhrec_ui as ideas
from decklab.tests import test_editor_considering_ui as considering
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

CUTS = r'''
  const cuts=()=>({cuts:true,deck_id:'commander/test',may_edit:true,draft:false,commanders:['Ghalta, Primal Hunger'],
    source:{cached:true,available:true,fetched:'2026-10-28T00:00:00Z'},forge:{available:false,min_games:800},pages:[],unknown:[],note:'Choose cuts yourself.',
    groups:[{key:'ranked',header:'On EDHREC, lowest first',cards:[{name:'Elf',qty:1,inclusion:20,card:card('Elf','Creature',1),reasons:[
      {kind:'role',text:'Ramp: 11 cards against a starting target of 10.'}]}]},
    {key:'absent',header:"Not on EDHREC's page for this commander",cards:[{name:'Missing from page',qty:1,inclusion:null,card:null,reasons:[]}]}]});
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CutUiTests(unittest.TestCase):
    def run_js(self, setup, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cuts_requests_only_cached_view_and_never_invents_an_absent_percentage(self):
        self.run_js(ideas.SETUP + CUTS, r'''
          api=async path=>{asked.push(path);return cuts();};location.hash='#/deck?id=commander/test';
          const ctx=openDeckCuts(commanderPage());await settle();
          same(asked,['/api/deck/edhrec?id=commander%2Ftest&view=cuts']);
          assert(ctx.area.textContent.includes('Planned list'));assert(ctx.area.textContent.includes('Ramp: 11'));
          const absent=ctx.area.querySelectorAll('.edhrec-cut')[1];assert(absent.textContent.includes('Inclusion unknown'));assert(!absent.textContent.includes('0%'));
          assert(ctx.area.querySelectorAll('a').some(link=>link.textContent==='Move to Considering'&&link.getAttribute('href').includes('cut=Elf')));
          buttonText(ctx.area.querySelectorAll('.edhrec-cut')[0],'Test this swap');
        ''')

    def test_read_only_cards_have_no_mutation_actions_and_late_profile_reply_is_ignored(self):
        self.run_js(ideas.SETUP + CUTS, r'''
          const readOnlyAnswer=cuts();readOnlyAnswer.may_edit=false;api=async()=>readOnlyAnswer;const ctx=openDeckCuts(commanderPage());await settle();
          assert(!ctx.area.textContent.includes('Move to Considering'));assert(!ctx.area.textContent.includes('Test this swap'));
          ctx.sheet.close();let done;api=()=>new Promise(resolve=>done=resolve);const late=openDeckCuts(commanderPage());
          state.profile={...state.profile};done(cuts());await settle();assert(!late.area.textContent.includes('Ramp: 11'));
        ''')

    def test_local_move_preserves_printings_categories_other_drafts_and_one_undo_restores_it(self):
        self.run_js(considering.SETUP, r'''
          const ed=openConsidering();const line=ed.lists.Deck[0];line.category='Plan';line.finish='foil';
          changed();const before=snapshot(ed),prose=JSON.stringify(ed.prose);
          assert(editorDemoteCut(ed,line.name));assert.equal(ed.lists.Deck.some(row=>row.name===line.name),false);
          const moved=ed.considering.find(row=>row.name===line.name&&row.category==='Plan');assert(moved);
          same(sendLine(moved),sendLine(line));assert.equal(JSON.stringify(ed.prose),prose);
          assert(draftBody().lists.target);assert(draftBody().lists.considering);undoLast();assert.equal(snapshot(ed),before);
        ''')

    def test_over_100_commander_draft_links_to_actual_draft_preview_without_saving(self):
        self.run_js(considering.SETUP, r'''
          const v=consideringView({id:'commander/test',kind:'commander'});v.sections=['Commander','Deck','Sideboard'];
          v.lists.target.Commander=[{name:'Leader',qty:1,card:{...elves,name:'Leader'}}];v.lists.target.Deck[1].qty=96;
          startEditor({mode:'edit',view:v,version:'target',restoreDraft:false});const ed=editor;
          assert(main.textContent.includes('1 over 100'));const link=main.querySelector('.editor-cuts-link');assert(link);
          const requests=[];apiWrite=async(path,body)=>{requests.push({path,body});return {cuts:true,may_edit:true,source:{available:false},forge:{min_games:800},groups:[],unknown:[],pages:[]};};
          link.click();for(let i=0;i<20;i++)await null;
          same(requests.map(row=>row.path),['/api/deck/cuts']);assert.equal(requests[0].body.sections.Deck[1].qty,96);
          assert(!requests[0].body.sections.Sideboard);assert.equal(requests[0].body.id,'commander/test');
        ''')

    def test_lands_commanders_and_stale_or_read_only_editors_cannot_be_demoted(self):
        self.run_js(considering.SETUP, r'''
          const ed=openConsidering(),before=snapshot(ed);assert.equal(editorDemoteCut(ed,'Forest'),false);assert.equal(snapshot(ed),before);
          ed.readOnly=true;assert.equal(editorDemoteCut(ed,'Llanowar Elves'),false);assert.equal(snapshot(ed),before);
        ''')

    def test_route_or_profile_departure_closes_private_cut_and_idea_sheets(self):
        self.run_js(ideas.SETUP + CUTS, r'''
          api=async()=>cuts();const ctx=openDeckCuts(commanderPage());await settle();assert(ctx.area.textContent.includes('Ramp: 11'));
          closeAllSheets();assert(ctx.sheet.closed);assert(!ctx.sheet.dialog.isConnected);assert.equal(edhrecSheets.size,0);
        ''')

    def test_ideas_cuts_choice_reads_the_cache_view_in_the_same_sheet(self):
        self.run_js(ideas.SETUP + CUTS, r'''
          api=async path=>{asked.push(path);return path.includes('view=cuts')?cuts():ANSWER();};
          const ctx=openEdhrecSheet(commanderPage());await settle();buttonText(ctx.area,'Cuts').click();await settle();
          assert(ctx.answer.cuts);assert.equal(asked.length,2);assert(asked[1].includes('view=cuts'));assert.equal(edhrecSheets.size,1);
        ''')
