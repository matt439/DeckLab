/* A small event/DOM test double, not browser automation. Loads the real page
 * functions; only start-up networking, rendering side effects and time are
 * controlled. Each Python test supplies one independent interaction scenario. */
"use strict";
const fs = require("fs"), vm = require("vm"), assert = require("assert/strict");
const [web, scenario, allScripts = false, viewport = null] = JSON.parse(fs.readFileSync(0, "utf8"));
const listeners = () => ({
  events: new Map(),
  addEventListener(type, fn) { if (!this.events.has(type)) this.events.set(type, []); this.events.get(type).push(fn); },
  removeEventListener(type, fn) { this.events.set(type, (this.events.get(type) || []).filter((f) => f !== fn)); },
  fire(type, props = {}) {
    const event = { target: this, currentTarget: this, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; }, ...props };
    for (const fn of this.events.get(type) || []) fn(event);
    return event;
  },
});
let document;
class Node {
  constructor(tag) {
    Object.assign(this, listeners());
    this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.style = {setProperty(name, value) { this[name] = String(value); }};
    this.parentNode = null; this.value = ""; this.hidden = false; this.disabled = false; this.scrollLeft = 0;
    this.box = { top: 0, bottom: 44, left: 0, right: 100, width: 100, height: 44 };
    const names = new Set();
    this.classList = { add: (...args) => args.forEach((n) => names.add(n)),
      remove: (...args) => args.forEach((n) => names.delete(n)), contains: (n) => names.has(n),
      toggle: (n, value) => { if (value === undefined ? !names.has(n) : value) names.add(n); else names.delete(n); } };
  }
  setAttribute(key, value) {
    this.attrs[key] = String(value);
    if (key === "id") this.id = String(value);
    if (key === "hidden" || key === "disabled") this[key] = true;
    if (key === "value") this.value = String(value);
    if (key.startsWith("data-")) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
  }
  getAttribute(key) { return key in this.attrs ? this.attrs[key] : null; }
  removeAttribute(key) { delete this.attrs[key]; if (key === "hidden" || key === "disabled") this[key] = false; }
  append(...items) {
    for (let item of items) { if (!(item instanceof Node)) item = new Text(String(item)); item.remove(); item.parentNode = this; this.children.push(item); }
  }
  appendChild(child) { this.append(child); return child; }
  insertBefore(child, before) {
    if (child === before) return child;
    if (before && before.parentNode !== this) throw Error("Insert reference is outside this parent");
    child.remove(); child.parentNode = this;
    this.children.splice(before ? this.children.indexOf(before) : this.children.length, 0, child); return child;
  }
  replaceChildren(...items) { this.children.forEach((n) => { n.parentNode = null; }); this.children = []; this.append(...items); }
  replaceWith(node) {
    const parent = this.parentNode; if (!parent) return;
    parent.children[parent.children.indexOf(this)] = node; node.parentNode = parent; this.parentNode = null;
  }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((n) => n !== this); this.parentNode = null; }
  set textContent(value) { this.replaceChildren(new Text(String(value))); }
  get textContent() { return this.children.map((c) => c.textContent).join(""); }
  contains(node) { return node === this || this.children.some((c) => c.contains(node)); }
  get isConnected() { return document.body.contains(this); }
  get nextSibling() { const nodes = this.parentNode?.children; return nodes ? nodes[nodes.indexOf(this) + 1] || null : null; }
  matches(selector) {
    const attr = /\[([^=\]]+)(?:=["']?([^\]"']+)["']?)?\]/g;
    for (const match of selector.matchAll(attr)) {
      if (this.getAttribute(match[1]) == null || (match[2] !== undefined && this.getAttribute(match[1]) !== match[2])) return false;
    }
    const simple = selector.replace(attr, "");
    if (simple.startsWith(".")) return (this.attrs.class || "").split(/\s+/).includes(simple.slice(1));
    if (simple.startsWith("#")) return this.id === simple.slice(1);
    return !simple || this.tag === simple;
  }
  querySelectorAll(selector) { return this.children.flatMap((n) => [...(n.matches(selector) ? [n] : []), ...n.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parentNode && this.parentNode.closest(selector); }
  focus(options) { if (this.disabled) return; document.activeElement = this; this.focusOptions = options; this.fire("focus"); }
  select() { this.selected = true; }
  scrollIntoView(options) { this.scrolled = (this.scrolled || 0) + 1; this.scrollOptions = options; }
  getBoundingClientRect() { return this.box; }
  click() { if (!this.disabled) this.fire("click"); }
}
class Text extends Node {
  constructor(data) { super("#text"); this.data = data; }
  get textContent() { return this.data; }
}
document = Object.assign(listeners(), {
  body: new Node("body"), documentElement: new Node("html"), activeElement: null,
  createElement: (tag) => new Node(tag), createElementNS: (_, tag) => new Node(tag),
  createTextNode: (text) => new Text(text),
  querySelector(selector) { return this.body.querySelector(selector); },
  querySelectorAll(selector) { return this.body.querySelectorAll(selector); },
  getElementById(id) { return this.body.querySelector("#" + id); },
});
const media = new Map();
const timers = new Map(); let nextTimer = 0;
const window = Object.assign(listeners(), {
  innerHeight: 1300, innerWidth: 2545, scrollY: 0,
  matchMedia(query) {
    if (!media.has(query)) media.set(query, Object.assign(listeners(), { matches: false, media: query }));
    return media.get(query);
  },
  scrollTo() {}, scrollBy() {},
});
// Viewport listeners register as the real scripts load, before the scenario.
if (viewport) {
  window.innerWidth = viewport.innerWidth;
  window.innerHeight = viewport.innerHeight;
  window.visualViewport = Object.assign(listeners(), {offsetLeft: 0, offsetTop: 0, scale: 1}, viewport.visual);
  window.matchMedia("(pointer: coarse)").matches = !!viewport.coarse;
  document.documentElement.style.setProperty = function (name, value) { this[name] = value; };
}
const context = { Node, document, window, console, URL, URLSearchParams, assert,
  navigator: {}, location: { hash: "#/library", search: "", href: "http://localhost/" },
  history: { state: {}, length: 1, replaceState() {} },
  setTimeout: (fn) => { const id = ++nextTimer; timers.set(id, fn); return id; },
  clearTimeout: (id) => timers.delete(id),
  requestAnimationFrame: (fn) => { const id = ++nextTimer; timers.set(id, fn); return id; },
  fetch: () => Promise.reject(new Error("network is disabled in this test")),
  AbortController, structuredClone, CSS: { escape: (s) => String(s) },
  flushTimers: () => { const current = [...timers.values()]; timers.clear(); current.forEach((fn) => fn()); },
};
vm.createContext(context);
const scriptNames = allScripts ? [...fs.readFileSync(web + "/index.html", "utf8").matchAll(/<script src="\/([^"?]+)"/g)].map(m => m[1])
  : ["core.js", "ui.js", "symbols.js", "cards-ui.js", "card-viewer.js", "library-tables.js", "library-boxchecks.js", "editor.js", "deck-availability.js", "deck.js", "deck-header.js", "deck-overview.js", "deck-retirement.js", "deck-prices.js", "deck-sideboard.js", "deck-opponents.js", "deck-standins.js", "deck-swaps.js", "product-storage.js", "token-plan.js", "accessory-pictures.js", "assembly-chooser.js", "assembly-switcher.js", "assembly-finish.js", "assembly-steps.js", "assembly-overlap.js", "assembly-sections.js", "assembly-sheets.js", "assembly-boxcheck.js", "box-collection.js", "box-editor.js", "collection-guards.js", "activity-undo.js", "precon-token-choices.js", "receipts.js", "receipt-tiles.js", "receipt-layout.js", "receipt-workflow.js", "commander-readiness.js", "commander-night.js", "deck-tools.js", "editor-screen.js", "editor-details.js", "editor-lines.js", "editor-cards.js", "editor-search-quantity.js", "editor-search-dock.js", "editor-swaps.js", "editor-save.js", "wishlist.js", "shopping.js", "shopping-buying.js", "shopping-queue.js", "shopping-reprints.js", "shopping-orders.js", "shopping-order-edit.js", "shopping-order-rows.js", "keyboard-help.js", "shell.js", "app.js"];
for (const name of scriptNames) {
  let source = fs.readFileSync(web + "/" + name, "utf8");
  // Network start-up is outside these tests; all actual interaction functions
  // and registered listeners are retained verbatim.
  if (name === "app.js") source = source.replace(/\nstart\(\);\s*$/, "\n");
  vm.runInContext(source, context, { filename: name });
}
vm.runInContext(`
  const main = el("main", {id: "main"}); document.body.append(main);
  let changes = 0, inspections = [];
  changed = () => { changes += 1; };
  openCard = (card, trigger) => { inspections.push({card, trigger}); };
  afterRender = () => {};
  editor = {mode: "new", profile: state.profile?.id, fields: {kind: "casual"}, lists: {Deck: []}, sections: ["Deck", "Sideboard"],
    addSection: "Deck", dom: {}, checkSeq: 0};
  const alpha = {name: "Alpha", mana_cost: "{G}", type_line: "Creature — Elf", cmc: 1, have: {}, default: null};
  const beta = {name: "Beta", mana_cost: "{U}", type_line: "Instant", cmc: 1, have: {}, default: null};
  const wrap = cardSearch(); main.append(wrap); const ac = editor.ac;
  function results(query, cards = [alpha, beta]) {
    ac.input.value = query; ac.query = query; ac.items = cards; ac.active = 0; drawOptions(ac);
  }
  function same(actual, expected) { assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected); }
`, context);
Promise.resolve(vm.runInContext(`(async () => { ${scenario}\n })()`, context))
  .then(() => process.stdout.write("ok\n"))
  .catch((error) => { process.stderr.write(error.stack + "\n"); process.exitCode = 1; });
