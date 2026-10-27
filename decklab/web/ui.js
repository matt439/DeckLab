/* Deck Lab's page: small helpers for components.css's shared pieces (decklab/UI-KIT.md): an overflow
menu (openMenu), a toast with Undo (showToast), the sticky bottom action bar (actionBar) and a deck's colour
pieces (deckColourPieces: its pips, stripe, tint and swatch). Sheets are editor.js's openSheet, sheetActions
and ask(); the plain toast is core.js's toast().

Loaded after core.js; nothing runs at load.
*/
"use strict";

const UNDO_MS = 8000;           // how long a toast with Undo stays
let openMenuNow = null;         // the menu open now ({close}), so opening another closes it

/** An overflow menu ("More ▾", a row's ⋯) under anchor, a button (above it when it fits there but not below). items: [{text, onclick?, href?, current?,
 * danger?, disabled?}] or "-" for a separator. A click on an item, Escape, Tab or a click elsewhere closes
 * it; the arrow keys, Home and End move between items, and the focus goes back to anchor. Sets anchor's
 * aria-expanded while it's open. Returns {node, close()}. */
function openMenu(anchor, items) {
  const dialog = keyboardDialog();
  if (!anchor || !anchor.isConnected || anchor.disabled || anchor.getAttribute("aria-disabled") === "true"
      || (dialog && !dialog.contains(anchor))) return { node: null, close() {} };
  keyboardMenuButton(anchor);
  if (openMenuNow) openMenuNow.close();
  closeMenus();
  const list = el("ul", { class: "menu", role: "menu", id: `menu-${++menuSeq}`, "data-popover": "" });
  list.keyboardAnchor = anchor;
  list.closePopover = () => close(false);
  const buttons = [];
  for (const item of items || []) {
    if (!item) continue;
    if (item === "-") { list.append(el("li", { class: "menu-sep", role: "separator" })); continue; }
    const props = { role: "menuitem", class: item.danger ? "menu-danger" : null, tabindex: "-1",
      "aria-current": item.current ? "page" : null, "aria-disabled": item.disabled ? "true" : null };
    const node = item.href
      ? el("a", { ...props, href: item.href, text: item.text,
        onclick: (event) => { if (item.disabled) { event.preventDefault(); return; } close(false); } })
      : el("button", { ...props, type: "button", text: item.text, disabled: item.disabled || null,
        onclick: () => { close(true); if (item.onclick) item.onclick(); } });
    buttons.push(node);
    list.append(el("li", { role: "none" }, node));
  }
  const place = () => {
    const box = anchor.getBoundingClientRect();
    const width = list.offsetWidth;
    const left = Math.max(8, Math.min(box.right - width, document.documentElement.clientWidth - width - 8));
    // Below the anchor, or above it when it doesn't fit below but does above (a Save caret in a bottom bar).
    const height = list.offsetHeight;
    const fitsBelow = box.bottom + 4 + height <= window.innerHeight;
    const top = fitsBelow || box.top - 4 - height < 0 ? box.bottom + 4 : box.top - 4 - height;
    list.style.left = `${left + window.scrollX}px`;
    list.style.top = `${top + window.scrollY}px`;
  };
  const outside = (e) => { if (!list.contains(e.target) && !anchor.contains(e.target)) close(false); };
  const keys = (e) => {
    if (!anchor.isConnected) { close(false); return; }
    if (!keyboardMenuOwns(list) || !list.contains(e.target) || keyboardEditing(e.target)
        || e.defaultPrevented || e.isComposing || e.keyCode === 229
        || e.altKey || e.ctrlKey || e.metaKey || (e.shiftKey && e.key !== "Tab")) return;
    if (e.repeat && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); return; }
    const enabled = buttons.filter((node) => !node.disabled && node.getAttribute("aria-disabled") !== "true");
    const at = enabled.indexOf(document.activeElement);
    const go = (i) => { if (!enabled.length) return; e.preventDefault();
      enabled[(i + enabled.length) % enabled.length].focus({ preventScroll: true }); };
    if (e.key === "Escape") { e.preventDefault(); close(true); }
    else if (e.key === "Tab") close(false);
    else if (e.key === "ArrowDown") go(at + 1);
    else if (e.key === "ArrowUp") go(at < 0 ? -1 : at - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(-1);
  };
  function close(refocus) {
    if (!list.isConnected) return;
    list.remove();
    anchor.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", outside, true);
    window.removeEventListener("resize", place);
    if (openMenuNow && openMenuNow.node === list) openMenuNow = null;
    if (refocus && anchor.isConnected) anchor.focus();
  }
  list.addEventListener("keydown", keys);
  document.body.append(list);
  place();
  anchor.setAttribute("aria-haspopup", "menu");
  anchor.setAttribute("aria-controls", list.id);
  anchor.setAttribute("aria-expanded", "true");
  document.addEventListener("pointerdown", outside, true);
  window.addEventListener("resize", place);
  const first = buttons.find((node) => !node.disabled && node.getAttribute("aria-disabled") !== "true");
  if (first) first.focus({ preventScroll: true });
  openMenuNow = { node: list, close: () => close(false) };
  return openMenuNow;
}

