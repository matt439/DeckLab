"""Receive selected physical rows through the real receipt UI, with disposable DOM fixtures."""
import unittest

from decklab.tests import test_receipts_ui as board


@unittest.skipUnless(board.NODE, "Node.js isn't installed")
class PartialReceiptTests(unittest.TestCase):
    run_js = board.ReceiptBoardTests.run_js

    def test_only_ticked_cards_arrive_even_without_component_checks(self):
        self.run_js("""
          const comp=view.comps[0];comp.c.checks=[];comp.checks=[];
          let calls=[];apiWrite=async(p,b)=>{calls.push([p,b]);return {...ready,
            totals:[['playable cards',{cards:1,added_rows:1,bumped_rows:0}]],
            assignments:[{source:'cards',received:'cards-2',pending:'cards',received_quantity:1,pending_quantity:2}]};};
          await previewDelivery(view);assert.equal(calls.length,0);
          assert(body().includes('tick at least one card that arrived'));closeReceiptSheets();
          rcptTick(view,comp,comp.rows[1],true);
          assert.equal(view.primary.textContent,'Confirm: 1 selected checked');
          assert.equal(rcptProgress(view).blanks,0);assert(view.blanks.hidden);
          await previewDelivery(view);assert.equal(calls.length,1);
          const sent=calls[0][1].components[0];same(sent.take,[{row:2}]);
          assert.equal(sent.verified,true);assert.equal(sent.rows.length,2);
          assert.equal(sent.rows[0].quantity,'2');assert.equal(sent.rows[0].condition,'');
          assert.equal(sent.rows[0].notes,'condition and language not recorded; check on arrival');
          assert(body().includes('1 card to record as cards-2'));assert(body().includes('2 cards stay pending as cards'));
          assert(!body().includes('go in with no condition or language recorded'));
        """)

    def test_split_copies_select_current_edited_row_indexes_and_conserve_the_total(self):
        self.run_js("""
          const comp=view.comps[0];rcptSplit(view,comp,comp.rows[0],1);
          const arrived=comp.rows[1];arrived.values.condition='LP';arrived.values.language='en';
          rcptTick(view,comp,arrived,true);comp.checks=[true];
          let sent;apiWrite=async(p,b)=>{sent=b;return ready;};await previewDelivery(view);
          same(sent.components[0].take,[{row:2}]);
          same(sent.components[0].rows.map(r=>[r.name,r.quantity,r.condition]),
            [['Alpha','1',''],['Alpha','1','LP'],['Beta','1','NM']]);
          assert.equal(comp.rows[0].orig,comp.rows[1].orig);
          assert.equal(sent.components[0].rows.reduce((n,r)=>n+Number(r.quantity),0),3);
          assert.equal(view.preview.received[0].rows.length,1);
          assert.equal(view.preview.received[0].rows[0].values.quantity,'1');
        """)

    def test_only_selected_token_backs_need_verification_and_pairing_is_preserved(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'tokens',kind:'tokens',status:'pending',checks:[],fields:""" + board.TOKEN_FIELDS + """,
            rows:[{front:'Bird',back:'Golem',set:'tx',front_collector_number:'1',back_collector_number:'2',finish:'nonfoil',
              quantity:'1',front_details:'1/1; flying',back_details:'3/3',notes:''},
              {front:'Ooze',back:'',set:'tx',front_collector_number:'3',back_collector_number:'',finish:'nonfoil',
              quantity:'2',front_details:'',back_details:'',notes:'pairing unverified'}],pictures:[],decks:[]}];
          clear(main);const v=drawReceipt(d,routeToken),comp=v.comps[0];
          rcptTick(v,comp,comp.rows[0],true);assert.equal(rcptClientBlockers(v).length,0);
          let sent;apiWrite=async(p,b)=>{sent=b;return ready;};await previewDelivery(v);
          same(sent.components[0].take,[{row:1}]);assert.equal(sent.components[0].rows.length,2);
          assert.equal(sent.components[0].rows[0].back,'Golem');assert.equal(sent.components[0].rows[0].quantity,'1');
          assert.equal(sent.components[0].rows[1].notes,'pairing unverified');
          closeReceiptSheets();rcptTick(v,comp,comp.rows[1],true);
          assert(rcptClientBlockers(v).some(b=>b.text.includes('say what its back is')));
        """)

    def test_whole_component_omits_take_and_component_checks_still_apply_to_partial(self):
        self.run_js("""
          const comp=view.comps[0];rcptTick(view,comp,comp.rows[1],true);
          assert(rcptClientBlockers(view).some(b=>b.text.includes('Check not ticked')));
          comp.checks=[true];assert.equal(rcptClientBlockers(view).length,0);
          rcptTick(view,comp,comp.rows[0],true);
          assert(!Object.hasOwn(rcptRequest(view).components[0],'take'));
          assert.equal(rcptRequest(view).components[0].verified,true);
        """)

    def test_products_stay_whole_and_never_send_row_selection(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'kit',kind:'product',status:'pending',checks:['Inspect physical tokens'],
            fields:[],rows:[],product:{name:'Fixture deck',format:'Casual'},
            items:[{name:'Alpha',set:'tst',collector_number:'1',finish:'nonfoil',quantity:'60',section:'deck'}],
            pictures:[],decks:[]}];clear(main);const v=drawReceipt(d,routeToken),comp=v.comps[0];
          comp.intact='no';assert.equal(rcptClientBlockers(v).length,0);
          same(rcptRequest(v).components,[{id:'kit',verified:false,intact:'no'}]);
          assert(!main.querySelector('.rcpt-tick'));
        """)

    def test_partial_success_uses_reviewed_rows_and_continues_with_a_fresh_delivery(self):
        self.run_js("""
          const comp=view.comps[0];rcptSplit(view,comp,comp.rows[0],1);comp.checks=[true];
          rcptTick(view,comp,comp.rows[0],true);
          const assignments=[{source:'cards',received:'cards-2',pending:'cards',received_quantity:1,pending_quantity:2}];
          apiWrite=async()=>({...ready,assignments,totals:[['playable cards',{cards:1,added_rows:1,bumped_rows:0}]]});
          await previewDelivery(view);let finish,calls=0;
          apiWrite=()=>{calls++;return new Promise(resolve=>finish=resolve);};
          const saving=applyDelivery(view);await applyDelivery(view);assert.equal(calls,1);
          assert(main.querySelectorAll('input').every(c=>c.disabled));
          rcptTick(view,comp,comp.rows[2],true);assert(!comp.rows[2].ticked);
          rcptSplit(view,comp,comp.rows[0],1);assert.equal(comp.rows.length,3);
          // A late model mutation cannot alter the projection that was reviewed.
          comp.rows[0].values.name='Changed after submission';comp.rows[0].values.quantity='99';
          finish({received:true,assignments,remaining:[{id:'cards',kind:'cards',quantity:2}],fingerprint:'c'.repeat(64),
            totals:[['playable cards',{cards:1,added_rows:1,bumped_rows:0}]],tables:{written:[],skipped:[],error:null}});
          state.library={cached:true};await saving;assert.equal(state.library,null);
          assert(main.textContent.includes('1 × Alpha'));assert(!main.textContent.includes('Changed after submission'));
          assert(!main.textContent.includes('Beta'));assert(main.textContent.includes('Unticked cards are still pending'));
          assert.equal(window.localStorage.getItem('decklab.receipt:matt:test:'+'a'.repeat(64)),null);
          let reloads=0;route=()=>{reloads++;};
          main.querySelectorAll('button').find(b=>b.textContent==='Continue pending delivery').click();assert.equal(reloads,1);
          assert.equal(main.querySelectorAll('.btn-primary').length,1);
        """)

    def test_reticking_after_preview_invalidates_apply_even_without_a_change_event(self):
        self.run_js("""
          const comp=view.comps[0];comp.checks=[true];rcptTick(view,comp,comp.rows[1],true);
          const calls=[];apiWrite=async p=>{calls.push(p);return ready;};await previewDelivery(view);
          comp.rows[0].ticked=true;await applyDelivery(view);
          same(calls,['/api/receipt/preview']);assert.equal(view.preview,null);
          assert(main.textContent.includes('Changed since preview'));
        """)

    def test_a_changed_selection_during_preview_discards_the_late_answer(self):
        self.run_js("""
          const comp=view.comps[0];comp.checks=[true];rcptTick(view,comp,comp.rows[1],true);
          let finish;apiWrite=()=>new Promise(resolve=>finish=resolve);const preparing=previewDelivery(view);
          rcptTick(view,comp,comp.rows[0],true);assert(!comp.rows[0].ticked,'busy UI cannot edit selection');
          comp.rows[0].ticked=true;finish(ready);await preparing;
          assert.equal(view.preview,null);assert(!body().includes('Record arrival'));
          assert(!view.primary.disabled);
        """)

    def test_database_retry_keeps_the_reviewed_token_and_the_draft(self):
        self.run_js("""
          const comp=view.comps[0];comp.checks=[true];rcptTick(view,comp,comp.rows[1],true);
          apiWrite=async()=>ready;await previewDelivery(view);
          const token=view.preview.token;apiWrite=async()=>{throw new ApiError(503,'Database unavailable');};
          await applyDelivery(view);assert.equal(view.preview.token,token);assert(!view.done);
          assert(window.localStorage.getItem('decklab.receipt:matt:test:'+'a'.repeat(64)));
          assert(body().includes('Retry recording arrival'));
          let sent;apiWrite=async(p,b)=>{sent=b;return {received:true,totals:ready.totals,tables:{written:[],skipped:[],error:null}};};
          await applyDelivery(view);same(sent,{profile:'matt',preview:token});assert(view.done);
        """)

    def test_conflict_keeps_the_draft_but_requires_authoritative_reload(self):
        self.run_js("""
          const comp=view.comps[0];comp.checks=[true];rcptTick(view,comp,comp.rows[1],true);
          apiWrite=async()=>ready;await previewDelivery(view);
          apiWrite=async()=>{throw new ApiError(409,'Delivery changed');};await applyDelivery(view);
          assert.equal(view.preview,null);assert(view.reloadRequired);assert(view.primary.disabled);
          assert(window.localStorage.getItem('decklab.receipt:matt:test:'+'a'.repeat(64)));
          let writes=0,reloads=0;apiWrite=async()=>{writes++;};route=()=>{reloads++;};
          await previewDelivery(view);await applyDelivery(view);assert.equal(writes,0);
          view.previewSheet.foot.querySelector('.btn-primary').click();assert.equal(reloads,1);
        """)

    def test_closed_receipt_questions_and_sheets_cannot_leak_or_mutate_after_switch(self):
        self.run_js("""
          const comp=view.comps[0];rcptOpenSheet(view,comp,comp.rows[0]);
          const oldNotes=view.sheet.sheet.body.querySelector('[aria-label=Notes]');
          const asking=rcptTickAll(view,comp);assert.equal(document.body.querySelectorAll('dialog').length,2);
          closeReceiptSheets();state.profile={id:'user1',name:'User1'};
          await asking;assert.equal(document.body.querySelectorAll('dialog').length,0);
          assert(comp.rows.every(r=>!r.ticked));
          const notes=comp.rows[0].values.notes;oldNotes.value='late private edit';oldNotes.fire('input');
          assert.equal(comp.rows[0].values.notes,notes);
          rcptTick(view,comp,comp.rows[0],true);assert(!comp.rows[0].ticked);
          await previewDelivery(view);assert.equal(view.preview,null);
        """)

    def test_late_apply_invalidates_cache_without_drawing_into_another_profile(self):
        self.run_js("""
          tickAll(view);apiWrite=async()=>ready;await previewDelivery(view);
          let finish;apiWrite=()=>new Promise(resolve=>finish=resolve);const saving=applyDelivery(view);
          closeReceiptSheets();state.profile={id:'user2',name:'User2'};state.library={cached:true};
          routeToken++;clear(main).append(el('p',{text:'User2 view'}));
          let routes=0;route=()=>{routes++;};finish({received:true,totals:ready.totals});await saving;
          assert.equal(state.library,null);assert.equal(main.textContent,'User2 view');assert.equal(routes,0);
          assert(!body().includes('Arrival recorded'));assert(!document.body.querySelector('dialog'));
        """)

    def test_nested_printing_picker_closes_with_receipt_details(self):
        self.run_js("""
          const comp=view.comps[0];rcptOpenSheet(view,comp,comp.rows[0]);
          let finish;api=()=>new Promise(resolve=>finish=resolve);
          document.body.querySelectorAll('button').find(b=>b.textContent==='Different printing…').click();
          assert.equal(document.body.querySelectorAll('dialog').length,2);
          closeReceiptSheets();state.profile={id:'user2',name:'User2'};
          finish({printings:[]});await Promise.resolve();await Promise.resolve();
          assert.equal(document.body.querySelectorAll('dialog').length,0);
          assert.equal(comp.rows[0].values.set,'tst');assert.equal(comp.rows[0].values.collector_number,'1');
          assert.equal(comp.rows[0].pic,null);
        """)

    def test_losing_write_permission_disables_retained_controls_and_requests(self):
        self.run_js("""
          const comp=view.comps[0];rcptOpenSheet(view,comp,comp.rows[0]);
          const oldNotes=view.sheet.sheet.body.querySelector('[aria-label=Notes]');
          state.may={admin:false,receipts:false};const notes=comp.rows[0].values.notes;
          oldNotes.value='not allowed';oldNotes.fire('input');rcptTick(view,comp,comp.rows[0],true);
          assert.equal(comp.rows[0].values.notes,notes);assert(!comp.rows[0].ticked);
          let writes=0;apiWrite=async()=>{writes++;return ready;};
          await previewDelivery(view);await applyDelivery(view);assert.equal(writes,0);
        """)


if __name__ == '__main__':
    unittest.main()
