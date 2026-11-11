'use strict';
// Invented basket/plan facts, copied text and cancelled order reviews. No retailer or saved order.
const path = require('node:path');
const assert = require('node:assert/strict');
const {run} = require('./common.js');

const AT = '2026-11-10T03:05:00Z';
const NAMES = ['Long Synthetic Woodland Card with Several Different Available Printings', 'Exact Synthetic Card',
  'Unpriced Synthetic Card', 'Zero Price Synthetic Card', 'Optional Synthetic Add-on Already on the Queue',
  'Unchecked Synthetic Card', 'Unconfirmed Synthetic Printing', 'Unread Synthetic Card'];

function payload(stale = false) {
  const queue = (number, extra = {}) => ({queue_row: number, name: NAMES[number - 1], quantity: 1, state: 'ready',
    for: 'Synthetic deck for layout review', printing: 'any', set: '', collector_number: '', finish: '', source: '',
    notes: 'Synthetic queue intent only.', listed_at: '', listed_aud: '', checked: '', in_stock: '', deck: null,
    card: number <= 2 ? {name: NAMES[number - 1], mana_cost: '', type_line: 'Synthetic review card',
      img: `/img/synthetic/basket-${number}/normal`, img_small: `/img/synthetic/basket-${number}/small`} : null, ...extra});
  const rows = [queue(1, {quantity: 4}), queue(2, {printing: 'exact', set: 'fdn', collector_number: '2', finish: 'nonfoil'}),
    queue(3, {quantity: 2}), queue(4), queue(5, {state: 'long_term', quantity: 2}), queue(6),
    queue(7, {printing: 'exact', set: 'old', collector_number: '7', finish: 'nonfoil'}), queue(8)];
  const listing = (number, price, extra = {}) => ({set: 'fdn', collector_number: String(number), finish: 'nonfoil',
    price_aud: price, stock: 7, copies: 1, condition: 'Near Mint', language: 'English',
    url: `https://www.mtgmate.com.au/cards/Synthetic/FDN/${number}`, ...extra});
  const line = (number, extra = {}) => ({...rows[number - 1], status: 'in_stock', fetched_at: AT, carried: false,
    is_token: false, add_on: false, copies: Number(rows[number - 1].quantity), stock: 7, short: false, line_aud: '1.00',
    listing: listing(number, '1.00'), more: [], ...extra});
  const mtgRows = [
    line(1, {copies: 3, stock: 3, short: true, line_aud: '1.40', partial: true,
      listing: listing(1, '0.40', {copies: 1, stock: 1}), more: [listing(12, '0.50', {set: 'm19', copies: 2, stock: 2,
        url: 'https://www.mtgmate.com.au/cards/Synthetic/M19/12', condition: 'Lightly Played'})]}),
    line(2), line(3, {line_aud: null, listing: listing(3, null, {copies: 2})}),
    line(4, {line_aud: '0.00', listing: listing(4, '0.00')}),
  ];
  const gpRows = [line(2, {line_aud: '0.50', listing: listing(2, '0.50', {stock: 1,
    url: 'https://gamesportal.com.au/products/synthetic-exact?variant=2'})}),
  line(4, {line_aud: '0.00', listing: listing(4, '0.00', {stock: 1,
    url: 'https://gamesportal.com.au/products/synthetic-zero'})})];
  const postage = {postage_aud: '8.00', free_over_aud: '10.00', charged_aud: '8.00', known: true,
    free: false, short_by_aud: '7.60', at_least: true};
  const unknownPostage = {postage_aud: null, free_over_aud: null, charged_aud: null, known: false,
    free: false, short_by_aud: null, at_least: false};
  const addOn = line(5, {add_on: true, lifts: true, line_aud: '8.00', listing: listing(5, '4.00', {copies: 2})});
  const basket = (key, shop, extra = {}) => ({key, shop, site: '', read: true, counts_stock: key === 'mtgmate',
    fetched_at: AT, rows: [], add_ons: [], unconfirmed: [], unknown: [], not_checked: [],
    total_aud: null, priced: 0, unpriced: 0, cards: 0, add_ons_totals: {}, ...extra});
  const mtg = basket('mtgmate', 'MTGMate', {rows: mtgRows, total_aud: '2.40', priced: 3, unpriced: 1, cards: 7, postage,
    add_ons: [addOn], add_ons_totals: {total_aud: '8.00', priced: 1, unpriced: 0, cards: 2},
    reach: {rows: [5], total_aud: '8.00', reaches: true},
    unconfirmed: [rows[6]], unknown: [rows[7]], not_checked: [rows[5]]});
  const gp = basket('gamesportal', 'Games Portal', {rows: gpRows, total_aud: '0.50', priced: 2, unpriced: 0, cards: 2,
    postage: unknownPostage, unconfirmed: [rows[6]], unknown: [rows[2], rows[7]], not_checked: [rows[5]]});
  const planRow = row => ({queue_row: row.queue_row, name: row.name, quantity: row.quantity, state: row.state,
    printing: row.printing, set: row.set, collector_number: row.collector_number, finish: row.finish,
    copies: row.copies, line_aud: row.line_aud});
  const planShop = (source, chosen, subtotal, extra = {}) => ({key: source.key, shop: source.shop,
    rows: chosen.map(planRow), cards: chosen.reduce((sum, row) => sum + row.copies, 0), subtotal_aud: subtotal,
    unpriced: chosen.filter(row => row.line_aud == null).length, postage: source.postage, ...extra});
  const bestShop = planShop(mtg, mtgRows, '2.40', {postage: {...postage, reach: mtg.reach}});
  const splitShops = [planShop(mtg, [mtgRows[0], mtgRows[2]], '1.40'), planShop(gp, gpRows, '0.50')];
  const option = (shops, extra = {}) => ({shops, keys: shops.map(shop => shop.key), cards: 7, uncovered: [rows[0], rows[5], rows[6], rows[7]],
    cards_aud: '2.40', postage_aud: '8.00', postage_unknown: [], total_aud: '10.40', unpriced: 1, ...extra});
  const best = option([bestShop]);
  const split = option(splitShops, {cards_aud: '1.90', total_aud: '9.90', postage_unknown: ['Games Portal']});
  const gpOnly = option([planShop(gp, gpRows, '0.50')], {cards: 2, cards_aud: '0.50', postage_aud: '0.00',
    total_aud: '0.50', unpriced: 0, postage_unknown: ['Games Portal']});
  return {queue_revision: 'synthetic-basket-q1', to_buy: rows, orders: [], checks: [], warnings: [], queue_decks: [], decks_missing: [],
    baskets: {queue_revision: stale ? 'synthetic-basket-q0' : 'synthetic-basket-q1', shops: [mtg, gp,
      basket('unread', 'Synthetic unread shop', {read: false, fetched_at: null})],
    unavailable: [{...rows[5], shops: [{shop: 'MTGMate', status: 'not_checked'}, {shop: 'Games Portal', status: 'unknown', partial: true},
      {shop: 'Synthetic unread shop', status: 'unread'}]}],
    plan: {recommended: best, by_price: split, options: [best, split, gpOnly], wanted: 11, weighed: false, saves_aud: null}}};
}

