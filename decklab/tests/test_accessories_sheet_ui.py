"""The accessories add/edit sheet's first focus (accessories.js accSheetFocus): Add starts on the link field,
Edit on Name with a mouse, and on a touch screen the heading, so no keyboard pops up over the picture.

Loads every page script into the event/DOM double (fixtures/workspace_ui_runner.js): no browser, server or save.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SCENARIO = r"""
  const row = { id: "ds-black", kind: "sleeves", owner: "shared", name: "Matte", brand: "Dragon Shield", colour: "black",
    quantity: 100, capacity: "", image: "", crop: "", link: "", image_source: "", notes: "", label: "Dragon Shield Matte",
    used_by: [] };
  function opened(coarse, args) {
    window.matchMedia("(pointer: coarse)").matches = coarse;
    const sheet = openAccessorySheet({ sha256: "s1", owners: [{ id: "shared", name: "Shared" }], ...args });
    const active = document.activeElement;
    sheet.close();
    return { sheet, active };
  }
  // A mouse: Edit starts on Name, Add on the link.
  let { sheet, active } = opened(false, { row });
  assert.equal(active.getAttribute("id"), `acc-name-${sheet.heading.id}`);
  ({ sheet, active } = opened(false, { kind: "sleeves" }));
  assert.equal(active.getAttribute("type"), "url");
  // A finger: Edit focuses the heading without scrolling, so the sheet opens at its top with the picture showing.
  ({ sheet, active } = opened(true, { row }));
  assert.equal(active, sheet.heading);
  assert.equal(sheet.heading.getAttribute("tabindex"), "-1");
  assert.equal(active.focusOptions.preventScroll, true);
  // Add still starts on the link (there's no picture yet to keep in view).
  ({ sheet, active } = opened(true, { kind: "sleeves" }));
  assert.equal(active.getAttribute("type"), "url");
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AccessorySheetFocusTests(unittest.TestCase):
    def test_first_focus_by_pointer(self):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SCENARIO, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
