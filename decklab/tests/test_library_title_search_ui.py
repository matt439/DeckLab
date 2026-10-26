"""Library title search keeps native input and URL intent within the authorized shelf data."""
import unittest

from decklab.tests.test_library_ui import _Shelf
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, 'Node.js is not installed')
class LibraryTitleSearchTests(_Shelf):
    def run_js(self, scenario):
        super().run_js(r'''
          const addresses=[],states=[];let pushes=0;
          history.state={pos:7,existing:'kept'};
          history.replaceState=(value,unused,url)=>{states.push(value);addresses.push(url);if(url!==undefined)location.hash=url;};
          history.pushState=()=>{pushes++;};
          const search=()=>main.querySelector('#library-title-search');
          const typeTitle=(value,props={})=>{const input=search();input.value=value;input.fire('input',props);return input;};
          const clearTitle=()=>main.querySelector('.lib-title-clear');
        ''' + scenario)

    def test_query_round_trip_escapes_literal_text_and_matches_only_titles(self):
        self.run_js(r'''
          const q='  Matt\'s "A+B" & [.*] #40%  ',filters=libraryFilters(new URLSearchParams({all:'1',q,sort:'name',deck:'casual/gruul'}));
          assert.equal(filters.q,q.trim());const hash=filtersHash(filters),round=libraryFilters(new URLSearchParams(hash.split('?')[1]));
          assert.equal(round.q,q.trim());assert.equal(round.deck,'casual/gruul');assert.equal(round.sort,'name');
          assert(hash.includes('%26')&&hash.includes('%23')&&hash.includes('%25'));
          assert(libMatchesTitle({title:'Matt\'s "A+B" & [.*] #40%'},filters));
          assert(libMatchesTitle({title:'Blue [.*] control'},{q:'[.*]'}));assert(!libMatchesTitle({title:'Blue control'},{q:'[.*]'}));
          assert(libMatchesTitle({title:'ÉLVES — Fullwidth ＢＬＵＥ'},{q:'élves'}));
          assert(libMatchesTitle({title:'ÉLVES — Fullwidth ＢＬＵＥ'},{q:'blue'}));
          assert(libMatchesTitle({title:'Gruul'},{q:'   '}));assert(!filtersHash({q:' \t '}).includes('q='));
          assert(!libMatchesTitle({id:'casual/secret',title:'Gruul',cover:{name:'Secret card'},archetype:'Secret'},{q:'secret'}));
        ''')

    def test_raw_multiword_typing_retains_input_caret_and_replaces_current_history(self):
        self.run_js(r'''
          as('matt',MAY.admin);
          const data={...DATA,decks:[deck('casual/mystic','Elvish Mystic Deck'),deck('casual/archers','Elvish Archers')]};
          const filters=libraryFilters(new URLSearchParams('all=1&sort=name'));drawLibrary(data,filters);
          const input=search(),root=main.querySelector('.lib-title-search');input.focus();input.selectionStart=7;input.selectionEnd=7;
          typeTitle('Elvish ');assert.equal(input.value,'Elvish ');assert.equal(filters.q,'Elvish ');
          input.value+='Mystic';input.fire('input');same(titles(),['Elvish Mystic Deck']);
          assert.equal(search(),input);assert.equal(main.querySelector('.lib-title-search'),root);assert.equal(document.activeElement,input);
          assert.equal(input.selectionStart,7);assert.equal(input.selectionEnd,7);
          assert.equal(new URLSearchParams(location.hash.split('?')[1]).get('q'),'Elvish Mystic');
          assert(states.every(value=>value===history.state));assert.equal(history.state.existing,'kept');assert.equal(history.state.pos,7);
          assert.equal(pushes,0);assert.equal(state.libraryHash,location.hash);
          const before=addresses.length;input.fire('search');assert.equal(addresses.length,before);
          clearTitle().click();assert.equal(input.value,'');assert.equal(filters.q,'');assert.equal(document.activeElement,input);
          assert(!location.hash.includes('q='));assert.equal(filters.all,true);assert.equal(filters.sort,'name');same(titles(),['Elvish Archers','Elvish Mystic Deck']);
        ''')

    def test_title_combines_with_mine_format_status_and_availability_for_every_group(self):
        self.run_js(r'''
          as('matt',MAY.admin);
          const match=extra=>libVisibleDecks(DATA,{...libraryFilters(new URLSearchParams()),...extra}).map(d=>d.title);
          same(match({q:'GRUUL',status:'built',format:'casual',readiness:'ready'}),['Gruul']);
          same(match({q:'gruul',status:'idea'}),[]);same(match({q:'giada'}),[]);same(match({q:'giada',all:true}),['Giada']);
          drawLibrary(DATA,libraryFilters(new URLSearchParams('q=otters')));
          assert(!main.textContent.includes('played only by someone else'));
          clear(main);drawLibrary(DATA,libraryFilters(new URLSearchParams('q=giada')));
          assert(main.textContent.includes('1 deck played only by someone else is hidden.'));
          assert.equal(libVisibleProducts(DATA,{q:'foundations'}).length,2);
          assert.equal(libVisibleProducts(DATA,{q:'foundations',status:'built'}).length,0);
          assert.equal(libVisibleProducts(DATA,{q:'foundations',format:'commander'}).length,0);
          as('user2',MAY.user2);assert.equal(libVisibleProducts(DATA,{q:'cats'}).length,0);
          assert.equal(libVisibleProducts(DATA,{q:'cats',all:true}).length,1);
        ''')

    def test_matching_folded_person_and_products_open_temporarily_without_changing_pairing_choices(self):
        self.run_js(r'''
          as('matt',MAY.admin);local.set('library.folded.user2','1');local.set(LIB_PRODUCTS_KEY,'0');
          const theirs=deck('user2/casual/flame','Blue Flame',{space:'user2',player:null});
          const home=deck('casual/flame','Home Flame');
          const product={...DECKS[5],title:'Flame (Foundations Beginner Box)'};
          const halves=[{id:'a'},{id:'b'}];let offered;pairingPicker=value=>{offered=value;return el('div');};
          const data={...DATA,decks:[home,theirs,product],halves};drawLibrary(data,libraryFilters(new URLSearchParams('all=1&q=flame')));
          let person=main.querySelector('.space-person'),products=main.querySelector('.lib-products');
          assert(isOpen(person));assert(isOpen(products));assert.equal(offered,halves);
          person.open=false;person.fire('toggle');products.open=false;products.fire('toggle');
          assert.equal(local.get('library.folded.user2'),'1');assert.equal(local.get(LIB_PRODUCTS_KEY),'0');
          clearTitle().click();person=main.querySelector('.space-person');products=main.querySelector('.lib-products');
          assert(!isOpen(person));assert(!isOpen(products));
        ''')

    def test_lab_detail_uses_matching_selection_and_clear_restores_prior_deck(self):
        self.run_js(r'''
          as('matt',MAY.admin);window.matchMedia(LIB_LAB_QUERY).matches=true;
          const asked=[];api=async path=>{asked.push(path);if(path==='/api/library/forge')return {decks:{}};
            if(path==='/api/tables/stale')return {stale:[],blocked:[],held:[]};if(path.startsWith('/api/deck?'))return {sections:{}};throw Error(path);};
          const filters=libraryFilters(new URLSearchParams('all=1&deck=casual/gruul'));drawLibrary(DATA,filters);await flush();
          const initial=asked.length,input=typeTitle('Ott');await flush();
          assert.equal(main.querySelector('.lib-detail').getAttribute('data-id'),'casual/otters');
          same(main.querySelectorAll('.deck-row').map(row=>row.getAttribute('data-id')),['casual/otters']);assert.equal(filters.deck,'casual/gruul');
          assert.equal(asked.length,initial+1);assert(asked.at(-1).startsWith('/api/deck?id=casual%2Fotters&'));
          const readCount=asked.length;typeTitle('Otters');await flush();assert.equal(asked.length,readCount);
          typeTitle('No matching title');await flush();assert.equal(main.querySelector('.lib-detail'),null);assert.equal(asked.length,readCount);
          clearTitle().click();await flush();assert.equal(search(),input);assert.equal(main.querySelector('.lib-detail').getAttribute('data-id'),'casual/gruul');
          assert.equal(asked.length,readCount);assert.equal(asked.filter(path=>path==='/api/library/forge').length,1);
          assert.equal(asked.filter(path=>path==='/api/tables/stale').length,1);assert.equal(pushes,0);
        ''')

    def test_empty_recovery_clears_query_and_select_filters_but_preserves_sort(self):
        self.run_js(r'''
          as('matt',MAY.admin);const filters=libraryFilters(new URLSearchParams('all=1&q=No-match&sort=name&status=built'));
          drawLibrary(DATA,filters);assert(main.querySelector('.empty').textContent.includes('No decks match these filters.'));
          const link=main.querySelector('.empty').querySelector('a');const old=search();const event=link.fire('click');
          assert(event.defaultPrevented);assert.equal(filters.q,'');assert.equal(filters.status,'');assert(filters.all);assert.equal(filters.sort,'name');
          assert.equal(search().value,'');assert(search()!==old);assert.equal(titles().length,7);assert(!location.hash.includes('q='));
          typeTitle('   ');assert.equal(titles().length,7);assert(!location.hash.includes('q='));
        ''')

    def test_phone_sheet_count_includes_matching_products_and_clear_filters_preserves_title(self):
        self.run_js(r'''
          as('matt',MAY.admin);drawLibrary(DATA,libraryFilters(new URLSearchParams('all=1&q=cats&format=product')));
          main.querySelector('.lib-filter-button').click();let sheet=openDialog();assert(button(sheet,'Show 1 deck'));
          button(sheet,'Clear filters').click();assert.equal(search().value,'cats');assert.equal(titles().length,1);
          assert(button(sheet,'Show 1 deck'));assert.equal(main.querySelector('.lib-filter-button').textContent,'Filter');
          assert(!button(sheet,'Clear filters'));
        ''')

    def test_empty_recovery_cannot_reset_a_retired_route_profile_or_connected_old_root(self):
        self.run_js(r'''
          as('matt',MAY.admin);drawLibrary(DATA,libraryFilters(new URLSearchParams('all=1&q=No-match')));
          const link=main.querySelector('.empty').querySelector('a'),input=search();
          const token=routeToken;routeToken++;link.fire('click');assert.equal(addresses.length,0);assert.equal(search(),input);routeToken=token;
          const profile=state.profile;state.profile=PROFILES[1];link.fire('click');assert.equal(addresses.length,0);state.profile=profile;
          const oldResults=main.querySelector('#library-results');clear(main);
          drawLibrary(DATA,libraryFilters(new URLSearchParams('all=1&q=otters')));main.append(oldResults);
          const current=search();link.fire('click');assert.equal(search(),current);assert.equal(current.value,'otters');assert.equal(addresses.length,0);
        ''')

    def test_composition_commits_once_and_retired_profile_route_or_root_controls_cannot_change_url(self):
        self.run_js(r'''
          as('matt',MAY.admin);drawLibrary(DATA,libraryFilters(new URLSearchParams('all=1')));
          const input=search();input.focus();const initial=titles().length;
          input.fire('compositionstart');typeTitle('Gia',{isComposing:true});input.fire('search');
          assert.equal(addresses.length,0);assert.equal(titles().length,initial);
          input.value='Giada';input.fire('compositionend');assert.equal(addresses.length,1);same(titles(),['Giada']);
          input.fire('input');assert.equal(addresses.length,1);
          const token=routeToken;routeToken++;typeTitle('Gruul');clearTitle().click();assert.equal(addresses.length,1);routeToken=token;
          const profile=state.profile;state.profile=PROFILES[1];typeTitle('Gruul');assert.equal(addresses.length,1);state.profile=profile;
          const oldRoot=main.querySelector('.lib-title-search'),oldResults=main.querySelector('#library-results');
          clear(main);drawLibrary(DATA,libraryFilters(new URLSearchParams('all=1')));main.append(oldRoot,oldResults);
          input.value='Otters';input.fire('input');oldRoot.querySelector('.lib-title-clear').click();assert.equal(addresses.length,1);
        ''')
