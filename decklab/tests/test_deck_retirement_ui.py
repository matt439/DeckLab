"""Retire saved deck ideas and inspect retained history through the real UI scripts.

All reads, writes and delayed responses are synthetic; no collection or database is changed.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + r"""
  clear(main); editor = null;
  const matt = {id:'matt',name:'Matt',role:'admin',space:'home',plays_as:'user'};
  state.profile=matt;state.profiles=[matt];state.may={admin:true,see_inventory:['home'],spaces:['home'],deck_spaces:['home']};
  const metadata=(extra={})=>({id:'casual/test',title:'Test Deck',sha256:'a'.repeat(64),
    revision:7,status:'idea',may_retire:true,why_not:null,...extra});
  const retired=(extra={})=>({retired:true,id:'casual/test',title:'Test Deck',
    history:'#/history?id=casual%2Ftest',...extra});
  const rev=(extra={})=>({revision:6,date:'2026-10-15T12:00:00+10:00',op:'A',author:'Matt',
    actor:'matt',subject:'Try an Elf deck',commit:null,
    change:{kind:'created',cards:[],fields:[],lists:['target'],size:{target:1,owned:null}},...extra});
  const retained=(extra={})=>({id:'casual/test',title:'Test Deck',retired:true,may_save:false,
    may_restore:true,retired_revision:7,current:null,revisions:[rev({revision:7,op:'D',
      subject:'Prefer the other deck',change:{kind:'deleted',cards:[],fields:[],lists:[]}}),rev()],...extra});
  const requests=[],reads=[],messages=[],sheets=[];
  const realSheet=openSheet;
  openSheet=(...args)=>{const sheet=realSheet(...args);sheets.push(sheet);return sheet;};
  const settle=async()=>{for(let n=0;n<30;n++)await Promise.resolve();};
  const held=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
    return {promise,resolve,reject};};
  const findButton=(root,text)=>root.querySelectorAll('button').find(node=>node.textContent===text);
  const action=(ctx,text)=>{const found=findButton(ctx.sheet.foot,text);assert(found,`Action ${text}`);return found;};
  const reason=ctx=>{const input=ctx.sheet.body.querySelector('input[type=text]');assert(input,'Reason input');return input;};
  const confirm=ctx=>{const input=ctx.sheet.body.querySelector('input[type=checkbox]');assert(input,'Confirmation checkbox');return input;};
  const typeReason=(ctx,value)=>{const input=reason(ctx);input.value=value;input.fire('input');return input;};
  const acknowledge=ctx=>{confirm(ctx).checked=true;confirm(ctx).fire('change');};
  const ready=ctx=>{typeReason(ctx,'Prefer the other deck');acknowledge(ctx);};
  const mount=(data=makePage())=>{clear(main);location.hash='#/deck?id='+encodeURIComponent(data.summary.id);
    drawDeck(data,deckViewOf(parseHash().params));return data;};
  const openRetirement=async(data=makePage())=>{mount(data);const ctx=openRetireDeck(data);assert(ctx,'Retirement context');
    await settle();return ctx;};
  const latest=()=>sheets.at(-1);
  let answerRead=async()=>metadata(),answerWrite=async()=>retired();
  api=async path=>{reads.push(path);return answerRead(path);};
  apiWrite=async(path,body)=>{requests.push([path,body]);return answerWrite(path,body);};
  toast=words=>messages.push(words);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckRetirementUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_menu_is_only_for_editable_unbuilt_saved_decks(self):
        self.run_js(r"""
          const ordinary=makePage();assert(canRetireDeck(ordinary));
          assert(deckMoreItems(ordinary).some(item=>item&&/^Retire deck[.\u2026]?$/.test(item.label||'')));
          for(const extra of [{status:'built'},{read_only:true},{id:'product/starter/green'},
              {id:'pairing/test'},{id:BOX_PREFIX+'green'},{id:''}]) {
            const data=makePage();Object.assign(data.summary,extra);
            assert(!canRetireDeck(data),JSON.stringify(extra));
            assert(!deckMoreItems(data).some(item=>item&&/Retire deck/.test(item.label||'')));
          }
          state.may={admin:false,deck_spaces:['user2'],home_player:null};
          assert(!canRetireDeck(ordinary));assert.equal(openRetireDeck(ordinary),null);same(reads,[]);same(requests,[]);
          const own=makePage();Object.assign(own.summary,{id:'user2/casual/test',space:'user2',player:null});
          assert(canRetireDeck(own));
        """)

    def test_reason_and_explicit_confirmation_are_both_required(self):
        self.run_js(r"""
          const ctx=await openRetirement();same(reads.filter(path=>path.startsWith('/api/deck/retire?')),
            ['/api/deck/retire?id=casual%2Ftest']);
          assert(action(ctx,'Retire deck').disabled);assert.equal(reason(ctx).getAttribute('type'),'text');
          assert(ctx.sheet.body.textContent.includes('history'));
          typeReason(ctx,'   ');acknowledge(ctx);assert(action(ctx,'Retire deck').disabled);
          typeReason(ctx,'Prefer the other deck');confirm(ctx).checked=false;confirm(ctx).fire('change');
          assert(action(ctx,'Retire deck').disabled);acknowledge(ctx);assert(!action(ctx,'Retire deck').disabled);
          same(requests,[]);action(ctx,'Cancel').click();await settle();same(requests,[]);assert(ctx.sheet.closed);
        """)

    def test_post_binds_reason_to_the_fresh_sha_and_revision(self):
        self.run_js(r"""
          const pending=held();answerWrite=()=>pending.promise;
          const ctx=await openRetirement();typeReason(ctx,'  Prefer the other deck  ');acknowledge(ctx);
          action(ctx,'Retire deck').click();await settle();
          same(requests,[['/api/deck/retire',{profile:'matt',id:'casual/test',sha256:'a'.repeat(64),
            revision:7,reason:'Prefer the other deck'}]]);
          pending.resolve(retired());await settle();assert(main.textContent.includes('Deck retired'));
          assert(main.querySelectorAll('a').some(a=>a.textContent==='View retained history'&&a.getAttribute('href').startsWith('#/history?id=')));
        """)

    def test_multiline_reason_cannot_be_sent_even_when_the_handler_is_called_directly(self):
        self.run_js(r"""
          const ctx=await openRetirement();typeReason(ctx,'First line\nSecond line');acknowledge(ctx);
          await sendRetireDeck(ctx);same(requests,[]);
          assert(action(ctx,'Retire deck').disabled||ctx.sheet.body.textContent.includes('line'));
        """)

    def test_metadata_refusal_and_read_failure_offer_no_retirement(self):
        self.run_js(r"""
          answerRead=async()=>metadata({may_retire:false,why_not:'Return its kit to storage first.'});
          let ctx=await openRetirement();assert(ctx.sheet.body.textContent.includes('Return its kit'));
          assert(!findButton(ctx.sheet.foot,'Retire deck'));await sendRetireDeck(ctx);same(requests,[]);ctx.sheet.close();
          answerRead=async()=>{throw Object.assign(new Error('Database unavailable'),{status:503});};
          ctx=await openRetirement();assert(ctx.sheet.body.textContent.includes('Database unavailable'));
          assert(!findButton(ctx.sheet.foot,'Retire deck'));await sendRetireDeck(ctx);same(requests,[]);
        """)

    def test_invalid_or_replaced_metadata_fails_closed_before_any_post(self):
        self.run_js(r"""
          for(const extra of [{id:'casual/other'},{revision:0},{revision:'7'},{sha256:'a'.repeat(40)},
              {status:'built'},{may_retire:false}]) {
            answerRead=async()=>metadata(extra);const ctx=await openRetirement();
            assert(!findButton(ctx.sheet.foot,'Retire deck'));await sendRetireDeck(ctx);
            same(requests,[]);ctx.sheet.close();
          }
          answerRead=async()=>metadata();const ctx=await openRetirement();ready(ctx);
          state.may={admin:false,deck_spaces:['user2']};await sendRetireDeck(ctx);same(requests,[]);
        """)

    def test_retirement_is_single_flight_and_reason_cannot_change_while_saving(self):
        self.run_js(r"""
          const pending=held();answerWrite=()=>pending.promise;
          const ctx=await openRetirement();ready(ctx);const submit=action(ctx,'Retire deck');
          submit.click();submit.click();await sendRetireDeck(ctx);await settle();assert.equal(requests.length,1);
          assert(reason(ctx).disabled);assert(confirm(ctx).disabled);assert(submit.disabled);
          pending.reject(Object.assign(new Error('Database unavailable'),{status:503}));await settle();
          assert.equal(reason(ctx).value,'Prefer the other deck');assert(confirm(ctx).checked);
          assert(!reason(ctx).disabled);assert(!action(ctx,'Retire deck').disabled);
        """)

    def test_duplicate_open_and_closing_during_save_do_not_repeat_the_retirement(self):
        self.run_js(r"""
          const pending=held();answerWrite=()=>pending.promise;
          const data=makePage(),ctx=await openRetirement(data);assert.equal(openRetireDeck(data),ctx);
          ready(ctx);action(ctx,'Retire deck').click();await settle();ctx.sheet.close();
          await sendRetireDeck(ctx);assert.equal(requests.length,1);state.library={decks:['old']};
          pending.resolve(retired());await settle();assert.equal(state.library,null);
          assert.equal(location.hash,deckHistoryHref('casual/test'));
          assert(!main.textContent.includes('Deck retired'));
        """)

    def test_temporary_error_keeps_reason_and_allows_an_explicit_retry(self):
        self.run_js(r"""
          let attempts=0;answerWrite=async()=>{if(!attempts++)throw Object.assign(new Error('Try again later'),{status:503});return retired();};
          const ctx=await openRetirement();ready(ctx);action(ctx,'Retire deck').click();await settle();
          assert(ctx.sheet.body.textContent.includes('Try again later'));assert.equal(reason(ctx).value,'Prefer the other deck');
          action(ctx,'Retire deck').click();await settle();assert.equal(requests.length,2);
          assert(main.textContent.includes('Deck retired'));assert(ctx.sheet.closed);
        """)

    def test_conflict_preserves_reason_but_old_revision_cannot_be_retried(self):
        self.run_js(r"""
          answerWrite=async()=>{throw Object.assign(new Error('Deck changed elsewhere'),{status:409});};
          const ctx=await openRetirement();ready(ctx);const submit=action(ctx,'Retire deck');submit.click();await settle();
          assert(ctx.sheet.body.textContent.includes('Deck changed elsewhere'));
          assert.equal(reason(ctx).value,'Prefer the other deck');assert(confirm(ctx).checked);
          submit.click();await sendRetireDeck(ctx);await settle();assert.equal(requests.length,1);
          answerRead=async()=>metadata({sha256:'b'.repeat(64),revision:9});
          action(ctx,'Review latest deck').click();await settle();
          assert.equal(reason(ctx).value,'Prefer the other deck');assert(!confirm(ctx).checked);
          assert(action(ctx,'Retire deck').disabled);acknowledge(ctx);assert(!action(ctx,'Retire deck').disabled);
          action(ctx,'Retire deck').click();await settle();assert.equal(requests.length,2);
          assert.equal(requests[1][1].sha256,'b'.repeat(64));assert.equal(requests[1][1].revision,9);
        """)

    def test_late_metadata_cannot_populate_a_closed_profile_or_route(self):
        self.run_js(r"""
          for(const leave of [ctx=>ctx.sheet.close(),()=>{state.profile={id:'user1'};},()=>{routeToken++;}]) {
            state.profile=matt;const pending=held();answerRead=()=>pending.promise;
            const data=mount();const ctx=openRetireDeck(data);leave(ctx);
            pending.resolve(metadata());await settle();assert(!ctx.sheet.body.querySelector('input'));
            await sendRetireDeck(ctx);same(requests,[]);closeDeckRetirementSheets();
          }
        """)

    def test_late_success_invalidates_library_without_drawing_over_another_page(self):
        self.run_js(r"""
          for(const leave of [()=>{state.profile={id:'user1'};},()=>{routeToken++;},()=>{location.hash='#/activity';}]) {
            state.profile=matt;const pending=held();answerRead=async()=>metadata();answerWrite=()=>pending.promise;
            const ctx=await openRetirement();ready(ctx);action(ctx,'Retire deck').click();await settle();
            leave();clear(main).append(el('p',{text:'Another page'}));state.library={decks:['stale']};
            pending.resolve(retired());await settle();assert.equal(state.library,null);
            assert.equal(main.textContent,'Another page');closeDeckRetirementSheets();
          }
        """)

    def test_app_route_profile_and_away_cleanup_close_retirement_dialogs(self):
        self.run_js(r"""
          let ctx=await openRetirement();location.hash='#/history?id=casual%2Ftest';
          answerRead=async()=>retained();noteVisit=()=>{};await route();await settle();assert(ctx.sheet.closed);
          answerRead=async()=>metadata();ctx=await openRetirement();drawWho();assert(ctx.sheet.closed);
          state.profile=matt;ctx=await openRetirement();state.remote=false;
          awayTooLong=()=>true;isMyDevice=()=>false;backFromAway();await settle();assert(ctx.sheet.closed);
          const count=requests.length;ready(ctx);await sendRetireDeck(ctx);assert.equal(requests.length,count);
        """)

    def test_retired_history_exposes_saved_list_read_only_and_a_separate_restore_action(self):
        self.run_js(r"""
          location.hash='#/history?id=casual%2Ftest';const data=retained();historyDraw(data,data.id,'target',routeToken);
          assert(main.textContent.toLowerCase().includes('retired'));assert(findButton(main,'Restore deck'));
          const item=main.querySelectorAll('.history-open')[0];assert(item);item.click();const sheet=latest();
          assert(!sheet.body.textContent.includes('Compare with the deck now'));
          assert(!sheet.foot.textContent.includes('Open planned list as a draft'));
          assert(sheet.body.textContent.includes('View saved list')||sheet.foot.textContent.includes('View saved list'));
          answerRead=async()=>({current:null,sections:{Deck:[{qty:1,name:'Elf',card:elf}]},warnings:[]});
          const saved=sheet.body.querySelector('details');saved.open=true;saved.fire('toggle');await settle();
          assert(sheet.body.textContent.includes('Elf'));assert(sheet.body.textContent.includes('Restore the deck from History'));
          assert.equal(editor,null);
          sheet.close();clear(main);historyDraw(retained({may_restore:false}),data.id,'target',routeToken);
          assert(!findButton(main,'Restore deck'));same(requests,[]);
        """)

    def test_restore_requires_confirmation_and_binds_the_retirement_revision(self):
        self.run_js(r"""
          location.hash='#/history?id=casual%2Ftest';const data=retained();historyDraw(data,data.id,'target',routeToken);
          answerWrite=async()=>({restored:true,id:data.id,title:data.title});
          const ctx=openRestoreDeck(data);assert(ctx&&ctx.sheet);same(requests,[]);
          assert(ctx.sheet.heading.textContent.includes('Test Deck'));
          assert(ctx.sheet.body.textContent.includes('whole deck'));
          action(ctx,'Restore deck').click();await settle();
          same(requests,[['/api/deck/restore',{profile:'matt',id:'casual/test',retired_revision:7}]]);
          assert.equal(location.hash,deckHref('casual/test'));assert(ctx.sheet.closed);
        """)

    def test_restore_is_single_flight_retries_temporary_errors_and_locks_on_conflict(self):
        self.run_js(r"""
          location.hash=deckHistoryHref('casual/test');const data=retained();
          const pending=held();answerWrite=()=>pending.promise;const ctx=openRestoreDeck(data);
          const submit=action(ctx,'Restore deck');submit.click();submit.click();await sendRestoreDeck(ctx);
          assert.equal(requests.length,1);assert(submit.disabled);
          pending.reject(Object.assign(new Error('Database unavailable'),{status:503}));await settle();
          assert(ctx.sheet.body.textContent.includes('Database unavailable'));assert(!action(ctx,'Restore deck').disabled);
          answerWrite=async()=>{throw Object.assign(new Error('Deck was already restored'),{status:409});};
          action(ctx,'Restore deck').click();await settle();assert.equal(requests.length,2);
          assert(ctx.sheet.body.textContent.includes('Deck was already restored'));
          assert(!findButton(ctx.sheet.foot,'Restore deck'));assert(findButton(ctx.sheet.foot,'Reload history'));
          submit.click();await sendRestoreDeck(ctx);assert.equal(requests.length,2);
          ctx.sheet.close();assert.equal(openRestoreDeck(retained({may_restore:false})),null);
          assert.equal(openRestoreDeck(retained({retired:false})),null);
        """)

    def test_retired_revision_editor_url_explains_the_history_return(self):
        self.run_js(r"""
          const sections={Deck:[{qty:1,name:'Elf',set:'fdn',number:'1',finish:'nonfoil',card:elf}]};
          answerRead=async()=>({id:'casual/test',title:'Test Deck',revision:6,version:'target',retired:true,
            current:null,sections,warnings:[]});
          location.hash='#/edit?id=casual%2Ftest&revision=6';
          showRevisionEditor(parseHash().params,routeToken);await settle();
          assert.equal(editor,null);assert(main.textContent.includes('This deck is retired'));
          assert(main.querySelectorAll('a').some(a=>a.getAttribute('href')===deckHistoryHref('casual/test')));
          assert(!findButton(main,'Save'));same(requests,[]);
        """)

    def test_activity_delete_rows_and_history_headlines_keep_a_working_history_link(self):
        self.run_js(r"""
          assert.equal(activityLink({history:'casual/test'}),'#/history?id=casual%2Ftest');
          assert.equal(activityLink({deck:'casual/live'}),deckHref('casual/live'));
          const retiredRow={table:'deck',op:'DELETE',summary:'Retired Test Deck',before:{id:'casual/test',title:'Test Deck'},after:null};
          const link=activityRow(retiredRow,{id:1},{cards:{}});assert.equal(link.tag,'a');
          assert.equal(link.getAttribute('href'),'#/history?id=casual%2Ftest');assert.equal(link.textContent,'Retired Test Deck');
        """)

    def test_reason_length_matches_backend_and_is_checked_before_posting(self):
        self.run_js(r"""
          const ctx=await openRetirement();assert.equal(reason(ctx).getAttribute('maxlength'),'1000');
          typeReason(ctx,'x'.repeat(1001));acknowledge(ctx);await sendRetireDeck(ctx);
          assert.equal(requests.length,0);assert(ctx.sheet.body.textContent.includes('at most 1,000'));
          typeReason(ctx,'x'.repeat(1000));await sendRetireDeck(ctx);
          assert.equal(requests.length,1);assert.equal(requests[0][1].reason.length,1000);
        """)

    def test_uncertain_save_and_missing_review_offer_history_without_claiming_success(self):
        self.run_js(r"""
          const ctx=await openRetirement();ready(ctx);state.library={cached:true};
          answerWrite=async()=>{throw new Error('Connection lost after sending');};await sendRetireDeck(ctx);
          assert.equal(state.library,null);
          assert(!ctx.done);assert(!main.textContent.includes('Deck retired'));
          assert(ctx.sheet.body.querySelectorAll('a').some(a=>a.getAttribute('href')===deckHistoryHref(ctx.id)));
          answerWrite=async()=>{throw Object.assign(new Error('No current deck'),{status:404});};await sendRetireDeck(ctx);
          assert(ctx.conflict);assert(!ctx.done);assert(findButton(ctx.sheet.foot,'Review latest deck'));
          answerRead=async()=>{throw Object.assign(new Error('No current deck'),{status:404});};
          action(ctx,'Review latest deck').click();await settle();
          assert(ctx.sheet.body.querySelectorAll('a').some(a=>a.textContent==='View retained history'));
          assert(!ctx.sheet.body.textContent.includes('has left the library'));assert.equal(requests.length,2);
        """)

    def test_late_restore_failure_still_invalidates_library_without_affecting_another_profile(self):
        self.run_js(r"""
          mount();const ctx=openRestoreDeck(retained()),pending=held();answerWrite=()=>pending.promise;
          const saving=sendRestoreDeck(ctx);state.library={cached:true};closeDeckRetirementSheets();
          state.profile={id:'user2',name:'User2'};clear(main).append(el('p',{text:'User2 view'}));
          pending.reject(new Error('Connection lost after restore'));await saving;
          assert.equal(state.library,null);assert.equal(main.textContent,'User2 view');assert.equal(messages.length,0);
          assert.equal(document.body.querySelectorAll('dialog').length,0);
        """)


if __name__ == "__main__":
    unittest.main()
