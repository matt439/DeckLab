"""Print proxies (E4-S25) on the real deck page scripts.

The deterministic DOM fixture drives the real scripts; no server, collection or
image is touched, and nothing is written.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + """
  state.may = {see_inventory: ['home']};
  let printed = 0; window.print = () => { printed += 1; };
  const toasts = []; toast = (text) => toasts.push(text);
  const settle = async () => { for (let i = 0; i < 5; i++) { await null; flushTimers(); } };
  const sheet = () => document.querySelector('.proxy-sheet');
  const menu = (page) => deckMoreItems(page).filter((i) => i && i !== 'sep').map((i) => i.label);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckProxiesUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)],
                                input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_one_card_size_proxy_per_missing_copy(self):
        self.run_js("""
          const page = makePage();
          assert(menu(page).includes('Print proxies'));
          const copies = proxyCopies(page);
          same(copies.map((c) => c.name), ['Bolt', 'Bolt', 'Bolt']);
          printProxies(page); await settle();
          assert.equal(printed, 1);
          const cards = sheet().querySelectorAll('.proxy-card');
          assert.equal(cards.length, 3);
          same(cards.map((c) => c.querySelector('img').getAttribute('src')), Array(3).fill('/img/fdn/1/large'));
          assert(sheet().textContent.includes('3 missing copies of the Planned list'));
          assert(sheet().textContent.includes('each card is 63 × 88 mm'));
          assert(sheet().textContent.includes('2 copies are on the way and not printed.'));
          assert.equal(sheet().querySelectorAll('.card-page').length, 1);
          window.fire('afterprint');
          assert.equal(sheet(), null);
        """)

    def test_missing_copies_fall_on_the_sideboard_and_pages_hold_nine(self):
        self.run_js("""
          const page = makePage();
          page.sections.Sideboard = [{qty: 2, name: 'Elf', set: 'fdn', number: '1', finish: 'nonfoil', card: elf}];
          page.owned.rows[0] = row('Elf', 8, 2); page.owned.rows[1] = row('Bolt', 3, 3);
          page.sections.Deck[2].qty = 3;
          const extra = card('Giant', 'Creature — Giant', 5);
          page.sections.Deck.push({qty: 4, name: 'Giant', set: 'fdn', number: '9', finish: 'nonfoil', card: extra});
          page.owned.rows.push(row('Giant', 4, 4));
          page.owned.totals.missing = 9;
          same(proxyCopies(page).map((c) => c.name), ['Bolt', 'Bolt', 'Bolt', 'Giant', 'Giant', 'Giant', 'Giant', 'Elf', 'Elf']);
          page.owned.rows.push(row('Ooze', 1, 1));
          page.sections.Deck.push({qty: 1, name: 'Ooze', set: 'fdn', number: '10', finish: 'nonfoil', card: card('Ooze', 'Creature', 2)});
          printProxies(page); await settle();
          same(sheet().querySelectorAll('.card-page').map((p) => p.querySelectorAll('.proxy-card').length), [9, 1]);
        """)

    def test_each_proxy_names_the_stand_in_it_covers(self):
        self.run_js("""
          const page = makePage();
          page.standins = {version: 'target', warnings: [], rows: [
            {for: 'Bolt', using: 'Shock', qty: 1, card: bolt}, {for: 'Bolt', using: null, qty: 1, card: bolt}]};
          same(proxyCopies(page).map((c) => c.covers), ['Shock', 'any card', null]);
          printProxies(page); await settle();
          same(sheet().querySelector('.proxy-list').querySelectorAll('li').map((li) => li.textContent),
               ['1. Bolt: covers the stand-in (Shock)', '2. Bolt: covers the stand-in (any card)', '3. Bolt']);
          // The Play-now list's markers aren't the Planned list's.
          page.standins.version = 'owned';
          same(proxyCopies(page).map((c) => c.covers), [null, null, null]);
        """)

    def test_backs_and_cards_without_pictures(self):
        self.run_js("""
          const page = makePage();
          bolt.faces = [{img: '/img/fdn/3/normal'}, {img: '/img/fdn/3/normal-back'}];
          bolt.img = '/img/fdn/3/normal';
          page.owned.rows[1] = row('Bolt', 3, 1);
          page.owned.totals.missing = 1;
          same(proxyCopies(page).map((c) => c.face), [0, 1]);
          printProxies(page); await settle();
          same(sheet().querySelectorAll('img').map((i) => i.getAttribute('src')), ['/img/fdn/3/large', '/img/fdn/3/large-back']);
          window.fire('afterprint');
          page.sections.Deck[2].card = null;
          printProxies(page); await settle();
          const text = sheet().querySelector('.proxy-text');
          assert(text.textContent.includes('Bolt'));
          assert.equal(sheet().querySelectorAll('img').length, 0);
        """)

    def test_only_for_viewers_who_see_the_inventory_and_something_missing(self):
        self.run_js("""
          const page = makePage();
          page.owned.rows[1] = row('Bolt', 3, 0); page.owned.totals.missing = 0;
          assert(!menu(page).includes('Print proxies'));
          printProxies(page); await settle();
          assert.equal(printed, 0); assert(toasts.at(-1).includes('Nothing in the Planned list is missing'));
          const hidden = makePage(); delete hidden.owned;
          assert(!menu(hidden).includes('Print proxies'));
          printProxies(hidden); await settle();
          assert.equal(printed, 0); assert.equal(sheet(), null);
          state.may = {see_inventory: ['user2']};
          assert(!menu(makePage()).includes('Print proxies'));
        """)

    def test_the_play_now_list_prints_the_planned_lists_proxies(self):
        self.run_js("""
          const planned = makePage(), shown = makePage();
          shown.version = 'owned'; shown.owned.totals.missing = 0;
          const asked = [];
          api = async (url) => { asked.push(url); return planned; };
          assert(menu(shown).includes('Print proxies'));
          printProxies(shown); await settle();
          same(asked, ['/api/deck?id=casual%2Ftest&version=target&omit=matchups']);
          assert.equal(sheet().querySelectorAll('.proxy-card').length, 3);
          assert.equal(printed, 1);
        """)

    def test_card_names_are_text(self):
        self.run_js("""
          const page = makePage();
          page.sections.Deck[2].card = null; page.sections.Deck[2].name = '<img src=x>';
          page.owned.rows[1] = row('<img src=x>', 3, 3);
          printProxies(page); await settle();
          assert.equal(sheet().querySelectorAll('img').length, 0);
          assert(sheet().textContent.includes('<img src=x>'));
        """)


if __name__ == "__main__":
    unittest.main()
