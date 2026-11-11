'use strict';
// Static first-use guidance and empty Collection, with synthetic adapters and no actual writes.
const path = require('node:path');
const assert = require('node:assert/strict');
const {run} = require('./common.js');

run('first-use', async review => {
  review.report.results = [];
  review.report.scope = 'Synthetic empty collection and static terminology/import guidance. No actual profiles, cards, imports or device acceptance.';
  for (const mode of ['help','empty','import']) for (const theme of ['light','dark'])
    for (const width of (review.options.smoke ? [393] : [393,820,1440])) {
      const spec = {mode,theme,width,height:900,coarse:width<1000};
      const result = {spec,status:'failed',page_errors:[],http_errors:[],console_errors:[]};
      let context;
      try {
        review.select('matt');context = await review.context(spec);const page = await context.newPage();
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
