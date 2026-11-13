"""Build decks' second card order follows home's storage setup (E8-S25 slice 5): the default
container's rule from the plan's "storage_order", over the real scripts with fixture plans."""
import json
import subprocess
import unittest

from decklab.tests.test_assembly_sort_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyStorageOrderUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_a_set_ordered_binder_groups_by_set_then_collector_number(self):
        self.run_js("""
          const cards = {'Zebra': card('Zebra', 'Creature', ['W']), 'Apple': card('Apple', 'Instant', ['U']),
            'Mango': card('Mango', 'Sorcery', ['B']), 'Kiwi': card('Kiwi', 'Creature', ['G']),
            'Forest': card('Forest', 'Basic Land', [])};
          const data = plan(cards, {basics: [{name: 'Forest', quantity: 2}]});
          data.decks[0].steps = data.decks[0].steps.filter(step => step.name !== 'Forest');     // a basic, not pulled
          data.storage_order = {rule: 'set', container: 'Binder', printings: {Zebra: ['fdn', '10'], Apple: ['fdn', '9'],
            Mango: ['dsk', '200']}};
          drawAssembly(data, routeToken);
          same(main.querySelector('.pack-sort').querySelectorAll('button').map(b => b.textContent), ['Name', 'Set order']);
          const set = main.querySelector('.pack-sort').querySelectorAll('button')[1];
          assert.equal(set.getAttribute('title'), 'As the binder is ordered');
          choose('Set order');
          assert.equal(chosen(), 'Set order');
          const groups = main.querySelectorAll('.pack-storage-group');
          same(groups.map(g => g.querySelector('h4').textContent.replace(/ · [0-9]+ cards?$/, '')),
            ['Set · DSK', 'Set · FDN', 'No printing recorded', 'No printing recorded']);
          same(groups.map(names), [['Mango'], ['Apple', 'Zebra'], ['Kiwi'], ['Forest']]);     // 9 before 10; Forest is its own step's
          assert(steps().some(s => s.includes('Basic lands')), steps());     // basics keep their own step
          assert.equal(local.get('packing-order.matt'), 'storage');
        """)

    def test_no_default_container_or_a_name_rule_offers_only_name(self):
        self.run_js("""
          const cards = {'Zebra': card('Zebra', 'Creature', ['W']), 'Apple': card('Apple', 'Instant', ['U'])};
          local.set('packing-order.matt', 'storage');
          for (const order of [null, {rule: 'name', container: 'Shoebox'}, {rule: 'none', container: 'Shelf'}]) {
            clear(main);
            drawAssembly({...plan(cards), storage_order: order}, routeToken);
            const sort = main.querySelector('.pack-sort');
            same(sort.querySelectorAll('button').map(b => b.textContent), ['Name']);
            assert(sort.querySelector('.segmented').hidden);
            assert.equal(main.querySelectorAll('.pack-storage-group').length, 0);
            same(names(main.querySelector('.pack-tiles')), ['Apple', 'Zebra']);
          }
          assert.equal(local.get('packing-order.matt'), 'storage');   // the choice is kept for later
          clear(main);
          drawAssembly({...plan(cards), storage_order: {rule: 'colour-type', container: 'Storage box'}}, routeToken);
          assert.equal(chosen(), 'Storage order');                    // today's order comes back
          assert(main.querySelectorAll('.pack-storage-group').length > 0);
        """)

    def test_two_containers_group_by_container_then_each_ones_rule(self):
        """E8-S25 slice 7: storage_order's containers and placed."""
        self.run_js("""
          const cards = {'Zebra': card('Zebra', 'Creature', ['W']), 'Apple': card('Apple', 'Instant', ['U']),
            'Mango': card('Mango', 'Sorcery', ['B']), 'Kiwi': card('Kiwi', 'Creature', ['G']),
            'Pear': card('Pear', 'Creature', ['R']), 'Fig': card('Fig', 'Instant', ['U'])};
          const data = plan(cards);
          data.storage_order = {rule: 'colour-type', container: 'Storage box', sleeved: false,
            containers: [{id: 'box', name: 'Storage box', order: 'colour-type', sleeved: false},
              {id: 'binder', name: 'Binder', order: 'set', sleeved: true},
              {id: 'shelf', name: 'Shelf', order: 'name', sleeved: false}],
            placed: {Zebra: 'binder', Apple: 'binder', Mango: null, Kiwi: 'box', Fig: 'shelf'},   // Pear: the default
            printings: {Zebra: ['fdn', '10'], Apple: ['fdn', '9']}};
          drawAssembly(data, routeToken);
          same(main.querySelector('.pack-sort').querySelectorAll('button').map(b => b.textContent), ['Name', 'Storage order']);
          choose('Storage order');
          const groups = main.querySelectorAll('.pack-container-group');
          same(groups.map(g => g.querySelector('h4').textContent), ['Storage box · 2 cards', 'Binder · 2 cards',
            'Shelf · 1 card', 'Somewhere else · 1 card']);
          same(groups.map(names), [['Pear', 'Kiwi'], ['Apple', 'Zebra'], ['Fig'], ['Mango']]);
          same(groups[0].querySelectorAll('h5').map(h => h.textContent), ['Creatures · Red · 1 card', 'Creatures · Green · 1 card']);
          same(groups[1].querySelectorAll('h5').map(h => h.textContent), ['Set · FDN · 2 cards']);
          assert.equal(groups[2].querySelectorAll('.pack-storage-group').length, 0);     // name: one grid
          choose('Name');
          assert.equal(main.querySelectorAll('.pack-container-group').length, 0);
          same(names(main), ['Apple', 'Fig', 'Kiwi', 'Mango', 'Pear', 'Zebra']);
        """)

    def test_one_container_looks_as_before(self):
        self.run_js("""
          const cards = {'Zebra': card('Zebra', 'Creature', ['W']), 'Apple': card('Apple', 'Instant', ['U'])};
          const data = plan(cards);
          data.storage_order = {rule: 'colour-type', container: 'Storage box', sleeved: false,
            containers: [{id: 'box', name: 'Storage box', order: 'colour-type', sleeved: false}], placed: {Zebra: null}};
          drawAssembly(data, routeToken);
          choose('Storage order');
          assert.equal(main.querySelectorAll('.pack-container-group').length, 0);
          same(main.querySelectorAll('.pack-storage-group').map(g => g.querySelector('h4').textContent),
            ['Creatures · White · 1 card', 'Spells · Blue · 1 card']);
        """)

    def test_put_back_says_unsleeved_only_when_the_default_container_isnt_sleeved(self):
        """E8-S25 slice 6: storage_order's sleeved."""
        self.run_js("""
          const cards = {'Zebra': card('Zebra', 'Creature', ['W']), 'Back': card('Back', 'Instant', ['U'])};
          const cases = [[undefined, true], [null, true], [{rule: 'colour-type', container: 'Storage box', sleeved: false}, true],
            [{rule: 'set', container: 'Binder', sleeved: true, printings: {}}, false]];
          for (const [order, unsleeved] of cases) {
            clear(main);
            const data = plan(cards, {steps: [{name: 'Zebra', storage: 1, keep: 0, transfers: [], waiting: 0, missing: 0}],
              returns: [{name: 'Back', quantity: 1}]});
            if (order !== undefined) data.storage_order = order;
            drawAssembly(data, routeToken);
            const back = main.querySelectorAll('.pack-step').find(s => s.querySelector('h3').textContent.includes('Put back'));
            assert(back, steps());
            const words = unsleeved ? 'put them back in storage, unsleeved.' : 'put them back in storage.';
            assert(back.textContent.includes('Take these out of the deck and ' + words), back.textContent);
          }
        """)


if __name__ == "__main__":
    unittest.main()
