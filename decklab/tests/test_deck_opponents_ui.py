"""Usual-opponent links and metadata sheets over the real scripts and fixture APIs."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  as('matt', MAY.admin);
  const other = {id: 'casual/other', title: 'Other Deck'};
  const third = {id: 'casual/third', title: 'Third Deck'};
  const page = () => ({summary: {id: 'casual/test', title: 'Test Deck', space: 'home', player: 'user', read_only: false},
    usual_opponents: [other]});
  const answer = () => ({id: 'casual/test', title: 'Test Deck', sha256: 'sha-1',
    opponents: [other.id], choices: [other, third], inherited: [], editable: true});
  const check = (sheet, n, value) => { const box = sheet.body.querySelectorAll('input')[n]; box.checked = value; box.fire('change'); };
  const show = async (result = answer()) => {
    api = async path => { assert.equal(path, '/api/deck/opponents?id=casual%2Ftest'); return result; };
    const ctx = openDeckOpponents('casual/test'); await flush(); return ctx;
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckOpponentsUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_overview_links_use_resolved_titles_and_update_after_save(self):
        self.run_js("""
          const p = page(); main.append(deckOpponentsSection(p));
          const section = main.querySelector('#sec-opponents');
          assert.equal(section.querySelector('a').getAttribute('href'), deckHref(other.id));
          assert.equal(section.querySelector('a').textContent, other.title);
          api = async () => answer();
          const writes = []; apiWrite = async (path, body) => {
            writes.push({path, body}); return {saved: true, usual_opponents: [third], sha256: 'sha-2'};
          };
          state.library = {old: true}; button(section, 'Choose usual opponents').click(); await flush();
          const sheet = [...deckOpponentSheets][0]; check(sheet, 0, false); check(sheet, 1, true);
          button(sheet.foot, 'Save').click(); await flush();
          same(writes, [{path: '/api/deck/opponents', body: {id: 'casual/test', sha256: 'sha-1', opponents: [third.id]}}]);
          assert(sheet.closed); assert.equal(state.library, null); assert.equal(deckOpponentSheets.size, 0);
          assert.equal(section.querySelector('a').textContent, third.title);
          same(p.summary.usual_opponents, [third.id]);
        """)

    def test_empty_and_read_only_sections_offer_only_permitted_actions(self):
        self.run_js("""
          const p = page(); p.usual_opponents = [];
          let section = deckOpponentsSection(p); assert(section.textContent.includes('No usual opponents chosen'));
          assert(button(section, 'Choose usual opponents'));
          p.summary.read_only = true; assert.equal(deckOpponentsSection(p), null);
          p.usual_opponents = [other]; section = deckOpponentsSection(p);
          assert.equal(section.querySelector('a').textContent, other.title); assert(!section.querySelector('button'));
          p.summary.read_only = false; as('user1', MAY.user1);
          section = deckOpponentsSection(p); assert(!section.querySelector('button'));
        """)

    def test_unchanged_selection_does_not_write_and_inherited_links_are_explained(self):
        self.run_js("""
          const a = answer(); a.inherited = [third]; const {sheet} = await show(a);
          assert.equal(button(sheet.foot, 'Save').disabled, true);
          assert(sheet.body.textContent.includes('Also linked from'));
          assert(sheet.body.textContent.includes('Change them there'));
          assert.equal(sheet.body.querySelector('a').getAttribute('href'), deckHref(third.id));
          check(sheet, 0, false); assert.equal(button(sheet.foot, 'Save').disabled, false);
          check(sheet, 0, true); assert.equal(button(sheet.foot, 'Save').disabled, true);
          let writes = 0; apiWrite = async () => { writes++; };
          button(sheet.foot, 'Save').click(); assert.equal(writes, 0);
        """)

    def test_save_is_single_flight_and_keeps_choices_after_network_failure(self):
        self.run_js("""
          const ctx = await show(), {sheet} = ctx; check(sheet, 1, true);
          let reject, calls = 0; apiWrite = () => { calls++; return new Promise((resolve, fail) => { reject = fail; }); };
          const save = button(sheet.foot, 'Save'); save.click(); save.click();
          assert.equal(calls, 1); assert(sheet.body.querySelectorAll('input').every(box => box.disabled));
          reject(new ApiError(503, 'Database unavailable')); await flush();
          assert(sheet.body.textContent.includes('Database unavailable')); assert(!sheet.closed);
          assert.equal(sheet.body.querySelectorAll('input')[1].checked, true);
          assert.equal(button(sheet.foot, 'Save').disabled, false);
          apiWrite = async () => ({saved: true, usual_opponents: [other, third]});
          button(sheet.foot, 'Save').click(); await flush(); assert(sheet.closed);
        """)

    def test_conflict_requires_reloading_without_automatic_overwrite(self):
        self.run_js("""
          const {sheet} = await show(); check(sheet, 1, true); let calls = 0;
          apiWrite = async () => { calls++; throw new ApiError(409, 'Deck changed elsewhere'); };
          button(sheet.foot, 'Save').click(); await flush();
          assert.equal(calls, 1); assert(!button(sheet.foot, 'Save'));
          assert(sheet.body.textContent.includes('Reload the choices, then choose again'));
          assert(sheet.body.querySelectorAll('input').every(box => box.disabled));
          api = async () => ({...answer(), sha256: 'sha-new', opponents: [third.id]});
          button(sheet.foot, 'Reload choices').click(); await flush();
          assert.equal(sheet.body.querySelectorAll('input')[0].getAttribute('checked'), null);
          assert.equal(sheet.body.querySelectorAll('input')[1].getAttribute('checked'), '');
          assert.equal(button(sheet.foot, 'Save').disabled, true);
        """)

    def test_failed_load_retries_and_read_only_answer_never_saves(self):
        self.run_js("""
          api = async () => { throw new ApiError(503, 'Cannot read choices'); };
          const {sheet} = openDeckOpponents('casual/test'); await flush();
          assert(sheet.body.textContent.includes('Cannot read choices'));
          api = async () => ({...answer(), editable: false, why_not: 'This deck belongs to another player'});
          button(sheet.foot, 'Try again').click(); await flush();
          assert(sheet.body.textContent.includes('another player')); assert(!button(sheet.foot, 'Save'));
          assert(sheet.body.querySelectorAll('input').every(box => box.disabled));
        """)

    def test_late_reads_after_navigation_or_profile_switch_are_ignored(self):
        self.run_js("""
          for (const leave of [() => { routeToken++; closeDeckOpponentSheets(); }, () => drawWho()]) {
            as('matt', MAY.admin); let resolve;
            api = () => new Promise(done => { resolve = done; });
            const {sheet} = openDeckOpponents('casual/test'); leave();
            assert(sheet.closed); assert.equal(deckOpponentSheets.size, 0);
            resolve(answer()); await flush(); assert(!document.querySelector('dialog'));
          }
        """)

    def test_late_save_does_not_update_or_notify_another_profile(self):
        self.run_js("""
          let changed = 0, notices = []; toast = text => notices.push(text);
          api = async () => answer(); const ctx = openDeckOpponents('casual/test', () => changed++); await flush();
          check(ctx.sheet, 1, true); let resolve;
          apiWrite = () => new Promise(done => { resolve = done; });
          button(ctx.sheet.foot, 'Save').click();
          state.profile = PROFILES[1]; closeDeckOpponentSheets(); state.library = {belongs: 'user1'};
          resolve({saved: true, usual_opponents: [third]}); await flush();
          assert.equal(changed, 0); same(notices, []); same(state.library, {belongs: 'user1'});
        """)

    def test_detached_overview_button_cannot_open_an_old_deck_sheet(self):
        self.run_js("""
          const section = deckOpponentsSection(page()); main.append(section);
          const choose = button(section, 'Choose usual opponents'); clear(main); choose.click();
          assert.equal(deckOpponentSheets.size, 0); assert(!document.querySelector('dialog'));
        """)