/** A toast at the bottom of the screen. With opts.undo (a function) it has an Undo button and stays
 * UNDO_MS (8 s): use it for removals and picks that happen at once, never instead of a confirm for
 * something that can't be undone. opts.ms: how long it stays. Returns {close()}. Without undo it's the
 * same as core.js's toast(). */
function showToast(message, opts = {}) {
  if (!opts.undo) { toast(message); return { close() { toast(""); } }; }
  let box = document.getElementById("toast-undo");
  if (!box) {
    box = el("div", { id: "toast-undo", class: "toast toast-undo", role: "status", "aria-live": "polite" });
    document.body.append(box);
  }
  clearTimeout(box.timer);
  const close = () => { clearTimeout(box.timer); clear(box); };
  add(clear(box), [el("span", { text: message }),
    el("button", { type: "button", class: "btn btn-quiet", text: opts.undoText || "Undo",
      onclick: () => { close(); opts.undo(); } })]);
  box.timer = setTimeout(close, opts.ms || UNDO_MS);
  return { close };
}

/** The sticky bar at the bottom of a page or form (components.css .action-bar): a status on the left (words
 * or nodes) and the actions on the right (nodes, usually one .btn-primary). Returns {node, status(...parts),
 * actions(...nodes)}, the last two to change them. */
function actionBar({ status: words = null, actions = [] } = {}) {
  const where = el("div", { class: "action-bar-status", role: "status", "aria-live": "polite" }, words);
  const buttons = el("div", { class: "actions" }, actions);
  const node = el("div", { class: "action-bar" }, where, buttons);
  return {
    node,
    status(...parts) { add(clear(where), parts); },
    actions(...nodes) { add(clear(buttons), nodes); },
  };
}


// ------------------------------------------------------------ a deck's colours

const PIP_SIZES = { 16: "sm", 20: "md", 22: "lg", 24: "xl" };   // tokens.css --pip-sm ... --pip-xl

/** The owned bar (design/visual-design.md 4.10): how much of a list is here, accent, then what's on the way,
 * hatched, on a --surface-3 track; aria-hidden, so put the words beside it. owned, waiting and total are copies. */
function ownedBar(owned, waiting, total) {
  const share = (n) => `${Math.round(Math.max(0, Math.min(1, total ? n / total : 0)) * 1000) / 10}%`;
  return el("span", { class: "owned-bar", "aria-hidden": "true" },
    el("span", { class: "owned-bar-fill", style: `width: ${share(owned)}` }),
    waiting ? el("span", { class: "owned-bar-way", style: `width: ${share(waiting)}` }) : null);
}

