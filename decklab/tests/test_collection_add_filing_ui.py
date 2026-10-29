"""Explicit single-card additions hand off frozen filing advice over fixture replies only."""
import json
import subprocess
import unittest

from decklab.tests.test_collection_guards_ui import FIXTURE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = FIXTURE + r'''
  let reloads=0;route=()=>{reloads++;};
  const openAdd=async()=>{colCloseSheets();location.hash='#/collection';const made=await make();made.ctx.sheet.close();
    const ctx=openCollectionSheet(made.cv,null,{name:'Llanowar Elves'});await flush();ctx.inputs.quantity.value='2';
    return {cv:made.cv,ctx};};
  const addedRow={...original,quantity:2,condition:'',language:'',notes:''};
  const filing=()=>({space:'home',profile:'matt',status:'ready',added:[
    {name:'Llanowar Elves',set:'fdn',collector_number:'227',finish:'nonfoil',quantity:2}],destinations:[
      {kind:'deck',row:0,quantity:1,deck:{id:'casual/waiting',title:'Waiting deck',status:'building'}},
      {kind:'storage',row:0,quantity:1}]});
  const filed=extra=>({ok:true,sha256:'s2',rows:[{...original,quantity:6}],merged:true,
    added:{rows:0,cards:2},filing:filing(),...extra});
  const guide=()=>main.querySelector('.col-filing-guide');
'''


