"""Pod forms over the real script order and disposable DOM; no server or real records.

Run with python scripts/test_fixtures.py decklab.tests.test_play_pods_ui.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  routeToken=43;location.hash='#/play';state.profile.space='home';
  const writes=[],sheets=[],routes=[],messages=[];
  const shaA='a'.repeat(64),shaB='b'.repeat(64),shaR='c'.repeat(64),reviewSha='d'.repeat(64),podId='1'.repeat(32);
  const snapshot=(extra={})=>({id:'commander/test',version:'target',sha256:shaA,title:'Commander deck',
    sections:{Commander:[{qty:1,name:'Leader',set:null,number:null,finish:'nonfoil'}],
      Deck:[{qty:99,name:'Forest',set:null,number:null,finish:'nonfoil'}]},can_record:true,...extra});
  const recordedSnapshot=(extra={})=>{const value=snapshot(extra);delete value.can_record;return value;};
  const makePod=(extra={})=>({mode:'pod',game_version:2,space:'home',date:'2026-10-28',result:'s1',notes:'A note',
    seats:[{seat_id:'s1',type:'deck',player:'Matt',deck:recordedSnapshot()},
      {seat_id:'s2',type:'external',player:'Opponent 1',commander:'Leader B'},
      {seat_id:'s3',type:'external',player:'Opponent 2',commander:''}],...extra});
  const entry=(extra={})=>({record:{version:1,kind:'games',id:podId,revision:2,...makePod()},sha256:shaR,can:{edit:true},...extra});
  const packet=(extra={})=>({today:'2026-10-28',pod_lists:[snapshot()],pods:[],games:[],sideboards:[],lists:[],decks:{},warnings:[],...extra});
  const response=(body,saved=false)=>({...(saved?{saved:true,sha256:shaR}:{preview:true,id:body.id||podId,review_sha256:reviewSha}),
    record:{...(saved?{version:1,kind:'games',id:body.id,revision:3}:{}),space:'home',
      mode:'pod',game_version:2,date:body.date,result:body.result,notes:podTrim(body.notes),
      seats:body.seats.map(seat=>seat.type==='external'?{...seat,player:podTrim(seat.player),commander:podTrim(seat.commander)}
        :{...seat,player:podTrim(seat.player),deck:recordedSnapshot({id:seat.deck.id,version:seat.deck.version,sha256:seat.deck.sha256})})}});
  apiWrite=async(path,body)=>{writes.push([path,structuredClone(body)]);return response(body,body.preview===false);};
  route=()=>routes.push(location.hash);toast=message=>messages.push(message);
  const realSheet=openSheet;openSheet=(...args)=>{const sheet=realSheet(...args);sheets.push(sheet);return sheet;};
  const mount=(data=packet())=>{clear(main);const section=playPodSection(data);main.append(section);return section;};
  const launch=(data=packet())=>{const section=mount(data);buttonText(section,'Record a pod game').click();return sheets.at(-1);};
  const controls=sheet=>({count:sheet.body.querySelector('#pod-count'),result:sheet.body.querySelector('#pod-result'),
    date:sheet.body.querySelector('#pod-date'),notes:sheet.body.querySelector('#pod-notes')});
  const set=(node,value,event='input')=>{node.value=value;node.fire(event);};
  const seat=(sheet,id,key)=>sheet.body.querySelector(`[data-pod-${key}=${id}]`);
  const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
  const review=async(sheet)=>{set(controls(sheet).result,'s1','change');buttonText(sheet.foot,'Review pod game').click();await settle();return sheets.at(-1);};
  const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PodUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_real_page_loads_new_script_after_play_and_renders_separate_pod_section(self):
        self.run_js("""
          const saved=entry();drawPlay(packet({pods:[saved]}),'');
          assert(main.textContent.includes('Commander pods'));assert(main.textContent.includes('Played 1v1 games'));
          assert(main.textContent.includes('No 1v1 games have been recorded here yet.'));
          assert(main.textContent.includes('1 pod game recorded.'));assert(!main.textContent.includes('Head to headGames'));
          assert(buttonText(main,'Record a pod game'));assert.equal(writes.length,0);
        """)

    def test_new_pod_requires_explicit_preview_and_one_explicit_save(self):
        self.run_js("""
          const edit=launch();assert.equal(writes.length,0);const preview=await review(edit);
          assert.notEqual(preview,edit);assert.equal(writes.length,1);assert.equal(writes[0][0],'/api/play/pod');
          const body=writes[0][1];assert.equal(body.mode,'pod');assert.equal(body.game_version,2);
          assert.equal(body.seats.length,3);assert.equal(body.profile,'matt');assert.equal(body.id,null);
          same(body.seats[0].deck,{id:'commander/test',version:'target',sha256:shaA});
          assert(!('sections' in body.seats[0].deck));assert.equal(body.seats[1].type,'external');
          flushTimers();document.fire('visibilitychange');await settle();assert.equal(writes.length,1);
          const save=buttonText(preview.foot,'Save pod game');save.click();save.click();await settle();
          assert.equal(writes.length,2);assert.equal(writes[1][1].preview,false);
          assert.equal(writes[1][1].id,podId);assert.equal(writes[1][1].review_sha256,reviewSha);
          assert(edit.closed);assert(preview.closed);same(routes,['#/play']);same(messages,['Pod game saved.']);
        """)

    def test_fourth_seat_and_inactive_external_values_survive_toggling(self):
        self.run_js("""
          const edit=launch();set(controls(edit).count,'4','change');assert.equal(edit.body.querySelectorAll('fieldset').length,4);
          set(seat(edit,'s4','player'),'Fourth label');set(seat(edit,'s4','commander'),'Fourth leader');
          set(controls(edit).result,'s4','change');set(controls(edit).count,'3','change');assert.equal(controls(edit).result.value,'');
          set(controls(edit).count,'4','change');assert.equal(seat(edit,'s4','player').value,'Fourth label');
          assert.equal(seat(edit,'s4','commander').value,'Fourth leader');
          set(seat(edit,'s2','commander'),'Kept external leader');set(seat(edit,'s2','type'),'deck','change');
          set(seat(edit,'s2','type'),'external','change');assert.equal(seat(edit,'s2','commander').value,'Kept external leader');
          await review(edit);assert.equal(writes[0][1].seats.length,4);assert.equal(writes[0][1].seats[3].player,'Fourth label');
        """)

    def test_back_to_editing_retains_typed_fields_and_server_preview_identity(self):
        self.run_js("""
          const edit=launch();set(seat(edit,'s2','commander'),'Typed commander');set(controls(edit).notes,'Private note');
          const preview=await review(edit);buttonText(preview.foot,'Back to editing').click();
          assert(!edit.closed);assert.equal(seat(edit,'s2','commander').value,'Typed commander');
          assert.equal(controls(edit).notes.value,'Private note');assert.equal(writes.length,1);
          await review(edit);assert.equal(writes[1][1].id,podId);assert.equal(writes[1][1].notes,'Private note');
        """)

    def test_current_deck_replacement_is_explicit_and_historical_sha_is_preserved(self):
        self.run_js("""
          const saved=entry(),data=packet({pods:[saved],pod_lists:[snapshot({sha256:shaB})]});
          const section=mount(data);buttonText(section,'Correct this pod game').click();const edit=sheets.at(-1);
          const list=seat(edit,'s1','list');assert(list.textContent.includes('recorded historical list'));
          assert.equal(list.value,'0');let preview=await review(edit);assert.equal(writes[0][1].sha256,shaR);
          assert.equal(writes[0][1].seats[0].deck.sha256,shaA);buttonText(preview.foot,'Back to editing').click();
          set(list,'1','change');preview=await review(edit);assert.equal(writes[1][1].seats[0].deck.sha256,shaB);
        """)

    def test_launcher_and_correction_require_explicit_positive_server_rights(self):
        self.run_js("""
          for(const can_record of [false,undefined,1,'true']){const section=mount(packet({pod_lists:[snapshot({can_record})]}));
            assert.equal(buttonText(section,'Record a pod game'),undefined);}
          for(const can of [undefined,{}, {edit:false},{edit:1},{edit:'true'}]){
            const section=mount(packet({pods:[entry({can})],pod_lists:[]}));assert.equal(buttonText(section,'Correct this pod game'),undefined);}
          state.profile=null;assert.equal(buttonText(mount(),'Record a pod game'),undefined);assert.equal(writes.length,0);
        """)

    def test_external_labels_and_notes_are_literal_text_and_public_generic_seats_render(self):
        self.run_js("""
          const record=makePod();record.seats[1].player='<img src=x onerror=secret>';record.seats[1].commander='<script>secret</script>';
          record.notes='<svg onload=secret>';let section=mount(packet({pods:[entry({record})]}));
          assert(section.textContent.includes('<img src=x onerror=secret>'));assert.equal(section.querySelectorAll('img').length,0);
          assert.equal(section.querySelectorAll('script').length,0);assert.equal(section.querySelectorAll('svg').length,0);
          delete record.space;delete record.notes;for(const value of record.seats){delete value.player;delete value.commander;}
          record.seats[0].deck={hidden:true,title:'A private deck'};
          section=mount(packet({pods:[entry({record,can:{edit:false}})],pod_lists:[]}));
          assert(section.textContent.includes('Player 1 won'));assert(section.textContent.includes('External opponent'));
          assert.equal(buttonText(section,'Correct this pod game'),undefined);assert.equal(writes.length,0);
        """)

    def test_strict_legacy_consumers_ignore_pods_and_malformed_marker_records(self):
        self.run_js("""
          const a=snapshot(),b=snapshot({id:'commander/other',sha256:shaB});
          const base={sides:[{...a,player:'Matt'}, {...b,player:'Other'}],result:'a',date:'2026-10-28'};
          const invalid=[makePod(),{...base,mode:'pod',game_version:2},{...base,mode:'other'},
            {...base,game_version:2},{...base,sides:[...base.sides,a]}];
          assert.equal(playMatchupSummaries(invalid.map(record=>({record}))).length,0);
          assert.equal(playSummarySection(invalid.map(record=>({record}))),null);
          assert.equal(playLastList([a,b],invalid.map(record=>({record})),'Matt'),-1);
          assert.equal(playResult(makePod()),'Result unavailable');
          const left={summary:{id:a.id},version:'target'},right={summary:{id:b.id},version:'target'};
          const node=compareGameParts({games:invalid.map(record=>({record}))},left,right,['A','B']);
          assert(node.textContent.includes('No games between these two lists'));
          const groups=playMatchupSummaries([{record:base},...invalid.map(record=>({record}))]);assert.equal(groups[0].games,1);
        """)

    def test_review_failure_preserves_draft_and_shows_no_raw_error(self):
        self.run_js("""
          apiWrite=async(path,body)=>{writes.push([path,body]);throw Error('PRIVATE configured database');};
          const edit=launch();set(seat(edit,'s2','player'),'Kept name');set(controls(edit).notes,'Kept notes');
          await review(edit);assert.equal(sheets.length,1);assert(!edit.closed);assert(edit.body.textContent.includes('draft is still here'));
          assert(!edit.body.textContent.includes('PRIVATE'));assert.equal(seat(edit,'s2','player').value,'Kept name');
          assert.equal(controls(edit).notes.value,'Kept notes');assert.equal(routes.length,0);
        """)

    def test_local_invalid_fields_get_actionable_feedback_without_a_request(self):
        self.run_js("""
          const cases=[edit=>{},edit=>set(controls(edit).date,'2026-02-30'),
            edit=>set(controls(edit).date,'2026-10-29'),edit=>set(seat(edit,'s2','player'),''),
            edit=>set(seat(edit,'s2','player'),'x'.repeat(81)),edit=>set(seat(edit,'s2','player'),'bad\\nline'),
            edit=>set(seat(edit,'s2','commander'),'x'.repeat(301)),edit=>set(controls(edit).notes,'x'.repeat(2001)),
            edit=>set(controls(edit).notes,'bad\\ud800'),edit=>set(seat(edit,'s1','type'),'external','change')];
          for(const [i,mutate] of cases.entries()){const edit=launch();if(i)set(controls(edit).result,'s1','change');
            mutate(edit);buttonText(edit.foot,'Review pod game').click();await settle();assert.equal(writes.length,0);
            const words=edit.body.querySelector('.form-error').textContent;assert(words.length>0);assert(!words.includes("couldn't be reviewed"));edit.close();}
        """)

    def test_unicode_limits_count_code_points_and_keep_allowed_multiline_notes(self):
        self.run_js("""
          const edit=launch(),name='\\ud83c\\udf08'.repeat(80),commander='\\ud83c\\udf08'.repeat(300),notes='\\ud83c\\udf08'.repeat(1998)+'\\n\\t';
          set(seat(edit,'s2','player'),name);set(seat(edit,'s2','commander'),commander);set(controls(edit).notes,notes);
          assert.equal(seat(edit,'s2','player').getAttribute('maxlength'),'160');
          assert.equal(seat(edit,'s2','commander').getAttribute('maxlength'),'600');
          const preview=await review(edit);assert.notEqual(preview,edit);assert.equal(writes.length,1);
          assert.equal(writes[0][1].seats[1].player,name);assert.equal(writes[0][1].seats[1].commander,commander);
          assert.equal(writes[0][1].notes,notes);assert(podText(name,80));assert(!podText(name+'x',80));
        """)

    def test_save_conflict_keeps_review_and_edit_draft_for_explicit_recovery(self):
        self.run_js("""
          const edit=launch();set(controls(edit).notes,'Preserve me');const preview=await review(edit);
          apiWrite=async(path,body)=>{writes.push([path,body]);const e=Error('PRIVATE conflict');e.status=409;throw e;};
          buttonText(preview.foot,'Save pod game').click();await settle();assert(!preview.closed);assert(!edit.closed);
          assert(preview.body.textContent.includes('draft is still here'));assert(!preview.body.textContent.includes('PRIVATE'));
          buttonText(preview.foot,'Back to editing').click();assert.equal(controls(edit).notes.value,'Preserve me');
          assert.equal(writes.length,2);assert.equal(routes.length,0);assert.equal(messages.length,0);
        """)

    def test_malformed_preview_has_no_save_action(self):
        self.run_js("""
          const mutations=[a=>a.preview=false,a=>a.id='bad',a=>a.review_sha256='bad',a=>a.record.game_version=1,
            a=>a.record.result='s4',a=>a.record.notes='Other',a=>a.record.seats[0].deck.sha256=shaB,
            a=>a.record.seats[0].deck.sections.Deck=null,a=>a.record.seats[0].deck.sections.Deck[0].qty=0,
            a=>a.record.seats[1].deck=snapshot(),a=>a.record.seats[1].player='Different',a=>a.error='PRIVATE',
            a=>a.record.space='user2',a=>a.record.date='2026-02-30',a=>a.record.sides=[],
            a=>a.record.seats[1].commander={},a=>a.record.seats[1].player='bad\\ud800',
            a=>a.record.seats[1].extra='PRIVATE',a=>a.record.seats[0].deck.sections.Deck=[],
            a=>a.record.seats[0].deck.hidden=true,a=>a.record.seats[0].deck.removed=true,
            a=>a.record.seats[0].deck.notes='PRIVATE'];
          for(const mutate of mutations){apiWrite=async(path,body)=>{const value=response(body);mutate(value);return value;};
            const edit=launch();await review(edit);assert.equal(sheets.at(-1),edit);assert(edit.body.textContent.includes("couldn't be checked"));
            assert.equal(buttonText(edit.foot,'Save pod game'),undefined);edit.close();}
        """)

    def test_late_preview_cannot_open_after_same_id_profile_object_replacement(self):
        self.run_js("""
          const pending=deferred();apiWrite=async(path,body)=>{writes.push([path,body]);return pending.promise;};
          const edit=launch();await review(edit);state.profile={...state.profile};
          pending.resolve(response(writes[0][1]));await settle();assert.equal(sheets.length,1);assert.equal(routes.length,0);
        """)

    def test_late_preview_cannot_open_after_route_hash_or_token_changes(self):
        self.run_js("""
          for(const change of [()=>location.hash='#/play?id=other',()=>routeToken++]){
            location.hash='#/play';const pending=deferred();apiWrite=async(path,body)=>{writes.push([path,body]);return pending.promise;};
            const edit=launch();await review(edit);change();pending.resolve(response(writes.at(-1)[1]));await settle();
            assert.equal(sheets.at(-1),edit);edit.close();}
          assert.equal(routes.length,0);
        """)

    def test_late_preview_cannot_open_after_changed_draft_or_detached_control(self):
        self.run_js("""
          for(const change of [edit=>set(controls(edit).notes,'Changed'),edit=>controls(edit).notes.value='No event',
              edit=>seat(edit,'s2','commander').remove(),edit=>edit.foot.replaceChildren(),edit=>edit.body.replaceChildren()]){
            const pending=deferred();apiWrite=async(path,body)=>{writes.push([path,body]);return pending.promise;};
            const edit=launch();await review(edit);change(edit);pending.resolve(response(writes.at(-1)[1]));await settle();
            assert.equal(sheets.at(-1),edit);edit.close();}
        """)

    def test_save_refuses_replaced_record_data_source_frame_or_footer_control(self):
        self.run_js("""
          const changes=[(edit,preview,data,saved)=>data.pods=[],(edit,preview,data,saved)=>saved.sha256=shaB,
            (edit,preview,data,saved)=>saved.record={...saved.record},(edit,preview,data,saved)=>saved.record.notes='Changed',
            (edit,preview)=>preview.body.replaceChildren(),(edit,preview)=>preview.foot.replaceChildren(el('button',{text:'Save pod game'})),
            (edit,preview)=>{const save=buttonText(preview.foot,'Save pod game');save.remove();preview.body.append(save);},
            (edit,preview)=>{const host=el('div');main.append(host);host.append(main.querySelector('.play-pod-record'));}];
          for(const mutate of changes){const saved=entry(),data=packet({pods:[saved]});const section=mount(data);
            buttonText(section,'Correct this pod game').click();const edit=sheets.at(-1),preview=await review(edit);
            const save=buttonText(preview.foot,'Save pod game'),before=writes.length;
            mutate(edit,preview,data,saved);save.click();await settle();assert.equal(writes.length,before);preview.close();edit.close();}
        """)

    def test_other_top_sheet_blocks_save_and_late_preview(self):
        self.run_js("""
          const edit=launch(),preview=await review(edit),other=openSheet('Another action');
          buttonText(preview.foot,'Save pod game').click();await settle();assert.equal(writes.length,1);other.close();
          buttonText(preview.foot,'Save pod game').click();await settle();assert.equal(writes.length,2);
        """)

    def test_late_save_reply_cannot_navigate_or_focus_replacement_page(self):
        self.run_js("""
          const edit=launch(),preview=await review(edit),pending=deferred();let body;
          apiWrite=async(path,value)=>{writes.push([path,value]);body=value;return pending.promise;};
          buttonText(preview.foot,'Save pod game').click();state.profile={...state.profile};clear(main);
          const replacement=el('button',{text:'New page'});main.append(replacement);replacement.focus();
          pending.resolve(response(body,true));await settle();assert.equal(document.activeElement,replacement);
          assert.equal(routes.length,0);assert.equal(messages.length,0);assert(!edit.closed);assert(!preview.closed);
        """)

    def test_invalid_save_reply_does_not_claim_success_or_retry_automatically(self):
        self.run_js("""
          const edit=launch(),preview=await review(edit);apiWrite=async(path,body)=>{writes.push([path,body]);return{saved:true,record:makePod(),sha256:shaR};};
          buttonText(preview.foot,'Save pod game').click();await settle();assert.equal(writes.length,2);
          assert(preview.body.textContent.includes("save response couldn't be checked"));assert(!edit.closed);
          flushTimers();document.fire('visibilitychange');await settle();assert.equal(writes.length,2);
          assert.equal(routes.length,0);assert.equal(messages.length,0);
        """)

    def test_utf8_label_helpers_and_incomplete_schema_fail_closed(self):
        self.run_js("""
          for(const value of ['bad\\nline','bad\\u0000line','bad\\ud800','bad\\udfff'])assert.equal(podText(value,80),false);
          assert(podText('Leader \\ud83c\\udf08',80));assert(!podText('',80));assert(podText('',80,true));
          assert.equal(podTrim('\\u0085 Label \\u0085'),'Label');assert.equal(podTrim('\\ufeffLabel'),'\\ufeffLabel');
          for(const record of [makePod({game_version:'2'}),makePod({mode:undefined}),makePod({seats:[]}),
              makePod({result:'s4'}),makePod({seats:[{seat_id:'s1'},{seat_id:'s1'},{seat_id:'s3'}]})])assert(!podShownRecord(record));
        """)
