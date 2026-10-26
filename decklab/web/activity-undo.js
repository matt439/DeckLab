/* One explicitly reviewed inverse inventory edit. Audit display rows are never write authority. */
"use strict";

const ACTIVITY_UNDO_FIELDS = {
  collection: ["name", "set", "collector_number", "finish", "quantity", "condition", "language", "notes"],
  tokens: ["front", "back", "set", "front_collector_number", "back_collector_number", "finish", "quantity", "front_details", "back_details", "notes"],
};
const ACTIVITY_UNDO_EDITABLE = { collection: ["quantity", "condition", "language", "notes"], tokens: ["quantity", "notes"] };

function activityUndoRow(row, kind) {
  if (!["collection", "tokens"].includes(kind)) return false;
  const fields = ACTIVITY_UNDO_FIELDS[kind];
  return fields && row && typeof row === "object" && !Array.isArray(row)
    && Object.keys(row).sort().join(",") === [...fields].sort().join(",")
    && fields.every(field => field === "quantity" ? Number.isSafeInteger(row[field]) && row[field] > 0 && row[field] <= 9999 : typeof row[field] === "string")
    && Boolean((row.name || row.front || "").trim());
}

function activityUndoEvidence(data, id, space) {
  if (!data || data.available !== true || data.id !== id || data.space !== space || !["collection", "tokens"].includes(data.kind)
      || typeof data.expect !== "string" || !/^[a-f0-9]{64}$/.test(data.expect)
      || typeof data.label !== "string" || !data.label.trim() || !activityUndoRow(data.current, data.kind)
      || !activityUndoRow(data.restored, data.kind) || !Array.isArray(data.fields) || !data.fields.length) return null;
  const allowed = ACTIVITY_UNDO_EDITABLE[data.kind], changed = ACTIVITY_UNDO_FIELDS[data.kind].filter(field => data.current[field] !== data.restored[field]);
  if (changed.some(field => !allowed.includes(field)) || changed.length !== data.fields.length
      || new Set(data.fields.map(item => item?.field)).size !== data.fields.length
      || data.fields.some(item => !item || !changed.includes(item.field) || item.before !== data.current[item.field]
        || item.after !== data.restored[item.field])) return null;
  return data;
}

function activityUndoReceipt(answer, preview) {
  return answer && answer.saved === true && answer.source_id === preview.id && answer.expect === preview.expect
    && answer.kind === preview.kind && answer.space === preview.space && typeof answer.sha256 === "string"
    && /^[a-f0-9]{64}$/.test(answer.sha256) && typeof answer.revision === "string" && answer.revision.trim()
    && typeof answer.summary === "string" && answer.summary.trim() && activityUndoRow(answer.restored, preview.kind)
    && ACTIVITY_UNDO_FIELDS[preview.kind].every(field => answer.restored[field] === preview.restored[field]);
}

function activityUndoOwner(ctx) {
  const view = ctx.view;
  return view.undoCtx === ctx && ctx.profile === state.profile?.id && ctx.space === ownSpace()
    && ctx.token === routeToken && view.token === ctx.token && view.profile === ctx.profile
    && ctx.hash === location.hash && view.hash === ctx.hash && JSON.stringify(view.filter) === ctx.filterSignature
    && view.days === ctx.root && ctx.root.isConnected && view.seq === ctx.seq;
}

function activityUndoButton(view, change) {
  if (change.undo?.review !== true || !Number.isSafeInteger(change.id) || change.id < 1) return null;
  const id = change.id, root = view.days;
  const button = el("button", { type: "button", class: "btn btn-quiet activity-review-undo", text: "Review undo", onclick: () => {
    if (view.undoBusy || view.undoRefreshNeeded || view.undoCtx || view.older?.disabled || root !== view.days || !root.isConnected
        || !button.isConnected || !root.contains(button) || view.token !== routeToken || view.profile !== state.profile?.id
        || view.hash !== location.hash || document.querySelector("dialog[open]")) return;
    openActivityUndo(view, id);
  } });
  return button;
}

