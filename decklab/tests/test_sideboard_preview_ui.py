"""Saved sideboard preview over fake API promises and Node DOM; no server, writes or games."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + """
  routeToken=19;location.hash='#/play';
  const calls=[],writes=[],sheets=[];
  const shaA='a'.repeat(64),shaB='b'.repeat(64),shaC='c'.repeat(64),shaD='d'.repeat(64),planId='1'.repeat(32);
  const item=(name,qty,set=null,number=null,finish='nonfoil')=>({name,qty,set,number,finish});
  const entry=()=>({sha256:shaD,editable:true,record:{id:planId,revision:3,updated_by:'Matt',notes:'Use against creatures',
    deck:{id:'casual/test',version:'target',title:'Test Deck',sha256:shaA},
    opponent:{id:'casual/other',version:'owned',title:'Other Deck',sha256:shaB},
    out:[{name:'Alpha',qty:1}],in:[{name:'Bolt',qty:1}],after:{Deck:[item('Alpha',1)]}}});
  const answer=()=>({version:1,plan:{id:planId,sha256:shaD,revision:3},
    base:{id:'casual/test',version:'target',title:'Test Deck',sha256:shaA,
      sections:{Deck:[item('Alpha',2,'fdn','1'),item('Alpha',1,'m21','2','foil'),item('Keep',57)],
        Sideboard:[item('Bolt',1,'fdn','3'),item('Bolt',1,'m21','4','foil')]}},
    post_board:{id:'casual/test',version:'target',title:'Test Deck',sha256:shaC,derived:true,
      sections:{Deck:[item('Alpha',1,'fdn','1'),item('Alpha',1,'m21','2','foil'),item('Keep',57),item('Bolt',1,'fdn','3')],
        Sideboard:[item('Alpha',1,'fdn','1'),item('Bolt',1,'m21','4','foil')]}},
    opponent:{id:'casual/other',version:'owned',title:'Other Deck',sha256:shaB},
    changes:{out:[{name:'Alpha',qty:1}],in:[{name:'Bolt',qty:1}]},
    counts:{main_before:60,main_after:60,sideboard_before:2,sideboard_after:2},
    game_plan:{status:'proposed',cached_work:'not_checked',remaining_games:null,execution:'not_performed',
      modes:[{id:'quick',targets:[200],base_games_max:200,post_board_games_max:200,total_games_max:400},
        {id:'ahead',targets:[400,800,1600,3200],base_games_max:3200,post_board_games_max:3200,total_games_max:6400}],
      basis:'Fresh paired-game upper bounds'}});
  apiWrite=async(...args)=>{writes.push(args);throw Error('Unexpected write');};
  api=async path=>{calls.push(path);return answer();};
  const realOpenSheet=openSheet;
  openSheet=(...args)=>{const sheet=realOpenSheet(...args);sheets.push(sheet);return sheet;};
  const mount=(saved=entry())=>{clear(main);const host=sideboardPreviewAction(saved);if(host)main.append(host);return host;};
  const action=host=>host?.querySelector('button');
  const retry=sheet=>buttonText(sheet.foot,'Try again')||buttonText(sheet.foot,'Refresh preview');
  const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
  const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
  const preview=async(saved=entry())=>{const host=mount(saved);action(host).click();await settle();return sheets.at(-1);};
  const unavailable=sheet=>sheet.body.textContent.includes("This saved plan couldn't be previewed");
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SideboardPreviewUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_explicit_action_reads_once_and_shows_exact_section_printings_and_game_guide(self):
        self.run_js("""
          const host=mount();assert.equal(calls.length,0);action(host).click();await settle();const sheet=sheets[0];
          same(calls,[`/api/play/sideboard-preview?id=${planId}&sha256=${shaD}`]);
          assert(sheet.body.textContent.includes('saved plan revision 3'));
          assert(sheet.body.textContent.includes('Main list: 60 before, 60 after'));
          assert(sheet.body.textContent.includes('Sideboard: 2 before, 2 after'));
          assert(sheet.body.textContent.includes('FDN 1; nonfoil'));
          assert(sheet.body.textContent.includes('M21 4; foil'));
          assert(sheet.body.textContent.includes('Complete post-board list'));
          assert(sheet.body.textContent.includes('400 total'));assert(sheet.body.textContent.includes('6,400 games total'));
          assert(sheet.body.textContent.includes('remaining games are unknown'));
          assert(sheet.body.textContent.includes('No test was started and no verdict is available'));
          same(sheet.foot.querySelectorAll('button').map(node=>node.textContent),['Done','Refresh preview']);
          assert.equal(document.activeElement,buttonText(sheet.foot,'Done'));assert.equal(writes.length,0);
          assert(!sheet.body.textContent.includes(shaA));assert(!sheet.body.textContent.includes(shaC));
          assert.equal(sheet.body.querySelectorAll('a').length,0);
        """)

    def test_game_log_and_deck_plan_hooks_keep_existing_revision_controls(self):
        self.run_js("""
          const saved=entry(),data={lists:[saved.record.deck,saved.record.opponent]};
          const game=playPlanCard(saved,data);main.append(game);
          assert(buttonText(game,'Revise this plan'));assert(buttonText(game,'Preview post-board list'));
          const deck=deckSideboardPlan(saved,true);main.append(deck);assert(buttonText(deck,'Preview post-board list'));
          assert.equal(calls.length,0);assert.equal(writes.length,0);
        """)

    def test_hidden_removed_or_unsigned_plan_has_no_preview_request_or_hidden_name(self):
        self.run_js("""
          for(const key of ['hidden','removed']){const saved=entry();saved.record.opponent={title:'PRIVATE DECK', [key]:true};
            const host=mount(saved);assert.equal(action(host),null);assert(host.textContent.includes('unavailable'));
            assert(!host.textContent.includes('PRIVATE DECK'));}
          const saved=entry();saved.sha256='bad';assert.equal(mount(saved),null);
          state.profile=null;assert.equal(mount(),null);assert.equal(calls.length,0);
        """)

    def test_errors_are_generic_without_raw_failure_body_then_retry_same_owner(self):
        self.run_js("""
          api=async path=>{calls.push(path);if(calls.length===1)throw Error('PRIVATE OPPONENT password=secret');return answer();};
          const sheet=await preview();assert(unavailable(sheet));assert(!sheet.body.textContent.includes('PRIVATE'));
          const control=retry(sheet);control.focus();control.click();await settle();
          assert(!unavailable(sheet));assert.equal(calls.length,2);assert.equal(document.activeElement,control);
          assert.equal(writes.length,0);
        """)

    def test_server_error_object_is_not_rendered_as_partial_success(self):
        self.run_js("""
          api=async()=>({...answer(),error:'PRIVATE RECORD',detail:'PRIVATE PATH'});
          const sheet=await preview();assert(unavailable(sheet));assert(!sheet.body.textContent.includes('PRIVATE'));
          assert(!sheet.body.textContent.includes('Main list:'));
        """)

    def test_display_projection_excludes_opponent_sections_notes_inventory_and_raw_game_basis(self):
        self.run_js("""
          const value=answer();value.opponent.sections={Deck:[item('PRIVATE OPPONENT CARD',5)]};
          value.base.notes=value.post_board.kit='PRIVATE KIT';value.game_plan.basis='PRIVATE CONFIG';
          value.raw='PRIVATE RECORD';value.post_board.sections.Deck[0].card={oracle_text:'PRIVATE ORACLE'};
          api=async()=>value;const sheet=await preview();assert(!unavailable(sheet));
          assert(!sheet.body.textContent.includes('PRIVATE'));assert.equal(writes.length,0);
          value.post_board.sections.Deck[0].name='MUTATED AFTER RESPONSE';assert(!sheet.body.textContent.includes('MUTATED'));
        """)

    def test_invalid_identity_hash_or_derived_flag_rejects_whole_answer(self):
        self.run_js("""
          const mutations=[a=>a.plan.id='2'.repeat(32),a=>a.plan.sha256=shaA,a=>a.base.sha256=shaB,
            a=>a.opponent.id='casual/private',a=>a.opponent.version='target',a=>a.opponent.sha256=shaA,
            a=>a.post_board.derived=false,a=>a.post_board.sha256='bad',a=>a.base.title='x'.repeat(501),
            a=>a.post_board.title='Different',a=>a.version=2,a=>a.plan.revision=1000000000,
            a=>a.base.title='bad\\ud800'];
          for(const mutate of mutations){const value=answer();mutate(value);api=async()=>value;const sheet=await preview();
            assert(unavailable(sheet));sheet.close();}
        """)

    def test_malformed_sections_rows_counts_and_conservation_reject_whole_answer(self):
        self.run_js("""
          const mutations=[a=>a.base.sections.Deck=null,a=>a.base.sections.Deck=[],a=>delete a.base.sections.Deck,
            a=>a.base.sections.Considering=[],a=>a.base.sections.Deck[0].qty=1.5,a=>a.base.sections.Deck[0].qty=1000,
            a=>a.base.sections.Deck[0].finish='blank',a=>a.base.sections.Deck[0].name='x'.repeat(301),
            a=>a.base.sections.Deck[0].number='x'.repeat(81),a=>a.counts.main_after=59,
            a=>a.post_board.sections.Sideboard[0].qty=2,
            a=>{a.base.sections.Commander=[item('Commander',1)];a.post_board.sections.Commander=[item('Other',1)];},
            a=>a.base.sections.Deck=Array.from({length:501},()=>item('Huge',1))];
          for(const mutate of mutations){const value=answer();mutate(value);api=async()=>value;const sheet=await preview();
            assert(unavailable(sheet));assert(!sheet.body.textContent.includes('Main list:'));sheet.close();}
        """)

    def test_malformed_or_zero_moves_cannot_appear_as_valid_plan(self):
        self.run_js("""
          const mutations=[a=>a.changes={out:[],in:[]},a=>a.changes.in=[{name:'Alpha',qty:1}],
            a=>a.changes.in=[{name:'Bolt',qty:2}],a=>a.changes.out=[{name:'Other',qty:1}],
            a=>a.changes.in=[{name:'Bolt',qty:0}],a=>a.changes.in=[{name:'Bolt',qty:100}],
            a=>a.changes.in=[{name:'Bolt',qty:1},{name:'Bolt',qty:1}],
            a=>a.changes.in=Array.from({length:101},(_,i)=>({name:'Card'+i,qty:1}))];
          for(const mutate of mutations){const value=answer();mutate(value);api=async()=>value;const sheet=await preview();
            assert(unavailable(sheet));sheet.close();}
        """)

    def test_malformed_game_plan_never_claims_cached_remaining_work_or_readiness(self):
        self.run_js("""
          const mutations=[a=>a.game_plan.remaining_games=0,a=>a.game_plan.execution='ready',
            a=>a.game_plan.cached_work='checked',a=>a.game_plan.modes[0].total_games_max=1,
            a=>a.game_plan.modes[1].targets.push(9999),a=>a.game_plan.modes.reverse()];
          for(const mutate of mutations){const value=answer();mutate(value);api=async()=>value;const sheet=await preview();
            assert(unavailable(sheet));assert(!sheet.body.textContent.includes('Proposed paired-game guide'));sheet.close();}
        """)

    def test_unavailable_format_guide_preserves_lists_and_suppresses_numeric_work(self):
        self.run_js("""
          for(const reason of ['format_mismatch','format_unknown']){const value=answer();
            value.game_plan={status:'unavailable',reason,modes:[],cached_work:'not_checked',remaining_games:null,execution:'not_performed'};
            api=async()=>value;const sheet=await preview();assert(!unavailable(sheet));
            assert(sheet.body.textContent.includes('Complete post-board list'));
            assert(sheet.body.textContent.includes('Paired-game guide unavailable'));
            assert(sheet.body.textContent.includes('No paired-game count is proposed'));
            assert(!sheet.body.textContent.includes('400 total'));assert(!sheet.body.textContent.includes('6,400'));
            sheet.close();}
          const value=answer();value.game_plan.status='unavailable';value.game_plan.reason='PRIVATE REASON';
          api=async()=>value;const sheet=await preview();assert(unavailable(sheet));assert(!sheet.body.textContent.includes('PRIVATE'));
        """)

    def test_legacy_empty_printing_fields_remain_unspecified_instead_of_breaking_preview(self):
        self.run_js("""
          const value=answer();for(const key of ['base','post_board'])for(const row of value[key].sections.Deck)
            if(row.name==='Keep')row.set=row.number='';
          api=async()=>value;const sheet=await preview();assert(!unavailable(sheet));assert(sheet.body.textContent.includes('Any printing; nonfoil'));
        """)

    def test_late_answer_after_profile_object_or_id_change_is_ignored(self):
        self.run_js("""
          for(const replace of [()=>state.profile={...state.profile},()=>state.profile.id='user2']){
            state.profile={id:'matt',name:'Matt'};const waiting=deferred();api=()=>waiting.promise;
            const host=mount();action(host).click();const sheet=sheets.at(-1);replace();waiting.resolve(answer());await settle();
            assert(sheet.body.textContent.includes('Loading'));assert(!sheet.body.textContent.includes('Main list:'));
            retry(sheet).click();assert.equal(calls.length,0);sheet.close();}
        """)

    def test_late_answer_after_navigation_or_original_action_detachment_is_ignored(self):
        self.run_js("""
          for(const change of [()=>routeToken++,()=>location.hash='#/library',host=>host.remove(),
            host=>{const replacement=el('main',{id:'main'});main.replaceWith(replacement);document.body.append(main);}]){
            routeToken=19;location.hash='#/play';const waiting=deferred();api=()=>waiting.promise;
            const host=mount();action(host).click();const sheet=sheets.at(-1);change(host);waiting.resolve(answer());await settle();
            assert(sheet.body.textContent.includes('Loading'));sheet.close();
            const other=document.querySelector('#main');if(other!==main)other.remove();if(!main.isConnected)document.body.append(main);}
        """)

    def test_late_answer_after_entry_record_or_sha_changes_is_ignored(self):
        self.run_js("""
          for(const change of [saved=>saved.sha256=shaA,saved=>saved.record={...saved.record},
            saved=>saved.record.opponent.sha256=shaA,saved=>saved.record.opponent.hidden=true]){
            const saved=entry(),waiting=deferred();api=()=>waiting.promise;const host=mount(saved);action(host).click();
            const sheet=sheets.at(-1);change(saved);waiting.resolve(answer());await settle();assert(sheet.body.textContent.includes('Loading'));sheet.close();}
        """)

    def test_original_action_frame_move_invalidates_pending_preview(self):
        self.run_js("""
          const waiting=deferred();api=()=>waiting.promise;clear(main);const saved=entry();
          const frame=el('article'),host=sideboardPreviewAction(saved);frame.append(host);main.append(frame);
          action(host).click();const sheet=sheets.at(-1),other=el('article');main.append(other);other.append(host);
          waiting.resolve(answer());await settle();assert(sheet.body.textContent.includes('Loading'));
          retry(sheet).click();assert(sheet.body.textContent.includes('Loading'));
        """)

    def test_closed_sheet_cannot_update_reopened_preview_or_reuse_old_footer(self):
        self.run_js("""
          const pending=[];api=()=>{const value=deferred();pending.push(value);return value.promise;};
          const host=mount();action(host).click();const old=sheets[0],oldRetry=retry(old);old.close();
          action(host).click();const current=sheets[1];pending[0].resolve(answer());await settle();
          assert(current.body.textContent.includes('Loading'));assert(old.body.textContent.includes('Loading'));
          oldRetry.click();assert.equal(pending.length,2);pending[1].resolve(answer());await settle();assert(!unavailable(current));
          assert(current.body.textContent.includes('Main list:'));
        """)

    def test_replaced_or_moved_sheet_footer_control_invalidates_late_read_and_retry(self):
        self.run_js("""
          for(const change of [sheet=>retry(sheet).remove(),sheet=>sheet.foot.replaceChildren(el('button',{text:'Replacement'})),
            sheet=>sheet.body.remove(),sheet=>{const wrapper=el('div');document.body.append(wrapper);wrapper.append(sheet.dialog);}]){
            const waiting=deferred();let reads=0;api=()=>{reads++;return waiting.promise;};const host=mount();action(host).click();
            const sheet=sheets.at(-1),control=retry(sheet);change(sheet);waiting.resolve(answer());await settle();
            assert(!sheet.body.textContent.includes('Main list:'));control.click();assert.equal(reads,1);sheet.close();}
        """)

    def test_retry_coalesces_pending_and_old_rows_cannot_expand_after_refresh(self):
        self.run_js("""
          const value=answer();for(let i=0;i<30;i++){value.base.sections.Deck.push(item('Extra'+i,1));value.post_board.sections.Deck.push(item('Extra'+i,1));}
          value.counts.main_before=value.counts.main_after=90;api=async path=>{calls.push(path);return value;};
          const sheet=await preview();const more=buttonText(sheet.body,'Show more rows');assert(more);more.focus();
          more.click();assert.equal(document.activeElement,more);assert.equal(more.textContent,'All rows shown');
          const waiting=deferred();api=path=>{calls.push(path);return waiting.promise;};const control=retry(sheet);control.click();control.click();
          assert.equal(calls.length,2);more.click();assert(sheet.body.textContent.includes('Loading'));
          waiting.resolve(answer());await settle();assert(sheet.body.textContent.includes('Main list: 60'));
        """)

    def test_other_dialog_blocks_page_action_and_retry_behind_it(self):
        self.run_js("""
          const host=mount(),overlay=openSheet('Other');action(host).click();assert.equal(calls.length,0);overlay.close();
          action(host).click();await settle();const sheet=sheets.at(-1),other=openSheet('Other again');retry(sheet).click();
          assert.equal(calls.length,1);buttonText(sheet.foot,'Done').click();assert(!sheet.closed);other.close();
          buttonText(sheet.foot,'Done').click();assert(sheet.closed);
        """)

    def test_deck_page_replaced_same_route_or_view_rejects_pending_answer(self):
        self.run_js("""
          for(const change of [()=>deckScreen={...deckScreen},()=>deckScreen.data={...deckScreen.data},()=>deckScreen.view={...deckScreen.view}]){
            location.hash=deckHref('casual/test');deckScreen={data:makePage(),view:{tab:'overview'}};
            const waiting=deferred();api=()=>waiting.promise;const host=mount();action(host).click();const sheet=sheets.at(-1);
            change();waiting.resolve(answer());await settle();assert(sheet.body.textContent.includes('Loading'));sheet.close();}
        """)

    def test_text_values_use_text_nodes_without_creating_html(self):
        self.run_js("""
          const value=answer();value.base.title=value.post_board.title='<img onerror=bad>';value.opponent.title='<svg onload=bad>';
          api=async()=>value;const sheet=await preview();assert(!unavailable(sheet));
          assert(sheet.body.textContent.includes('<img onerror=bad>'));assert.equal(sheet.body.querySelectorAll('img').length,0);
          assert.equal(sheet.body.querySelectorAll('svg').length,0);
        """)
