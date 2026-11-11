'use strict';
// Anonymous workload over intercepted numeric queue summaries; no simulator or data write.
const path = require('node:path');
const assert = require('node:assert/strict');
const {run} = require('./common.js');

const WORK = {
  exact: {games:1200, unknown:0, approximate:false},
  capped: {games:12800, unknown:0, approximate:true},
  partial: {games:12800, unknown:1, approximate:true},
  unknown: {games:0, unknown:2, approximate:false},
};

run('queue-workload', async review => {
  review.report.scope = 'Queued variant page and native run activity details, synthetic numeric work only; no start or stop requests.';
  review.report.results = [];
  const specs = [];
  for (const theme of ['light','dark']) {
    for (const width of [320,393,1440]) specs.push({theme,width,state:'capped'});
    for (const state of ['exact','partial','unknown']) specs.push({theme,width:393,state});
    specs.push({theme,width:320,state:'partial',root200:true});
  }
  review.report.expected_captures = specs.length;
  for (const spec of specs) {
    const result = {spec,status:'failed',page_errors:[],http_errors:[]};
    let context;
    try {
      review.select('user2');
      context = await review.context({...spec,height:900,coarse:spec.width<1000});
      const page = await context.newPage();
      review.observe(page,result.page_errors,result.http_errors);
      await page.route('**/api/matchups**', async route => {
        assert.equal(route.request().method(),'GET');
        return route.fulfill({status:200,json:{running:[{
          key:'synthetic-queued-test',kind:'variant',title:'Synthetic change test',status:'queued',
          sides:null,by:'User2',done:0,total:1600,ahead:2,ahead_work:WORK[spec.state],
          may_stop:false,link:review.config.ready.routes.member_variant.slice(1),
        }]}});
      });
      await page.route('**/api/variant?**', async route => {
        assert.equal(route.request().method(),'GET');
        const original = await route.fetch();
        assert(original.ok());
        const answer = await original.json();
        answer.status = 'queued';
        answer.job = {status:'queued',done:0,total:1600,ahead:2,ahead_work:WORK[spec.state],
          pairs:{},may_stop:false};
        return route.fulfill({status:200,json:answer});
      });
      await page.goto(review.pageUrl(review.config.ready.routes.member_variant,spec.theme),
        {waitUntil:'domcontentloaded'});
      await page.getByRole('heading',{name:'Waiting to start',exact:true}).waitFor();
      await page.evaluate(() => document.fonts.ready);
      if (spec.root200) await page.evaluate(() => {document.documentElement.style.fontSize='200%';});
      const activity = page.locator('#shell-status .run-activity');
      await activity.waitFor();
      result.activityPointerReachable = await activity.evaluate(node => {
        const box = node.getBoundingClientRect();
        return node.contains(document.elementFromPoint(box.left+box.width/2,box.top+box.height/2));
      });
      assert(result.activityPointerReachable,'Another header control covers the run activity');
      if (spec.root200) {
        await activity.focus();
        await activity.press('Enter');
      } else await activity.click();
      const details = page.locator('#run-details');
      await details.waitFor({state:'visible'});
      const waiting = details.locator('.run-waiting-list');
      const words = await waiting.innerText();
      assert(words.includes('2 runs ahead'));
      if (spec.state==='unknown') assert(/not known yet/i.test(words));
      else {
        assert(words.includes(spec.state==='exact' ? '1,200' : '12,800'));
        assert(words.includes('in this queue'));
      }
      if (spec.state==='partial') assert(words.includes('unknown'));
      if (spec.state==='capped' || spec.state==='partial') assert(words.includes('up to'));
      result.metrics = await waiting.evaluate(node => {
        const bounds = n => {const b=n.getBoundingClientRect();return {left:b.left,right:b.right,width:b.width};};
        const parent = bounds(node);
        return {text:node.innerText,clientWidth:document.documentElement.clientWidth,
          scrollWidth:document.documentElement.scrollWidth,parent,
          outside:[...node.querySelectorAll('*')].map(bounds).filter(b => b.width>0 &&
            (b.left<parent.left-1 || b.right>parent.right+1))};
      });
      assert(result.metrics.scrollWidth<=result.metrics.clientWidth+1,'Document overflow');
      assert.equal(result.metrics.outside.length,0,'Waiting details overflow their container');
      result.png = `${spec.state}-${spec.width}-${spec.theme}${spec.root200?'-root200':''}.png`;
      await page.screenshot({path:path.join(review.out,result.png),fullPage:false,animations:'disabled'});
      assert.equal(result.page_errors.length,0,'Uncaught queue page error');
      assert(!result.http_errors.some(error => error.category==='unexpected_http_error'),'Unexpected HTTP failure');
      result.status='captured';
    } catch (error) {result.error=review.safeText(error.message);}
    finally {if(context)await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(result=>result.status!=='captured').length,0,'Queue workload capture failed');
});