async function measure(page) {
  return page.evaluate(() => {
    const box = node => {
      const b = node.getBoundingClientRect();
      return {x: b.x, y: b.y, right: b.right, bottom: b.bottom, width: b.width, height: b.height};
    };
    const root = document.getElementById('shop-baskets').closest('section');
    const visible = node => node.checkVisibility() && node.getBoundingClientRect().width > 0;
    return {width: innerWidth, clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth,
      coarse: matchMedia('(pointer:coarse)').matches, rootFont: getComputedStyle(document.documentElement).fontSize,
      root: box(root), text: root.innerText,
      controls: [...root.querySelectorAll('button,a,summary')].filter(visible).map(node => ({...box(node),
        tag: node.tagName, text: node.textContent.trim(), label: node.getAttribute('aria-label'), disabled: !!node.disabled,
        href: node.getAttribute('href'), target: node.getAttribute('target'), rel: node.getAttribute('rel')})),
      rows: [...root.querySelectorAll('[data-basket-row],[data-plan-row],[data-plan-option]')].filter(visible).map(node => ({...box(node),
        name: node.dataset.basketRow || node.dataset.planRow || node.dataset.planOption, text: node.textContent})),
      overflow: [...root.querySelectorAll('*')].filter(visible).filter(node => {
        const b = node.getBoundingClientRect(); return b.x < -1 || b.right > document.documentElement.clientWidth + 1;
      }).slice(0, 15).map(node => ({className: node.className, text: node.textContent.slice(0, 100), ...box(node)}))};
  });
}

