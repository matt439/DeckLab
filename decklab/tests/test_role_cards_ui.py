"""The Stats tab's "Free cards by role" (E9-S26, stats.js rolePoolPart) under Node: shown only on a Commander deck
whose collection the visitor may see, it asks GET /api/deck/role-cards once when opened and lists each role's free
cards, says when the card data has no role tags, and handles refusals and failures.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js; nothing is sent to a server.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = PAGE + """
  const role = (name, cards = [], extra = {}) => Object.assign({role: name, tag: name, tagged: true, cards, more: 0}, extra);
  const pick = (name, free = 1, here = free) => ({name, free, here, card: {name, roles: []}});
  const commanderPage = () => { const page = makePage();
    page.summary.id = 'commander/ghalta'; page.summary.kind = 'commander'; page.version = 'owned';
    page.stats = {commander: {}}; return page; };
  const asks = [];
  let answer = {tags_available: true, colours: ['G'], roles: [
    role('ramp', [pick('Sol Ring', 2, 1), pick('Llanowar Elves')], {more: 3}), role('removal'),
    role('counterspell', [], {tagged: false})]};
  api = async (path) => { asks.push(path); if (answer instanceof Error) throw answer; return answer; };
  const settle = async () => { for (let i = 0; i < 6; i += 1) await Promise.resolve(); };
  const openPart = async (part) => { part.open = true; part.fire('toggle'); await settle(); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class RoleCardsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_opening_lists_each_roles_free_cards_once(self):
        self.run_js("""
          const part = rolePoolPart(commanderPage());
          assert.equal(part.querySelector('summary').textContent, 'Free cards by role');
          assert.equal(asks.length, 0);
          await openPart(part);
          assert.deepEqual(asks, ['/api/deck/role-cards?id=commander%2Fghalta&version=owned']);
          const text = part.textContent;
          assert(text.includes('Ramp') && text.includes('Sol Ring 2 free, 1 on the way'), text);
          assert(text.includes('Llanowar Elves 1 free') && !text.includes('Llanowar Elves 1 free,'), text);
          assert(text.includes('And 3 more cards.'), text);
          assert(text.includes('Removal') && text.includes('None free in the commander\\'s colours.'), text);
          assert(text.includes('Unavailable: the card data has no cards with Scryfall\\'s "counterspell" tag.'), text);
          // Closing and opening again doesn't ask again.
          part.open = false; part.fire('toggle'); await openPart(part);
          assert.equal(asks.length, 1);
          // The whole composition panel carries it for a Commander deck.
          const page = commanderPage();
          assert(compositionPanel({types: [], roles: []}, page).querySelector('.role-pool-part'));
        """)

    def test_tags_unavailable_says_so(self):
        self.run_js("""
          answer = {tags_available: false, colours: ['G'], roles: [role('ramp', [], {tagged: false})]};
          const part = rolePoolPart(commanderPage());
          await openPart(part);
          assert(part.textContent.includes('Role tags are unavailable'), part.textContent);
          assert(!part.textContent.includes('Ramp'), part.textContent);
        """)

    def test_only_for_a_commander_deck_whose_collection_is_seen(self):
        self.run_js("""
          // A casual deck (no Commander stats), a visitor who may not see the collection (no "owned"), a product.
          assert.equal(rolePoolPart(makePage()), null);
          const hidden = commanderPage(); delete hidden.owned;
          assert.equal(rolePoolPart(hidden), null);
          assert.equal(compositionPanel({types: [], roles: []}, hidden).querySelector('.role-pool-part'), null);
          const product = commanderPage(); product.summary.id = 'product/fdc-test';
          assert.equal(rolePoolPart(product), null);
        """)

    def test_a_refusal_says_why_and_a_failure_offers_try_again(self):
        self.run_js("""
          answer = new ApiError(400, "Choose the deck's commander first: its colour identity says which cards fit.");
          const refused = rolePoolPart(commanderPage());
          await openPart(refused);
          assert(refused.textContent.includes('Choose the deck\\'s commander first'), refused.textContent);
          assert.equal(refused.querySelectorAll('button').length, 0);
          answer = new ApiError(500, 'The collection couldn\\'t be read.');
          const failed = rolePoolPart(commanderPage());
          await openPart(failed);
          assert(failed.textContent.includes('Free cards by role couldn\\'t be loaded.'), failed.textContent);
          answer = {tags_available: true, colours: [], roles: [role('ramp', [pick('Sol Ring')])]};
          buttonText(failed, 'Try again').click();
          await settle();
          assert(failed.textContent.includes('Sol Ring 1 free'), failed.textContent);
        """)


if __name__ == "__main__":
    unittest.main()
