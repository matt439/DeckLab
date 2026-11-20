'use strict';
// Matched populated deck/library captures with native interactions and no final writes.
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { run } = require('./common.js');

async function checkPlayNowShortages(review, page, context, spec) {
  const id = new URLSearchParams(spec.route.split('?')[1]).get('id');
  const base = await review.readFixture(context, '/api/deck?id=' + encodeURIComponent(id));
  const line = base.sections.Deck[0];
  const playNow = {...base, version:'owned', versions:['target','owned'],
    sections:{Deck:[{...line, name:'Opt', qty:4, card:{...line.card, name:'Opt'}}]},
    owned:{...base.owned, rows:[{...base.owned.rows[0], name:'Opt', need:4, missing:3}],
      totals:{...base.owned.totals, missing:3}}};
  const rows = [['Elvish Mystic',4],['Llanowar Elves',1]].map(([name,copies]) =>
    ({name,missing:copies,copies,queued:0,joins:null}));
  await page.route('**/api/deck?*', route => route.fulfill({json:playNow}));
  await page.route('**/api/deck/swaps?*', route => route.fulfill({json:{cards:[]}}));
  await page.route('**/api/shopping/queue/missing', route => route.fulfill({json:{
    ready:true, deck:{id,title:base.summary.title}, revision:'fixture', rows, totals:{copies:5,cards:2}}}));
  await page.goto(review.pageUrl('/#/deck?id='+encodeURIComponent(id)+'&v=owned&tab=cards&filter=missing',spec.theme));
  const copy = page.getByRole('button',{name:'Copy missing cards',exact:true});
  await copy.waitFor();
  await page.evaluate(() => Object.defineProperty(navigator,'clipboard',{value:{writeText:async text => { window.copiedMissing = text; }}}));
  await copy.click();
  assert.equal(await page.evaluate(() => window.copiedMissing), '3 Opt\n');
  assert.equal(await page.getByRole('button',{name:'Queue missing cards…',exact:true}).count(),0);
  await page.getByRole('button',{name:'Review Planned list shortages',exact:true}).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('checkbox',{name:'Queue Elvish Mystic'}).uncheck();
  assert(!await dialog.getByRole('checkbox',{name:'Queue Opt'}).count());
  assert(await dialog.getByRole('button',{name:'Queue 1 copy (To buy)',exact:true}).isEnabled());
  const cancel = dialog.getByRole('button',{name:'Cancel',exact:true});
  if (spec.coarse) {
    const point = await cancel.evaluate(button => {
      const box = button.getBoundingClientRect(), x = box.x + box.width / 2, y = box.y + box.height / 2;
      return { x, y, reachable:button.contains(document.elementFromPoint(x, y)) };
    });
    assert(point.reachable, 'Queue footer is obscured');
    await page.touchscreen.tap(point.x, point.y);
  } else await cancel.click();
  await dialog.waitFor({state:'hidden'});
}

