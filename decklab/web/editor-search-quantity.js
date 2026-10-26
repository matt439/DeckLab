/* Editor search quantities: one preferred live line in the current Add-to section.
 * Loaded after editor-cards.js. Search painting stays read-only; actions use the
 * original quantity/remove/history functions, exact owner and current line. */
"use strict";

/** The exact line Add uses. Do not sum names or normalize the saved/default printing. */
function editorAddLine(ed, card, section) {
  const lines = ed.lists[section] || [];
  const d = card.default;
  return lines.find(line => line.name === card.name && (d ? line.set === d.set && line.number === d.number
    && line.finish === d.finish : !line.set)) || lines.find(line => line.name === card.name);
}

/** Passive answers may paint during another operation; only current search actions may mutate. */
function editorSearchCanAct(ac) {
  if (!editorSearchCurrent(ac) || ac.owner.saving || ac.owner.asking || ac.owner.leaving) return false;
  return ![...document.querySelectorAll("dialog[open]")].some(dialog => !dialog.contains(ac.input));
}

/** Keep both action modes attached; facts/Inspect never become descendants of a quantity control. */
function searchQuantitySlot(ac, card, index, addButton) {
  const record = { ac, card, index, addButton, line: null, section: null };
  const current = target => editorSearchActionCurrent(ac, card, index, target)
    && !target.disabled && !record.group.hidden
    && record.section === ac.owner.addSection && record.line
    && editorAddLine(ac.owner, card, record.section) === record.line
    && findLine(record.line.uid)?.line === record.line;
  const act = (target, change) => {
    if (!current(target)) { syncSearchQuantity(record); return false; }
    if (target !== qty) record.holdAddFocus = false; // A fresh Minus/Plus action owns its normal recovery.
    change(record.line);
    syncEditorSearchQuantities(ac);
    return true;
  };
  const minus = el("button", { type: "button", class: "step step-minus", text: "−",
    onclick: event => act(event.currentTarget, line => stepQty(line.uid, -1)) });
  const qty = el("input", { type: "text", class: "qty-input", inputmode: "numeric", pattern: "[0-9]*",
    maxlength: 2, enterkeyhint: "done" });
  const editing = () => {
    record.holdAddFocus = false;
    return record.edit = { line: record.line, section: record.section, done: false };
  };
  qty.addEventListener("focus", () => { if (current(qty)) { editing(); qty.select(); } });
  qty.addEventListener("input", () => {
    if (!current(qty)) { syncSearchQuantity(record); return; }
    editing();
    const n = typedQty(qty.value);
    if (n >= 1) act(qty, line => setQty(line.uid, n));
  });
  const commit = (event, kind) => {
    // A focused change precedes blur's destination. Keep its controls alive until blur or explicit Enter.
    if (kind === "change" && document.activeElement === qty && current(qty)) return;
    const edit = record.edit || editing();
    if (edit.done) return;
    edit.done = true; // Removing/focusing can dispatch another blur/change before this handler returns.
    record.holdAddFocus = true; // Sync during or after this commit must not guess an exit destination.
    if (edit.line !== record.line || edit.section !== record.section) { syncSearchQuantity(record); return; }
    const n = typedQty(qty.value);
    const active = document.activeElement, next = event?.relatedTarget;
    const background = node => !node || node === document.body || node === document.documentElement;
    const ownTarget = next && record.group.contains(next);
    const ownedExit = (record.group.contains(active) || background(active)) && (!next || ownTarget)
      && (kind === "enter" || kind === "tab" || kind === "blur" && ownTarget);
    const accepted = act(qty, line => { if (n === 0) removeLine(line.uid); else if (n >= 1) setQty(line.uid, n); });
    // Native blur may make BODY active before committing; Remove's original Undo focus belongs to this action too.
    const undo = edit.line && ac.owner.dom.lines?.querySelector(`[data-removed="${edit.line.uid}"]`)?.querySelector(".undo-btn");
    const focused = document.activeElement;
    if (accepted && n === 0 && ownedExit && record.group.hidden && editorSearchCanAct(ac)
        && (background(focused) || record.group.contains(focused) || focused === undo)) addButton.focus({ preventScroll: true });
  };
  qty.addEventListener("change", event => commit(event, "change"));
  qty.addEventListener("blur", event => commit(event, "blur"));
  qty.addEventListener("keydown", event => {
    // Zero can hide or disable the next control. Handle only that owned exit before the browser targets it.
    if (event.key === "Tab" && !event.ctrlKey && !event.altKey && !event.metaKey) {
      const next = event.shiftKey ? minus : plus;
      if (document.activeElement !== qty || !current(qty) || typedQty(qty.value) !== 0 || next.disabled || next.hidden) return;
      const remaining = (ac.owner.lists[record.section] || []).filter(line => line !== record.line);
      const after = editorAddLine({ lists: { [record.section]: remaining } }, card, record.section);
      if (after && (event.shiftKey || after.qty < MAX_COPIES)) return; // The native adjacent button survives.
      event.preventDefault(); commit(event, "tab");
      return;
    }
    if (event.key !== "Enter") return;
    event.preventDefault(); commit(event, "enter");
    if (document.activeElement === qty) qty.blur();
  });
  const plus = el("button", { type: "button", class: "step step-plus", text: "+",
    onclick: event => act(event.currentTarget, line => stepQty(line.uid, 1)) });
  record.group = el("div", { class: "stepper edit-stepper ac-stepper", hidden: true }, minus, qty, plus);
  record.context = el("small", { class: "ac-quantity-context", id: `ac-quantity-${index}`, hidden: true });
  record.slot = el("div", { class: "ac-actions" }, addButton, record.group, record.context);
  record.minus = minus; record.qty = qty; record.plus = plus;
  for (const control of [minus, qty, plus]) {
    control.setAttribute("aria-describedby", record.context.id);
    control.addEventListener("focus", () => {
      if (editorSearchResultsCurrent(ac)) { ac.active = index; markActive(ac); }
    });
  }
  record.slot.searchQuantity = record;
  return record.slot;
}

