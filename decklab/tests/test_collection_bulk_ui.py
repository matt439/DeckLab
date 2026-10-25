"""The Card list's "Set condition & language…" (E7-S29), over the real scripts with fixture answers."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  const row = (name, set, number, condition = '', language = '', notes = '') => ({name, set, collector_number: number,
    finish: 'nonfoil', quantity: 1, condition, language, notes});
  const rows = [row('Llanowar Elves', 'fdn', '227'), row('Sol Ring', 'sld', '2539', 'LP'),
    row('Black Lotus', 'lea', '232', '', 'ja', 'Merged copies have differing or unreported condition'),
    row('Arcane Signet', 'sld', '2538', 'NM', 'en')];
  const draw = (data = {}) => { clear(main); as('matt', MAY.admin);
    return drawCollectionRows({space: 'home', sha256: 's1', rows, editable: true, ...data}, 'home'); };
  const opener = () => main.querySelector('.col-bulk-open');
  const tick = (id) => { const box = main.querySelector(id); box.checked = true; box.fire('change'); };
  const open = () => { opener().click(); const handle = [...colSheets].pop(), sheet = handle.dialog;
    return {handle, sheet, summary: () => sheet.querySelector('.col-bulk-summary').textContent,
      language: sheet.querySelector('select'), blank: sheet.querySelector('input[type="checkbox"]'),
      condition: (text) => button(sheet, text).click()}; };
  const choose = (select, value) => { select.value = value; select.fire('change'); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionBulkUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_it_acts_on_the_shown_rows_and_says_what_save_will_do(self):
        self.run_js("""
          draw(); tick('#col-unrecorded');          // Condition or language not recorded: three of the four rows
          const s = open();
          assert(s.sheet.textContent.includes('For the 3 rows shown (of 4, after the search and filters)'));
          assert.equal(s.summary(), 'Choose a condition, a language or both.');
          assert(button(s.sheet, 'Save').disabled);
          // One of them has merged copies that didn't agree: said, so Matt can decide.
          assert(s.sheet.querySelector('.col-bulk-merged').textContent.includes('1 row holds copies whose conditions'));
          choose(s.language, 'en');
          assert.equal(s.summary(), 'Sets language English on 2 rows; 1 already has a language.');
          s.condition('NM');
          assert.equal(s.summary(), 'Sets language English on 2 rows and condition NM on 2 rows; 1 already has a language; 1 already has a condition.');
          assert(!button(s.sheet, 'Save 3 rows').disabled);
          // Not only blanks: Black Lotus's Japanese becomes English too, and Sol Ring's LP becomes NM.
          s.blank.checked = false; s.blank.fire('change');
          assert.equal(s.summary(), 'Sets language English on 3 rows and condition NM on 3 rows.');
          assert(button(s.sheet, 'Save 3 rows'));
        """)

    def test_save_posts_the_rows_it_changes_and_shows_the_answer(self):
        self.run_js("""
          const cv = draw(); tick('#col-unrecorded');
          const s = open(); choose(s.language, 'en');
          const calls = [];
          const after = rows.map(r => ({...r, language: r.language || 'en'}));
          apiWrite = async (path, body) => { calls.push([path, body]);
            return {ok: true, sha256: 's2', rows: after, changed: 2, stale_tables: []}; };
          button(s.sheet, 'Save 2 rows').click(); await flush();
          same(calls, [['/api/collection/bulk', {space: 'home', sha256: 's1', language: 'en', only_blank: true,
            keys: [{set: 'fdn', collector_number: '227', finish: 'nonfoil'}, {set: 'sld', collector_number: '2539', finish: 'nonfoil'}]}]]);
          assert(s.handle.closed);
          assert.equal(cv.sha256, 's2');
          assert(main.querySelector('.col-message').textContent.includes('Language saved on 2 rows.'));
          // Every row has its language now: only the two without a condition are still unrecorded.
          assert.equal(main.querySelectorAll('tr').filter(tr => tr.getAttribute('data-key')).length, 2);
        """)

    def test_a_condition_and_overwrite_post_every_shown_row_and_lock_the_sheet(self):
        self.run_js("""
          const cv = draw(); tick('#col-unrecorded');
          const s = open(); choose(s.language, 'en'); s.condition('NM');
          s.blank.checked = false; s.blank.fire('change');
          const calls = []; let answer;
          apiWrite = (path, body) => { calls.push([path, body]); return new Promise((done) => { answer = done; }); };
          button(s.sheet, 'Save 3 rows').click();
          // While it's on its way, the choices can't change what the sheet says it's sending.
          assert(s.language.disabled && s.blank.disabled && button(s.sheet, 'LP').disabled);
          const foot = s.handle.foot.querySelectorAll('button');
          assert(foot.length === 2 && foot.every(b => b.disabled));
          same(calls, [['/api/collection/bulk', {space: 'home', sha256: 's1', condition: 'NM', language: 'en', only_blank: false,
            keys: [{set: 'lea', collector_number: '232', finish: 'nonfoil'}, {set: 'fdn', collector_number: '227', finish: 'nonfoil'},
              {set: 'sld', collector_number: '2539', finish: 'nonfoil'}]}]]);
          answer({ok: true, sha256: 's2', rows: rows.map(r => ({...r, condition: 'NM', language: 'en'})), changed: 3,
            stale_tables: [{id: 'casual/x', title: 'X'}]});
          await flush();
          const said = main.querySelector('.col-message').textContent;
          assert(said.includes('Condition and language saved on 3 rows.'), said);
          assert(said.includes('See them on Decks'), said);           // the out-of-date tables, as a single save says
        """)

    def test_when_nothing_is_shown_after_a_save_the_search_keeps_the_focus(self):
        self.run_js("""
          draw(); tick('#col-unrecorded');
          const search = main.querySelector('#col-row-search'); search.value = 'elves'; search.fire('input');
          const s = open(); choose(s.language, 'en'); s.condition('NM');
          // The Elves are recorded now; other rows still aren't, so the filter stays on and shows nothing.
          apiWrite = async () => ({ok: true, sha256: 's2', changed: 1, stale_tables: [],
            rows: rows.map(r => r.name === 'Llanowar Elves' ? {...r, condition: 'NM', language: 'en'} : r)});
          button(s.sheet, 'Save 1 row').click(); await flush();
          assert(opener().hidden);
          assert.equal(document.activeElement, search);
        """)

    def test_a_refresh_that_clears_a_filter_never_widens_it(self):
        self.run_js("""
          const cv = draw(); tick('#col-unrecorded');
          const s = open(); choose(s.language, 'en');
          s.blank.checked = false; s.blank.fire('change');
          // Someone recorded everything meanwhile: the not-recorded filter turns itself off with the latest list.
          const latest = rows.map(r => ({...r, condition: r.condition || 'NM', language: r.language || 'de'}));
          apiWrite = async () => { throw new ApiError(409, 'The home collection has changed since the page loaded it.',
            {sha256: 's9', rows: latest}); };
          button(s.sheet, 'Save 3 rows').click(); await flush();
          assert(!cv.unrecordedOnly);
          assert(s.sheet.textContent.includes('no longer applies'));
          assert(s.sheet.textContent.includes('For the 3 rows it was opened on that are still listed.'));
          assert.equal(s.summary(), 'Sets language English on 3 rows.');      // not Arcane Signet, already English
          const calls = []; apiWrite = async (path, body) => { calls.push(body); return {ok: true, sha256: 's10', rows: latest, changed: 3}; };
          button(s.sheet, 'Save 3 rows').click(); await flush();
          same(calls[0].keys.map(k => k.set).sort(), ['fdn', 'lea', 'sld']);
        """)

    def test_a_refresh_that_leaves_nothing_shown_says_so(self):
        self.run_js("""
          draw();
          const search = main.querySelector('#col-row-search'); search.value = 'elves'; search.fire('input');
          const s = open(); choose(s.language, 'en');
          apiWrite = async () => { throw new ApiError(409, 'The home collection has changed since the page loaded it.',
            {sha256: 's9', rows: rows.slice(1)}); };
          button(s.sheet, 'Save 1 row').click(); await flush();
          assert(s.sheet.textContent.includes('No rows are shown now: close this, then change the search or filters.'));
          assert.equal(s.summary(), '');
          assert(button(s.sheet, 'Close'));
          assert.equal(s.sheet.querySelectorAll('button').filter(b => b.textContent.startsWith('Save')).length, 0);
        """)

    def test_a_search_narrows_it_and_read_only_has_no_button(self):
        self.run_js("""
          draw();
          const search = main.querySelector('#col-row-search'); search.value = 'sol'; search.fire('input');
          const s = open();
          assert(s.sheet.textContent.includes('For the 1 row shown (of 4'));
          choose(s.language, 'en');
          assert.equal(s.summary(), 'Sets language English on 1 row.');
          s.handle.close();
          search.value = 'no such card'; search.fire('input');
          assert(opener().hidden);
          draw({editable: false});
          assert.equal(opener(), null);
        """)

    def test_a_changed_collection_shows_the_latest_and_saves_nothing(self):
        self.run_js("""
          const cv = draw(); tick('#col-unrecorded');
          const s = open(); choose(s.language, 'en');
          const latest = [...rows.slice(1), row('Opt', 'dmu', '60')];      // Elves gone, Opt added meanwhile
          apiWrite = async () => { throw new ApiError(409, 'The home collection has changed since the page loaded it.',
            {sha256: 's9', rows: latest}); };
          button(s.sheet, 'Save 2 rows').click(); await flush();
          assert(!s.handle.closed);
          assert.equal(cv.sha256, 's9');
          assert(s.sheet.textContent.includes('Nothing was saved'));
          assert(s.sheet.textContent.includes('For the 3 rows shown'));
          assert.equal(s.summary(), 'Sets language English on 2 rows; 1 already has a language.');
          const calls = []; apiWrite = async (path, body) => { calls.push(body); return {ok: true, sha256: 's10', rows: latest, changed: 2}; };
          button(s.sheet, 'Save 2 rows').click(); await flush();
          same(calls[0].keys.map(k => k.set), ['dmu', 'sld']);
          assert.equal(calls[0].sha256, 's9');
        """)
