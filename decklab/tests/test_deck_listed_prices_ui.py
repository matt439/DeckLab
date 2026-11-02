"""The listed printing's price beside the cheapest one (E5-S31) on the deck page's banner, the Cards tab's
price table and the editor's missing list, through the real scripts. No network, no writes."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

LISTED = r"""
  const dear = (name, printing, cost) => ({name, printing, finish: 'foil', missing: 1, aud_each: cost, aud_missing: cost});
  const withListed = (listed, total = 600) => {
    const page = makePage();
    page.owned.rows[1] = {...page.owned.rows[1], aud_missing: 3.75, listed_printing: 'FIC 207 foil',
      listed_finish: 'foil', listed_aud_each: 560, listed_aud_missing: 1680, listed_material: true};
    page.owned.totals = {...page.owned.totals, as_listed: listed, aud_missing_as_listed: total};
    return page;
  };
  const bannerOf = (page) => availabilityBanner(page, {view: {tab: 'overview'}});
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ListedPriceUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), PAGE + LISTED + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_banner_says_cheapest_printings_and_lists_material_differences(self):
        self.run_js(r"""
          // No material difference: only the cheapest total, said to be for the cheapest printings.
          let banner = bannerOf(makePage());
          assert(banner.textContent.includes('3 missing, about A$3.75 at the cheapest printings'), banner.textContent);
          assert.equal(banner.querySelector('.deck-avail-listed'), null);
          // A card with no price: the qualifier stays on the figure.
          const unpriced = makePage(); unpriced.owned.totals = {...unpriced.owned.totals, unpriced: ['Bolt']};
          assert(bannerOf(unpriced).textContent.includes('about A$3.75 at the cheapest printings, and more'),
            bannerOf(unpriced).textContent);
          // One: named with its printing and price.
          banner = bannerOf(withListed([dear("Y'shtola, Night's Blessed", 'FIC 207 foil', 560)], 563.75));
          assert.equal(banner.querySelector('.deck-avail-listed').textContent,
            "As listed: Y'shtola, Night's Blessed (FIC 207 foil) about A$560.00.");
          // More than three fold into "and N more", with the total as listed.
          const many = ['A', 'B', 'C', 'D', 'E'].map((n, i) => dear(n, `SET ${i}`, 50 - i));
          many[0].missing = 2;
          banner = bannerOf(withListed(many, 300));
          assert.equal(banner.querySelector('.deck-avail-listed').textContent,
            'As listed: 2 A (SET 0) about A$50.00; B (SET 1) about A$49.00; C (SET 2) about A$48.00 and 2 more. ' +
            'About A$300.00 in all as listed.');
          // A price error leaves no A$ figure at all.
          const offline = withListed([dear('A', 'SET 0', 50)]); offline.owned.price_error = 'offline';
          banner = bannerOf(offline);
          assert(!banner.textContent.includes('A$'), banner.textContent);
        """)

    def test_banner_shows_nothing_to_a_viewer_who_may_not_see_the_collection(self):
        self.run_js(r"""
          const page = withListed([dear('A', 'SET 0', 50)]); delete page.owned;
          const banner = bannerOf(page);
          assert(!banner || (!banner.textContent.includes('As listed') && !banner.textContent.includes('A$')));
        """)

    def test_price_table_and_editor_show_the_listed_price_where_it_differs(self):
        self.run_js(r"""
          const page = withListed([dear('Bolt', 'FIC 207 foil', 560)]);
          clear(main); state.cards = new Map([['Elf', elf], ['Bolt', bolt]]);
          const section = ownedSection(page); main.append(section);
          const bodies = section.querySelectorAll('tbody');
          const boltBody = bodies.find((b) => b.textContent.includes('Bolt'));
          assert(boltBody.textContent.includes('As listed (FIC 207 foil): A$560.00 each'), boltBody.textContent);
          assert(boltBody.textContent.includes('A$1.25 each (estimate)'));       // the cheapest stays the figure
          assert(section.textContent.includes('"As listed" is the printing and finish your list names.'));
          assert(section.textContent.includes('Price table: 3 missing, about A$3.75 at the cheapest printings'));
          // Without a listed price anywhere the note doesn't explain "As listed".
          clear(main); const plain = ownedSection(makePage()); main.append(plain);
          assert(!plain.textContent.includes('As listed'), plain.textContent);
          // A listed price equal to the cheapest one, or none at all, adds nothing.
          assert.equal(listedPriceWords({...page.owned.rows[1], listed_aud_each: 1.25}), null);
          assert.equal(listedPriceWords({...page.owned.rows[1], listed_aud_each: null}), null);
          assert.equal(listedPriceWords({...page.owned.rows[1], missing: 0}), null);
          // The editor's missing list.
          const preview = ownedPreview(page.owned);
          assert(preview.textContent.includes('about A$3.75 at the cheapest printings (estimate).'), preview.textContent);
          assert(preview.textContent.includes('3 Bolt (about A$1.25 each); As listed (FIC 207 foil): A$560.00 each'),
            preview.textContent);
          assert(!ownedPreview(makePage().owned).textContent.includes('As listed'));
          // Loaded without deck-prices.js, the editor's list still draws, with no listed price.
          listedPriceWords = undefined;
          const bare = ownedPreview(page.owned);
          assert(bare.textContent.includes('3 Bolt (about A$1.25 each)') && !bare.textContent.includes('As listed'),
            bare.textContent);
        """)


if __name__ == "__main__":
    unittest.main()
