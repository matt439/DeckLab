"""Keyboard help and character preferences use current local UI scopes, with no new bindings."""
import json
import subprocess
import unittest

from decklab.tests import test_collection_layout_ui as collection_ui
from decklab.tests import test_editor_ui as editor_ui
from decklab.tests import test_editor_panes_ui as editor_panes_ui
from decklab.tests import test_library_ui as library_ui
from decklab.tests import test_shell_ui as shell_ui
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


HELP = shell_ui.SETUP + r'''
  const helpEntry=byId('menu-shortcuts')||el('button',{id:'menu-shortcuts',type:'button',text:'Keyboard shortcuts'});
  helpEntry.textContent='Keyboard shortcuts';helpEntry.remove();
  byId('avatar-menu').append(helpEntry);
  const helpAnchor=()=>{const node=el('button',{type:'button',text:'Open keyboard help'});main.append(node);node.focus();return node;};
  const choice=sheet=>sheet.dialog.querySelector('.keyboard-character-choice').querySelector('input');
  const checked=node=>node.checked===undefined?node.getAttribute('checked')!==null:node.checked;
  const helpRows=sheet=>sheet.dialog.querySelector('.keyboard-help-list');
  function helpRoot(commands,options={}) {
    const root=el('section');main.append(root);
    registerKeyboardHelp(root,commands,{profile:state.profile.id,current:()=>root.isConnected,...options});
    return root;
  }
'''


SHOPPING = r'''
  clear(main);editor=null;location.hash='#/shopping';
  state.profiles=[{id:'matt',name:'Matt',space:'home',role:'admin'}];state.profile=state.profiles[0];
  state.may={admin:true,orders:true,receipts:true,see_inventory:['home']};
  const empty={to_buy:[],orders:[],checks:[],warnings:[]};
  const pending={id:'illustrative-order',seller:'Fixture shop',ordered_on:'2000-01-01',status:'pending',
    components:[{id:'cards',kind:'cards',status:'pending',quantity:1,rows:1,items:[],path:'magic/orders/fixture.csv'}]};
  let reads=0,writes=0;api=async()=>{reads++;throw Error('No shortcut reads')};
  apiWrite=async()=>{writes++;throw Error('No shortcut writes')};
'''


