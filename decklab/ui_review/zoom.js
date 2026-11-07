'use strict';
// Actual Chromium page zoom, proved from CDP rather than inferred from CSS injection.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { run } = require('./common.js');

const digest = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');

async function screenshot(review,page,name) {
  const session=await page.context().newCDPSession(page);
  try {
    const layout=await session.send('Page.getLayoutMetrics');
    // Playwright's CSS-sized clip crops a native zoomed window; capture the compositor viewport.
    const captured=await session.send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false});
    const bytes=Buffer.from(captured.data,'base64');
    const width=bytes.readUInt32BE(16),height=bytes.readUInt32BE(20),visual=layout.cssVisualViewport;
    assert.equal(width,Math.round(visual.clientWidth*visual.zoom),'Zoom screenshot clipped its physical viewport width');
    assert.equal(height,Math.round(visual.clientHeight*visual.zoom),'Zoom screenshot clipped its physical viewport height');
    fs.writeFileSync(path.join(review.out,name),bytes);
    return {name,width,height,cssViewport:visual,method:'CDP compositor viewport without clip'};
  } finally {await session.detach();}
}

async function metrics(page, session) {
  const layout = await session.send('Page.getLayoutMetrics');
  const dom = await page.evaluate(() => {
    const box = node => {
      if (!node) return null;
      const b = node.getBoundingClientRect(), s = getComputedStyle(node);
      return { x:b.x, y:b.y, width:b.width, height:b.height, right:b.right, bottom:b.bottom,
        fontSize:s.fontSize, lineHeight:s.lineHeight, text:node.textContent.trim().slice(0,160) };
    };
    return { innerWidth, innerHeight, outerWidth, outerHeight, dpr:devicePixelRatio, scrollY,
      clientWidth:document.documentElement.clientWidth, scrollWidth:document.documentElement.scrollWidth,
      visualViewport:{ width:visualViewport.width, height:visualViewport.height, scale:visualViewport.scale },
      rootFont:getComputedStyle(document.documentElement).fontSize,
      bodyFont:getComputedStyle(document.body).fontSize,
      coarse:matchMedia('(pointer:coarse)').matches,
      editorRows:[...document.querySelectorAll('.edit-row:not(.edit-removed)')].map(node => ({
        row:box(node), identity:box(node.querySelector('.edit-card')), printing:box(node.querySelector('.edit-print-words')) })),
      receiptBar:box(document.querySelector('.rcpt-bar')),
      active:box(document.activeElement),
    };
  });
  return { ...dom, cdp:{ layoutViewport:layout.cssLayoutViewport, visualViewport:layout.cssVisualViewport } };
}

async function editorChecks(page) {
  const qty=page.getByRole('textbox',{name:'Copies of Llanowar Elves',exact:true});
  assert.equal(await qty.inputValue(),'4');
  await page.getByRole('button',{name:'One more Llanowar Elves',exact:true}).click();
  assert.equal(await qty.inputValue(),'5');
  await page.locator('.bar-undo').click();
  assert.equal(await qty.inputValue(),'4','Footer Undo did not restore the native stepper change');
  const more=page.getByRole('button',{name:'More for Llanowar Elves',exact:true});
  await more.click();
  await page.getByRole('menuitem',{name:'Remove',exact:true}).click();
  const undo=page.locator('.bar-undo');
  await undo.click();
  await more.waitFor({state:'visible'});
  await more.click();
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('menu').count(),0,'Escape left the row menu open');
  assert(await more.evaluate(node=>document.activeElement===node),'Escape did not restore focus to More');
  return { nativeStepperAndFooterUndo:true,localRemoveAndFooterUndo:true, originalMoreAndEscape:true };
}

