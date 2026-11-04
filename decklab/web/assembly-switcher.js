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
  view.viewerPanel = null;
}

/** The tile's own tick for a viewer entry, found afresh by its shared id: a re-render makes new tiles. */
function packViewerTick(view, entry) {
  return (view.ticks || []).find(t => t.tile && t.id === entry.tickId) || null;
}

/** A tile tick's own guards, so the big view shows when its press would do nothing. */
function packViewerMay(view) {
  return Boolean(assemblyActive(view) && packProgressOwner(view) && !view.saving && !view.previewing);
}

function packViewerNote(view, tick) {
  const p = view.progress;
  if (!tick) return "This card's task is no longer in the plan.";
  if (view.saving) return "Saving the decks…";
  if (view.previewing) return "Working out the plan…";
  if (p?.error) return p.pending.size ? "These ticks haven't been saved. Close this view to retry."
    : p.loaded ? "Shared ticks couldn't be checked." : "Shared ticks couldn't load, so this card may be ticked already.";
  return p?.loaded ? "" : "Loading shared ticks…";
}

/** The big view's tick and printing for the card shown: they hold no state of their own. A press clicks the
 * current tile's tick (the same id, guards and shared queue), and everything is drawn from the plan's ticks and
 * picks here, which runs with every tick, poll, Clear, Undo, save and re-render (packProgress). */
function packViewerPanel(view) {
  const panel = { entry: null, source: null, printing: null };
  panel.tick = el("button", { type: "button", class: "viewer-btn pack-viewer-tick", "aria-pressed": "false", onclick: () => {
    const tick = view.viewerPanel === panel && panel.entry && packViewerMay(view) ? packViewerTick(view, panel.entry) : null;
    tick?.node.click();
  } });
  panel.slot = el("div", { class: "pack-viewer-printing" });
  panel.note = el("p", { class: "pack-viewer-note", role: "status", hidden: true });
  panel.node = el("div", { class: "pack-viewer-controls" }, panel.tick, panel.slot, panel.note);
  return panel;
}

function packViewerPrinting(view, panel, entry) {
  const source = entry.printing ? packPrintingListed(view, entry.printing.deck.id, entry.printing.name) : null;
  if (source !== panel.source) {
    panel.source = source;
    panel.printing = source ? packPrintingMake(view, source.deck, source.name, source.qty) : null;
    clear(panel.slot);
    if (panel.printing) panel.slot.append(panel.printing.node);
  } else if (panel.printing) packPrintingDraw(view, panel.printing);
  panel.slot.hidden = !panel.printing;
}

function packViewerSync(view) {
  const panel = view.viewerPanel, entry = panel?.entry;
  if (!entry) return;
  const tick = packViewerTick(view, entry), may = packViewerMay(view), done = Boolean(tick?.done);
  packViewerPrinting(view, panel, entry);
  const select = panel.printing?.select, focus = document.activeElement;
  if ((focus === panel.tick && !(tick && may)) || (focus === select && !may)) viewerDom?.close.focus({ preventScroll: true });
  panel.tick.disabled = !tick || !may;
  if (select) select.disabled = !may;
  panel.tick.setAttribute("aria-pressed", String(done));
  panel.tick.setAttribute("aria-label", tick?.node.getAttribute("aria-label") || `${entry.card.name}: done`);
  panel.tick.textContent = !tick ? "Not in this plan" : `${done ? "Ticked" : "Tick off"}${tick.count > 1 ? ` ×${tick.count}` : ""}`;
  const note = packViewerNote(view, tick);
  if (panel.note.textContent !== note) panel.note.textContent = note;
  panel.note.hidden = !note;
}

/** What one card's item shows while it's the card in the viewer. */
function packViewerShow(view, panel, entry) {
  panel.entry = entry.tickId ? entry : null;
  if (!panel.entry) return [];
  packViewerSync(view);
  return [panel.node];
}

/** Fresh focus may land far down a wide plan; delayed work only reveals the still-owned focused node. */
function packSwitcherFocus(view, target) {
  const ctx = view.switcher, data = view.data;
  const current = () => packSwitcherHere(view) && view.switcher === ctx && view.data === data && target?.isConnected
    && !view.previewing && !view.saving && !view.reviewing && !document.querySelector("dialog[open]")
    && (ctx.panels.some(p => !p.node.hidden && p.node.contains(target)) || (!ctx.nav?.hidden && ctx.nav?.contains(target)));
  if (!current()) return;
  packExpandStep(view, target);
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

/** Reveal an original current task by its exact participant node; never infer ownership from a name. */
function packSwitcherRevealTask(view, target) {
  if (!packSwitcherHere(view) || view.previewing || view.saving || view.reviewing || document.querySelector("dialog[open]")
      || !target?.isConnected || !view.results.contains(target)) return false;
  const ctx = view.switcher, panel = ctx.panels.find(p => p.node.contains(target) && view.data.decks.includes(p.deck)
    && p.node.getAttribute("data-pack-deck") === `${p.deck.id}:${p.deck.version}`);
  if (!panel) return false;
  if (!ctx.wide) { ctx.active = packParticipantKey(panel.deck); packSwitcherProject(view); }
  packSwitcherFocus(view, target);
  return document.activeElement === target;
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
  if (!entry || !panel || panel.node.hidden || !packStepTargetShown(view, trigger)) return;
  const ids = new Map((view.ticks || []).filter(t => t.tile).map(t => [t.tile, t.id]));
  const printings = new Map((view.printingControls || []).map(c => [c.node.closest(".card-tile"), c]));
  const viewerPanel = view.viewerPanel = packViewerPanel(view);
  const reply = openCardViewer(entries.map(item => {
    const shown = { ...item, tickId: ids.get(item.tile) || null, printing: printings.get(item.tile) || null };
    return { card: item.card, caption: item.caption, status: () => packViewerShow(view, viewerPanel, shown) };
  }), index, { trigger });
  packViewerWatch(view, entry, reply);
}

function packRegisterCard(view, tile, card, caption) {
  const trigger = tile.querySelector(".card-tile-open");
  if (!card || !trigger) return;
  trigger.setAttribute("aria-haspopup", "dialog");
  viewerItem(trigger, card, "packing", caption);
  view.packViewerEntries ||= [];
  view.packViewerEntries.push({ data: view.data, trigger, tile, card, caption });
}

function packSwitcherBeforeRender(view) {
  const ctx = view.switcher, active = document.activeElement;
  if (!ctx) return null;
  const panel = ctx.panels.find(p => p.node.contains(active));
  const nav = ctx.panels.find(p => p.button === active);
  view.packViewerEntries = [];
  view.printingControls = [];
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
  packDisposeSteps(view);
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
    packStepsResize(view, wide);
    if (navPanel && wide && !document.querySelector("dialog[open]")) {
      packSwitcherFocus(view, navPanel.heading);
    } else if (panel && !panel.node.hidden && panel.node.contains(focus) && document.activeElement === focus) {
      // Density changes move the same focused summary/task beneath different headers and bars.
      packSwitcherFocus(view, focus);
    }
  };
  if (media.addEventListener) media.addEventListener("change", ctx.change); else media.addListener?.(ctx.change);
  packingSwitchers.add(view);
}
