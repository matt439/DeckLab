'use strict';
// Canonical queue controls over invented reference/check data, with no application write.
const path = require('node:path');
const assert = require('node:assert/strict');
const {run} = require('./common.js');

const NAMES = ['Synthetic Unchecked Card', 'Synthetic Deferred Card', 'Synthetic Exact Card', 'Synthetic Waiting Card'];

function payload() {
  const deck = {id: 'commander/synthetic-long-deck', title: 'Synthetic Woodland Creatures and the Long Journey Back Home', colors: ['G', 'U']};
  const snapshot = (shop, extra = {}) => ({shop, status: 'unknown', fetched_at: '2026-11-10T03:05:00Z',
    error: null, carried: true, ...extra});
  const mtg = extra => snapshot('MTGMate', {set: 'fdn', collector_number: '227', finish: 'nonfoil',
    condition: 'Near Mint', language: 'English', url: 'https://www.mtgmate.com.au/cards/Synthetic/FDN/227', ...extra});
  const other = extra => snapshot('Games Portal', extra);
  const row = (n, extra = {}) => ({name: NAMES[n - 1], quantity: n, queue_row: n, state: 'ready',
    for: deck.title, deck, printing: 'any', set: '', collector_number: '', finish: 'nonfoil', source: '',
    listed_at: '', listed_aud: '', checked: '', in_stock: '', notes: '',
    card: {name: NAMES[n - 1], mana_cost: '{G}', cmc: 1, type_line: 'Creature — Synthetic Elf',
      colors: ['G'], color_identity: ['G'], roles: [], oracle_text: 'Synthetic layout-review card only.',
      power: '1', toughness: '1', img: `/img/synthetic/queue-${n}/normal`, img_small: `/img/synthetic/queue-${n}/small`}, ...extra});
  return {queue_revision: 'synthetic-queue-card-q1', orders: [], checks: [], warnings: [], queue_decks: [deck],
    decks_missing: [], to_buy: [
      row(1, {shop_snapshots: [mtg({status: 'out_of_stock', price_aud: '0.25', stock: 0}), other()]}),
      row(2, {state: 'deferred', listed_at: 'Synthetic saved shop with a long recorded name', listed_aud: '0.50',
        checked: '2026-11-10', in_stock: 'yes', notes: 'Keep this synthetic note while comparing the recorded reference and daily checks.',
        shop_snapshots: [mtg({status: 'in_stock', price_aud: '0.40', stock: 7}), other()]}),
      row(3, {printing: 'exact', set: 'fdn', collector_number: '227', listed_at: 'Synthetic saved shop', listed_aud: '1.25',
        checked: '2026-11-01', in_stock: 'no', notes: 'Preserve the exact nonfoil request.',
        shop_snapshots: [mtg({status: 'out_of_stock', price_aud: '1.00', stock: 0}), other({status: 'out_of_stock',
          price_aud: '1.10', stock: 0, set: 'fdn', collector_number: '227', finish: 'nonfoil', condition: 'Lightly Played',
          language: 'English', url: 'https://gamesportal.com.au/products/synthetic-card'})]}),
      row(4, {state: 'waiting_for_stock', listed_at: 'Synthetic saved shop', listed_aud: '2.00', checked: '2026-10-01', in_stock: 'no',
        shop_snapshots: [mtg({status: 'in_stock', price_aud: '1.75', stock: 4, back_in_stock: true, partial: true,
          condition: 'Lightly Played', language: 'English', skipped_cheaper: true}),
        other({status: 'not_matched', shop_sets: ['old', 'sft'], partial: true})]}),
    ]};
}

function history() {
  return {queued: true, scope: 'any printing', shops: [
    {shop: 'MTGMate', counts_stock: true, days: [{on: '2026-11-09', listed: true, in_stock: true, stock: 2,
      price: '0.25', set: 'fdn', number: '227', finish: 'nonfoil', condition: 'Near Mint', language: 'English', lowest: true}]},
    {shop: 'Games Portal', counts_stock: false, days: []},
  ]};
}

