'use strict';
// Matched populated deck/library captures with native interactions and no final writes.
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { run } = require('./common.js');

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
      assert.equal(result.metrics.innerWidth,spec.width);
      assert(result.metrics.scrollWidth <= result.metrics.clientWidth, 'Document-wide overflow');
      assert.equal(result.page_errors.length,0,'Uncaught page error');
      assert(!result.http_errors.some(r => r.category === 'unexpected_http_error'),'Unexpected fixture HTTP failure');
      result.status = 'captured';
    } catch(error) { result.error = review.safeText(error.message); }
    finally { if(context) await context.close(); review.report.results.push(result); review.save(); }
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(r=>r.status!=='captured').length,0,'Composition captures failed');
});
