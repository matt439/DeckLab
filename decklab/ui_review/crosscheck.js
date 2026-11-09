'use strict';
// Real renderer and controls over explicitly intercepted synthetic simulator responses.
// No request reaches a simulator, database write or installed Deck Lab server.
const path = require('node:path');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

const HOME = 'casual/safari-fixture';
const OTHER = 'casual/synthetic-opponent';
const SHA = 'b'.repeat(64), TEST = 'c'.repeat(64);

function response(state, chosen = false) {
  const reference = (id, title) => ({id, title, version:'target', card_sha:SHA});
  const baseline = reference(HOME, 'Synthetic home woodland deck');
  const opponent = reference(OTHER, 'Synthetic woodland opponent');
  const counts = (wins, failed = 0) => ({asked:20, completed:20-failed, wins, losses:20-failed-wins,
    draws:0, failed, timeouts:0, cancelled:0, unplayed:0, win_rate:100*wins/(20-failed),
    win_rate_interval:{low:20,high:80,confidence:0.95}});
  const saved = ['saved','partial'].includes(state);
  const answer = {deck:baseline, opponent:chosen ? opponent : null, format:'casual', mode:'one-on-one',
    choices:[opponent], games_choices:[10,20,50], default_games:10, may_start:true, why_not:null,
    ready:state !== 'unavailable', test:saved || state === 'running' ? TEST : null,
    status:state === 'running' ? 'running' : saved ? 'done' : 'none', job:null, result:null,
    engines:{forge:{ready:true,version:'synthetic-forge',problem:null},
      xmage:{ready:state !== 'unavailable',version:'synthetic-xmage',problem:state === 'unavailable'
        ? 'XMage is not set up on this synthetic server.' : null}},
    note:'These are 1v1 games, including Commander; they do not predict a multiplayer pod.'};
  if(state === 'running') answer.job = {test:TEST,status:'running',by:'Matt',done:7,total:40,ahead:0,
    may_stop:true,error:null,cancelled_by:null};
  if(saved) answer.result = {id:TEST,plan_id:TEST,format:'casual',mode:'one-on-one',games_per_arm:20,
    has_variant:false,current:true,status:state === 'partial' ? 'partial' : 'done',
    decks:{baseline,opponent},engines:{
      forge:{status:'done',version:'synthetic-forge',baseline:counts(12),variant:null,problem:null},
      xmage:{status:state === 'partial' ? 'partial' : 'done',version:'synthetic-xmage',
        baseline:counts(7,state === 'partial' ? 3 : 0),variant:null,
        problem:state === 'partial' ? 'Synthetic incomplete game.' : null,
        coverage:{status:'supported',missing:[]}}},
    agreement:{status:'not_applicable',text:'Two independent scores; no combined win rate.'}};
  return answer;
}

