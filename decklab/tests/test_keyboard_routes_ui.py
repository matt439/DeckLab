"""F, row-focused M and ? route through current retained page controls.

These isolated DOM-double regressions make no browser or device acceptance claim.
"""
import json
import subprocess
import unittest

from decklab.tests import test_collection_find_layout_ui as find_ui
from decklab.tests import test_collection_layout_ui as rows_ui
from decklab.tests import test_editor_panes_ui as panes_ui
from decklab.tests import test_library_ui as library_ui
from decklab.tests import test_quick_editor_ui as quick_ui
from decklab.tests import test_shell_ui as shell_ui
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


DESKTOP = {'innerWidth': 1000, 'innerHeight': 830, 'coarse': False,
           'visual': {'width': 1000, 'height': 830}}
PHONE = {'innerWidth': 393, 'innerHeight': 852, 'coarse': True,
         'visual': {'width': 393, 'height': 852}}
ROUTES = r'''
  setUpKeyboardHelp();
  function routeFrom(target,key,extra={}) {
    target.focus();return document.fire('keydown',{key,target,...extra});
  }
  function routeAnchor(root=main) {
    const anchor=el('button',{type:'button',text:'Current page control'});root.append(anchor);anchor.focus();return anchor;
  }
  function noRouteIo() {
    const calls=[];
    api=async path=>{calls.push(['read',path]);throw Error('Character routes must not read the API');};
    apiWrite=async path=>{calls.push(['write',path]);throw Error('Character routes must not write the API');};
    return calls;
  }
'''
SHELL = shell_ui.SETUP + r'''
  const shortcuts=byId('menu-shortcuts')||el('button',{id:'menu-shortcuts',type:'button',text:'Keyboard shortcuts'});
  if(!shortcuts.parentNode)byId('avatar-menu').append(shortcuts);
  const shellActions=byId('topbar-actions'),shellAvatar=byId('avatar-button'),shellMenu=byId('avatar-menu');
  shellAvatar.remove();shellMenu.remove();shellActions.append(shellAvatar,shellMenu);
  function shellRoutes() {registerShellKeyboardHelp();return routeAnchor();}
  function scope(commands,options={}) {
    const root=el('section');main.append(root);
    registerKeyboardHelp(root,commands,{profile:state.profile.id,...options});return root;
  }
'''


