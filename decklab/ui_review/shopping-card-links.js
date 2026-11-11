'use strict';
// Native links over invented missing-card and combined-deck answers. No shop or app write.
const path = require('node:path');
const assert = require('node:assert/strict');
const {run} = require('./common.js');

const DECKS = [
  {id: 'commander/synthetic-woodland', title: 'Synthetic Woodland Creatures and the Very Long Journey Home'},
  {id: 'casual/synthetic-spells', title: 'Synthetic Spells for a Rainy Afternoon with Friends'},
  {id: 'commander/synthetic-collection', title: 'Synthetic Collection of Unreasonably Long Card Names'},
];
const SHOP_URL = 'https://www.mtgmate.com.au/cards/Synthetic-Card/FDN/100';
const SOURCE_URL = 'https://scryfall.com/card/synthetic/100/synthetic-card';

function payload() {
  const snapshots = [
    {shop: 'MTGMate', scope: 'nonfoil', status: 'in_stock', fetched_at: '2026-11-10T03:05:00Z',
      price_aud: '0.25', stock: 7, set: 'fdn', collector_number: '100', finish: 'nonfoil',
      url: SHOP_URL, condition: 'Near Mint', language: 'English'},
    {shop: 'Games Portal', scope: 'nonfoil', status: 'unknown', fetched_at: '2026-11-10T04:05:00Z'},
  ];
  const first = {name: 'Synthetic Missing Card', missing: 9, card: null, queue: [],
    decks: DECKS.map((deck, i) => ({...deck, missing: i + 2})), shop_snapshots: snapshots,
    reprints: {ready: true, data_date: '2026-11-10', as_of: '2026-11-11',
      coverage: 'Synthetic paper-printing source for layout review only.', notes: [],
      upcoming: [{set: 'sft', set_name: 'Synthetic Paper Printing with a Long Set Name',
        released_at: '2026-12-01', source_url: SOURCE_URL}], price_check: {offered: false}}};
  return {queue_revision: 'synthetic-link-q1', to_buy: [], orders: [], checks: [], warnings: [],
    queue_decks: DECKS, decks_missing: [],
    missing_cards: {ready: true, errors: [], warnings: [], rows: [first,
      {name: 'Synthetic Single Deck Card', missing: 1, card: null, queue: [], decks: [{...DECKS[0], missing: 1}]}]}};
}

function combined() {
  return {ready: true, errors: [], warnings: [], decks: DECKS.map((deck, i) => ({...deck, missing_alone: i === 2 ? 0 : i + 1})),
    totals: {cards: 1, copies: 6, copies_alone: 6, on_the_way: 0},
    rows: [{name: 'Synthetic Combined Card', card: null, need: 8, available: 2, missing: 6,
      missing_alone: 6, on_the_way: [], held_elsewhere: [],
      decks: DECKS.map((deck, i) => ({...deck, need: i + 1, missing_alone: i === 2 ? 0 : i + 1}))}]};
}

async function measure(page) {
  return page.evaluate(() => {
    const box = node => {
      const b = node.getBoundingClientRect();
      return {x: b.x, y: b.y, width: b.width, height: b.height, right: b.right, bottom: b.bottom};
    };
    const links = [...document.querySelectorAll('.shop-missing-card .shop-missing-decks a, .shop-missing-card .shop-missing-snapshot a, .shop-missing-card .reprint-printings a')];
    return {clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth,
      rootFont: getComputedStyle(document.documentElement).fontSize,
      links: links.map(node => {
        const count = node.querySelector('.shop-missing-count'), range = document.createRange();
        const text = [...node.childNodes].find(child => child.nodeType === Node.TEXT_NODE && child.textContent.trim());
        if (text) range.selectNodeContents(text); else range.selectNodeContents(node.querySelector('span:not(.shop-missing-count)') || node);
        return {href: node.getAttribute('href'), text: node.textContent.trim(), ...box(node),
          deck: !!node.closest('.shop-missing-decks'), combined: !!node.closest('.shop-combined-card'),
          group: box(node.closest('.shop-missing-decks') || node.closest('.shop-missing-card')),
          labelRects: [...range.getClientRects()].map(rect => ({x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom})),
          decoration: getComputedStyle(node).textDecorationLine, target: node.getAttribute('target'), rel: node.getAttribute('rel'),
          count: count ? {text: count.textContent.trim(), inside: count.closest('a') === node, ...box(count)} : null};
      })};
  });
}

