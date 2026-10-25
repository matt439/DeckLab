"""The Matchups setting chip reflects server state and never changes settings or blocks saved results."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, WEB, RUNNER


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SimulationChipUiTests(unittest.TestCase):
    def run_js(self, scenario):
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), scenario, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_modes_follow_new_answers_without_guessing(self):
        self.run_js("""
          clear(main); state.simulations = null;
          const chip = simulationsChip(); main.append(chip);
          assert.equal(chip.hidden, true); assert.equal(chip.textContent, '');
          for (const [mode, label] of [['admins', 'Admins only'], ['everyone', 'Anyone'], ['paused', 'Paused']]) {
            renderSimulations({mode, may_edit: false, may_start: mode === 'everyone'});
            assert.equal(chip.hidden, false);
            assert.equal(chip.textContent, 'Simulations: ' + label);
            assert.equal(chip.getAttribute('aria-label'), chip.textContent);
            assert.equal(chip.getAttribute('role'), 'img');
          }
          renderSimulations({mode: 'unknown', may_edit: false});
          assert.equal(chip.hidden, true); assert.equal(chip.textContent, '');
        """)

    def test_chip_is_beside_title_and_refuses_no_saved_results(self):
        self.run_js("""
          clear(main); state.simulations = {mode: 'paused', may_start: false, why_not: 'Simulations are paused.'};
          add(main, pageHead({title: 'Matchups', badge: simulationsChip()}));
          main.append(el('div', {class: 'saved-results', text: 'Saved matchup results'}));
          assert.equal(main.querySelector('h1').textContent, 'Matchups');
          assert(main.querySelector('.page-head-title').textContent.includes('Simulations: Paused'));
          assert(main.textContent.includes('Saved matchup results'));
          renderSimulations({mode: 'admins', unavailable: true, may_edit: false, may_start: false});
          const chip = main.querySelector('[data-simulations-chip]');
          assert(chip.getAttribute('title').includes('fallback setting'));
          assert(!chip.textContent.includes('Matt'));
          assert.equal(main.querySelectorAll('button').length, 0);
        """)
