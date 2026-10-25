/* Casual plan switching keeps one complete attached plan and its original card/tick controls. */
"use strict";

const packingSwitchers = new Set();
const packParticipantKey = deck => JSON.stringify([deck.id, deck.version]);

function packSwitcherHere(view) {
  return Boolean(view.switcher && !view.switcher.disposed && assemblyActive(view) && seesHomeInventory(state.may));
}

function packSwitcherColours(colors) {
  return Array.isArray(colors) && colors.length <= 5 && new Set(colors).size === colors.length
    && Array.from(colors).every(c => typeof c === "string" && "WUBRG".includes(c) && c.length === 1)
    ? deckColourPieces(colors) : null;
}

function packViewerCurrent(view, entry) {
  return packSwitcherHere(view) && entry.data === view.data && view.packViewerEntries.includes(entry)
    && entry.trigger.isConnected && view.results.contains(entry.trigger);
}

function packViewerForget(view, expected = view.packingViewer) {
  const entry = view.packingViewer;
  if (!entry || entry !== expected) return;
  entry.dialog?.removeEventListener("close", entry.capture, true);
  entry.dialog?.removeEventListener("close", entry.close);
  view.packingViewer = null;
}

/** Fresh focus may land far down a wide plan; delayed work only reveals the still-owned focused node. */
function packSwitcherFocus(view, target) {
  const ctx = view.switcher, data = view.data;
  const current = () => packSwitcherHere(view) && view.switcher === ctx && view.data === data && target?.isConnected
    && !view.previewing && !view.saving && !view.reviewing && !document.querySelector("dialog[open]")
    && (ctx.panels.some(p => !p.node.hidden && p.node.contains(target)) || (!ctx.nav?.hidden && ctx.nav?.contains(target)));
  if (!current()) return;
  if (document.activeElement !== target) target.focus({ preventScroll: true });
  const reveal = () => {
    if (!current() || document.activeElement !== target) return;
    target.scrollIntoView({ block: "start" });
    const rect = target.getBoundingClientRect(), vv = window.visualViewport;
    let top = vv?.offsetTop || 0, bottom = top + (vv?.height || window.innerHeight);
    const overlaps = r => r && r.height > 0 && r.right > rect.left && r.left < rect.right;
    const header = document.querySelector(".topbar")?.getBoundingClientRect();
    if (overlaps(header) && header.top <= top && header.bottom > top) top = header.bottom;
    const bar = view.bar?.node?.isConnected ? view.bar.node.getBoundingClientRect() : null;
    if (overlaps(bar) && bar.top > top && bar.top < bottom) bottom = bar.top;
    const delta = rect.top < top + 8 ? rect.top - top - 8 : rect.bottom > bottom - 8 ? rect.bottom - bottom + 8 : 0;
    if (delta) window.scrollBy({ top: delta, behavior: "auto" });
  };
  reveal(); requestAnimationFrame(reveal);
}

/** Keep the shared viewer's close focus when possible; repair only the exact owned current plan. */
function packViewerWatch(view, item, reply) {
  const dialog = [...document.querySelectorAll("dialog[open]")].find(node => node.matches(".viewer"));
  if (!dialog || !reply) return;
  packViewerForget(view);
  const entry = { ...item, reply, dialog, ownedClose: false };
  view.packingViewer = entry;
  const mayRepair = () => packSwitcherHere(view) && view.data === entry.data && view.packingViewer === entry
    && !view.previewing && !view.saving && !view.reviewing
    && ![...document.querySelectorAll("dialog[open]")].some(node => node !== dialog);
  const ownsFocus = () => document.activeElement === entry.trigger || document.activeElement === document.body
    || dialog.contains(document.activeElement);
  entry.capture = () => { entry.ownedClose = mayRepair() && viewerState === reply && ownsFocus(); };
  entry.close = () => {
    const repair = entry.ownedClose && mayRepair() && ownsFocus();
    packViewerForget(view, entry);
    if (!repair) return;
    const ctx = view.switcher, panel = ctx.panels.find(p => p.node.contains(entry.trigger));
    if (!ctx.wide && panel) { ctx.active = packParticipantKey(panel.deck); packSwitcherProject(view); }
    const target = entry.trigger.isConnected && panel && !panel.node.hidden ? entry.trigger
      : ctx.panels.find(p => packParticipantKey(p.deck) === ctx.active)?.heading;
    if (target?.isConnected) packSwitcherFocus(view, target);
  };
  dialog.addEventListener("close", entry.capture, true); // before the shared viewerClosed clears viewerState
  dialog.addEventListener("close", entry.close);         // after its normal original-trigger focus
}

/** Assembly's explicit group includes hidden plan panels, preserving task order and duplicate cards. */
function packOpenCard(view, trigger) {
  if (!packSwitcherHere(view) || view.previewing || view.saving || view.reviewing || document.querySelector("dialog[open]")) return;
  if (view.packingViewer) return; // native close may have removed open before its close event settles
  const entries = view.packViewerEntries.filter(entry => packViewerCurrent(view, entry));
  const index = entries.findIndex(entry => entry.trigger === trigger);
  const entry = entries[index];
  const panel = view.switcher.panels.find(p => p.node.contains(trigger));
  if (!entry || !panel || panel.node.hidden) return;
  const reply = openCardViewer(entries.map(({card, caption}) => ({card, caption})), index, { trigger });
  packViewerWatch(view, entry, reply);
}

