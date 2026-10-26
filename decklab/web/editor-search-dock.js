/* The Editor's casual Add dock. One retained search tree, a nonmodal region,
 * explicit dismissal/history and measured clearance above the existing Save bar.
 * Loaded after editor-search-quantity.js; no model, payload or Save hooks. */
"use strict";

function editorSearchDockWanted(ed = editor) {
  return Boolean(ed && (ed.quick || !window.matchMedia("(min-width: 1000px)").matches));
}

/** Structural ownership remains valid while cleanup is suspending/leaving the view. */
function editorSearchDockCurrent(dock) {
  const ed = dock?.ed;
  return Boolean(ed && editor === ed && ed.dom?.searchDock === dock && !dock.disposed
    && dock.token === routeToken && dock.profile === state.profile?.id && dock.profile === ed.profile
    && dock.id === ed.id && dock.version === ed.version && dock.ac === ed.ac && !dock.ac.cancelled
    && dock.page === ed.dom.page && dock.page?.isConnected && dock.page.contains(dock.root)
    && dock.part === ed.dom.addPart && dock.root.contains(dock.part) && dock.part.contains(dock.ac.wrap)
    && dock.bar === ed.dom.bar && dock.page.contains(dock.bar) && dock.page.contains(dock.spacer)
    && dock.spacer.parentNode === dock.bar.parentNode && dock.spacer.nextSibling === dock.bar
    && (!dock.panes || ed.dom.panes === dock.panes && dock.panes.hash === location.hash));
}

function editorSearchDocked(ac) {
  const dock = ac?.owner?.dom?.searchDock;
  return Boolean(editorSearchDockCurrent(dock) && dock.ac === ac && dock.fixed && !dock.root.hidden);
}

function editorSearchDockHidden(target) {
  for (let node = target; node; node = node.parentNode) if (node.hidden) return true;
  return false;
}

function invalidateEditorSearchDockFrame(dock) {
  ++dock.generation;
  if (dock.frame && typeof cancelAnimationFrame === "function") cancelAnimationFrame(dock.frame);
  if (dock.revealFrame && typeof cancelAnimationFrame === "function") cancelAnimationFrame(dock.revealFrame);
  if (dock.outsideFrame && typeof cancelAnimationFrame === "function") cancelAnimationFrame(dock.outsideFrame);
  dock.frame = 0; dock.revealFrame = 0; dock.outsideFrame = 0;
}

/** Hiding is reversible; the permanent cancel function is reserved for disposal. */
function suspendEditorSearchDock(dock) {
  const ac = dock.ac;
  ++ac.seq;
  clearTimeout(ac.timer); clearTimeout(ac.addedTimer);
  ac.pickFirst = false; ac.pickCount = null;
  if (ac.morePending) { ac.page = Math.max(1, ac.page - 1); resetSearchMore(ac); }
  clearAdded(ac);
  ac.dockSuspended = true;
  if (editorSearchDockCurrent(dock)) {
    document.body.classList.remove("is-searching", "keyboard-up");
    if (dock.ed.dom.addPart?.style) dock.ed.dom.addPart.style.minHeight = "";
  }
  invalidateEditorSearchDockFrame(dock);
}

function mountEditorSearchDock(ed = editor) {
  if (!ed?.dom?.page?.isConnected || ed.quick || noOwnedList() || ed.dom.searchDock) return;
  createEditorSearchDock(ed, ed.dom.panes?.search);
  projectEditorPanes(ed.dom.panes);
}

