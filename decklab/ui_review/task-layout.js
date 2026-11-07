'use strict';
// Receipt tools and empty alternatives, using ordinary local controls on invented records.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

async function measure(page, width) {
  return page.evaluate(width => {
    const box = node => {
      if (!node) return null;
      const b = node.getBoundingClientRect(), s = getComputedStyle(node);
      return { tag:node.tagName, className:node.className, x:b.x, y:b.y, width:b.width,
        height:b.height, right:b.right, bottom:b.bottom, display:s.display,
        fontSize:s.fontSize, fontWeight:s.fontWeight, lineHeight:s.lineHeight,
        padding:s.padding, gap:s.gap, color:s.color, background:s.backgroundColor,
        text:node.textContent.trim().slice(0,200), label:node.getAttribute('aria-label'),
        pressed:node.getAttribute('aria-pressed'), open:node.hasAttribute('open') };
    };
    const visible = node => {
      const b = node.getBoundingClientRect(), s = getComputedStyle(node);
      return b.width > 0 && b.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
    };
    const section = document.querySelector('.edit-considering');
    return { configuredWidth:width, innerWidth, innerHeight, scrollX, scrollY,
      clientWidth:document.documentElement.clientWidth, scrollWidth:document.documentElement.scrollWidth,
      documentOverflow:document.documentElement.scrollWidth > document.documentElement.clientWidth,
      layoutViewportExpanded:innerWidth > width,
      coarse:matchMedia('(pointer:coarse)').matches,
      rootFont:getComputedStyle(document.documentElement).fontSize,
      quick:document.body.classList.contains('is-quick-edit'),
      receiptToolbar:box(document.querySelector('.rcpt-toolbar')),
      receiptEverything:[...document.querySelectorAll('.rcpt-everything')]
        .map(node => ({...box(node),parentClass:node.parentElement?.className})),
      receiptTools:[...document.querySelectorAll('.rcpt-toolbar button,.rcpt-toolbar select,.rcpt-toolbar label')]
        .filter(visible).map(box),
      receiptGrid:box(document.querySelector('.rcpt-grid')),
      receiptBar:box(document.querySelector('.rcpt-bar')),
      receiptRecovery:box(document.querySelector('.rcpt-blanks')),
      checked:[...document.querySelectorAll('.rcpt-grid input[type=checkbox]:checked')]
        .map(node => node.getAttribute('aria-label')),
      considering:box(section),
      consideringContents:section ? [...section.children].filter(visible).map(box) : [],
      consideringButtons:section ? [...section.querySelectorAll('button,summary')].filter(visible).map(box) : [],
      consideringRows:section?.querySelectorAll('.editor-considering-row').length ?? null,
      dialog:box(document.querySelector('dialog[open]')),
      active:box(document.activeElement),
      editorReadOnly:typeof editor === 'undefined' || !editor ? null : {
        dirty:editor.dirty, historyLength:editor.history.length, consideringLength:editor.considering?.length },
    };
  },width);
}

function matrix(smoke) {
  const specs = [];
  for(const theme of ['light','dark']) {
    const add = (task,width,root200=false) => specs.push({task,width,
      height:width===820?1106:width>=1000?900:700, coarse:width<1000, theme,root200,
      name:`${task}-${width}${root200?'-root200':''}-${theme}`});
    for(const width of (smoke?[393,820]:[320,393,430,600,820,1440])) add('receipt',width);
    for(const width of (smoke?[393,820]:[320,393,820,1440])) add('considering',width);
    if(!smoke) for(const task of ['receipt','considering']) for(const width of [320,600]) add(task,width,true);
  }
  return specs.sort((a,b)=>Number(b.root200)-Number(a.root200));
}

async function screenshot(review,page,result,suffix='') {
  const name=result.spec.name+suffix+'.png';
  await page.screenshot({path:path.join(review.out,name),fullPage:false,animations:'disabled'});
  result.screenshots.push(name);
}

async function receiptChecks(review,page,result) {
  const activate=async locator => {
    if(result.spec.root200) {await locator.focus();await locator.press('Enter');}
    else await locator.click();
  };
  result.interactionMethod=result.spec.root200?'native keyboard; preliminary click occlusion remains separate evidence':'ordinary browser clicks';
  const check = () => page.getByRole('checkbox',{name:'Check off 1 copy of Llanowar Elves',exact:true});
  if(result.spec.root200) {await check().focus();await check().press('Space');}
  else await check().check();
  assert.equal(await check().isChecked(),true,'Initial local check did not select its row');
  await page.locator('.rcpt-blanks').waitFor({state:'visible'});
  const toolbar=page.locator('.rcpt-toolbar').first();
  await page.evaluate(() => window.scrollTo(0,0));
  result.top=await measure(page,result.spec.width);
  await screenshot(review,page,result,'-top');
  await toolbar.evaluate(node => window.scrollTo(0,scrollY+node.getBoundingClientRect().top-80));
  result.metrics=await measure(page,result.spec.width);
  await screenshot(review,page,result);
  let scope=toolbar;
  const tools=toolbar.getByRole('button',{name:'Tools',exact:true});
  if(await tools.isVisible()) {
    await activate(tools);
    scope=page.getByRole('dialog',{name:'Tools',exact:true});
    await scope.waitFor({state:'visible'});
    result.toolsOpen=await measure(page,result.spec.width);
    await screenshot(review,page,result,'-tools');
  }
  // Layout, preferences and filters are local controls. No fill, bulk tick, preview or arrival action is invoked.
  const layout=scope.getByRole('group',{name:'Layout',exact:true});
  await activate(layout.getByRole('button',{name:'List',exact:true}));
  assert.equal(await layout.getByRole('button',{name:'List',exact:true}).getAttribute('aria-pressed'),'true');
  assert.equal(await check().isChecked(),true,'Layout lost the local selection');
  await activate(layout.getByRole('button',{name:'Pictures',exact:true}));
  const clean=scope.locator('.rcpt-clean input');
  const original=await clean.isChecked();
  if(result.spec.root200) {await clean.focus();await clean.press('Space');await clean.press('Space');}
  else {await clean.setChecked(!original);await clean.setChecked(original);}
  assert.equal(await clean.isChecked(),original,'Preference did not return to its original state');
  if(scope!==toolbar) await activate(scope.getByRole('button',{name:'Done',exact:true}));
  await activate(toolbar.locator('[data-filter=ticked]'));
  assert.equal(await check().isChecked(),true,'Ticked filter lost the local selection');
  await activate(toolbar.locator('[data-filter=all]'));
  assert.equal(await check().isChecked(),true,'All filter lost the local selection');
  result.after=await measure(page,result.spec.width);
  result.localControlsChecked=true;
}

