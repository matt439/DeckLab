"""Per-deck pod summary words use server-qualified visible counts, without requests or writes."""
import unittest

from decklab.tests import test_play_pods_ui as pod_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class PodResultsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        pod_ui.PodUiTests.run_js(self, scenario)

    def test_ready_summary_names_decided_denominator_draws_fair_share_and_range(self):
        self.run_js(r'''
          const summary={status:'ready',minimum_games:10,wins:4,decided:12,draws:2,fair_share:7/24,
            range:{low:.1,high:.6},excluded:1,outside_winners:[{commander:'Leader // Face, Partner',wins:3}]};
          clear(main);main.append(playPodSection(packet({pod_summary:summary}),'commander/test'));
          const part=main.querySelector('.play-pod-summary');
          assert(part.textContent.includes('Won 4 of 12 decided pods'));
          assert(part.textContent.includes('2 draws counted separately'));
          assert(part.textContent.includes('Fair share across those table sizes: 29.2%'));
          assert(part.textContent.includes('95% Wilson range: 10.0%–60.0%'));
          assert(part.textContent.includes('Leader // Face, Partner (3 wins)'));
          assert(part.textContent.includes('1 ambiguous or incomplete pod left out'));
          assert.equal(writes.length,0);
        ''')

    def test_below_minimum_only_says_not_enough_and_no_unfiltered_rollup_is_shown(self):
        self.run_js(r'''
          const data=packet({pod_summary:{status:'insufficient',minimum_games:10,wins:999,
            outside_winners:[{commander:'Never reveal this premature ranking',wins:9}]}});
          clear(main);main.append(playPodSection(data,'commander/test'));
          const part=main.querySelector('.play-pod-summary');
          assert.equal(part.textContent,'Not enough pod games yet: at least 10 decided pods are needed.');
          assert(!part.textContent.includes('999'));assert(!part.textContent.includes('Never reveal'));
          clear(main);main.append(playPodSection(data));assert.equal(main.querySelector('.play-pod-summary'),null);
        ''')

    def test_unavailable_summary_does_not_invent_zero_and_malformed_rates_are_not_drawn(self):
        self.run_js(r'''
          clear(main);main.append(playPodSection(packet({pod_summary:{status:'unavailable',minimum_games:10}}),'commander/test'));
          assert(main.querySelector('.play-pod-summary').textContent.includes("couldn't be worked out"));
          const bad={status:'ready',minimum_games:10,wins:4,decided:12,draws:0,fair_share:1/3,range:{low:.9,high:.1}};
          assert.equal(podResultsPart(bad),null);assert.equal(writes.length,0);
        ''')
