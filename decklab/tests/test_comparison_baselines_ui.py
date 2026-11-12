"""Read-only Compare baselines retain their selectors, unknown states and no-copy semantics."""
import unittest

from decklab.tests import test_compare_ui as compare_ui
from decklab.tests.test_workspace_ui import NODE

SETUP = r'''
  const oldRevision=()=>{const value=deckB();value.summary.id='casual/test';value.summary.title='Older title';
    value.comparison={kind:'revision',revision:3,date:'2026-10-06T12:00:00+00:00',
      bracket_note:"Bracket judged using today's card data and Commander lists."};
    value.stats.colours.colours=[{...green,land_sources:12}];value.stats.roles=[{role:'ramp',count:1,cards:[]}];return value;};
'''


@unittest.skipUnless(NODE, "Node.js is not installed")
class ComparisonBaselineUiTests(unittest.TestCase):
    def run_js(self, scenario):
        compare_ui.CompareUiTests.run_js(self, SETUP + scenario)

    def test_revision_is_labelled_and_no_pool_result_or_game_log_fetch_runs(self):
        self.run_js(r'''
          const current=deckA();current.stats.colours.colours[0].land_sources=14;
          answers={'/api/compare/deck?':current,'/api/deck/revision?':oldRevision()};
          await show(compareRevisionHref('casual/test',3));
          assert(main.textContent.includes('Revision 3, 6 Oct 2026'));
          same(asked,['/api/compare/deck?id=casual%2Ftest&version=target',
            '/api/deck/revision?id=casual%2Ftest&version=target&revision=3&stats=1']);
          assert.equal(main.querySelector('#h-compare-shared'),null);assert.equal(main.querySelector('#h-compare-h2h'),null);
          const delta=main.querySelector('#h-compare-deltas').parentNode;
          assert(delta.textContent.includes('Change from Revision 3, 6 Oct 2026 to Test Deck'));
          const cells=delta.querySelector('tbody').children.map(row=>[row.querySelector('th').textContent,row.querySelector('td').textContent]);
          same(cells.find(row=>row[0]==='Average mana value'),['Average mana value','−0.3']);
          same(cells.find(row=>row[0]==='Green land sources'),['Green land sources','+2']);
          assert(compareAddress(compareSideOf(oldRevision()),compareSideOf(current)).includes('ar=3'));
        ''')

    def test_application_router_accepts_precon_selectors_on_either_side(self):
        self.run_js(r'''
          const seen=[];showCompare=params=>seen.push(Object.fromEntries(params));
          showLibrary=()=>{throw Error('Baseline incorrectly fell back to library');};
          closeEditor=()=>{};syncShell=()=>{};noteVisit=()=>{};
          for(const hash of ['#/compare?a=casual%2Ftest&bp=TestDinos_TST',
            '#/compare?ap=TestDinos_TST&b=casual%2Ftest','#/compare?ap=One_TST&bp=Two_TST']){
            location.hash=hash;route();
          }
          assert.equal(seen.length,3);assert.equal(seen[0].bp,'TestDinos_TST');assert.equal(seen[1].ap,'TestDinos_TST');
        ''')

    def test_land_source_delta_survives_the_last_spell_of_a_colour_being_removed(self):
        self.run_js(r'''
          const current=deckA(),old=oldRevision();current.stats.colours.colours=[];
          current.stats.colours.land_sources_by_colour={G:14};old.stats.colours.land_sources_by_colour={G:12};
          answers={'/api/compare/deck?':current,'/api/deck/revision?':old};await show(compareRevisionHref('casual/test',3));
          const cells=main.querySelector('#h-compare-deltas').parentNode.querySelector('tbody').children
            .map(row=>[row.querySelector('th').textContent,row.querySelector('td').textContent]);
          same(cells.find(row=>row[0]==='Green land sources'),['Green land sources','+2']);
        ''')

    def test_precon_side_never_uses_a_fake_deck_route_and_swap_keeps_the_public_selector(self):
        self.run_js(r'''
          const published=deckB();published.summary.id=null;published.comparison={kind:'precon',file:'TestDinos_TST',label:'Published precon: Test Dinos'};
          answers={'/api/compare/deck?':deckA(),'/api/compare/precon?':published};
          await show(comparePreconHref('casual/test','TestDinos_TST'));
          same(asked,['/api/compare/deck?id=casual%2Ftest&version=target','/api/compare/precon?file=TestDinos_TST']);
          const heads=main.querySelectorAll('.compare-title');assert.equal(heads[1].textContent,'Published precon: Test Dinos');
          assert.equal(heads[1].getAttribute('href'),null);assert.equal(main.querySelector('#h-compare-h2h'),null);
          main.querySelector('.menu-wrap').querySelector('button').click();
          const swap=main.querySelector('.menu-wrap').querySelectorAll('[role=menuitem]')[0].getAttribute('href');
          assert(swap.includes('ap=TestDinos_TST'));assert(swap.includes('b=casual%2Ftest'));assert(!swap.includes('null'));
        ''')

    def test_unknown_stats_stay_unknown_and_bracket_is_judged_by_todays_lists(self):
        self.run_js(r'''
          const current=deckA();current.stats.commander={bracket:{label:'Bracket 2'}};
          const old=oldRevision();old.stats=null;old.stats_unknown=true;old.stats_kind='commander';
          old.stats_note='Stats are unknown because a card is unrecognized.';old.fields={Sleeves:'PRIVATE_KIT'};
          answers={'/api/compare/deck?':current,'/api/deck/revision?':old};await show(compareRevisionHref('casual/test',3));
          assert(main.textContent.includes('Stat changes are unknown'));assert(main.textContent.includes('Unknown mana curve'));
          assert(main.textContent.includes("today's card data and Commander lists"));assert(!main.textContent.includes('PRIVATE_KIT'));
          same(rows('The two lists in brief').find(row=>row[0]==="Bracket (today's lists)"),["Bracket (today's lists)",'Bracket 2','Unknown']);
          assert(!asked.some(path=>path.includes('/api/compare/shared')||path.startsWith('/api/play')));
        ''')

    def test_public_precon_search_is_available_without_another_deck_and_profile_drift_cannot_draw_results(self):
        self.run_js(r'''
          const data=deckA();data.versions=['target'];answers={'/api/precons?q=':{decks:[{file:'TestDinos_TST',name:'Test Dinos'}]}};
          const opened=[],originalOpen=openSheet;openSheet=(...args)=>{const value=originalOpen(...args);opened.push(value);return value;};
          const chooser=openCompareChooser(data,[]);buttonText(chooser.body,'Compare with a published precon…').click();await settle();
          const sheet=opened.at(-1);
          assert(chooser.closed);assert.notEqual(sheet,chooser);assert.equal(document.querySelectorAll('dialog[open]').length,1);
          const link=sheet.body.querySelector('a');assert.equal(link.textContent,'Test Dinos');
          assert.equal(link.getAttribute('href'),comparePreconHref('casual/test','TestDinos_TST'));
          sheet.close();let resolve;api=()=>new Promise(done=>resolve=done);
          const pending=comparePreconChooser(data);state.profile={...state.profile};resolve({decks:[{file:'PrivateOld',name:'Late stale result'}]});
          await settle();assert(!pending.body.textContent.includes('Late stale result'));
        ''')

    def test_history_sheet_links_to_read_only_stats_comparison(self):
        self.run_js(r'''
          const rev={revision:3,date:'2026-10-06T12:00:00+00:00',op:'M',author:'Matt',change:{kind:'cards',cards:[],fields:[],lists:['target'],size:{target:22}}};
          const sheet=historySheet(rev,{may_save:false,retired:false},'casual/test','target',routeToken);
          const link=sheet.body.querySelectorAll('a').find(node=>node.textContent==='Compare stats with the deck now');
          assert(link);assert.equal(link.getAttribute('href'),compareRevisionHref('casual/test',3));assert.equal(asked.length,0);
        ''')

    def test_version_links_keep_the_baseline_and_history_falls_back_to_current_planned_list(self):
        self.run_js(r'''
          const current=deckA(),old=oldRevision();current.versions=old.versions=['target','owned'];
          answers={'/api/compare/deck?':current,'/api/deck/revision?':old};await show(compareRevisionHref('casual/test',3));
          const groups=main.querySelectorAll('.compare-head').map(node=>node.querySelector('.segmented'));
          const currentOwned=groups[0].querySelectorAll('a')[1].getAttribute('href');
          const oldOwned=groups[1].querySelectorAll('a')[1].getAttribute('href');
          assert(currentOwned.includes('av=owned')&&currentOwned.includes('br=3'));
          assert(oldOwned.includes('bv=owned')&&oldOwned.includes('br=3'));
          const rev={revision:3,date:'2026-10-06T12:00:00+00:00',op:'M',author:'Matt',change:{kind:'cards',cards:[],fields:[],lists:['owned'],size:{target:22,owned:22}}};
          const sheet=historySheet(rev,{may_save:false,retired:false,versions:['target']},'casual/test','owned',routeToken);
          const link=sheet.body.querySelectorAll('a').find(node=>node.textContent==='Compare stats with the deck now');
          assert.equal(link.getAttribute('href'),compareRevisionHref('casual/test',3,'owned','target'));
        ''')
