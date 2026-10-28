"""Combined player/kit draft review with real UI functions and a disposable Node DOM."""
import json
import subprocess
import unittest

from decklab.tests.test_editor_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


KIT_SETUP = SETUP + """
  state.profile = {id:'matt', name:'Matt', role:'admin', plays_as:'user', space:'home'};
  state.profiles = [state.profile, {id:'user1',name:'User1',role:'member',plays_as:'wife',space:'home'}];
  state.may = deriveMay(state.profile,false); routeToken = 7;
  const item = (id,kind,owner='shared',extra={}) => ({id,kind,owner,label:id,quantity:100,
    editable:true,used_by:[],capacity:null,...extra});
  const items = [item('matt-sleeves','sleeves','matt'), item('shared-sleeves','sleeves'),
    item('matt-box','deck_box','matt',{quantity:2}), item('shared-box','deck_box','shared',{quantity:2}),
    item('private-sleeves','sleeves','user1',{editable:false,label:'Private accessory'}),
    item('empty-box','deck_box','shared',{quantity:0})];
  const calls = []; api = async path => {calls.push(path);return {items};};
  const writes = []; apiWrite = async (path,body) => {writes.push([path,body]);throw new Error('No write during review');};
  const make = (extra={}) => {
    const ed = edit({space:'home',editable_fields:['status','player','archetype','sleeves','deck_box'],
      fields:{status:'built',player:'user',sleeves:'matt-sleeves',deck_box:'matt-box'},
      accessories:kitRowsOf(items,'matt'), ...extra});
    ed.space='home';ed.brackets=[];ed.dom.page=el('div');main.append(ed.dom.page);
    ed.dom.page.append(detailsPart());ed.dom.keyboardOwner={page:ed.dom.page,token:routeToken,profile:ed.profile};
    changed = opts => {ed.dirty=isDirty();if(opts?.history!==false)recordHistory(ed);};
    return ed;
  };
  const pick = (sheet,key,value) => {const control=sheet.body.querySelector(`[data-player-kit="${key}"]`);
    control.value=value;control.fire('change');};
  const apply = sheet => sheet.foot.querySelector('.btn-primary');
  const finish = async () => {for(let i=0;i<12;i++)await Promise.resolve();};
  const deferred = () => {let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class EditorPlayerKitUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), KIT_SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_review_applies_all_fields_as_one_local_step_and_preserves_complete_payload(self):
        self.run_js("""
          const ed=make(),sheet=await reviewPlayerKit('either');
          assert.equal(ed.fields.player,'user');assert.equal(ed.history.length,0);assert.equal(writes.length,0);
          assert(apply(sheet).disabled);pick(sheet,'sleeves','shared-sleeves');assert(apply(sheet).disabled);
          pick(sheet,'deck_box','shared-box');assert(!apply(sheet).disabled);
          assert(sheet.body.textContent.includes('Played by'));assert(sheet.body.textContent.includes('shared-box'));
          apply(sheet).click();assert(sheet.closed);assert.equal(ed.fields.player,'either');
          assert.equal(ed.fields.sleeves,'shared-sleeves');assert.equal(ed.fields.deck_box,'shared-box');
          assert.equal(ed.history.length,1);assert.equal(writes.length,0);
          same(draftBody().fields,{player:'either',sleeves:'shared-sleeves',deck_box:'shared-box'});
          same(draftBody().kit_rows,[{field:'sleeves',id:'shared-sleeves'},{field:'deck_box',id:'shared-box'}]);
          assert(!kitRows('sleeves').some(row=>row.id==='matt-sleeves'));
          assert(Object.isFrozen(ed.playerKitItems));assert(Object.isFrozen(ed.playerKitItems[0].used_by));
        """)

    def test_clear_both_is_explicit_and_one_undo_restores_player_and_kit(self):
        self.run_js("""
          const ed=make(),sheet=await reviewPlayerKit('either');pick(sheet,'sleeves','');pick(sheet,'deck_box','');
          apply(sheet).click();same(draftBody().fields,{player:'either',sleeves:null,deck_box:null});
          same(draftBody().kit_rows,[]);
          drawEditor=()=>{};assert.equal(undoLast(),true);
          assert.equal(ed.fields.player,'user');assert.equal(ed.fields.sleeves,'matt-sleeves');
          assert.equal(ed.fields.deck_box,'matt-box');assert.equal(ed.history.length,0);
          assert(kitRows('sleeves').some(row=>row.id==='matt-sleeves'));
          assert(kitRows('deck_box').some(row=>row.id==='matt-box'));
          assert.equal(draftBody().fields,undefined);assert.equal(writes.length,0);
        """)

    def test_retained_shared_field_is_included_even_when_only_other_kit_field_changes(self):
        self.run_js("""
          const ed=make({fields:{status:'built',player:'either',sleeves:'shared-sleeves',deck_box:'shared-box'}});
          const sheet=await reviewPlayerKit('user');pick(sheet,'sleeves','matt-sleeves');apply(sheet).click();
          same(draftBody().fields,{player:'user',sleeves:'matt-sleeves',deck_box:'shared-box'});
          assert.equal(ed.history.length,1);
        """)

    def test_cancel_does_not_change_player_kit_or_history(self):
        self.run_js("""
          const ed=make(),before=JSON.stringify(ed.fields),sheet=await reviewPlayerKit('either');
          pick(sheet,'sleeves','shared-sleeves');sheet.close();
          assert.equal(JSON.stringify(ed.fields),before);assert.equal(ed.history.length,0);assert.equal(writes.length,0);
        """)

    def test_private_destination_explains_owner_handoff_without_loading_or_changing_it(self):
        self.run_js("""
          const ed=make(),sheet=await reviewPlayerKit('wife');
          assert(sheet.body.textContent.includes("That player's kit is theirs to choose"));
          assert(!sheet.body.textContent.includes('Private accessory'));assert.equal(calls.length,0);
          assert.equal(apply(sheet),null);assert.equal(ed.fields.player,'user');assert.equal(ed.history.length,0);
        """)

    def test_hidden_nonhome_and_empty_kit_cases_keep_authoritative_existing_behavior(self):
        self.run_js("""
          const hidden=make({editable_fields:['status','player'],fields:{status:'built',player:'wife',sleeves:null,deck_box:null}});
          setField('player','user');assert.equal(hidden.fields.player,'user');assert.equal(calls.length,0);
          assert.equal(document.querySelector('dialog'),null);same(draftBody().fields,{player:'user'});
          const empty=make({fields:{status:'built',player:'either',sleeves:null,deck_box:null}});
          setField('player','user');assert.equal(empty.fields.player,'user');assert.equal(calls.length,1);
          assert.equal(kitRows('sleeves').length,0);await finish();assert(kitRows('sleeves').some(row=>row.id==='matt-sleeves'));
          const member=make();member.space='user2';assert.equal(editorPlayerKitVisible(member),false);
          assert.equal(await reviewPlayerKit('either'),null);assert.equal(writes.length,0);
        """)

    def test_only_editable_permitted_rows_are_offered_and_empty_boxes_cannot_be_selected(self):
        self.run_js("""
          make();const sheet=await reviewPlayerKit('either'),text=sheet.body.textContent;
          assert(!text.includes('Private accessory'));
          const sleeves=sheet.body.querySelector('[data-player-kit="sleeves"]');
          assert(!sleeves.querySelectorAll('option').some(option=>option.value==='matt-sleeves'));
          const boxes=sheet.body.querySelector('[data-player-kit="deck_box"]');
          assert(boxes.querySelectorAll('option').find(option=>option.value==='empty-box').disabled);
          assert.equal(boxes.value,'__choose__');assert(apply(sheet).disabled);
        """)

    def test_shared_sleeves_need_current_explicit_ack_and_changing_choice_clears_it(self):
        self.run_js("""
          items.find(row=>row.id==='shared-sleeves').used_by=[{holder:'casual/other',title:'Other deck'}];
          const ed=make(),sheet=await reviewPlayerKit('either');pick(sheet,'sleeves','shared-sleeves');pick(sheet,'deck_box','shared-box');
          assert(sheet.body.textContent.includes('Other deck'));assert(apply(sheet).disabled);
          const ack=sheet.body.querySelector('input');ack.checked=true;ack.fire('change');assert(!apply(sheet).disabled);
          pick(sheet,'deck_box','');assert.equal(ack.checked,false);assert(apply(sheet).disabled);
          ack.checked=true;ack.fire('change');apply(sheet).click();assert.equal(ed.history.length,1);
        """)

    def test_late_load_answers_cannot_change_closed_new_profile_route_or_modified_draft(self):
        self.run_js("""
          for(const mode of ['close','profile','route','sha','fields','list','editor']) {
            state.profile=state.profiles[0];state.may=deriveMay(state.profile,false);
            const ed=make(),pending=deferred();api=()=>pending.promise;const work=reviewPlayerKit('either');
            const dialog=document.querySelector('dialog');
            if(mode==='close')dialog.fire('close');if(mode==='profile')state.profile=state.profiles[1];
            if(mode==='route')routeToken++;if(mode==='sha')ed.sha256='b'.repeat(64);
            if(mode==='fields')ed.fields.archetype='New';if(mode==='list')ed.lists.Deck[0].qty++;
            if(mode==='editor')editor={...ed};pending.resolve({items});const sheet=await work;
            assert.equal(apply(sheet),null,mode);assert.equal(ed.fields.player,'user',mode);assert.equal(ed.history.length,0,mode);
            sheet.close();
          }
        """)

    def test_detached_controls_and_stale_draft_cannot_apply_review(self):
        self.run_js("""
          const ed=make(),sheet=await reviewPlayerKit('either');pick(sheet,'sleeves','');pick(sheet,'deck_box','');
          const old=apply(sheet);sheet.close();old.fire('click');assert.equal(ed.fields.player,'user');
          const next=await reviewPlayerKit('either');pick(next,'sleeves','');pick(next,'deck_box','');
          ed.fields.archetype='Changed outside the sheet';apply(next).fire('click');
          assert.equal(ed.fields.player,'user');assert.equal(ed.history.length,0);assert.equal(writes.length,0);
        """)

    def test_load_failure_does_not_infer_options_and_retry_requires_same_owner(self):
        self.run_js("""
          make();api=async()=>{throw new ApiError(503,'Unavailable');};const sheet=await reviewPlayerKit('either');
          assert(sheet.body.textContent.includes('Unavailable'));assert.equal(apply(sheet),null);
          const retry=sheet.body.querySelector('button');sheet.close();const oldCalls=calls.length;
          retry.fire('click');await finish();assert.equal(calls.length,oldCalls);assert.equal(writes.length,0);
        """)

    def test_real_check_and_ordinary_save_send_the_complete_reviewed_triple(self):
        self.run_js("""
          const ed=make(),sheet=await reviewPlayerKit('either');pick(sheet,'sleeves','shared-sleeves');pick(sheet,'deck_box','');
          apply(sheet).click();
          const expected={player:'either',sleeves:'shared-sleeves',deck_box:null};
          apiWrite=async(path,body)=>{writes.push([path,body]);return path.endsWith('/check')
            ? {ok:true,blocks:[],warnings:[],changes:{decklist:false,fields:Object.keys(expected),prose:[],marker:false}}
            : {saved:true,id:ed.id,title:ed.title,changed:true};};
          removeDraft=()=>true;await runCheck(ed);await doSave(null,null,{viewAfter:true});
          assert.equal(writes.length,2);same(writes[0][1].fields,expected);same(writes[1][1].fields,expected);
          assert.equal(writes[0][0],'/api/deck/check');assert.equal(writes[1][0],'/api/deck/save');
          same(writes[0][1].kit_rows,[{field:'sleeves',id:'shared-sleeves'}]);same(writes[1][1].kit_rows,writes[0][1].kit_rows);
          assert.equal(state.saved.answer.saved,true);
        """)

    def test_resumed_or_rebased_current_fields_derive_payload_without_extra_intent_state(self):
        self.run_js("""
          const ed=make();ed.fields={...ed.fields,player:'either',sleeves:null,deck_box:'shared-box'};
          same(draftBody().fields,{player:'either',sleeves:null,deck_box:'shared-box'});
          ed.base.fields={...ed.fields};assert.equal(draftBody().fields,undefined);
        """)

    def test_detached_original_player_button_cannot_change_current_editor(self):
        self.run_js("""
          const ed=make(),group=choiceField('player','Played by',allowedPlayers());ed.dom.page.append(group);
          const old=group.querySelectorAll('button').find(button=>button.getAttribute('data-focus')==='field:player:either');
          group.remove();old.fire('click');await finish();assert.equal(ed.fields.player,'user');assert.equal(calls.length,0);
        """)

    def test_accessory_add_refreshes_choice_cache_and_undo_refilters_real_picker(self):
        self.run_js("""
          const ed=make(),sheet=await reviewPlayerKit('either');pick(sheet,'sleeves','shared-sleeves');pick(sheet,'deck_box','shared-box');
          apply(sheet).click();let callback;openAccessorySheet=opts=>{callback=opts.onSaved;};addKitRow('sleeves');
          const refreshed=items.filter(row=>row.id!=='matt-sleeves').concat(item('fresh-sleeves','sleeves','matt'));
          callback({data:{items:refreshed},changed_id:'shared-sleeves'},'Saved');
          assert(!ed.playerKitItems.some(row=>row.id==='matt-sleeves'));
          drawEditor=()=>drawDetails();assert(undoLast());
          const picker=ed.dom.page.querySelector('[data-kit="sleeves"]');
          assert(picker.textContent.includes('fresh-sleeves'));assert(!kitRows('sleeves').some(row=>row.id==='matt-sleeves'));
          assert(kitRows('sleeves').some(row=>row.id==='fresh-sleeves'));assert.equal(writes.length,0);
        """)

    def test_pending_save_or_promotion_invalidates_loaded_review_controls(self):
        self.run_js("""
          for(const key of ['saving','asking','promoting']) {
            const ed=make(),sheet=await reviewPlayerKit('either');pick(sheet,'sleeves','');pick(sheet,'deck_box','');
            ed[key]=true;apply(sheet).fire('click');assert.equal(ed.fields.player,'user');assert.equal(ed.history.length,0);sheet.close();
          }
        """)

    def test_choice_cache_copies_only_bounded_primitive_facts(self):
        self.run_js("""
          const row=item('fixture','sleeves','matt',{used_by:[{holder:'casual/other',title:'Other',kind:'deck',need:60}]});
          const copied=editorPlayerKitItems([row]);row.label='Mutated';row.used_by[0].title='Changed';
          assert.equal(copied[0].label,'fixture');assert.equal(copied[0].used_by[0].title,'Other');
          assert(Object.isFrozen(copied[0]));assert(Object.isFrozen(copied[0].used_by[0]));
          assert.throws(()=>editorPlayerKitItems(Array(1001).fill(row)));
          assert.throws(()=>editorPlayerKitItems([item('bad','sleeves','matt',{quantity:{value:2}})]));
          assert.throws(()=>editorPlayerKitItems([item('bad','sleeves','matt',{used_by:[{title:{private:'bad'}}]})]));
        """)

    def test_actual_draft_save_resume_and_rebase_keep_recognized_ids(self):
        self.run_js("""
          const ed=make(),sheet=await reviewPlayerKit('either');pick(sheet,'sleeves','shared-sleeves');pick(sheet,'deck_box','shared-box');
          apply(sheet).click();let stored;local.set=(key,value)=>{stored=JSON.parse(value);return true;};
          assert(saveDraft(ed));const expected=[{field:'sleeves',id:'shared-sleeves'},{field:'deck_box',id:'shared-box'}];
          same(stored.playerKitRows,expected);readDraft=()=>stored;drawEditor=()=>{};
          startEditor({mode:'edit',view:ed.view,version:'target'});const resumed=editor;
          same(draftBody().kit_rows,expected);assert(!resumed.playerKitItems);
          const pending=deferred();api=()=>pending.promise;resumed.dom={page:el('div')};main.append(resumed.dom.page);
          resumed.dom.page.append(detailsPart());assert.equal(kitRows('sleeves').length,0);
          assert(!resumed.dom.page.querySelector('[data-focus="field:sleeves:matt-sleeves"]'));
          pending.resolve({items});await finish();assert(kitRows('sleeves').some(row=>row.id==='shared-sleeves'));
          assert(!kitRows('sleeves').some(row=>row.id==='matt-sleeves'));
          const mine={lists:resumed.lists,fields:resumed.fields,prose:resumed.prose,...editorPlayerKitSnapshot(resumed)};
          delete resumed.playerKitItems;const rebased=deferred();api=()=>rebased.promise;
          rebase(resumed,{...resumed.view,sha256:'b'.repeat(64)},mine,resumed.base);
          drawDetails();assert.equal(kitRows('sleeves').length,0);rebased.resolve({items});await finish();
          assert(resumed.dom.page.querySelector('[data-focus="field:sleeves:shared-sleeves"]'));
          assert(!resumed.dom.page.querySelector('[data-focus="field:sleeves:matt-sleeves"]'));
          same(draftBody().kit_rows,expected);assert.equal(draftBody().sha256,'b'.repeat(64));
          assert(Object.isFrozen(resumed.playerKitRows));assert(Object.isFrozen(resumed.playerKitRows[0]));
        """)

    def test_changed_triple_does_not_silently_discard_known_choice_intent(self):
        self.run_js("""
          const ed=make(),sheet=await reviewPlayerKit('either');pick(sheet,'sleeves','shared-sleeves');pick(sheet,'deck_box','shared-box');
          apply(sheet).click();ed.fields.sleeves='Unrelated legacy text';
          const body=draftBody();assert.equal(body.fields.sleeves,'Unrelated legacy text');
          assert(body.kit_rows.some(row=>row.field==='sleeves'&&row.id==='shared-sleeves'));
          // The server rejects that mismatch; only an explicit new choice changes intent.
          setField('sleeves',null);same(draftBody().kit_rows,[{field:'deck_box',id:'shared-box'}]);
        """)

    def test_malformed_present_metadata_stays_invalid_through_snapshots_and_restore(self):
        self.run_js("""
          const ed=make();ed.fields.player='either';ed.playerKitRows=[{field:'sleeves',id:'shared-sleeves'},
            {field:'sleeves',id:'shared-sleeves'}];
          assert.equal(draftBody().kit_rows,null);const saved=JSON.parse(snapshot(ed));assert.equal(saved.playerKitRows,null);
          restoreEditorPlayerKit(ed,saved);assert(Object.hasOwn(ed,'playerKitRows'));assert.equal(draftBody().kit_rows,null);
          setField('sleeves',null);assert.equal(draftBody().kit_rows,null);
          ed.view.editable_fields=['status','player'];assert.equal(draftBody().kit_rows,null);
        """)

    def test_status_clear_retains_local_intent_for_toggle_back_without_changing_free_kit_policy(self):
        self.run_js("""
          const ed=make(),sheet=await reviewPlayerKit('either');pick(sheet,'sleeves','shared-sleeves');pick(sheet,'deck_box','shared-box');
          apply(sheet).click();setField('status','building');assert(!Object.hasOwn(draftBody(),'kit_rows'));
          assert(Array.isArray(ed.playerKitRows));setField('status','built');
          same(draftBody().kit_rows,[{field:'sleeves',id:'shared-sleeves'},{field:'deck_box',id:'shared-box'}]);
          assert(ed.dom.page.textContent.includes('Review player and kit'));
        """)

    def test_resumed_matt_to_either_catalog_hides_base_rows_until_owned_refresh_succeeds(self):
        self.run_js("""
          const ed=make(),pending=deferred();api=path=>{calls.push(path);return pending.promise;};
          ed.fields={...ed.fields,player:'either',sleeves:'shared-sleeves',deck_box:'shared-box'};
          ed.playerKitRows=copiedPlayerKitRows([{field:'sleeves',id:'shared-sleeves'},{field:'deck_box',id:'shared-box'}]);
          const before=JSON.stringify([ed.fields,ed.playerKitRows]);drawDetails();assert.equal(calls.length,1);
          const waiting=ed.dom.page.querySelector('[data-kit="sleeves"]');
          assert.equal(waiting.querySelectorAll('.kit-tile').length,0);assert(!waiting.textContent.includes('Not in the accessories list'));
          assert.equal(kitRows('sleeves').length,0);assert.equal(JSON.stringify([ed.fields,ed.playerKitRows]),before);
          pending.resolve({items});await finish();const picker=ed.dom.page.querySelector('[data-kit="sleeves"]');
          assert(picker.querySelector('[data-focus="field:sleeves:shared-sleeves"]'));
          assert(!picker.querySelector('[data-focus="field:sleeves:matt-sleeves"]'));
          assert.equal(JSON.stringify([ed.fields,ed.playerKitRows]),before);assert.equal(ed.history.length,0);assert.equal(writes.length,0);
        """)

    def test_empty_either_to_matt_handoff_refreshes_real_picker_and_marks_new_known_choice(self):
        self.run_js("""
          const ed=make({fields:{status:'built',player:'either',sleeves:null,deck_box:null},accessories:kitRowsOf(items,'shared')});
          const pending=deferred();api=path=>{calls.push(path);return pending.promise;};setField('player','user');
          assert.equal(calls.length,1);assert.equal(document.querySelector('dialog'),null);assert.equal(kitRows('sleeves').length,0);
          pending.resolve({items});await finish();const picker=ed.dom.page.querySelector('[data-kit="sleeves"]');
          const option=picker.querySelector('[data-focus="field:sleeves:matt-sleeves"]');assert(option);option.click();
          assert.equal(ed.fields.sleeves,'matt-sleeves');same(draftBody().kit_rows,[{field:'sleeves',id:'matt-sleeves'}]);
          same(draftBody().fields,{player:'user',sleeves:'matt-sleeves',deck_box:null});assert.equal(writes.length,0);
        """)

    def test_rebased_same_sha_catalog_request_belongs_to_new_view_identity(self):
        self.run_js("""
          const ed=make(),first=deferred(),second=deferred();let reads=0;api=()=>++reads===1?first.promise:second.promise;
          ed.fields={...ed.fields,player:'either',sleeves:'shared-sleeves',deck_box:'shared-box'};
          drawDetails();const old=ed.playerKitCatalog;ed.view={...ed.view};drawDetails();assert.equal(reads,2);
          assert.notEqual(ed.playerKitCatalog,old);second.resolve({items:items.concat(item('new-shared','sleeves'))});await finish();
          first.resolve({items:items.concat(item('old-shared','sleeves'))});await finish();
          assert(kitRows('sleeves').some(row=>row.id==='new-shared'));assert(!kitRows('sleeves').some(row=>row.id==='old-shared'));
        """)

    def test_catalog_a_to_base_and_back_rejects_first_request_even_for_same_final_triple(self):
        self.run_js("""
          const ed=make(),first=deferred(),second=deferred();let reads=0;api=()=>++reads===1?first.promise:second.promise;
          const a={...ed.fields,player:'either',sleeves:'shared-sleeves',deck_box:'shared-box'};ed.fields={...a};drawDetails();
          ed.fields={...ed.base.fields};drawDetails();ed.fields={...a};drawDetails();assert.equal(reads,2);
          first.resolve({items:items.concat(item('old-shared','sleeves'))});await finish();assert(!ed.playerKitItems);
          second.resolve({items:items.concat(item('new-shared','sleeves'))});await finish();
          assert(kitRows('sleeves').some(row=>row.id==='new-shared'));assert(!kitRows('sleeves').some(row=>row.id==='old-shared'));
        """)

    def test_late_catalog_success_and_failure_cannot_cross_person_route_page_or_draft_triple(self):
        self.run_js("""
          for(const failure of [false,true])for(const mode of ['profile','route','page','kit']) {
            state.profile=state.profiles[0];state.may=deriveMay(state.profile,false);const ed=make(),pending=deferred();
            ed.fields={...ed.fields,player:'either',sleeves:'shared-sleeves',deck_box:'shared-box'};
            ed.playerKitRows=copiedPlayerKitRows([{field:'sleeves',id:'shared-sleeves'}]);api=()=>pending.promise;drawDetails();
            const proof=JSON.stringify(ed.playerKitRows);
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;
            if(mode==='page')ed.dom.page.remove();if(mode==='kit')ed.fields.sleeves=null;
            if(failure)pending.reject(new ApiError(503,'Old error'));else pending.resolve({items});await finish();
            assert(!ed.playerKitItems);assert.equal(JSON.stringify(ed.playerKitRows),proof);assert(!ed.dom.page.textContent.includes('Old error'));
          }
        """)

    def test_failed_catalog_keeps_draft_and_retry_is_bound_to_original_connected_control(self):
        self.run_js("""
          const ed=make();ed.fields={...ed.fields,player:'either',sleeves:'shared-sleeves',deck_box:'shared-box'};
          ed.playerKitRows=copiedPlayerKitRows([{field:'sleeves',id:'shared-sleeves'}]);const before=JSON.stringify([ed.fields,ed.playerKitRows]);
          api=async path=>{calls.push(path);throw new ApiError(503,'Choices unavailable');};drawDetails();await finish();
          const field=ed.dom.page.querySelector('[data-kit="sleeves"]'),retry=field.querySelector('button');
          assert(field.textContent.includes('Choices unavailable'));assert.equal(field.querySelectorAll('.kit-tile').length,0);
          assert(!field.textContent.includes('Not in the accessories list'));assert.equal(kitRows('sleeves').length,0);
          const pending=deferred();api=path=>{calls.push(path);return pending.promise;};retry.click();retry.fire('click');assert.equal(calls.length,2);
          pending.resolve({items});await finish();retry.fire('click');assert.equal(calls.length,2);
          assert.equal(JSON.stringify([ed.fields,ed.playerKitRows]),before);assert(kitRows('sleeves').some(row=>row.id==='shared-sleeves'));
        """)

    def test_failed_catalog_retry_cannot_read_after_profile_switch_and_private_destination_never_loads(self):
        self.run_js("""
          const ed=make();ed.fields={...ed.fields,player:'either',sleeves:'shared-sleeves',deck_box:'shared-box'};
          api=async path=>{calls.push(path);throw new ApiError(503,'Unavailable');};drawDetails();await finish();
          const retry=ed.dom.page.querySelector('[data-kit="sleeves"]').querySelector('button');state.profile=state.profiles[1];
          retry.fire('click');await finish();assert.equal(calls.length,1);
          state.profile=state.profiles[0];const privateDraft=make();privateDraft.fields.player='wife';drawDetails();
          assert.equal(calls.length,1);assert.equal(kitRows('sleeves').length,0);
          assert(privateDraft.dom.page.querySelector('[data-kit="sleeves"]').textContent.includes("That player's kit is theirs to choose"));
        """)

    def test_empty_origin_known_choice_then_clear_keeps_a_complete_valid_marked_payload(self):
        self.run_js("""
          const ed=make({fields:{status:'built',player:'either',sleeves:null,deck_box:null},accessories:kitRowsOf(items,'shared')});
          setField('player','user');await finish();setField('sleeves','matt-sleeves');
          same(draftBody().kit_rows,[{field:'sleeves',id:'matt-sleeves'}]);setField('sleeves',null);
          same(draftBody().fields,{player:'user',sleeves:null,deck_box:null});same(draftBody().kit_rows,[]);
          assert.equal(ed.fields.sleeves,null);assert.equal(writes.length,0);
        """)

    def test_unavailable_recognized_current_choice_is_preserved_without_legacy_fallback(self):
        self.run_js("""
          const ed=make();ed.fields.player='either';ed.playerKitRows=copiedPlayerKitRows([{field:'sleeves',id:'matt-sleeves'}]);
          const before=JSON.stringify([ed.fields,ed.playerKitRows]);drawDetails();await finish();
          const picker=ed.dom.page.querySelector('[data-kit="sleeves"]');
          assert(!picker.querySelector('[data-focus="field:sleeves:matt-sleeves"]'));
          assert(picker.textContent.includes('matt-sleeves is unavailable for this player'));
          assert(!picker.textContent.includes('Not in the accessories list'));
          assert.equal(JSON.stringify([ed.fields,ed.playerKitRows]),before);assert.equal(writes.length,0);
        """)
