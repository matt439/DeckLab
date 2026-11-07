'use strict';
// Receipt pointer, last-row and footer clearance qualification. All edits remain local.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

function matrix(smoke) {
  const result=[];
  for(const theme of ['light','dark']) {
    const add=(width,height,root200=false,coarse=width<1000,parcel='receipt') => result.push({
      width,height,root200,coarse,theme,parcel,
      name:`${parcel}-${width}x${height}${root200?'-root200':''}-${coarse?'coarse':'fine'}-${theme}` });
    for(const width of (smoke?[393]:[320,393,600,820,1440])) add(width,width===820?1106:width>=1000?900:700);
    for(const width of [320,600]) add(width,700,true);
    if(!smoke) add(740,360,false,false);
    for(const parcel of ['large_receipt','split_receipt']) {
      for(const width of (smoke?[393]:[393,820])) add(width,width===820?1106:700,false,true,parcel);
    }
  }
  return result;
}

async function measure(page) {
  return page.evaluate(() => {
    const box=node => {
      if(!node) return null;
      const b=node.getBoundingClientRect(),s=getComputedStyle(node);
      const cx=b.x+b.width/2,cy=b.y+b.height/2,hit=document.elementFromPoint(cx,cy);
      return {x:b.x,y:b.y,width:b.width,height:b.height,right:b.right,bottom:b.bottom,
        position:s.position,fontSize:s.fontSize,text:node.textContent.trim().slice(0,180),
        disabled:node.disabled??null,ariaDisabled:node.getAttribute('aria-disabled'),
        centerReceivesPointer:!!hit&&(node===hit||node.contains(hit))};
    };
    const bar=document.querySelector('.rcpt-bar'),sheet=document.querySelector('dialog[open]');
    return {innerWidth,innerHeight,scrollY,rootFont:getComputedStyle(document.documentElement).fontSize,
      documentOverflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
      bar:box(bar),toolbar:box(document.querySelector('.rcpt-toolbar')),grid:box(document.querySelector('.rcpt-grid')),
      checks:[...document.querySelectorAll('.rcpt-tick')].map(node=>({...box(node),checked:node.checked})),
      parts:[...document.querySelectorAll('.rcpt-arrived input')].map(node=>node.checked),
      date:box(document.querySelector('.rcpt-date')),primary:box(document.querySelector('.rcpt-bar .btn-primary')),
      active:box(document.activeElement),sheet:box(sheet),
      sheetBody:box(sheet?.querySelector('.sheet-body')),shellTop:box(document.querySelector('.topbar')),
      shellBottom:box(document.querySelector('.tabbar')),inline:bar?.classList.contains('is-inline')??false};
  });
}

async function shot(review,page,result,suffix) {
  const file=`${result.spec.name}-${suffix}.png`;
  await page.screenshot({path:path.join(review.out,file),fullPage:false,animations:'disabled'});
  result.screenshots.push(file);
}

