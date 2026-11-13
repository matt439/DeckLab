"""Shopping's storage fill under Node (E8-S25 slice 7, shopping-storage.js): under On the way, how full
each of home's containers with a capacity is now and once the pending orders arrive, worded as an
estimate with the scenario's caveats; nothing without the field, for a bad answer or outside home's records.

Run: python scripts/test_fixtures.py decklab.tests.test_shopping_storage_ui
Nothing is read or written: the answer is supplied.
"""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE

SETUP = r"""
  state.may = {admin: false, orders: false, see_inventory: ['home'], see_home_records: true};
  api = () => { throw new Error('The storage note must not read'); };
  apiWrite = () => { throw new Error('The storage note must not write'); };
  const box = (extra = {}) => ({id: 'box', name: 'Storage box', kind: 'box', capacity: 240, now: 123, incoming: 6,
    after: 129, over_now: false, over_after: false, ...extra});
  const fill = (extra = {}) => ({status: 'partial', containers: [box()], default: 'Storage box', unknown_sources: 0,
    pending_products: 0, tokens_excluded: false, ...extra});
  const answer = (extra = {}) => ({...empty, orders: [order()], ...extra});
  const note = () => main.querySelector('[data-storage-fill]');
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingStorageFillTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_fill_js(self, scenario):
        self.run_js(SETUP + scenario)

    def test_the_note_sits_under_on_the_way_with_now_and_after(self):
        self.run_fill_js(r"""
          drawShopping(answer({storage_fill: fill()}));
          const node = note();
          assert(node);
          assert.equal(node.closest('section').querySelector('h2').textContent, 'On the way');
          assert.equal(node.querySelector('h3').textContent, 'Storage once these arrive');
          const lines = node.querySelectorAll('[data-storage-container]');
          same(lines.map(line => line.textContent), ['Storage box: about 123 of 240 cards now, about 129 once these arrive.']);
          assert(!(node.getAttribute('class') || '').includes('box-warn'), node.getAttribute('class'));
          const words = node.querySelector('.sub').textContent;
          assert(words.startsWith('An estimate: each pending card goes where copies of its printing are kept, else the storage box'), words);
          assert(words.includes("Basic lands aren't counted."), words);
        """)

    def test_over_capacity_and_every_caveat(self):
        self.run_fill_js(r"""
          drawShopping(answer({storage_fill: fill({containers: [box(),
            {id: 'binder', name: 'Ultimate Guard binder', kind: 'binder', capacity: 10, now: 8, incoming: 4, after: 12,
             over_now: false, over_after: true}], default: 'Ultimate Guard binder', unknown_sources: 1, pending_products: 2,
            tokens_excluded: true})}));
          const node = note();
          assert((node.getAttribute('class') || '').includes('box box-warn'), node.getAttribute('class'));
          same(node.querySelectorAll('[data-storage-container]').map(line => line.textContent), [
            'Storage box: about 123 of 240 cards now, about 129 once these arrive.',
            'Ultimate Guard binder would be over capacity: about 12 cards for about 10 places (about 8 now).']);
          const words = node.querySelector('.sub').textContent;
          assert(words.includes('else Ultimate Guard binder, as if'), words);   // a proper name as written, as the receipt's
          assert(words.includes("Basic lands aren't counted, and nor are token cards."), words);
          assert(words.includes("2 pending products aren't counted: whether they stay intact is chosen when they arrive."), words);
          assert(words.includes("1 pending delivery couldn't be checked, so their cards aren't counted."), words);
          clear(main);
          drawShopping(answer({storage_fill: fill({pending_products: 1, default: null})}));
          const one = note().querySelector('.sub').textContent;
          assert(one.includes("1 pending product isn't counted: whether it stays intact is chosen when it arrives."), one);
          assert(!one.includes('else the'), one);
          for (const [name, said] of [["Matt's binder", "else Matt's binder, as if"], ['Shelf A', 'else Shelf A, as if'],
                                      ['Red binder', 'else the red binder, as if']]) {
            clear(main);
            drawShopping(answer({storage_fill: fill({default: name})}));
            const words = note().querySelector('.sub').textContent;
            assert(words.includes(said), words);
          }
        """)

    def test_nothing_without_the_field_for_a_bad_answer_nothing_on_the_way_or_outside_home_records(self):
        self.run_fill_js(r"""
          drawShopping(answer());
          assert.equal(note(), null);
          for (const bad of [fill({status: 'unknown'}), fill({containers: []}), fill({containers: [box({after: 1})]}),
                             fill({containers: [box({capacity: 0})]}), fill({containers: [box({name: 'Bad\u0007'})]}),
                             fill({unknown_sources: -1}), fill({tokens_excluded: 'no'}), fill({default: 7}), null, 'text']) {
            clear(main);
            drawShopping(answer({storage_fill: bad}));
            assert.equal(note(), null, JSON.stringify(bad));
          }
          clear(main);
          drawShopping({...empty, storage_fill: fill()});         // nothing on the way
          assert.equal(note(), null);
          clear(main);
          state.may = {admin: true, orders: true, see_inventory: ['home'], see_home_records: false};
          drawShopping(answer({storage_fill: fill()}));
          assert.equal(note(), null);
          assert.equal(shopStorageFill({data: {storage_fill: fill()}}), null);
        """)


if __name__ == "__main__":
    unittest.main()
