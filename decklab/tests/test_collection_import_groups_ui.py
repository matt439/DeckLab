"""Source-set import choices over the real UI scripts and fixture-only API promises."""
import json
import subprocess
import unittest

from decklab.tests import test_collection_guards_ui as support
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = support.FIXTURE + r"""
  const groupedPreview = (token = 'reviewed-groups') => {
    const card = (name, set, number, quantity, language = '') => ({name, set, collector_number: number,
      finish: 'nonfoil', quantity: String(quantity), condition: '', language, notes: ''});
    const source = (line, group, row, code, name = '', problem = null, dropped_basic = false) =>
      ({line, group, row, source_set: {code, name}, problem, dropped_basic});
    const sources = [
      source(2, 'g1', card('Llanowar Elves', 'fdn', '227', 2, 'en'), 'fdn'),
      source(3, 'g2', card('Llanowar Elves', 'fdn', '227', 3, 'ja'), '', 'Foundations'),
      source(4, 'g1', card('Missing FDN card', 'fdn', '999', 1), 'fdn', '', 'Printing unknown'),
      source(5, 'g3', card('Unknown card', '', '', 1), '', '', 'No matching card'),
      source(6, 'g1', card('Forest', 'fdn', '280', 5), 'fdn', '', null, true),
      source(7, 'g4', card('Aerie Mystics', 'con', '1', 1), 'con')];
    const definitions = [['g1', 'fdn', '', 'FDN'], ['g2', '', 'Foundations', 'Foundations'],
      ['g3', '', '', 'Unknown set'], ['g4', 'con', '', 'CON']];
    const groups = definitions.map(([id, code, name, label]) => {
      const rows = sources.filter(row => row.group === id);
      const valid = rows.filter(row => row.problem === null && !row.dropped_basic);
      return {id, code, name, label, rows: rows.length, lines: rows.map(row => row.line),
        problem_rows: rows.filter(row => row.problem !== null).length, valid_rows: valid.length,
        valid_cards: valid.reduce((sum, row) => sum + Number(row.row.quantity), 0),
        dropped_basics: rows.filter(row => row.dropped_basic).reduce((sum, row) => sum + Number(row.row.quantity), 0)};
    });
    return {token, format: 'deckbox', source_rows: sources, groups, sha256: 's1',
      rows: [{...sources[0].row, quantity: '5', language: '', line: 2, problem: null},
        {...sources[2].row, line: 4, problem: sources[2].problem},
        {...sources[3].row, line: 5, problem: sources[3].problem},
        {...sources[5].row, line: 7, problem: null}],
      problems: sources.filter(row => row.problem).map(row => ({line: row.line, message: row.problem})),
      adds: {rows: 2, cards: 6}, dropped_basics: 5, repeat_imports: []};
  };
  const openGrouped = async (preview = groupedPreview()) => {
    const {cv, ctx: edit} = await make(); edit.sheet.close();
    const ctx = openImportSheet(cv); ctx.preview = preview; drawImportPreview(ctx);
    return {cv, ctx, preview};
  };
  const groupCheck = (ctx, id) => ctx.sheet.dialog.querySelector(`.col-import-group-check[data-import-group=${id}]`);
  const chooseGroup = (ctx, id, checked = true) => {
    const input = groupCheck(ctx, id); assert(input, `missing group ${id}`);
    input.checked = checked; input.fire('change'); return input;
  };
  const importAction = ctx => ctx.sheet.foot.querySelector('[data-action=import]');
  const readyGroups = ctx => { chooseGroup(ctx, 'g1'); chooseGroup(ctx, 'g3'); };
  const imported = () => ({ok: true, sha256: 's2', rows: [], added: {rows: 2, cards: 4}, skipped: 2,
    excluded_groups: groupedPreview().groups.filter(group => ['g1', 'g3'].includes(group.id))});
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionImportGroupsUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_plan_preserves_source_contributions_and_exact_printing_identities(self):
        self.run_js("""
          const p = groupedPreview(), before = JSON.stringify(p);
          const all = colImportGroupPlan(p);
          same(all.adds, {rows: 2, cards: 6}); assert.equal(all.problems.length, 2);
          assert.equal(all.dropped_basics, 5);
          const plan = colImportGroupPlan(p, new Set(['g1', 'g3']));
          same(plan.adds, {rows: 2, cards: 4}); same(plan.rows.map(row => row.line), [3, 7]);
          same(plan.excluded_rows.map(row => row.line), [2, 4, 5, 6]);
          assert.equal(plan.valid_excluded_cards, 2); assert.equal(plan.problems.length, 0);
          assert.equal(JSON.stringify(p), before, 'review must not rewrite source facts');
          p.source_rows[0].row.collector_number = 'A'; p.source_rows[1].row.collector_number = 'a';
          same(colImportGroupPlan(p).adds, {rows: 3, cards: 6});
        """)

    def test_incomplete_or_inconsistent_group_metadata_blocks_instead_of_legacy_fallback(self):
        self.run_js("""
          const changes = [p => delete p.source_rows, p => { p.groups = null; },
            p => p.groups.push({...p.groups[0]}), p => { p.source_rows[0].group = 'g99'; },
            p => { p.source_rows[0].row.quantity = 'not a quantity'; },
            p => { p.source_rows[1].line = p.source_rows[0].line; },
            p => { p.groups[0].valid_cards = 99; }, p => { p.source_rows[0].problem = 42; }];
          for (const change of changes) {
            const p = groupedPreview(); change(p); assert(colImportHasGroups(p));
            assert.equal(colImportGroupPlan(p), null);
            const {ctx} = await openGrouped(p); assert.equal(colImportGroupRequest(ctx).blocked, true);
            let writes = 0; apiWrite = async () => { writes++; return imported(); };
            await applyImport(ctx, true); assert.equal(writes, 0); ctx.sheet.close();
          }
        """)

    def test_native_group_choices_start_unchecked_and_only_resolved_selection_can_import(self):
        self.run_js("""
          const {ctx} = await openGrouped();
          const controls = ctx.sheet.dialog.querySelectorAll('.col-import-group-check');
          assert.equal(controls.length, 4);
          assert(controls.every(node => node.tag === 'input' && node.getAttribute('type') === 'checkbox' && !node.checked));
          assert(ctx.area.textContent.includes('FDN')); assert(ctx.area.textContent.includes('Foundations'));
          assert(ctx.area.textContent.includes('Unknown set')); assert(ctx.area.textContent.includes('Printing unknown'));
          assert(ctx.area.textContent.includes('FDN: 1 problem row'));
          assert(ctx.area.textContent.includes('Foundations: 0 problem rows'));
          assert.equal(colImportGroupRequest(ctx).blocked, true);
          chooseGroup(ctx, 'g1'); assert.equal(colImportGroupRequest(ctx).blocked, true);
          chooseGroup(ctx, 'g3'); same(colImportGroupRequest(ctx).ids, ['g1', 'g3']);
          assert(importAction(ctx) && !importAction(ctx).disabled);
          assert(importAction(ctx).textContent.includes('4 cards'));
          chooseGroup(ctx, 'g2'); chooseGroup(ctx, 'g4');
          assert.equal(colImportGroupRequest(ctx).blocked, true);
          assert(!importAction(ctx) || importAction(ctx).disabled);
        """)

    def test_exclusion_review_lists_valid_problem_and_basic_rows_without_losing_control_focus(self):
        self.run_js("""
          const {ctx} = await openGrouped(); const controls = [...ctx.sheet.dialog.querySelectorAll('.col-import-group-check')];
          const first = groupCheck(ctx, 'g1'); first.focus(); chooseGroup(ctx, 'g1');
          assert.equal(document.activeElement, first);
          same(ctx.sheet.dialog.querySelectorAll('.col-import-group-check').map(node => node.getAttribute('data-import-group')),
            controls.map(node => node.getAttribute('data-import-group')));
          controls.forEach((node, index) => assert.equal(ctx.sheet.dialog.querySelectorAll('.col-import-group-check')[index], node));
          const outcome = ctx.groupReview.outcome.textContent;
          for (const name of ['Llanowar Elves', 'Missing FDN card', 'Forest']) assert(outcome.includes(name), name);
          for (const line of ['2', '4', '6']) assert(outcome.includes(line));
          assert(outcome.includes('2 valid cards'));
          assert(/before.*combin/i.test(ctx.area.textContent));
        """)

    def test_busy_import_freezes_native_choices_and_sends_the_reviewed_group_snapshot(self):
        self.run_js("""
          const {ctx, cv} = await openGrouped(); readyGroups(ctx); cv.rows = null; cv.sha256 = null;
          let receiveRows; api = () => new Promise(resolve => receiveRows = resolve);
          const calls = []; route = () => {}; apiWrite = async (path, body) => { calls.push({path, body}); return imported(); };
          const pending = applyImport(ctx, true); await flush();
          assert(ctx.input.disabled); assert(ctx.sheet.dialog.querySelectorAll('.col-import-group-check').every(node => node.disabled));
          chooseGroup(ctx, 'g1', false); chooseGroup(ctx, 'g2', true);
          assert(groupCheck(ctx, 'g1').checked); assert(!groupCheck(ctx, 'g2').checked);
          receiveRows({sha256: 'latest', rows: [original]}); await pending;
          assert.equal(calls.length, 1); same(calls[0].body.skip_groups, ['g1', 'g3']);
          assert.equal(calls[0].body.skip_problems, undefined); assert.equal(calls[0].body.token, 'reviewed-groups');
          assert.equal(calls[0].body.sha256, 'latest');
        """)

    def test_new_file_or_preview_clears_choices_and_stale_controls_cannot_change_new_review(self):
        self.run_js("""
          const {ctx} = await openGrouped(); readyGroups(ctx); const old = groupCheck(ctx, 'g1');
          apiWrite = async () => groupedPreview('replacement-token');
          await previewImport(ctx, 'replacement.csv', 'replacement content');
          assert.equal(ctx.preview.token, 'replacement-token'); assert.equal(ctx.groupReview.ids.size, 0);
          assert(ctx.sheet.dialog.querySelectorAll('.col-import-group-check').every(node => !node.checked));
          old.checked = true; old.fire('change'); assert.equal(ctx.groupReview.ids.size, 0);
          ctx.input.files = [{name: 'too-big.csv', size: COL_IMPORT_MAX + 1}]; ctx.input.fire('change'); await flush();
          assert.equal(ctx.preview, null); old.fire('change'); assert(!importAction(ctx));
        """)

    def test_permission_loss_rolls_back_synthetic_choice_changes_and_blocks_apply(self):
        self.run_js("""
          for (const change of ['editable', 'space-right']) {
            const {ctx, cv} = await openGrouped(); readyGroups(ctx);
            if (change === 'editable') cv.editable = false;
            else state.may = {...state.may, spaces: []};
            chooseGroup(ctx, 'g1', false); chooseGroup(ctx, 'g2', true);
            assert(groupCheck(ctx, 'g1').checked); assert(!groupCheck(ctx, 'g2').checked);
            same([...ctx.groupReview.ids], ['g1', 'g3']);
            assert.equal(colImportGroupRequest(ctx).blocked, true);
            let writes = 0; apiWrite = async () => { writes++; return imported(); };
            await applyImport(ctx, false); assert.equal(writes, 0); ctx.sheet.close();
          }
        """)

    def test_late_rows_after_context_or_permission_change_do_not_apply(self):
        self.run_js("""
          for (const change of ['profile', 'route', 'preview', 'closed', 'editable', 'space-right']) {
            const {ctx, cv} = await openGrouped(); readyGroups(ctx); cv.rows = null; cv.sha256 = null;
            let release; api = () => new Promise(resolve => release = resolve); let writes = 0;
            apiWrite = async () => { writes++; return imported(); };
            const pending = applyImport(ctx, false); await flush(); const originalPreview = ctx.preview;
            if (change === 'profile') state.profile = PROFILES[2];
            if (change === 'route') { colCloseSheets(); location.hash = '#/wishlist'; }
            if (change === 'preview') { ctx.preview = groupedPreview('different-token'); ctx.seq++; }
            if (change === 'closed') ctx.sheet.close();
            if (change === 'editable') cv.editable = false;
            if (change === 'space-right') state.may = {...state.may, spaces: []};
            release({sha256: 's3', rows: [original]}); await pending;
            assert.equal(writes, 0, change);
            if (!ctx.sheet.closed) ctx.sheet.close();
            assert.equal(originalPreview.token, 'reviewed-groups');
          }
        """)

    def test_repeat_repreview_resets_choices_and_requires_another_explicit_review(self):
        self.run_js("""
          const {ctx} = await openGrouped(); ctx.source = {filename: 'same.csv', text: 'unchanged source'};
          readyGroups(ctx); let applies = 0;
          apiWrite = async (path, body) => {
            if (path.endsWith('/preview')) { assert.equal(body.text, 'unchanged source'); return groupedPreview('fresh-token'); }
            applies++; if (applies === 1) throw new ApiError(409, 'Repeat imports changed', {repreview_required: true});
            assert.equal(body.token, 'fresh-token'); return imported();
          };
          route = () => {}; await applyImport(ctx, false); assert.equal(ctx.preview, null);
          button(ctx.sheet.dialog, 'Preview again').click(); await flush();
          assert.equal(ctx.groupReview.ids.size, 0); assert.equal(colImportGroupRequest(ctx).blocked, true);
          readyGroups(ctx); await applyImport(ctx, false); assert.equal(applies, 2);
        """)

    def test_collection_sha_retry_keeps_reviewed_group_selection(self):
        self.run_js("""
          const {ctx} = await openGrouped(); readyGroups(ctx); const calls = []; route = () => {};
          apiWrite = async (path, body) => {
            calls.push(body); if (calls.length === 1) throw new ApiError(409, 'Collection changed', {sha256: 's9', rows: [original]});
            return imported();
          };
          await applyImport(ctx, false); assert(!ctx.sheet.closed); same([...ctx.groupReview.ids], ['g1', 'g3']);
          button(ctx.sheet.dialog, 'Import into the latest list').click(); await flush();
          assert.equal(calls.length, 2); same(calls[0].skip_groups, ['g1', 'g3']); same(calls[1].skip_groups, ['g1', 'g3']);
          assert.equal(calls[1].sha256, 's9'); assert.equal(calls[1].skip_problems, undefined);
        """)

    def test_legacy_flat_preview_keeps_existing_explicit_skip_problems_request(self):
        self.run_js("""
          const p = groupedPreview(); delete p.groups; delete p.source_rows;
          assert.equal(colImportHasGroups(p), false); const {ctx} = await openGrouped(p);
          assert.equal(colImportGroupRequest(ctx), null); assert.equal(ctx.sheet.dialog.querySelectorAll('.col-import-group-check').length, 0);
          const calls = []; route = () => {}; apiWrite = async (path, body) => { calls.push(body); return imported(); };
          await applyImport(ctx, true); assert.equal(calls.length, 1); assert.equal(calls[0].skip_problems, true);
          assert.equal(calls[0].skip_groups, undefined);
        """)

    def test_large_preview_renders_five_thousand_source_rows_before_any_apply(self):
        self.run_js("""
          const base = groupedPreview();
          const sources = Array.from({length: 5000}, (_, index) => {
            const source = structuredClone(base.source_rows[index % 2 ? 3 : 0]);
            source.line = index + 2; source.row.quantity = '1'; return source;
          });
          const groups = [base.groups[0], base.groups[2]].map(group => {
            const rows = sources.filter(source => source.group === group.id);
            const problem = group.id === 'g3';
            return {...group, rows: 2500, problem_rows: problem ? 2500 : 0, valid_rows: problem ? 0 : 2500,
              valid_cards: problem ? 0 : 2500, dropped_basics: 0, lines: rows.map(row => row.line)};
          });
          const p = {...base, source_rows: sources, groups,
            problems: sources.filter(source => source.problem).map(source => ({line: source.line, message: source.problem})),
            adds: {rows: 1, cards: 2500}, dropped_basics: 0};
          const plan = colImportGroupPlan(p); same(plan.adds, {rows: 1, cards: 2500}); assert.equal(plan.rows.length, 5000);
          assert(plan.groups.every(group => group.sources.length === 2500)); assert.equal(plan.excluded_rows.length, 0);
          let writes = 0; apiWrite = async () => { writes++; return imported(); };
          const {ctx} = await openGrouped(p);
          assert.equal(ctx.sheet.dialog.querySelectorAll('.col-import-group-check').length, 2);
          const headings = ctx.area.querySelectorAll('h3').map(node => node.textContent);
          assert(headings.includes('FDN: 0 problem rows'));
          assert(headings.some(text => text.startsWith('Unknown set: ') && text.includes('problem rows')));
          const labels = ctx.area.querySelectorAll('label').map(node => node.textContent.replaceAll(',', ''));
          assert.equal(labels.filter(text => text.includes('2500 source rows')).length, 2);
          assert.equal(ctx.groupReview.outcome.querySelectorAll('tbody')[0].children.length, 5000);
          assert.equal(colImportGroupRequest(ctx).blocked, true); assert.equal(writes, 0);
        """)
