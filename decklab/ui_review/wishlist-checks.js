'use strict';
// Local Wishlist work only. Final Save stays denied by both fixture and browser boundaries.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

function savedDigest(answer) {
  const entries = answer.entries.map(({ name, notes, source, set, number }) => ({ name, notes, source, set, number }));
  return crypto.createHash('sha256').update(JSON.stringify(entries)).digest('hex');
}

async function checkWishlist(review, page, { unknown = false, zoom = false } = {}) {
  const api = '/api/profiles/matt/wishlist';
  const before = await review.readFixture(page.context(), api);
  const report = { saved_before: savedDigest(before), unknown, zoom };
  const tile = name => page.locator('.wishlist-grid .card-tile').filter({ has: page.getByRole('button', {
    name: new RegExp('^' + name + ',') }) });
  const expected = unknown ? 'Collection counts unavailable' : '3 owned · 1 on the way';
  assert.match(await tile('Llanowar Elves').innerText(), new RegExp(expected));
  assert.match(await tile('Forest').innerText(), new RegExp(unknown ? expected : 'None in your collection yet'));
  await tile('Llanowar Elves').getByRole('button').click();
  const sheet = page.locator('dialog.sheet').filter({ has: page.locator('.wishlist-sheet') });
  await sheet.waitFor({ state: 'visible' });
  assert((await sheet.innerText()).includes(expected));
  if (unknown) assert(!(await sheet.innerText()).includes('None in your collection yet'));
  if (zoom) {
    await sheet.locator('textarea').fill('Unsaved synthetic note retained after Zoom.');
    await sheet.locator('input[id^="wish-source-"]').fill('magic/decks/casual/safari-fixture.md');
    await sheet.getByRole('button', { name: 'Choose…', exact: true }).click();
    const picker = page.getByRole('dialog', { name: "Llanowar Elves: the printing you'd like", exact: true });
    await picker.locator('.card-tile-open').first().click();
    await picker.waitFor({ state: 'detached' });
    await sheet.locator('.wishlist-printing-words').filter({ hasText: 'SFT 1' }).waitFor();
    await page.waitForFunction(() => sheetEntries.length === 1 && history.state?.sheet === sheetEntries[0].token);
    assert((await sheet.locator('.wishlist-printing-words').innerText()).includes('SFT 1'));
    report.viewer_returns = [];
    for (const method of ['Close', 'Escape', 'Back']) {
      await sheet.getByRole('button', { name: 'Zoom: Llanowar Elves', exact: true }).click();
      const viewer = page.locator('dialog.viewer[open]');
      await viewer.waitFor({ state: 'visible' });
      // The sheet stays open under the viewer; the viewer still uses the whole Wishlist group.
      assert.equal(await sheet.getAttribute('open'), '');
      await viewer.getByRole('button', { name: 'Next card', exact: true }).click();
      await page.waitForFunction(() => document.querySelector('#viewer-title')?.textContent === 'Forest');
      await viewer.getByRole('button', { name: 'Previous card', exact: true }).click();
      if (method === 'Close') await viewer.getByRole('button', { name: 'Close', exact: true }).click();
      else if (method === 'Escape') await page.keyboard.press('Escape');
      else await page.goBack();
      await viewer.waitFor({ state: 'hidden' });
      await page.waitForFunction(() => !history.state?.cardViewer);
      assert.equal(await sheet.locator('textarea').inputValue(), 'Unsaved synthetic note retained after Zoom.');
      assert.equal(await sheet.locator('input[id^="wish-source-"]').inputValue(), 'magic/decks/casual/safari-fixture.md');
      assert((await sheet.locator('.wishlist-printing-words').innerText()).includes('SFT 1'));
      assert.equal(await sheet.getByRole('button', { name: 'Zoom: Llanowar Elves', exact: true })
        .evaluate(node => document.activeElement === node), true, 'Viewer did not restore focus to Zoom');
      report.viewer_returns.push(method);
    }
  }
  report.saved_after = savedDigest(await review.readFixture(page.context(), api));
  assert.equal(report.saved_after, report.saved_before, 'Local inspection changed the saved Wishlist');
  report.availability = expected;
  return report;
}

async function checkWishlistCancel(page) {
  const sheet = page.locator('dialog.sheet').filter({ has: page.locator('.wishlist-sheet') });
  await sheet.getByRole('button', { name: 'Close', exact: true }).click();
  await sheet.waitFor({ state: 'detached' });
  await page.waitForFunction(() => !history.state?.sheet);
  await page.locator('.wishlist-grid .card-tile-open').first().click();
  const reopened = page.locator('dialog.sheet').filter({ has: page.locator('.wishlist-sheet') });
  assert.equal(await reopened.locator('textarea').inputValue(), 'Synthetic saved note: keep me after Zoom.');
  assert((await reopened.locator('.wishlist-printing-words').innerText()).includes('Any printing'));
  return { closed_draft_without_saving: true, reopened_saved_values: true };
}

module.exports = { checkWishlist, checkWishlistCancel };
