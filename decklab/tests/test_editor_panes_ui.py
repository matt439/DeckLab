"""The three-pane projection retains the current editor/search and its exact focus ownership."""
import json
import re
import subprocess
import unittest

from decklab.tests import test_quick_editor_ui as quick
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


REAL_CHANGED = re.search(r'(?ms)^function changed\(.*?^\}', (WEB / 'editor-screen.js').read_text(encoding='utf-8')).group(0)
SETUP = quick.SETUP + '\nchanged = ' + REAL_CHANGED + r''';
  window.matchMedia('(min-width: 600px)').matches=true;
  window.matchMedia('(min-width: 1000px)').matches=true;
  function full(extra={},opts={}) {
    startEditor({mode:'edit',view:view(extra),version:'target',restoreDraft:false,...opts});
    assert.equal(editor.quick,false);return editor;
  }
  function width(wide) {
    window.matchMedia('(min-width: 1000px)').matches=wide;
    window.matchMedia('(min-width: 1000px)').fire('change');
  }
  const shown = key => !editor.dom.panes.panels[key].hidden && !editor.dom.sideBody.hidden;
  const foundCard={...elves,have:{owned:4},default:{set:'fdn',number:'227',finish:'nonfoil'}};
  function accepted(ac) {
    ac.input.value=elves.name;ac.query=elves.name;ac.items=[foundCard];ac.active=0;
    ac.resultScope=editorSearchScope(ac);drawOptions(ac);
  }
  function dockGeometry(ed,target,height=48) {
    const body=ed.dom.addPart,measure={moves:0};let value=0;
    body.box={top:100,bottom:250,height:150,left:0,right:1000};
    Object.defineProperty(body,'scrollTop',{configurable:true,get:()=>value,set:n=>{value=n;measure.moves++;}});
    target.getBoundingClientRect=()=>({top:602-value,bottom:602+height-value,height,left:420,right:680});
    return measure;
  }
'''

DEEP_LINK_SETUP = r'''
  const requests=[],replacements=[],opened=[];
  let routeView=view();editor=null;
  history.replaceState=(data,unused,url)=>{
    history.state=data;
    if(url!==undefined){location.hash=new URL(url,'http://localhost/').hash;replacements.push(location.hash);}
  };
  load=(path,token,ready)=>{requests.push(path);ready(routeView);};
  openSwapSheet=uid=>opened.push(uid);
  function deepLink(suffix) {
    location.hash=editHref('casual/sample','owned')+suffix;
    showEditor(new URLSearchParams(location.hash.split('?')[1]),routeToken);
    return editor;
  }
'''


