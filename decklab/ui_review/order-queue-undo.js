'use strict';
// Invented Activity replies over actual native controls; no application write reaches a route.
const path=require('node:path');
const assert=require('node:assert/strict');
const {run}=require('./common.js');

run('order-queue-undo',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic complete order/queue controller. Intercepted invented GET/POST replies only; no database, shop request, physical stock or actual order write.';
  for(const mode of ['added-cards','product-state'])for(const theme of ['light','dark'])for(const width of(review.options.smoke?[393]:[393,820,1440])){
    const spec={mode,theme,width,height:1000,coarse:width<1000},result={spec,status:'failed',page_errors:[],http_errors:[],route_errors:[],requests:[]};let context;
    try{
      review.select('matt');context=await review.context(spec);const page=await context.newPage();page.setDefaultTimeout(10000);review.observe(page,result.page_errors,result.http_errors);
      const product=mode==='product-state',orderId='2026-11-11-synthetic-order';let done=false;
      const row=quantity=>({name:'Llanowar Elves',set:'sft',collector_number:'1',finish:'nonfoil',quantity,for:'Synthetic deck',printing:'exact',
        listed_aud:'',listed_at:'',in_stock:'',checked:'',notes:'Synthetic queue intent',state:'ready',source:'',buy_under_aud:''});
      const current=row(product?'3':'1'),restored=row(product?'1':'3');
      const queue={available:true,id:42,expect:'c'.repeat(64),kind:'watchlist',space:'home',action:'watchlist_update',label:'Updates to 1 purchase-queue row',row_count:1,
        rows:[{label:'Llanowar Elves for Synthetic deck',watch_row_id:7,current,restored,fields:[{field:'quantity',before:current.quantity,after:restored.quantity}]}]};
      const card={name:'Llanowar Elves',set:'sft',collector_number:'1',finish:'nonfoil',quantity:product?'2':'3',condition:'',language:'',notes:'Synthetic recorded card facts'};
      if(product)Object.assign(card,{section:'extras',deck:'Synthetic deck',rarity:'common',in_play_boosters:'no'});
      const part={id:product?'product':'cards',kind:product?'product':'cards',status:product?'cancelled':'pending',received_on:'',checks:['Confirm the printing on arrival'],verified_checks:[],rows:[card]};
      if(product)Object.assign(part,{product:'synthetic-product',name:'Synthetic product',format:'Commander precon',product_status:'cancelled'});
      const order={id:orderId,seller:'Synthetic shop',ordered_on:'2026-11-11',sources:['Synthetic offline source'],notes:'Synthetic delivery note',audit_notes:'',components:[part]};
      const next=product?JSON.parse(JSON.stringify(order)):null;if(next){next.components[0].status='pending';next.components[0].product_status='preordered';}
      const tables={written:[],needs_attention:false};
      const preview={available:true,id:42,expect:'a'.repeat(64),kind:'order_queue',space:'home',action:'order_queue_restore',label:'recorded order and its purchase-queue intent',
        order_id:orderId,source_action:product?'state':'added',row_count:product?5:4,queue_count:1,current:order,restored:next,queue,reason_required:true,tables};
      const saved={saved:true,source_id:42,expect:preview.expect,kind:'order_queue',space:'home',action:preview.action,order_id:orderId,order:next,
        queue:{saved:true,source_id:42,expect:queue.expect,kind:'watchlist',space:'home',action:queue.action,row_count:1,restored_rows:[{watch_row_id:7,row:restored}],
          sha256:'b'.repeat(64),revision:'3',summary:'Synthetic queue restored'},revision:'3',summary:'Synthetic order and queue restored',tables};
      const reply=(route,body)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
      await page.route('**/api/activity**',async route=>{try{
        const request=route.request(),url=new URL(request.url());
        if(url.pathname==='/api/activity')return reply(route,{changes:[{id:42,at:'2026-11-11T08:00:00+10:00',actor:'matt',actor_name:'Matt',source:'web',via:'tunnel',
          message:'Synthetic recorded order change',reason:null,headline:'Matt changed a synthetic order',kinds:['orders'],rows:[],...(done?{}:{undo:{review:true,kind:'order_queue'}})}],next:null,everything:false,cards:{}});
        assert.equal(url.pathname,'/api/activity/undo');if(request.method()==='GET')return reply(route,preview);
        assert.equal(request.method(),'POST');const body=request.postDataJSON();result.requests.push(body);
        assert.deepEqual(body,{profile:'matt',id:42,expect:preview.expect,reason:'Synthetic recorded correction'});done=true;return reply(route,saved);
      }catch(error){result.route_errors.push(review.safeText(error.message));return reply(route,{available:false,id:42,reason:'Synthetic adapter assertion failed'});}});
      await page.goto(review.pageUrl('/#/activity',theme),{waitUntil:'domcontentloaded'});await page.getByRole('button',{name:'Review undo',exact:true}).click();
      const dialog=page.locator('dialog[open]').last(),save=dialog.getByRole('button',{name:'Save Undo',exact:true});await save.waitFor({state:'visible'});
      assert.equal(await save.isDisabled(),true);assert.equal(result.requests.length,0);assert.equal(await dialog.getByRole('checkbox').count(),0);
      await dialog.locator('details summary').first().click();assert((await dialog.innerText()).includes('Synthetic recorded card facts'));
      assert((await dialog.innerText()).includes('Condition: Not recorded'));
      if(product){assert((await dialog.innerText()).includes('Rarity: common'));assert((await dialog.innerText()).includes('In play boosters: no'));}
      result.review_png=`review-${mode}-${width}-${theme}.png`;await page.screenshot({path:path.join(review.out,result.review_png),animations:'disabled'});
      await dialog.getByRole('textbox',{name:'Reason for restoring the complete order and queue',exact:true}).fill('Synthetic recorded correction');
      assert.equal(await save.isDisabled(),false);assert.equal(result.requests.length,0);
      result.png=`confirm-${mode}-${width}-${theme}.png`;await page.screenshot({path:path.join(review.out,result.png),animations:'disabled'});
      await save.click();await dialog.getByRole('button',{name:'Done',exact:true}).waitFor({state:'visible'});assert.equal(result.requests.length,1);
      assert((await dialog.innerText()).includes('Undo saved as a new change'));await dialog.getByRole('button',{name:'Done',exact:true}).click();
      await page.waitForFunction(()=>!document.querySelector('dialog[open]'));
      result.metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth}));
      assert.equal(result.metrics.overflow,false);assert.equal(result.page_errors.length,0);assert.equal(result.route_errors.length,0);
      assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));result.status='captured';
    }catch(error){result.error=review.safeText(error.message);}
    finally{if(context)await context.close();review.report.results.push(result);review.save();}
    if(result.status!=='captured')throw Error('Order/queue case failed: '+(result.route_errors[0]||result.error));review.checkCancelled();
  }
});