@unittest.skipUnless(NODE, 'Node.js is not installed')
class KeyboardRoutesUiTests(unittest.TestCase):
    def run_js(self, setup, scenario, viewport=None):
        result = subprocess.run([NODE, str(RUNNER)],
            input=json.dumps([str(WEB), setup + ROUTES + scenario, True, viewport]),
            capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'ok')

    def test_dispatch_is_wired_once_and_only_explicit_current_routes_are_consumed(self):
        self.run_js(SHELL, r'''
          as('matt');setUpKeyboardHelp();setUpKeyboardHelp();const anchor=routeAnchor();let calls=0;
          scope([{keys:['F'],label:'Find fixture',scope:'Current fixture',characters:true,routeKey:'f',invoke:()=>{calls++;return true;}}]);
          for(const key of ['f','F'])assert(routeFrom(anchor,key).defaultPrevented);
          assert.equal(calls,2);
          for(const key of ['m','?','j','k','r','/','Enter','Escape'])assert(!routeFrom(anchor,key).defaultPrevented,key);
          assert(!routeFrom(anchor,'Enter',{ctrlKey:true}).defaultPrevented);assert.equal(calls,2);
          setKeyboardCharactersEnabled(false);assert(!routeFrom(anchor,'f').defaultPrevented);assert.equal(calls,2);
          setKeyboardCharactersEnabled(true);assert(routeFrom(anchor,'f').defaultPrevented);assert.equal(calls,3);
        ''')

    def test_character_routes_reject_handled_composition_modifiers_repeat_and_mismatched_focus(self):
        self.run_js(SHELL, r'''
          as('matt');const anchor=routeAnchor(),other=routeAnchor();let calls=0;
          scope([{keys:['F'],label:'Find fixture',scope:'Fixture',characters:true,routeKey:'f',invoke:()=>{calls++;}}]);
          for(const extra of [{defaultPrevented:true},{isComposing:true},{keyCode:229},{ctrlKey:true},{metaKey:true},
            {altKey:true},{shiftKey:true},{repeat:true},{getModifierState:key=>key==='AltGraph'}]) {
            const before=calls,event=routeFrom(anchor,'f',extra);assert.equal(calls,before);
            assert.equal(event.defaultPrevented,Boolean(extra.defaultPrevented));
          }
          anchor.editorComposing=true;assert(!routeFrom(anchor,'f').defaultPrevented);anchor.editorComposing=false;
          other.focus();assert(!document.fire('keydown',{key:'f',target:anchor}).defaultPrevented);
          anchor.setAttribute('aria-disabled','true');assert(!routeFrom(anchor,'f').defaultPrevented);anchor.removeAttribute('aria-disabled');
          anchor.hidden=true;assert(!routeFrom(anchor,'f').defaultPrevented);anchor.hidden=false;
          anchor.setAttribute('inert','');assert(!routeFrom(anchor,'f').defaultPrevented);anchor.removeAttribute('inert');
          assert.equal(calls,0);assert(routeFrom(anchor,'f').defaultPrevented);assert.equal(calls,1);
        ''')

    def test_editing_descendants_dialogs_and_original_menus_keep_their_keys(self):
        self.run_js(SHELL, r'''
          as('matt');const anchor=routeAnchor();let calls=0;
          scope([{keys:['F'],label:'Find fixture',scope:'Fixture',characters:true,routeKey:'f',invoke:()=>{calls++;}}]);
          for(const tag of ['input','textarea','select']) {
            const input=el(tag);main.append(input);assert(!routeFrom(input,'f').defaultPrevented);input.remove();
          }
          const edit=el('div',{contenteditable:'true'},el('span',{tabindex:'0',text:'Editable text'}));main.append(edit);
          assert(!routeFrom(edit.querySelector('span'),'f').defaultPrevented);edit.remove();
          const dialog=el('dialog',{open:''});document.body.append(dialog);
          assert(!routeFrom(anchor,'f').defaultPrevented);dialog.remove();
          const menu=openMenu(anchor,[{text:'Original action',onclick:()=>{throw Error('No menu action');}}]);
          assert(menu.node&&menu.node.isConnected);assert(!routeFrom(anchor,'f').defaultPrevented);menu.close();
          assert.equal(calls,0);assert(routeFrom(anchor,'f').defaultPrevented);assert.equal(calls,1);
        ''')

    def test_route_ownership_availability_busy_and_ambiguity_refuse_stale_dispatch(self):
        self.run_js(SHELL, r'''
          as('matt');const anchor=routeAnchor();let calls=0,live=true,ready=true,busy=false;
          const descriptor={keys:['F'],label:'Find fixture',scope:'Fixture',characters:true,routeKey:'f',
            available:()=>ready,invoke:()=>{calls++;}};
          const root=scope([descriptor],{current:()=>live,blocked:()=>busy});
          for(const change of [()=>{live=false;},()=>{ready=false;},()=>{busy=true;}]) {
            change();assert(!routeFrom(anchor,'f').defaultPrevented);live=ready=true;busy=false;
          }
          const duplicate=scope([{...descriptor}]);
          assert(!routeFrom(anchor,'f').defaultPrevented);duplicate.remove();
          assert(routeFrom(anchor,'f').defaultPrevented);assert.equal(calls,1);
          routeToken++;assert(!routeFrom(anchor,'f').defaultPrevented);assert(!keyboardHelpScopes.has(root));
          const next=scope([descriptor]);state.profile=PROFILES.find(p=>p.id==='user1');
          assert(!routeFrom(anchor,'f').defaultPrevented);assert(!keyboardHelpScopes.has(next));
          const currentRoot=scope([descriptor]);currentRoot.remove();assert(!routeFrom(anchor,'f').defaultPrevented);
          assert.equal(calls,1);
        ''')

    def test_question_mark_uses_semantic_shift_and_returns_to_original_focus_without_punctuation_aria(self):
        self.run_js(SHELL, r'''
          as('user2');const anchor=shellRoutes();const calls=noRouteIo();
          const hintEntry=byId('menu-shortcuts'),helpHint=hintEntry.querySelector('.keyboard-help-shortcut');
          assert(helpHint&&!helpHint.hidden);assert(helpHint.matches('.kbd'));assert.equal(helpHint.textContent,'?');
          assert.equal(helpHint.getAttribute('aria-hidden'),'true');assert(hintEntry.textContent.startsWith('Keyboard shortcuts'));
          setKeyboardCharactersEnabled(false);assert(helpHint.hidden);setKeyboardCharactersEnabled(true);assert(!helpHint.hidden);
          let hintBusy=true;scope([],{blocked:()=>hintBusy});refreshKeyboardHints();assert(helpHint.hidden);
          hintBusy=false;refreshKeyboardHints();assert(!helpHint.hidden);
          byId('avatar-button').hidden=true;refreshKeyboardHints();assert(helpHint.hidden);
          byId('avatar-button').hidden=false;refreshKeyboardHints();assert(!helpHint.hidden);
          registerShellKeyboardHelp();registerShellKeyboardHelp();refreshKeyboardHints();
          assert.equal(byId('menu-shortcuts'),hintEntry);assert.equal(hintEntry.querySelector('.keyboard-help-shortcut'),helpHint);
          assert.equal(hintEntry.querySelectorAll('.keyboard-help-shortcut').length,1);
          assert(routeFrom(anchor,'?',{shiftKey:true}).defaultPrevented);
          let sheet=keyboardHelpNow.sheet;assert(sheet.dialog.textContent.includes('Show keyboard shortcuts'));
          assert(keyboardHelpNow.anchor===anchor);assert.equal(byId('menu-shortcuts').getAttribute('aria-keyshortcuts'),null);
          assert(!document.querySelectorAll('[aria-keyshortcuts]').some(n=>(n.getAttribute('aria-keyshortcuts')||'').includes('?')));
          sheet.close();assert.equal(document.activeElement,anchor);
          assert(routeFrom(anchor,'?').defaultPrevented);sheet=keyboardHelpNow.sheet;
          assert(!routeFrom(anchor,'?').defaultPrevented);assert.equal(keyboardHelpNow.sheet,sheet);sheet.close();
          setKeyboardCharactersEnabled(false);assert(!routeFrom(anchor,'?',{shiftKey:true}).defaultPrevented);
          assert(helpHint.hidden);assert.equal(keyboardHelpNow,null);same(calls,[]);
        ''')

    def test_question_mark_yields_to_current_page_busy_and_stale_shell_profile_or_route(self):
        self.run_js(SHELL, r'''
          as('matt');const anchor=shellRoutes();let busy=true;
          scope([],{blocked:()=>busy});assert(!routeFrom(anchor,'?',{shiftKey:true}).defaultPrevented);
          assert.equal(keyboardHelpCommands().find(c=>c.keys.includes('?')).available,false);
          busy=false;assert(routeFrom(anchor,'?',{shiftKey:true}).defaultPrevented);keyboardHelpNow.sheet.close();
          state.profile=PROFILES.find(p=>p.id==='user1');assert(!routeFrom(anchor,'?').defaultPrevented);
          registerShellKeyboardHelp();routeToken++;assert(!routeFrom(anchor,'?').defaultPrevented);
          registerShellKeyboardHelp();const entry=byId('menu-shortcuts'),menu=entry.parentNode;
          entry.remove();document.body.append(entry);assert(!routeFrom(anchor,'?').defaultPrevented);
          entry.remove();menu.append(entry);assert(routeFrom(anchor,'?').defaultPrevented);keyboardHelpNow.sheet.close();
          byId('avatar-button').hidden=true;assert(!routeFrom(anchor,'?').defaultPrevented);
          assert.equal(keyboardHelpNow,null);
        ''')

    def test_full_editor_f_reveals_retained_add_search_without_changing_the_draft_or_requesting_data(self):
        self.run_js(panes_ui.SETUP, r'''
          location.hash='#/edit?id=casual%2Fsample&v=target';const ed=full(),ac=ed.ac,searchInput=ac.input;
          const before=JSON.stringify(draftBody()),history=ed.history.length,seq=ac.seq,calls=noRouteIo();
          ed.tab='notes';drawMain();setSide('stats');foldSide(true);const anchor=routeAnchor(ed.dom.page);
          assert(routeFrom(anchor,'f').defaultPrevented);assert.equal(ed.tab,'cards');assert.equal(ed.side,'add');assert(shown('add'));
          assert(ed.ac===ac&&ed.ac.input===searchInput);assert.equal(document.activeElement,searchInput);assert(searchInput.selected);
          assert.equal(searchInput.getAttribute('aria-keyshortcuts'),'F / Alt+Enter');
          assert.equal(JSON.stringify(draftBody()),before);assert.equal(ed.history.length,history);assert.equal(ac.seq,seq);same(calls,[]);
          const page=ed.dom.page;setKeyboardCharactersEnabled(false);
          assert.equal(searchInput.getAttribute('aria-keyshortcuts'),'Alt+Enter');assert(!routeFrom(anchor,'f').defaultPrevented);
          setKeyboardCharactersEnabled(true);assert.equal(searchInput.getAttribute('aria-keyshortcuts'),'F / Alt+Enter');
          assert(ed.dom.page===page&&ed.ac===ac&&ed.ac.input===searchInput);same(calls,[]);
        ''', DESKTOP)

    def test_quick_editor_f_opens_one_add_sheet_and_cancels_old_search_on_close(self):
        self.run_js(quick_ui.SETUP, r'''
          location.hash='#/edit?id=casual%2Fsample&v=target';const ed=begin({}, {restoreDraft:false}),anchor=routeAnchor(ed.dom.page);
          const before=JSON.stringify(draftBody()),history=ed.history.length,calls=noRouteIo();
          assert(routeFrom(anchor,'f').defaultPrevented);const first=ed.ac,dialog=keyboardDialog();
          assert(first&&dialog&&dialog.classList.contains('sheet-search'));assert.equal(document.activeElement,first.input);
          assert(!routeFrom(anchor,'f').defaultPrevented);assert.equal(ed.ac,first);assert.equal(keyboardDialog(),dialog);
          button(dialog,'Done').click();assert(first.cancelled);assert.equal(ed.ac,null);assert(!dialog.isConnected);
          assert(routeFrom(anchor,'f').defaultPrevented);assert(ed.ac&&ed.ac!==first);assert.equal(document.activeElement,ed.ac.input);
          button(keyboardDialog(),'Done').click();assert.equal(JSON.stringify(draftBody()),before);assert.equal(ed.history.length,history);same(calls,[]);
        ''', PHONE)

    def test_editor_f_allows_local_readonly_trial_but_refuses_missing_play_now_or_stale_model_frame(self):
        self.run_js(panes_ui.SETUP, r'''
          const trial=full({may_save:false}),anchor=routeAnchor(trial.dom.page);assert(trial.readOnly);
          assert(routeFrom(anchor,'f').defaultPrevented);assert.equal(document.activeElement,trial.ac.input);
          assert(!keyboardHelpCommands().some(c=>c.keys.includes('Ctrl/Cmd+S')));
          const trialRow=trial.dom.lines.querySelector('.edit-row'),trialMore=trialRow.editorChange.more;
          assert(routeFrom(trialRow.querySelector('.step-plus'),'m').defaultPrevented);
          assert.equal(document.querySelector('[data-popover]').keyboardAnchor,trialMore);closeMenus();
          closeEditor();const ed=full({lists:{target:structuredClone(list),owned:null}},{version:'owned'}),missing=routeAnchor(ed.dom.page);
          assert(noOwnedList());assert(!routeFrom(missing,'f').defaultPrevented);assert.equal(document.activeElement,missing);assert.equal(keyboardDialog(),null);
          closeEditor();const current=full(),target=routeAnchor(current.dom.page),savedRouteFrame=[current.id,current.version,current.space,current.mode];
          for(const [key,value] of [['id','casual/other'],['version','owned'],['space','other'],['mode','copy']]) {
            const prior=current[key];current[key]=value;assert(!routeFrom(target,'f').defaultPrevented,key);current[key]=prior;
          }
          same([current.id,current.version,current.space,current.mode],savedRouteFrame);assert(routeFrom(target,'f').defaultPrevented);
        ''', DESKTOP)

    def test_modal_quick_f_refresh_never_advertises_f_and_keeps_native_search_keys(self):
        self.run_js(quick_ui.SETUP, r'''
          location.hash='#/edit?id=casual%2Fsample&v=target';const modalEditor=begin({}, {restoreDraft:false});
          const modalAnchor=routeAnchor(modalEditor.dom.page),modalBody=JSON.stringify(draftBody());
          const modalHistory=modalEditor.history.length,modalCalls=noRouteIo();
          assert(routeFrom(modalAnchor,'f').defaultPrevented);
          const modalSearch=modalEditor.ac,modalInput=modalSearch.input,modalDialog=keyboardDialog();
          assert(modalDialog&&modalDialog.classList.contains('sheet-search'));
          const doneButton=button(modalDialog,'Done');
          for(const refresh of [refreshKeyboardHints,()=>window.fire('resize')]) {
            refresh();assert.equal(modalInput.getAttribute('aria-keyshortcuts'),'/ Alt+Enter');
            assert(!routeFrom(doneButton,'f').defaultPrevented);assert.equal(keyboardDialog(),modalDialog);
            assert.equal(modalEditor.ac,modalSearch);
          }
          setKeyboardCharactersEnabled(false);assert.equal(modalInput.getAttribute('aria-keyshortcuts'),'Alt+Enter');
          window.fire('resize');assert.equal(modalInput.getAttribute('aria-keyshortcuts'),'Alt+Enter');
          assert(!routeFrom(doneButton,'f').defaultPrevented);assert(!routeFrom(doneButton,'Enter').defaultPrevented);
          const modalFound={...elves,have:{owned:4},default:{set:'fdn',number:'227',finish:'nonfoil'}};
          modalInput.value=elves.name;modalSearch.query=elves.name;modalSearch.items=[modalFound];modalSearch.active=0;
          modalSearch.resultScope=editorSearchScope(modalSearch);drawOptions(modalSearch);modalInput.focus();
          assert(modalInput.fire('keydown',{key:'Enter',altKey:true}).defaultPrevented);
          assert.equal(inspections.length,1);assert.equal(modalSearch.items[modalSearch.active],modalFound);same(inspections[0].card,elves);
          setKeyboardCharactersEnabled(true);assert.equal(modalInput.getAttribute('aria-keyshortcuts'),'/ Alt+Enter');
          assert(!routeFrom(doneButton,'f').defaultPrevented);doneButton.click();
          assert.equal(keyboardDialog(),null);assert(modalSearch.cancelled);
          assert.equal(JSON.stringify(draftBody()),modalBody);assert.equal(modalEditor.history.length,modalHistory);same(modalCalls,[]);
        ''', PHONE)

    def test_new_deck_space_button_rebinds_retained_f_and_row_m_routes(self):
        self.run_js(panes_ui.SETUP, r'''
          state.profile=state.profiles[0];
          state.may={admin:true,create:[{space:'home',player:null},{space:'other',player:null}],
            see_inventory:['home','other'],see_accessories:true};
          location.hash='#/edit?mode=new&kind=casual&space=home';
          startEditor({mode:'new',kind:'casual',space:'home',view:view(),restoreDraft:false});
          const spaceEditor=editor,spacePage=spaceEditor.dom.page,spaceSearch=spaceEditor.ac;
          const spaceInput=spaceSearch.input,spaceRow=spaceEditor.dom.lines.querySelector('.edit-row');
          const spacePlus=spaceRow.querySelector('.step-plus'),spaceMore=spaceRow.editorChange.more;
          const spaceLines=JSON.stringify(sendList(spaceEditor.lists)),spaceCalls=noRouteIo();
          const spaceChoice=spacePage.querySelector('[data-space="other"]');assert(spaceChoice);spaceChoice.focus();spaceChoice.click();
          assert.equal(spaceEditor.space,'other');assert.equal(spaceEditor.fields.player,null);
          assert(spaceEditor.dom.page===spacePage&&spaceEditor.ac===spaceSearch&&spaceSearch.input===spaceInput);
          assert(spaceEditor.dom.lines.contains(spaceRow)&&spaceRow.editorChange.more===spaceMore);
          assert.equal(JSON.stringify(sendList(spaceEditor.lists)),spaceLines);
          const switchedBody=JSON.stringify(draftBody()),switchedHistory=spaceEditor.history.length;
          const spaceAnchor=routeAnchor(spacePage),spaceHelp=showKeyboardHelp(spaceAnchor);assert(spaceHelp);
          const findHelp=spaceHelp.dialog.querySelectorAll('.keyboard-help-row').find(row=>row.textContent.includes('Find a card to add'));
          assert(findHelp);assert.equal(findHelp.querySelector('.keyboard-help-keys').textContent,'F or /');spaceHelp.close();
          assert(routeFrom(spaceAnchor,'f').defaultPrevented);assert.equal(document.activeElement,spaceInput);
          assert.equal(spaceInput.getAttribute('aria-keyshortcuts'),'F / Alt+Enter');
          assert(routeFrom(spacePlus,'m').defaultPrevented);
          assert.equal(document.querySelector('[data-popover]').keyboardAnchor,spaceMore);closeMenus();
          assert.equal(JSON.stringify(draftBody()),switchedBody);assert.equal(spaceEditor.history.length,switchedHistory);
          assert(spaceEditor.dom.page===spacePage&&spaceEditor.ac===spaceSearch&&spaceSearch.input===spaceInput);
          assert(spaceEditor.dom.lines.contains(spaceRow)&&spaceRow.editorChange.more===spaceMore);same(spaceCalls,[]);
        ''', DESKTOP)

    def test_find_cards_f_selects_current_owner_field_and_ignores_an_earlier_duplicate_id(self):
        self.run_js(find_ui.FIXTURE, r'''
          location.hash='#/collection';const cv=drawFind({},'q=Alpha'),input=cv.filterControls.q,anchor=routeAnchor(cv.root);
          const before=[cv.query.toString(),location.hash,input.value,JSON.stringify(cv.data)],calls=noRouteIo();
          const decoy=el('input',{id:'collection-q',value:'Other controller'});main.remove();document.body.append(decoy,main);
          assert.equal(byId('collection-q'),decoy);assert(routeFrom(anchor,'f').defaultPrevented);
          assert.equal(document.activeElement,input);assert(input.selected);assert(!decoy.selected);assert.equal(input.getAttribute('aria-keyshortcuts'),'F');
          same([cv.query.toString(),location.hash,input.value,JSON.stringify(cv.data)],before);same(calls,[]);
          setKeyboardCharactersEnabled(false);assert.equal(input.getAttribute('aria-keyshortcuts'),null);
          assert(!routeFrom(anchor,'f').defaultPrevented);setKeyboardCharactersEnabled(true);
          assert(cv.filterControls.q===input);assert.equal(input.getAttribute('aria-keyshortcuts'),'F');same(calls,[]);
        ''')

    def test_card_list_f_selects_retained_row_search_without_filter_or_selection_changes(self):
        self.run_js(rows_ui.FIXTURE, r'''
          location.hash='#/collection?view=rows';const cv=draw({editable:false}),input=cv.rowSearch,anchor=routeAnchor(cv.root);
          assert(input&&input===cv.root.querySelector('#col-row-search'));input.value='Unsubmitted field text';
          const before=[cv.search,cv.sort,cv.selectedKey,cv.sha256,location.hash,JSON.stringify(cv.rows)],calls=noRouteIo();
          assert(routeFrom(anchor,'f').defaultPrevented);assert.equal(document.activeElement,input);assert(input.selected);
          assert.equal(input.value,'Unsubmitted field text');assert.equal(input.getAttribute('aria-keyshortcuts'),'F');
          same([cv.search,cv.sort,cv.selectedKey,cv.sha256,location.hash,JSON.stringify(cv.rows)],before);same(calls,[]);
          setCollectionBusy(cv,true);assert.equal(input.getAttribute('aria-keyshortcuts'),null);assert(!routeFrom(anchor,'f').defaultPrevented);
          setCollectionBusy(cv,false);assert.equal(input.getAttribute('aria-keyshortcuts'),'F');assert(routeFrom(anchor,'f').defaultPrevented);same(calls,[]);
        ''')

    def test_collection_f_refuses_hidden_disabled_foreign_detached_and_stale_controls(self):
        self.run_js(find_ui.FIXTURE, r'''
          const cv=drawFind(),input=cv.filterControls.q,anchor=routeAnchor(cv.root),calls=noRouteIo();
          for(const [attribute,value] of [['hidden',''],['disabled',''],['aria-disabled','true'],['inert','']]) {
            input.setAttribute(attribute,value);assert(!routeFrom(anchor,'f').defaultPrevented,attribute);input.removeAttribute(attribute);
          }
          const parent=input.parentNode;input.remove();document.body.append(input);assert(!routeFrom(anchor,'f').defaultPrevented);
          input.remove();parent.append(input);assert(routeFrom(anchor,'f').defaultPrevented);
          cv.busy=true;assert(!routeFrom(anchor,'f').defaultPrevented);cv.busy=false;
          cv.root.hidden=true;assert(!routeFrom(anchor,'f').defaultPrevented);cv.root.hidden=false;
          const token=routeToken;routeToken++;assert(!routeFrom(anchor,'f').defaultPrevented);routeToken=token;
          registerCollectionKeyboardHelp(cv);state.profile=PROFILES.find(p=>p.id==='user2');assert(!routeFrom(anchor,'f').defaultPrevented);
          state.profile=PROFILES[0];registerCollectionKeyboardHelp(cv);cv.root.remove();assert(!routeFrom(anchor,'f').defaultPrevented);same(calls,[]);
        ''')

    def test_m_activates_original_more_from_each_live_list_control_without_mutating_cards(self):
        self.run_js(panes_ui.SETUP, r'''
          const ed=full(),row=ed.dom.lines.querySelector('.edit-row'),more=row.editorChange.more;
          const before=JSON.stringify(draftBody()),history=ed.history.length,calls=noRouteIo();let clicks=0;
          more.addEventListener('click',()=>clicks++);assert.equal(more.getAttribute('aria-keyshortcuts'),'M');
          for(const control of [row.querySelector('.step-plus'),row.querySelector('.step-minus'),row.editorChange.trigger,row.querySelector('.edit-print')]) {
            assert(control);control.focus();assert.equal(editorMoreRoute(ed),more);assert(routeFrom(control,'m').defaultPrevented);
            const menu=document.querySelector('[data-popover]');assert(menu&&menu.keyboardAnchor===more);
            assert(menu.textContent.includes('Change printing')&&menu.textContent.includes('Remove'));closeMenus();
            assert.equal(JSON.stringify(draftBody()),before);assert.equal(ed.history.length,history);
          }
          assert.equal(clicks,4);assert(row.editorChange.more===more);same(calls,[]);
        ''', DESKTOP)

    def test_m_uses_original_picture_row_menu_and_help_preserves_eligible_return_focus(self):
        self.run_js(panes_ui.SETUP, r'''
          const ed=full();ed.look='visual';drawLines();
          const row=ed.dom.lines.querySelectorAll('[data-uid]').find(node=>node.editorChange);
          // This DOM double stores classList separately from the class attribute.
          // Reflect the browser's dynamic tile classes before exercising selectors.
          row.setAttribute('class',row.getAttribute('class')+' edit-row edit-tile');refreshKeyboardHints();
          const trigger=row.editorChange.trigger,more=row.editorChange.more;
          assert(row.classList.contains('edit-tile'));assert(trigger&&more);trigger.focus();
          const sheet=showKeyboardHelp(trigger),command=keyboardHelpCommands().find(c=>c.routeKey==='m');
          assert(command.available);assert(command.scope.includes('More button itself uses Enter or Space'));
          sheet.close();assert.equal(document.activeElement,trigger);assert(routeFrom(trigger,'m').defaultPrevented);
          assert.equal(document.querySelector('[data-popover]').keyboardAnchor,more);closeMenus();
          const quantity=row.querySelector('.qty-input');quantity.focus();const qtyHelp=showKeyboardHelp(quantity);
          assert.equal(keyboardHelpCommands().find(c=>c.routeKey==='m').available,false);qtyHelp.close();
          setKeyboardCharactersEnabled(false);assert.equal(more.getAttribute('aria-keyshortcuts'),null);assert(!routeFrom(trigger,'m').defaultPrevented);
          setKeyboardCharactersEnabled(true);assert.equal(more.getAttribute('aria-keyshortcuts'),'M');assert(row.editorChange.more===more);
        ''', DESKTOP)

    def test_m_rejects_text_more_itself_search_results_and_noncanonical_or_old_rows(self):
        self.run_js(panes_ui.SETUP, r'''
          const ed=full(),row=ed.dom.lines.querySelector('.edit-row'),record=row.editorChange,more=record.more;
          const plus=row.querySelector('.step-plus'),quantity=row.querySelector('.qty-input');let clicks=0;more.addEventListener('click',()=>clicks++);
          assert(!routeFrom(quantity,'m').defaultPrevented);assert(!routeFrom(more,'m').defaultPrevented);
          accepted(ed.ac);const result=ed.ac.list.querySelector('.step-plus');assert(result);assert(!routeFrom(result,'m').defaultPrevented);
          for(const [node,key,value] of [[plus,'hidden',''],[plus,'disabled',''],[plus,'aria-disabled','true'],[row,'inert',''],[more,'disabled','']]) {
            node.setAttribute(key,value);assert(!routeFrom(plus,'m').defaultPrevented,key);node.removeAttribute(key);
          }
          const section=record.section,at=ed.lists[section].indexOf(record.line),line=record.line;
          ed.lists[section][at]={...line};assert(!routeFrom(plus,'m').defaultPrevented);ed.lists[section][at]=line;
          record.section='Wrong section';assert(!routeFrom(plus,'m').defaultPrevented);record.section=section;
          const frame=ed.id;ed.id='casual/changed';assert(!routeFrom(plus,'m').defaultPrevented);ed.id=frame;
          for(const key of ['saving','asking','leaving']) {ed[key]=true;assert(!routeFrom(plus,'m').defaultPrevented,key);ed[key]=false;}
          drawLines();assert(!row.isConnected);assert(!routeFrom(plus,'m').defaultPrevented);assert.equal(clicks,0);
          assert.equal(document.querySelector('[data-popover]'),null);
        ''', DESKTOP)

    def test_f_and_m_are_unassigned_in_library_and_do_not_replace_existing_native_routes(self):
        self.run_js(library_ui.SHELF, r'''
          as('matt',MAY.admin);location.hash='#/library';window.matchMedia(LIB_LAB_QUERY).matches=true;
          drawLibrary(DATA,libraryFilters(new URLSearchParams('all=1')));const row=main.querySelector('.deck-row');
          const selected=main.querySelector('.lib-detail').getAttribute('data-id'),hash=location.hash,calls=noRouteIo();
          for(const key of ['f','m','Enter'])assert(!routeFrom(row,key).defaultPrevented,key);
          assert.equal(main.querySelector('.lib-detail').getAttribute('data-id'),selected);assert.equal(location.hash,hash);same(calls,[]);
          assert(row.getAttribute('aria-keyshortcuts').includes('J'));assert(!keyboardHelpCommands().some(c=>['f','m'].includes(c.routeKey)));
        ''')
