"""Pod counter/form handoff through actual scripts, fake storage and API promises.

Run: python scripts/test_fixtures.py decklab.tests.test_pod_life_bridge_ui
No real browser, storage, server, collection, database or Forge is used.
"""
import json
import subprocess
import unittest

from decklab.tests.test_play_pods_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

BRIDGE = r"""
  const store=new Map();window.localStorage={getItem:key=>store.has(key)?store.get(key):null,
    setItem:(key,value)=>store.set(key,String(value)),removeItem:key=>store.delete(key)};
  structuredClone=value=>JSON.parse(JSON.stringify(value)); // same-realm browser clone in the VM fixture
  editor=null; // the Game log has no live editor draft
  Date.now=()=>Date.parse('2026-10-29T01:00:00Z');document.visibilityState='visible';document.hidden=false;
  const counter=()=>document.querySelector('.pod-life-counter');
  const kept=data=>podLifeSaved(data);
  const localPacketKey=packet=>STORE+podLifeKey(state.profile,packet.session_id);
  const startCounter=async(data=packet())=>{const edit=launch(data);buttonText(edit.foot,'Start pod counter').click();
    await settle();return{edit,data,dialog:counter()};};
  const closeCounter=()=>buttonText(counter(),'Close').click();
  const counterSeat=id=>counter().querySelector(`[data-pod-life-seat=${id}]`);
  const concede=id=>counterSeat(id).querySelectorAll('button').find(button=>button.getAttribute('aria-label')?.endsWith(': concede')).click();
  const endDraw=async()=>{buttonText(counter(),'End game').click();buttonText(counter(),'Draw').click();await settle();return sheets.at(-1);};
  const checkResult=async edit=>{buttonText(edit.foot,'Review pod game').click();await settle();return sheets.at(-1);};
  const saveResult=async review=>{buttonText(review.foot,'Save pod game').click();await settle();};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PodLifeBridgeUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + BRIDGE + "{" + scenario + "}", True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_start_uses_owned_choices_without_result_or_server_requests(self):
        self.run_js(r"""
          const {edit,data,dialog}=await startCounter();assert(dialog);assert(edit.closed);
          assert.equal(dialog.querySelectorAll('.pod-life-seat').length,3);
          assert.equal(JSON.stringify(dialog.querySelectorAll('.life-total').map(node=>node.textContent)),JSON.stringify(['40','40','40']));
          const game=kept(data);assert.equal(game.profile,'matt');assert.equal(game.space,'home');assert.equal(game.ended,null);
          same(game.seats[0].deck,{id:'commander/test',version:'target',sha256:shaA});
          same(game.seats[0].sources,[{source_id:'c1',label:'Leader'}]);assert(!('sections' in game.seats[0].deck));
          assert.equal(writes.length,0);assert.equal(routes.length,0);closeCounter();
          assert(buttonText(main,'Resume pod counter'));assert(kept(data));
        """)

    def test_four_seats_and_literal_external_commander_names_are_not_split(self):
        self.run_js(r"""
          const data=packet(),edit=launch(data);set(controls(edit).count,'4','change');
          set(seat(edit,'s2','commander'),'Front // Back, Partner');set(seat(edit,'s3','commander'),'');
          buttonText(edit.foot,'Start pod counter').click();await settle();const game=kept(data);
          assert.equal(game.seats.length,4);same(game.seats[1].sources,[{source_id:'c1',label:'Front // Back, Partner'}]);
          same(game.seats[2].sources,[{source_id:'c1',label:'Commander 1'}]);assert.equal(writes.length,0);
          closeCounter();
        """)

    def test_partner_sources_are_seeded_separately_and_excess_sources_keep_the_setup(self):
        self.run_js(r"""
          for(const count of [2,3]){const chosen=snapshot();chosen.sections.Commander=Array.from({length:count},(_,i)=>
            ({name:`Leader ${i+1}`,qty:1,set:null,number:null,finish:'nonfoil'}));
            const data=packet({pod_lists:[chosen]}),edit=launch(data);buttonText(edit.foot,'Start pod counter').click();await settle();
            if(count===2){assert(counter());assert.equal(kept(data).seats[0].sources.length,2);closeCounter();}
            else{assert.equal(counter(),null);assert(!edit.closed);assert(edit.body.textContent.includes('at most two commander sources'));edit.close();}}
          assert.equal(writes.length,0);
        """)

    def test_catalog_eligible_commander_formats_do_not_depend_on_id_kind(self):
        self.run_js(r"""
          for(const id of ['casual/format-commander','product/test-precon','product/test-precon/leader']){
            const data=packet({pod_lists:[snapshot({id})]}),{dialog}=await startCounter(data);
            assert(dialog,id);assert.equal(kept(data).seats[0].deck.id,id);closeCounter();}
          assert.equal(writes.length,0);
        """)

    def test_first_elimination_continues_and_last_active_opens_the_filled_form_without_posting(self):
        self.run_js(r"""
          const {data}=await startCounter();concede('s2');assert.equal(kept(data).ended,null);
          assert.equal(sheets.length,1);concede('s3');await settle();const edit=sheets.at(-1);
          assert.equal(kept(data).ended.result,'s1');assert(!edit.closed);assert.equal(controls(edit).result.value,'s1');
          assert.equal(seat(edit,'s1','player').value,'Matt');assert.equal(writes.length,0);
          assert(!buttonText(edit.foot,'Start pod counter'));assert(counter());
        """)

    def test_end_draw_uses_existing_explicit_review_and_saves_only_record_fields(self):
        self.run_js(r"""
          const data=packet(),edit=launch(data);set(seat(edit,'s2','commander'),'External label');set(controls(edit).notes,'Typed note');
          buttonText(edit.foot,'Start pod counter').click();await settle();const game=kept(data),key=localPacketKey(game);
          store.set(STORE+LIFE_KEY,'legacy counter kept');const resultForm=await endDraw();assert.equal(writes.length,0);
          assert.equal(controls(resultForm).notes.value,'Typed note');assert.equal(controls(resultForm).result.value,'draw');
          const review=await checkResult(resultForm);assert.equal(writes.length,1);const body=writes[0][1];
          assert.equal(body.mode,'pod');assert.equal(body.result,'draw');assert.equal(body.notes,'Typed note');
          assert.equal(body.seats[1].commander,'External label');
          for(const value of body.seats)for(const field of ['life','poison','damage','sources','out'])assert(!(field in value));
          flushTimers();document.fire('visibilitychange');await settle();assert.equal(writes.length,1);
          await saveResult(review);assert.equal(writes.length,2);assert.equal(store.has(key),false);assert.equal(counter(),null);
          assert.equal(store.get(STORE+LIFE_KEY),'legacy counter kept');same(routes,['#/play']);
        """)

    def test_stale_sha_requires_explicit_current_replacement_before_preview(self):
        self.run_js(r"""
          const initial=await startCounter();closeCounter();const fresh=packet({pod_lists:[snapshot({sha256:shaB})]});
          mount(fresh);buttonText(main,'Resume pod counter').click();assert(counter());
          assert.equal(kept(fresh).seats[0].deck.sha256,shaA);const edit=await endDraw(),choice=seat(edit,'s1','list');
          assert.equal(choice.value,'');assert(choice.textContent.includes('Choose a current replacement list'));
          assert(!choice.textContent.includes('recorded historical list'));assert(edit.body.textContent.includes('capture that current list'));
          buttonText(edit.foot,'Review pod game').click();await settle();assert.equal(writes.length,0);
          assert.equal(choice.value,'');set(choice,'0','change');await checkResult(edit);
          assert.equal(writes.length,1);assert.equal(writes[0][1].seats[0].deck.sha256,shaB);
        """)

    def test_removed_renamed_and_nonrecordable_choices_can_resume_counting_without_a_silent_default(self):
        self.run_js(r"""
          for(const choices of [[],[snapshot({id:'commander/renamed',sha256:shaB})],[snapshot({can_record:false})]]){
            const started=await startCounter();closeCounter();const fresh=packet({pod_lists:choices});mount(fresh);
            assert(buttonText(main,'Resume pod counter'));buttonText(main,'Resume pod counter').click();assert(counter());
            const edit=await endDraw();buttonText(edit.foot,'Review pod game').click();await settle();assert.equal(writes.length,0);
            if(choices[0]?.can_record!==false)assert.equal(seat(edit,'s1','list').value,'');
            assert(edit.body.textContent.includes('keep counting')||edit.body.textContent.includes('Choose a saved Commander deck'));
            buttonText(edit.foot,'Cancel').click();assert(counter());closeCounter();clear(main);}
        """)

    def test_stale_selector_remains_unresolved_across_type_and_player_count_rerenders(self):
        self.run_js(r"""
          const started=await startCounter();closeCounter();const fresh=packet({pod_lists:[snapshot({sha256:shaB})]});
          mount(fresh);buttonText(main,'Resume pod counter').click();const edit=await endDraw();
          assert.equal(seat(edit,'s1','list').value,'');set(seat(edit,'s1','type'),'external','change');
          set(controls(edit).count,'4','change');set(seat(edit,'s1','type'),'deck','change');
          assert.equal(seat(edit,'s1','list').value,'');buttonText(edit.foot,'Review pod game').click();await settle();
          assert.equal(writes.length,0);assert(edit.body.textContent.includes('Choose a saved Commander deck'));
          set(seat(edit,'s1','list'),'0','change');await checkResult(edit);assert.equal(writes.length,1);
          assert.equal(writes[0][1].seats[0].deck.sha256,shaB);
        """)

    def test_hidden_disabled_moved_or_detached_start_controls_cannot_launch_or_store(self):
        self.run_js(r"""
          const mutations=[(edit,button)=>button.hidden=true,(edit,button)=>button.disabled=true,
            (edit,button)=>button.setAttribute('aria-hidden','true'),edit=>edit.foot.hidden=true,
            edit=>edit.body.parentNode.setAttribute('aria-hidden','true'),(edit,button)=>edit.body.append(button),
            edit=>edit.dialog.remove(),()=>state.profile={...state.profile},()=>routeToken++,()=>document.visibilityState='hidden'];
          for(const mutate of mutations){state.profile={id:'matt',name:'Matt',space:'home'};document.visibilityState='visible';
            const edit=launch(),button=buttonText(edit.foot,'Start pod counter');mutate(edit,button);button.fire('click');await settle();
            assert.equal(counter(),null);assert.equal(store.size,0);edit.close();}
          assert.equal(writes.length,0);
        """)

    def test_resume_host_parent_and_hidden_disabled_controls_remain_owned_before_open_or_error(self):
        self.run_js(r"""
          const started=await startCounter();closeCounter();
          const mutations=[(host,button)=>host.hidden=true,(host,button)=>button.disabled=true,
            (host,button)=>host.setAttribute('aria-hidden','true'),host=>{const other=el('section');main.append(other);other.append(host);},
            host=>host.parentNode.remove(),()=>state.profile={...state.profile}];
          for(const mutate of mutations){state.profile={id:'matt',name:'Matt',space:'home'};mount(started.data);
            const host=main.querySelector('.pod-counter-launcher'),button=buttonText(host,'Resume pod counter');
            mutate(host,button);const before=host.textContent;button.fire('click');await settle();assert.equal(counter(),null);
            assert.equal(host.textContent,before);}
          assert.equal(writes.length,0);
        """)

    def test_counter_clock_hide_and_closed_source_callbacks_never_post_or_open_a_form(self):
        self.run_js(r"""
          const {data}=await startCounter(),before=sheets.length;
          for(const node of counter().querySelectorAll('.pod-life-sources')){assert.equal(node.tag,'details');assert.equal(node.getAttribute('open'),null);}
          const disclosure=counterSeat('s2').querySelector('.pod-life-sources'),button=disclosure.querySelectorAll('button').at(-1);
          const old=JSON.stringify(kept(data));button.fire('click');assert.equal(JSON.stringify(kept(data)),old);
          document.visibilityState='hidden';document.hidden=true;flushTimers();document.fire('visibilitychange');
          concede('s2');concede('s3');await settle();assert.equal(writes.length,0);assert.equal(sheets.length,before);
          assert.equal(JSON.stringify(kept(data)),old);
        """)

    def test_uncertain_save_reply_preserves_counter_and_never_retries(self):
        self.run_js(r"""
          const {data}=await startCounter(),edit=await endDraw(),review=await checkResult(edit),game=kept(data),key=localPacketKey(game);
          apiWrite=async(path,body)=>{writes.push([path,body]);return{saved:true,record:makePod(),sha256:shaR};};
          await saveResult(review);assert.equal(writes.length,2);assert(store.has(key));assert(counter());assert(!review.closed);
          flushTimers();document.fire('visibilitychange');await settle();assert.equal(writes.length,2);assert.equal(routes.length,0);
        """)

    def test_late_save_after_profile_or_visibility_change_cannot_clear_counter_or_navigate(self):
        self.run_js(r"""
          for(const mutate of [()=>state.profile={...state.profile},()=>{document.hidden=true;document.visibilityState='hidden';}]){
            state.profile={id:'matt',name:'Matt',space:'home'};document.hidden=false;document.visibilityState='visible';
            const {data}=await startCounter(),edit=await endDraw(),review=await checkResult(edit),game=kept(data),key=localPacketKey(game),pending=deferred();let body;
            apiWrite=async(path,value)=>{writes.push([path,value]);body=value;return pending.promise;};
            buttonText(review.foot,'Save pod game').click();mutate();pending.resolve(response(body,true));await settle();
            assert(store.has(key));assert.equal(routes.length,0);assert.equal(messages.length,0);assert(!review.closed);
            review.close();edit.close();closePodLifeCounter(true);apiWrite=async(path,value)=>{writes.push([path,value]);return response(value,value.preview===false);};}
        """)

    def test_a_newer_stored_session_survives_the_old_confirmed_save_reply(self):
        self.run_js(r"""
          const {data}=await startCounter(),edit=await endDraw(),review=await checkResult(edit),old=kept(data),oldKey=localPacketKey(old),pending=deferred();let body;
          apiWrite=async(path,value)=>{writes.push([path,value]);body=value;return pending.promise;};buttonText(review.foot,'Save pod game').click();
          const newer={...structuredClone(old),session_id:'2'.repeat(32)},newKey=localPacketKey(newer);
          store.set(newKey,JSON.stringify(newer));store.set(STORE+podLifeKey(state.profile),newer.session_id);
          pending.resolve(response(body,true));await settle();assert(store.has(oldKey));assert.equal(store.get(newKey),JSON.stringify(newer));
          assert.equal(store.get(STORE+podLifeKey(state.profile)),newer.session_id);assert.equal(routes.length,0);assert.equal(messages.length,0);
        """)

    def test_successful_server_save_with_failed_local_removal_does_not_route_or_offer_duplicate_resume(self):
        self.run_js(r"""
          const {data}=await startCounter(),edit=await endDraw(),review=await checkResult(edit),game=kept(data),key=localPacketKey(game);
          window.localStorage.removeItem=()=>{throw Error('blocked');};await saveResult(review);
          assert.equal(writes.length,2);assert(store.has(key));assert(counter());assert.equal(routes.length,0);
          assert(counter().textContent.includes('Pod game saved.'));assert(counter().textContent.includes('Resume is disabled'));
          assert.equal(podLifeSaved(data),null);assert.equal(buttonText(document.body,'Save pod game'),undefined);
          flushTimers();await settle();assert.equal(writes.length,2);
        """)

    def test_normal_recording_and_legacy_counter_stay_available_without_the_new_runtime(self):
        self.run_js(r"""
          const open=podLifeOpen;podLifeOpen=undefined;const edit=launch();assert.equal(buttonText(edit.foot,'Start pod counter'),undefined);
          const review=await checkResult(edit);assert.equal(writes.length,0); // normal form still requires its result
          set(controls(edit).result,'draw','change');await checkResult(edit);assert.equal(writes.length,1);podLifeOpen=open;
          assert.equal(typeof lifeNewGame,'function');assert.equal(typeof lifeCounterLauncher,'function');
        """)

    def test_compact_layout_has_explicit_touch_geometry_and_collapsed_matrix_contract(self):
        css = (WEB / "play.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: 44px minmax(0, 1fr) 44px", css)
        self.assertIn(".pod-life-counter button { min-width: 44px; min-height: max(44px, var(--tap))", css)
        self.assertIn("@media (max-width: 359px)", css)
        self.assertIn("@media (min-width: 360px) and (max-width: 399px)", css)
        self.assertIn(".pod-life-sources:not([open]) > :not(summary) { display: none; }", css)
        # At 360px: 8px outer padding, 8px gap, 8px seat padding and 1px borders.
        seat_content = (360 - 2 * 8 - 8) / 2 - 2 * 8 - 2
        self.assertGreaterEqual(seat_content - 2 * 44 - 2 * 4, 4 * 20 * 0.6)
