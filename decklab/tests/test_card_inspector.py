"""Card inspector data and the card viewer's interactions; local Scryfall fixtures, no browser or network."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from decklab.lib import cards
from decklab.lib.api.card_lookup import _card_json, image_file

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "decklab" / "web"
FIXTURES = Path(__file__).parent / "fixtures"


class InspectorDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = cards.build_index(FIXTURES / "default_cards.jsonl", FIXTURES / "oracle_tags.jsonl", log=lambda _: None)

    def setUp(self):
        self.index_patch = patch.object(cards, "_index", cards._prepare(self.index))
        self.index_patch.start()
        self.addCleanup(self.index_patch.stop)

    def test_single_face_rules_and_no_image_are_available(self):
        card = cards.card("Llanowar Elves")
        result = _card_json(card, None)
        self.assertEqual(result["oracle_text"], card["oracle_text"])
        self.assertEqual((result["power"], result["toughness"]), ("1", "1"))
        self.assertIsNone(result["img"])

    def test_transform_and_modal_faces_have_separate_rules_and_images(self):
        for name, printing in (("Delver of Secrets // Insectile Aberration", ("isd", "51")),
                               ("Emeria's Call // Emeria, Shattered Skyclave", ("znr", "12"))):
            with self.subTest(name=name):
                card = cards.card(name)
                p = cards.printing(*printing)
                self.assertIsNotNone(p)
                result = _card_json(card, p)
                self.assertEqual(result["faces"][1]["oracle_text"], card["faces"][1]["oracle_text"])
                self.assertEqual(result["faces"][1]["img"], f"/img/{printing[0]}/{printing[1]}/normal-back")
                self.assertNotEqual(result["faces"][0]["img"], result["faces"][1]["img"])
                p = dict(p, **{"image_normal-back": None, "image_small-back": None})
                self.assertIsNone(_card_json(card, p)["faces"][1]["img"], "missing backs must not show front artwork")

    def test_adventure_and_split_keep_shared_art_but_distinct_rules(self):
        for name in ("Murderous Rider // Swift End", "Fire // Ice"):
            with self.subTest(name=name):
                card = cards.card(name)
                p = cards.printing(*card["printings"][0])
                faces = _card_json(card, p)["faces"]
                self.assertEqual(faces[0]["img"], faces[1]["img"])
                self.assertNotEqual(faces[0]["oracle_text"], faces[1]["oracle_text"])

    def test_back_image_cache_downloads_the_back_once_without_overwriting_front(self):
        p = cards.printing("isd", "51")
        with tempfile.TemporaryDirectory() as temporary:
            def download(url, path, **kwargs):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(url.encode())
            with patch.object(cards, "IMAGES_DIR", Path(temporary)), patch.object(cards, "_download", side_effect=download) as fetch:
                front = image_file("isd", "51", "normal")
                back = image_file("isd", "51", "normal-back")
                self.assertEqual(image_file("isd", "51", "normal-back"), back)
                self.assertNotEqual(front, back)
                self.assertEqual(front.read_text(), p["image_normal"])
                self.assertEqual(back.read_text(), p["image_normal-back"])
                self.assertEqual(fetch.call_count, 2)


# The card viewer (web/card-viewer.js) under Node.js, with the page's own el() and add() (core.js), symbols.js,
# cards-ui.js and deck.js, over a small stand-in for the DOM. matchMedia says motion is reduced, so a move
# lands at once (the last move is checked with its slide). argv[1] is the web folder.
NODE_RUNNER = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
class Node {}
class Element extends Node {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.events = {};
    this.parentNode = null; this.style = { transform: '' }; this.dataset = {}; this.scrollTop = 0; const self = this;
    this.classList = { add: (...c) => self._cls(c, true), remove: (...c) => self._cls(c, false),
      toggle: (c, on) => { const has = self._classes().includes(c); on = on === undefined ? !has : on; self._cls([c], on); return on; },
      contains: (c) => self._classes().includes(c) }; }
  _classes() { return (this.attrs.class || '').split(/\s+/).filter(Boolean); }
  _cls(names, on) { const set = new Set(this._classes()); for (const n of names) { if (on) set.add(n); else set.delete(n); } this.attrs.class = [...set].join(' '); }
  get hidden() { return 'hidden' in this.attrs; }
  set hidden(v) { if (v) this.attrs.hidden = ''; else delete this.attrs.hidden; }
  get disabled() { return 'disabled' in this.attrs; }
  set disabled(v) { if (v) this.attrs.disabled = ''; else delete this.attrs.disabled; }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === document.body; }
  get clientWidth() { return 400; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; if (k === 'src') this.src = ''; }
  append(...items) {
    for (const item of items) {
      const n = typeof item === 'string' ? new TextNode(item) : item;
      if (n.parentNode) n.remove();
      n.parentNode = this; this.children.push(n);
    }
  }
  replaceChildren(...items) { for (const c of this.children) c.parentNode = null; this.children = []; this.append(...items); }
  remove() { if (this.parentNode) { const list = this.parentNode.children; list.splice(list.indexOf(this), 1); this.parentNode = null; } }
  replaceWith(n) { const p = this.parentNode, list = p.children; list[list.indexOf(this)] = n; n.parentNode = p; this.parentNode = null; }
  contains(n) { for (; n; n = n.parentNode) if (n === this) return true; return false; }
  closest(sel) { const key = sel.slice(1, -1); for (let n = this; n && n.getAttribute; n = n.parentNode) if (n.getAttribute(key) !== null) return n; return null; }
  getClientRects() { return [1]; }
  all() { return this.children.flatMap((c) => (c instanceof Element ? [c, ...c.all()] : [])); }
  addEventListener(k, f) { (this.events[k] = this.events[k] || []).push(f); }
  fire(k, event = {}) {
    const e = { type: k, target: this, currentTarget: this, cancelable: true, preventDefault() { this.defaultPrevented = true; }, ...event };
    for (const f of this.events[k] || []) f(e);
    return e;
  }
  focus() { document.activeElement = this; }
  setPointerCapture(id) { this.captured = id; }
  showModal() { this.open = true; }
  close() { if (!this.open) return; this.open = false; this.fire('close'); }
  set textContent(v) { this.replaceChildren(String(v)); }
  get textContent() { return this.children.map((c) => c.textContent).join(''); }
}
class TextNode extends Node {
  constructor(t) { super(); this.data = t; this.parentNode = null; }
  get textContent() { return this.data; }
  remove() { if (this.parentNode) { const l = this.parentNode.children; l.splice(l.indexOf(this), 1); this.parentNode = null; } }
}
const document = { activeElement: null, body: new Element('body'), documentElement: new Element('html'),
  createElement: (t) => new Element(t), createElementNS: (ns, t) => new Element(t), createTextNode: (t) => new TextNode(t),
  addEventListener() {}, querySelector: () => null,
  querySelectorAll: (sel) => document.body.all().filter((n) => sel.startsWith('[')
    ? n.getAttribute(sel.slice(1, -1)) !== null : n.tagName === sel.toUpperCase()) };
const historyLog = [];
const history = { state: { pos: 4 }, length: 5,
  pushState(state) { historyLog.push(['push', state]); this.state = state; this.length += 1; },
  replaceState(state) { historyLog.push(['replace', state]); this.state = state; },
  back() { historyLog.push(['back']); this.state = { pos: 4 }; } };
let now = 1000;
const ctx = { document, Node, console, history, setTimeout, clearTimeout, Date: { now: () => now },
  matchMedia: () => ({ matches: true }), entryPos: () => history.state.pos,
  window: { addEventListener(k, f) { if (k === 'popstate') ctx.popstate = f; } } };
ctx.globalThis = ctx;
vm.createContext(ctx);
for (const f of ['core.js', 'symbols.js', 'cards-ui.js', 'card-viewer.js', 'deck.js']) {
  vm.runInContext(fs.readFileSync(process.argv[1] + '/' + f, 'utf8'), ctx, { filename: f });
}
const run = (code) => vm.runInContext(code, ctx);
run('setUpDialog()');
const text = (n) => n.textContent;
const find = (cls, root = document.body) => root.all().find((n) => n.classList.contains(cls));
const current = () => run('viewerDom').slides[1];

// One card: the faces, the rules, flipping, image errors, taps, closing and the focus.
const trigger = new Element('button');
document.body.append(trigger);
const dfc = { name: 'Front // Back', type_line: 'Creature // Creature', img: '/img/a/1/normal', img_small: '/img/a/1/small',
  faces: [{ name: 'Front', type_line: 'Creature', oracle_text: '{T}: Add {G}. (Reminder.)', img: '/img/a/1/normal', mana_cost: '{1}{G}' },
    { name: 'Back', type_line: 'Creature', oracle_text: 'Other rules', img: '/img/a/1/normal-back', power: '3', toughness: '2' }] };
run('openCard')(dfc, trigger);
const d = run('viewerDom');
assert(d.dialog.open);
assert.equal(document.activeElement, d.close);
assert(d.dialog.classList.contains('is-single'));
assert(!d.dialog.classList.contains('show-text'), 'a new viewer opening starts with the full picture');
assert.equal(text(d.title), 'Front // Back');
assert(text(d.text).includes('Other rules') && text(d.text).includes('3 / 2'), 'both faces are read');
const shownFace = () => d.text.all().filter((n) => n.classList.contains('is-shown')).map((n) => text(n));
assert.equal(shownFace().length, 1);
assert(shownFace()[0].startsWith('FrontShown'), 'the text marks the face the picture shows');
const tap = d.text.all().find((n) => n.tagName === 'IMG' && n.getAttribute('src') === '/sym/T.svg');
assert(tap && tap.getAttribute('alt') === 'tap', 'symbols are pictures with words');
assert(d.text.all().some((n) => n.tagName === 'I' && n.textContent === '(Reminder.)'));
assert.deepEqual(historyLog[0], ['push', { pos: 5, cardViewer: 1 }]);
assert(!d.flip.hidden);
let img = find('viewer-img', current());
assert.equal(img.src, '/img/a/1/normal');
const staleError = img.onerror;
d.flip.fire('click');
assert.equal(d.flip.getAttribute('aria-pressed'), 'true');
assert(shownFace()[0].startsWith('BackShown'), 'flipped, the back is marked');
// The Text panel: opening it moves the focus to the words, closing it back to the button (not the page).
d.textBtn.fire('click');
assert.equal(document.activeElement, d.text);
d.textBtn.fire('click');
assert.equal(document.activeElement, d.textBtn, 'closing the Text panel keeps the focus in the viewer');
img = find('viewer-img', current());
assert.equal(img.src, '/img/a/1/normal-back');
staleError();
assert(find('viewer-retry', current()).hidden, 'an old image answer never spoils the new face');
img.onerror();
assert(!find('viewer-retry', current()).hidden);
assert(text(current()).includes("couldn't load"));
find('viewer-retry', current()).onclick();
img.onload();
assert(find('viewer-retry', current()).hidden);
assert(!find('viewer-frame', current()).classList.contains('is-loading'));
d.dialog.fire('click', { target: img });
assert(d.dialog.open, 'a tap on the card keeps it open');
d.dialog.fire('click', { target: d.stage });
assert(!d.dialog.open, 'a tap beside it closes');
assert.equal(document.activeElement, trigger);
assert.deepEqual(historyLog[historyLog.length - 1], ['back']);

// No picture: its words in its place.
run('openCard')({ name: 'No artwork', type_line: 'Land', oracle_text: 'Usable rules', img: null }, trigger);
assert(text(current()).includes('Usable rules') && text(current()).includes('No image'));
d.dialog.fire('cancel');
assert(!d.dialog.open, 'Escape closes');

// A group: rows made with a viewerGroup open over each other, in page order.
const cards = ['A', 'B', 'C'].map((n) => ({ name: n, type_line: 'Instant', oracle_text: n + ' rules', img: `/img/x/${n}/normal`, img_small: `/img/x/${n}/small` }));
const rows = cards.map((c) => run('cardRow')(c, { qty: 2, viewerGroup: 'deck', caption: c.name + ' caption',
  viewerStatus: c.name === 'B' ? () => [run('status')('crit', 'Missing · need 2, have 0')] : null }));
const list = new Element('ul');
for (const r of rows) list.append(r);
document.body.append(list);
rows[1].fire('click');
assert.equal(text(d.count), '2 / 3');
assert(!d.dialog.classList.contains('is-single'));
assert.equal(text(d.hint), 'Swipe left or right');
assert(text(d.text).includes('B caption'));
// The tile's status stays in sight under the counter (a missing card doesn't look owned once it's big).
assert.equal(text(d.marks), 'Missing · need 2, have 0');
assert(!d.marks.hidden);
assert(!text(d.text).includes('Oracle text from'), 'no data-source footnote');
assert.equal(find('viewer-img', d.slides[0]).src, '/img/x/A/normal', 'the cards either side are drawn');
assert.equal(find('viewer-img', d.slides[2]).src, '/img/x/C/normal');
const key = (k) => d.dialog.fire('keydown', { key: k });
d.next.focus();
key('ArrowRight'); assert.equal(text(d.count), '3 / 3'); assert(d.next.disabled);
assert.equal(document.activeElement, d.prev, 'a nav button being disabled hands its focus on');
key('ArrowRight'); assert.equal(text(d.count), '3 / 3');
key('Home'); assert.equal(text(d.count), '1 / 3'); assert(d.prev.disabled);
assert.equal(document.activeElement, d.next);
d.next.fire('click'); assert.equal(text(d.title), 'B');

// Captured touch taps on the image must not become backdrop-dismiss clicks.
const tapPic = find('viewer-img', current());
d.dialog.fire('pointerdown', { pointerId: 8, pointerType: 'touch', clientX: 200, clientY: 300, timeStamp: 0, button: 0, target: tapPic });
d.dialog.fire('pointerup', { pointerId: 8, pointerType: 'touch', clientX: 200, clientY: 300, timeStamp: 50, target: d.dialog });
d.dialog.fire('click', { target: d.dialog });
assert(d.dialog.open, 'a captured image tap does not dismiss the viewer');

// Swipes: far enough or a flick turns the card; a short slow drag or the end of the list springs back.
const drag = (dx, ms, later = true, steps = 4) => {
  let t = 0;
  d.dialog.fire('pointerdown', { pointerId: 1, clientX: 300, clientY: 300, timeStamp: t, button: 0, isPrimary: true, target: d.stage });
  for (let i = 1; i <= steps; i++) {
    t += ms / steps;
    d.dialog.fire('pointermove', { pointerId: 1, clientX: 300 + dx * i / steps, clientY: 302, timeStamp: t, target: d.stage });
  }
  d.dialog.fire('pointerup', { pointerId: 1, clientX: 300 + dx, clientY: 302, timeStamp: t + 5, target: d.stage });
  if (later) now += 1000;
};
drag(-150, 400); assert.equal(text(d.count), '3 / 3', 'past a fifth of the width');
drag(150, 400); assert.equal(text(d.count), '2 / 3');
drag(-40, 600); assert.equal(text(d.count), '2 / 3', 'a short slow drag springs back');
drag(-50, 40); assert.equal(text(d.count), '3 / 3', 'a flick turns it');
drag(-200, 300); assert.equal(text(d.count), '3 / 3', 'nothing past the last card');
// A touch: the picture under the finger has the pointer first, and loses it (an event that bubbles to the
// stage) when the stage takes it over; that isn't the end of the swipe.
const touch = (dx) => {
  const pic = find('viewer-img', current());
  d.dialog.fire('pointerdown', { pointerId: 7, pointerType: 'touch', clientX: 300, clientY: 300, timeStamp: 0, button: 0, isPrimary: true, target: pic });
  d.dialog.fire('pointermove', { pointerId: 7, pointerType: 'touch', clientX: 300 + dx / 4, clientY: 301, timeStamp: 100, target: pic });
  d.dialog.fire('lostpointercapture', { pointerId: 7, pointerType: 'touch', target: pic });
  for (const i of [2, 3, 4]) d.dialog.fire('pointermove', { pointerId: 7, pointerType: 'touch', clientX: 300 + dx * i / 4, clientY: 302, timeStamp: 100 * i, target: d.stage });
  d.dialog.fire('pointerup', { pointerId: 7, pointerType: 'touch', clientX: 300 + dx, clientY: 302, timeStamp: 405, target: d.stage });
  d.dialog.fire('lostpointercapture', { pointerId: 7, pointerType: 'touch', target: d.dialog });
  now += 1000;
};
// A swipe that starts on the dark space beside the card (most of a wide screen) turns it too; one that
// starts on a button is the button's.
const side = (dx, target) => {
  d.dialog.fire('pointerdown', { pointerId: 3, pointerType: 'touch', clientX: 100, clientY: 300, timeStamp: 0, button: 0, isPrimary: true, target });
  for (const i of [1, 2, 3, 4]) d.dialog.fire('pointermove', { pointerId: 3, pointerType: 'touch', clientX: 100 + dx * i / 4, clientY: 301, timeStamp: 80 * i, target: d.stage });
  d.dialog.fire('pointerup', { pointerId: 3, pointerType: 'touch', clientX: 100 + dx, clientY: 301, timeStamp: 325, target: d.stage });
  now += 1000;
};
side(150, d.dialog); assert.equal(d.dialog.captured, 3, 'touch captures the entire dialog'); assert.equal(text(d.count), '2 / 3', 'a swipe on the dark space turns the card');
side(-150, d.dialog); assert.equal(text(d.count), '3 / 3');
side(150, d.close); assert.equal(text(d.count), '3 / 3', 'a press on a button never starts a swipe');
touch(150); assert.equal(text(d.count), '2 / 3', 'a touch swipe right goes back a card');
touch(-150); assert.equal(text(d.count), '3 / 3', 'a touch swipe left goes on a card');
assert.equal(d.track.style.transform, '');
d.dialog.fire('pointerdown', { pointerId: 1, clientX: 300, clientY: 300, timeStamp: 0, button: 0, target: d.stage });
d.dialog.fire('pointermove', { pointerId: 1, clientX: 305, clientY: 380, timeStamp: 50, target: d.stage });
d.dialog.fire('pointerup', { pointerId: 1, clientX: 305, clientY: 380, timeStamp: 60, target: d.stage });
assert.equal(text(d.count), '3 / 3', 'an up-and-down move is left alone');
drag(-30, 600, false);
d.dialog.fire('click', { target: d.stage });
assert(d.dialog.open, 'the click after a swipe is not a tap');
now += 1000;

// Back closes it without another step back; a card outside the group opens alone.
history.state = { pos: 4 };
const before = historyLog.length;
ctx.popstate();
assert(!d.dialog.open);
assert.equal(historyLog.length, before);
run('openCard')(cards[0], trigger);
assert(d.dialog.classList.contains('is-single'));
d.close.fire('click');

// Card names (deck.js cardLink: the guide, stats, practice, matchups) are a viewer group of their own.
for (const c of cards) run('state').cards.set(c.name, c);
const names = new Element('p');
const links = cards.map((c) => run('cardLink')({ name: c.name }));
for (const l of links) names.append(l);
document.body.append(names);
links[2].fire('click');
assert.equal(text(d.count), '3 / 3', 'a named card opens over the other names on the page');
key('ArrowLeft'); assert.equal(text(d.title), 'B');
d.close.fire('click');
names.remove();

// A stale viewer entry (closed with Close, then Forward) loses its mark and never keeps a later viewer open.
const stale = historyLog.filter((x) => x[0] === 'push').pop()[1];
history.state = stale;
ctx.popstate();
assert.equal(history.state.cardViewer, undefined, 'landing on an old viewer entry takes its mark off');
assert.equal(history.state.pos, stale.pos);
history.state = { ...stale, cardViewer: stale.cardViewer };     // even one still marked (Back to it)
run('openCard')(cards[1], trigger);
history.state = { pos: 5, cardViewer: stale.cardViewer };
ctx.popstate();
assert(!d.dialog.open, 'Back to an earlier viewer entry closes the open viewer');

// With motion, a move slides first and lands after the transition.
ctx.matchMedia = () => ({ matches: false });
rows[0].fire('click');
d.next.fire('click');
assert(d.track.classList.contains('is-settling'));
assert.equal(d.track.style.transform, 'translateX(-100%)');
setTimeout(() => {
  assert.equal(text(d.count), '2 / 3');
  assert.equal(d.track.style.transform, '');
  assert(!d.track.classList.contains('is-settling'));
  process.stdout.write('ok');
}, 400);
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for inspector interaction checks")
class InspectorInteractionTests(unittest.TestCase):
    def test_viewer_faces_reading_errors_dismissal_focus_groups_and_swipes(self):
        done = subprocess.run([shutil.which("node"), "-e", NODE_RUNNER, str(WEB)],
                              capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "ok")

    def test_source_colours_have_accessible_names(self):
        from decklab.tests.test_web import _run_page
        answer = _run_page(['globalThis.symbolImg = (c, o) => el("img", { src: `/sym/${c}.svg`, alt: o.alt }); '
                            'const w = colourPips(["W", "G"]); '
                            'if (w.children.length !== 2 || w.children[0].attrs.src !== "/sym/W.svg") throw new Error("not symbols"); '
                            'JSON.stringify(w.attrs)',
                            'JSON.stringify(colourPips([]).attrs)'], names=("core.js", "stats.js"))
        self.assertEqual(json.loads(answer[0])["aria-label"], "white, green")
        self.assertEqual(json.loads(answer[1])["aria-label"], "No coloured mana")
        self.assertNotIn("aria-hidden", json.loads(answer[0]))


if __name__ == "__main__":
    unittest.main()
