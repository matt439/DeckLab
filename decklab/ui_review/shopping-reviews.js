'use strict';
// Native controls over invented intercepted Shopping payloads. No app writes reach a route.
const path=require('node:path');
const assert=require('node:assert/strict');
const {run}=require('./common.js');

run('shopping-reviews',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic saved shop lines only: native reference checkbox/review and price-free basket order handoff. All POSTs are intercepted invented replies; no app write or vendor request.';
  for(const mode of ['reference','basket'])for(const theme of ['light','dark'])for(const width of (review.options.smoke?[393]:[393,820,1440])){
    const spec={mode,theme,width,height:1000,coarse:width<1000};
    const result={spec,status:'failed',page_errors:[],http_errors:[],requests:[],route_errors:[]};let context;
    try{
      review.select('matt');context=await review.context(spec);const page=await context.newPage();page.setDefaultTimeout(10000);
      review.observe(page,result.page_errors,result.http_errors);
      let revision='q1';
      const quote={shop:'MTGMate',shop_key:'mtgmate',status:'in_stock',price_aud:'3.00',stock:2,set:'sft',collector_number:'1',finish:'nonfoil',
        condition:'Near Mint',language:'English',fetched_at:'2026-11-11T12:00:00Z',carried:false,reference_receipt:'a'.repeat(64),
        lowest_kept:{days:90,readings:3},target_comparison:{amount_aud:'3.00',at_or_below:true}};
      const card={name:'Llanowar Elves',quantity:3,queue_row:1,state:'ready',for:'Synthetic deck',printing:'exact',set:'sft',collector_number:'1',
        finish:'nonfoil',listed_aud:'0.50',listed_at:'Old fixture shop',in_stock:'no',checked:'2026-11-01',buy_under_aud:'3.00',notes:'',card:null,deck:null,
        shop_snapshot:quote,shop_snapshots:[quote]};
      const later={...card,name:'Synthetic add-on',queue_row:2,state:'long_term',quantity:1,shop_snapshots:[],shop_snapshot:null};
      const item={...card,status:'in_stock',copies:2,stock:2,short:true,fetched_at:quote.fetched_at,carried:false,is_token:false,add_on:false,line_aud:'6.00',
        listing:{set:'sft',collector_number:'1',finish:'nonfoil',price_aud:'3.00',stock:2,copies:2,condition:'Near Mint',language:'English'},more:[]};
      const basket={key:'mtgmate',shop:'MTGMate',read:true,counts_stock:true,fetched_at:quote.fetched_at,rows:[item],add_ons:[],unconfirmed:[],unknown:[],not_checked:[],
        total_aud:'6.00',priced:1,unpriced:0,cards:2};
      const change={row:1,name:card.name,old:{listed_aud:'0.50',listed_at:'Old fixture shop',in_stock:'no',checked:'2026-11-01'},
        new:{listed_aud:'3.00',listed_at:'MTGMate',in_stock:'yes',checked:'2026-11-11'}};
      const reply=(route,body)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
      const intercepted=async(route,work)=>{try{return await work();}catch(error){result.route_errors.push(review.safeText(error.message));
        return reply(route,{error:'Synthetic fixture assertion failed'});}};
      await page.route('**/api/shopping',route=>reply(route,{to_buy:[card,later],orders:[],checks:[],warnings:[],queue_revision:revision,
        baskets:{queue_revision:revision,shops:[basket],unavailable:[]}}));
      await page.route('**/api/shopping/queue',route=>intercepted(route,()=>{
        assert.equal(route.request().method(),'POST');const body=route.request().postDataJSON();result.requests.push(body);
        if(body.action==='reference_preview'){
          assert.deepEqual(body,{profile:'matt',action:'reference_preview',expect:'q1',requests:[{row:1,shop:'mtgmate',receipt:'a'.repeat(64)}]});
          return reply(route,{preview:'synthetic-reference',changed:1,changes:[change]});
        }
        assert.deepEqual(body,{profile:'matt',action:'reference_apply',preview:'synthetic-reference'});revision='q2';Object.assign(card,change.new);
        return reply(route,{saved:true,revision,changed:1,changes:[change]});
      }));
      await page.route('**/api/shopping/order/preview',route=>intercepted(route,()=>{
        const body=route.request().postDataJSON();result.requests.push(body);
        assert.equal(body.profile,'matt');
        assert.equal(body.record.seller,'MTGMate');assert.equal(body.expect,'q1');
        assert.deepEqual(body.cards,{rows:[{name:'Llanowar Elves',set:'sft',collector_number:'1',finish:'nonfoil',quantity:2,condition:'',language:'',notes:''}],checks:[]});
        assert.deepEqual(body.fulfils,[{row:1,quantity:2}]);assert(!JSON.stringify(body).includes('price_aud'));
        return reply(route,{preview:'synthetic-order',tables:{written:[],skipped:[]},watchlist_reduced:[{name:card.name,quantity:2,left:1}]});
      }));
      await page.goto(review.pageUrl('/#/shopping',theme),{waitUntil:'domcontentloaded'});
      await page.getByRole('heading',{name:'Shopping',exact:true}).waitFor();
      if(mode==='reference'){
        const reveal=page.getByRole('button',{name:'Show shop snapshot for Llanowar Elves',exact:true});
        if(await reveal.isVisible())await reveal.click();
        await page.getByRole('button',{name:'Use this as the reference',exact:true}).click();
        const dialog=page.locator('dialog[open]').last(),check=dialog.getByRole('checkbox');
        assert.equal(await check.isChecked(),true);await check.uncheck();
        await dialog.getByRole('button',{name:'Preview',exact:true}).click();
        await dialog.getByRole('alert').filter({hasText:'Select 1 to 100'}).waitFor();assert.equal(result.requests.length,0);
        await check.check();await dialog.getByRole('button',{name:'Preview',exact:true}).click();
        const save=dialog.getByRole('button',{name:'Save references',exact:true});await save.waitFor({state:'visible'});
        await page.waitForFunction(()=>![...document.querySelectorAll('dialog[open] button')].find(node=>node.textContent==='Save references')?.disabled);
        assert.equal(result.requests.length,1);assert((await dialog.innerText()).includes('Old fixture shop'));
        const heading=await dialog.locator('thead').boundingBox(),firstRow=await dialog.locator('tbody tr').first().boundingBox();
        assert(firstRow.y>=heading.y+heading.height-1,'Reference values must not be covered by the table heading');
        result.png=`${mode}-${width}-${theme}.png`;await page.screenshot({path:path.join(review.out,result.png),animations:'disabled'});
        await save.click();await page.waitForFunction(()=>!document.querySelector('dialog[open]'));
        assert.equal(result.requests.length,2);
        if(await reveal.isVisible())await reveal.click();
        assert((await page.locator('#main').innerText()).includes('Lowest in kept 90 days'));
      }else{
        await page.getByRole('button',{name:'Record this order from MTGMate',exact:true}).click();
        const dialog=page.locator('dialog[open]').last();
        assert.equal(await dialog.locator('[data-order-field=seller]').inputValue(),'MTGMate');
        assert(/^\d{4}-\d{2}-\d{2}$/.test(await dialog.locator('[data-order-field=ordered_on]').inputValue()));
        assert.equal(await dialog.locator('[data-order-fulfils="1"]').isChecked(),true);
        assert.equal(await dialog.locator('[data-order-fulfils-quantity="1"]').inputValue(),'2');
        assert.equal(await dialog.locator('[data-order-fulfils="2"]').isChecked(),false);
        assert.equal(result.requests.length,0);assert((await dialog.innerText()).includes('need checking'));
        await dialog.getByRole('button',{name:'Preview order',exact:true}).click();
        await dialog.getByRole('button',{name:'Save order',exact:true}).waitFor({state:'visible'});assert.equal(result.requests.length,1);
        result.png=`${mode}-${width}-${theme}.png`;await page.screenshot({path:path.join(review.out,result.png),animations:'disabled'});
        await dialog.getByRole('button',{name:'Cancel',exact:true}).click();assert.equal(result.requests.length,1);
      }
      result.metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth}));
      assert.equal(result.metrics.overflow,false);assert.equal(result.page_errors.length,0);assert.equal(result.route_errors.length,0);
      assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));result.status='captured';
    }catch(error){result.error=review.safeText(error.message);}
    finally{if(context)await context.close();review.report.results.push(result);review.save();}
    if(result.status!=='captured')throw new Error('Shopping review case failed: '+(result.route_errors[0]||result.error));
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Shopping review capture failed');
});
