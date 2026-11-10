'use strict';
// Read-only baseline Compare rendering and its two entrypoints over explicit synthetic adapters.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');
const ID='casual/safari-fixture', FILE='ReviewPrecon_TST';

function side(baseline=false,version='target'){
  const card=(name,type,mv)=>({name,mana_cost:mv?`{${mv}}`:'',cmc:mv,type_line:type,colors:['G'],color_identity:['G'],
    roles:[],oracle_text:'Synthetic review card.',img:null,img_small:null});
  const line=(name,qty,type,mv)=>({name,qty,set:null,number:null,finish:'nonfoil',card:card(name,type,mv)});
  const one=baseline?1:3,forest=baseline?38:36;
  const sections={Commander:[line('Synthetic leader',1,'Legendary Creature',3)],
    Deck:[line('Synthetic elf',one,'Creature',1),line('Synthetic creature',60,'Creature',baseline?3:2),line('Forest',forest,'Basic Land',0)]};
  const bucket=Array.from({length:8},(_,index)=>({mv:index===7?'7+':String(index),creatures:0,noncreatures:0,total:0,cards:[]}));
  Object.assign(bucket[1],{creatures:one,total:one});Object.assign(bucket[baseline?3:2],{creatures:60,total:60});
  return {summary:{id:ID,title:baseline?'Synthetic earlier list':'Synthetic current deck',kind:'commander',format:'Commander',colors:['G']},
    version,versions:['target','owned'],sections,stats_unknown:false,stats_kind:'commander',warnings:[],stats:{
      curve:{average_mv:baseline?181/61:123/63,creatures:60+one,noncreatures:0,buckets:bucket,outside:[],x_spells:null},
      lands:{effective:forest,recommended:37,verdict:'ok'},colours:{colours:[{colours:'G',name:'green',land_sources:forest,
        ok:true,hardest:{have:forest,needed:20}}]},types:[{type:'creature',count:61+one,cards:[]},{type:'land',count:forest,cards:[]}],
      roles:[{role:'ramp',count:one,cards:[]}],commander:{bracket:{label:baseline?'3 – Upgraded':'2 – Core'}},unresolved:[],warnings:[]}};
}
function baseline(mode,version='target'){
  const value=side(true,version);
  value.comparison={kind:'revision',revision:3,date:'2026-10-06T12:00:00+00:00',
    bracket_note:"Bracket judged using today's card data and Commander lists."};
  if(mode==='precon'||mode==='picker'){
    value.summary.id=null;value.summary.title='Synthetic published precon with a long release name';value.versions=['target'];
    value.comparison={kind:'precon',file:FILE,label:`Published precon: ${value.summary.title}`,bracket_note:value.comparison.bracket_note};
  }
  if(mode==='unknown'){
    value.stats=null;value.stats_unknown=true;value.stats_note='Stats are unknown because a card is not recognized.';
    value.sections.Deck.push({name:'Unindexed synthetic spell',qty:1,set:null,number:null,finish:'nonfoil',card:null});
  }
  return value;
}

