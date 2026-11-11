'use strict';
// Native checkbox and explicit stale-review flow over intercepted synthetic responses only.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

const DECK = {file:'SyntheticBonus_TST',name:'Synthetic woodland precon',code:'tst',set_name:'Synthetic set',type:'Theme Deck'};
const DROP = {file:'SyntheticDrop_SLD',name:'Synthetic cards-only drop',code:'sld',set_name:'Synthetic set',type:'Secret Lair Drop'};
const COLLECTION = 'a'.repeat(64), SOURCE = 'c'.repeat(64);
const NEXT_COLLECTION = 'b'.repeat(64), NEXT_SOURCE = 'd'.repeat(64);

function preview(fresh = false, cardsOnly = false) {
  return {deck:cardsOnly?DROP:DECK,kind:'casual',title:cardsOnly?DROP.name:DECK.name,cards_only:cardsOnly,exists:null,ready:true,editable:true,
    sha256:fresh?NEXT_COLLECTION:COLLECTION,counts:{Deck:4},adds:{rows:2,cards:fresh?5:6},
    dropped_basics:0,left_out:{},tokens:[],problems:[],deck_problems:[],
    lists:{Deck:[{name:'Llanowar Elves',qty:4,set:'fdn',number:'227',finish:'nonfoil',card:null}]},
    notes:['Also in the box: a 2-card sample pack (random, not added).'],
    bonus_import:{source_sha256:fresh?NEXT_SOURCE:SOURCE,rows:[
      {source_row:1,name:'Pick Your Poison',set:'mkm',number:'170',finish:'foil',qty:2,
        words:'Pick Your Poison (MKM 170, foil)',owned:fresh?2:0,selected:!fresh,problem:null},
      {source_row:2,name:'Llanowar Elves',set:'fdn',number:'227',finish:'nonfoil',qty:1,
        words:'Llanowar Elves (FDN 227)',owned:fresh?0:2,selected:fresh,problem:null},
    ]}};
}

async function snapshot(page, block) {
  return block.evaluate(node => ({text:node.innerText,
    documentOverflow:document.documentElement.scrollWidth>document.documentElement.clientWidth+1,
    viewport:{width:innerWidth,height:innerHeight},
    controls:[...node.querySelectorAll('input')].map(input=>{
      const bounds=input.getBoundingClientRect(),label=input.closest('label'),box=label.getBoundingClientRect();
      return {checked:input.checked,disabled:input.disabled,type:input.type,label:label.innerText,
        input:{x:bounds.x,y:bounds.y,width:bounds.width,height:bounds.height},
        target:{x:box.x,y:box.y,width:box.width,height:box.height}};
    }),
  }));
}

