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


if __name__ == "__main__":
    unittest.main()