/** Full Editor keeps its original pane root; Quick creates its one search lazily. */
function createEditorSearchDock(ed, root = null) {
  if (!root) {
    root = el("section", { class: "edit-search-pane", id: "edit-pane-add" });
    ed.dom.addPart = addPart(() => closeEditorSearchDock(ed.dom.searchDock, { paste: true }));
    root.append(ed.dom.addPart);
    ed.dom.bar.parentNode.insertBefore(root, ed.dom.bar);
  }
  const dock = { ed, root, part: ed.dom.addPart, bar: ed.dom.bar, ac: ed.ac, page: ed.dom.page, panes: ed.dom.panes || null,
    id: ed.id, version: ed.version, token: routeToken, profile: ed.profile,
    open: false, fixed: false, casual: editorSearchDockWanted(ed), disposed: false,
    generation: 0, frame: 0, entry: null, trigger: null, sheets: new Map() };
  ed.dom.searchDock = dock;
  dock.spacer = el("div", { class: "edit-dock-clearance", "aria-hidden": "true", hidden: true });
  dock.bar.parentNode.insertBefore(dock.spacer, dock.bar);
  if (!ed.quick && dock.casual && ed.side === "add") ed.sideFolded = true;
  const title = root.querySelector("#h-editor-add") || el("h2", { id: "h-editor-add", class: "edit-pane-heading", tabindex: "-1", text: "Add cards" });
  title.remove(); // Retain the original pane heading and its exact resize-focus target.
  dock.close = el("button", { type: "button", class: "btn btn-quiet", text: "Done", "aria-label": "Close Add cards",
    onclick: () => closeEditorSearchDock(dock) });
  dock.head = el("div", { class: "edit-dock-head" }, title, dock.close);
  root.replaceChildren(dock.head, ...Array.from(root.children));
  root.addEventListener("keydown", event => {
    if (event.key !== "Escape" || editorKeyIgnored(event) || event.repeat || event.ctrlKey || event.metaKey
      || event.altKey || event.shiftKey || keyboardMenuOpen() || !editorSearchDockCurrent(dock) || !dock.fixed
      || document.querySelector("dialog[open]") || !root.contains(event.target) || !root.contains(document.activeElement)) return;
    event.preventDefault(); closeEditorSearchDock(dock);
  });
  if (typeof ResizeObserver === "function") {
    dock.observer = new ResizeObserver(() => queueEditorSearchDockFit(dock));
    dock.observer.observe(ed.dom.bar);
  }
  projectEditorSearchDock(dock);
  if (ed.quick) registerEditorKeyboardHelp(ed); // The retained Quick input exists only after this lazy mount.
  return dock;
}

/** Projection changes neither focus nor history, including when the window crosses 1000px. */
function projectEditorSearchDock(dock = editor?.dom?.searchDock) {
  if (!editorSearchDockCurrent(dock)) return;
  const ed = dock.ed, casual = editorSearchDockWanted(ed);
  if (casual !== dock.casual) {
    invalidateEditorSearchDockFrame(dock);
    const active = document.activeElement;
    const viewerReturn = typeof viewerState !== "undefined" && viewerState && viewerDom?.dialog?.contains(active)
      && dock.root.contains(viewerState.trigger);
    if (casual && ed.tab === "cards" && (dock.root.contains(active) || viewerReturn)) {
      // Preserve the exact focused/inspected pane on resize without manufacturing history.
      dock.open = true;
      dock.trigger = ed.dom.barParts?.addCards || dock.trigger;
    }
    dock.casual = casual;
  }
  const visible = !ed.leaving && ed.tab === "cards" && (!casual || dock.open && (!dock.panes || ed.side === "add"));
  const resuming = visible && dock.ac.dockSuspended;
  if (!visible && !dock.ac.dockSuspended) suspendEditorSearchDock(dock);
  else if (visible) dock.ac.dockSuspended = false;
  dock.fixed = visible && casual;
  dock.root.hidden = !visible;
  const query = parseQuery(dock.ac.input.value).q;
  if (resuming && !dock.ac.resultScope && (browsing(dock.ac) || query.length >= SEARCH_MIN)) {
    listMessage(dock.ac, query.length >= SEARCH_MIN
      ? "Search paused. Press Enter to look up and add an exact match, or edit the name."
      : "Search paused. Change a filter or type a card name to search again.");
  }
  dock.root.classList.toggle("edit-search-dock", dock.fixed);
  dock.close.hidden = !dock.fixed;
  if (dock.fixed) {
    dock.root.setAttribute("role", dock.panes ? "tabpanel" : "region");
    dock.root.setAttribute("aria-labelledby", dock.panes ? "edit-side-add" : "h-editor-add");
    // A fixed descendant still needs its retained ancestors attached and displayed.
    if (ed.dom.sideBody) {
      ed.sideFolded = false;
      ed.dom.sideBody.hidden = false;
      ed.dom.side.classList.remove("is-folded");
      ed.dom.sideFold.textContent = "Hide";
      ed.dom.sideFold.setAttribute("aria-expanded", "true");
    }
  } else if (dock.panes) {
    if (dock.panes.wide) dock.root.removeAttribute("role");
    else dock.root.setAttribute("role", "tabpanel");
    dock.root.setAttribute("aria-labelledby", dock.panes.wide ? "h-editor-add" : "edit-side-add");
  }
  const launcher = ed.dom.barParts?.addCards;
  if (launcher) {
    launcher.setAttribute("aria-controls", dock.root.id);
    launcher.setAttribute("aria-expanded", String(!dock.root.hidden));
  }
  document.body.classList.toggle("has-editor-search-dock", dock.fixed);
  dock.spacer.hidden = !dock.fixed;
  if (dock.fixed) queueEditorSearchDockFit(dock);
  else {
    invalidateEditorSearchDockFrame(dock);
    dock.outsideTarget = null;
    dock.spacer.style.height = "0px";
    for (const name of ["top", "left", "width", "height"]) dock.root.style[name] = "";
  }
}

