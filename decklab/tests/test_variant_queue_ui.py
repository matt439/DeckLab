"""Reviewed saved-test queue decisions with real UI code and disposable Node DOM."""
import json
import subprocess
import unittest

from decklab.tests.test_variant_buying_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


QUEUE_SETUP = SETUP + """
  const calls = [];
  const reviewed = (extra = {}) => ({ready: true, preview: 'review-one', expires_in: 600,
    proposal: {name: 'New Card', quantity: '1', state: 'ready', for: 'Example',
      source: 'magic/decks/casual/example.md', notes: 'Saved test #/variant?test=' + 'a'.repeat(64),
      printing: 'any', set: '', collector_number: '', finish: 'nonfoil'},
    test: 'a'.repeat(64), name: 'New Card', deck: {id: 'casual/example', title: 'Example', version: 'target'},
    added: 3, missing_added: 1, basis: 'Current supply checked.', ...extra});
  const saved = () => ({saved: true, test: 'a'.repeat(64), name: 'New Card', quantity: 1, revision: 'new'});
  apiWrite = async (path, body) => {calls.push({path, body}); return path.endsWith('/preview') ? reviewed() : saved();};
  vtRefresh = async page => {page.refreshed = (page.refreshed || 0) + 1;};
  const settle = async () => {for (let n = 0; n < 12; n++) await Promise.resolve();};
  const find = (host, text) => host.querySelectorAll('button').find(button => button.textContent === text);
  const opened = () => {
    const data = answer(), mounted = mount(data), trigger = mounted.section.querySelector('.vt-queue-add');
    trigger.fire('click'); return {...mounted, data, trigger, sheet: mounted.page.queueSheet};
  };
  const reviewNow = async sheet => {find(sheet.foot, 'Review request').fire('click'); await settle();};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class VariantQueueUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), QUEUE_SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_review_then_one_explicit_save_uses_only_server_receipt(self):
        self.run_js("""
          const {page, sheet, trigger} = opened(); assert(sheet); assert.equal(calls.length, 0);
          await reviewNow(sheet); assert.equal(calls.length, 1);
          assert.equal(calls[0].path, '/api/variant/queue/preview');
          assert.deepEqual(calls[0].body.choice, {printing:'any', set:'', collector_number:'', finish:'nonfoil'});
          const text = sheet.body.textContent;
          for (const words of ['1 copy of New Card', 'any printing, nonfoil', 'Ready to buy', 'Example', 'this saved test',
            'Current supply checked.', "Check a shop's current price"]) assert(text.includes(words));
          const button = find(sheet.foot, 'Add to Shopping'); button.fire('click'); button.fire('click'); await settle();
          assert.equal(calls.length, 2); assert.equal(calls[1].path, '/api/variant/queue');
          assert.deepEqual(calls[1].body, {preview: 'review-one'});
          assert(sheet.body.textContent.includes('1 copy of New Card added to Shopping'));
          assert.equal(trigger.disabled, true); assert.equal(page.refreshed, 1);
          assert(!find(sheet.foot, 'Add to Shopping')); find(sheet.foot, 'Done').fire('click'); assert(sheet.closed);
        """)

    def test_exact_printing_and_finish_are_reviewed_and_can_reset_to_default(self):
        self.run_js("""
          pickPrinting = async () => ({set:'tst', number:'7', finish:'etched'});
          const {sheet} = opened(); find(sheet.body, 'Choose exact printing').fire('click'); await settle();
          assert(sheet.body.textContent.includes('TST 7, etched'));
          apiWrite = async (path, body) => {calls.push({path,body}); return reviewed({proposal:{...reviewed().proposal,...body.choice}});};
          await reviewNow(sheet); assert.equal(calls[0].body.choice.printing, 'exact');
          assert.equal(calls[0].body.choice.finish, 'etched'); assert(sheet.body.textContent.includes('TST 7, etched'));
          const oldSave = find(sheet.foot, 'Add to Shopping'); find(sheet.foot, 'Change request').fire('click');
          oldSave.fire('click'); assert.equal(calls.length, 1);
          find(sheet.body, 'Any printing, nonfoil').fire('click'); await reviewNow(sheet);
          assert.deepEqual(calls[1].body.choice, {printing:'any', set:'', collector_number:'', finish:'nonfoil'});
        """)

    def test_queued_or_unknown_rows_and_nonadmins_have_no_queue_control(self):
        self.run_js("""
          const queued = answer(); queued.buying.rows[0].queued = [{quantity:2,state:'deferred',finish:'foil'}];
          assert(!mount(queued).section.querySelector('.vt-queue-add'));
          for (const changes of [{ready:false}, {availability_ready:false}, {queue_ready:false}]) {
            assert(!mount(answer(buying(changes))).section.querySelector('.vt-queue-add'));
          }
          const covered = answer(); covered.buying.rows[0].missing_added = 0;
          assert(!mount(covered).section.querySelector('.vt-queue-add'));
          state.profile = {id:'user1',role:'member',space:'home'}; state.may = deriveMay(state.profile,false);
          assert(!mount(answer()).section.querySelector('.vt-queue-add')); assert.equal(calls.length,0);
        """)

    def test_new_existing_intent_response_is_read_only_with_context(self):
        self.run_js("""
          apiWrite = async () => {calls.push('preview'); return {ready:false, reason:'Already queued.', omitted:2,
            existing:[{quantity:4,state:'long_term',purpose:'Another deck',printing:'exact',set:'tst',collector_number:'9',finish:'foil'}]};};
          const {sheet} = opened(); await reviewNow(sheet);
          const text = sheet.body.textContent; assert(text.includes('Already queued.'));
          assert(text.includes('4 copies: Long term for Another deck; TST 9, foil'));
          assert(text.includes('2 additional requests omitted')); assert(!find(sheet.foot,'Add to Shopping'));
          assert.equal(calls.length,1);
        """)

    def test_pending_preview_blocks_repeated_or_detached_control_invocations(self):
        self.run_js("""
          const pending = deferred(); apiWrite = (path, body) => {calls.push({path,body}); return pending.promise;};
          const {sheet,trigger} = opened(), old = find(sheet.foot,'Review request');
          old.fire('click'); old.fire('click'); trigger.fire('click');
          find(sheet.body,'Any printing, nonfoil').fire('click'); assert.equal(calls.length,1);
          pending.resolve(reviewed()); await settle(); old.fire('click'); assert.equal(calls.length,1);
          assert(find(sheet.foot,'Add to Shopping'));
        """)

    def test_late_preview_does_not_enter_closed_or_other_profile_route_or_new_data(self):
        self.run_js("""
          for (const change of ['close','profile','route','data']) {
            state.profile = {id:'matt',role:'admin',space:'home'}; state.may = deriveMay(state.profile,false);
            const pending = deferred(); apiWrite = () => pending.promise;
            const {page,sheet} = opened(); find(sheet.foot,'Review request').fire('click');
            if (change === 'close') sheet.close();
            if (change === 'profile') state.profile = {id:'user2',role:'member',space:'user2'};
            if (change === 'route') routeToken++;
            if (change === 'data') page.data = answer();
            pending.resolve(reviewed()); await settle(); assert(!find(sheet.foot,'Add to Shopping'));
            sheet.close();
          }
        """)

    def test_late_picker_does_not_modify_closed_sheet_or_different_profile(self):
        self.run_js("""
          const pending = deferred(); pickPrinting = () => pending.promise;
          const {sheet} = opened(); find(sheet.body,'Choose exact printing').fire('click');
          state.profile = {id:'user2',role:'member',space:'user2'};
          pending.resolve({set:'tst',number:'9',finish:'foil'}); await settle();
          assert(!sheet.body.textContent.includes('TST 9')); assert.equal(calls.length,0);
        """)

    def test_expired_receipt_requires_review_without_saving(self):
        self.run_js("""
          const before = Date.now; let now = 1000; Date.now = () => now;
          const {sheet} = opened(); await reviewNow(sheet); now += 600001;
          find(sheet.foot,'Add to Shopping').fire('click'); await settle(); Date.now = before;
          assert.equal(calls.length,1); assert(sheet.body.textContent.includes('review expired'));
          assert(find(sheet.foot,'Review request')); assert(!find(sheet.foot,'Add to Shopping'));
        """)

    def test_stale_apply_loses_receipt_and_requires_new_review(self):
        self.run_js("""
          apiWrite = async (path,body) => {calls.push({path,body}); if (path.endsWith('/preview')) return reviewed();
            throw new ApiError(409,'The collection changed. Review again.');};
          const {sheet} = opened(); await reviewNow(sheet); const save = find(sheet.foot,'Add to Shopping');
          save.fire('click'); await settle(); save.fire('click'); await settle();
          assert.equal(calls.length,2); assert(sheet.body.textContent.includes('The collection changed.'));
          assert(!find(sheet.foot,'Add to Shopping')); await reviewNow(sheet); assert.equal(calls.length,3);
        """)

    def test_uncertain_save_says_check_shopping_and_never_replays_receipt(self):
        self.run_js("""
          apiWrite = async (path,body) => {calls.push({path,body}); if (path.endsWith('/preview')) return reviewed();
            throw new ApiError(0,'Disconnected');};
          const {sheet} = opened(); await reviewNow(sheet); const save = find(sheet.foot,'Add to Shopping');
          save.fire('click'); await settle(); save.fire('click'); assert.equal(calls.length,2);
          assert(sheet.body.textContent.includes('The save could not be confirmed. Open Shopping to check'));
          assert(!find(sheet.foot,'Add to Shopping'));
        """)

    def test_apply_response_after_profile_switch_or_close_is_not_shown(self):
        self.run_js("""
          for (const change of ['profile','close','route']) {
            state.profile = {id:'matt',role:'admin',space:'home'}; state.may = deriveMay(state.profile,false);
            const pending = deferred(); apiWrite = async path => path.endsWith('/preview') ? reviewed() : pending.promise;
            const {page,sheet,trigger} = opened(); await reviewNow(sheet); find(sheet.foot,'Add to Shopping').fire('click');
            if (change === 'profile') state.profile = {id:'user2',role:'member',space:'user2'};
            if (change === 'close') sheet.close();
            if (change === 'route') routeToken++;
            pending.resolve(saved()); await settle(); assert(!sheet.body.textContent.includes('added to Shopping.'));
            assert.equal(page.refreshed,undefined); assert.equal(trigger.disabled,false); sheet.close();
          }
        """)

    def test_changed_server_proposal_does_not_enable_save(self):
        self.run_js("""
          apiWrite = async () => reviewed({proposal:{...reviewed().proposal,finish:'foil'}});
          const {sheet} = opened(); await reviewNow(sheet);
          assert(sheet.body.textContent.includes('could not be reviewed')); assert(!find(sheet.foot,'Add to Shopping'));
        """)
