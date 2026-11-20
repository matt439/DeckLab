'use strict';
// Static first-use guidance and empty Collection, with synthetic adapters and no actual writes.
const path = require('node:path');
const fs = require('node:fs/promises');
const assert = require('node:assert/strict');
const {run} = require('./common.js');

run('first-use', async review => {
  review.report.results = [];
  review.report.scope = 'Synthetic empty collection and static terminology/import guidance. No actual profiles, cards, imports or device acceptance.';
  for (const mode of ['help','empty','import','pile']) for (const theme of ['light','dark'])
    for (const width of (review.options.smoke ? [393] : [393,820,1440])) {
      const spec = {mode,theme,width,height:900,coarse:width<1000};
      const result = {spec,status:'failed',page_errors:[],http_errors:[],console_errors:[]};
      let context;
      try {
        review.select('matt');context = await review.context({...spec,acceptDownloads:mode==='pile'});const page = await context.newPage();
        review.observe(page,result.page_errors,result.http_errors);
        page.on('console',message=>{if(message.type()==='error')result.console_errors.push(review.safeText(message.text()));});
        await page.route('**/api/collection?*',route=>route.fulfill({status:200,json:{
          space:'home',editable:true,total:0,page:1,pages:1,cards:[],sha256:'a'.repeat(64),warnings:[],
          filters:{},spaces:[{id:'home',name:'Home'}]}}));
        const target = mode==='help' ? '/#/help' : '/#/collection';
        await page.goto(review.pageUrl(target,theme),{waitUntil:'domcontentloaded'});
        if(mode==='help') {
          await page.getByRole('heading',{name:'What these words mean',exact:true}).waitFor();
          assert((await page.locator('#main').innerText()).includes('Tables out of date'));
        } else {
          await page.getByRole('button',{name:'Add one card',exact:true}).waitFor();
          for(const name of ['Import cards','Add a precon','Scan cards'])
            assert.equal(await page.getByRole('button',{name,exact:true}).count(),1);
          if(mode==='pile') {
            await page.getByRole('button',{name:'Start with physical cards',exact:true}).click();
            let sheet=page.locator('dialog[open]').last();
            await sheet.getByRole('button',{name:'Enter a pile of loose cards',exact:true}).waitFor();
            assert((await sheet.innerText()).includes("You don't need a spreadsheet"));
            assert.equal(await sheet.getByRole('button',{name:'Add an unchanged precon',exact:true}).count(),1);
            await page.screenshot({path:path.join(review.out,`guide-${width}-${theme}.png`),fullPage:false});
            await sheet.getByRole('button',{name:'Enter a pile of loose cards',exact:true}).click();
            sheet=page.locator('dialog[open]').last();
            await sheet.getByRole('button',{name:'Find its printings',exact:true}).waitFor();
            await page.route('**/api/printings?*', route=>route.fulfill({status:200,json:{
              name:'Llanowar Elves',printings:Array.from({length:10},(_,index)=>({set:'fdn',
                collector_number:String(218+index),set_name:'Foundations',finishes:['nonfoil']}))}}));
            await sheet.getByPlaceholder("The card's exact name").fill('Llanowar Elves');
            await sheet.getByRole('button',{name:'Find its printings',exact:true}).click();
            await sheet.getByText('Other printings…',{exact:true}).click();
            await sheet.getByRole('button',{name:'Llanowar Elves (FDN 227) · Foundations',exact:true}).click();
            const download=page.waitForEvent('download');
            await sheet.getByRole('button',{name:'Download pending batch',exact:true}).click();
            const file=await download;
            assert(file.suggestedFilename().startsWith('pending-collection-'));
            const savedText=await fs.readFile(await file.path(),'utf8');
            assert(savedText.includes('Llanowar Elves'));
            assert(savedText.includes('fdn'));
            assert(!savedText.includes('data:image'));
            assert.equal(await file.failure(),null);
            assert((await sheet.innerText()).includes('Nothing was added now'));
            for(const dismiss of [()=>page.keyboard.press('Escape'),()=>page.evaluate(()=>history.back()),
              ()=>sheet.getByRole('button',{name:'Close',exact:true}).click()]) {
              await dismiss();
              await sheet.getByRole('heading',{name:'Discard this batch?'}).waitFor();
              assert((await sheet.innerText()).includes('1 card'));
              await sheet.getByRole('button',{name:'Keep scanning',exact:true}).click();
              await sheet.getByRole('button',{name:'Review 1 card',exact:true}).waitFor();
            }
            await sheet.getByRole('button',{name:'Cancel',exact:true}).click();
            await sheet.getByRole('button',{name:'Discard batch',exact:true}).click();
            await page.getByRole('button',{name:'Start with physical cards',exact:true}).click();
            await page.locator('dialog[open]').last().locator('[data-action=cancel]').click();
            assert.equal(await page.locator('dialog[open]').count(),0);
          }
          if(mode==='import') {
            await page.getByRole('button',{name:'Import cards',exact:true}).click();
            const sheet = page.locator('dialog[open]').last();
            await sheet.getByText('Where to export, or start a CSV',{exact:true}).click();
            await sheet.getByRole('button',{name:'Download blank collection CSV',exact:true}).waitFor();
            assert((await sheet.innerText()).includes('name-only list'));
          }
        }
        await page.evaluate(()=>document.fonts.ready);
        result.overflow = await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth);
        assert.equal(result.overflow,false);
        result.png = `${mode}-${width}-${theme}.png`;
        await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
        assert.equal(result.page_errors.length,0);assert.equal(result.console_errors.length,0);
        assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));
        result.status='captured';
      } catch(error) {result.error=review.safeText(error.message);}
      finally {if(context)await context.close();review.report.results.push(result);review.save();}
      review.checkCancelled();
    }
  assert.equal(review.report.results.filter(row=>row.status!=='captured').length,0,'First-use capture failed');
});