function openEditorSearchDock() {
  const ed = editor;
  if (!editorKeyboardCurrent(ed) || ed.leaving || ed.asking || ed.saving || noOwnedList()
    || keyboardMenuOpen() || document.querySelector("dialog[open]")) return;
  let dock = ed.dom.searchDock;
  if (!dock) dock = createEditorSearchDock(ed, ed.dom.panes?.search);
  if (!editorSearchDockCurrent(dock)) return;
  if (ed.tab !== "cards") { ed.tab = "cards"; drawMain(); }
  if (!ed.quick) {
    ed.side = "add"; ed.sideFolded = false;
    local.set("editSide", "add"); drawSideTabs();
  }
  if (!dock.open) {
    const active = document.activeElement;
    dock.trigger = active && active !== document.body && active !== document.documentElement
      ? active : ed.dom.barParts?.addCards;
    dock.open = true;
    dock.entry = pushSheetEntry(() => closeEditorSearchDock(dock));
  }
  if (dock.panes) projectEditorPanes(dock.panes);
  else projectEditorSearchDock(dock);
  if (!editorSearchCurrent(dock.ac)) return;
  if (dock.ac.items.length && dock.ac.query === parseQuery(dock.ac.input.value).q
    && (!dock.ac.resultScope || dock.ac.resultScope === editorSearchScope(dock.ac))) drawOptions(dock.ac);
  else schedule(dock.ac, 0); // A cancelled first lookup resumes as a read, with no pending Add intent.
  dock.ac.input.focus({ preventScroll: true });
  if (dock.ac.input.select) dock.ac.input.select();
}

/** Release the dock's owned entry before the ordinary modal Paste takes it over. */
function editorSearchPaste() {
  const dock = editor?.dom?.searchDock;
  if (dock?.open) closeEditorSearchDock(dock, { paste: true });
  else if (editorSearchDockCurrent(dock)) openEditorSearchDockPaste(dock);
  else openPaste();
}

function openEditorSearchDockPaste(dock) {
  dock.pasteHandoff = true;
  try { openPaste(); } finally { dock.pasteHandoff = false; }
}

function closeEditorSearchDock(dock = editor?.dom?.searchDock, { focus = true, paste = false } = {}) {
  if (!dock || dock.disposed || !dock.open) return;
  const owned = editorSearchDockCurrent(dock), inside = dock.root.contains(document.activeElement);
  dock.open = false;
  suspendEditorSearchDock(dock);
  const entry = dock.entry; dock.entry = null;
  if (entry) dock.lastClosedDock = { token: entry.token, pos: entry.pos };
  if (entry && !owned) entry.fromHistory = true;
  releaseSheetEntry(entry);
  if (!owned) return;
  if (!dock.ed.quick && editorSearchDockWanted(dock.ed) && dock.ed.side === "add") dock.ed.sideFolded = true;
  document.body.classList.remove("is-searching", "keyboard-up");
  if (dock.panes) projectEditorPanes(dock.panes);
  else projectEditorSearchDock(dock);
  if (paste && !dock.ed.leaving && !dock.ed.saving && !dock.ed.asking && !document.querySelector("dialog[open]")) {
    openEditorSearchDockPaste(dock); return;
  }
  const trigger = dock.trigger;
  if (focus && inside && editorSearchDockWanted(dock.ed) && !dock.ed.leaving && !dock.ed.asking && !dock.ed.saving
    && !document.querySelector("dialog[open]") && trigger?.isConnected && !trigger.disabled
    && !editorSearchDockHidden(trigger) && typeof trigger.focus === "function") trigger.focus({ preventScroll: true });
}

/** Observe exact nested sheets without changing their shared modal lifecycle. */
function trackEditorSearchDockSheet(sheet) {
  const dock = editor?.dom?.searchDock, entry = sheet.entry;
  if (!editorSearchDockCurrent(dock) || (!dock.open && !dock.pasteHandoff) || !entry) return;
  dock.sheets.set(entry.token, { sheet, entry });
  sheet.dialog.addEventListener("close", () => {
    if (!sheet.closed || !entry.done) return;
    dock.sheets.delete(entry.token);
    dock.lastClosedSheet = { token: entry.token, pos: entry.pos };
    retireEditorSearchDockMark(dock, entry.token, entry.pos);
  }, { once: true });
}