async function checkCase(review,page,result,context) {
  result.pointerFailures=[];
  // A failed pointer operation is retained as evidence. Keyboard fallback only arranges the next
  // diagnostic; it never turns a pointer failure into a pass.
  const click=async(locator,name,fallback='Enter') => {
    try {await locator.click({timeout:1800});return true;}
    catch(error) {
      result.pointerFailures.push({name,error:review.safeText(error.message),metrics:await measure(page)});
      await shot(review,page,result,`blocked-${result.pointerFailures.length}`);
      if(fallback) {await locator.focus();await locator.press(fallback);}
      return false;
    }
  };
  const order=new URLSearchParams(review.config.ready.routes[result.spec.parcel].split('?')[1]).get('order');
  const api='/api/receipt?order='+encodeURIComponent(order);
  const savedBefore=await review.readFixture(context,api);
  const parts=page.locator('.rcpt-arrived input');
  for(let n=0;n<await parts.count();n++) await click(parts.nth(n),`select arrived part ${n+1}`,'Space');
  if(result.spec.parcel==='split_receipt') assert.equal(await parts.count(),2,'Multipart fixture is missing a part');
  const first=page.locator('.rcpt-board .rcpt-tick').first();
  await click(first,'first card check','Space');
  assert(await first.isChecked(),'Initial local selection missing');
  if(result.spec.parcel==='split_receipt') {
    const count=await page.locator('.rcpt-board .rcpt-tick').count();
    await click(page.locator('.rcpt-picture-inspect').first(),'inspect copies before split');
    const sheet=page.locator('dialog[open]');
    await click(sheet.getByRole('button',{name:'Split into a new tile',exact:true}),'split one copy locally');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.rcpt-board .rcpt-tick').count(),count+1,'Split did not add one working tile');
    assert(await first.isChecked(),'Split lost the original checked part');
    assert(!await page.locator('.rcpt-board .rcpt-tick').nth(1).isChecked(),'Split marked pending copies arrived');
    result.splitChecked=true;
  }
  await page.evaluate(()=>scrollTo(0,0));
  result.top=await measure(page);await shot(review,page,result,'top');
  const tools=page.locator('.rcpt-toolbar').first().getByRole('button',{name:'Tools',exact:true});
  let scope=page.locator('.rcpt-toolbar').first();
  if(await tools.isVisible()) {
    await click(tools,'open Tools');
    scope=page.getByRole('dialog',{name:'Tools',exact:true});
    await scope.waitFor({state:'visible'});
    result.tools=await measure(page);await shot(review,page,result,'tools');
  }
  const layout=scope.getByRole('group',{name:'Layout',exact:true});
  await click(layout.getByRole('button',{name:'List',exact:true}),'switch to List');
  assert.equal(await layout.getByRole('button',{name:'List',exact:true}).getAttribute('aria-pressed'),'true');
  assert(await first.isChecked(),'List layout lost the checked copy');
  await click(layout.getByRole('button',{name:'Pictures',exact:true}),'return to Pictures');
  if(await scope.getAttribute('role')==='dialog'||await scope.evaluate(node=>node.tagName==='DIALOG')) {
    await click(scope.getByRole('button',{name:'Done',exact:true}),'close Tools');
  }
  const last=page.locator('.rcpt-grid input[type=checkbox]').last();
  const wasChecked=await last.isChecked();
  await click(last,'last card check','Space');
  assert.equal(await last.isChecked(),!wasChecked,'Last card selection did not change locally');
  result.lastRow=await measure(page);await shot(review,page,result,'last-row');
  await last.press('Tab');
  result.keyboardFocus=await measure(page);
  const a=result.keyboardFocus.active,t=result.keyboardFocus.shellTop,b=result.keyboardFocus.shellBottom;
  const bar=result.keyboardFocus.bar;
  result.focusClear=!!a&&a.y>=Math.max(0,t?.bottom||0)&&a.bottom<=Math.min(innerHeightFor(result),
    b&&b.height?b.y:Infinity,bar?.position==='sticky'?bar.y:Infinity);
  await shot(review,page,result,'focus');
  const when=page.getByRole('combobox',{name:'When it arrived',exact:true});
  await click(when,'arrival date choice',null);
  await when.selectOption('other');
  const date=page.getByRole('textbox',{name:'Arrival date',exact:true});
  // HTML date inputs have no textbox role in Chromium; retain the exact accessible name selector.
  const input=await date.count()?date:page.locator('input[aria-label="Arrival date"]');
  await click(input,'arrival date input',null);
  result.footer=await measure(page);await shot(review,page,result,'footer');
  await when.selectOption('today');
  assert(await first.isChecked(),'Footer controls lost the original local selection');
  const primary=page.locator('.rcpt-bar .btn-primary');
  // Trial performs native scrolling/actionability checks without emitting a click or preview request.
  await primary.click({trial:true,timeout:2500});
  result.primaryPointer=await measure(page);await shot(review,page,result,'primary');
  await when.focus();
  await when.press('Tab');
  assert(await primary.evaluate(node=>node===document.activeElement),'Native Tab did not reach Record arrival');
  result.primaryKeyboard=await measure(page);
  const p=result.primaryKeyboard.primary,pt=result.primaryKeyboard.shellTop,pb=result.primaryKeyboard.shellBottom;
  assert(p.centerReceivesPointer,'Focused Record arrival is covered');
  assert(p.y>=Math.max(0,pt?.bottom||0)&&p.bottom<=Math.min(result.primaryKeyboard.innerHeight,
    pb&&pb.height?pb.y:Infinity),'Focused Record arrival is obscured by shell chrome');
  await shot(review,page,result,'primary-focus');
  // Persisted receipt fields require explicit Resume after reload. Clean-notes preference is
  // intentionally only per page and is not asserted to survive a browser reload.
  await click(page.locator('.rcpt-toolbar').first().locator('[data-filter=ticked]'),'show checked cards');
  const draftBefore=await page.evaluate(()=>Object.entries(localStorage)
    .filter(([key])=>key.startsWith('decklab.receipt:')).map(([key,value])=>[key,JSON.parse(value)]));
  await page.reload({waitUntil:'domcontentloaded'});
  if(result.spec.root200) await page.evaluate(()=>{document.documentElement.style.fontSize='200%';});
  await page.getByRole('button',{name:'Resume your check',exact:true}).waitFor({state:'visible'});
  await click(page.getByRole('button',{name:'Resume your check',exact:true}),'resume local check after reload');
  assert(await first.isChecked(),'Reload/resume lost the first checked part');
  const draftAfter=await page.evaluate(()=>Object.entries(localStorage)
    .filter(([key])=>key.startsWith('decklab.receipt:')).map(([key,value])=>[key,JSON.parse(value)]));
  assert.deepEqual(draftAfter,draftBefore,'Reload/resume changed persisted checking values');
  assert.equal(await page.locator('.rcpt-toolbar').first().locator('[data-filter=ticked]').getAttribute('aria-pressed'),'true');
  assert.equal(await page.locator('.rcpt-toolbar').first().locator('[data-layout=pictures]').getAttribute('aria-pressed'),'true');
  if(result.spec.parcel==='split_receipt') assert.equal(await page.locator('.rcpt-arrived input:checked').count(),2);
  result.reloadRestoredDraft=true;
  result.resumed=await measure(page);await shot(review,page,result,'resumed');
  assert.deepEqual(await review.readFixture(context,api),savedBefore,'Local checking changed the saved receipt');
  result.savedReceiptUnchanged=true;
  result.localOnly=true;
}

