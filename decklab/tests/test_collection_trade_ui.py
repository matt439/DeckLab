"""The Collection page's "Record a trade…" (E7-S22, collection-trade.js), over the real scripts with fixture answers."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  const row = (name, set, number, quantity = 1) => ({name, set, collector_number: number, finish: 'nonfoil', quantity: String(quantity),
    condition: 'NM', language: 'en', notes: ''});
  const rows = [row('Llanowar Elves', 'fdn', '227', 4), row('Sol Ring', 'sld', '2539'), row('Black Lotus', 'lea', '232')];
  const draw = (data = {}) => { clear(main); as('matt', MAY.admin);
    return drawCollectionRows({space: 'home', sha256: 's1', rows, editable: true, ...data}, 'home'); };
  api = async (path) => {
    if (path.startsWith('/api/printings?name=')) return {name: 'Arcane Signet', printings: [
      {set: 'm3c', set_name: 'Modern Horizons 3 Commander', collector_number: '283', finishes: ['nonfoil', 'foil'], released: '2024-06-14'}]};
    if (path.startsWith('/api/cards/search')) return {cards: []};
    throw new Error('unexpected ' + path);
  };
  const type = (input, value) => { input.value = value; input.fire('input'); };
  const foot = (ctx, action) => ctx.sheet.foot.querySelector(`[data-action="${action}"]`);
  async function fill(ctx) {
    type(ctx.search, 'elves');
    button(ctx.sheet.body, 'Llanowar Elves (FDN 227) · 4 listed').click();
    button(ctx.sheet.body, '+').click();                           // two copies given
    ctx.card.inputs.name.value = 'Arcane Signet';
    await loadColPrintings(ctx.card, 'Arcane Signet'); await flush();
    ctx.card.inputs.quantity.value = '1';
    button(ctx.sheet.body, 'Add to the trade').click();
    ctx.with.value = 'User3';
  }
  const PREVIEW = {ok: true, sha256: 's1', gave: [{name: 'Llanowar Elves', set: 'fdn', collector_number: '227', finish: 'nonfoil',
    quantity: 2, before: 4, after: 2}], got: [{name: 'Arcane Signet', set: 'm3c', collector_number: '283', finish: 'nonfoil',
    quantity: '1', condition: '', language: '', notes: ''}], skipped_basics: 0, in_use: [], confirm_in_use: null,
    stale_tables: [], message: 'Trade with User3: gave 2 Llanowar Elves (FDN 227); got 1 Arcane Signet (M3C 283)', reason: 'Traded with User3'};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionTradeUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_both_sides_are_previewed_then_saved_as_one_trade(self):
        self.run_js("""
          const cv = draw();
          const ctx = await openTradeSheet(cv);
          // Preview can't act until both sides have cards, and says why.
          assert.equal(foot(ctx, 'preview').getAttribute('aria-disabled'), 'true');
          foot(ctx, 'preview').click();
          assert(ctx.sheet.body.textContent.includes('Add the cards that left first.'));
          await fill(ctx);
          assert.equal(foot(ctx, 'preview').getAttribute('aria-disabled'), null);
          assert(ctx.sheet.body.querySelector('.col-trade-got').textContent.includes('1 × Arcane Signet (M3C 283)'));
          const calls = [];
          apiWrite = async (path, body) => { calls.push([path, body]);
            if (path.endsWith('/preview')) return {...PREVIEW, stale_tables: [{id: 'casual/elves', title: 'Elves'}]};
            return {ok: true, sha256: 's2', rows, gave: 2, got: 1, stale_tables: [{id: 'casual/elves', title: 'Elves'}]}; };
          foot(ctx, 'preview').click(); await flush();
          const body = {space: 'home', sha256: 's1', gave: [{set: 'fdn', collector_number: '227', finish: 'nonfoil', quantity: 2}],
            got: [{name: 'Arcane Signet', set: 'm3c', collector_number: '283', finish: 'nonfoil', quantity: 1, condition: '',
              language: '', notes: ''}], with: 'User3'};
          same(calls, [['/api/collection/trade/preview', body]]);
          const review = ctx.sheet.body.querySelector('.col-trade-review').textContent;
          assert(review.includes('2 × Llanowar Elves (FDN 227): 4 listed, 2 left'), review);
          assert(review.includes("Saving leaves 1 deck's owned-vs-needed table out of date: Elves."), review);
          assert(review.includes('Trade with User3: gave 2 Llanowar Elves'), review);
          assert(!/A\\$|AUD|price/i.test(review), review);
          foot(ctx, 'save').click(); await flush();
          same(calls[1], ['/api/collection/trade', body]);
          assert(ctx.sheet.closed);
          assert.equal(cv.sha256, 's2');
          const said = main.querySelector('.col-message').textContent;
          assert(said.includes('Trade saved: gave 2 cards, got 1 card.'), said);
          assert(said.includes('See them on Decks'), said);
        """)

    def test_held_copies_need_save_it_anyway(self):
        self.run_js("""
          const ctx = await openTradeSheet(draw());
          await fill(ctx);
          const calls = [];
          const held = [{name: 'Llanowar Elves', before: 4, after: 2, in_use: 4, shortage: 2,
            holders: [{id: 'casual/elves', title: 'Elves', qty: 4}]}];
          apiWrite = async (path, body) => { calls.push(body);
            if (path.endsWith('/preview')) return {...PREVIEW, in_use: held, confirm_in_use: 'a'.repeat(64)};
            return {ok: true, sha256: 's2', rows, gave: 2, got: 1, stale_tables: []}; };
          foot(ctx, 'preview').click(); await flush();
          const box = ctx.sheet.body.querySelector('.col-trade-held');
          assert(box.textContent.includes('Llanowar Elves: 2 owned after the trade; 4 in use (2 short) in Elves (4)'), box.textContent);
          assert.equal(box.querySelector('a').getAttribute('href'), deckHref('casual/elves'));
          assert.equal(foot(ctx, 'save').getAttribute('aria-disabled'), 'true');
          foot(ctx, 'save').click(); await flush();
          assert.equal(calls.length, 1);                                // nothing sent before the tick
          const tick = box.querySelector('input[type="checkbox"]'); tick.checked = true; tick.fire('change');
          assert.equal(foot(ctx, 'save').getAttribute('aria-disabled'), null);
          foot(ctx, 'save').click(); await flush();
          assert.equal(calls[1].confirm_in_use, 'a'.repeat(64));
          assert(ctx.sheet.closed);
        """)

    def test_a_changed_collection_goes_back_to_the_trade_and_saves_nothing(self):
        self.run_js("""
          const cv = draw();
          const ctx = await openTradeSheet(cv);
          await fill(ctx);
          const latest = rows.slice(1);                                  // the Elves went meanwhile
          apiWrite = async () => { throw new ApiError(409, 'The home collection has changed since the page loaded it; look at it again and retry.',
            {sha256: 's9', rows: latest}); };
          foot(ctx, 'preview').click(); await flush();
          assert(!ctx.sheet.closed);
          assert.equal(cv.sha256, 's9');
          const text = ctx.sheet.body.textContent;
          assert(text.includes('No longer listed, so taken out of the cards that left: Llanowar Elves.'), text);
          assert(text.includes('Nothing was saved'), text);
          assert.equal(ctx.gave.length, 0);
          assert.equal(ctx.got.length, 1);                               // the cards that came in are kept
          assert.equal(foot(ctx, 'preview').getAttribute('aria-disabled'), 'true');
        """)

    def test_only_where_the_visitor_may_change_the_collection(self):
        self.run_js("""
          assert.equal(await openTradeSheet(draw({editable: false})), null);
          assert.equal(colSheets.size, 0);
        """)
