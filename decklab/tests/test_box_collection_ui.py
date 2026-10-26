"""Box differences hand off read-only provenance to fresh guarded Collection edits."""
import unittest

from decklab.tests import test_box_check_ui as boxes
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class BoxCollectionUiTests(unittest.TestCase):
    def run_js(self, scenario):
        boxes.BoxCheckUiTests.run_js(self, r'''
          const sourceHash='b'.repeat(64), rowsHash='e'.repeat(64);
          const copyRow=(extra={})=>({name:'Recorded Elf',set:'fdn',collector_number:'227',finish:'nonfoil',quantity:4,condition:'',language:'',notes:'',...extra});
          const rowReply=(extra={})=>({space:'home',editable:true,sha256:rowsHash,rows:[copyRow()],pictures:{},...extra});
          const prints=(name='Recorded Elf',extra={})=>({name,printings:[{set:'fdn',set_name:'Fixture',collector_number:'227',finishes:['nonfoil'],released:'2024'},
            {set:'tst',set_name:'New fixture',collector_number:'1',finishes:['nonfoil','foil'],released:'2025'}],...extra});
          let reads=[],writes=[],editCtx=null;
          const originalEditor=openCollectionSheet;
          openCollectionSheet=(...args)=>{editCtx=originalEditor(...args);return editCtx;};
          const repairs=sheet=>sheet.body.querySelectorAll('.box-collection-open');
          const difference=extra=>({id:'casual/a',title:'Elves',deck_sha256:sourceHash,recipe_sha256:'d'.repeat(64),
            section:'Deck',kind:'card',name:'Recorded Elf',for:null,quantity:1,direction:'missing',...extra});
          const installReads=(handler=null)=>{reads=[];api=async path=>{reads.push(path);if(handler)return handler(path);
            if(path.startsWith('/api/deck/edit?'))return{id:'casual/a',sha256:sourceHash};
            if(path==='/api/collection/rows')return rowReply();if(path.startsWith('/api/printings?'))return prints(decodeURIComponent(path.split('name=')[1]));
            throw Error('Unexpected read '+path);};};
          const arrive=async(diff=difference(),before={})=>{
            boxCollectionNavigate(Object.freeze(diff));routeToken++;boxCollectionRoute('collection',routeToken);clear(main);
            const cv=drawCollection({space:'home',editable:true,cards:[],total:0,page:1,pages:1,filters:{},...before},new URLSearchParams(),'home',routeToken);
            await settle();return cv;
          };
          const chooser=()=>[...colSheets].at(-1);
          const chooseExisting=async()=>{button(chooser().body,'Edit').click();await settle();return editCtx;};
          const chooseNew=async()=>{button(chooser().dialog,'Add another printing').click();await settle();return editCtx;};
          const selectPrinting=(ctx,index,finish='nonfoil')=>{ctx.strip.querySelectorAll('.col-strip-tile')[index].click();
            if(finish)ctx.finishBox.querySelectorAll('button').find(node=>node.dataset.value===finish).click();};
          const writeReplies=()=>{writes=[];apiWrite=async(path,body)=>{writes.push([path,body]);return{ok:true,sha256:'f'.repeat(64),rows:[body.row]};};colReload=()=>{};};
        ''' + scenario)

    def test_named_differences_offer_actual_physical_names_and_anonymous_markers_only_guidance(self):
        self.run_js(r'''
          const {sheet}=await openBox();allFound(sheet);found(sheet,2,'1');found(sheet,4,'0');found(sheet,5,'0');extraCard(sheet,'Opt','2');reviewButton(sheet).click();
          same(repairs(sheet).map(node=>node.getAttribute('aria-label')),['Review collection copies: Recorded Elf (Deck, missing)',
            'Review collection copies: Named physical marker (Deck, missing)','Review collection copies: Opt (Sideboard, extra)']);
          assert(sheet.body.textContent.includes('Identify this physical stand-in first'));assert(sheet.body.textContent.includes('discards its counts and extras'));
          assert(sheet.body.textContent.includes('does not save a check date'));assert(!repairs(sheet).some(node=>node.textContent.includes('Missing spell')));
        ''')

    def test_handoff_closes_local_review_without_saving_or_changing_recipe_kit_ticks(self):
        self.run_js(r'''
          const {sheet,view,data}=await openBox();const before=JSON.stringify(view.selected),kit=view.buildKit={fixture:'keep'},ticksBefore=JSON.stringify([...serverTicks]);
          allFound(sheet);found(sheet,4,'0');reviewButton(sheet).click();writes=[];apiWrite=async(path,body)=>{writes.push([path,body]);};
          repairs(sheet)[0].click();assert(sheet.closed);assert(!view.reviewing);assert.equal(location.hash,'#/collection');assert.equal(writes.length,0);
          same(boxCollectionHandoff.difference,difference({name:'Named physical marker',kind:'marker',for:'Represented spell'}));
          assert(Object.isFrozen(boxCollectionHandoff.difference));assert.equal(JSON.stringify(view.selected),before);assert.equal(view.buildKit,kit);
          assert.equal(JSON.stringify([...serverTicks]),ticksBefore);assert.equal(data.decks[0].box_check.checked_on,null);assert(!location.hash.includes('marker'));
          assert(!JSON.stringify(saved).includes('Named physical marker'));
        ''')

    def test_fresh_source_and_rows_are_read_once_before_name_chooser_and_receipt_is_consumed(self):
        self.run_js(r'''
          installReads();const cv=await arrive(difference(),{sha256:'old-cache',rows:[copyRow({quantity:90})]});
          same(reads,['/api/deck/edit?id=casual%2Fa','/api/collection/rows','/api/printings?name=Recorded%20Elf']);assert.equal(boxCollectionHandoff,null);
          assert.equal(cv.sha256,rowsHash);assert.equal(cv.rows[0].quantity,4);assert(chooser().body.textContent.includes('missing 1 physical card'));
          assert(chooser().body.textContent.includes('storage or another box'));assert.equal(location.hash,'#/collection');assert.equal(editCtx,null);
          const count=colSheets.size;boxCollectionConsume(cv);await settle();assert.equal(colSheets.size,count);assert.equal(reads.length,3);
        ''')

    def test_changed_or_missing_source_never_displays_repair_context_or_collection_rows(self):
        self.run_js(r'''
          for(const source of [{id:'casual/a',sha256:'x'.repeat(64)},{id:'casual/b',sha256:sourceHash},null]){
            colCloseSheets();installReads(async path=>source);const cv=await arrive();assert.equal(colSheets.size,0);
            assert(cv.message.textContent.includes('deck changed'));assert.equal(reads.length,1);assert.equal(main.querySelector('.box-collection-context'),null);
          }
          installReads(async()=>{throw Error('private backend detail');});const cv=await arrive();assert(cv.message.textContent.includes("source deck couldn't be checked"));
          assert(!cv.message.textContent.includes('private backend detail'));assert.equal(colSheets.size,0);
        ''')

    def test_cancel_other_profile_wrong_route_and_second_arrival_discard_memory(self):
        self.run_js(r'''
          for(const mode of ['profile','route','second','space']){
            state.profile={id:'matt',name:'Matt',role:'admin',space:'home'};state.may=null;boxCollectionNavigate(difference());routeToken++;
            if(mode==='profile')state.profile={...state.profile,id:'user1'};if(mode==='route')location.hash='#/library';
            if(mode==='space')state.profile={...state.profile,space:'user2'};
            boxCollectionRoute(mode==='route'?'library':'collection',routeToken);if(mode==='second')boxCollectionRoute('collection',routeToken+1);
            assert.equal(boxCollectionHandoff,null);
          }
        ''')

    def test_owner_guards_stop_after_each_read_without_late_rows_or_extra_lookups(self):
        self.run_js(r'''
          for(const stage of [0,1,2])for(const mode of ['profile','route','hash','root']){
            colCloseSheets();state.profile={id:'matt',name:'Matt',role:'admin',space:'home'};state.may=null;let finish;
            installReads(path=>{const position=reads.length-1;if(position===stage)return new Promise(done=>{finish=done;});
              return position===0?{id:'casual/a',sha256:sourceHash}:position===1?rowReply():prints();});
            const cv=await arrive();const previous=cv.rows;if(mode==='profile')state.profile={...state.profile,id:'user1'};
            if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';if(mode==='root')cv.root.remove();
            finish(stage===0?{id:'casual/a',sha256:sourceHash}:stage===1?rowReply():prints());await settle();
            assert.equal(reads.length,stage+1);assert.equal(editCtx,null);assert.equal(cv.rows,previous);
            assert(![...colSheets].some(sheet=>sheet.body.querySelector('.col-copy-rows')));
          }
        ''')

    def test_unknown_or_mismatched_extra_has_manual_guidance_and_no_printing_or_save_action(self):
        self.run_js(r'''
          for(const result of [null,{name:'Different name',printings:[]}]){
            colCloseSheets();installReads(path=>path.startsWith('/api/deck/edit?')?{id:'casual/a',sha256:sourceHash}:path==='/api/collection/rows'?rowReply():result);
            await arrive(difference({name:'Unknown extra',direction:'extra'}));const sheet=chooser();assert(sheet.body.textContent.includes('search Collection for the exact card name manually'));
            assert.equal(button(sheet.dialog,'Add another printing'),undefined);assert.equal(editCtx,null);
          }
        ''')

    def test_invalid_fresh_collection_receipt_cannot_open_rows_or_make_an_extra_lookup(self):
        self.run_js(r'''
          for(const change of [{sha256:'bad'},{space:'user2'},{editable:false},{rows:null},{rows:[null]},
            {rows:[copyRow({set:null})]},{rows:[copyRow({quantity:'bad'})]},{rows:[copyRow(),copyRow()]}]){
            colCloseSheets();installReads(path=>path.startsWith('/api/deck/edit?')?{id:'casual/a',sha256:sourceHash}:rowReply(change));await arrive();
            assert.equal(reads.length,2);assert(chooser().body.textContent.includes("copies couldn't be checked"));assert.equal(button(chooser().dialog,'Add another printing'),undefined);
          }
        ''')

    def test_malformed_printing_entries_fail_to_manual_guidance_without_inferred_finish(self):
        self.run_js(r'''
          for(const printings of [[null],[{set:'tst',collector_number:'1'}],[{set:'tst',collector_number:'1',finishes:[]}],
            [{set:'tst',collector_number:'1',finishes:['unknown']}],[{set:null,collector_number:'1',finishes:['nonfoil']}],
            [{set:'tst',collector_number:null,finishes:['nonfoil']}]]){
            colCloseSheets();installReads(path=>path.startsWith('/api/deck/edit?')?{id:'casual/a',sha256:sourceHash}:path==='/api/collection/rows'?rowReply():prints('Recorded Elf',{printings}));
            await arrive();assert(chooser().body.textContent.includes("copies couldn't be checked"));assert.equal(button(chooser().dialog,'Add another printing'),undefined);
          }
        ''')

    def test_closed_chooser_ignores_pending_row_and_printing_reads(self):
        self.run_js(r'''
          for(const stage of [1,2]){
            colCloseSheets();let finish;installReads(path=>{
              const position=reads.length-1;if(position===stage)return new Promise(done=>finish=done);
              return position===0?{id:'casual/a',sha256:sourceHash}:rowReply();});
            await arrive();const sheet=chooser();button(sheet.dialog,'Close').click();finish(stage===1?rowReply():prints());await settle();
            assert(sheet.closed);assert.equal(colSheets.size,0);assert.equal(editCtx,null);assert.equal(reads.length,stage+1);
          }
        ''')

    def test_editor_printing_read_ignores_a_late_route_or_profile_change(self):
        self.run_js(r'''
          for(const mode of ['route','profile']){
            colCloseSheets();state.profile={id:'matt',name:'Matt',role:'admin',space:'home'};state.may=null;installReads();await arrive();
            let finish;api=async()=>new Promise(done=>finish=done);button(chooser().dialog,'Add another printing').click();const ctx=editCtx;
            if(mode==='route')location.hash='#/library';else state.profile={...state.profile,id:'user1'};
            finish(prints());await settle();assert.equal(ctx.printings.length,0);assert.equal(ctx.chosen,-1);writeReplies();ctx.inputs.quantity.value='4';await saveCollectionSheet(ctx);assert.equal(writes.length,0);
          }
        ''')

    def test_recorded_date_can_still_hand_off_its_current_source_without_resaving(self):
        self.run_js(r'''
          const {sheet}=await openBox();allFound(sheet);found(sheet,2,'1');reviewButton(sheet).click();writes=[];
          apiWrite=async(path,body)=>{writes.push([path,body]);return boxAnswer({missing:[{section:'Deck',kind:'card',name:'Recorded Elf',for:null,quantity:1}],found_cards:28});};
          dateButton(sheet).click();await settle();assert(button(sheet.dialog,'Done'));repairs(sheet)[0].click();assert.equal(location.hash,'#/collection');
          assert.equal(boxCollectionHandoff.difference.deck_sha256,'c'.repeat(64));assert.equal(writes.length,1);assert.equal(writes[0][0],'/api/deck/box-check');
        ''')

    def test_selected_existing_printing_requires_explicit_total_owned_quantity(self):
        self.run_js(r'''
          installReads();await arrive();const ctx=await chooseExisting();assert.equal(ctx.inputs.quantity.value,'');assert.equal(ctx.inputs.name.value,'Recorded Elf');
          assert.equal(ctx.inputs.quantity.getAttribute('aria-label'),'Total owned copies of this printing');assert(ctx.form.textContent.includes('Total owned copies of this printing'));
          assert.equal(ctx.inputs.name.getAttribute('readonly'),'');assert.equal(ctx.chosen,0);writeReplies();await saveCollectionSheet(ctx);assert.equal(writes.length,0);
          ctx.inputs.quantity.value='7';await saveCollectionSheet(ctx);assert.equal(writes.length,1);assert.equal(writes[0][1].action,'edit');
          assert.equal(writes[0][1].row.quantity,7);assert.equal(writes[0][1].sha256,rowsHash);assert.equal(writes[0][1].row.name,'Recorded Elf');
          assert.equal(writes[0][1].recipe_sha256,undefined);assert.equal(writes[0][1].missing,undefined);
        ''')

    def test_repair_add_has_no_default_printing_finish_or_quantity_even_for_one_printing(self):
        self.run_js(r'''
          installReads(path=>path.startsWith('/api/deck/edit?')?{id:'casual/a',sha256:sourceHash}:path==='/api/collection/rows'?rowReply({rows:[]}):prints('Recorded Elf',{printings:[prints().printings[1]]}));
          await arrive();const ctx=await chooseNew();assert.equal(ctx.chosen,-1);assert.equal(ctx.inputs.quantity.value,'');writeReplies();ctx.inputs.quantity.value='3';
          await saveCollectionSheet(ctx);assert.equal(writes.length,0);assert(ctx.message.textContent.includes('Choose the printing you have'));
          selectPrinting(ctx,0,null);await saveCollectionSheet(ctx);assert.equal(writes.length,0);assert(ctx.message.textContent.includes('Choose the finish'));
          ctx.finishBox.querySelectorAll('button').find(node=>node.dataset.value==='foil').click();await saveCollectionSheet(ctx);
          assert.equal(writes.length,1);assert.equal(writes[0][1].action,'add');assert.equal(writes[0][1].row.quantity,3);assert.equal(writes[0][1].row.finish,'foil');
        ''')

    def test_repair_add_refuses_an_owned_printing_key_instead_of_adding_entered_total(self):
        self.run_js(r'''
          installReads();await arrive();const ctx=await chooseNew();selectPrinting(ctx,0);ctx.inputs.quantity.value='7';writeReplies();await saveCollectionSheet(ctx);
          assert.equal(writes.length,0);assert(ctx.message.textContent.includes('This printing is already listed'));assert(ctx.message.textContent.includes('total owned quantity'));
          assert(button(ctx.sheet.dialog,'Review listed copies'));
        ''')

    def test_repair_conflicts_require_fresh_row_review_and_never_offer_additive_or_recreate_retry(self):
        self.run_js(r'''
          for(const editing of [false,true]){
            colCloseSheets();installReads();await arrive();const ctx=editing?await chooseExisting():await chooseNew();if(!editing)selectPrinting(ctx,1);
            ctx.inputs.quantity.value='7';writes=[];apiWrite=async(path,body)=>{writes.push(body);throw new ApiError(409,'Changed',{sha256:'f'.repeat(64),rows:[]});};
            await saveCollectionSheet(ctx);assert.equal(writes.length,1);assert(ctx.sheet.body.textContent.includes('Review the current listed copies'));
            assert(button(ctx.sheet.dialog,'Review listed copies'));assert(!ctx.sheet.dialog.textContent.includes('Load the latest and add'));
            assert(!ctx.sheet.dialog.textContent.includes('Add Recorded Elf x7 as a new card'));assert.equal(button(ctx.sheet.dialog,'Save'),undefined);
          }
        ''')

    def test_repair_reduction_keeps_the_existing_reason_and_in_use_confirmation_flow(self):
        self.run_js(r'''
          installReads();await arrive();const ctx=await chooseExisting();ctx.inputs.quantity.value='2';writeReplies();const pending=saveCollectionSheet(ctx);await settle();
          const ask=[...colSheets].at(-1);assert(ask.body.textContent.includes('2 copies of Recorded Elf'));assert.equal(writes.length,0);
          button(ask.dialog,'Keep it').click();await pending;assert.equal(writes.length,0);assert.equal(ctx.inputs.quantity.value,'2');
        ''')

    def test_repair_remove_opens_only_the_existing_explicit_removal_confirmation(self):
        self.run_js(r'''
          installReads();await arrive();const ctx=await chooseExisting();writeReplies();ctx.sheet.foot.querySelector('[data-action="remove"]').click();await settle();
          assert(ctx.sheet.closed);const question=chooser();assert(question.body.textContent.includes('comes out of the collection'));assert.equal(writes.length,0);
          assert(button(question.dialog,'Keep it'));button(question.dialog,'Keep it').click();await settle();assert.equal(writes.length,0);
        ''')

    def test_source_and_editor_late_scope_changes_prevent_requests_and_preserve_newer_page(self):
        self.run_js(r'''
          installReads();await arrive();const ctx=await chooseExisting();ctx.inputs.quantity.value='7';writeReplies();location.hash='#/library';
          await saveCollectionSheet(ctx);assert.equal(writes.length,0);assert.equal(location.hash,'#/library');
          const count=reads.length;await loadColPrintings(ctx,'Recorded Elf');assert.equal(reads.length,count);
        ''')

    def test_ordinary_collection_add_keeps_original_default_printing_quantity_and_merge_path(self):
        self.run_js(r'''
          state.profile={id:'matt',name:'Matt',role:'admin',space:'home'};state.may=null;location.hash='#/collection';clear(main);
          const cv=drawCollectionRows(rowReply(),'home',routeToken);api=async()=>prints('Recorded Elf',{printings:[prints().printings[0]]});
          const ctx=openCollectionSheet(cv,null,{name:'Recorded Elf'});await settle();assert.equal(ctx.inputs.quantity.value,'1');assert.equal(ctx.chosen,0);
          writeReplies();await saveCollectionSheet(ctx);assert.equal(writes.length,1);assert.equal(writes[0][1].row.quantity,1);assert.equal(writes[0][1].action,'add');
        ''')

    def test_anonymous_and_malformed_differences_never_create_a_lookup_receipt(self):
        self.run_js(r'''
          state.profile={id:'matt',name:'Matt',role:'admin',space:'home'};state.may=null;const deck={id:'casual/a',title:'Elves'},evidence={meta:boxMeta()};
          for(const change of [{name:null,kind:'marker',for:'Represented spell'},{name:'Bad\nName'},{quantity:0},{quantity:10000},{section:'Unknown'},{kind:'card',for:'Target'}])
            assert.equal(boxCollectionDifference(deck,evidence,{section:'Deck',kind:'card',name:'Recorded Elf',for:null,quantity:1,...change},'missing'),null);
          assert.equal(boxCollectionDifference(deck,evidence,{section:'Deck',kind:'marker',name:'Physical card',for:'Represented spell',quantity:1},'missing').name,'Physical card');
        ''')

    def test_sheet_navigation_waits_exact_back_landing_and_discards_unrelated_destinations(self):
        self.run_js(r'''
          for(const mode of ['valid','wrong-position','new-route','profile']){
            closeAssemblySheets();clear(main);state.profile={id:'matt',name:'Matt',role:'admin',space:'home'};state.may=null;location.hash='#/assembly';
            const entries=[{hash:location.hash,state:{pos:0}}],queue=[];let at=0;history.state=entries[0].state;
            history.pushState=(value,unused,url)=>{entries.push({state:value,hash:url||location.hash});at++;history.state=value;};
            history.replaceState=(value,unused,url)=>{history.state=value;entries[at]={state:value,hash:url||location.hash};if(url)location.hash=url;};
            history.back=()=>queue.push(()=>{at--;history.state=entries[at].state;location.hash=entries[at].hash;window.fire('popstate',{state:history.state});});
            const {sheet}=await openBox();allFound(sheet);found(sheet,2,'1');reviewButton(sheet).click();repairs(sheet)[0].click();assert.equal(location.hash,'#/assembly');
            flushTimers();assert.equal(queue.length,1);if(mode==='wrong-position')entries[0].state={pos:9};
            if(mode==='new-route')entries[0].hash='#/settings';if(mode==='profile')state.profile={...state.profile,id:'user1'};
            queue.shift()();assert.equal(location.hash,mode==='valid'?'#/collection':mode==='new-route'?'#/settings':'#/assembly');
            if(mode!=='valid')assert(!boxCollectionHandoff||boxCollectionHandoff.profile.id!=='user1');boxCollectionHandoff=null;
          }
        ''')


if __name__ == "__main__":
    unittest.main()
