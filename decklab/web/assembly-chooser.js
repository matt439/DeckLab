/* One packing chooser moves between a rail and a sheet; selections and previews keep their existing model. */
"use strict";

const packingChoosers = new Set();

function packChooserHere(view) {
  return !view.chooserState?.disposed && assemblyActive(view) && seesHomeInventory(state.may);
}

function packChooserCanChange(view, node) {
  return packChooserHere(view) && node.isConnected && view.chooser.contains(node) && !view.saving && !view.reviewing;
}

function packChooserMove(node, parent) {
  node.remove();
  if (parent) parent.append(node);
}

function packChooserScroller(view) { return view.chooserState?.sheet?.body || view.chooser; }

/** Capture the control focused NOW, including on a late normalized-preview redraw. */
function packChooserBeforeDraw(view) {
  const ctx = view.chooserState, active = document.activeElement;
  if (!ctx) return null;
  for (const group of view.picks.querySelectorAll("details")) ctx.groups.set(group.getAttribute("data-pack-group"), group.open);
  return { scroll: ctx.sheet || ctx.wide ? packChooserScroller(view).scrollTop || 0 : ctx.scroll, node: active,
    control: view.chooser.contains(active) ? active.getAttribute("data-pack-control") : null,
    id: view.chooser.contains(active) ? active.getAttribute("data-pack-id") : null };
}

/** A rail may start below its sticky top. Reveal within the part actually visible after layout/anchoring. */
function packChooserReveal(view, target) {
  const ctx = view.chooserState, id = target.getAttribute("data-pack-id"), control = target.getAttribute("data-pack-control");
  const current = () => packChooserHere(view) && view.chooserState === ctx && ctx.wide && !ctx.sheet
    && !view.saving && !view.reviewing && !document.querySelector("dialog[open]")
    && !view.chooserRail.hidden && !target.disabled && target.isConnected && view.chooser.contains(target) && document.activeElement === target
    && target.getAttribute("data-pack-id") === id && target.getAttribute("data-pack-control") === control;
  const reveal = () => {
    if (!current()) return;
    const bounds = () => {
      const field = target.getBoundingClientRect(), rail = view.chooser.getBoundingClientRect(), vv = window.visualViewport;
      let top = Number.isFinite(vv?.offsetTop) ? vv.offsetTop : 0;
      let bottom = top + (vv?.height > 0 ? vv.height : window.innerHeight);
      const overlaps = rect => rect && rect.right > field.left && rect.left < field.right && rect.height > 0;
      const header = document.querySelector(".topbar")?.getBoundingClientRect();
      if (overlaps(header) && header.top <= top && header.bottom > top) top = header.bottom;
      const bar = view.bar?.node?.isConnected ? view.bar.node.getBoundingClientRect() : null;
      if (overlaps(bar) && bar.top > top && bar.top < bottom && bar.bottom > top) bottom = bar.top;
      return { field, top: Math.max(top, rail.top) + 8, bottom: Math.min(bottom, rail.bottom) - 8 };
    };
    let visible = bounds();
    if (!(visible.field.height > 0)) return;
    let aligned = false;
    const fits = () => visible.bottom - visible.top >= visible.field.height;
    const align = () => {
      if (aligned || !current()) return false;
      aligned = true;
      view.chooser.scrollIntoView({ block: "start" });
      if (!current()) return false;
      visible = bounds();
      return fits();
    };
    if (visible.bottom - visible.top < visible.field.height) {
      if (!align()) return;
    }
    const scroll = () => {
      if (!current()) return;
      const delta = visible.field.top < visible.top ? visible.field.top - visible.top
        : visible.field.bottom > visible.bottom ? visible.field.bottom - visible.bottom : 0;
      if (delta) view.chooser.scrollTop = Math.max(0, (view.chooser.scrollTop || 0) + delta);
      visible = bounds();
    };
    scroll();
    // A short rail or an endpoint can clamp local scrolling. Make one outer alignment attempt.
    if ((visible.field.top < visible.top || visible.field.bottom > visible.bottom) && align()) scroll();
  };
  if (!current()) return;
  reveal();
  // Preview rendering/native dialog close may move the page after synchronous focus restoration.
  requestAnimationFrame(reveal);
}

function packChooserFocus(view, saved) {
  if (!packChooserHere(view)) return;
  const target = saved?.control ? [...view.chooser.querySelectorAll("[data-pack-control]")].find(node =>
    node.getAttribute("data-pack-control") === saved.control && node.getAttribute("data-pack-id") === saved.id && !node.disabled) : null;
  const fallback = view.chooserState.sheet?.heading || view.chooserHeading;
  if (!target) { fallback.focus(); return; }
  for (let node = target.parentNode; node && node !== view.chooser; node = node.parentNode) {
    if (node.tagName === "DETAILS" || node.tag === "details") node.open = true;
  }
  target.focus({ preventScroll: true });
  if (view.chooserState.wide && !view.chooserState.sheet) packChooserReveal(view, target);
  else target.scrollIntoView({ block: "nearest" });
}

function packChooserAfterDraw(view, saved) {
  const ctx = view.chooserState;
  if (!ctx) return;
  for (const group of view.picks.querySelectorAll("details")) {
    const key = group.getAttribute("data-pack-group");
    if (ctx.groups.has(key)) group.open = ctx.groups.get(key);
  }
  packChooserSync(view);
  if (!saved || !packChooserHere(view)) return;
  packChooserScroller(view).scrollTop = saved.scroll;
  if (saved.control) packChooserFocus(view, saved);
}

