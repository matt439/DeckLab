"""The deck page's Considering part (E2-S23, deck-considering.js) under Node: its cards after the decklist on
the Cards tab with whether a copy is free, nothing about the pool for a viewer the server sent no counts,
and the handoff to the normal edit draft for whoever may change the deck.

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
          assert(text.includes('Free now'), text);
          assert(text.includes('0 of 2 free now · 1 on the way'), text);
          assert(text.includes('0 of 1 free now'), text);
          // After the decklist, never in it.
          const list = main.querySelector('.deck-cards');
          assert(!list.textContent.includes('Black Lotus'));
          assert.equal(part.querySelectorAll('.card-row').length, 3);
        """)

    def test_no_counts_and_no_actions_for_a_viewer_who_may_not(self):
        self.run_js("""
          const page = withConsidering(false);
          page.summary.read_only = true;
          const part = showCards(page);
          assert(!part.textContent.includes('free'), part.textContent);
          assert.equal(part.querySelectorAll('.deck-considering-row').length, 0);
          assert.equal(part.querySelectorAll('a').find(a => a.getAttribute('href')?.includes('focus=considering')), undefined);
          // A name Scryfall doesn't know (only deck push gets one in) is still listed, without card data.
          page.considering.lines.push({qty: 1, name: 'Ghost Card', set: null, number: null, finish: 'nonfoil', card: null});
          const ghost = showCards(page);
          assert(ghost.textContent.includes('Ghost Card'), ghost.textContent);
          assert(ghost.textContent.includes('Card details unavailable'), ghost.textContent);
          assert(!main.querySelector('.deck-cards').textContent.includes('Ghost Card'));
          // An empty list nobody here may fill isn't shown at all.
          const empty = makePage(); empty.summary.read_only = true; empty.considering = {sha256: 'a', lines: []};
          assert.equal(showCards(empty), null);
          const product = makePage(); product.considering = null;
          assert.equal(showCards(product), null);
        """)

    def test_edit_and_add_enter_the_same_ordinary_draft(self):
        self.run_js("""
          const page = withConsidering();
          const part = showCards(page);
          const edit = part.querySelectorAll('a').find(a => a.getAttribute('href')?.includes('focus=considering'));
          assert.equal(edit.textContent, 'Edit Considering');
          assert.equal(edit.getAttribute('href'), '#/edit?id=casual%2Ftest&v=target&focus=considering');
          assert.equal(part.querySelectorAll('.menu-button').length, 0);
          page.version = 'owned';
          const alternative = showCards(page).querySelectorAll('a').find(a => a.getAttribute('href')?.includes('focus=considering'));
          assert.equal(alternative.getAttribute('href'), '#/edit?id=casual%2Ftest&v=owned&focus=considering');
          const empty = makePage(); empty.considering = {sha256: 'b', lines: []};
          const add = showCards(empty).querySelectorAll('a').find(a => a.getAttribute('href')?.includes('focus=considering'));
          assert.equal(add.textContent, 'Add a card to consider…');
          assert.equal(add.getAttribute('href'), '#/edit?id=casual%2Ftest&v=target&focus=considering&consider=');
        """)
