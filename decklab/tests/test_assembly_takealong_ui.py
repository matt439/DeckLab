"""Shared optional take-along checks and a scoped print action; no native browser or writes."""
import unittest

from decklab.tests import test_assembly_completion_ui as completion
from decklab.tests.test_workspace_ui import NODE


SETUP = r'''
  const takeModel=()=>({available:true,
    decks:[{task:'take-along|deck|casual/a',context:'a'.repeat(64),title:'Elves',
      lines:['Deck box: Green box','Sleeves: Shared sleeves','Token cards: 2 Dog / Beast (TFDN) 12']}],
    counters:[{task:'take-along|counter|poison',context:'b'.repeat(64),title:'Poison counters',
      lines:['Used by Elves','A die or generic counter stands in']}],
    counter_note:'An estimate of kinds only.',counter_error:null,playmats:['My mat','Shared mat'],playmats_error:null});
  const takePlan=()=>({...plan([item()]),take_along:takeModel()});
  const openTake=(data=takePlan())=>{drawAssembly(data,routeToken);return packingProgressView;};
  const takeTicks=()=>main.querySelector('.pack-takealong').querySelectorAll('input');
  let prints=0;window.print=()=>prints++;
'''


@unittest.skipUnless(NODE, "Node.js is not installed")
class TakeAlongUiTests(unittest.TestCase):
    def run_js(self, scenario):
        completion.AssemblyCompletionUiTests.run_js(self, SETUP + scenario)

    def test_optional_checks_share_progress_and_do_not_change_card_readiness(self):
        self.run_js(r'''
          const data=takePlan(),v=openTake(data);await settle();
          const oldCardId=v.ticks.find(tick=>tick.tile).id;
          assert.equal(v.ticks.filter(tick=>tick.optional).length,2);
          assert.equal(v.ticks.filter(tick=>tick.tile).length,1);
          const before=v.bar.progress.copies.textContent;
          const check=takeTicks()[0];check.checked=true;check.fire('change');await settle();
          assert(v.ticks.find(tick=>tick.node===check).done);
          assert.equal(v.bar.progress.copies.textContent,before);
          assert.equal(v.ticks.find(tick=>tick.tile).id,oldCardId);
          checkCards();await settle();assert(packCanFinish(v));
          assert.equal(v.bar.progress.state.textContent,'All packed.');
          clear(main);const resumed=openTake(data);await settle();
          assert(takeTicks()[0].checked);assert(!takeTicks()[1].checked);
          assert.equal(resumed.ticks.find(tick=>tick.tile).id,oldCardId);
          assert(main.querySelector('.pack-takealong').textContent.includes('Playmats to remember: My mat; Shared mat'));
        ''')

    def test_optional_tick_failure_never_holds_the_build_and_card_bulk_does_not_tick_it(self):
        self.run_js(r'''
          const v=openTake();await settle();
          main.querySelector('.pack-bulk-tick').click();await settle();
          assert(takeTicks().every(check=>!check.checked));assert(packCanFinish(v));
          apiWrite=async()=>{throw new Error('Synthetic offline');};
          const check=takeTicks()[0];check.checked=true;check.fire('change');await settle();
          assert(v.progress.error);assert(packCanFinish(v));
          assert(!v.finish.message.textContent.includes('Save shared progress'));
        ''')

    def test_print_uses_the_same_visible_reminders_and_current_tick_state_only(self):
        self.run_js(r'''
          const v=openTake();await settle();
          takeTicks()[0].checked=true;takeTicks()[0].fire('change');await settle();
          v.takeAlong.button.click();assert.equal(prints,1);
          const sheet=document.querySelector('.print-sheet');
          assert(sheet.textContent.includes('[x] Elves'));
          assert(sheet.textContent.includes('[ ] Poison counters'));
          assert(sheet.textContent.includes('2 Dog / Beast (TFDN) 12'));
          assert(sheet.textContent.includes('My mat; Shared mat'));
          assert.equal(sheet.querySelector('input'),null);
          assert.equal(sheet.querySelector('img'),null);
          window.fire('afterprint');assert.equal(document.querySelector('.print-sheet'),null);
        ''')

    def test_departed_print_controls_are_refused_for_every_owner_boundary(self):
        self.run_js(r'''
          const cases=[
            v=>routeToken++,v=>location.hash='#/library',v=>state.profile={...state.profile},
            v=>v.data={...v.data},v=>v.data.take_along={...v.data.take_along},
            v=>v.takeAlong.button.remove(),v=>v.takeAlong.button.hidden=true,
            v=>v.takeAlong.section.hidden=true,v=>v.takeAlong.section.remove(),
            v=>v.previewing=true,v=>v.saving=true,v=>v.reviewing=true,
            v=>v.selected=[],v=>v.takeAlong.model.decks[0].lines.push('Changed reminder'),
            v=>state.may={see_home_records:false},
            v=>document.body.append(el('dialog',{open:true})),
            v=>{const foreign=el('div');document.body.append(foreign);foreign.append(v.takeAlong.button);},
          ];
          for(const change of cases){
            clear(main);for(const dialog of document.querySelectorAll('dialog'))dialog.remove();
            state.profile={id:'matt',name:'Matt',space:'home',role:'admin',plays_as:'user'};
            state.profiles=[state.profile];state.may={see_home_records:true};location.hash='#/assembly';
            const v=openTake();await settle();const button=v.takeAlong.button;
            change(v);button.click();assert.equal(prints,0);
          }
        ''')

    def test_unknown_or_unavailable_take_along_data_never_offers_fake_empty_checks(self):
        self.run_js(r'''
          const data=takePlan();data.take_along={available:false,reason:'Choose the built list.'};
          openTake(data);await settle();assert.equal(main.querySelector('.pack-takealong'),null);
          assert(main.querySelector('.pack-takealong-unavailable').textContent.includes('Choose the built list'));
          assert.equal(main.querySelector('.pack-takealong-tick'),null);
          assert.equal(prints,0);
        ''')
