'use strict';
// Rendered synthetic checks for readiness and publication hierarchy. No saves or live records.
const path = require('node:path');
const assert = require('node:assert/strict');
const {run} = require('./common.js');
const row = (id, title, extra = {}) => ({id, title, status:'built', built:true, version:'target',
  target_bracket:2, minimum:1, deciding:[], below_range:false, played_known:true, last_played:null,
  stand_ins:[], box_checked_on:null, ...extra});
const lineup = {available:true, basis:'The household aims for Bracket 2.',
  night:{name:'Synthetic Commander night',published_min:1,published_max:2}, groups:{
    fits:[row('commander/ready','Synthetic ready deck',{box_checked_on:'2026-11-10'}),
      row('commander/unfinished','Synthetic deck needing packing',{status:'idea',built:false,
        stand_ins:[{for:'Synthetic rare card',using:'Synthetic spare card',qty:1}]})],
    above:[row('commander/above','Synthetic above-aim deck',{minimum:3,
      deciding:[{reason:'Game Changer',cards:['Synthetic deciding card']}]})],
    unknown:[row('commander/unknown','Synthetic unknown deck',{minimum:null,unknown_reason:'Card checks unavailable.'})]}};

run('ui-priorities', async review => {
  review.report.results=[];
  review.report.scope='Synthetic Commander line-up, publication confirmation, Storage editor/preview and Shopping capacity renderer; no real data or writes. CSS/font/touch observations are not physical-device acceptance.';
  for (const theme of ['light','dark']) for (const width of review.options.smoke ? [393] : [393,1280]) {
    const spec={width,height:900,theme,coarse:width<1000};
    let context;
    const result={spec,status:'failed',page_errors:[],http_errors:[],screenshots:[]};
    try {
      review.select('matt'); context=await review.context(spec); const page=await context.newPage();
      page.setDefaultTimeout(10000);
      review.observe(page,result.page_errors,result.http_errors);
      await page.route('**/api/commander-night/lineup',route=>route.fulfill({status:200,json:lineup}));
      await page.route('**/api/visibility',route=>route.request().method()==='GET'
        ? route.fulfill({status:200,json:{switches:[{owner:'home',thing:'decks',public:false}]}})
        : route.fallback());
      let failedPreview=false;
      await page.route('**/api/visibility/preview?*',route=>route.fulfill({status:200,json:failedPreview
        ? {available:false,message:'Synthetic preview unavailable.'}
        : {available:true,counts:{decks:3},mentions:[{title:'Synthetic purchase notes'}]}}));
      const capture=async name=>{
        await page.evaluate(()=>document.fonts.ready);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth),false,'Horizontal page overflow');
        const filename=`${name}-${width}-${theme}.png`;result.screenshots.push(filename);
        await page.screenshot({path:path.join(review.out,filename),fullPage:true,animations:'disabled'});
      };
      await page.goto(review.pageUrl('/#/play',theme),{waitUntil:'domcontentloaded'});
      await page.getByRole('button',{name:'Show the line-up',exact:true}).click();
      await page.getByRole('heading',{name:'Synthetic deck needing packing',exact:true}).waitFor();
      const card=page.locator('.commander-lineup-deck').filter({hasText:'Synthetic deck needing packing'});
      assert.equal(await card.locator('.commander-lineup-standins.note-warn').count(),1);
      assert.equal(await card.locator('.commander-lineup-box.note-warn').count(),1);
      await capture('lineup');
      await page.getByText('What the bracket check covers',{exact:true}).click();
      assert.equal(await page.locator('.commander-lineup-help').getAttribute('open'),'');
      await page.goto(review.pageUrl('/#/visibility',theme),{waitUntil:'domcontentloaded'});
      await page.locator('[data-public=true]').click();
      let dialog=page.locator('dialog[open]').last();
      await dialog.getByRole('button',{name:'Make public',exact:true}).waitFor();
      assert((await dialog.innerText()).includes('visitors on the home network'));
      assert((await dialog.innerText()).includes('Nothing becomes public on the internet'));
      await capture('public-preview');
      await dialog.getByRole('button',{name:'Keep private',exact:true}).click();
      await page.waitForFunction(()=>!document.querySelector('dialog[open]'));
      assert.equal(await page.locator('[data-public=false]').getAttribute('aria-pressed'),'true');
      failedPreview=true;
      await page.locator('[data-public=true]').click();
      dialog=page.locator('dialog[open]').last();
      await dialog.getByRole('button',{name:'Make public without preview',exact:true}).waitFor();
      assert.equal(await dialog.locator('.note-warn[role=alert]').count(),1);
      await capture('public-preview-unavailable');
      await page.keyboard.press('Escape');
      await page.waitForFunction(()=>!document.querySelector('dialog[open]'));
      assert.equal(await page.locator('[data-public=false]').getAttribute('aria-pressed'),'true');
      await page.goto(review.pageUrl('/#/visibility',theme),{waitUntil:'domcontentloaded'});
      await page.locator('[data-public=true]').waitFor({state:'visible'});
      // Exercise the actual renderers with explicitly invented answers; these calls never invoke a server write.
      await page.evaluate(() => {
        const box={id:'box',name:'Synthetic storage box',kind:'box',capacity:100,sections:['Row 1','Row 2'],order:'name',sleeved:false};
        const sheet=openSheet('Synthetic storage setup',{wide:true});
        const ctx={cv:{space:'home'},sheet,busy:false,review:null,keys:0,profile:'matt',here:()=>!sheet.closed};
        ctx.message=el('div');ctx.edit=el('div',{class:'col-form storage-setup'});
        ctx.reviewBox=el('div',{class:'storage-review',hidden:true});
        sheet.body.append(ctx.message,ctx.edit,ctx.reviewBox);
        storageTake(ctx,{ready:true,can_edit:true,revision:1,storage:{default:'box',containers:[box]}});
        window.syntheticStorageContext=ctx;
        window.syntheticStorageAnswer={storage:{default:'box',containers:[box]},
          now:{containers:[{...box,cards:80}],unplaced:0,elsewhere:0},
          after:{containers:[{...box,cards:140}],unplaced:4,elsewhere:9},
          moves:[{from:null,to:box.name,locations:2}],counts_error:null};
      });
      dialog=page.locator('dialog[open]').last();
      await dialog.locator('.storage-name').fill('Synthetic renamed box');
      assert.equal(await dialog.locator('.storage-container > fieldset > legend').innerText(),'Synthetic renamed box');
      assert.equal(await dialog.locator('select').last().locator('option:checked').innerText(),'Synthetic renamed box');
      assert.equal(await dialog.locator('.storage-options').getAttribute('open'),null);
      await dialog.getByLabel(/^Filing order/).selectOption('set');
      assert.equal(await page.evaluate(()=>storageRecord(syntheticStorageContext).containers[0].order),'set');
      await capture('storage-edit');
      await dialog.getByText('Kind, section contents and sleeves',{exact:true}).click();
      await dialog.locator('.storage-options select[id*=-kind-]').waitFor({state:'visible'});
      await capture('storage-options');
      await page.evaluate(()=>{
        const storage=storageRecord(syntheticStorageContext);
        syntheticStorageAnswer.storage=storage;
        syntheticStorageAnswer.after.containers[0]={...storage.containers[0],cards:140};
        syntheticStorageAnswer.moves[0].to=storage.containers[0].name;
        syntheticStorageContext.review=syntheticStorageAnswer;
        drawStorageReview(syntheticStorageContext);
      });
      await dialog.getByText('Before you save',{exact:true}).waitFor();
      assert((await dialog.locator('.storage-impact').innerText()).includes('40 cards over capacity'));
      assert((await dialog.locator('.storage-impact').innerText()).includes('4 cards'));
      assert((await dialog.locator('.storage-filing-order').innerText()).includes('Synthetic renamed box · By set and collector number'));
      assert.equal(await dialog.locator('.storage-comparison > li').count(),1);
      await capture('storage-impact');
      await dialog.getByRole('button',{name:'Back',exact:true}).click();
      assert.equal(await dialog.locator('.storage-name').inputValue(),'Synthetic renamed box');
      await page.evaluate(()=>{syntheticStorageContext.review={...syntheticStorageAnswer,counts_error:'Synthetic collection unavailable.'};drawStorageReview(syntheticStorageContext);});
      assert.equal(await dialog.locator('.storage-comparison').count(),0);
      assert((await dialog.locator('.storage-impact').innerText()).includes('counts are unavailable'));
      await capture('storage-unknown');
      await page.keyboard.press('Escape');
      await page.waitForFunction(()=>!document.querySelector('dialog[open]'));
      await page.evaluate(()=>{
        // This is a renderer-only fixture, not a claim about Shopping API/backend capacity computation.
        const node=shopStorageFill({data:{storage_fill:{status:'partial',default:'Synthetic box',
          unknown_sources:2,pending_products:1,tokens_excluded:true,containers:[
            {name:'Synthetic roomy binder',capacity:360,now:80,incoming:20,after:100},
            {name:'Synthetic overflowing box',capacity:100,now:80,incoming:60,after:140}]}}});
        if(!node)throw Error('Synthetic shopping capacity did not render');
        add(clear(document.querySelector('#main')),[pageHead({title:'Synthetic Shopping capacity'}),node]);
      });
      assert((await page.locator('.shop-storage-lines > li').first().innerText()).includes('40 cards over capacity'));
      assert((await page.locator('.shop-storage-incomplete').innerText()).includes('2 deliveries'));
      await capture('shopping-capacity');
      assert.equal(result.page_errors.length,0);
      assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));
      result.status='captured';
    } catch(error) {result.error=review.safeText(error.message);}
    finally {if(context)await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'UI priority checks failed');
});