@unittest.skipUnless(NODE, "Node.js is not installed")
class CollectionAddFilingUiTests(unittest.TestCase):
    def run_js(self, scenario):
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "ok")

    def test_listed_printing_add_uses_only_the_new_copies_and_preserves_add_request(self):
        self.run_js(r'''
          const {cv,ctx}=await openAdd(),calls=[];apiWrite=async(path,body)=>{calls.push([path,body]);return filed();};
          await saveCollectionSheet(ctx);
          same(calls,[['/api/collection/save',{space:'home',sha256:'s1',action:'add',row:addedRow}]]);
          assert(ctx.sheet.closed);assert.equal(cv.rows[0].quantity,6);assert.equal(cv.sha256,'s2');
          assert(cv.message.textContent.includes('added to the row already listed'));
          assert(guide().textContent.includes('For the 2 copies added by this card save'));
          assert(guide().textContent.includes('1 \u00d7 Llanowar Elves (FDN 227)'));
          assert(guide().textContent.includes('Waiting deck'));assert(guide().textContent.includes('To storage'));
          assert.equal(guide().getAttribute('aria-label'),'Where these go, saved card addition');
          assert(guide().querySelectorAll('ul').some(list=>list.getAttribute('aria-label')==='Added printing copies'));
          assert(guide().querySelectorAll('button').every(more=>more.textContent==='Show more printing lines'));
          assert(!guide().textContent.includes('6 copies'));assert(!guide().textContent.includes('import is saved'));
          assert.equal(reloads,0);assert.equal(state.colNotice,null);
        ''')

    def test_new_printing_add_keeps_its_original_success_words_and_exact_finish(self):
        self.run_js(r'''
          const {cv,ctx}=await openAdd(),answer=filed({merged:false,added:{rows:1,cards:2},rows:[{...original,finish:'foil',quantity:2}]});
          ctx.finishBox.querySelector('[aria-pressed=true]').dataset.value='foil';
          answer.filing.added[0].finish='foil';let body;apiWrite=async(path,payload)=>{body=payload;return answer;};
          await saveCollectionSheet(ctx);assert.equal(body.action,'add');assert.equal(body.row.finish,'foil');
          assert(cv.message.textContent.includes('added.'));assert(!cv.message.textContent.includes('already listed'));
          assert(guide().textContent.includes('FDN 227 \u00b7 Foil'));assert.equal(cv.rows[0].finish,'foil');
        ''')

    def test_find_cards_uses_the_existing_one_use_profile_bound_reload_notice(self):
        self.run_js(r'''
          const {cv,ctx}=await openAdd();cv.kind='find';const answer=filed();apiWrite=async()=>answer;
          await saveCollectionSheet(ctx);assert.equal(reloads,1);assert.equal(guide(),null);
          assert.equal(state.colNotice.profile,'matt');assert.equal(state.colNotice.filing.source,'add');
          answer.filing.added[0].name='Mutated response';answer.filing.added[0].quantity=900;
          const fresh=drawCollectionRows({space:'home',sha256:'later',editable:true,rows:[{...original,quantity:777}]},'home');
          assert(guide().textContent.includes('2 copies added'));assert(!guide().textContent.includes('Mutated response'));
          assert(!guide().textContent.includes('777'));assert(!guide().textContent.includes('900'));assert.equal(state.colNotice,null);
          colTakeNotice(fresh);assert.equal(main.querySelectorAll('.col-filing-guide').length,1);
        ''')

    def test_stale_add_requires_explicit_readd_and_keeps_additive_quantity(self):
        self.run_js(r'''
          const {cv,ctx}=await openAdd(),calls=[];apiWrite=async(path,body)=>{calls.push(body);
            if(calls.length===1)throw new ApiError(409,'Collection changed',{sha256:'latest',rows:[{...original,quantity:9}]});
            return filed({sha256:'after-latest',rows:[{...original,quantity:11}]});};
          await saveCollectionSheet(ctx);assert.equal(calls.length,1);assert.equal(guide(),null);assert(!ctx.sheet.closed);
          assert(ctx.sheet.body.textContent.includes('Nothing was saved'));
          const again=button(ctx.sheet.foot,'Load the latest and add my card');assert(again);again.click();await flush();
          assert.equal(calls.length,2);assert.equal(calls[1].sha256,'latest');assert.equal(calls[1].action,'add');
          assert.equal(calls[1].row.quantity,2);assert.equal(cv.rows[0].quantity,11);assert.equal(cv.sha256,'after-latest');
          assert(guide().textContent.includes('2 copies added'));assert(!guide().textContent.includes('11 copies'));
        ''')

    def test_existing_row_edits_never_use_addition_advice_even_when_quantity_goes_up(self):
        self.run_js(r'''
          for(const change of [{quantity:8},{finish:'foil'},{condition:'LP'},{quantity:2}]){
            colCloseSheets();const {cv,ctx}=await make();let body;apiWrite=async(path,payload)=>{body=payload;return filed({rows:[{...original,...change}],merged:false});};
            const pending=colSend(ctx,{action:'edit',original:{set:'fdn',collector_number:'227',finish:'nonfoil'},row:{...original,...change}});
            await flush();const why=openDialog(),reduce=why&&button(why,'Save reduction');if(reduce)reduce.click();await pending;
            assert.equal(body.action,'edit');assert.equal(guide(),null);assert(!state.colNotice?.filing);
            assert(cv.message.textContent.includes('saved.'));
          }
        ''')

    def test_edit_of_a_removed_row_gains_advice_only_after_explicit_add_as_new(self):
        self.run_js(r'''
          const {cv,ctx}=await make(),calls=[];apiWrite=async(path,body)=>{calls.push(body);
            if(calls.length===1)throw new ApiError(409,'Removed meanwhile',{sha256:'empty',rows:[]});
            return filed({merged:false,added:{rows:1,cards:2},rows:[addedRow]});};
          const pending=colSend(ctx,{action:'edit',original:{set:'fdn',collector_number:'227',finish:'nonfoil'},row:addedRow});
          await flush();button(openDialog(),'Save reduction').click();await pending;
          assert.equal(guide(),null);assert.equal(calls.length,1);assert(ctx.sheet.body.textContent.includes('nothing left to edit'));
          const add=button(ctx.sheet.foot,'Add Llanowar Elves \u00d72 as a new card');assert(add);add.click();await flush();
          assert.equal(calls.length,2);assert.equal(calls[1].action,'add');assert(!Object.hasOwn(calls[1],'original'));
          assert.equal(cv.rows[0].quantity,2);assert(guide().textContent.includes('2 copies added'));
        ''')

    def test_optional_requested_location_is_preserved_without_extra_writes(self):
        self.run_js(r'''
          const {ctx}=await openAdd(),calls=[];apiWrite=async(path,body)=>{calls.push([path,body]);return filed();};
          await colSend(ctx,{action:'add',row:addedRow,location:'Row 2, B'});
          assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/collection/save');assert.equal(calls[0][1].location,'Row 2, B');
          assert(!guide().textContent.includes('Row 2, B'));assert.equal(guide().querySelectorAll('input').length,0);
        ''')

    def test_unknown_and_legacy_responses_preserve_success_without_guessing_storage(self):
        self.run_js(r'''
          for(const mode of ['unknown','legacy']){
            const {cv,ctx}=await openAdd(),answer=filed();if(mode==='legacy')delete answer.filing;
            else {answer.filing.status='unknown';answer.filing.destinations=[];answer.filing.message='Private exception';}
            apiWrite=async()=>answer;await saveCollectionSheet(ctx);assert(ctx.sheet.closed);assert.equal(cv.rows[0].quantity,6);
            assert(cv.message.textContent.includes('added to the row already listed'));
            if(mode==='legacy')assert.equal(guide(),null);else{
              assert(guide().textContent.includes('Destination unknown'));assert(guide().textContent.includes('The card addition is saved'));
              assert(!guide().textContent.includes('To storage'));assert(!guide().textContent.includes('Private exception'));
            }
          }
        ''')

    def test_late_addition_invalidates_old_cache_without_guidance_navigation_or_focus_theft(self):
        self.run_js(r'''
          for(const mode of ['closed','profile','route','hash','newer-dialog']){
            state.colNotice=null;const {cv,ctx}=await openAdd();let finish;apiWrite=()=>new Promise(resolve=>finish=resolve);
            const pending=saveCollectionSheet(ctx);await flush();let newer=null,focus=null;
            if(mode==='closed')ctx.sheet.close();if(mode==='profile')state.profile=PROFILES.find(person=>person.id==='user1');
            if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='newer-dialog'){newer=colOpenSheet('Other task');focus=el('button',{text:'Stay here'});newer.body.append(focus);focus.focus();}
            finish(filed());await pending;assert.equal(cv.rows,null,mode);assert.equal(state.library,null);
            assert.equal(guide(),null);assert.equal(state.colNotice,null);assert.equal(reloads,0);
            if(newer){assert(!newer.closed);assert(!ctx.sheet.closed);assert.equal(document.activeElement,focus);}
          }
        ''')

    def test_foreign_or_wrong_profile_facts_never_render_on_an_add(self):
        self.run_js(r'''
          for(const mode of ['foreign','profile']){
            const {ctx}=await openAdd(),answer=filed();if(mode==='profile')answer.filing.profile='user1';
            else answer.filing.destinations[0].deck={id:'user2/casual/private',title:'Hidden deck',status:'built'};
            apiWrite=async()=>answer;await saveCollectionSheet(ctx);
            if(mode==='profile')assert.equal(guide(),null);else {assert(guide().textContent.includes('Destination unknown'));
              assert(!guide().textContent.includes('Hidden deck'));assert.equal(guide().querySelectorAll('a').length,0);}
          }
        ''')

    def test_late_add_failure_cannot_redraw_or_reenable_an_old_review_under_newer_context(self):
        self.run_js(r'''
          for(const mode of ['closed','profile','route','hash','newer-dialog']){
            state.colNotice=null;const {cv,ctx}=await openAdd(),oldAdd=button(ctx.sheet.foot,'Add');let fail,writes=0;
            state.library={snapshot:'old'};apiWrite=()=>{writes++;return new Promise((resolve,reject)=>fail=reject);};
            const pending=saveCollectionSheet(ctx);await flush();const body=ctx.sheet.body.textContent;let newer=null,focus=null;
            if(mode==='closed')ctx.sheet.close();if(mode==='profile')state.profile=PROFILES.find(person=>person.id==='user1');
            if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='newer-dialog'){newer=colOpenSheet('Other task');focus=el('button',{text:'Stay here'});newer.body.append(focus);focus.focus();}
            fail(new ApiError(409,'Old add failure',{sha256:'changed',rows:[{...original,quantity:20}]}));await pending;
            assert.equal(writes,1);assert.equal(cv.rows,null);assert.equal(state.library,null);assert(ctx.addSave.stale);
            assert.equal(ctx.sheet.body.textContent,body);assert(!ctx.message.textContent.includes('Old add failure'));
            assert.equal(guide(),null);assert.equal(state.colNotice,null);assert.equal(reloads,0);
            oldAdd.fire('click');await colSend(ctx,{action:'add',row:addedRow});assert.equal(writes,1);
            if(newer){assert(!newer.closed);assert.equal(document.activeElement,focus);assert(ctx.busy);assert(oldAdd.disabled);}
          }
        ''')

    def test_pending_and_confirmed_old_add_controls_never_submit_the_copies_again(self):
        self.run_js(r'''
          const {ctx}=await openAdd(),oldAdd=button(ctx.sheet.foot,'Add');let finish,writes=0;
          apiWrite=()=>{writes++;return new Promise(resolve=>finish=resolve);};const pending=saveCollectionSheet(ctx);await flush();
          oldAdd.fire('click');await saveCollectionSheet(ctx);await colSend(ctx,{action:'add',row:addedRow});assert.equal(writes,1);
          const other=colOpenSheet('Other task'),focus=el('button',{text:'Keep focus'});other.body.append(focus);focus.focus();
          finish(filed());await pending;assert(ctx.addSave.done);assert(!ctx.addSave.pending);assert(!ctx.sheet.closed);
          other.close();oldAdd.fire('click');await saveCollectionSheet(ctx);await colSend(ctx,{action:'add',row:addedRow});
          assert.equal(writes,1);assert.equal(guide(),null);assert(ctx.busy);assert(oldAdd.disabled);
        ''')

    def test_detached_initial_and_readd_controls_stay_inert_after_a_current_failure(self):
        self.run_js(r'''
          const {ctx}=await openAdd(),oldAdd=button(ctx.sheet.foot,'Add');let fail;const calls=[];
          apiWrite=async(path,body)=>{calls.push(body);if(calls.length===1)
            throw new ApiError(409,'Changed',{sha256:'latest',rows:[{...original,quantity:9}]});
            return new Promise((resolve,reject)=>fail=reject);};
          await saveCollectionSheet(ctx);const again=button(ctx.sheet.foot,'Load the latest and add my card');assert(again);
          oldAdd.fire('click');await flush();assert.equal(calls.length,1);assert(!ctx.form.isConnected);
          again.click();await flush();const foot=ctx.sheet.foot.textContent;assert.equal(calls.length,2);assert(ctx.addSave.pending);
          again.fire('click');oldAdd.fire('click');await flush();assert.equal(calls.length,2);assert.equal(ctx.sheet.foot.textContent,foot);
          fail(new ApiError(400,'Printing refused',{}));await flush();assert(ctx.message.textContent.includes('Printing refused'));
          assert(!ctx.addSave.pending);again.fire('click');oldAdd.fire('click');await saveCollectionSheet(ctx);await flush();
          assert.equal(calls.length,2);assert.equal(guide(),null);assert(!ctx.sheet.closed);
        ''')

    def test_add_waiting_for_rows_cannot_continue_or_publish_a_late_load_failure_after_route_change(self):
        self.run_js(r'''
          for(const failed of [false,true]){
            const {cv,ctx}=await openAdd();cv.rows=null;cv.sha256=null;let settle,writes=0;
            api=()=>new Promise((resolve,reject)=>settle=failed?reject:resolve);apiWrite=async()=>{writes++;return filed();};
            const pending=saveCollectionSheet(ctx);await flush();location.hash='#/library';
            settle(failed?new ApiError(503,'Old rows unavailable',{}):{rows:[original],sha256:'loaded'});await pending;
            assert.equal(writes,0);assert(!ctx.message.textContent.includes('Old rows unavailable'));assert.equal(guide(),null);
          }
        ''')


if __name__ == "__main__":
    unittest.main()
