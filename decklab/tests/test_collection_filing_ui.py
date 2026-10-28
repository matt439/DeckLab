"""Saved-import filing advice over real UI scripts and deterministic fixture-only replies."""
import json
import subprocess
import unittest

from decklab.tests.test_collection_import_groups_ui import FIXTURE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = FIXTURE + r"""
  let reloads = 0; route = () => { reloads++; };
  const filing = () => ({space: 'home', profile: 'matt', status: 'ready', added: [
    {name: 'Llanowar Elves', set: 'fdn', collector_number: '227', finish: 'nonfoil', quantity: 3},
    {name: 'Aerie Mystics', set: 'con', collector_number: '1', finish: 'foil', quantity: 1}],
    destinations: [{kind: 'deck', row: 0, quantity: 2, deck: {id: 'casual/waiting', title: 'Waiting Deck', status: 'building'}},
      {kind: 'storage', row: 0, quantity: 1}, {kind: 'storage', row: 1, quantity: 1}]});
  const reply = () => ({...imported(), filing: filing()});
  const view = (profile = 'matt', may = MAY.admin, space = 'home') => {
    as(profile, may);
    return drawCollectionRows({space, sha256: 'latest', editable: true,
      rows: [{...original, quantity: 999, name: 'Later collection facts'}]}, space);
  };
  const guide = () => main.querySelector('.col-filing-guide');
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionFilingUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_grouped_apply_uses_saved_manifest_and_one_profile_bound_reload_notice(self):
        self.run_js(r"""
          const {cv, ctx, preview} = await openGrouped(); readyGroups(ctx); const calls = [], answer = reply();
          apiWrite = async (path, body) => { calls.push([path, body]); return answer; };
          await applyImport(ctx, false);
          same(calls, [['/api/collection/import/apply', {space: 'home', token: preview.token, sha256: 's1', skip_groups: ['g1', 'g3']}]]);
          assert.equal(reloads, 1); assert(ctx.sheet.closed); assert.equal(state.colNotice.profile, 'matt');
          assert(state.colNotice.words.includes('Imported 4 cards'));
          assert(state.colNotice.words.includes('2 source set groups left out'));
          answer.filing.added[0].name = 'Changed server object'; answer.filing.added[0].quantity = 700;
          preview.source_rows[1].row.quantity = '800'; preview.source_rows[1].row.name = 'Changed preview';
          const fresh = view(); assert(guide()); assert.equal(state.colNotice, null);
          assert(guide().textContent.includes('For the 4 copies added by this import'));
          assert(guide().textContent.includes('2 × Llanowar Elves (FDN 227)'));
          assert(guide().textContent.includes('1 × Aerie Mystics (CON 1 · Foil)'));
          assert(guide().textContent.includes('Waiting Deck')); assert(guide().textContent.includes('To storage'));
          assert(guide().textContent.includes('deck lists at that point'));
          for (const stale of ['Changed server object', 'Changed preview', 'Later collection facts', '999', '800'])
            assert(!guide().textContent.includes(stale), stale);
          assert.equal(guide().querySelectorAll('button').filter(button => !button.hidden).length, 0);
          assert.equal(guide().querySelectorAll('input').length, 0);
          assert(guide().querySelector('a').getAttribute('href').includes('casual%2Fwaiting'));
          colTakeNotice(fresh); assert.equal(main.querySelectorAll('.col-filing-guide').length, 1);
        """)

    def test_exact_printing_case_and_finish_stay_separate_and_added_counts_ignore_old_copies(self):
        self.run_js(r"""
          const cv = view(), answer = {added: {rows: 0, cards: 2}, filing: {space: 'home', profile: 'matt', status: 'ready',
            added: [{name: 'Same card', set: 'fdn', collector_number: 'A', finish: 'foil', quantity: 1},
              {name: 'Same card', set: 'fdn', collector_number: 'a', finish: 'nonfoil', quantity: 1}],
            destinations: [{kind: 'storage', row: 0, quantity: 1}, {kind: 'storage', row: 1, quantity: 1}]}};
          const data = colFilingSnapshot(answer, cv); assert.equal(data.status, 'ready'); assert.equal(data.added.length, 2);
          cv.message.append(colFilingGuide(cv, data)); assert(guide().textContent.includes('FDN A · Foil'));
          assert(guide().textContent.includes('FDN a')); assert(guide().textContent.includes('2 copies added'));
          assert(!guide().textContent.includes('999'));
        """)

    def test_unknown_calculation_keeps_saved_success_and_never_claims_storage(self):
        self.run_js(r"""
          const {cv, ctx} = await openGrouped(); readyGroups(ctx); const answer = reply();
          answer.filing.status = 'unknown'; answer.filing.message = 'Hidden exception must not reach the UI';
          answer.filing.destinations = []; apiWrite = async () => answer; await applyImport(ctx, false); view();
          assert(guide().textContent.includes('Destination unknown')); assert(guide().textContent.includes('The import is saved'));
          assert(guide().textContent.includes('3 × Llanowar Elves')); assert(guide().textContent.includes('1 × Aerie Mystics'));
          assert(!guide().textContent.includes('To storage')); assert(!guide().textContent.includes('Hidden exception'));
          assert.equal(guide().querySelectorAll('a').length, 0);
        """)

    def test_incomplete_duplicate_or_overallocated_manifest_fails_closed(self):
        self.run_js(r"""
          const cv = view();
          for (const change of [data => data.destinations.pop(), data => data.destinations[0].quantity = 4,
            data => data.added[1] = {...data.added[0]}, data => data.added[0].quantity = 99,
            data => data.destinations[0].row = -1, data => data.status = 'unexpected']) {
            const answer = reply(); change(answer.filing); const copy = colFilingSnapshot(answer, cv);
            assert.equal(copy.status, 'unknown'); clear(cv.message).append(colFilingGuide(cv, copy));
            assert(!guide().textContent.includes('To storage')); assert(!guide().textContent.includes('Waiting Deck'));
            assert(guide().textContent.includes('Destination unknown'));
          }
        """)

    def test_other_space_deck_data_and_extra_private_fields_never_render(self):
        self.run_js(r"""
          const cv = view(); const answer = reply();
          answer.filing.destinations[0].deck = {id: 'user2/casual/hidden', title: 'Private title', status: 'built'};
          answer.filing.kits = {'user2/casual/hidden': {sleeves: 'Private sleeves'}};
          answer.filing.revision = 'private global counter';
          const data = colFilingSnapshot(answer, cv); assert.equal(data.status, 'unknown'); cv.message.append(colFilingGuide(cv, data));
          for (const privateWord of ['Private title', 'Private sleeves', 'private global counter']) assert(!guide().textContent.includes(privateWord));
          assert.equal(guide().querySelectorAll('a').length, 0);
        """)

    def test_member_guide_accepts_only_that_members_deck_space(self):
        self.run_js(r"""
          const cv = view('user2', MAY.user2, 'user2'), answer = reply();
          answer.filing.space = 'user2'; answer.filing.profile = 'user2';
          answer.filing.destinations[0].deck = {id: 'user2/casual/waiting', title: 'My Waiting Deck', status: 'idea'};
          const data = colFilingSnapshot(answer, cv); assert.equal(data.status, 'ready'); cv.message.append(colFilingGuide(cv, data));
          assert(guide().textContent.includes('My Waiting Deck'));
          assert(guide().querySelector('a').getAttribute('href').includes('user2%2Fcasual%2Fwaiting'));
          assert(!guide().textContent.includes('Sleeve'));
          answer.filing.destinations[0].deck.id = 'casual/home';
          assert.equal(colFilingSnapshot(answer, cv).status, 'unknown');
        """)

    def test_notice_is_discarded_when_profile_or_space_changes_even_with_shared_home(self):
        self.run_js(r"""
          const {cv, ctx} = await openGrouped(); readyGroups(ctx); apiWrite = async () => reply();
          await applyImport(ctx, false); const user1 = view('user1', MAY.user1);
          assert.equal(guide(), null); assert.equal(state.colNotice, null); assert(!user1.message.textContent.includes('Imported'));
          const wrong = {...reply().filing, profile: 'matt'};
          assert.equal(colFilingSnapshot({added: {cards: 4}, filing: wrong}, user1), null);
          as('matt', MAY.admin); const other = drawCollectionRows({space: 'user2', editable: false, rows: [], sha256: 's'}, 'user2');
          state.colNotice = {profile: 'matt', space: 'home', words: 'Imported', filing: wrong}; colTakeNotice(other);
          assert.equal(guide(), null); assert.equal(state.colNotice, null);
        """)

    def test_legacy_response_keeps_counts_without_guessing_destinations(self):
        self.run_js(r"""
          const {ctx} = await openGrouped(); readyGroups(ctx); apiWrite = async () => imported();
          await applyImport(ctx, false); const cv = view();
          assert(cv.message.textContent.includes('Imported 4 cards')); assert.equal(guide(), null);
        """)

    def test_presentation_is_bounded_and_more_controls_keep_owned_focus_without_writing(self):
        self.run_js(r"""
          const cv = view(), data = filing();
          data.added = Array.from({length: 101}, (_, i) => ({name: `Card ${i}`, set: 'fdn', collector_number: String(i), finish: 'nonfoil', quantity: 1}));
          data.destinations = data.added.map((row, index) => ({kind: 'storage', row: index, quantity: 1}));
          const frozen = colFilingSnapshot({added: {cards: 101}, filing: data}, cv); cv.message.append(colFilingGuide(cv, frozen));
          const list = guide().querySelector('ul'), more = guide().querySelector('.col-filing-more');
          assert.equal(list.children.length, 100); assert(guide().textContent.includes('100 of 101 printing lines'));
          let calls = 0; apiWrite = async () => { calls++; }; more.focus(); more.click();
          assert.equal(list.children.length, 101); assert(more.hidden); assert.equal(document.activeElement, list);
          assert.equal(list.getAttribute('tabindex'), '0'); assert.equal(calls, 0);
          clear(cv.message); more.click(); assert.equal(calls, 0); assert.equal(guide(), null);
        """)

    def test_caps_or_missing_manifest_do_not_render_truncated_storage_advice(self):
        self.run_js(r"""
          const cv = view(); const answer = reply();
          answer.filing.destinations = Array.from({length: COL_FILING_MAX + 1}, () => ({kind: 'storage', row: 0, quantity: 1}));
          let frozen = colFilingSnapshot(answer, cv); assert.equal(frozen.status, 'unknown');
          cv.message.append(colFilingGuide(cv, frozen)); assert(!guide().textContent.includes('To storage'));
          answer.filing.added = null; frozen = colFilingSnapshot(answer, cv); clear(cv.message).append(colFilingGuide(cv, frozen));
          assert(guide().textContent.includes('The import is saved')); assert.equal(guide().querySelectorAll('li').length, 0);
        """)

    def test_first_paint_is_bounded_across_many_decks_and_each_keeps_its_own_more_control(self):
        self.run_js(r"""
          const cv = view(), data = filing();
          data.added = [{...data.added[0], quantity: 120}];
          data.destinations = Array.from({length: 120}, (_, i) => ({kind: 'deck', row: 0, quantity: 1,
            deck: {id: `casual/waiting-${i}`, title: `Waiting ${i}`, status: 'building'}}));
          const frozen = colFilingSnapshot({added: {cards: 120}, filing: data}, cv);
          cv.message.append(colFilingGuide(cv, frozen));
          assert.equal(guide().querySelectorAll('li').length, COL_FILING_PAGE);
          assert.equal(guide().querySelectorAll('.col-filing-panel').length, 120);
          const last = guide().querySelectorAll('.col-filing-panel').at(-1), more = last.querySelector('button');
          assert(last.textContent.includes('0 of 1 printing line')); assert(!more.hidden); more.click();
          assert.equal(last.querySelectorAll('li').length, 1); assert(more.hidden);
          assert.equal(guide().querySelectorAll('li').length, COL_FILING_PAGE + 1);
          assert.equal(document.activeElement, last.querySelector('ul'));
        """)

    def test_more_waits_for_dialog_and_menu_and_refuses_changed_profile_route_or_hidden_inventory(self):
        self.run_js(r"""
          const cv = view(), data = filing();
          data.added = [{...data.added[0], quantity: 101}];
          data.destinations = Array.from({length: 101}, () => ({kind: 'storage', row: 0, quantity: 1}));
          cv.message.append(colFilingGuide(cv, colFilingSnapshot({added: {cards: 101}, filing: data}, cv)));
          const list = guide().querySelector('ul'), more = guide().querySelector('button');
          const sheet = colOpenSheet('Own focus'); more.click(); assert.equal(list.children.length, 100); sheet.close();
          const originalMenu = keyboardMenuOpen; keyboardMenuOpen = () => true;
          more.click(); assert.equal(list.children.length, 100); keyboardMenuOpen = originalMenu;
          state.may = {...MAY.admin, see_inventory: []}; more.click(); assert.equal(list.children.length, 100); state.may = MAY.admin;
          const originalProfile = state.profile; state.profile = PROFILES.find(person => person.id === 'user1');
          more.click(); assert.equal(list.children.length, 100); state.profile = originalProfile;
          routeToken++; more.click(); assert.equal(list.children.length, 100); routeToken--;
          more.click(); assert.equal(list.children.length, 101);
        """)

    def test_late_success_after_close_or_newer_sheet_does_not_publish_or_steal_focus(self):
        self.run_js(r"""
          const {ctx} = await openGrouped(); readyGroups(ctx); let finish;
          apiWrite = () => new Promise(resolve => { finish = resolve; }); const pending = applyImport(ctx, false); await flush();
          ctx.sheet.close(); const other = colOpenSheet('Other task'); const focus = el('button', {text: 'Stay here'}); other.body.append(focus); focus.focus();
          finish(reply()); await pending;
          assert.equal(reloads, 0); assert(!state.colNotice); assert.equal(document.activeElement, focus); assert(!other.closed);
        """)

    def test_late_success_after_route_profile_or_preview_change_has_no_detailed_notice(self):
        self.run_js(r"""
          for (const change of [() => routeToken++, () => as('user1', MAY.user1), ctx => {ctx.seq++; ctx.preview = groupedPreview('new');}]) {
            const {ctx} = await openGrouped(); readyGroups(ctx); let finish; state.colNotice = null;
            apiWrite = () => new Promise(resolve => { finish = resolve; }); const pending = applyImport(ctx, false); await flush();
            change(ctx); finish(reply()); await pending; assert.equal(reloads, 0); assert(!state.colNotice);
            colCloseSheets();
          }
        """)

    def test_hidden_inventory_or_detached_old_guide_cannot_expand_more_lines(self):
        self.run_js(r"""
          const cv = view(), data = colFilingSnapshot(reply(), cv);
          state.may = {...MAY.admin, see_inventory: []}; assert.equal(colFilingGuide(cv, data), null);
          state.may = MAY.admin; const root = colFilingGuide(cv, data); cv.message.append(root);
          const before = root.textContent; routeToken++; assert(!colFilingHere(cv, data, root)); assert.equal(root.textContent, before);
        """)


if __name__ == "__main__":
    unittest.main()
