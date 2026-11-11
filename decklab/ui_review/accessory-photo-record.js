'use strict';
// Invented audit rows and a repository icon stand in for one current photo; all POSTs are intercepted.
const path=require('node:path');
const fs=require('node:fs');
const crypto=require('node:crypto');
const assert=require('node:assert/strict');
const {run}=require('./common.js');
const bytes=fs.readFileSync(path.join(__dirname,'..','web','icons','icon-192.png'));
const digest=crypto.createHash('sha256').update(bytes).digest('hex');
const FIELDS=['owner','kind','quantity','brand','name','colour','notes','link','image_source','capacity','crop'];

function preview(mode){
  const current={id:'synthetic-photo',kind:'deck_box',owner:'matt',brand:'Current brand',name:'Current synthetic record',colour:'blue',notes:'Current literal note',
    link:'https://example.com/current',image_source:'https://example.com/current.png',quantity:'2',capacity:'100',image:'synthetic-photo.png',crop:'0,0,0.5,1'};
  const restored=mode==='text-only'?{...current,notes:'Earlier <img src=x> literal note',capacity:'60',crop:'0.1,0.1,0.8,0.8'}:
    {...current,kind:'sleeves',owner:'shared',name:'Restored synthetic sleeves',notes:'Earlier <img src=x> literal note',quantity:mode==='zero'?'0':'125',capacity:'',crop:'0.1,0.1,0.8,0.8'};
  return {available:true,id:42,expect:'a'.repeat(64),kind:'accessory',action:'accessory_photo_record_update',label:current.name,current,restored,
    fields:FIELDS.filter(field=>current[field]!==restored[field]).map(field=>({field,before:current[field],after:restored[field]})),
    photo:{name:current.image,size:bytes.length,sha256:digest,version:'e'.repeat(8)},photo_confirmation_required:true,record_confirmation_required:true};
}

run('accessory-photo-record',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic compound crop/fact review, repository icon as current-photo bytes, exact metadata/stream/decode guards and dual acknowledgements. Every save reply is intercepted; no actual inventory, audit, photo or deck writes.';
  for(const mode of ['ready','text-only','zero','stale'])for(const theme of ['light','dark'])
    for(const width of (review.options.smoke?[393]:[393,820,1440])){
      const spec={mode,theme,width,height:900,coarse:width<1000};
      const result={spec,status:'failed',page_errors:[],http_errors:[],console_errors:[],requests:[]};let context;
      try{
        review.select('matt');context=await review.context(spec);const page=await context.newPage(),p=preview(mode);
        review.observe(page,result.page_errors,result.http_errors);
        page.on('console',message=>{if(message.type()==='error')result.console_errors.push(review.safeText(message.text()));});
        page.on('request',request=>{const url=new URL(request.url());if(url.pathname.startsWith('/api/'))result.requests.push({path:url.pathname,method:request.method()});});
        await page.route('**/api/activity**',route=>new URL(route.request().url()).pathname!=='/api/activity'?route.fallback():route.fulfill({status:200,json:{changes:[{id:42,at:'2000-01-05T01:00:00+00:00',actor:'matt',actor_name:'Matt',source:'web',via:'home',message:'',reason:null,
          headline:'Matt corrected a synthetic accessory record and crop',kinds:['accessories'],link:null,undo:{review:true,kind:'accessory'},
          rows:[{table:'accessory',op:'UPDATE',summary:'Synthetic recorded correction',before:{},after:{}}]}],next:null,everything:false,cards:{}}}));
        await page.route('**/api/activity/accessory-undo?*',route=>route.fulfill({status:200,json:p}));
        await page.route('**/accessory-img/synthetic-photo.png?*',route=>route.fulfill({status:200,headers:{'Content-Type':'image/png','Content-Length':String(bytes.length),'ETag':'"'+digest+'"'},body:bytes}));
        let posts=0;
        await page.route('**/api/activity/accessory-undo',route=>{
          posts++;assert.equal(route.request().method(),'POST');const body=route.request().postDataJSON();
          assert.equal(body.id,42);assert.equal(body.expect,p.expect);assert.equal(body.confirm_record,true);assert.equal(body.confirm_photo,true);
          return route.fulfill({status:200,json:mode==='stale'?{saved:false,error:'Synthetic unconfirmed outcome'}:
            {saved:true,source_id:42,expect:p.expect,kind:'accessory',action:p.action,restored:p.restored,photo:p.photo,sha256:'b'.repeat(64),revision:'4321',summary:'Restored the recorded correction and crop on the current photo.'}});
        });
        await page.goto(review.pageUrl('/#/activity',theme),{waitUntil:'domcontentloaded'});
        await page.getByRole('button',{name:'Review undo',exact:true}).click();
        const dialog=page.locator('dialog[open]');await dialog.getByRole('heading',{name:'Restored record and crop',exact:true}).waitFor();
        const checks=dialog.getByRole('checkbox');assert.equal(await checks.count(),2);
        assert.equal(await checks.nth(0).isChecked(),false);assert.equal(await checks.nth(1).isChecked(),false);
        await checks.nth(0).waitFor({state:'visible'});await page.waitForFunction(()=>!document.querySelector('dialog[open] input[type=checkbox]')?.disabled);
        assert.equal(await dialog.locator('img').count(),2);
        const save=dialog.getByRole('button',{name:'Save Undo',exact:true});assert.equal(await save.isDisabled(),true);
        await checks.nth(1).check();assert.equal(await save.isDisabled(),true);await checks.nth(0).check();assert.equal(await save.isDisabled(),false);
        await checks.nth(0).uncheck();assert.equal(await save.isDisabled(),true);await checks.nth(0).check();
        result.review_png=`review-${mode}-${width}-${theme}.png`;
        await dialog.getByRole('heading',{name:'Restored record and crop',exact:true}).scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(review.out,result.review_png),fullPage:false,animations:'disabled'});
        await save.click();
        if(mode==='stale')await dialog.getByRole('button',{name:'Reload Activity',exact:true}).waitFor();else await dialog.getByRole('button',{name:'Done',exact:true}).waitFor();
        assert.equal(posts,1);result.png=`saved-${mode}-${width}-${theme}.png`;
        await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
        result.metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
          dialogOverflow:[...document.querySelectorAll('dialog[open]')].some(node=>node.scrollWidth>node.clientWidth+1)}));
        assert.equal(result.metrics.overflow,false);assert.equal(result.metrics.dialogOverflow,false);
        assert.equal(result.page_errors.length,0);assert.equal(result.console_errors.length,0);assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));
        assert(!result.requests.some(row=>!['GET','HEAD'].includes(row.method)&&!['/api/activity/accessory-undo','/api/visit','/api/errors/report'].includes(row.path)));
        result.status='captured';
      }catch(error){result.error=review.safeText(error.message);}
      finally{if(context)await context.close();review.report.results.push(result);review.save();}review.checkCancelled();
    }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Compound accessory photo review failed');
});