/** A replacement editor owns this URL/position; an old transient cannot Back off it. */
function retireEditorSearchDockMark(dock, token, pos) {
  const takeover = dock.takeover, now = history.state;
  if (!takeover || !now || pos !== takeover.pos || now.sheet !== token || now.pos !== takeover.pos || location.hash !== takeover.hash
    || routeToken !== takeover.route || state.profile?.id !== takeover.profile) return;
  const { sheet, ...rest } = now;
  try { history.replaceState(rest, ""); } catch (error) { console.warn("The old search history mark could not be retired.", error); }
}

function takeOverEditorSearchDock(dock) {
  const ed = dock.ed;
  if (editor !== ed || ed.dom.searchDock !== dock || dock.ac !== ed.ac || dock.id !== ed.id || dock.version !== ed.version
    || dock.token !== routeToken || dock.profile !== ed.profile || dock.profile !== state.profile?.id
    || (!dock.entry && !dock.lastClosedDock && !dock.lastClosedSheet && !dock.sheets.size)) return;
  dock.takeover = { hash: location.hash, pos: entryPos(), route: routeToken, profile: dock.profile };
  if (dock.entry) {
    dock.entry.fromHistory = true;
    retireEditorSearchDockMark(dock, dock.entry.token, dock.entry.pos);
  }
  if (dock.lastClosedDock) retireEditorSearchDockMark(dock, dock.lastClosedDock.token, dock.lastClosedDock.pos);
  if (dock.lastClosedSheet) retireEditorSearchDockMark(dock, dock.lastClosedSheet.token, dock.lastClosedSheet.pos);
  for (const { sheet, entry } of dock.sheets.values()) {
    // Fallback/synchronous close may finish without dispatching a native close event.
    if (sheet.closed && entry.done) retireEditorSearchDockMark(dock, entry.token, entry.pos);
  }
}

/** A stale same-URL sheet position becomes this current editor's landed page entry. */
function editorSheetHistoryLanded(pos) {
  const ed = editor;
  if (!ed?.dom?.page?.isConnected || ed.entryToken !== routeToken || ed.profile !== state.profile?.id
    || ed.leaving || ed.asking || ed.saving || ed.undo || !Number.isFinite(pos)) return;
  if (location.hash === ed.entryHash || ed.mode === "edit" && location.hash === editHref(ed.id, ed.version)) ed.pos = pos;
}

function disposeEditorSearchDock(ed = editor, { takeover = false } = {}) {
  const dock = ed?.dom?.searchDock;
  if (!dock || dock.disposed) return;
  const owned = editorSearchDockCurrent(dock);
  if (takeover) takeOverEditorSearchDock(dock);
  dock.open = false;
  suspendEditorSearchDock(dock);
  dock.disposed = true;
  dock.observer?.disconnect();
  dock.spacer.remove();
  if (dock.entry && !owned) dock.entry.fromHistory = true;
  releaseSheetEntry(dock.entry); dock.entry = null;
  cancelEditorSearch(dock.ac);
  if (ed.quick) dock.root.remove();
  if (editor === ed) document.body.classList.remove("has-editor-search-dock", "is-searching", "keyboard-up");
}

function queueEditorSearchDockFit(dock = editor?.dom?.searchDock) {
  if (!editorSearchDockCurrent(dock) || !dock.fixed || dock.ed.leaving) return;
  const scope = editorSearchScope(dock.ac), hash = location.hash;
  if (dock.frame && dock.frameScope === scope && dock.frameHash === hash) return;
  if (dock.frame) invalidateEditorSearchDockFrame(dock);
  const generation = dock.generation;
  dock.frameScope = scope; dock.frameHash = hash;
  const frame = requestAnimationFrame(() => {
    if (dock.frame !== frame) return;
    dock.frame = 0;
    if (!editorSearchDockCurrent(dock) || !dock.fixed || dock.ed.leaving || generation !== dock.generation
      || scope !== editorSearchScope(dock.ac) || hash !== location.hash) return;
    fitEditorSearchDock(dock);
  });
  dock.frame = frame;
}