async function metrics(page) {
  return page.evaluate(() => {
    const box = node => {
      const b = node.getBoundingClientRect();
      return {x: b.x, y: b.y, right: b.right, bottom: b.bottom, width: b.width, height: b.height};
    };
    const visible = node => node.checkVisibility() && node.getBoundingClientRect().width > 0;
    const rows = [...document.querySelectorAll('[data-shop-queue]')];
    return {width: innerWidth, clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth, lab: matchMedia('(min-width:1000px)').matches,
      rootFont: getComputedStyle(document.documentElement).fontSize,
      overflow: [...document.querySelectorAll('body *')].filter(visible).filter(node => {
        const b = node.getBoundingClientRect(); return b.x < -1 || b.right > document.documentElement.clientWidth + 1;
      }).slice(0, 20).map(node => ({tag: node.tagName, className: node.className, text: node.textContent.slice(0, 100), ...box(node)})),
      rows: rows.map(row => ({id: row.dataset.shopQueue, ...box(row),
        text: row.innerText, surface: getComputedStyle(row).backgroundColor,
        controls: [...row.querySelectorAll('button,a,summary')].filter(visible).map(node => ({...box(node),
          text: node.textContent.trim().slice(0, 100), label: node.getAttribute('aria-label'), className: node.className})),
        research: row.querySelector('.shop-queue-research') ? box(row.querySelector('.shop-queue-research')) : null,
        checks: [...row.querySelectorAll('[data-shop-snapshot]')].map(node => ({...box(node), shop: node.dataset.shopSnapshotShop,
          state: node.dataset.shopSnapshot, text: node.textContent.trim()}))})),
      tableRegions: [...document.querySelectorAll('.shop-queue-table-wrap')].map(node => ({...box(node), scrollWidth: node.scrollWidth})),
      duplicates: {viewers: document.querySelectorAll('[data-shop-queue] .card-row[data-viewer]').length,
        histories: document.querySelectorAll('.shop-history-open').length, moves: document.querySelectorAll('.shop-category-move').length,
        details: document.querySelectorAll('.shop-queue-edit').length, snapshots: document.querySelectorAll('.shop-snapshot-list').length}};
  });
}

function geometry(result) {
  assert.equal(result.scrollWidth > result.clientWidth, false, 'Queue page caused document overflow');
  assert.deepEqual(result.duplicates, {viewers: 4, histories: 4, moves: 4, details: 4, snapshots: 4}, 'Queue controls or source nodes duplicated');
  for (const region of result.tableRegions)
    assert(region.x >= -1 && region.right <= result.clientWidth + 1, 'Lab scroll region left the viewport');
  if (result.lab) return; // Table columns retain their existing local horizontal scrolling.
  for (const row of result.rows) {
    assert(row.x >= -1 && row.right <= result.clientWidth + 1, 'Queue card left the viewport');
    if (row.research) assert(row.research.x >= row.x - 1 && row.research.right <= row.right + 1, 'Reference left its card');
    for (const check of row.checks) assert(check.x >= row.x - 1 && check.right <= row.right + 1, 'Shop check left its card');
    for (const control of row.controls) {
      assert(control.height >= 44, `Queue control lost its 44px target: ${control.label || control.text}`);
      assert(control.x >= row.x - 1 && control.right <= row.right + 1, 'Queue control left its card');
    }
    for (let i = 0; i < row.controls.length; i++) for (let j = i + 1; j < row.controls.length; j++) {
      const a = row.controls[i], b = row.controls[j];
      assert.equal(Math.min(a.right, b.right) - Math.max(a.x, b.x) > 1
        && Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y) > 1, false, 'Queue control targets overlap');
    }
  }
}

async function activate(page, locator, stress) {
  if (stress) {await locator.focus(); await page.keyboard.press('Enter');}
  else await locator.click();
}

async function sameNodes(page, originals, casual) {
  const identity = await page.evaluate(({originals, casual}) => originals.map(original => {
    const current = document.querySelector(`[data-shop-queue="${original.id}"]`);
    return {id: original.id, sameRow: !casual || current === original.row,
      viewer: current.querySelector('.card-row') === original.viewer,
      move: current.querySelector('.shop-category-move') === original.move,
      details: current.querySelector('.shop-queue-edit') === original.details,
      actions: current.querySelector('.shop-queue-actions') === original.actions,
      history: original.history.isConnected, snapshot: original.snapshot.isConnected,
      checkNodes: original.checks.every(node => node.isConnected),
      research: !casual || current.querySelector('.shop-queue-research') === original.research};
  }), {originals, casual});
  for (const row of identity) for (const [key, value] of Object.entries(row))
    if (key !== 'id') assert.equal(value, true, `Queue ${row.id} replaced or detached ${key}`);
  return identity;
}

