"""E5-S30: the editor Add panel's My wishlist tick (editor-wishlist.js) under Node: offered to a casual or
Commander deck (saved or new, never a product) when a profile is chosen, asking nothing until it's ticked; the
wished cards come in the wishlist's order without the draft's cards, marked only when the server sent marks;
a card added keeps its wished printing; a Commander deck asks by its draft commander; nothing is written.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js with invented cards; nothing is sent to a
server."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = r"""
  const card = (name, type = 'Creature — Elf', cmc = 2, identity = ['G']) =>
    ({name, mana_cost: '{G}', type_line: type, cmc, color_identity: identity, img_small: null});
  const wish = (name, extra = {}, shape = {}) => Object.assign({name, set: '', number: '', in_deck: false,
    card: card(name, shape.type, shape.cmc, shape.identity)}, extra);
  const ANSWER = (marks = true) => ({profile: 'matt', space: 'home', kind: 'commander', identity: 'G', left_out: 2,
    marks, rate: marks ? 1.43 : null, rate_date: '2026-10-27', price_date: '2026-10-28', price_error: null, warnings: [],
    cards: [
      wish('Elvish Mystic', Object.assign({set: 'cmm', number: '648'}, marks ? {status: 'free', free: 2, on_the_way: 1} : {})),
      wish('Pick Your Poison', marks ? {status: 'to_buy', free: 0, on_the_way: 0, aud_each: 0.39} : {}, {type: 'Sorcery', cmc: 1}),
      wish('Llanowar Elves', marks ? {status: 'in_deck', in_deck: true} : {in_deck: true})]});
  state.profile = {id: 'matt', name: 'Matt', space: 'home'};
  const asked = [], writes = [];
  let answer = ANSWER();
  api = async (path) => {
    asked.push(path);
    if (path.startsWith('/api/deck/find')) return {cards: [], pages: 1};
    if (!path.startsWith('/api/deck/wishlist')) throw new Error('unexpected ' + path);
    if (answer instanceof Error) throw answer;
    return answer;
  };
  apiWrite = async (...args) => { writes.push(args); throw new Error('nothing is written'); };
  const settle = async () => { for (let round = 0; round < 3; round += 1) { flushTimers(); for (let i = 0; i < 8; i += 1) await Promise.resolve(); } };
  const ghalta = {uid: 'c1', name: 'Ghalta, Primal Hunger', qty: 1, set: null, number: null, finish: 'nonfoil'};
  function deckEditor(extra = {}, lists = {Commander: [{...ghalta}], Deck: [{uid: 'd1', name: 'Llanowar Elves', qty: 1}]}) {
    cancelEditorSearch(editor && editor.ac);
    clear(main);
    editor = Object.assign({mode: 'edit', id: 'commander/test', kind: 'commander', sha256: 'a'.repeat(64), version: 'target',
      profile: 'matt', fields: {kind: 'commander'}, lists, sections: ['Commander', 'Deck', 'Sideboard'],
      addSection: 'Deck', dom: {}, checkSeq: 0}, extra);
    main.append(cardSearch());
    return editor.ac;
  }
  const tick = (ac, on = true) => { const box = ac.filters.querySelector('.ac-wishlist').querySelector('input'); box.checked = on; box.fire('change'); };
  const names = (ac) => ac.list.querySelectorAll('.ac-name-text').map((n) => n.textContent);
  const wishAsks = () => asked.filter((path) => path.startsWith('/api/deck/wishlist'));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class EditorWishlistUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_offered_to_casual_and_commander_decks_with_a_profile_and_asks_nothing_until_ticked(self):
        self.run_js(r"""
          assert(deckEditor().filters.querySelector('.ac-wishlist'), 'a saved Commander deck has it');
          assert(deckEditor({kind: 'casual', fields: {kind: 'casual'}}).filters.querySelector('.ac-wishlist'), 'and a casual one');
          assert(deckEditor({mode: 'new', id: null, kind: undefined, fields: {kind: 'casual'}}).filters.querySelector('.ac-wishlist'),
            'and a new deck');
          assert.equal(deckEditor({id: 'product/fdc-test'}).filters.querySelector('.ac-wishlist'), null, 'never a product');
          state.profile = null;
          assert.equal(deckEditor({profile: null}).filters.querySelector('.ac-wishlist'), null, 'nobody chosen, no wishlist');
          state.profile = {id: 'matt', name: 'Matt', space: 'home'};
          const ac = deckEditor();
          assert.equal(ac.filters.querySelector('.ac-wishlist').textContent, 'My wishlist');
          await settle();
          assert.equal(wishAsks().length, 0);
        """)

    def test_wished_cards_list_without_the_draft_and_keep_their_printing(self):
        self.run_js(r"""
          const ac = deckEditor();
          tick(ac); await settle();
          same(wishAsks(), ['/api/deck/wishlist?id=commander%2Ftest&commander=Ghalta%2C+Primal+Hunger']);
          same(names(ac), ['Elvish Mystic', 'Pick Your Poison'], 'the wishlist order, the draft\'s Llanowar Elves left out');
          const note = ac.note.textContent;
          assert(!ac.note.hidden);
          assert(note.includes('From your own wishlist'), note);
          assert(note.includes('2 wished cards don\'t fit this deck.'), note);
          assert(note.includes('1 wished card already in this draft isn\'t listed.'), note);
          const sides = ac.list.querySelectorAll('.ac-side').map((n) => n.textContent);
          assert(sides[0].includes('CMM 648') && sides[0].includes('2 free') && sides[0].includes('1 on the way'), sides[0]);
          assert(sides[1].includes('To buy · ~A$0.39'), sides[1]);
          ac.input.value = 'poison'; ac.input.fire('input'); await settle();
          same(names(ac), ['Pick Your Poison']);
          ac.input.value = ''; ac.input.fire('input'); await settle();
          assert.equal(wishAsks().length, 1, 'asked once');
          ac.list.querySelectorAll('.ac-add')[0].click();
          assert.equal(changes, 1);
          const line = editor.lists.Deck.find((l) => l.name === 'Elvish Mystic');
          same([line.set, line.number, line.finish], ['cmm', '648', 'nonfoil'], 'the wished printing is kept');
          assert.equal('wish' in line.card, false, 'the wish itself is not kept on the line');
          ac.list.querySelectorAll('.ac-add')[1].click();
          const poison = editor.lists.Deck.find((l) => l.name === 'Pick Your Poison');
          assert(!poison.set, 'no wished printing: Save chooses one');
          await settle();
          assert.equal(writes.length, 0, 'nothing is saved until Save');
        """)

    def test_no_marks_without_the_inventory_and_a_new_deck_asks_by_kind(self):
        self.run_js(r"""
          answer = ANSWER(false);
          let ac = deckEditor({mode: 'new', id: null, kind: undefined, space: 'home', fields: {kind: 'casual'}}, {Deck: []});
          tick(ac); await settle();
          same(wishAsks(), ['/api/deck/wishlist?kind=casual&space=home'], 'a casual deck sends no commander');
          const sides = ac.list.querySelectorAll('.ac-side').map((n) => n.textContent).join(' ');
          assert(!sides.includes('free') && !sides.includes('To buy'), sides);
          assert(ac.note.textContent.includes("isn't yours to see"), ac.note.textContent);
          answer = Object.assign(new Error('Choose who you are to see your wishlist.'), {status: 403});
          ac = deckEditor({sha256: 'b'.repeat(64)});
          tick(ac); await settle();
          assert(ac.list.textContent.includes("Your wishlist couldn't be loaded. Choose who you are"), ac.list.textContent);
        """)