/** The chooser freezes wherever it is mounted; closing the sheet remains available navigation. */
function packChooserSync(view) {
  const ctx = view.chooserState;
  if (!ctx || ctx.disposed) return;
  const count = view.selected.length, blocked = Boolean(view.saving || view.reviewing);
  view.chooserCount.textContent = count ? ` · ${count} chosen` : "";
  view.chooserLaunch.textContent = count ? `Decks · ${count} chosen` : "Decks";
  view.chooserLaunch.disabled = blocked;
  view.chooserEmpty.hidden = Boolean(view.choices.length);
  view.chooserDismiss.textContent = count ? "Show the plan" : "Close";
  view.chooserDismiss.setAttribute("class", `btn pack-chooser-dismiss${count ? " btn-primary pack-show-plan" : ""}`);
  if (ctx.sheet) ctx.sheet.heading.textContent = count ? `Decks · ${count} chosen` : "Decks";
  for (const node of ["button", "input", "select"].flatMap(tag => [...view.chooser.querySelectorAll(tag)])) {
    if (blocked) { if (!ctx.frozen.has(node)) ctx.frozen.set(node, node.disabled); node.disabled = true; }
    else if (ctx.frozen.has(node)) node.disabled = ctx.frozen.get(node);
  }
  if (!blocked) ctx.frozen.clear();
}

/** Rescue original nodes before a programmatic native close; old deferred onClose cannot reclaim them. */
function packChooserClose(view, focus = true) {
  const ctx = view.chooserState, sheet = ctx?.sheet;
  if (!sheet) return;
  ctx.scroll = sheet.body.scrollTop || 0;
  ctx.sheet = null;
  packChooserMove(view.chooser, ctx.wide && !ctx.disposed ? view.chooserRail : null);
  packChooserMove(view.message, view.messageSlot);
  view.chooserLaunch.setAttribute("aria-expanded", "false");
  sheet.close();
  if (focus && packChooserHere(view) && !ctx.wide) view.chooserLaunch.focus();
}

function packRevealChooser(view) {
  const ctx = view.chooserState;
  if (!ctx || !packChooserHere(view) || view.saving || view.reviewing) return;
  if (ctx.wide) { packChooserFocus(view, null); return; }
  if (ctx.sheet && !ctx.sheet.closed) { ctx.sheet.heading.focus(); return; }
  let sheet;
  sheet = openSheet("Decks", { onClose: () => {
    if (ctx.sheet !== sheet) return;
    ctx.scroll = sheet.body.scrollTop || 0;
    ctx.sheet = null;
    // Native header/Back closes remove the dialog before this callback.
    packChooserMove(view.chooser, ctx.wide && !ctx.disposed ? view.chooserRail : null);
    packChooserMove(view.message, view.messageSlot);
    view.chooserLaunch.setAttribute("aria-expanded", "false");
    if (packChooserHere(view) && !ctx.wide) view.chooserLaunch.focus();
  } });
  ctx.sheet = sheet;
  sheet.dialog.classList.add("pack-decks-sheet");
  sheet.heading.setAttribute("tabindex", "-1");
  packChooserMove(view.message, sheet.body);
  packChooserMove(view.chooser, sheet.body);
  packChooserMove(view.chooserDismiss, sheet.foot);
  sheet.body.scrollTop = ctx.scroll;
  view.chooserLaunch.setAttribute("aria-expanded", "true");
  packChooserSync(view);
  sheet.heading.focus();
}

function packDisposeChooser(view) {
  const ctx = view.chooserState;
  if (!ctx || ctx.disposed) return;
  ctx.disposed = true;
  ctx.media.removeEventListener?.("change", ctx.change);
  ctx.media.removeListener?.(ctx.change);
  packChooserClose(view, false);
  packingChoosers.delete(view);
}

function closePackingChoosers() { for (const view of [...packingChoosers]) packDisposeChooser(view); }

function packInitChooser(view) {
  closePackingChoosers();
  const media = window.matchMedia("(min-width: 1000px)");
  const ctx = view.chooserState = { media, wide: media.matches, sheet: null, scroll: 0,
    groups: new Map(), frozen: new Map(), disposed: false };
  view.chooserDismiss = el("button", { type: "button", class: "btn pack-chooser-dismiss", text: "Close",
    onclick: () => { if (packChooserHere(view) && ctx.sheet) packChooserClose(view); } });
  ctx.change = () => {
    if (!packChooserHere(view)) { packDisposeChooser(view); return; }
    const wide = media.matches;
    if (wide === ctx.wide) return;
    const saved = packChooserBeforeDraw(view), active = document.activeElement;
    const inside = view.chooser.contains(active) || active === view.chooserLaunch || Boolean(ctx.sheet?.dialog.contains(active));
    ctx.wide = wide;
    ctx.scroll = saved?.scroll || 0;
    packChooserClose(view, false);
    packChooserMove(view.chooser, wide ? view.chooserRail : null);
    if (wide) view.chooser.scrollTop = ctx.scroll;
    view.chooserLaunch.hidden = wide;
    view.chooserRail.hidden = !wide;
    view.chooserSlot.hidden = !wide;
    if (inside) {
      if (wide) packChooserFocus(view, saved);
      else view.chooserLaunch.focus();
    }
  };
  if (media.addEventListener) media.addEventListener("change", ctx.change);
  else media.addListener?.(ctx.change);
  packingChoosers.add(view);
  view.chooserLaunch.hidden = ctx.wide;
  view.chooserRail.hidden = !ctx.wide;
  view.chooserSlot.hidden = !ctx.wide;
  packChooserMove(view.chooser, ctx.wide ? view.chooserRail : null);
  packChooserSync(view);
}
