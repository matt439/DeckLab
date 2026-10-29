"""Strict source-aware duel result bridge, in actual script order over fake storage and API replies.

Run: python scripts/test_fixtures.py decklab.tests.test_life_source_bridge_ui
No real collection, cache, storage, browser, server, database or Forge is accessed.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + r"""
  routeToken=81;location.hash='#/play';state.profile.space='home';document.visibilityState='visible';document.hidden=false;editor=null;
  Date.now=()=>Date.parse('2026-10-29T01:00:00Z');structuredClone=value=>JSON.parse(JSON.stringify(value));
  const store=new Map();window.localStorage={getItem:key=>store.has(key)?store.get(key):null,
    setItem:(key,value)=>store.set(key,String(value)),removeItem:key=>store.delete(key)};
  const hashA='a'.repeat(64),hashB='b'.repeat(64),hashC='c'.repeat(64),hashR='d'.repeat(64),hashPlan='e'.repeat(64),
    postHash='f'.repeat(64),recordId='1'.repeat(32),planId='2'.repeat(32),sessionId='3'.repeat(32);
  const line=(name,qty=1)=>({name,qty,set:null,number:null,finish:'nonfoil'});
  const list=(id,sha256,title)=>({id,version:'target',sha256,title,sections:{Commander:[line('Leader')],Deck:[line('Forest',99)],Sideboard:[line('Opt',1)]}});
  const lists=()=>[list('commander/a',hashA,'First deck'),list('commander/b',hashB,'Second deck')];
  const makeData=(extra={})=>({lists:lists(),decks:{'commander/a':{can_record:true},'commander/b':{can_record:false}},
    games:[],sideboards:[],warnings:[],today:'2026-10-29',pod_lists:[],pods:[],...extra});
  let currentData=makeData(),ownerLive=true,cleanupCalls=0,cleanupResult=true;
  const writes=[],routes=[],messages=[],sheets=[];route=()=>routes.push(location.hash);toast=text=>messages.push(text);
  const openSheetReal=openSheet;openSheet=(...args)=>{const sheet=openSheetReal(...args);sheets.push(sheet);return sheet;};
  const makeGame=(data=currentData)=>{const game=lifeSourceNewGame({profile:'matt',space:'home',session_id:sessionId,date:data.today,
    choices:[{list:data.lists[0],name:'Matt'},{list:data.lists[1],name:'Opponent'}]});assert(game);lifeSourceEnd(game,'a');return game;};
  const reply=(body,saved=false)=>({...(saved?{saved:true,sha256:hashR}:{preview:true,id:body.id||recordId,review_sha256:hashR}),record:{
    ...(saved?{version:1,kind:'games',id:body.id,revision:1,created_on:'2026-10-29T01:00:00+00:00',updated_on:'2026-10-29T01:00:00+00:00',updated_by:'Matt'}:{}),
    date:body.date,result:body.result,notes:podTrim(body.notes),space:'home',sides:body.sides.map(side=>{
      const chosen=currentData.lists.find(value=>value.id===side.id&&value.version===side.version&&value.sha256===side.sha256);
      assert(chosen);const value={...structuredClone(chosen),player:podTrim(side.player),mulligans:side.mulligans};
      if(side.plan_id){const savedPlan=currentData.sideboards.find(item=>item.record.id===side.plan_id);assert(savedPlan);
        Object.assign(value,{base_sha256:side.sha256,sha256:postHash,plan_id:side.plan_id,plan_sha256:side.plan_sha256,
          sections:structuredClone(savedPlan.record.after)});}return value;})}});
  apiWrite=async(path,body)=>{writes.push([path,structuredClone(body)]);return reply(body,body.preview===false);};
  const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
  const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
  const begin=(game=null,data=makeData())=>{currentData=data;const chosen=game||makeGame(data);clear(main);
    const frame=el('div'),source=el('button',{text:'Counter source'});frame.append(source);main.append(frame);
    const bridge={source,isCurrent:()=>ownerLive,onSaved:()=>{cleanupCalls++;return cleanupResult;}};
    assert(lifeSourceReview(data,chosen,bridge));return{edit:sheets.at(-1),game:chosen,bridge,source,frame,data};};
  const control=(edit,key,side='')=>edit.body.querySelector(`[data-life-source-${key}${side?'='+side:''}]`);
  const set=(node,value,event='input')=>{node.value=value;node.fire(event);};
  const preview=async edit=>{edit.body.querySelector('form').fire('submit');await settle();return sheets.at(-1);};
  const save=async sheet=>{buttonText(sheet.foot,'Save this record').click();await settle();};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LifeSourceBridgeUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + "{" + scenario + "}", True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_exact_preset_keeps_ordinary_fields_and_requires_preview_then_one_save(self):
        self.run_js(r"""
          const {edit}=begin();assert.equal(control(edit,'date').value,'2026-10-29');assert.equal(control(edit,'result').value,'a');
          assert.equal(control(edit,'name','b').value,'Opponent');assert.equal(writes.length,0);
          set(control(edit,'notes'),'A played game');set(control(edit,'mulligans','a'),'2','change');const reviewed=await preview(edit);
          assert.notEqual(reviewed,edit);assert.equal(writes.length,1);const body=writes[0][1];assert.equal(writes[0][0],'/api/play/game');
          same(body.sides.map(side=>[side.id,side.sha256,side.player,side.mulligans]),
            [['commander/a',hashA,'Matt',2],['commander/b',hashB,'Opponent',0]]);
          for(const field of ['v','session_id','sources','damage','commander','poison','players'])assert(!(field in body));
          for(const side of body.sides)for(const field of ['sources','damage','life','poison','list'])assert(!(field in side));
          assert.equal(cleanupCalls,0);flushTimers();document.fire('visibilitychange');await settle();assert.equal(writes.length,1);
          const button=buttonText(reviewed.foot,'Save this record');button.click();button.click();await settle();
          assert.equal(writes.length,2);assert.equal(writes[1][1].id,recordId);assert.equal(writes[1][1].review_sha256,hashR);
          assert.equal(cleanupCalls,1);assert(edit.closed);assert(reviewed.closed);same(messages,['Record saved.']);same(routes,['#/play']);
        """)

    def test_changed_removed_and_renamed_selectors_have_no_default_or_historical_snapshot(self):
        self.run_js(r"""
          const original=makeData(),game=makeGame(original);
          for(const replacement of [[],[list('commander/a',hashC,'Current deck'),original.lists[1]],
              [list('commander/renamed',hashC,'Renamed deck'),original.lists[1]]]){
            const data=makeData({lists:replacement,decks:{'commander/a':{can_record:true},'commander/renamed':{can_record:true}}});
            const {edit}=begin(game,data),picker=control(edit,'list','a');assert.equal(picker.value,'');
            assert(picker.textContent.includes('Choose a current replacement list'));assert(!picker.textContent.includes('historical'));
            await preview(edit);assert.equal(writes.length,0);assert(edit.body.textContent.includes('keep counting without recording'));
            assert.equal(picker.value,'');edit.close();}
        """)

    def test_explicit_replacement_captures_current_sha_and_keeps_typed_draft(self):
        self.run_js(r"""
          const game=makeGame(),data=makeData();data.lists[0].sha256=hashC;const {edit}=begin(game,data);
          set(control(edit,'name','b'),'Named opponent');set(control(edit,'notes'),'Kept notes');await preview(edit);assert.equal(writes.length,0);
          set(control(edit,'list','a'),'0','change');const reviewed=await preview(edit);assert.equal(writes[0][1].sides[0].sha256,hashC);
          buttonText(reviewed.foot,'Back to editing').click();assert.equal(control(edit,'notes').value,'Kept notes');
          assert.equal(control(edit,'name','b').value,'Named opponent');assert.equal(control(edit,'list','a').value,'0');
        """)

    def test_current_positive_permission_is_required_without_legacy_fallback(self):
        self.run_js(r"""
          for(const decks of [undefined,{}, {'commander/a':{can_record:false}},{'commander/a':{can_record:1}}]){
            const {edit}=begin(null,makeData({decks}));await preview(edit);assert.equal(writes.length,0);
            assert(edit.body.textContent.includes('Choose a current deck you may record'));edit.close();}
        """)

    def test_selected_catalog_sha_sections_and_title_drift_require_a_fresh_explicit_choice(self):
        self.run_js(r"""
          for(const mutate of [chosen=>chosen.sha256=hashC,chosen=>chosen.sections.Deck[0].qty=98,
              chosen=>chosen.title='Changed current title']){
            const {edit,game}=begin(),before=writes.length;set(control(edit,'notes'),'Keep these notes');
            set(control(edit,'name','b'),'Kept opponent');mutate(currentData.lists[0]);await preview(edit);
            assert.equal(writes.length,before);assert.equal(control(edit,'list','a').value,'');
            assert(edit.body.textContent.includes('Choose current replacements explicitly'));
            assert.equal(control(edit,'notes').value,'Keep these notes');assert.equal(control(edit,'name','b').value,'Kept opponent');
            assert.equal(game.players[0].list.sha256,hashA);await preview(edit);assert.equal(writes.length,before);
            set(control(edit,'list','a'),'0','change');const reviewed=await preview(edit);assert.notEqual(reviewed,edit);
            assert.equal(writes.length,before+1);assert.equal(writes.at(-1)[1].sides[0].sha256,currentData.lists[0].sha256);
            reviewed.close();edit.close();}
        """)

    def test_a_selection_from_outdated_option_text_refreshes_before_it_can_adopt_new_contents(self):
        self.run_js(r"""
          const {edit}=begin();currentData.lists[0].sha256=hashC;currentData.lists[0].title='New current title';
          set(control(edit,'list','a'),'0','change');assert.equal(control(edit,'list','a').value,'');
          assert(control(edit,'list','a').textContent.includes('New current title'));await preview(edit);assert.equal(writes.length,0);
          set(control(edit,'list','a'),'0','change');await preview(edit);assert.equal(writes.length,1);
          assert.equal(writes[0][1].sides[0].sha256,hashC);
        """)

    def test_hidden_selection_callbacks_cannot_renew_a_changed_catalog_binding(self):
        self.run_js(r"""
          const {edit}=begin();currentData.lists[0].sha256=hashC;const picker=control(edit,'list','a');
          picker.hidden=true;set(picker,'0','change');set(picker,'0','change');picker.hidden=false;
          await preview(edit);assert.equal(writes.length,0);assert.equal(picker.value,'');
          set(picker,'0','change');await preview(edit);assert.equal(writes.length,1);assert.equal(writes[0][1].sides[0].sha256,hashC);
        """)

    def test_matching_sideboard_plan_keeps_base_selector_and_checks_transformed_sections(self):
        self.run_js(r"""
          const data=makeData(),after={Commander:[line('Leader')],Deck:[line('Forest',98),line('Opt')],Sideboard:[line('Forest')]};
          data.sideboards=[{sha256:hashPlan,record:{id:planId,deck:structuredClone(data.lists[0]),opponent:structuredClone(data.lists[1]),
            out:[{name:'Forest',qty:1}],in:[{name:'Opt',qty:1}],after}}];
          const {edit}=begin(null,data);set(control(edit,'plan','a'),planId,'change');const reviewed=await preview(edit);
          assert.notEqual(reviewed,edit);assert.equal(writes[0][1].sides[0].sha256,hashA);
          assert.equal(writes[0][1].sides[0].plan_id,planId);assert.equal(writes[0][1].sides[0].plan_sha256,hashPlan);
          assert(reviewed.body.textContent.includes('sideboarded'));await save(reviewed);assert.equal(cleanupCalls,1);
        """)

    def test_selected_plan_sha_or_transformed_contents_cannot_change_without_reselection(self):
        self.run_js(r"""
          for(const mutate of [item=>item.sha256=hashC,item=>item.record.after.Deck[0].qty=97]){
            const data=makeData();data.sideboards=[{sha256:hashPlan,record:{id:planId,deck:structuredClone(data.lists[0]),
              opponent:structuredClone(data.lists[1]),out:[{name:'Forest',qty:1}],in:[{name:'Opt',qty:1}],
              after:{Commander:[line('Leader')],Deck:[line('Forest',98),line('Opt')],Sideboard:[line('Forest')]}}}];
            const {edit}=begin(null,data),before=writes.length;set(control(edit,'plan','a'),planId,'change');
            set(control(edit,'notes'),'Preserve plan draft');mutate(data.sideboards[0]);await preview(edit);
            assert.equal(writes.length,before);assert.equal(control(edit,'plan','a').value,'pending');
            assert.equal(control(edit,'notes').value,'Preserve plan draft');await preview(edit);assert.equal(writes.length,before);
            set(control(edit,'plan','a'),planId,'change');const reviewed=await preview(edit);assert.equal(writes.length,before+1);
            assert.equal(writes.at(-1)[1].sides[0].plan_sha256,data.sideboards[0].sha256);reviewed.close();edit.close();}
        """)

    def test_a_deleted_selected_plan_requires_explicit_none_instead_of_silently_dropping_it(self):
        self.run_js(r"""
          const data=makeData();data.sideboards=[{sha256:hashPlan,record:{id:planId,deck:structuredClone(data.lists[0]),
            opponent:structuredClone(data.lists[1]),out:[{name:'Forest',qty:1}],in:[{name:'Opt',qty:1}],
            after:{Commander:[line('Leader')],Deck:[line('Forest',98),line('Opt')],Sideboard:[line('Forest')]}}}];
          const {edit}=begin(null,data);set(control(edit,'plan','a'),planId,'change');data.sideboards.splice(0,1);
          await preview(edit);assert.equal(writes.length,0);assert.equal(control(edit,'plan','a').value,'pending');
          assert.equal(control(edit,'plan','a').disabled,false);await preview(edit);assert.equal(writes.length,0);
          set(control(edit,'plan','a'),'','change');await preview(edit);assert.equal(writes.length,1);
          assert(!('plan_id' in writes[0][1].sides[0]));
        """)

    def test_opponents_selected_plan_needs_explicit_acknowledgement_after_list_drift(self):
        self.run_js(r"""
          const data=makeData();data.sideboards=[{sha256:hashPlan,record:{id:planId,deck:structuredClone(data.lists[1]),
            opponent:structuredClone(data.lists[0]),out:[{name:'Forest',qty:1}],in:[{name:'Opt',qty:1}],
            after:{Commander:[line('Leader')],Deck:[line('Forest',98),line('Opt')],Sideboard:[line('Forest')]}}}];
          const {edit}=begin(null,data);set(control(edit,'plan','b'),planId,'change');data.lists[0].sha256=hashC;
          await preview(edit);assert.equal(writes.length,0);assert.equal(control(edit,'list','a').value,'');
          assert.equal(control(edit,'plan','b').value,'pending');set(control(edit,'list','a'),'0','change');
          assert.equal(control(edit,'plan','b').value,'pending');await preview(edit);assert.equal(writes.length,0);
          set(control(edit,'plan','b'),'','change');await preview(edit);assert.equal(writes.length,1);
          assert.equal(writes[0][1].sides[0].sha256,hashC);assert(!('plan_id' in writes[0][1].sides[1]));
        """)

    def test_late_catalog_drift_does_not_refresh_options_or_open_review_from_the_response(self):
        self.run_js(r"""
          const {edit}=begin(),pending=deferred();let body;
          apiWrite=async(path,value)=>{writes.push([path,value]);body=value;return pending.promise;};
          edit.body.querySelector('form').fire('submit');currentData.lists[0].sha256=hashC;
          pending.resolve({...reply({...body,sides:body.sides.map((side,i)=>i?side:{...side,sha256:hashC})}),
            id:recordId});await settle();assert.equal(sheets.at(-1),edit);assert.equal(control(edit,'list','a').value,'0');
          await preview(edit);assert.equal(writes.length,1);assert.equal(control(edit,'list','a').value,'');
        """)

    def test_bad_dates_names_notes_result_and_mulligans_get_local_feedback(self):
        self.run_js(r"""
          const mutations=[edit=>set(control(edit,'date'),'2026-02-30'),edit=>set(control(edit,'date'),'2026-10-30'),
            edit=>set(control(edit,'name','a'),''),edit=>set(control(edit,'name','b'),'x'.repeat(81)),
            edit=>set(control(edit,'notes'),'x'.repeat(2001)),edit=>set(control(edit,'notes'),'bad\ud800'),
            edit=>set(control(edit,'result'),''),edit=>set(control(edit,'mulligans','a'),''),
            edit=>set(control(edit,'mulligans','b'),'1.5'),edit=>set(control(edit,'mulligans','b'),'21')];
          for(const mutate of mutations){const {edit}=begin();mutate(edit);await preview(edit);assert.equal(writes.length,0);
            assert(edit.body.querySelector('.form-error').textContent);edit.close();}
        """)

    def test_unicode_and_literal_names_are_reviewed_as_text(self):
        self.run_js(r"""
          const {edit}=begin(),name='\ud83c\udf08'.repeat(80),notes='<img src=x onerror=secret>\n\t';
          set(control(edit,'name','a'),name);set(control(edit,'name','b'),'<script>secret</script>');set(control(edit,'notes'),notes);
          const reviewed=await preview(edit);assert.notEqual(reviewed,edit);assert.equal(writes[0][1].sides[0].player,name);
          assert(reviewed.body.textContent.includes('<script>secret</script>'));assert.equal(reviewed.body.querySelectorAll('script').length,0);
          assert.equal(reviewed.body.querySelectorAll('img').length,0);assert.equal(control(edit,'name','a').getAttribute('maxlength'),'160');
        """)

    def test_malformed_preview_fields_do_not_offer_save_or_clear_counter(self):
        self.run_js(r"""
          const mutations=[value=>value.preview=false,value=>value.id='bad',value=>value.review_sha256='bad',
            value=>value.record.mode='pod',value=>value.record.game_version=2,value=>value.record.space='user2',
            value=>value.record.result='b',value=>value.record.notes='Changed',value=>value.record.sides.push(value.record.sides[0]),
            value=>value.record.sides[0].sha256=hashC,value=>value.record.sides[0].sections.Deck[0].qty=98,
            value=>value.record.sides[0].sections.Deck[0].extra='PRIVATE',value=>value.record.sides[0].hidden=true,
            value=>value.record.sides[0].player='Other',value=>value.record.sides[0].mulligans=4,value=>value.error='PRIVATE'];
          for(const mutate of mutations){const {edit}=begin();apiWrite=async(path,body)=>{const value=reply(body);mutate(value);return value;};
            await preview(edit);assert.equal(sheets.at(-1),edit);assert(edit.body.textContent.includes("preview couldn't be checked"));
            assert.equal(buttonText(edit.foot,'Save this record'),undefined);assert.equal(cleanupCalls,0);edit.close();}
        """)

    def test_preview_failure_keeps_draft_and_never_quotes_server_error(self):
        self.run_js(r"""
          const {edit}=begin();set(control(edit,'notes'),'Draft survives');apiWrite=async()=>{throw Error('PRIVATE database detail');};
          await preview(edit);assert.equal(sheets.at(-1),edit);assert.equal(control(edit,'notes').value,'Draft survives');
          assert(!edit.body.textContent.includes('PRIVATE'));assert.equal(cleanupCalls,0);assert.equal(routes.length,0);
        """)

    def test_whole_side_labels_moved_to_other_side_or_outside_form_block_preview(self):
        self.run_js(r"""
          const mutations=[edit=>control(edit,'name','b').closest('fieldset').append(control(edit,'name','a').parentNode),
            edit=>main.append(control(edit,'notes').parentNode),edit=>main.append(control(edit,'date').parentNode),
            edit=>edit.foot.append(control(edit,'result').parentNode)];
          for(const mutate of mutations){const {edit}=begin();mutate(edit);await preview(edit);assert.equal(writes.length,0);edit.close();}
        """)

    def test_original_profile_route_source_data_and_visibility_own_preview(self):
        self.run_js(r"""
          const changes=[ctx=>state.profile={...state.profile},ctx=>routeToken++,ctx=>location.hash='#/play?id=other',
            ctx=>ownerLive=false,ctx=>currentData.lists=[...currentData.lists],ctx=>currentData.decks={...currentData.decks},
            ctx=>{const frame=el('div');main.append(frame);frame.append(ctx.source);},ctx=>ctx.source.hidden=true,
            ctx=>document.visibilityState='hidden',ctx=>ctx.edit.dialog.remove()];
          for(const change of changes){state.profile={id:'matt',name:'Matt',space:'home'};location.hash='#/play';ownerLive=true;document.visibilityState='visible';
            const ctx=begin();change(ctx);await preview(ctx.edit);assert.equal(writes.length,0);ctx.edit.close();}
        """)

    def test_late_preview_draft_or_owner_changes_do_not_open_review(self):
        self.run_js(r"""
          for(const mutate of [ctx=>set(control(ctx.edit,'notes'),'Changed'),ctx=>control(ctx.edit,'notes').value='No event',
              ctx=>state.profile={...state.profile},ctx=>main.append(control(ctx.edit,'notes').parentNode),ctx=>ownerLive=false]){
            state.profile={id:'matt',name:'Matt',space:'home'};ownerLive=true;const ctx=begin(),pending=deferred();let body;
            apiWrite=async(path,value)=>{body=value;return pending.promise;};ctx.edit.body.querySelector('form').fire('submit');
            mutate(ctx);pending.resolve(reply(body));await settle();assert.equal(sheets.at(-1),ctx.edit);ctx.edit.close();}
        """)

    def test_moved_whole_labels_or_hidden_replaced_review_controls_block_save(self):
        self.run_js(r"""
          const changes=[(edit,review)=>control(edit,'name','b').closest('fieldset').append(control(edit,'name','a').parentNode),
            (edit,review)=>main.append(control(edit,'notes').parentNode),(edit,review)=>review.body.hidden=true,
            (edit,review)=>review.foot.hidden=true,(edit,review)=>review.body.replaceChildren(),
            (edit,review)=>{const button=buttonText(review.foot,'Save this record');review.body.append(button);},
            (edit,review)=>review.dialog.remove()];
          for(const mutate of changes){const {edit}=begin(),review=await preview(edit),button=buttonText(review.foot,'Save this record'),before=writes.length;
            mutate(edit,review);button.fire('click');await settle();assert.equal(writes.length,before);assert.equal(cleanupCalls,0);review.close();edit.close();}
        """)

    def test_other_top_dialog_blocks_save_until_original_review_is_top(self):
        self.run_js(r"""
          const {edit}=begin(),review=await preview(edit),other=openSheet('Other action');buttonText(review.foot,'Save this record').click();
          await settle();assert.equal(writes.length,1);other.close();await save(review);assert.equal(writes.length,2);assert.equal(cleanupCalls,1);
        """)

    def test_save_response_must_match_reviewed_content_and_outer_record_identity(self):
        self.run_js(r"""
          const mutations=[value=>value.record.sides[0].title='Changed title',value=>value.record.id='9'.repeat(32),
            value=>value.record.revision=2,value=>value.record.kind='sideboards',value=>value.record.version=2,
            value=>value.record.updated_on='bad',value=>value.sha256='bad',value=>value.saved=false];
          for(const mutate of mutations){const {edit}=begin();apiWrite=async(path,body)=>{writes.push([path,body]);const value=reply(body,body.preview===false);
              if(body.preview===false)mutate(value);return value;};const review=await preview(edit),button=buttonText(review.foot,'Save this record');await save(review);
            assert(review.body.textContent.includes("save response couldn't be checked"));assert(!edit.closed);assert.equal(cleanupCalls,0);
            const before=writes.length;button.fire('click');await settle();assert.equal(writes.length,before);
            review.close();edit.close();}
        """)

    def test_late_save_after_session_profile_or_page_change_does_not_clear_or_navigate(self):
        self.run_js(r"""
          for(const mutate of [()=>ownerLive=false,()=>state.profile={...state.profile},()=>document.visibilityState='hidden',()=>location.hash='#/library']){
            ownerLive=true;state.profile={id:'matt',name:'Matt',space:'home'};document.visibilityState='visible';location.hash='#/play';
            apiWrite=async(path,body)=>{writes.push([path,body]);return reply(body,body.preview===false);};
            const {edit}=begin(),review=await preview(edit),pending=deferred();let body;
            apiWrite=async(path,value)=>{body=value;return pending.promise;};buttonText(review.foot,'Save this record').click();mutate();
            pending.resolve(reply(body,true));await settle();assert.equal(cleanupCalls,0);assert.equal(routes.length,0);assert.equal(messages.length,0);
            review.close();edit.close();}
        """)

    def test_confirmed_save_with_failed_cleanup_is_truthful_and_does_not_route_or_repeat(self):
        self.run_js(r"""
          const {edit}=begin();cleanupResult=false;const review=await preview(edit);await save(review);
          assert.equal(cleanupCalls,1);assert.equal(writes.length,2);assert(edit.closed);assert(review.closed);
          same(messages,['Record saved.']);same(routes,[]);flushTimers();await settle();assert.equal(writes.length,2);
        """)

    def test_scoped_bridge_rejects_wrong_owner_unfinished_or_malformed_packets(self):
        self.run_js(r"""
          const data=makeData(),source=el('button',{text:'Source'});clear(main);main.append(source);
          for(const mutate of [game=>game.profile='user1',game=>game.space='user2',game=>game.v=1,game=>game.ended=null,
              game=>game.players[0].list.sections={Deck:[]},game=>game.players[1].sources.push({source_id:'c2',label:'Injected'})]){
            const game=makeGame(data);mutate(game);assert.equal(lifeSourceReview(data,game,{source,isCurrent:()=>true,onSaved:()=>true}),false);}
          assert.equal(writes.length,0);assert.equal(sheets.length,0);
        """)

    def test_production_v2_counter_hands_off_through_the_same_strict_bridge(self):
        self.run_js(r"""
          const data=makeData();currentData=data;clear(main);drawPlay(data,'');buttonText(main,'Life counter').click();
          const dialog=document.querySelector('.life-source-counter');assert(dialog);assert.equal(writes.length,0);
          const loser=dialog.querySelectorAll('button').find(button=>button.getAttribute('aria-label')==='Opponent: concede'
            ||button.getAttribute('aria-label')==='User1: concede');assert(loser);loser.click();await settle();
          const edit=sheets.at(-1);assert(edit.body.querySelector('.life-source-form'));assert.equal(writes.length,0);
          const review=await preview(edit);assert.equal(writes[0][0],'/api/play/game');await save(review);assert.equal(writes.length,2);
          assert.equal(document.querySelector('.life-source-counter'),null);
        """)

    def test_zero_current_lists_still_offer_v2_resume_and_explicit_replacement_form(self):
        self.run_js(r"""
          const data=makeData();currentData=data;clear(main);drawPlay(data,'');buttonText(main,'Life counter').click();
          assert(document.querySelector('.life-source-counter'));closeLifeCounter();const fresh=makeData({lists:[],decks:{}});
          currentData=fresh;clear(main);drawPlay(fresh,'');assert(buttonText(main,'Resume life counter'));
          buttonText(main,'Resume life counter').click();const dialog=document.querySelector('.life-source-counter');assert(dialog);
          buttonText(dialog,'End game').click();buttonText(dialog,'Draw').click();await settle();const edit=sheets.at(-1);
          assert.equal(control(edit,'list','a').value,'');assert.equal(control(edit,'list','b').value,'');await preview(edit);
          assert.equal(writes.length,0);assert(edit.body.textContent.includes('current replacement lists'));
        """)

    def test_source_damage_disclosures_have_touch_targets_and_closed_content_contract(self):
        css = (WEB / "play.css").read_text(encoding="utf-8")
        self.assertIn(".life-source-counter button { min-width: 44px; min-height: max(44px, var(--tap))", css)
        self.assertIn(".life-source-damage:not([open]) > :not(summary) { display: none; }", css)
        self.assertIn(".life-source-damage > summary { min-height: max(44px, var(--tap))", css)
