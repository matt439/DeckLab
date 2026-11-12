"""The card viewer's Game Changer chip and known two-card combos fold (E9-S37), over the real page scripts."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = r'''
  state.profile={id:'matt',space:'home'};state.may={see_inventory:['home']};
  location.hash='#/deck?id=user2/commander/test';
  const card={name:'Rhystic Study',type_line:'Enchantment',img:'/img/pcy/45/normal',game_changer:true,
    scryfall_url:'https://scryfall.com/card/pcy/45'};
  const plain={name:'Llanowar Elves',type_line:'Creature',img:'/img/fdn/227/normal'};
  const flush=async()=>{for(let i=0;i<20;i++)await null;};
  const combo=(id,extra={})=>({id,url:`https://commanderspellbook.com/combo/${id}/`,class:'win',standalone:true,
    results:['Win the game'],more_results:0,bracket_floor:3,must_be_commander:false,
    others:[{name:'Leader',must_be_commander:true}],...extra});
  let answer={name:'Rhystic Study',game_changer:true,checked:true,date:'2026-11-01',version:'7.3.0',total:30,
    combos:[combo('a-b'),combo('c-d',{standalone:false,bracket_floor:1,class:'infinite',must_be_commander:true,
      others:[{name:'Payoff',must_be_commander:false}],results:['Infinite mana','Infinite ETB','Infinite LTB'],more_results:2}),
      combo('bad',{url:'https://evil.example/combo/1/'})],
    credit:"Commander Spellbook's combo list (commanderspellbook.com, with thanks)",source_url:'https://commanderspellbook.com/'};
  const reads=[];
  api=async path=>{reads.push(path);if(path.startsWith('/api/cards/combos'))return typeof answer==='function'?answer(path):answer;
    if(path.startsWith('/api/cards/decks'))return {basic:true};return {available:true,rulings:[]};};
  const show=(c=card)=>{viewerCombos.clear();openCardViewer([c]);viewerDom.dialog.open=true;};
  const part=()=>viewerDom.text.querySelector('.viewer-combos');
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CardViewerCombosUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_game_changer_chip_from_the_card_and_from_the_answer(self):
        self.run_js(r'''
          show();const chip=part().querySelector('.viewer-gc');assert(chip);assert.equal(chip.textContent,'Game Changer');
          await flush();assert.equal(part().querySelectorAll('.viewer-gc').length,1);
          answer={...answer,name:'Llanowar Elves',game_changer:false};show(plain);assert.equal(part().querySelector('.viewer-gc'),null);
          await flush();assert.equal(part().querySelector('.viewer-gc'),null);
          answer={...answer,game_changer:true};show({...plain});await flush();assert(part().querySelector('.viewer-gc'));
        ''')

    def test_collapsed_fold_lists_pieces_commander_floor_link_date_credit_and_cap(self):
        self.run_js(r'''
          show();await flush();const fold=part().querySelector('details');assert(fold);assert(!fold.open);
          assert.equal(fold.querySelector('summary').textContent,'Known two-card combos with this card (30)');
          const items=fold.querySelectorAll('li');assert.equal(items.length,3);
          assert(items[0].textContent.includes('With Leader (must be the commander)'));
          assert(items[0].textContent.includes('Win the game · Bracket 3 or higher'));
          const link=items[0].querySelector('a');assert.equal(link.getAttribute('href'),'https://commanderspellbook.com/combo/a-b/');
          assert.equal(link.getAttribute('target'),'_blank');assert.equal(link.getAttribute('rel'),'noopener noreferrer');
          assert(items[1].textContent.includes('With Payoff; this card must be the commander'));
          assert(items[1].textContent.includes('Infinite mana · Infinite ETB · Infinite LTB · 2 more · needs a payoff · Any bracket'));
          assert.equal(items[2].querySelector('a'),null);
          assert(fold.textContent.includes('The 3 most serious shown, of 30.'));
          assert(fold.textContent.includes("Commander Spellbook's combo list (commanderspellbook.com, with thanks), its list of 2026-11-01."));
          assert.equal(fold.querySelectorAll('a').slice(-1)[0].getAttribute('href'),'https://commanderspellbook.com/');
        ''')

    def test_a_card_with_none_says_so_only_when_the_list_was_read(self):
        self.run_js(r'''
          answer={...answer,total:0,combos:[]};show();await flush();
          assert.equal(part().querySelector('summary').textContent,'Known two-card combos with this card (0)');
          assert(part().textContent.includes('None in the list.'));
        ''')

    def test_an_unread_list_says_combos_werent_checked_never_none(self):
        self.run_js(r'''
          answer={name:'Rhystic Study',game_changer:true,checked:false,reason:"Combos weren't checked: the list can't be read."};
          show();await flush();assert(part().textContent.includes("Combos weren't checked: the list can't be read."));
          assert.equal(part().querySelector('details'),null);assert(!part().textContent.includes('None'));
          assert(part().querySelector('.viewer-gc'));
          answer={available:true,rulings:[]};show();await flush();assert(part().textContent.includes("Combos weren't checked."));
        ''')

    def test_failures_retry_next_time_and_a_non_card_shows_nothing(self):
        self.run_js(r'''
          answer=()=>{throw Object.assign(Error('private server detail'),{status:503});};show();await flush();
          assert(part().textContent.includes("Combos couldn't load"));assert(!part().textContent.includes('private'));
          assert(!viewerCombos.has('Rhystic Study'));
          answer=()=>{throw Object.assign(Error('No card'),{status:404});};show({name:'Treasure',type_line:'Token'});await flush();
          assert.equal(part().textContent,'');
        ''')

    def test_the_lookup_names_only_the_card_never_a_deck_or_space_and_is_asked_once(self):
        self.run_js(r'''
          viewerCombos.clear();openCardViewer([card]);viewerDom.dialog.open=true;await flush();
          openCardViewer([card]);await flush();
          const asked=reads.filter(path=>path.startsWith('/api/cards/combos'));
          assert.deepEqual(asked,['/api/cards/combos?name=Rhystic+Study']);
        ''')


if __name__ == "__main__":
    unittest.main()
