"""A casual switcher retains all current plan tasks and an explicit whole-packing viewer."""
import unittest
from decklab.tests import test_assembly_completion_ui as completion
from decklab.tests.test_workspace_ui import NODE, WEB

SETUP = """
  const media=window.matchMedia('(min-width: 1000px)');
  const dataFor=(count=2)=>{
    const decks=Array.from({length:count},(_,i)=>({...item(i?'casual/d'+i:'casual/a',i===1?'owned':'target'),
      title:i<2?'Same title':'Deck '+i,colors:i===0?['G']:i===1?['U']:[],
      steps:[{name:i===1?'Beta':'Alpha',need:2,keep:0,storage:2,transfers:[],waiting:0,missing:0}]}));
    const data=plan(decks);data.cards.Beta={...beta,img:'/img/b/1/normal',img_small:'/img/b/1/small'};return data;
  };
  const draw=(count=2,narrow=true)=>{media.matches=!narrow;drawAssembly(dataFor(count),routeToken);return packingProgressView;};
  const key=p=>packParticipantKey(p.deck);
  const visible=v=>v.switcher.panels.filter(p=>!p.node.hidden);
  const resize=wide=>{media.matches=wide;media.fire('change');};
  const viewerCalls=[];
  const fakeViewer=()=>{openCardViewer=(items,index,opts)=>{
    const dialog=el('dialog',{class:'viewer',open:''}),button=el('button',{text:'Viewer close'});dialog.append(button);
    document.body.append(dialog);button.focus();dialog.open=true;
    const reply={items,index,trigger:opts.trigger};viewerState=reply;viewerCalls.push({items,index,opts,dialog,reply});return reply;
  };};
  // The double has no capture phase: explicitly run native capture -> shared handler -> bubble order.
  const closePacking=(v,shared=true)=>{
    const entry=v.packingViewer;entry.dialog.open=false;entry.dialog.removeAttribute('open');entry.capture();
    if(shared&&viewerState===entry.reply){viewerState=null;if(entry.reply.trigger.isConnected)entry.reply.trigger.focus({preventScroll:true});}
    entry.close();entry.dialog.remove();return entry;
  };
"""

