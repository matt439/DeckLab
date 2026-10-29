"""Source-aware duel counter over the actual page script order and fake storage.

The model/runtime count locally; result forms are captured rather than sent.
No browser, network, database, configured cache or real records are used.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = """
  let clockNow=Date.UTC(2026,9,29,8);Date.now=()=>clockNow;editor=null;saveDraft=()=>{};
  const store=new Map(),writes=[],records=[];
  window.localStorage={getItem:key=>store.has(key)?store.get(key):null,
    setItem:(key,value)=>store.set(key,String(value)),removeItem:key=>store.delete(key)};
  state.profile={id:'matt',name:'Matt',space:'home',plays_as:'user'};
  state.profiles=[state.profile,{id:'user1',name:'User1',space:'home',plays_as:'wife'}];
  routeToken=83;location.hash='#/play';document.visibilityState='visible';clear(main);
  const line=name=>({name,qty:1,set:null,number:null,finish:'nonfoil'});
  const list=(id,title,sha,commanders=[])=>({id,title,version:'target',sha256:sha.repeat(64),
    sections:{Deck:[{...line('Forest'),qty:60}],...(commanders.length?{Commander:commanders.map(line)}:{})}});
  const lists=[list('casual/a','Alpha','a'),list('casual/b','Beta','b'),
    list('commander/c','Gamma','c',['Literal // Face, Label']),list('commander/d','Delta','d',['Partner 1','Partner 2'])];
  const data={lists,decks:Object.fromEntries(lists.map(value=>[value.id,{can_record:true,player:'user',status:'built'}])),
    games:[],sideboards:[],warnings:[],pods:[],pod_lists:[],today:'2026-10-29'};
  let selection=[0,1];
  const chosen=()=>selection.map((index,i)=>({list:lists[index],name:i?'User1':'Matt'}));
  const named=(root,text)=>root.querySelectorAll('button').find(button=>button.textContent===text);
  const mount=()=>{clear(main);const panel=el('section',{class:'fixture-quick'});panel.append(lifeCounterLauncher(data,chosen));
    lifeV2BindLauncher(panel);main.append(panel);return panel;};
  const counter=()=>document.body.querySelector('.life-source-counter');
  const start=(choices=[0,1])=>{selection=choices;mount();(named(main,'Life counter')||named(main,'New life counter')).click();assert(counter());return lifeV2Open.game;};
  const press=label=>counter().querySelectorAll('button').find(button=>button.getAttribute('aria-label')===label);
  const active=()=>lifeV2Open.game,kept=()=>lifeV2Saved(data);
  const packetKey=game=>STORE+lifeV2Key(state.profile,game.session_id);
  const pointerKey=()=>STORE+lifeV2Key();
  const reveal=id=>counter().querySelector(`[data-life-source-seat=${id}]`).querySelector('details').setAttribute('open','');
  lifeSourceReview=(answer,packet,context)=>records.push({data:answer,packet,context});
  apiWrite=async(...args)=>{writes.push(args);throw Error('Counter made a request');};
  const settle=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LifeSourceCounterUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=25, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-6000:])
        self.assertEqual(result.stdout.strip(), "ok")

    def test_actual_page_model_starts_casual_at_twenty_and_commander_at_forty(self):
        self.run_js("""
          assert.equal(typeof lifeSourceNewGame,'function');start();assert.equal(active().v,2);
          same(active().players.map(player=>player.life),[20,20]);same(active().players.map(player=>player.sources.length),[0,0]);
          assert.equal(active().date,'2026-10-29');assert(!JSON.stringify(kept()).includes('sections'));closeLifeCounter();
          start([2,3]);same(active().players.map(player=>player.life),[40,40]);same(active().players.map(player=>player.sources.length),[1,2]);
          assert.equal(writes.length,0);assert.equal(records.length,0);
        """)

    def test_v1_raw_combined_damage_survives_draw_v2_start_and_explicit_legacy_resume(self):
        self.run_js("""
          selection=[2,3];const legacy=lifeNewGame(chosen(),'matt',clockNow-1000);legacy.players[0].commander=15;
          legacy.compatible_note='Kept';const raw=JSON.stringify(legacy,null,3)+String.fromCharCode(10);store.set(STORE+LIFE_KEY,raw);
          mount();assert(main.textContent.includes('Legacy combined commander damage'));assert.equal(store.get(STORE+LIFE_KEY),raw);
          named(main,'Life counter').click();assert(counter());assert.equal(store.get(STORE+LIFE_KEY),raw);closeLifeCounter();
          named(main,'Resume legacy life counter').click();assert(lifeOpen);assert.equal(lifeOpen.game.players[0].commander,15);
          flushTimers();document.fire('visibilitychange');assert.equal(store.get(STORE+LIFE_KEY),raw);closeLifeCounter();
          assert.equal(store.get(STORE+LIFE_KEY),raw);
        """)

    def test_delayed_legacy_save_cannot_close_or_delete_a_new_v2_counter(self):
        self.run_js("""
          const legacy=lifeNewGame(chosen(),'matt',clockNow-1000);legacy.ended={result:'draw',why:'chosen',at:clockNow};
          store.set(STORE+LIFE_KEY,JSON.stringify(legacy));mount();named(main,'Resume legacy life counter').click();
          let callback;playGameForm=(...args)=>{callback=args[3].onSaved;};lifeRecord(lifeOpen);closeLifeCounter();
          named(main,'Life counter').click();const session=active().session_id,before=store.get(packetKey(active())),old=store.get(STORE+LIFE_KEY);
          assert.equal(callback(),false);assert(counter());assert.equal(active().session_id,session);
          assert.equal(store.get(packetKey(active())),before);assert.equal(store.get(STORE+LIFE_KEY),old);
        """)

    def test_source_specific_damage_includes_own_commanders_and_never_sums_partners(self):
        self.run_js("""
          start([2,3]);reveal('a');for(let i=0;i<12;i++)press('Matt: 1 more User1: Partner 1').click();
          for(let i=0;i<9;i++)press('Matt: 1 more User1: Partner 2').click();
          assert.equal(active().players[0].life,19);assert.equal(active().ended,null);assert.equal(records.length,0);
          named(counter(),'Undo last change').click();reveal('a');
          assert.equal(active().players[0].damage.find(row=>row.seat_id==='b'&&row.source_id==='c2').value,8);
          for(let i=0;i<21;i++)press('User1: 1 more Own commander: Partner 1')?.click();
          // Open the other player's native disclosure before its own source can change.
          assert.equal(active().players[1].life,40);reveal('b');
          for(let i=0;i<21;i++)press('User1: 1 more Own commander: Partner 1').click();
          assert.equal(active().ended.result,'a');assert.equal(active().ended.why,'commander');assert.equal(records.length,1);
          assert.equal(active().players[1].damage.find(row=>row.seat_id==='b'&&row.source_id==='c2').value,0);
        """)

    def test_commander_labels_are_literal_and_closed_disclosure_controls_are_inert(self):
        self.run_js("""
          start([2,3]);assert.equal(active().players[0].sources[0].label,'Literal // Face, Label');
          press('Matt: 1 more User1: Partner 1').click();assert.equal(active().players[0].life,40);
          reveal('a');press('Matt: 1 more User1: Partner 1').click();assert.equal(active().players[0].life,39);
          assert.equal(active().players[0].sources.length,1);assert.equal(writes.length,0);
        """)

    def test_poison_concede_undo_and_foreground_result_handoff(self):
        self.run_js("""
          start();named(counter(),'Poison').click();for(let i=0;i<9;i++)press('User1: 1 more poison').click();
          assert.equal(active().ended,null);press('User1: 1 more poison').click();assert.equal(records.length,1);
          assert.equal(records[0].packet.ended.result,'a');assert.equal(records[0].packet.ended.why,'poison');
          named(counter(),'Undo last change').click();assert.equal(active().ended,null);assert.equal(active().players[1].poison,9);
          assert.equal(records[0].context.isCurrent(),false);press('Matt: concede').click();assert.equal(records.length,2);
          assert.equal(records[1].packet.ended.result,'b');assert.equal(writes.length,0);
        """)

    def test_tap_and_hold_are_owned_and_repeat_does_not_open_a_record_form(self):
        self.run_js("""
          start();const minus=press('User1: 1 life less (hold for 5)');minus.click();assert.equal(active().players[1].life,19);
          minus.fire('pointerdown');flushTimers();minus.fire('pointerup');minus.click();assert.equal(active().players[1].life,14);
          minus.fire('pointerdown');for(let i=0;i<3;i++)flushTimers();minus.fire('pointerup');minus.click();
          assert(active().ended);assert.equal(records.length,0);named(counter(),'Record result').click();assert.equal(records.length,1);
        """)

    def test_hidden_detached_replaced_or_changed_generation_stops_holds(self):
        self.run_js("""
          start();let minus=press('Matt: 1 life less (hold for 5)');minus.fire('pointerdown');
          document.visibilityState='hidden';document.fire('visibilitychange');flushTimers();assert.equal(active().players[0].life,20);
          document.visibilityState='visible';document.fire('visibilitychange');minus.fire('pointerdown');
          named(counter(),'Poison').click();flushTimers();assert.equal(active().players[0].life,20);minus.fire('pointerup');
          minus.fire('pointerdown');minus.replaceWith(el('button',{text:'Replacement'}));flushTimers();assert.equal(active().players[0].life,20);
          assert.equal(records.length,0);assert.equal(writes.length,0);
        """)

    def test_same_id_profile_replacement_route_and_data_changes_make_old_callbacks_inert(self):
        self.run_js("""
          start();const original=state.profile,minus=press('Matt: 1 life less (hold for 5)');state.profile={...original};
          minus.click();assert.equal(active().players[0].life,20);state.profile=original;routeToken++;minus.click();
          assert.equal(active().players[0].life,20);routeToken--;location.hash='#/shopping';minus.click();assert.equal(active().players[0].life,20);
          location.hash='#/play';const old=data.lists;data.lists=[...old];minus.click();assert.equal(active().players[0].life,20);data.lists=old;
          const decks=data.decks;data.decks={...decks};minus.click();assert.equal(active().players[0].life,20);
          assert.equal(records.length,0);
        """)

    def test_whole_original_launcher_panel_relocation_blocks_start_and_resume(self):
        self.run_js("""
          const panel=mount(),startButton=named(panel,'Life counter'),wrapper=el('div');main.append(wrapper);wrapper.append(panel);
          startButton.click();assert.equal(counter(),null);main.append(panel);startButton.click();assert(counter());closeLifeCounter();
          const resume=named(panel,'Resume life counter');wrapper.append(panel);resume.click();assert.equal(counter(),null);
          assert(kept());
        """)

    def test_ended_resume_and_display_timers_never_reopen_result_or_extend_ttl(self):
        self.run_js("""
          start();named(counter(),'End game').click();named(counter(),'Draw').click();const stamp=JSON.stringify(kept());
          closeLifeCounter();records.length=0;named(main,'Resume life counter').click();assert(counter());clockNow+=10000;
          flushTimers();document.fire('visibilitychange');assert.equal(records.length,0);assert.equal(JSON.stringify(kept()),stamp);
          named(counter(),'Record result').click();assert.equal(records.length,1);
        """)

    def test_stale_or_deleted_selectors_resume_without_a_catalog_and_without_replacement(self):
        self.run_js("""
          start([2,3]);press('Matt: 5 life less').click();const before=kept();closeLifeCounter();data.lists=[];data.decks={};
          clear(main);const wrapper=el('section');wrapper.append(lifeV2EmptyLauncher(data));lifeV2BindLauncher(wrapper);main.append(wrapper);
          assert.equal(named(wrapper,'Life counter'),undefined);named(wrapper,'Resume life counter').click();assert(counter());
          same(active().players.map(player=>player.list),before.players.map(player=>player.list));assert.equal(active().players[0].life,35);
          assert.equal(writes.length,0);
        """)

    def test_newer_storage_pointer_and_same_session_raw_changes_block_old_actions_and_cleanup(self):
        self.run_js("""
          start();named(counter(),'End game').click();named(counter(),'Draw').click();const callback=records[0].context;
          const newer=lifeSourceNewGame({...lifeV2Scope(),session_id:'2'.repeat(32),date:data.today,choices:chosen()});
          store.set(packetKey(newer),JSON.stringify(newer));store.set(pointerKey(),newer.session_id);const raw=store.get(packetKey(newer));
          assert.equal(callback.isCurrent(),false);assert.equal(callback.onSaved(),false);named(counter(),'Undo last change').click();
          assert.equal(store.get(packetKey(newer)),raw);assert.equal(kept().session_id,newer.session_id);closeLifeCounter();
          named(main,'Resume life counter').click();const changed=kept();changed.players[0].life=18;store.set(packetKey(changed),JSON.stringify(changed));
          press('Matt: 1 life less (hold for 5)').click();assert.equal(active().players[0].life,20);
        """)

    def test_partial_storage_failures_keep_counting_and_recover_without_touching_v1(self):
        self.run_js("""
          for(const fail of ['pointer','packet','both']){
            let blocked=true;store.clear();store.set(STORE+LIFE_KEY,'legacy bytes');
            window.localStorage.setItem=(key,value)=>{if(blocked&&key.includes(LIFE_SOURCE_KEY)&&(fail==='both'||
              (fail==='pointer'?key.endsWith('.active'):!key.endsWith('.active'))))throw Error('blocked');store.set(key,String(value));};
            start();assert(counter().querySelector('.life-source-error').textContent.includes('could not'));
            press('Matt: 1 life less (hold for 5)').click();assert.equal(active().players[0].life,19);
            blocked=false;press('Matt: 1 life less (hold for 5)').click();assert.equal(kept().players[0].life,18);
            assert.equal(counter().querySelector('.life-source-error').textContent,'');assert.equal(store.get(STORE+LIFE_KEY),'legacy bytes');closeLifeCounter();}
        """)

    def test_post_change_storage_failure_keeps_memory_and_older_safe_resume(self):
        self.run_js("""
          start();let blocked=true;window.localStorage.setItem=(key,value)=>{if(blocked)throw Error('quota');store.set(key,String(value));};
          press('Matt: 1 life less (hold for 5)').click();press('Matt: 1 life less (hold for 5)').click();
          assert.equal(active().players[0].life,18);assert.equal(kept().players[0].life,20);blocked=false;
          press('Matt: 1 life less (hold for 5)').click();assert.equal(kept().players[0].life,17);
        """)

    def test_confirmed_save_cleanup_is_session_scoped_and_failed_remove_blocks_duplicate_resume(self):
        self.run_js("""
          start();named(counter(),'End game').click();named(counter(),'Draw').click();const game=kept(),callback=records[0].context;
          window.localStorage.removeItem=()=>{throw Error('Removal blocked');};assert.equal(callback.onSaved(),false);
          assert(counter());assert(counter().querySelector('.life-source-error').textContent.includes('Game saved.'));
          assert.equal(kept(),null);assert.equal(callback.isCurrent(),false);named(counter(),'Record result').click();
          assert.equal(records.length,1);assert(store.has(packetKey(game)));assert.equal(active().ended.result,'draw');
          named(counter(),'Close').click();assert.equal(lifeV2Saved(data),null);
        """)

    def test_verified_save_clears_only_current_packet_and_keeps_legacy_bytes(self):
        self.run_js("""
          store.set(STORE+LIFE_KEY,'legacy bytes');start();named(counter(),'End game').click();named(counter(),'Draw').click();
          const packet=kept(),callback=records[0].context;assert(callback.isCurrent());assert(callback.onSaved());
          assert.equal(counter(),null);assert.equal(kept(),null);assert(!store.has(packetKey(packet)));assert.equal(store.get(STORE+LIFE_KEY),'legacy bytes');
        """)

    def test_late_wake_after_profile_change_hide_show_or_close_is_released(self):
        self.run_js("""
          const pending=[],released=[];navigator.wakeLock={request:()=>new Promise(resolve=>pending.push(resolve))};
          const wake=name=>({release:()=>released.push(name)});start();const original=state.profile;state.profile={...original};
          pending.shift()(wake('profile'));await settle();same(released,['profile']);state.profile=original;closeLifeCounter();
          named(main,'Resume life counter').click();document.visibilityState='hidden';document.fire('visibilitychange');
          document.visibilityState='visible';document.fire('visibilitychange');pending.shift()(wake('hidden'));await settle();
          assert(released.includes('hidden'));pending.shift()(wake('current'));await settle();closeLifeCounter();assert(released.includes('current'));
          named(main,'Resume life counter').click();closeLifeCounter();pending.shift()(wake('closed'));await settle();assert(released.includes('closed'));
        """)

    def test_expired_invalid_and_foreign_packets_do_not_resume_or_get_deleted(self):
        self.run_js("""
          start();const game=kept(),key=packetKey(game),raw=store.get(key);closeLifeCounter();
          for(const patch of [{v:1},{started:clockNow-2*24*60*60*1000},{updated:clockNow+1},{profile:'user2'},{extra:true}]){
            store.set(key,JSON.stringify({...game,...patch}));assert.equal(kept(),null);assert(store.has(key));}
          store.set(key,raw);state.profile={id:'user1',space:'home'};assert.equal(kept(),null);assert.equal(store.get(key),raw);
        """)

    def test_lost_pointer_capture_blur_and_pagehide_stop_repeats_until_a_fresh_press(self):
        self.run_js("""
          start();const minus=press('Matt: 1 life less (hold for 5)');
          for(const stop of ['lostpointercapture','blur','pagehide']){
            minus.fire('pointerdown');if(stop==='lostpointercapture')minus.fire(stop);else window.fire(stop);
            flushTimers();assert.equal(active().players[0].life,20);window.fire('focus');window.fire('pageshow');
            flushTimers();assert.equal(active().players[0].life,20);}
          minus.fire('pointerdown');flushTimers();minus.fire('pointerup');minus.click();assert.equal(active().players[0].life,15);
          assert.equal(records.length,0);
        """)

    def test_offered_legacy_resume_controls_bind_profile_frame_storage_and_visibility(self):
        self.run_js("""
          const legacy=lifeNewGame(chosen(),'matt',clockNow-1000);const raw=JSON.stringify(legacy,null,2);
          store.set(STORE+LIFE_KEY,raw);const panel=mount();named(main,'Resume legacy life counter').click();
          const oldCounter=document.body.querySelector('.life-counter');const minus=oldCounter.querySelectorAll('button')
            .find(button=>button.getAttribute('aria-label')==='Matt: 1 life less (hold for 5)');
          const profile=state.profile;state.profile={...profile};minus.click();assert.equal(lifeOpen.game.players[0].life,20);state.profile=profile;
          document.visibilityState='hidden';document.fire('visibilitychange');minus.click();assert.equal(store.get(STORE+LIFE_KEY),raw);
          document.visibilityState='visible';document.fire('visibilitychange');const wrapper=el('div');main.append(wrapper);wrapper.append(panel);
          minus.click();assert.equal(lifeOpen.game.players[0].life,20);main.append(panel);routeToken++;minus.click();
          assert.equal(lifeOpen.game.players[0].life,20);routeToken--;const previous=data.decks;data.decks={...previous};minus.click();
          assert.equal(lifeOpen.game.players[0].life,20);data.decks=previous;minus.click();assert.equal(lifeOpen.game.players[0].life,19);
          const stored=store.get(STORE+LIFE_KEY);store.set(STORE+LIFE_KEY,stored+' ');minus.click();
          assert.equal(lifeOpen.game.players[0].life,19);assert.equal(store.get(STORE+LIFE_KEY),stored+' ');
        """)

    def test_offered_legacy_holds_stop_for_hidden_replaced_and_changed_generation_controls(self):
        self.run_js("""
          store.set(STORE+LIFE_KEY,JSON.stringify(lifeNewGame(chosen(),'matt',clockNow-1000)));mount();named(main,'Resume legacy life counter').click();
          const oldCounter=document.body.querySelector('.life-counter'),button=oldCounter.querySelectorAll('button')
            .find(value=>value.getAttribute('aria-label')==='Matt: 1 life less (hold for 5)');
          button.fire('pointerdown');named(oldCounter,'Poison').click();flushTimers();assert.equal(lifeOpen.game.players[0].life,20);button.fire('pointerup');
          button.fire('pointerdown');window.fire('blur');flushTimers();assert.equal(lifeOpen.game.players[0].life,20);window.fire('focus');
          button.fire('pointerdown');button.replaceWith(el('button',{text:'Replacement'}));flushTimers();assert.equal(lifeOpen.game.players[0].life,20);
          assert.equal(writes.length,0);assert.equal(records.length,0);
        """)

    def test_offered_legacy_late_wake_releases_after_hide_profile_change_and_close(self):
        self.run_js("""
          const pending=[],released=[];navigator.wakeLock={request:()=>new Promise(resolve=>pending.push(resolve))};
          const wake=name=>({release:()=>released.push(name)});store.set(STORE+LIFE_KEY,JSON.stringify(lifeNewGame(chosen(),'matt',clockNow-1000)));
          mount();named(main,'Resume legacy life counter').click();const profile=state.profile;state.profile={...profile};
          pending.shift()(wake('profile'));await settle();assert(released.includes('profile'));state.profile=profile;
          document.visibilityState='hidden';document.fire('visibilitychange');document.visibilityState='visible';document.fire('visibilitychange');
          closeLifeCounter();pending.shift()(wake('closed'));await settle();assert(released.includes('closed'));
        """)

    def test_production_quick_record_and_empty_resume_bind_the_original_panel(self):
        self.run_js("""
          clear(main);drawPlay(data,'');named(main,'Life counter').click();assert(counter());const game=kept();closeLifeCounter();
          const empty={...data,lists:[],decks:{}};clear(main);drawPlay(empty,'');assert.equal(named(main,'Life counter'),undefined);
          named(main,'Resume life counter').click();assert(counter());same(active().players.map(player=>player.list),game.players.map(player=>player.list));
          assert.equal(writes.length,0);
        """)

    def test_legacy_restart_keeps_the_original_launcher_owner_guard(self):
        self.run_js("""
          store.set(STORE+LIFE_KEY,JSON.stringify(lifeNewGame(chosen(),'matt',clockNow-1000)));
          const panel=mount();named(main,'Resume legacy life counter').click();
          lifeEnd(lifeOpen.game,'draw',clockNow);lifeLegacyStore(lifeOpen);lifeDraw(lifeOpen);
          named(document.body.querySelector('.life-counter'),'New game').click();assert.equal(lifeOpen.game.ended,null);
          const wrapper=el('div');main.append(wrapper);wrapper.append(panel);
          const minus=document.body.querySelector('.life-counter').querySelectorAll('button')
            .find(button=>button.getAttribute('aria-label')==='Matt: 1 life less (hold for 5)');
          minus.click();assert.equal(lifeOpen.game.players[0].life,20);assert.equal(writes.length,0);
        """)

    def test_terminal_hold_opens_one_filled_result_only_on_matching_foreground_release(self):
        self.run_js("""
          start();const initial=lifeV2Clone(active()),minus=press('User1: 1 life less (hold for 5)');
          minus.fire('pointerdown',{pointerId:7});for(let i=0;i<4;i++)flushTimers();
          assert.equal(active().ended.result,'a');assert.equal(records.length,0);assert.equal(writes.length,0);
          minus.fire('pointerup',{pointerId:7});assert.equal(records.length,1);assert.equal(records[0].packet.ended.result,'a');
          assert.equal(records[0].packet.date,initial.date);same(records[0].packet.players.map(player=>player.list),initial.players.map(player=>player.list));
          minus.click();minus.fire('pointerup',{pointerId:7});flushTimers();assert.equal(records.length,1);assert.equal(writes.length,0);
        """)

    def test_terminal_hold_cancellation_visibility_and_detach_discard_release_handoff(self):
        self.run_js("""
          for(const cancel of ['pointercancel','pointerleave','lostpointercapture','hide','blur','detach']){
            records.length=0;start();const minus=press('User1: 1 life less (hold for 5)');
            minus.fire('pointerdown',{pointerId:8});for(let i=0;i<4;i++)flushTimers();assert(active().ended);assert.equal(records.length,0);
            if(cancel==='hide'){document.visibilityState='hidden';document.fire('visibilitychange');document.visibilityState='visible';document.fire('visibilitychange');}
            else if(cancel==='blur'){window.fire('blur');window.fire('focus');}
            else if(cancel==='detach')minus.remove();else minus.fire(cancel,{pointerId:8});
            minus.fire('pointerup',{pointerId:8});minus.click();assert.equal(records.length,0);assert.equal(writes.length,0);
            named(counter(),'Record result').click();assert.equal(records.length,1);closeLifeCounter();
          }
        """)

    def test_terminal_hold_second_pointer_storage_and_generation_changes_cannot_handoff(self):
        self.run_js("""
          for(const changed of ['wrong release','second press','storage','undo']){
            records.length=0;start();const minus=press('User1: 1 life less (hold for 5)');
            minus.fire('pointerdown',{pointerId:9});for(let i=0;i<4;i++)flushTimers();assert.equal(records.length,0);
            if(changed==='wrong release')minus.fire('pointerup',{pointerId:10});
            else if(changed==='second press')minus.fire('pointerdown',{pointerId:10});
            else if(changed==='storage'){const saved=kept();saved.players[0].life=19;store.set(packetKey(saved),JSON.stringify(saved));}
            else named(counter(),'Undo last change').click();
            minus.fire('pointerup',{pointerId:9});assert.equal(records.length,0);assert.equal(writes.length,0);closeLifeCounter();
          }
        """)

    def test_terminal_hold_owner_drift_cannot_open_a_form_or_touch_a_newer_session(self):
        self.run_js("""
          start();const minus=press('User1: 1 life less (hold for 5)');minus.fire('pointerdown',{pointerId:11});
          for(let i=0;i<4;i++)flushTimers();const original=kept();state.profile={...state.profile};
          const newer=lifeSourceNewGame({...lifeV2Scope(),session_id:'4'.repeat(32),date:data.today,choices:chosen()});
          store.set(packetKey(newer),JSON.stringify(newer));store.set(pointerKey(),newer.session_id);const raw=store.get(packetKey(newer));
          minus.fire('pointerup',{pointerId:11});assert.equal(records.length,0);assert.equal(store.get(packetKey(newer)),raw);
          assert.equal(kept().session_id,newer.session_id);assert.equal(writes.length,0);assert(original.ended);
        """)

    def test_offered_legacy_terminal_hold_requires_its_matching_release_and_honors_cancellation(self):
        self.run_js("""
          for(const cancel of [false,true]){
            closeLifeCounter();const legacy=lifeNewGame(chosen(),'matt',clockNow-1000);
            store.set(STORE+LIFE_KEY,JSON.stringify(legacy));mount();named(main,'Resume legacy life counter').click();
            let opened=0;playGameForm=(answer,id,entry,preset)=>{opened++;assert.equal(preset.result,'a');};
            const oldCounter=document.body.querySelector('.life-counter'),minus=oldCounter.querySelectorAll('button')
              .find(button=>button.getAttribute('aria-label')==='User1: 1 life less (hold for 5)');
            minus.fire('pointerdown',{pointerId:12});for(let i=0;i<4;i++)flushTimers();assert.equal(opened,0);assert(lifeOpen.game.ended);
            if(cancel)minus.fire('lostpointercapture',{pointerId:12});minus.fire('pointerup',{pointerId:12});minus.click();
            assert.equal(opened,cancel?0:1);minus.fire('pointerup',{pointerId:12});assert.equal(opened,cancel?0:1);
            assert.equal(writes.length,0);
          }
        """)
