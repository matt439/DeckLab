"""Explicit loan/whole-return controls, review recovery and stale callback privacy."""
import json
import subprocess
import unittest

from decklab.tests.test_collection_bulk_ui import FIXTURE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


LOANS = FIXTURE + """
  const loan = {id: 'a'.repeat(32), name: 'Llanowar Elves', set: 'fdn', collector_number: '227', finish: 'nonfoil',
    quantity: '2', borrower: 'User1', lent_on: '2026-11-11', returned_on: '', notes: 'PRIVATE LOAN NOTE'};
  const calls = [];
  api = async () => ({space: 'home', loans: [loan], next: null, ready: true});
  const loanSheet = async () => { const cv = draw(); return openCollectionLoans(cv); };
  const lendForm = async () => { const ctx = await loanSheet(); button(ctx.sheet.dialog, 'Lend copies…').click(); return ctx; };
  const fill = ctx => { ctx.printing.value = colKey(rows[0]); ctx.quantity.value = '1'; ctx.borrower.value = 'User1'; ctx.date.value = '2026-11-11'; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LoanUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), LOANS + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_lend_needs_explicit_printing_borrower_and_posts_only_observed_loan_facts(self):
        self.run_js("""
          const ctx = await lendForm();
          assert.equal(ctx.printing.value, ''); assert.equal(ctx.borrower.value, '');
          apiWrite = async (path, body) => { calls.push([path, body]); return {ok: true, loan, rows, sha256: 's1', stale_tables: []}; };
          button(ctx.sheet.dialog, 'Lend copies').click(); await flush(); assert.equal(calls.length, 0);
          fill(ctx); ctx.notes.value = 'Observed note';
          button(ctx.sheet.dialog, 'Lend copies').click(); await flush();
          same(calls, [['/api/collection/lend', {space: 'home', sha256: 's1', row: {name: 'Llanowar Elves', set: 'fdn',
            collector_number: '227', finish: 'nonfoil', quantity: 1, borrower: 'User1', lent_on: '2026-11-11', notes: 'Observed note'}}]]);
          assert(ctx.sheet.closed); assert(main.textContent.includes('Loan recorded.'));
        """)

    def test_return_is_explicit_all_copies_and_uses_only_the_reviewed_loan_id(self):
        self.run_js("""
          const ctx = await loanSheet();
          assert(ctx.sheet.dialog.textContent.includes('PRIVATE LOAN NOTE'));
          button(ctx.sheet.dialog, 'Record return…').click();
          assert(ctx.content.textContent.includes('all 2 copies'));
          ctx.date.value = '2026-11-12';
          apiWrite = async (path, body) => { calls.push([path, body]); return {ok: true, loan: {...loan, returned_on: '2026-11-12'}, rows, sha256: 's1', stale_tables: []}; };
          button(ctx.sheet.dialog, 'Record return').click(); await flush();
          same(calls, [['/api/collection/return', {space: 'home', loan_id: 'a'.repeat(32), returned_on: '2026-11-12'}]]);
          assert(ctx.sheet.closed); assert(main.textContent.includes('Return recorded.'));
        """)

    def test_stale_receipt_requires_explicit_refresh_preserves_draft_and_never_auto_lends(self):
        self.run_js("""
          const ctx = await lendForm(); fill(ctx); ctx.notes.value = 'Keep my note';
          apiWrite = async (path, body) => { calls.push([path, body]); throw new ApiError(409, 'Collection changed'); };
          button(ctx.sheet.dialog, 'Lend copies').click(); await flush();
          assert.equal(ctx.borrower.value, 'User1'); assert.equal(ctx.notes.value, 'Keep my note');
          assert(ctx.message.textContent.includes('Nothing saved.'));
          api = async () => ({space: 'home', rows, sha256: 's2'});
          button(ctx.sheet.dialog, 'Refresh collection and review').click(); await flush();
          assert.equal(calls.length, 1); assert.equal(ctx.reviewSha, 's2'); assert.equal(ctx.borrower.value, 'User1');
          assert.equal(ctx.notes.value, 'Keep my note'); assert.equal(ctx.printing.value, colKey(rows[0]));
          apiWrite = async (path, body) => { calls.push([path, body]); return {ok: true, loan, rows, sha256: 's2', stale_tables: []}; };
          button(ctx.sheet.dialog, 'Lend copies').click(); await flush(); assert.equal(calls[1][1].sha256, 's2');
        """)

    def test_uncertain_server_result_disables_replay_and_detached_controls_never_write(self):
        self.run_js("""
          const ctx = await lendForm(); fill(ctx); const old = button(ctx.sheet.dialog, 'Lend copies');
          apiWrite = async () => { calls.push('write'); throw new ApiError(500, 'Unconfirmed result'); };
          old.click(); await flush();
          assert(ctx.unknown); assert(ctx.message.textContent.includes("save result couldn't be confirmed"));
          old.click(); await flush(); assert.equal(calls.length, 1);
          assert(!button(ctx.sheet.dialog, 'Lend copies')); button(ctx.sheet.dialog, 'Close').click();
          old.click(); await flush(); assert.equal(calls.length, 1);
        """)

    def test_late_private_reads_and_closed_or_changed_profile_controls_are_ignored(self):
        self.run_js("""
          let resolve; api = () => new Promise(done => { resolve = done; });
          const cv = draw(); const pending = openCollectionLoans(cv); await flush();
          const sheet = [...colSheets].at(-1); as('user2', MAY.user2); sheet.close();
          resolve({space: 'home', loans: [loan], next: null, ready: true}); await pending;
          assert(!document.body.textContent.includes('PRIVATE LOAN NOTE'));
          api = async () => ({space: 'home', loans: [], next: null, ready: true});
          const ctx = await lendForm(); fill(ctx); const old = button(ctx.sheet.dialog, 'Lend copies');
          apiWrite = async () => { calls.push('write'); return {}; };
          as('user2', MAY.user2); old.click(); await flush(); assert.equal(calls.length, 0);
        """)

    def test_read_only_collection_cannot_open_private_loan_controls(self):
        self.run_js("""
          api = async () => { throw Error('Private loan request'); };
          const cv = draw({editable: false});
          assert.equal(await openCollectionLoans(cv), null);
        """)

    def test_owned_needed_table_names_lent_copies_without_borrower_or_date(self):
        self.run_js("""
          draw();
          const owned = {name: 'Llanowar Elves', need: 2, owned: 2, available: 1, missing: 1, aud_each: null, aud_missing: null,
            priced_finish: null, labels: {on_the_way: [], in_use: [], lent_out: 1}, on_the_way: 0, on_the_way_from: []};
          const node = ownedRow(owned, 1, true);
          assert(node.textContent.includes('1 lent out'));
          assert(!node.textContent.includes('User1')); assert(!node.textContent.includes('2026-11-11'));
        """)