@unittest.skipUnless(NODE, 'Node.js is not installed')
class EditorPanesUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)],
            input=json.dumps([str(WEB), SETUP + scenario, True,
                {'innerWidth': 1000, 'innerHeight': 830, 'coarse': False,
                 'visual': {'width': 1000, 'height': 830}}]),
            capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'ok')

    def test_tabs_and_check_updates_retain_all_roots_search_and_native_result_controls(self):
        self.run_js(r'''
          const ed=full(),ctx=ed.dom.panes,ac=ed.ac;accepted(ac);
          const roots=[ed.dom.addPart,ed.dom.stats,ed.dom.check],searchInput=ac.input,resultList=ac.list;
          const add=resultList.querySelector('.ac-add'),inspect=resultList.querySelector('.ac-thumb');
          const tabs=SIDE_TABS.map(([key])=>ctx.buttons[key].button),seq=ac.seq;
          width(false);setSide('add');
          for(const key of ['stats','checks','add']) {
            setSide(key);assert(shown(key));
            for(const root of roots)assert(root.isConnected&&ctx.root.contains(root));
            assert.equal(ed.ac,ac);assert.equal(ac.input,searchInput);assert.equal(ac.list,resultList);
            assert.equal(ac.list.querySelector('.ac-add'),add);assert.equal(ac.list.querySelector('.ac-thumb'),inspect);
          }
          tabs[2].focus();ed.check={blocks:[{}],warnings:[]};drawSideTabs();
          assert.equal(document.activeElement,tabs[2]);
          same(SIDE_TABS.map(([key])=>ctx.buttons[key].button===tabs[SIDE_TABS.findIndex(([k])=>k===key)]),[true,true,true]);
          assert.equal(tabs[2].querySelector('.tab-count').textContent,'1');assert(ac.seq>seq,'Closing casual Add invalidates pending work without model changes');
          width(true);for(const key of ['add','stats','checks'])assert(shown(key));
          assert.equal(ed.ac,ac);assert.equal(ed.dom.stats,roots[1]);assert(ed.dom.stats.textContent.includes('Mana curve'));
        ''')

    def test_closed_casual_search_rejects_old_reply_and_reopens_with_a_fresh_read(self):
        self.run_js(r'''
          const ed=full(),ac=ed.ac,requests=[],before=JSON.stringify(ed.lists);let resolve;
          api=path=>{requests.push(path);return new Promise(r=>resolve=r);};
          ac.input.value=elves.name;const pending=lookUp(ac,elves.name);setSide('checks');width(false);
          assert.equal(ed.ac,ac);assert(ac.dockSuspended);assert(!editorSearchCurrent(ac));
          resolve({cards:[foundCard],pages:2});await pending;assert.equal(ac.items.length,0);assert.equal(requests.length,1);
          setSide('add');flushTimers();assert.equal(requests.length,2);
          resolve({cards:[foundCard],pages:2});await settle();assert.equal(ac.items[0].name,elves.name);
          assert.equal(ac.pages,2);assert(!ac.pickFirst);assert.equal(JSON.stringify(ed.lists),before);
        ''')

    def test_checks_heading_class_survives_reply_recreation_and_both_responsive_modes(self):
        self.run_js(r'''
          const ed=full(),ctx=ed.dom.panes;let heading=ed.dom.check.querySelector('#h-check');
          assert.equal(heading.getAttribute('class'),'edit-pane-heading');assert(!heading.matches('.sr-only'));
          drawCheck();assert(ed.dom.check.querySelector('#h-check')!==heading);heading=ed.dom.check.querySelector('#h-check');
          assert.equal(heading.getAttribute('class'),'edit-pane-heading');width(false);
          assert.equal(ed.dom.check.querySelector('#h-check'),heading);assert.equal(heading.getAttribute('class'),'sr-only');
          setSide('checks');ed.checkError='Fixture check failed';drawCheck();heading=ed.dom.check.querySelector('#h-check');
          assert.equal(heading.getAttribute('class'),'sr-only');width(true);
          assert.equal(ed.dom.check.querySelector('#h-check'),heading);assert.equal(heading.getAttribute('class'),'edit-pane-heading');
          ed.gone=true;drawCheck();assert.equal(ed.dom.check.querySelector('#h-check').getAttribute('class'),'edit-pane-heading');
          assert.equal(ed.dom.check.querySelectorAll('#h-check').length,1);assert.equal(ed.dom.panes,ctx);
        ''')

    def test_modes_keep_trial_editing_quick_none_yet_and_notes_contracts(self):
        self.run_js(r'''
          let ed=full({may_save:false});assert(ed.readOnly);assert(!main.querySelector('.bar-save'));
          assert(ed.dom.addPart.isConnected&&ed.ac.input.isConnected);
          startEditor({mode:'new',kind:'casual',restoreDraft:false});ed=editor;
          assert(ed.dom.panes&&ed.ac.input.isConnected);assert.equal(ed.mode,'new');assert(main.querySelector('.bar-save'));
          startEditor({mode:'new',kind:'casual',from:'casual/source',view:view({new_deck:{kind:'casual',title:'Copied fixture'}}),restoreDraft:false});
          assert.equal(editor.from,'casual/source');assert(editor.dom.panes&&editor.ac.input.isConnected);
          ed=full({lists:{target:structuredClone(list),owned:null}},{version:'owned'});
          assert(!ed.dom.panes&&!ed.dom.sideBody);assert(noOwnedList());assert(main.textContent.includes('Start it from'));
          ed=full();const ac=ed.ac,ctx=ed.dom.panes;ed.tab='notes';drawMain();const focus=document.activeElement;
          width(false);assert(main.querySelector('.edit-page').classList.contains('is-notes'));
          assert.equal(ed.ac,ac);assert(ctx.root.isConnected);assert.equal(document.activeElement,focus);
          window.matchMedia('(min-width: 600px)').matches=false;startEditor({mode:'edit',view:view(),version:'target',restoreDraft:false});
          assert(editor.quick);assert(!editor.dom.panes&&!editor.dom.sideBody);assert(main.querySelector('.bar-add'));
        ''')

    def test_shortcut_bar_add_and_checks_reveal_the_original_controls(self):
        self.run_js(r'''
          const ed=full(),ctx=ed.dom.panes,ac=ed.ac;accepted(ac);width(false);setSide('stats');foldSide(true);
          const before=JSON.stringify(draftBody()),history=ed.history.length,seq=ac.seq;let writes=0;
          apiWrite=async()=>{writes++;throw Error('unexpected write');};
          const ev={key:'/',target:main,preventDefault(){this.prevented=true;}};editorKeys(ev);
          assert(ev.prevented);assert.equal(ed.ac,ac);assert.equal(document.activeElement,ac.input);assert(shown('add'));
          setSide('stats');ed.dom.barParts.addCards.click();assert.equal(document.activeElement,ac.input);assert(shown('add'));
          jumpToChecks();assert(shown('checks'));assert.equal(document.activeElement,ed.dom.check);assert(ed.dom.check.scrolled);
          // Explicit Add/Checks requests leave Notes through its existing Cards projection; resizing alone does not.
          ed.tab='notes';drawMain();const prose=JSON.stringify(ed.prose);focusSearch();
          assert.equal(ed.tab,'cards');assert.equal(ed.ac,ac);assert(document.activeElement===ac.input);
          ed.tab='notes';drawMain();jumpToChecks();assert.equal(ed.tab,'cards');assert(document.activeElement===ed.dom.check);
          assert.equal(JSON.stringify(ed.prose),prose);
          assert.equal(JSON.stringify(draftBody()),before);assert.equal(ed.history.length,history);assert(ac.seq>seq,'Explicitly closed Add invalidates request intent');assert.equal(writes,0);
          for(const [key,panel] of Object.entries(ctx.panels)) {
            assert.equal(panel.getAttribute('role'),'tabpanel');
            assert.equal(ctx.buttons[key].button.getAttribute('aria-controls'),panel.id);
          }
        ''')

    def test_resize_preserves_original_visible_control_and_does_not_persist_model_or_requests(self):
        self.run_js(r'''
          const ed=full(),ctx=ed.dom.panes,ac=ed.ac;accepted(ac);ed.side='stats';ed.sideFolded=true;
          const before=JSON.stringify(draftBody()),history=ed.history.length,seq=ac.seq;let calls=0,focuses=0;
          api=async()=>{calls++;throw Error('unexpected read');};apiWrite=api;
          ac.input.focus();const original=ac.input.focus.bind(ac.input);ac.input.focus=(...args)=>{focuses++;original(...args);};
          width(false);assert.equal(ed.side,'add');assert(shown('add'));assert.equal(document.activeElement,ac.input);
          width(true);assert.equal(document.activeElement,ac.input);assert.equal(focuses,0);assert.equal(ed.ac,ac);
          assert.equal(JSON.stringify(draftBody()),before);assert.equal(ed.history.length,history);assert.equal(ac.seq,seq);assert.equal(calls,0);
          assert.equal(ctx.search.querySelector('.edit-add'),ed.dom.addPart);
        ''')

    def test_only_a_tab_that_becomes_hidden_hands_focus_to_its_exact_visible_heading(self):
        self.run_js(r'''
          const ed=full(),ctx=ed.dom.panes; width(false);setSide('add');
          const statsTab=ctx.buttons.stats.button;statsTab.focus();window.fire('resize');assert.equal(document.activeElement,statsTab);
          width(true);assert.equal(document.activeElement,ctx.panels.stats.querySelector('h2'));
          width(false);ctx.buttons.add.button.focus();ed.saving=true;width(true);
          assert.equal(document.activeElement,ctx.buttons.add.button);ed.saving=false;
          width(false);setSide('add');ed.dom.sideFold.focus();width(true);assert.equal(document.activeElement,ctx.panels.add.querySelector('h2'));
        ''')

    def test_owned_viewer_return_pane_stays_visible_without_touching_modal_focus(self):
        self.run_js(r'''
          const ed=full(),ctx=ed.dom.panes;accepted(ed.ac);const trigger=ed.ac.list.querySelector('.ac-thumb');
          ed.side='stats';openCardViewer([foundCard],0,{trigger});const dialog=viewerDom.dialog,close=viewerDom.close;
          dialog.open=true;close.focus();width(false);assert(shown('add'));assert.equal(document.activeElement,close);
          // Native close can unset open before dispatch; the exact pending return node remains authoritative.
          dialog.open=false;ed.side='checks';width(true);width(false);assert(shown('add'));assert.equal(document.activeElement,close);
          // A live current pane focus after native close outranks the older pending viewer return.
          width(true);ctx.panels.stats.querySelector('h2').focus();width(false);
          assert(shown('stats'));assert(document.activeElement===ctx.panels.stats.querySelector('h2'));
          dialog.remove();const unrelated=openSheet('Unrelated modal');unrelated.dialog.open=true;unrelated.dialog.querySelector('.sheet-close').focus();
          ed.side='checks';width(true);width(false);assert(shown('checks'));unrelated.dialog.remove();viewerState=null;
          const outside=el('button');main.append(outside);outside.focus();ed.side='stats';viewerState={trigger:outside};
          width(true);width(false);assert(shown('stats'));assert.equal(document.activeElement,outside);viewerState=null;
        ''')

    def test_hidden_header_rescues_only_its_recorded_focus_through_native_auto_blur(self):
        self.run_js(r'''
          for(const timing of ['before','during']) {
            window.matchMedia('(min-width: 1000px)').matches=true;
            const ed=full(),ctx=ed.dom.panes;width(false);ctx.buttons.stats.button.focus();
            if(timing==='before')document.activeElement=document.body;
            else {
              let hidden=false;Object.defineProperty(ctx.head,'hidden',{get:()=>hidden,set:value=>{
                hidden=value;if(value&&ctx.head.contains(document.activeElement)) {
                  document.activeElement=document.body;document.fire('focusin',{target:document.body});
                }
              }});
            }
            width(true);assert(document.activeElement===ctx.panels.stats.querySelector('h2'));
            assert.equal(ctx.headerFocus,null);
          }
        ''')

    def test_header_auto_blur_never_reclaims_outside_intent_busy_or_changed_scope(self):
        self.run_js(r'''
          for(const action of ['outside-focus','outside-pointer','during-projection','saving','asking','modal','space']) {
            for(const d of document.querySelectorAll('dialog'))d.remove();window.matchMedia('(min-width: 1000px)').matches=true;
            const ed=full(),ctx=ed.dom.panes,outside=el('button');main.append(outside);width(false);ctx.buttons.add.button.focus();
            if(action==='outside-focus') {outside.focus();document.fire('focusin',{target:outside});document.activeElement=document.body;}
            else if(action==='outside-pointer') {document.fire('pointerdown',{target:main,type:'pointerdown'});document.activeElement=document.body;}
            else if(action==='during-projection') {
              let hidden=false;Object.defineProperty(ctx.head,'hidden',{get:()=>hidden,set:value=>{
                hidden=value;if(value){outside.focus();document.fire('focusin',{target:outside});}
              }});
            } else if(action==='modal') {const dialog=el('dialog',{open:true});document.body.append(dialog);outside.focus();}
            else if(action==='space')ed.space='other';
            else ed[action]=true;
            const before=document.activeElement;width(true);
            assert(document.activeElement===(action==='during-projection'?outside:before),action);
          }
        ''')

    def test_original_viewer_close_focus_event_reveals_current_return_control_without_refocus(self):
        self.run_js(r'''
          const ed=full(),ctx=ed.dom.panes,ac=ed.ac,pictured={...foundCard,img_small:'/img/f/small',img:'/img/f/normal'};
          ac.input.value=elves.name;ac.query=elves.name;ac.items=[pictured];ac.active=0;drawOptions(ac);
          ac.list.removeAttribute('hidden'); // Native .hidden=false reflects the attribute; this DOM double does not.
          const trigger=ac.list.querySelector('.ac-thumb-btn'),seq=ac.seq,query=ac.query;let moves=0;
          window.innerHeight=330;window.visualViewport.height=330;
          const local=dockGeometry(ed,trigger);
          ed.dom.bar.box={top:258,bottom:330,height:72,left:0,right:1000};window.scrollBy=()=>moves++;
          openCardViewer([pictured],0,{trigger});viewerState.history=false;viewerDom.dialog.open=true;
          width(false);assert(shown('add'));assert.equal(moves,0);
          viewerDom.dialog.open=false;viewerDom.dialog.removeAttribute('open');viewerClosed();
          assert(document.activeElement===trigger);const focus=trigger.focus.bind(trigger);let focusedAgain=0;
          trigger.focus=(...args)=>{focusedAgain++;focus(...args);};
          // The DOM double does not bubble focusin; dispatch the native event after shared viewerClosed focuses.
          ctx.root.fire('focusin',{target:trigger});flushTimers();assert(local.moves>0);assert.equal(moves,0);assert(trigger.getBoundingClientRect().bottom<=250);
          assert(document.activeElement===trigger);assert.equal(focusedAgain,0);assert.equal(ac.seq,seq);assert.equal(ac.query,query);
          ctx.root.fire('focusin',{target:trigger});const outside=el('button');main.append(outside);outside.focus();const before=moves,localBefore=local.moves;flushTimers();assert.equal(local.moves,localBefore);
          assert.equal(moves,before);assert(document.activeElement===outside);
          const old=ctx;full();old.root.fire('focusin',{target:trigger});assert.equal(moves,before);
        ''')

    def test_old_controls_and_resize_callbacks_refuse_replaced_or_stale_contexts(self):
        self.run_js(r'''
          for(const mutate of [()=>routeToken++,()=>state.profile={id:'other'},()=>editor.id='casual/replaced',
            ()=>editor.version='owned',()=>editor.ac.cancelled=true,()=>editor.ac={...editor.ac},()=>editor.dom.page.remove()]) {
            state.profile=state.profiles[1];const ed=full(),ctx=ed.dom.panes,tab=ctx.buttons.checks.button;
            const selected=ed.side,wide=ctx.wide;mutate();tab.click();resizeEditorPanes();
            assert.equal(ed.side,selected);assert.equal(ctx.wide,wide);
          }
          state.profile=state.profiles[1];const old=full(),ctx=old.dom.panes,oldTab=ctx.buttons.checks.button;
          const current=full(),ac=current.ac;oldTab.click();assert.equal(editor,current);assert.equal(current.ac,ac);assert.equal(current.side,'add');
        ''')

    def test_native_return_focus_while_dialog_open_reveals_only_after_close_on_one_frame(self):
        self.run_js(r'''
          const ed=full(),ctx=ed.dom.panes,ac=ed.ac,pictured={...foundCard,img_small:'/img/f/small',img:'/img/f/normal'};
          ac.input.value=elves.name;ac.query=elves.name;ac.items=[pictured];ac.active=0;drawOptions(ac);ac.list.removeAttribute('hidden');
          const trigger=ac.list.querySelector('.ac-thumb-btn'),scope=editorSearchScope(ac);let moves=0,focusCalls=0;
          window.innerHeight=330;window.visualViewport.height=330;
          const local=dockGeometry(ed,trigger);
          ed.dom.bar.box={top:258,bottom:330,height:72,left:0,right:1000};window.scrollBy=()=>moves++;
          openCardViewer([pictured],0,{trigger});viewerState.history=false;viewerDom.dialog.open=true;width(false);
          // Browser autofocus can return to the page before the dialog's open state is removed.
          trigger.focus();ctx.root.fire('focusin',{target:trigger});assert.equal(moves,0);
          const focus=trigger.focus.bind(trigger);trigger.focus=(...args)=>{focusCalls++;focus(...args);};
          viewerDom.dialog.open=false;viewerDom.dialog.removeAttribute('open');viewerClosed();assert.equal(focusCalls,1);
          flushTimers();assert(local.moves>0);assert.equal(moves,0);assert(trigger.getBoundingClientRect().bottom<=250);
          assert(document.activeElement===trigger);assert.equal(focusCalls,1);assert.equal(editorSearchScope(ac),scope);
          const done=local.moves;flushTimers();assert.equal(local.moves,done);assert.equal(moves,0);
        ''')

    def test_modal_blocked_focus_queue_refuses_open_modal_changed_scope_focus_or_busy_effect(self):
        self.run_js(r'''
          for(const action of ['open','new-modal','new-focus','saving','asking','route','profile','space','version','disabled','detached','new-search','new-view']) {
            for(const dialog of document.querySelectorAll('dialog'))dialog.remove();state.profile=state.profiles[1];
            window.matchMedia('(min-width: 1000px)').matches=true;
            const ed=full(),ctx=ed.dom.panes,target=ed.ac.input;let moves=0;
            width(false);setSide('add');flushTimers();const local=dockGeometry(ed,target,32);
            ed.dom.bar.box={top:258,bottom:330,height:72,left:0,right:1000};window.innerHeight=330;window.visualViewport.height=330;
            window.scrollBy=()=>moves++;const modal=el('dialog',{open:true});document.body.append(modal);
            target.focus();ctx.root.fire('focusin',{target});assert.equal(moves,0);
            if(action!=='open')modal.remove();
            if(action==='new-modal')document.body.append(el('dialog',{open:true}));
            else if(action==='new-focus'){const other=el('button');main.append(other);other.focus();}
            else if(action==='route')routeToken++;
            else if(action==='profile')state.profile={id:'other'};
            else if(action==='space')ed.space='other';
            else if(action==='version')ed.version='owned';
            else if(action==='disabled')target.disabled=true;
            else if(action==='detached')ed.dom.page.remove();
            else if(action==='new-search')ed.ac={...ed.ac};
            else if(action==='new-view')full();
            else if(action==='saving'||action==='asking')ed[action]=true;
            const active=document.activeElement;flushTimers();assert.equal(local.moves,0,action);assert.equal(moves,0,action);assert(document.activeElement===active);
            flushTimers();assert.equal(moves,0,action+' has no repeated retry');
          }
        ''')

    def test_same_route_popstate_repairs_ua_scroll_restoration_after_the_first_focus_frame(self):
        self.run_js(r'''
          location.hash='#/edit?id=casual/sample&v=target';
          const ed=full(),ctx=ed.dom.panes,target=ed.ac.input,hash=location.hash;let moves=0,focusCalls=0;
          width(false);setSide('add');flushTimers();window.innerHeight=330;window.visualViewport.height=330;
          const local=dockGeometry(ed,target,32);
          ed.dom.bar.box={top:258,bottom:330,height:72,left:0,right:1000};window.scrollBy=()=>moves++;
          target.focus();const focus=target.focus.bind(target);target.focus=(...args)=>{focusCalls++;focus(...args);};
          ctx.root.fire('focusin',{target});flushTimers();assert(target.getBoundingClientRect().bottom<=250);
          // Closing the viewer's history entry can restore its saved page scroll after that first frame.
          ed.dom.addPart.scrollTop=0;assert.equal(target.getBoundingClientRect().top,602);window.fire('popstate');assert.equal(moves,0);
          // UA restoration follows popstate dispatch. The one owned frame must use the final geometry.
          ed.dom.addPart.scrollTop=0;flushTimers();assert(target.getBoundingClientRect().bottom<=250);assert(local.moves>0);assert.equal(moves,0);
          assert(document.activeElement===target);assert.equal(focusCalls,0);assert.equal(location.hash,hash);
          const done=local.moves;flushTimers();assert.equal(local.moves,done);assert.equal(moves,0);
        ''')

    def test_history_repair_refuses_real_navigation_before_hashchange_and_all_late_owner_changes(self):
        self.run_js(r'''
          for(const action of ['hash-before','focus-before','route','profile','hash-after','focus-after','space','version',
            'modal','saving','asking','disabled','detached','new-search','new-view']) {
            for(const dialog of document.querySelectorAll('dialog'))dialog.remove();state.profile=state.profiles[1];
            location.hash='#/edit?id=casual/sample&v=target';window.matchMedia('(min-width: 1000px)').matches=true;
            const ed=full(),ctx=ed.dom.panes,target=ed.ac.input,hash=location.hash;let moves=0;
            width(false);setSide('add');flushTimers();window.innerHeight=330;window.visualViewport.height=330;
            const local=dockGeometry(ed,target,32);ed.dom.bar.box={top:258,bottom:330,height:72,left:0,right:1000};
            window.scrollBy=()=>moves++;if(document.activeElement!==target)target.focus();
            // This open modal prevents immediate scrolling; the frame then proves every late guard.
            const blocker=el('dialog',{open:true});document.body.append(blocker);
            if(action==='hash-before')location.hash='#/library';
            if(action==='focus-before'){const other=el('button');main.append(other);other.focus();}
            window.fire('popstate');assert.equal(moves,0);
            if(action!=='modal')blocker.remove();
            if(action==='hash-before')location.hash=hash; // A refused event must not acquire a target later.
            else if(action==='route')routeToken++;
            else if(action==='profile')state.profile={id:'other'};
            else if(action==='hash-after')location.hash='#/library';
            else if(action==='focus-after'){const other=el('button');main.append(other);other.focus();}
            else if(action==='space')ed.space='other';
            else if(action==='version')ed.version='owned';
            else if(action==='saving'||action==='asking')ed[action]=true;
            else if(action==='disabled')target.disabled=true;
            else if(action==='detached')ed.dom.page.remove();
            else if(action==='new-search')ed.ac={...ed.ac};
            else if(action==='new-view')full();
            const active=document.activeElement;flushTimers();assert.equal(local.moves,0,action);assert.equal(moves,0,action);assert(document.activeElement===active);
          }
        ''')

    def test_actual_existing_owned_swap_link_keeps_the_canonical_pane_identity(self):
        self.run_js(DEEP_LINK_SETUP+r'''
          const ed=deepLink('&swap='+encodeURIComponent(bolt.name)),hash=editHref(ed.id,'owned');
          assert.equal(ed.version,'owned');assert(ed.hasFileList);assert(!ed.starting);
          assert.equal(location.hash,hash);assert.equal(ed.dom.panes.hash,hash);
          same(replacements,[hash]);assert.equal(requests.length,1);assert(requests[0].startsWith('/api/deck/edit?'));
          same(opened,[ed.lists.Sideboard[0].uid]);assert.equal(ed.lists.Sideboard[0].name,bolt.name);
          width(false);setSide('add');const target=ed.ac.input;let moves=0;flushTimers();
          const local=dockGeometry(ed,target,32);ed.dom.bar.box={top:258,bottom:330,height:72,left:0,right:1000};
          window.innerHeight=330;window.visualViewport.height=330;window.scrollBy=()=>moves++;
          if(document.activeElement!==target)target.focus();revealEditorPaneFocus(ed.dom.panes,target);flushTimers();assert(local.moves>0,'canonicalized current dock remains live');assert.equal(moves,0);
        ''')

    def test_actual_notes_link_keeps_notes_intent_and_still_refuses_real_navigation(self):
        self.run_js(DEEP_LINK_SETUP+r'''
          const ed=deepLink('&tab=notes'),hash=editHref(ed.id,'owned'),ac=ed.ac;
          assert.equal(ed.dom.panes.hash,hash);assert.equal(location.hash,hash);same(replacements,[hash]);
          assert.equal(ed.tab,'notes');assert(main.querySelector('.edit-page').classList.contains('is-notes'));
          const prose=JSON.stringify(ed.prose),textarea=document.getElementById('prose-notes');
          assert.equal(textarea.value,ed.prose.notes);focusSearch();assert.equal(ed.tab,'cards');assert.equal(ed.ac,ac);
          assert.equal(JSON.stringify(ed.prose),prose);assert.equal(requests.length,1);same(opened,[]);
          width(false);setSide('add');const target=ac.input;let moves=0;flushTimers();
          const local=dockGeometry(ed,target,32);ed.dom.bar.box={top:258,bottom:330,height:72,left:0,right:1000};
          window.innerHeight=330;window.visualViewport.height=330;window.scrollBy=()=>moves++;if(document.activeElement!==target)target.focus();
          location.hash='#/library';window.fire('popstate');assert.equal(moves,0,'hash guard precedes routeToken/hashchange');
          location.hash=hash;revealEditorPaneFocus(ed.dom.panes,target);flushTimers();assert(local.moves>0);assert.equal(moves,0);
          const done=local.moves;revealEditorPaneFocus(ed.dom.panes,target);location.hash='#/library';flushTimers();assert.equal(local.moves,done,'old queued scope cannot follow navigation');assert.equal(moves,0);
        ''')

    def test_alias_draft_gate_preserves_intent_until_callback_and_canonical_refresh_drops_old_frames(self):
        self.run_js(DEEP_LINK_SETUP+r'''
          const alias='casual/earlier-address',stored=new Map();
          local.get=key=>stored.get(key)??null;local.set=(key,value)=>{stored.set(key,String(value));return true;};
          local.remove=key=>{stored.delete(key);return true;};
          routeView=view({requested_id:alias,aliases:[alias]});
          const oldKey=draftKey({mode:'edit',profile:state.profile.id,id:alias,version:'owned'});
          const raw=JSON.stringify({v:1,saved:1000,sha256:routeView.sha256,starting:false,
            base:{lists:sendList(routeView.lists.owned),fields:pickFields(routeView.fields)},
            lists:sendList(routeView.lists.owned),fields:pickFields(routeView.fields)});
          stored.set(oldKey,raw);deepLink('&tab=notes');
          const intentHash=location.hash,params=new URLSearchParams(intentHash.split('?')[1]);
          assert.equal(editor,null);assert(intentHash.includes('tab=notes'));assert(main.textContent.includes('Choose a saved draft'));
          same(replacements,[]);button(main,'Open saved deck').click();const ed=editor,ctx=ed.dom.panes,ac=ed.ac;
          assert(ed&&ctx);assert.equal(ctx.hash,intentHash);assert.equal(location.hash,intentHash);
          assert.equal(stored.get(oldKey),raw);assert.equal(ed.tab,'cards','deferred callback keeps the existing intent timing');
          width(false);setSide('add');const target=ac.input;let moves=0;flushTimers();
          const scrollMeasure=dockGeometry(ed,target,32);ed.dom.bar.box={top:258,bottom:330,height:72,left:0,right:1000};
          window.innerHeight=330;window.visualViewport.height=330;window.scrollBy=()=>moves++;if(document.activeElement!==target)target.focus();
          const modal=el('dialog',{open:true});document.body.append(modal);revealEditorPaneFocus(ctx,target);assert.equal(moves,0);
          openSwapsFromRoute(params,ed.id);const canonical=editHref(ed.id,'owned');
          assert.equal(location.hash,canonical);assert.equal(ctx.hash,canonical);same(replacements,[canonical]);
          assert.equal(ed.tab,'notes');focusSearch();assert.equal(ed.ac,ac);assert(document.activeElement===target);
          modal.remove();flushTimers();assert.equal(scrollMeasure.moves,0,'old queued deep-link hash cannot adopt the refreshed canonical address');assert.equal(moves,0);
          focusSearch();revealEditorPaneFocus(ctx,target);flushTimers();assert(scrollMeasure.moves>0,'fresh canonical dock work remains allowed');assert.equal(moves,0);
          assert.equal(stored.get(oldKey),raw);assert.equal(requests.length,1);
        ''')

    def test_actual_new_deck_space_choice_keeps_current_panes_live_and_rejects_old_deferred_scope(self):
        self.run_js(r'''
          createTargets=()=>[{space:'home',player:'wife'},{space:'other'}];
          startEditor({mode:'new',kind:'casual',restoreDraft:false});const ed=editor,ctx=ed.dom.panes,ac=ed.ac;
          const beforeSpace=ed.space,other=beforeSpace==='home'?'other':'home';
          let moved=0;ctx.search.box={top:0,bottom:830,height:830,left:0,right:500};
          ed.dom.bar.box={top:760,bottom:830,height:70,left:0,right:1000};ac.input.box={top:800,bottom:832,height:32,left:10,right:400};
          window.scrollBy=()=>moved++;ac.input.focus();revealEditorPaneFocus(ctx,ac.input);const before=moved;
          const choice=main.querySelector(`[data-space="${other}"]`);assert(choice);choice.click();assert.equal(ed.space,other);
          assert.equal(ed.ac,ac);assert.equal(ed.dom.panes,ctx);flushTimers();assert.equal(moved,before);
          width(false);setSide('stats');assert(shown('stats'));ctx.buttons.add.button.click();
          assert(shown('add'));focusSearch();assert.equal(document.activeElement,ac.input);
          assert.equal(editorSearchScope(ac),JSON.stringify([ed.id,ed.version,other]));
        ''')

    def test_reveal_remeasures_clamped_local_scroll_then_uses_actual_viewport_and_bar(self):
        self.run_js(r'''
          const ed=full(),ctx=ed.dom.panes,target=ed.ac.input;let doc=0,local=0,moves=0;
          window.innerHeight=330;window.visualViewport.height=330;
          Object.defineProperty(ctx.search,'scrollTop',{get:()=>local,set:v=>{local=Math.max(0,Math.min(120,v));}});
          ctx.search.getBoundingClientRect=()=>({top:176-doc,bottom:564-doc,height:388,left:400,right:680});
          target.getBoundingClientRect=()=>({top:430-doc-local,bottom:462-doc-local,height:32,left:420,right:660});
          ed.dom.bar.box={top:270,bottom:330,height:60,left:0,right:1000};
          window.scrollBy=opts=>{doc+=opts.top;moves++;};target.focus();resizeEditorPanes();
          const rect=target.getBoundingClientRect();assert(rect.top>=0&&rect.bottom<=262);assert.equal(local,120);assert(moves>0);
          const count=moves;flushTimers();assert.equal(moves,count);assert.equal(document.activeElement,target);
        ''')

    def test_queued_reveal_never_steals_focus_or_scrolls_new_modal_busy_or_stale_view(self):
        self.run_js(r'''
          for(const mutate of [()=>outside.focus(),()=>{const d=openSheet('New modal');d.dialog.open=true;},
            ()=>ed.saving=true,()=>ed.asking=true,()=>ed.leaving=true,()=>target.disabled=true,
            ()=>routeToken++,()=>state.profile={id:'other'},()=>ed.version='owned',()=>ed.space='other',()=>ed.dom.page.remove()]) {
            clear(main);for(const dialog of document.querySelectorAll('dialog'))dialog.remove();state.profile=state.profiles[1];
            var ed=full(),ctx=ed.dom.panes,target=ed.ac.input,outside=el('button');main.append(outside);let moved=0;
            ctx.search.box={top:0,bottom:830,height:830,left:0,right:500};ed.dom.bar.box={top:760,bottom:830,height:70,left:0,right:1000};
            target.box={top:800,bottom:832,height:32,left:10,right:400};window.scrollBy=()=>{moved++;};
            target.focus();revealEditorPaneFocus(ctx,target);const before=moved;mutate();const active=document.activeElement;
            flushTimers();assert.equal(moved,before);assert.equal(document.activeElement,active);
          }
        ''')