function openActivityUndo(view, id) {
  const ctx = { view, id, root: view.days, seq: view.seq, profile: state.profile?.id, space: ownSpace(), token: routeToken,
    hash: location.hash, filter: { ...view.filter }, filterSignature: JSON.stringify(view.filter),
    pending: false, saved: false, needsRefresh: false, refreshing: false, refreshed: false, preview: null };
  view.undoCtx = ctx; view.undoBusy = true;
  const sheet = ctx.sheet = colOpenSheet("Review undo", { wide: true, onClose: () => {
    if (!activityUndoOwner(ctx) || ctx.pending) return;
    if (ctx.saved || ctx.needsRefresh) activityUndoAfterClose(ctx);
    else { view.undoCtx = null; view.undoBusy = false; }
  } });
  ctx.current = () => activityUndoOwner(ctx) && !sheet.closed;
  ctx.here = () => ctx.current() && [...document.querySelectorAll("dialog[open]")].at(-1) === sheet.dialog;
  clear(sheet.body).append(loadingBox("Checking whether this change can be undone."));
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }]);
  api("/api/activity/undo?" + new URLSearchParams({ id })).then(data => {
    if (!ctx.current()) return;
    if (data?.available === false && data.id === id && typeof data.reason === "string") {
      clear(sheet.body).append(el("p", { text: "Undo is not available for this change." }), el("p", { class: "sub", text: data.reason }));
      sheetActions(sheet, [{ text: "Close", onclick: () => sheet.close() }]); return;
    }
    const preview = activityUndoEvidence(data, id, ctx.space);
    if (!preview) throw new Error("The Undo preview could not be checked.");
    ctx.preview = preview; activityUndoShow(ctx);
  }).catch(failure => {
    if (!ctx.current()) return;
    clear(sheet.body).append(errorBox("The Undo preview couldn't be loaded", failure, null));
    sheetActions(sheet, [{ text: "Close", onclick: () => sheet.close() }]);
  });
  return sheet;
}

function activityUndoShow(ctx) {
  const { sheet, preview, view } = ctx, signature = JSON.stringify(preview);
  const words = { quantity: "Quantity", condition: "Condition", language: "Language", notes: "Notes" };
  const identity = ACTIVITY_UNDO_FIELDS[preview.kind].filter(field => !ACTIVITY_UNDO_EDITABLE[preview.kind].includes(field));
  const text = value => value === "" ? "Not recorded" : String(value);
  const panels = [["Current", "before"], ["Restored by Undo", "after"]].map(([title, key]) => el("section", { class: "panel" },
    el("h3", { text: title }), preview.fields.map(field => el("p", {}, el("b", { text: words[field.field] + ": " }), text(field[key])))));
  clear(sheet.body).append(el("h3", { text: preview.label }),
    el("p", { class: "sub", text: "Review the current row and the values this Undo will restore. Saving creates one new audited change; the original change stays in Activity." }),
    el("dl", {}, identity.flatMap(field => [el("dt", { text: field.replaceAll("_", " ") }), el("dd", { text: text(preview.current[field]) })])),
    el("div", { class: "panels" }, panels));
  const error = el("p", { class: "form-error", role: "alert", tabindex: "-1" }); sheet.body.append(error);
  function actions() {
    sheetActions(sheet, ctx.saved ? [{ text: "Done", kind: "primary", onclick: event => { if (ctx.here() && event.currentTarget.isConnected) sheet.close(); } }]
      : ctx.needsRefresh ? [{ text: "Reload Activity", kind: "primary", onclick: event => { if (ctx.here() && event.currentTarget.isConnected) sheet.close(); } },
        { text: "Close", onclick: () => sheet.close() }]
        : [{ text: "Cancel", disabled: ctx.pending, onclick: () => sheet.close() },
          { text: ctx.pending ? "Saving Undo." : "Save Undo", kind: "primary", disabled: ctx.pending, onclick: save }]);
  }
  async function save(event) {
    if (!ctx.here() || ctx.pending || ctx.saved || ctx.needsRefresh || !event?.currentTarget?.isConnected || !sheet.foot.contains(event.currentTarget)
        || ctx.preview !== preview || JSON.stringify(preview) !== signature || !activityUndoEvidence(preview, ctx.id, ctx.space)) return;
    const trigger = document.activeElement;
    const focusOwned = () => document.activeElement === trigger || document.activeElement === document.body || !document.activeElement?.isConnected;
    ctx.pending = true; error.textContent = ""; actions();
    try {
      const answer = await apiWrite("/api/activity/undo", { id: ctx.id, expect: preview.expect });
      state.library = null;
      if (!activityUndoReceipt(answer, preview)) throw new Error("The Undo result could not be confirmed.");
      if (!activityUndoOwner(ctx)) return;
      ctx.saved = true;
      if (ctx.current()) {
        const confirmation = el("p", { role: "status", tabindex: "-1", text: "Undo saved as a new change. " + answer.summary });
        sheet.body.append(confirmation); actions(); if (ctx.here() && focusOwned()) confirmation.focus();
      }
    } catch (failure) {
      state.library = null;
      if (!activityUndoOwner(ctx)) return;
      ctx.needsRefresh = true;
      error.textContent = (failure.status ? failure.message : "The Undo result could not be confirmed.") + " Reload Activity before reviewing another Undo.";
      if (ctx.current() && ctx.here() && focusOwned()) error.focus();
    } finally {
      ctx.pending = false;
      if (activityUndoOwner(ctx)) {
        if (ctx.current()) actions(); else activityUndoAfterClose(ctx);
      }
    }
  }
  actions();
}

