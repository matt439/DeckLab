"""The retained nonmodal Add dock, using invented in-process UI fixtures only."""
import json
import subprocess
import unittest

from decklab.tests import test_quick_editor_ui as quick
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = quick.SETUP + r'''
  function full() {
    window.matchMedia('(min-width: 600px)').matches=true;
    window.matchMedia('(min-width: 1000px)').matches=true;
    startEditor({mode:'edit',view:view(),version:'target',restoreDraft:false});
    return editor;
  }
  function width(wide) {
    window.matchMedia('(min-width: 1000px)').matches=wide;
    window.matchMedia('(min-width: 1000px)').fire('change');
  }
  function accepted(ac, cards=[{...elves,img_small:'/img/fixture/small',img:'/img/fixture/normal',have:{}}]) {
    ac.input.value=elves.name;ac.query=elves.name;ac.items=cards;ac.active=0;
    ac.page=1;ac.pages=3;ac.resultScope=editorSearchScope(ac);drawOptions(ac);
  }
  function ownHistory() {
    let pushes=0,backs=0,index=0;const entries=[{state:{pos:0},hash:location.hash}];history.state=entries[0].state;
    const hash=url=>url===undefined?location.hash:new URL(url,'http://localhost/').hash;
    history.pushState=(value,unused,url)=>{
      const next={state:value,hash:hash(url)};entries.splice(index+1);entries.push(next);index++;
      history.state=value;location.hash=next.hash;pushes++;
    };
    history.replaceState=(value,unused,url)=>{
      entries[index]={state:value,hash:hash(url)};history.state=value;location.hash=entries[index].hash;
    };
    history.back=()=>{backs++;index=Math.max(0,index-1);history.state=entries[index].state;location.hash=entries[index].hash;};
    return {get pushes(){return pushes;},get backs(){return backs;}};
  }
  function outsideFixture(height=400) {
    const ed=begin();openAddSheet();const dock=ed.dom.searchDock;
    window.innerHeight=height;window.visualViewport.height=height;
    const header=el('header',{class:'topbar'});header.box={top:0,bottom:40,height:40,left:0,right:393};document.body.append(header);
    let scroll=0,moves=0,reads=0;
    dock.bar.getBoundingClientRect=()=>{
      reads++;const top=Math.min(height-60,80+(parseFloat(dock.spacer.style.height)||0));
      return {top,bottom:top+60,height:60,left:0,right:393};
    };
    const field=el('input');dock.bar.parentNode.insertBefore(field,dock.spacer);
    field.getBoundingClientRect=()=>({top:height-100-scroll,bottom:height-56-scroll,height:44,left:10,right:160});
    window.scrollBy=(x,y)=>{moves++;scroll=Math.max(0,Math.min(parseFloat(dock.spacer.style.height)||0,scroll+y));};
    return {ed,dock,field,header,get moves(){return moves;},get reads(){return reads;},setScroll(n){scroll=n;}};
  }
  async function savedFixture(ed,sheet=null,id=ed.id||'casual/created-fixture') {
    const title=ed.fields.title||ed.title||'Saved fixture',calls=[];
    const savedView=view({id,title,fields:{...ed.fields},sha256:'b'.repeat(64),
      lists:{target:structuredClone(ed.lists),owned:ed.view?.lists?.owned||null}});
    apiWrite=async(path,body)=>{calls.push({path,body});return {id,title,deck:savedView,changed:true,stale_tables:[]};};
    await doSave(sheet,ed.dom.barParts.save);return calls;
  }
'''


