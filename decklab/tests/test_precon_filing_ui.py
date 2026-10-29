"""Precon filing handoff through the existing saved deck box over fixture replies only."""
import unittest

from decklab.tests import test_precon_tokens_ui as precon_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class PreconFilingUiTests(unittest.TestCase):
    def run_js(self, scenario):
        precon_ui.PreconTokensUiTests.run_js(self, r'''
          const filing=extra=>({space:'home',profile:'matt',status:'ready',added:[
            {name:'Llanowar Elves',set:'fdn',collector_number:'227',finish:'nonfoil',quantity:4}],
            destinations:[{kind:'deck',row:0,quantity:4,deck:{id:'casual/fixture',title:'Fixture deck',status:'built'}}],...extra});
          const filed=extra=>added({collection:{ok:true,sha256:'saved-collection',added:{rows:1,cards:4},filing:filing()},...extra});
          const showSaved=()=>{clear(main);const box=savedBox(state.saved?.answer.id);if(box)main.append(box);return box;};
          const guide=()=>main.querySelector('.col-filing-guide');
        ''' + scenario)

    def test_current_success_keeps_exact_navigation_and_frozen_printing_facts_in_saved_box(self):
        self.run_js(r'''
          const ctx=await open(),answer=filed(),calls=[];
          apiWrite=async(path,body)=>{calls.push([path,body]);return answer;};await addPrecon(ctx);
          same(calls,[['/api/precons/add',{space:'home',file:'Fixture_TST',title:'Fixture deck',sha256:'collection-first'}]]);
          assert(ctx.sheet.closed);assert.equal(location.hash,deckHref('casual/fixture','target'));
          assert.equal(state.saved.mode,'new');assert.equal(state.saved.profile,'matt');assert.equal(state.saved.answer.precon.cards,4);
          answer.collection.filing.added[0].name='Mutated reply';answer.collection.filing.added[0].quantity=999;
          ctx.preview.lists.Deck[0].name='Mutated preview';ctx.preview.lists.Deck[0].qty=888;
          const box=showSaved();assert(box.textContent.includes('Fixture deck is created'));
          assert(box.textContent.includes(`4 cards from the ${ctx.preview.deck.name} precon went into`));
          assert(guide());assert(guide().textContent.includes('For the 4 copies added with this precon'));
          assert(guide().textContent.includes('4 \u00d7 Llanowar Elves (FDN 227)'));
          assert(guide().textContent.includes('deck lists at that point'));assert(!guide().textContent.includes('To storage'));
          for(const word of ['Mutated reply','Mutated preview','999','888'])assert(!box.textContent.includes(word),word);
          assert.equal(guide().querySelector('a').getAttribute('href'),deckHref('casual/fixture','target'));
          assert(Object.isFrozen(state.saved.answer.precon.filing.added[0]));
          assert.equal(guide().querySelectorAll('input').length,0);assert.equal(calls.length,1);
        ''')

    def test_optional_tokens_keep_original_receipts_and_are_not_playable_filing_copies(self):
        self.run_js(r'''
          const ctx=await open();choose(ctx);let body;
          apiWrite=async(path,payload)=>{body=payload;return filed();};await addPrecon(ctx);
          same(body,{space:'home',file:'Fixture_TST',title:'Fixture deck',sha256:'collection-first',
            add_tokens:true,tokens_sha256:'a'.repeat(64),tokens_source_sha256:'c'.repeat(64)});
          assert.equal(state.saved.answer.precon.tokens,3);const box=showSaved();
          assert(box.textContent.includes('3 token cards also added as unconfirmed rows'));
          assert(guide().textContent.includes('4 copies'));assert(!guide().textContent.includes('7 copies'));
          for(const token of ['Dog','The Monarch','Source suggestion'])assert(!guide().textContent.includes(token));
        ''')

    def test_legacy_success_and_all_basic_precon_keep_their_existing_saved_box_without_guesses(self):
        self.run_js(r'''
          for(const response of [added(),added({collection:null})]){
            const ctx=await open();apiWrite=async()=>response;await addPrecon(ctx);
            const box=showSaved();assert(box);assert.equal(guide(),null);assert(!Object.hasOwn(state.saved.answer.precon,'filing'));
            assert.equal(location.hash,deckHref('casual/fixture','target'));
            if(response.collection===null)assert(box.textContent.includes('had only plain basic lands'));
          }
        ''')

    def test_unknown_advice_remains_successful_and_never_calls_unchecked_copies_storage(self):
        self.run_js(r'''
          const ctx=await open(),answer=filed();answer.collection.filing=filing({status:'unknown',destinations:[],message:'Hidden detail'});
          apiWrite=async()=>answer;await addPrecon(ctx);const box=showSaved();
          assert(box.textContent.includes('Fixture deck is created'));assert(guide().textContent.includes('Destination unknown'));
          assert(guide().textContent.includes('The precon is saved'));assert(guide().textContent.includes('4 \u00d7 Llanowar Elves'));
          assert(!guide().textContent.includes('To storage'));assert(!guide().textContent.includes('Hidden detail'));
          assert.equal(guide().querySelectorAll('a').length,0);
        ''')

    def test_foreign_destinations_fail_closed_and_member_saved_box_uses_only_own_space(self):
        self.run_js(r'''
          const ctx=await open(),answer=filed();answer.collection.filing.destinations[0].deck.id='user2/casual/private';
          answer.collection.filing.destinations[0].deck.title='Hidden foreign deck';apiWrite=async()=>answer;await addPrecon(ctx);showSaved();
          assert(guide().textContent.includes('Destination unknown'));assert(!guide().textContent.includes('Hidden foreign deck'));
          as('user2',MAY.user2);location.hash=deckHref('user2/casual/fixture','target');
          const collection=filed().collection;collection.filing.space=collection.filing.profile='user2';
          collection.filing.destinations[0].deck={id:'user2/casual/fixture',title:'My precon',status:'built'};
          const frozen=colFilingSnapshot(collection,{space:'user2',profile:'user2'},'precon');
          state.saved={hash:location.hash,profile:'user2',answer:{id:'user2/casual/fixture',title:'My precon',created:true,
            precon:{cards:4,name:'Fixture precon',whose:'my collection',filing:frozen}}};
          showSaved();assert(guide().textContent.includes('My precon'));
          assert.equal(guide().querySelector('a').getAttribute('href'),deckHref('user2/casual/fixture','target'));
          state.profile=PROFILES.find(person=>person.id==='matt');assert.equal(savedBox('user2/casual/fixture'),null);
        ''')

    def test_hidden_inventory_and_mismatched_profile_or_space_do_not_gain_filing_details(self):
        self.run_js(r'''
          const ctx=await open();apiWrite=async()=>filed();await addPrecon(ctx);const savedOwner=state.saved;
          state.may={...MAY.admin,see_inventory:[]};assert.equal(showSaved().querySelector('.col-filing-guide'),null);
          state.may=MAY.admin;state.profile=PROFILES.find(person=>person.id==='user1');assert.equal(savedBox('casual/fixture'),null);
          state.profile=PROFILES.find(person=>person.id==='matt');state.saved={...savedOwner,hash:'#/deck?other'};
          assert.equal(savedBox('casual/fixture'),null);
        ''')

    def test_saved_guide_expansion_uses_its_original_controls_and_stops_after_owner_dismissal(self):
        self.run_js(r'''
          const ctx=await open(),answer=filed(),facts=answer.collection.filing;
          facts.added=Array.from({length:101},(_,i)=>({name:`Card ${i}`,set:'fdn',collector_number:String(i),finish:'nonfoil',quantity:1}));
          facts.destinations=facts.added.map((row,i)=>({kind:'deck',row:i,quantity:1,deck:{id:'casual/fixture',title:'Fixture deck',status:'built'}}));
          answer.collection.added={rows:101,cards:101};let writes=0;apiWrite=async()=>{writes++;return answer;};await addPrecon(ctx);
          let box=showSaved(),list=guide().querySelector('ul'),more=guide().querySelector('.col-filing-more');
          assert.equal(list.children.length,100);more.focus();more.click();assert.equal(list.children.length,101);
          assert.equal(document.activeElement,list);assert(more.hidden);assert.equal(writes,1);
          box=showSaved();list=guide().querySelector('ul');more=guide().querySelector('.col-filing-more');
          const dismiss=box.querySelector('[aria-label="Close this box"]');dismiss.click();assert.equal(state.saved,null);
          more.click();assert.equal(list.children.length,100);assert.equal(guide(),null);assert.equal(writes,1);
        ''')

    def test_guide_controls_refuse_route_profile_new_saved_owner_and_modal_focus_changes(self):
        self.run_js(r'''
          const ctx=await open(),answer=filed(),facts=answer.collection.filing;
          facts.added[0].quantity=101;facts.destinations=Array.from({length:101},()=>({...facts.destinations[0],quantity:1}));
          answer.collection.added.cards=101;apiWrite=async()=>answer;await addPrecon(ctx);showSaved();
          const more=guide().querySelector('button'),list=guide().querySelector('ul'),owner=state.saved;
          const sheet=colOpenSheet('Other task');more.click();assert.equal(list.children.length,100);sheet.close();
          state.saved={...owner};more.click();assert.equal(list.children.length,100);state.saved=owner;
          const hash=location.hash;location.hash='#/collection';more.click();assert.equal(list.children.length,100);location.hash=hash;
          const profile=state.profile;state.profile=PROFILES.find(person=>person.id==='user1');more.click();assert.equal(list.children.length,100);state.profile=profile;
          routeToken++;more.click();assert.equal(list.children.length,100);routeToken--;
          more.click();assert.equal(list.children.length,101);
        ''')

    def test_late_success_never_publishes_guidance_or_navigates_from_newer_context(self):
        self.run_js(r'''
          for(const mode of ['closed','profile','route','hash','preview','newer-sheet']){
            const ctx=await open();let finish;apiWrite=()=>new Promise(resolve=>finish=resolve);const pending=addPrecon(ctx);await flush();
            let newer=null,focus=null;
            if(mode==='closed')ctx.sheet.close();if(mode==='profile')state.profile=PROFILES.find(person=>person.id==='user1');
            if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';if(mode==='preview')ctx.preview={...ctx.preview};
            if(mode==='newer-sheet'){ctx.sheet.close();newer=colOpenSheet('Other task');focus=el('button',{text:'Stay here'});newer.body.append(focus);focus.focus();}
            const hash=location.hash;finish(filed());await pending;assert.equal(state.saved,null,mode);assert.equal(location.hash,hash,mode);
            if(newer){assert(!newer.closed);assert.equal(document.activeElement,focus);}
          }
        ''')


if __name__ == "__main__":
    unittest.main()