function geometry(metrics) {
  for (const link of metrics.links) {
    assert(link.height >= 44, 'Missing-card link lost its 44px touch target');
    assert(link.x >= -1 && link.right <= metrics.clientWidth + 1, 'Missing-card link left the viewport');
    assert.equal(link.decoration, 'none', 'Missing-card links must be contained controls');
    if (!link.deck) continue;
    assert(Math.abs(link.width - link.group.width) <= 3, 'Deck link no longer fills its grouped row');
    for (const rect of link.labelRects) {
      assert(rect.x >= link.x - 1 && rect.right <= link.right + 1, 'Deck label left its control');
      assert(rect.y >= link.y - 1 && rect.bottom <= link.bottom + 1, 'Deck label left its control');
    }
    if (link.count) {
      assert.equal(link.count.inside, true, 'Deck quantity is outside the deck link');
      assert(link.count.x >= link.x - 1 && link.count.right <= link.right + 1, 'Deck quantity left its control');
      assert(link.count.y >= link.y - 1 && link.count.bottom <= link.bottom + 1, 'Deck quantity left its control');
    }
  }
  const decks = metrics.links.filter(link => link.deck);
  for (let i = 0; i < decks.length; i++) for (let j = i + 1; j < decks.length; j++) {
    const a = decks[i], b = decks[j];
    const overlap = Math.min(a.right, b.right) - Math.max(a.x, b.x) > 1
      && Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y) > 1;
    assert.equal(overlap, false, 'Deck link targets overlap');
  }
}

async function activateWithoutNavigation(page, locator, keyboard) {
  const href = await locator.getAttribute('href');
  await locator.evaluate(node => node.addEventListener('click', event => {
    event.preventDefault(); node.dataset.reviewActivatedHref = node.getAttribute('href');
  }, {once: true}));
  await locator.focus();
  if (keyboard) await page.keyboard.press('Enter'); else await locator.click();
  assert.equal(await locator.getAttribute('data-review-activated-href'), href, 'Native link activation lost its destination');
  assert.equal(await locator.evaluate(node => document.activeElement === node), true, 'Native link lost focus');
  assert.equal(new URL(page.url()).hash, '#/shopping');
  return {href, method: keyboard ? 'keyboard Enter' : 'pointer', intercepted_before_navigation: true};
}

