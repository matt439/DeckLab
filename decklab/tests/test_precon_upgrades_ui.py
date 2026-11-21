"""Review an upgrade from Compare and hand a single swap to the ordinary editor."""
import unittest

from decklab.tests import test_compare_ui as compare_ui
from decklab.tests.test_workspace_ui import NODE


SETUP = r"""
  const id='commander/upgrade-fixture',file='UpgradeDinos_TST';
  const current=deckA(), stock=deckB();
  current.summary={...current.summary,id,kind:'commander'};current.may_upgrade_precon=true;
  stock.summary={...stock.summary,id:null,kind:'commander',title:'Upgrade Dinos'};
  stock.comparison={kind:'precon',file};
  const lead={qty:1,name:'Lead card',card:card('Lead card','Legendary Creature',4,['G'])};
  const cut={qty:1,name:'Old spell',card:card('Old spell','Sorcery',3,['G']),category:'Ramp'};
  const add={qty:1,name:'New answer',card:card('New answer','Sorcery',1,['G'])};
  const target={Commander:[lead],Deck:[cut,{qty:98,name:'Forest',card:forest}]};
  const editView={id,sha256:'a'.repeat(64),may_save:true,lists:{target,owned:null,considering:[{...add,category:'Maybe'}]},
    fields:{status:'building',target_bracket:2},prose:{notes:'Keep the guide'}};
  const receipt={deck_id:id,file,sha256:editView.sha256,before_minimum:2,target_bracket:2,
    proposals:[{cut,add,free:2,stock_cut:true,after_minimum:3,reason:'A low-cost answer.',trade_off:'One fewer ramp spell.'}]};
  const calls=[],stored={};
  window.localStorage={getItem:key=>stored[key]??null,setItem:(key,value)=>{stored[key]=String(value);},
    removeItem:key=>{delete stored[key];}};
  const key=draftKey({mode:'edit',profile:state.profile.id,id,version:'target'});
  let view=editView;
  apiWrite=async (path,body)=>{calls.push([path,body]);return structuredClone(receipt);};
  const compareApi=api;
  api=async path=>{if(path.startsWith('/api/deck/edit?')){calls.push([path]);return structuredClone(view);} return compareApi(path);};
  const showGuide=async()=>{
    answers={'/api/compare/deck?':current,'/api/compare/precon?':stock};
    await show(comparePreconHref(id,file));
  };
  const begin=async()=>{
    await showGuide();assert(buttonText(main,'Find early interaction…'));same(calls,[]);
    buttonText(main,'Find early interaction…').click();await settle();
    return keyboardDialog();
  };
"""


@unittest.skipUnless(NODE, "Node.js is not installed")
class PreconUpgradeUiTests(unittest.TestCase):
    def run_js(self, scenario):
        compare_ui.CompareUiTests.run_js(self, SETUP + scenario)

    def test_compare_offers_explicit_goal_and_applies_only_the_reviewed_pair(self):
        self.run_js(r"""
          const sheet=await begin();
          same(calls,[['/api/deck/precon-upgrades',{id,file,goal:'early-interaction'}]]);
          assert(sheet.textContent.includes('2 free copies on hand'));
          assert(sheet.textContent.includes('One fewer ramp spell.'));
          assert(sheet.textContent.includes('floor changes from 2 to 3'));
          assert(sheet.textContent.includes('Your target is Bracket 2.'));
          assert.equal(local.get(key),null);
          buttonText(sheet,'Review in editor').click();await settle();
          const draft=JSON.parse(local.get(key));
          same(draft.lists.Commander,[lead]);
          same(draft.lists.Deck.map(line=>[line.name,line.qty]),[['Forest',98],['New answer',1]]);
          same(draft.base.lists,target);same(draft.considering,editView.lists.considering);
          same(draft.fields,pickFields(editView.fields));same(draft.prose,proseOf(editView));
          assert.equal(location.hash,'#/edit?id=commander%2Fupgrade-fixture&v=target');
          same(calls.map(row=>row[0]),['/api/deck/precon-upgrades','/api/deck/edit?id=commander%2Fupgrade-fixture']);
          startEditor({mode:'edit',view:{...editView,kind:'commander',space:'home',title:'Upgrade fixture',editable:true,
            field_text:{},sections:['Commander','Deck']},version:'target'});
          assert(isDirty());
          assert.equal(mainCount(editor.lists,'commander'),100);
          same(draftBody().lists, {target:sendList(draft.lists)});
        """)

    def test_a_changed_save_blocks_the_draft_and_a_read_only_compare_hides_the_action(self):
        self.run_js(r"""
          const sheet=await begin();
          view={...editView,sha256:'b'.repeat(64)};
          buttonText(sheet,'Review in editor').click();await settle();
          assert(sheet.textContent.includes('The deck changed'));
          assert.equal(local.get(key),null);assert(location.hash.startsWith('#/compare'));
          buttonText(sheet,'Close').click();
          delete current.may_upgrade_precon;
          await showGuide();assert(!buttonText(main,'Find early interaction…'));
        """)

    def test_testing_opens_normal_test_review_without_starting_any_run(self):
        self.run_js(r"""
          const sheet=await begin();
          buttonText(sheet,'Test this change').click();await settle();
          assert.equal(location.hash,'#/edit?id=commander%2Fupgrade-fixture&v=target&test=change');
          assert(local.get(key));assert.equal(calls.length,2);
        """)

    def test_an_edited_local_draft_wins_over_pending_replace_confirmation(self):
        self.run_js(r"""
          const sheet=await begin();
          local.set(key,'previous draft');
          let choose;ask=()=>new Promise(resolve=>{choose=resolve;});
          buttonText(sheet,'Review in editor').click();await settle();assert(choose);
          local.set(key,'updated draft');choose('replace');await settle();
          assert.equal(local.get(key),'updated draft');assert(location.hash.startsWith('#/compare'));
        """)
