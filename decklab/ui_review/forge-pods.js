'use strict';
// Native pod choices and reviewed Start, with every simulator reply intercepted in the browser.
const path = require('node:path');
const assert = require('node:assert/strict');
const {run} = require('./common.js');

const KEY = 'a'.repeat(64);
const SIDES = [
  ['commander/synthetic-woodland', 'Synthetic woodland council and the very patient forest', 2],
  ['commander/synthetic-river', 'Synthetic river explorers', 2],
  ['user2/commander/synthetic-public', 'Synthetic public mountain assembly', 3],
  ['commander/synthetic-night', 'Synthetic midnight conclave', 3],
].map(([id,title,target_bracket],index) => ({id,title,target_bracket,kind:'commander',version:'target',
  card_sha:String(index+1).repeat(64),public:id.startsWith('user2/')}));

function saved(partial = false) {
  const counted = partial ? 6 : 16, wins = partial ? [2,1,1,1] : [5,4,4,3];
  return {key:KEY,kind:'pods',sides:SIDES,decks:SIDES,games:16,planned:16,completed:partial?8:16,
    remaining:partial?8:0,state:partial?'stopped':'done',statistical_only:true,
    note:'Synthetic statistics only; clock stops are excluded.',
    summary:{pods:partial?8:16,counted,draws:partial?1:0,clock_stops:partial?2:0,failed_batches:partial?1:0,
      by_deck:Object.fromEntries(SIDES.map((side,index) => [side.id,{wins:wins[index],pods:counted,
        rate:wins[index]/counted,range:[0.08,0.62]}]))}};
}

function answer(mode, stage = 'none') {
  const blocked = mode === 'blocked';
  const result = mode === 'partial' ? saved(true) : stage === 'done' ? saved() : null;
  return {key:stage==='none' && mode!=='partial'?null:KEY,status:mode==='partial'?'done':stage,
    sides:stage==='none' && mode!=='partial'?[]:SIDES,result,
    job:stage==='running'?{status:'running',done:4,total:16,ahead:0,may_stop:true}:null,
    notice:mode==='partial'?'The pod run was stopped; every game that finished is kept.':null,error:null,
    choices:SIDES,results:result?[result]:mode==='ready'?[saved()]:[],
    running:mode==='ready' && stage==='none'?[{key:'pods:'+'b'.repeat(64),kind:'pods',
      title:'Synthetic active Commander pod with a long descriptive title',status:'running',
      done:4,total:16,may_stop:false,link:'#/forge-pods?key='+'b'.repeat(64)}]:[],
    game_choices:[16,32,64,128],default_games:16,
    simulations:{may_start:!blocked,why_not:blocked?'Only an admin can start simulations right now.':null},
    forge:{ready:true,problem:null}};
}

