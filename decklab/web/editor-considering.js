/* Saved-deck alternatives in the editor. Considering is a separate draft, outside playable sections,
 * counts, availability, packing and Forge. Changes use the editor's normal check, history and save. */
"use strict";

function editorConsideringCopy(lines) { return (lines || []).map(newLine); }
function editorConsideringSignature(lines) { return listSignature({ Deck: lines || [] }); }
function editorConsideringSupported(ed = editor) {
  return !!(ed?.mode === "edit" && Array.isArray(ed.view?.lists?.considering) && !ed.consideringUnavailable);
}
function initEditorConsidering(ed) {
  if (!editorConsideringSupported(ed)) return;
  ed.considering = editorConsideringCopy(ed.view.lists.considering);
  ed.base.considering = editorConsideringCopy(ed.view.lists.considering);
}
function editorConsideringChanged(ed = editor) {
  return !!(ed?.mode === "edit" && Array.isArray(ed.considering)
    && (!Array.isArray(ed.base?.considering)
      || editorConsideringSignature(ed.considering) !== editorConsideringSignature(ed.base.considering)));
}
function editorConsideringSnapshot(ed) {
  return Array.isArray(ed.considering) ? { considering: ed.considering.map(l => ({ ...sendLine(l), card: l.card })) } : {};
}
function editorConsideringBase(ed) {
  return Array.isArray(ed.base.considering) ? { considering: ed.base.considering.map(sendLine) } : {};
}
function restoreEditorConsidering(ed, saved) {
  // Missing in an old draft means keep the fetched list; an explicit empty array means clear it.
  if (!Array.isArray(saved?.considering) || ed.mode !== "edit") return;
  ed.considering = editorConsideringCopy(saved.considering);
  if (!Array.isArray(ed.view?.lists?.considering)) {
    const knownBase = Array.isArray(saved.base?.considering) || Array.isArray(ed.base.considering);
    if (knownBase) ed.base.considering = editorConsideringCopy(saved.base?.considering || ed.base.considering);
    else delete ed.base.considering;
    ed.consideringUnavailable = !knownBase || editorConsideringChanged(ed);
  }
}

/** Whole-list three-way rebase preserves category-only edits, ordering and duplicate printing rows.
 * Concurrent edits keep this complete draft and name that choice for the subsequent review. */
function rebaseEditorConsidering(ed, view, mine, base, notes) {
  const latest = view.lists?.considering;
  const hadMine = Array.isArray(mine.considering);
  const knownBase = Array.isArray(base.considering), was = knownBase ? base.considering : undefined;
  const changedHere = hadMine && (!knownBase || editorConsideringSignature(mine.considering) !== editorConsideringSignature(was));
  if (!Array.isArray(latest)) {
    ed.consideringUnavailable = changedHere;
    if (changedHere) {
      ed.considering = editorConsideringCopy(mine.considering);
      if (knownBase) ed.base.considering = editorConsideringCopy(was);
      else delete ed.base.considering;
      notes.push("Considering could not be loaded. Your alternatives are kept on this device; reload it before saving.");
    } else { delete ed.considering; delete ed.base.considering; }
    return;
  }
  ed.consideringUnavailable = false;
  ed.base.considering = editorConsideringCopy(latest);
  ed.considering = editorConsideringCopy(changedHere ? mine.considering : latest);
  if (changedHere && editorConsideringSignature(latest) !== editorConsideringSignature(was)
      && editorConsideringSignature(latest) !== editorConsideringSignature(mine.considering)) {
    notes.push("Considering changed in the latest version too. Your complete alternatives list is kept; review it before saving.");
  }
}

function editorConsideringMutable(ed = editor, inSheet = false) {
  return editorConsideringSupported(ed) && editorKeyboardCurrent(ed) && !ed.readOnly && !ed.saving
    && ed.tab === "cards" && ed.dom.considering?.isConnected && !ed.asking && !ed.leaving
    && !keyboardMenuOpen() && (inSheet || !document.querySelector("dialog[open]"));
}
function editorConsideringLine(ed, uid) { return ed.considering?.find(l => l.uid === uid); }

