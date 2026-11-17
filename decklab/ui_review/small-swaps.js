'use strict';
// Native suggestion controls over isolated synthetic data; all suggestion replies are intercepted.
const path = require('node:path');
const assert = require('node:assert/strict');
const {run} = require('./common.js');
const ID = 'casual/safari-fixture';

function listLine(name, qty, card, number, category) {
  return {name,qty,set:'sft',number:String(number),finish:'nonfoil',card,
    ...(category ? {category} : {})};
}

async function fixtureData(review, context) {
  const view = await review.readFixture(context, `/api/deck/edit?id=${ID}`);
  const data = await review.readFixture(context, `/api/deck?id=${ID}&omit=matchups`);
  const [overrun, sage, elf, visionary] = await Promise.all(['Overrun','Reclamation Sage','Llanowar Elves','Llanowar Visionary'].map(async name =>
    (await review.readFixture(context, '/api/cards/lookup?name=' + encodeURIComponent(name))).card));
  const forest = data.sections.Deck.find(row => row.name === 'Forest');
  const sections = {Deck:[listLine('Overrun',4,overrun,10,'Finishers'),
    listLine('Reclamation Sage',4,sage,8,'Answers'),listLine('Llanowar Elves',4,elf,1,'Ramp'),
    {...forest,qty:48}]};
  const considering = [listLine('Llanowar Visionary',2,visionary,6,'Draw')];
  data.sections = structuredClone(sections);
  data.summary.card_count = 60;
  data.summary.title = 'Synthetic small-swap study';
  data.owned.rows = sections.Deck.filter(row => row.name !== 'Forest').map(row => ({name:row.name,
    need:row.qty,missing:0,owned:row.qty,available:row.qty,on_the_way:0,on_the_way_from:[],in_use_elsewhere:[],
    labels:{on_the_way:[],in_use:[]},aud_each:null}));
  data.owned.conflicts = [];
  data.owned.totals = {cards:3,need:12,missing:0,aud_missing:0,unpriced:[]};
  data.considering = {sha256:view.sha256,lines:considering.map(row => ({...row,free:2,on_the_way:0}))};
  view.lists.target = structuredClone(sections);
  view.lists.considering = structuredClone(considering);
  view.title = data.summary.title;
  return {data,view,proposal:{cuts:[{name:'Overrun',qty:1}],adds:[{...considering[0],qty:1}],
    reason:'Llanowar Visionary costs less mana and draws a card when it enters.',
    trade_off:'You give up a late-game team boost. This is an idea to try, not a measured improvement.',max_qty:2}};
}

async function metrics(page) {
  return page.evaluate(() => {
    const dialog = [...document.querySelectorAll('dialog[open]')].at(-1);
    const box = dialog?.getBoundingClientRect();
    return {width:innerWidth,clientWidth:document.documentElement.clientWidth,
      scrollWidth:document.documentElement.scrollWidth,dialog:box ? {left:box.left,right:box.right,width:box.width} : null,
      focused:document.activeElement?.getAttribute('class'),
      proposals:[...document.querySelectorAll('.small-swap-proposal')].map(node => node.innerText)};
  });
}

function contained(value) {
  assert(value.scrollWidth <= value.clientWidth + 1, 'Document overflow');
  if(value.dialog) {
    assert(value.dialog.left >= -1 && value.dialog.right <= value.clientWidth + 1, 'Sheet exceeds viewport');
  }
}

