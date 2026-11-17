"""Goal suggestions and explicit linked-draft handoff over real scripts and disposable DOM/API doubles."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + r"""
  const addition = card('New idea', 'Sorcery', 1, ['R']);
  const source = {qty:3,name:'New idea',set:'m21',number:'7',finish:'foil',category:'Draw',card:addition};
  const page = makePage();
  page.summary.card_count=60;
  page.sections.Deck=[{qty:2,name:'Bolt',set:'fdn',number:'3',category:'Slow plan',card:bolt},
    {qty:58,name:'Forest',card:forest}];
  page.considering={sha256:'abc',lines:[{...source},{...source,qty:1,category:'Later'}]};
  const editView={id:page.summary.id,sha256:'abc',title:'Test Deck',may_save:true,
    fields:{status:'building',player:'user',archetype:'Keep the theme'},
    prose:{notes:'Keep my guide',substitutes:'Keep my notes'},
    lists:{target:structuredClone(page.sections),owned:null,considering:structuredClone(page.considering.lines)}};
  const answer={deck_id:page.summary.id,version:'target',goal:'earlier',sha256:'abc',reason:null,
    proposals:[{cuts:[{name:'Bolt',qty:1}],adds:[{...source,qty:1}],max_qty:2,
      reason:'The cheaper spell leaves mana for another play.',trade_off:'Less late-game punch.'}]};
  const calls=[],stored={};
  window.localStorage={getItem:key=>stored[key]??null,setItem:(key,value)=>{stored[key]=String(value);},
    removeItem:key=>{delete stored[key];}};
  let getEdit=async()=>structuredClone(editView),getAnswer=async body=>({...structuredClone(answer),goal:body.goal});
  api=async path=>{calls.push([path]);return getEdit();};
  apiWrite=async(path,body)=>{calls.push([path,structuredClone(body)]);assert.equal(path,'/api/deck/small-swaps');return getAnswer(body);};
  const settleSmall=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
  const draftKeyOf='draft.matt.casual/test.target';
  function beginSmall() {
    clear(main);main.append(el('div',{text:'Deck page'}));deckScreen={data:page};
    location.hash='#/deck?id=casual%2Ftest&v=target&tab=cards';
    return openSmallSwapSuggestions(page);
  }
  async function suggestSmall() {const ctx=beginSmall();assert(ctx);ctx.suggest.click();await settleSmall();return ctx;}
  const proposalButton=(ctx,text)=>buttonText(ctx.results,text);
  same=(actual,expected)=>assert.deepEqual(JSON.parse(JSON.stringify(actual)),JSON.parse(JSON.stringify(expected)));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckSmallSwapsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_offered_only_for_editable_60_card_planned_deck_with_inventory(self):
        self.run_js(r"""
          assert(smallSwapSuggestionsOffered(page));
          for(const modify of [p=>p.summary.kind='commander',p=>p.version='owned',p=>p.summary.read_only=true,
            p=>p.sections.Deck[1].qty=57,p=>delete p.considering]) {
            const other=structuredClone(page);modify(other);assert.equal(openSmallSwapSuggestions(other),null);
          }
          state.may={see_inventory:['user2'],deck_spaces:['user2']};
          assert.equal(openSmallSwapSuggestions(page),null);same(calls,[]);same(stored,{});
        """)

    def test_suggest_is_explicit_and_carries_goal_and_protected_names_without_a_write(self):
        self.run_js(r"""
          const ctx=beginSmall();same(calls,[]);same(stored,{});
          ctx.protected.find(input=>input.value==='Bolt').checked=true;
          ctx.suggest.click();await settleSmall();
          same(calls,[['/api/deck/small-swaps',{id:'casual/test',version:'target',goal:'earlier',protected:['Bolt']}]]);
          assert(ctx.results.textContent.includes('Less late-game punch.'));
          assert(ctx.results.textContent.includes('Review in editor'));
          assert(ctx.results.textContent.includes('Test this change'));
          assert.equal(ctx.results.querySelector('.small-swap-quantity').value,'1');
          same(stored,{});assert(location.hash.startsWith('#/deck'));
        """)

    def test_review_preserves_prose_fields_exact_printing_category_and_linked_considering(self):
        self.run_js(r"""
          const original=structuredClone(editView),ctx=await suggestSmall();
          ctx.results.querySelector('.small-swap-quantity').value='2';
          proposalButton(ctx,'Review in editor').click();await settleSmall();
          const draft=JSON.parse(local.get(draftKeyOf));assert(draft);
          assert.equal(draft.lists.Deck.some(line=>line.name==='Bolt'),false);
          const added=draft.lists.Deck.find(line=>line.name==='New idea');same(added,{...source,qty:2});
          same(draft.considering,[{...source,qty:1},{...source,qty:1,category:'Later'}]);
          same(draft.base.considering,original.lists.considering);same(draft.base.lists,original.lists.target);
          same(draft.fields,pickFields(original.fields));same(draft.prose,original.prose);
          same(draft.base.prose,original.prose);
          same(draft.consideringMoves,[{source:sendLine({...source,qty:2}),section:'Deck'}]);
          same(editView,original);same(calls.map(c=>c[0]),['/api/deck/small-swaps','/api/deck/edit?id=casual%2Ftest']);
          assert.equal(location.hash,'#/edit?id=casual%2Ftest&v=target');
        """)

    def test_test_action_opens_the_existing_test_review_and_does_not_start_a_run(self):
        self.run_js(r"""
          const ctx=await suggestSmall();proposalButton(ctx,'Test this change').click();await settleSmall();
          assert.equal(location.hash,'#/edit?id=casual%2Ftest&v=target&test=change');
          const draft=JSON.parse(local.get(draftKeyOf));assert.equal(draft.lists.Deck.find(line=>line.name==='Bolt').qty,1);
          assert.equal(draft.lists.Deck.find(line=>line.name==='New idea').qty,1);
          assert.equal(calls.length,2);assert(ctx.sheet.closed);
        """)

    def test_goal_or_protection_changes_invalidate_old_result_and_inflight_reply(self):
        self.run_js(r"""
          let resolve;getAnswer=()=>new Promise(done=>{resolve=done;});
          const ctx=beginSmall();ctx.suggest.click();ctx.goal.value='draw';ctx.goal.fire('change');
          resolve(answer);await settleSmall();assert.equal(ctx.results.children.length,0);same(stored,{});
          getAnswer=async body=>({...answer,goal:body.goal});ctx.suggest.click();await settleSmall();
          assert(ctx.results.children.length>0);
          ctx.protected[0].checked=true;ctx.protected[0].fire('change');
          assert.equal(ctx.results.children.length,0);assert.equal(ctx.answer,null);
        """)

    def test_replies_cannot_update_replaced_page_profile_route_sheet_or_footer(self):
        self.run_js(r"""
          for(const change of [ctx=>routeToken++,ctx=>state.profile={...state.profile},ctx=>deckScreen={data:page},
            ctx=>location.hash='#/library',ctx=>ctx.sheet.close(),ctx=>ctx.suggest.remove(),
            ctx=>{ctx.sheet.foot=el('div');},ctx=>main.remove()]) {
            if(!main.isConnected)document.body.append(main);
            let resolve;getAnswer=()=>new Promise(done=>{resolve=done;});
            const ctx=beginSmall();ctx.suggest.click();change(ctx);resolve(answer);await settleSmall();
            assert.equal(ctx.results.children.length,0);same(stored,{});ctx.sheet.close();
          }
        """)

    def test_changed_deck_or_missing_exact_considering_row_never_creates_a_draft(self):
        self.run_js(r"""
          for(const change of [view=>view.sha256='new',view=>view.may_save=false,
            view=>view.lists.considering[0].finish='nonfoil',view=>view.lists.target.Deck[0].qty=0]) {
            getEdit=async()=>{const v=structuredClone(editView);change(v);return v;};
            const ctx=await suggestSmall();proposalButton(ctx,'Review in editor').click();await settleSmall();
            same(stored,{});assert(location.hash.startsWith('#/deck'));ctx.sheet.close();
          }
        """)

    def test_review_get_cannot_overwrite_after_inputs_or_context_change(self):
        self.run_js(r"""
          for(const change of [ctx=>ctx.goal.fire('change'),ctx=>routeToken++,ctx=>state.profile={...state.profile},
            ctx=>proposalButton(ctx,'Review in editor').remove(),ctx=>ctx.sheet.close()]) {
            let resolve;getEdit=()=>new Promise(done=>{resolve=done;});
            const ctx=await suggestSmall();proposalButton(ctx,'Review in editor').click();change(ctx);
            resolve(editView);await settleSmall();same(stored,{});assert(location.hash.startsWith('#/deck'));ctx.sheet.close();
          }
        """)

    def test_existing_draft_keep_replace_and_concurrent_draft_change(self):
        self.run_js(r"""
          for(const choice of ['keep','replace','concurrent']) {
            local.set(draftKeyOf,'original draft');
            const ctx=await suggestSmall();let resolve;
            ask=()=>new Promise(done=>{resolve=done;});
            proposalButton(ctx,'Review in editor').click();await settleSmall();
            assert(resolve);assert.equal(local.get(draftKeyOf),'original draft');
            if(choice==='concurrent')local.set(draftKeyOf,'newer draft');
            resolve(choice==='keep'?'keep':'replace');await settleSmall();
            if(choice==='replace')assert.equal(JSON.parse(local.get(draftKeyOf)).v,1);
            else assert.equal(local.get(draftKeyOf),choice==='keep'?'original draft':'newer draft');
            ctx.sheet.close();local.remove(draftKeyOf);
          }
        """)

    def test_quantity_redraws_card_counts_and_invalidates_a_pending_review(self):
        self.run_js(r"""
          const ctx=await suggestSmall(),quantity=ctx.results.querySelector('.small-swap-quantity');
          let resolve;getEdit=()=>new Promise(done=>{resolve=done;});
          const review=proposalButton(ctx,'Review in editor'),test=proposalButton(ctx,'Test this change');
          review.click();assert(test.disabled);test.click();assert.equal(calls.length,2);
          quantity.value='2';quantity.fire('change');
          const cards=ctx.results.querySelector('.small-swap-cards');
          assert.equal(cards.querySelectorAll('.qty').map(node=>node.textContent).join(','),'2,2');
          resolve(editView);await settleSmall();same(stored,{});assert(location.hash.startsWith('#/deck'));
          assert.equal(review.disabled,false);assert.equal(test.disabled,false);
        """)

    def test_detached_quantity_or_changed_quantity_during_overwrite_prompt_keeps_existing_draft(self):
        self.run_js(r"""
          for(const change of [q=>{q.value='2';q.fire('change');},q=>q.remove()]) {
            local.set(draftKeyOf,'old draft');const ctx=await suggestSmall();let resolve;
            ask=()=>new Promise(done=>{resolve=done;});
            proposalButton(ctx,'Review in editor').click();await settleSmall();assert(resolve);
            change(ctx.results.querySelector('.small-swap-quantity'));resolve('replace');await settleSmall();
            assert.equal(local.get(draftKeyOf),'old draft');assert(location.hash.startsWith('#/deck'));
            ctx.sheet.close();local.remove(draftKeyOf);
          }
        """)

    def test_errors_keep_choices_and_never_relay_raw_error_or_claim_no_candidates(self):
        self.run_js(r"""
          for(const status of [400,403,404,500]) {
            getAnswer=async()=>{throw new ApiError(status,'PRIVATE CONTENT');};
            const ctx=beginSmall();ctx.goal.value='draw';ctx.protected[0].checked=true;
            ctx.suggest.click();await settleSmall();
            assert(!ctx.sheet.body.textContent.includes('PRIVATE CONTENT'));
            assert(!ctx.sheet.body.textContent.includes('No small change fits'));
            assert.equal(ctx.goal.value,'draw');assert(ctx.protected[0].checked);assert.equal(ctx.suggest.disabled,false);
            ctx.sheet.close();
          }
          getAnswer=async body=>({...answer,goal:body.goal,proposals:[],reason:'No free Considering card fits this goal.'});
          const ctx=await suggestSmall();assert(ctx.message.textContent.includes('No free Considering card'));same(stored,{});
        """)

    def test_storage_failure_and_invalid_quantities_leave_page_and_saved_lists_intact(self):
        self.run_js(r"""
          for(const qty of [0,3,1.5,NaN])assert.equal(smallSwapDraft(editView,answer.proposals[0],qty),null);
          const ctx=await suggestSmall();window.localStorage.setItem=()=>{throw Error('full');};
          proposalButton(ctx,'Review in editor').click();await settleSmall();same(stored,{});
          assert(ctx.message.textContent.includes("couldn't be kept"));assert(location.hash.startsWith('#/deck'));
        """)
