"""The Matchups tab's free replacements for cards never cast (E3-S25, deck-swaps.js neverCastReplacements) under
Node: "How its cards played" asks GET /api/deck/replacements for each spell its games drew and never cast, only
for a visitor who may see the deck's space's collection (nothing on a refusal), and "Test this swap" opens the
editor with the swap as its draft and its Test this change sheet (variant.js vtOpenTestFromRoute).

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js; nothing is sent to a server.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  const shock = card('Shock', 'Instant', 1, ['R']);
  const statRow = (name, extra) => ({name, qty: 3, land: false, drawn_games: 50, copies_drawn: 60, cast: 0,
    other_casts: 0, stuck: 60, stuck_share: 1, judged: false, ...extra});
  const matchups = {results: [{sides: [{current: true}]}], cards: {games: 900, of: 900, bad: 0, old: 0, enough: true,
    min_split: 30, commander: [], rows: [statRow('Bolt'), statRow('Elf', {cast: 40, stuck: 2, stuck_share: 0.03}),
      statRow('Wastes', {land: true})]}};
  const replacements = {deck_id: 'casual/test', version: 'target', kind: 'casual', colours: ['G', 'R'], warnings: [],
    rate: 1.43, rate_date: '2026-10-12', price_date: '2026-10-12',
    card: {name: 'Bolt', qty: 3, card: bolt, type: 'instant', colours: ['R'], mv: 1},
    candidates: [{name: 'Shock', card: shock, default: {set: 'm21', number: '159', finish: 'nonfoil', why: 'owned'},
      free: 2, here: 2, max_qty: 2, basic: false, aud: 0.2,
      note: {severity: 0, words: 'Close to even', text: 'Close to even: the same job.'}}], more: 3};
  const editView = {id: 'casual/test', title: 'Test Deck', sha256: 'abc', fields: {status: 'building', player: 'user'},
    lists: {target: {Deck: [{qty: 2, name: 'Bolt', set: 'fdn', number: '3', card: bolt},
      {qty: 1, name: 'Bolt', set: 'm21', number: '4', card: bolt}, {qty: 20, name: 'Forest', card: forest}]}, owned: null}};
  const stored = {};
  window.localStorage = {getItem: (k) => stored[k] ?? null, setItem: (k, v) => { stored[k] = String(v); },
    removeItem: (k) => { delete stored[k]; }};
  const calls = [];
  let refuse = null;
  api = async (path) => {
    calls.push(path);
    if (path.startsWith('/api/deck/edit')) return editView;
    if (refuse) throw new ApiError(refuse, 'No.');
    return replacements;
  };
  const settle = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };
  const asked = () => calls.filter((p) => p.startsWith('/api/deck/replacements'));
  const draw = (page = makePage()) => { clear(main); main.append(el('div', {}, deckCardStats(matchups, 'list', {data: page}))); };
  const boxes = () => main.querySelectorAll('.mu-replace');
  const draftKeyOf = 'draft.matt.casual/test.target';
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckReplacementsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_a_spell_never_cast_gets_its_free_replacements(self):
        self.run_js("""
          const page = makePage();
          draw(page); await settle();
          // Only the spell drawn and never cast: not the one cast, not the land never played.
          same(asked(), ['/api/deck/replacements?id=casual%2Ftest&version=target&card=Bolt']);
          same(boxes().length, 1);
          const text = boxes()[0].textContent;
          assert(text.includes('Free replacements:'), text);
          assert(text.includes('Instant, red, mana value 0–2'), text);
          assert(text.includes('Shock'));
          assert(text.includes('Close to even: the same job.'));
          assert(text.includes('2 free'));
          assert(text.includes('3 more cards fit; these are the closest.'));
          assert(!text.includes('On the way'));
          const test = boxes()[0].querySelectorAll('button').find((b) => b.textContent === 'Test this swap');
          assert.equal(test.getAttribute('aria-label'), 'Test Shock for Bolt');
          // Asked once per list on screen: drawing the tab again uses the same answer.
          draw(page); await settle();
          same(asked().length, 1);
          // The Play-now list asks for its own.
          const owned = makePage(); owned.version = 'owned';
          draw(owned); await settle();
          same(asked().at(-1), '/api/deck/replacements?id=casual%2Ftest&version=owned&card=Bolt');
          // A card on the way says so; none fitting says what it looked for.
          replacements.candidates[0].here = 0; replacements.more = 0;
          draw(makePage()); await settle();
          assert(boxes()[0].textContent.includes('On the way'));
          assert(boxes()[0].textContent.includes('2 on the way'));
          replacements.candidates = [];
          draw(makePage()); await settle();
          same(boxes()[0].textContent, 'No free card in the pool fits its slot (Instant, red, mana value 0–2).');
          assert.equal(boxes()[0].querySelectorAll('button').length, 0);
          // Without the deck page's answer (the matchup screens), nothing is asked.
          calls.length = 0; clear(main); main.append(el('div', {}, deckCardStats(matchups, 'list')));
          await settle(); same(calls, []); same(boxes().length, 0);
        """)

    def test_nothing_without_the_collection_or_on_a_refusal(self):
        self.run_js("""
          // A visitor who may not see the deck's space's inventory: nothing asked, nothing shown.
          state.may = {see_inventory: ['user2'], deck_spaces: ['user2']};
          draw(); await settle();
          same(asked(), []); same(boxes().length, 0);
          assert(main.textContent.includes('Drawn, never cast'));
          state.may = null;
          const hidden = makePage(); delete hidden.owned;
          draw(hidden); await settle();
          same(asked(), []); same(boxes().length, 0);
          for (const id of ['product/fdc-test', 'pairing/a+b']) {
            const other = makePage(); other.summary.id = id;
            draw(other); await settle();
            same(asked(), []);
          }
          // A refusal shows nothing (no reason, no error box), and isn't kept.
          for (const status of [403, 404, 400]) {
            refuse = status; calls.length = 0;
            draw(); await settle();
            same(asked().length, 1); same(boxes().length, 0);
            assert(!main.textContent.includes("couldn't be loaded"));
            assert(!main.textContent.includes('No.'));
          }
          // Any other failure says so, with Try again, which asks again.
          refuse = 500; calls.length = 0;
          draw(); await settle();
          assert(boxes()[0].textContent.includes("Free replacements couldn't be loaded."));
          refuse = null;
          boxes()[0].querySelectorAll('button').find((b) => b.textContent === 'Try again').click();
          await settle();
          same(asked().length, 2);
          assert(boxes()[0].textContent.includes('Shock'));
          // The profile changed before the answer came: the answer isn't shown to the new one.
          const page = makePage(); calls.length = 0;
          draw(page);
          state.profile = {id: 'user1', name: 'User1', plays_as: 'wife'};
          await settle();
          same(boxes().length, 0);
        """)

    def test_test_this_swap_opens_the_editor_with_the_swap(self):
        self.run_js("""
          draw(); await settle();
          const button = () => boxes()[0].querySelectorAll('button').find((b) => b.textContent === 'Test this swap');
          button().click(); await settle();
          assert(calls.includes('/api/deck/edit?id=casual%2Ftest'));
          assert.equal(location.hash, '#/edit?id=casual%2Ftest&v=target&test=change');
          const draft = JSON.parse(local.get(draftKeyOf));
          same(draft.sha256, 'abc');
          same(draft.base.lists, editView.lists.target);
          // max_qty 2 of the 3 Bolts, off the first lines, and 2 Shock in its default printing.
          same(draft.lists.Deck.map((l) => [l.qty, l.name, l.set || null, l.number || null]),
               [[1, 'Bolt', 'm21', '4'], [20, 'Forest', null, null], [2, 'Shock', 'm21', '159']]);
          // A draft already there: asked first, and kept when the answer is Keep.
          local.set(draftKeyOf, '{"v": 1, "mine": true}');
          const asks = [];
          ask = async (title, words) => { asks.push(title, words[0]); return 'keep'; };
          location.hash = '#/deck?id=casual%2Ftest&tab=matchups';
          button().click(); await settle();
          same(asks, ['Replace your unsaved changes?', 'Replace your unsaved changes to Test Deck with this swap?']);
          same(local.get(draftKeyOf), '{"v": 1, "mine": true}');
          assert.equal(location.hash, '#/deck?id=casual%2Ftest&tab=matchups');
          ask = async () => 'replace';
          button().click(); await settle();
          same(JSON.parse(local.get(draftKeyOf)).lists.Deck.at(-1).name, 'Shock');
          // The card left the list since: said, and no draft or editor.
          local.remove(draftKeyOf);
          editView.lists.target.Deck = [{qty: 20, name: 'Forest', card: forest}];
          const toasts = []; toast = (m) => toasts.push(m);
          location.hash = '#/deck?id=casual%2Ftest&tab=matchups';
          button().click(); await settle();
          same(toasts, ["Bolt isn't in the planned list any more."]);
          same(local.get(draftKeyOf), null);
          assert.equal(location.hash, '#/deck?id=casual%2Ftest&tab=matchups');
        """)

    def test_test_this_swap_stops_when_the_draft_cant_be_kept_or_the_page_changed(self):
        self.run_js("""
          draw(); await settle();
          const button = () => boxes()[0].querySelectorAll('button').find((b) => b.textContent === 'Test this swap');
          const toasts = []; toast = (m) => toasts.push(m);
          const start = '#/deck?id=casual%2Ftest&tab=matchups';
          // The draft can't be stored (storage full or blocked): said, and no editor on an older draft.
          local.set(draftKeyOf, '{"v": 1, "mine": true}');
          ask = async () => 'replace';
          const setItem = window.localStorage.setItem;
          window.localStorage.setItem = () => { throw new Error('QuotaExceededError'); };
          location.hash = start;
          button().click(); await settle();
          same(toasts, ["The swap couldn't be kept on this device, so it can't be tested. Make it in the editor instead."]);
          same(local.get(draftKeyOf), '{"v": 1, "mine": true}');
          assert.equal(location.hash, start);
          window.localStorage.setItem = setItem;
          local.remove(draftKeyOf);
          // Left the page, or switched profile, while the list loaded: no draft, no editor.
          let release; const loading = () => new Promise((r) => { release = () => r(editView); });
          api = (path) => { calls.push(path); return loading(); };
          button().click();
          location.hash = '#/library'; release(); await settle();
          same(local.get(draftKeyOf), null);
          assert.equal(location.hash, '#/library');
          location.hash = start;
          button().click();
          state.profile = {id: 'user1', name: 'User1', plays_as: 'wife'}; release(); await settle();
          same(local.get(draftKeyOf), null); same(local.get('draft.user1.casual/test.target'), null);
          assert.equal(location.hash, start);
          state.profile = {id: 'matt', name: 'Matt', plays_as: 'user'};
          // A second click while the first is loading starts nothing more.
          calls.length = 0;
          button().click(); button().click();
          same(calls.filter((p) => p.startsWith('/api/deck/edit')).length, 1);
          assert(button().disabled);
          release(); await settle();
          assert(!button().disabled);
          assert.equal(location.hash, '#/edit?id=casual%2Ftest&v=target&test=change');
          same(toasts.length, 1);
        """)

    def test_the_editor_opens_from_test_this_swap_with_its_test_sheet(self):
        self.run_js("""
          // End to end: the swap's draft and address, then the real editor route restoring that draft.
          draw(); await settle();
          boxes()[0].querySelectorAll('button').find((b) => b.textContent === 'Test this swap').click();
          await settle();
          const hash = '#/edit?id=casual%2Ftest&v=target&test=change';
          assert.equal(location.hash, hash);
          let opened = 0; const toasts = [];
          vtOpenTestSheet = () => { opened += 1; };
          toast = (m) => toasts.push(m);
          history.replaceState = (s, t, url) => { if (url !== undefined) location.hash = new URL(url, 'http://localhost/').hash; };
          load = (path, token, ready) => ready({...structuredClone(editView), space: 'home', kind: 'casual',
            sections: ['Deck', 'Sideboard'], editable: true, may_save: true, field_text: {}, prose: {notes: ''}});
          clear(main);
          showEditor(new URLSearchParams(location.hash.split('?')[1]), routeToken);
          await settle();
          same([opened, toasts], [1, []]);
          assert.equal(editor.lists.Deck.find((l) => l.name === 'Shock').qty, 2);
          assert.equal(location.hash, '#/edit?id=casual%2Ftest&v=target');
        """)

    def test_the_swap_list(self):
        self.run_js("""
          const sections = {Deck: [{qty: 1, name: 'Bolt', set: 'fdn', number: '3'}, {qty: 1, name: 'Shock', set: 'm21', number: '159'},
            {qty: 20, name: 'Forest'}], Sideboard: [{qty: 2, name: 'Bolt'}]};
          const shockCandidate = {name: 'Shock', max_qty: 3, default: {set: 'm21', number: '159', finish: 'nonfoil'}};
          // Only the copies the Deck section still has; added on the line of the same printing; the sideboard untouched.
          const out = replacementSwapList(sections, 'bolt', shockCandidate);
          same(out, {Deck: [{qty: 2, name: 'Shock', set: 'm21', number: '159'}, {qty: 20, name: 'Forest'}],
            Sideboard: [{qty: 2, name: 'Bolt'}]});
          same(sections.Deck[0].qty, 1);                     // the saved list itself is unchanged
          // A foil default gets its finish; none, a bare line.
          same(replacementSwapList(sections, 'Bolt', {name: 'Spark', max_qty: 1, default: {set: 'x', number: '1', finish: 'foil'}})
            .Deck.at(-1), {qty: 1, name: 'Spark', card: null, set: 'x', number: '1', finish: 'foil'});
          same(replacementSwapList(sections, 'Bolt', {name: 'Spark', max_qty: 1, default: null}).Deck.at(-1),
            {qty: 1, name: 'Spark', card: null});
          same(replacementSwapList(sections, 'Lightning Bolt', shockCandidate), null);
          same(replacementSwapList({Sideboard: [{qty: 1, name: 'Bolt'}]}, 'Bolt', shockCandidate), null);
        """)

    def test_the_editor_opens_the_test_sheet_from_the_address(self):
        self.run_js("""
          let opened = 0; const toasts = [], hashesSeen = [];
          vtOpenTestSheet = () => { opened += 1; };
          toast = (m) => toasts.push(m);
          history.replaceState = (s, t, hash) => { hashesSeen.push(hash); location.hash = hash; };
          const deck = [{qty: 3, name: 'Bolt'}, {qty: 20, name: 'Forest'}];
          const swapped = [{qty: 1, name: 'Bolt'}, {qty: 20, name: 'Forest'}, {qty: 2, name: 'Shock'}];
          const hash = '#/edit?id=casual%2Ftest&v=target&test=change';
          const start = (lists, extra = {}) => {
            location.hash = hash;
            editor = {mode: 'edit', id: 'casual/test', version: 'target', kind: 'casual', hasFileList: true,
              entryHash: hash, base: {lists: {Deck: deck}}, lists, fields: {kind: 'casual'}, ...extra};
          };
          start({Deck: swapped});
          vtOpenTestFromRoute(new URLSearchParams('id=casual/test&v=target&test=change'), 'casual/test');
          same([opened, hashesSeen], [1, ['#/edit?id=casual%2Ftest&v=target']]);
          // A draft that no longer tests (the size changed): the reason, no sheet.
          start({Deck: [{qty: 20, name: 'Forest'}, {qty: 2, name: 'Shock'}]});
          vtOpenTestFromRoute(new URLSearchParams('id=casual/test&test=change'), 'casual/test');
          same([opened, toasts], [1, ['Keep the same number of cards to test a change']]);
          // Without test=change, for another deck, or an editor that isn't this address's: nothing.
          start({Deck: swapped});
          vtOpenTestFromRoute(new URLSearchParams('id=casual/test'), 'casual/test');
          vtOpenTestFromRoute(new URLSearchParams('id=casual/test&test=change'), 'casual/other');
          start({Deck: swapped}, {entryHash: '#/edit?id=casual%2Ftest&v=owned&test=change'});
          vtOpenTestFromRoute(new URLSearchParams('id=casual/test&test=change'), 'casual/test');
          same([opened, hashesSeen.length], [1, 2]);
        """)


if __name__ == "__main__":
    unittest.main()
