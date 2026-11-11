'use strict';
// Remaining real page renderers, with explicitly synthetic GET-only state adapters.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

const PAGES = [
  {name:'collection', route:'/#/collection', endpoint:'/api/collection', ready:'.collection-page'},
  {name:'collection-rows', route:'/#/collection?view=rows', endpoint:'/api/collection/rows', ready:'.collection-page'},
  {name:'shopping', route:'/#/shopping', endpoint:'/api/shopping', ready:'.shop-page'},
  {name:'tokens', route:'/#/tokens', endpoint:'/api/tokens', ready:'.tok-page'},
  {name:'accessories', route:'/#/accessories', endpoint:'/api/accessories', ready:'.acc-page'},
  {name:'play', route:'/#/play', endpoint:'/api/play', ready:'.play-section'},
  {name:'activity', route:'/#/activity', endpoint:'/api/activity', ready:'.activity-layout'},
  {name:'settings', route:'/#/settings', endpoint:'/api/settings/maintenance', ready:'.settings-part'},
  {name:'wishlist', route:'/#/wishlist', endpoint:'/api/profiles/matt/wishlist', ready:'.wishlist-page'},
];

function empty(data, name) {
  for (const key of Object.keys(data)) if (Array.isArray(data[key])) data[key] = [];
  if (name === 'collection') { data.total=0; data.shown=0; }
  if (name === 'tokens') {data.cards=0;data.sorted=true;}
  if (name === 'shopping') for(const key of ['missing','combined']) if(data[key]&&typeof data[key]==='object') {
    for(const sub of Object.keys(data[key])) if(Array.isArray(data[key][sub])) data[key][sub]=[];
  }
  return data;
}

async function measure(page) {
  return page.evaluate(() => {
    const visible = n => {const b=n.getBoundingClientRect(); return b.width>0 && b.height>0 && getComputedStyle(n).visibility!=='hidden';};
    const sample = selector => [...document.querySelectorAll(selector)].filter(visible).slice(0,6).map(n=>{
      const b=n.getBoundingClientRect(),s=getComputedStyle(n);
      return {text:n.textContent.trim().slice(0,160),x:b.x,y:b.y,width:b.width,height:b.height,
        fontFamily:s.fontFamily,fontSize:s.fontSize,fontWeight:s.fontWeight,fontStyle:s.fontStyle,
        lineHeight:s.lineHeight,textTransform:s.textTransform,letterSpacing:s.letterSpacing,
        color:s.color,background:s.backgroundColor,padding:s.padding,gap:s.gap,opacity:s.opacity};
    });
    return {width:innerWidth,height:innerHeight,scrollY,clientWidth:document.documentElement.clientWidth,
      scrollWidth:document.documentElement.scrollWidth,rootFont:getComputedStyle(document.documentElement).fontSize,
      title:document.querySelector('#main h1')?.textContent,
      samples:Object.fromEntries(['#main h1','#main h2','#main h3','#main .sub','#main table.data th',
        '#main table.data td','#main .group-row','#main .card-name','#main .btn-primary',
        '#main .btn','#main .box-crit','#main .empty','#main [role=status]',
        '.shop-jumps','.activity-change','.col-find-name','.col-detail-code','.col-results',
        '.col-storage-forecast','.col-forecast-summary','.field-hint','.field > span:not(.field-hint)'].map(s=>[s,sample(s)])),
      text:document.querySelector('#main')?.innerText.slice(0,6000),
      overflow:[...document.querySelectorAll('#main *')].filter(visible).filter(n=>{
        const b=n.getBoundingClientRect();return b.right>innerWidth+1 || b.left < -1;
      }).slice(0,15).map(n=>({tag:n.tagName,class:n.className,text:n.textContent.trim().slice(0,80)}))};
  });
}