@unittest.skipUnless(NODE, 'Node.js is not installed')
class EditorSearchDockUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)],
            input=json.dumps([str(WEB), SETUP + scenario, True,
                {'innerWidth': 393, 'innerHeight': 830, 'coarse': True,
                 'visual': {'width': 393, 'height': 830}}]),
            capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'ok')

    def test_quick_nonmodal_reopen_retains_search_controls_and_accepted_results(self):
        self.run_js(r'''
          const ed=begin(),before=listSignature(ed.lists),historyCounts=ownHistory();
          ed.dom.barParts.addCards.focus();openAddSheet();const dock=ed.dom.searchDock,ac=ed.ac;
          assert.equal(document.querySelectorAll('dialog').length,0);assert(dock.fixed&&dock.open);
          assert.equal(dock.root.parentNode,ed.dom.bar.parentNode);
          assert(dock.root.parentNode.children.indexOf(dock.root)<dock.root.parentNode.children.indexOf(ed.dom.bar));
          assert.equal(dock.root.getAttribute('role'),'region');assert.equal(ac.input,document.activeElement);
          accepted(ac);const row=ac.list.children[0],qty=row.querySelector('.qty-input');
          dock.close.focus();closeEditorSearchDock(dock);
          assert(ac.dockSuspended&&!ac.cancelled&&dock.root.hidden);assert.equal(ed.ac,ac);
          assert.equal(document.activeElement,ed.dom.barParts.addCards);
          openAddSheet();assert.equal(ed.ac,ac);assert.equal(ac.list.children[0],row);
          assert.equal(row.querySelector('.qty-input'),qty);assert(!ac.pickFirst&&!ac.dockSuspended);
          assert.equal(listSignature(ed.lists),before);assert.equal(historyCounts.pushes,1);
        ''')

    def test_closed_pending_exact_enter_cannot_add_or_replace_reopened_results(self):
        self.run_js(r'''
          const ed=begin();openAddSheet();const dock=ed.dom.searchDock,ac=ed.ac,before=listSignature(ed.lists);
          accepted(ac);const oldItems=ac.items,rows=[...ac.list.children];let resolve;
          api=()=>new Promise(r=>resolve=r);ac.pickFirst=true;ac.pickCount=4;
          const pending=lookUp(ac,elves.name);closeEditorSearchDock(dock,{focus:false});openAddSheet();
          resolve({cards:[elves],pages:1});await pending;
          assert.equal(listSignature(ed.lists),before);assert.equal(ac.items,oldItems);
          assert.equal(ac.list.children[0],rows[0]);assert(!ac.pickFirst&&ac.pickCount===null);
        ''')

    def test_cancelled_first_lookup_resumes_as_read_without_replaying_enter(self):
        self.run_js(r'''
          const ed=begin();openAddSheet();const dock=ed.dom.searchDock,ac=ed.ac,before=listSignature(ed.lists),pending=[];
          api=url=>new Promise(resolve=>pending.push({url,resolve}));
          ac.input.value=elves.name;ac.input.fire('input');ac.input.fire('keydown',{key:'Enter',shiftKey:true});
          assert(ac.pickFirst);closeEditorSearchDock(dock,{focus:false});openAddSheet();flushTimers();
          assert.equal(pending.length,2);assert(!ac.pickFirst);
          pending[0].resolve({cards:[elves],pages:1});pending[1].resolve({cards:[elves],pages:1});await settle();
          assert.equal(ac.items[0].name,elves.name);assert.equal(listSignature(ed.lists),before);
        ''')

    def test_dismissed_more_rolls_back_page_and_retry_requests_same_page(self):
        self.run_js(r'''
          begin();openAddSheet();const dock=editor.dom.searchDock,ac=editor.ac;accepted(ac);
          const row=ac.list.children[0],pending=[];api=url=>new Promise(resolve=>pending.push({url,resolve}));
          ac.more.click();assert.equal(ac.page,2);assert(ac.morePending);
          closeEditorSearchDock(dock,{focus:false});assert.equal(ac.page,1);assert(!ac.morePending);
          openAddSheet();pending[0].resolve({cards:[bolt],pages:3});await settle();
          assert.equal(ac.items.length,1);assert.equal(ac.list.children[0],row);
          ac.more.click();assert(new URLSearchParams(pending[1].url.split('?')[1]).get('page')==='2');
          pending[1].resolve({cards:[bolt],pages:3});await settle();assert.equal(ac.items.length,2);
        ''')

    def test_escape_clears_query_then_closes_without_outside_focus_theft(self):
        self.run_js(r'''
          begin();openAddSheet();const dock=editor.dom.searchDock,ac=editor.ac;accepted(ac);ac.input.focus();
          const escapeEvent=ac.input.fire('keydown',{key:'Escape'});dock.root.fire('keydown',escapeEvent);
          assert.equal(ac.input.value,'');assert(dock.open);
          dock.root.fire('keydown',{key:'Escape'});assert(!dock.open);
          openAddSheet();const outside=el('input');main.append(outside);outside.focus();
          closeEditorSearchDock(dock);assert.equal(document.activeElement,outside);
        ''')

    def test_modal_viewer_keeps_dock_and_its_exact_return_nodes(self):
        self.run_js(r'''
          begin();openAddSheet();const dock=editor.dom.searchDock,ac=editor.ac;accepted(ac);
          const trigger=ac.list.querySelector('.ac-thumb-btn');viewerDom=buildViewer();
          viewerState={trigger,history:false};viewerDom.dialog.open=true;viewerDom.dialog.setAttribute('open','');viewerDom.close.focus();
          dock.root.fire('keydown',{key:'Escape'});assert(dock.open);
          resizeEditorSearchDock();flushTimers();assert.equal(document.activeElement,viewerDom.close);
          assert.equal(ac.list.querySelector('.ac-thumb-btn'),trigger);
          viewerDom.dialog.open=false;viewerDom.dialog.removeAttribute('open');viewerClosed();
          assert.equal(document.activeElement,trigger);
        ''')

    def test_full_projection_keeps_focused_and_viewer_return_search_on_narrowing_without_history(self):
        self.run_js(r'''
          const ed=full(),dock=ed.dom.searchDock,ac=ed.ac,h=ownHistory();accepted(ac);ac.input.focus();
          width(false);assert(dock.fixed&&dock.open&&!dock.root.hidden);assert.equal(document.activeElement,ac.input);
          assert.equal(h.pushes,0);width(true);assert(!dock.fixed&&!dock.root.hidden);assert.equal(h.pushes,0);
          const trigger=ac.list.querySelector('.ac-thumb-btn');viewerDom=buildViewer();
          viewerState={trigger,history:false};viewerDom.dialog.setAttribute('open','');viewerDom.close.focus();
          dock.open=false;width(false);assert(dock.fixed&&dock.open&&!dock.root.hidden);
          assert.equal(document.activeElement,viewerDom.close);assert.equal(h.pushes,0);
          viewerState=null;viewerDom.dialog.remove();width(true);const stats=ed.dom.panes.panels.stats.querySelector('h2');
          stats.focus();width(false);assert(!dock.fixed&&dock.root.hidden);assert.equal(document.activeElement,stats);assert.equal(h.pushes,0);
        ''')

    def test_full_show_and_add_from_notes_open_same_search_while_passive_notes_resize_stays_closed(self):
        self.run_js(r'''
          const ed=full(),dock=ed.dom.searchDock,ac=ed.ac;const outside=el('button');main.append(outside);outside.focus();
          width(false);assert(dock.root.hidden&&ac.dockSuspended);foldSide(false);assert(dock.fixed&&dock.open);
          ed.tab='notes';drawMain();assert(!dock.open&&dock.root.hidden);const focus=document.activeElement;
          width(true);width(false);assert.equal(ed.tab,'notes');assert.equal(document.activeElement,focus);
          focusSearch();assert.equal(ed.tab,'cards');assert.equal(ed.ac,ac);assert(dock.fixed&&dock.open);
        ''')

    def test_notes_suspension_clears_old_search_keyboard_classes(self):
        self.run_js(r'''
          const ed=full(),dock=ed.dom.searchDock;ed.ac.input.focus();assert(document.body.classList.contains('is-searching'));
          document.body.classList.add('keyboard-up');assert(!dock.open);ed.tab='notes';drawMain();
          assert(dock.ac.dockSuspended&&dock.root.hidden);
          assert(!document.body.classList.contains('is-searching'));assert(!document.body.classList.contains('keyboard-up'));
        ''')

    def test_return_to_inline_after_cancelled_lookup_shows_honest_idle_without_resize_reads(self):
        self.run_js(r'''
          const ed=full(),ac=ed.ac;let reads=0;api=async()=>{reads++;return {cards:[elves]};};
          ac.input.value=elves.name;ac.input.fire('input');width(false);assert(ac.dockSuspended);
          width(true);flushTimers();assert.equal(reads,0);assert(!ac.dockSuspended);
          assert(ac.list.textContent.includes('Search paused.'));assert(!ac.pickFirst);
          const before=ed.lists.Deck[0].qty;ac.input.fire('keydown',{key:'Enter'});await settle();
          assert.equal(reads,1);assert.equal(ed.lists.Deck[0].qty,before+1);
        ''')

    def test_paste_reuses_owned_history_entry_and_leaves_retained_search_suspended(self):
        self.run_js(r'''
          begin();const h=ownHistory();openAddSheet();const dock=editor.dom.searchDock,ac=editor.ac,token=history.state.sheet;
          editorSearchPaste();assert(!dock.open&&ac.dockSuspended);assert(document.getElementById('paste-text'));
          assert.equal(document.querySelectorAll('dialog').length,1);assert.equal(sheetEntries.length,1);
          assert.notEqual(history.state.sheet,token);assert.equal(h.pushes,1);flushTimers();assert.equal(h.backs,0);
        ''')

    def test_save_shortcut_is_available_in_nonmodal_dock_and_blocked_by_real_modal(self):
        self.run_js(r'''
          begin();openAddSheet();let saveCalls=0;saveNow=()=>saveCalls++;
          const key=()=>({key:'s',ctrlKey:true,preventDefault(){this.prevented=true;}});
          const open=key();editorKeys(open);assert(open.prevented);assert.equal(saveCalls,1);
          const modal=el('dialog',{open:''});document.body.append(modal);const blocked=key();editorKeys(blocked);
          assert(blocked.prevented);assert.equal(saveCalls,1);
        ''')

    def test_real_shared_history_closes_viewer_then_explicit_dock(self):
        self.run_js(r'''
          Node.prototype.showModal=function(){this.open=true;this.setAttribute('open','');};
          Node.prototype.close=function(){this.open=false;this.removeAttribute('open');this.fire('close');};
          begin();const h=ownHistory();setUpDialog();openAddSheet();const dock=editor.dom.searchDock;accepted(editor.ac);
          const trigger=editor.ac.list.querySelector('.ac-thumb-btn'),entry=dock.entry;
          openCardViewer([editor.ac.items[0]],0,{trigger});assert.equal(h.pushes,2);
          history.state={pos:entry.pos,sheet:entry.token};window.fire('popstate');
          assert(!viewerState&&dock.open);assert.equal(document.activeElement,trigger);assert.equal(sheetEntries.length,1);
          history.state={pos:0};window.fire('popstate');assert(!dock.open&&dock.root.hidden);
          assert.equal(sheetEntries.length,0);assert.equal(h.backs,0);
        ''')

    def test_real_save_replacement_takes_over_own_entry_for_same_url_and_new_deck_url(self):
        self.run_js(r'''
          for(const mode of ['edit','new']) {
            location.hash=mode==='edit'?editHref('casual/sample','target'):'#/new?kind=casual';
            let ed;if(mode==='edit')ed=begin();else {startEditor({mode:'new',kind:'casual',restoreDraft:false});ed=editor;ed.fields.title='Created fixture';}
            const h=ownHistory();history.replaceState({...history.state,unrelated:'keep'},'');openAddSheet();const dock=ed.dom.searchDock;
            const calls=await savedFixture(ed);const current=editor,hash=location.hash,pos=entryPos();
            assert.notEqual(current,ed);assert(dock.disposed&&dock.ac.cancelled);assert.equal(pos,1);assert.equal(current.pos,pos);
            assert.equal(history.state.sheet,undefined);assert.equal(history.state.unrelated,'keep');flushTimers();
            assert.equal(h.backs,0);assert.equal(location.hash,hash);assert.equal(entryPos(),pos);assert.equal(editor,current);
            assert.equal(calls.length,1);assert.equal(calls[0].path,mode==='edit'?'/api/deck/save':'/api/decks');
            openAddSheet();assert.equal(editor.dom.searchDock.entry.pos,pos+1);closeEditorSearchDock();flushTimers();
            assert.equal(h.backs,1);assert.equal(location.hash,hash);closeEditor();
          }
        ''')

    def test_save_review_takeover_waits_for_exact_native_finish_before_retiring_its_mark(self):
        self.run_js(r'''
          const nativeCloses=[];Node.prototype.showModal=function(){this.open=true;this.setAttribute('open','');};
          Node.prototype.close=function(){this.open=false;this.removeAttribute('open');nativeCloses.push(()=>this.fire('close'));};
          location.hash=editHref('casual/sample','target');const ed=begin(),h=ownHistory();openAddSheet();
          const dock=ed.dom.searchDock,review=openSheet('Save fixture'),token=review.entry.token;
          assert(dock.sheets.has(token));await savedFixture(ed,review);const current=editor,hash=location.hash,pos=entryPos();
          assert(!review.closed&&!review.entry.done);assert.equal(history.state.sheet,token,'Live recorded token is not guessed closed');
          assert.equal(pos,2);assert.equal(current.pos,pos);nativeCloses.shift()();
          assert(review.closed&&review.entry.done);assert.equal(history.state.sheet,undefined);flushTimers();
          assert.equal(h.backs,0);assert.equal(location.hash,hash);assert.equal(editor,current);assert.equal(current.pos,entryPos());
        ''')

    def test_synchronously_closed_review_mark_cannot_back_off_created_saved_url(self):
        self.run_js(r'''
          Node.prototype.showModal=function(){this.open=true;this.setAttribute('open','');};
          Node.prototype.close=function(){this.open=false;this.removeAttribute('open');this.fire('close');};
          location.hash='#/new?kind=casual';startEditor({mode:'new',kind:'casual',restoreDraft:false});const ed=editor;ed.fields.title='Created fixture';
          const h=ownHistory();openAddSheet();const review=openSheet('Create fixture');await savedFixture(ed,review);
          const current=editor,hash=location.hash;assert(review.closed&&review.entry.done);assert.equal(history.state.sheet,undefined);
          flushTimers();assert.equal(h.backs,0);assert.equal(location.hash,hash);assert.equal(editor,current);assert.equal(current.pos,entryPos());
        ''')

    def test_explicit_paste_handoff_async_close_cannot_back_off_actual_save_replacement(self):
        self.run_js(r'''
          const closes=[];Node.prototype.showModal=function(){this.open=true;this.setAttribute('open','');};
          Node.prototype.close=function(){this.open=false;this.removeAttribute('open');closes.push(()=>this.fire('close'));};
          location.hash=editHref('casual/sample','target');const ed=begin(),h=ownHistory();ed.fields.archetype='Pending fixture';
          openAddSheet();const dock=ed.dom.searchDock;editorSearchPaste();assert(!dock.open&&!dock.pasteHandoff);
          const paste=[...dock.sheets.values()][0]?.sheet;assert(paste&&paste.body.querySelector('#paste-text'));
          paste.close();assert(!paste.dialog.open&&!paste.closed);const token=paste.entry.token;
          await savedFixture(ed);const current=editor,hash=location.hash,pos=entryPos();
          assert.equal(history.state.sheet,token);closes.shift()();flushTimers();
          assert.equal(h.backs,0);assert.equal(history.state.sheet,undefined);assert.equal(location.hash,hash);
          assert.equal(editor,current);assert.equal(current.pos,pos);assert.equal(current.fields.archetype,'Pending fixture');
        ''')

    def test_retired_review_finish_preserves_new_live_sheet_and_stale_owner_close_has_no_back_effect(self):
        self.run_js(r'''
          const nativeCloses=[];Node.prototype.showModal=function(){this.open=true;this.setAttribute('open','');};
          Node.prototype.close=function(){this.open=false;this.removeAttribute('open');nativeCloses.push(()=>this.fire('close'));};
          const ed=begin(),h=ownHistory();openAddSheet();const review=openSheet('Save fixture');await savedFixture(ed,review);
          const other=openSheet('New unrelated live sheet'),mark=history.state.sheet,pos=entryPos(),hash=location.hash;
          nativeCloses.shift()();flushTimers();assert.equal(history.state.sheet,mark);assert.equal(entryPos(),pos);assert.equal(location.hash,hash);
          assert(!other.closed&&!other.entry.done);assert.equal(h.backs,0);
          // A stale dock cannot remove or step off a replacement search's history owner.
          other.entry.fromHistory=true;other.close();nativeCloses.shift()();flushTimers();
          closeEditor();begin();const nextHistory=ownHistory();openAddSheet();const stale=editor.dom.searchDock;
          main.append(cardSearch());document.body.classList.add('is-searching');closeEditorSearchDock(stale);flushTimers();
          assert.equal(nextHistory.backs,0);assert(document.body.classList.contains('is-searching'));
        ''')

    def test_trial_new_copy_and_actual_new_space_choice_keep_current_search_and_permissions(self):
        self.run_js(r'''
          let ed=begin({may_save:false});openAddSheet();assert(ed.readOnly&&ed.dom.searchDock.open);assert(!ed.dom.barParts.save);
          startEditor({mode:'new',kind:'casual',restoreDraft:false});ed=editor;openAddSheet();assert(ed.dom.searchDock.open&&!ed.readOnly);
          startEditor({mode:'new',kind:'casual',from:'casual/source',view:view({new_deck:{kind:'casual',title:'Copy fixture'}}),restoreDraft:false});
          ed=editor;openAddSheet();assert.equal(ed.from,'casual/source');assert(ed.dom.searchDock.open);
          createTargets=()=>[{space:'home',player:'wife'},{space:'other'}];
          window.matchMedia('(min-width: 600px)').matches=true;window.matchMedia('(min-width: 1000px)').matches=false;
          startEditor({mode:'new',kind:'casual',restoreDraft:false});ed=editor;focusSearch();const ac=ed.ac,dock=ed.dom.searchDock;
          let resolve;api=()=>new Promise(r=>resolve=r);ac.input.value=elves.name;const pending=lookUp(ac,elves.name);
          const other=ed.space==='home'?'other':'home';main.querySelector(`[data-space="${other}"]`).click();
          resolve({cards:[elves],pages:1});await pending;
          assert.equal(ed.space,other);assert.equal(ed.ac,ac);assert.equal(ed.dom.searchDock,dock);
          assert.equal(ac.items.length,0);assert(editorSearchCurrent(ac));assert(dock.open&&dock.fixed);
          startEditor({mode:'edit',view:view({lists:{target:structuredClone(list),owned:null}}),version:'owned',restoreDraft:false});openAddSheet();
          assert(noOwnedList());assert(!editor.dom.searchDock&&!editor.ac);
        ''')

    def test_bar_observer_is_scoped_disconnected_and_old_callback_cannot_size_replacement(self):
        self.run_js(r'''
          const observers=[];globalThis.ResizeObserver=class {
            constructor(callback){this.callback=callback;observers.push(this);}
            observe(target){this.target=target;}
            disconnect(){this.disconnected=true;}
          };
          const ed=begin();openAddSheet();const dock=ed.dom.searchDock,observer=observers[0];
          assert.equal(observer.target,ed.dom.bar);closeEditor();assert(observer.disconnected);
          begin();openAddSheet();const next=editor.dom.searchDock;next.root.style.top='current';
          observer.callback();flushTimers();assert.equal(dock.disposed,true);assert(next.open);
          // The current instance's own frame may size itself; the old observer never queues its frame.
          assert.equal(dock.frame,0);assert.equal(observers.length,2);
        ''')

    def test_geometry_uses_actual_bar_header_and_visual_offset_without_scale_multiplication(self):
        self.run_js(r'''
          const ed=begin();openAddSheet();const dock=ed.dom.searchDock;
          const header=el('header',{class:'topbar'});document.body.append(header);
          header.box={top:40,bottom:90,left:10,right:390,height:50};
          ed.dom.bar.box={top:420,bottom:510,left:10,right:390,height:90};
          Object.assign(window.visualViewport,{offsetTop:40,offsetLeft:10,width:380,height:500,scale:2});
          fitEditorSearchDock(dock);same([dock.root.style.top,dock.root.style.left,dock.root.style.width,dock.root.style.height],
            ['90px','10px','380px','330px']);
          ed.dom.bar.box.top=350;ed.dom.bar.box.height=160;resizeEditorSearchDock();flushTimers();
          assert.equal(dock.root.style.height,'260px');assert.equal(dock.root.style.top,'90px');
          Object.assign(window.visualViewport,{offsetLeft:10.25,width:380.5});ed.dom.bar.box.top=350.75;
          fitEditorSearchDock(dock);assert.equal(dock.root.style.left,'11px');assert.equal(dock.root.style.width,'379px');
          assert(Number.parseFloat(dock.root.style.top)+Number.parseFloat(dock.root.style.height)<=350.75);
        ''')

    def test_short_editor_spacer_remeasures_moving_bar_and_clears_on_notes_and_dispose(self):
        self.run_js(r'''
          const f=outsideFixture();fitEditorSearchDock(f.dock);
          assert(f.reads>=2);assert.equal(f.dock.spacer.style.height,'300px');
          assert.equal(f.dock.root.style.top,'40px');assert.equal(f.dock.root.style.height,'300px');
          assert.equal(parseFloat(f.dock.root.style.top)+parseFloat(f.dock.root.style.height),f.dock.bar.getBoundingClientRect().top);
          f.ed.tab='notes';drawMain();assert(f.dock.spacer.hidden);assert.equal(f.dock.spacer.style.height,'0px');
          focusSearch();assert(f.dock.open);const spacer=f.dock.spacer;closeEditor();assert(!spacer.isConnected);
        ''')

    def test_outside_last_row_focus_gets_real_scroll_range_and_remains_above_dock_without_refocus(self):
        self.run_js(r'''
          const f=outsideFixture(),target=f.field;let focuses=0;
          const focus=target.focus.bind(target);target.focus=(...args)=>{focuses++;focus(...args);};target.focus();
          document.fire('focusin',{target});flushTimers();
          assert.equal(document.activeElement,target);assert.equal(focuses,1);assert.equal(f.moves,1);
          const rect=target.getBoundingClientRect(),dockTop=parseFloat(f.dock.root.style.top);
          assert(rect.top>=40&&rect.bottom<=dockTop);assert.equal(f.dock.spacer.style.height,'300px');
          assert.equal(f.dock.root.style.height,'240px');assert(f.dock.open);
          f.ed.dom.barParts.save.focus();document.fire('focusin',{target:f.ed.dom.barParts.save});const before=f.moves;
          flushTimers();assert.equal(f.moves,before);assert.equal(document.activeElement,f.ed.dom.barParts.save);
        ''')

    def test_short_viewport_shrinks_dock_for_same_outside_control_and_oversized_alignment_is_stable(self):
        self.run_js(r'''
          const f=outsideFixture(180),target=f.field;target.focus();document.fire('focusin',{target});flushTimers();
          assert.equal(f.dock.root.style.height,'20px');assert(target.getBoundingClientRect().bottom<=parseFloat(f.dock.root.style.top));
          let scroll=0;target.getBoundingClientRect=()=>({top:80-scroll,bottom:224-scroll,height:144,left:10,right:160});
          window.scrollBy=(x,y)=>{scroll+=y;};revealEditorSearchDockOutside(f.dock,target);flushTimers();
          assert.equal(f.dock.root.style.height,'0px');assert.equal(target.getBoundingClientRect().top,48);
          const done=scroll;revealEditorSearchDockOutside(f.dock,target);flushTimers();assert.equal(scroll,done);
        ''')

    def test_outside_reveal_drops_focus_modal_scope_and_attachment_changes_without_scrolling(self):
        self.run_js(r'''
          for(const action of ['focus','modal','saving','asking','route','hash','space','disabled','reparent','page']) {
            for(const modal of document.querySelectorAll('dialog'))modal.remove();state.profile=state.profiles[1];
            const f=outsideFixture(),target=f.field;target.focus();document.fire('focusin',{target});
            if(action==='focus')f.ed.dom.barParts.save.focus();
            else if(action==='modal')document.body.append(el('dialog',{open:true}));
            else if(action==='saving'||action==='asking')f.ed[action]=true;
            else if(action==='route')routeToken++;
            else if(action==='hash')location.hash+='_other';
            else if(action==='space')f.ed.space='other';
            else if(action==='disabled')target.disabled=true;
            else if(action==='reparent'){target.remove();document.body.append(target);}
            else f.ed.dom.page.remove();
            const active=document.activeElement;flushTimers();assert.equal(f.moves,0,action);assert.equal(document.activeElement,active);
          }
        ''')

    def test_owned_native_modal_return_queues_one_outside_reveal_but_manual_scroll_is_respected(self):
        self.run_js(r'''
          const f=outsideFixture(),target=f.field,modal=el('dialog',{open:true});document.body.append(modal);
          target.focus();document.fire('focusin',{target});assert.equal(f.moves,0);
          modal.remove();flushTimers();assert.equal(f.moves,1);assert.equal(document.activeElement,target);
          f.setScroll(0);const before=f.moves;window.fire('scroll',{type:'scroll'});flushTimers();assert.equal(f.moves,before);
          f.dock.close.focus();document.fire('focusin',{target:f.dock.close});flushTimers();assert.equal(f.moves,before);
        ''')

    def test_focus_reveal_is_local_reserves_sticky_input_and_drops_stale_deferred_work(self):
        self.run_js(r'''
          const ed=begin();openAddSheet();const dock=ed.dom.searchDock,ac=ed.ac;accepted(ac);
          const target=ac.list.querySelector('.qty-input'),body=ed.dom.addPart,band=ac.input.closest('.ac');
          body.box={top:100,bottom:400,left:0,right:393,height:300};body.scrollTop=100;
          band.box={top:100,bottom:156,left:0,right:393,height:56};target.box={top:110,bottom:154,left:20,right:154,height:44};
          let moved=0;window.scrollBy=()=>moved++;target.focus();revealEditorSearchDockFocus(dock,target);flushTimers();
          assert.equal(body.scrollTop,54);assert.equal(document.activeElement,target);assert.equal(moved,0);
          target.focus();revealEditorSearchDockFocus(dock,target);const before=body.scrollTop;
          const outside=el('input');main.append(outside);outside.focus();flushTimers();assert.equal(body.scrollTop,before);
          target.focus();revealEditorSearchDockFocus(dock,target);closeEditorSearchDock(dock,{focus:false});flushTimers();
          assert.equal(body.scrollTop,before);assert.equal(moved,0);
        ''')

    def test_deferred_fit_rejects_route_profile_mount_and_replaced_editor_and_disconnects_observer(self):
        self.run_js(r'''
          for(const mutate of [()=>routeToken++,()=>location.hash+='_different',()=>state.profile={id:'elsewhere'},()=>editor.dom.page.remove(),
            ()=>{const wrap=editor.ac.wrap;wrap.remove();main.append(wrap);},
            ()=>{const d=editor.dom.searchDock,host=el('div');d.spacer.remove();d.bar.remove();host.append(d.spacer,d.bar);document.body.append(host);},
            ()=>editor.ac=cardSearch()]) {
            state.profile=state.profiles[1];const ed=begin();openAddSheet();const dock=ed.dom.searchDock;
            dock.root.style.top='sentinel';queueEditorSearchDockFit(dock);mutate();flushTimers();assert.equal(dock.root.style.top,'sentinel');
          }
          state.profile=state.profiles[1];const ed=begin();openAddSheet();const old=ed.dom.searchDock;
          closeEditor();assert(old.disposed&&old.ac.cancelled&&!old.root.isConnected);
          begin();openAddSheet();const next=editor.dom.searchDock;closeEditorSearchDock(old);
          assert(next.open&&document.body.classList.contains('has-editor-search-dock'));
        ''')

    def test_deferred_reveal_refuses_same_focused_control_reparented_outside_its_add_body(self):
        self.run_js(r'''
          begin();openAddSheet();const dock=editor.dom.searchDock,ac=editor.ac;accepted(ac);const target=ac.list.querySelector('.qty-input');
          dock.part.box={top:100,bottom:250,height:150,left:0,right:393};dock.part.scrollTop=20;
          target.box={top:602,bottom:646,height:44,left:10,right:150};target.focus();revealEditorSearchDockFocus(dock,target);
          target.remove();dock.root.append(target);assert.equal(document.activeElement,target);assert(target.isConnected);
          flushTimers();assert.equal(dock.part.scrollTop,20);
        ''')


