'use strict';
// Exercise local editor drafts and dry checks through ordinary browser controls.
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { run } = require('./common.js');

async function state(page) {
  return page.evaluate(() => {
    const box = node => node ? { text: node.textContent.trim(), disabled: !!node.disabled,
      connected: node.isConnected, hidden: !!node.hidden, rect: (() => {
        const rect = node.getBoundingClientRect();
        return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
      })() } : null;
    const model = typeof editor === 'undefined' ? null : editor;
    return {
      href: location.href, theme: document.documentElement.dataset.theme,
      viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio,
        coarse: matchMedia('(pointer: coarse)').matches },
      quick: document.body.classList.contains('is-quick-edit'),
      dialogs: [...document.querySelectorAll('dialog[open]')].map(dialog => ({
        heading: dialog.querySelector('h2')?.textContent.trim() || '', text: dialog.textContent.trim(),
      })),
      bar_count: document.querySelector('.bar-count')?.textContent.trim() || '',
      undo: box(document.querySelector('.bar-undo')),
      discard: box(document.querySelector('.bar-discard')),
      save: box(document.querySelector('.bar-save')),
      row_undo: [...document.querySelectorAll('.undo-btn')].map(node => ({ label: node.getAttribute('aria-label'), ...box(node) })),
      quantities: [...document.querySelectorAll('.qty-input[aria-label]')]
        .map(node => ({ label: node.getAttribute('aria-label'), value: node.value })),
      headings: [...document.querySelectorAll('#main h2')].map(node => node.textContent.trim()),
      focused: document.activeElement ? { tag: document.activeElement.tagName,
        label: document.activeElement.getAttribute('aria-label'), text: document.activeElement.textContent?.trim().slice(0, 120) } : null,
      model_read_only: model ? { saving: model.saving, asking: model.asking, leaving: model.leaving,
        dirty: model.dirty, history_length: model.history?.length, saved_sha: model.sha256 } : null,
    };
  });
}

async function checksSettled(page) {
  await page.waitForFunction(() => typeof editor !== 'undefined' && editor && !editor.checking && !editor.saving,
    null, { timeout: 15000 });
}

function savedFields(value) {
  return { sha256: value.sha256, lists: value.lists, may_save: value.may_save };
}

