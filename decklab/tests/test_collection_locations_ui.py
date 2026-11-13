"""Storage locations (E8-S22) and the storage box's count (E8-S19) on the Collection page and Build
decks, over the real scripts with fixture answers (no network)."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  const original = {name: 'Llanowar Elves', set: 'fdn', collector_number: '227', finish: 'nonfoil', quantity: 4,
    condition: 'NM', language: 'en', notes: ''};
  const located = {ready: true, rows: {'fdn|227|nonfoil': 'Row 2, B'}};
  const storage = {rows: {'fdn|227|nonfoil': {held: 1, guess: false}}, error: null};
  const draw = (data = {}) => { as('matt', MAY.admin);
    return drawCollectionRows({space: 'home', sha256: 's1', rows: [original], editable: true, storage,
      locations: located, storage_box: {cards: 3, capacity: 2400, over: false, not_counted: 0}, ...data}, 'home'); };
  const sheet = async (cv) => {
    api = async () => ({name: original.name, printings: [{set: 'fdn', set_name: 'Foundations',
      collector_number: '227', finishes: ['nonfoil'], released: '2024'}]});
    const ctx = openCollectionSheet(cv, original); await flush(); return ctx;
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionLocationsUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_rows_show_their_location_and_the_box_count(self):
        self.run_js("""
          const cv = draw();
          assert.equal(colStorageWords(cv, original), '1 copy in decks \\u00b7 3 free \\u00b7 Row 2, B');
          const note = main.querySelector('.col-storage-box');
          assert(!note.hidden); assert(note.textContent.includes('about 3 of'), note.textContent);
          draw({storage_box: {cards: 2500, capacity: 2400, over: true, not_counted: 2}});
          const over = main.querySelector('.col-storage-box');
          assert(over.className.includes('box-warn'));
          assert(over.textContent.includes('over capacity')); assert(over.textContent.includes('Basic lands (2 cards)'));
          draw({storage_box: {cards: 2, capacity: 2400, over: false, not_counted: 0, elsewhere: 1}});
          assert(main.querySelector('.col-storage-box').textContent.includes("box's rows (1 card, such as in a binder)"));
          draw({storage_box: null}); assert(main.querySelector('.col-storage-box').hidden);
        """)

    def test_the_card_sheet_sends_a_changed_location_only(self):
        self.run_js("""
          const cv = draw(); let ctx = await sheet(cv);
          const input = ctx.location.input;
          assert.equal(input.value, 'Row 2, B'); assert(!input.disabled);
          const options = ctx.location.list.querySelectorAll('option').map(o => o.getAttribute('value'));
          same(options, ['Row 1', 'Row 2', 'Row 3', 'Row 4', 'Row 2, B']);
          const calls = [];
          apiWrite = async (path, body) => { calls.push(body);
            return {ok: true, sha256: 's2', rows: [original],
              locations: {ready: true, rows: {'fdn|227|nonfoil': body.location ?? 'Row 2, B'}}}; };
          ctx.inputs.quantity.value = '4';
          await saveCollectionSheet(ctx); await flush();
          assert.equal(calls.length, 1); assert(!Object.hasOwn(calls[0], 'location'));
          ctx = await sheet(cv);
          ctx.location.input.value = '  Binder '; ctx.location.input.fire('input');
          await saveCollectionSheet(ctx); await flush();
          assert.equal(calls[1].location, 'Binder');
          assert.equal(colLocationOf(cv, original), 'Binder');
        """)

    def test_without_the_migration_the_field_is_off_and_says_why(self):
        self.run_js("""
          const cv = draw({locations: {ready: false, rows: {}}}); const ctx = await sheet(cv);
          assert(ctx.location.input.disabled);
          assert(ctx.location.hint.textContent.includes('database needs updating'));
          const calls = []; apiWrite = async (path, body) => { calls.push(body); return {ok: true, sha256: 's2', rows: [original]}; };
          ctx.inputs.quantity.value = '5'; await saveCollectionSheet(ctx); await flush();
          assert.equal(calls.length, 1); assert(!Object.hasOwn(calls[0], 'location'));
        """)

    def test_the_storage_setup_draws_one_line_per_container(self):
        self.run_js("""
          const box = {id: 'box', name: 'Storage box', kind: 'box', capacity: 2400, sleeved: false, cards: 3, over: false};
          const binder = {id: 'binder', name: 'Binder', kind: 'binder', capacity: 360, sleeved: true, cards: 310, over: false};
          const setup = (containers, extra = {}) => ({storage_setup: {source: 'saved', default: 'box', containers,
            elsewhere: 0, unplaced: 0, not_counted: 0, suggestions: ['Row 1', 'Binder'], ...extra}});
          draw(setup([box]));
          let note = main.querySelector('.col-storage-box');
          assert.equal(note.textContent,
            `Storage box: about 3 of ${num(2400)} cards (the copies not in built decks or products kept intact).`);
          draw(setup([box, binder, {...binder, id: 'shelf', name: 'Shelf', capacity: null, cards: 12}], {elsewhere: 2}));
          note = main.querySelector('.col-storage-box');
          const lines = note.querySelectorAll('.col-storage-line').map(span => span.textContent);
          same(lines.slice(0, 3), [`Storage box: about 3 of ${num(2400)} cards.`, 'Binder: about 310 of 360 cards.',
            'Shelf: about 12 cards.']);
          assert(lines[3].includes("somewhere that isn't one of these (2 cards)"), lines[3]);
          assert(!note.className.includes('box-warn'));
          draw(setup([box, {...binder, cards: 400, over: true}]));
          note = main.querySelector('.col-storage-box');
          assert(note.className.includes('box-warn'));
          assert(note.textContent.includes('Binder is over capacity: about 400 cards for about 360 places.'));
          draw(setup([])); assert(main.querySelector('.col-storage-box').hidden);
          draw(setup([{...box, cards: null}])); assert(main.querySelector('.col-storage-box').hidden);
          draw({storage_setup: {containers: 'bad'}});              // a bad answer falls back to storage_box
          assert(main.querySelector('.col-storage-box').textContent.includes('about 3 of'));
        """)

    def test_suggestions_follow_the_setup_and_a_member_gets_no_home_rows(self):
        self.run_js("""
          let cv = draw({storage_setup: {source: 'saved', default: 'binder', containers: [], elsewhere: 0, unplaced: 0,
            not_counted: 0, suggestions: ['Page 1', 'Page 2']}});
          same(colLocationChoices(cv), ['Page 1', 'Page 2', 'Row 2, B']);
          assert.equal(colLocationExample(cv), 'Such as Page 2, B or Binder');
          cv = draw({storage_setup: {source: 'none', default: null, containers: [], elsewhere: 0, unplaced: 0,
            not_counted: 0, suggestions: []}});
          same(colLocationChoices(cv), ['Row 2, B']);
          assert.equal(colLocationExample(cv), 'Such as Binder or Shelf 2');
          same(colLocationChoices({space: 'user2', locations: {rows: {}}}), []);     // an older server
          same(colLocationChoices({space: 'home', locations: {rows: {}}}), ['Row 1', 'Row 2', 'Row 3', 'Row 4']);
        """)

    def test_packing_tiles_name_where_cards_are_kept(self):
        self.run_js("""
          const view = {data: {storage_locations: {ready: true, cards: {'Llanowar Elves': ['Row 2, B', 'Binder']}}}};
          assert.equal(packLocationMeta(view, 'Llanowar Elves'), 'Row 2, B \\u00b7 Binder');
          assert.equal(packLocationMeta(view, 'Shock'), null);
          assert.equal(packLocationNote(view), null);
          const off = packLocationNote({data: {storage_locations: {ready: false, cards: {}}}});
          assert(off.textContent.includes('database needs updating'));
        """)


if __name__ == "__main__":
    unittest.main()
