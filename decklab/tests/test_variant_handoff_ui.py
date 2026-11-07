"""Result-to-editor handoffs, permission checks and async ownership over disposable DOM/drafts."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB
from decklab.tests.test_web import _text


SETUP = """
  state.profile = {id: 'user2', role: 'member', space: 'user2'};
  state.may = deriveMay(state.profile, true); routeToken = 19;
  const testId = 'a'.repeat(64), originalHash = '#/variant?test=' + testId;
  location.hash = originalHash;
  const notices = [], stored = new Map();
  toast = words => notices.push(words);
  local.get = key => stored.get(key) || null;
  local.set = (key, value) => stored.set(key, value);
  let writes = 0, prompts = 0;
  apiWrite = () => { writes += 1; throw Error('Handoffs must not save or start games'); };
  ask = async () => { prompts += 1; return 'replace'; };
  const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve = a; reject = b;});
    return {promise, resolve, reject}; };
  const fixture = (id = 'user2/casual/example', version = 'target', may = true) => {
    const data = {status: 'done', may_edit: may, test: {test: testId, base: {id, version, title: 'Example'},
      variant: {changes: {remove: [[1, 'Shock']], add: [[1, 'Opt']]}}}};
    const page = {token: routeToken, profile: state.profile.id, test: testId, data, host: el('div')};
    const panel = vtVerdictPanel(page, data); page.host.append(panel); main.append(page.host);
    const actions = [...panel.querySelectorAll('button')];
    const back = actions.find(b => b.textContent === 'Back to the editor');
    const save = actions.find(b => b.textContent === 'Save this change');
    const lists = {Deck: [{qty: 1, name: 'Shock', set: 'tst', number: '1'}, {qty: 59, name: 'Forest'}],
      Sideboard: [{qty: 1, name: 'Negate'}]};
    const view = {id, kind: vtDeckKind(id), editable: true, may_save: true, sha256: 'saved-sha', fields: {},
      lists: {target: lists, owned: lists}};
    return {page, data, save, back, view, key: `draft.${state.profile.id}.${id}.${version}`};
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class VariantHandoffUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_actions_follow_current_capability_for_home_member_and_generated_ids(self):
        self.run_js("""
          for (const id of ['casual/example', 'commander/example', 'user2/casual/example', 'user2/commander/example']) {
            for (const may of [true, false, undefined, 'true']) {
              const f = fixture(id, 'target', may);
              if (may === undefined) delete f.data.may_edit;
              const panel = vtVerdictPanel(f.page, f.data).textContent;
              assert.equal(panel.includes('Back to the editor'), may === true);
              assert.equal(panel.includes('Save this change'), may === true);
            }
          }
          for (const id of ['product/example', 'pairing/a+b', 'gauntlet:example', 'user2/product/example',
              'other/user2/casual/example', 'casual/', '/casual/example']) {
            const f = fixture(id); assert(!f.save); assert(!f.back);
          }
          assert.equal(writes, 0); assert.equal(stored.size, 0);
        """)

    def test_all_supported_kinds_prepare_only_the_correct_list_and_editor_draft(self):
        self.run_js("""
          for (const id of ['casual/example', 'commander/example', 'user2/casual/example', 'user2/commander/example']) {
            for (const version of ['target', 'owned']) {
              location.hash = originalHash; stored.clear();
              const f = fixture(id, version); api = async path => { assert(path.includes(encodeURIComponent(id))); return f.view; };
              await vtSaveChange(f.page, f.data, f.save);
              const draft = JSON.parse(stored.get(f.key));
              assert.equal(draft.sha256, 'saved-sha'); assert.equal(draft.starting, false);
              assert.equal(draft.lists.Deck.find(x => x.name === 'Shock'), undefined);
              assert.equal(draft.lists.Deck.find(x => x.name === 'Opt').qty, 1);
              assert.equal(draft.lists.Sideboard[0].name, 'Negate');
              assert.equal(draft.base.lists.Deck[0].name, 'Shock');
              assert.equal(f.view.lists[version].Deck[0].name, 'Shock');
              assert.equal(location.hash, editHref(id, version));
            }
          }
          assert.equal(writes, 0); assert.equal(prompts, 0);
        """)

    def test_back_checks_fresh_permission_and_keeps_existing_draft_untouched(self):
        self.run_js("""
          const f = fixture(); stored.set(f.key, 'existing'); api = async () => f.view;
          await vtEditorHandoff(f.page, f.data, f.back);
          assert.equal(location.hash, editHref(f.view.id, 'target'));
          assert.equal(stored.get(f.key), 'existing'); assert.equal(prompts, 0); assert.equal(writes, 0);
        """)

    def test_commander_swap_uses_saved_sections_and_preserves_partner_and_printings(self):
        self.run_js("""
          for (const id of ['commander/example', 'user2/commander/example']) {
            location.hash = originalHash; stored.clear();
            const f = fixture(id);
            f.view.lists.target.Commander = [{qty: 1, name: 'Old Leader // Back', set: 'tst', number: '7'},
              {qty: 1, name: 'Partner', set: 'tst', number: '9'}];
            f.data.test.variant = {changes: {remove: [[1, 'Old Leader'], [1, 'Shock']],
              add: [[1, 'New Leader'], [1, 'Opt']]}, cards: {Commander: [[1, 'New Leader'], [1, 'Partner']],
                Main: [[1, 'Opt'], [59, 'Forest']]}};
            api = async () => f.view; await vtSaveChange(f.page, f.data, f.save);
            const draft = JSON.parse(stored.get(f.key));
            same(draft.lists.Commander, [{qty: 1, name: 'Partner', set: 'tst', number: '9'}, {qty: 1, name: 'New Leader'}]);
            assert(!draft.lists.Deck.some(x => x.name === 'New Leader'));
            assert(draft.lists.Deck.some(x => x.name === 'Opt'));
            assert.equal(draft.lists.Sideboard[0].name, 'Negate');
            assert.equal(f.view.lists.target.Commander[0].name, 'Old Leader // Back');
            assert.equal(location.hash, editHref(id, 'target'));
          }
          assert.equal(writes, 0);
        """)

    def test_changed_removals_and_ambiguous_legacy_commander_never_write_partial_drafts(self):
        self.run_js("""
          for (const scenario of ['missing removal', 'missing recipe', 'changed commander']) {
            location.hash = originalHash; stored.clear(); const f = fixture('user2/commander/example');
            if (scenario === 'missing removal') f.view.lists.target.Deck = [{qty: 60, name: 'Forest'}];
            else {
              f.view.lists.target.Commander = [{qty: 1, name: scenario === 'changed commander' ? 'Different Leader' : 'Old Leader'}];
              f.data.test.variant.changes = {remove: [[1, 'Old Leader']], add: [[1, 'New Leader']]};
              if (scenario === 'changed commander') f.data.test.variant.cards = {Commander: [[1, 'New Leader']], Main: []};
            }
            api = async () => f.view; await vtSaveChange(f.page, f.data, f.save);
            assert.equal(stored.size, 0); assert.equal(location.hash, originalHash); assert.equal(f.save.disabled, false);
          }
          assert.equal(writes, 0);
        """)

    def test_readonly_wrong_deck_kind_or_missing_list_never_handoffs(self):
        self.run_js("""
          for (const patch of [{may_save: false}, {may_save: undefined}, {editable: false}, {kind: 'product'},
              {id: 'user2/casual/renamed'}, {lists: {target: null}}]) {
            const f = fixture(); api = async () => ({...f.view, ...patch});
            for (const apply of [false, true]) await vtEditorHandoff(f.page, f.data, apply ? f.save : f.back, apply);
            assert.equal(location.hash, originalHash); assert.equal(stored.size, 0);
            assert.equal(f.save.disabled, false); assert.equal(f.back.disabled, false);
          }
          assert.equal(writes, 0); assert.equal(prompts, 0);
        """)

    def test_stale_reads_cannot_change_profile_route_page_data_or_detached_control(self):
        self.run_js("""
          for (const mutate of [f => {state.profile = {id: 'user3'};}, f => {routeToken += 1;},
              f => {location.hash = '#/library';}, f => {f.page.data = {...f.data};},
              f => {f.page.host.remove();}, f => {f.save.remove();}]) {
            state.profile = {id: 'user2', space: 'user2'}; location.hash = originalHash;
            const f = fixture(), pending = deferred(); api = () => pending.promise;
            const request = vtSaveChange(f.page, f.data, f.save); mutate(f); pending.resolve(f.view); await request;
            assert.equal(stored.size, 0); assert(!location.hash.startsWith('#/edit'));
          }
          assert.equal(writes, 0); assert.equal(prompts, 0); assert.equal(notices.length, 0);
        """)

    def test_replace_confirmation_rechecks_permission_and_draft_before_local_write(self):
        self.run_js("""
          for (const scenario of ['replace', 'keep', 'permission', 'draft', 'profile', 'route', 'failure']) {
            state.profile = {id: 'user2', space: 'user2'}; location.hash = originalHash; stored.clear();
            const f = fixture(), waiting = deferred(); stored.set(f.key, 'original');
            let reads = 0; api = async () => {
              reads += 1;
              if (reads === 2 && scenario === 'failure') throw Error('Unable to check editor');
              return {...f.view, may_save: scenario !== 'permission' || reads === 1};
            };
            ask = () => waiting.promise;
            const request = vtSaveChange(f.page, f.data, f.save);
            await Promise.resolve(); await Promise.resolve();
            if (scenario === 'draft') stored.set(f.key, 'newer');
            if (scenario === 'profile') state.profile = {id: 'user3'};
            if (scenario === 'route') location.hash = '#/library';
            waiting.resolve(scenario === 'keep' ? 'keep' : 'replace'); await request;
            if (scenario === 'replace') {
              assert.equal(JSON.parse(stored.get(f.key)).lists.Deck.some(x => x.name === 'Opt'), true);
              assert.equal(location.hash, editHref(f.view.id, 'target')); assert.equal(reads, 2);
            } else {
              assert.equal(stored.get(f.key), scenario === 'draft' ? 'newer' : 'original');
              assert(!location.hash.startsWith('#/edit'));
            }
          }
          assert.equal(writes, 0);
        """)

    def test_pending_action_cannot_launch_a_second_handoff_and_failure_allows_retry(self):
        self.run_js("""
          const f = fixture(), pending = deferred(); let reads = 0;
          api = () => {reads += 1; return pending.promise;};
          const request = vtSaveChange(f.page, f.data, f.save);
          await vtEditorHandoff(f.page, f.data, f.back); assert.equal(reads, 1);
          pending.reject(Error('Unable to check editor')); await request;
          assert.equal(f.save.disabled, false); assert.equal(f.page.handoffBusy, false);
          assert.equal(stored.size, 0); assert.equal(location.hash, originalHash);
          api = async () => f.view; await vtSaveChange(f.page, f.data, f.save);
          assert.equal(JSON.parse(stored.get(f.key)).lists.Deck.some(x => x.name === 'Opt'), true);
          assert.equal(writes, 0);
        """)

    def test_excluded_reason_keeps_words_and_link_without_whole_row_fading(self):
        css = _text("variant.css")
        dropped = css.split(".vt-row-dropped {", 1)[1].split("}", 1)[0]
        self.assertNotIn("opacity", dropped)
        self.run_js("""
          const row = vtRows({test: {against: 'field'}, opponents: [{id: 'casual/example', title: 'Example',
            base_key: 'b'.repeat(64), dropped: 'Not included: no games finished.'}]}).querySelector('.vt-row-dropped');
          assert(row.textContent.includes('Not included: no games finished.'));
          assert.equal(row.querySelector('a').getAttribute('href'), '#/matchup?key=' + 'b'.repeat(64));
        """)