class EditorSearchDockSourceTests(unittest.TestCase):
    def test_dock_sizes_bound_scrolling_and_leave_original_action_bar_available(self):
        css = (WEB / 'editor.css').read_text(encoding='utf-8')
        self.assertIn('.edit-search-dock .search-input { min-height: 48px;', css)
        self.assertIn('.edit-search-dock .ac-option { min-height: 76px;', css)
        self.assertIn('.edit-search-dock .ac-colour { width: var(--tap); height: var(--tap); }', css)
        self.assertIn('.edit-search-dock .edit-dock-head h2 { display: block;', css)
        self.assertIn('.edit-dock-clearance { flex: none; pointer-events: none; overflow-anchor: none; }', css)
        self.assertIn('body.has-editor-search-dock.is-searching.keyboard-up .edit-bar { display: flex; }', css)
        self.assertIn('max-height: none !important; overflow: visible;', css)

    def test_runtime_and_fixture_load_dock_once_after_quantity_and_before_save(self):
        html = (WEB / 'index.html').read_text(encoding='utf-8')
        self.assertEqual(html.count('src="/editor-search-dock.js"'), 1)
        self.assertLess(html.index('/editor-search-quantity.js'), html.index('/editor-search-dock.js'))
        self.assertLess(html.index('/editor-search-dock.js'), html.index('/editor-save.js'))
        source = (WEB / 'editor-search-dock.js').read_text(encoding='utf-8')
        self.assertNotIn('showModal', source)
        self.assertNotIn('apiWrite(', source)
        self.assertNotIn('history.back(', source)
        self.assertEqual(source.count('window.addEventListener("resize", resizeEditorSearchDock)'), 1)
        self.assertEqual(source.count('window.addEventListener("scroll", resizeEditorSearchDock)'), 1)
