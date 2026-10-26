"""P1 Collection columns project existing card/storage metadata without new reads."""
import json
import re
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_device_layout_ui import IPAD_LANDSCAPE, MACBOOK, _tokens_on
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  const row = (name, number, extra = {}) => ({name, set: 'fdn', collector_number: String(number),
    finish: 'nonfoil', quantity: 1, condition: 'NM', language: 'en', notes: '', ...extra});
  const rows = [row('Alpha', 1, {finish: 'foil', quantity: 4}), row('Colourless', 2, {finish: 'etched', quantity: 2}),
    row('Mystery', 3, {condition: '', language: ''}), row('Forest', 4, {quantity: 3})];
  const card = (name, number, extra = {}) => ({name, type_line: 'Creature - Elf Druid', cmc: 1, mana_cost: '{G}',
    oracle_text: '', colors: ['R'], color_identity: ['U', 'G'], img: '/img/fdn/' + number + '/normal',
    img_small: '/img/fdn/' + number + '/small', exact: true, ...extra});
  const pictures = {'fdn|1|foil': card('Alpha', 1),
    'fdn|2|etched': card('Colourless', 2, {colors: [], color_identity: [], type_line: 'Artifact'}),
    'fdn|3|nonfoil': card('Mystery', 3, {colors: undefined, color_identity: undefined, type_line: undefined}),
    'fdn|4|nonfoil': card('Forest', 4, {colors: [], color_identity: ['G'], type_line: 'Basic Land - Forest'})};
  const storage = {rows: {'fdn|1|foil': {held: 3, guess: true}, 'fdn|4|nonfoil': {held: null, guess: false}}, error: null};
  const draw = (data = {}) => { as('matt', MAY.admin); clear(main);
    return drawCollectionRows({space: 'home', sha256: 's1', rows, pictures, storage, editable: true, ...data}, 'home'); };
  const table = () => main.querySelector('.col-table');
  const record = key => table().querySelectorAll('tr').find(tr => tr.getAttribute('data-key') === key);
  const cell = (key, cls) => record(key).querySelector('.col-td-' + cls);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionColumnsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "ok")

    def test_columns_stay_real_table_columns_in_the_promised_order(self):
        self.run_js("""
          draw(); assert.equal(table().tag, 'table');
          const headers = table().querySelectorAll('th');
          assert(['Name', 'Card'].includes(headers[1].textContent.trim()));
          same(headers.slice(2).map(node => node.textContent.trim()), ['Colour identity', 'Type', 'Printing', 'Finish',
            'Copies', 'Condition', 'Language', 'In decks', '~A$ each', 'Notes']);
          assert(headers.every(node => node.getAttribute('scope') === 'col'));
          for (const key of rows.map(colKey)) {
            for (const cls of ['colour', 'type', 'printing', 'finish', 'qty', 'condition', 'language', 'held', 'price']) {
              assert.equal(cell(key, cls).tag, 'td', cls);
            }
          }
        """)

    def test_colour_is_identity_not_card_colour_and_unknown_is_not_colourless(self):
        self.run_js("""
          draw(); const multi = cell('fdn|1|foil', 'colour').querySelector('.id-pips');
          assert.equal(multi.getAttribute('role'), 'img');
          assert(multi.getAttribute('class').split(' ').includes('id-pips-sm'));
          same(multi.querySelectorAll('.id-pip').map(node => node.textContent), ['U', 'G']);
          assert(multi.getAttribute('aria-label').includes('blue')); assert(multi.getAttribute('aria-label').includes('green'));
          assert(!multi.getAttribute('aria-label').includes('red'));
          const colourless = cell('fdn|2|etched', 'colour').querySelector('.id-pips');
          same(colourless.querySelectorAll('.id-pip').map(node => node.textContent), ['C']);
          assert(colourless.getAttribute('aria-label').includes('Colourless'));
          const unknown = cell('fdn|3|nonfoil', 'colour');
          assert.equal(unknown.querySelector('.id-pips'), null);
          assert.equal(unknown.querySelector('.cell-unknown').getAttribute('aria-hidden'), 'true');
          assert(unknown.querySelector('.sr-only').textContent.includes('Colour identity not recorded'));
        """)

    def test_type_and_finish_have_their_own_cells_and_do_not_expand_copy_counts(self):
        self.run_js("""
          draw(); const type = cell('fdn|1|foil', 'type').querySelector('.col-type-text');
          assert.equal(type.textContent, 'Creature - Elf Druid'); assert.equal(type.getAttribute('title'), type.textContent);
          const missing = cell('fdn|3|nonfoil', 'type');
          assert.equal(missing.querySelector('.cell-unknown').getAttribute('aria-hidden'), 'true');
          assert(missing.querySelector('.sr-only').textContent.includes('Type not recorded'));
          for (const [key, words] of [['fdn|1|foil', 'Foil'], ['fdn|2|etched', 'Etched']]) {
            const finish = cell(key, 'finish').querySelector('.chip-foil'); assert.equal(finish.textContent, words);
            assert(finish.getAttribute('class').split(' ').includes('chip-plain'));
            assert(!cell(key, 'printing').textContent.includes(words));
            assert.equal(cell(key, 'printing').querySelector('.chip-foil'), null);
          }
          assert(cell('fdn|3|nonfoil', 'finish').textContent.includes('Non-foil'));
          assert.equal(cell('fdn|3|nonfoil', 'finish').querySelector('.chip-foil'), null);
          assert.equal(cell('fdn|1|foil', 'printing').textContent, 'FDN 1');
          assert.equal(cell('fdn|1|foil', 'qty').textContent, '4');
          assert.equal(cell('fdn|1|foil', 'qty').querySelector('.col-held'), null);
        """)

    def test_in_decks_counts_remain_anonymous_and_preserve_printing_uncertainty(self):
        self.run_js("""
          state.library = {decks: [{id: 'user2/casual/private', title: 'Private deck title'}]};
          draw(); const held = cell('fdn|1|foil', 'held');
          assert(/3 in decks[?]/.test(held.textContent)); assert(/1 free/.test(held.textContent));
          assert(held.querySelector('.sr-only').textContent.includes('Printing allocation uncertain'));
          same(held.querySelectorAll('.sim-num').map(node => node.textContent), ['3', '1']);
          assert.equal(held.querySelectorAll('a').length, 0);
          assert(!main.textContent.includes('Private deck title')); assert(!main.textContent.includes('user2/casual/private'));
          assert.equal(cell('fdn|2|etched', 'held').textContent, 'In storage');
          assert(/not tracked/i.test(cell('fdn|4|nonfoil', 'held').textContent));
          assert(!/0 free/.test(cell('fdn|4|nonfoil', 'held').textContent));
        """)

    def test_missing_or_failed_storage_does_not_invent_storage_or_zero_counts(self):
        self.run_js("""
          for (const value of [undefined, {rows: {}, error: 'Counts unavailable.'}]) {
            draw({storage: value});
            for (const key of rows.map(colKey)) {
              const held = cell(key, 'held');
              assert.equal(held.querySelector('.cell-unknown').getAttribute('aria-hidden'), 'true');
              assert(/not known|not recorded|unavailable/i.test(held.querySelector('.sr-only').textContent));
              assert(!held.textContent.includes('In storage')); assert(!/0 in decks|0 free/.test(held.textContent));
            }
          }
          const cv = draw();
          colChanged(cv, {sha256: 's2', rows, storage: {rows: {'fdn|1|foil': {held: 1, guess: false}}, error: null}}, '');
          const held = cell('fdn|1|foil', 'held');
          assert(/1 in decks/.test(held.textContent)); assert(/3 free/.test(held.textContent));
          assert(!held.textContent.includes('?')); assert(!held.textContent.includes('Printing allocation uncertain'));
        """)

    def test_columns_use_only_loaded_metadata_without_mutating_canonical_rows_or_hash(self):
        self.run_js("""
          let reads = 0, writes = 0;
          api = async () => { reads++; throw new Error('columns must not read'); };
          apiWrite = async () => { writes++; throw new Error('columns must not write'); };
          const before = JSON.stringify(rows), cv = draw({editable: false});
          colSelectRow(cv, 'fdn|1|foil');
          main.querySelector('.col-th-quantity').querySelector('button').click();
          assert.equal(reads, 0); assert.equal(writes, 0);
          assert.equal(JSON.stringify(rows), before); assert.equal(JSON.stringify(cv.rows), before);
          assert.equal(cv.sha256, 's1'); assert.equal(main.querySelector('.col-preview-edit'), null);
          assert(cell('fdn|1|foil', 'colour').querySelector('.id-pips'));
          assert(cell('fdn|1|foil', 'held').textContent.includes('1 free'));
        """)


