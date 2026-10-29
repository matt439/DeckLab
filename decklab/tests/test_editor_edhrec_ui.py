"""A Commander deck's EDHREC ideas in the editor's Add panel (E9-S07, editor-edhrec.js) under Node: the scope is
offered only to a saved Commander deck and asks nothing until it's ticked; the ideas come in EDHREC's order
without the draft's cards, with the fetched date, and marked only when the server sent marks; a result adds
to the draft's chosen section with no write; they're asked for the draft's commander(s), so a changed one
needs no save; a late answer for an old scope, revision or commander is ignored; and a failure is said in EDHREC's words while the search goes on working.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js with invented cards; nothing is sent to a
server and EDHREC is never asked.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = r"""
  const card = (name, type = 'Creature — Elf', cmc = 2, identity = ['G']) =>
    ({name, mana_cost: '{G}', type_line: type, cmc, color_identity: identity, img_small: null});
  const idea = (name, inclusion, extra = {}, shape = {}) => Object.assign({name, inclusion, decks: inclusion * 10,
    of: 1000, synergy: 0.1, in_deck: false, considering: false, card: card(name, shape.type, shape.cmc, shape.identity)}, extra);
  const ANSWER = (marks = true, commanders = ['Ghalta, Primal Hunger']) => ({deck_id: 'commander/test', commanders,
    identity: 'G', sha256: 'a'.repeat(64), marks, may_add: marks, warnings: [], left_out: [],
    rate: marks ? 1.43 : null, rate_date: '2026-10-27', price_date: '2026-10-28', price_error: null,
    source: {commander: 'Ghalta, Primal Hunger', decks: 1000, url: 'https://edhrec.com/commanders/ghalta-primal-hunger',
      fetched: '2026-10-28T01:02:03+00:00', stale: null},
    groups: [{header: 'High Synergy Cards', cards: [
      idea('Elvish Mystic', 64, marks ? {status: 'free', free: 2, on_the_way: 1} : {}),
      idea('Pick Your Poison', 26, marks ? {status: 'to_buy', free: 0, on_the_way: 0, aud_each: 0.39} : {}, {type: 'Sorcery', cmc: 1}),
      idea('Llanowar Elves', 70, marks ? {status: 'in_deck', in_deck: true} : {in_deck: true})]},
      {header: 'Lands', cards: [
        idea('Bojuka Bog', 30, marks ? {status: 'in_use', free: 0, on_the_way: 0} : {}, {type: 'Land', cmc: 0, identity: ['B']}),
        idea('Elvish Mystic', 64, marks ? {status: 'free', free: 2, on_the_way: 1} : {})]}]});
  const asked = [], writes = [];
  let answer = ANSWER(), hold = null;
  api = async (path) => {
    asked.push(path);
    if (path.startsWith('/api/deck/find')) return {cards: [alpha], pages: 1};
    if (!path.startsWith('/api/deck/edhrec')) throw new Error('unexpected ' + path);
    if (hold) return hold.promise;
    if (answer instanceof Error) throw answer;
    return answer;
  };
  apiWrite = async (...args) => { writes.push(args); throw new Error('nothing is written'); };
  const deferred = () => { const d = {}; d.promise = new Promise((resolve, reject) => Object.assign(d, {resolve, reject})); return d; };
  const settle = async () => { for (let round = 0; round < 3; round += 1) { flushTimers(); for (let i = 0; i < 8; i += 1) await Promise.resolve(); } };
  const ghalta = {uid: 'c1', name: 'Ghalta, Primal Hunger', qty: 1, set: null, number: null, finish: 'nonfoil'};
  function commanderEditor(extra = {}, lists = {Commander: [{...ghalta}], Deck: [{uid: 'd1', name: 'Llanowar Elves', qty: 1}]}) {
    cancelEditorSearch(editor && editor.ac);
    clear(main);
    editor = Object.assign({mode: 'edit', id: 'commander/test', kind: 'commander', sha256: 'a'.repeat(64), version: 'target',
      profile: state.profile?.id, fields: {kind: 'commander'}, lists, sections: ['Commander', 'Deck', 'Sideboard'],
      addSection: 'Deck', dom: {}, checkSeq: 0}, extra);
    main.append(cardSearch());
    return editor.ac;
  }
  const tick = (ac, on = true) => { const box = ac.filters.querySelector('.ac-edhrec').querySelector('input'); box.checked = on; box.fire('change'); };
  const names = (ac) => ac.list.querySelectorAll('.ac-name-text').map((n) => n.textContent);
  const edhrecAsks = () => asked.filter((path) => path.startsWith('/api/deck/edhrec')).length;
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class EditorEdhrecUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_only_a_saved_commander_deck_offers_the_scope_and_nothing_is_asked_until_ticked(self):
        self.run_js(r"""
          assert.equal(ac.filters.querySelector('.ac-edhrec'), null, 'a new 60-card deck has no EDHREC scope');
          let other = commanderEditor({mode: 'new', id: null});
          assert.equal(other.filters.querySelector('.ac-edhrec'), null, 'an unsaved Commander deck has none');
          other = commanderEditor({kind: 'casual', fields: {kind: 'casual'}});
          assert.equal(other.filters.querySelector('.ac-edhrec'), null);
          other = commanderEditor({id: 'product/fdc-test'});
          assert.equal(other.filters.querySelector('.ac-edhrec'), null, 'never a product');
          const mine = commanderEditor();
          assert(mine.filters.querySelector('.ac-edhrec'), 'a saved Commander deck has it');
          assert.equal(mine.filters.querySelector('.ac-edhrec').textContent, 'EDHREC ideas');
          await settle();
          assert.equal(edhrecAsks(), 0, 'EDHREC is not asked until the scope is chosen');
          assert(mine.note.hidden);
        """)

    def test_ideas_list_in_edhrec_order_without_the_draft_and_add_to_the_chosen_section(self):
        self.run_js(r"""
          const ac = commanderEditor();
          tick(ac); await settle();
          assert.equal(edhrecAsks(), 1);
          assert(asked[0].endsWith('id=commander%2Ftest&commander=Ghalta%2C%20Primal%20Hunger'), asked[0]);
          same(names(ac), ['Elvish Mystic', 'Pick Your Poison', 'Bojuka Bog'],
            'EDHREC order, a card in two categories once, the draft\'s Llanowar Elves left out');
          const note = ac.note.textContent;
          assert(!ac.note.hidden);
          assert(note.includes('Ghalta, Primal Hunger on EDHREC'), note);
          assert(note.includes('fetched 2026-10-28'), note);
          assert(note.includes('1 idea already in this draft isn\'t listed.'), note);
          assert(note.includes('1 USD = 1.43 AUD (ECB rate of 2026-10-27), prices pulled 2026-10-28'), note);
          const sides = ac.list.querySelectorAll('.ac-side').map((n) => n.textContent);
          assert(sides[0].includes('64% of decks') && sides[0].includes('2 free') && sides[0].includes('1 on the way'), sides[0]);
          assert(sides[1].includes('To buy · ~A$0.39'), sides[1]);
          assert(sides[2].includes('In other decks') && !sides[2].includes('deck:'), sides[2]);
          // The typed name narrows them here, without asking again; so do the filters.
          ac.input.value = 'elvish'; ac.input.fire('input'); await settle();
          same(names(ac), ['Elvish Mystic']);
          ac.input.value = ''; ac.input.fire('input'); ac.type = 'land'; refilter(ac); await settle();
          same(names(ac), ['Bojuka Bog']);
          ac.type = ''; refilter(ac); await settle();
          assert.equal(edhrecAsks(), 1, 'asked once for this deck revision');
          // Adding changes only the draft (one change), in the section chosen.
          ac.list.querySelectorAll('.ac-add')[0].click();
          assert.equal(changes, 1);
          same(editor.lists.Deck.map((l) => [l.name, l.qty]), [['Elvish Mystic', 1], ['Llanowar Elves', 1]]);
          assert.equal('edhrec' in editor.lists.Deck[0].card, false, 'the idea itself is not kept on the line');
          editor.addSection = 'Sideboard';
          ac.list.querySelectorAll('.ac-add')[1].click();
          same(editor.lists.Sideboard.map((l) => [l.name, l.qty]), [['Pick Your Poison', 1]]);
          await settle();
          assert.equal(writes.length, 0, 'nothing is saved until Save');
          assert.equal(asked.filter((path) => !path.startsWith('/api/deck/edhrec')).length, 0);
        """)

    def test_more_shows_every_idea_once_when_the_draft_changes_between_pages(self):
        self.run_js(r"""
          const many = ANSWER();
          many.groups = [{header: 'Top Cards', cards: Array.from({length: 30}, (_, i) => idea(`Card ${i + 1}`, 90 - i))}];
          answer = many;
          const order = (ac) => names(ac).map((n) => Number(n.split(' ')[1]));
          // Adding an idea from the first page doesn't make More skip the 25th.
          let ac = commanderEditor();
          tick(ac); await settle();
          assert.equal(ac.items.length, 24, '24 at a time');
          assert(!ac.more.hidden, 'More is offered');
          ac.list.querySelectorAll('.ac-add')[0].click();
          assert(editor.lists.Deck.some((l) => l.name === 'Card 1'));
          ac.more.click(); await settle();
          same(order(ac), Array.from({length: 30}, (_, i) => i + 1), 'every idea once, in EDHREC order');
          assert(ac.more.hidden, 'nothing more to show');
          // Taking a card out of the draft between pages shows it after, never one already listed again.
          ac = commanderEditor({}, {Commander: [{...ghalta}], Deck: [{uid: 'd3', name: 'Card 3', qty: 1}]});
          tick(ac); await settle();
          same(order(ac), [1, 2, ...Array.from({length: 22}, (_, i) => i + 4)]);
          editor.lists.Deck = [];
          ac.more.click(); await settle();
          const seen = order(ac);
          assert.equal(new Set(seen).size, seen.length, 'no idea twice: ' + seen);
          same([...seen].sort((a, b) => a - b), Array.from({length: 30}, (_, i) => i + 1));
          assert(ac.more.hidden);
          assert.equal(edhrecAsks(), 2, 'More asks EDHREC nothing new');
        """)

    def test_a_viewer_the_server_sent_no_marks_sees_no_owned_words(self):
        self.run_js(r"""
          answer = ANSWER(false);
          const ac = commanderEditor();
          tick(ac); await settle();
          same(names(ac), ['Elvish Mystic', 'Pick Your Poison', 'Bojuka Bog']);
          const sides = ac.list.querySelectorAll('.ac-side').map((n) => n.textContent).join(' | ');
          for (const words of ['free', 'To buy', 'In other decks', 'on the way', 'A$']) assert(!sides.includes(words), sides);
          assert(ac.note.textContent.includes("This deck's collection isn't yours to see"));
          assert(!ac.note.textContent.includes('1 USD'));
        """)

    def test_ideas_follow_the_draft_commander_without_a_save(self):
        self.run_js(r"""
          const edhrecPaths = () => asked.filter((path) => path.startsWith('/api/deck/edhrec'));
          const omnath = {uid: 'c2', name: 'Omnath, Locus of Mana', qty: 1};
          let ac = commanderEditor({}, {Commander: [{...omnath}], Deck: []});
          tick(ac); await settle();
          assert(edhrecPaths()[0].endsWith('&commander=Omnath%2C%20Locus%20of%20Mana'), edhrecPaths()[0]);
          assert.equal(ac.items.length, 4, 'the changed commander ideas show with no save (its empty Deck has no Llanowar Elves)');
          assert(!ac.list.textContent.includes('Save the deck'), ac.list.textContent);
          // The commander changing in the draft while ideas show asks again, for the new one.
          ac = commanderEditor();
          tick(ac); await settle();
          assert.equal(ac.items.length, 3);
          const before = edhrecAsks();
          editor.lists.Commander = [];
          syncEditorSearchQuantities(ac); await settle();
          assert.equal(ac.items.length, 0);
          assert(ac.list.textContent.includes('Put a commander in the Commander section'), ac.list.textContent);
          assert.equal(edhrecAsks(), before, 'no commander: nothing asked');
          editor.lists.Commander = [{...ghalta}, {uid: 'c3', name: 'Tymna the Weaver', qty: 1}];
          syncEditorSearchQuantities(ac); await settle();
          const pair = edhrecPaths().at(-1);
          assert(pair.includes('&commander=Ghalta%2C%20Primal%20Hunger&commander2=Tymna%20the%20Weaver'), pair);
          assert.equal(ac.items.length, 3);
          editor.lists.Commander.push({uid: 'c4', name: 'Thrasios, Triton Hero', qty: 1});
          syncEditorSearchQuantities(ac); await settle();
          assert(ac.list.textContent.includes('one commander or a pair'), ac.list.textContent);
          assert.equal(edhrecPaths().at(-1), pair, 'three commanders: nothing asked');
          // A commander the server refuses says so; putting another in asks again.
          answer = new ApiError(400, "Not A Card isn't a card Deck Lab knows, so EDHREC has no ideas for it.");
          editor.lists.Commander = [{uid: 'c5', name: 'Not A Card', qty: 1}];
          syncEditorSearchQuantities(ac); await settle();
          assert(ac.list.textContent.includes("Not A Card isn't a card Deck Lab knows"), ac.list.textContent);
          assert(!ac.list.querySelectorAll('button').some((b) => b.textContent === 'Try again'));
          answer = ANSWER();
          const asks = edhrecAsks();
          editor.lists.Commander = [{...ghalta}];
          syncEditorSearchQuantities(ac); await settle();
          assert.equal(ac.items.length, 3, 'Ghalta is asked again and its ideas show');
          assert.equal(edhrecAsks(), asks + 1, 'only the last request is kept, so Ghalta is asked once more');
          assert.equal(writes.length, 0);
        """)

    def test_a_late_answer_for_an_old_scope_revision_or_commander_is_ignored(self):
        self.run_js(r"""
          let ac = commanderEditor();
          hold = deferred();
          tick(ac); await settle();
          assert(ac.list.textContent.includes('Asking EDHREC…'));
          tick(ac, false);                      // back to the plain search before the answer
          hold.resolve(ANSWER()); hold = null; await settle();
          assert.equal(ac.items.length, 0, 'the answer came after the scope changed');
          assert(ac.note.hidden);
          // A save (a new revision) before the answer: that answer is never shown, and the new one is asked.
          ac = commanderEditor();
          hold = deferred();
          tick(ac); await settle();
          editor.sha256 = 'c'.repeat(64);
          const first = hold; hold = null;
          refilter(ac); await settle();
          first.resolve(ANSWER(true, ['Someone Else'])); await settle();
          same(names(ac), ['Elvish Mystic', 'Pick Your Poison', 'Bojuka Bog']);
          // Another editor (another deck or profile) makes the old search's answer count for nothing.
          ac = commanderEditor();
          hold = deferred();
          tick(ac); await settle();
          const old = ac; const late = hold; hold = null;
          const fresh = commanderEditor({id: 'commander/other'});
          late.resolve(ANSWER()); await settle();
          assert.equal(old.items.length, 0);
          assert.equal(fresh.items.length, 0);
          // The draft's commander changing before the answer: the old commander's ideas never show,
          // and the new commander is asked for.
          ac = commanderEditor();
          hold = deferred();
          tick(ac); await settle();
          const ghaltas = hold; hold = null;
          const asks = edhrecAsks();
          answer = ANSWER(true, ['Omnath, Locus of Mana']);
          answer.groups = [{header: 'Top Cards', cards: [idea('Omnath Idea', 50)]}];
          editor.lists.Commander = [{uid: 'c2', name: 'Omnath, Locus of Mana', qty: 1}];
          syncEditorSearchQuantities(ac); await settle();
          assert.equal(edhrecAsks(), asks + 1, 'the new commander is asked for');
          assert(asked.at(-1).endsWith('&commander=Omnath%2C%20Locus%20of%20Mana'), asked.at(-1));
          ghaltas.resolve(ANSWER()); await settle();
          same(names(ac), ['Omnath Idea'], 'the late answer for Ghalta is not shown');
        """)

    def test_a_failure_is_said_in_edhrecs_words_and_the_search_still_works(self):
        self.run_js(r"""
          answer = new ApiError(502, "EDHREC can't be reached (timed out). Try again later: nothing else on the page needs it.");
          const ac = commanderEditor();
          tick(ac); await settle();
          const text = ac.list.textContent;
          assert(text.includes("EDHREC ideas couldn't be loaded. EDHREC can't be reached (timed out)."), text);
          const again = ac.list.querySelectorAll('button').find((b) => b.textContent === 'Try again');
          assert(again, 'a 502 can be tried again');
          answer = ANSWER();
          again.click(); await settle();
          assert.equal(edhrecAsks(), 2);
          assert.equal(ac.items.length, 3);
          // No page for this commander: its own words, and nothing to try again.
          answer = new ApiError(404, 'EDHREC has no page for this commander yet, so there are no ideas to show.');
          const none = commanderEditor();
          tick(none); await settle();
          assert(none.list.textContent.includes('EDHREC has no page for this commander yet'));
          assert(!none.list.querySelectorAll('button').some((b) => b.textContent === 'Try again'));
          // The rest of the Add panel goes on: back to the search, whose results add as before.
          tick(none, false); await settle();
          none.input.value = 'Alpha'; none.input.fire('input'); await settle();
          const finds = asked.filter((path) => path.startsWith('/api/deck/find'));
          assert.equal(finds.length, 1, 'the plain search asks /api/deck/find again');
          assert(finds[0].includes('q=Alpha'), finds[0]);
          same(names(none), ['Alpha']);
          none.list.querySelector('.ac-add').click();
          same(editor.lists.Deck.map((l) => l.name), ['Alpha', 'Llanowar Elves']);
          assert.equal(edhrecAsks(), 3, 'the plain search never asks EDHREC');
        """)


if __name__ == "__main__":
    unittest.main()
