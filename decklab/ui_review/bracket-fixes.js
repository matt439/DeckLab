'use strict';
// Invented counted-minimum plans/candidates render over a disposable real deck/editor. No saves or runs.
const path=require('node:path');
const assert=require('node:assert/strict');
const {run}=require('./common.js');
const ID='commander/woodland-council';
const NAMES=['Llanowar Elves','Elvish Mystic','Beast Whisperer','Overrun'];

function projected(base,mode,receipt){
  const value=structuredClone(base),br=value.stats.commander.bracket,overlap=mode==='overlap';
  value.summary.target_bracket=overlap?2:3;value.stats.warnings=[];
  Object.assign(br,{minimum:overlap?3:4,cards_minimum:overlap?1:4,label:overlap?'3 – Upgraded':'4 – Optimized',
    game_changers:overlap?[]:NAMES.map(name=>({name,qty:1})),mass_land_denial:[],extra_turns:[],unknown_cards:[],
    combos:{checked:true,list_date:'2000-01-01',matches:overlap?[{names:[NAMES[0],NAMES[2]],floor:3,class:'infinite',standalone:true,raises_floor:true,results:['Synthetic infinite result'],url:'https://commanderspellbook.com/'}]:[]}});
  br.fixes={checked:true,target:value.summary.target_bracket,current_minimum:br.minimum,cuts:1,
    receipt:mode==='outsider'?null:receipt,examples_only:true,
    note:"These cuts change the counted minimum, not the deck's actual bracket. Replace the cut cards and check the complete list.",
    plans:[{fixed:overlap?[NAMES[0]]:[],choose:overlap?null:{count:1,names:NAMES},example:[NAMES[0]],after_minimum:overlap?1:3}]};
  if(mode==='unknown')br.fixes={checked:false,target:3,reason:'Tag or combo data is unavailable, so the fewest cuts cannot be checked.',receipt:null};
  return value;
}

run('bracket-fixes',async review=>{
  review.report.results=[];
  review.report.scope='Synthetic counted-floor plans and safe/unsafe/unknown replacement adapters; actual Overview/Stats choices and ordinary editor Test-this-change entry. Backend math/privacy has separate fixtures. No save or simulation start.';
  for(const mode of ['choices','overlap','unknown','outsider','test'])for(const theme of ['light','dark'])
    for(const width of (review.options.smoke?[393]:[393,820,1440])){
      const spec={mode,theme,width,height:900,coarse:width<1000};
      const result={spec,status:'failed',page_errors:[],http_errors:[],console_errors:[],requests:[]};let context;
      try{
        review.select(mode==='outsider'?'user2':'matt');context=await review.context(spec);const page=await context.newPage();
        review.observe(page,result.page_errors,result.http_errors);
        page.on('console',message=>{if(message.type()==='error')result.console_errors.push(review.safeText(message.text()));});
        page.on('request',request=>{const url=new URL(request.url());if(url.pathname.startsWith('/api/'))result.requests.push({path:url.pathname,method:request.method()});});
        const base=await review.readFixture(context,`/api/deck?id=${ID}&omit=matchups`);
        const receipt=mode==='outsider'?null:(await review.readFixture(context,`/api/deck/edit?id=${ID}`)).sha256;
        const spare=(await review.readFixture(context,'/api/cards/lookup?name=Synthetic+spare+Elf'))?.card;assert(spare);
        await page.route('**/api/deck?*',route=>route.fulfill({status:200,json:projected(base,mode,receipt)}));
        await page.route('**/api/deck/bracket-replacements',route=>{
          const body=route.request().postDataJSON();assert.deepEqual(body.cuts,[NAMES[0]]);
          return route.fulfill({status:200,json:{note:'After all selected cuts and this replacement, the counted minimum stays within the target. Test changes one slot.',
            candidates:[{name:spare.name,card:spare,free:1,here:1,max_qty:1,default:{set:'sft',number:'11',finish:'nonfoil'},fit:'safe',after_minimum:mode==='overlap'?1:3,one_swap_legal:true,
              fit_note:'After all selected cuts and this replacement, the counted minimum would remain within the target.',note:{text:'Synthetic free replacement.'}},
              {name:'Synthetic Game Changer replacement',card:null,free:1,here:1,max_qty:1,fit:'unsafe',after_minimum:4,one_swap_legal:true,fit_note:'Would count four Game Changers again.'},
              {name:'Synthetic unchecked replacement',card:null,free:1,here:1,max_qty:1,fit:'unknown',after_minimum:null,one_swap_legal:false,fit_note:'The counted minimum is unknown.'}]}});
        });
        await page.route('**/api/variant/estimate?*',route=>route.fulfill({status:200,json:{available:false,opponents:0,reason:'Synthetic read-only review'}}));
        const tab=['choices','unknown'].includes(mode)?'stats':'overview';
        await page.goto(review.pageUrl(`/#/deck?id=${ID}&tab=${tab}`,theme),{waitUntil:'domcontentloaded'});
        const root=page.locator(tab==='stats'?'#sec-stats .bracket-fixes':'.commander-readiness .bracket-fixes');await root.waitFor({state:'visible'});
        if(mode==='unknown'){
          assert((await root.innerText()).includes('cannot be checked'));assert.equal(await root.getByRole('button',{name:'Free replacements',exact:true}).count(),0);
        }else{
          assert((await root.innerText()).includes('Fewest cards to cut from these counts: 1'));
          if(mode==='outsider')assert.equal(await root.getByRole('button',{name:'Free replacements',exact:true}).count(),0);
          else{
            if(mode!=='overlap'){const fields=root.getByRole('checkbox');assert.equal(await fields.count(),4);assert.equal(await fields.first().isChecked(),false);await fields.first().check();}
            await root.getByRole('button',{name:'Free replacements',exact:true}).first().click();
            await root.getByText('Would raise the counted minimum again',{exact:true}).waitFor();
            const buttons=root.getByRole('button',{name:'Test this swap',exact:true});assert.equal(await buttons.count(),3);
            assert.equal(await buttons.nth(0).isDisabled(),false);assert.equal(await buttons.nth(1).isDisabled(),true);assert.equal(await buttons.nth(2).isDisabled(),true);
            if(mode==='test'){
              await buttons.first().click();await page.getByRole('heading',{name:'Test this change',exact:true}).waitFor();
              await page.locator('dialog.vt-sheet[open] .vt-choice').first().waitFor({state:'visible'});
            }
          }
        }
        result.metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth}));assert.equal(result.metrics.overflow,false);
        if(mode!=='test')await root.evaluate(node=>node.scrollIntoView({block:'start'}));result.png=`${mode}-${width}-${theme}.png`;
        await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
        assert(!result.requests.some(row=>!['GET','HEAD'].includes(row.method)&&!['/api/deck/check','/api/deck/bracket-replacements','/api/visit','/api/errors/report'].includes(row.path)));
        assert.equal(result.page_errors.length,0);assert.equal(result.console_errors.length,0);assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'));
        result.status='captured';
      }catch(error){result.error=review.safeText(error.message);}
      finally{if(context)await context.close();review.report.results.push(result);review.save();}review.checkCancelled();
    }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Bracket fix capture failed');
});