async function settingsLayout(page) {
  return page.evaluate(() => {
    const shown = node => {const b=node.getBoundingClientRect();return b.width>0&&b.height>0&&getComputedStyle(node).visibility!=='hidden';};
    const panels=[...document.querySelectorAll('.settings-part')];
    const rows=panels.flatMap(panel=>[panel,...panel.querySelectorAll('input,select,textarea,button,fieldset,summary,a[href]')]
      .filter(shown).map(node=>{
        const b=node.getBoundingClientRect(),p=panel.getBoundingClientRect();
        return {tag:node.tagName,id:node.id,panel:panel.id,left:b.left,right:b.right,width:b.width,
          panelLeft:p.left,panelRight:p.right,disabled:node.disabled===true};
      }));
    const controls=panels.flatMap(panel=>[...panel.querySelectorAll('input,select,textarea,button,summary,a[href]')])
      .filter(node=>shown(node)&&!node.disabled);
    let horizontalScroll=false,focusFailures=0;
    for(const control of controls) {
      control.focus();
      horizontalScroll ||= Math.abs(scrollX)>1;
      if(document.activeElement!==control) focusFailures++;
    }
    document.activeElement?.blur();scrollTo(0,0);
    return {width:innerWidth,clientWidth:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,
      rows,controls:controls.length,horizontalScroll,focusFailures};
  });
}

