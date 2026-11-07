'use strict';
// Group evidence on its real shared scale; disposable adapters, native disclosure, no writes.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

async function measure(page, configuredWidth) {
  return page.evaluate(configuredWidth => {
    const box = node => {
      if (!node) return null;
      const b = node.getBoundingClientRect(), s = getComputedStyle(node);
      return { x:b.x, y:b.y, width:b.width, height:b.height, display:s.display,
        fontSize:s.fontSize, fontWeight:s.fontWeight, lineHeight:s.lineHeight,
        color:s.color, background:s.backgroundColor, opacity:s.opacity, padding:s.padding,
        text:node.textContent.trim() };
    };
    const lines = node => {
      if (!node) return [];
      const range = document.createRange();
      range.selectNodeContents(node);
      return [...range.getClientRects()].filter(b => b.width > 0 && b.height > 0)
        .map(b => ({ x:b.x, y:b.y, width:b.width, height:b.height }));
    };
    const axis = node => ({ box:box(node), labels:[...node.querySelectorAll('span')]
      .map(n => ({ box:box(n), fragments:lines(n) })) });
    const bars = root => [...root.querySelectorAll('.vt-diff')].map(node => ({
      box:box(node), label:node.getAttribute('aria-label'), role:node.getAttribute('role'),
      zero:box(node.querySelector('.vt-diff-zero')), band:box(node.querySelector('.vt-diff-band')),
      tick:box(node.querySelector('.vt-diff-tick')),
      bandStyle:node.querySelector('.vt-diff-band')?.getAttribute('style') || null,
      tickStyle:node.querySelector('.vt-diff-tick')?.getAttribute('style') || null,
    }));
    return { innerWidth, innerHeight, scrollY, clientWidth:document.documentElement.clientWidth,
      scrollWidth:document.documentElement.scrollWidth, scrollHeight:document.documentElement.scrollHeight,
      visualViewport:window.visualViewport ? {width:visualViewport.width,height:visualViewport.height,
        scale:visualViewport.scale,offsetLeft:visualViewport.offsetLeft,offsetTop:visualViewport.offsetTop} : null,
      documentOverflow:document.documentElement.scrollWidth > document.documentElement.clientWidth,
      overflowElements:[...document.body.querySelectorAll('*')].filter(node => {
        const b = node.getBoundingClientRect(),s = getComputedStyle(node);
        return b.width > 0 && b.height > 0 && b.left >= 0 && b.right > configuredWidth + 1
          && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'
          && s.clip !== 'rect(0px, 0px, 0px, 0px)' && s.clipPath !== 'inset(50%)';
      }).slice(0,15).map(node => {
        const b = node.getBoundingClientRect();
        return {tag:node.tagName,className:node.className,
          rect:{x:b.x,y:b.y,width:b.width,height:b.height},text:node.textContent.trim().slice(0,100)};
      }),
      coarse:matchMedia('(pointer:coarse)').matches,
      rootFont:getComputedStyle(document.documentElement).fontSize,
      bodyFont:getComputedStyle(document.body).fontSize,
      title:document.querySelector('#main h1')?.textContent.trim(),
      verdict:box(document.querySelector('.vt-verdict,.vt-live')),
      actions:[...document.querySelectorAll('.vt-actions button')].map(box),
      groupSection:box(document.querySelector('.vt-groups')),
      groupContainerFont:document.querySelector('.vt-groups')
        ? getComputedStyle(document.querySelector('.vt-groups')).fontSize : null,
      tables:[...document.querySelectorAll('.vt-group-table')].map(table => ({
        box:box(table), role:table.getAttribute('role'), labelledby:table.getAttribute('aria-labelledby'),
        headings:[...table.querySelectorAll('thead th')].map(n => ({...box(n), scope:n.scope})),
        rows:[...table.querySelectorAll('tbody tr')].map(row => ({
          box:box(row), role:row.getAttribute('role'),
          cells:[...row.children].map(n => {
            const copy = n.cloneNode(true);
            for(const decorative of copy.querySelectorAll('[aria-hidden="true"]')) decorative.remove();
            return {...box(n), rawText:n.textContent.trim(), text:copy.textContent.trim(), tag:n.tagName,
              role:n.getAttribute('role'),scope:n.getAttribute('scope'),fragments:lines(n)};
          }),
          bars:bars(row),
        })),
        axes:[...table.querySelectorAll('.vt-axis')].map(axis),
      })),
      bars:bars(document), axes:[...document.querySelectorAll('.vt-axis')].map(axis),
      omitted:[...document.querySelectorAll('.vt-row-dropped')].map(box),
      pageText:document.querySelector('.vt-page')?.textContent.trim(),
    };
  },configuredWidth);
}

