"""Usual opponents in the real Packing and new-matchup pickers, without a server or Forge."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = """
  clear(main);
  state.profile = {id:'matt',name:'Matt',space:'home',role:'admin',plays_as:'user'};
  state.profiles = [state.profile]; state.remote = false;
  // The shared DOM double has no native HTMLSelectElement option/value behavior.
  const createElement = document.createElement;
  document.createElement = tag => {
    const node = createElement(tag);
    if (tag === 'select') {
      let selected = '';
      Object.defineProperty(node, 'options', {get: () => node.querySelectorAll('option')});
      Object.defineProperty(node, 'value', {get: () => node.options.some(o => o.value === selected) ? selected
        : (node.options.find(o => o.getAttribute('selected') !== null) || node.options[0])?.value || '',
        set: value => { selected = String(value); }});
    }
    return node;
  };
  const choice = (id, title, status='building', usual_opponents=[], extra={}) =>
    ({id,title,status,usual_opponents,space:'home',kind:'casual',versions:['target','owned'],...extra});
  const choices = () => [choice('casual/a','Alpha','built',['casual/c','casual/c','casual/missing']),
    choice('casual/b','Beta'), choice('casual/c','Gamma','idea',['casual/a']),
    choice('product/d','Delta','product')];
  const pack = (items=choices(), selected=[{id:'casual/a',version:'owned'}]) => {
    const view = {choices:items,selected,seq:0,timer:null,run:()=>{}};
    view.picks = el('div');
    view.chooser = el('div', {}, el('span',{class:'pack-choose-count'}),el('div',{class:'pack-show-plan'}));
    main.append(view.picks,view.chooser); drawPackPicks(view); return view;
  };
  const group = (view, title) => view.picks.querySelectorAll('.pack-group')
    .find(g => (g.querySelector('h3') || g.querySelector('summary'))?.textContent === title);
  const names = root => root.querySelectorAll('li').map(row => row.querySelector('span').textContent);
  const selectPack = (view, title, checked) => {
    const row = view.picks.querySelectorAll('li').find(item => item.querySelector('span').textContent === title);
    assert(row,title); const input = row.querySelector('input'); input.checked = checked; input.fire('change');
  };
  const library = () => ({decks:choices(),halves:[]});
  const optionIds = picker => picker.node.querySelector('select').options.map(o => o.value);
  const usualGroup = picker => picker.node.querySelectorAll('optgroup')
    .find(node => node.getAttribute('label') === 'Usual opponents');
  const chooseDeck = (sheet, n, id) => {
    const select = sheet.body.querySelector('#pick-' + n); select.value = id; select.fire('change');
  };
  const live = () => ({forge:{ready:true},choices:[200,400],default_games:200,running:[],results:[]});
  const settle = async () => { for(let i=0;i<24;i++) await null; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class UsualOpponentPickerUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_packing_suggests_unselected_opponents_once_before_the_status_groups(self):
        self.run_js("""
          const view = pack();
          assert.equal(view.picks.children[0].querySelector('h3').textContent,'Usual opponents');
          same(names(group(view,'Usual opponents')),['Gamma']);
          same(names(group(view,'Built')),['Alpha']);
          assert.equal(names(view.picks).filter(name => name === 'Gamma').length,1);
          assert(!view.picks.textContent.includes('missing'));
          same(view.selected,[{id:'casual/a',version:'owned'}]);
          selectPack(view,'Gamma',true);
          assert(!group(view,'Usual opponents'));
          same(names(group(view,'Ideas')),['Gamma']);
          same(view.selected,[{id:'casual/a',version:'owned'},{id:'casual/c',version:'target'}]);
        """)

    def test_packing_union_changes_with_selection_without_forgetting_versions_or_selecting_extra_decks(self):
        self.run_js("""
          const items = choices(); items[1].usual_opponents = ['product/d','casual/c'];
          const view = pack(items,[{id:'casual/a',version:'owned'},{id:'casual/b',version:'target'}]);
          same(names(group(view,'Usual opponents')),['Gamma','Delta']);
          selectPack(view,'Alpha',false); same(names(group(view,'Usual opponents')),['Gamma','Delta']);
          selectPack(view,'Beta',false); assert(!group(view,'Usual opponents'));
          same(view.selected,[]);
        """)

    def test_packing_maximum_still_disables_suggested_unselected_decks(self):
        self.run_js("""
          const items = choices();
          for(let n=0;n<PACK_MAX-1;n++) items.push(choice('casual/x'+n,'Extra '+n));
          const selected = items.filter(item => item.id !== 'casual/c' && item.id !== 'product/d').slice(0,PACK_MAX)
            .map(item => ({id:item.id,version:'target'}));
          const view = pack(items,selected);
          assert.equal(view.selected.length,PACK_MAX);
          assert(group(view,'Usual opponents').querySelector('input').disabled);
          assert(!group(view,'Built').querySelector('input').disabled);
        """)

    def test_packing_uses_a_resolved_pairing_choice_in_both_directions(self):
        self.run_js("""
          const items = choices(); items[0].usual_opponents = ['pairing/alpha+beta'];
          items.push(choice('pairing/alpha+beta','First + Second','built',['casual/a'],{kind:'pairing',versions:['target']}));
          const view = pack(items);
          same(names(group(view,'Usual opponents')),['First + Second']);
          selectPack(view,'First + Second',true); assert(!group(view,'Usual opponents'));
          selectPack(view,'Alpha',false); same(names(group(view,'Usual opponents')),['Alpha']);
          same(view.selected,[{id:'pairing/alpha+beta',version:'target'}]);
        """)

    def test_forge_orders_only_eligible_usual_opponents_and_deduplicates_options(self):
        self.run_js("""
          const data = library(); data.decks.push(choice('commander/x','Commander','idea',[],{kind:'commander'}),
            choice('casual/bad','Broken','idea',[],{error:'Unreadable'}),
            choice(BOX_PREFIX+'half','Individual half'));
          const picker = deckPicker(2,data,()=>{});
          picker.limit(false,'casual/a',['casual/c','casual/c','casual/a','casual/missing','casual/bad',
            'commander/x',BOX_PREFIX+'half']);
          same(usualGroup(picker).querySelectorAll('option').map(o => o.value),['casual/c']);
          assert.equal(picker.node.querySelector('select').children[0],usualGroup(picker));
          assert.equal(optionIds(picker).filter(id => id === 'casual/c').length,1);
          assert(!optionIds(picker).includes('casual/missing'));
          assert(!optionIds(picker).includes('commander/x'));
          picker.other('casual/a'); assert.equal(picker.value().id,'casual/c');
        """)

    def test_forge_reorders_preferences_without_replacing_a_chosen_deck_or_play_now_version(self):
        self.run_js("""
          const picker = deckPicker(2,library(),()=>{});
          picker.limit(false,'casual/a',['casual/c']); picker.set('casual/b','owned');
          picker.limit(false,'casual/c',['product/d']);
          assert.equal(picker.value().id,'casual/b'); assert.equal(picker.value().version,'owned');
          same(usualGroup(picker).querySelectorAll('option').map(o => o.value),['product/d']);
          picker.set('casual/c','owned'); picker.limit(false,'casual/c',['product/d']);
          assert.equal(picker.value().id,'casual/c'); assert.equal(picker.value().version,'owned');
        """)

    def test_new_matchup_defaults_to_a_usual_opponent_and_preserves_explicit_preset(self):
        self.run_js("""
          const data = library();
          let sheet = openPlaySheet(data,live,routeToken,{a:'casual/a',av:'owned'});
          assert.equal(sheet.body.querySelector('#pick-2').value,'casual/c');
          chooseDeck(sheet,2,'casual/b');
          sheet.body.querySelectorAll('.mu-pick')[1].querySelectorAll('button')
            .find(button => button.textContent === listName('owned')).click();
          chooseDeck(sheet,1,'casual/c'); assert.equal(sheet.body.querySelector('#pick-2').value,'casual/b');
          assert(sheet.body.querySelectorAll('.mu-pick')[1].querySelectorAll('button')
            .some(button => button.textContent === listName('owned') && button.getAttribute('aria-pressed') === 'true'));
          sheet.close();
          sheet = openPlaySheet(data,live,routeToken,{a:'casual/a',b:'casual/b',bv:'owned'});
          assert.equal(sheet.body.querySelector('#pick-2').value,'casual/b');
          const second = sheet.body.querySelectorAll('.mu-pick')[1];
          assert(second.querySelectorAll('button').some(button => button.textContent === listName('owned')
            && button.getAttribute('aria-pressed') === 'true'));
          chooseDeck(sheet,1,'casual/c');
          assert.equal(sheet.body.querySelector('#pick-2').value,'casual/b');
          assert(second.querySelectorAll('button').some(button => button.textContent === listName('owned')
            && button.getAttribute('aria-pressed') === 'true'));
        """)

    def test_format_changes_choose_an_eligible_preferred_fallback(self):
        self.run_js("""
          const data = library(); data.decks.push(
            choice('commander/a','Angels','built',['commander/c'],{kind:'commander'}),
            choice('commander/b','Beasts','built',[],{kind:'commander'}),
            choice('commander/c','Cats','built',[],{kind:'commander'}));
          const sheet = openPlaySheet(data,live,routeToken,{a:'casual/a',b:'casual/b',bv:'owned'});
          chooseDeck(sheet,1,'commander/a');
          assert.equal(sheet.body.querySelector('#pick-2').value,'commander/c');
          assert(!sheet.body.querySelector('#pick-2').options.some(option => option.value === 'casual/b'));
          const second = sheet.body.querySelectorAll('.mu-pick')[1];
          assert(second.querySelectorAll('button').some(button => button.textContent === listName('owned')
            && button.getAttribute('aria-pressed') === 'true'));
        """)

    def test_usual_pairings_need_exactly_two_known_halves_and_keep_a_manual_pairing(self):
        self.run_js("""
          const data = library(); data.halves = [{id:BOX_PREFIX+'alpha',title:'First half'},
            {id:BOX_PREFIX+'beta',title:'Second half'},{id:BOX_PREFIX+'bad',title:'Broken',error:'Unreadable'}];
          const picker = deckPicker(2,data,()=>{});
          picker.limit(false,'casual/a',['pairing/alpha+beta','pairing/alpha+missing','pairing/alpha+alpha',
            'pairing/alpha+beta+beta','pairing/alpha+bad']);
          same(usualGroup(picker).querySelectorAll('option').map(o => o.value),['pairing/alpha+beta']);
          picker.other('casual/a'); assert.equal(picker.value().id,'pairing/alpha+beta');
          assert.equal(picker.value().title,'First half + Second half');
          assert.equal(picker.value().version,'target');
          picker.limit(false,'casual/b',[]); assert.equal(picker.value().id,'pairing/alpha+beta');
          picker.limit(true,'commander/x',['pairing/alpha+beta']);
          assert(!optionIds(picker).some(id => id.startsWith('pairing/')));
          picker.limit(false,'casual/a',[]); picker.set('pairing/beta+alpha','owned');
          assert.equal(picker.value().id,'pairing/beta+alpha');
          picker.limit(false,'casual/b',['casual/c']);
          assert.equal(picker.value().id,'pairing/beta+alpha');
        """)

    def test_a_pairing_in_deck_one_uses_its_reciprocal_preferences_in_either_half_order(self):
        self.run_js("""
          const data = library(); data.halves = [{id:BOX_PREFIX+'alpha',title:'First'},
            {id:BOX_PREFIX+'beta',title:'Second'}];
          data.usual_opponents = {'pairing/alpha+beta':['casual/c']};
          const sheet = openPlaySheet(data,live,routeToken,{a:'pairing/beta+alpha'});
          assert.equal(sheet.body.querySelector('#pick-2').value,'casual/c');
          const preferredOptions = sheet.body.querySelectorAll('.mu-pick')[1].querySelectorAll('optgroup')
            .find(node => node.getAttribute('label') === 'Usual opponents');
          same(preferredOptions.querySelectorAll('option').map(o => o.value),['casual/c']);
        """)


if __name__ == "__main__":
    unittest.main()