run('compare-baselines',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic intrinsic-only current/revision/precon adapters; real Compare/History/picker controls and charts. No inventory/result endpoints, trial/deck creation or real card acceptance.';
  const specs=[];
  for(const mode of ['revision','precon','unknown'])for(const theme of ['light','dark'])
    for(const width of (review.options.smoke?[393]:[393,820,1440]))specs.push({mode,theme,width,height:900,coarse:width<1000});
  for(const mode of ['history','picker'])for(const theme of ['light','dark'])
    for(const width of (review.options.smoke?[393]:[393,820]))specs.push({mode,theme,width,height:900,coarse:true});
  for(const spec of specs){
    let context;
    const result={spec,status:'failed',page_errors:[],http_errors:[],console_errors:[],reads:[]};
    try{
      review.select('matt');context=await review.context(spec);const page=await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      page.on('console',message=>{if(message.type()==='error')result.console_errors.push(review.safeText(message.text()));});
      page.on('request',request=>{const url=new URL(request.url());if(url.pathname.startsWith('/api/'))result.reads.push({path:url.pathname,method:request.method()});});
      await page.route('**/api/compare/deck?*',route=>route.fulfill({status:200,json:side(false,new URL(route.request().url()).searchParams.get('version')||'target')}));
      await page.route('**/api/deck/revision?*',route=>{
        const url=new URL(route.request().url());assert.equal(url.searchParams.get('stats'),'1');
        return route.fulfill({status:200,json:baseline(spec.mode,url.searchParams.get('version')||'target')});
      });
      await page.route('**/api/compare/precon?*',route=>route.fulfill({status:200,json:baseline('precon')}));
      await page.route('**/api/deck/history?*',route=>route.fulfill({status:200,json:{id:ID,title:'Synthetic current deck',
        versions:['target','owned'],retired:false,may_save:false,truncated:false,sha256:'a'.repeat(64),revisions:[
          {revision:3,date:'2026-10-06T12:00:00+00:00',op:'M',author:'Matt',subject:null,
            change:{kind:'cards',cards:[],fields:[],lists:['target'],size:{target:100,owned:100},more:0}}]}}));
      await page.route('**/api/decks',route=>route.fulfill({status:200,json:{decks:[{...side().summary,versions:['target','owned']}]}}));
      await page.route('**/api/precons?*',route=>route.fulfill({status:200,json:{decks:[{file:FILE,name:'Synthetic published precon with a long release name'}],more:false}}));
      const q=new URLSearchParams({a:ID});
      if(spec.mode==='precon'||spec.mode==='picker')q.set('bp',FILE);else{q.set('b',ID);q.set('br','3');}
      await page.goto(review.pageUrl(spec.mode==='history'?`/#/history?id=${encodeURIComponent(ID)}`:`/#/compare?${q}`,spec.theme),{waitUntil:'domcontentloaded'});
      if(spec.mode==='history'){
        await page.locator('.history-open').first().click();
        const sheet=page.locator('dialog[open]').last();
        await sheet.getByRole('link',{name:'Compare stats with the deck now',exact:true}).click();
      }
      await page.waitForSelector('#h-compare-deltas');
      if(spec.mode==='picker'){
        await page.locator('.page-head .menu-wrap > button').click();
        await page.getByRole('menuitem',{name:'Compare with another deck…',exact:true}).click();
        await page.getByRole('button',{name:'Compare with a published precon…',exact:true}).click();
        const sheet=page.locator('dialog[open]').last();
        await sheet.getByRole('searchbox',{name:'Find a published precon',exact:true}).fill('Synthetic');
        const link=sheet.getByRole('link',{name:'Synthetic published precon with a long release name',exact:true});
        await link.waitFor({state:'visible'});
        result.pickerPng=`picker-search-${spec.width}-${spec.theme}.png`;
        await page.screenshot({path:path.join(review.out,result.pickerPng),fullPage:false,animations:'disabled'});
        await link.click();await page.locator('dialog[open]').waitFor({state:'detached'});
        await page.waitForSelector('#h-compare-deltas');
      }
      await page.evaluate(()=>document.fonts.ready);
      assert.equal(await page.locator('#h-compare-shared,#h-compare-h2h').count(),0);
      assert(!result.reads.some(row=>['/api/compare/shared','/api/play','/api/deck'].includes(row.path)),'Baseline fetched pool/results readers');
      const labels=await page.locator('.compare-title').allTextContents();
      assert(labels[1].includes(spec.mode==='precon'||spec.mode==='picker'?'Published precon:':'Revision 3,'));
      result.metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
        labels:[...document.querySelectorAll('.compare-title')].map(node=>node.innerText),
        headings:[...document.querySelectorAll('#main h2')].map(node=>node.innerText)}));
      assert.equal(result.metrics.overflow,false,'Baseline comparison expands the viewport');
      if(spec.mode==='unknown')assert((await page.locator('#main').innerText()).includes('Stat changes are unknown'));
      else assert((await page.locator('#main').innerText()).includes("today's lists"));
      result.png=`${spec.mode}-${spec.width}-${spec.theme}.png`;
      await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
      await page.locator('#h-compare-deltas').scrollIntoViewIfNeeded();
      result.deltaPng=`${spec.mode}-deltas-${spec.width}-${spec.theme}.png`;
      await page.screenshot({path:path.join(review.out,result.deltaPng),fullPage:false,animations:'disabled'});
      assert.equal(result.page_errors.length,0);assert.equal(result.console_errors.length,0);
      assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));
      result.status='captured';
    }catch(error){result.error=review.safeText(error.message);}
    finally{if(context)await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Baseline comparison capture failed');
});