async function consideringChecks(review,page,result,context) {
  await page.waitForFunction(() => typeof editor!=='undefined' && editor && !editor.checking);
  const deckId=new URLSearchParams(review.config.ready.routes.editor.split('?')[1]).get('id');
  const api='/api/deck/edit?id='+encodeURIComponent(deckId);
  const before=await review.readFixture(context,api);
  const section=page.locator('.edit-considering');
  await section.waitFor({state:'visible'});
  await section.evaluate(node => window.scrollTo(0,scrollY+node.getBoundingClientRect().top-80));
  assert.equal(await section.locator('.editor-considering-row').count(),0,'Fixture alternatives must be empty');
  result.metrics=await measure(page,result.spec.width);
  result.accessibility=await section.ariaSnapshot();
  await screenshot(review,page,result);
  const summary=section.locator('details > summary');
  if(await summary.count()) {
    await summary.click();
    assert.equal(await section.locator('details').first().getAttribute('open'),'');
    result.helpOpen=await measure(page,result.spec.width);
    await screenshot(review,page,result,'-help');
    await summary.click();
    assert.equal(await section.locator('details').first().getAttribute('open'),null);
  } else result.helpOpen=null; // Matched baseline predates the disclosure.
  await section.locator('.editor-considering-add').click();
  const dialog=page.getByRole('dialog',{name:'Add a card to consider',exact:true});
  await dialog.waitFor({state:'visible'});
  result.addOpen=await measure(page,result.spec.width);
  await screenshot(review,page,result,'-add');
  await page.keyboard.press('Escape');
  await dialog.waitFor({state:'detached'});
  result.after=await measure(page,result.spec.width);
  assert.equal(result.after.editorReadOnly.consideringLength,0,'Opening Add changed alternatives');
  assert.equal(result.after.editorReadOnly.dirty,result.metrics.editorReadOnly.dirty,'Opening Add changed draft dirty state');
  assert.deepEqual(await review.readFixture(context,api),before,'Local controls changed the saved deck');
  result.savedDeckUnchanged=true;
  result.localControlsChecked=true;
}

run('task-layout',async review => {
  const specs=matrix(review.options.smoke);
  review.report.results=[];
  review.report.expected_captures=specs.length;
  review.report.scope='Receipt tools and empty Considering with invented records. Ordinary local layout/filter/help/Add controls; no saving, bulk fill, preview or arrival. CSS root-font stress is not browser zoom. Overflow remains diagnostic for paired comparison.';
  for(const spec of specs) {
    let context,page;
    const result={spec,status:'failed',page_errors:[],http_errors:[],screenshots:[]};
    try {
      review.select(); context=await review.context(spec); page=await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      const route=review.config.ready.routes[spec.task==='receipt'?'receipt':'editor'];
      await page.goto(review.pageUrl(route,spec.theme),{waitUntil:'domcontentloaded'});
      await page.waitForSelector(spec.task==='receipt'?'.rcpt-grid':'.edit-page');
      await page.evaluate(() => document.fonts.ready);
      if(spec.root200) await page.evaluate(() => {document.documentElement.style.fontSize='200%';});
      await page.waitForTimeout(250);
      result.configuredViewport=page.viewportSize();
      assert.deepEqual(result.configuredViewport,{width:spec.width,height:spec.height});
      if(spec.task==='receipt') await receiptChecks(review,page,result);
      else await consideringChecks(review,page,result,context);
      assert.equal(result.page_errors.length,0,'Uncaught page error');
      assert(!result.http_errors.some(r=>r.category==='unexpected_http_error'),'Unexpected fixture HTTP failure');
      result.status='captured';
    } catch(error) {
      result.error=review.safeText(error.message);
      if(page&&!page.isClosed()) try {result.failureMetrics=await measure(page,spec.width);await screenshot(review,page,result,'-failed');} catch(_) {}
    } finally {if(context) await context.close();review.report.results.push(result);review.save();}
    console.log(JSON.stringify({id:spec.name,status:result.status}));
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(r=>r.status!=='captured').length,0,'Task layout captures failed');
});
