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
  ed.consideringMoves = [];
  if (ed.version === "owned" && editorPromotionAvailable(ed)) {
    ed.planned = copyList(ed.view.lists.target);
    ed.base.planned = copyList(ed.view.lists.target);
  }
}
function editorConsideringChanged(ed = editor) {
  return !!(ed?.mode === "edit" && Array.isArray(ed.considering)
    && (!Array.isArray(ed.base?.considering)
      || editorConsideringSignature(ed.considering) !== editorConsideringSignature(ed.base.considering)));
}
function editorConsideringSnapshot(ed) {
  return Array.isArray(ed.considering) ? { considering: ed.considering.map(l => ({ ...sendLine(l), card: l.card })),
    ...(ed.planned ? { planned: keepList(ed.planned) } : {}), consideringMoves: ed.consideringMoves || [],
    promotionReview: !!ed.promotionReview, promotionAccepted: ed.promotionAccepted || null,
    promotionAcknowledged: ed.promotionAcknowledged || null, promotionUnavailable: !!ed.promotionUnavailable } : {};
}
function editorConsideringBase(ed) {
  return { ...(Array.isArray(ed.base.considering) ? { considering: ed.base.considering.map(sendLine) } : {}),
    ...(ed.base.planned ? { planned: sendList(ed.base.planned) } : {}) };
}
function editorConsideringDraft(saved) {
  const out = {};
  for (const key of ["considering", "planned", "consideringMoves", "promotionReview", "promotionAccepted", "promotionAcknowledged", "promotionUnavailable"]) {
    if (Object.hasOwn(saved, key)) out[key] = saved[key];
  }
  return out;
}
function restoreEditorConsidering(ed, saved) {
  // Missing in an old draft means keep the fetched list; an explicit empty array means clear it.
  if (!Array.isArray(saved?.considering) || ed.mode !== "edit") return;
  ed.considering = editorConsideringCopy(saved.considering);
  if (ed.version === "owned" && saved.planned) ed.planned = copyList(saved.planned);
  ed.consideringMoves = Array.isArray(saved.consideringMoves) ? saved.consideringMoves : [];
  ed.promotionReview = !!saved.promotionReview;
  ed.promotionAccepted = saved.promotionAccepted || null;
  ed.promotionAcknowledged = saved.promotionAcknowledged || null;
  ed.promotionUnavailable = !!saved.promotionUnavailable;
  if (ed.promotionUnavailable && ed.view?.lists?.target != null && Array.isArray(ed.view.lists.considering)) {
    ed.promotionUnavailable = false; ed.promotionReview = true; ed.promotionAcknowledged = null;
  }
  if (ed.planned && ed.view?.lists?.target == null) {
    ed.promotionUnavailable = true;
    if (saved.base?.planned) ed.base.planned = copyList(saved.base.planned);
  }
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
  if (rebaseEditorPromotions(ed, view, mine, base, notes)) return;
  if (ed.version === "owned" && view.lists?.target) {
    ed.base.planned = copyList(view.lists.target);
    ed.planned = copyList(view.lists.target);
  }
  ed.consideringMoves = []; ed.promotionReview = false; ed.promotionAcknowledged = null; ed.promotionAccepted = null; ed.promotionUnavailable = false;
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
    && ed.tab === "cards" && ed.dom.considering?.isConnected && !ed.promoting && !ed.asking && !ed.leaving
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
  drawEditorPromotionState(ed, section);
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
  if (editorPromotionAvailable(ed)) row.append(el("div", { class: "editor-considering-moves" },
    [["Deck", "main", "Move to Planned"], ["Sideboard", "side", "Move to Planned sideboard"]].map(([section, key, label]) =>
      el("button", { type: "button", class: `btn btn-quiet editor-considering-move-${key}`, text: label,
        "aria-label": `${line.name}: ${label}`, onclick: (event) => {
          if (current()) promoteEditorConsidering(ed, line, section, row, event.currentTarget);
        } }))));
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
  fillEditorPlannedCards(answer, sent);
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
  markEditorPlannedRows(ed);
}
function editorConsideringReview(body, answer) {
  if (!answer.changes?.considering && !editor.promotionReview) return;
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

// A promotion is one linked change to Planned and Considering, even from a Play-now editor.
function editorPromotionAvailable(ed = editor) {
  return editorConsideringSupported(ed) && ed.view?.lists?.target != null && !ed.promotionUnavailable;
}
function editorPlannedList(ed = editor) { return ed.version === "target" ? ed.lists : ed.planned; }
function editorPromotionChanged(ed = editor) {
  return !!(ed?.mode === "edit" && ed.version === "owned" && ed.planned
    && (!ed.base.planned || listSignature(ed.planned) !== listSignature(ed.base.planned)));
}
function editorPromotionPair(target, considering) {
  return { target: sendList(target || {}), considering: (considering || []).map(sendLine) };
}
function editorPromotionSignature(pair) {
  return JSON.stringify([listSignature(pair.target), editorConsideringSignature(pair.considering)]);
}
function editorPromotionReviewKey(ed = editor) {
  return JSON.stringify([ed.sha256, editorPromotionSignature(editorPromotionPair(editorPlannedList(ed), ed.considering))]);
}
function editorPromotionReviewNeeded(ed = editor) {
  return !!ed.promotionReview && ed.promotionAcknowledged !== editorPromotionReviewKey(ed);
}
function addEditorPromotionBody(body, ed = editor) {
  if (editorPromotionChanged(ed) && !ed.promotionUnavailable) (body.lists || (body.lists = {})).target = sendList(ed.planned);
}
function editorHasLinkedPromotion(ed, mine, base) {
  if (!Array.isArray(mine.consideringMoves) || !mine.consideringMoves.length) return false;
  const target = ed.version === "target" ? mine.lists : mine.planned;
  const was = ed.version === "target" ? base.lists : base.planned;
  return !was || !Array.isArray(base.considering)
    || editorPromotionSignature(editorPromotionPair(target, mine.considering)) !== editorPromotionSignature(editorPromotionPair(was, base.considering));
}

/** Match copy capacities, most-specific printings first. Missing set/number may be filled; supplied
 * printing, finish and category may not change, and normalization may not lose or invent copies. */
function editorPromotionFaithful(proposed, checked) {
  const sections = new Set([...Object.keys(proposed || {}), ...Object.keys(checked || {})]);
  for (const section of sections) {
    const left = (checked?.[section] || []).map(l => ({ ...l, remaining: l.qty }));
    const ordered = [...(proposed?.[section] || [])].sort((a, b) => Number(!!b.set) + Number(!!b.number) - Number(!!a.set) - Number(!!a.number));
    for (const line of ordered) {
      let need = line.qty;
      for (const found of left) {
        if ((line.card?.name || line.name).toLowerCase() !== found.name.toLowerCase()
            || (line.category || "") !== (found.category || "") || (line.finish || "nonfoil") !== (found.finish || "nonfoil")
            || line.set && line.set.toLowerCase() !== found.set || line.number && line.number !== found.number) continue;
        const take = Math.min(need, found.remaining); need -= take; found.remaining -= take;
        if (!need) break;
      }
      if (need) return false;
    }
    if (left.some(l => l.remaining)) return false;
  }
  return true;
}

function editorPromotionMessage(ed, text) {
  ed.promotionError = text;
  const root = ed.dom.considering;
  if (!root?.isConnected) return;
  let note = root.querySelector(".editor-promotion-error");
  if (!note) { note = el("p", { class: "box box-warn editor-promotion-error", role: "alert" }); root.append(note); }
  note.textContent = text;
}

/** Validate the complete proposed pair first. Until it answers for this exact draft, neither list
 * changes. New-printing overflows and unknown names are refused by the normal authoritative checker. */
async function promoteEditorConsidering(ed, line, section, row, button) {
  if (!editorConsideringMutable(ed) || !editorPromotionAvailable(ed) || !["Deck", "Sideboard"].includes(section)
      || !row.isConnected || !ed.dom.considering.contains(row) || editorConsideringLine(ed, line.uid) !== line) return false;
  if (!Number.isInteger(line.qty) || line.qty < 1 || line.qty > MAX_COPIES) {
    editorPromotionMessage(ed, "Choose 1 to 99 copies before moving this alternative."); return false;
  }
  const owner = editorWriteOwner(ed), root = ed.dom.considering, before = snapshot(ed), sha = ed.sha256;
  const target = copyList(editorPlannedList(ed));
  const promoted = newLine(line);
  (target[section] || (target[section] = [])).push(promoted);
  const considering = ed.considering.filter(l => l !== line);
  const body = draftBody();
  body.lists = { ...(body.lists || {}), target: sendList(target), considering: considering.map(sendLine) };
  const current = () => owner() && root === ed.dom.considering && root.isConnected && row.isConnected
    && root.contains(row) && ed.tab === "cards" && ed.sha256 === sha && !document.querySelector("dialog[open]")
    && !keyboardMenuOpen() && snapshot(ed) === before && editorConsideringLine(ed, line.uid) === line;
  ed.promoting = true;
  if (button) busy(button, "Checking...");
  drawBar();
  let answer;
  try {
    answer = await apiWrite("/api/deck/check", body);
    if (!current()) return false;
    if (answer.file_changed) { editorPromotionMessage(ed, "The deck changed. Load the latest version before moving this alternative."); return false; }
    if (answer.blocks?.length) { editorPromotionMessage(ed, answer.blocks.map(b => b.problem).join(" ")); return false; }
    if (!answer.lists?.target || !Array.isArray(answer.lists.considering)
        || !editorPromotionFaithful(target, answer.lists.target)
        || !editorPromotionFaithful({ Deck: considering }, { Deck: answer.lists.considering })) {
      editorPromotionMessage(ed, "This move would change a printing, finish or category, or merge away copies. The alternative has been kept; choose matching rows before moving it.");
      return false;
    }
    // Pin checked defaults only after fidelity passes: inventory changes before Save must not
    // reselect a different printing or finish for the newly playable cards.
    const validatedTarget = copyList(answer.lists.target);
    if (ed.version === "target") ed.lists = validatedTarget;
    else ed.planned = validatedTarget;
    ed.considering = considering;
    ed.consideringMoves = [...(ed.consideringMoves || []), { source: sendLine(line), section }];
    ed.promotionAccepted = { local: editorPromotionSignature(editorPromotionPair(validatedTarget, considering)),
      pair: editorPromotionPair(answer.lists.target, answer.lists.considering) };
    ed.promotionAcknowledged = null;
    ed.promotionError = null;
    ed.promoting = false;
    syncSections(); drawEditor(); changed({ list: false });
    ed.dom.considering?.querySelector(".editor-considering-add")?.focus();
    return true;
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (current()) editorPromotionMessage(ed, e.message);
    return false;
  } finally {
    ed.promoting = false;
    if (button?.isConnected && button.dataset.busy) unbusy(button);
    if (owner()) drawBar();
  }
}

/** Pending linked moves never use quantity deltas against a newer Planned list. Identical accepted
 * outcomes are already applied; a divergent pair requires review of the complete replacement. */
function rebaseEditorPromotions(ed, view, mine, base, notes) {
  if (!Array.isArray(mine.consideringMoves) || !mine.consideringMoves.length) return false;
  const mineTarget = ed.version === "target" ? mine.lists : mine.planned;
  const baseTarget = ed.version === "target" ? base.lists : base.planned;
  const pair = editorPromotionPair(mineTarget, mine.considering);
  const old = editorPromotionPair(baseTarget, base.considering);
  const local = editorPromotionSignature(pair), was = editorPromotionSignature(old);
  if (baseTarget && Array.isArray(base.considering) && local === was) return false;
  const available = view.lists?.target != null && Array.isArray(view.lists.considering);
  const latest = available ? editorPromotionPair(view.lists.target, view.lists.considering) : null;
  const accepted = mine.promotionAccepted;
  const applied = latest && (editorPromotionSignature(latest) === local || accepted?.pair && accepted.local === local
    && editorPromotionSignature(latest) === editorPromotionSignature(accepted.pair));
  const chosenTarget = applied ? view.lists.target : mineTarget;
  const chosenConsidering = applied ? view.lists.considering : mine.considering;
  if (ed.version === "target") {
    ed.lists = copyList(chosenTarget);
    ed.base.lists = copyList(available ? view.lists.target : baseTarget);
  } else {
    ed.planned = copyList(chosenTarget);
    if (available || baseTarget) ed.base.planned = copyList(available ? view.lists.target : baseTarget);
  }
  ed.considering = editorConsideringCopy(chosenConsidering);
  if (available || Array.isArray(base.considering)) ed.base.considering = editorConsideringCopy(available ? view.lists.considering : base.considering);
  ed.consideringMoves = applied ? [] : mine.consideringMoves;
  ed.promotionUnavailable = !available;
  ed.consideringUnavailable = !available;
  ed.promotionReview = !applied && available && (mine.promotionReview || !baseTarget || !Array.isArray(base.considering)
    || editorPromotionSignature(latest) !== was);
  ed.promotionAccepted = applied ? null : accepted;
  ed.promotionAcknowledged = null;
  if (!available) notes.push("The linked Planned and Considering move is kept on this device. Reload both lists before saving.");
  else if (ed.promotionReview) notes.push("Planned or Considering changed in the latest version too. Your complete linked draft is kept; review both replacement lists before saving.");
  return true;
}

function drawEditorPromotionState(ed, section) {
  if (ed.promotionError) editorPromotionMessage(ed, ed.promotionError);
  if (ed.promotionUnavailable) section.append(el("p", { class: "box box-warn", text: "The linked move is kept on this device. Reload both lists before saving." }));
  if (!editorPromotionChanged(ed)) return;
  const lines = el("div", { class: "editor-planned-lines" });
  for (const [name, rows] of Object.entries(ed.planned)) rows.forEach(line => lines.append(el("p", {
    class: "editor-planned-row", "data-planned-uid": line.uid, text: `${sectionTitle(name)}: ${line.qty} ${line.name} (${printingText(line)})${line.category ? ` · ${line.category}` : ""}` })));
  section.append(el("details", { class: "more editor-planned-draft" }, el("summary", { text: "Planned changes awaiting Save" }),
    el("p", { class: "sub", text: "These changes belong to Planned. This Play-now list stays as it is." }), lines));
  markEditorPlannedRows(ed);
}
function fillEditorPlannedCards(answer, sent) {
  if (!sent.planned || !answer.lists?.target || answer.blocks?.some(b => b.list === "target")) return;
  for (const [section, uids] of Object.entries(sent.planned)) {
    if (answer.lists.target[section]?.length !== uids.length) continue;
    uids.forEach((uid, i) => {
    const line = editor.planned?.[section]?.find(l => l.uid === uid), found = answer.lists.target[section]?.[i];
    if (line && !line.card && found?.card && found.name.toLowerCase() === line.name.toLowerCase()) line.card = found.card;
    });
  }
}
function markEditorPlannedRows(ed) {
  const root = ed.dom.considering;
  if (!root) return;
  root.querySelectorAll(".editor-planned-row").forEach(row => {
    row.classList.remove("is-blocked"); row.querySelectorAll(".edit-block").forEach(node => node.remove());
  });
  for (const block of ed.check?.blocks || []) {
    if (ed.version !== "owned" || block.list !== "target" || block.index == null) continue;
    const uid = ed.sent.planned?.[block.section]?.[block.index];
    const row = uid && root.querySelector(`[data-planned-uid="${uid}"]`);
    if (row) {
      row.classList.add("is-blocked"); row.append(el("span", { class: "edit-block", text: block.problem }));
      root.querySelector(".editor-planned-draft")?.setAttribute("open", "");
    }
  }
}
function editorPromotionReview(body, answer, sheet) {
  const ed = editor;
  if (editorPromotionChanged(ed) || ed.promotionReview) {
    const target = answer.lists?.target && !answer.blocks?.some(b => b.list === "target") ? answer.lists.target : editorPlannedList(ed);
    const rows = Object.entries(target).flatMap(([section, lines]) => lines.map(l => el("li", {
      text: `${sectionTitle(section)}: ${l.qty} ${l.name} (${printingText(l)})${l.category ? ` · ${l.category}` : ""}` })));
    body.append(el("h3", { text: "Planned will be saved as:" }), rows.length ? el("ul", { class: "review-list" }, rows)
      : el("p", { text: "No cards: clears Planned." }));
  }
  if (!ed.promotionReview) return false;
  const key = editorPromotionReviewKey(ed), current = editorWriteOwner(ed, sheet);
  const input = el("input", { type: "checkbox", class: "editor-promotion-ack" });
  const control = { input, body };
  sheet.promotionReviewControl = control;
  input.checked = !editorPromotionReviewNeeded(ed);
  input.addEventListener("change", () => {
    if (!input.isConnected || sheet.body !== body || !body.contains(input) || sheet.promotionReviewControl !== control
        || !current() || key !== editorPromotionReviewKey(ed) || ed.saving || ed.promoting) {
      input.checked = !!ed.promotionReview && !editorPromotionReviewNeeded(ed);
      return;
    }
    ed.promotionAcknowledged = input.checked ? key : null;
    const save = sheet.foot.querySelector('[data-action="save"]');
    if (save) save.disabled = !!answer.blocks?.length || editorPromotionReviewNeeded(ed);
  });
  body.append(el("div", { class: "box box-warn" }, el("h3", { text: "Review the complete linked move" }),
    el("p", { text: "The latest Planned or Considering list changed too. Saving replaces both with the complete lists shown here; review any latest changes before continuing." }),
    el("label", {}, input, " I reviewed both complete lists and want to save this draft.")));
  return editorPromotionReviewNeeded(ed);
}
