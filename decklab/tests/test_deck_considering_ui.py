"""The deck page's Considering part (E2-S23, deck-considering.js) under Node: its cards after the decklist on
the Cards tab with whether a copy is free, nothing about the pool for a viewer the server sent no counts,
and the move, remove and add saves (POST /api/deck/considering) for whoever may change the deck.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js; nothing is sent to a server.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  const lotus = card('Black Lotus', 'Artifact', 0, []);
  const withConsidering = (counts = true) => { const page = makePage();
    page.considering = {sha256: 'a'.repeat(64), lines: [
      Object.assign({qty: 1, name: 'Black Lotus', set: 'lea', number: '232', finish: 'nonfoil', card: lotus},
        counts ? {free: 1, on_the_way: 0} : {}),
      Object.assign({qty: 2, name: 'Bolt', set: 'fdn', number: '3', finish: 'nonfoil', card: bolt},
        counts ? {free: 1, on_the_way: 1} : {}),
      Object.assign({qty: 1, name: 'Elf', set: 'fdn', number: '1', finish: 'nonfoil', card: elf},
        counts ? {free: 0, on_the_way: 0} : {})]};
    return page; };
  const writes = [];
  api = async (path, opts) => { writes.push([path, JSON.parse(opts.body)]); return {saved: true}; };
  let routed = 0; route = () => { routed += 1; };
  const toasts = []; toast = (text) => toasts.push(text);
  const settle = async () => { for (let i = 0; i < 6; i += 1) await Promise.resolve(); };
  const showCards = (page) => { clear(main); location.hash = '#/deck?id=casual%2Ftest&tab=cards';
    drawDeck(page, deckViewOf(parseHash().params)); return main.querySelector('.deck-considering'); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckConsideringUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_cards_tab_lists_them_with_free_copies(self):
        self.run_js("""
          const part = showCards(withConsidering());
          assert(part, 'the Cards tab has the part');
          assert.equal(part.querySelector('h2').textContent, 'Considering');
          const text = part.textContent;
          assert(text.includes('Free in the pool'), text);
          assert(text.includes('1 of 2 free (1 on the way)'), text);
          assert(text.includes('None free'), text);
          // After the decklist, never in it.
          const list = main.querySelector('.deck-cards');
          assert(!list.textContent.includes('Black Lotus'));
          assert.equal(part.querySelectorAll('.deck-considering-row').length, 3);
        """)

    def test_no_counts_and_no_actions_for_a_viewer_who_may_not(self):
        self.run_js("""
          const page = withConsidering(false);
          page.summary.read_only = true;
          const part = showCards(page);
          assert(!part.textContent.includes('free'), part.textContent);
          assert.equal(part.querySelectorAll('.deck-considering-row').length, 0);
          assert(!part.textContent.includes('Add a card'));
          // An empty list nobody here may fill isn't shown at all.
          const empty = makePage(); empty.summary.read_only = true; empty.considering = {sha256: 'a', lines: []};
          assert.equal(showCards(empty), null);
          const product = makePage(); product.considering = null;
          assert.equal(showCards(product), null);
        """)

    def test_moves_removes_and_adds_are_saves(self):
        self.run_js("""
          const page = withConsidering();
          showCards(page);
          await saveConsidering(page, {action: 'move', index: 1});
          await saveConsidering(page, {action: 'remove', index: 0});
          await settle();
          same(writes.map(([path, body]) => [path, body.action, body.index, body.id, body.sha256.length]),
            [['/api/deck/considering', 'move', 1, 'casual/test', 64], ['/api/deck/considering', 'remove', 0, 'casual/test', 64]]);
          assert.equal(routed, 2);        // the page is drawn again from the saved deck
          same(toasts, ['Moved into the Planned list.', 'Taken off Considering.']);
          const empty = makePage(); empty.considering = {sha256: 'b', lines: []};
          const part = showCards(empty);
          assert(part.textContent.includes('No cards being considered'));
          buttonText(part, 'Add a card to consider…').click();
          const sheet = document.body.querySelectorAll('dialog').pop();
          const [name, qty] = sheet.querySelectorAll('input');
          name.value = 'Opt'; qty.value = '2';
          sheet.querySelectorAll('button').find((b) => b.textContent === 'Add').click();
          await settle();
          same(writes[2][1].line, {name: 'Opt', qty: 2});
        """)
