'use strict';
// Invented complete product-kit changes and intercepted save receipts; never writes actual product data.
const path=require('node:path');
const assert=require('node:assert/strict');
const {run}=require('./common.js');

function preview(mode){
  const rows=[{file:'alpha.csv',title:'Synthetic intact Alpha product',current:{sleeves:'shared-sleeves-b',deck_box:'shared-box-b'},restored:{sleeves:'shared-sleeves-a',deck_box:'shared-box-a'}}];
  if(mode!=='one')rows.push({file:'beta.csv',title:'Synthetic intact Beta product with a longer title',current:{sleeves:'shared-sleeves-a',deck_box:'shared-box-a'},restored:{sleeves:'shared-sleeves-b',deck_box:'shared-box-b'}});
  else rows[0].restored={sleeves:'',deck_box:''};
  return {available:true,id:42,expect:'a'.repeat(64),kind:'product_kit',action:'product_kit_restore',label:'Complete product-kit change',row_count:rows.length,rows,kit_confirmation_required:true};
}

run('product-kit-undo',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic complete product-only kit review, clear/move and unconfirmed-reply adapters over actual Activity/modal controls. All POSTs intercepted, no product/deck/inventory writes.';
  for(const mode of ['one','move','unconfirmed'])for(const theme of ['light','dark'])for(const width of (review.options.smoke?[393]:[393,820,1440])){
    const spec={mode,theme,width,height:900,coarse:width<1000};
    const result={spec,status:'failed',page_errors:[],http_errors:[],console_errors:[],requests:[]};let context;
    try{
      review.select('matt');context=await review.context(spec);const page=await context.newPage(),p=preview(mode);
      review.observe(page,result.page_errors,result.http_errors);
      page.on('console',message=>{if(message.type()==='error')result.console_errors.push(review.safeText(message.text()));});
      page.on('request',request=>{const url=new URL(request.url());if(url.pathname.startsWith('/api/'))result.requests.push({path:url.pathname,method:request.method()});});
      await page.route('**/api/activity**',route=>new URL(route.request().url()).pathname!=='/api/activity'?route.fallback():route.fulfill({status:200,json:{changes:[
        {id:42,at:'2000-01-05T01:00:00+00:00',actor:'matt',actor_name:'Matt',source:'web',via:'home',message:'',reason:null,headline:'Matt moved synthetic shared product kit',kinds:['products'],link:null,
          undo:{review:true,kind:'product_kit'},rows:[{table:'product_status',op:'UPDATE',summary:'Synthetic product kit change',before:{},after:{}}]}],next:null,everything:false,cards:{}}}));
      await page.route('**/api/activity/product-kit-undo?*',route=>route.fulfill({status:200,json:p}));
      let posts=0;
      await page.route('**/api/activity/product-kit-undo',route=>{
        posts++;assert.equal(route.request().method(),'POST');const body=route.request().postDataJSON();assert.equal(body.id,42);assert.equal(body.expect,p.expect);assert.equal(body.confirm_kit,true);
        return route.fulfill({status:200,json:mode==='unconfirmed'?{saved:false,error:'Synthetic unconfirmed outcome'}:
          {saved:true,source_id:42,expect:p.expect,kind:p.kind,action:p.action,row_count:p.row_count,rows:p.rows,sha256:'b'.repeat(64),revision:'4321',summary:'Restored every reviewed product-kit assignment.'}});
      });
      await page.goto(review.pageUrl('/#/activity',theme),{waitUntil:'domcontentloaded'});await page.getByRole('button',{name:'Review undo',exact:true}).click();
      const dialog=page.locator('dialog[open]');await dialog.getByRole('heading',{name:p.rows[0].title,exact:true}).waitFor();
      const consent=dialog.getByRole('checkbox'),save=dialog.getByRole('button',{name:'Save Undo',exact:true});assert.equal(await consent.count(),1);assert.equal(await consent.isChecked(),false);assert.equal(await save.isDisabled(),true);
      await consent.check();assert.equal(await save.isDisabled(),false);await consent.uncheck();assert.equal(await save.isDisabled(),true);await consent.check();
      result.review_png=`review-${mode}-${width}-${theme}.png`;await page.screenshot({path:path.join(review.out,result.review_png),fullPage:false,animations:'disabled'});
      await save.click();if(mode==='unconfirmed')await dialog.getByRole('button',{name:'Reload Activity',exact:true}).waitFor();else await dialog.getByRole('button',{name:'Done',exact:true}).waitFor();assert.equal(posts,1);
      result.png=`saved-${mode}-${width}-${theme}.png`;await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
      result.metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
        dialogOverflow:[...document.querySelectorAll('dialog[open]')].some(node=>node.scrollWidth>node.clientWidth+1)}));assert.equal(result.metrics.overflow,false);assert.equal(result.metrics.dialogOverflow,false);
      assert.equal(result.page_errors.length,0);assert.equal(result.console_errors.length,0);assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));
      assert(!result.requests.some(row=>!['GET','HEAD'].includes(row.method)&&!['/api/activity/product-kit-undo','/api/visit','/api/errors/report'].includes(row.path)));result.status='captured';
    }catch(error){result.error=review.safeText(error.message);}
    finally{if(context)await context.close();review.report.results.push(result);review.save();}review.checkCancelled();
  }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Product-kit Undo capture failed');
});
