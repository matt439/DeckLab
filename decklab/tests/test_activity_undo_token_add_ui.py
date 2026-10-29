"""Restoring a deleted token-card row needs whole-count confirmation and an exact fresh-id receipt."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityUndoTokenAddUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const pairRow=extra=>tokenRow({front:'Angel',back:'The Monarch',set:'tst',front_collector_number:'1',back_collector_number:'2',
            finish:'nonfoil',quantity:2,notes:'Paired faces verified',...extra});
          const tokenAdd=(extra={})=>{const p=preview({kind:'tokens',action:'token_add',label:'Angel / The Monarch',current:null,restored:pairRow(),
            identity_policy:'fresh_id',physical_confirmation_required:true,packing_restored:false,...extra});delete p.fields;
            if(Object.hasOwn(extra,'fields'))p.fields=extra.fields;return p;};
          const restored=(p=tokenAdd(),extra={})=>accepted(p,{action:'token_add',added_token_row_id:900,summary:'Restored the deleted token card as a new row.',...extra});
          const owned=sheet=>sheet.body.querySelector('input');
          const confirmOwned=(sheet,checked=true)=>{const input=owned(sheet);input.checked=checked;input.fire('change');return input;};
        ''' + scenario)

    def test_whole_physical_count_and_fresh_row_policy_are_shown_before_an_unchecked_confirmation(self):
        self.run_js(r'''
          const {sheet}=await open(tokenAdd());const text=sheet.body.textContent;
          for(const words of ['restores all 2 physical token cards','as a new token-card row','Each front/back pair is one physical card',
            'Historical token-card row to restore','Angel','The Monarch','tst','nonfoil','Paired faces verified','Not recorded',
            'still physically have the whole recorded quantity','Tokens page',"Earlier packing isn't reconnected",'original change stays in Activity',
            'I confirm I still physically have all 2 physical token cards'])assert(text.includes(words),words);
          assert(!text.includes('Reason for removing'));assert(!text.includes('Current token-card row'));
          assert.equal(sheet.body.querySelectorAll('input').length,1);assert.equal(owned(sheet).getAttribute('type'),'checkbox');
          assert.equal(owned(sheet).checked,false);assert(save(sheet).disabled);
        ''')

    def test_single_sided_card_names_one_card_without_pair_wording(self):
        self.run_js(r'''
          const row=pairRow({front:'Treasure',back:'',back_collector_number:'',quantity:1,notes:'single-sided verified'});
          const {sheet}=await open(tokenAdd({label:'Treasure',restored:row}));const text=sheet.body.textContent;
          assert(text.includes('restores all 1 physical token card recorded'));assert(!text.includes('front/back pair'));
        ''')

    def test_only_the_exact_token_restore_packet_is_accepted(self):
        self.run_js(r'''
          for(const extra of [{kind:'collection'},{identity_policy:'fresh_id_on_future_add'},{identity_policy:'reuse_id'},{packing_restored:true},
            {physical_confirmation_required:false},{current:pairRow()},{restored:null},{restored:pairRow({quantity:0})},{restored:pairRow({quantity:'2'})},
            {restored:{...pairRow(),id:71}},{label:'Angel'},{read_only:true},{read_only:false},{reason_required:true},{token_row_id:71},
            {fields:[]},{space:'user2'},{extra:'unknown'}]){
            const {sheet}=await open(tokenAdd(extra));assert(!save(sheet),JSON.stringify(extra));assert.equal(owned(sheet),null);
            assert(!sheet.body.textContent.includes('Historical token-card row to restore'),JSON.stringify(extra));
          }
        ''')

    def test_save_posts_only_source_receipt_and_true_confirmation_once(self):
        self.run_js(r'''
          const {sheet,p}=await open(tokenAdd());const input=confirmOwned(sheet);assert(!save(sheet).disabled);let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};const old=save(sheet);old.click();old.fire('click');
          same(sent,[['/api/activity/undo',{id:42,expect:'a'.repeat(64),confirm_owned:true}]]);assert(input.disabled);
          input.checked=false;input.fire('change');assert.equal(input.checked,true);finish(restored(p));await settle();
          assert(button(sheet.dialog,'Done'));assert(!save(sheet));assert(sheet.body.textContent.includes('Restored the deleted token card as a new row.'));
          old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_unchecked_or_programmatic_confirmation_cannot_save_and_reopen_resets_it(self):
        self.run_js(r'''
          const {sheet,view,trigger}=await open(tokenAdd());let writes=0;apiWrite=async()=>{writes++;};owned(sheet).checked=true;save(sheet).fire('click');await settle();
          assert.equal(writes,0);confirmOwned(sheet);const old=save(sheet);owned(sheet).checked=false;old.fire('click');await settle();assert.equal(writes,0);
          button(sheet.dialog,'Cancel').click();assert(!view.undoBusy);api=async()=>tokenAdd();trigger.click();await settle();
          const fresh=[...colSheets].at(-1);assert(fresh!==sheet);assert.equal(owned(fresh).checked,false);assert(save(fresh).disabled);assert.equal(writes,0);
        ''')

    def test_receipt_requires_a_new_positive_id_and_the_reviewed_row(self):
        self.run_js(r'''
          const invalid=[{action:'add'},{action:undefined},{added_token_row_id:0},{added_token_row_id:'900'},{added_token_row_id:undefined},
            {added_token_row_id:1.5},{restored:pairRow({quantity:1})},{restored:pairRow({notes:'Changed'})},{restored:{...pairRow(),id:900}},
            {added_key:{set:'tst',collector_number:'1',finish:'nonfoil'}},{removed_token_row_id:71},{source_id:43},{expect:'c'.repeat(64)},
            {space:'user2'},{kind:'collection'},{saved:false},{sha256:'bad'},{summary:''},{extra:'unknown'}];
          for(const extra of invalid){const {sheet,p}=await open(tokenAdd());confirmOwned(sheet);let writes=0;apiWrite=async()=>{writes++;return restored(p,extra);};
            const old=save(sheet);old.click();await settle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
            assert(sheet.body.textContent.includes('could not be confirmed'));old.fire('click');assert.equal(writes,1);}
          const collection={...preview(),action:'add',physical_confirmation_required:true,current:null,restored:collectionRow()};delete collection.fields;
          assert.equal(activityUndoReceipt(accepted(collection,{action:'add',added_token_row_id:900,
            added_key:{set:'fdn',collector_number:'227',finish:'nonfoil'}}),collection),false);
        ''')

    def test_stale_or_unknown_result_keeps_the_row_and_requires_reload_without_retry(self):
        self.run_js(r'''
          for(const failure of [Error('Lost reply'),new ApiError(409,'The token cards changed.',{}),new ApiError(503,'Unconfirmed.',{})]){
            const {sheet}=await open(tokenAdd());confirmOwned(sheet);let writes=0;apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await settle();
            assert(sheet.body.textContent.includes('Historical token-card row to restore'));assert(owned(sheet).disabled);assert(!save(sheet));
            assert(button(sheet.dialog,'Reload Activity'));old.fire('click');assert.equal(writes,1);
          }
        ''')

    def test_late_preview_for_a_previous_profile_reveals_nothing(self):
        self.run_js(r'''
          const {trigger}=mount();let finish;api=()=>new Promise(done=>finish=done);trigger.click();const pending=[...colSheets].at(-1);
          state.profile=state.profiles[1];finish(tokenAdd());await settle();assert.equal(owned(pending),null);assert(!pending.body.textContent.includes('Angel'));
        ''')

    def test_historical_text_is_literal_and_a_read_only_hint_offers_nothing(self):
        self.run_js(r'''
          const raw='<img src=x onerror=alert(1)>';const {sheet}=await open(tokenAdd({restored:pairRow({notes:raw})}));
          assert(sheet.body.textContent.includes(raw));assert.equal(sheet.body.querySelector('img'),null);
          const made=mount([candidate(42,{undo:{review:true,kind:'tokens',action:'token_restore_review',read_only:true}})]);
          assert.equal(made.trigger,null);
        ''')


if __name__ == "__main__":
    unittest.main()
