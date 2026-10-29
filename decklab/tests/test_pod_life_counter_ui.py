"""Local pod-counter interactions over the real model/runtime and a disposable DOM.

Storage, time and result handoffs are fake; no browser, user data, server or
network is used. Run through scripts/test_fixtures.py before test imports.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = """
  let clockNow=Date.UTC(2026,9,29,8);Date.now=()=>clockNow;
  const store=new Map(),writes=[],handoffs=[];let currentOwner=true;
  window.localStorage={getItem:key=>store.has(key)?store.get(key):null,
    setItem:(key,value)=>store.set(key,String(value)),removeItem:key=>store.delete(key)};
  state.profile={id:'matt',name:'Matt',space:'home'};routeToken=72;location.hash='#/play';
  document.visibilityState='visible';clear(main);
  editor=null;saveDraft=()=>{};
  const source=el('button',{text:'Start pod counter'});main.append(source);
  const data={pod_lists:[],pods:[],today:'2026-10-29'};
  const input=(count=3,session='1'.repeat(32))=>({profile:'matt',space:'home',session_id:session,date:'2026-10-29',notes:'Local note',
    seats:Array.from({length:count},(_,index)=>({seat_id:'s'+(index+1),player:['A','B','C','D'][index],
      ...(index===0?{type:'deck',deck:{id:'commander/a',version:'target',sha256:'a'.repeat(64)},title:'Saved deck'}
        :{type:'external',commander:index===1?'Literal // Leader, Partner':''}),
      sources:[{source_id:'c1',label:index===1?'Literal // Leader, Partner':''}]}))});
  const options=(extra={})=>({source,isCurrent:()=>currentOwner,onRecord:(packet,context)=>handoffs.push({packet,context}),replace:true,...extra});
  const open=(count=3,extra={})=>{const game=podLifeNew(input(count));assert(game);assert(podLifeOpen(data,game,options(extra)));return game;};
  const counter=()=>document.body.querySelector('.pod-life-counter');
  const named=(root,text)=>root.querySelectorAll('button').find(button=>button.textContent===text);
  const press=label=>counter().querySelectorAll('button').find(button=>button.getAttribute('aria-label')===label);
  const seatNode=id=>counter().querySelector(`[data-pod-life-seat=${id}]`);
  const active=()=>podLifeCounterOpen.packet;
  const kept=()=>podLifeSaved(data);
  const point=id=>STORE+podLifeKey(state.profile,id);
  const reveal=id=>seatNode(id).querySelector('details').setAttribute('open','');
  apiWrite=async(...args)=>{writes.push(args);throw Error('Counting made a request');};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PodLifeCounterUiTests(unittest.TestCase):
    def run_js(self, scenario):
        scripts = ("hands.js", "play.js", "play-pods.js", "pod-life-model.js", "pod-life-counter.js")
        sources = "\n".join((WEB / name).read_text(encoding="utf-8") for name in scripts)
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), sources + SETUP + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=25, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-6000:])
        self.assertEqual(result.stdout.strip(), "ok")

    def test_three_and_four_players_start_at_forty_and_store_selectors_only(self):
        self.run_js("""
          for(const count of [3,4]){store.clear();open(count);same(active().seats.map(seat=>seat.life),Array(count).fill(40));
            assert.equal(counter().querySelectorAll('.pod-life-seat').length,count);assert(kept());
            assert(!JSON.stringify(kept()).includes('sections'));assert.equal(kept().profile,'matt');
            assert.equal(kept().space,'home');assert.equal(store.get(point('active')),'1'.repeat(32));
            closePodLifeCounter();}
          assert.equal(writes.length,0);assert.equal(handoffs.length,0);assert.match(podLifeSessionId(),/^[a-f0-9]{32}$/);
        """)

    def test_life_taps_poison_and_first_elimination_leave_other_players_counting(self):
        self.run_js("""
          open();press('A: 5 life less').click();press('A: 1 more life').click();assert.equal(active().seats[0].life,36);
          named(counter(),'Poison').click();assert.equal(kept().poison,true);
          for(let i=0;i<10;i++)press('B: 1 more poison').click();
          assert.equal(podLifeOut(active(),'s2'),'poison');assert.equal(handoffs.length,0);assert.equal(active().ended,null);
          press('C: 1 life less').click();assert.equal(active().seats[2].life,39);
          press('B: 1 more life').click();assert.equal(active().seats[1].life,40);
          press('C: concede').click();assert.equal(handoffs.length,1);assert.equal(handoffs[0].packet.ended.result,'s1');
          assert.equal(writes.length,0);
        """)

    def test_own_commander_and_partner_sources_remain_separate(self):
        self.run_js("""
          const value=input();value.seats[0].sources=[{source_id:'c1',label:'First'},{source_id:'c2',label:'Second'}];
          const game=podLifeNew(value);assert(podLifeOpen(data,game,options()));reveal('s1');
          for(let i=0;i<12;i++)press('A: 1 more Own commander: First').click();
          for(let i=0;i<9;i++)press('A: 1 more Own commander: Second').click();
          assert.equal(active().seats[0].life,19);assert.equal(podLifeOut(active(),'s1'),'');assert.equal(handoffs.length,0);
          for(let i=0;i<9;i++)press('A: 1 more Own commander: First').click();
          assert.equal(podLifeOut(active(),'s1'),'commander');assert.equal(active().seats[0].damage.find(row=>row.seat_id==='s1'&&row.source_id==='c2').value,9);
          assert.equal(handoffs.length,0);assert.equal(active().ended,null);
        """)

    def test_closed_native_damage_disclosure_is_inert_and_external_second_source_is_explicit(self):
        self.run_js("""
          open();const hidden=press('A: 1 more B: Literal // Leader, Partner');hidden.click();
          assert.equal(active().seats[0].life,40);assert.equal(active().seats[1].sources.length,1);
          named(seatNode('s2'),'Add second commander').click();assert.equal(active().seats[1].sources.length,1);
          reveal('s2');named(seatNode('s2'),'Add second commander').click();
          assert.equal(active().seats[1].sources.length,2);assert.equal(active().seats[1].sources[0].label,'Literal // Leader, Partner');
          assert.equal(active().seats[1].sources[1].label,'Commander 2');
          reveal('s1');press('A: 1 more B: Commander 2').click();assert.equal(active().seats[0].life,39);
          assert.equal(active().seats[0].damage.find(row=>row.seat_id==='s2'&&row.source_id==='c1').value,0);
          assert.equal(named(seatNode('s2'),'Add second commander'),undefined);
        """)

    def test_end_game_and_keep_playing_are_explicit_and_handoff_waits_for_choice(self):
        self.run_js("""
          open();named(counter(),'Draw').click();assert.equal(handoffs.length,0);
          named(counter(),'End game').click();named(counter(),'Keep playing').click();assert.equal(active().ended,null);
          named(counter(),'End game').click();named(counter(),'Draw').click();assert.equal(handoffs.length,1);
          assert.equal(handoffs[0].packet.ended.result,'draw');assert.equal(kept().ended.result,'draw');
          flushTimers();document.fire('visibilitychange');assert.equal(handoffs.length,1);assert.equal(writes.length,0);
        """)

    def test_resume_ended_counter_offers_review_but_never_opens_it_automatically(self):
        self.run_js("""
          open();named(counter(),'End game').click();named(counter(),'B won').click();closePodLifeCounter();handoffs.length=0;
          const saved=kept();assert(podLifeOpen(data,saved,options({replace:false})));
          flushTimers();document.fire('visibilitychange');assert.equal(handoffs.length,0);
          named(counter(),'Review pod result').click();assert.equal(handoffs.length,1);assert.equal(handoffs[0].packet.ended.result,'s2');
        """)

    def test_close_resume_keeps_counts_and_deleted_deck_selectors_without_a_catalog(self):
        self.run_js("""
          open();press('C: 5 life less').click();const before=kept();named(counter(),'Close').click();assert.equal(counter(),null);
          assert(podLifeOpen(data,kept(),options({replace:false})));assert.equal(active().seats[2].life,35);
          same(active().seats[0].deck,before.seats[0].deck);same(data.pod_lists,[]);assert.equal(writes.length,0);
          const updated=active().updated;clockNow+=5000;flushTimers();assert.equal(active().updated,updated);
          assert.equal(kept().updated,updated);assert.equal(handoffs.length,0);
        """)

    def test_saved_packet_validation_does_not_delete_malformed_expired_or_other_profile_data(self):
        self.run_js("""
          open();closePodLifeCounter();const key=point('1'.repeat(32)),original=store.get(key);
          for(const changed of [raw=>({...raw,extra:true}),raw=>({...raw,started:clockNow-2*24*60*60*1000}),
            raw=>({...raw,updated:clockNow+1}),raw=>({...raw,profile:'user1'})]){
            store.set(key,JSON.stringify(changed(JSON.parse(original))));assert.equal(kept(),null);assert(store.has(key));}
          store.set(key,'{bad json');assert.equal(kept(),null);assert.equal(store.get(key),'{bad json');
          store.set(key,original);state.profile={id:'user1',space:'home'};assert.equal(kept(),null);assert.equal(store.get(key),original);
        """)

    def test_same_id_profile_replacement_and_stale_routes_cannot_change_or_handoff(self):
        self.run_js("""
          open();const old=state.profile,before=JSON.stringify(kept()),button=press('A: 1 life less');
          state.profile={...old};button.click();named(counter(),'End game').click();assert.equal(JSON.stringify(kept()),before);
          state.profile=old;routeToken++;button.click();assert.equal(active().seats[0].life,40);routeToken--;
          location.hash='#/shopping';button.click();assert.equal(active().seats[0].life,40);location.hash='#/play';
          currentOwner=false;button.click();assert.equal(active().seats[0].life,40);assert.equal(handoffs.length,0);
        """)

    def test_hidden_document_detached_buttons_and_replaced_frames_are_inert(self):
        self.run_js("""
          open();const button=press('A: 1 life less'),before=JSON.stringify(kept());document.visibilityState='hidden';
          button.click();flushTimers();document.fire('visibilitychange');assert.equal(JSON.stringify(kept()),before);
          document.visibilityState='visible';document.fire('visibilitychange');const parent=button.parentNode;
          button.replaceWith(el('button',{text:'Replacement'}));button.click();assert.equal(active().seats[0].life,40);
          parent.append(button);const grid=podLifeCounterOpen.grid;grid.replaceWith(el('div'));button.click();
          assert.equal(active().seats[0].life,40);assert.equal(handoffs.length,0);
        """)

    def test_another_top_dialog_blocks_controls_and_clock_never_extends_ttl(self):
        self.run_js("""
          open();const started=active().started,updated=active().updated,packet=JSON.stringify(kept());
          const other=el('dialog',{open:''});document.body.append(other);press('A: 1 life less').click();
          assert.equal(active().seats[0].life,40);other.remove();clockNow+=10000;flushTimers();
          assert.equal(active().started,started);assert.equal(active().updated,updated);assert.equal(JSON.stringify(kept()),packet);
          assert.equal(handoffs.length,0);
        """)

    def test_foreground_review_context_survives_sheet_overlay_and_clears_only_its_packet(self):
        self.run_js("""
          open();named(counter(),'End game').click();named(counter(),'Draw').click();const callback=handoffs[0].context;
          const sheet=el('dialog',{open:''});document.body.append(sheet);assert(callback.isCurrent());
          sheet.remove();assert(callback.onSaved());assert.equal(counter(),null);assert.equal(kept(),null);
          assert.equal(store.get(point('active')),'1'.repeat(32));assert(!store.has(point('1'.repeat(32))));
        """)

    def test_newer_session_pointer_and_packet_are_preserved_by_old_controls_and_save_callback(self):
        self.run_js("""
          open();named(counter(),'End game').click();named(counter(),'Draw').click();const callback=handoffs[0].context;
          const newer=podLifeNew(input(3,'2'.repeat(32)));store.set(point('2'.repeat(32)),JSON.stringify(newer));
          store.set(point('active'),'2'.repeat(32));const before=store.get(point('2'.repeat(32)));
          assert.equal(callback.isCurrent(),false);assert.equal(callback.onSaved(),false);named(counter(),'Undo last change').click();
          assert.equal(store.get(point('active')),'2'.repeat(32));assert.equal(store.get(point('2'.repeat(32))),before);
          assert.equal(kept().session_id,'2'.repeat(32));
        """)

    def test_stale_resume_and_old_save_callbacks_cannot_replace_a_new_counter(self):
        self.run_js("""
          open();named(counter(),'End game').click();named(counter(),'Draw').click();const callback=handoffs[0].context,old=kept();
          closePodLifeCounter();const newer=podLifeNew(input(3,'2'.repeat(32)));assert(podLifeOpen(data,newer,options()));
          assert.equal(callback.onSaved(),false);assert.equal(active().session_id,'2'.repeat(32));closePodLifeCounter();
          assert.equal(podLifeOpen(data,old,options({replace:false})),false);assert.equal(kept().session_id,'2'.repeat(32));
        """)

    def test_undo_invalidates_an_old_result_handoff_and_restores_only_this_game(self):
        self.run_js("""
          open();press('B: concede').click();assert.equal(handoffs.length,0);named(counter(),'Undo last change').click();
          assert.equal(podLifeOut(active(),'s2'),'');named(counter(),'End game').click();named(counter(),'Draw').click();
          const callback=handoffs[0].context;named(counter(),'Undo last change').click();assert.equal(active().ended,null);
          assert.equal(callback.isCurrent(),false);assert.equal(callback.onSaved(),false);assert(kept());
        """)

    def test_partial_and_total_storage_failure_still_count_and_warn_then_recover(self):
        self.run_js("""
          for(const failed of ['pointer','packet','both']){
            let blocked=true;window.localStorage={getItem:key=>store.has(key)?store.get(key):null,
              setItem:(key,value)=>{if(blocked&&(failed==='both'||(failed==='pointer'?key.endsWith('.active'):!key.endsWith('.active'))))throw Error('blocked');store.set(key,String(value));},
              removeItem:key=>store.delete(key)};store.clear();open();assert(counter().querySelector('.pod-life-error').textContent.includes('could not'));
            press('A: 1 life less').click();assert.equal(active().seats[0].life,39);assert(counter().querySelector('.pod-life-error').textContent.includes('could not'));
            blocked=false;press('A: 1 life less').click();assert.equal(active().seats[0].life,38);assert.equal(kept().seats[0].life,38);
            assert.equal(counter().querySelector('.pod-life-error').textContent,'');closePodLifeCounter();}
        """)

    def test_storage_failing_after_a_change_keeps_memory_counting_and_older_safe_resume(self):
        self.run_js("""
          open();let blocked=true;window.localStorage.setItem=(key,value)=>{if(blocked)throw Error('quota');store.set(key,String(value));};
          press('A: 1 life less').click();press('A: 1 life less').click();assert.equal(active().seats[0].life,38);
          assert.equal(kept().seats[0].life,40);assert(counter().querySelector('.pod-life-error').textContent.includes('could not'));
          blocked=false;press('A: 1 life less').click();assert.equal(kept().seats[0].life,37);
          assert.equal(counter().querySelector('.pod-life-error').textContent,'');
        """)

    def test_literal_labels_create_no_markup_and_replaced_callbacks_are_inert(self):
        self.run_js("""
          const value=input();value.seats[1].player='<img src=x>';value.seats[1].sources[0].label='<script>bad</script>';
          const game=podLifeNew(value),opts=options();assert(podLifeOpen(data,game,opts));assert(counter().textContent.includes('<img src=x>'));
          assert.equal(counter().querySelectorAll('img').length,0);assert.equal(counter().querySelectorAll('script').length,0);
          opts.onRecord=()=>{throw Error('replaced');};press('A: 1 life less').click();assert.equal(active().seats[0].life,40);
          assert.equal(handoffs.length,0);
        """)

    def test_bad_start_owner_or_packet_never_opens_or_changes_local_storage(self):
        self.run_js("""
          const game=podLifeNew(input());assert.equal(podLifeOpen(data,game,options({isCurrent:()=>{throw Error('stale');}})),false);
          assert.equal(podLifeOpen(data,{...game,extra:1},options()),false);source.remove();assert.equal(podLifeOpen(data,game,options()),false);
          assert.equal(counter(),null);assert.equal(store.size,0);assert.equal(writes.length,0);
        """)

    def test_confirmed_save_with_failed_local_removal_blocks_duplicate_resume_and_review(self):
        self.run_js("""
          open();named(counter(),'End game').click();named(counter(),'Draw').click();const callback=handoffs[0].context,saved=kept();
          window.localStorage.removeItem=()=>{throw Error('Removal blocked');};assert.equal(callback.onSaved(),false);
          assert(counter());assert(counter().querySelector('.pod-life-error').textContent.includes('Pod game saved.'));
          assert.equal(kept(),null);assert.equal(callback.isCurrent(),false);assert.equal(callback.onSaved(),false);
          named(counter(),'Review pod result').click();named(counter(),'Undo last change').click();assert.equal(handoffs.length,1);
          assert.equal(active().ended.result,'draw');assert(store.has(point('1'.repeat(32))));named(counter(),'Close').click();
          assert.equal(podLifeOpen(data,saved,options({replace:false})),false);assert.equal(writes.length,0);
        """)

    def test_changed_raw_packet_in_same_session_blocks_old_counter_actions(self):
        self.run_js("""
          open();const changed=kept();changed.seats[0].life=39;const raw=JSON.stringify(changed);
          store.set(point('1'.repeat(32)),raw);press('A: 1 life less').click();assert.equal(active().seats[0].life,40);
          named(counter(),'End game').click();named(counter(),'Draw').click();assert.equal(active().ended,null);
          assert.equal(store.get(point('1'.repeat(32))),raw);assert.equal(handoffs.length,0);assert.equal(writes.length,0);
        """)
