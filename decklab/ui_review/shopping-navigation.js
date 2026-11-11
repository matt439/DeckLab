'use strict';
// Native section navigation over invented Shopping data; no application write or shop request.
const path = require('node:path');
const assert = require('node:assert/strict');
const {run} = require('./common.js');

const PRIMARY = ['shop-on-the-way', 'shop-to-buy', 'shop-decks', 'shop-missing-cards'];
const SECONDARY = ['shop-combined', 'shop-by-shop', 'shop-baskets', 'shop-follow-ups', 'shop-long-term'];

function payload() {
  const decks = Array.from({length: 7}, (_, i) => ({id: `casual/synthetic-${i + 1}`,
    title: `Synthetic deck ${i + 1}`, kind: 'casual', status: 'idea', player: 'matt', missing: i + 1, on_the_way: 0}));
  const row = (i, state = 'ready') => ({name: `Synthetic card ${i}`, quantity: 1, queue_row: i, state,
    for: decks[0].title, deck: decks[0], printing: 'any', set: '', collector_number: '', finish: 'nonfoil',
    listed_aud: '', listed_at: '', in_stock: '', checked: '', notes: '', card: null});
  const order = (i, received = false) => ({id: `2026-11-01-synthetic-${i}`, seller: `Synthetic shop ${i}`,
    ordered_on: '2026-11-01', status: received ? 'received' : 'pending', notes: '',
    components: [{id: 'cards', kind: 'cards', status: received ? 'received' : 'pending',
      quantity: 3, received_on: received ? '2026-11-02' : '', items: []}]});
  return {queue_revision: 'synthetic-q1', to_buy: [1, 2, 3, 4].map(i => row(i)).concat(row(5, 'long_term')),
    orders: [order(1), order(2), order(3, true)],
    checks: [1, 2].map(i => ({order_id: '2026-11-01-synthetic-3', component_id: 'cards',
      status: 'received', text: `Synthetic follow-up ${i}`})),
    decks_missing: decks, queue_decks: decks, warnings: [],
    missing_cards: {ready: true, warnings: [], errors: [], rows: Array.from({length: 36}, (_, i) =>
      ({name: `Synthetic missing ${i + 1}`, missing: 1, decks: [], queue: [], card: null}))},
    baskets: {queue_revision: 'synthetic-q1', shops: [], unavailable: []}};
}

async function measure(page) {
  return page.evaluate(() => {
    const box = node => {
      const b = node.getBoundingClientRect();
      return {x: b.x, y: b.y, width: b.width, height: b.height, right: b.right, bottom: b.bottom};
    };
    const links = [...document.querySelectorAll('.shop-jumps a')].filter(node => node.checkVisibility());
    return {width: document.documentElement.clientWidth, innerWidth, clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth, rootFont: getComputedStyle(document.documentElement).fontSize,
      nav: box(document.querySelector('.shop-jumps')),
      primaryColumns: document.querySelector('.shop-jumps').checkVisibility()
        ? getComputedStyle(document.querySelector('.shop-jump-primary')).gridTemplateColumns.split(/\s+/).length : null,
      overflow: [...document.querySelectorAll('body *')].filter(node => {
        const b = node.getBoundingClientRect(); return node.checkVisibility() && b.height > 0
          && (b.x < -1 || b.right > document.documentElement.clientWidth + 1);
      }).slice(0, 12).map(node => ({tag: node.tagName, class: node.className, text: node.textContent.slice(0, 90), ...box(node)})),
      links: links.map(node => {
        const count = node.querySelector('.shop-jump-count');
        const label = [...node.children].find(child => child !== count);
        return {href: node.getAttribute('href'), text: node.textContent, ...box(node),
          decoration: getComputedStyle(node).textDecorationLine,
          count: count ? {text: count.textContent, insideLink: count.closest('a') === node, ...box(count)} : null,
          label: label ? box(label) : null};
      })};
  });
}

function checkGeometry(metrics) {
  assert(metrics.nav.x >= -1 && metrics.nav.right <= metrics.clientWidth + 1, 'Section navigation left the viewport');
  assert(metrics.primaryColumns <= 2, 'Primary shortcuts must stay at most two across');
  for (const link of metrics.links) {
    assert(link.height >= 44, 'Section link lost its touch target');
    assert(link.x >= -1 && link.right <= metrics.width + 1, 'Section link left the viewport');
    assert.equal(link.decoration, 'none', 'Section link reverted to scattered underlined text');
    if (!link.count) continue;
    assert.equal(link.count.insideLink, true, 'Count is outside its section control');
    assert(link.count.x >= link.x - 1 && link.count.right <= link.right + 1, 'Count left the control');
    assert(link.count.y >= link.y - 1 && link.count.bottom <= link.bottom + 1, 'Count left the control');
    assert(link.label, 'Count needs a visible label');
    assert(link.count.x - link.label.right <= 13, 'Count is visually detached from its label');
  }
}

