"""Existing Editor bindings respect native editing, owner focus and activation boundaries."""
import unittest

from decklab.tests import test_editor_panes_ui as panes, test_quick_editor_ui as quick
from decklab.tests.test_workspace_ui import NODE


FIXTURE = r"""
  // The shared DOM double has no descendant CSS engine or reflected hidden property.
  // Match those browser semantics for actual showQty and owned-focus visibility here.
  const keyboardQueryAll = document.querySelectorAll.bind(document);
  document.querySelectorAll = selector => selector.startsWith('#main ')
    ? main.querySelectorAll(selector.slice(6)) : keyboardQueryAll(selector);
  Object.defineProperty(Node.prototype, 'hidden', {configurable:true,
    get() { return this.attrs.hidden !== undefined; },
    set(on) { if(on)this.attrs.hidden='';else delete this.attrs.hidden; }});
  document.body.append(el('p', {id:'toast', role:'status'}));
"""


@unittest.skipUnless(NODE, 'Node.js is not installed')
class EditorKeyboardTests(unittest.TestCase):
    def run_js(self, scenario):
        panes.EditorPanesUiTests.run_js(self, FIXTURE + scenario)

    def test_undo_restores_semantic_row_control_after_uid_recreation_in_both_looks(self):
        self.run_js(r'''
          for(const [look,kind] of [['list','more'],['list','minus'],['list','print'],['list','card'],
            ['visual','more'],['visual','card']]) {
            const ed=full();ed.look=look;drawLines();const line=ed.lists.Deck[0],uid=line.uid,key=lineKey(line);
            setQty(uid,5);const row=ed.dom.lines.querySelector(`[data-uid="${uid}"]`);
            const selector={more:'.edit-more',minus:'.step-minus',print:'.edit-print'}[kind];
            const old=kind==='card'?row.editorChange.trigger:row.querySelector(selector);old.focus();
            const event=document.fire('keydown',{key:'z',ctrlKey:true,target:old});assert(event.defaultPrevented);
            const restored=ed.lists.Deck.find(item=>lineKey(item)===key);assert.equal(restored.qty,4);assert.notEqual(restored.uid,uid);
            const fresh=ed.dom.lines.querySelector(`[data-uid="${restored.uid}"]`);
            const expected=kind==='card'?fresh.editorChange.trigger:fresh.querySelector(selector);
            assert(document.activeElement===expected&&expected!==old&&expected.isConnected,`${look}/${kind}`);
            assert.equal(expected.scrollOptions.block,'center');
          }
        ''')

    def test_removed_undo_addition_disappearance_and_disabled_plus_have_live_focus_fallbacks(self):
        self.run_js(r'''
          let ed=full(),line=ed.lists.Deck[0];removeLine(line.uid);
          const undo=ed.dom.lines.querySelector(`[data-removed="${line.uid}"]`).querySelector('.undo-btn');undo.focus();
          document.fire('keydown',{key:'z',metaKey:true,target:undo});line=ed.lists.Deck.find(item=>item.name===elves.name);
          assert(document.activeElement===ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`).querySelector('.step-plus'));
          ed=full();line=addCard(bolt,'Deck',1);const more=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`).querySelector('.edit-more');more.focus();
          document.fire('keydown',{key:'z',ctrlKey:true,target:more});assert(!ed.lists.Deck.some(item=>item.name===bolt.name));
          assert(document.activeElement.isConnected&&ed.dom.lines.contains(document.activeElement));
          assert(document.activeElement!==more&&document.activeElement!==document.body);
          ed=full({lists:{target:{Deck:[{qty:99,name:elves.name,set:'fdn',number:'227',card:elves}]},owned:null}});
          line=ed.lists.Deck[0];setQty(line.uid,98);const plus=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`).querySelector('.step-plus');assert(!plus.disabled);plus.focus();assert(document.activeElement===plus);
          document.fire('keydown',{key:'z',ctrlKey:true,target:plus});line=ed.lists.Deck[0];
          const restored=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`);assert.equal(line.qty,99);
          assert(restored.querySelector('.step-plus').disabled);assert(document.activeElement===restored.querySelector('.qty-input'),JSON.stringify({active:document.activeElement?.dataset.focus,connected:document.activeElement?.isConnected,expected:restored.querySelector('.qty-input').dataset.focus,disabled:restored.querySelector('.qty-input').matches(':disabled')}));
          // A wide trial editor can have neither a visible bar Add nor a Save after the last added row is undone.
          Node.prototype.getClientRects=function(){return this.matches('.bar-add-jump')?[]:[this.box];};
          ed=full({may_save:false,lists:{target:{Deck:[]},owned:null}});line=addCard(elves,'Deck',1);
          const last=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`).querySelector('.edit-more');last.focus();
          document.fire('keydown',{key:'z',ctrlKey:true,target:last});assert.equal(Object.values(ed.lists).flat().length,0);
          assert(document.activeElement===document.getElementById('edit-tab-cards'));
        ''')

    def test_undo_preserves_fresh_bar_parts_and_falls_back_when_play_now_save_becomes_disabled(self):
        self.run_js(r'''
          for(const key of ['addCards','save','saveMore','checks']) {
            const ed=full();if(key==='addCards')width(false);setQty(ed.lists.Deck[0].uid,5);
            ed.check={blocks:[{list:'target',section:'Deck',index:0,problem:'Fixture block'}],warnings:[]};drawBar();
            const old=ed.dom.barParts[key],address=old.getAttribute('data-focus');assert(address);old.focus();assert(document.activeElement===old,key+' initial focus');
            document.fire('keydown',{key:'z',ctrlKey:true,target:old});
            const fresh=ed.dom.barParts[key];assert(fresh!==old&&document.activeElement===fresh,JSON.stringify({key,active:document.activeElement?.dataset.focus,connected:document.activeElement?.isConnected,hidden:fresh.hidden,disabled:fresh.disabled}));
            assert.equal(fresh.getAttribute('data-focus'),address);assert.equal(ed.dom.page.querySelectorAll(`[data-focus="${address}"]`).length,1);
          }
          const ed=full({lists:{target:{Deck:[{qty:4,name:elves.name,card:elves}]},owned:null}},{version:'owned'});
          assert(noOwnedList());startOwned();const old=ed.dom.barParts.save;assert(!old.disabled);old.focus();
          document.fire('keydown',{key:'z',ctrlKey:true,target:old});assert(noOwnedList());assert(ed.dom.barParts.save.disabled);
          assert(document.activeElement===document.getElementById('edit-tab-cards'));
        ''')

    def test_duplicate_printing_undo_focus_keeps_the_semantic_occurrence(self):
        self.run_js(r'''
          const ed=full();ed.lists=copyList({Deck:[{qty:2,name:elves.name,set:'fdn',number:'227',card:elves},
            {qty:3,name:elves.name,set:'fdn',number:'227',card:elves}]});ed.snap=snapshot(ed);drawLines();
          const second=ed.lists.Deck[1];setQty(second.uid,4);
          const print=ed.dom.lines.querySelector(`[data-uid="${second.uid}"]`).querySelector('.edit-print');print.focus();
          document.fire('keydown',{key:'z',ctrlKey:true,target:print});assert.equal(ed.lists.Deck[1].qty,3);
          const target=ed.dom.lines.querySelector(`[data-uid="${ed.lists.Deck[1].uid}"]`).querySelector('.edit-print');
          assert(document.activeElement===target);assert(target!==print);
        ''')

    def test_restore_never_reclaims_new_focus_or_stale_busy_modal_ownership(self):
        self.run_js(r'''
          for(const flag of ['focus','modal','menu','profile','route','saving','asking','leaving']) {
            state.profile=state.profiles[1];const ed=full(),line=ed.lists.Deck[0];setQty(line.uid,5);
            const old=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`).querySelector('.edit-more');old.focus();
            const saved=editorUndoFocus(ed);assert(saved);ed.lists=copyList(ed.lists);drawEditor();let overlay;
            if(flag==='focus') {overlay=el('button');document.body.append(overlay);overlay.focus();}
            else if(flag==='modal') {overlay=el('dialog',{open:true});document.body.append(overlay);}
            else if(flag==='menu') {overlay=el('div',{role:'menu'});ed.dom.page.append(overlay);}
            else if(flag==='profile')state.profile={id:'other'};else if(flag==='route')routeToken++;else ed[flag]=true;
            const active=document.activeElement,before=snapshot(ed);restoreEditorUndoFocus(ed,saved);
            assert(document.activeElement===active,flag);assert.equal(snapshot(ed),before);overlay?.remove();
          }
        ''')

    def test_global_save_undo_modifiers_repeat_native_editing_and_owned_overlays(self):
        self.run_js(r'''
          const ed=full();let saves=0,undos=0,searches=0;saveNow=()=>{saves++;};undoLast=()=>{undos++;return true;};focusSearch=()=>{searches++;};
          const target=ed.dom.barParts.addCards;target.focus();
          for(const extra of [{shiftKey:true},{altKey:true},{ctrlKey:true,metaKey:true},{isComposing:true},{keyCode:229},
            {getModifierState:key=>key==='AltGraph'},{defaultPrevented:true},{repeat:true}]) {
            const before=[saves,undos];document.fire('keydown',{key:'s',ctrlKey:true,target,...extra});
            document.fire('keydown',{key:'z',ctrlKey:true,target,...extra});same([saves,undos],before);
          }
          document.fire('keydown',{key:'s',ctrlKey:true,target});document.fire('keydown',{key:'s',metaKey:true,target});
          document.fire('keydown',{key:'z',ctrlKey:true,target});document.fire('keydown',{key:'z',metaKey:true,target});same([saves,undos],[2,2]);
          const nativeInput=el('input'),outer=el('div',{contenteditable:'true'}),child=el('span');outer.append(child);ed.dom.page.append(nativeInput,outer);
          for(const native of [nativeInput,child]) {native.focus();const event=document.fire('keydown',{key:'z',ctrlKey:true,target:native});assert(!event.defaultPrevented);}
          assert.equal(undos,2);
          for(const overlay of [el('div',{role:'menu'}),el('dialog',{open:true})]) {
            ed.dom.page.append(overlay);const before=[saves,undos,searches];
            const event=document.fire('keydown',{key:'s',ctrlKey:true,target});assert(event.defaultPrevented);
            document.fire('keydown',{key:'z',ctrlKey:true,target});document.fire('keydown',{key:'/',target});
            same([saves,undos,searches],before);overlay.remove();
          }
          document.fire('keydown',{key:'/',shiftKey:true,target});assert.equal(searches,1);
          for(const extra of [{ctrlKey:true},{metaKey:true},{altKey:true},{repeat:true},{getModifierState:key=>key==='AltGraph'}]) {
            document.fire('keydown',{key:'/',target,...extra});assert.equal(searches,1);
          }
        ''')

    def test_global_keys_and_direct_undo_refuse_busy_and_stale_mounted_editors(self):
        self.run_js(r'''
          for(const flag of ['saving','asking','leaving','profile','route','detached']) {
            state.profile=state.profiles[1];const ed=full();setQty(ed.lists.Deck[0].uid,5);
            const before=snapshot(ed),count=ed.history.length;let saves=0;saveNow=()=>{saves++;};
            if(flag==='profile')state.profile={id:'other'};else if(flag==='route')routeToken++;
            else if(flag==='detached')ed.dom.page.remove();else ed[flag]=true;
            document.fire('keydown',{key:'s',ctrlKey:true,target:document.body});
            document.fire('keydown',{key:'z',ctrlKey:true,target:document.body});assert.equal(undoLast(),false);
            assert.equal(saves,0);assert.equal(snapshot(ed),before);assert.equal(ed.history.length,count);
          }
        ''')

    def test_tabs_and_kit_arrows_preserve_modified_browser_chords_and_repeat_navigation(self):
        self.run_js(r'''
          const ed=full(),tabs=ed.dom.sideTabs;const addTab=ed.dom.panes.buttons.add.button;addTab.focus();
          for(const extra of [{altKey:true},{ctrlKey:true},{metaKey:true},{shiftKey:true},{isComposing:true},{defaultPrevented:true}]) {
            const event=tabs.fire('keydown',{key:'ArrowRight',...extra});assert.equal(ed.side,'add');assert(document.activeElement===addTab);
            if(!extra.defaultPrevented)assert(!event.defaultPrevented);
          }
          tabs.fire('keydown',{key:'ArrowRight',repeat:true});assert.equal(ed.side,'stats');
          ed.dom.sideTabs.fire('keydown',{key:'End',repeat:true});assert.equal(ed.side,'checks');
          const field=kitField('sleeves');ed.dom.page.append(field);const group=field.querySelector('.kit-pick');
          const choices=group.querySelectorAll('.kit-tile'),first=choices[0];first.focus();let picks=0;setField=()=>{picks++;};
          for(const extra of [{altKey:true},{ctrlKey:true},{metaKey:true},{shiftKey:true},{isComposing:true},{defaultPrevented:true}]) {
            group.fire('keydown',{key:'ArrowRight',...extra});assert.equal(picks,0);
          }
          for(const busy of ['saving','asking','leaving']) {ed[busy]=true;group.fire('keydown',{key:'ArrowRight'});assert.equal(picks,0);ed[busy]=false;}
          group.fire('keydown',{key:'ArrowRight',repeat:true});assert.equal(picks,1);
        ''')

    def test_search_keeps_enter_variants_and_repeat_arrows_but_rejects_claimed_modified_activation(self):
        self.run_js(r'''
          const ed=full(),ac=ed.ac;accepted(ac);ac.input.focus();let adds=[],views=0;
          // A null request preserves pick()'s existing typed-count/default-one decision.
          pick=(owner,index,n)=>adds.push(n);viewResult=()=>{views++;};
          for(const extra of [{ctrlKey:true},{metaKey:true},{ctrlKey:true,altKey:true},{altKey:true,shiftKey:true},
            {isComposing:true},{keyCode:229},{defaultPrevented:true},{repeat:true}])ac.input.fire('keydown',{key:'Enter',...extra});
          same(adds,[]);assert.equal(views,0);
          ac.input.fire('keydown',{key:'Enter'});ac.input.fire('keydown',{key:'Enter',shiftKey:true});
          ac.input.fire('keydown',{key:'Enter',altKey:true});same(adds,[null,4]);assert.equal(views,1);
          ac.items.push({...forest,have:{}});drawOptions(ac);ac.active=0;
          ac.input.fire('keydown',{key:'ArrowDown',repeat:true});assert.equal(ac.active,1);
          for(const extra of [{altKey:true},{ctrlKey:true},{metaKey:true},{shiftKey:true}]) {
            const event=ac.input.fire('keydown',{key:'ArrowDown',...extra});assert.equal(ac.active,1);assert(!event.defaultPrevented);
          }
          const menu=el('div',{role:'menu'});ac.wrap.append(menu);ac.input.fire('keydown',{key:'Enter'});same(adds,[null,4]);menu.remove();
          const modal=el('dialog',{open:true});document.body.append(modal);ac.input.fire('keydown',{key:'Enter'});
          ac.input.fire('keydown',{key:'Enter',altKey:true});same(adds,[null,4]);assert.equal(views,1);modal.remove();
        ''')

    def test_search_composition_cancels_pending_add_and_only_finished_text_schedules_lookup(self):
        self.run_js(r'''
          const ed=full(),ac=ed.ac;let reads=0,resolve;const before=JSON.stringify(ed.lists);
          ac.input.value=elves.name;ac.pickFirst=true;api=()=>{reads++;return new Promise(done=>resolve=done);};
          const pending=lookUp(ac,elves.name);ac.input.fire('compositionstart');assert(!ac.pickFirst);
          ac.input.value=bolt.name;ac.input.fire('input',{isComposing:true});ac.input.fire('keydown',{key:'Enter',isComposing:true});
          flushTimers();assert.equal(reads,1);resolve({cards:[foundCard],pages:1});await pending;assert.equal(JSON.stringify(ed.lists),before);
          api=async()=>{reads++;return {cards:[{...bolt,have:{}}],pages:1};};
          ac.input.fire('compositionend');ac.input.fire('input',{isComposing:false});flushTimers();await settle();
          assert.equal(reads,2);assert.equal(ac.items[0].name,bolt.name);assert.equal(JSON.stringify(ed.lists),before);assert(!ac.pickFirst);
        ''')

    def test_row_quantity_composition_prevented_input_and_exact_enter_commit(self):
        self.run_js(r'''
          const ed=full(),line=ed.lists.Deck[0],row=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`),qty=row.querySelector('.qty-input');
          qty.focus();let blurs=0;qty.blur=()=>{blurs++;qty.fire('change');};
          qty.fire('compositionstart');qty.value='8';qty.fire('input',{isComposing:true});qty.fire('keydown',{key:'Enter',isComposing:true});
          assert.equal(line.qty,4);assert.equal(blurs,0);qty.fire('compositionend');assert.equal(line.qty,8);
          const history=ed.history.length;qty.fire('input');assert.equal(ed.history.length,history);
          qty.value='9';qty.fire('input',{defaultPrevented:true});assert.equal(line.qty,8);
          qty.value='0';for(const extra of [{ctrlKey:true},{metaKey:true},{altKey:true},{shiftKey:true},{repeat:true},{defaultPrevented:true}]) {
            qty.fire('keydown',{key:'Enter',...extra});assert.equal(blurs,0);assert.equal(ed.removed.length,0);
          }
          qty.fire('keydown',{key:'Enter'});assert.equal(blurs,1);assert.equal(ed.removed.length,1);
        ''')

    def test_main_quantity_input_and_finished_composition_remain_live_during_save_precheck(self):
        self.run_js(r'''
          const ed=full(),line=ed.lists.Deck[0],qty=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`).querySelector('.qty-input');
          qty.focus();let checks=0,release,sent=null;const pending=new Promise(done=>release=done);
          runCheck=async(owner,info)=>{checks++;if(checks===1){await pending;info.superseded=true;return null;}
            return {blocks:[],file_changed:false,changes:{decklist:true,fields:[],prose:[],marker:false}};};
          doSave=async()=>{sent=sendList(ed.lists);};const saving=saveNow();assert(ed.saving);
          qty.value='5';qty.fire('input');assert.equal(line.qty,5);
          qty.fire('compositionstart');qty.value='6';qty.fire('input',{isComposing:true});assert.equal(line.qty,5);
          qty.fire('compositionend');assert.equal(line.qty,6);assert.equal(qty.value,'6');
          release();await saving;assert.equal(checks,2);assert.equal(sent.Deck[0].qty,6);assert(!ed.saving);
        ''')

    def test_queued_row_composition_input_and_change_refuse_stale_disabled_or_departing_context(self):
        self.run_js(r'''
          for(const flag of ['profile','route','frame','disabled','asking','leaving','line']) {
            state.profile=state.profiles[1];const ed=full(),line=ed.lists.Deck[0];
            const qty=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`).querySelector('.qty-input');qty.focus();qty.fire('compositionstart');
            qty.value='8';qty.fire('input',{isComposing:true});
            if(flag==='profile')state.profile={id:'other'};else if(flag==='route')routeToken++;
            else if(flag==='frame')drawEditor();else if(flag==='disabled')qty.disabled=true;
            else if(flag==='line')ed.lists=copyList(ed.lists);else ed[flag]=true;
            const before=snapshot(ed),count=ed.history.length;qty.fire('compositionend');qty.fire('input');
            qty.value='0';qty.fire('change');assert.equal(snapshot(ed),before,flag);assert.equal(ed.history.length,count);assert.equal(ed.removed.length,0);
          }
        ''')

    def test_search_quantity_composition_repeat_and_modifiers_never_remove_until_owned_commit(self):
        quick.QuickEditorUiTests.run_js(self,'changed = '+panes.REAL_CHANGED+r''';
          const ed=begin();openAddSheet();const ac=ed.ac,card={...elves,default:{set:'fdn',number:'227',finish:'nonfoil'}};
          ac.input.value=elves.name;ac.query=elves.name;ac.items=[card];ac.active=0;ac.resultScope=editorSearchScope(ac);drawOptions(ac);
          const record=ac.list.querySelector('.ac-actions').searchQuantity,line=record.line;record.qty.focus();record.qty.fire('compositionstart');
          record.qty.value='0';record.qty.fire('input',{isComposing:true});record.qty.fire('keydown',{key:'Enter',isComposing:true});
          assert.equal(ed.removed.length,0);assert.equal(line.qty,4);record.qty.fire('compositionend');
          for(const extra of [{ctrlKey:true},{metaKey:true},{altKey:true},{shiftKey:true},{repeat:true},{defaultPrevented:true}]) {
            record.qty.fire('keydown',{key:'Enter',...extra});assert.equal(ed.removed.length,0);assert(!record.edit.done);
          }
          record.qty.fire('keydown',{key:'Tab',repeat:true});assert.equal(ed.removed.length,0);
          record.qty.fire('keydown',{key:'Enter'});assert.equal(ed.removed.length,1);assert.equal(record.edit.done,true);
          assert(document.activeElement===record.addButton);
        ''')
