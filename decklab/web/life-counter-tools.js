/* Optional screen wake locks and bounded frame-local Undo for the life counters.
 * Neither helper writes storage, changes a game or opens a result form. */
"use strict";

const LIFE_UNDO_LIMIT = 20;
const LIFE_SLEEP_NOTE = "Screen may sleep on this address; your count is saved";

function lifeUndoRemember(open, previous, ended) {
  open.history ||= [];
  if (ended) open.history = [];
  else { open.history.push(previous); if (open.history.length > LIFE_UNDO_LIMIT) open.history.shift(); }
  open.previous = open.history.at(-1) || null;
}
function lifeUndoPop(open) {
  open.history?.pop(); open.previous = open.history?.at(-1) || null;
}
function lifeWakeRelease(lock) {
  try { lock?.release?.()?.catch?.(() => {}); } catch (_) { /* an optional facility can already be gone */ }
}
function lifeWakeCurrent(control) {
  try { return !!control && !control.stopped && control.here() === true; } catch (_) { return false; }
}
function lifeWakeNote(control) {
  if (!control?.note) return;
  control.note.hidden = !!control.lock;
  let saved = false; try { saved = control.saved() === true; } catch (_) { /* optional status only */ }
  control.note.textContent = saved ? LIFE_SLEEP_NOTE
    : "Screen may sleep on this address; this count could not be saved for Resume";
}
function lifeMarkerOptions(makeButton, toggle) {
  const buttons = LIFE_MARKER_KINDS.map(kind => ({ kind, button: makeButton(kind[0].toUpperCase() + kind.slice(1),
    button => toggle(kind, button), { class: "filter-chip", "aria-pressed": "false" }) }));
  return { buttons, node: el("details", { class: "life-marker-options" }, el("summary", { text: "Markers" }),
    el("div", { class: "actions" }, buttons.map(row => row.button))) };
}
function lifeWakeControl(here, saved, note) {
  const control = { here, saved, note, seq: 0, pending: false, lock: null, stopped: false };
  lifeWakeNote(control); return control;
}
async function lifeWakeRequest(control) {
  if (!lifeWakeCurrent(control) || control.pending || control.lock) return;
  lifeWakeNote(control);
  if (typeof navigator.wakeLock?.request !== "function") return;
  const sequence = ++control.seq; control.pending = true;
  try {
    const lock = await navigator.wakeLock.request("screen");
    if (!lifeWakeCurrent(control) || control.seq !== sequence) { lifeWakeRelease(lock); return; }
    control.lock = lock; lifeWakeNote(control);
    lock.addEventListener?.("release", () => {
      if (control.lock !== lock) return;
      control.lock = null; if (lifeWakeCurrent(control)) lifeWakeNote(control);
    }, { once: true });
  } catch (_) { if (lifeWakeCurrent(control) && control.seq === sequence) lifeWakeNote(control); }
  finally { if (control.seq === sequence) control.pending = false; }
}
function lifeWakePause(control, stop = false) {
  if (!control) return;
  control.seq++; control.pending = false;
  const lock = control.lock; control.lock = null; control.stopped ||= stop;
  lifeWakeRelease(lock); if (!stop) lifeWakeNote(control);
}
