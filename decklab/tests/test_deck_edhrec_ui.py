"""A Commander deck's EDHREC ideas (E9-S07, deck-edhrec.js) under Node: a button on the Cards tab of a
Commander deck only, nothing asked of the server until it's pressed, the sheet's cards grouped by EDHREC's
categories with their share and marks (none for a viewer the server sent none), a failure said plainly,
the Page choice narrowing them to one of EDHREC's budget, bracket or theme pages, and Consider adding a card to the deck's Considering list (POST /api/deck/considering).

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js; nothing is sent to a server.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  const idea = (name, inclusion, extra = {}) => Object.assign({name, inclusion, decks: inclusion * 10, of: 1000,
    synergy: 0.1, in_deck: false, considering: false, card: card(name, 'Creature', 1)}, extra);
  const ANSWER = (marks = true) => ({deck_id: 'commander/test', commanders: ['Ghalta, Primal Hunger'], identity: 'G',
    sha256: 'a'.repeat(64), marks, may_add: marks, warnings: [], left_out: [{name: 'Wrath of God', why: 'x'}],
    rate: marks ? 1.43 : null, rate_date: '2026-10-27', price_date: '2026-10-28', price_error: null,
    source: {commander: 'Ghalta, Primal Hunger', decks: 1000, url: 'https://edhrec.com/commanders/ghalta-primal-hunger',
      fetched: '2026-10-28T01:02:03+00:00', stale: null},
    groups: [{header: 'High Synergy Cards', cards: [
      idea('Elf', 80, marks ? {in_deck: true, status: 'in_deck', free: 0, on_the_way: 0} : {in_deck: true}),
      idea('Elvish Mystic', 64, marks ? {status: 'free', free: 2, on_the_way: 1} : {}),
      idea('Pick Your Poison', 26, marks ? {status: 'to_buy', free: 0, on_the_way: 0, aud_each: 0.39} : {})]},
      {header: 'Lands', cards: [idea('Bojuka Bog', 30, marks ? {status: 'in_use', free: 0, on_the_way: 0} : {})]}]});
  const asked = [];
  let answer = ANSWER(), pageAnswer = null;
  const PAGES = [{page: 'budget', label: 'Budget', group: 'budget', decks: null},
    {page: 'core', label: 'Core (bracket 2)', group: 'bracket', decks: null},
    {page: 'elves', label: 'Elves', group: 'theme', decks: 120}];
  api = async (path, opts) => {
    asked.push([path, opts && opts.body ? JSON.parse(opts.body) : null]);
    if (path.startsWith('/api/deck/edhrec')) {
      const got = path.includes('&page=') && pageAnswer ? pageAnswer : answer;
      if (got instanceof Error) throw got;
      return got;
    }
    return {saved: true, sha256: 'b'.repeat(64)};
  };
  let routed = 0; route = () => { routed += 1; };
  const toasts = []; toast = (text) => toasts.push(text);
  const settle = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };
  const commanderPage = () => { const page = makePage(); page.summary.kind = 'commander'; page.summary.id = 'commander/test'; return page; };
  const showCards = (page) => { clear(main); location.hash = '#/deck?id=' + encodeURIComponent(page.summary.id) + '&tab=cards';
    drawDeck(page, deckViewOf(parseHash().params)); return main.querySelector('.deck-edhrec'); };
  const openIdeas = async (page) => { const part = showCards(page); buttonText(part, 'See EDHREC ideas…').click(); await settle();
    return document.body.querySelectorAll('dialog').pop(); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckEdhrecUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_a_commander_deck_offers_it_and_nothing_is_asked_until_pressed(self):
        self.run_js("""
          assert.equal(showCards(makePage()), null);
          const part = showCards(commanderPage());
          assert(part, 'the Cards tab has the part');
          assert.equal(part.querySelector('h2').textContent, 'EDHREC ideas');
          assert(!asked.some(([path]) => path.startsWith('/api/deck/edhrec')), 'not asked on a page load');
        """)

    def test_the_sheet_groups_and_marks_them(self):
        self.run_js("""
          const sheet = await openIdeas(commanderPage());
          same(asked.map(([path]) => path).filter((path) => path.startsWith('/api/deck/')), ['/api/deck/edhrec?id=commander%2Ftest']);
          const text = sheet.textContent;
          assert(text.includes(`Ghalta, Primal Hunger on EDHREC, from ${num(1000)} decks, fetched 2026-10-28`), text);
          assert(text.includes('High Synergy Cards') && text.includes('Lands'), text);
          // Not in the deck by default: the deck's own Elf is left out until All.
          assert(!text.includes('In the deck'), text);
          assert(text.includes('64% of decks · 2 free · 1 on the way'), text);
          assert(text.includes('26% of decks · To buy · ~A$0.39'), text);
          assert(text.includes('Owned, all in other decks'), text);
          assert(text.includes(`1 USD = ${num(1.43, 4)} AUD (ECB rate of 2026-10-27)`), text);
          assert(text.includes('1 card left out'), text);
          buttonText(sheet, 'To buy (1)').click();
          assert(!sheet.textContent.includes('Elvish Mystic'));
          assert(!sheet.textContent.includes('Lands'));
          buttonText(sheet, 'All (4)').click();
          assert(sheet.textContent.includes('80% of decks · In the deck'));
          const link = sheet.querySelectorAll('a').find((a) => a.textContent === 'Open on EDHREC');
          assert.equal(link.getAttribute('rel'), 'noopener noreferrer');
        """)

    def test_no_marks_and_no_consider_for_a_viewer_who_may_not(self):
        self.run_js("""
          answer = ANSWER(false);
          const sheet = await openIdeas(commanderPage());
          const text = sheet.textContent;
          assert(!/free|To buy|Owned/.test(text.replace("isn't yours to see", '')), text);
          assert(text.includes("nothing here says what's owned"), text);
          assert(!buttonText(sheet, 'Consider'));
          same(sheet.querySelector('.segmented').querySelectorAll('button').map((b) => b.textContent), ['Not in the deck (3)', 'All (4)']);
        """)

    def test_a_failure_is_said_plainly(self):
        self.run_js("""
          answer = new ApiError("EDHREC couldn't be reached (offline). Try again later: nothing else on the page needs it.", 502);
          const sheet = await openIdeas(commanderPage());
          assert(sheet.textContent.includes("EDHREC couldn't be reached"), sheet.textContent);
          assert(buttonText(sheet, 'Try again'));
          answer = ANSWER();
          buttonText(sheet, 'Try again').click();
          await settle();
          assert(sheet.textContent.includes('High Synergy Cards'));
        """)

    def test_the_page_choice_narrows_the_ideas(self):
        self.run_js("""
          answer = Object.assign(ANSWER(), {page: '', pages: PAGES});
          const sheet = await openIdeas(commanderPage());
          const select = sheet.querySelector('#edhrec-page');
          assert(select, 'a Page choice');
          same(select.querySelectorAll('optgroup').map((g) => g.getAttribute('label')), ['Budget', 'Commander Brackets', 'Themes']);
          same(select.querySelectorAll('option').map((o) => o.textContent),
            ['All decks with this commander', 'Budget', 'Core (bracket 2)', 'Elves (120 decks)']);
          pageAnswer = Object.assign(ANSWER(), {page: 'budget', pages: PAGES,
            groups: [{header: 'Budget Cards', cards: [idea('Cheap Elf', 50, {status: 'to_buy', free: 0, on_the_way: 0, aud_each: 0.1})]}]});
          select.value = 'budget'; select.fire('change'); await settle();
          same(asked.map(([path]) => path).filter((path) => path.startsWith('/api/deck/edhrec')),
            ['/api/deck/edhrec?id=commander%2Ftest', '/api/deck/edhrec?id=commander%2Ftest&page=budget']);
          let text = sheet.textContent;
          assert(text.includes('Ghalta, Primal Hunger on EDHREC (Budget page)'), text);
          assert(text.includes('Budget Cards') && text.includes('Cheap Elf') && !text.includes('High Synergy Cards'), text);
          // A page EDHREC hasn't got says so, and the choice stays to pick another.
          pageAnswer = new ApiError(404, 'EDHREC has no core page for this commander, so there are no ideas to show there. Choose another page.');
          let again = sheet.querySelector('#edhrec-page');
          again.value = 'core'; again.fire('change'); await settle();
          text = sheet.textContent;
          assert(text.includes('EDHREC has no core page'), text);
          assert(!buttonText(sheet, 'Try again'));
          again = sheet.querySelector('#edhrec-page');
          assert(again, 'the choice is still there');
          again.value = ''; again.fire('change'); await settle();
          assert.equal(asked.map(([path]) => path).filter((path) => path.startsWith('/api/deck/edhrec')).at(-1), '/api/deck/edhrec?id=commander%2Ftest');
          assert(sheet.textContent.includes('High Synergy Cards'));
          assert(!sheet.textContent.includes('page)'));
        """)

    def test_no_page_choice_without_pages(self):
        self.run_js("""
          const sheet = await openIdeas(commanderPage());
          assert.equal(sheet.querySelector('#edhrec-page'), null);
        """)

    def test_consider_adds_to_the_considering_list(self):
        self.run_js("""
          const page = commanderPage();
          const sheet = await openIdeas(page);
          const buttons = sheet.querySelectorAll('button').filter((b) => b.textContent === 'Consider');
          assert.equal(buttons.length, 3);
          assert.equal(buttons[0].getAttribute('aria-label'), 'Add Elvish Mystic to the Considering list');
          buttons[0].click(); await settle();
          buttons[1].click(); await settle();
          const writes = asked.filter(([path]) => path === '/api/deck/considering').map(([, body]) => body);
          same(writes.map((b) => [b.id, b.sha256, b.action, b.line]),
            [['commander/test', 'a'.repeat(64), 'add', {name: 'Elvish Mystic', qty: 1}],
             ['commander/test', 'b'.repeat(64), 'add', {name: 'Pick Your Poison', qty: 1}]]);
          assert.equal(buttons[0].textContent, 'Considering');
          assert(buttons[0].disabled);
          same(toasts, ['Added Elvish Mystic to Considering.', 'Added Pick Your Poison to Considering.']);
          assert.equal(routed, 0);
          buttonText(sheet, 'Close').click();
          assert.equal(routed, 1);              // the page drawn again with its Considering list
        """)


if __name__ == "__main__":
    unittest.main()
