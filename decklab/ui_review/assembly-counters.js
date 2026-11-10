'use strict';
// Optional packing reminders, using a synthetic GET adapter with no inventory or tick writes.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

function payload(state, takealong=false) {
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
  const data={decks, choices:decks.map(deck=>({id:deck.id,title:deck.title,versions:['target'],status:'building'})),
    counters, tokens:[], token_plan:[], token_problems:[], sleeve_notes:[], rows:[], cards:{},
    ready:true, counts_confirmed:true, unresolved:[], warnings:[], totals:{waiting:0,missing:0},
    completion:{can_mark_built:false,reason:'Synthetic read-only plan.',decks:[]},
    note:'Synthetic packing plan. No card or inventory changes are made.'};
  if(takealong) {
    for(const deck of decks) deck.completion={status:'built',already_built:true,editable:false};
    for(const choice of data.choices) choice.status='built';
    data.take_along={available:true,
      decks:decks.map((deck,index)=>({task:`take-along|deck|${deck.id}`,context:String(index+1).repeat(64),title:deck.title,
        lines:index?['Sleeves and deck box details are unavailable in this view.','Token cards: Packing not recorded']:
          ['Deck box: Synthetic green box','Sleeves: Shared sleeves','Token cards: 2 Dog / Beast (TFDN) 12']})),
      counters:counters.needs.map((need,index)=>({task:`take-along|counter|${need.key}`,context:String(index+3).repeat(64),
        title:need.name,lines:['Used by Woodland reminders, A second deck with a long name',
          ...(need.cover?[need.cover.words]:[])]})),
      counter_note:counters.note,counter_error:counters.error||null,
      playmats:['Synthetic own playmat','Shared playmat'],playmats_error:null};
  }
  return data;
}

run('assembly-counters', async review => {
  review.report.results=[];
  review.report.scope='Counter-kind and built-deck take-along reminders; synthetic read and in-memory optional tick adapters only. Print CSS inspected with a stubbed system print call. No real-device acceptance.';
  const specs=[];
  for(const theme of ['light','dark']) for(const state of ['ready','failed','unmigrated'])
    for(const width of (review.options.smoke?[393,820]:[393,820,1440]))
      specs.push({theme,state,width,height:width===820?1106:900,coarse:width<1000});
  for(const theme of ['light','dark']) for(const state of ['ready','failed'])
    for(const width of (review.options.smoke?[393,820]:[393,820,1440]))
      specs.push({theme,state,width,height:width===820?1106:900,coarse:width<1000,takealong:true});
  for(const spec of specs) {
    const result={spec,status:'failed',page_errors:[],http_errors:[]};
    let context;
    try {
      review.select('matt');
      context=await review.context(spec);
      const page=await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      await page.route('**/api/assembly?*',route=>route.fulfill({status:200,json:payload(spec.state,spec.takealong)}));
      const checked=new Set();result.syntheticTickPatches=[];
      await page.route('**/api/assembly/ticks',async route=>{
        assert.equal(route.request().method(),'POST');
        const body=route.request().postDataJSON();
        assert(body.ids.every(id=>id.includes('take-along|')),'Unexpected packing task in take-along adapter');
        for(const change of body.changes||[]) {
          assert(body.ids.includes(change.id));
          if(change.done)checked.add(change.id);else checked.delete(change.id);
          result.syntheticTickPatches.push({done:change.done});
        }
        return route.fulfill({status:200,json:{ticks:body.ids.filter(id=>checked.has(id))}});
      });
      if(spec.takealong) await page.addInitScript(()=>{
        window.reviewPrintCalls=0;window.print=()=>window.reviewPrintCalls++;
      });
      await page.goto(review.pageUrl('/#/assembly',spec.theme),{waitUntil:'domcontentloaded'});
      await page.waitForSelector('.pack-deck');
      if(spec.takealong) {
        const section=page.locator('.pack-takealong');
        await section.waitFor({state:'visible'});
        const ticks=section.locator('input[type=checkbox]');
        assert.equal(await ticks.count(),5);
        await ticks.first().check();
        await page.waitForFunction(()=>packingProgressView.progress.pending.size===0);
        assert.equal(await ticks.first().isChecked(),true);
        assert.equal(result.syntheticTickPatches.length,1);
        await section.evaluate(node=>scrollTo(0,Math.max(0,scrollY+node.getBoundingClientRect().top-90)));
        result.metrics=await section.evaluate(node=>({text:node.innerText,
          overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth}));
        assert.equal(result.metrics.overflow,false,'Take-along list overflows the viewport');
        assert(result.metrics.text.includes('2 Dog / Beast (TFDN) 12'));
        assert(result.metrics.text.includes('Sleeves and deck box details are unavailable'));
        result.png=`takealong-${spec.state}-${spec.width}-${spec.theme}.png`;
        await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
        await section.getByRole('button',{name:'Print take-along list',exact:true}).click();
        assert.equal(await page.evaluate(()=>window.reviewPrintCalls),1);
        await page.emulateMedia({media:'print'});
        const print=page.locator('.pack-takealong-print');
        await print.waitFor({state:'visible'});
        assert((await print.innerText()).includes('[x] Woodland reminders'));
        assert.equal(await print.locator('input,img,button').count(),0);
        result.printPng=`takealong-print-${spec.state}-${spec.width}-${spec.theme}.png`;
        await page.screenshot({path:path.join(review.out,result.printPng),fullPage:true,animations:'disabled'});
        await page.emulateMedia({media:'screen'});
        await page.evaluate(()=>window.dispatchEvent(new Event('afterprint')));
        assert.equal(await print.count(),0);
        assert.equal(result.page_errors.length,0,'Uncaught page error');
        assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'),'Unexpected HTTP failure');
        result.status='captured';
        continue;
      }
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