run('forge-pods', async review => {
  review.report.scope='Synthetic four-deck choices, explicit plan/Start, global progress and complete/partial win shares at phone/tablet/desktop widths. All simulator requests are intercepted; no Forge, state or inventory write.';
  review.report.results=[];
  const specs=[];
  for(const theme of ['light','dark']) {
    for(const width of (review.options.smoke?[393]:[320,393,820,1440])) specs.push({theme,width,mode:'ready'});
    specs.push({theme,width:393,mode:'blocked'},{theme,width:820,mode:'partial'});
  }
  for(const spec of specs) {
    const result={spec,status:'failed',page_errors:[],http_errors:[],synthetic_requests:[]};let context;
    try {
      review.select('matt');context=await review.context({...spec,height:1000,coarse:spec.width<1000});
      const page=await context.newPage();page.setDefaultTimeout(10000);review.observe(page,result.page_errors,result.http_errors);
      let stage='none',checks=0,starts=0,finish=false;
      await page.route('**/api/forge/pods**',async route => {
        const request=route.request(),url=new URL(request.url());
        assert.equal(url.origin,review.origin,'Only the owned fixture origin may be intercepted');
        if(url.pathname==='/api/forge/pods') {
          assert.equal(request.method(),'GET');
          if(stage==='running' && finish) stage='done';
          return route.fulfill({status:200,json:answer(spec.mode,stage)});
        }
        assert.equal(request.method(),'POST');
        const body=request.postDataJSON();result.synthetic_requests.push({path:url.pathname,body});
        const selections=SIDES.map(side => ({id:side.id,version:'target'}));
        if(url.pathname==='/api/forge/pods/plan') {
          checks++;assert.equal(starts,0);assert.deepEqual(body,{profile:'matt',decks:selections,games:16});
          const plan=answer(spec.mode,'none');plan.key=KEY;plan.sides=SIDES;
          plan.plan={games:16,remaining:16,completed:0};
          return route.fulfill({status:200,json:plan});
        }
        assert.equal(url.pathname,'/api/forge/pods/run');starts++;assert.equal(checks,1);assert.equal(starts,1);
        assert.equal(spec.mode,'ready');
        assert.deepEqual(body,{profile:'matt',decks:selections,games:16,expected_key:KEY});
        stage='running';return route.fulfill({status:202,json:answer(spec.mode,stage)});
      });
      await page.route('**/api/matchups**',route => {
        assert.equal(route.request().method(),'GET');
        return route.fulfill({status:200,json:{running:stage==='running'?[{
          key:'pods:'+KEY,kind:'pods',title:'Four-player Commander pod',status:'running',
          done:4,total:16,ahead:0,sides:null,by:'Matt',may_stop:true,link:'#/forge-pods?key='+KEY,
        }]:[]}});
      });
      await page.goto(review.pageUrl('/#/forge-pods'+(spec.mode==='partial'?'?key='+KEY:''),spec.theme),
        {waitUntil:'domcontentloaded'});
      await page.getByRole('heading',{name:'Choose the pod',exact:true}).waitFor();
      await page.evaluate(() => document.fonts.ready);
      if(spec.mode==='ready') {
        const active=page.locator('[aria-labelledby="fp-running-heading"]');
        const history=page.locator('.fp-history-list');
        await active.waitFor({state:'visible'});await history.waitFor({state:'visible'});
        assert((await active.innerText()).includes('Synthetic active Commander pod'));
        assert((await history.innerText()).includes('Synthetic woodland council'));
        for(const [name,rows] of [['active-list',active],['saved-list',history]]) {
          await rows.scrollIntoViewIfNeeded();
          result[name+'Metrics']=await rows.evaluate(node => ({text:node.innerText,
            documentOverflow:document.documentElement.scrollWidth>document.documentElement.clientWidth+1,
            rows:[...node.querySelectorAll('.mu-row')].map(row=>({text:row.innerText,
              width:row.getBoundingClientRect().width,names:row.querySelector('.mu-names')?.innerText}))}));
          assert(!result[name+'Metrics'].documentOverflow,'Pod list row document overflow');
          assert(result[name+'Metrics'].rows.every(row=>row.names),'Shared row-name helper missing');
          result[name+'Png']=`${name}-${spec.width}-${spec.theme}.png`;
          await page.screenshot({path:path.join(review.out,result[name+'Png']),fullPage:false,animations:'disabled'});
        }
      }
      if(spec.mode==='partial') {
        await page.getByRole('heading',{name:'Pod win shares',exact:true}).waitFor();
        assert.equal(await page.locator('.fp-share').count(),4);
        assert((await page.locator('.fp-results').innerText()).includes('6 counted pod games'));
        assert((await page.locator('.fp-results').innerText()).includes('2 clock stops'));
        assert((await page.locator('.fp-results').innerText()).includes('1 failed batch'));
      } else {
        for(let index=0;index<4;index++) await page.locator('#fp-deck-'+index).selectOption(SIDES[index].id+'|target');
        const start=page.getByRole('button',{name:'Start',exact:true});
        assert(await start.isDisabled());assert.equal(starts,0);
        await page.getByRole('button',{name:'Check this pod',exact:true}).click();
        await page.getByRole('heading',{name:'Ready to start',exact:true}).waitFor();
        assert.equal(checks,1);assert.equal(starts,0,'A plan never launches a run');
        if(spec.mode==='blocked') {
          assert(await start.isDisabled());
          assert((await page.locator('#fp-start-reason').innerText()).includes('Only an admin'));
        } else {
          assert(await start.isEnabled());
          result.reviewPng=`review-${spec.width}-${spec.theme}.png`;
          await page.screenshot({path:path.join(review.out,result.reviewPng),fullPage:false,animations:'disabled'});
          await start.click();await page.getByRole('heading',{name:'Playing this pod',exact:true}).waitFor();
          assert.equal(starts,1);assert((await page.locator('.fp-live').innerText()).includes('4 of 16'));
          const activity=page.locator('#shell-status .run-activity');await activity.waitFor();await activity.click();
          await page.locator('#run-details').waitFor({state:'visible'});
          assert((await page.locator('#run-details').innerText()).includes('Four-player Commander pod'));
          result.runningPng=`running-${spec.width}-${spec.theme}.png`;
          await page.screenshot({path:path.join(review.out,result.runningPng),fullPage:false,animations:'disabled'});
          await page.keyboard.press('Escape');finish=true;
          await page.getByRole('heading',{name:'Pod win shares',exact:true}).waitFor({timeout:15000});
          assert.equal(await page.locator('.fp-share').count(),4);
          assert((await page.locator('.fp-results').innerText()).includes('16 counted pod games'));
        }
      }
      const target=spec.mode==='blocked'?page.locator('.fp-chooser'):page.locator('.fp-results');
      await target.scrollIntoViewIfNeeded();
      result.metrics=await page.evaluate(() => ({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
        clientWidth:document.documentElement.clientWidth,shares:[...document.querySelectorAll('.fp-share')].map(node=>node.innerText),
        choices:[...document.querySelectorAll('.fp-deck')].map(node=>({value:node.value,width:node.getBoundingClientRect().width}))}));
      assert(result.metrics.scrollWidth<=result.metrics.clientWidth+1,'Document overflow');
      assert.equal(result.synthetic_requests.length,spec.mode==='ready'?2:spec.mode==='blocked'?1:0);
      result.png=`${spec.mode}-${spec.width}-${spec.theme}.png`;
      await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
      assert.equal(result.page_errors.length,0,'Uncaught browser error');
      assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'),'Unexpected HTTP failure');
      result.status='captured';
    } catch(error) {result.error=review.safeText(error.message);}
    finally {if(context)await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Pod review failed');
});