class EditorPaneSourceTests(unittest.TestCase):
    def test_three_panes_have_bounded_side_tracks_original_search_scroller_and_no_fourth_peek(self):
        css=(WEB/'editor.css').read_text(encoding='utf-8')
        self.assertIn('minmax(0, 1fr) clamp(560px, calc(100% - 376px), 656px)',css)
        # Measured 1000px native work width was 936.57px: fixed max tracks had consumed 656px.
        # The bounded side track now reserves the list before growing either side pane.
        for work, side in ((936.57,560.57),(1000,624),(1200,656)):
            self.assertAlmostEqual(min(656,max(560,work-376)),side,places=2)
            self.assertGreaterEqual(work-side-16,360)
        self.assertNotIn('position: static; width: auto; height: auto;',css)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr))',css)
        self.assertIn('.edit-search-pane, .edit-facts-pane {',css)
        self.assertIn('max-height: inherit; min-height: 0; overflow-y: auto;',css)
        self.assertIn('.edit-page.has-editor-panes .peek-layout { display: block; }',css)
        self.assertIn('.edit-page.has-editor-panes .card-peek { display: none; }',css)
        self.assertNotIn('@media (max-width: 999px)',css)
        source=(WEB/'editor-screen.js').read_text(encoding='utf-8')
        project=re.search(r'(?ms)^function projectEditorPanes\(.*?^\}',source).group(0)
        for forbidden in ('clear(', '.append(', 'cardSearch(', 'addPart(', 'api(', 'apiWrite(', 'queueDraft(', 'changed('):
            self.assertNotIn(forbidden,project)
        self.assertEqual(source.count('window.addEventListener("resize", resizeEditorPanes)'),1)
        self.assertLess(len(source.splitlines()),1200)
