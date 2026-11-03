"""Try a precon before buying it (E3-S39, precon-trial.js) through the real page scripts, with fixture answers:
the "Try a precon" sheet and its create flow, the Testing page's button, Precons we could build's secondary
action, a trial deck's Overview notice, the library's Trying out group, the board's Not owned chip and the
offer to retire a trial after Add a precon. No server, database or Forge."""
import json
import re
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

FIXTURE = SETUP + """
  const ENTRY = {file: 'Dinos_TST', name: 'Test Dinos', code: 'tst', set_name: 'Test Set', type: 'Commander Deck',
    released: '2026-10-02', source: ''};
  const VIEW = {deck: ENTRY, kind: 'commander', title: 'Ghalta: Test Dinos', trial: null, owned_deck: null,
    may_create: true, testable: true, why_not_testable: null, cards: 100};
  const SEARCH = {date: '2026-10-08', more: false, decks: [ENTRY]};
  const CREATED = {created: true, id: 'commander/ghalta-test-dinos', title: 'Ghalta: Test Dinos', warnings: [], stale_tables: []};
  const TRIAL = {id: 'commander/ghalta-test-dinos', title: 'Ghalta: Test Dinos', kind: 'commander', status: 'idea',
    player: 'user', space: 'home', trial: 'Dinos_TST'};
  function stub(view = VIEW) {
    const asked = [];
    api = async (path) => { asked.push(path);
      if (path.startsWith('/api/precons/trial?')) return typeof view === 'function' ? view() : view;
      if (path.startsWith('/api/precons?')) return SEARCH;
      throw new Error('unexpected ' + path); };
    return asked;
  }
  function action(sheet, value) { return sheet.foot.querySelector(`[data-action="${value}"]`); }
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PreconTrialUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_search_pick_and_try_it_in_forge(self):
        self.run_js("""
          as('matt', MAY.admin); location.hash = '#/matchups';
          const asked = stub();
          const ctx = openTrialSearch('home'); await flush();
          same(asked, ['/api/precons?q=']);
          assert(ctx.area.textContent.includes('Test Dinos'), ctx.area.textContent);
          ctx.area.querySelector('.precon-pick').click(); await flush();
          assert.equal(asked.at(-1), '/api/precons/trial?file=Dinos_TST&space=home');
          assert.equal(ctx.sheet.heading.textContent, 'Test Dinos');
          const words = ctx.area.textContent;
          assert(words.includes('Test Set · Commander Deck · released 2026-10-02'), words);
          assert(words.includes('100 cards, played as a Commander deck'), words);
          assert(words.includes('trial deck idea'), words);
          assert.equal(ctx.area.querySelector('.ptr-runs'), null);       // runs are allowed: no reason line
          // One primary in the sheet: Try it in Forge.
          assert.equal(ctx.sheet.foot.querySelectorAll('.btn-primary').length, 1);
          // Its title box holds the suggestion; a blank one is refused here, a taken one focuses the box.
          assert.equal(ctx.titleInput.value, 'Ghalta: Test Dinos');
          const calls = [];
          apiWrite = async (path, body) => { calls.push([path, body]);
            throw new ApiError(409, "There's already a deck called Ghalta: Test Dinos: pick another title.", {conflict: 'commander/ghalta-test-dinos'}); };
          ctx.titleInput.value = '  ';
          action(ctx.sheet, 'try').click(); await flush();
          same(calls, []);
          assert.equal(ctx.titleNote.textContent, 'The deck needs a title.');
          ctx.titleInput.value = 'Ghalta: Test Dinos';
          action(ctx.sheet, 'try').click(); await flush();
          same(calls, [['/api/precons/trial', {file: 'Dinos_TST', space: 'home', title: 'Ghalta: Test Dinos'}]]);
          assert(!ctx.sheet.closed);
          assert(ctx.message.textContent.includes('pick another title'), ctx.message.textContent);
          assert.equal(document.activeElement, ctx.titleInput);
          assert(ctx.titleInput.selected);
          assert(!action(ctx.sheet, 'try').disabled);
          calls.length = 0;
          apiWrite = async (path, body) => { calls.push([path, body]); return CREATED; };
          ctx.titleInput.value = 'Dinos (trial)';
          action(ctx.sheet, 'try').click(); await flush();
          same(calls, [['/api/precons/trial', {file: 'Dinos_TST', space: 'home', title: 'Dinos (trial)'}]]);
          assert(ctx.sheet.closed);
          assert.equal(location.hash, '#/deck?id=commander%2Fghalta-test-dinos&v=target&tab=matchups&part=gauntlet');
          // Back to the list from a pick.
          location.hash = '#/matchups';
          const again = openTrialSearch('home'); await flush();
          again.area.querySelector('.precon-pick').click(); await flush();
          action(again.sheet, 'back').click(); await flush();
          assert(!again.searchField.hidden);
          assert.equal(again.sheet.heading.textContent, 'Try a precon');
        """)

    def test_existing_trial_refusals_and_the_simulations_reason(self):
        self.run_js("""
          as('user2', MAY.user2); location.hash = '#/matchups';
          // A trial already made: Open its trial, no second create.
          stub({...VIEW, trial: {id: 'user2/commander/ghalta-test-dinos', title: 'Ghalta: Test Dinos'}});
          let ctx = await openTrialPrecon('Dinos_TST', 'user2');
          assert(ctx.area.textContent.includes("You're already trying it"), ctx.area.textContent);
          assert.equal(action(ctx.sheet, 'try'), null);
          action(ctx.sheet, 'open').click();
          assert(ctx.sheet.closed);
          assert.equal(location.hash, '#/deck?id=user2%2Fcommander%2Fghalta-test-dinos&v=target&tab=matchups&part=gauntlet');
          // Not testable: the reason and no button.
          location.hash = '#/matchups';
          stub({...VIEW, testable: false, why_not_testable: 'Its 20-card list is too small to test against 60-card decks.'});
          ctx = await openTrialPrecon('Dinos_TST', 'user2');
          assert(ctx.area.textContent.includes('Its 20-card list is too small'), ctx.area.textContent);
          assert.equal(action(ctx.sheet, 'try'), null);
          assert.equal(ctx.sheet.foot.querySelectorAll('.btn-primary').length, 0);
          ctx.sheet.close();
          // May not add decks there.
          stub({...VIEW, may_create: false});
          ctx = await openTrialPrecon('Dinos_TST', 'user2');
          assert(ctx.area.textContent.includes("You can't add decks here"), ctx.area.textContent);
          assert.equal(action(ctx.sheet, 'try'), null);
          ctx.sheet.close();
          // Runs refused: the simulations reason, naming nobody; the trial can still be made.
          state.simulations = {may_start: false, why_not: 'Only an admin can start simulations right now. Saved results still show.'};
          stub();
          ctx = await openTrialPrecon('Dinos_TST', 'user2');
          const note = ctx.area.querySelector('.ptr-runs');
          assert(note && note.textContent.includes('Only an admin can start simulations right now.'), ctx.area.textContent);
          assert(action(ctx.sheet, 'try'));
          // A 409 naming an existing trial opens it; another refusal stays in the sheet.
          apiWrite = async () => { throw new ApiError(409, 'Already trying it.', {existing: 'user2/commander/ghalta-test-dinos'}); };
          action(ctx.sheet, 'try').click(); await flush();
          assert(ctx.sheet.closed);
          assert.equal(location.hash, '#/deck?id=user2%2Fcommander%2Fghalta-test-dinos&v=target&tab=matchups&part=gauntlet');
          location.hash = '#/matchups';
          ctx = await openTrialPrecon('Dinos_TST', 'user2');
          apiWrite = async () => { throw new ApiError(400, "Scryfall has no card named 'Nope'.", {problems: [{message: 'Nope'}]}); };
          action(ctx.sheet, 'try').click(); await flush();
          assert(!ctx.sheet.closed);
          assert(ctx.message.textContent.includes('Scryfall has no card'), ctx.message.textContent);
          assert.equal(location.hash, '#/matchups');
          assert(!action(ctx.sheet, 'try').disabled);
          // A late answer for another person is dropped.
          let release; stub(() => new Promise((r) => { release = r; }));
          const late = openTrialPrecon('Dinos_TST', 'user2'); await flush();
          const sheet = openDialog();
          as('matt', MAY.admin);
          release(VIEW); await late; await flush();
          assert(!sheet.textContent.includes('Try it in Forge saves'), sheet.textContent);
        """)

    def test_the_testing_page_button_and_open_precon(self):
        self.run_js("""
          as('matt', MAY.admin); location.hash = '#/matchups?open=precon';
          stub();
          add(main, pageHead({title: 'Testing', primary: el('button', {class: 'btn btn-primary', text: 'Play a matchup'})}));
          ptrTestingButton(main, new URLSearchParams('open=precon'), routeToken);
          const buttons = main.querySelector('.page-head-buttons');
          assert(button(buttons, 'Try a precon…'), buttons.textContent);
          assert.equal(buttons.querySelectorAll('.btn-primary').length, 1);
          let replaced = null; history.replaceState = (s, t, url) => { replaced = url; };
          flushTimers(); await flush();
          assert.equal(replaced, '#/matchups');
          assert.equal(openDialog().querySelector('h2')?.textContent || openDialog().textContent.slice(0, 11), 'Try a precon');
          // No run button (runs refused) still leaves room for it; a viewer who may add no decks gets none.
          clear(main);
          add(main, pageHead({title: 'Testing'}));
          ptrTestingButton(main, new URLSearchParams(''), routeToken);
          assert(button(main, 'Try a precon…'));
          as('user1', {...MAY.user1, create: []});
          add(main, pageHead({title: 'Testing'}));
          ptrTestingButton(main, new URLSearchParams(''), routeToken);
          assert.equal(button(main, 'Try a precon…'), null);
        """)

    def test_precons_we_could_build_offers_it_too(self):
        self.run_js("""
          as('matt', MAY.admin); location.hash = '#/collection';
          const cv = drawCollectionRows({space: 'home', sha256: 's1', rows: [], editable: true}, 'home');
          const DETAIL = {deck: ENTRY, kind: 'commander', title: 'Ghalta: Test Dinos', cards: 5, covered: 5, share: 1,
            missing: [], totals: {missing: 0}, problems: [], may_start: true, testable: true, why_not_testable: null};
          api = async (path) => path.includes('/deck?') ? DETAIL : {decks: [{...ENTRY, kind: 'commander', cards: 5, covered: 5, missing: 0, share: 1}],
            types: [], status: {}, total: 1};
          const ctx = openCoverageSheet(cv); await flush();
          ctx.area.querySelector('.pcov-pick').click(); await flush();
          const trial = action(ctx.sheet, 'trial');
          assert(trial && trial.textContent.includes('Try it in Forge'));
          assert(!trial.classList.contains('btn-primary') && !(trial.getAttribute('class') || '').includes('btn-primary'));
          assert.equal(ctx.sheet.foot.querySelectorAll('.btn-primary').length, 1);     // Start a deck from it
          const calls = [];
          apiWrite = async (path, body) => { calls.push([path, body]);
            throw new ApiError(409, "There's already a deck called that: pick another title.", {conflict: 'commander/x'}); };
          trial.click(); await flush();
          same(calls, [['/api/precons/trial', {file: 'Dinos_TST', space: 'home', title: 'Ghalta: Test Dinos'}]]);
          assert.equal(document.activeElement, ctx.titleInput);
          // The title typed in the view names the trial.
          calls.length = 0;
          apiWrite = async (path, body) => { calls.push([path, body]); return CREATED; };
          ctx.titleInput.value = 'My Dinos Trial';
          action(ctx.sheet, 'trial').click(); await flush();
          same(calls, [['/api/precons/trial', {file: 'Dinos_TST', space: 'home', title: 'My Dinos Trial'}]]);
          assert(ctx.sheet.closed);
          assert.equal(location.hash, '#/deck?id=commander%2Fghalta-test-dinos&v=target&tab=matchups&part=gauntlet');
          assert.equal(ptrCoverageAction(ctx, {...DETAIL, may_start: false}), null);
          // A precon Forge can't test: no button, the reason; runs refused: the simulations reason.
          const small = {...DETAIL, testable: false, why_not_testable: 'Its 20-card list is too small to test against 60-card decks.'};
          assert.equal(ptrCoverageAction(ctx, small), null);
          assert(ptrCoverageNotes(small).textContent.includes('Its 20-card list is too small'));
          assert.equal(ptrCoverageNotes({...DETAIL, testable: true}), null);
          state.simulations = {may_start: false, why_not: 'Only an admin can start simulations right now.'};
          assert(ptrCoverageNotes({...DETAIL, testable: true}).textContent.includes('Only an admin can start simulations'));
          assert.equal(ptrCoverageNotes({...small, may_start: false}), null);
        """)

    def test_a_trial_decks_overview_notice(self):
        self.run_js("""
          as('matt', MAY.admin); location.hash = '#/deck?id=commander%2Fghalta-test-dinos&v=target&tab=matchups&part=gauntlet';
          const data = {summary: TRIAL, version: 'target', played: {games: 0}, considering: {lines: [], sha256: 'a'.repeat(64)}};
          const notice = deckOverviewPlayed(data);
          main.append(notice);
          const words = notice.textContent;
          assert(words.includes("You don't own this precon.") && !words.includes('Played at home'), words);
          assert.equal(notice.querySelector('a').getAttribute('href'), '#/deck?id=commander%2Fghalta-test-dinos&v=target&tab=matchups&part=gauntlet');
          const bought = notice.querySelectorAll('a').find((a) => a.textContent === 'Bought it? Add a precon');
          assert.equal(bought.getAttribute('href'), '#/collection?open=precon');
          // Remove trial: the existing retirement sheet.
          const retired = []; openRetireDeck = (d) => { retired.push(d.summary.id); return {}; };
          button(notice, 'Remove trial').click();
          same(retired, ['commander/ghalta-test-dinos']);
          // The deck page's tabs rewrite the address in place (deck.js deckAddress): still this page.
          location.hash = '#/deck?id=commander%2Fghalta-test-dinos&v=target';
          // Keep as a deck idea: asked first, then the keep write with the text this page was drawn with.
          const asked = [], calls = []; let routed = 0;
          ask = async () => 'keep'; route = () => { routed += 1; };
          api = async (path) => { asked.push(path); return {}; };
          apiWrite = async (path, body) => { calls.push([path, body]); return {saved: true}; };
          button(notice, 'Keep as a deck idea').click(); await flush();
          same(asked, []);           // no fresh read: a save since is the server's 409
          same(calls, [['/api/precons/trial/keep', {id: 'commander/ghalta-test-dinos', expected_sha: 'a'.repeat(64)}]]);
          assert.equal(routed, 1);
          // Another page: nothing.
          location.hash = '#/deck?id=commander%2Fother&v=target';
          button(notice, 'Keep as a deck idea').click(); await flush();
          assert.equal(calls.length, 1);
          location.hash = '#/deck?id=commander%2Fghalta-test-dinos&v=target';
          // Cancelled: nothing written.
          ask = async () => 'cancel';
          button(notice, 'Keep as a deck idea').click(); await flush();
          assert.equal(calls.length, 1);
          // A viewer who can't change the deck reads the notice without its actions; an ordinary idea deck keeps its panel.
          as('user1', MAY.user1);
          const readOnly = ptrDeckNotice({summary: {...TRIAL, player: 'user'}, version: 'target'});
          assert.equal(button(readOnly, 'Keep as a deck idea'), null);
          assert.equal(button(readOnly, 'Remove trial'), null);
          const idea = deckOverviewPlayed({summary: {...TRIAL, trial: null}, played: {games: 0}});
          assert(idea.textContent.includes('Played at home'));
        """)

    def test_library_group_picker_and_board_marks(self):
        self.run_js("""
          as('matt', MAY.admin);
          const decks = [{id: 'commander/a', title: 'A Idea', kind: 'commander', status: 'idea', space: 'home', trial: null},
            {id: 'commander/b', title: 'B Trial', kind: 'commander', status: 'idea', space: 'home', trial: 'Dinos_TST'},
            {id: 'commander/c', title: 'C Built', kind: 'commander', status: 'built', space: 'home', trial: null}];
          const rows = el('div', {}, statusRows(decks, {sort: 'title', select() {}, lab: true}));
          const heads = rows.querySelectorAll('.lib-status-head').map((h) => h.textContent.replace(/\\d+$/, ''));
          same(heads, ['Built', 'Ideas', 'Trying out']);
          const groups = rows.querySelectorAll('.deck-rows').map((u) => u.textContent);
          assert(groups[1].includes('A Idea') && !groups[1].includes('B Trial'), groups[1]);
          assert(groups[2].includes('B Trial'), groups[2]);
          same(libRowOrder(decks, 'title').map((d) => d.id), ['commander/c', 'commander/a', 'commander/b']);
          assert.equal(deckStatusPill(decks[1]).textContent, 'Trial');
          assert.equal(deckStatusPill(decks[0]).textContent, 'Idea');
          assert.equal(ptrPickerTitle(decks[1]), 'B Trial (trial, not owned)');
          const row = gbRow({token: routeToken}, {deck: {id: 'commander/b', title: 'B Trial'}, trial: true, state: 'untested'});
          assert(row.textContent.includes('Not owned'), row.textContent);
          const plain = gbRow({token: routeToken}, {deck: {id: 'commander/a', title: 'A Idea'}, state: 'untested'});
          assert(!plain.textContent.includes('Not owned'));
        """)

    def test_after_add_a_precon_the_trial_can_be_retired(self):
        self.run_js("""
          as('user1', MAY.user1); location.hash = '#/deck?id=commander%2Fbought&v=target';
          state.saved = {hash: location.hash, profile: 'user1', version: 'target', mode: 'new',
            answer: {created: true, id: 'commander/bought', title: 'Bought', warnings: [], stale_tables: [],
              precon: {name: 'Test Dinos', whose: 'the collection', cards: 90,
                trials: [{id: 'commander/ghalta-test-dinos', title: 'Ghalta: Test Dinos'}]}}};
          const box = savedBox('commander/bought');
          main.append(box);
          const offer = button(box, 'Remove the trial deck Ghalta: Test Dinos');
          assert(offer, box.textContent);
          const retired = []; let opts = null; openRetireDeck = (d, o) => { retired.push(d.summary); opts = o; return {}; };
          api = async (path) => { assert.equal(path, '/api/decks'); return {decks: [{...TRIAL, player: 'wife'}]}; };
          offer.click(); await flush();
          same(retired.map((s) => [s.id, s.player]), [['commander/ghalta-test-dinos', 'wife']]);
          // Once retired, the new deck's page is drawn again, without that offer.
          let routed = 0; route = () => { routed += 1; };
          main.append(el('p', {class: 'still-here', text: 'the new deck'}));
          opts.onRetired({title: 'Ghalta: Test Dinos'});
          assert.equal(routed, 1);
          assert(main.querySelector('.still-here'));
          same(state.saved.answer.precon.trials, []);
          // Without trials the box has no offer.
          state.saved.answer.precon.trials = undefined;
          assert(!savedBox('commander/bought').textContent.includes('Remove the trial deck'));
          assert.equal(ptrTrialsPart([]), null);
        """)


class PreconTrialSourceTests(unittest.TestCase):
    """The file's own rules: its globals are prefixed, writes go through apiWrite, its CSS uses ptr-."""

    def test_globals_writes_and_css(self):
        script = (WEB / "precon-trial.js").read_text(encoding="utf-8")
        names = re.findall(r"(?m)^(?:async )?function (\w+)\(", script) + re.findall(r"(?m)^const (\w+)", script)
        self.assertEqual([n for n in names if not (n.startswith("ptr") or n.startswith("PTR_") or n.startswith("openTrial"))], [])
        self.assertNotIn("fetch(", script)
        for path in ('"/api/precons/trial"', '"/api/precons/trial/keep"'):
            self.assertIn(f"apiWrite({path}", script)
        self.assertNotIn("/api/deck/retire", script)        # Keep sends the drawn page's sha, never a fresh one
        self.assertNotIn("hash: location.hash", script)     # late answers are checked by page, not exact address
        self.assertIn("/api/precons/trial?", script)
        self.assertIn("token === routeToken", script.replace("ctx.token === routeToken", "token === routeToken"))
        css = (WEB / "collection.css").read_text(encoding="utf-8")
        block = css[css.index("/* Try a precon"):]
        block = re.sub(r"/\*.*?\*/", "", block[:block.index("\n\n")], flags=re.S)
        classes = set(re.findall(r"\.([a-z][\w-]*)", block)) - {"sub"}       # the shared .sub, laid out only
        self.assertTrue(classes)
        self.assertEqual([c for c in classes if not c.startswith("ptr-")], [])
