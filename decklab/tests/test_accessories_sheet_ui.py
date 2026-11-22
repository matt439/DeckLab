"""The accessories add/edit sheet starts on Name with a mouse or on its heading with touch.

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
  // A mouse: Name comes first; the picture and link are optional.
  let { sheet, active } = opened(false, { row });
  assert.equal(active.getAttribute("id"), `acc-name-${sheet.heading.id}`);
  ({ sheet, active } = opened(false, { kind: "sleeves" }));
  assert.equal(active.getAttribute("id"), `acc-name-${sheet.heading.id}`);
  assert(!sheet.body.querySelector('.acc-photo-settings').open);
  // Touch focuses the heading instead of bringing up the keyboard.
  ({ sheet, active } = opened(true, { row }));
  assert.equal(active, sheet.heading);
  assert.equal(sheet.heading.getAttribute("tabindex"), "-1");
  assert.equal(active.focusOptions.preventScroll, true);
  ({ sheet, active } = opened(true, { kind: "sleeves" }));
  assert.equal(active, sheet.heading);
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