def container_rules(css, width):
    """Extract one named container's rules without depending on indentation."""
    start = re.search(rf"@container\s+collection-table\s+\(max-width:\s*{width}px\)\s*\{{", css)
    if start is None:
        raise AssertionError(f"No collection-table container query at {width}px")
    depth, at = 1, start.end()
    for end in range(at, len(css)):
        depth += (css[end] == "{") - (css[end] == "}")
        if depth == 0:
            return css[at:end]
    raise AssertionError("Unclosed collection-table query")


class CollectionColumnsLayoutTests(unittest.TestCase):
    def test_container_hides_colour_type_language_before_the_core_columns(self):
        css = (WEB / "collection.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"container(?:-name)?:\s*collection-table")
        for width, selectors in ((1100, (".col-column-colour",)), (1000, (".col-column-type",)),
                                 (900, (".col-th-language", ".col-td-language"))):
            rules = container_rules(css, width)
            for selector in selectors:
                self.assertIn(selector, rules)
            self.assertRegex(rules, r"display:\s*none")
            for core in (".col-td-name", ".col-td-printing", ".col-td-finish", ".col-td-qty", ".col-td-price"):
                self.assertNotIn(core, rules)

    def test_dense_rows_use_the_pointer_floor_without_padding_expanding_every_row(self):
        css = (WEB / "collection.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.col-row-lab[^{}]*\.col-table\s+td\s*\{[^{}]*padding-top:\s*0;[^{}]*padding-bottom:\s*0;")
        self.assertRegex(css, r"\.col-row-lab[^{}]*\.col-open\s*\{[^{}]*min-height:\s*var\(--row-h\)")
        self.assertEqual(_tokens_on(MACBOOK)["--row-h"], "36px")
        self.assertEqual(_tokens_on(IPAD_LANDSCAPE)["--row-h"], "44px")
        self.assertRegex(css, r"\.col-row-lab[^{}]*\[data-selected\][^{}]*\.col-td-name\s*\{[^{}]*inset\s+2px[^{}]*var\(--accent\)")
