"""The Collection page's "Commanders we could build…" (E9-S28, commander-candidates.js), over the real scripts
with fixture answers."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

FIXTURE = SETUP + """
  const cat = (category, label, target, count, inCoverage, extra = {}) => ({category, label, target, about: false, count,
    short: inCoverage && count < target, in_coverage: inCoverage, measure: '', ...extra});
  const lead = (name, colours, covered, short, extra = {}) => ({name, colours, covered, of: 40, share: covered / 40, free: 1,
    cards: 12, lands: 3, partner: [], card: null, short,
    categories: [cat('lands', 'Lands', 38, 3, false), cat('ramp', 'Ramp', 10, 10, true), cat('card advantage', 'Card advantage', 12, 8, true),
      cat('targeted disruption', 'Targeted disruption', 12, 9, true), cat('mass disruption', 'Mass disruption', 6, 3, true),
      cat('plan', 'Plan cards', 30, null, false, {about: true})], ...extra});
  const RANKED = {space: 'home', total: 3, tags_available: true,
    source: {id: 'command-zone-658', title: 'Commander Deckbuilding Template', url: 'https://example.com/658', episode_date: '2025-02-18', checked: '2026-10-31'},
    candidates: [lead('Ghalta, Primal Hunger', ['G'], 30, ['Card advantage', 'Targeted disruption', 'Mass disruption']),
      lead('Kraum, Ludevic\\'s Opus', ['U', 'R'], 20, ['Ramp'], {partner: ['partner']})]};
  const make = (data = {}) => { as('matt', MAY.admin); location.hash = '#/collection';
    return drawCollectionRows({space: 'home', sha256: 's1', rows: [], editable: true, ...data}, 'home'); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CommanderCandidatesUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_ranking_and_one_candidate(self):
        self.run_js("""
          const cv = make();
          const asked = [];
          api = async (path) => { asked.push(path); return RANKED; };
          const ctx = openCommanderCandidates(cv); await flush();
          same(asked, ['/api/commanders/candidates?']);
          const list = ctx.area.textContent;
          assert(list.includes('Ghalta, Primal Hunger') && list.includes('75% of the role targets · 30 of 40'), list);
          assert(list.includes('Short of card advantage, targeted disruption, mass disruption'), list);
          assert(list.indexOf('Ghalta') < list.indexOf('Kraum'));
          assert(list.includes('has partner') && list.includes('The best 2 of 3.'), list);
          assert(list.includes('Commander Deckbuilding Template') && list.includes('figures checked 2026-10-31'), list);
          // Opening one: each category against its target.
          ctx.area.querySelectorAll('.pcov-pick')[1].click(); await flush();
          assert.equal(ctx.sheet.heading.textContent, "Kraum, Ludevic's Opus");
          const words = ctx.area.textContent;
          assert(words.includes('Targeted disruption') && words.includes('Not counted') && words.includes('Basics fill the rest'), words);
          assert(words.includes('a second commander would widen its colours'), words);
          assert(ctx.area.querySelectorAll('.ccand-short').length === 3);
          // Back draws the ranking again without asking.
          ctx.sheet.foot.querySelector('[data-action="back"]').click(); await flush();
          assert.equal(asked.length, 1);
          assert(ctx.area.textContent.includes('Ghalta'));
        """)

    def test_a_members_space_asks_for_it_and_failures_show(self):
        self.run_js("""
          const cv = make({space: 'user2'}); cv.space = 'user2';
          const asked = [];
          api = async (path) => { asked.push(path); throw new ApiError(403, "That collection isn't public."); };
          const ctx = openCommanderCandidates(cv); await flush();
          same(asked, ['/api/commanders/candidates?space=user2']);
          assert(ctx.message.textContent.includes("That collection isn't public."), ctx.message.textContent);
          api = async () => ({...RANKED, candidates: [], total: 0, tags_available: false});
          await rankCandidates(ctx);
          assert(ctx.area.textContent.includes('Role tags are unavailable'), ctx.area.textContent);
          assert(ctx.area.textContent.includes('No card that may be a commander'), ctx.area.textContent);
        """)
