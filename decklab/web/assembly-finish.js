/* The finish bar presents existing shared progress; only packMarkBuilt saves assembled lists. */
"use strict";

let packFinishSerial = 0;

/** A bar is owned by one rendered plan, outside the later-starting results containing block. */
function packClearBar(view) {
  view.bar?.node.remove();
  view.bar = null;
}

function packBuildBar(view) {
  const copies = el("strong", { class: "pack-copy-figure" });
  const meter = el("progress", { class: "pack-copy-meter", "aria-hidden": "true" });
  const cards = el("div", { class: "pack-copy-progress", "aria-hidden": "true" },
    copies, el("span", { class: "pack-copy-label", text: "card copies pulled" }), meter);
  const other = el("span", { class: "pack-other-progress", "aria-hidden": "true" });
  const spoken = el("span", { class: "pack-progress-long sr-only" });
  const state = el("span", { class: "pack-progress-state" });
  const progress = el("div", { class: "pack-progress" }, spoken, cards, other, state);
  const finish = view.finish;
  const action = finish?.button ? el("div", { class: "pack-finish-action" }, finish.button, finish.message) : null;
  if (finish && !finish.button) progress.append(finish.message);
  const bar = actionBar({ status: progress, actions: [action,
    el("button", { type: "button", class: "btn btn-quiet pack-clear", text: "Clear", "aria-label": "Clear ticks",
      title: "Clear ticks", onclick: () => packClearTicks(view) })] });
  bar.node.classList.add("pack-bar");
  bar.progress = { copies, meter, cards, other, spoken, state };
  return bar;
}

/** Same ordered completion messages as the checklist, with a current focus destination when blocked. */
function packFinishAdvice(view, cards) {
  const completion = view.data.completion, count = completion.decks.length;
  const advice = (text, target = null) => ({ text, target });
  if (view.saving) return advice("Marking built.");
  if (view.previewing) return advice("Updating the plan.");
  if (view.builtMessage) return advice(view.builtMessage);
  if (!count) return advice(completion.reason || "These lists are already marked built.");
  if (!completion.can_mark_built) return advice(completion.reason || "This plan can't be marked built yet.");
  if (view.finishError) return advice("Refresh the plan before trying again.", view.finish.error.querySelector("button"));
  if (view.progress?.error) return advice("Save shared progress before marking these decks built.", view.progressNote.querySelector("button"));
  if (!view.progress?.loaded) return advice("Loading shared progress.");
  if (view.progress.pending.size) return advice("Saving shared progress.");
  if (cards.every(t => t.done)) return advice("Cards checked. Mark the assembled lists as built when you're ready.");
  return advice("Check off the remaining cards, then mark the assembled lists as built here.", cards.find(t => !t.done)?.node);
}

function packFinishCurrent(view, button) {
  return packSwitcherHere(view) && view.finish?.button === button && view.finish.data === view.data
    && button.isConnected && view.bar?.node.contains(button) && !document.querySelector("dialog[open]");
}

/** A blocked primary only reveals existing guidance. The original predicate/save path owns readiness. */
function packFinishClick(view, button) {
  if (!packFinishCurrent(view, button) || view.reviewing) return;
  if (packCanFinish(view)) { packMarkBuilt(view); return; }
  const advice = packFinishAdvice(view, (view.ticks || []).filter(t => t.tile));
  const target = advice.target;
  if (target && (view.ticks || []).some(t => t.tile && !t.done && t.node === target)) {
    packSwitcherRevealTask(view, target);
    return;
  }
  // Resolve Retry/Refresh fresh, without activating it. Loading/saving use the retained reason.
  const focus = target?.isConnected && view.root.contains(target) && !target.disabled ? target : view.finish.message;
  if (!packFinishCurrent(view, button) || !focus.isConnected) return;
  focus.focus({ preventScroll: true });
  focus.scrollIntoView({ block: "nearest" });
}

/** Update retained nodes, so polling never replaces a focused reason, primary, or meter. */
function packUpdateBar(view, ticks, cards, other) {
  const sum = list => list.reduce((total, tick) => total + tick.count, 0);
  const pulled = sum(cards.filter(t => t.done)), total = sum(cards), done = other.filter(t => t.done).length;
  const progress = view.bar.progress;
  progress.cards.hidden = !cards.length;
  progress.copies.textContent = cards.length ? `${pulled} / ${total}` : "";
  if (cards.length) {
    progress.meter.setAttribute("max", total);
    progress.meter.setAttribute("value", pulled);
  } else {
    progress.meter.removeAttribute("max"); progress.meter.removeAttribute("value");
  }
  progress.other.hidden = !other.length;
  progress.other.textContent = other.length ? `${done} of ${plural(other.length, "other step")}` : "";
  progress.spoken.textContent = [cards.length ? `Pulled ${pulled} of ${plural(total, "card")}` : null,
    other.length ? `${done} of ${plural(other.length, "other step")}` : null].filter(Boolean).join(" · ");
  progress.state.textContent = ticks.length && ticks.every(t => t.done) ? "All packed." : !ticks.length ? "Nothing to tick in this plan." : "";
  if (!view.finish) return;
  view.finish.message.textContent = packFinishAdvice(view, cards).text;
  if (view.finish.button) {
    view.finish.button.disabled = false;
    view.finish.button.setAttribute("aria-disabled", String(!packCanFinish(view)));
    view.finish.button.textContent = view.saving ? "Marking built." : view.finish.label;
  }
}
