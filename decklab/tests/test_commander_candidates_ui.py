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
  const pic = (name) => ({name, mana_cost: '{G}', type_line: 'Creature', cmc: 1, color_identity: ['G'], img_small: null});
  const row = (name, free = 1) => ({name, free, card: pic(name)});
  const CARDS = {space: 'home', name: "Kraum, Ludevic's Opus", colours: ['U', 'R'], source: RANKED.source,
    categories: [{category: 'lands', label: 'Lands', target: 38, count: 1, short: false, in_coverage: false, cards: [row('Shivan Reef')], more: 0},
      {category: 'ramp', label: 'Ramp', target: 10, count: 12, short: false, in_coverage: true, cards: [row('Sol Ring', 2)], more: 11},
      {category: 'mass disruption', label: 'Mass disruption', target: 6, count: 0, short: true, in_coverage: true, cards: [], more: 0}],
    others: {cards: [row('Grizzly Bears')], more: 0, count: 1}};
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
          api = async (path) => { asked.push(path); return path.startsWith('/api/commanders/candidate?') ? CARDS : RANKED; };
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
          assert(words.includes('its pairs with free cards are rows of their own'), words);
          assert(ctx.area.querySelectorAll('.ccand-short').length === 3);
          // Its free cards by name, asked once it's opened.
          same(asked, ['/api/commanders/candidates?', '/api/commanders/candidate?name=Kraum%2C+Ludevic%27s+Opus']);
          assert(words.includes('Free cards by role') && words.includes('Sol Ring') && words.includes('2 free'), words);
          assert(words.includes('12 of 10') && words.includes('11 more cards not listed.'), words);
          assert(words.includes('0 of 6, 6 short') && words.includes('None free in its colours.'), words);
          assert(words.includes('Shivan Reef') && words.includes('basics fill the rest'), words);
          assert(words.includes('Other free cards') && words.includes('Grizzly Bears'), words);
          // New deck from it: the new-deck editor with it as the commander.
          const link = ctx.area.querySelector('.ccand-actions').querySelector('a');
          assert.equal(link.textContent, 'New deck from it');
          assert.equal(link.getAttribute('href'), "#/new?kind=commander&commander=Kraum%2C+Ludevic%27s+Opus");
          // See EDHREC ideas: deck-edhrec.js's sheet for this commander and space, no deck.
          ctx.area.querySelector('.ccand-actions').querySelector('button').click(); await flush();
          assert.equal(asked[2], "/api/deck/edhrec?commander=Kraum%2C%20Ludevic's%20Opus&space=home");
          // Back draws the ranking again without asking.
          ctx.sheet.foot.querySelector('[data-action="back"]').click(); await flush();
          assert.equal(asked.length, 3);
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
          // A viewer who may not add decks in the space gets no New deck from it.
          state.may = {...state.may, create: [{space: 'home', player: null}]};
          assert.equal(candidateNewDeckHref(ctx, {name: 'Ghalta, Primal Hunger'}), null);
          state.may = {...state.may, create: [{space: 'user2', player: null}]};
          assert.equal(candidateNewDeckHref(ctx, {name: 'Ghalta, Primal Hunger'}), '#/new?kind=commander&commander=Ghalta%2C+Primal+Hunger&space=user2');
          api = async () => ({...RANKED, candidates: [], total: 0, tags_available: false});
          await rankCandidates(ctx);
          assert(ctx.area.textContent.includes('Role tags are unavailable'), ctx.area.textContent);
          assert(ctx.area.textContent.includes('No card that may be a commander'), ctx.area.textContent);
        """)


PAIRS = """
  const PAIR = lead("Kraum, Ludevic's Opus and Tymna the Weaver", ['W', 'U', 'B', 'R'], 34, ['Mass disruption'],
    {kind: 'pair', names: ["Kraum, Ludevic's Opus", 'Tymna the Weaver'], pairing: 'partner',
     faces: [{name: "Kraum, Ludevic's Opus", free: 1, card: null}, {name: 'Tymna the Weaver', free: 2, card: null}]});
  const HELD = lead('Ghalta, Primal Hunger', ['G'], 30, [], {kind: 'held', free: 0,
    held_by: [{id: 'commander/stompy', title: 'Ghalta Stompy', quantity: 1}, {id: null, title: 'one of the home decks', quantity: 1}]});
  const WITH = {...RANKED, total: 3, candidates: [PAIR, ...RANKED.candidates], pairs: {found: 120, left_out: 20, untried: 4},
    held: [HELD], held_total: 1};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CommanderPairsUiTests(unittest.TestCase):
    """E9-S28's third slice: pair rows, the caps' words, and the held rows apart, naming their decks."""

    def run_js(self, code):
        CommanderCandidatesUiTests.run_js(self, PAIRS + code)

    def test_a_pair_opens_with_both(self):
        self.run_js("""
          const cv = make();
          const asked = [];
          api = async (path) => { asked.push(path); return path.startsWith('/api/commanders/candidate?') ? CARDS : WITH; };
          const ctx = openCommanderCandidates(cv); await flush();
          const list = ctx.area.textContent;
          assert(list.includes("Kraum, Ludevic's Opus and Tymna the Weaver") && list.includes('together by partner'), list);
          assert(list.includes("20 more pairs of the 120 found aren't listed.") && list.includes("4 cards that may pair weren't tried"), list);
          ctx.area.querySelector('.ccand-pair').querySelector('.pcov-pick').click(); await flush();
          same(asked.slice(1), ["/api/commanders/candidate?name=Kraum%2C+Ludevic%27s+Opus&partner=Tymna+the+Weaver"]);
          assert.equal(ctx.area.querySelector('.ccand-tile').children.length, 2);
          const words = ctx.area.textContent;
          assert(words.includes('Two commanders together (partner)') && words.includes('2 free'), words);
          const link = ctx.area.querySelector('.ccand-actions').querySelector('a');
          assert.equal(link.getAttribute('href'), "#/new?kind=commander&commander=Kraum%2C+Ludevic%27s+Opus&partner=Tymna+the+Weaver");
          ctx.area.querySelector('.ccand-actions').querySelector('button').click(); await flush();
          assert.equal(asked[2], "/api/deck/edhrec?commander=Kraum%2C%20Ludevic's%20Opus&commander2=Tymna%20the%20Weaver&space=home");
        """)

    def test_held_rows_come_after_naming_their_decks(self):
        self.run_js("""
          const cv = make();
          api = async (path) => path.startsWith('/api/commanders/candidate?') ? CARDS : WITH;
          const ctx = openCommanderCandidates(cv); await flush();
          const list = ctx.area.textContent;
          assert(list.indexOf('Held by a deck') > list.indexOf('Kraum, Ludevic'), list);
          const held = ctx.area.querySelector('.ccand-held-list');
          assert(held.textContent.includes('in Ghalta Stompy and one of the home decks'), held.textContent);
          assert.equal(ctx.area.querySelectorAll('.ccand-held').length, 1);
          held.querySelector('.pcov-pick').click(); await flush();
          const words = ctx.area.textContent;
          assert(words.includes('Every copy is in Ghalta Stompy and one of the home decks') && words.includes('None free'), words);
        """)
