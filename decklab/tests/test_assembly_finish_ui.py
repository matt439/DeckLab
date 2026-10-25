"""Finish guidance is view-only until the original complete-plan save guard accepts it."""
import unittest

from decklab.tests import test_assembly_completion_ui as completion
from decklab.tests.test_workspace_ui import NODE, WEB


SETUP = """
  const openFinish = (decks=[item()]) => { drawAssembly(plan(decks),routeToken);return packingProgressView; };
  const two = () => { const a=item(),b=item('casual/b','owned');
    a.title=b.title='Same deck title';a.steps[0].storage=3;b.steps[0].storage=1;return [a,b]; };
  const reason = v => v.finish.message;
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyFinishUiTests(unittest.TestCase):
    def run_js(self, scenario):
        completion.AssemblyCompletionUiTests.run_js(self, SETUP + scenario)

    def test_copy_meter_is_global_and_optional_steps_have_separate_task_units(self):
        self.run_js("""
          window.matchMedia('(min-width: 1000px)').matches=false;const decks=two();
          decks[0].kit={sleeves:{state:'linked',id:'fixture-sleeves',label:'Fixture sleeves'}};decks[0].sleeves_need=99;
          const v=openFinish(decks);await settle();v.ticks.find(t=>t.tile).node.click();await settle();
          const p=v.bar.progress;assert.equal(p.copies.textContent,'3 / 4');assert.equal(p.meter.getAttribute('max'),'4');
          assert.equal(p.meter.getAttribute('value'),'3');assert.equal(p.other.textContent,'0 of 1 other step');
          assert(p.spoken.textContent.includes('Pulled 3 of 4 cards'));assert(v.switcher.panels[1].node.hidden);
          v.ticks.find(t=>t.tile&&!t.done).node.click();await settle();assert(packCanFinish(v));assert(!builtBlocked());
          assert.equal(p.copies.textContent,'4 / 4');assert.equal(p.other.textContent,'0 of 1 other step');
          assert.equal(p.state.textContent,'');assert.equal(p.meter.getAttribute('aria-hidden'),'true');
        """)

    def test_zero_card_tasks_show_no_meter_or_zero_denominator_but_can_finish(self):
        self.run_js("""
          const d=item();d.steps=[];const data=plan([d]);let body;
          mockApi(async(path,payload)=>{assert.equal(path,'/api/assembly/built');body=payload;
            return {built:data.completion.decks,plan:completed(data),warnings:[],tables:{}};});
          drawAssembly(data,routeToken);await settle();const v=packingProgressView,p=v.bar.progress;
          assert(p.cards.hidden);assert.equal(p.copies.textContent,'');assert.equal(p.meter.getAttribute('max'),null);
          assert.equal(p.meter.getAttribute('value'),null);assert.equal(p.state.textContent,'Nothing to tick in this plan.');
          assert(packCanFinish(v));builtButton().click();await settle();
          same(body,{decks:[{id:'casual/a',version:'target'}],fingerprint:'first-plan',confirmed:true});
        """)

    def test_blocked_primary_is_focusable_and_reveals_original_hidden_duplicate_task(self):
        self.run_js("""
          window.matchMedia('(min-width: 1000px)').matches=false;const v=openFinish(two());await settle();
          v.ticks[0].node.click();await settle();const original=v.ticks[1].node,ids=v.ticks.map(t=>t.id),data=v.data;
          const calls=[];mockApi((path,body)=>{calls.push([path,body]);throw new Error('guidance must not request');});
          const button=builtButton();assert(!button.disabled);assert.equal(button.getAttribute('aria-disabled'),'true');
          assert.equal(button.getAttribute('aria-describedby'),reason(v).id);button.focus();assert(document.activeElement===button);
          button.click();assert(document.activeElement===original);assert(!v.switcher.panels[1].node.hidden);
          assert.equal(v.switcher.active,packParticipantKey(v.switcher.panels[1].deck));
          assert.equal(v.switcher.panels[1].deck.version,'owned');assert(v.data===data);same(v.ticks.map(t=>t.id),ids);
          assert(!v.ticks[1].done);assert(v.ticks[1].node===original);same(calls,[]);
        """)

    def test_polling_retains_focused_reason_meter_primary_and_allows_ready_read_only_poll(self):
        self.run_js("""
          const v=openFinish();await settle();checkCards();await settle();const p=v.bar.progress,button=builtButton(),message=reason(v);
          message.focus();let resolvePoll;apiWrite=(path,body)=>new Promise(resolve=>{assert.equal(path,'/api/assembly/ticks');
            resolvePoll=()=>resolve({ticks:body.ids});});
          const pending=packSync(v);assert(v.progress.busy);assert(packCanFinish(v));assert(!builtBlocked());
          assert(v.bar.progress===p&&p.meter.isConnected&&reason(v)===message&&builtButton()===button);
          assert(document.activeElement===message);resolvePoll();await pending;await settle();
          assert(v.bar.progress===p&&reason(v)===message&&builtButton()===button);assert(document.activeElement===message);
          assert.equal(p.copies.textContent,'2 / 2');assert.equal(p.meter.getAttribute('value'),'2');
        """)

    def test_ordered_loading_pending_saving_and_server_reasons_only_receive_focus(self):
        self.run_js("""
          const v=openFinish();await settle();const calls=[];mockApi((p,b)=>{calls.push([p,b]);throw new Error('no activation');});
          v.progress.loaded=false;packProgress(v);builtButton().click();assert(document.activeElement===reason(v));
          assert.equal(reason(v).textContent,'Loading shared progress.');v.progress.loaded=true;
          v.progress.pending.set('fixture',{done:true});packProgress(v);builtButton().click();
          assert.equal(reason(v).textContent,'Saving shared progress.');assert(document.activeElement===reason(v));v.progress.pending.clear();
          packSaving(v,true);assert(!builtButton().disabled);builtButton().click();assert(document.activeElement===reason(v));
          assert.equal(reason(v).textContent,'Marking built.');packSaving(v,false);
          v.previewing=true;packProgress(v);builtButton().click();assert(document.activeElement===reason(v));
          assert.equal(reason(v).textContent,'Updating the plan.');v.previewing=false;
          v.data.completion.can_mark_built=false;v.data.completion.reason='Inventory fixture needs attention.';packProgress(v);
          builtButton().click();assert.equal(reason(v).textContent,'Inventory fixture needs attention.');
          assert(document.activeElement===reason(v));same(calls,[]);
        """)

    def test_retry_and_refresh_are_resolved_fresh_and_focused_without_activation(self):
        self.run_js("""
          const v=openFinish();await settle();let calls=0;apiWrite=async()=>{calls++;throw new Error('no requests');};
          v.progress.error='Fixture unavailable';packProgressNotice(v);packProgress(v);const retry=v.progressNote.querySelector('button');
          builtButton().click();assert(document.activeElement===retry);assert.equal(calls,0);
          v.previewing=true;packProgress(v);builtButton().click();assert(document.activeElement===reason(v));
          assert.equal(reason(v).textContent,'Updating the plan.');v.previewing=false;
          v.finishError='Fixture plan changed';packFinishError(v);packProgress(v);const refresh=v.finish.error.querySelector('button');
          builtButton().click();assert(document.activeElement===refresh);assert.equal(calls,0);
          packSaving(v,true);builtButton().click();assert(document.activeElement===reason(v));assert.equal(calls,0);packSaving(v,false);
          packFinishError(v);const fresh=v.finish.error.querySelector('button');assert(fresh!==refresh);
          builtButton().click();assert(document.activeElement===fresh);assert.equal(calls,0);
        """)

    def test_stale_busy_modal_profile_route_and_replaced_plan_controls_cannot_save_or_steal_focus(self):
        self.run_js("""
          for(const mode of ['profile','route','permission','old-control','old-plan','reviewing','dialog']){
            clear(main);state.profile={id:'matt',role:'admin',space:'home'};state.may=null;const v=openFinish();await settle();
            const old=builtButton();let calls=0;mockApi(()=>{calls++;throw new Error('refused');});
            const outside=el('button',{text:'Current place'});main.append(outside);outside.focus();let dialog;
            if(mode==='profile')state.profile={id:'user1'};if(mode==='route')++routeToken;
            if(mode==='permission')state.may={see_home_records:false};if(mode==='reviewing')v.reviewing=true;
            if(mode==='old-control')renderAssemblyPlan(v,v.data);if(mode==='old-plan')v.data={...v.data};
            if(mode==='dialog')dialog=openSheet('Current modal');old.click();
            assert.equal(calls,0,mode);assert(document.activeElement===outside,mode);dialog?.close();
          }
        """)

    def test_deferred_hidden_task_reveal_never_moves_later_focus_or_new_route(self):
        self.run_js("""
          for(const mode of ['focus','profile','route','new-plan','dialog','saving','disposed']){
            clear(main);serverTicks.clear();state.profile={id:'matt',role:'admin',space:'home'};state.may=null;
            window.matchMedia('(min-width: 1000px)').matches=false;const v=openFinish(two());await settle();
            v.ticks[0].node.click();await settle();const frames=[];requestAnimationFrame=fn=>frames.push(fn);
            builtButton().click();const target=v.ticks[1].node,scrolled=target.scrolled;assert(document.activeElement===target);
            const outside=el('button',{text:'New focus'});main.append(outside);let dialog;
            if(mode==='focus')outside.focus();if(mode==='profile')state.profile={id:'user1'};if(mode==='route')++routeToken;
            if(mode==='new-plan')renderAssemblyPlan(v,{...v.data});if(mode==='dialog')dialog=openSheet('New modal');
            if(mode==='saving')v.saving=true;if(mode==='disposed')packDisposeSwitcher(v);const active=document.activeElement;
            frames.forEach(fn=>fn());assert(document.activeElement===active,mode);assert.equal(target.scrolled,scrolled,mode);dialog?.close();
          }
        """)

    def test_bar_mount_stays_in_plan_column_and_outside_results_only_task_scope(self):
        self.run_js("""
          window.matchMedia('(min-width: 1000px)').matches=false;const v=openFinish(two());await settle();
          assert(v.bar.node.parentNode===v.planMain);assert(v.results.parentNode===v.planMain);
          assert(v.root.contains(v.bar.node));assert(!v.results.contains(v.bar.node));assert(!v.planMain.contains(v.chooserSlot));
          const ids=v.ticks.map(t=>t.id),scope=v.progress.scope;
          v.bar.node.append(el('input',{'data-pack-tick':'outside-results-fixture','data-pack-count':'99'}));
          wirePackTicks(v);assert.equal(v.ticks.length,2);same(v.ticks.map(t=>t.id),ids);assert.equal(v.progress.scope,scope);
          assert(v.switcher.panels.every(p=>p.node.isConnected));assert(v.switcher.panels[1].node.hidden);
        """)

    def test_ordinary_and_empty_redraw_remove_old_bar_without_leaving_extra_controls(self):
        self.run_js("""
          const v=openFinish();await settle();const old=v.bar,button=v.finish.button,meter=old.progress.meter;
          renderAssemblyPlan(v,{...v.data});assert(!old.node.isConnected);assert(!button.isConnected);assert(!meter.isConnected);
          assert(v.bar!==old);assert(v.bar.node.parentNode===v.planMain);assert.equal(v.root.querySelectorAll('.action-bar').length,1);
          const fresh=v.bar;renderAssemblyPlan(v,{...v.data,decks:[],completion:{...v.data.completion,decks:[]}});
          assert(!fresh.node.isConnected);assert.equal(v.bar,null);assert.equal(v.finish,null);
          assert.equal(v.root.querySelectorAll('.action-bar').length,0);assert.equal(v.ticks.length,0);assert(v.results.textContent.includes('Choose the decks'));
        """)

    def test_current_preview_error_clears_bar_but_stale_error_cannot_remove_new_plan_bar(self):
        self.run_js("""
          const v=openFinish();await settle();const data=v.data,previews=[];
          apiWrite=(path,body)=>{if(path==='/api/assembly/ticks')return Promise.resolve({ticks:[]});
            assert.equal(path,'/api/assembly/preview');return new Promise((resolve,reject)=>previews.push({resolve,reject}));};
          const oldRun=v.run(),newRun=v.run();previews[1].resolve({...data,selections:v.selected});await newRun;await settle();
          const fresh=v.bar;previews[0].reject(new Error('Stale fixture failure'));await oldRun;
          assert(v.bar===fresh&&fresh.node.isConnected);assert(!v.message.textContent.includes('Stale fixture'));
          const button=v.finish.button,failed=v.run();previews[2].reject(new Error('Current fixture failure'));await failed;await settle();
          assert(!fresh.node.isConnected);assert.equal(v.bar,null);assert.equal(v.finish,null);assert.equal(v.data,null);
          assert.equal(v.root.querySelectorAll('.action-bar').length,0);assert.equal(v.ticks.length,0);
          assert.equal(v.message.textContent,'Current fixture failure');const place=el('button',{text:'Current place'});main.append(place);place.focus();
          button.click();assert(document.activeElement===place);assert.equal(previews.length,3);
        """)


class AssemblyFinishSourceTests(unittest.TestCase):
    def test_packing_progress_figure_uses_the_normative_mono_mid_role(self):
        css = (WEB / 'assembly.css').read_text(encoding='utf-8')
        rule = css.split('.pack-copy-figure {', 1)[1].split('}', 1)[0]
        self.assertIn('font-family: var(--font-mono)', rule)
        self.assertIn('font-size: var(--fs-fig-mid)', rule)
