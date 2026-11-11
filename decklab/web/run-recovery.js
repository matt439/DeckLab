/* Starter-private unfinished runs. Timer reads never wake the PC; only explicit buttons write. */
"use strict";

const RUN_RECOVERY_POLL_MS = 45000;
const RUN_RECOVERY_TIMEOUT_MS = 10000;
const RUN_RECOVERY_KINDS = new Set(["field", "group", "gauntlet", "variant", "variant_more"]);

function resetRunRecovery(reset = true) {
  if (runsPill.recoveryRequest) runsPill.recoveryRequest.abort();
  runsPill.recoveryRequest = null;
  if (!reset) return;
  runsPill.unfinished = [];
  runsPill.recoveryAvailable = true;
  runsPill.recoveryAt = null;
  runsPill.recoveryAction = null;
  runsPill.recoveryMessage = null;
}

function recoveryAnswer(data) {
  return data && typeof data.available === "boolean" && Array.isArray(data.unfinished) && data.unfinished.length <= 128
    && data.unfinished.every(row => row && /^[0-9a-f]{32}$/.test(row.id || "") && RUN_RECOVERY_KINDS.has(row.kind)
      && typeof row.title === "string" && row.title.length <= 240 && typeof row.may_resume === "boolean"
      && (row.why_not == null || typeof row.why_not === "string" && row.why_not.length <= 2000)
      && typeof row.created === "string" && Number.isFinite(new Date(row.created).getTime())
      && (row.link == null || typeof row.link === "string" && /^#\/deck\?id=/.test(row.link)));
}

function pollRunRecovery(force = false) {
  if (!state.profile || document.visibilityState === "hidden" || runsPill.recoveryRequest) return;
  if (!force && runsPill.recoveryAt != null && Date.now() - runsPill.recoveryAt < RUN_RECOVERY_POLL_MS) return;
  const profile = state.profile, controller = new AbortController();
  runsPill.recoveryRequest = controller;
  const timeout = setTimeout(() => controller.abort(), RUN_RECOVERY_TIMEOUT_MS);
  if (timeout && timeout.unref) timeout.unref();
  const current = () => runsPill.recoveryRequest === controller && state.profile === profile;
  api("/api/forge/unfinished", {poll: true, wakeHop: false, signal: controller.signal}).then(data => {
    if (!current()) return;
    runsPill.recoveryAvailable = Boolean(recoveryAnswer(data) && data.available);
    runsPill.unfinished = runsPill.recoveryAvailable ? data.unfinished : [];
    if (runsPill.recoveryAvailable && !runsPill.recoveryAction) runsPill.recoveryMessage = null;
    drawRunsPill();
  }).catch(error => {
    if (!current()) return;
    if (!(error instanceof ApiError) && error?.name !== "AbortError") throw error;
    runsPill.recoveryAvailable = false;
    runsPill.unfinished = [];
    drawRunsPill();
  }).finally(() => {
    clearTimeout(timeout);
    if (current()) { runsPill.recoveryRequest = null; runsPill.recoveryAt = Date.now(); }
  });
}

function runRecoveryOwner(button) {
  const details = runsPill.details;
  return {profile: state.profile, details, token: routeToken, hash: location.hash, button,
    current() { return state.profile === this.profile && routeToken === this.token && location.hash === this.hash
      && runsPill.details === this.details && this.details && this.details.hash === this.hash
      && this.details.body.isConnected && this.button.isConnected && this.details.body.contains(this.button)
      && ([...document.querySelectorAll("dialog")].filter(dialog => dialog.open).at(-1) || null)
        === (this.details.sheet?.dialog || null); }};
}

async function runRecoveryAction(offer, action, button) {
  const owner = runRecoveryOwner(button);
  if (!owner.current() || button.disabled || runsPill.recoveryAction?.details === owner.details) return;
  const operation = {profile: state.profile, details: owner.details, offer};
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), RUN_RECOVERY_TIMEOUT_MS);
  if (timeout && timeout.unref) timeout.unref();
  runsPill.recoveryAction = operation;
  for (const control of owner.details.body.querySelectorAll("[data-run-recovery]")) control.disabled = true;
  try {
    const result = await apiWrite(`/api/forge/${action}`, {id: offer.id}, "POST", {wakeHop: false, signal: controller.signal});
    if (!owner.current()) return;
    runsPill.unfinished = (runsPill.unfinished || []).filter(row => row !== offer);
    runsPill.recoveryMessage = null;
    toast(action === "dismiss" ? "The recovery offer was dismissed. Saved games are kept." : result.complete
      ? "That request has already finished. Saved games are kept." : "The request was checked. Remaining work is in the run list.");
    if (action === "resume" && !result.complete) syncRunsPill(true);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (owner.current()) runsPill.recoveryMessage = `The request couldn't be confirmed: ${error.message} Check the run list before trying again.`;
  } finally {
    clearTimeout(timeout);
    if (runsPill.recoveryAction === operation) runsPill.recoveryAction = null;
    if (owner.current()) { button.disabled = false; drawRunsPill(); fillRunDetails(); pollRunRecovery(true); }
  }
}

function runRecoveryParts() {
  const rows = state.profile ? runsPill.unfinished || [] : [];
  if (!rows.length && runsPill.recoveryAvailable !== false && !runsPill.recoveryMessage) return [];
  const content = [];
  if (runsPill.recoveryAvailable === false) {
    const retry = el("button", {type: "button", class: "btn btn-quiet btn-inline", text: "Check again"});
    retry.addEventListener("click", () => { if (runRecoveryOwner(retry).current()) pollRunRecovery(true); });
    content.push(el("p", {class: "note note-warn"}, "Unfinished-run recovery can't be checked on the PC right now. No work was resumed. ", retry));
  }
  if (runsPill.recoveryMessage) content.push(el("p", {class: "note note-info", text: runsPill.recoveryMessage}));
  if (rows.length) content.push(el("p", {class: "sub", text: "Saved games are kept. Nothing starts until you choose Play the rest."}));
  content.push(el("ul", {class: "run-waiting-list"}, rows.map(offer => {
    const resume = el("button", {type: "button", class: "btn btn-secondary", text: "Play the rest",
      disabled: !offer.may_resume || runsPill.recoveryAction?.details === runsPill.details,
      "data-run-recovery": "1", "data-focus": `recover-${offer.id}`});
    const dismiss = el("button", {type: "button", class: "btn btn-quiet", text: "Dismiss",
      disabled: runsPill.recoveryAction?.details === runsPill.details,
      "data-run-recovery": "1", "data-focus": `dismiss-${offer.id}`});
    resume.addEventListener("click", () => runRecoveryAction(offer, "resume", resume));
    dismiss.addEventListener("click", () => runRecoveryAction(offer, "dismiss", dismiss));
    return el("li", {}, el("div", {class: "run-waiting-name"},
      offer.link ? el("a", {href: offer.link, text: offer.title}) : el("span", {text: offer.title}),
      el("p", {class: "sub", text: new Date(offer.created).toLocaleString(LOCALE)}),
      offer.why_not ? el("p", {class: "sub", text: offer.why_not}) : null), el("div", {class: "actions"}, resume, dismiss));
  })));
  return [el("section", {class: "run-waiting run-recovery", "aria-label": "Unfinished runs"},
    el("h3", {class: "run-waiting-head", text: "Unfinished runs"}), content)];
}
