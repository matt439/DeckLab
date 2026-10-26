"""ui.js openMenu's placement under Node.js, over a small stand-in for the DOM: below its button, or above it
when it doesn't fit below (a Save caret in a bottom bar), and opening it never scrolls the page."""
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "decklab" / "web"

NODE_RUNNER = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
class Node {}
class Element extends Node {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.events = {}; this.parentNode = null;
    this.style = {}; this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false }; this.box = null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...items) { for (const n of items) { if (typeof n === 'string') continue; n.parentNode = this; this.children.push(n); } }
  remove() { if (this.parentNode) { const l = this.parentNode.children; l.splice(l.indexOf(this), 1); this.parentNode = null; } }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === document.body; }
  contains(n) { for (; n; n = n.parentNode) if (n === this) return true; return false; }
  addEventListener(k, f) { (this.events[k] = this.events[k] || []).push(f); }
  removeEventListener() {}
  focus(opts) { document.activeElement = this; focusCalls.push(opts || null); }
  getBoundingClientRect() { return this.box; }
  get offsetWidth() { return 200; }
  get offsetHeight() { return this.tagName === 'UL' ? 90 : 0; }
  set textContent(v) { this.text = String(v); }
}
const focusCalls = [];
const document = { activeElement: null, body: new Element('body'), documentElement: { clientWidth: 820 },
  createElement: (t) => new Element(t), createElementNS: (ns, t) => new Element(t), createTextNode: (t) => t,
  addEventListener() {}, removeEventListener() {}, getElementById: () => null, querySelector: () => null,
  querySelectorAll: () => [] }; // This placement fixture has no core popover menus or dialogs.
const window = { innerHeight: 1106, scrollX: 0, scrollY: 400, addEventListener() {}, removeEventListener() {} };
const ctx = { document, window, Node, console, setTimeout, clearTimeout };
ctx.globalThis = ctx;
vm.createContext(ctx);
for (const f of ['core.js', 'ui.js']) vm.runInContext(fs.readFileSync(process.argv[1] + '/' + f, 'utf8'), ctx, { filename: f });
const openMenu = vm.runInContext('openMenu', ctx);
const menuOf = () => document.body.children.find((n) => n.tagName === 'UL');

// A button in a bar at the screen's bottom: the menu opens above it, fully on screen.
const caret = new Element('button');
caret.box = { top: 1054, bottom: 1098, left: 756, right: 796 };
document.body.append(caret);
let m = openMenu(caret, [{ text: 'Save & view deck' }]);
assert.equal(menuOf().style.top, `${1054 - 4 - 90 + 400}px`, 'above the button, in page coordinates');
assert.deepEqual(focusCalls.pop(), { preventScroll: true }, 'focusing the first item never scrolls the page');
m.close();

// A button in the top half: below it, as before.
const top = new Element('button');
top.box = { top: 200, bottom: 240, left: 40, right: 140 };
document.body.append(top);
m = openMenu(top, [{ text: 'One' }, { text: 'Two' }]);
assert.equal(menuOf().style.top, `${240 + 4 + 400}px`);
m.close();

// Room neither below nor above (a tiny window): below it, as before.
window.innerHeight = 120;
top.box = { top: 60, bottom: 100, left: 40, right: 140 };
m = openMenu(top, [{ text: 'One' }]);
assert.equal(menuOf().style.top, `${100 + 4 + 400}px`);
m.close();
process.stdout.write('ok');
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for the menu checks")
class MenuPlacementTests(unittest.TestCase):
    def test_menu_flips_above_a_bottom_button_without_scrolling(self):
        done = subprocess.run([shutil.which("node"), "-e", NODE_RUNNER, str(WEB)],
                              capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "ok")


if __name__ == "__main__":
    unittest.main()