/** A bounded refresh keeps the filter and loaded page depth; old rows stay until every read succeeds. */
async function activityUndoRefresh(ctx) {
  const view = ctx.view;
  if (!activityUndoOwner(ctx) || !ctx.sheet.closed || ctx.pending || ctx.refreshing || ctx.refreshed || document.querySelector("dialog[open]")) return;
  ctx.refreshing = true; view.undoRefreshNeeded = true;
  const depth = view.loadedPages || 1, pages = []; let cursor = null;
  try {
    for (let page = 0; page < depth; page++) {
      const data = await api(activityPath(ctx.filter, cursor));
      if (!activityUndoOwner(ctx) || document.querySelector("dialog[open]")) return;
      if (!data || !Array.isArray(data.changes) || !(data.next === null || Number.isSafeInteger(data.next) && data.next > 0)
          || typeof data.everything !== "boolean" || data.changes.some(change => !change || !Number.isSafeInteger(change.id) || change.id < 1
            || !Array.isArray(change.rows) || !Number.isFinite(new Date(change.at).getTime()))) throw new Error("The refreshed Activity could not be checked.");
      pages.push(data); cursor = data.next; if (cursor === null) break;
    }
    if (!activityUndoOwner(ctx) || document.querySelector("dialog[open]")) return;
    const oldRoot = view.days, oldPeople = view.peopleRow, oldEmpty = view.empty;
    const anchor = oldRoot.querySelector('[data-activity-id="' + ctx.id + '"]'), offset = anchor?.getBoundingClientRect().top;
    const active = document.activeElement, focusId = oldRoot.contains(active) ? active.closest(".activity-change")?.getAttribute("data-activity-id") : null;
    const kept = { days: view.days, peopleRow: view.peopleRow, people: view.people, cards: view.cards, lastDay: view.lastDay,
      lastList: view.lastList, shown: view.shown, empty: view.empty, next: view.next, everything: view.everything, loadedPages: view.loadedPages };
    try {
      Object.assign(view, { days: el("div", { class: "activity-days" }), peopleRow: el("nav", { class: "activity-filter", "aria-label": "Whose changes" }),
        people: new Map(), cards: Object.assign({}, ...pages.map(page => page.cards || {})), lastDay: null, lastList: null,
        shown: 0, empty: null, next: cursor, everything: pages[0].everything, loadedPages: pages.length });
      const changes = pages.flatMap(page => page.changes);
      if (new Set(changes.map(change => change.id)).size !== changes.length) throw new Error("Activity repeated a change.");
      activityAppend(view, changes); if (!view.shown) view.empty = activityEmpty(view);
    } catch (failure) { Object.assign(view, kept); throw failure; }
    ctx.refreshed = true; view.undoCtx = null; view.undoBusy = false; view.undoRefreshNeeded = false;
    oldRoot.replaceWith(view.days); oldPeople.replaceWith(view.peopleRow); oldEmpty?.remove();
    if (view.empty) view.days.parentNode.insertBefore(view.empty, view.older.parentNode);
    view.older.hidden = !view.next; clear(view.note).append("Activity is up to date.");
    const fresh = view.days.querySelector('[data-activity-id="' + ctx.id + '"]');
    if (fresh && offset !== undefined) window.scrollBy?.(0, fresh.getBoundingClientRect().top - offset);
    else if (!fresh) view.days.querySelector("h2")?.scrollIntoView?.({ block: "nearest" });
    const focus = focusId && view.days.querySelector('[data-activity-id="' + focusId + '"]');
    if (focus) focus.focus({ preventScroll: true });
    else if (focusId && !fresh) {
      const heading = view.days.querySelector("h2") || view.note;
      heading.setAttribute("tabindex", "-1"); heading.focus({ preventScroll: true });
    }
  } catch (failure) {
    if (activityUndoOwner(ctx)) activityUndoReloadNote(ctx, failure.message);
  } finally { ctx.refreshing = false; }
}

function activityUndoReloadNote(ctx, message = "Reload Activity before reviewing another Undo.") {
  if (!activityUndoOwner(ctx)) return;
  const view = ctx.view; view.undoRefreshNeeded = true;
  clear(view.note).append(message, " ", el("button", { type: "button", class: "btn", text: "Reload Activity", onclick: event => {
    if (activityUndoOwner(ctx) && event.currentTarget.isConnected && view.note.contains(event.currentTarget)) activityUndoRefresh(ctx);
  } }));
}

function activityUndoAfterClose(ctx) {
  if (!activityUndoOwner(ctx) || ctx.pending || ctx.refreshed || ctx.refreshing) return;
  const entry = ctx.sheet.entry;
  const stop = () => { window.removeEventListener("popstate", landed); window.removeEventListener("hashchange", stop); };
  const landed = () => {
    stop();
    if (!activityUndoOwner(ctx) || entry && (history.state?.sheet === entry.token || history.state?.pos !== entry.pos - 1)) return;
    activityUndoReloadNote(ctx); activityUndoRefresh(ctx);
  };
  if (!entry || entry.fromHistory || history.state?.sheet !== entry.token) landed();
  else { window.addEventListener("popstate", landed); window.addEventListener("hashchange", stop); }
}