function geometry(metrics) {
  assert.equal(metrics.scrollWidth > metrics.clientWidth, false, 'Shopping caused document overflow');
  assert(metrics.root.x >= -1 && metrics.root.right <= metrics.clientWidth + 1, 'Baskets left the viewport');
  assert.equal(metrics.overflow.length, 0, 'Basket content left its viewport');
  for (const control of metrics.controls) {
    assert(control.x >= -1 && control.right <= metrics.clientWidth + 1, 'Basket control left the viewport');
    if (metrics.coarse) assert(control.height >= 44, `Basket control lost touch floor: ${control.label || control.text}`);
    if (control.href?.startsWith('https:')) {
      const url = new URL(control.href);
      assert(['www.mtgmate.com.au', 'gamesportal.com.au'].includes(url.hostname), 'Unexpected external listing host');
      assert.equal(control.target, '_blank'); assert.equal(control.rel, 'noopener noreferrer');
    }
  }
}

async function activate(page, locator, root200) {
  if (root200) {await locator.focus(); await page.keyboard.press('Enter');} else await locator.click();
}

run('shopping-baskets-layout', async review => {
  review.report.results = [];
  review.report.scope = 'Invented baskets and fewest-shops plans, including partial stock, alternate printings, zero/unknown prices, unpriced totals, add-ons and unread checks. Copy is intercepted; order previews are invented replies and cancelled. Read-only adapters qualify UI presentation, not backend authorization. No retailer fetch or final write.';
  const specs = [];
  for (const theme of ['light', 'dark']) {
    for (const width of (review.options.smoke ? [393, 1440] : [320, 393, 430, 600, 820, 1280, 1440]))
      specs.push({theme, width, height: 1000, coarse: width < 1000, mode: 'current'});
    for (const width of (review.options.smoke ? [320] : [320, 600]))
      specs.push({theme, width, height: 1000, coarse: true, root200: true, mode: 'current'});
    for (const mode of ['read-only', 'stale']) specs.push({theme, width: 393, height: 1000, coarse: true, mode});
  }
  review.report.expected_captures = specs.length;
  for (const spec of specs) {
    const result = {spec, status: 'failed', page_errors: [], http_errors: [], copies: [], previews: [], final_writes: []};
    let context, page;
    try {
      review.select('matt'); context = await review.context(spec);
      await context.exposeBinding('__reviewBasketClipboard', (_source, text) => result.copies.push(text));
      await context.addInitScript(() => Object.defineProperty(navigator, 'clipboard', {configurable: true,
        value: {writeText: text => window.__reviewBasketClipboard(text)}}));
      page = await context.newPage(); page.setDefaultTimeout(10000);
      review.observe(page, result.page_errors, result.http_errors);
      page.on('request', request => {
        if (!['GET', 'HEAD'].includes(request.method()) && !['/api/visit', '/api/shopping/order/preview'].includes(new URL(request.url()).pathname))
          result.final_writes.push(review.safeUrl(request.url()));
      });
      if (spec.mode === 'read-only') {
        await page.route('**/api/profiles', async route => {
          const response = await route.fetch(), body = await response.json();
          body.profiles = body.profiles.map(profile => profile.id === 'matt' ? {...profile, role: 'member'} : profile);
          return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
        });
        await page.route('**/api/me', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
          profile: 'matt', remote: true, may: {admin: false, orders: false, see_inventory: ['home'], see_home_records: true}})}));
      }
      const source = JSON.stringify(payload(spec.mode === 'stale'));
      await page.route('**/api/shopping', route => route.fulfill({status: 200, contentType: 'application/json', body: source}));
      await page.route('**/img/synthetic/**', route => route.fulfill({status: 200, contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="244" height="340"><rect width="244" height="340" fill="#496658"/><text x="20" y="60" fill="white" font-size="20">Synthetic card</text></svg>'}));
      await page.route('**/api/shopping/order/preview', route => {
        const body = route.request().postDataJSON(); result.previews.push(body);
        return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({preview: 'synthetic-basket-review',
          tables: {written: [], skipped: []}, watchlist_reduced: [{name: NAMES[0], quantity: 3, left: 1}]})});
      });
      await page.goto(review.pageUrl('/#/shopping', spec.theme), {waitUntil: 'domcontentloaded'});
      const root = page.locator('#shop-baskets').locator('..').locator('..');
      await page.locator('.shop-plan').waitFor(); await page.evaluate(() => document.fonts.ready);
      if (spec.root200) await page.evaluate(() => {document.documentElement.style.fontSize = '200%';});
      const mtg = page.locator('[data-basket="mtgmate"]'), gp = page.locator('[data-basket="gamesportal"]'), plan = page.locator('.shop-plan');
      await page.waitForTimeout(100);
      if (spec.width === 393 || spec.root200) {
        await plan.evaluate(node => window.scrollTo(0, scrollY + node.getBoundingClientRect().top - 80));
        const suffix = `${spec.width}-${spec.theme}-${spec.mode}${spec.root200 ? '-root200' : ''}`;
        result.plan_png = `fewest-shops-${suffix}.png`; await page.screenshot({path: path.join(review.out, result.plan_png), animations: 'disabled'});
        await mtg.evaluate(node => window.scrollTo(0, scrollY + node.getBoundingClientRect().top - 80));
        result.basket_png = `basket-${suffix}.png`; await page.screenshot({path: path.join(review.out, result.basket_png), animations: 'disabled'});
      }
      result.initial = await measure(page); geometry(result.initial);
      assert.equal(await mtg.locator(':scope > .shop-basket-rows [data-basket-row]').count(), 4);
      assert.equal(await gp.locator(':scope > .shop-basket-rows [data-basket-row]').count(), 2);
      assert.equal(await mtg.locator('.shop-basket-addons [data-basket-row]').count(), 1);
      const facts = await mtg.textContent();
      for (const text of [NAMES[0], '3 ×', 'only 3 of 4', 'M19 12', 'A$0.40', 'A$0.50', 'price not shown', 'A$0.00',
        'Near Mint', 'Lightly Played', 'Reaches free postage', 'first page only']) assert(facts.includes(text), `Missing basket fact: ${text}`);
      assert((await gp.textContent()).includes('Postage not known'));
      assert((await page.locator('[data-basket="unread"]').textContent()).includes('no stock is claimed'));
      assert.equal(await page.locator('[data-basket="unread"] .shop-basket-copy').count(), 0);
      assert.equal(await page.locator('#shop-baskets').evaluate(node => node.closest('section').querySelectorAll('[data-viewer]').length), 0,
        'Basket decoration added another card viewer');
      assert.equal(await plan.locator('[data-plan-total]').getAttribute('data-plan-total'), '10.40');
      assert.equal(await plan.locator('[data-plan-by-price]').getAttribute('data-plan-by-price'), '9.90');
      assert((await plan.textContent()).includes('plus postage not known at Games Portal'));
      assert((await plan.textContent()).includes('1 row without a price'));
      const uncovered = plan.locator('.shop-plan-uncovered');
      assert.equal(await uncovered.evaluate(node => node.open), false);
      await uncovered.locator('summary').focus(); await page.keyboard.press('Enter');
      assert.equal(await uncovered.evaluate(node => node.open), true);
      assert.equal(await uncovered.locator('li').count(), 4);
      assert((await uncovered.textContent()).includes(NAMES[7])); geometry(await measure(page));
      await page.keyboard.press('Space'); assert.equal(await uncovered.evaluate(node => node.open), false);
      const others = plan.locator('.shop-plan-others'), summary = others.locator('summary');
      assert.equal(await others.evaluate(node => node.open), false); await summary.focus(); await page.keyboard.press('Enter');
      assert.equal(await others.evaluate(node => node.open), true);
      assert.equal(await others.locator('[data-plan-option]').count(), 2); result.expanded = await measure(page); geometry(result.expanded);
      if (spec.width === 393 && spec.mode === 'current') {
        await others.evaluate(node => window.scrollTo(0, scrollY + node.getBoundingClientRect().top - 80));
        result.others_png = `other-ways-${spec.width}-${spec.theme}.png`;
        await page.screenshot({path: path.join(review.out, result.others_png), animations: 'disabled'});
        await summary.focus();
      }
      await page.keyboard.press('Space'); assert.equal(await others.evaluate(node => node.open), false);
      if (spec.mode === 'stale') {
        assert((await root.textContent()).includes('The queue changed since these baskets were worked out'));
        assert.equal(await root.locator('.shop-basket-order').count(), 0);
        assert(await root.locator('.shop-basket-copy,.shop-plan-copy').evaluateAll(nodes => nodes.every(node => node.disabled)));
      } else {
        const expectedCopy = `3 ${NAMES[0]}\n1 ${NAMES[1]} (FDN) 2 [nonfoil]\n2 ${NAMES[2]}\n1 ${NAMES[3]}\n`;
        await activate(page, mtg.locator('.shop-basket-copy'), spec.root200);
        await page.waitForFunction(() => !document.querySelector('[data-basket="mtgmate"] .shop-basket-copy').disabled);
        await activate(page, plan.locator('.shop-plan-copy').first(), spec.root200);
        await page.waitForFunction(() => !document.querySelector('.shop-plan-copy').disabled);
        assert.deepEqual(result.copies, [expectedCopy, expectedCopy], 'Copied rows changed counts/printing or included add-ons');
        if (spec.mode === 'read-only') assert.equal(await root.locator('.shop-basket-order').count(), 0);
        else {
          const order = mtg.locator('.shop-basket-order'); await activate(page, order, spec.root200);
          const dialog = page.locator('dialog[open]').last(); await dialog.locator('.shop-order-form').waitFor();
          assert.equal(await dialog.locator('[data-order-field="seller"]').inputValue(), 'MTGMate');
          assert.equal(await dialog.locator('[data-order-fulfils="5"]').isChecked(), false);
          await activate(page, dialog.getByRole('button', {name: 'Preview order', exact: true}), spec.root200);
          await dialog.getByRole('button', {name: 'Save order', exact: true}).waitFor();
          await page.waitForFunction(() => ![...document.querySelectorAll('dialog[open] button')].find(node => node.textContent === 'Save order')?.disabled);
          assert.equal(result.previews.length, 1);
          const request = result.previews[0]; assert.equal(request.expect, 'synthetic-basket-q1'); assert.equal(request.record.seller, 'MTGMate');
          assert.deepEqual(request.fulfils, [{row: 1, quantity: 3}, {row: 2, quantity: 1}, {row: 3, quantity: 2}, {row: 4, quantity: 1}]);
          assert.equal(request.cards.rows.length, 5, 'Alternate printings were not handed off separately');
          assert(!JSON.stringify(request).includes('price_aud'), 'Retailer prices entered the order hand-off');
          assert(request.cards.rows.every(row => row.condition === '' && row.language === '' && row.notes === ''), 'Saved retailer evidence entered order metadata');
          await activate(page, dialog.getByRole('button', {name: 'Cancel', exact: true}), spec.root200);
          await page.waitForFunction(() => !document.querySelector('dialog[open]'));
          assert.equal(await order.evaluate(node => document.activeElement === node), true);
        }
      }
      result.saved_reply_unchanged = await page.evaluate(async expected => JSON.stringify(await (await fetch('/api/shopping')).json()) === expected, source);
      assert.equal(result.saved_reply_unchanged, true); assert.equal(result.final_writes.length, 0, 'Basket review attempted a final write');
      assert.equal(result.page_errors.length, 0, 'Uncaught page or console error');
      assert(!result.http_errors.some(error => error.category === 'unexpected_http_error'), 'Unexpected HTTP failure'); result.status = 'captured';
    } catch (error) {
      result.error = review.safeText(error.message);
      if (page && !page.isClosed()) {result.failure_png = `failed-${spec.width}-${spec.theme}-${spec.mode}${spec.root200 ? '-root200' : ''}.png`;
        await page.screenshot({path: path.join(review.out, result.failure_png), animations: 'disabled'});}
    } finally {if (context) await context.close(); review.report.results.push(result); review.save();}
    if (result.status !== 'captured') throw new Error('Shopping baskets layout failed: ' + result.error);
    review.checkCancelled();
  }
});