run('crosscheck', async review => {
  review.report.scope='Cross-check renderer, states and intercepted explicit start; synthetic responses only, no engine or database writes.';
  review.report.results=[];
  const specs=[];
  for(const theme of ['light','dark']) {
    for(const width of (review.options.smoke ? [393,1440] : [320,393,820,1440]))
      specs.push({theme,width,state:'saved'});
    for(const state of (review.options.smoke ? ['unavailable','running'] : ['unavailable','running','partial','failed','loading']))
      specs.push({theme,width:393,state});
  }
  review.report.expected_captures=specs.length;
  for(const spec of specs) {
    const result={spec,status:'failed',page_errors:[],http_errors:[],synthetic_writes:[]};
    let context,release;
    try {
      review.select();
      context=await review.context({...spec,height:900,coarse:spec.width<1000});
      const page=await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      const gate=new Promise(resolve=>{release=resolve;});
      let reads=0,simulationState=spec.state;
      await page.route('**/api/crosscheck**',async route=>{
        const request=route.request(),url=new URL(request.url());
        assert.equal(url.origin,review.origin);
        if(request.method()==='POST') {
          assert.equal(spec.state,'saved');assert.equal(spec.width,393);assert.equal(spec.theme,'light');
          const body=request.postDataJSON();
          assert.equal(body.profile,'matt');
          if(url.pathname==='/api/crosscheck/run') {
            assert.equal(body.id,HOME);assert.equal(body.opponent,OTHER);
            assert.equal(body.expected_card_sha,SHA);assert.equal(body.expected_opponent_card_sha,SHA);
            assert.equal(body.games,10);simulationState='running';
            result.synthetic_writes.push('start');
            return route.fulfill({status:202,json:response('running',true)});
          }
          assert.equal(url.pathname,'/api/crosscheck/stop');assert.equal(body.test,TEST);
          simulationState='partial';result.synthetic_writes.push('stop');
          const answer=response('partial',true);
          answer.job={test:TEST,status:'error',error:'stopped',may_stop:false,done:7,total:40};
          return route.fulfill({status:200,json:answer});
        }
        assert.equal(url.pathname,'/api/crosscheck','Capture only permits read requests');
        assert.equal(request.method(),'GET');
        assert.equal(url.searchParams.get('id'),HOME);
        reads++;
        if(spec.state==='loading') await gate;
        if(spec.state==='failed') return route.fulfill({status:503,json:{error:'Synthetic simulator check is temporarily unavailable.'}});
        return route.fulfill({status:200,json:response(simulationState,!!url.searchParams.get('opponent'))});
      });
      await page.goto(review.pageUrl('/#/deck?id='+encodeURIComponent(HOME)+'&v=target&tab=matchups',spec.theme),
        {waitUntil:'domcontentloaded'});
      const section=page.locator('#sec-crosscheck');
      await section.waitFor({state:'visible'});
      assert.equal(reads,0,'Collapsed feature unexpectedly read simulator state');
      await section.getByRole('button',{name:'Choose a deck to test against',exact:true}).click();
      if(spec.state==='loading') await section.getByText('Loading the simulator check…',{exact:true}).waitFor();
      else if(spec.state==='failed') await section.getByText(/temporarily unavailable/).waitFor();
      else await section.locator('#cc-opponent').waitFor();
      await page.evaluate(()=>document.fonts.ready);
      await section.evaluate(node=>scrollTo(0,Math.max(0,scrollY+node.getBoundingClientRect().top-80)));
      await page.waitForTimeout(150);
      if(spec.state==='saved') {
        assert.equal(await section.getByRole('rowheader').count(),2);
        for(const label of ['Forge','XMage']) {
          const unoccluded=await section.getByRole('rowheader',{name:label,exact:true}).evaluate(node=>{
            const box=node.getBoundingClientRect();
            return node.contains(document.elementFromPoint(box.left+box.width/2,box.top+box.height/2));
          });
          assert(unoccluded,`The ${label} result is covered by another element`);
        }
        assert(await section.getByText('60.0%',{exact:true}).isVisible());
        assert(await section.getByText('35.0%',{exact:true}).isVisible());
        assert(await section.getByText(/no combined win rate/).first().isVisible());
        await section.locator('#cc-opponent').selectOption(OTHER);
        await page.waitForTimeout(150);
        assert.equal(await section.locator('#cc-opponent').inputValue(),OTHER);
        assert(!(await section.getByRole('button',{name:'Run both simulators',exact:true}).isDisabled()));
      }
      if(spec.state==='unavailable') assert(await section.getByRole('button',{name:'Run both simulators',exact:true}).isDisabled());
      if(spec.state==='running') assert(await section.getByRole('button',{name:'Stop check',exact:true}).isVisible());
      result.metrics=await section.evaluate(node=>({text:node.innerText,width:innerWidth,
        scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth,
        overflow:[...node.querySelectorAll('*')].filter(n=>{
          const b=n.getBoundingClientRect();return b.width>0 && (b.right>innerWidth+1 || b.left < -1);
        }).slice(0,10).map(n=>({tag:n.tagName,text:n.textContent.trim().slice(0,80)}))}));
      assert(result.metrics.scrollWidth<=result.metrics.clientWidth+1,'Cross-check introduced document overflow');
      result.png=`${spec.state}-${spec.width}-${spec.theme}.png`;
      await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
      if(spec.state==='saved' && spec.width===393 && spec.theme==='light') {
        await section.getByRole('button',{name:'Run both simulators',exact:true}).click();
        await section.getByText('The simulator check is playing.',{exact:true}).waitFor();
        await section.getByRole('button',{name:'Stop check',exact:true}).click();
        await page.getByRole('dialog').getByRole('button',{name:'Stop check',exact:true}).click();
        await section.getByText(/The check was stopped/).waitFor();
        assert.deepEqual(result.synthetic_writes,['start','stop']);
        result.explicitStartAndStop=true;
      }
      if(spec.state==='failed') for(const error of result.http_errors)
        if(error.status===503 && new URL(error.url,review.origin).pathname==='/api/crosscheck') error.category='expected_failure_state';
      // The existing read-only Safari fixture refuses group-run tooling on Testing.
      // This is retained explicitly, independently of the intercepted new feature.
      for(const error of result.http_errors)
        if(error.status===403 && new URL(error.url,review.origin).pathname==='/api/field/group') error.category='expected_fixture_gap';
      assert.equal(result.page_errors.length,0,'Uncaught cross-check page error');
      assert(!result.http_errors.some(error=>error.category==='unexpected_http_error'),'Unexpected cross-check HTTP failure');
      result.reads=reads;result.status='captured';
    } catch(error) {result.error=review.safeText(error.message);}
    finally {if(release)release();if(context)await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Cross-check capture failed');
});