async function measure(page) {
  return page.evaluate(() => {
    const box = node => {
      if (!node) return null;
      const b = node.getBoundingClientRect(), s = getComputedStyle(node);
      return { x: b.x, y: b.y, width: b.width, height: b.height, fontFamily: s.fontFamily,
        fontSize: s.fontSize, fontWeight: s.fontWeight, lineHeight: s.lineHeight,
        fontStyle: s.fontStyle, letterSpacing: s.letterSpacing,
        color: s.color, background: s.backgroundColor, padding: s.padding, gap: s.gap,
        margin: s.margin, borderRadius: s.borderRadius, opacity: s.opacity };
    };
    const typeSample = selector => {
      const node = [...document.querySelectorAll(selector)].find(n => {
        const rect = n.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && getComputedStyle(n).visibility !== 'hidden';
      });
      return { selector, text: node?.textContent.trim().slice(0, 200) || '', box: box(node) };
    };
    return { innerWidth, innerHeight, scrollY, clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight,
      coarse: matchMedia('(pointer:coarse)').matches,
      rootFont: getComputedStyle(document.documentElement).fontSize,
      bodyFont: getComputedStyle(document.body).fontSize,
      title: document.querySelector('#main h1')?.textContent,
      elements: Object.fromEntries(['.deck-page-head','.deck-title-row','.deck-avail','.deck-meta','.deck-top',
        '.deck-tabs','.deck-overview-played','.deck-played','.lib-detail','.lib-detail-body',
        '.lib-detail h2','.lib-glance-facts','.lib-key-cards','.deck-row-main','.deck-row-title','#sec-guide']
        .map(selector => [selector, box(document.querySelector(selector))])),
      typeSamples: ['#main h1', '.deck-section h2', '.deck-section h3', '.deck-meta', '.deck-avail',
        '.deck-tabs a', '.deck-overview-played', '.deck-played', '.lib-detail h2', '.lib-detail h3',
        '.lib-glance-facts', '.lib-key-cards', '.deck-row-title', '.deck-row .deck-availability',
        '.deck-card-title', '.deck-group h2', '.deck-group h3', '.btn-primary', '.btn-quiet',
        '#main input:not([type="checkbox"],[type="radio"],[type="hidden"])', '.nav-item', '.tabbar a',
        '#main .box-crit', '#main .empty'].map(typeSample),
      headings: [...document.querySelectorAll('#main h1,#main h2,#main h3')].map(n => n.textContent.trim()),
      libraryRows: document.querySelectorAll('.deck-row,.deck-card').length,
      selected: document.querySelector('.lib-detail')?.dataset.id,
      playedText: document.querySelector('.deck-overview-played')?.textContent.trim(),
      stateText: [...document.querySelectorAll('#main .load-failed,#main .box-crit,#main .empty')].map(n => n.textContent.trim()),
      links: [...document.querySelectorAll('#main a')].slice(0, 30).map(n => ({ text: n.textContent.trim(), href: n.getAttribute('href') })),
    };
  });
}

