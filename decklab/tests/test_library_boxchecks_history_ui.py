"""Check-date controls preserve the Library's asynchronous filter-sheet history contract."""
import unittest

from decklab.tests import test_library_filter_history_ui as history_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class LibraryBoxChecksHistoryTests(unittest.TestCase):
    def run_js(self, scenario):
        history_ui.LibraryFilterHistoryTests().run_js(r'''
          data.decks[0].status='built';data.decks[0].box_check={checked_on:'2026-01-01'};
          data.decks[1].status='built';data.decks[1].box_check={checked_on:null};
          const dateInput=sheet=>sheet.querySelector('#sheet-filter-checked-before');
        ''' + scenario)

    def test_date_blur_does_not_replace_first_show_click_and_query_commits_after_back(self):
        self.run_js(r'''
          const sheet=openFilters();choose(sheet,'box_check','before');const date=dateInput(sheet);assert.equal(date.value,'');assert(button(sheet,'Close filters'));
          date.focus();date.value='2026-02-01';date.fire('input');const show=button(sheet,'Show 1 deck');assert(show);date.fire('change');
          assert.equal(button(sheet,'Show 1 deck'),show);assert.equal(dateInput(sheet),date);show.click();assert.equal(location.hash,origin);flushTimers();land();
          assert(location.hash.includes('box_check=before'));assert(location.hash.includes('checked_before=2026-02-01'));same(titles(),['Blue Elves']);assert.equal(reroutes,0);
        ''')

    def test_partial_native_date_value_stays_on_same_control_without_footer_replacement(self):
        self.run_js(r'''
          const sheet=openFilters();choose(sheet,'box_check','before');const date=dateInput(sheet),close=button(sheet,'Close filters');
          date.focus();date.value='';date.fire('input');date.fire('change');assert.equal(dateInput(sheet),date);assert.equal(button(sheet,'Close filters'),close);
          assert.equal(document.activeElement,date);assert.equal(filters.checked_before,'');assert(sheet.textContent.includes('Choose a date'));assert.equal(location.hash,origin);
        ''')

    def test_native_back_preserves_unrecorded_mode_without_a_cutoff_or_new_read(self):
        self.run_js(r'''
          const sheet=openFilters();choose(sheet,'box_check','unrecorded');same(titles(),['Red Elves']);history.back();land();
          assert(!openDialog());assert(location.hash.includes('box_check=unrecorded'));assert(!location.hash.includes('checked_before='));assert.equal(reroutes,0);
        ''')

    def test_header_close_and_clear_keep_origin_until_landing_then_remove_both_keys(self):
        self.run_js(r'''
          let sheet=openFilters();choose(sheet,'box_check','before');choose(sheet,'checked-before','2026-02-01');closeFilters(sheet);flushTimers();land();
          const committed=location.hash;assert(committed.includes('checked_before='));sheet=openFilters();button(sheet,'Clear filters').click();
          assert.equal(location.hash,committed);assert.equal(dateInput(sheet).value,'');closeFilters(sheet);flushTimers();land();
          assert(!location.hash.includes('box_check='));assert(!location.hash.includes('checked_before='));assert.equal(filters.sort,'name');assert(filters.all);assert.equal(reroutes,0);
        ''')

    def test_late_close_cannot_commit_check_date_into_a_new_library_owner(self):
        self.run_js(r'''
          const sheet=openFilters();choose(sheet,'box_check','before');choose(sheet,'checked-before','2026-02-01');closeFilters(sheet);flushTimers();
          state.profile={...state.profile,id:'user1'};routeToken++;clear(main);drawLibrary(data,libraryFilters(new URLSearchParams('all=1')));
          const fresh=main.querySelector('#library-title-search');land();assert.equal(location.hash,origin);assert.equal(main.querySelector('#library-title-search'),fresh);
          assert(!location.hash.includes('checked_before='));assert.equal(reroutes,0);
        ''')


if __name__ == "__main__":
    unittest.main()
