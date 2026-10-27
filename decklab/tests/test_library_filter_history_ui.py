"""Phone Library filters survive real-style sheet entries and asynchronous Back traversal."""
import unittest

from decklab.tests.test_library_ui import _Shelf
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class LibraryFilterHistoryTests(_Shelf):
    def run_js(self, scenario):
        super().run_js(r'''
          as('matt',MAY.admin);location.hash='#/library?all=1&sort=name';
          const entries=[{hash:location.hash,state:{pos:0,existing:'kept'}}],traversals=[];let at=0,reroutes=0;
          history.state=entries[0].state;history.length=1;
          history.replaceState=(value,unused,url)=>{history.state=value;entries[at]={state:value,hash:url===undefined?location.hash:url};location.hash=entries[at].hash;};
          history.pushState=(value,unused,url)=>{entries.splice(at+1);entries.push({state:value,hash:url===undefined?location.hash:url});at++;
            history.length=entries.length;history.state=value;location.hash=entries[at].hash;};
          history.back=()=>traversals.push(()=>{
            if(at===0)return;const old=location.hash;at--;const target=entries[at].hash,changed=old!==target;
            history.state=entries[at].state;location.hash=target;window.fire('popstate',{state:history.state});
            // Native traversal decides whether hashchange is needed from its old and target URLs,
            // before a popstate listener can replaceState to retain the chosen filters.
            if(changed)window.fire('hashchange',{oldURL:'http://localhost/'+old,newURL:'http://localhost/'+target});
          });
          route=()=>{reroutes++;};
          const land=()=>{const next=traversals.shift();assert(next,'Expected an asynchronous Back');next();};
          const data={...DATA,decks:[deck('casual/a','Blue Elves',{colors:['U','B'],archetype:'Tempo'}),
            deck('casual/b','Red Elves',{colors:['R'],archetype:'Aggro'})]};
          const filters=libraryFilters(new URLSearchParams(location.hash.split('?')[1]));drawLibrary(data,filters);
          const origin=location.hash,input=main.querySelector('#library-title-search');
          const openFilters=()=>{main.querySelector('.lib-filter-button').click();return openDialog();};
          const choose=(sheet,key,value)=>{const select=sheet.querySelector('#sheet-filter-'+key);select.value=value;select.fire('change');};
          const closeFilters=sheet=>sheet.querySelector('.sheet-close').click();
        ''' + scenario)

    def test_show_commits_only_after_back_lands_without_reloading_or_losing_filter_results(self):
        self.run_js(r'''
          const sheet=openFilters();assert(history.state.sheet);choose(sheet,'color','UB');
          same(titles(),['Blue Elves']);assert.equal(location.hash,origin);assert.equal(state.libraryHash,origin);
          button(sheet,'Show 1 deck').click();assert.equal(location.hash,origin);flushTimers();
          assert(history.state.sheet);assert.equal(traversals.length,1);assert.equal(location.hash,origin);
          land();assert(!history.state.sheet);assert(location.hash.includes('color=UB'));
          assert.equal(state.libraryHash,location.hash);assert.equal(history.state.existing,'kept');
          same(titles(),['Blue Elves']);assert.equal(main.querySelector('#library-title-search'),input);assert.equal(reroutes,0);
        ''')

    def test_native_browser_back_closes_sheet_and_commits_current_choices_after_landing(self):
        self.run_js(r'''
          const sheet=openFilters();choose(sheet,'color','UB');choose(sheet,'archetype','tempo');
          history.back();land();assert(!openDialog());assert(!history.state.sheet);
          assert(location.hash.includes('color=UB'));assert(location.hash.includes('archetype=tempo'));
          same(titles(),['Blue Elves']);assert.equal(reroutes,0);flushTimers();assert.equal(traversals.length,0);
        ''')

    def test_header_close_and_clear_filters_keep_original_query_until_the_history_entry_lands(self):
        self.run_js(r'''
          const first=openFilters();choose(first,'color','UB');closeFilters(first);flushTimers();land();
          const committed=location.hash;assert(committed.includes('color=UB'));
          const second=openFilters();button(second,'Clear filters').click();same(titles(),['Blue Elves','Red Elves']);
          assert.equal(location.hash,committed);closeFilters(second);flushTimers();land();
          assert(!location.hash.includes('color='));assert.equal(filters.sort,'name');assert(filters.all);assert.equal(reroutes,0);
        ''')

    def test_typing_after_explicit_close_before_back_lands_joins_the_same_final_query(self):
        self.run_js(r'''
          const sheet=openFilters();choose(sheet,'color','UB');closeFilters(sheet);
          input.value='Blue';input.fire('input');assert.equal(location.hash,origin);same(titles(),['Blue Elves']);
          flushTimers();land();const query=new URLSearchParams(location.hash.split('?')[1]);
          assert.equal(query.get('color'),'UB');assert.equal(query.get('q'),'Blue');assert.equal(reroutes,0);
        ''')

    def test_late_close_or_back_cannot_overwrite_a_different_profile_route_or_library_owner(self):
        self.run_js(r'''
          const sheet=openFilters();choose(sheet,'color','UB');closeFilters(sheet);flushTimers();
          state.profile={...state.profile,id:'user1'};routeToken++;
          clear(main);drawLibrary(data,libraryFilters(new URLSearchParams('all=1')));const fresh=main.querySelector('#library-title-search');
          land();assert.equal(location.hash,origin);assert.equal(main.querySelector('#library-title-search'),fresh);
          assert(!location.hash.includes('color='));assert.equal(reroutes,0);
        ''')

    def test_navigation_while_close_is_pending_does_not_commit_to_or_step_back_from_the_new_page(self):
        self.run_js(r'''
          const sheet=openFilters();choose(sheet,'color','UB');closeFilters(sheet);
          const next='#/settings';history.pushState({pos:2},'',next);routeToken++;
          window.fire('hashchange',{oldURL:'http://localhost/'+origin,newURL:'http://localhost/'+next});
          clear(main);main.append(el('p',{text:'New page'}));flushTimers();assert.equal(traversals.length,0);
          assert.equal(location.hash,next);assert.equal(main.textContent,'New page');assert(!location.hash.includes('color='));
        ''')

    def test_an_unexpected_history_destination_does_not_receive_the_previous_sheet_filters(self):
        self.run_js(r'''
          const sheet=openFilters();choose(sheet,'color','UB');closeFilters(sheet);flushTimers();
          entries[0]={hash:'#/library?all=1&q=Other',state:{pos:0}};land();
          assert.equal(location.hash,'#/library?all=1&q=Other');assert.equal(reroutes,1);assert(!location.hash.includes('color='));
        ''')

    def test_matching_address_at_a_different_history_position_cannot_receive_staged_filters(self):
        self.run_js(r'''
          const sheet=openFilters();choose(sheet,'color','UB');closeFilters(sheet);flushTimers();
          entries[0].state={pos:12};land();assert.equal(location.hash,origin);assert(!location.hash.includes('color='));
          assert.equal(history.state.pos,12);assert.equal(reroutes,0);
        ''')

    def test_reused_closed_sheet_entry_still_commits_to_its_underlying_page(self):
        self.run_js(r'''
          const prior=openSheet('Prior sheet');prior.close();const sheet=openFilters();
          choose(sheet,'color','UB');flushTimers();assert.equal(traversals.length,0);
          closeFilters(sheet);flushTimers();land();assert(location.hash.includes('color=UB'));
          assert(!history.state.sheet);assert.equal(history.state.pos,0);assert.equal(reroutes,0);
        ''')

    def test_a_sheet_without_history_commits_directly_on_close(self):
        self.run_js(r'''
          history.pushState=undefined;const sheet=openFilters();choose(sheet,'color','UB');
          assert.equal(location.hash,origin);closeFilters(sheet);assert(location.hash.includes('color=UB'));
          flushTimers();assert.equal(traversals.length,0);assert.equal(reroutes,0);
        ''')