/** Read current lines without replacing controls, including Quick search outside #main. */
function syncSearchQuantity(record) {
  const { ac, card, index, addButton, group, context, qty, minus, plus } = record;
  if (!editorSearchCurrent(ac, true) || ac.items[index] !== card
      || (ac.resultScope && ac.resultScope !== editorSearchScope(ac))) return;
  const section = ac.owner.addSection;
  const line = editorAddLine(ac.owner, card, section) || null;
  const focused = document.activeElement;
  record.line = line; record.section = section;
  const option = record.slot.closest(".ac-option");
  option?.classList.toggle("is-in-list", Boolean(line));
  addButton.hidden = Boolean(line); group.hidden = !line; context.hidden = !line;
  if (line) {
    group.setAttribute("data-uid", line.uid);
    const where = `${sectionTitle(section)} · ${printingText(line)}`;
    context.textContent = `This line: ${where}`;
    qty.setAttribute("aria-label", `Copies of ${card.name} on this line`);
    minus.setAttribute("aria-label", line.qty <= 1 ? `Remove ${card.name} from this line` : `One fewer ${card.name} on this line`);
    plus.setAttribute("aria-label", `One more ${card.name} on this line`);
    const typing = focused === qty && typedQty(qty.value) === line.qty;
    if (!typing) qty.value = String(line.qty);
    const off = line.qty >= MAX_COPIES;
    if (editorSearchCanAct(ac) && (focused === addButton || (off && focused === plus))) qty.focus({ preventScroll: true });
    plus.disabled = off;
  } else {
    group.removeAttribute("data-uid");
    context.textContent = "";
    if (!record.holdAddFocus && group.contains(focused) && editorSearchCanAct(ac)) addButton.focus({ preventScroll: true });
  }
}

function syncEditorSearchQuantities(ac) {
  if (!editorSearchResultsCurrent(ac)) return;
  for (const slot of ac.list.querySelectorAll(".ac-actions")) syncSearchQuantity(slot.searchQuantity);
}
