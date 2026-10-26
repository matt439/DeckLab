/* Step disclosure is presentation only: original tasks, shared ticks and save eligibility stay intact. */
"use strict";

function packInitSteps(view) {
  view.stepState = { data: null, records: [], saved: new Map(), disposed: false, wide: view.switcher.wide };
}

function packStepsHere(view) {
  return packSwitcherHere(view) && view.stepState && !view.stepState.disposed && view.stepState.data === view.data;
}

function packStepCurrent(view, step) {
  return packStepsHere(view) && view.stepState.records.includes(step) && step.data === view.data
    && view.data?.decks.includes(step.deck) && step.node.isConnected && view.results.contains(step.node)
    && step.node.closest("[data-pack-deck]")?.getAttribute("data-pack-deck") === `${step.deck.id}:${step.deck.version}`;
}

function packStepsCanChange(view, step) {
  return packStepCurrent(view, step) && !view.previewing && !view.saving && !view.reviewing
    && !document.querySelector("dialog[open]");
}

function packStepsStart(view, data) {
  const ctx = view.stepState;
  if (!ctx || ctx.disposed) return;
  ctx.saved = data ? new Map(ctx.records.filter(step => step.scope !== null).map(step => [step.key,
    { scope: step.scope, manual: step.manual, done: step.done, auto: step.auto, open: step.node.open }])) : new Map();
  ctx.data = data;
  ctx.records = [];
}

/** Programmatic toggles may queue/coalesce events. Record the projected value synchronously. */
function packStepOpen(step, open) {
  step.desired = Boolean(open);
  step.node.open = step.desired;
}

function packStepManual(view, step, open) {
  if (!packStepsCanChange(view, step)) return;
  // Some native mouse activations leave focus in the body. Never hide that original focus target.
  if (!open && step.body.contains(document.activeElement)) {
    step.summary.focus({ preventScroll: true });
    if (!packStepsCanChange(view, step) || document.activeElement !== step.summary) return;
  }
  step.manual = Boolean(open);
  step.auto = false;
  packStepOpen(step, step.manual);
}

function packRegisterStep(view, deck, kind, number, node) {
  const ctx = view.stepState;
  const step = { key: JSON.stringify([deck.id, deck.version, kind]), data: view.data, deck, node, number,
    summary: node.querySelector("summary"), body: node.querySelector(".pack-step-body"),
    badge: node.querySelector(".pack-step-n"), spoken: node.querySelector(".pack-step-spoken"),
    scope: null, manual: null, done: false, auto: false, queued: false };
  ctx.records.push(step);
  packStepOpen(step, true);
  step.summary.addEventListener("click", event => {
    event.preventDefault(); // Native mouse, keyboard and assistive activation use the same owned toggle.
    packStepManual(view, step, !step.node.open);
  });
  node.addEventListener("toggle", () => {
    if (!packStepCurrent(view, step) || Boolean(node.open) === step.desired) return;
    if (!packStepsCanChange(view, step)) { packStepOpen(step, step.desired); return; }
    // A browser reveal is an explicit expansion too. Late events never manufacture manual intent.
    packStepManual(view, step, Boolean(node.open));
  });
  node.addEventListener("focusout", () => {
    if (step.queued) return;
    step.queued = true;
    Promise.resolve().then(() => {
      step.queued = false;
      if (packStepCurrent(view, step)) packStepsProgress(view);
    });
  });
}

function packStepProtected(view, step) {
  const returning = view.packingViewer;
  return step.node.contains(document.activeElement) || Boolean(returning && returning.data === view.data
    && step.body.contains(returning.trigger));
}

function packStepsProgress(view) {
  if (!packStepsHere(view)) return;
  const ctx = view.stepState, progress = view.progress;
  for (const step of ctx.records) {
    if (!packStepCurrent(view, step)) continue;
    const ticks = (view.ticks || []).filter(tick => step.body.contains(tick.node));
    const scope = JSON.stringify(ticks.map(tick => tick.id).sort());
    if (step.scope === null) {
      step.scope = scope;
      const saved = ctx.saved.get(step.key);
      if (saved?.scope === scope) {
        Object.assign(step, { manual: saved.manual, done: saved.done, auto: saved.auto });
        packStepOpen(step, saved.open);
      }
    }
    const done = ticks.length > 0 && ticks.every(tick => tick.done);
    if (done !== step.done) {
      step.manual = null;
      step.auto = done;
      if (!done) packStepOpen(step, true); // Undo/new shared work never stays hidden behind a done row.
    }
    step.done = done;
    step.node.classList.toggle("is-done", done);
    step.badge.textContent = done ? "" : String(step.number);
    step.spoken.textContent = `Step ${step.number}${done ? ", done" : ""}. `;
    if (!ctx.wide && done && step.auto && step.manual === null && packStepsCanChange(view, step)
        && progress?.loaded && !progress.busy && !progress.error && !ticks.some(tick => progress.pending.has(tick.id))
        && !packStepProtected(view, step)) {
      packStepOpen(step, false);
      step.auto = false;
    }
  }
}

/** Same details/summary/body survive the density change; lab starts expanded and stays manually usable. */
function packStepsResize(view, wide) {
  if (!packStepsHere(view)) return;
  const ctx = view.stepState;
  ctx.wide = wide;
  for (const step of ctx.records) {
    if (!packStepCurrent(view, step)) continue;
    if (wide) packStepOpen(step, true);
    else if (step.done && step.manual !== true) { step.manual = null; step.auto = true; }
  }
  packStepsProgress(view);
}

/** The guide/viewer's current original target must be exposed before their existing focus path runs. */
function packExpandStep(view, target) {
  if (!packStepsHere(view)) return;
  const step = view.stepState.records.find(item => item.body.contains(target));
  if (!step || !packStepsCanChange(view, step)) return;
  if (!step.node.open) {
    step.manual = true;
    step.auto = false;
    packStepOpen(step, true);
  }
}

function packStepTargetShown(view, target) {
  const step = view.stepState?.records.find(item => item.body.contains(target));
  return !step || Boolean(packStepCurrent(view, step) && step.node.open);
}

function packDisposeSteps(view) {
  if (!view.stepState) return;
  view.stepState.disposed = true;
  view.stepState.records = [];
  view.stepState.saved.clear();
}