run('families', async review => {
  review.report.results=[];
  review.report.scope='Synthetic remaining page families; GET adapters for empty, unavailable and pending reads. No final writes.';
  const specs=[];
  for(const theme of ['light','dark']) for(const p of PAGES) {
    const widths=p.name==='settings' ? (review.options.smoke ? [320,393,1440] : [320,375,393,430,820,1440])
      : (review.options.smoke ? [393,1440] : [393,820,1440]);
    for(const width of widths)
      specs.push({...p,theme,width,height:width<600?700:900,state:'populated',coarse:width<1000});
    if(p.name==='settings') specs.push({...p,theme,width:393,height:700,state:'populated',coarse:true,root200:true});
    if(!review.options.smoke) for(const state of ['empty','failed','busy']) {
      if(p.name==='settings' && state==='empty') continue;
      specs.push({...p,theme,width:393,height:700,coarse:true,state});
    }
  }
  review.report.expected_captures=specs.length;
  for(const spec of specs) {
    const result={spec,status:'failed',page_errors:[],http_errors:[]};let context,release;
    try {
      review.select();context=await review.context(spec);const page=await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      if(spec.name==='settings') {
        await page.route('**/api/pricing-setting',async route=>{
          if(new URL(route.request().url()).origin!==review.origin||route.request().method()!=='GET') return route.fallback();
          const response=await route.fetch({maxRedirects:0});
          assert(response.ok(),'Settings price adapter requires an ordinary successful read');
          const data=await response.json();
          data.listing_preferences={saved:{minimum_condition:'MP',english_only:true},effective:{minimum_condition:'MP',english_only:true},
            conditions:[{code:'NM',label:'Near Mint'},{code:'LP',label:'Lightly Played'},{code:'MP',label:'Moderately Played'},
              {code:'HP',label:'Heavily Played'},{code:'DMG',label:'Damaged'}]};
          return route.fulfill({response,json:data});
        });
      }
      if(spec.state!=='populated') {
        let reachedResolve;const reached=new Promise(resolve=>{reachedResolve=resolve;});
        const gate=new Promise(resolve=>{release=resolve;});
        let requests=0;
        await page.route('**/api/**',async route=>{
          const request=route.request(),url=new URL(request.url());
          if(url.origin!==review.origin || request.method()!=='GET' || url.pathname!==spec.endpoint) return route.fallback();
          if(spec.state==='busy'&&spec.name==='collection'&&++requests===1) return route.fallback();
          reachedResolve();
          if(spec.state==='busy') {await gate;return route.continue();}
          if(spec.state==='failed') return route.fulfill({status:503,json:{error:'Synthetic review: this page is temporarily unavailable.',reason:'database'}});
          const response=await route.fetch({maxRedirects:0});
          assert(response.ok(),'Empty-state adapter requires an ordinary successful read');
          return route.fulfill({response,json:empty(await response.json(),spec.name)});
        });
        result.reached=reached;
      }
      await page.goto(review.pageUrl(spec.route,spec.theme),{waitUntil:'domcontentloaded'});
      if(spec.root200) await page.evaluate(()=>{document.documentElement.style.fontSize='200%';});
      if(spec.state==='busy'&&spec.name==='collection') {
        await page.waitForSelector(spec.ready);
        await page.locator('.col-filter-q input').fill('Opt');
      }
      if(result.reached) {await Promise.race([result.reached,new Promise((_,reject)=>setTimeout(()=>reject(new Error('State endpoint was not requested')),12000))]);delete result.reached;}
      if(spec.state==='failed') await page.locator('#main .box-crit:visible,#main .load-failed:visible,#main [role=alert]:visible')
        .first().waitFor({state:'visible',timeout:15000});
      else if(spec.state!=='busy') await page.waitForSelector(spec.ready,{timeout:15000});
      if(spec.name==='settings') for(const selector of ['#sim-workers','#night-target','.postage-shop','#pricing-minimum-condition','#settings-member-id'])
        await page.waitForSelector(selector,{timeout:15000});
      await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(250);
      if(spec.name==='settings'&&['failed','busy'].includes(spec.state)) {
        await page.locator('#settings-maintenance').evaluate(node=>{
          scrollTo(0,Math.max(0,scrollY+node.getBoundingClientRect().top-80));
        });
      }
      result.metrics=await measure(page);
      if(spec.name==='settings'&&spec.state==='populated') {
        const hints=result.metrics.samples['.field-hint'],labels=result.metrics.samples['.field > span:not(.field-hint)'];
        assert(hints.length&&hints.every(row=>row.fontWeight==='400'),'Settings helper copy inherited label emphasis');
        assert(labels.length&&labels.every(row=>row.fontWeight==='600'),'Settings labels lost their hierarchy');
        result.settingsLayout=await settingsLayout(page);
        const layout=result.settingsLayout;
        assert.equal(layout.width,spec.width,'Settings expanded the layout viewport');
        assert(layout.scrollWidth<=layout.clientWidth+1,'Settings makes the document scroll horizontally');
        assert(layout.rows.every(row=>row.left>=-1&&row.right<=layout.clientWidth+1),'Settings content extends beyond the viewport');
        assert(layout.rows.every(row=>row.left>=row.panelLeft-1&&row.right<=row.panelRight+1),'Settings controls extend beyond their panel');
        assert(layout.controls>0&&!layout.horizontalScroll&&layout.focusFailures===0,'Settings controls need horizontal scrolling to receive focus');
      }
      result.png=`${spec.name}-${spec.state}-${spec.width}-${spec.theme}${spec.root200?'-root200':''}.png`;
      await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
      const forecast=page.locator('.col-forecast-details');
      if(spec.state==='populated'&&await forecast.count()) {
        assert.equal(await forecast.getAttribute('open'),null);
        await forecast.locator(':scope > summary').click();
        assert.equal(await forecast.getAttribute('open'),'');
        assert(await forecast.getByText(/does not predict final occupancy/).isVisible(),'Conditional assumptions are inaccessible');
        result.forecastPng=`${spec.name}-${spec.width}-${spec.theme}-forecast.png`;
        await page.screenshot({path:path.join(review.out,result.forecastPng),fullPage:false,animations:'disabled'});
        await forecast.locator(':scope > summary').click();
        assert.equal(await forecast.getAttribute('open'),null);
        result.forecastDisclosure=true;
      }
      if(spec.name==='tokens'&&spec.state==='populated') {
        await page.locator('#tok-search').fill('Dog');
        await page.reload({waitUntil:'domcontentloaded'});
        await page.waitForSelector('#tok-search');
        assert.equal(await page.locator('#tok-search').inputValue(),'Dog','Token search preference was lost on reload');
        result.persistence={tokenSearchReload:true};
      }
      if(spec.state==='failed') for(const e of result.http_errors) if(e.status===503 && new URL(e.url,review.origin).pathname===spec.endpoint) e.category='expected_failure_state';
      assert.equal(result.page_errors.length,0,'Uncaught page error');
      assert(!result.http_errors.some(e=>e.category==='unexpected_http_error'),'Unexpected HTTP failure');
      // Overflow is retained as a diagnosis, never hidden by a harness CSS override.
      result.status='captured';
    } catch(error) {delete result.reached;result.error=review.safeText(error.message);}
    finally {if(release)release();if(context)await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(r=>r.status!=='captured').length,0,'Page-family capture failed');
});
