"""Run the actual Safari measurement JavaScript over frozen native-run geometry.

These fixtures protect coordinate arithmetic, not Simulator acceptance. The Save
rectangle and viewport pan reproduce the keyboard-open trace from 2026-10-15.
"""
import json
import shutil
import subprocess
import unittest

from decklab.safari import interaction

NODE = shutil.which("node")
HARNESS = r"""
const fs = require('node:fs');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
function node(value) {
  const rect = value.rect;
  const element = {
    disabled: false,
    clientLeft: 0, clientTop: 0,
    clientWidth: rect.width, clientHeight: rect.height,
    scrollWidth: rect.width, scrollTop: 0,
    getBoundingClientRect: () => rect,
    style: {display:'block', visibility:'visible', opacity:'1',
            overflowX:'visible', overflowY:'visible', ...(value.style || {})},
    parentElement: value.parent ? node(value.parent) : null
  };
  return element;
}
const element = node(fixture.element);
global.document = {querySelector: () => element};
global.getComputedStyle = (element) => element.style;
global.visualViewport = fixture.viewport;
global.innerWidth = 393;
global.innerHeight = 695;
const result = new Function(fixture.script).apply(null, ['.bar-save']);
process.stdout.write(JSON.stringify(result));
"""


def rect(left, top, width, height):
    return {"left": left, "top": top, "right": left + width, "bottom": top + height,
            "width": width, "height": height}


class FrozenDom:
    def __init__(self, element, viewport):
        self.element, self.viewport = element, viewport

    def execute(self, script, arguments):
        result = subprocess.run([NODE, "-e", HARNESS], input=json.dumps({
            "script": script, "element": self.element, "viewport": self.viewport}),
            text=True, capture_output=True, timeout=10)
        if result.returncode:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)


@unittest.skipUnless(NODE, "Node.js is needed to execute the actual bounds JavaScript")
class SafariBoundsTests(unittest.TestCase):
    def measure(self, geometry, *, pan=0, height=391, parent=None):
        element = {"rect": geometry}
        if parent:
            element["parent"] = parent
        driver = FrozenDom(element, {"width": 393, "height": height,
                                     "offsetLeft": 0, "offsetTop": pan})
        return interaction.bounds(driver, ".bar-save")

    def test_keyboard_open_save_below_visual_viewport_is_not_visible(self):
        measured = self.measure(rect(289, 417.65625, 88, 44), pan=225.34375)
        self.assertEqual(measured["rect"]["bottom"], 461.65625)
        self.assertEqual(measured["viewport"]["bottom"], 391)
        self.assertEqual(measured["pan"], {"left": 0, "top": 225.34375})
        with self.assertRaisesRegex(AssertionError, "clipped or outside"):
            interaction.fully_visible(measured, "Keyboard-open Save")

    def test_visual_origin_control_stays_visible_despite_layout_pan(self):
        measured = self.measure(rect(20, 20, 88, 44), pan=225.34375)
        interaction.fully_visible(measured, "Visible control near the visual top")
        self.assertEqual(measured["visible"]["top"], 20)

    def test_unpanned_control_and_ancestor_clipping(self):
        geometry = rect(289, 643, 88, 44)
        interaction.fully_visible(self.measure(geometry, height=695), "Normal Save")
        clipped = self.measure(geometry, height=695, parent={
            "rect": rect(0, 0, 393, 660), "style": {"overflowY": "auto"}})
        self.assertEqual(clipped["visible"]["bottom"], 660)
        with self.assertRaisesRegex(AssertionError, "clipped or outside"):
            interaction.fully_visible(clipped, "Ancestor-clipped Save")


if __name__ == "__main__":
    unittest.main()