/** A deck's colour pieces (design/visual-design.md 4.3 and 2.2) from its colour identity: the letters of its
 * commander's color_identity, else its cards' (the server's "colors" in /api/decks, deck.js deckPageColours),
 * never typed. [] is a colourless deck, drawn as one C. null or undefined (not known: no card could be read)
 * gives null, so the page draws nothing. Otherwise {colours, label, pips(size, opts), stripe(thin), swatch(),
 * tint(angle), art, vars(angle)}:
 * - colours: WUBRG order, ["C"] for colourless; label: "Colours: blue, red", or "Colourless".
 * - pips(size, {overArt, cls}): a role="img" group named by label, one pip per colour, 16, 20, 22 or 24 px
 *   (else 20); overArt gives each pip the white ring for a picture; cls is the page's own class.
 * - stripe(thin) and swatch(): aria-hidden (the pips or words beside them say the colours), equal hard
 *   segments of --stripe-*; the stripe 5 px across a tile or head (thin: 3 px under a thumbnail), the swatch a
 *   small block before a deck's name on a page that isn't about decks.
 * - tint(angle): a background image, 135deg on tiles and 90 on bands: one colour's tint to its deeper stop, two
 *   colours' tints, three at 0, 55 and 100%, and the neutral --tint-multi for four or five (four pastels turn
 *   to mud). In dark the tints are the dark stripes, translucent, so lay it over --surface (.deck-tint does).
 * - art: the picture's placeholder colour, the first colour's (--art-multi for three or more).
 * - vars(angle): "--deck-stripe: …; --deck-tint: …; --deck-art: …" for a style attribute, read by .deck-tint
 *   and a page's own rules. */
function deckColourPieces(identity) {
  if (!Array.isArray(identity)) return null;
  const has = new Set(identity.map((c) => String(c).toUpperCase()));
  const found = "WUBRG".split("").filter((c) => has.has(c));
  const colours = found.length ? found : ["C"];
  const token = (kind, c, suffix = "") => `var(--${kind}-${c.toLowerCase()}${suffix})`;
  const at = (i) => `${Math.round((i / colours.length) * 10000) / 100}%`;
  const stripeImage = `linear-gradient(90deg, ${colours.map((c, i) => `${token("stripe", c)} ${at(i)} ${at(i + 1)}`).join(", ")})`;
  const label = found.length ? `Colours: ${found.map((c) => COLOUR_WORDS[c]).join(", ")}` : "Colourless";
  const tint = (angle = 135) => {
    const one = colours[0];
    const stops = colours.length === 1 ? [token("tint", one), token("tint", one, "-deep")]
      : colours.length === 2 ? colours.map((c) => token("tint", c))
        : colours.length === 3 ? colours.map((c, i) => `${token("tint", c)} ${["0%", "55%", "100%"][i]}`)
          : ["var(--tint-multi)", "var(--tint-multi)"];
    return `linear-gradient(${angle}deg, ${stops.join(", ")})`;
  };
  const art = colours.length >= 3 ? "var(--art-multi)" : token("art", colours[0]);
  const bar = (cls) => el("span", { class: cls, "aria-hidden": "true", style: `--deck-stripe: ${stripeImage}` });
  return {
    colours, label, art, tint,
    pips(size = 20, { overArt = false, cls = "" } = {}) {
      const step = PIP_SIZES[size] || "md";
      return el("span", { class: ["id-pips", `id-pips-${step}`, overArt ? "is-over-art" : "", cls].filter(Boolean).join(" "),
        role: "img", "aria-label": label },
      colours.map((c) => el("span", { class: `id-pip id-pip-${c.toLowerCase()}`, text: c })));
    },
    stripe: (thin = false) => bar(thin ? "deck-stripe is-thin" : "deck-stripe"),
    swatch: () => bar("deck-swatch"),
    vars: (angle = 135) => `--deck-stripe: ${stripeImage}; --deck-tint: ${tint(angle)}; --deck-art: ${art}`,
  };
}
