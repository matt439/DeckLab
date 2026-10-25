"""Per-run Stop controls and anonymous admin controls over the real page scripts.

The deterministic DOM/API double never starts Forge or touches the database.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = """
  const member = {id: 'user2', name: 'User2', role: 'member', space: 'user2'};
  const admin = {id: 'matt', name: 'Matt', role: 'admin', space: 'home'};
  state.profile = member; state.may = {admin: false, runs: false};
  const sides = [{id: 'user2/casual/a', title: 'A'}, {id: 'user2/casual/b', title: 'B'}];
  const liveData = (may_stop) => ({status: 'running', key: 'opaque', sides,
    job: {status: 'running', may_stop, done: 1, total: 4, pairs: {}, wins: [1, 0]}});
  const hiddenRun = (key = 'field:opaque') => ({key, kind: 'field', title: "A run of one of User4's decks",
    status: 'running', may_stop: true, hidden: true, sides: null, link: null, done: 1, total: 4, by: 'someone'});
  const button = (root, text = 'Stop') => root.querySelectorAll('button').find((b) => b.textContent === text);
  const host = el('div', {id: 'shell-status'}); document.body.append(host);
  async function flush() { for (let n = 0; n < 20; n++) await Promise.resolve(); }
  function target(kind) {
    const data = liveData(true), page = {token: routeToken, data, test: 'test:opaque'};
    const stop = el('button', {text: 'Stop'}); main.append(stop);
    if (kind === 'matchup') return {rights: data.job, call: () => stopRun(page, stop)};
    if (kind === 'field') return {rights: data.job, call: () => fvStop({token: routeToken,
      id: sides[0].id, version: 'target', answer: data})};
    if (kind === 'variant') return {rights: data.job, call: () => vtStop(page)};
    const run = hiddenRun();
    return {rights: run, call: () => stopListedRun(run, stop)};
  }
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ForgeStopUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_server_decision_controls_each_live_panel_with_legacy_admin_fallback(self):
        self.run_js("""
          assert.equal(mayStopRuns({may_stop: true}), true);
          assert.equal(mayStopRuns({may_stop: false}), false);
          assert.equal(mayStopRuns(), false);
          for (const profile of [member, admin]) {
            state.profile = profile;
            for (const allowed of [true, false]) {
              const data = liveData(allowed), box = liveBox({token: routeToken, data});
              box.update(data);
              assert.equal(box.node.querySelector('.actions').hidden, !allowed);
              assert.equal(!!button(el('div', {}, fvLive({}, data))), allowed);
              assert.equal(!!button(vtLivePanel({}, data)), allowed);
            }
          }
          state.profile = admin;
          assert.equal(mayStopRuns(), true);
          state.profile = null;
          assert.equal(mayStopRuns({may_stop: true}), false);
        """)

    def test_anonymous_admin_row_and_activity_offer_stop_without_a_private_link(self):
        self.run_js("""
          state.profile = admin;
          const run = hiddenRun(), row = runningRow(run); main.append(row);
          assert(row.textContent.includes(run.title));
          assert.equal(row.querySelectorAll('a').length, 0);
          assert(button(row));
          // The top bar shows only the activity icon; its details (a sheet below 1,000 px) hold the run.
          noteRuns([run]);
          const icon = host.querySelector('.run-activity');
          assert.equal(icon.getAttribute('aria-label'), 'Forge is playing: show progress');
          assert(!host.textContent.includes(run.title));
          icon.click();
          assert.equal(icon.getAttribute('aria-expanded'), 'true');
          // Below 1,000 px a sheet, not the lab's popover in the slot.
          assert.equal(window.matchMedia('(min-width: 1000px)').matches, false);
          assert.equal(host.querySelector('#run-details'), null);
          const details = document.querySelector('#run-details');
          assert(details.getAttribute('class').includes('run-sheet'));
          assert(!details.getAttribute('class').includes('run-popover'));
          assert(details.textContent.includes(run.title));
          assert.equal(button(details).getAttribute('aria-label'), 'Stop the Forge run');
          same(details.querySelectorAll('a').map((a) => a.getAttribute('href')), ['#/matchups']);
          assert.equal(details.querySelector('.run-summary').getAttribute('role'), 'status');
          assert(!details.textContent.includes(run.key));
          run.may_stop = false;
          noteRuns([run]);
          assert.equal(button(details), undefined);
          assert.equal(button(runningRow(run)), undefined);
          // Several anonymous runs: no private links, and the combined list on Matchups.
          noteRuns([hiddenRun(), hiddenRun('variant:opaque')]);
          same(details.querySelectorAll('a').map((a) => a.getAttribute('href')), ['#/matchups']);
          // Nothing left running: the details close and the icon goes.
          noteRuns([]);
          assert.equal(document.querySelector('#run-details'), null);
          assert.equal(host.hidden, true);
        """)

    def test_the_details_are_a_popover_from_1000_px(self):
        self.run_js("""
          state.profile = admin;
          window.matchMedia('(min-width: 1000px)').matches = true;
          const run = hiddenRun();
          noteRuns([run]);
          const icon = host.querySelector('.run-activity');
          icon.click();
          const pop = host.querySelector('#run-details');
          assert(pop, 'a popover in the slot, under the icon');
          assert.equal(pop.getAttribute('class'), 'run-details run-popover');
          assert(pop.textContent.includes(run.title));
          // Escape closes it and gives the icon the focus back; the icon opens it again.
          document.fire('keydown', {key: 'Escape'});
          assert.equal(host.querySelector('#run-details'), null);
          assert.equal(icon.getAttribute('aria-expanded'), 'false');
          assert.equal(document.activeElement, icon);
          icon.click();
          assert(host.querySelector('#run-details'));
          // Not the Escape that closes Stop's question over it (from the dialog, already handled, or while it's
          // open): that would leave the question asking about a Stop that's gone.
          const dialog = el('dialog'), inside = el('button'); dialog.append(inside); document.body.append(dialog);
          assert.equal(document.fire('keydown', {key: 'Escape', target: inside}).defaultPrevented, false);
          document.fire('keydown', {key: 'Escape', defaultPrevented: true});
          runsPill.stopping = true;
          document.fire('keydown', {key: 'Escape'});
          runsPill.stopping = false;
          assert(host.querySelector('#run-details'));
          // A click elsewhere closes it, but not one in Stop's question (a dialog) over it.
          document.fire('pointerdown', {target: inside});
          assert(host.querySelector('#run-details'));
          document.fire('pointerdown', {target: main});
          assert.equal(host.querySelector('#run-details'), null);
          // Another page closes it too.
          icon.click();
          location.hash = '#/collection';
          syncRunsPill();
          assert.equal(host.querySelector('#run-details'), null);
        """)

    def test_the_details_keep_the_focus_when_they_redraw(self):
        self.run_js("""
          state.profile = admin;
          window.matchMedia('(min-width: 1000px)').matches = true;
          const run = {...hiddenRun(), hidden: false, link: '#/matchup?key=opaque'};
          noteRuns([run]);
          host.querySelector('.run-activity').click();
          const pop = host.querySelector('#run-details');
          const part = (key) => pop.querySelectorAll('[data-focus]').find((n) => n.getAttribute('data-focus') === key);
          // Each ask rebuilds the details: the link or button that had the focus has it again.
          const stop = part('field:opaque:stop'); stop.focus();
          noteRuns([{...run}]);
          assert.notEqual(part('field:opaque:stop'), stop);
          assert.equal(document.activeElement, part('field:opaque:stop'));
          part('field:opaque:open').focus();
          noteRuns([{...run}]);
          assert.equal(document.activeElement, part('field:opaque:open'));
          part('matchups').focus();
          noteRuns([{...run}]);
          assert.equal(document.activeElement, part('matchups'));
          // Gone (no Stop any more): the first part has it.
          part('field:opaque:stop').focus();
          noteRuns([{...run, may_stop: false}]);
          assert.equal(part('field:opaque:stop'), undefined);
          assert.equal(document.activeElement, part('field:opaque:open'));
          // Focus elsewhere on the page stays where it is.
          const elsewhere = el('button'); main.append(elsewhere); elsewhere.focus();
          noteRuns([{...run}]);
          assert.equal(document.activeElement, elsewhere);
        """)

    def test_stop_in_the_details_asks_and_keeps_its_button_while_asking(self):
        self.run_js("""
          state.profile = admin;
          const calls = []; let confirm;
          ask = () => new Promise((resolve) => { confirm = resolve; });
          apiWrite = async (url, body) => { calls.push([url, body]); return {stopped: true}; };
          syncRunsPill = () => {};
          const run = hiddenRun('opaque-matchup');
          noteRuns([run]);
          host.querySelector('.run-activity').click();
          const details = document.querySelector('#run-details');
          const pending = button(details).click();
          await flush();
          // A refresh while the question is open doesn't replace the button its answer needs.
          const stop = button(details);
          noteRuns([{...run}]);
          assert.equal(button(details), stop);
          confirm('stop'); await flush();
          same(calls, [['/api/matchup/stop', {key: 'opaque-matchup'}]]);
        """)

    def test_anonymous_stop_uses_only_the_opaque_key_for_each_run_kind(self):
        self.run_js("""
          state.profile = admin;
          const calls = [], questions = []; let refreshed = 0;
          ask = async (title, parts) => { questions.push([title, parts]); return 'stop'; };
          apiWrite = async (url, body) => { calls.push([url, body]); return {stopped: true, hidden: true}; };
          syncRunsPill = () => { refreshed++; };
          for (const key of ['opaque-matchup', 'field:opaque', 'variant:opaque']) {
            const run = hiddenRun(key), stop = listedRunStop(run); main.append(stop);
            await stopListedRun(run, stop);
          }
          same(calls, ['opaque-matchup', 'field:opaque', 'variant:opaque'].map((key) => ['/api/matchup/stop', {key}]));
          assert.equal(refreshed, 3);
          questions.forEach(([title, parts]) => {
            assert.equal(title, 'Stop this run?');
            assert(parts.includes("A run of one of User4's decks"));
            assert(!parts.join(' ').includes('opaque'));
          });
        """)

    def test_stop_rechecks_rights_person_and_route_after_confirmation(self):
        self.run_js("""
          const calls = []; apiWrite = async (...args) => { calls.push(args); return {}; };
          for (const kind of ['matchup', 'field', 'variant', 'listed']) {
            for (const change of ['person', 'route', 'rights']) {
              clear(main); state.profile = member;
              const current = target(kind); let confirm;
              ask = () => new Promise((resolve) => { confirm = resolve; });
              const pending = current.call(); assert(confirm, kind);
              if (change === 'person') state.profile = admin;
              if (change === 'route') routeToken++;
              if (change === 'rights') current.rights.may_stop = false;
              confirm('stop'); await pending;
              assert.equal(calls.length, 0, kind + ': ' + change);
            }
          }
        """)

    def test_eligible_member_can_stop_on_each_page_even_when_starting_is_paused(self):
        self.run_js("""
          const calls = []; let drawn = 0;
          ask = async () => 'stop';
          apiWrite = async (...args) => { calls.push(args); return {status: 'done'}; };
          apply = () => { drawn++; }; fvDraw = () => { drawn++; }; vtDraw = () => { drawn++; };
          fvSchedule = () => {}; syncRunsPill = () => {};
          for (const kind of ['matchup', 'field', 'variant']) await target(kind).call();
          same(calls, [
            ['/api/matchup/stop', {key: 'opaque'}],
            ['/api/field/stop', {id: sides[0].id, version: 'target'}],
            ['/api/variant/stop', {test: 'test:opaque'}]]);
          assert.equal(drawn, 3);
          let asked = 0; ask = async () => { asked++; return 'stop'; };
          for (const kind of ['matchup', 'field', 'variant', 'listed']) {
            const denied = target(kind); denied.rights.may_stop = false;
            await denied.call();
          }
          assert.equal(asked, 0); assert.equal(calls.length, 3);
        """)

    def test_stale_stop_responses_do_not_draw_or_toast_in_another_persons_page(self):
        self.run_js("""
          let drawn = 0, notices = 0, refreshed = 0;
          apply = () => { drawn++; }; fvDraw = () => { drawn++; }; vtDraw = () => { drawn++; };
          toast = () => { notices++; }; syncRunsPill = () => { refreshed++; };
          ask = async () => 'stop';
          for (const kind of ['matchup', 'field', 'variant', 'listed']) {
            for (const failed of [false, true]) {
              clear(main); state.profile = member; const current = target(kind); let finish;
              apiWrite = () => new Promise((resolve, reject) => { finish = failed ? reject : resolve; });
              const pending = current.call(); await flush(); assert(finish, kind);
              state.profile = admin;
              finish(failed ? new Error('An old response') : {}); await pending;
              assert.equal(drawn, 0, kind); assert.equal(notices, 0, kind); assert.equal(refreshed, 0, kind);
            }
          }
        """)

    def test_anonymous_stop_does_not_post_if_the_run_ends_while_confirming(self):
        self.run_js("""
          state.profile = admin;
          const run = hiddenRun(), stop = listedRunStop(run); main.append(stop);
          let confirm, writes = 0;
          ask = () => new Promise((resolve) => { confirm = resolve; });
          apiWrite = async () => { writes++; return {}; };
          const pending = stopListedRun(run, stop);
          run.status = 'done'; confirm('stop'); await pending;
          assert.equal(writes, 0);
        """)

    def test_a_late_running_list_never_crosses_the_person_switch(self):
        self.run_js("""
          syncRunsPill();
          let finish, request;
          api = (url, options) => { request = options; return new Promise((resolve) => { finish = resolve; }); };
          const pending = askRunsPill();
          state.profile = admin;
          syncRunsPill();
          assert.equal(request.signal.aborted, true);
          finish({running: [{...hiddenRun(), title: 'Previous person only'}]}); await pending;
          assert.equal(runsPill.profile, admin.id);
          assert.equal(runsPill.running.length, 0);
          assert(!host.textContent.includes('Previous person only'));
        """)
