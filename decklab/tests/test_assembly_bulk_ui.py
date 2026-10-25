"""Scoped bulk packing progress through real UI functions, without live builds."""
import unittest

from decklab.tests import test_assembly_progress_ui as progress_tests
from decklab.tests.test_workspace_ui import NODE


HELPERS = """
  state.may = {admin:true, accessories:true, see_accessories:true, see_inventory:['home']};
  const panels = root => root.querySelectorAll('.pack-deck');
  const bulk = panel => panel.querySelector('.pack-bulk-tick');
  const cardRows = (names=['Alpha','Beta','Gamma']) => names.map(name =>
    ({name,keep:0,storage:1,transfers:[],waiting:0,missing:0}));
  let undo = null;
  showToast = (text, options) => { undo=options?.undo; return {close() {}}; };
  const changes = () => posts.filter(p => p.changes?.length);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyBulkUiTests(unittest.TestCase):
    def run_js(self, scenario):
        progress_tests.AssemblyProgressUiTests.run_js(self, HELPERS + scenario)

    def test_named_list_scope_checks_its_card_actions_and_leaves_other_steps_and_decks(self):
        self.run_js("""
          const deck = item('casual/a',{title:'Elves',version:'owned',
            steps:[{name:'Alpha',keep:0,storage:2,transfers:[],waiting:0,missing:0},
              {name:'Beta',keep:0,storage:0,transfers:[{from:'casual/donor',from_title:'Donor',quantity:1}],waiting:0,missing:0},
              {name:'Unowned',keep:0,storage:0,transfers:[],waiting:1,missing:2}],
            basics:[{name:'Forest',quantity:3}],returns:[{name:'Old card',quantity:1}],
            standins:{rows:[{for:'Ghost',qty:2,using:''}]},sleeves:'Red',sleeves_need:9,
            kit:{need:9,warnings:[],sleeves:{id:'red',label:'Red',state:'linked',quantity:100},
              deck_box:{id:'box',label:'Box',state:'linked',quantity:1}},
            tokens:{needs:[{name:'Elf',state:'ready',cards:[{front:'Elf',quantity:1,side:'front'}]}]}});
          const root=open(plan([deck,item('casual/b')])); await settle();
          const first=panels(root)[0], second=panels(root)[1];
          assert(first.querySelector('.pack-bulk-scope').textContent.includes('Play-now list: 5 card checks (9 cards)'));
          assert(first.querySelector('.pack-bulk-scope').textContent.includes('All listed sections, including any sideboard'));
          assert(bulk(first).getAttribute('aria-label').includes('Elves (Play-now list)'));
          const optional=first.querySelectorAll('[data-pack-tick]').filter(n => n.tag === 'input');
          assert.equal(optional.length,3);
          bulk(first).click(); await settle();
          assert(tiles(first).every(n => n.getAttribute('aria-pressed') === 'true'));
          same(checked(second),['false']); assert(optional.every(n => !n.checked));
          assert(first.querySelectorAll('.assembly-pending').some(n => /Wait for 1/.test(n.textContent) && n.textContent.includes('Unowned')));
          assert(first.querySelectorAll('.assembly-pending').some(n => /Unavailable: 2/.test(n.textContent) && n.textContent.includes('Unowned')));
          assert.equal(changes().length,1); assert.equal(changes()[0].changes.length,5);
          assert(changes()[0].changes.every(c => c.done)); assert.equal(server.size,5);
          assert.equal(bulk(first).textContent,'All card checks ticked'); assert(bulk(first).disabled);
          bulk(first).click(); await settle(); assert.equal(changes().length,1);
        """)

    def test_bulk_and_undo_preserve_existing_checks_other_decks_and_later_individual_edits(self):
        self.run_js("""
          const root=open(plan([item('casual/a',{steps:cardRows()}),item('casual/b')])); await settle();
          const [first,second]=panels(root), cards=tiles(first);
          cards[0].click(); tiles(second)[0].click(); await settle();
          posts.length=0; bulk(first).click(); await settle();
          assert.equal(changes().length,1); assert.equal(changes()[0].changes.length,2);
          cards[1].click(); await settle(); cards[1].click(); await settle();
          assert.equal(typeof undo,'function'); undo(); await settle();
          same(checked(first),['true','true','false']); same(checked(second),['true']);
          assert.equal(server.size,3);
          assert.equal(changes().at(-1).changes.length,1,'Undo changes only untouched bulk additions');
        """)

    def test_undo_can_overlay_its_in_flight_save_without_a_stale_ack_rechecking_cards(self):
        self.run_js("""
          const root=open(plan([item('casual/a',{steps:cardRows()})])); await settle();
          const pending=[];
          apiWrite=(path,body) => new Promise(resolve => pending.push({body,resolve}));
          bulk(panels(root)[0]).click(); await settle();
          assert.equal(pending.length,1); assert.equal(pending[0].body.changes.length,3);
          undo(); same(checked(root),['false','false','false']);
          pending[0].resolve(apply(pending[0].body)); await settle();
          same(checked(root),['false','false','false']); assert.equal(pending.length,2);
          assert(pending[1].body.changes.every(c => !c.done));
          pending[1].resolve(apply(pending[1].body)); await settle();
          assert.equal(server.size,0); same(checked(root),['false','false','false']);
        """)

    def test_bulk_waits_for_initial_read_pending_save_and_background_poll(self):
        self.run_js("""
          const pending=[];
          apiWrite=(path,body) => new Promise(resolve => pending.push({body,resolve}));
          const root=open(plan([item('casual/a',{steps:cardRows()})])); await settle();
          const button=bulk(panels(root)[0]), view=packingProgressView;
          assert(button.disabled); button.click(); assert.equal(pending.length,1);
          pending[0].resolve(apply(pending[0].body)); await settle(); assert(!button.disabled);
          tiles(root)[0].click(); await settle(); assert(button.disabled);
          button.click(); assert.equal(pending.length,2);
          pending[1].resolve(apply(pending[1].body)); await settle(); assert(!button.disabled);
          packSync(view); await settle(); assert(button.disabled,'poll in flight disables bulk');
          button.click(); assert.equal(pending.length,3);
          pending[2].resolve(apply(pending[2].body)); await settle(); assert(!button.disabled);
        """)

    def test_failed_shared_save_retains_marks_but_blocks_bulk_undo_and_build_until_retry(self):
        self.run_js("""
          const data=plan([item('casual/a',{steps:cardRows()})]);
          data.completion={fingerprint:'current',can_mark_built:true,decks:[{id:'casual/a',title:'A',version:'target'}]};
          const root=open(data); await settle();
          apiWrite=async () => { throw new Error('Offline'); };
          bulk(panels(root)[0]).click(); await settle();
          same(checked(root),['true','true','true']); assert.equal(server.size,0);
          assert(bulk(panels(root)[0]).disabled); assert(root.querySelector('.pack-built').getAttribute('aria-disabled') === 'true');
          undo(); await settle(); same(checked(root),['true','true','true']);
          apiWrite=async (path,body) => { posts.push(body); return apply(body); };
          root.querySelectorAll('button').find(b => b.textContent === 'Retry').click(); await settle();
          assert.equal(server.size,3); assert(root.querySelector('.pack-built').getAttribute('aria-disabled') === 'false');
          undo(); await settle(); same(checked(root),['false','false','false']);
          assert(root.querySelector('.pack-built').getAttribute('aria-disabled') === 'true');
        """)

    def test_bulk_and_undo_are_inert_during_preview_review_and_build_save(self):
        self.run_js("""
          const root=open(plan([item('casual/a',{steps:cardRows()})])); await settle();
          const view=packingProgressView, button=bulk(panels(root)[0]);
          for (const flag of ['previewing','reviewing','saving']) {
            view[flag]=true; packProgress(view); assert(button.disabled);
            button.fire('click'); await settle(); assert.equal(changes().length,0);
            view[flag]=false; packProgress(view); assert(!button.disabled);
          }
          button.click(); await settle(); const count=changes().length;
          for (const flag of ['previewing','reviewing','saving']) {
            view[flag]=true; packProgress(view); undo(); await settle();
            assert.equal(changes().length,count); same(checked(root),['true','true','true']);
            view[flag]=false; packProgress(view);
          }
        """)

    def test_sort_keeps_undo_but_detached_buttons_and_changed_lists_are_inert(self):
        self.run_js("""
          const data=plan([item('casual/a',{steps:cardRows()})]), root=open(data); await settle();
          const old=bulk(panels(root)[0]), view=packingProgressView;
          old.click(); await settle(); const oldUndo=undo;
          root.querySelector('.pack-sort').querySelectorAll('button').find(b => b.textContent === 'Storage order').click();
          await settle(); tiles(root)[0].click(); await settle();
          const before=changes().length, snapshot=checked(root);
          old.fire('click'); await settle();
          assert.equal(changes().length,before); assert.equal(JSON.stringify(checked(root)),JSON.stringify(snapshot));
          oldUndo(); await settle(); same(checked(root),['false','false','false']);
          bulk(panels(root)[0]).click(); await settle(); assert.equal(server.size,3);
          const currentUndo=undo;
          renderAssemblyPlan(view,plan([item('casual/a',{version:'owned',steps:cardRows()})])); await settle();
          currentUndo(); await settle(); same(checked(root),['false','false','false']);
        """)

    def test_old_controls_ignore_profile_changes_navigation_and_replacement_data(self):
        self.run_js("""
          for (const mode of ['profile','route','data']) {
            clear(main); state.profile={id:'matt',name:'Matt',space:'home',role:'admin',plays_as:'user'};
            const root=open(plan([item('casual/a',{steps:cardRows()})])); await settle();
            const button=bulk(panels(root)[0]), view=packingProgressView;
            button.click(); await settle(); const oldUndo=undo;
            tiles(root)[0].click(); await settle(); const before=changes().length, snapshot=checked(root);
            if (mode === 'profile') state.profile={id:'user1',name:'User1',space:'home',role:'member',plays_as:'wife'};
            if (mode === 'route') ++routeToken;
            if (mode === 'data') view.data={...view.data};
            button.fire('click'); oldUndo(); await settle();
            assert.equal(changes().length,before,mode); assert.equal(JSON.stringify(checked(root)),JSON.stringify(snapshot));
            server.clear();
          }
        """)

    def test_empty_or_waiting_only_decks_have_no_visible_bulk_action(self):
        self.run_js("""
          const root=open(plan([item('casual/a',{steps:[]}),item('casual/b',{steps:[
            {name:'Alpha',keep:2,storage:0,transfers:[],waiting:1,missing:2}]})])); await settle();
          assert.equal(tiles(root).length,0);
          assert(root.querySelectorAll('.pack-bulk').every(node => node.hidden));
          root.querySelectorAll('.pack-bulk-tick').forEach(button => button.fire('click'));
          await settle(); assert.equal(changes().length,0);
        """)

    def test_duplicate_task_ids_are_counted_and_patched_once(self):
        self.run_js("""
          const root=open(plan([item('casual/a',{steps:cardRows(['Alpha','Alpha'])})])); await settle();
          const first=panels(root)[0];
          assert(first.querySelector('.pack-bulk-scope').textContent.includes('1 card check (1 card)'));
          bulk(first).click(); await settle();
          assert.equal(changes().length,1); assert.equal(changes()[0].changes.length,1);
          same(checked(first),['true','true']);
        """)

    def test_concurrent_deck_bulk_patches_preserve_both_devices_changes(self):
        self.run_js("""
          const data=plan([item('casual/a',{steps:cardRows()}),item('casual/b',{steps:cardRows()})]);
          const first=open(data), firstView=packingProgressView;
          const second=open(data), secondView=packingProgressView; await settle();
          const pending=[];
          apiWrite=(path,body) => new Promise(resolve => pending.push({body,resolve}));
          bulk(panels(first)[0]).click(); bulk(panels(second)[1]).click(); await settle();
          assert.equal(pending.length,2); assert(pending.every(p => p.body.changes.length === 3));
          for (const call of pending.splice(0).reverse()) call.resolve(apply(call.body));
          await settle(); assert.equal(server.size,6);
          apiWrite=async (path,body) => apply(body);
          await packSync(firstView); await packSync(secondView);
          same(checked(first),Array(6).fill('true')); same(checked(second),Array(6).fill('true'));
        """)

    def test_bulk_does_not_bypass_missing_inventory_permission_or_separate_final_review(self):
        self.run_js("""
          for (const mode of ['missing','warnings','readonly','review']) {
            clear(main); server.clear();
            const data=plan([item('casual/a',{steps:cardRows()})]);
            data.completion={fingerprint:mode,can_mark_built:mode === 'review',
              reason:mode,decks:[{id:'casual/a',title:'A',version:'target'}],review:mode === 'review'};
            if (mode === 'missing') { data.ready=false; data.totals.missing=2; }
            if (mode === 'warnings') { data.counts_confirmed=false; data.warnings=['Inventory unavailable']; }
            if (mode === 'readonly') data.decks[0].completion={editable:false};
            let builds=0,reviews=0;
            apiWrite=async (path,body) => { if (path === '/api/assembly/ticks') return apply(body); builds++; throw new Error('Unexpected build'); };
            packReviewBuilt=async () => { reviews++; return null; };
            const root=open(data); await settle(); bulk(panels(root)[0]).click(); await settle();
            same(checked(root),['true','true','true']); assert.equal(builds,0);
            const finish=root.querySelector('.pack-built');
            assert.equal(finish.getAttribute('aria-disabled') === 'true',mode !== 'review'); finish.click(); await settle();
            assert.equal(builds,0); assert.equal(reviews,mode === 'review' ? 1 : 0);
          }
        """)
