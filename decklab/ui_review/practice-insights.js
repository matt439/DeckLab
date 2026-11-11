'use strict';
// Synthetic saved goldfish facts over a disposable deck; no simulation, save or inventory writes.
const path=require('node:path');
const assert=require('node:assert/strict');
const {run}=require('./common.js');
const ID='commander/woodland-council';

function practice(){
  const turns=[1,2,3,4,5,6,7,8];
  const row={mulligans:{rate:.2,free_rate:.1,kept:[{cards:7,share:.8},{cards:6,share:.2}]},
    land_drops:{on_time:turns.map(turn=>({turn,chance:.9})),mana:turns.map(turn=>({turn,chance:.8,average:turn+.2}))},
    stuck:{games:.2,turns:[2,3,4],missed_drops:1,missed_turns:6},flood:{turns:.1,games:.2,from_turn:4,to_turn:8,game_turns:3},
    colours:{by_turn:[{colour:'G',name:'green',chances:[.6,.7,.8,.9,.95]}],screw_turns:.1,screw_wasted_turns:.05},
    mana_used:{share:.7,all_used:.6,by_turn:turns.map(turn=>({turn,share:.7,all_used:.6}))},
    first_big:{min_mv:4,in_deck:0,note:'No large spell in the synthetic timing adapter.',by_turn:null},
    commanders:[{name:'Synthetic first commander',average_turn:3.4,never:.2,by_turn:turns.map(turn=>({turn,chance:Math.min(.8,turn/10)}))},
      {name:'Synthetic partner commander',average_turn:4,never:.4,by_turn:turns.map(turn=>({turn,chance:Math.min(.6,turn/10)}))}],
    castability:[{name:'Llanowar Elves',games_seen:900,held_turns:1600,enough_mana_turns:1000,blocked_turns:250,games_waited:200,blocked_share:.25,average_wait:1.25}],
    categories:[{name:'Ramp',cards:5,spells:5,checked:true,by_turn:turns.map(turn=>({turn,at_least:[.9,.65,.3,.1,0]}))},
      {name:'Unreadable category',cards:1,spells:0,checked:false,by_turn:null}]};
  return {kind:'commander',games:20000,turns:8,seed:77,seed_source:'given',seconds:1,workers:1,saved:true,cached:true,cache_key:'a'.repeat(40),
    deck:{cards:100,lands:37,spell_lands:0},setups:[{id:'multiplayer',label:'Multiplayer',text:'Three or more players.'},{id:'play',label:'On the play',text:'A two-player game.'}],
    results:{multiplayer:row,play:structuredClone(row)},warnings:[],cards:{special:[{name:'Lotus Petal',qty:1,rule:'Self-sacrifice mana is available once; the source leaves the battlefield.'}],not_modelled:[]},rules:[],sources:{},
    land_trials:{cuts:['Llanowar Elves','Forest'],colours:['G'],tapped_cut:'Synthetic tapped land',max_games:20000}};
}

function trials(best){
  const metrics={stuck:.2,colour_screw:.1,colour_waste:.05,flood:.1,mana_used:.7};
  const delta={stuck:best?-.02:-.005,colour_screw:0,colour_waste:-.005,flood:0,mana_used:.01};
  return {status:'done',result:{settings:{games:20000,turns:8,seed:77},baseline:{multiplayer:metrics,play:metrics},
    best:{multiplayer:best?'0':null,play:best?'0':null},threshold:.01,warnings:[],
    note:'A mana-only simulation estimate. At least 1 percentage point less stuck or colour screw, with no more than 1 point worse stuck, colour screw or flood. This screen is not a significance test or play advice.',
    variants:[{id:'0',cut:'Llanowar Elves',add:'Forest',tapped_land:false,deltas:{multiplayer:delta,play:delta}},
      {id:'1',cut:'Synthetic tapped land',add:'Forest',tapped_land:true,deltas:{multiplayer:delta,play:delta}}]}};
}