run('shopping-queue-cards', async review => {
  review.report.results = [];
  review.report.scope = 'Invented purchase queue cards, recorded reference facts and dated shop checks. Original controls/source nodes survive grouping and density projections. Native menus, cancelled details, viewer and intercepted history GET only; no writes or retailer fetch.';
  const specs = [];
  for (const theme of ['light', 'dark']) {
    for (const width of (review.options.smoke ? [393, 1440] : [320, 393, 430, 600, 820, 999, 1000, 1440]))
      specs.push({theme, width, height: 1000, coarse: width < 1000});
    for (const width of (review.options.smoke ? [320] : [320, 600]))
      specs.push({theme, width, height: 1000, coarse: true, root200: true});
  }
  review.report.expected_captures = specs.length;
  for (const spec of specs) {
    const result = {spec, status: 'failed', page_errors: [], http_errors: [], writes: [], history_requests: []};
    let context, originals, page;
    try {
      review.select('matt'); context = await review.context(spec);
      page = await context.newPage(); page.setDefaultTimeout(10000);
      review.observe(page, result.page_errors, result.http_errors);
      page.on('request', request => {
        if (!['GET', 'HEAD'].includes(request.method()) && new URL(request.url()).pathname !== '/api/visit')
          result.writes.push(review.safeUrl(request.url()));
      });
      const source = JSON.stringify(payload());
      await page.route('**/api/shopping', route => route.fulfill({status: 200, contentType: 'application/json', body: source}));
      await page.route('**/api/shopping/price-history?*', route => {
        const url = new URL(route.request().url()); result.history_requests.push({name: url.searchParams.get('name'), row: url.searchParams.get('row')});
        return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(history())});
      });
      await page.route('**/api/cards/rulings?*', route => route.fulfill({status: 200, contentType: 'application/json',
        body: JSON.stringify({name: NAMES[0], available: true, updated: '2026-11-10', rulings: []})}));
      await page.route('**/api/cards/decks?*', route => route.fulfill({status: 200, contentType: 'application/json',
        body: JSON.stringify({name: NAMES[0], holds: [], wants: [], owned: 0, free: 0, incoming: 0, basic: false})}));
      await page.route('**/img/synthetic/**', route => route.fulfill({status: 200, contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="244" height="340"><rect width="244" height="340" fill="#496658"/><text x="20" y="60" fill="white" font-size="20">Synthetic card</text></svg>'}));
      await page.goto(review.pageUrl('/#/shopping', spec.theme), {waitUntil: 'domcontentloaded'});
      await page.locator('[data-shop-queue="1"]').waitFor(); await page.evaluate(() => document.fonts.ready);
      if (spec.root200) await page.evaluate(() => {document.documentElement.style.fontSize = '200%';});
      await page.waitForTimeout(100); result.initial = await metrics(page); geometry(result.initial);
      if (spec.width >= 1000) {await page.setViewportSize({width: 393, height: 1000}); await page.waitForTimeout(100);}
      originals = await page.evaluateHandle(() => [...document.querySelectorAll('[data-shop-queue]')].map(row => ({id: row.dataset.shopQueue, row,
        viewer: row.querySelector('.card-row'), research: row.querySelector('.shop-queue-research'), snapshot: row.querySelector('.shop-snapshot-list'),
        checks: [...row.querySelectorAll('[data-shop-snapshot]')], history: row.querySelector('.shop-history-open'),
        move: row.querySelector('.shop-category-move'), details: row.querySelector('.shop-queue-edit'), actions: row.querySelector('.shop-queue-actions')})));
      result.casual = await metrics(page); geometry(result.casual);
      const first = page.locator('[data-shop-queue="1"]'), second = page.locator('[data-shop-queue="2"]');
      assert((await first.locator('.shop-queue-research').innerText()).includes('Not checked at a shop yet'));
      assert((await second.locator('.shop-queue-research').innerText()).includes('A$0.50'));
      assert((await first.textContent()).includes('MTGMate: out of stock'));
      assert((await first.textContent()).includes("Games Portal: price unknown, the shop couldn't be read"));
      assert((await page.locator('[data-shop-queue="4"]').textContent()).includes('Back in stock'));
      assert((await page.locator('[data-shop-queue="4"]').textContent()).includes('first page only, more results not read'));
      assert((await page.locator('[data-shop-queue="4"]').textContent()).includes('listed, but not matched to your printing'));
      assert.deepEqual(await page.locator('.shop-snapshot-list time').evaluateAll(nodes => nodes.map(node => node.getAttribute('datetime'))),
        Array(8).fill('2026-11-10T03:05:00Z'), 'A saved shop timestamp changed');
      if ((spec.width === 393 || spec.root200) && spec.width < 1000) {
        await first.evaluate(node => window.scrollTo(0, scrollY + node.getBoundingClientRect().top - 80));
        result.png = `queue-cards-${spec.width}-${spec.theme}${spec.root200 ? '-root200' : ''}.png`;
        await page.screenshot({path: path.join(review.out, result.png), animations: 'disabled'});
        if (!spec.root200) {
          await second.evaluate(node => window.scrollTo(0, scrollY + node.getBoundingClientRect().top - 80));
          result.second_png = `queue-cards-${spec.width}-${spec.theme}-priced.png`;
          await page.screenshot({path: path.join(review.out, result.second_png), animations: 'disabled'});
        }
      }
      const move = first.locator('.shop-category-move'); await activate(page, move, spec.root200);
      await first.locator('.menu').waitFor({state: 'visible'});
      result.move_menu = await first.locator('.menu').evaluate(node => {
        const box = node.getBoundingClientRect(); return {x: box.x, right: box.right, viewport: document.documentElement.clientWidth};
      });
      assert(result.move_menu.x >= -1 && result.move_menu.right <= result.move_menu.viewport + 1, 'Move menu left the viewport');
      await page.keyboard.press('Escape');
      assert.equal(await first.locator('.menu').isVisible(), false); assert.equal(await move.evaluate(node => document.activeElement === node), true);
      const details = first.locator('.shop-queue-edit'); await activate(page, details, spec.root200);
      const detailSheet = page.locator('dialog[open]').last(); await detailSheet.locator('.shop-queue-form').waitFor();
      assert.equal(await detailSheet.locator('[data-queue-field="quantity"]').inputValue(), '1');
      await activate(page, detailSheet.getByRole('button', {name: 'Cancel', exact: true}), spec.root200);
      await page.waitForFunction(() => !document.querySelector('dialog[open]'));
      assert.equal(await details.evaluate(node => document.activeElement === node), true);
      const historyButton = first.locator('.shop-history-open'); await activate(page, historyButton, spec.root200);
      const historySheet = page.locator('dialog[open]').last(); await historySheet.locator('.shop-history-shop').first().waitFor();
      assert((await historySheet.innerText()).includes('A$0.25'));
      await activate(page, historySheet.getByRole('button', {name: 'Close', exact: true}).last(), spec.root200);
      await page.waitForFunction(() => !document.querySelector('dialog[open]'));
      assert.equal(await historyButton.evaluate(node => document.activeElement === node), true);
      await activate(page, first.locator('.card-row'), spec.root200);
      const viewer = page.locator('dialog.viewer[open]'); await viewer.waitFor();
      await activate(page, viewer.getByRole('button', {name: 'Close', exact: true}), spec.root200);
      await page.waitForFunction(() => !document.querySelector('dialog.viewer[open]'));
      await page.waitForFunction(() => location.hash === '#/shopping');
      assert.equal(await first.locator('.card-row').evaluate(node => document.activeElement === node), true);
      for (const order of ['shop', 'state', 'shop']) {
        const control = page.locator(`[data-queue-order="${order}"]`); await activate(page, control, spec.root200);
        assert.equal(await control.getAttribute('aria-pressed'), 'true');
        await sameNodes(page, originals, true); geometry(await metrics(page));
      }
      await move.focus(); result.density_identity = [];
      for (const width of [1000, 1440, spec.width < 1000 ? spec.width : 393]) {
        await page.setViewportSize({width, height: 1000}); await page.waitForTimeout(100);
        result.density_identity.push({width, rows: await sameNodes(page, originals, width < 1000)});
        geometry(await metrics(page));
        assert.equal(await page.evaluate(originals => document.activeElement === originals.find(row => row.id === '1').move, originals), true,
          'Density change lost the original focused Move control');
      }
      assert.equal(await page.locator('[data-queue-order="shop"]').getAttribute('aria-pressed'), 'true');
      assert.deepEqual(result.history_requests, [{name: NAMES[0], row: '1'}]);
      result.saved_reply_unchanged = await page.evaluate(async expected =>
        JSON.stringify(await (await fetch('/api/shopping')).json()) === expected, source);
      assert.equal(result.saved_reply_unchanged, true, 'Saved synthetic reply changed');
      assert.equal(result.writes.length, 0, 'Queue interaction attempted an application write');
      assert.equal(result.page_errors.length, 0, 'Uncaught page or console error');
      assert(!result.http_errors.some(error => error.category === 'unexpected_http_error'), 'Unexpected fixture HTTP error');
      result.status = 'captured';
    } catch (error) {
      result.error = review.safeText(error.message);
      if (page && !page.isClosed()) {
        result.failure_png = `queue-cards-failed-${spec.width}-${spec.theme}${spec.root200 ? '-root200' : ''}.png`;
        await page.screenshot({path: path.join(review.out, result.failure_png), animations: 'disabled'});
      }
    }
    finally {if (originals) await originals.dispose(); if (context) await context.close(); review.report.results.push(result); review.save();}
    if (result.status !== 'captured') throw new Error('Shopping queue-card review failed: ' + result.error);
    review.checkCancelled();
  }
});
