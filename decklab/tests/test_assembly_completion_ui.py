"""Build completion from the packing checklist, with no server or inventory writes."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = """
  clear(main);
  window.matchMedia('(min-width: 1000px)').matches = true;
  state.profile = {id:'matt', name:'Matt', plays_as:'user', role:'admin', space:'home'};
  state.profiles = [state.profile];
  location.hash = '#/assembly';
  const saved = {};
  window.localStorage = {
    getItem: key => saved[key] ?? null,
    setItem: (key, value) => { saved[key] = String(value); },
    removeItem: key => { delete saved[key]; }
  };
  const item = (id='casual/a', version='target') => ({
    id, title:id === 'casual/a' ? 'Elves' : 'Burn', version,
    sleeves:null, kit:null, sleeves_need:null, tokens:null, basics:[], returns:[],
    steps:[{name:'Alpha', need:2, keep:0, storage:2, transfers:[], waiting:0, missing:0}],
    completion:{status:'building', built_version:null, sha256:'a'.repeat(64),
      editable:true, already_built:false}
  });
  const plan = (decks=[item()], fingerprint='first-plan') => ({
    choices:decks.map(d => ({id:d.id, title:d.title, status:'building', versions:['target','owned']})),
    decks, rows:[], ready:true, counts_confirmed:true, unresolved:[], warnings:[],
    note:'A plan.', token_note:'', totals:{waiting:0, missing:0}, tokens:[], token_plan:[],
    cards:{Alpha:{...alpha, img:'/img/a/1/normal', img_small:'/img/a/1/small'}},
    completion:{fingerprint, can_mark_built:true, reason:null,
      decks:decks.map(({id,title,version}) => ({id,title,version}))}
  });
  const completed = data => ({...data, completion:{fingerprint:'completed-plan',
    can_mark_built:false, reason:'These decks are already built.', decks:[]},
    decks:data.decks.map(d => ({...d,
      completion:{...d.completion, status:'built', built_version:d.version, already_built:true},
      steps:d.steps.map(s => ({...s, keep:s.need, storage:0, transfers:[]}))}))});
  const builtButton = () => main.querySelector('.pack-built');
  const ticks = () => main.querySelectorAll('.pack-tick');
  const checked = () => ticks().map(t => t.getAttribute('aria-pressed'));
  const checkCards = () => ticks().forEach(t => t.click());
  const settle = async () => { for (let i=0; i<32; i++) await null; };
  const serverTicks = new Set();
  const mockApi = handler => {
    apiWrite = async (path,body) => {
      if (path === '/api/assembly/ticks') {
        for (const change of body.changes || []) {
          if (change.done) serverTicks.add(change.id); else serverTicks.delete(change.id);
        }
        return {ticks:body.ids.filter(id => serverTicks.has(id))};
      }
      return handler(path,body);
    };
  };
  mockApi(() => { throw new Error('Unexpected request'); });
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyCompletionUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_owned_list_completes_here_and_duplicate_clicks_do_not_save_twice(self):
        self.run_js("""
          const data = plan([item('casual/a','owned')]);
          const posts = []; let resolveSave;
          mockApi((path, body) => {
            posts.push([path,body]);
            return new Promise(resolve => { resolveSave = resolve; });
          });
          drawAssembly(data, routeToken); await settle();
          assert.equal(builtButton().textContent, 'Mark as built');
          assert.equal(builtButton().disabled, true);
          builtButton().click(); assert.equal(posts.length, 0);
          checkCards(); await settle(); assert.equal(builtButton().disabled, false);
          const originalTiles = ticks();
          builtButton().click(); builtButton().click();
          assert.equal(posts.length, 1);
          assert.equal(builtButton().disabled, true);
          same(posts[0], ['/api/assembly/built', {decks:[{id:'casual/a',version:'owned'}],
            fingerprint:'first-plan', confirmed:true}]);
          resolveSave({saved:true, built:data.completion.decks, plan:completed(data), warnings:[], tables:{}});
          await settle();
          assert.equal(location.hash, '#/assembly');
          assert.equal(ticks().length, originalTiles.length);
          same(checked(), ['true']);
          assert(!builtButton() || builtButton().disabled);
          assert(/built/i.test(main.textContent));
        """)

    def test_multiple_decks_finish_together_and_keep_the_original_checked_tasks(self):
        self.run_js("""
          const data = plan([item(),item('casual/b','owned')]);
          const posts = [];
          mockApi(async (path,body) => {
            posts.push([path,body]);
            return {saved:true,built:data.completion.decks,plan:completed(data),warnings:[],tables:{}};
          });
          drawAssembly(data,routeToken); await settle();
          assert.equal(builtButton().textContent,'Mark 2 decks built');
          ticks()[0].click(); await settle(); assert.equal(builtButton().disabled,true);
          ticks()[1].click(); await settle(); assert.equal(builtButton().disabled,false);
          builtButton().click(); await settle();
          same(posts.map(p => p[1].decks), [[{id:'casual/a',version:'target'},{id:'casual/b',version:'owned'}]]);
          same(checked(),['true','true']);
          assert.equal(main.querySelectorAll('.pack-deck').length,2);
          assert.equal(location.hash,'#/assembly');
          assert(!builtButton() || builtButton().disabled);
        """)

    def test_saved_decks_stay_built_when_table_refresh_reports_a_problem(self):
        self.run_js("""
          const data = plan();
          mockApi(async () => ({saved:true,built:data.completion.decks,plan:completed(data),
            warnings:[],tables:{error:'Another deck has no availability table.'}}));
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle(); builtButton().click(); await settle();
          assert(main.textContent.includes('Elves is now marked built.'));
          assert(main.textContent.includes('availability tables could not be updated'));
          assert(main.textContent.includes('Another deck has no availability table.'));
          assert.equal(main.querySelectorAll('a').find(link=>link.textContent==='Tables out of date').getAttribute('href'),TABLES_HREF);
          assert(!builtButton());
          same(checked(),['true']);
        """)

    def test_ready_deck_without_card_tasks_can_be_completed(self):
        self.run_js("""
          const deck = item(); deck.steps = [];
          const data = plan([deck]); let posts = 0;
          mockApi(async () => { posts++; return {saved:true,built:data.completion.decks,
            plan:completed(data),warnings:[],tables:{}}; });
          drawAssembly(data,routeToken); await settle();
          assert.equal(ticks().length,0);
          assert.equal(builtButton().disabled,false);
          builtButton().click(); await settle();
          assert.equal(posts,1);
          assert(main.textContent.includes('Elves is now marked built.'));
        """)

    def test_completion_waits_for_shared_ticks_to_load_and_save_successfully(self):
        self.run_js("""
          const pending = [];
          apiWrite = (path,body) => {
            assert.equal(path,'/api/assembly/ticks');
            return new Promise((resolve,reject) => pending.push({body,resolve,reject}));
          };
          drawAssembly(plan(),routeToken); await settle();
          checkCards(); await settle();
          assert.equal(builtButton().disabled,true,'initial progress is still loading');
          pending[0].resolve({ticks:[]}); await settle();
          assert.equal(pending.length,2); assert.equal(builtButton().disabled,true,'tick save is pending');
          pending[1].reject(new Error('Connection lost')); await settle();
          assert.equal(builtButton().disabled,true,'unsaved ticks cannot finish a shared plan');
          main.querySelectorAll('button').find(b => b.textContent === 'Retry').click(); await settle();
          pending[2].resolve({ticks:pending[2].body.ids}); await settle();
          same(checked(),['true']); assert.equal(builtButton().disabled,false);
        """)

    def test_failed_completion_keeps_ticks_and_offers_a_fresh_plan(self):
        self.run_js("""
          const data = plan(); const posts = [];
          mockApi(async (path,body) => {
            posts.push([path,body]);
            if (path === '/api/assembly/built') throw new Error('The plan changed. Refresh the plan.');
            return plan([item()], 'updated-plan');
          });
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle(); builtButton().click(); await settle();
          assert(main.textContent.includes('The plan changed. Refresh the plan.'));
          same(checked(),['true']);
          const refresh = main.querySelectorAll('button').find(b => b.textContent === 'Refresh plan');
          assert(refresh); refresh.click(); await settle();
          assert.equal(posts.at(-1)[0],'/api/assembly/preview');
          same(checked(),['true']);
          assert.equal(builtButton().disabled,false);
          assert.equal(location.hash,'#/assembly');
        """)

    def test_changing_the_selected_list_disables_completion_before_preview_returns(self):
        self.run_js("""
          const data = plan(); const posts = []; let resolvePreview;
          mockApi((path,body) => {
            posts.push([path,body]);
            return new Promise(resolve => { resolvePreview = resolve; });
          });
          drawAssembly(data,routeToken); await settle(); checkCards(); await settle();
          assert.equal(builtButton().disabled,false);
          const owned = main.querySelectorAll('button').find(b => b.textContent === 'Play-now list');
          owned.click();
          assert.equal(builtButton().disabled,true);
          builtButton().click(); assert.equal(posts.length,0);
          flushTimers(); await settle();
          assert.equal(builtButton().disabled,true);
          same(posts,[['/api/assembly/preview',{decks:[{id:'casual/a',version:'owned'}]}]]);
          resolvePreview(plan([item('casual/a','owned')],'owned-plan')); await settle();
          same(checked(),['false']); assert.equal(builtButton().disabled,true);
        """)

    def test_unavailable_or_read_only_plans_cannot_complete_even_with_checked_cards(self):
        self.run_js("""
          const posts = []; mockApi(async (...args) => { posts.push(args); });
          for (const mode of ['missing','readonly']) {
            clear(main); const data = plan([item()],mode);
            data.completion.can_mark_built = false;
            data.completion.reason = mode === 'missing' ? 'Some cards are still missing.' : 'Only the owner may build this deck.';
            if (mode === 'missing') { data.ready=false; data.totals.missing=1; }
            else { data.decks[0].completion.editable=false; }
            drawAssembly(data,routeToken); await settle(); checkCards(); await settle();
            assert(main.textContent.includes(data.completion.reason));
            assert(!builtButton() || builtButton().disabled);
            if (builtButton()) builtButton().click();
          }
          assert.equal(posts.length,0);
        """)

    def test_sleeve_ticks_are_optional_and_unchanged_card_tasks_survive_new_fingerprints(self):
        self.run_js("""
          const data = plan();
          data.decks[0].sleeves='red'; data.decks[0].sleeves_need=2;
          data.decks[0].kit={sleeves:{state:'text',value:'red',label:'red'},deck_box:null,need:2,warnings:[]};
          drawAssembly(data,routeToken); await settle();
          const other = main.querySelectorAll('[data-pack-tick]').filter(t => t.tag === 'input');
          assert(other.length); assert(other.every(t => !t.checked));
          checkCards(); await settle(); assert.equal(builtButton().disabled,false);
          clear(main); drawAssembly(data,routeToken); await settle();
          same(checked(),['true']); assert.equal(builtButton().disabled,false);
          const storage = main.querySelectorAll('button').find(b => b.textContent === 'Storage order');
          storage.click(); same(checked(),['true']); assert.equal(builtButton().disabled,false);
          clear(main); drawAssembly({...data,completion:{...data.completion,fingerprint:'unrelated-revision'}},routeToken);
          await settle(); same(checked(),['true']); assert.equal(builtButton().disabled,false);
          clear(main); const changed = plan(); changed.decks[0].steps[0].storage = 3;
          drawAssembly(changed,routeToken); await settle();
          same(checked(),['false']); assert.equal(builtButton().disabled,true);
        """)