function drawEditorConsidering() {
  const ed = editor, host = ed.dom.mainBody;
  if (!host || ed.tab !== "cards") return;
  ed.dom.considering?.remove();
  ed.dom.considering = null;
  if (!editorConsideringSupported(ed)) {
    if (ed.consideringUnavailable) host.append(el("p", { class: "box box-warn", text:
      "Considering could not be loaded. Your alternatives are kept on this device; reload the deck before saving." }));
    return;
  }
  const section = ed.dom.considering = el("section", { class: "edit-considering", "aria-labelledby": "h-edit-considering" },
    el("h2", { id: "h-edit-considering", text: "Considering" }),
    el("p", { class: "sub", text: "Alternatives for this deck. They stay outside its playable lists, counts and packing. Save keeps these changes with the deck." }));
  const rows = el("div", { class: "editor-considering-rows" });
  section.append(rows);
  if (!ed.considering.length) rows.append(el("p", { class: "sub", text: "No cards being considered." }));
  for (const line of ed.considering) rows.append(editorConsideringRow(ed, line));
  if (!ed.readOnly) section.append(el("button", { type: "button", class: "btn btn-quiet editor-considering-add",
    "data-focus": "considering:add", text: "Add a card to consider", onclick: (event) => {
      if (ed.dom.considering === section && section.isConnected && section.contains(event.currentTarget)) openEditorConsideringAdd(ed);
    } }));
  host.append(section);
  markEditorConsideringRows();
}

function editorConsideringCard(line) {
  return cardRow(line.card, { qty: line.qty, name: line.name, meta: line.card ? printingText(line) : undefined,
    unknownMeta: `${printingText(line)} · Card details unavailable`, viewerGroup: "editor-considering",
    caption: `${line.qty} x ${line.name}` });
}
function updateEditorConsideringCard(row, line) {
  const next = editorConsideringCard(line);
  row.consideringCard.replaceWith(next); row.consideringCard = next;
}
function editorConsideringRow(ed, line) {
  const row = el("div", { class: "editor-considering-row", "data-considering-uid": line.uid });
  row.consideringCard = editorConsideringCard(line);
  row.append(row.consideringCard);
  if (line.category) row.append(el("span", { class: "sub editor-considering-category", text: line.category }));
  if (ed.readOnly) return row;
  const input = el("input", { type: "number", class: "qty-input editor-considering-qty", min: 1, max: MAX_COPIES,
    step: 1, inputmode: "numeric", value: String(line.qty), "data-considering-uid": line.uid,
    "data-focus": `considering:${line.uid}:qty`, "aria-label": `${line.name}: copies to consider` });
  const current = () => editorConsideringMutable(ed) && row.isConnected && ed.dom.considering.contains(row)
    && editorConsideringLine(ed, line.uid) === line;
  const set = (value) => {
    if (!current() || !input.isConnected || input.editorComposing) return;
    if (!Number.isInteger(value) || value < 1 || value > MAX_COPIES) { input.value = String(line.qty); return; }
    if (line.qty === value) return;
    line.qty = value; input.value = String(value);
    // Keep the focused quantity and action controls mounted while its card caption updates.
    updateEditorConsideringCard(row, line);
    changed({ list: false });
  };
  const typed = () => {
    const value = Number(input.value);
    if (Number.isInteger(value) && value >= 1 && value <= MAX_COPIES) set(value);
  };
  input.addEventListener("input", typed);
  input.addEventListener("change", () => set(Number(input.value)));
  editorComposition(input, typed);
  const step = (delta) => el("button", { type: "button", class: "btn btn-quiet step",
    "aria-label": `${line.name}: ${delta < 0 ? "one fewer" : "one more"} to consider`, text: delta < 0 ? "−" : "+",
    onclick: () => set(Math.max(1, Math.min(MAX_COPIES, line.qty + delta))) });
  row.append(el("div", { class: "editor-considering-actions" }, step(-1), input, step(1),
    el("button", { type: "button", class: "btn btn-quiet editor-considering-remove", text: "Remove",
      "aria-label": `Remove ${line.name} from Considering`, "data-focus": `considering:${line.uid}:remove`, onclick: () => {
        if (!current()) return;
        ed.considering = ed.considering.filter(l => l.uid !== line.uid);
        drawEditorConsidering(); changed({ list: false });
        ed.dom.considering?.querySelector(".editor-considering-add")?.focus();
      } })));
  return row;
}

function openEditorConsideringAdd(ed = editor) {
  if (!editorConsideringMutable(ed)) return null;
  const section = ed.dom.considering;
  const sheet = openSheet("Add a card to consider");
  const nameId = `editor-consider-name-${sheet.heading.id}`, qtyId = `editor-consider-qty-${sheet.heading.id}`;
  const name = el("input", { id: nameId, class: "editor-considering-name", type: "text", autocomplete: "off", required: true });
  const qty = el("input", { id: qtyId, class: "editor-considering-copies", type: "number", inputmode: "numeric",
    min: 1, max: MAX_COPIES, step: 1, value: "1" });
  const message = el("p", { class: "form-error", role: "alert" });
  sheet.body.append(el("p", { class: "sub", text: "Added to this draft. Save the deck to keep it." }),
    el("label", { for: nameId, text: "Card name" }), name, el("label", { for: qtyId, text: "Copies" }), qty, message);
  const add = () => {
    if (sheet.closed || sheet.dialog.getAttribute("open") == null || keyboardDialog() !== sheet.dialog
        || !editorConsideringMutable(ed, true) || ed.dom.considering !== section || !section.isConnected) return;
    const n = Number(qty.value || 0);
    if (!name.value.trim()) { message.textContent = "Type a card's name."; name.focus(); return; }
    if (!Number.isInteger(n) || n < 1 || n > MAX_COPIES) { message.textContent = "Choose 1 to 99 copies."; qty.focus(); return; }
    ed.considering.push(newLine({ name: name.value.trim(), qty: n }));
    sheet.close(); drawEditorConsidering(); changed({ list: false });
    ed.dom.considering?.querySelector(".editor-considering-add")?.focus();
  };
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }, { text: "Add", kind: "primary", value: "add", onclick: add }]);
  return sheet;
}

