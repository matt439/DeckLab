'use strict';
// Capture the real app UI against the isolated fixture, without native desktop input.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

async function metrics(page) {
  return page.evaluate(() => {
    const box = node => {
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height,
        display: style.display, visibility: style.visibility, fontSize: style.fontSize,
        fontFamily: style.fontFamily, fontWeight: style.fontWeight, lineHeight: style.lineHeight,
        fontStyle: style.fontStyle, textDecoration: style.textDecorationLine,
        color: style.color, background: style.backgroundColor, opacity: style.opacity,
        gridTemplateColumns: style.gridTemplateColumns, overflowX: style.overflowX,
        minHeight: style.minHeight, disabled: node.disabled === true, hidden: node.hidden === true };
    };
    const ancestorStyles = node => {
      const rows = [];
      while (node && rows.length < 10) {
        const style = getComputedStyle(node);
        rows.push({ tag: node.tagName, class: node.className, opacity: style.opacity,
          color: style.color, background: style.backgroundColor });
        node = node.parentElement;
      }
      return rows;
    };
    const styleRows = [...document.querySelectorAll('.vt-row-dropped,.gt-muted,.fv-muted,.gb-meta,.gb-note,.gt-small')]
      .slice(0, 30).map(node => ({ text: node.textContent.trim(), box: box(node), ancestors: ancestorStyles(node) }));
    return {
      url: location.href, title: document.title, theme: document.documentElement.dataset.theme,
      innerWidth, innerHeight, clientWidth: document.documentElement.clientWidth,
      clientHeight: document.documentElement.clientHeight, scrollWidth: document.documentElement.scrollWidth,
      scrollHeight: document.documentElement.scrollHeight, scrollX, scrollY, devicePixelRatio,
      rootFont: getComputedStyle(document.documentElement).fontSize,
      bodyFont: getComputedStyle(document.body).fontSize,
      coarse: matchMedia('(pointer:coarse)').matches, fine: matchMedia('(pointer:fine)').matches,
      hover: matchMedia('(hover:hover)').matches, reducedMotion: matchMedia('(prefers-reduced-motion:reduce)').matches,
      fontsStatus: document.fonts.status, figtree: document.fonts.check('16px Figtree'),
      jetbrains: document.fonts.check('16px "JetBrains Mono"'),
      loadedFontFaces: [...document.fonts].filter(font => font.status === 'loaded')
        .map(font => ({ family: font.family, weight: font.weight, status: font.status })),
      main: box(document.querySelector('#main')), frame: box(document.querySelector('.rcpt-layout-frame')),
      receiptGrid: box(document.querySelector('.rcpt-grid')),
      receiptTiles: [...document.querySelectorAll('.rcpt-grid .card-tile')].map(box),
      receiptImages: [...document.querySelectorAll('.rcpt-grid img')].map(box),
      blankTarget: box(document.querySelector('.rcpt-blanks')),
      recordTarget: box([...document.querySelectorAll('button')].find(node => node.textContent.trim() === 'Record arrival')),
      actionBar: box(document.querySelector('.rcpt-bar')),
      editorSaveButtons: [...document.querySelectorAll('button')]
        .filter(node => /^(Save|Check|Save draft for later)$/.test(node.textContent.trim()))
        .map(node => ({ text: node.textContent.trim(), box: box(node) })),
      headingText: [...document.querySelectorAll('#main h1,#main h2,#main h3')].map(node => node.textContent.trim()),
      typeSamples: ['.page-head h1', '.gb-title', '.gb-scope', '.gb-help > summary', '.btn-primary', '.btn-quiet',
        '.rcpt-section-head h2', '.rcpt-blanks', '.edit-card .nm-text'].map(selector => ({ selector,
          box: box(document.querySelector(selector)) })),
      boardRows: [...document.querySelectorAll('.gb-row')].map(node => ({ state: node.dataset.state,
        identity: box(node.querySelector('.gb-name')), evidence: box(node.querySelector('.gb-score')),
        actions: box(node.querySelector('.gb-actions')) })),
      editorRows: [...document.querySelectorAll('.edit-list > .edit-row:not(.edit-removed)')].map(node => ({
        row: box(node), identity: box(node.querySelector('.edit-card')), printing: box(node.querySelector('.edit-print-words')) })),
      errorText: [...document.querySelectorAll('#main .load-failed,#main .form-error,#main [role=alert]')]
        .map(node => node.textContent.trim()),
      styleRows,
      images: [...document.images].map(img => ({ src: img.currentSrc || img.src, complete: img.complete,
        naturalWidth: img.naturalWidth, naturalHeight: img.naturalHeight, loading: img.loading, box: box(img) })),
    };
  });
}

async function checkDisclosures(page, spec) {
  const selectors = spec.receipt ? ['.rcpt-order-details', '.rcpt-checking-help']
    : spec.name.startsWith('board-') ? ['.gb-help'] : [];
  const result = [];
  for (const selector of selectors) {
    const details = page.locator(selector).first();
    await details.locator(':scope > summary').click();
    assert.equal(await details.getAttribute('open'), '', 'Native disclosure did not open');
    await details.locator(':scope > summary').click();
    assert.equal(await details.getAttribute('open'), null, 'Native disclosure did not close');
    result.push(selector);
  }
  if (spec.receipt) {
    assert(await page.getByRole('checkbox', { name: 'Check off 1 copy of Llanowar Elves', exact: true }).isChecked(),
      'Disclosure changed the local receipt selection');
  }
  return result;
}

