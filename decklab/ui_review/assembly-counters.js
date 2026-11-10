'use strict';
// Optional packing reminders, using a synthetic GET adapter with no inventory or tick writes.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

function payload(state) {
  const decks = ['Woodland reminders', 'A second deck with a long name'].map((title, index) => ({
    id:`casual/reminders-${index}`, title, version:'target', steps:[], basics:[], returns:[],
    sleeves:null, kit:null, sleeves_need:null, tokens:{needs:[], copies:[], unlisted:[]},
    completion:{status:'building',already_built:false,editable:false},
  }));
  const source = deck => ({id:deck.id,title:deck.title,sideboard_only:false});
  const counters = {note:'An estimate of kinds only. Coverage is checked across all chosen decks together.',
    details:'Read from the cards; an estimate of kinds only. Deck Lab never says how many a game needs.',
    needs:[{key:'+1/+1',name:'+1/+1 counters',group:'permanent',decks:decks.map(source),
      cover:{state:'named',words:'You have +1/+1 counters'}},
    {key:'poison',name:'Poison counters',group:'player',decks:decks.map(source),
      cover:{state:'generic',words:'A die or generic counter stands in'}},
    {key:'d20',name:'d20',group:'die',decks:decks.map(source),
      cover:{state:'none',words:'No d20 recorded'}}]};
  if(state!=='ready') {
    for(const need of counters.needs) delete need.cover;
    if(state==='failed') counters.error="Counters and dice couldn't be checked; the rest of the plan still works.";
    else counters.owned={ready:false,words:"Dice and counters can't be recorded yet: the database needs its migration 0020."};
  }
  return {decks, choices:decks.map(deck=>({id:deck.id,title:deck.title,versions:['target'],status:'building'})),
    counters, tokens:[], token_plan:[], token_problems:[], sleeve_notes:[], rows:[], cards:{},
    ready:true, counts_confirmed:true, unresolved:[], warnings:[], totals:{waiting:0,missing:0},
    completion:{can_mark_built:false,reason:'Synthetic read-only plan.',decks:[]},
    note:'Synthetic packing plan. No card or inventory changes are made.'};
}

run('assembly-counters', async review => {
  review.report.results=[];
  review.report.scope='Read-only counter-kind reminders; synthetic GET adapters, all changes disabled. No real-device acceptance.';
  const specs=[];
  for(const theme of ['light','dark']) for(const state of ['ready','failed','unmigrated'])
    for(const width of (review.options.smoke?[393,820]:[393,820,1440]))
      specs.push({theme,state,width,height:width===820?1106:900,coarse:width<1000});
  for(const spec of specs) {
    const result={spec,status:'failed',page_errors:[],http_errors:[]};
    let context;
    try {
      review.select('matt');
      context=await review.context(spec);
      const page=await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      await page.route('**/api/assembly?*',route=>route.fulfill({status:200,json:payload(spec.state)}));
      await page.goto(review.pageUrl('/#/assembly',spec.theme),{waitUntil:'domcontentloaded'});
      await page.waitForSelector('.pack-deck');
      const step=page.locator('.pack-deck').first().locator('.pack-step.is-optional').first();
      if(await step.getAttribute('open')===null) await step.locator(':scope > summary').click();
      const block=step.locator('.pack-counters');
      await block.waitFor({state:'visible',timeout:10000});
      await page.evaluate(()=>document.fonts.ready);
      await block.evaluate(node=>scrollTo(0,Math.max(0,scrollY+node.getBoundingClientRect().top-90)));
      result.metrics=await block.evaluate(node=>({
        text:node.innerText, count:node.querySelectorAll('li').length,
        interactive:node.querySelectorAll('button,input').length,
        overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
        viewport:{width:innerWidth,height:innerHeight},
        rows:[...node.querySelectorAll('li')].map(row=>({text:row.innerText,width:row.getBoundingClientRect().width})),
      }));
      assert.equal(result.metrics.count,3);
      assert.equal(result.metrics.interactive,0);
      assert(result.metrics.text.includes('Used by Woodland reminders, A second deck with a long name'));
      assert.equal(await page.locator('.pack-tick,.pack-tick-optional').count(),0);
      if(spec.state==='ready') assert.equal(await block.locator('.dice-cover').count(),3);
      else assert.equal(await block.locator('.dice-cover').count(),0);
      assert.equal(result.metrics.overflow,false,'Packing reminders overflow the viewport');
      result.png=`${spec.state}-${spec.width}-${spec.theme}.png`;
      await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
      assert.equal(result.page_errors.length,0,'Uncaught page error');
      assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'),'Unexpected HTTP failure');
      result.status='captured';
    } catch(error) {result.error=review.safeText(error.message);}
    finally {if(context)await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Assembly counter capture failed');
});