/** A separate flat UID mapping: alternative errors must never mark the playable Deck[index]. */
function fillEditorConsideringCards(answer, sent) {
  const ed = editor, lines = answer.lists?.considering, uids = sent.considering;
  if (!Array.isArray(lines) || !Array.isArray(uids) || lines.length !== uids.length
      || answer.blocks?.some(b => b.list === "considering")) return;
  uids.forEach((uid, i) => {
    const line = editorConsideringLine(ed, uid), checked = lines[i];
    if (line && !line.card && checked?.card && checked.name.toLowerCase() === line.name.toLowerCase()) {
      line.card = checked.card;
      const row = ed.dom.considering?.querySelector(`[data-considering-uid="${uid}"]`);
      if (row) updateEditorConsideringCard(row, line);
    }
  });
}
function markEditorConsideringRows() {
  const ed = editor, root = ed?.dom?.considering;
  if (!root) return;
  for (const row of root.querySelectorAll(".editor-considering-row")) {
    row.classList.remove("is-blocked");
    row.querySelectorAll(".edit-block").forEach(p => p.remove());
  }
  for (const block of ed.check?.blocks || []) {
    if (block.list !== "considering" || block.index == null) continue;
    const uid = ed.sent.considering?.[block.index];
    const row = uid && root.querySelector(`[data-considering-uid="${uid}"]`);
    if (row) { row.classList.add("is-blocked"); row.append(el("p", { class: "edit-block", text: block.problem })); }
  }
}
function editorConsideringReview(body, answer) {
  if (!answer.changes?.considering) return;
  const lines = Array.isArray(answer.lists?.considering) && !answer.blocks?.some(b => b.list === "considering")
    ? answer.lists.considering : editor.considering;
  body.append(el("h3", { text: "Considering will be saved as:" }));
  body.append(lines.length ? el("ul", { class: "review-list" }, lines.map(l =>
    el("li", { text: `${l.qty} ${l.name} (${printingText(l)})${l.category ? ` · ${l.category}` : ""}` })))
    : el("p", { text: "No alternatives: clears Considering." }));
}

/** Undo recreates UIDs: recover the exact printing/category occurrence, then its nearby row or Add. */
function editorConsideringUndoFocus(ed) {
  const active = document.activeElement, root = ed.dom.considering;
  if (!editorConsideringMutable(ed) || !active?.isConnected || !root.contains(active)) return null;
  const row = active.closest(".editor-considering-row");
  const index = ed.considering.findIndex(l => String(l.uid) === row?.dataset.consideringUid);
  const key = line => JSON.stringify([lineKey(line), line.category || ""]);
  const line = ed.considering[index];
  return { active, token: routeToken, profile: ed.profile, id: ed.id, version: ed.version,
    index, key: line && key(line), occurrence: line ? ed.considering.slice(0, index).filter(l => key(l) === key(line)).length : 0,
    kind: active.matches(".editor-considering-remove") ? ".editor-considering-remove"
      : active.matches(".card-row") ? ".card-row" : ".editor-considering-qty" };
}
function restoreEditorConsideringUndoFocus(ed, saved) {
  if (!saved || !editorConsideringMutable(ed) || saved.token !== routeToken || saved.profile !== ed.profile
      || saved.id !== ed.id || saved.version !== ed.version) return;
  const active = document.activeElement;
  if (active && active !== saved.active && active !== document.body && active.isConnected) return;
  const matching = ed.considering.filter(l => JSON.stringify([lineKey(l), l.category || ""]) === saved.key);
  const line = matching[Math.min(saved.occurrence, matching.length - 1)] || ed.considering[Math.min(saved.index, ed.considering.length - 1)];
  const row = line && ed.dom.considering.querySelector(`[data-considering-uid="${line.uid}"]`);
  const target = row?.querySelector(saved.kind) || row?.querySelector(".editor-considering-qty")
    || ed.dom.considering.querySelector(".editor-considering-add");
  if (target?.isConnected && !target.disabled && !target.hidden) target.focus({ preventScroll: true });
}
