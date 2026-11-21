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

    def test_colour_type_dividers_start_with_their_section_when_the_rule_maps_groups(self):
        """E8-S25 slice 7: storage_order's sections ({group: section}); without them, today's labels."""
        self.run_js("""
          const cards = {'Zebra': card('Zebra', 'Creature', ['W']), 'Bird': card('Bird', 'Artifact Creature', ['U']),
            'Apple': card('Apple', 'Instant', ['U']), 'Relic': card('Relic', 'Artifact', []),
            'Grove': card('Grove', 'Land', [], {produced_mana: ['G']}), 'Odd': null};
          const sections = {creatures: 'Row 1', spells: 'Row 2', lands: 'Row 3', tokens: 'Row 4'};
          const heads = () => main.querySelectorAll('.pack-storage-group').map(g => g.querySelector('h4').textContent.replace(/ · [0-9]+ cards?$/, ''));
          clear(main);
          drawAssembly({...plan(cards), storage_order: {rule: 'colour-type', container: 'Storage box', sleeved: false, sections}}, routeToken);
          choose('Storage order');
          same(heads(), ['Row 1 · Creatures · White', 'Row 1 · Artifact creatures', 'Row 2 · Spells · Blue', 'Row 2 · Artifacts',
            'Row 3 · Lands · Green', 'Other cards']);
          clear(main);
          drawAssembly({...plan(cards), storage_order: {rule: 'colour-type', container: 'Storage box', sections: {lands: 'Row 3', bogus: 'X'}}}, routeToken);
          same(heads(), ['Creatures · White', 'Artifact creatures', 'Spells · Blue', 'Artifacts', 'Row 3 · Lands · Green', 'Other cards']);
          clear(main);
          drawAssembly({...plan(cards), storage_order: {rule: 'colour-type', container: 'Storage box'}}, routeToken);
          same(heads(), ['Creatures · White', 'Artifact creatures', 'Spells · Blue', 'Artifacts', 'Lands · Green', 'Other cards']);
        """)

    def test_two_containers_group_by_container_then_each_ones_rule(self):
        """E8-S25 slice 7: storage_order's containers and placed."""
        self.run_js("""
          const cards = {'Zebra': card('Zebra', 'Creature', ['W']), 'Apple': card('Apple', 'Instant', ['U']),
            'Mango': card('Mango', 'Sorcery', ['B']), 'Kiwi': card('Kiwi', 'Creature', ['G']),
            'Pear': card('Pear', 'Creature', ['R']), 'Fig': card('Fig', 'Instant', ['U'])};
          const data = plan(cards);
          data.storage_order = {rule: 'colour-type', container: 'Storage box', sleeved: false,
            containers: [{id: 'box', name: 'Storage box', order: 'colour-type', sleeved: false, sections: {creatures: 'Row 1'}},
              {id: 'binder', name: 'Binder', order: 'set', sleeved: true},
              {id: 'shelf', name: 'Shelf', order: 'name', sleeved: false}],
            placed: {Zebra: 'binder', Apple: 'binder', Mango: null, Kiwi: 'box', Fig: 'shelf'},   // Pear: the default
            printings: {Zebra: ['fdn', '10'], Apple: ['fdn', '9']}};
          drawAssembly(data, routeToken);
          same(main.querySelector('.pack-sort').querySelectorAll('button').map(b => b.textContent), ['Name', 'Storage order']);
          choose('Storage order');
          assert.equal(main.querySelector('.pack-order-help').textContent, 'Grouped by container, then by its filing order.');
          assert(!main.querySelector('.pack-order-help').hidden);
          const groups = main.querySelectorAll('.pack-container-group');
          assert.equal(groups[0].querySelector('[data-pack-remaining]').textContent, '2 cards left in this step');
          assert(groups[3].textContent.includes('match no configured storage container'));
          groups[0].querySelector('[data-pack-tick]').click();
          assert.equal(groups[0].querySelector('[data-pack-remaining]').textContent, '1 card left in this step');
          same(groups.map(g => g.querySelector('h4').textContent), ['Storage box · 2 cards', 'Binder · 2 cards',
            'Shelf · 1 card', 'Somewhere else · 1 card']);
          same(groups.map(names), [['Pear', 'Kiwi'], ['Apple', 'Zebra'], ['Fig'], ['Mango']]);
          same(groups[0].querySelectorAll('h5').map(h => h.textContent), ['Row 1 · Creatures · Red · 1 card', 'Row 1 · Creatures · Green · 1 card']);
          same(groups[1].querySelectorAll('h5').map(h => h.textContent), ['Set · FDN · 2 cards']);
          assert.equal(groups[2].querySelectorAll('.pack-storage-group').length, 0);     // name: one grid
          choose('Name');
          assert.equal(main.querySelectorAll('.pack-container-group').length, 0);
          same(names(main), ['Apple', 'Fig', 'Kiwi', 'Mango', 'Pear', 'Zebra']);
        """)

    def test_one_container_distinguishes_recorded_locations_elsewhere(self):
        self.run_js("""
          const cards = {'Zebra': card('Zebra', 'Creature', ['W']), 'Apple': card('Apple', 'Instant', ['U'])};
          const data = plan(cards);
          data.storage_order = {rule: 'colour-type', container: 'Storage box', sleeved: false,
            containers: [{id: 'box', name: 'Storage box', order: 'colour-type', sleeved: false}], placed: {Zebra: null}};
          drawAssembly(data, routeToken);
          choose('Storage order');
          const groups = main.querySelectorAll('.pack-container-group');
          same(groups.map(g => g.querySelector('h4').textContent), ['Storage box · 1 card', 'Somewhere else · 1 card']);
          same(groups.map(names), [['Apple'], ['Zebra']]);
          assert.equal(groups[0].querySelector('h5').textContent, 'Spells · Blue · 1 card');
        """)

    def test_recorded_section_then_mapped_section_in_physical_order(self):
        self.run_js("""
          const cards = {Bear: card('Bear', 'Creature', ['G']), Sap: card('Sap', 'Creature', ['R']),
            Rain: card('Rain', 'Instant', ['U']), Plains: card('Plains', 'Land', [], {produced_mana: ['W']}),
            Unknown: null};
          const data = plan(cards);
          data.storage_order = {rule: 'colour-type', container: 'Long box',
            section_order: ['Front', 'Middle', 'Rear'], sections: {creatures: 'Rear', lands: 'Front'},
            filed_sections: {Bear: 'Middle'}};
          drawAssembly(data, routeToken); choose('Storage order');
          const groups = main.querySelectorAll('.pack-storage-group');
          same(groups.map(g => g.querySelector('h4').textContent), ['Front · Lands · White · 1 card',
            'Middle · Creatures · Green · 1 card', 'Rear · Creatures · Red · 1 card',
            'Spells · Blue · 1 card', 'Other cards · 1 card']);
          same(names(main), ['Plains', 'Bear', 'Sap', 'Rain', 'Unknown']);
        """)

    def test_set_order_in_recorded_sections_without_a_default(self):
        self.run_js("""
          const cards = Object.fromEntries(['Zebra', 'Apple', 'Mango', 'Kiwi', 'Fig'].map(n => [n, card(n, 'Creature')]));
          const data = plan(cards);
          data.storage_order = {rule: 'none', container: null,
            containers: [{id: 'binder', name: 'Binder', order: 'set', section_order: ['Back', 'Front']}],
            filed_sections: {Zebra:'Back', Apple:'Front', Mango:'Front'},
            placed: {Zebra:'binder', Apple:'binder', Mango:'binder', Kiwi:'binder', Fig:null},
            printings: {Zebra:['zzz','3'], Apple:['aaa','10'], Mango:['aaa','2'], Kiwi:['aaa','1']}};
          drawAssembly(data, routeToken); choose('Storage order');
          const groups = main.querySelectorAll('.pack-container-group');
          same(groups.map(g => g.querySelector('h4').textContent), ['Binder · 4 cards', 'Somewhere else · 1 card']);
          same(groups[0].querySelectorAll('h5').map(h => h.textContent),
            ['Back · Set · ZZZ · 1 card', 'Front · Set · AAA · 2 cards', 'Set · AAA · 1 card']);
          same(names(main), ['Zebra', 'Mango', 'Apple', 'Kiwi', 'Fig']);
        """)

    def test_name_ordered_container_with_sections_offers_a_physical_order(self):
        self.run_js("""
          const cards = Object.fromEntries(['Zebra', 'Apple', 'Mango'].map(n => [n, card(n, 'Creature')]));
          const data = plan(cards);
          data.storage_order = {rule: 'name', container: 'Binder', section_order: ['Back', 'Front'],
            filed_sections: {Zebra:'Back', Mango:'Front'}};
          drawAssembly(data, routeToken); choose('Storage order');
          same(main.querySelectorAll('.pack-storage-group').map(g => g.querySelector('h4').textContent),
            ['Back · 1 card', 'Front · 1 card', 'No section recorded · 1 card']);
          same(names(main), ['Zebra', 'Mango', 'Apple']);
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