run('shopping-navigation', async review => {
  review.report.results = [];
  review.report.scope = 'Invented Shopping sections only: grouped links, retained native disclosure and keyboard focus-to-section. All navigation is read-only. Root200 is CSS text stress, not browser zoom.';
  const specs = [];
  for (const theme of ['light', 'dark']) {
    for (const width of (review.options.smoke ? [393, 1440] : [320, 393, 430, 600, 820, 1280, 1440]))
      specs.push({theme, width, height: 1000, coarse: width < 1000});
    for (const width of (review.options.smoke ? [320] : [320, 600]))
      specs.push({theme, width, height: 1000, coarse: true, root200: true});
  }
  review.report.expected_captures = specs.length;
  for (const spec of specs) {
    const result = {spec, status: 'failed', page_errors: [], http_errors: [], mutations: [], blocked_visit_beacons: 0};
    let context;
    try {
      review.select('matt');
      context = await review.context(spec);
      const page = await context.newPage(); page.setDefaultTimeout(10000);
      review.observe(page, result.page_errors, result.http_errors);
      page.on('request', request => {
        // common.js fulfills visit telemetry before any application route runs.
        if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/visit') {
          result.blocked_visit_beacons++; return;
        }
        if (!['GET', 'HEAD'].includes(request.method())) result.mutations.push(review.safeUrl(request.url()));
      });
      await page.route('**/api/shopping', route => route.fulfill({status: 200, contentType: 'application/json',
        body: JSON.stringify(payload())}));
      await page.goto(review.pageUrl('/#/shopping', spec.theme), {waitUntil: 'domcontentloaded'});
      const nav = page.locator('.shop-jumps'); await nav.waitFor({state: 'attached'});
      await page.evaluate(() => document.fonts.ready);
      if (spec.root200) await page.evaluate(() => {document.documentElement.style.fontSize = '200%';});
      await page.waitForTimeout(100);
      result.initial = await measure(page);
      result.document_overflow = result.initial.scrollWidth > result.initial.clientWidth;
      // The existing deck-shortfall rows may overflow under enlarged text. Keep
      // that broader diagnostic while strictly qualifying this nav's own bounds.
      if (!spec.root200) assert.equal(result.document_overflow, false, 'Shopping caused document overflow');
      if (spec.width >= 1281) {
        assert.equal(await nav.isVisible(), false, 'Wide two-pane Shopping should not show section shortcuts');
      } else {
        assert.equal(await nav.isVisible(), true);
        assert.deepEqual(await nav.locator('.shop-jump-primary a').evaluateAll(nodes => nodes.map(node => node.hash.slice(1))), PRIMARY);
        assert.deepEqual(await nav.locator('.shop-jump-secondary a').evaluateAll(nodes => nodes.map(node => node.hash.slice(1))), SECONDARY);
        const more = nav.locator('.shop-jump-more'), summary = more.locator('summary');
        assert.equal(await more.evaluate(node => node.open), false, 'Secondary destinations should start folded');
        assert.equal(await summary.innerText(), 'More sections');
        assert((await summary.boundingBox()).height >= 44, 'More sections lost its touch target');
        assert.equal(await nav.locator('.shop-jump-secondary a').first().isVisible(), false);
        checkGeometry(result.initial);
        if (spec.width === 393 && !spec.root200) {
          result.top_png = `shopping-${spec.width}-${spec.theme}-top.png`;
          await page.screenshot({path: path.join(review.out, result.top_png), animations: 'disabled'});
        }
        if (spec.root200) {
          result.stress_png = `shopping-${spec.width}-${spec.theme}-root200.png`;
          await page.screenshot({path: path.join(review.out, result.stress_png), animations: 'disabled'});
        }
        await summary.focus(); await page.keyboard.press('Enter');
        assert.equal(await more.evaluate(node => node.open), true, 'Native Enter did not open More sections');
        result.expanded = await measure(page); checkGeometry(result.expanded);
        result.nav_snapshot = await nav.ariaSnapshot();
        if (spec.width === 393 && !spec.root200) {
          result.expanded_png = `shopping-${spec.width}-${spec.theme}-expanded.png`;
          await page.screenshot({path: path.join(review.out, result.expanded_png), animations: 'disabled'});
        }
        result.pointer_jumps = [];
        if (!spec.root200) for (const id of [PRIMARY[0], SECONDARY[0]]) {
          await nav.locator(`a[href="#${id}"]`).click();
          const focus = await page.evaluate(() => ({id: document.activeElement?.id, hash: location.hash,
            tabindex: document.activeElement?.getAttribute('tabindex')}));
          assert.deepEqual(focus, {id, hash: '#/shopping', tabindex: '-1'}, 'Pointer section jump lost heading focus or changed route');
          assert.equal(await more.evaluate(node => node.open), true, 'Pointer jump closed More sections');
          result.pointer_jumps.push(focus);
        }
        result.jumps = [];
        for (const id of [...PRIMARY, ...SECONDARY]) {
          const link = nav.locator(`a[href="#${id}"]`);
          await link.focus(); await page.keyboard.press('Enter');
          const focus = await page.evaluate(() => ({id: document.activeElement?.id, hash: location.hash,
            tabindex: document.activeElement?.getAttribute('tabindex')}));
          assert.deepEqual(focus, {id, hash: '#/shopping', tabindex: '-1'}, 'Section jump changed its route or lost heading focus');
          assert.equal(await more.evaluate(node => node.open), true, 'A section jump closed More sections');
          result.jumps.push(focus);
        }
        await summary.focus(); await page.keyboard.press('Space');
        assert.equal(await more.evaluate(node => node.open), false, 'Native Space did not close More sections');
      }
      assert.equal(result.page_errors.length, 0, 'Uncaught page error');
      assert(!result.http_errors.some(error => error.category === 'unexpected_http_error'), 'Unexpected fixture HTTP failure');
      assert.equal(result.mutations.length, 0, 'Section navigation attempted a write');
      result.status = 'captured';
    } catch (error) {result.error = review.safeText(error.message);}
    finally {if (context) await context.close(); review.report.results.push(result); review.save();}
    if (result.status !== 'captured') throw new Error('Shopping navigation review failed: ' + result.error);
    review.checkCancelled();
  }
});
