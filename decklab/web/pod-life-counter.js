/* A local three/four-player counter. Model packets never contain historical snapshots.
 * Only current user actions hand an ended game to the ordinary reviewed pod form. */
"use strict";

const POD_LIFE_KEY = "play.podLifeCounter";
const podLifeCompleted = new Set(); // confirmed server saves: no duplicate Resume on this page if local removal fails
let podLifeCounterOpen = null;

function podLifeSessionId() {
  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") crypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
}
function podLifeScope(profile = state.profile) {
  const space = profile?.space === undefined ? "home" : profile.space;
  return profile && podLifeProfile(profile.id) && (space === "home" || space === profile.id)
    ? { profile: profile.id, space } : null;
}
/** The active pointer and each packet have separate keys, so clearing an old session cannot delete a new one. */
function podLifeKey(profile = state.profile, session = "active") {
  const scope = podLifeScope(profile);
  return scope && (session === "active" || podLifeSession(session))
    ? `${POD_LIFE_KEY}.${scope.space}.${scope.profile}.${session}` : null;
}
function podLifeStored(profile, session, now = Date.now()) {
  try {
    const raw = local.get(podLifeKey(profile, session));
    if (typeof raw !== "string" || raw.length > 64000) return null;
    const packet = JSON.parse(raw);
    return podLifeValid(packet, podLifeScope(profile), now) && packet.session_id === session ? packet : null;
  } catch (_) { return null; }
}
/** A stale/deleted deck choice can still be counted; the recording bridge must prove current replacements. */
function podLifeSaved(_data, now = Date.now()) {
  const profile = state.profile, key = podLifeKey(profile);
  if (!key) return null;
  const session = local.get(key);
  return podLifeSession(session) && !podLifeCompleted.has(podLifeKey(profile, session)) ? podLifeStored(profile, session, now) : null;
}
function podLifeVisible(node, allowDisabled = false) {
  if (!node?.isConnected || !allowDisabled && node.disabled) return false;
  for (let value = node; value; value = value.parentNode) {
    if (value.hidden || value.getAttribute?.("aria-hidden") === "true") return false;
    if ((value.tagName?.toLowerCase() || value.tag) === "details" && !value.open && value.getAttribute("open") === null) {
      const summary = Array.from(value.children).find(child => (child.tagName?.toLowerCase() || child.tag) === "summary");
      if (!summary?.contains(node)) return false;
    }
  }
  return true;
}
function podLifeStorageCurrent(open) {
  const pointer = local.get(open.pointerKey), raw = local.get(open.packetKey);
  return pointer === open.pointerObserved && raw === open.stored;
}
/** Frame ownership remains true below a review sheet; foreground controls additionally need top=true. */
function podLifeCounterHere(open, top = false) {
  try {
    const currentMain = document.getElementById("main");
    if (podLifeCounterOpen !== open || state.profile !== open.profile || state.profile?.id !== open.scope.profile ||
        podLifeScope(state.profile)?.space !== open.scope.space || routeToken !== open.routeToken || location.hash !== open.hash ||
        currentMain !== open.main || !currentMain?.isConnected || open.data !== open.originalData ||
        open.data.pod_lists !== open.lists || open.data.pods !== open.pods || open.options.source !== open.source ||
        open.options.isCurrent !== open.owner || open.options.onRecord !== open.onRecord || open.options.onClose !== open.onClose || open.owner() !== true ||
        !podLifeVisible(open.source) || !currentMain.contains(open.source) || open.source.parentNode !== open.sourceParent ||
        open.dialog.parentNode !== open.dialogParent || !podLifeVisible(open.dialog) ||
        open.dialog.getAttribute("open") === null && !open.dialog.open || open.inner.parentNode !== open.dialog ||
        open.grid.parentNode !== open.inner || open.bar.parentNode !== open.inner || open.end.parentNode !== open.inner ||
        open.clock.parentNode !== open.bar || open.error.parentNode !== open.inner ||
        open.packet !== open.originalPacket || open.packet.session_id !== open.session ||
        !podLifeValid(open.packet, open.scope)) return false;
    if (top) {
      if (document.hidden === true || document.visibilityState && document.visibilityState !== "visible") return false;
      const dialogs = Array.from(document.querySelectorAll("dialog")).filter(node =>
        (node.open || node.getAttribute("open") !== null) && !node.hidden);
      if (dialogs.at(-1) !== open.dialog) return false;
    }
    return true;
  } catch (_) { return false; }
}
function podLifeControlHere(open, button, allowDisabled = false) {
  const parent = open.controls.get(button);
  return podLifeCounterHere(open, true) && parent && button.parentNode === parent && open.dialog.contains(button) &&
    podLifeVisible(button, allowDisabled) && (!open.completed || button === open.closeButton) &&
    (!open.choosing || open.end.contains(button) || button === open.closeButton);
}
function podLifeButton(open, words, action, attrs = {}) {
  const button = el("button", { type: "button", class: "btn btn-quiet", text: words, ...attrs });
  button.addEventListener("click", () => { if (podLifeControlHere(open, button)) action(button); });
  return button;
}
function podLifeRegister(open, root) {
  for (const button of root.querySelectorAll("button")) open.controls.set(button, button.parentNode);
}
function podLifeWrite(open) {
  const encoded = JSON.stringify(open.packet);
  local.set(open.packetKey, encoded);
  const raw = local.get(open.packetKey);
  let pointer = local.get(open.pointerKey);
  if ((raw !== open.stored && raw !== encoded) || pointer !== open.pointerObserved) {
    open.error.textContent = "Another local counter changed. Close this counter and use Resume."; return;
  }
  // Retry a failed initial pointer write only from the same foreground action
  // while its observed value is unchanged, never over a different new session.
  if (pointer !== open.session) { local.set(open.pointerKey, open.session); pointer = local.get(open.pointerKey); }
  if (pointer !== open.pointerObserved && pointer !== open.session) {
    open.error.textContent = "Another local counter changed. Close this counter and use Resume."; return;
  }
  open.stored = raw; open.pointerObserved = pointer; open.persisted = pointer === open.session && raw === encoded;
  open.error.textContent = open.persisted ? "" : "The counter is open, but its latest change could not be kept for Resume.";
  if (open.persisted && podLifeSession(open.previousSession) && open.previousSession !== open.session) {
    local.remove(podLifeKey(open.profile, open.previousSession)); open.previousSession = null;
  }
}
function podLifeAction(open, button, change, rebuild = false) {
  if (!podLifeControlHere(open, button) || !podLifeStorageCurrent(open)) return false;
  const previous = podLifeClone(open.packet), token = { button, generation: open.generation };
  open.action = token;
  if (!change()) { open.action = null; return false; }
  open.previous = previous; open.generation++; open.choosing = false;
  podLifeWrite(open);
  // Prove the foreground action before rendering hides a chosen result or
  // disables the player who just went out. Record checks the current top frame again.
  const record = podLifeEnded(open.packet) && open.action === token && podLifeControlHere(open, button, true);
  podLifeDraw(open, rebuild);
  if (record && open.action === token) podLifeRecord(open);
  open.action = null;
  return true;
}
function podLifeStep(open, button, id, field, delta, source = null) {
  return podLifeAction(open, button, () => podLifeChange(open.packet, id, field, delta, source));
}
function podLifeSeat(open, seat) {
  const total = el("output", { class: "life-total", "aria-live": "polite", "aria-label": `${seat.player}: life` });
  const adjust = delta => podLifeButton(open, delta > 0 ? `+${delta}` : String(delta), button =>
    podLifeStep(open, button, seat.seat_id, "life", delta), {
    class: "btn life-adjust", "aria-label": `${seat.player}: ${Math.abs(delta)} ${delta < 0 ? "life less" : "more life"}` });
  const mainRow = el("div", { class: "pod-life-main" }, adjust(-1), total, adjust(1));
  const extras = el("div", { class: "pod-life-extras" }, adjust(-5), adjust(5));
  const counters = [];
  const counter = (field, label, source = null) => {
    const value = el("output", { class: "life-small-value", "aria-label": `${seat.player}: ${label}` });
    const button = delta => podLifeButton(open, delta < 0 ? "-" : "+", control =>
      podLifeStep(open, control, seat.seat_id, field, delta, source), {
      "aria-label": `${seat.player}: ${delta < 0 ? "1 less" : "1 more"} ${label}` });
    const row = el("div", { class: "life-small", role: "group", "aria-label": `${seat.player}: ${label}` },
      el("span", { class: "life-small-label", text: label }), button(-1), value, button(1));
    counters.push({ row, value, field, source });
    return row;
  };
  const poison = counter("poison", "poison");
  const sources = el("details", { class: "pod-life-sources" }, el("summary", { text: "Commander damage received" }));
  for (const other of open.packet.seats)
    for (const source of other.sources) sources.append(counter("commander", `${other.seat_id === seat.seat_id ? "Own commander" : other.player}: ${source.label}`,
      { seat_id: other.seat_id, source_id: source.source_id }));
  const out = el("p", { class: "pod-life-status", role: "status" });
  const concede = podLifeButton(open, "Concede", button =>
    podLifeAction(open, button, () => podLifeConcede(open.packet, seat.seat_id)), { "aria-label": `${seat.player}: concede` });
  const label = seat.type === "deck" ? seat.title : seat.commander || "External opponent";
  const node = el("section", { class: "pod-life-seat", "data-pod-life-seat": seat.seat_id, "aria-label": seat.player },
    el("h3", { text: seat.player }), el("p", { class: "sub", text: label }), mainRow, extras, poison, sources, out, concede);
  if (seat.type === "external" && seat.sources.length === 1) {
    const sourceName = el("input", { type: "text", maxlength: 600, value: "", "aria-label": `${seat.player}: second commander label (optional)` });
    const addSource = podLifeButton(open, "Add second commander", button => {
      if (!podLifeVisible(sourceName) || sourceName.parentNode !== sourceField) return;
      podLifeAction(open, button, () => podLifeAddSource(open.packet, seat.seat_id, sourceName.value), true);
    });
    const sourceField = el("div", { class: "pod-life-source-add" }, sourceName, addSource);
    sources.append(el("p", { class: "sub", text: "An unknown commander uses a numbered source. Add a second source explicitly; names are never split." }), sourceField);
  }
  return { node, draw() {
    total.textContent = String(seat.life); const reason = podLifeOut(open.packet, seat.seat_id);
    node.classList.toggle("pod-life-out", !!reason); out.textContent = reason ? `Out: ${reason === "conceded" ? "conceded" : reason}.` : "Still playing";
    for (const item of counters) {
      item.row.hidden = item.field === "poison" && !open.packet.poison;
      item.value.textContent = String(item.field === "poison" ? seat.poison : seat.damage.find(value =>
        value.seat_id === item.source.seat_id && value.source_id === item.source.source_id)?.value || 0);
    }
    for (const button of node.querySelectorAll("button")) button.disabled = !!reason || !!podLifeEnded(open.packet) || open.completed;
  } };
}
function podLifeClock(open) {
  clearTimeout(open.timer);
  if (!podLifeCounterHere(open) || document.hidden === true || document.visibilityState && document.visibilityState !== "visible") return;
  const seconds = Math.max(0, Math.floor((Date.now() - open.packet.started) / 1000));
  const hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds / 60) % 60, remainder = seconds % 60;
  const two = value => String(value).padStart(2, "0");
  open.clock.textContent = hours ? `${hours}:${two(minutes)}:${two(remainder)}` : `${minutes}:${two(remainder)}`;
  open.timer = setTimeout(() => podLifeClock(open), 1000); // display only: no packet update, storage write or handoff
}
function podLifeDraw(open, rebuild = false) {
  if (rebuild) {
    for (const [button] of open.controls) if (open.grid.contains(button)) open.controls.delete(button);
    clear(open.grid); open.seatRows = open.packet.seats.map(seat => podLifeSeat(open, seat));
    open.grid.append(...open.seatRows.map(row => row.node)); podLifeRegister(open, open.grid);
  }
  for (const row of open.seatRows) row.draw();
  const ended = podLifeEnded(open.packet);
  open.poisonButton.setAttribute("aria-pressed", String(open.packet.poison)); open.poisonButton.disabled = !!ended || open.completed;
  open.endButton.disabled = !!ended || open.completed; open.undoButton.disabled = !open.previous || open.completed;
  open.end.hidden = !open.choosing && !ended;
  open.endTitle.textContent = ended ? ended.result === "draw" ? "Draw" :
    `${open.packet.seats.find(seat => seat.seat_id === ended.result)?.player || "A player"} won` : "Choose the pod's result";
  open.recordButton.hidden = !ended || open.completed;
  open.keepButton.hidden = !!ended;
  for (const row of open.winners) row.button.hidden = !!ended || !!podLifeOut(open.packet, row.id);
  open.drawButton.hidden = !!ended;
}
/** Only this function's foreground callers can offer a result; Resume and clocks never call it. */
function podLifeRecord(open) {
  if (!podLifeCounterHere(open, true) || !podLifeStorageCurrent(open) || !podLifeEnded(open.packet) || open.handoff || open.completed) return false;
  const generation = open.generation, session = open.session;
  const current = () => podLifeCounterHere(open) && !open.completed && open.generation === generation && open.session === session && podLifeStorageCurrent(open);
  const onSaved = () => {
    if (!current()) return false;
    open.completed = true; open.generation++; podLifeCompleted.add(open.packetKey);
    // Deliberately leave the pointer alone: a later session's pointer cannot be removed.
    const removed = local.remove(open.packetKey);
    if (removed !== true || local.get(open.packetKey) !== null) {
      open.error.textContent = "Pod game saved. Its local counter could not be removed. Resume is disabled on this page; if this counter reappears after reload, do not record it again.";
      podLifeDraw(open); return false;
    }
    closePodLifeCounter(); return true;
  };
  open.handoff = true;
  try { open.onRecord(podLifeClone(open.packet), { isCurrent: current, onSaved }); }
  catch (_) { if (current()) open.error.textContent = "The result form could not be opened. Keep this counter and try again."; }
  finally { open.handoff = false; }
  return true;
}
/** options.replace is true only for an explicitly started new local session, never a Resume. */
function podLifeOpen(data, packet, options) {
  const profile = state.profile, scope = podLifeScope(profile), currentMain = document.getElementById("main");
  let current = false;
  try { current = options?.isCurrent?.() === true; } catch (_) { return false; }
  if (!scope || !podLifeValid(packet, scope) || !options || typeof options.isCurrent !== "function" ||
      typeof options.onRecord !== "function" || !current ||
      !podLifeVisible(options.source) || !currentMain?.contains(options.source)) return false;
  if (podLifeCounterOpen) return false;
  const session = packet.session_id, pointerKey = podLifeKey(profile), packetKey = podLifeKey(profile, session);
  if (podLifeCompleted.has(packetKey)) return false;
  const pointer = local.get(pointerKey), stored = local.get(packetKey), encoded = JSON.stringify(packet);
  if (options.replace !== true && (pointer !== session || stored !== encoded) ||
      pointer === session && stored !== encoded) return false;
  const open = { data, originalData: data, lists: data.pod_lists, pods: data.pods, packet: podLifeClone(packet),
    profile, scope, session, pointerKey, packetKey, options, source: options.source, sourceParent: options.source.parentNode,
    owner: options.isCurrent, onRecord: options.onRecord, onClose: options.onClose, routeToken, hash: location.hash, main: currentMain,
    generation: 0, choosing: false, previous: null, timer: null, handoff: false, completed: false, controls: new Map(), stored,
    pointerObserved: pointer, previousSession: pointer, persisted: false };
  open.originalPacket = open.packet;
  open.clock = el("span", { class: "life-clock", role: "timer", "aria-label": "Pod game time" });
  open.error = el("p", { class: "form-error pod-life-error", role: "status" });
  open.poisonButton = podLifeButton(open, "Poison", button => podLifeAction(open, button, () => podLifePoison(open.packet, !open.packet.poison)),
    { "aria-pressed": String(packet.poison) });
  open.endButton = podLifeButton(open, "End game", () => { open.choosing = true; podLifeDraw(open); });
  open.undoButton = podLifeButton(open, "Undo last change", button => {
    if (!open.previous || !podLifeStorageCurrent(open)) return;
    const previous = open.previous;
    if (podLifeControlHere(open, button) && podLifeUndo(open.packet, previous)) {
      open.previous = null; open.generation++; open.choosing = false; podLifeWrite(open); podLifeDraw(open, true);
    }
  });
  open.closeButton = podLifeButton(open, "Close", () => closePodLifeCounter());
  open.bar = el("div", { class: "pod-life-bar" }, open.clock, open.poisonButton, open.endButton, open.undoButton, open.closeButton);
  open.grid = el("div", { class: "pod-life-grid" });
  open.endTitle = el("h3", { text: "Choose the pod's result" });
  open.winners = packet.seats.map(seat => ({ id: seat.seat_id, button: podLifeButton(open, `${seat.player} won`, button =>
    podLifeAction(open, button, () => podLifeEnd(open.packet, seat.seat_id))) }));
  open.drawButton = podLifeButton(open, "Draw", button => podLifeAction(open, button, () => podLifeEnd(open.packet, "draw")));
  open.keepButton = podLifeButton(open, "Keep playing", () => { open.choosing = false; podLifeDraw(open); });
  open.recordButton = podLifeButton(open, "Review pod result", () => podLifeRecord(open));
  open.end = el("div", { class: "pod-life-end", role: "group", "aria-label": "Pod result", hidden: true },
    open.endTitle, ...open.winners.map(row => row.button), open.drawButton, open.keepButton, open.recordButton);
  open.inner = el("div", { class: "pod-life-inner" }, open.grid, open.bar, open.end, open.error);
  open.dialog = el("dialog", { class: "pod-life-counter", "aria-label": "Pod life counter" }, open.inner);
  open.dialog.addEventListener("close", () => { if (podLifeCounterOpen === open) closePodLifeCounter(); });
  open.visible = () => { if (podLifeCounterOpen === open) podLifeClock(open); };
  document.addEventListener("visibilitychange", open.visible);
  document.body.append(open.dialog); open.dialogParent = open.dialog.parentNode; podLifeCounterOpen = open;
  if (typeof open.dialog.showModal === "function") open.dialog.showModal(); else open.dialog.setAttribute("open", "");
  if (options.replace === true) {
    local.set(packetKey, encoded); local.set(pointerKey, session);
    const found = local.get(pointerKey), raw = local.get(packetKey);
    if (found !== pointer && found !== session || raw !== stored && raw !== encoded) { closePodLifeCounter(true); return false; }
    open.stored = raw; open.pointerObserved = found; open.persisted = found === session && raw === encoded;
    if (open.persisted && pointer && podLifeSession(pointer) && pointer !== session) {
      local.remove(podLifeKey(profile, pointer)); open.previousSession = null;
    }
  } else { open.stored = stored; open.persisted = true; }
  if (!open.persisted) open.error.textContent = "The counter is open, but it could not be kept for Resume.";
  podLifeRegister(open, open.bar); podLifeRegister(open, open.end); podLifeDraw(open, true); podLifeClock(open);
  open.entry = typeof pushSheetEntry === "function" ? pushSheetEntry(() => {
    if (podLifeCounterOpen === open) closePodLifeCounter();
  }) : null;
  return true;
}
/** Closing keeps the local packet; application route cleanup may close an obsolete frame without touching storage. */
function closePodLifeCounter(quiet = false) {
  const open = podLifeCounterOpen;
  if (!open) return false;
  const notify = !quiet && podLifeCounterHere(open);
  podLifeCounterOpen = null; clearTimeout(open.timer);
  if (open.dialog.open && typeof open.dialog.close === "function") open.dialog.close();
  open.dialog.remove();
  if (typeof releaseSheetEntry === "function") releaseSheetEntry(open.entry);
  document.removeEventListener("visibilitychange", open.visible);
  if (notify && typeof open.onClose === "function") open.onClose();
  return true;
}
