"""The Record bar reveals blockers and retains the exact preview/confirmation/apply workflow."""
import unittest

from decklab.tests import test_receipts_ui as board


@unittest.skipUnless(board.NODE, "Node.js isn't installed")
class ReceiptBarTests(unittest.TestCase):
    run_js = board.ReceiptBoardTests.run_js

    def test_blocked_primary_is_focusable_described_and_reveals_the_first_row(self):
        self.run_js("""
          let writes=0;apiWrite=async()=>{writes++;throw new Error('no write');};
          const comp=view.comps[0];assert.equal(view.primary.textContent,'Record arrival');
          assert.equal(view.primary.disabled,false);assert.equal(view.primary.getAttribute('aria-disabled'),'true');
          assert.equal(view.primary.getAttribute('aria-describedby'),view.recordReason.id);
          assert.equal(document.getElementById(view.recordReason.id),view.recordReason);
          assert(view.recordReason.textContent.includes('tick at least one card that arrived'));
          assert(view.recordReason.textContent.includes('2 things to check'));
          rcptSetFilter(view,'ticked');assert(comp.rows.every(r=>r.tile.hidden));
          view.primary.focus();assert.equal(document.activeElement,view.primary);view.primary.click();
          assert.equal(view.filter,'all');assert(comp.rows.every(r=>!r.tile.hidden));
          assert.equal(document.activeElement,comp.rows[0].tile.querySelector('.rcpt-tick'));
          assert.equal(writes,0);assert(!view.previewSheet);assert(!view.sheet);
        """)

    def test_empty_selection_focuses_the_first_live_arrival_checkbox(self):
        self.run_js("""
          const d=delivery();d.components.push({...d.components[0],id:'later'});
          const v=drawReceipt(d,routeToken);let writes=0;apiWrite=async()=>{writes++;return ready;};
          assert(v.comps.every(c=>!c.selected));assert.equal(v.primary.disabled,false);
          assert.equal(v.primary.getAttribute('aria-disabled'),'true');
          assert(v.recordReason.textContent.includes('This arrived'));
          const checkbox=v.comps[0].section.querySelector('.rcpt-arrived').querySelector('input');
          v.primary.click();assert.equal(document.activeElement,checkbox);assert.equal(writes,0);
          assert(v.comps.every(c=>!c.selected));same(rcptRequest(v).components,[]);
          assert.equal(rcptClientBlockers(v).length,1);
        """, draw=False)

    def test_a_selected_part_with_no_rows_keeps_a_focusable_blocker_and_never_previews(self):
        self.run_js("""
          const d=delivery();d.components[0].rows=[];d.components[0].checks=[];
          const v=drawReceipt(d,routeToken),comp=v.comps[0];let writes=0;apiWrite=async()=>{writes++;return ready;};
          assert(comp.selected);assert.equal(v.primary.getAttribute('aria-disabled'),'true');
          v.primary.click();assert.equal(comp.section.getAttribute('tabindex'),'-1');
          assert.equal(document.activeElement,comp.section);assert.equal(writes,0);assert(!v.previewSheet);
        """, draw=False)

    def test_partial_blanks_remain_ready_and_record_opens_the_exact_confirmation_first(self):
        self.run_js("""
          const comp=view.comps[0];rcptTick(view,comp,comp.rows[0],true);
          assert.equal(view.primary.getAttribute('aria-disabled'),'true');
          view.primary.click();assert.equal(document.activeElement,comp.checkBoxes[0]);
          comp.checks=[true];rcptChanged(view);assert.equal(rcptClientBlockers(view).length,0);
          assert.equal(view.primary.getAttribute('aria-disabled'),'false');assert.equal(view.primary.disabled,false);
          assert(!view.blanks.hidden);assert(!comp.rows[1].ticked);
          const request=rcptRequest(view),calls=[];apiWrite=async(path,data)=>{calls.push([path,data]);return ready;};
          await rcptRecord(view);assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/receipt/preview');
          same(calls[0][1],{profile:'matt',order:'test',fingerprint:'a'.repeat(64),...request});
          same(calls[0][1].components[0].take,[{row:1}]);
          assert.equal(calls[0][1].components[0].rows[0].condition,'');
          assert.equal(calls[0][1].components[0].rows[0].language,'');
          assert.equal(calls[0][1].components[0].verified,true);
          assert(view.previewSheet);assert(body().includes('Record this arrival?'));
          assert(body().includes("Home's collection"));assert(body().includes('they stay blank'));
          assert.equal(view.preview.received[0].rows.length,1);
          assert.equal(view.preview.received[0].rows[0].values.quantity,'2');
          const preview=view.preview,key=preview.key;rcptSetFilter(view,'ticked');rcptSetFilter(view,'todo');
          assert.equal(view.preview,preview);assert.equal(rcptRequestKey(view),key);assert.equal(calls.length,1);
          await applyDelivery(view);same(calls.map(c=>c[0]),['/api/receipt/preview','/api/receipt/apply']);
          same(calls[1][1],{profile:'matt',preview:ready.preview});assert(view.done);
        """)

    def test_product_only_requires_a_known_choice_and_focuses_the_first_enabled_option(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'kit',kind:'product',status:'pending',checks:['Inspect physical tokens'],
            fields:[],rows:[],product:{name:'Whole fixture'},items:[{name:'Alpha',quantity:'60'}],pictures:[],decks:[]}];
          const v=drawReceipt(d,routeToken),comp=v.comps[0];let writes=0;apiWrite=async()=>{writes++;return ready;};
          assert(comp.selected);assert(comp.choice.querySelectorAll('button')[0].disabled);
          for(const choice of ['',null,'unknown','YES']){
            comp.intact=choice;rcptSync(v);assert.equal(v.primary.getAttribute('aria-disabled'),'true');
            v.primary.click();assert.equal(document.activeElement,comp.choice.querySelectorAll('button')[1]);
            assert.equal(writes,0);assert.equal(rcptClientBlockers(v).length,1);
          }
          comp.choice.querySelectorAll('button')[1].click();assert.equal(comp.intact,'no');
          assert.equal(v.primary.getAttribute('aria-disabled'),'false');assert.equal(rcptClientBlockers(v).length,0);
          const request=rcptRequest(v);same(request.components,[{id:'kit',verified:false,intact:'no'}]);
          await rcptRecord(v);assert.equal(writes,1);assert(v.previewSheet);
          assert.equal(rcptRequestKey(v),JSON.stringify(request));assert.equal(rcptProgress(v).copies,0);
        """, draw=False)

    def test_unknown_metadata_is_preserved_for_server_validation_without_becoming_a_client_blocker(self):
        self.run_js("""
          const comp=view.comps[0];comp.checks=[true];const row=comp.rows[1];
          row.values.condition='unlisted';row.values.language='xx';row.values.finish='mystery';rcptTick(view,comp,row,true);
          assert.equal(rcptClientBlockers(view).length,0);assert.equal(view.primary.getAttribute('aria-disabled'),'false');
          const request=rcptRequest(view);let sent;
          apiWrite=async(path,data)=>{sent=data;return {...ready,ready:false,blockers:['cards: unknown fixture metadata']};};
          await rcptRecord(view);same(sent.components,request.components);
          assert.equal(sent.components[0].rows[1].condition,'unlisted');assert.equal(sent.components[0].rows[1].language,'xx');
          assert.equal(sent.components[0].rows[1].finish,'mystery');assert.equal(view.preview,null);
          assert(body().includes('unknown fixture metadata'));assert(!view.previewSheet);assert(!view.done);
        """)

    def test_selected_token_back_reveals_its_sheet_but_unselected_token_back_does_not_block(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'tokens',kind:'tokens',status:'pending',checks:[],fields:""" + board.TOKEN_FIELDS + """,
            rows:[{front:'Bird',back:'Golem',set:'tx',front_collector_number:'1',back_collector_number:'2',finish:'nonfoil',
              quantity:'1',front_details:'1/1; flying',back_details:'3/3',notes:''},
              {front:'Ooze',back:'',set:'tx',front_collector_number:'3',back_collector_number:'',finish:'nonfoil',
              quantity:'2',front_details:'',back_details:'',notes:'pairing unverified'}],pictures:[],decks:[]}];
          const v=drawReceipt(d,routeToken),comp=v.comps[0];let writes=0;apiWrite=async()=>{writes++;return ready;};
          rcptTick(v,comp,comp.rows[0],true);assert.equal(v.primary.getAttribute('aria-disabled'),'false');
          rcptTick(v,comp,comp.rows[1],true);assert.equal(v.primary.getAttribute('aria-disabled'),'true');
          rcptSetFilter(v,'todo');assert(comp.rows.every(r=>r.tile.hidden));v.primary.click();
          assert.equal(v.filter,'all');assert(v.sheet);assert.equal(v.sheet.row,comp.rows[1]);
          assert.equal(writes,0);assert(!v.previewSheet);assert.equal(rcptRequest(v).components[0].rows[1].back,'');
        """, draw=False)

    def test_calendar_date_blockers_keep_native_values_and_never_preview_until_valid(self):
        self.run_js("""
          tickAll(view);let writes=0;apiWrite=async()=>{writes++;return ready;};
          const invalid=['','2026-02-30','2025-02-29','2026-13-01','0000-01-01','2026-10-9','2026-10-09','2026-09-30'];
          for(const value of invalid){
            view.date={mode:'other',value};rcptSync(view);const before=rcptRequestKey(view);
            assert.equal(view.primary.getAttribute('aria-disabled'),'true',value);view.primary.click();
            assert.equal(document.activeElement,view.dateInput);assert.equal(view.dateInput.hidden,false);
            assert.equal(view.dateInput.getAttribute('type'),'date');
            assert.equal(view.date.value,value);assert.equal(rcptRequestKey(view),before);assert.equal(writes,0);
          }
          assert.equal(rcptValidDay('2024-02-29'),true);assert.equal(rcptValidDay('2026-04-31'),false);
          view.dateInput.value='2026-10-08';view.dateInput.fire('change');
          assert.equal(view.primary.getAttribute('aria-disabled'),'false');await rcptRecord(view);assert.equal(writes,1);
        """)

    def test_a_coercible_restored_date_never_crashes_or_sends_an_array_as_the_arrival_day(self):
        self.run_js("""
          tickAll(view);let writes=0;apiWrite=async()=>{writes++;return ready;};
          view.comps[0].checks=view.comps[0].checks.map(()=>true);rcptChanged(view);
          const key='decklab.receipt:matt:test:'+'a'.repeat(64);
          const draft=JSON.parse(window.localStorage.getItem(key));
          draft.date={mode:'other',value:['2026-10-08']};
          // Older draft admission used a regex that coerces this array to a calendar-day string.
          rcptApplyDraft(view,draft);assert.equal(view.primary.getAttribute('aria-disabled'),'true');
          assert(view.recordReason.textContent.includes('valid arrival date'));
          await rcptRecord(view);assert.equal(writes,0);assert.equal(document.activeElement,view.dateInput);
          for(const value of [null,undefined,[],['2026-10-08'],{},20261008])assert.equal(rcptValidDay(value),false);
          view.dateInput.value='2026-10-08';view.dateInput.fire('change');
          assert.equal(view.primary.getAttribute('aria-disabled'),'false');await rcptRecord(view);assert.equal(writes,1);
        """)

    def test_primary_preserves_busy_reload_done_profile_route_and_permission_guards(self):
        self.run_js("""
          tickAll(view);let writes=0;apiWrite=async()=>{writes++;return ready;};
          const focus=document.activeElement;
          receiptBusy(view,true);rcptSync(view);await rcptRecord(view);assert(view.primary.disabled);
          receiptBusy(view,false);view.reloadRequired=true;rcptSync(view);await rcptRecord(view);
          assert(view.primary.disabled);assert(view.recordReason.textContent.includes('Reload'));
          view.reloadRequired=false;view.done=true;rcptSync(view);await rcptRecord(view);assert(view.primary.disabled);
          view.done=false;state.profile={id:'user1'};rcptSync(view);await rcptRecord(view);assert(view.primary.disabled);
          state.profile={id:'matt'};routeToken++;rcptSync(view);await rcptRecord(view);assert(view.primary.disabled);routeToken--;
          state.may={receipts:false};rcptSync(view);await rcptRecord(view);assert(view.primary.disabled);
          state.may=null;rcptSync(view);assert.equal(view.primary.disabled,false);
          assert.equal(writes,0);assert.equal(document.activeElement,focus);assert(!view.previewSheet);
        """)

    def test_primary_preview_freezes_controls_and_drops_late_route_and_profile_responses(self):
        self.run_js("""
          for(const change of ['route','profile']){
            clear(main);state.profile={id:'matt'};const v=drawReceipt(delivery(),routeToken);tickAll(v);
            let finish;const calls=[];apiWrite=(path,data)=>{calls.push([path,data]);return new Promise(resolve=>{finish=resolve;});};
            const pending=rcptRecord(v);assert(v.busy);assert(v.primary.disabled);
            assert(v.root.querySelectorAll('input').every(input=>input.disabled));
            await rcptRecord(v);assert.equal(calls.length,1);
            if(change==='route'){routeToken++;clear(main).append(el('p',{text:'Other page'}));}
            else state.profile={id:'user1'};
            finish(ready);await pending;assert.equal(v.preview,null);assert(!v.previewSheet);
            assert.equal(calls.length,1);assert(!v.done);
          }
        """, draw=False)

    def test_edit_after_review_still_refuses_apply_and_requires_new_exact_preview(self):
        self.run_js("""
          tickAll(view);const calls=[];apiWrite=async(path,data)=>{calls.push([path,data]);return ready;};
          await rcptRecord(view);assert(view.previewSheet);const reviewed=view.preview;
          view.comps[0].rows[0].values.condition='LP';rcptChanged(view);
          assert(view.stale.textContent.includes('Changed since preview'));
          await applyDelivery(view);assert.equal(calls.length,1);assert.equal(view.preview,null);
          assert(!view.previewSheet);assert(!view.done);assert(main.textContent.includes('Changed since preview'));
          await rcptRecord(view);assert.equal(calls.length,2);assert.notEqual(view.preview.key,reviewed.key);
          assert.equal(calls[1][1].components[0].rows[0].condition,'LP');
        """)
