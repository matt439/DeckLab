"""Preferred-line search quantities and action-only async cancellation."""
import re
import unittest

from decklab.tests import test_quick_editor_ui as quick, test_workspace_ui as workspace


REAL_CHANGED = re.search(r'(?ms)^function changed\(.*?^\}',
                        (workspace.WEB / 'editor-screen.js').read_text(encoding='utf-8')).group()
SETUP = r"""
  toast=()=>{};
  function found(cards,q=cards[0].name) {
    const ac=editor.ac;ac.input.value=q;ac.items=cards;ac.query=q;ac.active=0;drawOptions(ac);return ac;
  }
  const quantity=(ac,index=0)=>ac.list.querySelectorAll('.ac-actions')[index].searchQuantity;
"""


@unittest.skipUnless(workspace.NODE, "Node.js isn't installed")
class EditorSearchQuantityUiTests(unittest.TestCase):
    def run_js(self, scenario):
        quick.QuickEditorUiTests().run_js('changed = '+REAL_CHANGED+';\n'+SETUP+scenario)

    def test_exact_shared_resolver_never_sums_names_sections_or_normalizes_finish(self):
        self.run_js(r"""
          const lines=[{uid:'a',name:elves.name,qty:2,set:'old',number:'1',finish:'foil'},
            {uid:'b',name:elves.name,qty:3,set:'new',number:'7',finish:'nonfoil'},
            {uid:'c',name:elves.name,qty:4,set:'new',number:'7',finish:'foil'},
            {uid:'d',name:elves.name,qty:5,set:null,number:null,finish:'nonfoil'}];
          const ed={lists:{Deck:lines,Sideboard:[{...lines[2],uid:'side',qty:11}]}};
          const before=JSON.stringify(ed),card={...elves,default:{set:'new',number:'7',finish:'foil'}};
          assert.equal(editorAddLine(ed,card,'Deck'),lines[2]);
          assert.equal(editorAddLine(ed,card,'Sideboard').uid,'side');
          assert.equal(editorAddLine(ed,{...card,default:{set:'new',number:'7'}},'Deck'),lines[0]);
          assert.equal(editorAddLine(ed,{...card,default:null},'Deck'),lines[3]);
          assert.equal(editorAddLine(ed,card,'Commander'),undefined);
          assert.equal(JSON.stringify(ed),before);
        """)

    def test_quick_outside_main_follows_one_printing_and_selected_section_in_place(self):
        self.run_js(r"""
          begin();editor.lists=copyList({Deck:[{qty:2,name:elves.name,set:'old',number:'1',finish:'foil',card:elves},
            {qty:3,name:elves.name,set:'new',number:'7',finish:'nonfoil',card:elves}],
            Sideboard:[{qty:8,name:elves.name,set:'new',number:'7',finish:'nonfoil',card:elves}]});
          drawLines();openAddSheet();
          const card={...elves,default:{set:'new',number:'7',finish:'nonfoil'}},ac=found([card]);
          assert.equal(main.contains(ac.wrap),true);
          const record=quantity(ac),qtyField=record.qty,inspect=ac.list.querySelector('.ac-thumb-btn');
          assert.equal(ac.list.fire('mousedown',{target:qtyField}).defaultPrevented,false);
          assert.equal(ac.list.fire('mousedown',{target:record.plus}).defaultPrevented,false);
          assert.equal(ac.list.fire('mousedown',{target:record.addButton}).defaultPrevented,true);
          assert.equal(qtyField.value,'3');assert.equal(record.addButton.hidden,true);
          assert(record.context.textContent.includes('NEW 7'));assert(record.context.textContent.includes('Deck'));
          record.plus.click();same(editor.lists.Deck.map(line=>line.qty),[2,4]);assert.equal(qtyField.value,'4');
          assert.equal(editor.lists.Sideboard[0].qty,8);assert.equal(quantity(ac),record);
          editor.addSection='Sideboard';drawAddTo();assert.equal(qtyField.value,'8');
          assert(record.context.textContent.includes('Sideboard'));
          qtyField.value='6';qtyField.fire('input');assert.equal(editor.lists.Sideboard[0].qty,6);
          same(editor.lists.Deck.map(line=>line.qty),[2,4]);assert.equal(quantity(ac).qty,qtyField);
          assert.equal(ac.list.querySelector('.ac-thumb-btn'),inspect);
        """)

    def test_zero_uses_original_remove_undo_and_max_recovers_focus_without_replacing_controls(self):
        self.run_js(r"""
          begin();editor.lists.Deck[0].qty=1;drawLines();openAddSheet();const ac=found([elves]);
          const record=quantity(ac),line=editor.lists.Deck[0],group=record.group;
          record.minus.focus();record.minus.click();
          assert(!editor.lists.Deck.includes(line));assert.equal(editor.removed[0].line,line);
          assert.equal(record.group.hidden,true);assert.equal(record.addButton.hidden,false);
          assert.equal(document.activeElement,record.addButton);
          const undo=main.querySelector(`[data-removed="${line.uid}"]`).querySelector('.undo-btn');
          undo.focus();undo.click();assert.equal(editor.lists.Deck.find(row=>row.uid===line.uid),line);
          assert.equal(record.group,group);assert.equal(record.group.hidden,false);assert.equal(record.qty.value,'1');
          assert.notEqual(document.activeElement,record.qty,'search refresh does not take focus from original Undo');
          record.qty.value='99';record.qty.fire('input');assert.equal(line.qty,MAX_COPIES);
          assert.equal(record.plus.disabled,true);record.qty.value='';record.qty.fire('change');
          assert.equal(record.qty.value,'99');record.qty.value='0';record.qty.fire('input');record.qty.fire('change');
          assert.equal(record.group.hidden,true);assert.equal(editor.removed.length,1);
        """)

    def test_commander_add_keeps_enter_increment_and_auto_section_transition(self):
        self.run_js(r"""
          begin({kind:'commander',sections:['Commander','Deck','Sideboard'],
            lists:{target:{Commander:[],Deck:[{qty:2,name:elves.name,card:elves}],Sideboard:[]},owned:null}});
          editor.addSection='Commander';openAddSheet();const ac=found([elves]);
          assert.equal(quantity(ac).group.hidden,true);ac.input.fire('keydown',{key:'Enter',shiftKey:true});
          assert.equal(editor.lists.Commander[0].qty,4);assert.equal(editor.addSection,'Deck');
          assert.equal(quantity(ac).qty.value,'2');assert(quantity(ac).context.textContent.includes('The 99'));
          assert.equal(document.activeElement,ac.input);
          ac.input.value='3 '+elves.name;ac.input.fire('keydown',{key:'Enter'});
          assert.equal(editor.lists.Deck[0].qty,5);assert.equal(editor.lists.Commander[0].qty,4);
          editor.addSection='Commander';drawAddTo();assert.equal(quantity(ac).qty.value,'4');
        """)

    def test_stale_line_control_cannot_retarget_a_removed_replaced_or_moved_uid(self):
        self.run_js(r"""
          begin();openAddSheet();const ac=found([elves]),record=quantity(ac),line=record.line;
          editor.lists.Deck=editor.lists.Deck.filter(row=>row!==line);
          editor.lists.Sideboard.push(line);const before=line.qty;
          record.plus.click();assert.equal(line.qty,before);assert.equal(record.group.hidden,true);
          editor.addSection='Sideboard';drawAddTo();assert.equal(record.qty.value,String(before));
          const replacement={...line};editor.lists.Sideboard=editor.lists.Sideboard.map(row=>row===line?replacement:row);
          record.plus.click();assert.equal(replacement.qty,before,'old binding resyncs without applying to replacement');
          closeEditor();begin();const next=JSON.stringify(editor.lists);record.plus.click();record.minus.click();
          assert.equal(JSON.stringify(editor.lists),next);
        """)

    def test_native_inspect_and_prefix_nodes_survive_quantity_added_more_and_no_art_return(self):
        self.run_js(r"""
          begin();openAddSheet();const pictured={...elves,img_small:'/img/f/small',img:'/img/f/normal'};
          const ac=found([pictured]),row=ac.list.querySelector('.ac-option'),record=quantity(ac);
          const inspect=row.querySelector('.ac-thumb-btn');assert(!record.group.closest('button'));
          assert.equal(row.contains(record.group),true);record.plus.click();
          ac.pages=2;drawOptions(ac);let resolve;api=()=>new Promise(done=>{resolve=done;});
          ac.more.click();viewerDom=buildViewer();viewerState={trigger:inspect,history:false};
          viewerDom.dialog.open=true;viewerDom.dialog.setAttribute('open','');viewerDom.close.focus();
          resolve({cards:[bolt],pages:2});await settle();
          assert.equal(ac.list.querySelector('.ac-option'),row);assert.equal(quantity(ac),record);
          assert.equal(row.querySelector('.ac-thumb-btn'),inspect);assert.equal(document.activeElement,viewerDom.close);
          viewerDom.dialog.open=false;viewerDom.dialog.removeAttribute('open');viewerClosed();assert.equal(document.activeElement,inspect);
          ac.items=[elves];ac.query=elves.name;ac.input.value=elves.name;drawOptions(ac);ac.active=0;
          viewResult(ac);assert.equal(inspections.at(-1).trigger,quantity(ac).qty,'no-art return uses visible retained quantity field');
        """)
        css = (workspace.WEB / 'editor.css').read_text(encoding='utf-8')
        self.assertRegex(css, r'\.ac-list \.ac-option\.is-in-list\s*\{[^}]*grid-template-columns:\s*44px minmax\(0, 1fr\)')
        self.assertRegex(css, r'\.ac-option\.is-in-list \.ac-actions\s*\{[^}]*grid-column:\s*1 / -1;[^}]*flex-wrap:\s*wrap;')
        self.assertRegex(css, r'\.ac-result-facts \.ac-name-text\s*\{[^}]*white-space:\s*normal;[^}]*line-clamp:\s*unset;')
        self.assertRegex(css, r'\.ac-result-facts \.ac-side\s*\{[^}]*flex-wrap:\s*wrap;')

    def test_async_exact_enter_drops_behind_saving_asking_or_unrelated_modal_but_paints(self):
        self.run_js(r"""
          editor=null;for(const blocker of ['saving','asking','viewer','paste']) {
            closeEditor();for(const old of document.querySelectorAll('dialog'))old.remove();
            begin();openAddSheet();const ac=editor.ac,before=JSON.stringify(editor.lists);
            let resolve;api=()=>new Promise(done=>{resolve=done;});
            ac.input.value=elves.name;ac.input.fire('input');ac.input.fire('keydown',{key:'Enter',shiftKey:true});
            assert.equal(ac.pickFirst,true);let dialog;
            if(blocker==='saving'||blocker==='asking')editor[blocker]=true;
            else {dialog=el('dialog',{open:true});document.body.append(dialog);}
            resolve({cards:[elves]});await settle();
            assert.equal(JSON.stringify(editor.lists),before);assert.equal(ac.items[0].name,elves.name);
            assert.equal(ac.pickFirst,false);assert.equal(ac.pickCount,null);
            if(dialog)dialog.remove();else editor[blocker]=false;
            syncEditorSearchQuantities(ac);assert.equal(JSON.stringify(editor.lists),before,'blocked intent never replays');
          }
        """)

    def test_actions_reject_busy_modal_route_profile_query_and_keep_own_quick_dialog_valid(self):
        self.run_js(r"""
          begin();openAddSheet();const ac=found([elves]),record=quantity(ac);const start=record.line.qty;
          record.plus.click();assert.equal(record.line.qty,start+1,'own Quick dialog allows current native quantity action');
          for(const flag of ['saving','asking']){editor[flag]=true;record.plus.click();editor[flag]=false;}
          const dialog=el('dialog',{open:true});document.body.append(dialog);record.plus.click();dialog.remove();
          const token=routeToken;routeToken++;record.plus.click();routeToken=token;
          const profile=state.profile;state.profile={id:'other'};record.minus.click();state.profile=profile;
          ac.input.value='A different query';record.plus.click();
          assert.equal(record.line.qty,start+1);assert.equal(inspections.length,0);
        """)

    def test_actual_full_editor_save_check_and_paste_open_drop_only_pending_add_intent(self):
        self.run_js(r"""
          window.matchMedia('(min-width: 600px)').matches=true;
          startEditor({mode:'edit',view:view(),version:'target'});assert.equal(editor.quick,false);
          focusSearch();const ac=editor.ac,before=JSON.stringify(editor.lists);let findAnswer,checkAnswer;
          let writes=0;apiWrite=async()=>{writes++;throw Error('unexpected write');};
          api=()=>new Promise(done=>{findAnswer=done;});
          ac.input.value=elves.name;ac.input.fire('input');ac.input.fire('keydown',{key:'Enter'});
          runCheck=()=>new Promise(done=>{checkAnswer=done;});
          const saving=saveNow();assert.equal(editor.saving,true);
          findAnswer({cards:[elves]});await settle();
          assert.equal(ac.items[0].name,elves.name);assert.equal(ac.pickFirst,false);
          assert.equal(JSON.stringify(editor.lists),before);
          checkAnswer({blocks:[],changes:{decklist:false,fields:[],prose:[],marker:false}});await saving;
          assert.equal(editor.saving,false);assert.equal(JSON.stringify(editor.lists),before);
          ac.input.value=elves.name;ac.input.fire('input');ac.input.fire('keydown',{key:'Enter',shiftKey:true});
          let paste;const makeSheet=openSheet;openSheet=options=>(paste=makeSheet(options));
          openPaste();assert(paste.dialog.isConnected);assert.equal(paste.dialog.contains(ac.input),false);
          findAnswer({cards:[elves]});await settle();
          assert.equal(ac.pickFirst,false);assert.equal(ac.pickCount,null);assert.equal(JSON.stringify(editor.lists),before);
          paste.close();syncEditorSearchQuantities(ac);assert.equal(JSON.stringify(editor.lists),before);assert.equal(writes,0);
        """)

    def test_explicit_enter_commit_needs_no_implicit_change_and_removal_focus_survives_blur(self):
        self.run_js(r"""
          begin();openAddSheet();const ac=found([elves]),record=quantity(ac),line=record.line;
          record.qty.focus();record.qty.value='0';record.qty.fire('input');
          let blurs=0;record.qty.blur=()=>{blurs++;document.activeElement=document.body;record.qty.fire('blur');};
          const history=editor.history.length;const event=record.qty.fire('keydown',{key:'Enter'});
          assert(event.defaultPrevented);assert.equal(blurs,0,'zero commit repairs Add before any native blur');
          assert.equal(editor.removed.length,1);assert.equal(editor.removed[0].line,line);
          assert.equal(editor.history.length,history+1);assert.equal(record.group.hidden,true);
          assert.equal(document.activeElement,record.addButton);
          record.qty.fire('change');record.qty.fire('blur',{relatedTarget:record.plus});
          assert.equal(editor.removed.length,1);assert.equal(editor.history.length,history+1);
          assert.equal(document.activeElement,record.addButton);
        """)

    def test_body_active_blur_commits_zero_once_without_retargeting_another_printing(self):
        self.run_js(r"""
          begin();editor.lists.Deck=copyList({Deck:[
            {qty:1,name:elves.name,set:'fdn',number:'227',finish:'nonfoil',card:elves},
            {qty:9,name:elves.name,set:'other',number:'1',finish:'foil',card:elves}]}).Deck;
          drawLines();openAddSheet();const ac=found([{...elves,default:{set:'fdn',number:'227',finish:'nonfoil'}}]);
          const record=quantity(ac),original=record.line,fallback=editor.lists.Deck[1];
          record.qty.focus();record.qty.value='0';record.qty.fire('input');const history=editor.history.length;
          document.activeElement=document.body;record.qty.fire('blur',{relatedTarget:record.plus});
          assert.equal(editor.removed[0].line,original);assert.equal(record.line,fallback);
          assert.equal(record.qty.value,'9');assert.equal(fallback.qty,9);
          record.qty.fire('change');record.qty.fire('blur');
          assert.equal(editor.removed.length,1);assert.equal(fallback.qty,9);assert.equal(editor.history.length,history+1);
          // With no fallback, BODY->own hidden Plus exits recover the current visible Add.
          record.qty.focus();record.qty.value='0';record.qty.fire('input');document.activeElement=document.body;
          record.qty.fire('blur',{relatedTarget:record.plus});
          assert.equal(record.group.hidden,true);assert.equal(document.activeElement,record.addButton);
        """)

    def test_invalid_blur_resets_without_history_and_outside_focus_is_not_taken_by_zero_commit(self):
        self.run_js(r"""
          begin();openAddSheet();const ac=found([elves]),record=quantity(ac),start=record.line.qty;
          record.qty.focus();record.qty.value='ab';record.qty.fire('input');const history=editor.history.length;
          document.activeElement=document.body;record.qty.fire('blur',{relatedTarget:record.plus});
          assert.equal(record.qty.value,String(start));assert.equal(record.line.qty,start);assert.equal(editor.history.length,history);
          const outside=el('button');document.body.append(outside);record.qty.focus();record.qty.value='0';record.qty.fire('input');
          let addFocus=0;const focus=record.addButton.focus.bind(record.addButton);record.addButton.focus=(...args)=>{addFocus++;focus(...args);};
          outside.focus();record.qty.fire('blur',{relatedTarget:outside});
          assert.equal(editor.removed.length,1);assert.equal(document.activeElement,outside);assert.equal(addFocus,0);
          record.qty.fire('change');assert.equal(document.activeElement,outside);assert.equal(addFocus,0);
        """)

    def test_commit_drops_stale_busy_and_other_modal_edits_without_deferred_replay(self):
        self.run_js(r"""
          editor=null;
          for(const mode of ['saving','asking','modal','query','route','profile','line','section','detached','editor']) {
            closeEditor();for(const dialog of document.querySelectorAll('dialog'))dialog.remove();state.profile=state.profiles[1];
            begin();openAddSheet();const ed=editor,ac=found([elves]),record=quantity(ac),line=record.line;
            record.qty.focus();record.qty.value='0';record.qty.fire('input');const history=ed.history.length;
            if(mode==='saving'||mode==='asking')ed[mode]=true;
            else if(mode==='modal')document.body.append(el('dialog',{open:true}));
            else if(mode==='query')ac.input.value='another name';
            else if(mode==='route')routeToken++;
            else if(mode==='profile')state.profile={id:'other'};
            else if(mode==='line')ed.lists.Deck=ed.lists.Deck.map(row=>row===line?{...row}:row);
            else if(mode==='section')ed.addSection='Sideboard';
            else if(mode==='detached')ac.wrap.remove();
            else if(mode==='editor')begin();
            record.qty.fire('change'); // A rejected focused change must not wait and replay after guards clear.
            document.activeElement=document.body;record.qty.fire('blur');record.qty.fire('change');
            assert.equal(line.qty,4,mode);assert.equal(ed.removed.length,0,mode);assert.equal(ed.history.length,history,mode);
            ed.saving=false;ed.asking=false;for(const dialog of document.querySelectorAll('dialog'))dialog.remove();
            record.qty.fire('change');assert.equal(ed.removed.length,0,mode+' no replay');
          }
        """)

    def test_outside_blur_destination_never_focuses_add_with_old_quantity_or_body_active(self):
        self.run_js(r"""
          editor=null;
          for(const active of ['quantity','body']) {
            closeEditor();for(const dialog of document.querySelectorAll('dialog'))dialog.remove();
            begin({}, {restoreDraft:false});openAddSheet();const ac=found([elves]),record=quantity(ac),line=record.line;
            const outside=el('button');ac.wrap.append(outside);record.qty.focus();record.qty.value='0';record.qty.fire('input');
            let focusedAdd=0;const focus=record.addButton.focus.bind(record.addButton);
            record.addButton.focus=(...args)=>{focusedAdd++;focus(...args);};
            if(active==='body')document.activeElement=document.body;
            const before=editor.history.length;record.qty.fire('blur',{relatedTarget:outside});
            assert.equal(editor.removed[0].line,line);assert.equal(editor.history.length,before+1);
            assert.equal(focusedAdd,0,active+' must reject even reentrant Add recovery');
            syncEditorSearchQuantities(ac);assert.equal(focusedAdd,0,active+' later sync cannot guess an exit');
            outside.focus();record.qty.fire('change');record.qty.fire('blur',{relatedTarget:outside});
            assert(document.activeElement===outside);assert.equal(focusedAdd,0);assert.equal(editor.removed.length,1);
            record.addButton.focus();record.addButton.click();
            assert.equal(record.group.hidden,false);assert.equal(record.addButton.hidden,true);assert.equal(record.qty.value,'1');
            assert(document.activeElement===ac.input,'fresh Add retains the normal search keyboard focus');
          }
        """)

    def test_focused_change_waits_for_outside_blur_destination_without_transient_add_recovery(self):
        self.run_js(r"""
          begin();openAddSheet();const ac=found([elves]),record=quantity(ac),line=record.line;
          const outside=el('button');ac.wrap.append(outside);record.qty.focus();record.qty.value='0';record.qty.fire('input');
          let focusedAdd=0;const focus=record.addButton.focus.bind(record.addButton);
          record.addButton.focus=(...args)=>{focusedAdd++;focus(...args);};
          const history=editor.history.length;record.qty.fire('change');
          assert.equal(editor.removed.length,0);assert.equal(line.qty,4);assert.equal(record.edit.done,false);
          assert.equal(record.group.hidden,false);assert.equal(record.qty.value,'0');assert.equal(editor.history.length,history);assert.equal(focusedAdd,0);
          document.activeElement=document.body;record.qty.fire('blur',{relatedTarget:outside});outside.focus();
          assert.equal(editor.removed[0].line,line);assert.equal(focusedAdd,0);assert(document.activeElement===outside);
          syncEditorSearchQuantities(ac);assert.equal(focusedAdd,0,'committed outside destination stays suppressed after blur');
          record.qty.fire('change');assert.equal(editor.removed.length,1);assert.equal(focusedAdd,0);
        """)

    def test_native_change_then_body_blur_to_own_plus_commits_once_and_recovers_add(self):
        self.run_js(r"""
          begin();openAddSheet();const ac=found([elves]),record=quantity(ac),line=record.line;
          record.qty.focus();record.qty.value='0';record.qty.fire('input');const history=editor.history.length;
          record.qty.fire('change');assert.equal(editor.removed.length,0);assert.equal(record.edit.done,false);
          assert.equal(record.group.hidden,false);assert.equal(record.plus.disabled,false);assert.equal(record.qty.value,'0');
          document.activeElement=document.body;record.qty.fire('blur',{relatedTarget:record.plus});
          assert.equal(editor.removed[0].line,line);assert.equal(editor.history.length,history+1);
          assert.equal(record.group.hidden,true);assert(document.activeElement===record.addButton);
          record.qty.fire('change');record.qty.fire('blur',{relatedTarget:record.plus});
          assert.equal(editor.removed.length,1);assert.equal(editor.history.length,history+1);assert(document.activeElement===record.addButton);
        """)

    def test_invalid_focused_change_resets_at_blur_and_unfocused_change_keeps_fallback_commit(self):
        self.run_js(r"""
          begin();openAddSheet();const ac=found([elves]),record=quantity(ac),line=record.line;
          record.qty.focus();record.qty.value='ab';record.qty.fire('input');const history=editor.history.length;
          record.qty.fire('change');assert.equal(record.qty.value,'ab');assert.equal(record.edit.done,false);
          document.activeElement=document.body;record.qty.fire('blur',{relatedTarget:record.plus});
          assert.equal(record.qty.value,'4');assert.equal(line.qty,4);assert.equal(editor.history.length,history);
          record.qty.focus();record.qty.value='0';record.qty.fire('input');document.activeElement=document.body;
          let focusedAdd=0;const focus=record.addButton.focus.bind(record.addButton);
          record.addButton.focus=(...args)=>{focusedAdd++;focus(...args);};
          record.qty.fire('change');assert.equal(editor.removed[0].line,line);assert.equal(record.edit.done,true);
          assert.equal(focusedAdd,0,'unfocused change can commit but cannot invent its exit destination');
          record.qty.fire('blur');assert.equal(editor.removed.length,1);assert.equal(focusedAdd,0);
        """)

    def test_invalid_and_rejected_commit_hold_recovery_but_a_fresh_minus_still_returns_add(self):
        self.run_js(r"""
          editor=null;
          for(const mode of ['invalid','rejected']) {
            closeEditor();for(const dialog of document.querySelectorAll('dialog'))dialog.remove();
            begin({}, {restoreDraft:false});editor.lists.Deck[0].qty=1;drawLines();openAddSheet();const ac=found([elves]),record=quantity(ac),line=record.line;
            record.qty.focus();record.qty.value=mode==='invalid'?'ab':'0';record.qty.fire('input');
            let focusedAdd=0;const focus=record.addButton.focus.bind(record.addButton);
            record.addButton.focus=(...args)=>{focusedAdd++;focus(...args);};
            const outside=el('button');ac.wrap.append(outside);
            if(mode==='rejected')editor.lists.Deck=editor.lists.Deck.filter(row=>row!==line);
            record.qty.fire('blur',{relatedTarget:outside});assert.equal(focusedAdd,0);assert.equal(editor.removed.length,0);
            if(mode==='invalid')assert.equal(record.qty.value,'1');
            else {editor.lists.Deck.unshift(line);syncEditorSearchQuantities(ac);}
            // A fresh native button action clears only the focus hold; the old commit stays latched.
            record.minus.focus();record.minus.click();assert.equal(editor.removed[0].line,line);
            assert(document.activeElement===record.addButton);assert.equal(focusedAdd,1,mode+' must preserve normal Minus recovery');
            record.qty.fire('change');assert.equal(editor.removed.length,1);assert.equal(focusedAdd,1);
          }
        """)


    def test_zero_tab_replaces_only_its_enabled_adjacent_control_without_a_browser_default(self):
        self.run_js(r"""
          editor=null;
          for(const backwards of [false,true]) {
            closeEditor();for(const dialog of document.querySelectorAll('dialog'))dialog.remove();
            begin({}, {restoreDraft:false});openAddSheet();const ac=found([elves]),record=quantity(ac),line=record.line;
            record.qty.focus();record.qty.value='0';record.qty.fire('input');const history=editor.history.length;
            const event=record.qty.fire('keydown',{key:'Tab',shiftKey:backwards});
            assert(event.defaultPrevented,'the browser must not focus a button hidden by this removal');
            assert.equal(editor.removed[0].line,line);assert.equal(editor.history.length,history+1);
            assert.equal(record.group.hidden,true);assert(document.activeElement===record.addButton);
            record.qty.fire('change');record.qty.fire('blur',{relatedTarget:backwards?record.minus:record.plus});
            assert.equal(editor.removed.length,1);assert.equal(editor.history.length,history+1);
            assert(document.activeElement===record.addButton);
          }
        """)

    def test_normal_modified_busy_and_disabled_next_tab_keep_native_navigation(self):
        self.run_js(r"""
          editor=null;
          for(const mode of ['normal','control','alt','meta','busy','disabled','outside']) {
            closeEditor();for(const dialog of document.querySelectorAll('dialog'))dialog.remove();
            begin({}, {restoreDraft:false});
            if(mode==='disabled')editor.lists.Deck[0].qty=MAX_COPIES;
            drawLines();openAddSheet();const ac=found([elves]),record=quantity(ac),line=record.line;
            record.qty.focus();const before=line.qty,history=editor.history.length;
            if(mode!=='normal'){record.qty.value='0';record.qty.fire('input');}
            if(mode==='busy')editor.saving=true;
            let outside;if(mode==='outside'){outside=el('button');ac.wrap.append(outside);outside.focus();}
            const event=record.qty.fire('keydown',{key:'Tab',ctrlKey:mode==='control',altKey:mode==='alt',metaKey:mode==='meta'});
            assert(!event.defaultPrevented,mode+' must keep browser navigation');
            assert.equal(editor.removed.length,0,mode);assert.equal(line.qty,before,mode);assert.equal(editor.history.length,history,mode);
            if(mode==='disabled') {
              assert(record.plus.disabled);record.qty.fire('change');assert.equal(editor.removed.length,0);
              const outside=el('button');ac.wrap.append(outside);let addFocus=0;
              const focus=record.addButton.focus.bind(record.addButton);record.addButton.focus=(...args)=>{addFocus++;focus(...args);};
              document.activeElement=document.body;record.qty.fire('blur',{relatedTarget:outside});outside.focus();
              assert.equal(editor.removed[0].line,line);assert.equal(addFocus,0);assert(document.activeElement===outside);
            }
            editor.saving=false;
          }
        """)


    def test_zero_tab_preserves_surviving_fallback_controls_and_handles_a_newly_disabled_plus(self):
        self.run_js(r"""
          editor=null;
          for(const [count,backwards] of [[9,false],[9,true],[99,false]]) {
            closeEditor();for(const dialog of document.querySelectorAll('dialog'))dialog.remove();
            begin({}, {restoreDraft:false});editor.lists.Deck=copyList({Deck:[
              {qty:4,name:elves.name,set:'one',number:'1',finish:'nonfoil',card:elves},
              {qty:count,name:elves.name,set:'other',number:'2',finish:'foil',card:elves}]}).Deck;
            drawLines();openAddSheet();const ac=found([{...elves,default:{set:'one',number:'1',finish:'nonfoil'}}]);
            const record=quantity(ac),original=record.line,fallback=editor.lists.Deck[1],history=editor.history.length;
            record.qty.focus();record.qty.value='0';record.qty.fire('input');
            const event=record.qty.fire('keydown',{key:'Tab',shiftKey:backwards});
            if(count===99) {
              assert(event.defaultPrevented,'a newly disabled Plus cannot receive the browser default');
              assert(document.activeElement===record.qty);assert.equal(record.qty.value,'99');assert(record.plus.disabled);
              const again=record.qty.fire('keydown',{key:'Tab'});assert(!again.defaultPrevented,'the next normal Tab can leave the max field');
            } else {
              assert(!event.defaultPrevented,'a surviving adjacent button keeps native Tab');
              assert.equal(editor.removed.length,0);record.qty.fire('change');assert.equal(editor.removed.length,0);
              const next=backwards?record.minus:record.plus;document.activeElement=document.body;
              record.qty.fire('blur',{relatedTarget:next});next.focus();assert(document.activeElement===next);assert(!next.disabled);
            }
            assert.equal(editor.removed[0].line,original);assert.equal(editor.removed.length,1);
            assert.equal(editor.history.length,history+1);assert.equal(record.line,fallback);assert.equal(fallback.qty,count);
            assert.equal(record.group.hidden,false);assert.equal(record.addButton.hidden,true);
          }
        """)