run('shopping-card-links', async review => {
  review.report.results = [];
  review.report.scope = 'Invented missing-card and combined-deck links, saved shop evidence and reprint sources. Native activations are intercepted before navigation; no external page, app write or price fetch. Root200 is CSS text stress, not browser zoom.';
  const specs = [];
  for (const theme of ['light', 'dark']) {
    for (const width of (review.options.smoke ? [393, 1440] : [320, 393, 430, 600, 820, 1280, 1440]))
      specs.push({theme, width, height: 1000, coarse: width < 1000});
    for (const width of (review.options.smoke ? [320] : [320, 600]))
      specs.push({theme, width, height: 1000, coarse: true, root200: true});
  }
  review.report.expected_captures = specs.length;
  for (const spec of specs) {
    const result = {spec, status: 'failed', page_errors: [], http_errors: [], writes: [], combined_requests: []};
    let context;
    try {
      review.select('matt'); context = await review.context(spec);
      const page = await context.newPage(); page.setDefaultTimeout(10000);
      review.observe(page, result.page_errors, result.http_errors);
      page.on('request', request => {
        if (!['GET', 'HEAD'].includes(request.method()) && new URL(request.url()).pathname !== '/api/visit')
          result.writes.push(review.safeUrl(request.url()));
      });
      const source = JSON.stringify(payload()), answer = JSON.stringify(combined());
      await page.route('**/api/shopping', route => route.fulfill({status: 200, contentType: 'application/json', body: source}));
      await page.route('**/api/shopping/combined?*', route => {
        result.combined_requests.push(new URL(route.request().url()).searchParams.get('decks'));
        return route.fulfill({status: 200, contentType: 'application/json', body: answer});
      });
      await page.goto(review.pageUrl('/#/shopping', spec.theme), {waitUntil: 'domcontentloaded'});
      const first = page.locator('[data-missing-card="Synthetic Missing Card"]'); await first.waitFor();
      await page.evaluate(() => document.fonts.ready);
      if (spec.root200) await page.evaluate(() => {document.documentElement.style.fontSize = '200%';});
      await page.waitForTimeout(100);
      result.initial = await measure(page); geometry(result.initial);
      assert.equal(result.initial.scrollWidth > result.initial.clientWidth, false, 'Missing-card page overflowed');
      const deckLinks = first.locator('.shop-missing-decks a'); assert.equal(await deckLinks.count(), 3);
      assert.deepEqual(await deckLinks.evaluateAll(nodes => nodes.map(node => node.getAttribute('href'))),
        DECKS.map(deck => `#/deck?id=${encodeURIComponent(deck.id)}&v=target&tab=cards&filter=missing`));
      assert.equal(await page.locator('[data-missing-card="Synthetic Single Deck Card"] .shop-missing-decks a').count(), 1);
      const external = result.initial.links.filter(link => !link.deck);
      assert.deepEqual(external.map(link => link.href), [SHOP_URL, SOURCE_URL]);
      for (const link of external) {assert.equal(link.target, '_blank'); assert.equal(link.rel, 'noopener noreferrer');}
      assert((await first.innerText()).includes('Games Portal: price unknown'));
      if (spec.width <= 430) assert(result.initial.links.some(link => link.deck && link.labelRects.length > 1),
        'Long synthetic deck titles did not exercise wrapped labels');
      if (spec.width === 393 || spec.root200) {
        await first.evaluate(node => window.scrollTo(0, scrollY + node.getBoundingClientRect().top - 80));
        result.png = `missing-card-links-${spec.width}-${spec.theme}${spec.root200 ? '-root200' : ''}.png`;
        await page.screenshot({path: path.join(review.out, result.png), animations: 'disabled'});
      }
      result.activations = [await activateWithoutNavigation(page, deckLinks.first(), true)];
      if (!spec.root200) result.activations.push(await activateWithoutNavigation(page, first.locator('.shop-missing-snapshot a'), false));
      result.activations.push(await activateWithoutNavigation(page, first.locator('.reprint-printings a'), true));
      const choose = page.getByRole('button', {name: 'Choose decks…', exact: true});
      await choose.focus(); await page.keyboard.press('Enter');
      const dialog = page.locator('dialog[open]').last();
      for (const deck of DECKS) {
        const checkbox = dialog.locator(`input[data-combined-deck="${deck.id}"]`);
        await checkbox.focus(); await page.keyboard.press('Space'); assert.equal(await checkbox.isChecked(), true);
      }
      await dialog.getByRole('button', {name: 'Show what to buy', exact: true}).focus(); await page.keyboard.press('Enter');
      await page.locator('.shop-combined-card').waitFor();
      assert.deepEqual(result.combined_requests, [DECKS.map(deck => deck.id).join(',')]);
      result.combined = await measure(page); geometry(result.combined);
      assert.equal(result.combined.scrollWidth > result.combined.clientWidth, false, 'Combined missing-card page overflowed');
      const combinedLinks = page.locator('.shop-combined-card .shop-missing-decks a');
      assert.equal(await combinedLinks.count(), 3);
      assert.deepEqual(await combinedLinks.evaluateAll(nodes => nodes.map(node => node.getAttribute('href'))),
        DECKS.map((deck, i) => `#/deck?id=${encodeURIComponent(deck.id)}&v=target&tab=cards${i === 2 ? '' : '&filter=missing'}`));
      if (spec.width === 393 && !spec.root200) {
        await page.locator('.shop-combined-card').evaluate(node => window.scrollTo(0, scrollY + node.getBoundingClientRect().top - 80));
        result.combined_png = `combined-card-links-${spec.width}-${spec.theme}.png`;
        await page.screenshot({path: path.join(review.out, result.combined_png), animations: 'disabled'});
      }
      result.activations.push(await activateWithoutNavigation(page, combinedLinks.first(), true));
      result.saved_reply_unchanged = await page.evaluate(async expected =>
        JSON.stringify(await (await fetch('/api/shopping')).json()) === expected, source);
      assert.equal(result.saved_reply_unchanged, true);
      assert.equal(result.writes.length, 0, 'Link review attempted an application write');
      assert.equal(result.page_errors.length, 0, 'Uncaught page error');
      assert(!result.http_errors.some(error => error.category === 'unexpected_http_error'), 'Unexpected fixture HTTP failure');
      result.status = 'captured';
    } catch (error) {result.error = review.safeText(error.message);}
    finally {if (context) await context.close(); review.report.results.push(result); review.save();}
    if (result.status !== 'captured') throw new Error('Shopping card-links review failed: ' + result.error);
    review.checkCancelled();
  }
});