@unittest.skipUnless(NODE,"Node.js isn't installed")
class AssemblySwitcherTests(unittest.TestCase):
    def run_js(self,scenario):
        completion.AssemblyCompletionUiTests.run_js(self,SETUP+scenario)

    def test_zero_one_two_and_twelve_participants_keep_all_original_tasks(self):
        self.run_js("""
          for(const n of [0,1,2,12]){clear(main);const v=draw(n);await settle();
            assert.equal(v.switcher.panels.length,n);assert.equal(v.switcher.nav.querySelectorAll('button').length,n);
            assert.equal(visible(v).length,n?1:0);assert.equal(v.ticks.length,n);
            assert(v.ticks.every(t=>t.tile));assert(v.switcher.panels.every(p=>p.node.isConnected));
            assert.equal(v.switcher.nav.hidden,n<2);assert.equal(v.packViewerEntries.length,n);
            if(n)assert(v.bar.node.textContent.includes('Pulled 0 of '+(2*n)+' cards'));
          }
        """)

    def test_switching_changes_no_nodes_ids_counts_requests_or_local_preferences(self):
        self.run_js("""
          const v=draw();await settle();const panels=v.switcher.panels.map(p=>p.node),tickNodes=v.ticks.slice(),ids=v.ticks.map(t=>t.id);
          const entries=v.packViewerEntries.slice(),before=JSON.stringify(v.selected),stored=JSON.stringify(saved),calls=[];
          mockApi((p,b)=>{calls.push([p,b]);throw new Error('no requests on switch');});const button=v.switcher.panels[1].button;
          button.focus();button.click();assert(document.activeElement===button);assert.equal(visible(v)[0].deck.id,'casual/d1');
          assert.equal(button.getAttribute('aria-pressed'),'true');assert.equal(v.switcher.panels[0].button.getAttribute('aria-pressed'),'false');
          assert(v.switcher.panels.every((p,i)=>p.node===panels[i]));assert(v.ticks.every((t,i)=>t===tickNodes[i]));same(v.ticks.map(t=>t.id),ids);
          assert(v.packViewerEntries.every((e,i)=>e===entries[i]));assert.equal(JSON.stringify(v.selected),before);
          assert.equal(JSON.stringify(saved),stored);same(calls,[]);assert(v.results.contains(v.bar.node));assert(v.results.contains(v.finish.button));
        """)

    def test_whole_viewer_keeps_hidden_task_duplicates_order_captions_and_index(self):
        self.run_js("""
          const v=draw(3);await settle();fakeViewer();const nodes=v.packViewerEntries.map(e=>e.trigger);
          nodes[0].click();let call=viewerCalls.at(-1);same(call.items.map(e=>e.card.name),['Alpha','Beta','Alpha']);
          assert(call.items[0].caption.includes('Pull 2'));assert.equal(call.index,0);assert(call.opts.trigger===nodes[0]);
          assert.equal(v.packViewerEntries.length,3);closePacking(v);v.switcher.panels[2].button.click();nodes[2].click();
          call=viewerCalls.at(-1);assert.equal(call.index,2);same(call.items.map(e=>e.card.name),['Alpha','Beta','Alpha']);
          assert(nodes.every(n=>n.getAttribute('data-viewer')==='packing'&&n.getAttribute('aria-haspopup')==='dialog'));
          closePacking(v);assert(document.activeElement===nodes[2]);
        """)

    def test_unknown_cards_keep_task_but_have_no_fake_viewer_button_or_entry(self):
        self.run_js("""
          const data=dataFor();data.decks[1].steps[0].name='Unresolved fixture';media.matches=false;drawAssembly(data,routeToken);await settle();
          const v=packingProgressView;assert.equal(v.ticks.length,2);assert.equal(v.packViewerEntries.length,1);
          const tile=v.switcher.panels[1].node.querySelector('.card-tile');assert(tile);
          assert.equal(tile.querySelector('.card-tile-open').tag,'div');assert(tile.querySelector('.pack-tick'));
        """)

    def test_colour_gate_preserves_unknown_and_true_colourless_without_invented_identity(self):
        self.run_js("""
          for(const bad of [null,undefined,['bad'],['g'],['G','G'],Array(1),['G',null],['W','U','B','R','G','G']])assert.equal(packSwitcherColours(bad),null);
          assert(packSwitcherColours([]).label==='Colourless');assert(packSwitcherColours(['U','G']).label.toLowerCase().includes('blue'));
          const data=dataFor(3);data.decks[0].colors=['bad'];data.decks[1].colors=[];data.decks[2].colors=['G'];
          media.matches=false;drawAssembly(data,routeToken);await settle();const buttons=packingProgressView.switcher.panels.map(p=>p.button);
          assert(!buttons[0].querySelector('.id-pips'));assert(!buttons[0].getAttribute('style'));
          assert.equal(buttons[1].querySelector('.id-pips').getAttribute('aria-label'),'Colourless');
          assert(buttons[2].querySelector('.id-pips').getAttribute('aria-label').toLowerCase().includes('green'));
          assert(buttons.every(b=>b.getAttribute('aria-label')===null));assert(buttons[1].textContent.includes('Play-now list'));
        """)

    def test_redraw_keeps_id_version_then_same_deck_version_and_removal_fallback(self):
        self.run_js("""
          const v=draw();await settle();v.switcher.panels[1].button.click();const initial=v.switcher.active;
          const reordered={...v.data,decks:[...v.data.decks].reverse()};renderAssemblyPlan(v,reordered);assert.equal(v.switcher.active,initial);
          const changed={...reordered,decks:reordered.decks.map(d=>d.id==='casual/d1'?{...d,version:'target'}:d)};
          renderAssemblyPlan(v,changed);assert.equal(visible(v)[0].deck.id,'casual/d1');assert.equal(visible(v)[0].deck.version,'target');
          renderAssemblyPlan(v,{...changed,decks:changed.decks.filter(d=>d.id!=='casual/d1')});assert.equal(visible(v)[0].deck.id,'casual/a');
          renderAssemblyPlan(v,{...changed,decks:[]});assert.equal(v.switcher.active,null);assert.equal(v.packViewerEntries.length,0);
        """)

    def test_wide_to_casual_keeps_focused_panel_and_nav_to_wide_reveals_current_heading(self):
        self.run_js("""
          const v=draw(2,false);await settle();assert.equal(visible(v).length,2);
          v.packViewerEntries[1].trigger.focus();resize(false);assert.equal(visible(v)[0].deck.id,'casual/d1');
          const b=v.switcher.panels[1].button;b.focus();resize(true);const heading=v.switcher.panels[1].heading;
          assert(document.activeElement===heading);assert.equal(heading.scrollOptions.block,'start');assert.equal(visible(v).length,2);
          heading.focus();renderAssemblyPlan(v,v.data);assert(document.activeElement===v.switcher.panels[1].heading);
          assert.equal(v.switcher.panels[1].heading.scrollOptions.block,'start');
        """)

    def test_unpressed_keyboard_nav_focus_survives_redraw_and_resize_without_selecting_it(self):
        self.run_js("""
          const v=draw();await settle();const active=v.switcher.active;v.switcher.panels[1].button.focus();
          renderAssemblyPlan(v,v.data);assert(document.activeElement===v.switcher.panels[1].button);
          assert.equal(v.switcher.active,active);assert.equal(visible(v)[0].deck.id,'casual/a');
          resize(true);assert(document.activeElement===v.switcher.panels[1].heading);assert.equal(v.switcher.active,active);
          assert.equal(v.switcher.panels[1].heading.scrollOptions.block,'start');
        """)

    def test_wide_to_casual_uses_viewer_return_panel_not_current_viewer_card(self):
        self.run_js("""
          const v=draw(2,false);await settle();fakeViewer();const trigger=v.packViewerEntries[1].trigger;
          trigger.click();const entry=v.packingViewer;entry.reply.index=0;resize(false);
          assert.equal(visible(v)[0].deck.id,'casual/d1');assert(!trigger.closest('.pack-deck').hidden);
          closePacking(v);assert(document.activeElement===trigger);assert(!v.packingViewer);
        """)

    def test_hidden_tasks_still_block_completion_and_bulk_undo_survives_switch(self):
        self.run_js("""
          const v=draw();await settle();v.ticks[0].node.click();await settle();assert(!packCanFinish(v));
          let undo;showToast=(text,opts)=>{undo=opts.undo;};v.switcher.panels[1].button.click();
          v.bulk[1].button.click();await settle();assert(v.ticks.every(t=>t.done));assert(packCanFinish(v));
          v.switcher.panels[0].button.click();undo();await settle();assert(v.ticks[0].done);assert(!v.ticks[1].done);
          assert(!packCanFinish(v));assert.equal(v.ticks.length,2);assert.equal(v.bulk.length,2);
        """)

    def test_stale_trigger_button_busy_profile_route_and_old_data_are_inert(self):
        self.run_js("""
          for(const mode of ['previewing','saving','reviewing','profile','route','old-data','permission']){
            state.profile={id:'matt',role:'admin',space:'home'};state.may=null;clear(main);const v=draw();await settle();fakeViewer();
            const button=v.switcher.panels[1].button,trigger=v.packViewerEntries[0].trigger,active=v.switcher.active;
            if(['previewing','saving','reviewing'].includes(mode))v[mode]=true;
            if(mode==='profile')state.profile={id:'other'};if(mode==='route')++routeToken;
            if(mode==='old-data')v.data={...v.data};if(mode==='permission')state.may={see_home_records:false};
            button.click();trigger.click();assert.equal(v.switcher.active,active);assert.equal(viewerCalls.length,0);
          }
        """)

    def test_pending_native_close_refuses_reopen_and_old_callbacks_cannot_clear_new_watch(self):
        self.run_js("""
          const v=draw();await settle();fakeViewer();const trigger=v.packViewerEntries[0].trigger;trigger.click();const old=v.packingViewer;
          old.dialog.removeAttribute('open');old.dialog.open=false;trigger.click();assert.equal(viewerCalls.length,1);
          old.capture();viewerState=null;old.close();old.dialog.remove();assert(!v.packingViewer);
          trigger.click();const fresh=v.packingViewer;assert(fresh!==old);assert.equal(viewerCalls.length,2);
          old.capture();old.close();assert(v.packingViewer===fresh);assert(fresh.dialog.isConnected);
          closePacking(v);assert(!v.packingViewer);assert(document.activeElement===trigger);
        """)

    def test_close_repairs_only_same_plan_and_does_not_repair_different_viewer_or_outside_focus(self):
        self.run_js("""
          for(const mode of ['same-plan','new-plan','different-viewer','outside','profile','route']){
            state.profile={id:'matt',role:'admin',space:'home'};clear(main);const v=draw();await settle();fakeViewer();
            v.packViewerEntries[0].trigger.click();const entry=v.packingViewer;
            if(mode==='same-plan')renderAssemblyPlan(v,v.data);
            if(mode==='new-plan')renderAssemblyPlan(v,{...v.data});
            if(mode==='different-viewer')viewerState={...entry.reply};
            if(mode==='profile')state.profile={id:'other'};if(mode==='route')++routeToken;
            const outside=el('button',{text:'Elsewhere'});main.append(outside);
            if(mode==='outside')outside.focus();else document.activeElement=entry.dialog.querySelector('button');
            entry.dialog.open=false;entry.dialog.removeAttribute('open');entry.capture();viewerState=null;entry.close();
            if(mode==='same-plan')assert(document.activeElement===visible(v)[0].heading);
            else assert(document.activeElement!==visible(v)[0]?.heading);
            assert(!v.packingViewer);entry.dialog.remove();
          }
        """)

    def test_cleanup_removes_listeners_and_heading_reveal_never_steals_later_focus(self):
        self.run_js("""
          const v=draw(2,false);await settle();const frames=[];requestAnimationFrame=fn=>frames.push(fn);
          packSwitcherFocus(v,v.switcher.panels[1].heading);const outside=el('button',{text:'Outside'});v.root.append(outside);outside.focus();
          const calls=v.switcher.panels[1].heading.scrolled;frames.shift()();assert(document.activeElement===outside);
          assert.equal(v.switcher.panels[1].heading.scrolled,calls);fakeViewer();v.packViewerEntries[0].trigger.click();const entry=v.packingViewer;
          const listener=v.switcher.change;closeAssemblySheets();assert(v.switcher.disposed);assert(!v.packingViewer);
          assert(!(entry.dialog.events.get('close')||[]).includes(entry.capture));assert(!(entry.dialog.events.get('close')||[]).includes(entry.close));
          assert(!(media.events.get('change')||[]).includes(listener));entry.capture();entry.close();assert(document.activeElement!==v.switcher.panels[0].heading);
          entry.dialog.remove();
        """)

    def test_owned_heading_reveal_uses_actual_header_clearance_and_drops_stale_frames(self):
        self.run_js("""
          for(const mode of ['current','focus','data','profile','route','disposed','modal']){
            state.profile={id:'matt',role:'admin',space:'home'};clear(main);const v=draw(2,false);await settle();
            const heading=v.switcher.panels[1].heading,frames=[];let y=900,scrolls=0,focuses=0;
            requestAnimationFrame=fn=>frames.push(fn);window.innerHeight=420;
            const focus=heading.focus.bind(heading);heading.focus=opts=>{focuses++;focus(opts);};
            heading.getBoundingClientRect=()=>({top:y,bottom:y+24,height:24,left:360,right:800,width:440});
            heading.scrollIntoView=()=>{scrolls++;y=12;};window.scrollBy=opts=>{y-=opts.top;};
            const header=el('header',{class:'topbar'});header.box={top:0,bottom:56,height:56,left:0,right:1000,width:1000};document.body.append(header);
            v.bar.node.box={top:360,bottom:420,height:60,left:324,right:984,width:660};
            packSwitcherFocus(v,heading);assert.equal(y,64);assert.equal(focuses,1);assert.equal(frames.length,1);
            if(mode==='focus'){const other=el('button',{text:'Other'});main.append(other);other.focus();}
            if(mode==='data')v.data={...v.data};if(mode==='profile')state.profile={id:'other'};if(mode==='route')++routeToken;
            if(mode==='disposed')packDisposeSwitcher(v);let modal;if(mode==='modal')modal=openSheet('Other dialog');
            const before=scrolls,active=document.activeElement;frames.shift()();assert.equal(focuses,1);assert(document.activeElement===active);
            assert.equal(scrolls,before+(mode==='current'?1:0));header.remove();modal?.close();
          }
        """)

class AssemblySwitcherSourceTests(unittest.TestCase):
    def test_shared_visibility_filter_is_unchanged_and_original_wrapper_is_retained(self):
        shared=(WEB/'cards-ui.js').read_text(encoding='utf-8');js=(WEB/'assembly.js').read_text(encoding='utf-8')
        self.assertIn('n.getClientRects().length > 0',shared)
        self.assertIn('packRegisterCard(view, tile, card, description)',js)
        css=(WEB/'assembly.css').read_text(encoding='utf-8')
        self.assertIn('.pack-deck-switcher[hidden], .pack-deck[hidden] { display: none; }',css)
