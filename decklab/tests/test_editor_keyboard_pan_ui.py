"""The editor's Save bar stays above an on-screen keyboard when Safari pans the visual viewport.

An iPad Air 11-inch in landscape (the Safari suite, 2026-11-05) panned by 219.5 with 341 visible, and its
window.innerHeight didn't match the sticky scrollport (688), so innerHeight's estimate of the lift left Save
under the keyboard. The bar here is stuck to that scrollport: its rect follows the lift the page sets, and
its rects are measured from the visual viewport's top as iOS gives them (or the layout viewport's, as
other browsers do). Runs the real page scripts in the DOM double; nothing is saved.
"""
import unittest

from decklab.tests import test_editor_ui as editor_ui
from decklab.tests.test_workspace_ui import NODE

# A stuck bar 44 tall ending at the scrollport's bottom less the lift; `visualRects` as iOS measures them.
BAR = """
  edit();
  const style = document.documentElement.style, vv = window.visualViewport;
  const lift = () => parseFloat(style['--editor-keyboard-bottom']) || 0;
  let scrollport = 688, scrollY = 400, visualRects = true;
  const bar = el('div', {class: 'edit-bar'}); document.body.append(bar); editor.dom.bar = bar;
  window.getComputedStyle = node => ({bottom: node === bar ? `${lift()}px` : 'auto'});
  bar.getBoundingClientRect = () => {
    const bottom = scrollport - lift() - (visualRects ? vv.offsetTop : 0);
    return {top: bottom - 44, bottom, left: 0, right: 1180, width: 1180, height: 44};
  };
  document.documentElement.getBoundingClientRect = () => {
    const top = visualRects ? -(scrollY + vv.offsetTop) : -scrollY;
    return {top, bottom: top + 3000, left: 0, right: 1180, width: 1180, height: 3000};
  };
  const pan = (height, offsetTop) => {
    Object.assign(vv, {height, offsetTop, pageTop: scrollY + offsetTop}); vv.fire('resize'); vv.fire('scroll');
  };
  // Where the bar ends inside the visual viewport, whichever way the rects are measured.
  const barBottom = () => bar.getBoundingClientRect().bottom - (visualRects ? 0 : vv.offsetTop);
"""

IPAD = {"innerWidth": 1180, "innerHeight": 688, "coarse": True, "visual": {"width": 1180, "height": 688}}


@unittest.skipUnless(NODE, "Node.js isn't installed")
class EditorKeyboardPanTests(unittest.TestCase):
    run_js = editor_ui.EditorPageTests.run_js

    def test_ipad_landscape_pan_keeps_save_within_the_visual_viewport_whatever_inner_height_says(self):
        for inner in (560.5, 688):
            with self.subTest(innerHeight=inner):
                self.run_js(BAR + f"""
                  window.innerHeight = {inner};
                  pan(341, 0);
                  assert.equal(lift(), 347);
                  assert.equal(barBottom(), 341);
                  pan(341, 219.5);
                  assert.equal(lift(), 127.5);
                  assert(barBottom() <= 341 && barBottom() >= 341 - 0.5, String(barBottom()));
                  // Another scroll event with nothing moved gives the same lift: no feedback loop.
                  vv.fire('scroll'); vv.fire('scroll');
                  assert.equal(lift(), 127.5);
                  // The keyboard going away drops the lift.
                  pan(688, 0);
                  assert.equal(lift(), 0);
                """, viewport=IPAD)

    def test_unpanned_keyboard_lift_is_unchanged(self):
        self.run_js(BAR + """
          pan(341, 0);
          assert.equal(lift(), 688 - 341);
          assert.equal(barBottom(), 341);
        """, viewport=IPAD)

    def test_an_over_estimate_comes_down_to_the_visual_bottom(self):
        # innerHeight larger than the scrollport (the initial containing block with the toolbar folded).
        self.run_js(BAR + """
          window.innerHeight = 763;
          pan(341, 219.5);
          assert.equal(lift(), 127.5);
          assert.equal(barBottom(), 341);
        """, viewport=IPAD)

    def test_layout_viewport_rects_are_measured_from_the_pan(self):
        # Chrome measures rects from the layout viewport: the visible bottom is offsetTop + height there.
        self.run_js(BAR + """
          visualRects = false; window.innerHeight = 560.5;
          pan(341, 219.5);
          assert.equal(lift(), 127.5);
          assert.equal(barBottom(), 341);
        """, viewport=IPAD)

    def test_a_hidden_or_absent_bar_keeps_the_inner_height_estimate(self):
        self.run_js(BAR + """
          window.innerHeight = 600;
          bar.getBoundingClientRect = () => ({top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0});
          pan(341, 219.5);
          assert.equal(lift(), 600 - 341 - 219.5);
          bar.remove();
          pan(341, 100);
          assert.equal(lift(), 600 - 341 - 100);
        """, viewport=IPAD)
