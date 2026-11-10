'use strict';
// Actual counter launchers and controls over a synthetic Game log; no record is previewed or saved.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

function payload() {
  const line=name=>({name,qty:1,set:null,number:null,finish:'nonfoil'});
  const lists=['a','b'].map((id,index)=>({id:`commander/counter-${id}`,version:'target',sha256:id.repeat(64),
    title:index?'Synthetic second deck':'Synthetic first deck',
    sections:{Commander:[line(`Commander ${id.toUpperCase()}`)],Deck:[{...line('Forest'),qty:99}]},
    counter_markers:['poison','energy','experience','monarch','initiative']}));
  return {lists,pod_lists:lists.map(list=>({...list,can_record:true})),games:[],pods:[],sideboards:[],warnings:[],
    today:new Date().toISOString().slice(0,10),
    decks:Object.fromEntries(lists.map(list=>[list.id,{player:'user',status:'built',can_record:true}]))};
}

run('life-counters',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic Game-log read adapter; native counter launch, marker controls and repeated Undo. Wake Lock API is explicitly simulated; no record requests or physical-device acceptance.';
  const specs=[];
  for(const mode of ['duel','pod'])for(const theme of ['light','dark'])for(const wake of ['unavailable','supported'])
    for(const width of (review.options.smoke?[393]:[393,820,1440]))
      specs.push({mode,theme,wake,width,height:width===820?1106:900,coarse:width<1000});
  for(const spec of specs){
    let context;
    const result={spec,status:'failed',page_errors:[],http_errors:[],console_errors:[]};
    try{
      review.select('matt');context=await review.context(spec);const page=await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      page.on('console',message=>{if(message.type()==='error')result.console_errors.push(review.safeText(message.text()));});
      await page.addInitScript(supported=>{
        window.reviewWake={requested:0,released:0};
        Object.defineProperty(navigator,'wakeLock',{configurable:true,value:supported?{request:async type=>{
          if(type!=='screen')throw Error('Unexpected lock kind');window.reviewWake.requested++;
          const lock=new EventTarget();lock.released=false;lock.release=async()=>{
            if(lock.released)return;lock.released=true;window.reviewWake.released++;lock.dispatchEvent(new Event('release'));
          };return lock;
        }}:undefined});
      },spec.wake==='supported');
      await page.route('**/api/play',route=>{
        assert.equal(route.request().method(),'GET');return route.fulfill({status:200,json:payload()});
      });
      await page.goto(review.pageUrl('/#/play',spec.theme),{waitUntil:'domcontentloaded'});
      await page.getByRole('button',{name:'Life counter',exact:true}).waitFor();
      if(spec.mode==='duel')await page.getByRole('button',{name:'Life counter',exact:true}).click();
      else{
        await page.getByRole('button',{name:'Record a pod game',exact:true}).click();
        await page.getByRole('button',{name:'Start pod counter',exact:true}).click();
      }
      const counter=page.locator(spec.mode==='duel'?'.life-source-counter':'.pod-life-counter');
      await counter.waitFor({state:'visible'});
      const first=counter.locator(spec.mode==='duel'?'[data-life-source-seat=a]':'[data-pod-life-seat=s1]');
      const second=counter.locator(spec.mode==='duel'?'[data-life-source-seat=b]':'[data-pod-life-seat=s2]');
      const plus=first.getByRole('button',{name:/1 more life/});
      for(let index=0;index<3;index++)await plus.click();
      await counter.getByRole('button',{name:'Undo last change',exact:true}).click();
      await counter.getByRole('button',{name:'Undo last change',exact:true}).click();
      await first.getByRole('button',{name:/1 more energy$/}).click();
      await first.getByRole('button',{name:/: monarch$/}).click();
      await second.getByRole('button',{name:/: monarch$/}).click();
      assert.equal(await first.getByRole('button',{name:/: monarch$/}).getAttribute('aria-pressed'),'false');
      assert.equal(await second.getByRole('button',{name:/: monarch$/}).getAttribute('aria-pressed'),'true');
      result.packet=await page.evaluate(mode=>{
        const game=mode==='duel'?lifeV2Open.game:podLifeCounterOpen.packet;
        return {firstLife:(game.players||game.seats)[0].life,energy:game.markers.values[0].energy,
          monarchs:game.markers.values.map(row=>row.monarch),enabled:game.markers.enabled,poison:game.poison};
      },spec.mode);
      assert.equal(result.packet.firstLife,41);assert.equal(result.packet.energy,1);
      assert.deepEqual(result.packet.monarchs,spec.mode==='duel'?[false,true]:[false,true,false]);
      assert(result.packet.poison&&Object.values(result.packet.enabled).every(Boolean));
      await counter.locator('.life-marker-options > summary').click();
      const sleep=counter.locator('.life-sleep-note');
      if(spec.wake==='supported')assert.equal(await sleep.isHidden(),true);
      else assert.equal(await sleep.innerText(),'Screen may sleep on this address; your count is saved');
      await page.evaluate(()=>document.fonts.ready);
      result.metrics=await counter.evaluate(node=>({width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height,
        scrollHeight:node.scrollHeight,clientHeight:node.clientHeight,
        documentOverflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
        note:node.querySelector('.life-sleep-note').textContent,
        markerSettings:node.querySelector('.life-marker-options').innerText}));
      assert.equal(result.metrics.documentOverflow,false,'Counter expands the document horizontally');
      result.png=`${spec.mode}-${spec.wake}-${spec.width}-${spec.theme}.png`;
      if(spec.mode==='pod')await counter.evaluate(node=>{node.scrollTop=0;});
      await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
      await counter.locator(spec.mode==='duel'?'.life-bar':'.pod-life-bar').scrollIntoViewIfNeeded();
      result.controlsPng=`${spec.mode}-controls-${spec.wake}-${spec.width}-${spec.theme}.png`;
      await page.screenshot({path:path.join(review.out,result.controlsPng),fullPage:false,animations:'disabled'});
      await counter.getByRole('button',{name:'Close',exact:true}).click();
      assert.equal(await counter.count(),0);
      result.wake=await page.evaluate(()=>window.reviewWake);
      if(spec.wake==='supported')assert(result.wake.requested>=1&&result.wake.released===result.wake.requested);
      else assert.equal(result.wake.requested,0);
      assert.equal(result.page_errors.length,0);assert.equal(result.console_errors.length,0);
      assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));
      result.status='captured';
    }catch(error){result.error=review.safeText(error.message);}
    finally{if(context)await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Life-counter capture failed');
});
