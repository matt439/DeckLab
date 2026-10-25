"""The card checklist follows the storage boxes without losing work in progress."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, WEB, RUNNER


SETUP = """
  clear(main);
  window.matchMedia('(min-width: 1000px)').matches = true;
  state.profile = {id:'matt',name:'Matt',space:'home',role:'admin',plays_as:'user'};
  const saved = {};
  window.localStorage = {getItem: k => saved[k] ?? null,
    setItem: (k, v) => { saved[k] = String(v); }, removeItem: k => { delete saved[k]; }};
  const settle = async () => { for (let i=0;i<32;i++) await null; };
  let requests = 0;
  const serverTicks = new Set();
  const mockApi = handler => {
    apiWrite = async (path,body) => {
      if (path === '/api/assembly/ticks') {
        for (const change of body.changes || []) {
          if (change.done) serverTicks.add(change.id); else serverTicks.delete(change.id);
        }
        return {ticks:body.ids.filter(id => serverTicks.has(id))};
      }
      return handler(path,body);
    };
  };
  mockApi(() => { requests++; throw new Error('Sorting must not request another plan'); });
  const card = (name, type_line, colors = [], extra = {}) => ({name, type_line, colors,
    mana_cost:'', img:null, img_small:null, ...extra});
  const plan = (cards, extra = {}) => ({choices:[],rows:[],ready:true,counts_confirmed:true,
    unresolved:[],warnings:[],note:'',token_note:'',totals:{waiting:0,missing:0},tokens:[],token_plan:[],cards,
    decks:[{id:'casual/a',title:'A',version:'target',sleeves:null,kit:null,sleeves_need:null,tokens:null,
      steps:Object.keys(cards).map(name => ({name,keep:0,storage:1,transfers:[],waiting:0,missing:0})),
      basics:[],returns:[],...extra}]});
  const choose = label => {
    const button = main.querySelector('.pack-sort').querySelectorAll('button').find(b => b.textContent === label);
    assert(button, label); button.click();
  };
  const chosen = () => main.querySelector('.pack-sort').querySelectorAll('button')
    .find(b => b.getAttribute('aria-pressed') === 'true').textContent;
  const names = root => root.querySelectorAll('.card-tile-name').map(n => n.textContent);
  const steps = () => main.querySelectorAll('.pack-step').map(s => s.querySelector('h3').textContent);
  const progress = () => main.querySelector('.pack-progress-long').textContent;
  const tick = id => main.querySelectorAll('.pack-tick').find(n => n.getAttribute('data-pack-tick') === id);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblySortUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_storage_dividers_use_front_types_and_actual_colours(self):
        self.run_js("""
          const cards = {};
          const add = (name, type, colors, extra) => { cards[name] = card(name, type, colors, extra); };
          // Deliberately reversed: neither source order nor alphabetical order matches the box.
          add('Relic', 'Artifact', ['W']);
          add('Bronze bird', 'Artifact Creature', ['U']);
          add('Tree home', 'Land Creature', ['G'], {produced_mana:['G']});
          add('Artifact land', 'Artifact Land', [], {produced_mana:['W']});
          add('Blue land', 'Land', [], {color_identity:['U']});
          add('Red land', 'Land', [], {produced_mana:['R'],color_identity:['R','G']});
          add('Rainbow land', 'Land', [], {produced_mana:['W','U','B','R','G'],color_identity:[]});
          add('Wastes', 'Basic Land', [], {produced_mana:['C'],color_identity:[]});
          add('Void spell', 'Sorcery', [], {color_identity:['R']});
          add('Mixed spell', 'Instant', ['W','U']);
          add('Green spell', 'Enchantment', ['G']);
          add('Red spell', 'Sorcery', ['R']);
          add('Black spell', 'Instant', ['B']);
          add('Blue spell', 'Instant', ['U']);
          add('White spell', 'Sorcery', ['W']);
          add('Void creature', 'Creature', [], {color_identity:['R']});
          add('Mixed creature', 'Creature', ['B','G']);
          add('Green creature', 'Enchantment Creature', ['G']);
          add('Red creature', 'Creature', ['R']);
          add('Black creature', 'Creature', ['B']);
          add('Blue creature', 'Creature', ['U']);
          add('White creature Z', 'Creature', ['W']);
          add('White creature A', 'Creature', ['W'], {color_identity:['W','B']});
          add('Front creature // Back land', 'Creature // Land', ['W','U'], {faces:[
            {type_line:'Creature',colors:['W']}, {type_line:'Land',colors:[]}]});
          add('Adventure creature // Adventure spell', 'Creature // Sorcery', ['R','G'], {faces:[
            {type_line:'Creature',colors:['G']}, {type_line:'Sorcery',colors:['R']}]});
          add('Front land // Back creature', 'Land // Creature', ['B'], {produced_mana:['B'],faces:[
            {type_line:'Land',colors:[]}, {type_line:'Creature',colors:['B']}]});
          cards['Unknown card'] = null;
          drawAssembly(plan(cards), routeToken);
          assert.equal(chosen(), 'Name');
          choose('Storage order');
          const groups = main.querySelectorAll('.pack-storage-group');
          const headings = groups.map(g => g.querySelector('h4').textContent.replace(/ · [0-9]+ cards?$/, ''));
          const colours = ['White','Blue','Black','Red','Green','Multicolour','Colourless'];
          for (const [offset, prefix] of [[0, 'Creatures'], [8, 'Spells'], [16, 'Lands']]) {
            for (let i = 0; i < 7; i++) {
              assert(headings[offset + i].startsWith(prefix), headings[offset + i]);
              assert(headings[offset + i].endsWith(colours[i]), headings[offset + i]);
            }
          }
          same([headings[7],headings[15],headings[23]], ['Artifact creatures','Artifacts','Other cards']);
          same(groups.map(names), [
            ['Front creature','White creature A','White creature Z'], ['Blue creature'], ['Black creature'],
            ['Red creature'], ['Adventure creature','Green creature'], ['Mixed creature'], ['Void creature'],
            ['Bronze bird'],
            ['White spell'], ['Blue spell'], ['Black spell'], ['Red spell'], ['Green spell'], ['Mixed spell'],
            ['Void spell'], ['Relic'], ['Artifact land'], ['Blue land'], ['Front land'], ['Red land'],
            ['Tree home'], ['Rainbow land'], ['Wastes'], ['Unknown card']]);
          assert.equal(requests, 0);
        """)

    def test_reordering_keeps_ticks_and_basics_and_updates_viewer_order(self):
        self.run_js("""
          const cards = {Zebra:card('Zebra','Creature',['W']), Alpha:card('Alpha','Instant',['R']),
            Forest:card('Forest','Basic Land',[],{produced_mana:['G']}), Return:card('Return','Artifact',[])};
          const data = plan(cards, {steps:[
            {name:'Alpha',storage:2,keep:0,transfers:[],waiting:0,missing:0},
            {name:'Zebra',storage:1,keep:0,transfers:[{from:'casual/b',from_title:'B',quantity:1}],waiting:0,missing:0}],
            basics:[{name:'Forest',quantity:20}],returns:[{name:'Return',quantity:1}],
            tokens:{needs:[{name:'Elf',state:'missing'}]}});
          drawAssembly(data, routeToken);
          const ids = () => main.querySelectorAll('.pack-tick').map(n => n.getAttribute('data-pack-tick')).sort();
          const originalIds = ids();
          same(names(main), ['Alpha','Zebra','Zebra','Forest','Return']);
          tick('basic|Forest').click(); tick('pull|Alpha').click();
          assert.equal(progress(), 'Pulled 22 of 25 cards');
          choose('Storage order');
          assert.equal(JSON.stringify(ids()), JSON.stringify(originalIds));
          assert.equal(tick('basic|Forest').getAttribute('aria-pressed'), 'true');
          assert.equal(tick('pull|Alpha').getAttribute('aria-pressed'), 'true');
          assert.equal(progress(), 'Pulled 22 of 25 cards');
          assert(!steps().some(s => s.includes('Basic lands')));
          assert(steps().findIndex(s => s.endsWith('Tokens')) > steps().findIndex(s => s.includes('Put back')));
          const pull = main.querySelectorAll('.pack-step').find(s => s.querySelector('h3').textContent.includes('Pull from storage'));
          same(names(pull), ['Zebra','Alpha','Forest']);
          const basicsGroup = pull.querySelectorAll('.pack-storage-group').find(g => names(g).includes('Forest'));
          const basicsHeading = basicsGroup.querySelector('h4').textContent;
          assert.equal(basicsHeading, 'Lands · Green · 20 cards');
          const viewer = viewerGroup(main.querySelectorAll('.card-tile-open')[1]);
          assert.equal(JSON.stringify(viewer.items.map(item => item.card.name)), JSON.stringify(names(main)));
          assert.equal(viewer.index, 1);
          choose('Name');
          same(names(main), ['Alpha','Zebra','Zebra','Forest','Return']);
          assert(steps().some(s => s.includes('Basic lands (20 cards)')));
          assert.equal(JSON.stringify(ids()), JSON.stringify(originalIds));
          assert.equal(progress(), 'Pulled 22 of 25 cards');
          let undo = null;
          showToast = (text, options) => { undo = options.undo; return {close() {}}; };
          main.querySelector('.pack-clear').click();
          assert.equal(progress(), 'Pulled 0 of 25 cards');
          choose('Storage order');
          assert.equal(progress(), 'Pulled 0 of 25 cards');
          assert(undo); undo();
          assert.equal(tick('basic|Forest').getAttribute('aria-pressed'), 'true');
          assert.equal(tick('pull|Alpha').getAttribute('aria-pressed'), 'true');
          assert.equal(progress(), 'Pulled 22 of 25 cards');
          assert.equal(requests, 0);
          assert.equal(changes, 0);
        """)

    def test_order_is_remembered_per_person_and_blocked_storage_keeps_progress(self):
        self.run_js("""
          const data = plan({Zebra:card('Zebra','Creature',['W']), Alpha:card('Alpha','Instant',['R'])});
          drawAssembly(data, routeToken); choose('Storage order');
          clear(main); drawAssembly(data, routeToken);
          assert.equal(chosen(), 'Storage order');
          same(names(main), ['Zebra','Alpha']);
          state.profile = {id:'user1',name:'User1',space:'home',role:'member',plays_as:'wife'};
          clear(main); drawAssembly(data, routeToken);
          assert.equal(chosen(), 'Name');
          same(names(main), ['Alpha','Zebra']);
          state.profile = {id:'matt',name:'Matt',space:'home',role:'admin',plays_as:'user'};
          clear(main); drawAssembly(data, routeToken);
          assert.equal(chosen(), 'Storage order');
          // A browser that refuses persistence still allows sorting and checking cards off.
          window.localStorage = {getItem() { throw new Error('blocked'); },
            setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); }};
          clear(main); drawAssembly(data, routeToken);
          assert.equal(chosen(), 'Name');
          tick('pull|Alpha').click();
          choose('Storage order');
          assert.equal(tick('pull|Alpha').getAttribute('aria-pressed'), 'true');
          assert.equal(progress(), 'Pulled 1 of 2 cards');
          choose('Name');
          assert.equal(tick('pull|Alpha').getAttribute('aria-pressed'), 'true');
          assert.equal(progress(), 'Pulled 1 of 2 cards');
          assert.equal(requests, 0);
        """)

    def test_storage_costs_increase_and_totals_count_copies(self):
        self.run_js("""
          const cards = {
            Alpha:card('Alpha','Creature',['G'],{cmc:7}),
            Zebra:card('Zebra','Creature',['G'],{cmc:1}),
            Beta:card('Beta','Creature',['G'],{cmc:1}),
            Free:card('Free','Creature',['G'],{cmc:0}),
            Unknown:card('Unknown','Creature',['G'],{cmc:null}),
            Missing:card('Missing','Creature',['G']),
            Forest:card('Forest','Basic Land',[],{cmc:0,produced_mana:['G']})};
          const data = plan(cards, {steps:Object.keys(cards).filter(n => n !== 'Forest').map(name =>
            ({name,keep:0,storage:name === 'Zebra' ? 4 : 1,transfers:[],waiting:0,missing:0})),
            basics:[{name:'Forest',quantity:20}]});
          drawAssembly(data, routeToken);
          assert(steps().some(s => s.includes('Pull from storage (9 cards)')));
          choose('Storage order');
          const groups = main.querySelectorAll('.pack-storage-group');
          same(names(groups[0]), ['Free','Beta','Zebra','Alpha','Missing','Unknown']);
          assert.equal(groups[0].querySelector('h4').textContent, 'Creatures · Green · 9 cards');
          assert.equal(groups[1].querySelector('h4').textContent, 'Lands · Green · 20 cards');
          assert(steps().some(s => s.includes('Pull from storage (29 cards)')));
          tick('pull|Zebra').click();
          assert.equal(progress(), 'Pulled 4 of 29 cards');
          // A verification total stays fixed as copies are checked off.
          assert.equal(groups[0].querySelector('h4').textContent, 'Creatures · Green · 9 cards');
          choose('Name');
          same(names(main), ['Alpha','Beta','Free','Missing','Unknown','Zebra','Forest']);
          assert.equal(tick('pull|Zebra').getAttribute('aria-pressed'), 'true');
        """)

    def test_finish_markers_follow_each_decks_list_and_explain_mixed_finishes(self):
        self.run_js("""
          const cards = {Foil:card('Foil','Creature',['G']), Mixed:card('Mixed','Creature',['G']),
            Etched:card('Etched','Artifact',[]), Plain:card('Plain','Creature',['G'])};
          const data = plan(cards, {finishes:{Foil:[{finish:'foil',quantity:1}],
            Mixed:[{finish:'foil',quantity:1},{finish:'nonfoil',quantity:2}],
            Etched:[{finish:'etched',quantity:1}], Plain:[{finish:'nonfoil',quantity:1}]},
            returns:[{name:'Foil',quantity:1}]});
          data.decks.push({...data.decks[0],id:'casual/b',title:'B',returns:[],finishes:{},
            steps:[{name:'Foil',keep:0,storage:1,transfers:[],waiting:0,missing:0}]});
          drawAssembly(data, routeToken);
          for (const order of ['Name','Storage order']) {
            choose(order);
            const decks = main.querySelectorAll('.pack-deck');
            const tile = id => decks[0].querySelectorAll('.pack-tick')
              .find(n => n.getAttribute('data-pack-tick') === id).closest('.card-tile');
            assert(tile('pull|Foil').getAttribute('class').includes('is-foil'));
            assert.equal(tile('pull|Foil').querySelector('.chip-foil').textContent, 'Foil');
            assert(tile('pull|Etched').getAttribute('class').includes('is-etched'));
            assert.equal(tile('pull|Etched').querySelector('.chip-foil').textContent, 'Etched');
            assert(!tile('pull|Mixed').getAttribute('class').includes('is-foil'));
            assert.equal(tile('pull|Mixed').querySelector('.chip-foil').textContent, 'List: 1 foil · 2 nonfoil');
            assert(tile('pull|Mixed').querySelector('.card-tile-open').getAttribute('aria-label')
              .includes('Deck list: 1 foil · 2 nonfoil'));
            assert(!tile('pull|Plain').querySelector('.chip-foil'));
            assert(!tile('return|Foil').querySelector('.chip-foil'));
            assert(!decks[1].querySelector('.chip-foil'));
          }
        """)

    def test_failed_preview_cannot_restore_the_old_plan_by_sorting(self):
        self.run_js("""
          const data = plan({Zebra:card('Zebra','Creature',['W']), Alpha:card('Alpha','Instant',['R'])});
          data.choices = [{id:'casual/a',title:'A',status:'building',versions:['target']},
            {id:'casual/b',title:'B',status:'built',versions:['target']}];
          drawAssembly(data, routeToken);
          const sort = main.querySelector('.pack-sort');
          const staleButton = sort.querySelectorAll('button').find(b => b.textContent === 'Storage order');
          const otherDeck = () => main.querySelectorAll('input').find(b => b.parentNode.textContent === 'B');
          mockApi(async () => { requests++; throw new Error('Could not load the plan'); });
          otherDeck().checked = true; otherDeck().fire('change');
          flushTimers(); await settle();
          assert.equal(requests, 1);
          assert.equal(sort.hidden, true);
          assert.equal(main.querySelectorAll('.card-tile').length, 0);
          assert(main.querySelector('.pack-message').textContent.includes('Could not load the plan'));
          // Retaining the old DOM button must not revive the stale availability result.
          staleButton.click();
          assert.equal(main.querySelectorAll('.card-tile').length, 0);
          assert.equal(requests, 1);
          mockApi(async () => { requests++; return data; });
          otherDeck().checked = false; otherDeck().fire('change');
          flushTimers(); await settle();
          assert.equal(sort.hidden, false);
          assert.equal(main.querySelector('.pack-message').textContent, '');
          choose('Storage order');
          same(names(main), ['Zebra','Alpha']);
          assert.equal(requests, 2);
        """)