run('practice-insights',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic saved goldfish timing/colour-wait/category facts and one-basic trial replies over a disposable real deck. No CPU simulations, Forge runs, inventory or deck saves.';
  for(const mode of ['details','no-best','best','failed'])for(const theme of ['light','dark'])
    for(const width of (review.options.smoke?[393]:[393,820,1440])){
      const spec={mode,theme,width,height:900,coarse:width<1000};
      const result={spec,status:'failed',page_errors:[],http_errors:[],console_errors:[],requests:[]};let context;
      try{
        review.select('matt');context=await review.context(spec);const page=await context.newPage();
        review.observe(page,result.page_errors,result.http_errors);
        page.on('console',message=>{if(message.type()==='error')result.console_errors.push(review.safeText(message.text()));});
        page.on('request',request=>{const url=new URL(request.url());if(url.pathname.startsWith('/api/'))result.requests.push({path:url.pathname,method:request.method()});});
        const base=await review.readFixture(context,`/api/deck?id=${ID}&omit=matchups`);base.practice={status:'done',result:practice()};
        await page.route('**/api/deck?*',route=>route.fulfill({status:200,json:base}));
        await page.route('**/api/goldfish/what-if',route=>{
          const body=route.request().postDataJSON();assert.equal(body.id,ID);assert.equal(body.version,'target');assert.equal(body.cache_key,'a'.repeat(40));
          return route.fulfill({status:200,json:mode==='failed'?{status:'error',error:'Synthetic simulation failure; try again.'}:trials(mode==='best')});
        });
        await page.goto(review.pageUrl(`/#/deck?id=${ID}&tab=practice`,theme),{waitUntil:'domcontentloaded'});
        const root=page.locator('#sec-practice');await root.getByRole('heading',{name:'Commander timing',exact:true}).waitFor();
        assert((await root.innerText()).includes('Synthetic partner commander'));
        const waits=root.locator('.practice-castability');await waits.locator('summary').click();assert((await waits.innerText()).includes('250 of 1,000 turns'));
        await root.getByRole('combobox',{name:'Category cards cast',exact:true}).selectOption('2');
        assert((await root.locator('.practice-category').innerText()).includes('65.0% of games cast at least 2 Ramp cards'));
        if(mode==='details'){
          await root.getByRole('combobox',{name:'Cast category',exact:true}).selectOption('1');
          assert((await root.locator('.practice-category').innerText()).includes("wasn't checked"));
          await root.getByRole('heading',{name:'Commander timing',exact:true}).evaluate(node=>node.scrollIntoView({block:'start'}));
          result.timing_png=`timing-${width}-${theme}.png`;await page.screenshot({path:path.join(review.out,result.timing_png),fullPage:false,animations:'disabled'});
          await root.locator('.practice-category').evaluate(node=>node.scrollIntoView({block:'start'}));
          result.category_png=`category-${width}-${theme}.png`;await page.screenshot({path:path.join(review.out,result.category_png),fullPage:false,animations:'disabled'});
          await waits.evaluate(node=>node.scrollIntoView({block:'start'}));
        }else{
          await root.getByRole('button',{name:'Run land trials',exact:true}).click();
          const output=root.locator('.practice-land-output');
          if(mode==='failed')await output.getByRole('alert').waitFor();
          else await output.getByText(mode==='best'?/Best change for this setup/:/No best change:/).waitFor();
          await output.evaluate(node=>node.scrollIntoView({block:'start'}));
        }
        result.metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
          tables:[...document.querySelectorAll('.practice-land-result .chance-scroll')].map(node=>({width:node.clientWidth,scroll:node.scrollWidth,root:getComputedStyle(node).overflowX}))}));assert.equal(result.metrics.overflow,false);
        for(const table of result.metrics.tables)assert.equal(table.root,'auto');
        result.png=`${mode}-${width}-${theme}.png`;await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
        assert(!result.requests.some(row=>!['GET','HEAD'].includes(row.method)&&!['/api/goldfish/what-if','/api/visit','/api/errors/report'].includes(row.path)));
        assert(!result.requests.some(row=>row.path==='/api/goldfish'));assert.equal(result.page_errors.length,0);assert.equal(result.console_errors.length,0);
        assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));result.status='captured';
      }catch(error){result.error=review.safeText(error.message);}
      finally{if(context)await context.close();review.report.results.push(result);review.save();}review.checkCancelled();
    }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Practice insights capture failed');
});