async function longBlockerChecks(review,page,result) {
  let removed=0;
  while(await page.getByRole('button',{name:/^More for /}).count()) {
    assert(removed++<15,'Unexpected repeated Commander rows');
    await page.getByRole('button',{name:/^More for /}).first().click();
    await page.getByRole('menuitem',{name:'Remove',exact:true}).click();
  }
  assert(removed>=9,'Long-diff fixture lost its populated Commander rows');
  await page.waitForFunction(()=>typeof editor!=='undefined'&&editor&&!editor.checking&&!editor.saving);
  await page.locator('.bar-save').click();
  const dialog=page.getByRole('dialog').filter({has:page.getByRole('heading',{name:"This can't be saved yet",exact:true})});
  await dialog.waitFor({state:'visible'});
  assert.equal(await dialog.getByRole('button',{name:'Save',exact:true}).isDisabled(),true,'Blocked review offered final Save');
  const blocker=dialog.locator('.box-crit');
  const initial=await dialog.evaluate(node=>{
    const body=node.querySelector('.sheet-body').getBoundingClientRect();
    const block=node.querySelector('.box-crit').getBoundingClientRect();
    return {bodyTop:body.top,bodyBottom:body.bottom,blockerTop:block.top,blockerBottom:block.bottom,
      blockerInitiallyVisible:block.top>=body.top&&block.top<Math.min(innerHeight,body.bottom)};
  });
  assert(initial.blockerInitiallyVisible,'Save blocker starts hidden below the long removal diff');
  result.initialReviewScreenshot=await screenshot(review,page,`editor-blocker-${result.spec.name}-review-initial.png`);
  await blocker.scrollIntoViewIfNeeded();
  const reviewMetrics=await dialog.evaluate(node=>{
    const body=node.querySelector('.sheet-body'), b=node.getBoundingClientRect();
    const blocker=node.querySelector('.box-crit').getBoundingClientRect();
    return { removedRows:node.querySelectorAll('.review-removed').length,
      bodyHeight:body.clientHeight,bodyScrollHeight:body.scrollHeight,bodyScrollTop:body.scrollTop,
      blockerTop:blocker.top,blockerBottom:blocker.bottom,dialogTop:b.top,dialogBottom:b.bottom,
      blockerVisible:blocker.top>=b.top&&blocker.top<Math.min(innerHeight,b.bottom),
      blockerText:node.querySelector('.box-crit').textContent.trim() };
  });
  assert(reviewMetrics.blockerVisible,'Long-diff blocker cannot be discovered by scrolling');
  assert.equal(reviewMetrics.removedRows,removed,'Review omitted removed card identities');
  result.reviewPng=`editor-blocker-${result.spec.name}-review.png`;
  result.reviewScreenshot=await screenshot(review,page,result.reviewPng);
  await dialog.getByRole('button',{name:'Keep editing',exact:true}).click();
  assert.equal(await page.locator('.bar-undo').isDisabled(),false,'Keep editing lost footer Undo');
  assert.equal(await page.locator('.bar-discard').isDisabled(),false,'Keep editing lost footer Discard');
  return {removed,initial,review:reviewMetrics,blockedSave:true,keepEditingRecoveredFooter:true};
}

async function receiptChecks(page) {
  const checkbox=page.getByRole('checkbox',{name:'Check off 1 copy of Llanowar Elves',exact:true});
  await checkbox.check();
  assert.equal(await checkbox.isChecked(),true);
  await checkbox.uncheck();
  const last=page.locator('.rcpt-grid input[type=checkbox]').last();
  await last.focus();
  const focus=await last.evaluate(node => {
    const b=node.getBoundingClientRect(), hit=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);
    return { focused:document.activeElement===node, top:b.y, bottom:b.bottom,
      inViewport:b.y>=0&&b.bottom<=innerHeight, hit:hit===node||node.contains(hit) };
  });
  assert(focus.focused&&focus.inViewport&&focus.hit,'Last receipt checkbox is obscured at browser zoom');
  const when=page.getByRole('combobox',{name:'When it arrived',exact:true});
  const original=await when.inputValue();
  await when.selectOption('other');
  const date=page.getByLabel('Arrival date',{exact:true});
  await date.focus();
  const dateFocus=await date.evaluate(node=>{
    const b=node.getBoundingClientRect(),hit=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);
    return {focused:document.activeElement===node,top:b.y,bottom:b.bottom,
      inViewport:b.y>=0&&b.bottom<=innerHeight,hit:hit===node||node.contains(hit)};
  });
  assert(dateFocus.focused&&dateFocus.inViewport&&dateFocus.hit,'Native arrival date is obscured at browser zoom');
  await when.selectOption(original);
  return { localCheckAndUncheck:true,lastRowFocus:focus,nativeDateFocus:dateFocus,dateChoiceRestored:true };
}

