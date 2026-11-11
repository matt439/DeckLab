'use strict';
// Card links and private printing facts over the isolated fixture's real read-only API routes.
const path=require('node:path');
const assert=require('node:assert/strict');
const {run}=require('./common.js');

run('card-viewer-details',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic fixture card lookup/copy reads; actual card modal, native disclosure and outbound anchor properties. External navigation and all writes are excluded.';
  for(const mode of ['commander','casual','foreign','overpage'])for(const theme of ['light','dark'])
    for(const width of (review.options.smoke?[393]:[393,820,1440])){
      const spec={mode,theme,width,height:900,coarse:width<1000};
      const result={spec,status:'failed',page_errors:[],http_errors:[],console_errors:[],reads:[]};let context;
      try{
        review.select('matt');context=await review.context(spec);const page=await context.newPage();
        review.observe(page,result.page_errors,result.http_errors);
        page.on('console',message=>{if(message.type()==='error')result.console_errors.push(review.safeText(message.text()));});
        page.on('request',request=>{const url=new URL(request.url());if(url.pathname.startsWith('/api/'))result.reads.push(url.pathname);});
        await page.route('**/img/**',route=>route.fulfill({status:200,contentType:'image/svg+xml',
          body:'<svg xmlns="http://www.w3.org/2000/svg" width="488" height="680"><rect width="488" height="680" fill="#2d603e"/><text x="30" y="80" fill="white" font-size="30">Synthetic card image</text></svg>'}));
        const q=new URLSearchParams({name:'Llanowar Elves',set:'sft',number:'1'});
        if(mode==='commander')q.set('commander','1');if(mode==='foreign')q.set('space','user2');
        const address=`#/card?${q}`;
        if(mode==='overpage'){
          await page.goto(review.pageUrl('/#/help',theme),{waitUntil:'domcontentloaded'});
          await page.getByRole('heading',{name:'What these words mean',exact:true}).waitFor();
          await page.evaluate(hash=>{location.hash=hash;},address);
        }else await page.goto(review.pageUrl('/'+address,theme),{waitUntil:'domcontentloaded'});
        const dialog=page.locator('dialog.viewer[open]');await dialog.waitFor({state:'visible'});
        const text=dialog.getByRole('button',{name:'Text',exact:true});if(await text.isVisible())await text.click();
        const scryfall=dialog.getByRole('link',{name:'Open on Scryfall',exact:true});await scryfall.waitFor({state:'visible'});
        assert.equal(await scryfall.getAttribute('href'),'https://scryfall.com/card/sft/1');
        assert.equal(await scryfall.getAttribute('target'),'_blank');assert.equal(await scryfall.getAttribute('rel'),'noopener noreferrer');
        assert.equal(await dialog.getByRole('link',{name:'Open on EDHREC',exact:true}).count(),mode==='commander'?1:0);
        assert((await dialog.getByRole('link',{name:'Card link',exact:true}).getAttribute('href')).includes('set=sft'));
        assert(!result.reads.includes('/api/cards/copies'),'Copies read before disclosure');
        const copies=dialog.locator('.viewer-copies');
        if(mode==='foreign')assert.equal(await copies.count(),0);
        else{
          await copies.locator('summary').click();await copies.getByText('Location not recorded',{exact:true}).first().waitFor();
          assert((await copies.innerText()).includes('SFT 1'));assert(result.reads.includes('/api/cards/copies'));
        }
        result.metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
          copies:document.querySelector('.viewer-copies')?.innerText||null,underlay:document.querySelector('#main h1')?.innerText}));
        assert.equal(result.metrics.overflow,false);if(mode==='overpage')assert.equal(result.metrics.underlay,'What these words mean');
        result.png=`${mode}-${width}-${theme}.png`;await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
        await dialog.getByRole('button',{name:'Close',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('dialog.viewer[open]'));
        await page.waitForFunction(expected=>location.hash===expected,mode==='overpage'?'#/help':'#/library');
        assert.equal(result.page_errors.length,0);assert.equal(result.console_errors.length,0);
        assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));result.status='captured';
      }catch(error){result.error=review.safeText(error.message);}
      finally{if(context)await context.close();review.report.results.push(result);review.save();}review.checkCancelled();
    }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Card viewer detail capture failed');
});