function packRegisterCard(view, tile, card, caption) {
  const trigger = tile.querySelector(".card-tile-open");
  if (!card || !trigger) return;
  trigger.setAttribute("aria-haspopup", "dialog");
  viewerItem(trigger, card, "packing", caption);
  view.packViewerEntries ||= [];
  view.packViewerEntries.push({ data: view.data, trigger, card, caption });
}

function packSwitcherBeforeRender(view) {
  const ctx = view.switcher, active = document.activeElement;
  if (!ctx) return null;
  const panel = ctx.panels.find(p => p.node.contains(active));
  const nav = ctx.panels.find(p => p.button === active);
  view.packViewerEntries = [];
  return { nav: nav ? packParticipantKey(nav.deck) : null, panel: panel ? packParticipantKey(panel.deck) : null };
}

/** Hide presentation only: every card task remains in wirePackTicks, bulk scope and completion. */
function packSwitcherProject(view) {
  const ctx = view.switcher;
  if (!ctx || !packSwitcherHere(view)) return;
  if (!ctx.panels.length) ctx.active = null;
  else if (!ctx.panels.some(p => packParticipantKey(p.deck) === ctx.active)) {
    const id = ctx.active ? JSON.parse(ctx.active)[0] : null;
    ctx.active = packParticipantKey(ctx.panels.find(p => p.deck.id === id)?.deck || ctx.panels[0]?.deck || {id:null,version:null});
  }
  if (ctx.nav) ctx.nav.hidden = ctx.wide || ctx.panels.length < 2;
  for (const panel of ctx.panels) {
    const selected = packParticipantKey(panel.deck) === ctx.active;
    panel.node.hidden = !ctx.wide && !selected;
    panel.button?.setAttribute("aria-pressed", String(selected));
  }
}

function packAttachSwitcher(view, data, panels) {
  const ctx = view.switcher;
  ctx.panels = panels.map(({deck, node}) => ({deck, node, heading: node.querySelector("h2")}));
  ctx.nav = el("div", { class: "pack-deck-switcher", role: "group", "aria-label": "Deck plans" });
  for (const panel of ctx.panels) {
    panel.heading.setAttribute("tabindex", "-1");
    const colours = packSwitcherColours(panel.deck.colors);
    panel.button = el("button", { type: "button", class: "pack-deck-choice", "aria-pressed": "false",
      style: colours ? colours.vars(90) : null, onclick: () => {
        if (!packSwitcherHere(view) || view.data !== data || !ctx.panels.includes(panel) || !panel.button.isConnected
            || ctx.wide || view.previewing || view.saving || view.reviewing || document.querySelector("dialog[open]")) return;
        ctx.active = packParticipantKey(panel.deck); packSwitcherProject(view);
      } }, colours?.stripe(), el("strong", { text: panel.deck.title }),
      el("span", { class: "pack-deck-choice-list", text: listName(panel.deck.version) }), colours?.pips(16));
    ctx.nav.append(panel.button);
  }
  packSwitcherProject(view);
  return ctx.nav;
}

function packSwitcherAfterRender(view, saved) {
  const ctx = view.switcher;
  packSwitcherProject(view);
  if (!saved || !packSwitcherHere(view) || document.querySelector("dialog[open]")) return;
  const wanted = saved.nav || (ctx.wide ? saved.panel : null);
  const panel = (wanted ? ctx.panels.find(p => packParticipantKey(p.deck) === wanted) : null)
    || ctx.panels.find(p => packParticipantKey(p.deck) === ctx.active);
  if (saved.nav && !ctx.wide && panel?.button.isConnected && !ctx.nav.hidden) packSwitcherFocus(view, panel.button);
  else if (saved.panel && panel?.heading.isConnected) packSwitcherFocus(view, panel.heading);
}

function packDisposeSwitcher(view) {
  const ctx = view.switcher;
  if (!ctx || ctx.disposed) return;
  ctx.disposed = true;
  ctx.media.removeEventListener?.("change", ctx.change); ctx.media.removeListener?.(ctx.change);
  packViewerForget(view); packingSwitchers.delete(view);
}

function closePackingSwitchers() { for (const view of [...packingSwitchers]) packDisposeSwitcher(view); }

function packInitSwitcher(view) {
  closePackingSwitchers();
  const media = window.matchMedia("(min-width: 1000px)");
  const ctx = view.switcher = { media, wide: media.matches, disposed: false, panels: [], active: null, nav: null };
  view.packViewerEntries = [];
  ctx.change = () => {
    if (!packSwitcherHere(view)) { packDisposeSwitcher(view); return; }
    const wide = media.matches;
    if (wide === ctx.wide) return;
    const focus = document.activeElement, navPanel = ctx.panels.find(p => p.button === focus);
    const entry = view.packingViewer;
    const returning = entry && entry.data === view.data && entry.dialog?.getAttribute("open") !== null
      ? ctx.panels.find(p => p.node.contains(entry.trigger)) : null;
    const panel = returning || ctx.panels.find(p => p.node.contains(focus));
    if (!wide && panel) ctx.active = packParticipantKey(panel.deck);
    ctx.wide = wide; packSwitcherProject(view);
    if (navPanel && wide && !document.querySelector("dialog[open]")) {
      packSwitcherFocus(view, navPanel.heading);
    }
  };
  if (media.addEventListener) media.addEventListener("change", ctx.change); else media.addListener?.(ctx.change);
  packingSwitchers.add(view);
}
