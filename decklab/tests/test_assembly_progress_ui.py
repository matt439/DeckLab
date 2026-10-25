"""Shared packing progress with deterministic requests, without a running server."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = """
  clear(main);
  window.matchMedia('(min-width: 1000px)').matches = true;
  location.hash = '#/assembly';
  state.profile = {id:'matt',name:'Matt',space:'home',role:'admin',plays_as:'user'};
  state.profiles = [state.profile];
  const saved = {};
  window.localStorage = {getItem:k => saved[k] ?? null,
    setItem:(k,v) => { saved[k] = String(v); }, removeItem:k => { delete saved[k]; }};
  const server = new Set(), posts = [];
  const apply = body => {
    for (const change of body.changes || []) {
      if (change.done) server.add(change.id); else server.delete(change.id);
    }
    return {ticks:body.ids.filter(id => server.has(id))};
  };
  apiWrite = async (path,body) => {
    assert.equal(path,'/api/assembly/ticks');
    posts.push(body); return apply(body);
  };
  const item = (id='casual/a', extra={}) => ({id,title:id,version:'target',
    sleeves:null,kit:null,sleeves_need:null,tokens:null,basics:[],returns:[],
    steps:[{name:'Alpha',keep:0,storage:2,transfers:[],waiting:0,missing:0}],...extra});
  const plan = (decks=[item()], fingerprint='first') => ({
    choices:decks.map(d => ({id:d.id,title:d.title,status:'building',versions:['target','owned']})),
    decks,rows:[],ready:true,counts_confirmed:true,unresolved:[],warnings:[],note:'',token_note:'',
    totals:{waiting:0,missing:0},tokens:[],token_plan:[],cards:{Alpha:alpha,Beta:beta},
    completion:{fingerprint,can_mark_built:false,reason:'Read only.',decks:[]}});
  const open = data => { drawAssembly(data,routeToken); return main.children.at(-1); };
  const tiles = root => root.querySelectorAll('.pack-tick');
  const checked = root => tiles(root).map(t => t.getAttribute('aria-pressed'));
  const settle = async () => { for (let i=0;i<32;i++) await null; };
  const poll = async () => { flushTimers(); await settle(); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyProgressUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_another_profile_and_device_load_the_same_server_progress(self):
        self.run_js("""
          const first = open(plan()); await settle();
          tiles(first)[0].click(); await settle();
          assert.equal(server.size,1);
          state.profile = {id:'user1',name:'User1',space:'home',role:'member',plays_as:'wife'};
          clear(main); const second = open(plan()); await settle();
          same(checked(second),['true']);
          assert(posts.some(p => p.changes?.some(c => c.done)));
        """)

    def test_selection_title_sort_and_unrelated_revisions_keep_unchanged_tasks(self):
        self.run_js("""
          let root = open(plan()); await settle();
          tiles(root)[0].click(); await settle();
          clear(main); root = open(plan([item('casual/a',{title:'Renamed'}),item('casual/b')],'new-deck'));
          await settle(); same(checked(root),['true','false']);
          const storage = root.querySelector('.pack-sort').querySelectorAll('button')
            .find(b => b.textContent === 'Storage order');
          storage.click(); await settle(); same(checked(root),['true','false']);
          clear(main); root = open(plan([item('casual/a',{title:'Renamed'})],'unrelated-save'));
          await settle(); same(checked(root),['true']);
        """)

    def test_changed_quantity_source_finish_and_list_require_a_new_check(self):
        self.run_js("""
          let root = open(plan()); await settle(); tiles(root)[0].click(); await settle();
          const changed = [
            item('casual/a',{steps:[{name:'Alpha',keep:0,storage:3,transfers:[],waiting:0,missing:0}]}),
            item('casual/a',{steps:[{name:'Alpha',keep:0,storage:0,
              transfers:[{from:'casual/b',from_title:'B',quantity:2}],waiting:0,missing:0}]}),
            item('casual/a',{finishes:{Alpha:[{finish:'foil',quantity:2}]}}),
            item('casual/a',{version:'owned'})
          ];
          for (const deck of changed) {
            clear(main); root = open(plan([deck])); await settle(); same(checked(root),['false']);
          }
          clear(main); root = open(plan()); await settle(); same(checked(root),['true']);
        """)

    def test_identically_named_sleeves_and_boxes_keep_distinct_progress(self):
        self.run_js("""
          const data = (sleevesId,boxId) => plan([item('casual/a',{
            sleeves:'Red',sleeves_need:60,kit:{need:60,warnings:[],
              sleeves:{id:sleevesId,state:'linked',label:'Red',quantity:100},
              deck_box:{id:boxId,state:'linked',label:'Deck box',quantity:1}}})]);
          const kitTicks = root => root.querySelectorAll('[data-pack-tick]').filter(n => n.tag === 'input');
          let root = open(data('sleeves-a','box-a')); await settle();
          assert.equal(kitTicks(root).length,2);
          kitTicks(root).forEach(t => { t.checked=true; t.fire('change'); }); await settle();
          assert(kitTicks(root).every(t => t.checked)); assert.equal(server.size,2);
          clear(main); root=open(data('sleeves-b','box-b')); await settle();
          assert(kitTicks(root).every(t => !t.checked),'matching labels cannot tick different physical kit');
          clear(main); root=open(data('sleeves-a','box-a')); await settle();
          assert(kitTicks(root).every(t => t.checked));
          const renamed=data('sleeves-a','box-a');
          renamed.decks[0].kit.sleeves.label='Red sleeves'; renamed.decks[0].kit.deck_box.label='Favourite box';
          clear(main); root=open(renamed); await settle();
          assert(kitTicks(root).every(t => t.checked),'renaming the same kit keeps its physical checks');
        """)

    def test_token_physical_variants_are_distinct_and_unrelated_row_moves_keep_progress(self):
        self.run_js("""
          const elf={front:'Elf',back:'',set:'tfdn',front_collector_number:'1',back_collector_number:'',
            finish:'nonfoil',quantity:1,front_details:'1/1; green',back_details:'',notes:'Original notes'};
          const other={...elf,front:'Goblin',front_collector_number:'2',front_details:'1/1; red'};
          const data=(rows,row) => ({...plan([item('casual/a',{tokens:{needs:[{
            name:'Elf',state:'ready',cards:[{front:'Elf',back:'',quantity:1,side:'front',row}]}]}})]),tokens:rows});
          const tokenTick=root => root.querySelectorAll('[data-pack-tick]').find(n => n.tag === 'input');
          let root=open(data([elf],0)); await settle();
          tokenTick(root).checked=true; tokenTick(root).fire('change'); await settle();
          assert.equal(server.size,1);
          for (const changed of [{...elf,set:'tother'}, {...elf,front_details:'1/1; green; deathtouch'}]) {
            clear(main); root=open(data([changed],0)); await settle(); assert.equal(tokenTick(root).checked,false);
          }
          clear(main); root=open(data([other,{...elf,notes:'Edited notes',key:'different-position'}],1)); await settle();
          assert.equal(tokenTick(root).checked,true,'row positions and notes do not change the physical token');
        """)

    def test_server_token_identity_bounds_large_alternative_labels_and_tracks_physical_changes(self):
        self.run_js("""
          const make = (packingKey,reverse=false) => {
            let rows=Array.from({length:25},(_,i) => ({front:'Elf '+String(i)+'x'.repeat(60),back:'Goblin',
              set:'tfdn',front_collector_number:String(i),back_collector_number:'99',finish:'nonfoil',
              quantity:1,front_details:'x'.repeat(300),back_details:'x'.repeat(300),notes:'Notes'}));
            if (reverse) rows=rows.reverse().map(r => ({...r,notes:'Unrelated edited notes'}));
            return {...plan([item('casual/a',{tokens:{needs:[{key:'elf-green-1-1',name:'Elf',state:'ready',
              packing_key:packingKey,cards:rows.map((r,row) => ({front:r.front,back:r.back,
                quantity:1,side:'front',row}))}]}})]),tokens:rows};
          };
          const tokenTick=root => root.querySelectorAll('[data-pack-tick]').find(n => n.tag === 'input');
          let root=open(make('a'.repeat(64))); await settle();
          assert(tokenTick(root).parentNode.textContent.length>1000,'the display label can be long');
          assert(packingProgressView.ticks.find(t => !t.tile).id.length<250,'server key keeps request identity bounded');
          tokenTick(root).checked=true; tokenTick(root).fire('change'); await settle();
          clear(main); root=open(make('a'.repeat(64),true)); await settle();
          assert.equal(tokenTick(root).checked,true,'same physical alternatives survive display reordering');
          clear(main); root=open(make('b'.repeat(64))); await settle();
          assert.equal(tokenTick(root).checked,false,'changed physical identity needs a fresh check');
        """)

    def test_simultaneous_devices_patch_only_their_own_changed_task(self):
        self.run_js("""
          const data = plan([item('casual/a'),item('casual/b')]);
          const first = open(data), firstView = packingProgressView;
          const second = open(data), secondView = packingProgressView; await settle();
          const pending = [];
          apiWrite = (path,body) => { posts.push(body);
            return new Promise(resolve => pending.push({body,resolve})); };
          tiles(first)[0].click(); tiles(second)[1].click(); await settle();
          assert.equal(pending.length,2);
          assert(pending.every(p => p.body.changes.length === 1));
          for (const call of pending.splice(0).reverse()) call.resolve(apply(call.body));
          await settle(); assert.equal(server.size,2);
          apiWrite = async (path,body) => { posts.push(body); return apply(body); };
          await packSync(firstView); await packSync(secondView);
          same(checked(first),['true','true']); same(checked(second),['true','true']);
        """)

    def test_a_stale_save_ack_cannot_overwrite_a_newer_local_uncheck(self):
        self.run_js("""
          const root = open(plan()); await settle();
          const pending = [];
          apiWrite = (path,body) => new Promise(resolve => pending.push({body,resolve}));
          const tick = tiles(root)[0]; tick.click(); await settle();
          assert.equal(pending.length,1);
          tick.click(); same(checked(root),['false']);
          pending[0].resolve(apply(pending[0].body)); await settle();
          same(checked(root),['false']); assert.equal(pending.length,2);
          pending[1].resolve(apply(pending[1].body)); await settle();
          same(checked(root),['false']); assert.equal(server.size,0);
        """)

    def test_a_late_initial_read_cannot_erase_a_click_made_while_loading(self):
        self.run_js("""
          const pending = [];
          apiWrite = (path,body) => new Promise(resolve => pending.push({body,resolve}));
          const root = open(plan()); await settle(); assert.equal(pending.length,1);
          tiles(root)[0].click(); same(checked(root),['true']);
          assert.equal(pending.length,1,'requests remain serial while the initial read is pending');
          pending[0].resolve({ticks:[]}); await settle(); same(checked(root),['true']);
          assert.equal(pending.length,2); assert.equal(pending[1].body.changes[0].done,true);
          pending[1].resolve(apply(pending[1].body)); await settle(); assert.equal(server.size,1);
        """)

    def test_a_late_poll_cannot_erase_a_click_and_the_poll_sees_other_devices(self):
        self.run_js("""
          const root = open(plan()); await settle();
          const pending = [];
          apiWrite = (path,body) => new Promise(resolve => pending.push({body,resolve}));
          await poll(); assert.equal(pending.length,1); assert(!pending[0].body.changes);
          tiles(root)[0].click(); same(checked(root),['true']);
          pending[0].resolve({ticks:[]}); await settle(); same(checked(root),['true']);
          assert.equal(pending.length,2);
          pending[1].resolve(apply(pending[1].body)); await settle();
          server.clear();
          apiWrite = async (path,body) => apply(body);
          await poll(); same(checked(root),['false']);
        """)

    def test_a_failed_initial_read_can_retry_without_losing_checked_work(self):
        self.run_js("""
          apiWrite = async () => { throw new Error('Connection lost'); };
          const root = open(plan()); await settle();
          assert(/couldn.t be checked|couldn.t be read/i.test(root.textContent),root.textContent);
          tiles(root)[0].click(); await settle(); same(checked(root),['true']);
          apiWrite = async (path,body) => apply(body);
          root.querySelectorAll('button').find(b => b.textContent === 'Retry').click();
          await settle(); same(checked(root),['true']); assert.equal(server.size,1);
        """)

    def test_pending_changes_finish_saving_after_leaving_the_route(self):
        self.run_js("""
          const root = open(plan()); await settle();
          const pending = [];
          apiWrite = (path,body) => new Promise(resolve => pending.push({body,resolve}));
          tiles(root)[0].click(); await settle();
          tiles(root)[0].click(); same(checked(root),['false']);
          ++routeToken; clear(main); main.append(el('p',{text:'Another page'}));
          pending[0].resolve(apply(pending[0].body)); await settle();
          assert.equal(pending.length,2,'a queued uncheck still reaches the server after navigation');
          pending[1].resolve(apply(pending[1].body)); await settle();
          assert.equal(server.size,0); assert.equal(main.textContent,'Another page');
        """)

    def test_profile_switch_does_not_send_queued_changes_as_the_new_person(self):
        self.run_js("""
          const root = open(plan()); await settle();
          const pending = [];
          apiWrite = (path,body) => new Promise(resolve => pending.push({body,resolve}));
          tiles(root)[0].click(); await settle(); tiles(root)[0].click();
          state.profile = {id:'user1',name:'User1',space:'home',role:'member',plays_as:'wife'};
          pending[0].resolve(apply(pending[0].body)); await settle();
          assert.equal(pending.length,1,'old queued changes cannot be attributed to the new viewer');
          same(checked(root),['false']);
        """)

    def test_selection_changes_during_a_save_keep_old_ticks_and_read_new_tasks(self):
        self.run_js("""
          const root = open(plan()); await settle(); const view = packingProgressView;
          const pending = [];
          apiWrite = (path,body) => new Promise(resolve => pending.push({body,resolve}));
          tiles(root)[0].click(); await settle();
          renderAssemblyPlan(view,plan([item(),item('casual/b')]));
          same(checked(root),['true','false']);
          server.add(view.ticks[1].id);
          pending[0].resolve(apply(pending[0].body)); await settle();
          assert.equal(pending.length,2,'the new selection gets its own scoped read');
          pending[1].resolve(apply(pending[1].body)); await settle();
          same(checked(root),['true','true']); assert.equal(server.size,2);
        """)

    def test_late_tick_save_after_a_failed_preview_cannot_revive_or_mutate_the_old_plan(self):
        self.run_js("""
          const data=plan(), root=open(data); await settle(); const view=packingProgressView;
          let resolveSave,saveBody;
          apiWrite=(path,body) => {
            if (path === '/api/assembly/preview') return Promise.reject(new Error('Could not load the plan'));
            assert.equal(path,'/api/assembly/ticks');
            return new Promise(resolve => { resolveSave=resolve; saveBody=body; });
          };
          const oldTick=tiles(root)[0]; oldTick.click(); await settle();
          assert.equal(oldTick.getAttribute('aria-pressed'),'true'); assert(resolveSave);
          await packRun(view); await settle();
          assert.equal(tiles(root).length,0); assert.equal(view.data,null);
          assert(root.querySelector('.pack-message').textContent.includes('Could not load the plan'));
          resolveSave(apply(saveBody)); await settle();
          assert.equal(server.size,1); assert.equal(tiles(root).length,0);
          assert.equal(oldTick.getAttribute('aria-pressed'),'true','the detached checklist stays untouched');
          assert(root.querySelector('.pack-message').textContent.includes('Could not load the plan'));
          apiWrite=async (path,body) => path === '/api/assembly/preview' ? data : apply(body);
          await packRun(view); await settle();
          same(checked(root),['true']); assert.equal(root.querySelector('.pack-message').textContent,'');
        """)

    def test_outage_retries_automatically_and_hidden_or_departed_pages_do_not_poll(self):
        self.run_js("""
          const root = open(plan()); await settle();
          apiWrite = async () => { throw new Error('Connection lost'); };
          tiles(root)[0].click(); await settle(); assert.equal(server.size,0);
          let requests=0;
          apiWrite = async (path,body) => { requests++; return apply(body); };
          await poll(); assert.equal(server.size,1); same(checked(root),['true']);
          const before=requests; document.hidden=true;
          await poll(); await poll(); assert.equal(requests,before);
          server.clear(); document.hidden=false; document.fire('visibilitychange'); await settle();
          assert(requests>before); same(checked(root),['false']);
          const after=requests; ++routeToken; clear(main);
          await poll(); await poll(); assert.equal(requests,after);
        """)

    def test_clear_undo_cannot_reapply_ticks_to_a_different_selection(self):
        self.run_js("""
          const root=open(plan()); await settle(); const view=packingProgressView;
          tiles(root)[0].click(); await settle(); let undo;
          showToast=(text,options) => { undo=options?.undo; return {close() {}}; };
          root.querySelector('.pack-clear').click(); await settle(); assert.equal(server.size,0);
          renderAssemblyPlan(view,plan([item('casual/b')])); await settle();
          undo(); await settle(); same(checked(root),['false']); assert.equal(server.size,0);
        """)

    def test_clear_and_undo_change_only_visible_tasks(self):
        self.run_js("""
          let root = open(plan([item(),item('casual/b')])); await settle();
          tiles(root).forEach(t => t.click()); await settle(); assert.equal(server.size,2);
          clear(main); root = open(plan()); await settle();
          let undo;
          showToast = (text,options) => { undo=options?.undo; return {close() {}}; };
          root.querySelector('.pack-clear').click(); await settle();
          same(checked(root),['false']); assert.equal(server.size,1);
          assert.equal(typeof undo,'function'); undo(); await settle();
          same(checked(root),['true']); assert.equal(server.size,2);
          clear(main); root = open(plan([item('casual/b')])); await settle(); same(checked(root),['true']);
        """)

    def test_failed_save_keeps_visible_work_and_retry_saves_it(self):
        self.run_js("""
          const root = open(plan()); await settle();
          apiWrite = async () => { throw new Error('Connection lost'); };
          tiles(root)[0].click(); await settle(); same(checked(root),['true']);
          assert.equal(server.size,0);
          assert(/not saved|unsaved|couldn.t save|haven.t been saved/i.test(root.textContent),root.textContent);
          const retry = root.querySelectorAll('button').find(b => /retry/i.test(b.textContent));
          assert(retry);
          apiWrite = async (path,body) => { posts.push(body); return apply(body); };
          retry.click(); await settle(); assert.equal(server.size,1); same(checked(root),['true']);
        """)

    def test_legacy_browser_ticks_cannot_overwrite_server_progress(self):
        self.run_js("""
          saved['decklab.packing.casual/a:target.first'] = JSON.stringify(['casual/a:target|pull|Alpha']);
          const root = open(plan()); await settle(); same(checked(root),['false']);
          assert.equal(server.size,0); assert(posts.every(p => !p.changes?.length));
        """)

    def test_a_departed_route_or_switched_profile_ignores_late_reads(self):
        self.run_js("""
          const pending = [];
          apiWrite = (path,body) => new Promise(resolve => pending.push({body,resolve}));
          const old = open(plan()); await settle(); assert.equal(pending.length,1);
          ++routeToken; clear(main); main.append(el('p',{text:'Another page'}));
          pending[0].resolve({ticks:pending[0].body.ids}); await settle();
          assert.equal(main.textContent,'Another page'); same(checked(old),['false']);
          const root = open(plan()); await settle(); assert.equal(pending.length,2);
          state.profile = {id:'user1',name:'User1',space:'home',role:'member',plays_as:'wife'};
          pending[1].resolve({ticks:pending[1].body.ids}); await settle(); same(checked(root),['false']);
        """)
