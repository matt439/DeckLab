"""The Tokens page's "Scan token cards…" (E7-S32, tokens-scan.js), over the real scripts with fixture answers.

The photo's shrinking (a canvas, in the browser) is stood in for; POST /api/tokens/scan's answers are fixtures, and
Add sends the reviewed list to POST /api/tokens/scan/add as one change.
"""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  const fishRow = {key: 'r0', index: 0, front: 'Fish', back: '', set: '', front_collector_number: '', back_collector_number: '',
    finish: '', quantity: 1, front_details: '', back_details: '', notes: '', uses: [], faces: []};
  const DATA = {space: 'home', sha256: 's1', exists: true, sorted: true, index_ready: true, rows: [fishRow], cards: 1,
    missing: [], incoming: [], problems: [], info: [],
    face_names: ['Fish', 'Rabbit', 'The Ring', 'The Ring // The Ring Tempts You', 'The Ring Tempts You', 'Treasure']};
  local.get = () => null; local.set = () => true;
  const draw = (data = {}, who = ['matt', MAY.admin], space = 'home') => { as(...who);
    return drawTokens({...DATA, ...data}, routeToken, space); };
  const proposal = (front, set, number, how, faces = [front]) => ({front, faces, set, collector_number: number,
    set_name: set.toUpperCase(), how, img_small: null});
  const FISH = {ok: true, space: 'home', unread: false, message: 'Read Fish, TBLB 7.',
    proposals: [proposal('Fish', 'tblb', '7', 'name and number')]};
  const RING = {ok: true, space: 'home', unread: false, message: 'Read The Ring, TLTR H13.',
    proposals: [proposal('The Ring', 'tltr', 'H13', 'name and number', ['The Ring', 'The Ring Tempts You'])]};
  const TREASURE = {ok: true, space: 'home', unread: false, message: "Read Treasure; its printing wasn't read.",
    proposals: [proposal('Treasure', '', '', 'name')]};
  const MIXED = {ok: true, space: 'home', unread: false, message: 'Read Rabbit, but the set code and number name another token.',
    proposals: [proposal('Rabbit', '', '', 'name'), proposal('Fish', 'tblb', '7', 'number')]};
  colScanShrink = async () => 'QUJD';
  const foot = (ctx, action) => ctx.sheet.foot.querySelector(`[data-action="${action}"]`);
  const pick = (ctx, label) => ctx.list.querySelector(`[aria-label="${label}"]`);
  const options = (select) => [...select.querySelectorAll('option')].map((o) => o.textContent);
  const shoot = async (ctx) => { ctx.input.files = [{name: 'photo.jpg'}]; ctx.input.fire('change'); await flush(); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class TokenScanUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_photos_fill_the_pending_list_and_add_sends_one_change(self):
        self.run_js("""
          const view = draw();
          const ctx = openTokenScan(view);
          assert.equal(ctx.input.getAttribute('capture'), 'environment');
          assert.equal(foot(ctx, 'review'), null);                      // nothing to review yet
          const calls = [];
          const answers = [FISH, FISH, TREASURE];
          apiWrite = async (path, body) => { calls.push([path, body]);
            if (path === '/api/tokens/scan') return answers.shift();
            return {saved: true, added: {rows: 2, cards: 3}, warnings: [], data: {...DATA, sha256: 's2'}}; };
          await shoot(ctx);
          same(calls[0], ['/api/tokens/scan', {photo: 'QUJD'}]);
          assert(ctx.message.textContent.includes('Added Fish (TBLB 7).'), ctx.message.textContent);
          await shoot(ctx);                                             // a second copy joins the first
          same(ctx.pending.map((c) => [c.front, c.set, c.quantity]), [['Fish', 'tblb', 2]]);
          await shoot(ctx);                                             // a face read alone: no printing recorded
          same(ctx.pending.map((c) => [c.front, c.set, c.back]), [['Fish', 'tblb', ''], ['Treasure', '', '']]);
          same(options(pick(ctx, 'Printing of Treasure')), ['Printing not recorded']);
          const single = pick(ctx, 'Treasure is single-sided (checked)');
          single.checked = true; single.fire('change');
          assert.equal(foot(ctx, 'review').textContent, 'Review 3 token cards');
          foot(ctx, 'review').click();
          assert(ctx.review.textContent.includes('already listed'), ctx.review.textContent);   // Fish: a row of its own
          assert.equal(foot(ctx, 'add').textContent, 'Add 3 token cards');
          foot(ctx, 'add').click(); await flush();
          const [path, body] = calls[calls.length - 1];
          assert.equal(path, '/api/tokens/scan/add');
          same(body, {sha256: 's1', rows: [
            {front: 'Fish', back: '', set: 'tblb', front_collector_number: '7', back_collector_number: '', quantity: 2, single_sided: false},
            {front: 'Treasure', back: '', set: '', front_collector_number: '', back_collector_number: '', quantity: 1, single_sided: true}]});
          assert(ctx.sheet.closed);
          assert.equal(view.data.sha256, 's2');
          assert(main.textContent.includes('Added 3 token cards.'), main.textContent);
        """)

    def test_the_back_stays_blank_until_chosen(self):
        self.run_js("""
          const ctx = openTokenScan(draw());
          const calls = [];
          apiWrite = async (path, body) => { calls.push(body); return RING; };
          await shoot(ctx);
          same(ctx.pending.map((c) => [c.front, c.back]), [['The Ring', '']]);   // never inferred from the printing
          assert.equal(pick(ctx, 'Back of The Ring').value, '');
          ctx.list.querySelector('[aria-label="Back of The Ring is The Ring Tempts You"]').click();
          same(ctx.pending.map((c) => [c.front, c.back, c.single]), [['The Ring', 'The Ring Tempts You', false]]);
          assert.equal(pick(ctx, 'The Ring is single-sided (checked)'), null);    // a card with a back isn't
          same(tokScanRows(ctx), [{front: 'The Ring', back: 'The Ring Tempts You', set: 'tltr', front_collector_number: 'H13',
            back_collector_number: 'H13', quantity: 1, single_sided: false}]);
          const back = pick(ctx, 'Back of The Ring');
          back.value = 'treasure'; back.fire('change');                // a typed back is its exact name, off the printing
          same(tokScanRows(ctx)[0], {front: 'The Ring', back: 'Treasure', set: 'tltr', front_collector_number: 'H13',
            back_collector_number: '', quantity: 1, single_sided: false});
          const printing = pick(ctx, 'Printing of The Ring');
          same(options(printing), ['Printing not recorded', 'TLTR H13']);
          printing.value = ''; printing.fire('change');
          same(tokScanRows(ctx)[0].set, '');
        """)

    def test_copies_of_one_card_join_whatever_their_single_sided_tick(self):
        self.run_js("""
          const ctx = openTokenScan(draw());
          apiWrite = async () => TREASURE;
          await shoot(ctx);
          const single = pick(ctx, 'Treasure is single-sided (checked)');
          single.checked = true; single.fire('change');
          ctx.name.value = 'Treasure';
          button(ctx.sheet.body, 'Add it').click();                   // an unticked copy: the server's same card
          same(ctx.pending.map((c) => [c.front, c.quantity, c.single]), [['Treasure', 2, false]]);
          same(tokScanRows(ctx).length, 1);
          const tick = pick(ctx, 'Treasure is single-sided (checked)');
          tick.checked = true; tick.fire('change');
          ctx.name.value = 'Treasure';
          button(ctx.sheet.body, 'Add it').click();
          const back = pick(ctx, 'Back of Treasure');               // a line with a back, then cleared, joins too
          back.value = 'Fish'; back.fire('change');
          ctx.name.value = 'Treasure';
          button(ctx.sheet.body, 'Add it').click();
          const ticked = [...ctx.list.querySelectorAll('[aria-label="Treasure is single-sided (checked)"]')];
          assert.equal(ticked.length, 1);
          ticked[0].checked = true; ticked[0].fire('change');
          same(ctx.pending.map((c) => [c.back, c.quantity, c.single]), [['Fish', 3, false], ['', 1, true]]);
          const backs = [...ctx.list.querySelectorAll('[aria-label="Back of Treasure"]')];
          backs[0].value = ''; backs[0].fire('change');
          same(ctx.pending.map((c) => [c.back, c.quantity, c.single]), [['', 4, false]]);
          same(tokScanRows(ctx).map((r) => [r.quantity, r.single_sided]), [[4, false]]);
          assert.equal(foot(ctx, 'review').disabled, false);
        """)

    def test_more_lines_than_one_change_takes_says_why(self):
        self.run_js("""
          const ctx = openTokenScan(draw());
          ctx.pending = Array.from({length: 51}, (_, i) => ({front: 'Treasure', back: '', single: false, set: 'tset',
            collector_number: String(i + 1), faces: ['Treasure'], quantity: 1, choices: []}));
          drawTokenScanPending(ctx);
          assert.equal(foot(ctx, 'review').disabled, true);
          assert(ctx.list.textContent.includes('At most 50 lines can be added at once'), ctx.list.textContent);
          ctx.pending.pop();
          drawTokenScanPending(ctx);
          assert.equal(foot(ctx, 'review').disabled, false);
          assert(!ctx.list.textContent.includes('At most 50'), ctx.list.textContent);
        """)

    def test_a_printing_without_the_face_read_is_chosen_not_guessed(self):
        self.run_js("""
          const ctx = openTokenScan(draw());
          apiWrite = async () => MIXED;
          await shoot(ctx);
          assert.equal(ctx.pending.length, 0);
          assert(ctx.message.textContent.includes('another token'), ctx.message.textContent);
          button(ctx.result, 'Fish (TBLB 7)').click();
          same(ctx.pending.map((c) => [c.front, c.set, c.collector_number]), [['Fish', 'tblb', '7']]);
        """)

    def test_a_typed_name_is_checked_against_the_token_faces(self):
        self.run_js("""
          const ctx = openTokenScan(draw());
          apiWrite = async () => ({ok: true, space: 'home', unread: true, proposals: [], read: null, lines: [],
            message: "Tesseract isn't installed. Type the token's name instead."});
          await shoot(ctx);
          assert(ctx.message.textContent.includes("Type the token's name instead."), ctx.message.textContent);
          ctx.name.value = 'Tresure';
          button(ctx.sheet.body, 'Add it').click();
          assert(ctx.message.textContent.includes('Did you mean Treasure?'), ctx.message.textContent);
          assert.equal(ctx.pending.length, 0);
          ctx.name.value = 'the ring // the ring tempts you';
          button(ctx.sheet.body, 'Add it').click();
          same(ctx.pending.map((c) => [c.front, c.back, c.set]), [['The Ring', '', '']]);
          const back = pick(ctx, 'Back of The Ring');
          back.value = 'Nonsense'; back.fire('change');
          assert(ctx.list.textContent.includes('"Nonsense" isn\\'t a token'), ctx.list.textContent);
          assert.equal(foot(ctx, 'review').disabled, true);             // fixed before it can be added
        """)

    def test_a_changed_list_keeps_the_cards_and_asks_again(self):
        self.run_js("""
          const view = draw();
          const ctx = openTokenScan(view);
          const latest = {...DATA, sha256: 's9', rows: []};
          let adds = 0;
          apiWrite = async (path, body) => {
            if (path === '/api/tokens/scan') return FISH;
            adds++;
            if (adds === 1) throw Object.assign(new ApiError(409, 'The tokens list changed after you opened it.'), {data: {latest}});
            assert.equal(body.sha256, 's9');
            return {saved: true, added: {rows: 1, cards: 1}, warnings: [], data: {...latest, sha256: 's10'}}; };
          await shoot(ctx);
          foot(ctx, 'review').click();
          foot(ctx, 'add').click(); await flush();
          assert(!ctx.sheet.closed);
          assert.equal(view.data.sha256, 's9');
          assert(ctx.message.textContent.includes('add them again'), ctx.message.textContent);
          same(ctx.pending.map((c) => [c.front, c.quantity]), [['Fish', 1]]);
          foot(ctx, 'add').click(); await flush();
          assert(ctx.sheet.closed);
          assert.equal(view.data.sha256, 's10');
        """)

    def test_a_member_scans_into_their_own_tokens_only(self):
        self.run_js("""
          assert.equal(openTokenScan(draw({space: 'user2'}, ['user1', MAY.user1], 'user2')), null);
          assert(!main.textContent.includes('Scan token cards'), 'read-only page offers no scan');
          const view = draw({space: 'user2', rows: []}, ['user2', MAY.user2], 'user2');
          const ctx = openTokenScan(view);
          assert(ctx.sheet.heading.textContent.includes("User2's tokens"));
          const calls = [];
          apiWrite = async (path, body) => { calls.push([path, body]); return TREASURE; };
          await shoot(ctx);
          same(calls[0], ['/api/tokens/scan', {photo: 'QUJD', space: 'user2'}]);
        """)
