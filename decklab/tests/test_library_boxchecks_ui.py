"""Historical box-check filters use only already-loaded, authorized Library summaries."""
import unittest

from decklab.tests.test_library_ui import _Shelf
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class LibraryBoxChecksUiTests(_Shelf):
    def run_js(self, scenario):
        super().run_js(r'''
          as('matt',MAY.admin);location.hash='#/library?all=1';
          libLoadForge=()=>{};libTablesPanel=()=>null;libGlance=()=>({facts:null,cards:null});
          const checked=(id,title,date,extra={})=>deck(id,title,{status:'built',box_check:{checked_on:date},...counts(0),...extra});
          const data={...DATA,decks:[checked('casual/early','Early','2026-01-10',{colors:['U','B'],archetype:'Tempo'}),
            checked('casual/on','On cutoff','2026-02-01'),checked('casual/recent','Recent','2026-03-01'),checked('casual/never','Unrecorded',null),
            deck('casual/old-api','No metadata',{status:'built'}),checked('casual/bad','Malformed','2026-02-30'),
            checked('casual/building','Building',null,{status:'building'}),checked('product/fixture/blue','Product',null,{read_only:true}),
            checked('user2/casual/member','Member',null,{space:'user2',player:null}),checked('casual/error','Unreadable',null,{error:'Unreadable source'})]};
          const chosen=(extra={})=>({...libraryFilters(new URLSearchParams('all=1')), ...extra});
          const visible=(filters,source=data)=>libVisibleDecks(source,filters).map(item=>item.title);
          history.replaceState=(value,unused,url)=>{if(url!==undefined)location.hash=url;};
          const change=(id,value,event='change')=>{const control=main.querySelector(id);control.value=value;control.fire(event);return control;};
        ''' + scenario)

    def test_any_keeps_existing_decks_and_products_without_reclassifying_missing_metadata(self):
        self.run_js(r'''
          assert.equal(visible(chosen()).length,9);assert.equal(libVisibleProducts(data,chosen()).length,1);
          assert(libMatchesBoxCheck({box_check:{checked_on:'bad'}},{}));assert.equal(libBoxCheckRecord(data.decks[4]),null);
          assert.equal(libBoxCheckRecord(data.decks[5]),null);assert(libBoxCheckRecord(data.decks[3]));
        ''')

    def test_explicit_null_is_unrecorded_while_omitted_malformed_and_outside_scope_are_excluded(self):
        self.run_js(r'''
          same(visible(chosen({box_check:'unrecorded'})),['Unrecorded']);assert.equal(libVisibleProducts(data,chosen({box_check:'unrecorded'})).length,0);
          for(const record of [undefined,null,{},[],{checked_on:undefined},{checked_on:'bad'},{checked_on:'2026-02-30'}]){
            const item=checked('casual/fixture','Fixture',null,{box_check:record});assert(!libMatchesBoxCheck(item,{box_check:'unrecorded'}));
          }
        ''')

    def test_checked_before_is_strict_and_never_includes_unrecorded_dates(self):
        self.run_js(r'''
          same(visible(chosen({box_check:'before',checked_before:'2026-02-01'})),['Early']);
          same(visible(chosen({box_check:'before',checked_before:'2026-01-10'})),[]);
          same(visible(chosen({box_check:'before',checked_before:'2026-03-02'})),['Early','On cutoff','Recent']);
          assert.equal(libBoxDate('2024-02-29'),'2024-02-29');for(const date of ['2026-02-29','2026-02-30','2026-1-01','2026-01-01T00:00:00Z','0000-01-01'])assert.equal(libBoxDate(date),null);
        ''')

    def test_bookmark_round_trip_preserves_other_filters_and_counts_date_pair_once(self):
        self.run_js(r'''
          const original=chosen({box_check:'before',checked_before:'2026-02-01',q:'Early',color:'UB',archetype:'tempo',status:'built',
            readiness:'ready',format:'casual',sort:'name',deck:'casual/early'}),hash=filtersHash(original),round=libraryFilters(new URLSearchParams(hash.split('?')[1]));
          for(const key of ['box_check','checked_before','q','color','archetype','status','readiness','format','sort','deck'])assert.equal(round[key],original[key],key);
          assert.equal(libFilterCount(round),6);assert(hash.includes('box_check=before'));assert(hash.includes('checked_before=2026-02-01'));
          assert.equal(libFilterCount({box_check:'before',checked_before:'2026-02-01'}),1);assert.equal(libFilterCount({checked_before:'2026-02-01'}),0);
        ''')

    def test_invalid_cutoff_bookmark_retains_mode_for_guidance_without_defaulting_date(self):
        self.run_js(r'''
          for(const raw of ['','bad','2026-02-30','2026-2-01']){
            const filters=libraryFilters(new URLSearchParams({all:'1',box_check:'before',checked_before:raw}));assert.equal(filters.box_check,'before');assert.equal(filters.checked_before,'');
            assert(filtersHash(filters).includes('box_check=before'));assert(!filtersHash(filters).includes('checked_before='));assert(libBoxCheckIssue(data,filters).blocking);
          }
          assert.equal(libraryFilters(new URLSearchParams('box_check=unknown&checked_before=2026-02-01')).box_check,'');
        ''')

    def test_blank_before_mode_shows_choose_date_guidance_instead_of_zero_due_results(self):
        self.run_js(r'''
          const filters=chosen({box_check:'before'});drawLibrary(data,filters);const input=main.querySelector('#filter-checked-before');
          assert.equal(input.getAttribute('type'),'date');assert.equal(input.value,'');assert(!input.disabled);
          assert(main.textContent.includes('Choose a date'));assert(!main.textContent.includes('No decks match these filters'));
          assert(!main.textContent.includes('Showing 0'));assert(!main.textContent.includes('0 due'));assert.equal(titles().length,0);
        ''')

    def test_older_api_reply_is_not_all_unrecorded_and_reports_missing_metadata(self):
        self.run_js(r'''
          const older={...DATA,decks:[deck('casual/a','Old reply',{status:'built'})]},filters=chosen({box_check:'unrecorded'});
          drawLibrary(older,filters);assert.equal(titles().length,0);assert(main.textContent.includes("Check dates aren't available for these decks"));
          assert(main.textContent.includes('Reload the Library or clear this filter'));assert(!main.textContent.includes('No decks match these filters'));
        ''')

    def test_partial_metadata_filters_only_reliable_records_and_explains_exclusions(self):
        self.run_js(r'''
          const filters=chosen({box_check:'unrecorded'});drawLibrary(data,filters);same(titles(),['Unrecorded']);
          assert(main.textContent.includes('Decks without check-date information are excluded'));
          assert(main.textContent.includes('Box check filters apply to built home decks'));assert(!main.textContent.includes('No metadata (unrecorded)'));
        ''')

    def test_metadata_is_read_access_not_edit_permission_and_combines_with_mine(self):
        self.run_js(r'''
          as('user1',MAY.user1);const readonly=checked('casual/owned-by-other','Read-only home','2026-01-01',{read_only:true,player:'user'});
          assert(libBoxCheckRecord(readonly));assert(libMatchesBoxCheck(readonly,{box_check:'before',checked_before:'2026-02-01'}));
          const source={...DATA,decks:[readonly,checked('casual/mine','Mine','2026-01-01',{player:'wife'})]};
          same(visible(chosen({all:false,box_check:'before',checked_before:'2026-02-01'}),source),['Mine']);
          same(visible(chosen({all:true,box_check:'before',checked_before:'2026-02-01'}),source),['Read-only home','Mine']);
        ''')

    def test_unauthorized_or_member_library_has_no_controls_and_bookmark_fails_honestly(self):
        self.run_js(r'''
          for(const who of ['member','no-home-records']){
            if(who==='member')as('user2',MAY.user2);else{as('matt',MAY.admin);state.may={...MAY.admin,see_home_records:false};}
            clear(main);drawLibrary(data,chosen({box_check:'unrecorded'}));assert(!main.querySelector('#filter-box_check'));
            assert(!main.querySelector('#filter-checked-before'));assert(!libBoxCheckRecord(data.decks[3]));assert.equal(titles().length,0);
            assert(main.textContent.includes("Check dates aren't available in this Library"));
          }
        ''')

    def test_native_date_changes_retain_control_focus_title_and_all_other_filters(self):
        self.run_js(r'''
          const filters=chosen({q:'Early',color:'UB',archetype:'tempo',format:'casual',status:'built',readiness:'ready',sort:'name',deck:'casual/early'});
          drawLibrary(data,filters);const title=main.querySelector('#library-title-search');change('#filter-box_check','before');const date=main.querySelector('#filter-checked-before');
          date.focus();change('#filter-checked-before','2026-02-01','input');same(titles(),['Early']);assert.equal(document.activeElement,date);
          assert.equal(main.querySelector('#filter-checked-before'),date);assert.equal(main.querySelector('#library-title-search'),title);assert.equal(title.value,'Early');
          assert.equal(filters.color,'UB');assert.equal(filters.archetype,'tempo');assert.equal(filters.status,'built');assert.equal(filters.sort,'name');assert.equal(filters.deck,'casual/early');
        ''')

    def test_any_and_unrecorded_modes_clear_hidden_cutoff_and_before_begins_blank(self):
        self.run_js(r'''
          const filters=chosen({box_check:'before',checked_before:'2026-02-01'});drawLibrary(data,filters);change('#filter-box_check','unrecorded');
          assert.equal(filters.checked_before,'');assert(main.querySelector('#filter-checked-before').disabled);assert(!location.hash.includes('checked_before='));
          change('#filter-box_check','before');assert.equal(main.querySelector('#filter-checked-before').value,'');assert(main.textContent.includes('Choose a date'));
          change('#filter-box_check','');assert.equal(filters.box_check,'');assert(!location.hash.includes('box_check='));
        ''')

    def test_phone_clear_resets_check_pair_but_keeps_title_sort_selection_and_mine(self):
        self.run_js(r'''
          const filters=chosen({all:false,q:'Early',box_check:'before',checked_before:'2026-02-01',sort:'name',deck:'casual/early'});drawLibrary(data,filters);
          main.querySelector('.lib-filter-button').click();const sheet=openDialog();button(sheet,'Clear filters').click();
          assert.equal(filters.box_check,'');assert.equal(filters.checked_before,'');assert.equal(filters.q,'Early');assert.equal(filters.sort,'name');
          assert.equal(filters.deck,'casual/early');assert.equal(filters.all,false);assert.equal(main.querySelector('.lib-filter-button').textContent,'Filter');
          assert.equal(sheet.querySelector('#sheet-filter-checked-before').value,'');assert(sheet.querySelector('#sheet-filter-checked-before').disabled);
        ''')

    def test_empty_recovery_clears_check_pair_and_preserves_existing_sort_and_selection_intent(self):
        self.run_js(r'''
          const filters=chosen({box_check:'before',checked_before:'1900-01-01',sort:'name',deck:'casual/early'});drawLibrary(data,filters);
          main.querySelector('.empty').querySelector('a').fire('click');assert.equal(filters.box_check,'');assert.equal(filters.checked_before,'');
          assert.equal(filters.sort,'name');assert.equal(filters.deck,'casual/early');assert(!location.hash.includes('box_check='));assert(titles().length>1);
        ''')

    def test_selected_note_is_historical_and_selection_fallback_does_not_replace_url_intent(self):
        self.run_js(r'''
          window.matchMedia(LIB_LAB_QUERY).matches=true;const filters=chosen({box_check:'before',checked_before:'2026-02-01',deck:'casual/recent'});drawLibrary(data,filters);
          assert.equal(main.querySelector('.lib-detail').getAttribute('data-id'),'casual/early');assert.equal(filters.deck,'casual/recent');
          const note=main.querySelector('.lib-box-check-date');assert(note.textContent.includes('Last box check recorded: 2026-01-10'));
          assert(note.textContent.includes('Contents may have changed since'));assert.equal(note.querySelector('time').getAttribute('datetime'),'2026-01-10');
          change('#filter-box_check','unrecorded');assert(main.querySelector('.lib-box-check-date').textContent.includes('No box check date is recorded'));
        ''')

    def test_stale_date_events_roll_back_without_rewriting_new_profile_route_or_controls(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','detached']){
            as('matt',MAY.admin);clear(main);location.hash='#/library?all=1';const filters=chosen({box_check:'before',checked_before:'2026-02-01'});drawLibrary(data,filters);
            const date=main.querySelector('#filter-checked-before');if(mode==='profile')state.profile={...state.profile,id:'user1'};if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/settings';if(mode==='detached')date.remove();
            const prior=location.hash;date.value='2026-03-01';date.fire('input');assert.equal(date.value,'2026-02-01');assert.equal(filters.checked_before,'2026-02-01');assert.equal(location.hash,prior);
          }
        ''')

    def test_filters_add_no_reads_or_writes_and_leave_summary_metadata_unchanged(self):
        self.run_js(r'''
          let reads=0,writes=0;api=async()=>{reads++;};apiWrite=async()=>{writes++;};const before=JSON.stringify(data),filters=chosen();drawLibrary(data,filters);
          change('#filter-box_check','unrecorded');change('#filter-box_check','before');change('#filter-checked-before','2026-02-01','input');
          assert.equal(reads,0);assert.equal(writes,0);assert.equal(JSON.stringify(data),before);
        ''')