function digest(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

run('editor', async review => {
  const report = review.report;
  report.viewport = { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
  report.scope = [
    'Empty-list Save review is blocked; Keep editing returns to the existing local draft.',
    'Footer disabled-state reproduction is an observation, never a requirement that the known bug remain.',
    'Visible row Undo restores the local list; saved deck and kept server draft must remain unchanged.',
    'Seeded server draft is resumed into this isolated browser; no draft publication or final Save is permitted.',
    'Page model inspection is read-only; interactions use browser clicks without DOM value setters.',
  ];
  report.page_errors = [];
  report.http_errors = [];
  report.cases = {};
  report.screenshots = [];
  review.select();
  const context = await review.context({ width: 390, height: 844, coarse: true, theme: 'light' });
  const page = await context.newPage();
  review.observe(page, report.page_errors, report.http_errors);
  page.on('dialog', async dialog => {
    report.browser_dialogs ||= [];
    report.browser_dialogs.push({ type: dialog.type(), message: review.safeText(dialog.message()) });
    await dialog.dismiss();
  });
  const editorRoute = review.config.ready.routes.editor;
  const query = new URLSearchParams(editorRoute.split('?')[1] || '');
  const deckId = query.get('id');
  assert(deckId && deckId.startsWith('casual/'), 'Missing synthetic saved editor deck');
  const editPath = '/api/deck/edit?id=' + encodeURIComponent(deckId);
  const draftPath = '/api/deck/draft?id=' + encodeURIComponent(deckId) + '&version=target';
  const screenshot = async name => {
    review.checkCancelled();
    await page.screenshot({ path: path.join(review.out, name), fullPage: false, animations: 'disabled', timeout: 30000 });
    report.screenshots.push(name);
  };
  try {
    const savedBefore = savedFields(await review.readFixture(context, editPath));
    assert.equal(savedBefore.may_save, true, 'Synthetic saved deck must be editable');
    report.saved_before = { sha256: savedBefore.sha256, lists_digest: digest(savedBefore.lists), may_save: savedBefore.may_save };
    await page.goto(review.pageUrl(editorRoute), { waitUntil: 'networkidle', timeout: 30000 });
    await page.locator('.edit-page').waitFor({ timeout: 15000 });
    await page.evaluate(() => document.fonts.ready);
    report.actual_viewport = await page.evaluate(() => ({ width: innerWidth, height: innerHeight, dpr: devicePixelRatio }));
    assert.deepEqual(report.actual_viewport, { width: 390, height: 844, dpr: 2 }, 'Unexpected editor viewport');
    await page.getByRole('button', { name: 'More for Forest', exact: true }).waitFor({ timeout: 15000 });
    await checksSettled(page);
    report.cases.empty_blocker = { before: await state(page), actions: [] };
    for (const name of ['Llanowar Elves', 'Elvish Mystic', 'Forest']) {
      review.checkCancelled();
      await page.getByRole('button', { name: `More for ${name}`, exact: true }).click();
      await page.getByRole('menuitem', { name: 'Remove', exact: true }).click();
      report.cases.empty_blocker.actions.push(`More for ${name} -> Remove`);
    }
    await checksSettled(page);
    report.cases.empty_blocker.removed = await state(page);
    assert.match(report.cases.empty_blocker.removed.bar_count, /0/);
    assert.equal(report.cases.empty_blocker.removed.row_undo.length, 3, 'Each removed fixture row needs local Undo');
    await page.locator('.bar-save').click();
    const modal = page.getByRole('dialog').filter({ has: page.getByText('The planned list is empty:', { exact: false }) });
    await modal.waitFor({ state: 'visible', timeout: 15000 });
    // The modal belongs to the active pre-save operation; saving becomes false only after Keep editing.
    await page.waitForFunction(() => typeof editor !== 'undefined' && editor && !editor.checking, null, { timeout: 15000 });
    report.cases.empty_blocker.review = await state(page);
    assert.equal(await modal.getByRole('button', { name: 'Save', exact: true }).isDisabled(), true,
      'Final Save must be blocked for an empty planned list');
    await screenshot('01-empty-list-review-390-light.png');
    await modal.getByRole('button', { name: 'Keep editing', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('dialog[open]'), null, { timeout: 15000 });
    await checksSettled(page);
    const after = await state(page);
    report.cases.empty_blocker.after_keep_editing = after;
    await screenshot('02-after-keep-editing-footer-390-light.png');
    report.cases.empty_blocker.footer_stale_disabled_reproduced = after.undo?.disabled === true
      && after.discard?.disabled === true && after.model_read_only?.saving === false
      && after.model_read_only?.history_length > 0;
    let restoredRows = 0;
    while (await page.locator('.undo-btn').count()) {
      assert(restoredRows++ < 3, 'Unexpected repeated row Undo controls');
      await page.locator('.undo-btn').first().click();
    }
    await checksSettled(page);
    report.cases.empty_blocker.after_row_undo = await state(page);
    const savedAfter = savedFields(await review.readFixture(context, editPath));
    assert.deepEqual(savedAfter, savedBefore, 'Saved deck changed during dry-run review');
    report.saved_after = { sha256: savedAfter.sha256, lists_digest: digest(savedAfter.lists), may_save: savedAfter.may_save };
    const keptBefore = await review.readFixture(context, draftPath);
    assert(keptBefore.draft, 'Disposable fixture must provide a seeded kept draft');
    report.kept_before = { present: true, digest: digest(keptBefore) };
    const resume = page.getByRole('button', { name: 'Resume it', exact: true });
    assert.equal(await resume.count(), 1, 'Seeded kept draft Resume it control is missing');
    await resume.click();
    await page.waitForFunction(() => [...document.querySelectorAll('h2')].some(node =>
      ['Use the draft kept for later?', 'You picked up the draft kept for later'].includes(node.textContent.trim())),
    null, { timeout: 10000 });
    let confirmation = null;
    const useKept = page.getByRole('button', { name: 'Use the kept draft', exact: true });
    if (await useKept.isVisible()) {
      confirmation = await state(page);
      await useKept.click(); // Explicit local replacement, never a server write.
    }
    await page.getByRole('heading', { name: 'You picked up the draft kept for later', exact: true }).waitFor();
    await checksSettled(page);
    report.cases.kept_resume = { status: 'observed_same_browser_resume_only', confirmation, after: await state(page) };
    await screenshot('03-kept-draft-resumed-390-light.png');
    const keptAfter = await review.readFixture(context, draftPath);
    assert.deepEqual(keptAfter, keptBefore, 'Server kept draft changed while resuming');
    report.kept_after = { present: true, digest: digest(keptAfter) };
    assert.deepEqual(savedFields(await review.readFixture(context, editPath)), savedBefore, 'Saved deck changed after resume');
    report.saved_deck_unchanged = true;
    report.server_kept_draft_unchanged = true;
    assert.equal(report.screenshots.length, 3, 'Editor review screenshots are incomplete');
    assert.equal(report.page_errors.length, 0, 'Uncaught page error during editor review');
    assert(!report.http_errors.some(row => row.category === 'unexpected_http_error'), 'Unexpected editor fixture HTTP failure');
  } catch (error) {
    if (!page.isClosed()) {
      try { report.failure_state = await state(page); await screenshot('failure.png'); } catch (_) {}
    }
    throw error;
  }
});
