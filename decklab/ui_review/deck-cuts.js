'use strict';
// Cached EDHREC and actual Commander draft controls over the isolated fixture. No saves or runs.
const path=require('node:path');
const assert=require('node:assert/strict');
const {run}=require('./common.js');
const ID='commander/woodland-council';

run('deck-cuts',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic cached public EDHREC data with real Cuts GET/draft-preview POST, disclosure, local Considering move and Undo. No fetch, deck save or Forge run.';
  for(const mode of ['saved','outsider','draft','move','saved-move'])for(const theme of ['light','dark'])
    for(const width of (review.options.smoke?[393]:[393,820,1440])){
      const spec={mode,theme,width,height:900,coarse:width<1000};
      const result={spec,status:'failed',page_errors:[],http_errors:[],console_errors:[],requests:[]};let context;
      try{
        review.select(mode==='outsider'?'user2':'matt');context=await review.context(spec);const page=await context.newPage();
        review.observe(page,result.page_errors,result.http_errors);
        page.on('console',message=>{if(message.type()==='error')result.console_errors.push(review.safeText(message.text()));});
        page.on('request',request=>{const url=new URL(request.url());if(url.pathname.startsWith('/api/'))result.requests.push({path:url.pathname,method:request.method(),view:url.searchParams.get('view')});});
        const editing=['draft','move'].includes(mode);
        const before=mode!=='outsider'?await review.readFixture(context,`/api/deck/edit?id=${ID}`):null;
        await page.goto(review.pageUrl(editing?`/#/edit?id=${ID}&v=target`:`/#/deck?id=${ID}&tab=cards`,theme),{waitUntil:'domcontentloaded'});
        if(editing){
          const copies=page.getByRole('textbox',{name:'Copies of Forest',exact:true});await copies.waitFor({state:'visible'});await copies.fill('93');await copies.dispatchEvent('input');await copies.blur();
          await page.locator('.editor-cuts-link').waitFor();assert((await page.locator('.edit-bar').innerText()).includes('1 over 100'));
          result.barPng=`${mode}-bar-${width}-${theme}.png`;await page.screenshot({path:path.join(review.out,result.barPng),fullPage:false,animations:'disabled'});
          await page.locator('.editor-cuts-link').click();
        }else await page.getByRole('button',{name:'Review cuts…',exact:true}).click();
        const dialog=page.locator('dialog.sheet[open]').last();
        await dialog.getByRole('heading',{name:'On EDHREC\'s page, lowest inclusion first',exact:true}).waitFor();
        await dialog.getByRole('heading',{name:"Not on EDHREC's page for this commander",exact:true}).waitFor();
        assert((await dialog.innerText()).includes('fetched 2000-01-01'));assert(!result.requests.some(row=>row.path==='/api/deck/edhrec'&&row.view!=='cuts'));
        const row=dialog.locator('.edhrec-cut').filter({hasText:'Beast Whisperer'}).first();await row.locator('summary').click();
        if(mode==='outsider')assert.equal(await dialog.getByText('Move to Considering',{exact:true}).count(),0);
        else assert.equal(await row.getByText('Move to Considering',{exact:true}).count(),1);
        result.metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
          headings:[...document.querySelectorAll('dialog[open] h3')].map(node=>node.innerText)}));
        assert.equal(result.metrics.overflow,false);result.png=`${mode}-${width}-${theme}.png`;
        await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
        if(['move','saved-move'].includes(mode)){
          if(mode==='move')await row.getByRole('button',{name:'Move to Considering',exact:true}).click();
          else{
            await row.getByRole('link',{name:'Move to Considering',exact:true}).click();
            const confirm=page.locator('dialog.sheet[open]').last();await confirm.getByRole('heading',{name:'Move to Considering?',exact:true}).waitFor();
            await confirm.getByRole('button',{name:'Move to Considering',exact:true}).click();
          }
          const moved=page.locator('.editor-considering-row').filter({hasText:'Beast Whisperer'});await moved.waitFor({state:'visible'});
          assert.equal(await page.locator('.edit-row').filter({hasText:'Beast Whisperer'}).count(),0);
          result.movedPng=`${mode}-moved-${width}-${theme}.png`;await moved.scrollIntoViewIfNeeded();
          await page.screenshot({path:path.join(review.out,result.movedPng),fullPage:false,animations:'disabled'});
          await page.keyboard.press('Control+z');await moved.waitFor({state:'detached'});
          assert.equal(await page.locator('.edit-row').filter({hasText:'Beast Whisperer'}).count(),1);
        }
        if(before){const after=await review.readFixture(context,`/api/deck/edit?id=${ID}`);assert.equal(after.sha256,before.sha256,'Cut review wrote the saved deck');}
        assert(!result.requests.some(row=>!['GET','HEAD'].includes(row.method)&&!['/api/deck/check','/api/deck/cuts','/api/visit','/api/errors/report'].includes(row.path)));
        assert.equal(result.page_errors.length,0);assert.equal(result.console_errors.length,0);
        assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));result.status='captured';
      }catch(error){result.error=review.safeText(error.message);}
      finally{if(context)await context.close();review.report.results.push(result);review.save();}review.checkCancelled();
    }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Cuts capture failed');
});