@unittest.skipUnless(NODE, 'Node.js is not installed')
class KeyboardHelpUiTests(unittest.TestCase):
    def run_js(self, setup, scenario, viewport=None):
        # Full index order includes keyboard-help.js; partial legacy loaders are
        # verified separately when the production helper is registered there.
        result = subprocess.run([NODE, str(RUNNER)],
            input=json.dumps([str(WEB), setup + scenario, True, viewport]),
            capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'ok')

    def test_preferences_default_on_persist_per_profile_and_refuse_stale_profile_mutations(self):
        self.run_js(HELP, r'''
          as('matt');assert(keyboardCharactersEnabled());assert(keyboardCharactersEnabled('matt'));
          assert(keyboardCharactersEnabled({...state.profile}));assert(!keyboardCharactersEnabled('user1'));
          const matt=state.profile;
          let saved=setKeyboardCharactersEnabled(false);assert(saved.applied&&saved.persisted);
          assert(!keyboardCharactersEnabled());assert.equal(local.get('keyboard.characters.matt'),'off');
          as('user1');assert(keyboardCharactersEnabled());
          const stale=setKeyboardCharactersEnabled(true,matt);assert.equal(stale.applied,false);
          assert.equal(local.get('keyboard.characters.matt'),'off');assert(keyboardCharactersEnabled());
          saved=setKeyboardCharactersEnabled(false,'user1');assert(saved.applied&&saved.persisted);
          assert.equal(local.get('keyboard.characters.user1'),'off');assert(!keyboardCharactersEnabled());
          as('matt');assert(!keyboardCharactersEnabled());
          saved=setKeyboardCharactersEnabled(true);assert(saved.applied&&saved.persisted);
          assert(keyboardCharactersEnabled());assert.equal(local.get('keyboard.characters.matt'),'on');
          state.profile=null;assert(!keyboardCharactersEnabled());
          assert.equal(setKeyboardCharactersEnabled(false).applied,false);
        ''')

    def test_avatar_help_is_available_to_admin_home_member_and_remote_member_without_admin_settings(self):
        self.run_js(HELP, r'''
          setUpShell();
          for(const id of ['matt','user1','user2']) {
            as(id);drawShell();await flush();
            assert.equal(helpEntry.hidden,false);helpEntry.focus();helpEntry.click();
            const dialog=document.querySelector('dialog[open]');assert(dialog);
            assert(dialog.textContent.includes('Keyboard shortcuts'));
            assert(dialog.querySelector('.keyboard-character-choice').querySelector('input'));
            assert.equal(byId('menu-settings').hidden,id!=='matt');
            dialog.querySelector('.sheet-close').click();assert(!dialog.isConnected);
          }
        ''')

    def test_context_registry_tracks_live_commands_and_ignores_detached_or_other_profile_scopes(self):
        self.run_js(HELP, r'''
          as('matt');let live=true,phase='rows';
          const commands=()=>phase==='rows'?[{keys:['J','K'],label:'Move between visible rows',scope:'Fixture rows',characters:true}]
            :[{keys:['Ctrl+S','Cmd+S'],label:'Save the current draft',scope:'Fixture editor'}];
          const root=el('section');main.append(root);
          assert.equal(registerKeyboardHelp(root,commands,{profile:state.profile.id,current:()=>live&&root.isConnected}),root);
          assert(keyboardHelpCommands().some(c=>c.label==='Move between visible rows'));
          phase='edit';assert(!keyboardHelpCommands().some(c=>c.label==='Move between visible rows'));
          assert(keyboardHelpCommands().some(c=>c.label==='Save the current draft'));
          live=false;assert(!keyboardHelpCommands().some(c=>c.scope==='Fixture editor'));
          live=true;root.remove();assert(!keyboardHelpCommands().some(c=>c.scope==='Fixture editor'));
          helpRoot([{keys:['R'],label:'Receive the focused fixture delivery',scope:'Private old fixture',characters:true}]);
          state.profile=PROFILES.find(p=>p.id==='user1');
          assert(!keyboardHelpCommands().some(c=>c.scope==='Private old fixture'));
        ''')

    def test_help_lists_the_underlying_current_scope_and_opens_without_api_or_navigation(self):
        self.run_js(HELP, r'''
          as('matt');location.hash='#/library';
          const root=helpRoot([{keys:['J','K'],label:'Move between visible rows',scope:'Fixture library',characters:true},
            {keys:['Enter'],label:'Open the selected fixture deck',scope:'Fixture library'}]);
          let reads=0,writes=0;api=async()=>{reads++;throw Error('Help must not read')};
          apiWrite=async()=>{writes++;throw Error('Help must not write')};
          const anchor=helpAnchor(),hash=location.hash,sheet=showKeyboardHelp(anchor);assert(sheet);
          assert(helpRows(sheet).textContent.includes('Move between visible rows'));
          assert(helpRows(sheet).textContent.includes('Open the selected fixture deck'));
          assert(helpRows(sheet).textContent.includes('J'));assert(helpRows(sheet).textContent.includes('K'));
          assert.equal(location.hash,hash);assert.equal(root.isConnected,true);same([reads,writes],[0,0]);
          sheet.close();assert(!sheet.dialog.isConnected);assert.equal(document.activeElement,anchor);
          assert.equal(location.hash,hash);same([reads,writes],[0,0]);
        ''')

    def test_refresh_callbacks_keep_current_controls_and_skip_stale_scope_owners(self):
        self.run_js(HELP, r'''
          as('matt');let currentScope=true,refreshes=0;
          const root=el('section'),input=el('input'),summary=el('summary');root.append(input,summary);main.append(root);
          const refresh=enabled=>{refreshes++;input.setAttribute('aria-keyshortcuts',enabled?'/ Alt+Enter':'Alt+Enter');
            if(enabled)summary.setAttribute('aria-keyshortcuts','R');else summary.removeAttribute('aria-keyshortcuts');};
          registerKeyboardHelp(root,[{keys:['/'],label:'Focus current fixture search',scope:'Fixture editor',characters:true}],
            {profile:state.profile.id,current:()=>currentScope,refresh});
          refreshKeyboardHints();const initial=refreshes;assert(initial>0);
          setKeyboardCharactersEnabled(false);refreshKeyboardHints();assert(refreshes>initial);
          assert.equal(input.getAttribute('aria-keyshortcuts'),'Alt+Enter');assert.equal(summary.getAttribute('aria-keyshortcuts'),null);
          assert(root.querySelector('input')===input&&root.querySelector('summary')===summary);
          setKeyboardCharactersEnabled(true);refreshKeyboardHints();
          assert.equal(input.getAttribute('aria-keyshortcuts'),'/ Alt+Enter');assert.equal(summary.getAttribute('aria-keyshortcuts'),'R');
          currentScope=false;const inactive=refreshes;refreshKeyboardHints();assert(refreshes>inactive);
          assert.equal(input.getAttribute('aria-keyshortcuts'),'Alt+Enter');assert.equal(summary.getAttribute('aria-keyshortcuts'),null);
          const stopped=refreshes;currentScope=true;state.profile=PROFILES.find(p=>p.id==='user1');refreshKeyboardHints();assert.equal(refreshes,stopped);
          state.profile=PROFILES[0];root.remove();refreshKeyboardHints();assert.equal(refreshes,stopped);
        ''')

    def test_storage_failure_keeps_session_choice_and_reports_failure_without_mutating_other_profiles(self):
        self.run_js(HELP, r'''
          as('matt');const anchor=helpAnchor(),sheet=showKeyboardHelp(anchor);assert(sheet);
          const toggle=choice(sheet);assert(checked(toggle));
          window.localStorage.setItem=()=>{throw Error('Fixture storage is blocked')};
          toggle.checked=false;toggle.fire('change');assert(!keyboardCharactersEnabled());
          const notice=sheet.dialog.querySelector('.keyboard-save-notice');assert(notice&&!notice.hidden&&notice.textContent.trim());
          sheet.close();const again=showKeyboardHelp(anchor);assert.equal(checked(choice(again)),false);again.close();
          as('user1');assert(keyboardCharactersEnabled());
          as('matt');assert(!keyboardCharactersEnabled());
          window.localStorage.getItem=()=>{throw Error('Fixture reads are blocked too')};assert(!keyboardCharactersEnabled());
          const result=setKeyboardCharactersEnabled(true);assert(result.applied&&!result.persisted);assert(keyboardCharactersEnabled());
        ''')

    def test_initial_inactive_mounted_registration_strips_hints_and_old_scopes_are_pruned(self):
        self.run_js(HELP, r'''
          as('matt');const detached=el('section');let calls=0;
          const command={keys:['J'],label:'Fixture row navigation',scope:'Old fixture rows',characters:true};
          registerKeyboardHelp(detached,[command],{refresh:()=>{calls++}});assert.equal(calls,0);
          main.append(detached);assert(!keyboardHelpCommands().some(c=>c.scope===command.scope));
          const input=el('input',{'aria-keyshortcuts':'/ Alt+Enter'});detached.append(input);let active=false;
          registerKeyboardHelp(detached,[command],{current:()=>active,refresh:enabled=>{
            calls++;keyboardCharacterKeys(input,['/'],enabled);}});
          assert.equal(calls,1);assert.equal(input.getAttribute('aria-keyshortcuts'),'Alt+Enter');
          assert(!keyboardHelpCommands().some(c=>c.scope===command.scope));
          active=true;refreshKeyboardHints();assert.equal(input.getAttribute('aria-keyshortcuts'),'/ Alt+Enter');
          assert(keyboardHelpCommands().some(c=>c.scope===command.scope));
          const previous=calls;routeToken++;
          const currentRoot=helpRoot([{keys:['Enter'],label:'Current fixture action',scope:'Current fixture'}]);
          assert(!keyboardHelpScopes.has(detached));assert(keyboardHelpScopes.has(currentRoot));
          refreshKeyboardHints();assert.equal(calls,previous);
          assert(!keyboardHelpCommands().some(c=>c.scope===command.scope));
          assert(keyboardHelpCommands().some(c=>c.scope==='Current fixture'));
        ''')

    def test_unavailable_current_commands_keep_their_reason_and_character_off_is_explicit(self):
        self.run_js(HELP, r'''
          as('matt');helpRoot([
            {keys:['J','K'],label:'Move through fixture rows',scope:'Fixture rows',characters:true},
            {keys:['Ctrl/Cmd+S'],label:'Save fixture draft',scope:'Fixture editor',available:()=>false,
              unavailable:'Wait for the current fixture operation.'}]);
          const sheet=showKeyboardHelp(helpAnchor());assert(sheet);
          assert(helpRows(sheet).querySelectorAll('.keyboard-help-unavailable').some(node=>node.textContent.includes('current fixture operation')));
          const save=keyboardHelpCommands().find(c=>c.label==='Save fixture draft');assert.equal(save.available,false);
          choice(sheet).checked=false;choice(sheet).fire('change');
          const character=keyboardHelpCommands().find(c=>c.label==='Move through fixture rows');
          assert.equal(character.available,false);assert(character.why.includes('off'));
          assert(helpRows(sheet).querySelectorAll('.keyboard-help-unavailable').some(node=>node.textContent.includes('off')));
          assert(helpRows(sheet).textContent.includes('Save fixture draft'));sheet.close();
        ''')

    def test_closed_and_other_profile_help_callbacks_cannot_change_preferences(self):
        self.run_js(HELP, r'''
          as('matt');let anchor=helpAnchor(),sheet=showKeyboardHelp(anchor),toggle=choice(sheet);
          sheet.close();toggle.checked=false;toggle.fire('change');assert(keyboardCharactersEnabled());
          assert.equal(local.get('keyboard.characters.matt'),null);
          sheet=showKeyboardHelp(anchor);toggle=choice(sheet);
          state.profile=PROFILES.find(p=>p.id==='user1');toggle.checked=false;toggle.fire('change');
          assert(keyboardCharactersEnabled());assert.equal(local.get('keyboard.characters.user1'),null);
          assert.equal(local.get('keyboard.characters.matt'),null);sheet.close();
        ''')

    def test_foreign_modal_and_stale_return_context_do_not_steal_focus(self):
        self.run_js(HELP, r'''
          as('matt');let anchor=helpAnchor();
          const foreign=el('dialog',{open:''});document.body.append(foreign);
          assert.equal(showKeyboardHelp(anchor),null);assert(foreign.isConnected);foreign.remove();
          for(const mutate of [()=>{routeToken++;},()=>{location.hash='#/collection';},
            ()=>{state.profile=PROFILES.find(p=>p.id==='user1');},()=>{anchor.remove();}]) {
            state.profile=PROFILES[0];location.hash='#/library';anchor=helpAnchor();
            const sheet=showKeyboardHelp(anchor);assert(sheet);
            const current=el('button',{type:'button',text:'Current page control'});document.body.append(current);current.focus();
            mutate();sheet.close();assert.equal(document.activeElement,current);
            current.remove();anchor.remove();
          }
        ''')

    def test_disabled_characters_leave_library_selection_unchanged_until_reenabled(self):
        self.run_js(library_ui.SHELF, r'''
          as('matt',MAY.admin);location.hash='#/library';window.matchMedia(LIB_LAB_QUERY).matches=true;
          drawLibrary(DATA,libraryFilters(new URLSearchParams('all=1')));
          const selected=()=>main.querySelector('.lib-detail').getAttribute('data-id'),before=selected();
          const row=main.querySelector('.deck-row');assert.equal(row.getAttribute('aria-keyshortcuts'),'J K');
          setKeyboardCharactersEnabled(false);assert(!document.fire('keydown',{key:'j',target:main}).defaultPrevented);
          assert.equal(selected(),before);assert.equal(row.getAttribute('aria-keyshortcuts'),null);
          assert(main.querySelector('.deck-row')===row);
          setKeyboardCharactersEnabled(true);assert.equal(row.getAttribute('aria-keyshortcuts'),'J K');
          assert(main.querySelector('.deck-row')===row);assert(document.fire('keydown',{key:'j',target:main}).defaultPrevented);
          assert.notEqual(selected(),before);
        ''')

    def test_editor_slash_can_be_disabled_while_modifier_save_undo_and_modal_save_guard_remain(self):
        self.run_js(editor_ui.SETUP, r'''
          const ed=edit(),page=el('div');main.append(page);
          ed.dom={page,keyboardOwner:{page,token:routeToken,profile:ed.profile}};let focuses=0,saves=0,undos=0;
          focusSearch=()=>{focuses++};saveNow=()=>{saves++};undoLast=()=>{undos++;return true};
          setKeyboardCharactersEnabled(false);
          assert(!document.fire('keydown',{key:'/',target:main}).defaultPrevented);assert.equal(focuses,0);
          assert(document.fire('keydown',{key:'s',ctrlKey:true,target:main}).defaultPrevented);assert.equal(saves,1);
          assert(document.fire('keydown',{key:'s',metaKey:true,target:main}).defaultPrevented);assert.equal(saves,2);
          assert(document.fire('keydown',{key:'z',ctrlKey:true,target:main}).defaultPrevented);assert.equal(undos,1);
          const sheet=el('dialog',{open:''});document.body.append(sheet);
          assert(document.fire('keydown',{key:'s',ctrlKey:true,target:main}).defaultPrevented);assert.equal(saves,2);sheet.remove();
          editor.readOnly=true;assert(document.fire('keydown',{key:'s',ctrlKey:true,target:main}).defaultPrevented);assert.equal(saves,2);
          editor.readOnly=false;setKeyboardCharactersEnabled(true);
          assert(document.fire('keydown',{key:'/',target:main}).defaultPrevented);assert.equal(focuses,1);
        ''')

    def test_collection_character_gate_leaves_enter_viewer_action_and_original_controls_working(self):
        self.run_js(collection_ui.FIXTURE, r'''
          location.hash='#/collection';const cv=draw();let region=main.querySelector('.col-row-lab').querySelector('.table-wrap');
          const hint=region.querySelector('.keyboard-character-hint');assert(hint&&!hint.hidden);
          assert(region.getAttribute('aria-keyshortcuts').includes('J'));assert(region.getAttribute('aria-keyshortcuts').includes('Enter'));
          setCollectionBusy(cv,true);assert.equal(region.getAttribute('aria-keyshortcuts'),'Enter');assert(hint.hidden);
          assert.equal(keyboardHelpCommands().find(c=>c.label==='Select the next or previous card').available,false);
          setCollectionBusy(cv,false);assert(region.getAttribute('aria-keyshortcuts').includes('J'));assert(!hint.hidden);
          setKeyboardCharactersEnabled(false);const selected=cv.selectedKey;
          assert.equal(region.getAttribute('aria-keyshortcuts'),'Enter');assert(hint.hidden);
          assert(!region.fire('keydown',{key:'j'}).defaultPrevented);assert.equal(cv.selectedKey,selected);
          colSelectRow(cv,'fdn|2|nonfoil');const target=tableRow(cv.selectedKey).querySelector('.col-open');
          region=main.querySelector('.col-row-lab').querySelector('.table-wrap');
          assert(region.fire('keydown',{key:'Enter',target}).defaultPrevented);
          assert.equal(inspections.length,1);assert.equal(inspections[0].card,cv.pictures['fdn|2|nonfoil']);
          setKeyboardCharactersEnabled(true);const liveRegion=main.querySelector('.col-row-lab').querySelector('.table-wrap');
          assert(liveRegion.getAttribute('aria-keyshortcuts').includes('J'));
          assert(!liveRegion.querySelector('.keyboard-character-hint').hidden);
          assert(liveRegion.fire('keydown',{key:'j'}).defaultPrevented);
          assert.notEqual(cv.selectedKey,'fdn|2|nonfoil');
        ''')

    def test_editor_help_covers_existing_search_and_quantity_commands_without_replacing_metadata(self):
        self.run_js(editor_panes_ui.SETUP, r'''
          location.hash='#/edit?id=casual%2Fsample&v=target';const ed=full();
          const searchInput=ed.ac.input,save=ed.dom.barParts.save,page=ed.dom.page,body=JSON.stringify(draftBody()),history=ed.history.length;
          accepted(ed.ac);
          assert.equal(searchInput.getAttribute('aria-keyshortcuts'),'/ Alt+Enter');
          assert.equal(save.getAttribute('aria-keyshortcuts'),'Control+S Meta+S');
          const commands=keyboardHelpCommands();
          for(const key of ['ArrowUp','ArrowDown','Enter','Shift+Enter','Alt+Enter','Escape'])
            assert(commands.some(c=>c.keys.includes(key)),key);
          assert(commands.some(c=>c.label==='Finish editing a quantity'&&c.scope.includes('quantity field focused')));
          assert(commands.some(c=>c.label==='Finish editing an Add cards quantity'&&c.available));
          assert(commands.some(c=>c.label==='Choose a search result'&&c.scope.includes('current results loaded')));
          assert(commands.some(c=>c.label==='Inspect a search result'&&c.scope.includes('current result chosen')));
          ed.saving=true;drawBar();assert.equal(searchInput.getAttribute('aria-keyshortcuts'),'Alt+Enter');
          assert.equal(save.getAttribute('aria-keyshortcuts'),null);
          assert.equal(keyboardHelpCommands().find(c=>c.keys.includes('/')).available,false);
          assert(keyboardHelpCommands().find(c=>c.label==='Finish editing a quantity').available);
          assert.equal(keyboardHelpCommands().find(c=>c.label==='Finish editing an Add cards quantity').available,false);
          ed.saving=false;drawBar();assert.equal(searchInput.getAttribute('aria-keyshortcuts'),'/ Alt+Enter');
          assert.equal(save.getAttribute('aria-keyshortcuts'),'Control+S Meta+S');
          assert(keyboardHelpCommands().find(c=>c.label==='Finish editing an Add cards quantity').available);
          save.setAttribute('aria-keyshortcuts','Control+S Meta+S Alt+S');save.disabled=true;refreshKeyboardHints();
          assert.equal(save.getAttribute('aria-keyshortcuts'),'Alt+S');
          drawBar();assert.equal(save.getAttribute('aria-keyshortcuts'),'Control+S Meta+S Alt+S');
          save.removeAttribute('aria-keyshortcuts');refreshKeyboardHints();
          ed.asking=true;drawBar();assert.equal(save.getAttribute('aria-keyshortcuts'),null);
          assert.equal(keyboardHelpCommands().find(c=>c.label==='Finish editing a quantity').available,false);
          ed.asking=false;drawBar();assert.equal(save.getAttribute('aria-keyshortcuts'),'Control+S Meta+S');
          setKeyboardCharactersEnabled(false);assert.equal(searchInput.getAttribute('aria-keyshortcuts'),'Alt+Enter');
          assert.equal(save.getAttribute('aria-keyshortcuts'),'Control+S Meta+S');
          assert.equal(keyboardHelpCommands().find(c=>c.keys.includes('/')).available,false);
          assert(keyboardHelpCommands().find(c=>c.keys.includes('Alt+Enter')).available);
          setKeyboardCharactersEnabled(true);assert.equal(searchInput.getAttribute('aria-keyshortcuts'),'/ Alt+Enter');
          assert(ed.ac.input===searchInput&&ed.dom.barParts.save===save&&ed.dom.page===page);
          assert.equal(JSON.stringify(draftBody()),body);assert.equal(ed.history.length,history);
          closeEditor();const trial=full({may_save:false});assert(trial.readOnly);
          assert(!keyboardHelpCommands().some(c=>c.keys.includes('Ctrl/Cmd+S')));
          assert(keyboardHelpCommands().some(c=>c.keys.includes('Alt+Enter')));
        ''', {'innerWidth':1000,'innerHeight':830,'coarse':False,'visual':{'width':1000,'height':830}})

    def test_actual_save_precheck_immediately_strips_and_restores_metadata_after_blocked_or_failed_checks(self):
        self.run_js(editor_panes_ui.SETUP, r'''
          location.hash='#/edit?id=casual%2Fsample&v=target';
          const goodCheck={blocks:[],warnings:[],file_changed:false,
            changes:{decklist:false,fields:[],prose:[],marker:false}};
          for(const outcome of ['blocked','failed']) {
            const ed=full(),searchInput=ed.ac.input,saveButton=ed.dom.barParts.save;
            accepted(ed.ac);ed.check=structuredClone(goodCheck);drawCheck();drawBar();
            const quantity=ed.dom.lines.querySelector('.qty-input'),page=ed.dom.page;
            const beforeBody=JSON.stringify(draftBody()),beforeHistory=ed.history.length,requests=[];
            let releaseCheck,rejectCheck;
            api=async()=>{throw Error('Save precheck must not read another endpoint');};
            apiWrite=(path,body)=>{
              requests.push({path,body:structuredClone(body)});
              assert.equal(path,'/api/deck/check','Only the frozen precheck is allowed; no deck save');
              return new Promise((resolve,reject)=>{releaseCheck=resolve;rejectCheck=reject;});
            };
            assert.equal(searchInput.getAttribute('aria-keyshortcuts'),'/ Alt+Enter');
            assert.equal(saveButton.getAttribute('aria-keyshortcuts'),'Control+S Meta+S');
            const pending=saveNow();
            // An existing check makes drawCheckingState skip drawBar. The state
            // transition itself must strip hints before this promise settles.
            assert(ed.saving&&ed.checking);assert.equal(requests.length,1);
            assert.equal(saveButton.getAttribute('aria-keyshortcuts'),null);
            assert.equal(searchInput.getAttribute('aria-keyshortcuts'),'Alt+Enter');
            assert(quantity.isConnected&&!quantity.disabled);
            assert(keyboardHelpCommands().find(c=>c.label==='Finish editing a quantity').available);
            assert.equal(keyboardHelpCommands().find(c=>c.label==='Finish editing an Add cards quantity').available,false);
            assert.equal(keyboardHelpCommands().find(c=>c.keys.includes('/')).available,false);
            await saveNow();assert.equal(requests.length,1,'A repeated Save cannot start another check or write');
            if(outcome==='blocked')releaseCheck({...structuredClone(goodCheck),blocks:[{field:'title',problem:'Fixture save block'}]});
            else rejectCheck(new ApiError(503,'Fixture check unavailable'));
            await pending;
            assert.equal(ed.saving,false);assert.equal(ed.checking,false);assert(!saveButton.disabled);
            assert.equal(saveButton.getAttribute('aria-keyshortcuts'),'Control+S Meta+S');
            assert.equal(searchInput.getAttribute('aria-keyshortcuts'),'/ Alt+Enter');
            assert(keyboardHelpCommands().find(c=>c.label==='Finish editing a quantity').available);
            assert(keyboardHelpCommands().find(c=>c.label==='Finish editing an Add cards quantity').available);
            const review=keyboardDialog();assert(review);
            assert(review.textContent.includes(outcome==='blocked'?'Fixture save block':'Fixture check unavailable'));
            button(review,'Keep editing').click();assert.equal(keyboardDialog(),null);
            assert(ed.dom.page===page&&ed.ac.input===searchInput&&ed.dom.barParts.save===saveButton);
            assert(ed.dom.lines.contains(quantity)&&!quantity.disabled);
            assert.equal(JSON.stringify(draftBody()),beforeBody);assert.equal(ed.history.length,beforeHistory);
            same(requests.map(request=>request.path),['/api/deck/check']);
            assert.equal(JSON.stringify(requests[0].body),beforeBody);closeEditor();
          }
        ''', {'innerWidth':1000,'innerHeight':830,'coarse':False,'visual':{'width':1000,'height':830}})

    def test_delivery_r_gate_preserves_disclosure_defaults_and_reenables_the_original_summary(self):
        self.run_js(SHOPPING, r'''
          const view=drawShopping({...empty,orders:[pending]}),summary=main.querySelector('.shop-delivery-summary');summary.focus();
          const record=summary.keyboardDelivery,description=record.description,hint=record.hint;
          assert.equal(summary.getAttribute('aria-keyshortcuts'),'R');assert(!hint.hidden);assert(description.textContent.includes('Press R'));
          shopQueueBusy(view,true);assert.equal(summary.getAttribute('aria-keyshortcuts'),null);assert(hint.hidden);
          assert.equal(keyboardHelpCommands().find(c=>c.keys.includes('R')).available,false);
          shopQueueBusy(view,false);assert.equal(summary.getAttribute('aria-keyshortcuts'),'R');assert(!hint.hidden);
          setKeyboardCharactersEnabled(false);refreshKeyboardHints();
          assert.equal(summary.getAttribute('aria-keyshortcuts'),null);assert(hint.hidden);
          assert(!description.textContent.includes('Press R'));assert(description.textContent.includes('Enter or Space'));
          assert(!summary.fire('keydown',{key:'r'}).defaultPrevented);assert.equal(location.hash,'#/shopping');
          for(const key of ['Enter',' ','Escape'])assert(!summary.fire('keydown',{key}).defaultPrevented);
          assert(main.querySelector('.shop-delivery-summary')===summary);assert.equal(view.data.orders[0],pending);
          setKeyboardCharactersEnabled(true);refreshKeyboardHints();summary.focus();
          assert.equal(summary.getAttribute('aria-keyshortcuts'),'R');assert(!hint.hidden);assert(description.textContent.includes('Press R'));
          assert(summary.keyboardDelivery===record&&record.description===description&&record.hint===hint);
          assert(summary.fire('keydown',{key:'r'}).defaultPrevented);
          assert.equal(location.hash,'#/receipt?order=illustrative-order');same([reads,writes],[0,0]);
          clear(main);location.hash='#/shopping';
          state.profile={id:'user1',name:'User1',space:'home',role:'member'};state.profiles.push(state.profile);
          state.may={admin:false,orders:false,receipts:false,see_inventory:['home']};assert(!mayDo('receipts'));
          drawShopping({...empty,orders:[pending]});const readonly=main.querySelector('.shop-delivery-summary');
          setKeyboardCharactersEnabled(false);setKeyboardCharactersEnabled(true);
          assert.equal(readonly.getAttribute('aria-keyshortcuts'),null);assert.equal(readonly.keyboardDelivery.description,null);
          readonly.focus();assert(!readonly.fire('keydown',{key:'r'}).defaultPrevented);assert.equal(location.hash,'#/shopping');
          assert(!keyboardHelpCommands().some(c=>c.keys.includes('R')));same([reads,writes],[0,0]);
        ''')
