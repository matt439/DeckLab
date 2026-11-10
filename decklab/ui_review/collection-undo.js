'use strict';
// Invented audit rows only. Every POST reply is intercepted before the fixture server.
const path=require('node:path');
const assert=require('node:assert/strict');
const {run}=require('./common.js');

function preview(){
  const old={name:'Llanowar Elves',set:'fdn',collector_number:'227',finish:'nonfoil',quantity:2,condition:'NM',language:'en',notes:'Historical <img src=x> literal note'};
  const current={...old,set:'m19',collector_number:'314',quantity:3,notes:'Current synthetic record'};
  const key=row=>({set:row.set,collector_number:row.collector_number,finish:row.finish});
  const label=row=>`${row.name} (${row.set.toUpperCase()} ${row.collector_number}, ${row.finish})`;
  return {available:true,id:42,expect:'a'.repeat(64),kind:'collection',space:'home',action:'collection_change_restore',
    label:'Complete collection change (2 rows)',row_count:2,reason_required:true,physical_confirmation_required:true,
    rows:[{key:key(old),label:label(old),current:null,restored:old},{key:key(current),label:label(current),current,restored:null}],
    location_transfer:{from:key(current),to:key(old),location:'Row 4'}};
}

run('collection-undo',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic complete collection recovery, exact nullable rows, current-location transfer and explicit reason/physical confirmation. All save replies are intercepted; no actual inventory, audit or deck writes.';
  for(const mode of ['review','unconfirmed'])for(const theme of ['light','dark'])
    for(const width of (review.options.smoke?[393]:[393,820,1440])){
      const spec={mode,theme,width,height:900,coarse:width<1000};
      const result={spec,status:'failed',page_errors:[],http_errors:[],console_errors:[],requests:[]};let context;
      try{
        review.select('matt');context=await review.context(spec);const page=await context.newPage(),p=preview();
        review.observe(page,result.page_errors,result.http_errors);
        page.on('console',message=>{if(message.type()==='error')result.console_errors.push(review.safeText(message.text()));});
        page.on('request',request=>{const url=new URL(request.url());if(url.pathname.startsWith('/api/'))result.requests.push({path:url.pathname,method:request.method()});});
        await page.route('**/api/activity**',route=>new URL(route.request().url()).pathname!=='/api/activity'?route.fallback():route.fulfill({status:200,json:{changes:[
          {id:42,at:'2000-01-05T01:00:00+00:00',actor:'matt',actor_name:'Matt',source:'web',via:'home',message:'',reason:null,
            headline:'Matt corrected a synthetic collection printing',kinds:['collection'],link:null,undo:{review:true},
            rows:[{table:'collection_card',op:'DELETE',summary:'Synthetic complete row change',before:{},after:null}]}],next:null,everything:false,cards:{}}}));
        await page.route('**/api/activity/undo?*',route=>route.fulfill({status:200,json:p}));
        let posts=0;
        await page.route('**/api/activity/undo',route=>{
          posts++;assert.equal(route.request().method(),'POST');
          assert.deepEqual(route.request().postDataJSON(),{profile:'matt',id:42,expect:p.expect,reason:'Synthetic wrong printing',confirm_owned:true});
          return route.fulfill({status:200,json:{saved:false,error:'Synthetic unconfirmed outcome'}});
        });
        await page.goto(review.pageUrl('/#/activity',theme),{waitUntil:'domcontentloaded'});
        await page.getByRole('button',{name:'Review undo',exact:true}).click();
        const dialog=page.locator('dialog[open]');await dialog.getByText('No row',{exact:true}).first().waitFor();
        assert.equal(await dialog.locator('.activity-undo-batch-row').count(),2);
        assert.equal(await dialog.locator('img').count(),0);
        const save=dialog.getByRole('button',{name:'Save Undo',exact:true});assert.equal(await save.isDisabled(),true);
        const check=dialog.getByRole('checkbox');assert.equal(await check.count(),1);assert.equal(await check.isChecked(),false);
        await dialog.getByRole('textbox').fill('Synthetic wrong printing');assert.equal(await save.isDisabled(),true);
        await check.check();assert.equal(await save.isEnabled(),true);
        if(mode==='unconfirmed'){
          await save.click();await dialog.getByRole('button',{name:'Reload Activity',exact:true}).waitFor();
          assert.equal(await dialog.getByRole('button',{name:'Save Undo',exact:true}).count(),0);assert.equal(posts,1);
        }else assert.equal(posts,0);
        result.png=`collection-undo-${mode}-${width}-${theme}.png`;
        await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
        result.metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
          dialogOverflow:[...document.querySelectorAll('dialog[open]')].some(node=>node.scrollWidth>node.clientWidth+1)}));
        assert.equal(result.metrics.overflow,false);assert.equal(result.metrics.dialogOverflow,false);
        assert.equal(result.page_errors.length,0);assert.equal(result.console_errors.length,0);
        assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));
        assert(!result.requests.some(row=>!['GET','HEAD'].includes(row.method)&&!['/api/activity/undo','/api/visit','/api/errors/report'].includes(row.path)));
        result.status='captured';
      }catch(error){result.error=review.safeText(error.message);}
      finally{if(context)await context.close();review.report.results.push(result);review.save();}review.checkCancelled();
    }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Collection recovery review failed');
});
