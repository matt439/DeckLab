'use strict';
// Responsive shell diagnostics using ordinary read-only UI on the disposable fixture.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

async function measure(page, configuredWidth) {
  return page.evaluate(configuredWidth => {
    const box = node => {
      if (!node) return null;
      const b = node.getBoundingClientRect(), s = getComputedStyle(node);
      return { id:node.id, tag:node.tagName, className:node.className,
        x:b.x, y:b.y, width:b.width, height:b.height, right:b.right, bottom:b.bottom,
        display:s.display, visibility:s.visibility, opacity:s.opacity,
        fontSize:s.fontSize, fontWeight:s.fontWeight, lineHeight:s.lineHeight,
        flex:s.flex, minWidth:s.minWidth, padding:s.padding, gap:s.gap,
        outline:s.outline, outlineOffset:s.outlineOffset, boxShadow:s.boxShadow,
        text:node.textContent.trim().slice(0,150), label:node.getAttribute('aria-label') };
    };
    const visible = node => {
      const b = node.getBoundingClientRect(), s = getComputedStyle(node);
      return b.width > 1 && b.height > 1 && s.display !== 'none' && s.visibility !== 'hidden';
    };
    const children = [...document.querySelector('.topbar-inner').children]
      .filter(visible).map(box);
    const overlaps = [];
    for(let i=0;i<children.length;i++) for(let j=i+1;j<children.length;j++) {
      const a=children[i],b=children[j];
      if(Math.min(a.right,b.right)-Math.max(a.x,b.x) > 1
        && Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y) > 1) overlaps.push([a.id || a.className,b.id || b.className]);
    }
    return { configuredWidth, innerWidth, innerHeight, scrollX, scrollY,
      clientWidth:document.documentElement.clientWidth, scrollWidth:document.documentElement.scrollWidth,
      visualViewport:window.visualViewport ? { width:visualViewport.width,height:visualViewport.height,
        scale:visualViewport.scale,offsetLeft:visualViewport.offsetLeft,offsetTop:visualViewport.offsetTop } : null,
      documentOverflow:document.documentElement.scrollWidth > document.documentElement.clientWidth,
      layoutViewportExpanded:innerWidth > configuredWidth,
      rootFont:getComputedStyle(document.documentElement).fontSize,
      coarse:matchMedia('(pointer:coarse)').matches,
      header:box(document.querySelector('#topbar')), children, overlaps,
      shellOutsideViewport:children.filter(b => b.x < -1 || b.right > configuredWidth + 1),
      controls:[...document.querySelectorAll('#topbar a,#topbar button,#topbar input')]
        .filter(visible).map(box),
      searchField:box(document.querySelector('#gs-bar-input')),
      searchForm:box(document.querySelector('#global-search .gs-form')),
      searchIcon:box(document.querySelector('.gs-open')),
      activity:box(document.querySelector('.shell-status > .run-activity')),
      title:box(document.querySelector('#topbar-title')),
      avatar:box(document.querySelector('#avatar-button')),
      active:box(document.activeElement),
    };
  },configuredWidth);
}

function matrix(routes, smoke) {
  const specs = [];
  for(const theme of ['light','dark']) {
    const widths = smoke ? [393,600,1000] : [320,393,599,600,624,625,699,700,820,999,1000,1199,1200,1440];
    const add = (name,width,height,route=routes.member_variant,profile='user2',extra={}) => specs.push({
      name:`${name}-${theme}`,width,height,coarse:width<1000,route,profile,theme,...extra });
    for(const width of widths) add(`back-${width}`,width,width===820?1106:746);
    for(const width of (smoke ? [600] : [320,600,820,1000,1440]))
      add(`back-root200-${width}`,width,746,routes.member_variant,'user2',{root200:true});
    if(!smoke) {
      add('landscape-740',740,360);
      for(const width of [600,820]) add(`brand-${width}`,width,1106,routes.populated_library,'matt');
      add('receipt-600',600,746,routes.receipt,'matt');
      for(const width of [600,820]) for(const root200 of [false,true])
        add(`running-${width}${root200?'-root200':''}`,width,1106,routes.member_variant,'user2',{case:'running',root200});
    }
  }
  return specs;
}