function innerHeightFor(result) {return result.keyboardFocus.innerHeight;}

run('receipt-layout',async review => {
  const specs=matrix(review.options.smoke);review.report.results=[];review.report.expected_captures=specs.length;
  review.report.scope='Ordinary pointer checks of receipt layout/date controls, first/last card selection, native Tab clearance, explicit reload/resume and larger/multipart parcels. CSS root-font stress and short landscape are synthetic; no preview, fill, Save or arrival recording.';
  for(const spec of specs) {
    let context,page;const result={spec,status:'failed',page_errors:[],http_errors:[],screenshots:[]};
    try {
      review.select();context=await review.context(spec);page=await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      await page.goto(review.pageUrl(review.config.ready.routes[spec.parcel],spec.theme),{waitUntil:'domcontentloaded'});
      await page.waitForSelector('.rcpt-grid');await page.evaluate(()=>document.fonts.ready);
      if(spec.root200) await page.evaluate(()=>{document.documentElement.style.fontSize='200%';});
      await page.waitForTimeout(250);
      await checkCase(review,page,result,context);
      assert.equal(result.pointerFailures.length,0,'Receipt controls could not receive pointer input');
      assert(result.focusClear,'Last-row Tab focus is obscured by page chrome');
      assert.equal(result.page_errors.length,0,'Uncaught page error');
      assert(!result.http_errors.some(e=>e.category==='unexpected_http_error'),'Unexpected fixture HTTP error');
      for(const key of ['top','tools','lastRow','keyboardFocus','footer','primaryPointer','primaryKeyboard','resumed']) {
        if(result[key]) assert(!result[key].documentOverflow,`Document overflow at ${key}`);
      }
      result.status='captured';
    } catch(error) {
      result.error=review.safeText(error.message);
      if(page&&!page.isClosed()) try {result.failureMetrics=await measure(page);await shot(review,page,result,'failed');} catch(_) {}
    } finally {if(context) await context.close();review.report.results.push(result);review.save();}
    console.log(JSON.stringify({id:spec.name,status:result.status}));review.checkCancelled();
  }
  assert.equal(review.report.results.filter(r=>r.status!=='captured').length,0,'Receipt qualification failed');
});
