"""The Collection page's "Scan cards…" (E7-S32, collection-scan.js), over the real scripts with fixture answers.

The photo's shrinking (a canvas, in the browser) is stood in for; POST /api/collection/scan's answers are
fixtures, and Review hands the pending list to the Import cards sheet's preview as a collection-columns CSV.
"""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  const rows = [{name: 'Llanowar Elves', set: 'fdn', collector_number: '227', finish: 'nonfoil', quantity: '4',
    condition: 'NM', language: 'en', notes: ''}];
  const draw = (data = {}) => { clear(main); as('matt', MAY.admin);
    return drawCollectionRows({space: 'home', sha256: 's1', rows, editable: true, ...data}, 'home'); };
  const proposal = (name, set, number, how, extra = {}) => ({name, set, collector_number: number, set_name: set.toUpperCase(),
    finish: 'nonfoil', language: 'en', how, img_small: null, owned: 0, ...extra});
  const ELVES = {ok: true, space: 'home', unread: false, message: 'Read Llanowar Elves, FDN 227.',
    proposals: [proposal('Llanowar Elves', 'fdn', '227', 'name and number', {owned: 4}),
                proposal('Llanowar Elves', 'm19', '314', 'name')]};
  const GHALTA = {ok: true, space: 'home', unread: false, message: 'Read Ghalta, Primal Hunger, but not its set code: choose the printing.',
    proposals: [proposal('Ghalta, Primal Hunger', 'rix', '130', 'name'), proposal('Ghalta, Primal Hunger', 'cmm', '289', 'name')]};
  colScanShrink = async () => 'QUJD';
  const foot = (ctx, action) => ctx.sheet.foot.querySelector(`[data-action="${action}"]`);
  const shoot = async (ctx) => { ctx.input.files = [{name: 'photo.jpg'}]; ctx.input.fire('change'); await flush(); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionScanUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_photos_fill_the_pending_list_and_review_previews_them_as_an_import(self):
        self.run_js("""
          const cv = draw();
          const ctx = openScanSheet(cv);
          assert.equal(ctx.input.getAttribute('capture'), 'environment');
          assert.equal(ctx.input.getAttribute('accept'), 'image/*');
          assert.equal(foot(ctx, 'review'), null);                    // nothing to review yet
          const calls = [];
          const answers = [ELVES, ELVES, GHALTA];
          apiWrite = async (path, body) => { calls.push([path, body]);
            if (path === '/api/collection/scan') return answers.shift();
            return {token: 't'.repeat(32), format: 'collection', rows: [], problems: [], adds: {rows: 2, cards: 3},
              dropped_basics: 0, sha256: 's1', repeat_imports: []}; };
          await shoot(ctx);
          same(calls[0], ['/api/collection/scan', {space: 'home', photo: 'QUJD'}]);
          assert(ctx.message.textContent.includes('Added Llanowar Elves (FDN 227).'), ctx.message.textContent);
          assert(ctx.result.textContent.includes('Not that one?'), ctx.result.textContent);
          await shoot(ctx);                                             // a second copy of the same printing
          assert.equal(ctx.pending.length, 1);
          assert.equal(ctx.pending[0].quantity, 2);
          await shoot(ctx);                                             // only the name read: nothing added until chosen
          assert.equal(ctx.pending.length, 1);
          assert(ctx.message.textContent.includes('choose the printing'), ctx.message.textContent);
          button(ctx.result, 'Ghalta, Primal Hunger (RIX 130) · RIX').click();
          assert.equal(ctx.pending.length, 2);
          const condition = ctx.list.querySelectorAll('select')[3];     // Ghalta's condition (finish, condition each)
          condition.value = 'LP'; condition.fire('change');
          assert.equal(foot(ctx, 'review').textContent, 'Review 3 cards');
          foot(ctx, 'review').click(); await flush();
          assert(ctx.sheet.closed);
          const [path, body] = calls[calls.length - 1];
          assert.equal(path, '/api/collection/import/preview');
          assert.equal(body.space, 'home');
          assert(/^scan-\\d{4}-\\d{2}-\\d{2}\\.csv$/.test(body.filename), body.filename);
          assert.equal(body.text, 'name,set,collector_number,finish,quantity,condition,language,notes\\n'
            + 'Llanowar Elves,fdn,227,nonfoil,2,,en,\\n'
            + '"Ghalta, Primal Hunger",rix,130,nonfoil,1,LP,en,\\n');
        """)

    def test_choosing_another_printing_replaces_the_one_added(self):
        self.run_js("""
          const ctx = openScanSheet(draw());
          apiWrite = async () => ELVES;
          await shoot(ctx);
          button(ctx.result, 'Llanowar Elves (M19 314) · M19').click();
          same(ctx.pending.map((c) => [c.set, c.collector_number, c.quantity]), [['m19', '314', 1]]);
        """)

    def test_reprints_sharing_the_number_read_are_chosen_not_guessed(self):
        self.run_js("""
          const ctx = openScanSheet(draw());
          apiWrite = async () => ({ok: true, space: 'home', unread: false,
            message: 'Read Llanowar Elves, but more than one printing has that number: choose the printing.',
            proposals: [proposal('Llanowar Elves', 'aaa', '314', 'name and number'),
                        proposal('Llanowar Elves', 'bbb', '314', 'name and number')]});
          await shoot(ctx);
          assert.equal(ctx.pending.length, 0);
          assert(ctx.message.textContent.includes('choose the printing'), ctx.message.textContent);
          assert(ctx.result.textContent.includes('Choose its printing:'), ctx.result.textContent);
          button(ctx.result, 'Llanowar Elves (BBB 314) · BBB').click();
          same(ctx.pending.map((c) => [c.set, c.collector_number, c.quantity]), [['bbb', '314', 1]]);
        """)

    def test_a_preview_with_problems_or_failing_goes_back_to_the_scanned_list(self):
        self.run_js("""
          const cv = draw();
          let ctx = openScanSheet(cv);
          const previews = [
            {token: 't'.repeat(32), format: 'collection', rows: [], problems: [{line: 2, message: 'No foil printing.'}],
              adds: {rows: 1, cards: 1}, dropped_basics: 0, sha256: 's1', repeat_imports: []},
            new ApiError(503, 'The database can\\'t be reached.')];
          apiWrite = async (path) => { if (path === '/api/collection/scan') return ELVES;
            const next = previews.shift(); if (next instanceof Error) throw next; return next; };
          await shoot(ctx);
          ctx.list.querySelectorAll('select')[0].value = 'foil';
          ctx.list.querySelectorAll('select')[0].fire('change');
          foot(ctx, 'review').click(); await flush();
          let importing = [...colSheets][colSheets.size - 1];
          assert(importing.body.textContent.includes('go back to the scanned list'), importing.body.textContent);
          importing.foot.querySelector('[data-action="back"]').click();
          assert(importing.closed);
          importing = [...colSheets][colSheets.size - 1];
          const list = importing.body.querySelector('.col-scan-pending');
          assert(list.textContent.includes('Llanowar Elves (FDN 227)'), list.textContent);
          assert.equal(list.querySelectorAll('select')[0].value, 'foil');
          importing.foot.querySelector('[data-action="review"]').click(); await flush();
          const failed = [...colSheets][colSheets.size - 1];
          assert(failed.body.textContent.includes("can't be reached"), failed.body.textContent);
          failed.foot.querySelector('[data-action="back"]').click();
          assert([...colSheets][colSheets.size - 1].body.querySelector('.col-scan-pending').textContent.includes('Llanowar Elves'));
        """)

    def test_an_unread_photo_offers_the_name_and_its_printings(self):
        self.run_js("""
          const ctx = openScanSheet(draw());
          apiWrite = async () => ({ok: true, space: 'home', unread: true, proposals: [], read: null, lines: [],
            message: "Windows' OCR engine is only on Windows. Tesseract isn't installed. Type the card's name instead."});
          await shoot(ctx);
          assert(ctx.message.textContent.includes("Type the card's name instead."), ctx.message.textContent);
          assert.equal(ctx.pending.length, 0);
          const asked = [];
          api = async (path) => { asked.push(path);
            if (path.includes('Nonsense')) throw new ApiError(404, "No card named 'Nonsense'");
            return {name: 'Arcane Signet', printings: [{set: 'm3c', set_name: 'Modern Horizons 3 Commander',
              collector_number: '283', finishes: ['foil', 'nonfoil'], released: '2024-06-14'}]}; };
          ctx.name.value = 'Nonsense';
          button(ctx.sheet.body, 'Find its printings').click(); await flush();
          assert(ctx.message.textContent.includes('There\\'s no card named "Nonsense"'), ctx.message.textContent);
          ctx.name.value = 'arcane signet';
          button(ctx.sheet.body, 'Find its printings').click(); await flush();
          assert.equal(asked[1], '/api/printings?name=arcane%20signet');
          button(ctx.result, 'Arcane Signet (M3C 283) · Modern Horizons 3 Commander').click();
          same(ctx.pending.map((c) => [c.name, c.finish, c.language, c.condition]), [['Arcane Signet', 'nonfoil', '', '']]);
        """)

    def test_a_failed_scan_says_why_and_takes_another_photo(self):
        self.run_js("""
          const ctx = openScanSheet(draw());
          apiWrite = async () => { throw new ApiError(429, 'Another photo is being read right now; try again in a moment.'); };
          await shoot(ctx);
          assert(ctx.message.textContent.includes('Another photo is being read'), ctx.message.textContent);
          assert.equal(ctx.busy, false);
          assert.equal(ctx.input.disabled, false);
        """)

    def test_only_where_the_visitor_may_change_the_collection(self):
        self.run_js("""
          assert.equal(openScanSheet(draw({editable: false})), null);
          assert.equal(colSheets.size, 0);
          const more = main.textContent;
          assert(!more.includes('Scan cards'), 'read-only page offers no scan');
        """)
