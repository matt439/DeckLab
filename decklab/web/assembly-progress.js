/* Shared Build decks progress. Each task describes one physical action, independent of the other
 * selected decks. The server hashes these descriptions before storing them and only returns checks
 * for the tasks requested here, so another person's kit cannot be read through progress.
 * Writes patch individual tasks, never replace a stale device's entire checklist. */
"use strict";

const PACK_SYNC_MS = 3000;
let packingProgressView = null;

function packProgressOwner(view) {
  return view.progress?.profile === state.profile?.id;
}

/** Renames reset physical confirmations, including a title-only change or a return to an old id.
 * Keep zero-generation task ids unchanged; only the relevant donor affects a transfer task. */
function packTaskPlace(view, where, task) {
  const participant = (view.data?.decks || []).find(item => `${item.id}:${item.version}` === where);
  const version = participant?.rename_version || 0;
  const donor = task.startsWith("move|") ? task.slice(task.lastIndexOf("|") + 1) : null;
  const donorVersion = donor ? view.data?.rename_versions?.[donor] || 0 : 0;
  const assembly = participant?.assembly_key || "";
  const donorAssembly = donor ? view.data?.assembly_keys?.[donor] || "" : "";
  if (assembly || donorAssembly) return [where, version, donorVersion, assembly, donorAssembly];
  return version || donorVersion ? [where, version, donorVersion] : where;
}

function wirePackTicks(view) {
  if (!view.progress) {
    if (packingProgressView?.progress) clearTimeout(packingProgressView.progress.timer);
    packingProgressView = view;
    view.progress = { profile: state.profile?.id, remote: new Set(), pending: new Map(),
      loaded: false, busy: false, error: null, serial: 0, edits: new Map(), timer: null, again: false };
  }
  const previous = view.progress.scope;
  view.ticks = Array.from(view.results.querySelectorAll("[data-pack-tick]")).map(node => {
    const deck = node.closest("[data-pack-deck]");
    const count = Number(node.getAttribute("data-pack-count")) || 1;
    const task = node.getAttribute("data-pack-tick");
    const where = packTaskPlace(view, deck?.getAttribute("data-pack-deck") || "plan", task);
    const id = JSON.stringify([where, task, count, node.getAttribute("data-pack-context") || ""]);
    const tile = (node.getAttribute("class") || "").split(" ").includes("pack-tick") ? node.closest(".card-tile") : null;
    const tick = { id, node, tile, count, done: false };
    tick.set = done => {
      tick.done = done;
      if (tile) {
        node.setAttribute("aria-pressed", String(done));
        tile.classList.toggle("is-ticked", done);
      } else node.checked = done;
    };
    node.addEventListener(tile ? "click" : "change", () => {
      if (!assemblyActive(view) || !packProgressOwner(view) || view.saving || view.previewing) return;
      packQueueTicks(view, [{ id, done: tile ? !tick.done : Boolean(node.checked) }]);
    });
    return tick;
  });
  view.progress.scope = JSON.stringify(view.ticks.map(t => t.id).sort());
  if (previous !== view.progress.scope) view.progress.activity = null;
  packApplyTicks(view);
  if (previous !== view.progress.scope) packSync(view);
}

function packApplyTicks(view) {
  const progress = view.progress;
  for (const tick of view.ticks || []) {
    tick.set(progress.pending.get(tick.id)?.done ?? progress.remote.has(tick.id));
  }
  packProgressNotice(view);
  packProgress(view);
}

