"""Optional holder swatches use supplied Planned identity, independently of saved hint version."""
import json
import subprocess
import unittest

from decklab.tests.test_collection_hints_ui import HINTS
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionHintColorsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), HINTS + scenario, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "ok")

    def test_supplied_planned_identity_is_decorative_and_does_not_change_the_hint_list_route(self):
        self.run_js(r"""
          state.library = {decks: [{id: 'casual/saved', colors: ['U'], title: 'Do not infer this'}]};
          const cv = drawHints(entry({listed_holders: [hint('casual/saved', 'owned', {colors: ['R', 'G']})]}));
          const roots = surfaces(cv);
          assert.equal(roots[0].querySelector('.deck-swatch'), null);
          for (const root of roots.slice(1)) {
            const link = root.querySelector('.col-packing-hints').querySelector('a'), swatch = link.querySelector('.deck-swatch');
            assert(swatch); assert.equal(swatch.getAttribute('aria-hidden'), 'true');
            assert.equal(swatch.getAttribute('tabindex'), null); assert.equal(swatch.getAttribute('role'), null);
            const paint = swatch.getAttribute('style');
            assert(paint.includes('--stripe-r')); assert(paint.includes('--stripe-g'));
            assert(!paint.includes('--stripe-u')); assert(!paint.includes('--stripe-c'));
            assert.equal(link.textContent, '2 \u00d7 Saved deck (Play-now list)');
            assert.equal(link.getAttribute('href'), deckHref('casual/saved', 'owned'));
            assert(root.textContent.includes('Saved packing lists may differ from the boxes and current deck lists.'));
            assert(root.textContent.includes('Links open current lists.'));
            assert(!root.textContent.includes('Do not infer this'));
          }
        """)

    def test_only_known_empty_identity_is_colourless_while_unknown_or_invalid_colors_keep_valid_hints(self):
        self.run_js(r"""
          const values = [undefined, null, 'G', {}, ['C'], ['g'], ['G', null], [1], [true]];
          for (const colors of values) {
            const cv = drawHints(entry({listed_holders: [hint('casual/saved', 'owned', {colors})]}));
            for (const root of surfaces(cv).slice(1)) {
              assert(root.querySelector('.col-packing-hints')); assert(root.querySelector('a'));
              assert.equal(root.querySelector('.deck-swatch'), null);
              assert.equal(root.querySelector('a').getAttribute('href'), deckHref('casual/saved', 'owned'));
            }
          }
          const cv = drawHints(entry({listed_holders: [hint('casual/saved', 'target', {colors: []})]}));
          for (const root of surfaces(cv).slice(1)) {
            const swatch = root.querySelector('.deck-swatch'); assert(swatch);
            assert(swatch.getAttribute('style').includes('--stripe-c'));
            assert.equal(swatch.getAttribute('aria-hidden'), 'true');
          }
        """)

    def test_color_rendering_uses_only_the_response_and_keeps_rows_hash_and_source_arrays_unchanged(self):
        self.run_js(r"""
          let reads = 0, writes = 0;
          api = async () => { reads++; throw new Error('colours must not read'); };
          apiWrite = async () => { writes++; throw new Error('colours must not write'); };
          const saved = entry({listed_holders: [hint('casual/saved', 'target', {colors: ['W', 'B']})]});
          const before = JSON.stringify({rows, saved}), cv = drawHints(saved, {editable: false});
          surfaces(cv); main.querySelector('.col-th-price').querySelector('button').click();
          assert.equal(JSON.stringify({rows: cv.rows, saved}), before); assert.equal(cv.sha256, 's1');
          assert.equal(reads, 0); assert.equal(writes, 0); assert.equal(changes, 0);
          for (const root of surfaces(cv).slice(1)) {
            const swatch = root.querySelector('.deck-swatch'); assert(swatch);
            assert(swatch.getAttribute('style').includes('--stripe-w')); assert(swatch.getAttribute('style').includes('--stripe-b'));
            assert(!root.textContent.includes('Edit copies'));
          }
        """)