run('small-swaps', async review => {
  review.report.results = [];
  review.report.scope = 'Synthetic native goal/protected-card selection, one/two-copy review drafts, empty/error recovery and explicit Test this change entry at phone/tablet/desktop widths. No inventory/deck save or Forge run.';
  const specs = [];
  for(const theme of ['light','dark']) {
    for(const width of (review.options.smoke ? [393] : [320,393,820,1280])) specs.push({theme,width,mode:'ready'});
    if(!review.options.smoke) specs.push({theme,width:393,mode:'empty'},{theme,width:393,mode:'retry'});
  }
  for(const spec of specs) {
    const result = {spec,status:'failed',page_errors:[],http_errors:[],requests:[],suggestions:[]};
    let context;
    try {
      review.select('matt');
      context = await review.context({...spec,height:950,coarse:spec.width<1000});
      const page = await context.newPage();page.setDefaultTimeout(10000);
      const expectedConsole = [];
      page.on('console', message => {
        if(spec.mode === 'retry' && message.type() === 'error'
          && message.text() === 'Failed to load resource: the server responded with a status of 503 (Service Unavailable)'
          && new URL(message.location().url,review.origin).pathname === '/api/deck/small-swaps') {
          expectedConsole.push('Console error: ' + message.text());
        }
      });
      review.observe(page,result.page_errors,result.http_errors);
      page.on('request', request => {
        const url = new URL(request.url());
        if(url.pathname.startsWith('/api/')) result.requests.push({path:url.pathname,method:request.method()});
      });
      const synthetic = await fixtureData(review,context);
      let attempts = 0;
      await page.route('**/api/deck?*', route => route.fulfill({status:200,json:synthetic.data}));
      await page.route('**/api/deck/edit?*', route => route.fulfill({status:200,json:synthetic.view}));
      await page.route('**/api/deck/small-swaps', async route => {
        const request = route.request();assert.equal(new URL(request.url()).origin,review.origin);
        assert.equal(request.method(),'POST');
        const body = request.postDataJSON();result.suggestions.push(body);attempts++;
        assert.deepEqual(body,{profile:'matt',id:ID,version:'target',goal:'earlier',protected:['Reclamation Sage']});
        if(spec.mode === 'retry' && attempts === 1) {
          return route.fulfill({status:503,json:{error:'Synthetic suggestion source unavailable. Try again.'}});
        }
        return route.fulfill({status:200,json:{deck_id:ID,version:'target',sha256:synthetic.view.sha256,goal:'earlier',
          proposals:spec.mode === 'empty' ? [] : [synthetic.proposal],
          reason:spec.mode === 'empty' ? 'No free Considering card addresses this goal without cutting a protected card.' : null}});
      });
      await page.goto(review.pageUrl(`/#/deck?id=${ID}&tab=cards`,spec.theme),{waitUntil:'domcontentloaded'});
      const entry = page.getByRole('button',{name:'Suggest a small swap…',exact:true});
      await entry.click();
      const dialog = page.locator('dialog.sheet[open]').last();
      await dialog.getByRole('heading',{name:'Suggest a small swap',exact:true}).waitFor();
      assert.equal(attempts,0,'Opening the form asks for no recommendation');
      await dialog.locator('.small-swap-goal').selectOption('earlier');
      await dialog.locator('summary').filter({hasText:'Keep these cards'}).click();
      await dialog.locator('.small-swap-protect').first().waitFor();
      await dialog.locator('.small-swap-protect[value="Reclamation Sage"]').check();
      const selected = await dialog.locator('.small-swap-protect:checked').evaluateAll(nodes => nodes.map(node => node.value));
      assert.deepEqual(selected,['Reclamation Sage']);
      result.formMetrics = await metrics(page);contained(result.formMetrics);
      result.formPng = `form-${spec.mode}-${spec.width}-${spec.theme}.png`;
      await page.screenshot({path:path.join(review.out,result.formPng),fullPage:false,animations:'disabled'});
      await dialog.getByRole('button',{name:'Suggest',exact:true}).click();
      if(spec.mode === 'retry') {
        await dialog.getByText("Suggestions couldn't load. Your choices are kept; choose Suggest to try again.",{exact:true}).waitFor();
        assert.equal(await dialog.locator('.small-swap-proposal').count(),0);
        await dialog.getByRole('button',{name:'Suggest',exact:true}).click();
      }
      if(spec.mode === 'empty') {
        await dialog.getByText('No free Considering card addresses this goal without cutting a protected card.',{exact:true}).waitFor();
        assert.equal(await dialog.getByRole('button',{name:'Review in editor',exact:true}).count(),0);
        assert.equal(await dialog.getByRole('button',{name:'Test this change',exact:true}).count(),0);
      } else {
        await dialog.locator('.small-swap-proposal').waitFor();
        const quantity = dialog.locator('.small-swap-quantity');
        assert.equal(await quantity.inputValue(),'1');
        await quantity.selectOption('2');
        assert((await dialog.locator('.small-swap-proposal').innerText()).includes('You give up a late-game team boost'));
        await dialog.locator('summary').filter({hasText:'Keep these cards'}).click();
        await dialog.locator('.small-swap-proposal').evaluate(node => node.scrollIntoView({block:'start'}));
      }
      result.resultMetrics = await metrics(page);contained(result.resultMetrics);
      result.resultPng = `result-${spec.mode}-${spec.width}-${spec.theme}.png`;
      await page.screenshot({path:path.join(review.out,result.resultPng),fullPage:false,animations:'disabled'});
      assert(!result.requests.some(row => row.method === 'POST' && /\/(save|run|start|considering)$/.test(row.path)),
        'Looking at suggestions issued a save or simulation request');
      if(spec.mode === 'ready') {
        const testing = spec.width === 393 || spec.width === 1280;
        if(spec.width === 820) {
          const previous = await page.evaluate(({id}) => {
            const key = draftKey({mode:'edit',profile:'matt',id,version:'target'});
            const text = JSON.stringify({v:1,nativeMarker:'keep this unrelated draft'});
            local.set(key,text);
            return {key,text};
          },{id:ID});
          await dialog.getByRole('button',{name:'Review in editor',exact:true}).click();
          let prompt = page.locator('dialog.sheet[open]').last();
          await prompt.getByRole('heading',{name:'Replace your unsaved changes?',exact:true}).waitFor();
          await prompt.getByRole('button',{name:'Keep my changes',exact:true}).click();
          assert.equal(await page.evaluate(key => local.get(key),previous.key),previous.text);
          await dialog.getByRole('button',{name:'Review in editor',exact:true}).click();
          prompt = page.locator('dialog.sheet[open]').last();
          await prompt.getByRole('heading',{name:'Replace your unsaved changes?',exact:true}).waitFor();
          await prompt.getByRole('button',{name:'Replace them',exact:true}).click();
          result.overwritePrompt = {keptExisting:true,explicitReplace:true};
        } else {
        await dialog.getByRole('button',{name:testing?'Test this change':'Review in editor',exact:true}).click();
        }
        await page.waitForURL(url => url.hash.startsWith('#/edit?'));
        if(testing) {
          // The explicit test action only opens the normal test review; it cannot press its Start button.
          await page.getByRole('heading',{name:/Test this change|Test a change/}).last().waitFor();
        } else await page.locator('.edit-row').first().waitFor();
        const saved = await page.evaluate(() => Object.entries(localStorage).map(([,value]) => {
          try {return JSON.parse(value);} catch {return null;}
        }).find(value => value && value.v === 1 && value.lists?.Deck?.some(row => row.name === 'Overrun' && row.qty === 2)));
        assert(saved,'Reviewed proposal was not kept as a local editor draft');
        const count = name => saved.lists.Deck.filter(row => row.name === name).reduce((sum,row) => sum+row.qty,0);
        assert.equal(count('Overrun'),2);assert.equal(count('Llanowar Visionary'),2);
        assert.equal(count('Reclamation Sage'),4);
        assert.equal(saved.lists.Deck.reduce((sum,row) => sum+row.qty,0),60);
        assert.equal(saved.considering.length,0,'Promoted copies remained in Considering');
        result.reviewedDraft = {copies:2,main:60,protectedCopies:4,considering:0,testSheet:testing};
        assert(!result.requests.some(row => row.method === 'POST' && /\/(save|run|start|considering)$/.test(row.path)),
          'Opening the editor/test review issued a save or simulation request');
      }
      assert.equal(attempts,spec.mode === 'retry' ? 2 : 1);
      if(spec.mode === 'retry') {
        const failures = result.http_errors.filter(error => error.status === 503 && error.url === '/api/deck/small-swaps');
        assert.equal(failures.length,1,'The injected failure must occur exactly once');
        failures[0].category = 'expected_injected_failure';
        if(review.options.strictConsole) {
          assert.equal(expectedConsole.length,1,'The expected native 503 log must match the injected endpoint');
          const index = result.page_errors.indexOf(expectedConsole[0]);
          assert(index >= 0);result.page_errors.splice(index,1);
          result.expected_console_errors = expectedConsole;
        }
      }
      assert.equal(result.page_errors.length,0,'Uncaught browser or strict-console error');
      assert(!result.http_errors.some(error => error.category === 'unexpected_http_error'),'Unexpected HTTP failure');
      result.status = 'captured';
    } catch(error) {
      result.error = review.safeText(error.message);
      if(context) {
        const page = context.pages().at(-1);
        if(page) {
          result.failurePng = `failure-${spec.mode}-${spec.width}-${spec.theme}.png`;
          await page.screenshot({path:path.join(review.out,result.failurePng),fullPage:false,animations:'disabled'}).catch(() => {});
          result.failureMetrics = await page.evaluate(() => [...document.querySelectorAll('dialog[open], dialog[open] .sheet-body, dialog[open] summary')].map(node => {
            const box = node.getBoundingClientRect();
            return {tag:node.tagName,class:node.className,text:node.innerText.slice(0,100),left:box.left,top:box.top,
              width:box.width,height:box.height,display:getComputedStyle(node).display,scroll:node.scrollTop};
          })).catch(() => null);
        }
      }
    }
    finally {if(context) await context.close();review.report.results.push(result);review.save();}
    review.checkCancelled();
  }
  assert.equal(review.report.results.filter(result => result.status !== 'captured').length,0,'Small-swap native review failed');
});
