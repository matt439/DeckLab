'use strict';
// Bounded read-only browser qualification of repaired UI paths over invented records.
const assert = require('node:assert/strict');

async function guidePosition(page) {
  await page.waitForFunction(() => {
    const guide = document.querySelector('#sec-guide');
    return guide && document.activeElement === guide && !guide.closest('[hidden]');
  }, null, { timeout: 10000 });
  return page.evaluate(() => {
    const guide = document.querySelector('#sec-guide');
    const heading = guide.querySelector('h2').getBoundingClientRect();
    const strip = document.querySelector('.deck-tabs').getBoundingClientRect();
    const params = new URLSearchParams(location.hash.split('?')[1]);
    return { hash: location.hash, part: params.get('part'), tab: params.get('tab'),
      guideFocused: document.activeElement === guide, guideTop: guide.getBoundingClientRect().top,
      headingTop: heading.top, headingBottom: heading.bottom, stripBottom: strip.bottom,
      overviewVisible: !document.querySelector('#deck-panel-overview').hidden,
      topics: guide.querySelectorAll('.guide-topic').length,
      stale: Boolean(guide.querySelector('.guide-stale')), scrollY,
      scrollMarginTop: getComputedStyle(guide).scrollMarginTop };
  });
}

function assertGuidePosition(observation) {
  assert.equal(observation.part, 'guide', 'Guide destination was lost from the address');
  assert.equal(observation.tab, null, 'Guide destination must use Overview');
  assert(observation.overviewVisible && observation.guideFocused, 'Existing guide did not receive focus');
  assert(observation.topics > 0, 'Seeded guide did not render its topics');
  assert(observation.headingTop >= observation.stripBottom - 1, 'Guide heading is hidden by the sticky tabs');
}

/** Desktop cases start on the selected library detail and follow its real link. Narrow cases can start on
 * that copied guide address (the library has no detail pane on phones). No mutations or injected layout. */
async function checkGuideDestination(review, page, { fromLibrary = true } = {}) {
  review.checkCancelled();
  let href = null;
  if (fromLibrary) {
    const link = page.getByRole('link', { name: 'How to play', exact: true });
    await link.waitFor({ state: 'visible', timeout: 10000 });
    href = await link.getAttribute('href');
    assert(href && href.includes('&part=guide'), 'Library guide link lacks its destination');
    await link.click();
  }
  const initial = await guidePosition(page);
  assertGuidePosition(initial);
  let back = null, forward = null;
  if (fromLibrary) {
    await page.goBack();
    await page.waitForSelector('.lib-detail', { timeout: 10000 });
    back = await page.evaluate(() => ({ hash: location.hash,
      selected: document.querySelector('.lib-detail')?.dataset.id,
      guidePresent: Boolean(document.querySelector('#sec-guide')) }));
    assert(back.hash.startsWith('#/library') && !back.guidePresent, 'Back did not return to the library');
    await page.goForward();
    forward = await guidePosition(page);
    assertGuidePosition(forward);
    assert.equal(forward.hash, initial.hash, 'Forward did not retain the guide destination');
  }
  return { href, initial, back, forward,
    scope: fromLibrary ? 'Library click, guide focus/clearance and Back/Forward'
      : 'Copied guide destination, focus and sticky clearance at the current viewport' };
}

module.exports = { checkGuideDestination };
