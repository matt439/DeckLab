"""Library colour/archetype filters project only already-authorized shelf summaries."""
import unittest

from decklab.tests.test_library_ui import _Shelf
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class LibraryMetadataFiltersTests(_Shelf):
    def run_js(self, scenario):
        super().run_js(r'''
          const addresses=[],pushes=[];history.state={pos:9,existing:'kept'};
          history.replaceState=(value,unused,url)=>{assert.equal(value,history.state);addresses.push(url);if(url!==undefined)location.hash=url;};
          history.pushState=(...args)=>{pushes.push(args);}; // Opening the existing sheet owns its history entry.
          const change=(id,value)=>{const control=main.querySelector(id);control.value=value;control.fire('change');return control;};
          const filtered=(data,extra={})=>libVisibleDecks(data,{...libraryFilters(new URLSearchParams('all=1')),...extra}).map(d=>d.title);
        ''' + scenario)

    def test_colour_includes_every_selected_identity_colour_and_keeps_unknown_distinct(self):
        self.run_js(r'''
          assert(libMatchesColour({colors:['U','B']},'UB'));
          assert(libMatchesColour({colors:['U','B','R']},'UB'));
          assert(!libMatchesColour({colors:['U']},'UB'));
          assert(!libMatchesColour({colors:['B','R']},'UB'));
          assert(libMatchesColour({colors:[]},'C'));
          assert(!libMatchesColour({colors:[]},'unknown'));
          for(const colors of [null,undefined,['C'],['U','U'],['U',null],['UB'],'UB']){
            assert(!libMatchesColour({colors},'C'));assert(!libMatchesColour({colors},'U'));
            assert(libMatchesColour({colors},'unknown'));
          }
          assert(!libMatchesColour({colors:[],error:'Unreadable list'},'C'));
          assert(libMatchesColour({colors:[],error:'Unreadable list'},'unknown'));
          // A cover card's colour and viewed Play-now identity cannot override Planned summary colours.
          assert(!libMatchesColour({colors:['G'],cover:{colors:['U','B']},owned_colors:['U','B']},'UB'));
          assert(libMatchesColour({colors:null},''));
        ''')

    def test_all_colour_choices_and_literal_archetype_round_trip_in_bookmarks(self):
        self.run_js(r'''
          const choices=libColourChoices();assert.equal(choices.length,34);
          assert.equal(choices.find(([value])=>value==='UB')[1],'Includes blue + black');
          for(const [color] of choices){
            const hash=filtersHash({all:true,color,archetype:'  Aggro + [Blue] & 40%  ',q:'Elves',sort:'name',deck:'casual/a'});
            const round=libraryFilters(new URLSearchParams(hash.split('?')[1]));
            assert.equal(round.color,color);assert.equal(round.archetype,'aggro + [blue] & 40%');
            assert.equal(round.q,'Elves');assert.equal(round.sort,'name');assert.equal(round.deck,'casual/a');assert(round.all);
          }
          assert.equal(libraryFilters(new URLSearchParams('color=BU')).color,'UB');
          for(const color of ['UU','ub','CUB','WUQ','unknown-ish'])assert.equal(libraryFilters(new URLSearchParams({color})).color,'');
          assert(filtersHash({archetype:'A+B & [.*] #40%'}).includes('%26'));
          assert.equal(libFilterCount({color:'UB',archetype:'control',q:'a',sort:'name'}),2);
        ''')

    def test_archetypes_match_whole_normalized_headers_and_choices_use_only_loaded_summaries(self):
        self.run_js(r'''
          const data={decks:[deck('casual/a','A',{archetype:'  Blue   [.*] + Control '}),
            deck('casual/b','B',{archetype:'BLUE [.*] + CONTROL'}),
            deck('casual/c','C',{archetype:'Blue control'}),deck('casual/d','Blue [.*] + Control')]};
          same(filtered(data,{archetype:'blue [.*] + control'}),['A','B']);
          same(filtered(data,{archetype:'[.*]'}),[]);
          const choices=libArchetypeChoices(data,'unmatched & literal');
          assert.equal(choices.length,4);assert(choices.some(([value])=>value==='unmatched & literal'));
          assert.equal(libArchetypeQuery('\uFF23\uFF4F\uFF4E\uFF54\uFF52\uFF4F\uFF4C'),'control');
          assert.equal(libArchetypeChoices({decks:[]},'').length,1);
          assert(!choices.some(([value])=>value==='hidden archetype'));
        ''')

    def test_native_filters_retain_title_input_focus_and_existing_filter_state(self):
        self.run_js(r'''
          as('matt',MAY.admin);
          const data={...DATA,decks:[deck('casual/a','Elves',{colors:['U','B'],archetype:'Tempo',status:'built',...counts(0)}),
            deck('casual/b','Other Elves',{colors:['U'],archetype:'Control',status:'built',...counts(0)})]};
          const filters=libraryFilters(new URLSearchParams('q=Elves&status=built&readiness=ready&sort=name&deck=casual/a'));
          drawLibrary(data,filters);const title=main.querySelector('#library-title-search'),color=main.querySelector('#filter-color');
          color.focus();change('#filter-color','UB');same(titles(),['Elves']);
          assert.equal(main.querySelector('#filter-color'),color);assert.equal(document.activeElement,color);
          assert.equal(main.querySelector('#library-title-search'),title);assert.equal(title.value,'Elves');
          change('#filter-archetype','tempo');same(titles(),['Elves']);
          assert.equal(filters.q,'Elves');assert.equal(filters.status,'built');assert.equal(filters.readiness,'ready');
          assert.equal(filters.sort,'name');assert.equal(filters.deck,'casual/a');assert.equal(filters.all,false);
          assert.equal(main.querySelector('.lib-filter-button').textContent,'Filter (4)');
          assert.equal(color.tag,'select');assert.equal(color.parentNode.getAttribute('for'),'filter-color');
          assert.equal(color.parentNode.querySelector('span').textContent,'Colour identity');
          assert.equal(history.state.existing,'kept');assert.equal(state.libraryHash,location.hash);
          assert.equal(pushes.length,0);
        ''')

    def test_colour_archetype_and_title_combine_with_mine_status_readiness_and_products(self):
        self.run_js(r'''
          as('matt',MAY.admin);
          const data={...DATA,decks:[deck('casual/mine','Blue Elves',{colors:['U','B'],archetype:'Tempo',status:'built',...counts(0)}),
            deck('casual/theirs','Other Blue Elves',{colors:['U','B','R'],archetype:'Tempo',player:'wife',status:'built',...counts(0)}),
            deck('casual/wrong','Wrong Blue Elves',{colors:['U'],archetype:'Tempo',status:'built',...counts(0)}),
            deck('product/fixture/blue','Blue Elves (Fixture)',{colors:['U','B'],archetype:null,status:null,player:null,...counts(0)})]};
          const f={q:'blue elves',color:'UB',archetype:'tempo',format:'casual',status:'built',readiness:'ready'};
          same(filtered(data,{...f,all:false}),['Blue Elves']);same(filtered(data,f),['Blue Elves','Other Blue Elves']);
          drawLibrary(data,{...libraryFilters(new URLSearchParams()),...f});
          assert(main.textContent.includes('1 deck played only by someone else is hidden.'));
          assert.equal(libVisibleProducts(data,{color:'UB',q:'blue'}).length,1);
          assert.equal(libVisibleProducts(data,{color:'UB',archetype:'tempo'}).length,0);
          assert.equal(libVisibleProducts(data,{color:'UB',status:'built'}).length,0);
          as('user2',MAY.user2);assert.equal(libVisibleProducts(data,{color:'UB'}).length,0);
          assert.equal(libVisibleProducts(data,{color:'UB',all:true}).length,1);
        ''')

    def test_sheet_clear_resets_both_metadata_filters_and_preserves_title_sort_mine_and_selection(self):
        self.run_js(r'''
          as('matt',MAY.admin);const data={...DATA,decks:DATA.decks.map(d=>({...d,archetype:'Tempo'}))};
          const filters=libraryFilters(new URLSearchParams('q=Gruul&color=RG&archetype=tempo&sort=name&deck=casual/gruul'));
          drawLibrary(data,filters);main.querySelector('.lib-filter-button').click();const sheet=openDialog();
          assert(button(sheet,'Show 1 deck'));assert.equal(sheet.querySelector('#sheet-filter-color').value,'RG');
          assert.equal(sheet.querySelector('#sheet-filter-archetype').value,'tempo');
          button(sheet,'Clear filters').click();assert.equal(filters.color,'');assert.equal(filters.archetype,'');
          assert.equal(filters.q,'Gruul');assert.equal(filters.sort,'name');assert.equal(filters.all,false);assert.equal(filters.deck,'casual/gruul');
          assert.equal(main.querySelector('#library-title-search').value,'Gruul');assert(button(sheet,'Show 1 deck'));
          assert.equal(main.querySelector('.lib-filter-button').textContent,'Filter');assert(!button(sheet,'Clear filters'));
          assert.equal(document.activeElement,sheet.querySelector('select'));
        ''')

    def test_unmatched_bookmark_stays_represented_and_empty_recovery_clears_metadata(self):
        self.run_js(r'''
          as('matt',MAY.admin);const filters=libraryFilters(new URLSearchParams('all=1&color=WUBRG&archetype=literal%20%5B.*%5D&sort=name'));
          drawLibrary(DATA,filters);assert.equal(main.querySelector('#filter-color').value,'WUBRG');
          const archetype=main.querySelector('#filter-archetype');assert.equal(archetype.value,'literal [.*]');
          assert(archetype.children.some(option=>option.getAttribute('value')==='literal [.*]'));
          assert(main.querySelector('.empty').textContent.includes('No decks match these filters.'));
          main.querySelector('.empty').querySelector('a').fire('click');
          assert.equal(filters.color,'');assert.equal(filters.archetype,'');assert(filters.all);assert.equal(filters.sort,'name');
          assert.equal(titles().length,7);assert(!location.hash.includes('color=')&&!location.hash.includes('archetype='));
        ''')

    def test_metadata_matches_open_folded_groups_without_changing_remembered_preferences(self):
        self.run_js(r'''
          as('matt',MAY.admin);local.set('library.folded.user2','1');local.set(LIB_PRODUCTS_KEY,'0');
          const data={...DATA,decks:[deck('casual/home','Home',{colors:['U','B']}),
            deck('user2/casual/blue','Other',{space:'user2',player:null,colors:['U','B']}),
            deck('product/fixture/blue','Blue (Fixture)',{status:null,player:null,colors:['U','B']})]};
          drawLibrary(data,libraryFilters(new URLSearchParams('all=1&color=UB')));
          const person=main.querySelector('.space-person'),product=main.querySelector('.lib-products');
          assert(isOpen(person));assert(isOpen(product));person.open=false;person.fire('toggle');product.open=false;product.fire('toggle');
          assert.equal(local.get('library.folded.user2'),'1');assert.equal(local.get(LIB_PRODUCTS_KEY),'0');
          change('#filter-color','');assert(!isOpen(main.querySelector('.space-person')));assert(!isOpen(main.querySelector('.lib-products')));
        ''')

    def test_lab_selection_survives_filter_fallback_and_filters_add_no_api_reads(self):
        self.run_js(r'''
          as('matt',MAY.admin);window.matchMedia(LIB_LAB_QUERY).matches=true;const asked=[];
          api=async path=>{asked.push(path);if(path==='/api/library/forge')return {decks:{}};
            if(path==='/api/tables/stale')return {stale:[],blocked:[],held:[]};if(path.startsWith('/api/deck?'))return {sections:{}};throw Error(path);};
          const data={...DATA,decks:[deck('casual/red','Red',{colors:['R'],archetype:'Aggro'}),
            deck('casual/blue','Blue',{colors:['U','B'],archetype:'Control'})]};
          const filters=libraryFilters(new URLSearchParams('all=1&deck=casual/red'));drawLibrary(data,filters);await flush();
          const before=asked.length;change('#filter-color','UB');await flush();
          assert.equal(main.querySelector('.lib-detail').getAttribute('data-id'),'casual/blue');assert.equal(filters.deck,'casual/red');
          assert.equal(asked.length,before+1);change('#filter-archetype','control');await flush();assert.equal(asked.length,before+1);
          const color=main.querySelector('#filter-color'),archetype=main.querySelector('#filter-archetype'),title=main.querySelector('#library-title-search');
          const wide=window.matchMedia(LIB_LAB_QUERY);wide.matches=false;wide.fire('change');await flush();
          same(titles(),['Blue']);assert.equal(main.querySelector('.lib-detail'),null);
          wide.matches=true;wide.fire('change');await flush();assert.equal(main.querySelector('.lib-detail').getAttribute('data-id'),'casual/blue');
          assert.equal(main.querySelector('#filter-color'),color);assert.equal(main.querySelector('#filter-archetype'),archetype);
          assert.equal(main.querySelector('#library-title-search'),title);assert.equal(filters.color,'UB');assert.equal(filters.archetype,'control');
          assert.equal(asked.length,before+1);
          change('#filter-color','');change('#filter-archetype','');await flush();
          assert.equal(main.querySelector('.lib-detail').getAttribute('data-id'),'casual/red');assert.equal(asked.length,before+1);
          assert.equal(asked.filter(path=>path==='/api/library/forge').length,1);assert.equal(asked.filter(path=>path==='/api/tables/stale').length,1);
        ''')

    def test_retired_route_profile_or_connected_old_controls_cannot_change_filter_intent(self):
        self.run_js(r'''
          as('matt',MAY.admin);const filters=libraryFilters(new URLSearchParams('all=1'));drawLibrary(DATA,filters);
          const color=main.querySelector('#filter-color'),archetype=main.querySelector('#filter-archetype'),token=routeToken,profile=state.profile;
          routeToken++;color.value='U';color.fire('change');assert.equal(filters.color,'');assert.equal(addresses.length,0);routeToken=token;
          state.profile=PROFILES[1];archetype.value='control';archetype.fire('change');assert.equal(filters.archetype,'');assert.equal(addresses.length,0);state.profile=profile;
          const oldResults=main.querySelector('#library-results'),oldSearch=main.querySelector('.lib-title-search');clear(main);
          drawLibrary(DATA,libraryFilters(new URLSearchParams('all=1')));main.append(oldResults,oldSearch,color,archetype);
          color.value='R';color.fire('change');archetype.value='tempo';archetype.fire('change');
          assert.equal(filters.color,'');assert.equal(filters.archetype,'');assert.equal(addresses.length,0);
        ''')