function matrix(routes, smoke) {
  const specs = [];
  for (const theme of ['light','dark']) {
    const sizes = smoke ? [[320,700,true],[600,746,true]]
      : [[320,700,true],[393,700,true],[599,746,true],[600,746,true],[624,746,true],[625,746,true],
        [820,1106,true],[1440,900,false],[740,360,true]];
    for (const [width,height,coarse] of sizes) specs.push({
      name:`groups-${width}-${theme}`, route:routes.member_variant, width,height,coarse,theme, groups:true });
    if (!smoke) for(const width of [320,600]) specs.push({name:`groups-root200-${width}-${theme}`,
      route:routes.member_variant,width,height:700,coarse:true,theme,groups:true,root200:true});
    for (const state of ['failed','running']) specs.push({ name:`variant-${state}-393-${theme}`,
      route:routes.member_variant,width:393,height:700,coarse:true,theme,case:state });
  }
  return specs;
}

run('variant-layout', async review => {
  review.report.results = [];
  const specs = matrix(review.config.ready.routes,review.options.smoke);
  review.report.expected_captures = specs.length;
  review.report.scope = 'Narrow group evidence and breakpoint controls; synthetic result adapters, no production result authorization or physical-device acceptance. Root200 is CSS root-font stress, not browser zoom.';
  for (const spec of specs) {
    let context,page;
    const result = { spec,status:'failed',page_errors:[],http_errors:[] };
    try {
      review.select('user2',spec.case);
      context = await review.context(spec); page = await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      await page.goto(review.pageUrl(spec.route,spec.theme), {waitUntil:'domcontentloaded'});
      await page.waitForSelector('.vt-page', {timeout:15000});
      await page.waitForSelector(spec.case === 'running' ? '.vt-live-head'
        : spec.case === 'failed' ? '.vt-verdict .vt-error' : '.vt-group-table', {timeout:15000});
      await page.evaluate(() => document.fonts.ready);
      if(spec.root200) await page.evaluate(() => {document.documentElement.style.fontSize = '200%';});
      await page.waitForTimeout(350);
      if(spec.groups) await page.locator('#vt-groups-h').evaluate(node => {
        window.scrollTo(0,Math.max(0,scrollY + node.getBoundingClientRect().top - 80));
      });
      result.metrics = await measure(page,spec.width);
      result.configuredViewport = page.viewportSize();
      result.accessibility = await page.locator('.vt-groups').count()
        ? await page.locator('.vt-groups').ariaSnapshot() : null;
      result.png = spec.name + '.png';
      await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
      if(spec.groups && spec.width === 393) {
        await page.locator('#vt-groups-identity_size').evaluate(node => {
          window.scrollTo(0,Math.max(0,scrollY + node.getBoundingClientRect().top - 80));
        });
        result.lower = {png:spec.name + '-lower.png',metrics:await measure(page,spec.width)};
        await page.screenshot({path:path.join(review.out,result.lower.png),fullPage:false,animations:'disabled'});
      }
      const disclosure = page.locator('.vt-how').first();
      if(await disclosure.count()) {
        const beforeText = result.metrics.pageText;
        await disclosure.locator(':scope > summary').click();
        assert.equal(await disclosure.getAttribute('open'),'','Native test explanation did not open');
        await disclosure.locator(':scope > summary').click();
        assert.equal(await disclosure.getAttribute('open'),null,'Native test explanation did not close');
        assert.equal((await page.locator('.vt-page').textContent()).trim(),beforeText,'Disclosure changed result evidence');
        result.explanation_checked = true;
      }
      assert.deepEqual(result.configuredViewport,{width:spec.width,height:spec.height},'Unexpected configured viewport');
      // Preserve baseline overflow as measured UI evidence. In mobile emulation it can
      // also enlarge the layout/visual viewport; neither is a harness viewport mismatch.
      result.layoutDiagnostics = {documentOverflow:result.metrics.documentOverflow,
        layoutViewportExpanded:result.metrics.innerWidth > spec.width,
        rootFontStress:!!spec.root200};
      if(spec.case === 'running') {
        assert.equal(result.metrics.tables.length,0,'Running results should not show finished group evidence');
        assert(result.metrics.verdict.text.includes('Playing'),'Missing running progress');
      } else {
        assert.equal(result.metrics.tables.length,3,'Expected all nonempty groupings');
        assert.equal(result.metrics.tables.reduce((n,t) => n + t.rows.length,0),4,'Group rows lost');
        assert.equal(result.metrics.tables[0].rows[0].cells[0].text,'Blue');
        assert.equal(result.metrics.tables[0].rows[0].cells[1].text,'1');
        assert.equal(result.metrics.tables[0].rows[1].cells[1].text,'2');
        assert(result.metrics.tables[1].rows[0].cells[2].text.includes('No difference yet'));
      }
      const scales = result.metrics.axes.map(a => a.labels.map(l => l.box.text).join('|'));
      assert(scales.length >= (spec.case === 'running' ? 1 : 4)
        && new Set(scales).size === 1,'Difference axes do not share one scale');
      assert.equal(result.page_errors.length,0,'Uncaught page error');
      assert(!result.http_errors.some(r => r.category === 'unexpected_http_error'),'Unexpected fixture HTTP failure');
      result.status = 'captured';
    } catch(error) {result.error = review.safeText(error.message);}
    finally {if(context) await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(r => r.status !== 'captured').length,0,'Variant layout captures failed');
});