function matrix(routes) {
  const specs = [];
  for (const theme of ['light', 'dark']) {
    for (const width of [1440, 320]) {
      specs.push({ name: `board-mixed-${width}-${theme}`, route: routes.board, ready: '.gb-row',
        width, height: width === 320 ? 844 : 900, coarse: width === 320, theme });
    }
    for (const state of ['failed', 'running']) {
      specs.push({ name: `variant-${state}-1440-${theme}`, route: routes.home_variant, ready: '.vt-page',
        case: state, width: 1440, height: 900, theme });
    }
    specs.push({ name: `variant-member-390-${theme}`, route: routes.member_variant, ready: '.vt-page',
      profile: 'user2', width: 390, height: 844, coarse: true, theme });
    for (const state of ['failed', 'stale']) {
      specs.push({ name: `pair-${state}-1440-${theme}`, route: routes.pair, ready: '.mu-head',
        case: state, width: 1440, height: 900, theme });
    }
    for (const width of [429, 430, 999, 1000]) {
      for (const coarse of [false, true]) {
        specs.push({ name: `receipt-${width}-${coarse ? 'coarse' : 'fine'}-${theme}`,
          route: routes.receipt, ready: '.rcpt-grid', receipt: true,
          width, height: 900, coarse, theme, fullPage: false });
      }
    }
    specs.push({ name: `editor-root200-320-${theme}`, route: routes.editor,
      ready: '.edit-page', width: 320, height: 844, coarse: true, theme, root200: true, fullPage: true });
  }
  return specs;
}

async function capture(review, spec, index) {
  const id = String(index + 1).padStart(2, '0') + '-' + spec.name;
  const result = { id, spec, status: 'failed', page_errors: [], http_errors: [] };
  let context, page;
  try {
    review.select(spec.profile, spec.case);
    context = await review.context(spec);
    page = await context.newPage();
    review.observe(page, result.page_errors, result.http_errors);
    await page.goto(review.pageUrl(spec.route, spec.theme), { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector(spec.ready, { timeout: 15000 });
    await page.evaluate(() => document.fonts.ready);
    if (spec.root200) {
      // Deliberate CSS layout stress only; all other interactions use ordinary browser input.
      await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
    }
    if (spec.receipt) {
      await page.getByRole('checkbox', { name: 'Check off 1 copy of Llanowar Elves', exact: true })
        .check({ timeout: 10000 });
      await page.locator('.rcpt-blanks').waitFor({ state: 'visible', timeout: 10000 });
      await page.locator('.rcpt-grid').first().scrollIntoViewIfNeeded();
    }
    await page.waitForTimeout(350);
    review.checkCancelled();
    result.metrics = await metrics(page);
    assert.equal(result.metrics.innerWidth, spec.width, 'Unexpected CSS viewport width');
    assert.equal(result.metrics.innerHeight, spec.height, 'Unexpected CSS viewport height');
    assert.equal(result.metrics.devicePixelRatio, 2, 'Unexpected device scale factor');
    result.png = id + '.png';
    await page.screenshot({ path: path.join(review.out, result.png), fullPage: spec.fullPage !== false,
      animations: 'disabled', timeout: 30000 });
    result.disclosures_checked = await checkDisclosures(page, spec);
    if (spec.coarse && spec.receipt) assert(result.metrics.blankTarget.height >= 44, 'Receipt recovery target is too short');
    if (spec.root200) {
      for (const row of result.metrics.editorRows) {
        assert(row.identity.width >= row.row.width * .8, 'Enlarged editor identity is squeezed');
        if (row.printing) assert(row.printing.width >= row.row.width * .8, 'Enlarged printing details are squeezed');
      }
    }
    assert.equal(result.page_errors.length, 0, 'Uncaught page error during capture');
    assert(!result.http_errors.some(row => row.category === 'unexpected_http_error'), 'Unexpected fixture HTTP failure');
    result.status = 'captured';
  } catch (error) {
    result.error = review.safeText(error.message);
    if (page && !page.isClosed()) {
      try {
        result.metrics = await metrics(page);
        result.png = id + '-failed.png';
        await page.screenshot({ path: path.join(review.out, result.png), fullPage: false, timeout: 10000 });
      } catch (_) { /* A closed browser cannot provide a failure screenshot. */ }
    }
  } finally {
    if (context) {
      try { await context.close(); } catch (error) {
        result.status = 'failed';
        result.close_error = review.safeText(error.message);
      }
    }
    // Late page exceptions during teardown are still a failed capture.
    if (result.page_errors.length) result.status = 'failed';
    review.report.results.push(result);
    review.save();
  }
  console.log(JSON.stringify({ id, status: result.status, theme: spec.theme, width: spec.width }));
  review.checkCancelled();
}

run('capture', async review => {
  const full = matrix(review.config.ready.routes);
  const specs = review.options.smoke
    ? full.filter(spec => ['board-mixed-1440-light', 'receipt-430-coarse-dark'].includes(spec.name)) : full;
  review.report.results = [];
  review.report.expected_captures = specs.length;
  review.report.scope = {
    full_matrix_captures: 32, themes: ['light', 'dark'], dpr: 2,
    board: 'Synthetic mixed Commander and constructed rows; most Details targets are intentionally unseeded.',
    variant: 'Synthetic failed/running and member control; adapter does not qualify backend masking.',
    receipt: '429/430 and 999/1000 CSS-pixel boundaries with fine/coarse emulation; one local check only.',
    editor: '320 CSS pixels with root-font 200% stress; dry-check POST is permitted, Save is never invoked.',
  };
  for (let index = 0; index < specs.length; index++) await capture(review, specs[index], index);
  const failures = review.report.results.filter(row => row.status !== 'captured').length;
  review.report.failed_captures = failures;
  assert.equal(failures, 0, 'One or more rendered captures failed');
  assert.equal(review.report.results.length, specs.length, 'Capture matrix is incomplete');
});
