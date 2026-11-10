"""Read-only change polling and draft-preserving actions with fake promises/DOM."""
import json
import subprocess
import unittest

from decklab.tests.test_shell_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SCENARIO = "const realChangeApi=api;\n" + SETUP + r'''
  as('matt',false); location.hash='#/deck?id=casual/test'; routeToken++;
  let writes=0, reloads=0;apiWrite=()=>{writes++;throw Error('No writes');};route=()=>{reloads++;};
  const revision=(inventory='a',decks='b',library='c')=>({ready:true,inventory:inventory.repeat(64),decks:decks.repeat(64),library:library.repeat(64)});
  const base=()=>noteRevisions(revision(),{owner:changeRequestOwner(),kind:'read'});
  const poll=value=>noteRevisions(value,{owner:changeRequestOwner(),kind:'poll'});
  const notice=()=>main.querySelector('.change-notice');
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ChangeSignalUiTests(unittest.TestCase):
    def run_js(self, source):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([
            str(WEB), SCENARIO + source + "\nassert.equal(writes,0);", True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_signal_drops_the_cache_group_without_reloading_or_touching_a_draft_and_unknown_is_not_zero(self):
        self.run_js(r'''
          const draft={card:'KEEP_TYPED_CARD'};editor=draft;state.library={decks:[]};state.libraryForge={old:true};state.libraryGauntlet={old:true};
          base();poll(revision());assert.equal(notice(),null);
          poll(revision('d'));assert(notice().textContent.includes('Saved on another device'));
          assert.equal(reloads,0);assert.equal(editor,draft);assert.equal(draft.card,'KEEP_TYPED_CARD');
          assert.equal(state.library,null);assert.equal(state.libraryForge,null);assert.equal(state.libraryGauntlet,null);
          const known=changeSignals.latest;poll({ready:false});assert.equal(changeSignals.latest,known);
          assert(notice(),'an existing notice and baseline survive an unknown read');
          poll(revision('d'));assert.equal(changeSignals.latest.inventory,'d'.repeat(64));
        ''')

    def test_read_header_closes_initial_poll_race_and_committed_own_write_ignores_older_inflight_answers(self):
        self.run_js(r'''
          const read=changeRequestOwner(),oldPoll=changeRequestOwner();
          noteRevisions(revision('d'),{owner:oldPoll,kind:'poll'});
          noteRevisions(revision(),{owner:read,kind:'read'});assert(notice(),'the loaded old page differs from the first poll');
          const stale=changeRequestOwner();noteRevisions(revision('e'),{owner:changeRequestOwner(),kind:'write'});
          assert.equal(notice(),null,'a local write acknowledges its exact saved snapshot');
          noteRevisions(revision(),{owner:stale,kind:'poll'});assert.equal(notice(),null);
          assert.equal(changeSignals.latest.inventory,'e'.repeat(64));
          const owner=changeRequestOwner();changesFromHeader({headers:{get:()=>JSON.stringify(revision('f'))}},owner,'GET');
          assert(notice());assert.equal(writes,0);
          const baseBefore=changeSignals.page.base;
          changesFromHeader({headers:{get:key=>key==='X-Deck-Lab-Changes'?JSON.stringify(revision('f')):null}},changeRequestOwner(),'POST');
          assert.equal(changeSignals.page.base,baseBefore,'a dry check or draft write never acknowledges an unseen external save');
          changesFromHeader({headers:{get:key=>key==='X-Deck-Lab-Changes'?JSON.stringify(revision('f')):'1'}},changeRequestOwner(),'POST');
          assert.equal(changeSignals.page.base.inventory,'f'.repeat(64));assert.equal(notice(),null);
        ''')

    def test_timer_checks_are_poll_marked_no_wake_and_hidden_tabs_abort_and_ignore_profile_stale_replies(self):
        self.run_js(r'''
          base();let finish,request;api=async(path,options)=>{
            assert.equal(path,'/api/changes');assert.equal(options.poll,true);assert.equal(options.wakeHop,false);
            request=options;return await new Promise(done=>{finish=done;});};
          document.visibilityState='hidden';pollChangeSignals();assert.equal(request,undefined);
          document.visibilityState='visible';pollChangeSignals();await flush();assert(request);
          stopChangeSignals();assert(request.signal.aborted);
          finish(revision('d'));await flush();assert.equal(notice(),null);
          changeSignals.at=null;pollChangeSignals();await flush();as('user2');location.hash='#/collection';
          changeRequestOwner();finish(revision('f'));await flush();assert.equal(notice(),null);
          assert.equal(changeSignals.latest,null);assert.equal(reloads,0);
        ''')

    def test_a_newer_background_header_never_becomes_the_baseline_of_an_older_loaded_page(self):
        self.run_js(r'''
          const pageRead=changeRequestOwner(),backgroundRead=changeRequestOwner();
          changesFromHeader({headers:{get:key=>key==='X-Deck-Lab-Changes'?JSON.stringify(revision('d')):null}},backgroundRead,'GET',true);
          assert.equal(changeSignals.page,null,'a timer cannot establish the loaded page baseline');
          changesFromHeader({headers:{get:key=>key==='X-Deck-Lab-Changes'?JSON.stringify(revision()):null}},pageRead,'GET',false);
          assert(notice(),'the actual loaded page is older than the observed background snapshot');
          assert.equal(changeSignals.page.base.inventory,'a'.repeat(64));
          assert.equal(changeSignals.latest.inventory,'d'.repeat(64));assert.equal(reloads,0);
        ''')

    def test_old_route_write_never_acknowledges_a_new_page_or_drops_its_inflight_initial_baseline(self):
        self.run_js(r'''
          base();const writeA=changeRequestOwner();
          location.hash='#/deck?id=casual/second';routeToken++;clear(main);base();
          const pageB=changeSignals.page,baseB=pageB.base,generation=changeSignals.generation;
          poll(revision('d','e','f'));assert(notice(),'another device changed B after it loaded');
          noteRevisions(revision('d','e','f'),{owner:writeA,kind:'write'});
          assert.equal(pageB.base,baseB,'A commit cannot acknowledge the loaded B page');
          assert.equal(changeSignals.generation,generation);assert(notice());
          // Now B's data read has not returned when the old-route write completes.
          stopChangeSignals(true);location.hash='#/deck?id=casual/first';routeToken++;clear(main);base();
          const delayedWriteA=changeRequestOwner();
          location.hash='#/deck?id=casual/second';routeToken++;clear(main);
          const initialB=changeRequestOwner(),initialGeneration=changeSignals.generation;
          noteRevisions(revision('d','e','f'),{owner:delayedWriteA,kind:'write'});
          assert.equal(changeSignals.generation,initialGeneration,'cross-route completion does not invalidate B initial data');
          noteRevisions(revision(),{owner:initialB,kind:'read'});
          assert.equal(changeSignals.page.base.inventory,'a'.repeat(64));
          assert.equal(changeSignals.latest.inventory,'d'.repeat(64));assert(notice());assert.equal(reloads,0);
        ''')

    def test_reload_owner_guards_keep_open_sheets_and_explicit_editor_reload_reapplies_instead_of_discarding(self):
        self.run_js(r'''
          location.hash='#/edit?id=casual/test';base();poll(revision('d'));
          const draft={mode:'edit',id:'casual/test',typed:'KEEP'};editor=draft;
          let calls=0;reapplyLatest=async(sheet,error,button,current)=>{
            assert(current());assert.equal(editor,draft);calls++;return true;};
          notice().querySelector('button').click();await flush();assert.equal(calls,1);assert.equal(editor.typed,'KEEP');assert.equal(reloads,0);
          // An open collection edit is never closed or discarded by Reload.
          location.hash='#/collection';routeToken++;base();poll(revision('d'));
          const dialog=el('dialog');dialog.open=true;document.body.append(dialog);
          notice().querySelector('button').click();await flush();assert.equal(reloads,0);assert(dialog.open);
          dialog.remove();const button=notice().querySelector('button');location.hash='#/library';routeToken++;
          button.click();await flush();assert.equal(reloads,0,'a detached page action cannot reload its successor');
        ''')

    def test_new_deck_reload_reads_reference_data_but_preserves_typed_cards_and_uses_no_write(self):
        self.run_js(r'''
          location.hash='#/new';base();poll(revision('d'));
          editor={mode:'new',typed:['KEEP_CARD'],fields:{title:'KEEP_TITLE'}};
          const draft=editor;api=async path=>{assert.equal(path,'/api/decks');
            noteRevisions(revision('d'),{owner:changeRequestOwner(),kind:'read'});return {decks:[]};};
          notice().querySelector('button').click();await flush();assert.equal(editor,draft);
          same(editor.typed,['KEEP_CARD']);assert.equal(editor.fields.title,'KEEP_TITLE');assert.equal(reloads,0);assert.equal(notice(),null);
        ''')

    def test_private_profile_and_epoch_stale_library_answers_cannot_refill_the_cache(self):
        self.run_js(r'''
          let finish;fetch=async()=>await new Promise(done=>{finish=done;});
          const pending=realChangeApi('/api/decks');await flush();invalidateLibrary();
          finish({ok:true,json:async()=>({decks:[{title:'OLD_PRIVATE'}]})});const data=await pending;
          assert.equal(cacheLibrary(data),null);assert.equal(state.library,null);
          const newer=realChangeApi('/api/decks');await flush();invalidateLibrary();
          finish({ok:true,headers:{get:key=>key==='X-Deck-Lab-Changes'?JSON.stringify(revision()):null},json:async()=>({decks:[]})});
          const latestLibrary=await newer;assert.equal(cacheLibrary(latestLibrary),latestLibrary,'a matching fresh signal proves a raced answer current');
          const unknown=realChangeApi('/api/decks');await flush();
          finish({ok:true,headers:{get:key=>key==='X-Deck-Lab-Changes'?JSON.stringify({ready:false}):null},json:async()=>({decks:[],inventory_stale:'Unavailable'})});
          const stale=await unknown;assert.equal(cacheLibrary(stale),stale);assert.equal(state.library,null,'stale data may draw but cannot refill a fresh cache');
          const profileAnswer={decks:[{title:'OLD_PROFILE'}]};
          libraryAnswerOwners.set(profileAnswer,{profile:state.profile,epoch:state.libraryEpoch});
          as('user2');assert.equal(cacheLibrary(profileAnswer),null);assert.equal(state.library,null);
        ''')

    def test_public_deck_changes_use_library_token_but_other_public_collections_get_no_inventory_counter(self):
        self.run_js(r'''
          location.hash='#/deck?id=user2/casual/public';base();poll(revision('a','b','d'));assert(notice());
          location.hash='#/collection?space=user2';routeToken++;base();poll(revision('d','e','f'));assert.equal(notice(),null);
          assert.equal(reloads,0);
        ''')