run('composition', async review => {
  review.report.results = [];
  const routes = review.config.ready.routes;
  const specs = [];
  for (const theme of ['light', 'dark']) {
    for (const width of [393, 1440]) {
      for (const kind of ['commander', 'casual']) specs.push({ name: `${kind}-${width}-${theme}`,
        route: routes[kind], ready: '.deck-tabs', width, height: width === 393 ? 700 : 900,
        coarse: width === 393, theme });
    }
    for (const [width, height, coarse] of (review.options.smoke
      ? [[393,700,true],[1180,746,true],[1470,830,false]]
      : [[393,700,true],[820,1106,true],[1180,746,true],[1470,830,false],[2560,1305,false]])) {
        specs.push({ name: `library-${width}-${theme}`, route: routes.populated_library,
          ready: width >= 1000 ? '.lib-glance-part' : '.deck-card', width, height, coarse, theme });
        specs.push({ name: `library-work-${width}-${theme}`, route: routes.populated_library,
          ready: width >= 1000 ? '.lib-glance-part' : '.deck-card', width, height, coarse, theme,
          scrollTo: width >= 1000 ? '.lib-split' : '.deck-grid' });
    }
    if (!review.options.smoke) {
      specs.push({ name: `commander-2560-${theme}`, route: routes.commander,
        ready: '.deck-tabs', width:2560, height:1305, theme });
      specs.push({ name: `empty-deck-393-${theme}`, route: routes.empty_deck,
        ready: '.deck-tabs', width:393, height:700, coarse:true, theme });
      specs.push({ name: `commander-guide-393-${theme}`, route: routes.commander_guide,
        ready:'#sec-guide', width:393, height:700, coarse:true, theme, scrollTo:'#sec-guide' });
      specs.push({ name: `commander-history-393-${theme}`, route: routes.commander,
        ready:'.deck-overview-played', width:393, height:700, coarse:true, theme, scrollTo:'.deck-overview-played' });
      specs.push({ name: `library-filter-empty-393-${theme}`, route:routes.populated_library + '&q=NoSuchSyntheticDeck',
        ready:'.empty', width:393, height:700, coarse:true, theme });
      specs.push({ name: `library-failed-1470-${theme}`, route:routes.populated_library,
        ready:'.box-crit', width:1470, height:830, theme, case:'library-failed' });
    }
  }
  review.report.expected_captures = specs.length;
  review.report.scope = 'Invented populated Commander, casual with no history, empty idea and multi-deck library; no final writes, real-art or device acceptance.';
  for (const spec of specs) {
    let context, page;
    const result = { spec, status:'failed', page_errors:[], http_errors:[] };
    try {
      review.select('matt',spec.case); context = await review.context(spec); page = await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      const deckPath = '/api/deck/edit?id=commander%2Fwoodland-council';
      const digest = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
      const before = digest(await review.readFixture(context,deckPath));
      await page.goto(review.pageUrl(spec.route,spec.theme), { waitUntil:'domcontentloaded' });
      await page.waitForSelector(spec.ready, { timeout:15000 });
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(500);
      if(spec.scrollTo) await page.locator(spec.scrollTo).first().evaluate(node => {
        window.scrollTo(0,Math.max(0,scrollY + node.getBoundingClientRect().top - 80));
      });
      result.metrics = await measure(page);
      result.png = spec.name + '.png';
      await page.screenshot({ path:path.join(review.out,result.png), fullPage:false, animations:'disabled' });
      if(spec.name.startsWith('library-') && spec.width >= 1000 && !spec.case) {
        await page.locator('a.deck-row').filter({hasText:'Synthetic home woodland deck'}).click();
        await page.waitForFunction(() => document.querySelector('.lib-detail')?.dataset.id === 'casual/safari-fixture');
        assert(new URLSearchParams((await page.evaluate(() => location.hash)).split('?')[1]).get('deck') === 'casual/safari-fixture');
        result.selection = { selected:'casual/safari-fixture', originalControls:true };
      }
      result.savedDeck = { before, after:digest(await review.readFixture(context,deckPath)) };
      assert.equal(result.savedDeck.before,result.savedDeck.after,'Read-only composition changed the saved deck');
      if (spec.route === routes.empty_deck) {
        const action = page.locator('.deck-head-actions .btn-primary');
        assert.equal(await action.count(), 1);
        assert.equal(await action.innerText(), 'Add cards');
        assert.equal(await page.getByRole('link', {name:'Build deck', exact:true}).count(), 0);
        assert(await page.getByText('This list has no main-deck cards yet.', {exact:true}).isVisible());
        await page.getByRole('tab', {name:'Cards', exact:true}).click();
        assert(await page.getByText('This list has no cards yet.', {exact:true}).isVisible());
        assert.equal(await page.locator('#sec-owned').count(), 0);
        const id = new URLSearchParams(spec.route.split('?')[1]).get('id');
        await action.click();
        await page.waitForSelector('.edit-page');
        assert.equal(new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('id'), id);
        await page.goto(review.pageUrl('/#/assembly?deck=' + encodeURIComponent(id),spec.theme));
        const finish = page.locator('.pack-built');
        await page.waitForSelector('.pack-completion-message');
        assert.equal(await finish.getAttribute('aria-disabled'), 'true');
        assert.match(await page.locator('.pack-completion-message').innerText(), /Add main-deck cards/);
        assert(!/Every card is here|Cards checked/.test(await page.locator('#main').innerText()));
      }
      if (spec.route === routes.casual && spec.theme === 'light') {
        await checkPlayNowShortages(review,page,context,spec);
        result.checkedPlayNowShortages = true;
      }
      assert.equal(result.metrics.innerWidth,spec.width);
      assert(result.metrics.scrollWidth <= result.metrics.clientWidth, 'Document-wide overflow');
      if (spec.route === routes.commander && spec.width === 393 && !spec.scrollTo) {
        await page.setViewportSize({ width: 320, height: spec.height });
        await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
        const rules = page.locator('.deck-overview-stats .verdict').filter({ hasText: 'Deck rules' });
        result.enlargedVerdict = await rules.evaluate(tile => ({
          label: tile.querySelector('.verdict-value').textContent,
          clientWidth: tile.clientWidth, scrollWidth: tile.scrollWidth,
          pageWidth: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth,
        }));
        const v = result.enlargedVerdict;
        assert.equal(v.label, 'Followed');
        assert(v.scrollWidth <= v.clientWidth && v.pageWidth <= v.viewport,
          'Commander verdict overflows at 320px with doubled text');
      }
      assert.equal(result.page_errors.length,0,'Uncaught page error');
      assert(!result.http_errors.some(r => r.category === 'unexpected_http_error'),'Unexpected fixture HTTP failure');
      result.status = 'captured';
    } catch(error) { result.error = review.safeText(error.message); }
    finally { if(context) await context.close(); review.report.results.push(result); review.save(); }
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(r=>r.status!=='captured').length,0,'Composition captures failed');
});