run('precon-bonus', async review => {
  review.report.scope='Twelve native precon/drop reviews with synthetic intercepted GET/POST replies; no inventory, deck, database or source fetch is saved.';
  review.report.results=[];
  for(const mode of ['precon','drop']) for(const theme of ['light','dark']) for(const width of [393,820,1440]) {
    const spec={mode,theme,width,height:width===820?1106:900,coarse:width<1000},cardsOnly=mode==='drop',deck=cardsOnly?DROP:DECK;
    const result={spec,status:'failed',page_errors:[],http_errors:[],synthetic_requests:[]};
    let context;
    try {
      review.select('matt');
      context=await review.context(spec);
      const page=await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      let previews=0,adds=0;
      await page.route('**/api/precons**',async route=>{
        const request=route.request(),url=new URL(request.url());
        assert.equal(url.origin,review.origin,'Only this run\'s fixture origin may be intercepted');
        if(url.pathname==='/api/precons') {
          assert.equal(request.method(),'GET');
          assert.equal(url.searchParams.get('products'),'1');
          return route.fulfill({status:200,json:{date:'2026-11-10',decks:[deck],more:false}});
        }
        if(url.pathname==='/api/precons/preview') {
          assert.equal(request.method(),'GET');assert.equal(url.searchParams.get('file'),deck.file);
          previews++;
          return route.fulfill({status:200,json:preview(previews>1,cardsOnly)});
        }
        assert.equal(url.pathname,'/api/precons/add');assert.equal(request.method(),'POST');
        const body=request.postDataJSON();
        result.synthetic_requests.push(body);adds++;
        assert.deepEqual(Object.keys(body).sort(),['profile','space','file','title','sha256','bonus_choices','bonus_source_sha256'].sort());
        assert.equal(body.profile,'matt');assert.equal(body.space,'home');assert.equal(body.file,deck.file);
        assert.equal(body.title,cardsOnly?DROP.name:'Synthetic reviewed title');
        assert.equal(body.sha256,adds===1?COLLECTION:NEXT_COLLECTION);
        assert.equal(body.bonus_source_sha256,adds===1?SOURCE:NEXT_SOURCE);
        assert.deepEqual(body.bonus_choices,adds===1?[2]:[1]);
        assert(adds<=2,'Unexpected automatic or repeated add');
        // Even explicit clicks receive synthetic refusals, so no inventory write or route change occurs.
        if(adds===2 && cardsOnly) return route.fulfill({status:200,json:{cards_only:true,deck:null,
          collection:{added:{cards:6,rows:2}},stale_tables:[],trials:[]}});
        return route.fulfill({status:409,json:adds===1
          ? {error:'Synthetic source changed. Preview the precon again.',bonus_conflict:true}
          : {error:'Synthetic title is already in use.',conflict:'casual/safari-fixture'}});
      });
      await page.goto(review.pageUrl('/#/collection?open=precon',theme),{waitUntil:'domcontentloaded'});
      if(cardsOnly) assert((await page.locator('.precon-pick').first().innerText()).includes('Cards only'));
      await page.locator('.precon-pick').first().click();
      const block=page.locator('.precon-bonus');
      await block.waitFor({state:'visible',timeout:10000});
      const dialog=page.locator('dialog[open]').last(),checks=block.locator('input[type="checkbox"]');
      await page.evaluate(()=>document.fonts.ready);
      assert.equal(await checks.count(),2);assert(await checks.nth(0).isChecked());assert(!(await checks.nth(1).isChecked()));
      assert((await block.innerText()).includes('2 already owned'));
      assert((await dialog.innerText()).includes('a 2-card sample pack (random, not added)'));
      await block.scrollIntoViewIfNeeded();
      result.initial=await snapshot(page,block);
      assert(!result.initial.documentOverflow,'The review overflows the document');
      result.initialPng=`${mode}-${width}-${theme}-initial.png`;
      await page.screenshot({path:path.join(review.out,result.initialPng),fullPage:false,animations:'disabled'});

      if(cardsOnly) {
        assert.equal(await dialog.locator('.precon-title input').count(),0);
        assert((await dialog.innerText()).includes('Cards only; no deck is created'));
      } else await dialog.locator('.precon-title input').fill('Synthetic reviewed title');
      await checks.nth(0).uncheck();await checks.nth(1).check();
      assert((await dialog.locator('.precon-summary').innerText()).includes('5 cards go into the collection'));
      assert.equal(adds,0,'Changing a local checkbox must not write');
      await dialog.getByRole('button',{name:`Add ${deck.name}`,exact:true}).click();
      const refresh=dialog.getByRole('button',{name:'Preview again',exact:true});
      await refresh.waitFor({state:'visible'});
      assert.equal(adds,1);assert.equal(previews,1,'A conflict must not automatically refresh the preview');
      assert.equal(await dialog.getByRole('button',{name:`Add ${deck.name}`,exact:true}).count(),0);
      assert((await dialog.innerText()).includes('Nothing was added. Preview again'));
      assert(await checks.nth(0).isDisabled());assert(await checks.nth(1).isDisabled());
      result.stalePng=`${mode}-${width}-${theme}-stale.png`;
      await page.screenshot({path:path.join(review.out,result.stalePng),fullPage:false,animations:'disabled'});

      await refresh.click();
      await page.waitForFunction(()=>document.querySelector('.precon-bonus input')?.checked===false
        && document.querySelectorAll('.precon-bonus input')[1]?.checked===true
        && !document.querySelector('.precon-bonus input')?.disabled);
      assert.equal(previews,2);assert.equal(adds,1);
      if(!cardsOnly) assert.equal(await dialog.locator('.precon-title input').inputValue(),'Synthetic reviewed title');
      result.refreshed=await snapshot(page,block);
      assert(!result.refreshed.documentOverflow);
      result.refreshedPng=`${mode}-${width}-${theme}-refreshed.png`;
      await block.scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(review.out,result.refreshedPng),fullPage:false,animations:'disabled'});
      await checks.nth(0).check();await checks.nth(1).uncheck();
      await dialog.getByRole('button',{name:`Add ${deck.name}`,exact:true}).click();
      if(cardsOnly) {
        await dialog.getByText(/6 cards from Synthetic cards-only drop added/).waitFor();
        assert((await dialog.innerText()).includes('No deck was created'));
        assert.equal(await dialog.getByRole('button',{name:`Add ${deck.name}`,exact:true}).count(),0);
        assert(await page.evaluate(()=>state.saved===null));
        result.savedPng=`${mode}-${width}-${theme}-saved.png`;
        await page.screenshot({path:path.join(review.out,result.savedPng),fullPage:false,animations:'disabled'});
      } else await dialog.getByText('Synthetic title is already in use.',{exact:true}).waitFor();
      assert.equal(adds,2);assert.equal(previews,2);
      for(const error of result.http_errors) if(error.status===409
          && new URL(error.url,review.origin).pathname==='/api/precons/add') error.category='expected_synthetic_refusal';
      assert.equal(result.page_errors.length,0,'Uncaught page error');
      assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'),'Unexpected HTTP failure');
      result.reads=previews;result.status='captured';
    } catch(error) {result.error=review.safeText(error.message);}
    finally {if(context)await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Precon bonus review failed');
});