async function keyboardChecks(page, result, review) {
  // No application functions are invoked: browser keyboard events exercise the public shortcuts.
  await page.locator('#avatar-button').focus();
  await page.keyboard.press('/');
  await page.waitForFunction(() => ['gs-bar-input','gs-sheet-input'].includes(document.activeElement?.id));
  const search = page.locator('#gs-bar-input:focus,#gs-sheet-input:focus');
  assert.equal(await search.count(),1,'Slash did not focus a visible search');
  result.search = { id:await search.getAttribute('id'), metrics:await measure(page,result.spec.width) };
  assert(await search.isVisible(),'Search focus is hidden');
  if(result.spec.width===600) {
    result.search.png = result.spec.name + '-search.png';
    await page.screenshot({path:path.join(review.out,result.search.png),fullPage:false,animations:'disabled'});
  }
  await page.keyboard.press('Escape');
  if(result.search.id==='gs-sheet-input') await page.waitForSelector('.gs-sheet',{state:'detached'});
  assert.equal(await page.locator('.gs-sheet[open]').count(),0,'Search sheet did not close');
  await page.locator('#avatar-button').focus();
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.querySelector('#avatar-button')?.getAttribute('aria-expanded')==='true');
  result.avatarMenu = { metrics:await measure(page,result.spec.width),
    snapshot:await page.locator('#avatar-menu').ariaSnapshot() };
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.querySelector('#avatar-button')?.getAttribute('aria-expanded')==='false');
  result.avatarMenu.returnedFocus = await page.evaluate(() => document.activeElement?.id);
  result.keyboard_checked = true;
}

run('shell-layout', async review => {
  review.report.results = [];
  const specs = matrix(review.config.ready.routes,review.options.smoke);
  review.report.expected_captures = specs.length;
  review.report.scope = 'Responsive shell, keyboard search and avatar menu on invented read-only fixtures. Overflow and overlap remain diagnostics for paired baseline comparison. Root200 is CSS root-font stress, not browser zoom.';
  for(const spec of specs) {
    let context,page;
    const result = {spec,status:'failed',page_errors:[],http_errors:[]};
    try {
      review.select(spec.profile,spec.case);
      context = await review.context(spec); page = await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      await page.goto(review.pageUrl(spec.route,spec.theme),{waitUntil:'domcontentloaded'});
      await page.waitForSelector('#avatar-button');
      await page.waitForFunction(() => document.querySelector('#main h1')?.textContent.trim()
        && !document.querySelector('#topbar-actions')?.hidden);
      await page.evaluate(() => document.fonts.ready);
      if(spec.root200) await page.evaluate(() => {document.documentElement.style.fontSize='200%';});
      if(spec.case==='running') await page.waitForFunction(() => !document.querySelector('#shell-status')?.hidden);
      await page.waitForTimeout(350);
      await page.evaluate(() => window.scrollTo(0,0));
      result.metrics = await measure(page,spec.width);
      result.configuredViewport = page.viewportSize();
      assert.deepEqual(result.configuredViewport,{width:spec.width,height:spec.height},'Unexpected configured viewport');
      result.png = spec.name + '.png';
      await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
      await keyboardChecks(page,result,review);
      await page.evaluate(() => window.scrollTo(0,300));
      await page.waitForTimeout(100);
      result.scrolled = await measure(page,spec.width);
      assert.equal(result.page_errors.length,0,'Uncaught page error');
      assert(!result.http_errors.some(r => r.category==='unexpected_http_error'),'Unexpected fixture HTTP failure');
      result.status='captured';
    } catch(error) {result.error=review.safeText(error.message);}
    finally {if(context) await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(r => r.status!=='captured').length,0,'Shell layout captures failed');
});
