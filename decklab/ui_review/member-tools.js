'use strict';
const path = require('node:path');
const assert = require('node:assert/strict');
const {run} = require('./common.js');

run('member-tools',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic own-space needs and personal-copy menu. No actual zip, collection, prices, records, queue or member export.';
  for(const mode of ['ready','unavailable'])for(const theme of ['light','dark'])
    for(const width of (review.options.smoke?[393]:[393,820,1440])){
      const spec={mode,theme,width,height:900,coarse:width<1000};
      const result={spec,status:'failed',page_errors:[],http_errors:[],console_errors:[]};let context;
      try{
        review.select('user2');context=await review.context(spec);const page=await context.newPage();
        review.observe(page,result.page_errors,result.http_errors);
        page.on('console',message=>{if(message.type()==='error')result.console_errors.push(review.safeText(message.text()));});
        let attempts=0;
        await page.route('**/api/space/needed?*',route=>{
          attempts++;
          const ready=mode==='ready'||attempts>1;
          const decks=[{id:'user2/casual/own-plan',title:'Own plan'}];
          return route.fulfill({status:200,json:ready
            ? {ready,decks,rows:[{name:'Synthetic long-named needed creature',quantity:3,decks}]}
            : {ready,decks,rows:[],check_collection:true,reason:'Your collection needs checking before missing cards can be counted.'}});
        });
        await page.goto(review.pageUrl('/#/library',theme),{waitUntil:'domcontentloaded'});
        await page.getByRole('button',{name:'Find and buy cards',exact:true}).click();
        await page.getByRole('button',{name:'Use recorded collection',exact:true}).click();
        const sheet=page.locator('dialog[open]').last();
        if(mode==='ready')await sheet.getByRole('button',{name:'Copy combined shortages',exact:true}).waitFor();
        else {
          await sheet.getByText('Your collection needs checking before missing cards can be counted.',{exact:true}).waitFor();
          assert.equal(await sheet.getByRole('link',{name:'Check my collection'}).getAttribute('href'),'#/collection?space=user2&view=rows');
          assert.equal(await sheet.getByRole('button',{name:'Copy combined shortages',exact:true}).count(),0);
        }
        await page.evaluate(()=>document.fonts.ready);
        result.overflow=await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth);
        assert.equal(result.overflow,false);
        result.png=`${mode}-${width}-${theme}.png`;
        await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
        if(mode==='unavailable'){
          await sheet.getByRole('button',{name:'Try again'}).click();
          await sheet.getByRole('button',{name:'Copy combined shortages'}).waitFor();
          assert.equal(attempts,2);
        }
        assert.equal(result.page_errors.length,0);assert.equal(result.console_errors.length,0);
        assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));
        result.status='captured';
      }catch(error){result.error=review.safeText(error.message);}
      finally{if(context)await context.close();review.report.results.push(result);review.save();}
      review.checkCancelled();
    }
  assert.equal(review.report.results.filter(row=>row.status!=='captured').length,0,'Member-tools capture failed');
});