/** All measurements are CSS pixels in the same coordinate system as DOMRect. */
function fitEditorSearchDock(dock) {
  if (!editorSearchDockCurrent(dock) || !dock.fixed) return;
  const vv = window.visualViewport;
  const left = Number.isFinite(vv?.offsetLeft) ? Math.max(0, vv.offsetLeft) : 0;
  const width = Number.isFinite(vv?.width) && vv.width > 0 ? vv.width : window.innerWidth;
  let top = Number.isFinite(vv?.offsetTop) ? Math.max(0, vv.offsetTop) : 0;
  const viewportBottom = top + (Number.isFinite(vv?.height) && vv.height > 0 ? vv.height : window.innerHeight);
  let bottom = viewportBottom;
  const header = document.querySelector(".topbar")?.getBoundingClientRect();
  let bar = dock.bar.getBoundingClientRect();
  const overlap = rect => rect && rect.height > 0 && rect.right > left && rect.left < left + width;
  if (overlap(header) && header.bottom > top && header.top < bottom) top = Math.min(bottom, header.bottom);
  // Reserve the dock before remeasuring a short editor's moving sticky bar. This
  // also creates the real document range needed by the last focusable deck row.
  const bottomStyle = typeof getComputedStyle === "function" ? parseFloat(getComputedStyle(dock.bar).bottom) : NaN;
  const settledBottom = Math.min(viewportBottom, window.innerHeight - (Number.isFinite(bottomStyle) ? Math.max(0, bottomStyle) : 0));
  const available = Math.max(0, settledBottom - (bar?.height > 0 ? bar.height : 0) - top);
  const outside = editorSearchDockOutsideCurrent(dock, dock.outsideTarget) ? dock.outsideTarget.getBoundingClientRect() : null;
  const reserve = outside?.height > 0 && Number.isFinite(outside.height) ? Math.min(available, outside.height + 16) : 0;
  const budget = Math.max(0, Math.min(560, available - reserve));
  const clearance = `${Math.ceil(budget + reserve)}px`;
  if (dock.spacer.style.height !== clearance) dock.spacer.style.height = clearance;
  bar = dock.bar.getBoundingClientRect(); // The preceding clearance may have moved it into its sticky position.
  if (overlap(bar) && bar.bottom > top && bar.top < bottom) bottom = Math.max(top, bar.top);
  const height = Math.max(0, Math.min(budget, bottom - top));
  const drawTop = Math.ceil(bottom - height), drawLeft = Math.ceil(left);
  const values = { top: `${drawTop}px`, left: `${drawLeft}px`,
    width: `${Math.max(0, Math.floor(left + width) - drawLeft)}px`, height: `${Math.max(0, Math.floor(bottom) - drawTop)}px` };
  for (const [name, value] of Object.entries(values)) if (dock.root.style[name] !== value) dock.root.style[name] = value;
}

function editorSearchDockOutsideOwned(dock, target) {
  return Boolean(editorSearchDockCurrent(dock) && dock.fixed && target?.isConnected && document.activeElement === target
    && dock.page.contains(target) && !dock.root.contains(target) && !dock.bar.contains(target)
    && !target.disabled && !editorSearchDockHidden(target));
}

function editorSearchDockOutsideCurrent(dock, target) {
  return editorSearchDockOutsideOwned(dock, target) && !dock.ed.leaving && !dock.ed.asking && !dock.ed.saving
    && !document.querySelector("dialog[open]");
}

/** Nonmodal page controls retain focus; only their actual covered geometry is corrected. */
function revealEditorSearchDockOutside(dock, target) {
  if (!editorSearchDockOutsideOwned(dock, target)) return;
  if (dock.outsideTarget !== target) { invalidateEditorSearchDockFrame(dock); dock.outsideTarget = target; }
  if (dock.outsideFrame) return;
  const scope = editorSearchScope(dock.ac), hash = location.hash, generation = dock.generation;
  const frame = requestAnimationFrame(() => {
    if (dock.outsideFrame !== frame) return;
    dock.outsideFrame = 0;
    if (!editorSearchDockOutsideCurrent(dock, target) || dock.outsideTarget !== target
      || scope !== editorSearchScope(dock.ac) || hash !== location.hash || generation !== dock.generation) return;
    fitEditorSearchDock(dock);
    const rect = target.getBoundingClientRect(), vv = window.visualViewport;
    let top = Number.isFinite(vv?.offsetTop) ? Math.max(0, vv.offsetTop) : 0;
    const bottom = parseFloat(dock.root.style.top), header = document.querySelector(".topbar")?.getBoundingClientRect();
    if (header?.height > 0 && header.right > rect.left && header.left < rect.right && header.bottom > top) top = header.bottom;
    const available = bottom - top;
    if (![rect.top, rect.bottom, rect.height, top, bottom].every(Number.isFinite) || rect.height <= 0 || available <= 0
      || rect.top >= top && rect.bottom <= bottom) return;
    const oversized = rect.height > available;
    const gap = Math.min(8, oversized ? available / 4 : (available - rect.height) / 2);
    const by = oversized || rect.top < top ? rect.top - top - gap : rect.bottom - bottom + gap;
    if (Number.isFinite(by) && Math.abs(by) > .5 && editorSearchDockOutsideCurrent(dock, target)) window.scrollBy(0, by);
  });
  dock.outsideFrame = frame;
}

