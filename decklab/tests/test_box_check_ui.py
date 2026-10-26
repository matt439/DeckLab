"""Local physical-box observations and guarded date saves over fixture APIs only."""
import unittest

from decklab.tests import test_assembly_takeapart_ui as take_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class BoxCheckUiTests(unittest.TestCase):
    def run_js(self, scenario):
        take_ui.AssemblyTakeApartUiTests.run_js(self, r'''
          const boxMeta=extra=>({expect:'b'.repeat(64),recipe_sha256:'d'.repeat(64),checked_on:null,editable:true,why_not:null,...extra});
          const boxPlan=(physical=contents(),meta=boxMeta())=>{const data=takePlan(physical);data.decks[0].box_check=meta;
            data.cards['Recorded Elf']={...alpha,name:'Recorded Elf',img_small:'/img/intended-printing',finish:'foil'};
            data.box_check_cards={'Recorded Elf':{...alpha,name:'Recorded Elf',img_small:'/img/name-only-art'},
              'Missing spell':{...alpha,name:'Missing spell',img_small:'/img/represented-spell'}};return data;};
          const mountBox=async(physical=contents(),meta=boxMeta())=>{reset();state.may=null;mockApi(()=>{throw Error('Unexpected fixture request');});const data=boxPlan(physical,meta);
            const view=drawAssembly(data,routeToken);await settle();return{data,view,button:view.results.querySelector('.pack-box-check')};};
          const openBox=async(physical=contents(),meta=boxMeta())=>{const made=await mountBox(physical,meta);made.button.click();
            return{...made,sheet:[...assemblySheets].at(-1)};};
          const nums=sheet=>sheet.body.querySelectorAll('input').filter(input=>input.getAttribute('type')==='number');
          const found=(sheet,index,value)=>{const input=nums(sheet)[index];input.value=value;input.fire('input');return input;};
          const reviewButton=sheet=>button(sheet.dialog,'Review differences');
          const dateButton=sheet=>button(sheet.dialog,'Save check date');
          const allFound=sheet=>localChecks(sheet).forEach(input=>{input.checked=true;input.fire('change');});
          const reviewed=sheet=>{allFound(sheet);reviewButton(sheet).click();return sheet;};
          const observed=()=>[{section:'Commander',row:0,quantity:1},{section:'Companion',row:0,quantity:1},
            {section:'Deck',row:0,quantity:2},{section:'Deck',row:1,quantity:20},{section:'Deck',row:2,quantity:1},
            {section:'Deck',row:3,quantity:1},{section:'Sideboard',row:0,quantity:3}];
          const boxAnswer=extra=>({saved:true,id:'casual/a',revision:1,sha256:'c'.repeat(64),recipe_sha256:'d'.repeat(64),
            checked_on:'2026-10-27',missing:[],extra:[],expected_cards:29,found_cards:29,...extra});
          const extraInput=(sheet,label)=>sheet.body.querySelectorAll('input').filter(input=>input.getAttribute('aria-label')===label).at(-1);
          const extraCard=(sheet,name='Mountain',quantity='2',section='Sideboard')=>{
            button(sheet.body,'Add extra card').click();const named=extraInput(sheet,'Extra card exact canonical name');
            named.value=name;named.fire('input');const input=extraInput(sheet,'Extra physical quantity');input.value=quantity;input.fire('input');
            const choice=sheet.body.querySelectorAll('select').at(-1);choice.value=section;choice.fire('change');return{named,input,choice};
          };
        ''' + scenario)

    def test_every_recorded_section_basic_and_installed_marker_starts_unreviewed(self):
        self.run_js(r'''
          const {sheet}=await openBox();assert.equal(localChecks(sheet).length,7);assert(localChecks(sheet).every(input=>!input.checked));
          same(nums(sheet).map(input=>input.value),['','','','','','','']);assert(reviewButton(sheet).disabled);
          for(const words of ['Commander','Companion','Deck','Sideboard','Recorded commander','Recorded companion','Recorded Elf','Forest',
            'Named physical marker (marked for Represented spell)','Unspecified stand-in (marked for Missing spell)','Packed sideboard card',
            'representative name-only art','historical date','counts and differences stay only in this review'])assert(sheet.body.textContent.includes(words),words);
          assert(!sheet.body.textContent.includes('2 x Alpha'));assert(!dateButton(sheet));
        ''')

    def test_art_uses_only_separate_name_map_and_anonymous_marker_has_no_intended_target_art(self):
        self.run_js(r'''
          const {sheet}=await openBox(),images=sheet.body.querySelectorAll('img').map(img=>img.getAttribute('src')).filter(src=>src.startsWith('/img/'));
          same(images,['/img/name-only-art']);assert(!images.includes('/img/intended-printing'));assert(!images.includes('/img/represented-spell'));
          const tiles=sheet.body.querySelectorAll('.card-tile');assert.equal(tiles.length,7);
          assert(tiles.every(tile=>tile.tag==='label'));assert(tiles.every(tile=>!tile.getAttribute('class').includes('is-foil')));
          assert(tiles[5].textContent.includes('Unspecified physical stand-in'));
        ''')

    def test_ticks_fill_full_quantity_and_untick_returns_to_unreviewed_zero_is_explicit(self):
        self.run_js(r'''
          const {sheet}=await openBox();localChecks(sheet)[3].checked=true;localChecks(sheet)[3].fire('change');assert.equal(nums(sheet)[3].value,'20');
          localChecks(sheet)[3].checked=false;localChecks(sheet)[3].fire('change');assert.equal(nums(sheet)[3].value,'');
          allFound(sheet);assert(!reviewButton(sheet).disabled);found(sheet,3,'0');assert(!localChecks(sheet)[3].checked);
          assert(!reviewButton(sheet).disabled);found(sheet,3,'21');assert(!localChecks(sheet)[3].checked);assert(!reviewButton(sheet).disabled);
          found(sheet,3,'20');assert(localChecks(sheet)[3].checked);found(sheet,3,'');assert(!localChecks(sheet)[3].checked);
          assert(reviewButton(sheet).disabled);
        ''')

    def test_local_counts_cancel_and_reopen_make_no_requests_or_shared_packing_ticks(self):
        self.run_js(r'''
          const {sheet,view}=await openBox();const calls=[];apiWrite=async(path,body)=>{calls.push([path,body]);throw Error('Local counts must not write');};
          allFound(sheet);found(sheet,2,'1');extraCard(sheet);button(sheet.dialog,'Cancel').click();assert(!view.reviewing);assert.equal(calls.length,0);
          view.results.querySelector('.pack-box-check').click();const fresh=[...assemblySheets].at(-1);assert(fresh!==sheet);
          assert(nums(fresh).every(input=>input.value===''));assert.equal(localChecks(fresh).length,7);assert.equal(calls.length,0);
        ''')

    def test_blur_change_of_last_extra_count_keeps_review_button_and_its_first_click(self):
        self.run_js(r'''
          const {sheet}=await openBox();allFound(sheet);const extra=extraCard(sheet,'Opt','2','Sideboard');
          extra.input.focus();const review=reviewButton(sheet);assert(!review.disabled);
          // A spinbutton emits input while typing, then change when pointer focus leaves
          // for Review. The original button must survive until that same click lands.
          extra.input.fire('change');assert(review.isConnected);assert.equal(reviewButton(sheet),review);
          review.focus();review.click();assert(dateButton(sheet));
          assert(sheet.body.textContent.includes('Sideboard: 2 x Opt'));
          assert.equal(button(sheet.dialog,'Back to counts').disabled,false);
        ''')

    def test_all_rows_and_extra_fields_must_be_reviewed_with_bounded_whole_counts(self):
        self.run_js(r'''
          const {sheet}=await openBox();allFound(sheet);
          for(const value of ['','-1','1.5','10000','NaN','1e2']){found(sheet,1,value);assert(reviewButton(sheet).disabled,value);}
          found(sheet,1,'0');assert(!reviewButton(sheet).disabled);const extra=extraCard(sheet,'Mountain','0');assert(reviewButton(sheet).disabled);
          extra.input.value='1';extra.input.fire('input');assert(!reviewButton(sheet).disabled);
          extra.named.value=' Mountain';extra.named.fire('input');assert(reviewButton(sheet).disabled);
          extra.named.value='Mountain';extra.named.fire('input');assert(!reviewButton(sheet).disabled);
        ''')

    def test_section_aware_deficits_excess_and_explicit_extra_do_not_cancel_each_other(self):
        self.run_js(r'''
          const {sheet}=await openBox();allFound(sheet);found(sheet,0,'0');found(sheet,2,'1');found(sheet,3,'21');found(sheet,5,'0');extraCard(sheet);
          reviewButton(sheet).click();const text=sheet.body.textContent;
          for(const words of ['Commander: 1 x Recorded commander','Deck: 1 x Recorded Elf','Deck: 1 x Unspecified stand-in (marked for Missing spell)',
            'Deck: 1 x Forest','Sideboard: 2 x Mountain','29 recorded physical cards; 29 cards found'])assert(text.includes(words),words);
          assert(dateButton(sheet));button(sheet.dialog,'Back to counts').click();same(nums(sheet).slice(0,7).map(input=>input.value),['0','1','1','21','1','0','3']);
          assert(reviewButton(sheet));assert(!dateButton(sheet));
        ''')

    def test_exact_sha_recipe_and_all_observations_sent_once_date_save_changes_no_other_recipe(self):
        self.run_js(r'''
          const {sheet,view}=await openBox();const before=JSON.stringify(view.selected),kit=view.buildKit={a:{sleeves:'keep'}};reviewed(sheet);
          let resolve;const calls=[];apiWrite=(path,body)=>{calls.push([path,body]);return new Promise(r=>resolve=r);};
          const old=dateButton(sheet);old.focus();old.click();old.fire('click');assert.equal(calls.length,1);assert(view.saving);
          same(calls,[['/api/deck/box-check',{id:'casual/a',expect:'b'.repeat(64),recipe_sha256:'d'.repeat(64),rows:observed(),extras:[]}]]);
          assert(nums(sheet).every(input=>input.disabled));resolve(boxAnswer());await settle();assert(!view.saving);assert(button(sheet.dialog,'Done'));
          assert(sheet.body.textContent.includes('Last box check recorded: 2026-10-27'));assert(sheet.body.textContent.includes('Review differences'));
          assert.equal(JSON.stringify(view.selected),before);assert.equal(view.buildKit,kit);old.fire('click');assert.equal(calls.length,1);
        ''')

    def test_confirmed_difference_receipt_matches_exact_named_and_anonymous_observations(self):
        self.run_js(r'''
          const {sheet}=await openBox();allFound(sheet);found(sheet,0,'0');found(sheet,2,'1');found(sheet,3,'21');found(sheet,5,'0');extraCard(sheet);
          reviewButton(sheet).click();let body;apiWrite=async(path,payload)=>{body=payload;return boxAnswer({missing:[
            {section:'Deck',kind:'marker',name:null,for:'Missing spell',quantity:1},{section:'Commander',kind:'card',name:'Recorded commander',for:null,quantity:1},
            {section:'Deck',kind:'card',name:'Recorded Elf',for:null,quantity:1}],extra:[{section:'Sideboard',kind:'card',name:'Mountain',for:null,quantity:2},
              {section:'Deck',kind:'card',name:'Forest',for:null,quantity:1}]});};dateButton(sheet).click();await settle();assert(button(sheet.dialog,'Done'));
          same(body.extras,[{section:'Sideboard',name:'Mountain',quantity:2}]);assert.equal(body.rows[5].quantity,0);
        ''')

    def test_duplicate_explicit_extra_in_same_section_is_blocked_but_other_section_is_distinct(self):
        self.run_js(r'''
          const {sheet}=await openBox();allFound(sheet);extraCard(sheet,'Mountain','1','Deck');const second=extraCard(sheet,'Mountain','2','Deck');
          assert(reviewButton(sheet).disabled);second.choice.value='Sideboard';second.choice.fire('change');assert(!reviewButton(sheet).disabled);
          button(sheet.body,'Remove extra').click();assert(!reviewButton(sheet).disabled);
        ''')

    def test_unavailable_or_malformed_evidence_has_no_save_or_mutable_intended_fallback(self):
        self.run_js(r'''
          for(const [physical,meta] of [[contents({available:false,reason:'Physical record unavailable'}),boxMeta()],
            [contents(),boxMeta({expect:'x'})],[contents(),boxMeta({recipe_sha256:'x'})],[contents(),boxMeta({expect:'c'.repeat(64)})],
            [contents(),boxMeta({checked_on:'2026-02-30'})],[contents({card_count:28}),boxMeta()],
            [contents({sections:{Deck:[real('A',10000)]},card_count:10000}),boxMeta()],
            [contents({sections:{Deck:[real('A',1),real('A',1)]},card_count:2}),boxMeta()]]){
            const {sheet}=await openBox(physical,meta);assert.equal(nums(sheet).length,0);assert(!reviewButton(sheet));assert(!dateButton(sheet));
            assert(!sheet.body.textContent.includes('Alpha'));assert(button(sheet.dialog,'Close'));
          }
        ''')

    def test_read_only_review_explains_permission_in_both_stages_and_never_saves(self):
        self.run_js(r'''
          const {sheet}=await openBox(contents({can_take_apart:false}),boxMeta({editable:false,why_not:'This deck cannot be edited.'}));
          assert(sheet.body.textContent.includes('This deck cannot be edited.'));reviewed(sheet);assert(dateButton(sheet).disabled);
          let calls=0;apiWrite=async()=>{calls++;return boxAnswer();};dateButton(sheet).fire('click');assert.equal(calls,0);
        ''')

    def test_button_guards_exact_original_page_recipe_busy_progress_and_connected_trigger(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','data','recipe','saving','reviewing','previewing','progress','pending','error','detached','modal']){
            const {view,button:trigger}=await mountBox();let top;
            if(mode==='profile')state.profile={id:'user1'};if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='data')view.data={...view.data};if(mode==='recipe')view.selected[0].version='owned';if(mode==='saving')view.saving=true;
            if(mode==='reviewing')view.reviewing=true;if(mode==='previewing')view.previewing=true;if(mode==='progress')view.progress.loaded=false;
            if(mode==='pending')view.progress.pending.set('p',{});if(mode==='error')view.progress.error='Cannot save';if(mode==='detached')trigger.remove();
            if(mode==='modal')top=openSheet('Other modal');trigger.fire('click');assert.equal(assemblySheets.size,0,mode);top?.close();
          }
        ''')

    def test_nonbuilt_product_personal_or_absent_metadata_gets_no_box_button(self):
        self.run_js(r'''
          for(const mode of ['notbuilt','product','personal','noinfo']){
            const made=await mountBox();made.view.root.remove();const deck=made.data.decks[0];
            if(mode==='notbuilt')deck.completion.status='building';if(mode==='product')deck.id='product/fixture/blue';
            if(mode==='personal')state.profile={id:'user2',space:'user2'};if(mode==='noinfo')delete deck.box_check;
            const view=drawAssembly(made.data,routeToken);await settle();assert(!view.results.querySelector('.pack-box-check'),mode);
          }
        ''')

    def test_stale_or_hidden_input_changes_roll_back_and_reviewed_controls_cannot_change(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','recipe','data','metadata','modal','review']){
            const {sheet,view,data}=await openBox();allFound(sheet);let top;
            if(mode==='profile')state.profile={id:'other'};if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='recipe')view.selected[0].sideboard={Changed:1};if(mode==='data')view.data={...view.data};
            if(mode==='metadata')data.decks[0].box_check.recipe_sha256='e'.repeat(64);if(mode==='modal')top=openSheet('Other');
            if(mode==='review')reviewButton(sheet).click();found(sheet,2,'99');assert.equal(nums(sheet)[2].value,'2',mode);
            const tick=localChecks(sheet)[2];tick.checked=false;tick.fire('change');assert(tick.checked,mode);top?.close();
          }
        ''')

    def test_retired_review_back_save_and_disconnected_expected_control_cannot_write(self):
        self.run_js(r'''
          const {sheet}=await openBox();allFound(sheet);const oldReview=reviewButton(sheet);oldReview.click();const oldSave=dateButton(sheet);
          button(sheet.dialog,'Back to counts').click();let calls=0;apiWrite=async()=>{calls++;return boxAnswer();};oldSave.fire('click');assert.equal(calls,0);
          nums(sheet)[0].remove();oldReview.fire('click');assert(!dateButton(sheet));assert.equal(calls,0);
        ''')

    def test_network_conflict_or_malformed_receipt_requires_reload_without_blind_retry(self):
        self.run_js(r'''
          for(const failure of [Error('Lost response'),new ApiError(409,'Changed',{}),null]){
            const {sheet}=await openBox();reviewed(sheet);let calls=0;apiWrite=async()=>{calls++;if(failure)throw failure;return boxAnswer({found_cards:28});};
            const old=dateButton(sheet);old.focus();old.click();await settle();assert(button(sheet.dialog,'Reload plan'));assert(!dateButton(sheet));
            assert(sheet.body.textContent.includes('Reload the plan before saving again'));old.fire('click');assert.equal(calls,1);
          }
        ''')

    def test_every_receipt_field_and_diff_identity_must_match_before_historical_date_is_confirmed(self):
        self.run_js(r'''
          const invalid=[{saved:1},{saved:false},{sha256:'b'.repeat(64)},{id:'casual/b'},{revision:-1},{sha256:'short'},{recipe_sha256:'e'.repeat(64)},{checked_on:'2026-02-30'},
            {expected_cards:30},{found_cards:28},{missing:[{section:'Deck',kind:'card',name:'Recorded Elf',for:null,quantity:1}]},
            {extra:[{section:'Sideboard',kind:'marker',name:null,for:'Secret',quantity:1}]}];
          for(const extra of invalid){const {sheet}=await openBox();reviewed(sheet);apiWrite=async()=>boxAnswer(extra);dateButton(sheet).click();await settle();
            assert(!button(sheet.dialog,'Done'));assert(button(sheet.dialog,'Reload plan'));assert(!sheet.body.textContent.includes('Last box check recorded: 2026-10-27'));}
        ''')

    def test_known_400_exact_name_refusal_preserves_counts_and_requires_new_local_review(self):
        self.run_js(r'''
          const {sheet}=await openBox();allFound(sheet);extraCard(sheet,'mountain','2');reviewButton(sheet).click();
          apiWrite=async()=>{throw new ApiError(400,'Use exact canonical name Mountain',{});};dateButton(sheet).click();await settle();
          assert(reviewButton(sheet));assert(!dateButton(sheet));assert(!button(sheet.dialog,'Reload plan'));assert.equal(extraInput(sheet,'Extra card exact canonical name').value,'mountain');
          assert(sheet.body.textContent.includes('Use exact canonical name Mountain'));assert(nums(sheet).slice(0,7).every(input=>input.value!==''));
        ''')

    def test_same_day_noop_confirms_only_unchanged_hash_and_already_recorded_date(self):
        self.run_js(r'''
          const date='2026-10-27';
          const {sheet}=await openBox(contents(),boxMeta({checked_on:date}));reviewed(sheet);
          apiWrite=async()=>boxAnswer({saved:false,sha256:'b'.repeat(64),checked_on:date});dateButton(sheet).click();await settle();
          assert(button(sheet.dialog,'Done'));assert(!button(sheet.dialog,'Reload plan'));
          for(const [meta,answer] of [[boxMeta(),boxAnswer({saved:false,sha256:'b'.repeat(64)})],
              [boxMeta({checked_on:date}),boxAnswer()]]){
            const current=await openBox(contents(),meta);reviewed(current.sheet);apiWrite=async()=>answer;
            dateButton(current.sheet).click();await settle();assert(!button(current.sheet.dialog,'Done'));
            assert(button(current.sheet.dialog,'Reload plan'));
          }
        ''')

    def test_done_refreshes_same_exact_recipe_only_after_history_landing_and_keeps_other_choices(self):
        self.run_js(r'''
          const {sheet,view,data}=await openBox();const before=JSON.stringify(view.selected),kit=view.buildKit={a:{sleeves:'same'}};
          sheet.entry={token:700,pos:3,done:false,fromHistory:false};history.state={sheet:700,pos:3};let refreshed=0;
          view.run=()=>{refreshed++;assert.equal(JSON.stringify(view.selected),before);assert.equal(view.buildKit,kit);};
          reviewed(sheet);apiWrite=async()=>boxAnswer();dateButton(sheet).click();await settle();assert.equal(refreshed,0);
          button(sheet.dialog,'Done').click();assert.equal(refreshed,0);assert(view.reviewing);history.state={pos:2};window.fire('popstate');
          assert.equal(refreshed,1);assert(!view.reviewing);assert.equal(JSON.stringify(view.selected),before);assert.equal(view.data,data);
          window.fire('popstate');assert.equal(refreshed,1);
        ''')

    def test_closed_pending_known_success_reconciles_only_original_owner_without_repeating_save(self):
        self.run_js(r'''
          const {sheet,view}=await openBox();reviewed(sheet);let resolve,calls=0,refreshed=0;view.run=()=>{refreshed++;};
          apiWrite=()=>{calls++;return new Promise(r=>resolve=r);};dateButton(sheet).click();closeHeader(sheet).click();assert(sheet.closed);assert(view.saving);
          resolve(boxAnswer());await settle();assert.equal(calls,1);assert.equal(refreshed,1);assert(!view.saving);assert(!view.reviewing);
        ''')

    def test_late_pending_result_and_later_history_event_cannot_take_over_changed_profile_page_or_recipe(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','data','recipe','metadata']){
            const {sheet,view,data}=await openBox();reviewed(sheet);let resolve,refresh=0;view.run=()=>{refresh++;};
            apiWrite=()=>new Promise(r=>resolve=r);dateButton(sheet).click();sheet.close();
            if(mode==='profile')state.profile={id:'other'};if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='data')view.data={...view.data};if(mode==='recipe')view.selected[1].prefer=['Different'];
            if(mode==='metadata')data.decks[0].box_check.expect='e'.repeat(64);resolve(boxAnswer());await settle();
            assert.equal(refresh,0,mode);window.fire('popstate');assert.equal(refresh,0,mode);
          }
        ''')

    def test_confirmation_and_error_focus_only_when_request_still_owns_focus(self):
        self.run_js(r'''
          for(const moved of [false,true])for(const failed of [false,true]){
            const {sheet}=await openBox();reviewed(sheet);let resolve,reject;apiWrite=()=>new Promise((r,no)=>{resolve=r;reject=no;});
            dateButton(sheet).focus();dateButton(sheet).click();const close=closeHeader(sheet);if(moved)close.focus();
            if(failed)reject(Error('Lost response'));else resolve(boxAnswer());await settle();
            if(moved)assert.equal(document.activeElement,close);else assert.equal(document.activeElement.getAttribute('role'),failed?'alert':'status');
          }
        ''')

    def test_historical_deck_date_is_private_calendar_valid_and_does_not_certify_current_contents(self):
        self.run_js(r'''
          const data={summary:{status:'built'},version:'target',versions:['target'],owned:{rows:[],totals:{missing:0,aud_missing:0}},box_checked_on:'2026-10-27'};
          const banner=availabilityBanner(data,null);assert(banner.textContent.includes('Last box check recorded: 2026-10-27'));
          assert(banner.textContent.includes('Contents may have changed since'));assert.equal(banner.querySelector('time').getAttribute('datetime'),'2026-10-27');
          delete data.owned;assert.equal(availabilityBanner(data,null),null);
          assert.equal(boxCheckDate('2026-02-30'),null);assert.equal(boxCheckDate('2026-02-29'),null);assert.equal(boxCheckDate('2024-02-29'),'2024-02-29');
          assert.equal(boxCheckDateNote({box_checked_on:null}),null);assert.equal(boxCheckDateNote({box_checked_on:'not a date'}),null);
        ''')


if __name__ == "__main__":
    unittest.main()
