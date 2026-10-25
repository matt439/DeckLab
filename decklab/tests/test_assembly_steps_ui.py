"""Completion disclosures preserve physical tasks, explicit viewer scope and current focus."""
import unittest

from decklab.tests import test_assembly_completion_ui as completion
from decklab.tests import test_assembly_switcher_ui as switcher
from decklab.tests.test_workspace_ui import NODE, WEB


SETUP = switcher.SETUP + """
  const steps=v=>v.stepState.records;
  const stepOf=(v,index=0)=>steps(v).find(s=>s.body.contains(v.ticks[index].node));
  const outside=()=>{const button=el('button',{text:'Another current place'});main.append(button);button.focus();return button;};
  const remoteAll=v=>{v.ticks.forEach(t=>serverTicks.add(t.id));return packSync(v);};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyStepsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        completion.AssemblyCompletionUiTests.run_js(self, SETUP + scenario)

    def test_confirmed_completion_folds_casual_without_removing_tasks_or_changing_units(self):
        self.run_js("""
          const v=draw();await settle();const nodes=v.ticks.map(t=>t.node),tiles=v.ticks.map(t=>t.tile),scope=v.progress.scope;
          const entries=v.packViewerEntries.slice(),place=outside();await remoteAll(v);await settle();
          const real=steps(v).filter(s=>v.ticks.some(t=>s.body.contains(t.node)));
          assert(real.every(s=>s.done&&!s.node.open));assert(steps(v).every(s=>s.node.tag==='details'));
          assert(real.every(s=>s.node.classList.contains('is-done')&&s.spoken.textContent.includes('done')));
          assert(v.ticks.every((t,i)=>t.node===nodes[i]&&t.tile===tiles[i]&&t.node.isConnected));
          assert(v.packViewerEntries.every((e,i)=>e===entries[i]));assert.equal(v.progress.scope,scope);
          assert.equal(v.bar.progress.copies.textContent,'4 / 4');assert(packCanFinish(v));assert(document.activeElement===place);
        """)

    def test_local_final_tick_waits_for_ack_and_focusout_without_moving_focus(self):
        self.run_js("""
          const v=draw(1);await settle();const step=stepOf(v),tick=v.ticks[0];let answer;
          apiWrite=(path,body)=>new Promise(resolve=>{assert.equal(path,'/api/assembly/ticks');answer=()=>resolve({ticks:body.ids});});
          tick.node.focus();tick.node.click();assert(tick.done);assert(step.node.open);assert(v.progress.pending.size);
          answer();await settle();assert(step.node.open);assert(document.activeElement===tick.node);assert(!v.progress.pending.size);
          const place=outside();step.node.fire('focusout');await settle();assert(!step.node.open);assert(document.activeElement===place);
        """)

    def test_remote_done_preserves_focused_body_and_manual_reopen_survives_polls_and_sort(self):
        self.run_js("""
          const v=draw(1);await settle();const step=stepOf(v),trigger=v.packViewerEntries[0].trigger;
          trigger.focus();await remoteAll(v);assert(step.done&&step.node.open);const place=outside();step.node.fire('focusout');await settle();
          assert(!step.node.open);const event=step.summary.fire('click');assert(event.defaultPrevented);assert(step.node.open&&step.manual===true);
          for(let i=0;i<3;i++){packStepsProgress(v);step.node.fire('toggle');}assert(step.node.open&&step.manual===true);
          v.order='storage';renderAssemblyPlan(v,v.data);await settle();const fresh=stepOf(v);
          assert(fresh!==step);assert(fresh.node.open&&fresh.manual===true);assert.equal(fresh.scope,step.scope);
          assert(document.activeElement===place);step.summary.click();step.node.open=false;step.node.fire('toggle');
          assert(fresh.node.open&&fresh.manual===true);
        """)

    def test_queued_programmatic_toggle_events_never_create_manual_reopen_intent(self):
        self.run_js("""
          const v=draw(1);await settle();const step=stepOf(v);outside();
          packStepOpen(step,false);packStepOpen(step,true);packStepOpen(step,false);
          step.node.fire('toggle',{oldState:'closed',newState:'open'});assert.equal(step.manual,null);assert(!step.node.open);
          await remoteAll(v);assert(!step.node.open);step.summary.click();assert(step.node.open&&step.manual===true);
          step.node.fire('toggle',{oldState:'open',newState:'closed'});assert(step.node.open&&step.manual===true);
          // Browser-driven reveals without a summary click are adopted from the actual current state.
          packStepOpen(step,false);step.manual=null;step.node.open=true;step.node.fire('toggle');assert.equal(step.manual,true);
        """)

    def test_owned_manual_close_repairs_only_focus_that_would_be_hidden(self):
        self.run_js("""
          const v=draw(1);await settle();const step=stepOf(v),tick=v.ticks[0].node;
          tick.focus();const event=step.summary.fire('click');assert(event.defaultPrevented);
          assert(!step.node.open);assert(document.activeElement===step.summary);assert.equal(step.summary.focusOptions.preventScroll,true);
          step.summary.click();assert(step.node.open);const place=outside();step.summary.click();assert(!step.node.open);
          assert(document.activeElement===place);step.summary.click();tick.focus();step.node.open=false;step.node.fire('toggle');
          assert(document.activeElement===step.summary);assert(!step.node.open);
        """)

    def test_undo_and_remote_uncheck_reopen_without_selecting_deck_or_focusing(self):
        self.run_js("""
          const v=draw();await settle();outside();let undo;showToast=(words,opts)=>{undo=opts?.undo;};
          const active=v.switcher.active;v.bulk[1].button.click();await settle();const second=stepOf(v,1);assert(!second.node.open);
          const place=outside();undo();await settle();assert(second.node.open&&!second.done);assert.equal(v.switcher.active,active);
          assert(document.activeElement===place);await remoteAll(v);assert(!second.node.open);serverTicks.delete(v.ticks[1].id);
          await packSync(v);assert(second.node.open&&!second.done);assert.equal(v.switcher.active,active);assert(document.activeElement===place);
        """)

    def test_resize_retains_same_disclosure_and_focused_original_task_and_allows_lab_manual_toggle(self):
        self.run_js("""
          const v=draw(1);await settle();outside();await remoteAll(v);const step=stepOf(v),summary=step.summary,body=step.body,tick=v.ticks[0].node;
          summary.focus();resize(true);assert(step.node.open);assert(document.activeElement===summary);
          summary.click();assert(!step.node.open);summary.click();assert(step.node.open);tick.focus();resize(false);
          assert(step.node.open&&document.activeElement===tick);assert(step.summary===summary&&step.body===body&&v.ticks[0].node===tick);
          const place=outside();step.node.fire('focusout');await settle();assert(step.node.open); // explicit reopen latch
          assert(document.activeElement===place);assert.equal((summary.events.get('keydown')||[]).length,0);
        """)

    def test_viewer_return_and_finish_guide_expand_exact_original_step_before_focus(self):
        self.run_js("""
          const v=draw();await settle();fakeViewer();const origin=v.packViewerEntries[0].trigger,first=stepOf(v);
          origin.click();await remoteAll(v);assert(first.done&&first.node.open);assert(stepOf(v,1).node.open);
          packStepOpen(first,false);closePacking(v);assert(first.node.open);assert(document.activeElement===origin);
          packStepsProgress(v);assert(!stepOf(v,1).node.open);
          serverTicks.delete(v.ticks[1].id);await packSync(v);const second=stepOf(v,1);outside();second.summary.click();assert(!second.node.open);
          const ids=v.ticks.map(t=>t.id),original=v.ticks[1].node;const calls=[];apiWrite=async(p,b)=>{calls.push([p,b]);throw new Error('guide must only focus');};
          builtButton().click();assert(second.node.open);assert(!v.switcher.panels[1].node.hidden);assert(document.activeElement===original);
          assert.equal(second.deck.version,'owned');same(v.ticks.map(t=>t.id),ids);same(calls,[]);assert(!v.ticks[1].done);
        """)

    def test_modal_operations_pending_and_errors_defer_automatic_fold(self):
        self.run_js("""
          for(const mode of ['dialog','saving','previewing','reviewing','pending','error','busy']){
            clear(main);serverTicks.clear();state.profile={id:'matt',role:'admin',space:'home'};const v=draw(1);await settle();const step=stepOf(v);
            outside();v.ticks[0].set(true);let modal;
            if(mode==='dialog')modal=openSheet('Current sheet');if(['saving','previewing','reviewing'].includes(mode))v[mode]=true;
            if(mode==='pending')v.progress.pending.set(v.ticks[0].id,{done:true});if(mode==='error')v.progress.error='Fixture';if(mode==='busy')v.progress.busy=true;
            packStepsProgress(v);assert(step.done&&step.node.open,mode);if(modal)modal.close();v.saving=v.previewing=v.reviewing=false;
            v.progress.pending.clear();v.progress.error=null;v.progress.busy=false;outside();packStepsProgress(v);assert(!step.node.open,mode);
          }
        """)

    def test_stale_controls_and_queued_focusout_never_change_current_plan_or_outside_focus(self):
        self.run_js("""
          for(const mode of ['profile','route','permission','replacement','disposed','dialog','saving','previewing','reviewing']){
            clear(main);serverTicks.clear();state.profile={id:'matt',role:'admin',space:'home'};state.may=null;
            const v=draw(1);await settle();const step=stepOf(v);v.ticks[0].set(true);v.ticks[0].node.focus();packStepsProgress(v);
            const place=outside();step.node.fire('focusout');let modal;
            if(mode==='profile')state.profile={id:'user1'};if(mode==='route')++routeToken;if(mode==='permission')state.may={see_home_records:false};
            if(mode==='replacement')renderAssemblyPlan(v,{...v.data});if(mode==='disposed')packDisposeSwitcher(v);if(mode==='dialog')modal=openSheet('New modal');
            if(['saving','previewing','reviewing'].includes(mode))v[mode]=true;
            const before=step.node.open,active=document.activeElement;step.summary.click();await settle();assert.equal(step.node.open,before,mode);
            assert(document.activeElement===active,mode);modal?.close();assert(place.isConnected);
          }
        """)

    def test_information_only_steps_never_become_done_and_version_scope_does_not_adopt_manual_state(self):
        self.run_js("""
          const d=item();d.steps=[];d.kit={sleeves:{state:'missing'},need:0};d.sleeves_need=0;
          media.matches=false;drawAssembly(plan([d]),routeToken);await settle();const v=packingProgressView,info=steps(v)[0];
          assert(info&&info.node.open&&!info.done);assert.equal(info.badge.textContent,'1');assert(packCanFinish(v));
          renderAssemblyPlan(v,dataFor(1));await settle();outside();await remoteAll(v);const old=stepOf(v);old.summary.click();assert(old.manual===true);
          const changed={...v.data,decks:v.data.decks.map(deck=>({...deck,version:'owned'}))};renderAssemblyPlan(v,changed);await settle();
          const fresh=stepOf(v);assert.notEqual(fresh.key,old.key);assert.equal(fresh.manual,null);assert(fresh.node.open&&!fresh.done);
        """)

    def test_resize_reveals_same_closed_move_summary_above_measured_header_and_bar(self):
        self.run_js("""
          const data=dataFor(1);data.decks[0].steps[0].transfers=[{from:'casual/donor',from_title:'Donor',quantity:1}];
          media.matches=true;drawAssembly(data,routeToken);await settle();const v=packingProgressView;
          const step=steps(v).find(s=>JSON.parse(s.key)[2]==='move'),target=step.summary,ids=v.ticks.map(t=>t.id),selected=JSON.stringify(v.selected);
          target.click();assert(!step.node.open);target.focus();let top=335,calls=0;
          const frames=[];requestAnimationFrame=fn=>frames.push(fn);window.innerHeight=330;window.visualViewport=null;
          target.getBoundingClientRect=()=>({left:20,right:800,top,bottom:top+44,width:780,height:44});
          target.scrollIntoView=()=>{calls++;top=0;};window.scrollBy=({top:delta})=>{top-=delta;};
          const header=el('header',{class:'topbar'});document.body.append(header);
          header.getBoundingClientRect=()=>({left:0,right:1000,top:0,bottom:56,width:1000,height:56});
          v.bar.node.getBoundingClientRect=()=>({left:0,right:1000,top:231,bottom:330,width:1000,height:99});
          resize(false);assert(document.activeElement===target);assert(calls>0);assert(top>=64&&top+44<=223);
          const first=calls;resize(true);assert(document.activeElement===target);assert(calls>first);assert(step.node.open);
          assert(step.summary===target);same(v.ticks.map(t=>t.id),ids);assert.equal(JSON.stringify(v.selected),selected);
        """)

    def test_resize_reveals_exact_focused_body_without_refocusing_or_rebuilding(self):
        self.run_js("""
          const v=draw(1,false);await settle();const step=stepOf(v),target=v.ticks[0].node,body=step.body;
          target.focus();let focusCalls=0;const focus=target.focus.bind(target);target.focus=opts=>{focusCalls++;focus(opts);};
          const old=target.scrolled||0,ids=v.ticks.map(t=>t.id),calls=[];mockApi((p,b)=>{calls.push([p,b]);throw new Error('resize must not request');});
          resize(false);assert((target.scrolled||0)>old);assert(document.activeElement===target);assert.equal(focusCalls,0);
          const first=target.scrolled;resize(true);assert(target.scrolled>first);assert(document.activeElement===target);assert.equal(focusCalls,0);
          assert(step.body===body&&v.ticks[0].node===target);same(v.ticks.map(t=>t.id),ids);same(calls,[]);
        """)

    def test_resize_focus_reveal_refuses_modal_busy_stale_view_and_outside_focus(self):
        self.run_js("""
          for(const mode of ['dialog','viewer','saving','previewing','reviewing','profile','route','permission','disposed','outside']){
            clear(main);state.profile={id:'matt',role:'admin',space:'home'};state.may=null;serverTicks.clear();
            const v=draw(1,false);await settle();const target=stepOf(v).summary;target.focus();const before=target.scrolled||0;let modal;
            if(mode==='dialog'){modal=openSheet('Current modal');target.focus();}
            if(mode==='viewer'){fakeViewer();v.packViewerEntries[0].trigger.click();}
            if(['saving','previewing','reviewing'].includes(mode))v[mode]=true;
            if(mode==='profile')state.profile={id:'user1'};if(mode==='route')++routeToken;
            if(mode==='permission')state.may={see_home_records:false};if(mode==='disposed')packDisposeSwitcher(v);if(mode==='outside')outside();
            const active=document.activeElement;resize(false);assert.equal(target.scrolled||0,before,mode);assert(document.activeElement===active,mode);
            modal?.close();if(v.packingViewer)closePacking(v,false);
          }
        """)

    def test_resize_queued_reveal_cannot_scroll_or_focus_after_ownership_changes(self):
        self.run_js("""
          for(const mode of ['focus','dialog','saving','previewing','reviewing','profile','route','new-plan','disposed']){
            clear(main);state.profile={id:'matt',role:'admin',space:'home'};state.may=null;serverTicks.clear();
            const v=draw(1,false);await settle();const target=stepOf(v).summary;target.focus();const frames=[];requestAnimationFrame=fn=>frames.push(fn);
            resize(false);assert(frames.length);const before=target.scrolled||0;let modal;
            if(mode==='focus')outside();if(mode==='dialog')modal=openSheet('Later modal');
            if(['saving','previewing','reviewing'].includes(mode))v[mode]=true;
            if(mode==='profile')state.profile={id:'user1'};if(mode==='route')++routeToken;
            if(mode==='new-plan')renderAssemblyPlan(v,{...v.data});if(mode==='disposed')packDisposeSwitcher(v);
            const active=document.activeElement;frames.forEach(fn=>fn());assert.equal(target.scrolled||0,before,mode);assert(document.activeElement===active,mode);modal?.close();
          }
        """)


class AssemblyStepsSourceTests(unittest.TestCase):
    def test_native_summary_body_and_casual_done_height_stay_scoped(self):
        css=(WEB/'assembly-steps.css').read_text(encoding='utf-8')
        self.assertIn('min-height: 56px',css)
        self.assertIn('.pack-step:not([open]) > .pack-step-body',css)
        self.assertIn('@media (min-width: 1000px)',css)
        source=(WEB/'assembly-steps.js').read_text(encoding='utf-8')
        self.assertNotIn('keydown',source)
        self.assertNotIn('apiWrite',source)
        self.assertNotIn('localStorage',source)