function editorSearchDockFocus(event) {
  const dock = editor?.dom?.searchDock, target = document.activeElement;
  if (!editorSearchDockCurrent(dock) || !dock.fixed || event.target !== target) return;
  if (editorSearchDockOutsideOwned(dock, target)) { revealEditorSearchDockOutside(dock, target); return; }
  if (dock.outsideTarget) { invalidateEditorSearchDockFrame(dock); dock.outsideTarget = null; }
  queueEditorSearchDockFit(dock);
  if (dock.part.contains(target)) revealEditorSearchDockFocus(dock, target);
}

/** Reveal only the same focused dock control, locally, without moving or focusing the page. */
function revealEditorSearchDockFocus(dock, target) {
  if (!editorSearchDockCurrent(dock) || !dock.fixed || document.activeElement !== target || !dock.root.contains(target)) return;
  const body = dock.part;
  if (!body.contains(target)) return; // The retained header/Done are outside this scroller.
  const scope = editorSearchScope(dock.ac), generation = dock.generation, hash = location.hash;
  if (dock.revealFrame && dock.revealTarget === target && dock.revealScope === scope && dock.revealHash === hash) return;
  if (dock.revealFrame && typeof cancelAnimationFrame === "function") cancelAnimationFrame(dock.revealFrame);
  dock.revealTarget = target; dock.revealScope = scope; dock.revealHash = hash;
  const frame = requestAnimationFrame(() => {
    if (dock.revealFrame !== frame) return;
    dock.revealFrame = 0;
    if (!editorSearchDockCurrent(dock) || !dock.fixed || generation !== dock.generation
      || scope !== editorSearchScope(dock.ac) || hash !== location.hash || document.activeElement !== target || !target.isConnected || !body.contains(target)
      || target.disabled || editorSearchDockHidden(target) || dock.ed.saving || dock.ed.asking || dock.ed.leaving
      || document.querySelector("dialog[open]")) return;
    fitEditorSearchDock(dock);
    const bounds = body.getBoundingClientRect(), rect = target.getBoundingClientRect();
    if (![bounds.top, bounds.bottom, rect.top, rect.bottom, rect.height].every(Number.isFinite) || rect.height <= 0) return;
    let top = bounds.top;
    const inputBand = dock.ac.input.closest(".ac"), band = inputBand?.getBoundingClientRect();
    if (!inputBand?.contains(target) && band?.height > 0 && band.right > rect.left && band.left < rect.right
      && band.bottom > top && band.top < bounds.bottom) top = Math.min(bounds.bottom, band.bottom);
    if (rect.top < top) body.scrollTop -= top - rect.top;
    else if (rect.bottom > bounds.bottom) body.scrollTop += Math.min(rect.bottom - bounds.bottom, rect.top - top);
  });
  dock.revealFrame = frame;
}

function resizeEditorSearchDock(event) {
  const dock = editor?.dom?.searchDock;
  if (!editorSearchDockCurrent(dock)) return;
  projectEditorSearchDock(dock);
  const active = document.activeElement;
  if (event?.type === "scroll") return; // A person's page scroll is not a request to reclaim its focused field.
  if (dock.fixed && dock.root.contains(active)) revealEditorSearchDockFocus(dock, active);
  else if (dock.fixed) revealEditorSearchDockOutside(dock, active);
}

window.addEventListener("resize", resizeEditorSearchDock);
window.addEventListener("scroll", resizeEditorSearchDock);
window.matchMedia("(min-width: 1000px)").addEventListener("change", resizeEditorSearchDock);
document.addEventListener("focusin", editorSearchDockFocus);
if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", resizeEditorSearchDock);
  window.visualViewport.addEventListener("scroll", resizeEditorSearchDock);
}
