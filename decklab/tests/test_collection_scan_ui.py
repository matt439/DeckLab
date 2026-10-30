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
  const pick = (ctx, label) => ctx.list.querySelector(`[aria-label="${label}"]`);
  const options = (select) => [...select.querySelectorAll('option')].map((o) => o.textContent);
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
          const condition = pick(ctx, 'Condition of Ghalta, Primal Hunger');
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
          pick(ctx, 'Finish of Llanowar Elves').value = 'foil';
          pick(ctx, 'Finish of Llanowar Elves').fire('change');
          foot(ctx, 'review').click(); await flush();
          let importing = [...colSheets][colSheets.size - 1];
          assert(importing.body.textContent.includes('go back to the scanned list'), importing.body.textContent);
          importing.foot.querySelector('[data-action="back"]').click();
          assert(importing.closed);
          importing = [...colSheets][colSheets.size - 1];
          const list = importing.body.querySelector('.col-scan-pending');
          assert(list.textContent.includes('Llanowar Elves (FDN 227)'), list.textContent);
          assert.equal(list.querySelector('[aria-label="Finish of Llanowar Elves"]').value, 'foil');
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

    def test_a_pending_card_s_printing_is_chosen_from_the_scan_s_proposals(self):
        self.run_js("""
          const ctx = openScanSheet(draw());
          apiWrite = async () => ELVES;
          await shoot(ctx);
          const printing = pick(ctx, 'Printing of Llanowar Elves');
          same(options(printing), ['FDN 227 · 4 listed', 'M19 314']);
          assert.equal(printing.value, '0');
          ctx.pending[0].finish = 'foil';                               // a finish the choice may not have
          printing.value = '1'; printing.fire('change');
          same(ctx.pending.map((c) => [c.set, c.collector_number, c.finish, c.quantity]), [['m19', '314', 'nonfoil', 1]]);
          assert(ctx.list.textContent.includes('Llanowar Elves (M19 314)'), ctx.list.textContent);
          await shoot(ctx);                                             // FDN 227 again: a row of its own
          same(ctx.pending.map((c) => [c.set, c.quantity]), [['m19', 1], ['fdn', 1]]);
          const second = ctx.list.querySelectorAll('[aria-label="Printing of Llanowar Elves"]')[1];
          second.value = '1'; second.fire('change');                    // now the same printing: the two join
          same(ctx.pending.map((c) => [c.set, c.collector_number, c.quantity]), [['m19', '314', 2]]);
          same(options(pick(ctx, 'Printing of Llanowar Elves')), ['FDN 227 · 4 listed', 'M19 314']);
        """)

    def test_a_proposal_s_finish_stays_when_the_printing_chosen_has_it(self):
        self.run_js("""
          const ctx = openScanSheet(draw());
          apiWrite = async () => ({...ELVES, proposals: [
            proposal('Llanowar Elves', 'fdn', '227', 'name and number', {finishes: ['nonfoil', 'foil']}),
            proposal('Llanowar Elves', 'm19', '314', 'name', {finishes: ['nonfoil', 'foil']})]});
          await shoot(ctx);
          pick(ctx, 'Finish of Llanowar Elves').value = 'foil';
          pick(ctx, 'Finish of Llanowar Elves').fire('change');
          const printing = pick(ctx, 'Printing of Llanowar Elves');
          printing.value = '1'; printing.fire('change');
          same(ctx.pending.map((c) => [c.set, c.finish]), [['m19', 'foil']]);
        """)

    def test_other_printings_open_the_shared_printing_picker(self):
        self.run_js("""
          const ctx = openScanSheet(draw());
          apiWrite = async () => ELVES;
          await shoot(ctx);
          const asked = [];
          let answer = null;
          pickPrinting = async (name, opts) => { asked.push([name, opts.current]);
            const sheet = {closed: false}; opts.onOpen(sheet); assert(colSheets.has(sheet)); return answer; };
          button(ctx.list, 'Other printings…').click(); await flush();
          same(asked[0], ['Llanowar Elves', {set: 'fdn', number: '227', finish: 'nonfoil'}]);
          same(ctx.pending.map((c) => [c.set, c.collector_number]), [['fdn', '227']]);   // closed: nothing changes
          answer = {set: null, number: null, finish: 'nonfoil'};                          // a basic's Any printing isn't one
          button(ctx.list, 'Other printings…').click(); await flush();
          same(ctx.pending.map((c) => [c.set, c.collector_number]), [['fdn', '227']]);
          answer = {set: 'jmp', number: '393', finish: 'foil', set_name: 'Jumpstart', owned: 1,
            finish_choices: ['nonfoil', 'foil']};
          button(ctx.list, 'Other printings…').click(); await flush();
          same(ctx.pending.map((c) => [c.set, c.collector_number, c.finish, c.quantity]), [['jmp', '393', 'foil', 1]]);
          // FDN 227's 4 listed are nonfoil, so not shown beside a foil card.
          same(options(pick(ctx, 'Printing of Llanowar Elves')), ['FDN 227', 'M19 314', 'JMP 393 · Jumpstart · 1 listed']);
          assert.equal(pick(ctx, 'Printing of Llanowar Elves').value, '2');
          assert.equal(colSheets.size, 1);                              // the picker's sheet is let go
          // The picked printing keeps its finishes: chosen again, the card's finish stays when it has it.
          pick(ctx, 'Finish of Llanowar Elves').value = 'nonfoil';
          pick(ctx, 'Finish of Llanowar Elves').fire('change');
          let printing = pick(ctx, 'Printing of Llanowar Elves');
          printing.value = '1'; printing.fire('change');
          printing = pick(ctx, 'Printing of Llanowar Elves');
          printing.value = '2'; printing.fire('change');
          same(ctx.pending.map((c) => [c.set, c.finish]), [['jmp', 'nonfoil']]);
          same(options(pick(ctx, 'Printing of Llanowar Elves')), ['FDN 227 · 4 listed', 'M19 314', 'JMP 393 · Jumpstart']);
        """)

    def test_a_card_taken_out_while_the_picker_is_open_stays_out(self):
        self.run_js("""
          const ctx = openScanSheet(draw());
          const answers = [ELVES, ELVES, GHALTA];
          apiWrite = async () => answers.shift();
          await shoot(ctx);
          const printing = pick(ctx, 'Printing of Llanowar Elves');
          printing.value = '1'; printing.fire('change');                // M19 314
          await shoot(ctx);                                             // FDN 227: a row of its own
          await shoot(ctx);
          button(ctx.result, 'Ghalta, Primal Hunger (RIX 130) · RIX').click();
          same(ctx.pending.map((c) => [c.set, c.quantity]), [['m19', 1], ['fdn', 1], ['rix', 1]]);
          let resolve;
          pickPrinting = () => new Promise((r) => { resolve = r; });
          button(ctx.list, 'Other printings…').click();                // the M19 row's
          button(ctx.list, 'Take out').click();                         // ... taken out while it's open
          resolve({set: 'fdn', number: '227', finish: 'nonfoil', finish_choices: ['nonfoil']}); await flush();
          // It isn't joined to the FDN row, and no other row goes.
          same(ctx.pending.map((c) => [c.name, c.set, c.quantity]),
            [['Llanowar Elves', 'fdn', 1], ['Ghalta, Primal Hunger', 'rix', 1]]);
        """)

    def test_a_card_s_printing_choices_are_only_its_own_name_s(self):
        self.run_js("""
          const ctx = openScanSheet(draw());
          apiWrite = async () => ({...ELVES, proposals: [...ELVES.proposals,
            proposal('Elvish Mystic', 'xyz', '227', 'number')]});
          await shoot(ctx);
          same(options(pick(ctx, 'Printing of Llanowar Elves')), ['FDN 227 · 4 listed', 'M19 314']);
          assert(ctx.result.textContent.includes('Elvish Mystic (XYZ 227)'), ctx.result.textContent);
          button(ctx.result, 'Elvish Mystic (XYZ 227) · XYZ').click();   // instead: that card, with its own choices
          same(ctx.pending.map((c) => [c.name, c.set]), [['Elvish Mystic', 'xyz']]);
          same(options(pick(ctx, 'Printing of Elvish Mystic')), ['XYZ 227']);
        """)

    def test_language_is_as_read_else_not_recorded_and_goes_to_the_preview(self):
        self.run_js("""
          const ctx = openScanSheet(draw());
          const calls = [];
          apiWrite = async (path, body) => { calls.push([path, body]);
            if (path === '/api/collection/scan') return ELVES;
            return {token: 't'.repeat(32), format: 'collection', rows: [], problems: [{line: 2, message: 'Check it.'}],
              adds: {rows: 2, cards: 2}, dropped_basics: 0, sha256: 's1', repeat_imports: []}; };
          api = async () => ({name: 'Arcane Signet', printings: [{set: 'm3c', set_name: 'Modern Horizons 3 Commander',
            collector_number: '283', finishes: ['foil', 'nonfoil'], released: '2024-06-14'}]});
          await shoot(ctx);
          ctx.name.value = 'Arcane Signet';
          button(ctx.sheet.body, 'Find its printings').click(); await flush();
          button(ctx.result, 'Arcane Signet (M3C 283) · Modern Horizons 3 Commander').click();
          assert.equal(pick(ctx, 'Language of Llanowar Elves').value, 'en');           // printed on the card, read
          const signet = pick(ctx, 'Language of Arcane Signet');
          assert.equal(signet.value, '');                                              // not read: never assumed English
          assert.equal(options(signet)[0], 'Not recorded');
          assert(options(signet).includes('Japanese (ja)'));
          signet.value = 'ja'; signet.fire('change');
          same(options(pick(ctx, 'Printing of Arcane Signet')), ['M3C 283 · Modern Horizons 3 Commander']);
          foot(ctx, 'review').click(); await flush();
          assert.equal(calls[calls.length - 1][1].text, 'name,set,collector_number,finish,quantity,condition,language,notes\\n'
            + 'Llanowar Elves,fdn,227,nonfoil,1,,en,\\n' + 'Arcane Signet,m3c,283,nonfoil,1,,ja,\\n');
          // Back to the scanned list: the same languages and printing choices.
          const importing = [...colSheets][colSheets.size - 1];
          importing.foot.querySelector('[data-action="back"]').click();
          const again = [...colSheets][colSheets.size - 1].body.querySelector('.col-scan-pending');
          assert.equal(again.querySelector('[aria-label="Language of Arcane Signet"]').value, 'ja');
          same(options(again.querySelector('[aria-label="Printing of Llanowar Elves"]')), ['FDN 227 · 4 listed', 'M19 314']);
        """)

    def test_a_language_change_joining_another_row_adds_its_copies(self):
        self.run_js("""
          const ctx = openScanSheet(draw());
          const answers = [ELVES, {...ELVES, proposals: [proposal('Llanowar Elves', 'fdn', '227', 'name and number',
            {language: ''})]}];
          apiWrite = async () => answers.shift();
          await shoot(ctx); await shoot(ctx);
          same(ctx.pending.map((c) => [c.language, c.quantity]), [['en', 1], ['', 1]]);
          const blank = ctx.list.querySelectorAll('[aria-label="Language of Llanowar Elves"]')[1];
          blank.value = 'en'; blank.fire('change');
          same(ctx.pending.map((c) => [c.language, c.quantity]), [['en', 2]]);
        """)
