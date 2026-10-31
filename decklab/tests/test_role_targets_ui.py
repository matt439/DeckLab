"""The Stats tab's Commander role targets (E9-S26, stats.js compositionPanel, roleTargetMark and roleTargetsPart)
under Node: each role bar the Command Zone template gives a target shows it and whether the deck is below, at or
above it (a role with none of its cards included), the template's table lists every category with what Deck Lab
counts, says "Not counted" for plan cards and cites the episode, and a casual deck shows none of it.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js; nothing is sent to a server.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  const category = (name, label, target, count, statusWord, extra = {}) => Object.assign({category: name, label,
    target, about: false, count, status: statusWord, roles: [], except: [], role_bar: null,
    measure: `What Deck Lab counts for ${label}.`}, extra);
  const targets = () => ({source: 'command-zone-658', episode: 658, episode_date: '2025-02-18', checked: '2026-10-31',
    categories: [category('lands', 'Lands', 38, 38, 'at'), category('ramp', 'Ramp', 10, 4, 'below', {role_bar: 'ramp'}),
      category('card advantage', 'Card advantage', 12, 13, 'above', {role_bar: 'draw'}),
      category('targeted disruption', 'Targeted disruption', 12, 2, 'below'),
      category('mass disruption', 'Mass disruption', 6, 0, 'below', {role_bar: 'board wipe'}),
      category('plan', 'Plan cards', 30, null, null, {about: true, measure: 'No Deck Lab role: the plan.'})],
    by_role: {ramp: 'ramp', draw: 'card advantage', 'board wipe': 'mass disruption'}});
  const roleRow = (role, count) => ({role, count, cards: count ? [{name: 'Some Card', qty: count}] : []});
  const commanderStats = () => ({types: [], roles: [roleRow('removal', 3), roleRow('ramp', 4), roleRow('draw', 13),
    roleRow('counterspell', 0), roleRow('board wipe', 0)], role_targets: targets()});
  const rowFor = (host, label) => host.querySelectorAll('li').find((li) => li.querySelector('.bar-label') &&
    li.querySelector('.bar-label').textContent.startsWith(label));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class RoleTargetsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_role_bars_show_their_target_and_where_the_deck_is(self):
        self.run_js("""
          const comp = compositionPanel(commanderStats(), null);
          const ramp = rowFor(comp, 'Ramp').querySelector('.bar-label').textContent;
          assert(ramp.includes('target 10') && ramp.includes('Below'), ramp);
          const draw = rowFor(comp, 'Card draw').querySelector('.bar-label').textContent;
          assert(draw.includes('target 12') && draw.includes('Above'), draw);
          // No board wipes: still listed, since the template asks for 6.
          const wipes = rowFor(comp, 'Board wipes');
          assert(wipes, comp.textContent);
          assert(wipes.textContent.includes('target 6') && wipes.textContent.includes('Below'), wipes.textContent);
          // Removal counts board wipes too, so its bar has no target; a role with none and no target isn't listed.
          assert(!rowFor(comp, 'Removal').textContent.includes('target'), rowFor(comp, 'Removal').textContent);
          assert.equal(rowFor(comp, 'Counterspells'), undefined);
        """)

    def test_the_template_table_cites_the_episode_and_says_what_is_counted(self):
        self.run_js("""
          const comp = compositionPanel(commanderStats(), null);
          const part = comp.querySelector('.role-targets-part');
          assert(part, comp.textContent);
          assert.equal(part.querySelector('summary').textContent,
            'Role targets: Command Zone template, episode 658 (2025-02-18)');
          const rows = part.querySelectorAll('tr').slice(1).map((tr) => tr.textContent);
          assert.equal(rows.length, 6);
          assert(rows[0].includes('Lands') && rows[0].includes('38') && rows[0].includes('At'), rows[0]);
          assert(rows[3].includes('Targeted disruption') && rows[3].includes('Below'), rows[3]);
          assert(rows[5].includes('Plan cards') && rows[5].includes('about 30') && rows[5].includes('Not counted'), rows[5]);
          assert(rows[5].includes('No Deck Lab role'), rows[5]);
          assert(part.textContent.includes('Figures checked 2026-10-31.'), part.textContent);
          // The Sources panel lists the template once deck_stats sends it with the others.
          const sources = sourcesPanel({role_targets: targets(), sources: {'command-zone-658':
            {title: 'Commander Deckbuilding Template for the New Era (The Command Zone, episode 658)',
             date: 'episode of 2025-02-18', url: 'https://www.youtube.com/watch?v=x'}}});
          assert(sources && sources.textContent.includes('episode 658'), sources && sources.textContent);
        """)

    def test_a_casual_deck_shows_no_targets(self):
        self.run_js("""
          const st = commanderStats(); st.role_targets = null;
          const comp = compositionPanel(st, null);
          assert.equal(comp.querySelector('.role-targets-part'), null);
          assert(!comp.textContent.includes('target'), comp.textContent);
          assert.equal(rowFor(comp, 'Board wipes'), undefined);
        """)


if __name__ == "__main__":
    unittest.main()