/** A small visible status, including a retry when a tick couldn't be shared. */
function packProgressNotice(view) {
  if (!view.progressNote) return;
  const p = view.progress;
  if (p.note !== view.progressNote) {
    p.note = view.progressNote;
    p.message = el("div");
    p.activityNode = el("div", { class: "pack-last-activity", hidden: true });
    clear(p.note).append(p.message, p.activityNode);
    p.messageKey = null; p.activityKey = null;
  }
  view.progressNote.hidden = !view.ticks?.length;
  if (view.progressNote.hidden) return;
  const words = p.error
    ? `${p.pending.size ? "These ticks haven't been saved. " : "Shared ticks couldn't be checked. "}${p.error}`
    : p.pending.size ? "Saving ticks…" : !p.loaded ? "Loading shared ticks…" : "Ticks saved for both of you.";
  if (p.messageKey !== words) {
    p.messageKey = words;
    // Waiting words get the small spinner (the .loading-small piece); the saved line stays plain.
    const waiting = !p.error && (p.pending.size || !p.loaded);
    clear(p.message).append(waiting
      ? el("span", { class: "loading loading-small" }, el("span", { class: "spinner spinner-small", "aria-hidden": "true" }), words)
      : el("span", { class: p.error ? "box box-warn" : "sub", text: words }));
    if (p.error) p.message.append(el("button", { type: "button", class: "btn btn-quiet", text: "Retry",
      onclick: () => packSync(view) }));
  }
  const a = p.activity, date = a && new Date(a.at);
  const valid = a && typeof a.by === "string" && a.by.trim() && Number.isSafeInteger(a.checks) && a.checks > 0
    && typeof a.at === "string" && Number.isFinite(date.getTime());
  const key = valid ? JSON.stringify([a.profile, a.by, a.at, a.checks]) : "";
  if (p.activityKey !== key) {
    p.activityKey = key;
    clear(p.activityNode);
    p.activityNode.hidden = !valid;
    if (valid) {
      const index = typeof a.profile === "string" ? state.profiles.findIndex(person => person.id === a.profile) : -1;
      p.activityNode.append(el("span", { class: `avatar pack-activity-avatar ${index >= 0 ? `avatar-${index % 4}` : "is-unknown"}`,
        "aria-hidden": "true", text: index >= 0 ? a.by.trim().slice(0, 1).toUpperCase() : "?" }),
        el("span", {}, el("span", { text: `Last recorded update: ${a.by} · ${plural(a.checks, "check update")}. ` }),
          el("time", { datetime: a.at, text: date.toLocaleString("en-AU", {
            day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" }) })));
    }
  }
}

function packQueueTicks(view, changes) {
  if (!packProgressOwner(view)) return;
  const p = view.progress;
  for (const { id, done } of changes) {
    const serial = ++p.serial;
    p.pending.set(id, { done, serial });
    p.edits.set(id, serial);
  }
  p.error = null;
  packApplyTicks(view);
  packSync(view);
}

/** Requests are serial within a device. Newer local toggles overlay each response until saved;
 * a late poll therefore cannot undo a click, and two devices patching different tasks both survive. */
async function packSync(view) {
  const p = view.progress;
  if (!p || !packProgressOwner(view)) return;
  if (p.busy) { p.again = true; return; }
  if (!assemblyActive(view) && !p.pending.size) return;
  clearTimeout(p.timer);
  const changes = [...p.pending].map(([id, change]) => ({ id, ...change }));
  const activityScope = p.scope;
  const ids = [...new Set([...(view.ticks || []).map(t => t.id), ...changes.map(t => t.id)])];
  const currentIds = new Set((view.ticks || []).map(t => t.id));
  const exactActivityScope = ids.every(id => currentIds.has(id));
  if (!ids.length) {
    p.loaded = true;
    packApplyTicks(view);
    return;
  }
  p.busy = true;
  p.again = false;
  packBulkProgress(view);
  try {
    const body = { ids };
    if (changes.length) body.changes = changes.map(({ id, done }) => ({ id, done }));
    const answer = await apiWrite("/api/assembly/ticks", body);
    if (!packProgressOwner(view)) return;
    if (!Array.isArray(answer.ticks)) throw new Error("The shared ticks couldn't be read. Try again.");
    if (p.scope === activityScope) p.activity = exactActivityScope ? answer.activity || null : null;
    ids.forEach(id => p.remote.delete(id));
    answer.ticks.filter(id => ids.includes(id)).forEach(id => p.remote.add(id));
    for (const change of changes) {
      if (p.pending.get(change.id)?.serial === change.serial) p.pending.delete(change.id);
    }
    p.loaded = true;
    p.error = null;
  } catch (problem) {
    if (packProgressOwner(view)) { p.error = problem.message; p.activity = null; }
  } finally {
    p.busy = false;
    if (packProgressOwner(view)) {
      if (assemblyActive(view)) packApplyTicks(view);
      if (!p.error && (p.pending.size || p.again)) {
        packSync(view);
      } else if (assemblyActive(view) && packingProgressView === view) packScheduleTicks(view);
    }
  }
}

function packScheduleTicks(view) {
  clearTimeout(view.progress.timer);
  view.progress.timer = setTimeout(() => {
    if (!assemblyActive(view) || !packProgressOwner(view)) return;
    if (!document.hidden && !view.saving) packSync(view);
    else packScheduleTicks(view);
  }, PACK_SYNC_MS);
}

/** Clear and Undo touch only this checklist's checked tasks. Other decks keep their progress. */
function packClearTicks(view) {
  if (!assemblyActive(view) || view.saving || !packProgressOwner(view)) return;
  const were = (view.ticks || []).filter(t => t.done).map(t => t.id);
  if (!were.length) return;
  packQueueTicks(view, were.map(id => ({ id, done: false })));
  const scope = view.progress.scope;
  showToast(`Cleared ${plural(were.length, "tick")}.`, { undo: () => {
    if (!assemblyActive(view) || !packProgressOwner(view) || view.progress.scope !== scope || view.saving) return;
    packQueueTicks(view, were.map(id => ({ id, done: true })));
  } });
}

/** One named deck/list's card actions. Kit and token checkboxes keep their own checks. */
function packBulkControl(view, deck) {
  const button = el("button", { type: "button", class: "btn pack-bulk-tick", text: "Tick all card checks",
    disabled: true, "aria-label": `${deck.title} (${listName(deck.version)}): tick all card checks` });
  const note = el("p", { class: "sub pack-bulk-scope" });
  const node = el("div", { class: "pack-bulk" }, note, button);
  const group = { deck, data: view.data, scope: null, node, button, note };
  view.bulk.push(group);
  button.addEventListener("click", () => packBulkTicks(view, group));
  return node;
}

function packBulkTasks(view, group) {
  const panel = group.node.closest("[data-pack-deck]");
  return [...new Map((view.ticks || []).filter(t => t.tile && t.node.closest("[data-pack-deck]") === panel)
    .map(t => [t.id, t])).values()];
}

function packBulkCurrent(view, group) {
  return Boolean(assemblyActive(view) && packProgressOwner(view) && group.node.isConnected
    && view.bulk?.includes(group) && view.data === group.data && view.data?.decks.includes(group.deck)
    && group.scope === view.progress.scope && view.progress.loaded && !view.progress.error
    && !view.previewing && !view.reviewing && !view.saving);
}

function packBulkProgress(view) {
  for (const group of view.bulk || []) {
    const ticks = packBulkTasks(view, group), p = view.progress;
    if (group.scope === null && p) group.scope = p.scope;
    group.node.hidden = !ticks.length;
    group.note.textContent = `${listName(group.deck.version)}: ${plural(ticks.length, "card check")} `
      + `(${plural(ticks.reduce((sum, t) => sum + t.count, 0), "card")}). `
      + `${packScopeWords(group.deck)}. Confirm after completing these card actions.`;
    const remaining = ticks.some(t => !t.done);
    group.button.textContent = remaining ? "Tick all card checks" : "All card checks ticked";
    group.button.disabled = !remaining || !packBulkCurrent(view, group) || p.busy || Boolean(p.pending.size);
  }
}

/** Patch only newly checked tasks; Undo preserves pre-existing checks and subsequent individual edits. */
function packBulkTicks(view, group) {
  const p = view.progress;
  if (!packBulkCurrent(view, group) || p.busy || p.pending.size) return;
  const ids = packBulkTasks(view, group).filter(t => !t.done).map(t => t.id);
  if (!ids.length) return;
  packQueueTicks(view, ids.map(id => ({ id, done: true })));
  const changed = new Map(ids.map(id => [id, p.edits.get(id)]));
  showToast(`Ticked ${plural(ids.length, "card check")} for ${group.deck.title}.`, { undo: () => {
    // Sorting replaces controls but keeps the same plan, logical deck and physical task scope.
    const active = (view.bulk || []).find(item => item.data === group.data && item.scope === group.scope
      && item.deck.id === group.deck.id && item.deck.version === group.deck.version);
    if (!active || !packBulkCurrent(view, active)) return;
    const current = new Set(packBulkTasks(view, active).map(t => t.id));
    const undo = [...changed].filter(([id, serial]) => current.has(id) && p.edits.get(id) === serial);
    if (undo.length) packQueueTicks(view, undo.map(([id]) => ({ id, done: false })));
  } });
}

// A locked phone resumes with the server's latest checks, without waiting for the next poll.
document.addEventListener("visibilitychange", () => {
  const view = packingProgressView;
  if (!document.hidden && view && assemblyActive(view) && !view.saving) packSync(view);
});