run('zoom',async review => {
  review.report.results=[];
  review.report.zoomBrowsers=[];
  review.report.scope='Actual Chromium page zoom over disposable synthetic records; fine pointer only, no CSS enlargement, final writes or physical device acceptance.';
  const routes=review.config.ready.routes;
  const tasks=[
    ['editor',routes.editor,'.edit-page'],['receipt',routes.receipt,'.rcpt-grid'],['testing',routes.board,'.gb-row'],
    ['editor-blocker','/#/edit?id=commander%2Fwoodland-council&v=target','.edit-page'],
    ['collection','/#/collection','.collection-page'],
    ['collection-rows','/#/collection?view=rows','.collection-page'],
    ['shopping','/#/shopping','.shop-page'],['tokens','/#/tokens','.tok-page'],
    ['accessories','/#/accessories','.acc-page'],['play','/#/play','.play-section'],
    ['activity','/#/activity','.activity-layout'],['settings','/#/settings','.settings-part'],
    ['wishlist','/#/wishlist','.wishlist-page'],
  ];
  const specs=[];
  for(const theme of ['light','dark']) for(const width of (review.options.smoke?[1470]:[1470,640])) {
    for(const zoom of [1,2]) specs.push({theme,width,height:900,zoom,name:`window-${width}-zoom${zoom}-${theme}`});
  }
  review.report.expected_captures=specs.length*tasks.length;
  const pairs=new Map();
  for(const spec of specs) {
    review.checkCancelled();
    if(review.browser?.isConnected()) await review.browser.close();
    const profile=path.join(review.config.runtime,'zoom-profile-'+spec.name);
    assert.equal(path.dirname(profile),review.config.runtime,'Zoom profile must belong to the disposable runtime');
    fs.mkdirSync(path.join(profile,'Default'),{recursive:true});
    // Current Chromium's empty storage-partition key is "x"; "0" supports older builds.
    // The CDP/layout/DPR assertions below must still prove the requested actual zoom.
    fs.writeFileSync(path.join(profile,'Default','Preferences'),JSON.stringify({
      partition:{default_zoom_level:{x:Math.log(spec.zoom)/Math.log(1.2),'0':Math.log(spec.zoom)/Math.log(1.2)},per_host_zoom_levels:{}},
    }));
    const {chromium}=require('playwright-core');
    let context;
    const ownership={spec,started:false,closed:false};
    review.report.zoomBrowsers.push(ownership);
    try {
      context=await chromium.launchPersistentContext(profile,{headless:true,executablePath:review.options.browser,
        viewport:null,colorScheme:spec.theme,reducedMotion:'reduce',acceptDownloads:false,serviceWorkers:'block',
        locale:'en-AU',timezoneId:'Australia/Brisbane',args:[
          '--disable-background-networking','--no-first-run','--disable-default-apps',
          '--force-device-scale-factor=1',`--window-size=${spec.width},${spec.height}`,
        ]});
      ownership.started=true;
      review.browser=context.browser();
      assert(review.browser,'Persistent zoom context must expose its owned browser');
      await review.guardContext(context);
      for(const [task,route,ready] of tasks) {
        const result={spec:{...spec,task},status:'failed',page_errors:[],http_errors:[]};
        review.report.results.push(result);
        let page;
        try {
          review.select();
          page=await context.newPage();
          review.observe(page,result.page_errors,result.http_errors);
          const savedPath='/api/deck/edit?id='+encodeURIComponent(task==='editor-blocker'?'commander/woodland-council':'casual/safari-fixture');
          const before=digest(await review.readFixture(context,savedPath));
          await page.goto(review.pageUrl(route,spec.theme),{waitUntil:'domcontentloaded'});
          await page.waitForSelector(ready,{timeout:15000});
          await page.evaluate(()=>document.fonts.ready);
          const session=await context.newCDPSession(page);
          result.before=await metrics(page,session);
          assert.equal(result.before.cdp.visualViewport.zoom,spec.zoom,'Chrome did not apply actual requested page zoom');
          assert.equal(result.before.visualViewport.scale,1,'Pinch zoom must not substitute for page zoom');
          const pairKey=[spec.width,spec.theme,task].join('-');
          if(spec.zoom===1) pairs.set(pairKey,result.before);
          else {
            const base=pairs.get(pairKey);
            assert(base,'Missing matched browser window baseline');
            result.zoomProof={baselineZoom:base.cdp.visualViewport.zoom,
              measuredZoom:result.before.cdp.visualViewport.zoom,
              baselineLayoutWidth:base.cdp.layoutViewport.clientWidth,
              enlargedLayoutWidth:result.before.cdp.layoutViewport.clientWidth,
              baselineOuterWidth:base.outerWidth,enlargedOuterWidth:result.before.outerWidth,
              dprRatio:result.before.dpr/base.dpr};
            assert.equal(result.before.outerWidth,base.outerWidth,'Browser window changed during page zoom comparison');
            assert(Math.abs(result.before.cdp.layoutViewport.clientWidth*2-base.cdp.layoutViewport.clientWidth)<=2,
              'Actual 200% page zoom must halve the CSS layout viewport');
            assert(Math.abs(result.before.dpr/base.dpr-2)<.01,'Page zoom must double CSS-to-device scale');
          }
          assert(result.before.scrollWidth<=result.before.clientWidth,'Document overflow at actual browser zoom');
          result.interactions=task==='editor'?await editorChecks(page):task==='receipt'?await receiptChecks(page)
            :task==='editor-blocker'?await longBlockerChecks(review,page,result):null;
          result.after=await metrics(page,session);
          result.savedDeck={before,after:digest(await review.readFixture(context,savedPath))};
          assert.equal(result.savedDeck.before,result.savedDeck.after,'Zoom interactions changed the saved deck');
          result.png=`${task}-${spec.name}.png`;
          result.screenshot=await screenshot(review,page,result.png);
          assert.equal(result.page_errors.length,0,'Uncaught page error at actual browser zoom');
          assert(!result.http_errors.some(row=>row.category==='unexpected_http_error'),'Unexpected fixture HTTP failure');
          result.status='captured';
        } catch(error) {result.error=review.safeText(error.message);}
        finally {if(page) await page.close();review.save();}
      }
    } finally {
      if(context) await context.close();
      ownership.closed=!review.browser?.isConnected();
      review.save();
    }
  }
  review.report.cleanup.zoom_browsers_closed=review.report.zoomBrowsers.every(row=>row.started&&row.closed);
  assert(review.report.cleanup.zoom_browsers_closed,'Zoom browser cleanup is incomplete');
  assert.equal(review.report.results.filter(row=>row.status!=='captured').length,0,'Actual browser zoom qualification failed');
});
