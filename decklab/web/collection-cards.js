/* Collection row editing, printing choices and conflict recovery; shared with collection.js. */
"use strict";

/** Ask before removing a row, with an optional reason (it goes into the change history). Resolves with
 * {reason} or null. */
function askRemoveCollectionRow(row, title) {
  return askCollectionReduction(row, null, title);
}

async function removeCollectionRow(cv, row) {
  if (!colActive(cv) || cv.busy || !cv.editable) return;
  const choice = await askRemoveCollectionRow(row);
  if (!choice || !colActive(cv) || cv.busy) return;
  let target = row;
  let confirmation = null;
  for (;;) {
    const seq = ++cv.seq;
    setCollectionBusy(cv, true);
    clear(cv.message).append(loadingBox(`Removing ${target.name}…`));
    try {
      await colEnsureRows(cv);
      if (!colActive(cv) || seq !== cv.seq) return;
      const body = { space: cv.space, sha256: cv.sha256, action: "remove",
        row: { ...colBase(target), quantity: Number(target.quantity) },
        original: { set: target.set, collector_number: target.collector_number, finish: target.finish } };
      if (choice.reason) body.reason = choice.reason;
      if (confirmation) body.confirm_in_use = confirmation;
      const answer = await apiWrite("/api/collection/save", body);
      if (!colActive(cv) || seq !== cv.seq) return;
      colChanged(cv, answer, `${target.name} removed.`);
      return;
    } catch (error) {
      if (!colActive(cv) || seq !== cv.seq) return;
      setCollectionBusy(cv, false);
      if (error.status === 409 && error.data?.in_use && error.data.confirm_in_use) {
        const proceed = await askCollectionInUse(error.data.in_use, "remove");
        if (!proceed || !colActive(cv) || seq !== cv.seq) { if (colActive(cv)) colSay(cv, "Nothing removed."); return; }
        confirmation = error.data.confirm_in_use;
        continue;
      }
      if (error.status !== 409 || !error.data || !Array.isArray(error.data.rows)) {
        colSay(cv, error.message);
        return;
      }
      cv.sha256 = error.data.sha256;
      colTakeRows(cv, error.data);
      if (cv.kind === "rows") drawColRowList(cv);
      const now = cv.rows.find((r) => colKey(r) === colKey(target));
      if (!now) { colSay(cv, "Already removed: someone removed it since you opened the list."); return; }
      const changed = !colSameRow(colBase(now), colBase(target));
      clear(cv.message);
      const again = await askCollectionChoice("The collection changed after you opened it", [error.message,
        changed ? `${now.name} was changed meanwhile: ${colChangedWords(colBase(target), colBase(now))}.` : "That row is still there as it was.",
        "Nothing was removed yet."],
      [{ text: `Remove ${now.name} ×${now.quantity} as it is now`, kind: "primary", value: "again" }, { text: "Keep it", value: null }]);
      if (again !== "again" || !colActive(cv)) return;
      target = now;
      confirmation = null;
    }
  }
}


// ------------------------------------------------------ the add and edit sheet

/** Add a card, or edit a row (row: a rows answer's row). The name comes with suggestions; the printing
 * is picked from a strip of the card's printings (GET /api/printings, with their pictures), then its
 * finish. Editing, Remove sits at the bottom. opts.name: the name a new card starts with. */
function openCollectionSheet(cv, row = null, opts = {}) {
  if (!colActive(cv) || cv.busy || !cv.editable || opts.repair && !opts.repair.here()) return null;
  const editing = Boolean(row);
  const sheet = colOpenSheet(editing ? row.name : `Add a card to ${colWhose(cv.space)}`, { wide: true });
  const ctx = { cv, sheet, row, editing, base: row ? colBase(row) : null, busy: false, printings: [], chosen: -1, nameSeq: 0,
    printSeq: 0, suggestTimer: 0, stripFilter: "", boxRepair: opts.repair || null };
  ctx.form = el("form", { class: "col-form", novalidate: true,
    onsubmit: (event) => { event.preventDefault(); saveCollectionSheet(ctx); } });
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.form.append(ctx.message, colFields(ctx, row || (opts.name ? { name: opts.name } : null)));
  sheet.body.append(ctx.form);
  boxCollectionEditorNote(ctx);
  // Editing: Save, and Remove at the bottom (the sheet's × closes it); adding: Cancel and Add.
  sheetActions(sheet, [
    editing ? null : { text: "Cancel", value: "cancel", onclick: () => sheet.close() },
    { text: editing ? "Save" : "Add", kind: "primary", value: "save", onclick: () => saveCollectionSheet(ctx) },
    ctx.boxRepair ? { text: "Review listed copies", onclick: () => {
      if (!ctx.busy && !sheet.closed && boxCollectionEditorHere(ctx)) boxCollectionAfterSheet(sheet, () => boxCollectionEditorHere(ctx),
        () => openCopiesSheet(cv, name, { repair: ctx.boxRepair }));
    } } : null,
    editing ? { text: "Remove…", kind: "danger btn-quiet", value: "remove", onclick: () => {
      if (ctx.boxRepair) {
        if (!ctx.busy && !sheet.closed && boxCollectionEditorHere(ctx)) boxCollectionAfterSheet(sheet, () => boxCollectionEditorHere(ctx),
          () => removeCollectionRow(cv, row));
      } else { sheet.close(); removeCollectionRow(cv, row); }
    } } : null]);
  const name = row ? row.name : opts.name;
  if (name) loadColPrintings(ctx, name, row);
  else colFillFinishes(ctx);
  (editing || name ? ctx.inputs.quantity : ctx.inputs.name).focus();
  return ctx;
}

function colFields(ctx, row) {
  const id = (key) => `col-${key}-${ctx.sheet.heading.id}`;
  const value = (key) => row && row[key] != null ? String(row[key]) : "";
  ctx.datalist = el("datalist", { id: id("names") });
  const name = el("input", { id: id("name"), type: "text", maxlength: 150, value: value("name"), autocomplete: "off",
    list: id("names"), spellcheck: "false", autocapitalize: "words", placeholder: "Start typing a card name" });
  const quantity = el("input", { id: id("quantity"), class: "col-qty-input", type: "number", inputmode: "numeric", min: 1,
    max: 9999, step: 1, value: ctx.row ? String(ctx.row.quantity) : "1", "aria-label": "Copies" });
  const step = (by) => { quantity.value = String(Math.min(9999, Math.max(1, (parseInt(quantity.value, 10) || 0) + by))); };
  const language = el("select", { id: id("language") }, COL_LANGUAGES.map(([v, t]) => el("option", { value: v, text: v ? `${t} (${v})` : t })));
  language.value = value("language");
  const languageNow = value("language");
  if (languageNow && !COL_LANGUAGES.some(([o]) => o === languageNow)) {
    language.append(el("option", { value: languageNow, text: `${languageNow} (as recorded)` }));
    language.value = languageNow;
  }
  // A condition written by hand that isn't one of the choices stays as it is.
  const conditionNow = value("condition");
  const conditions = COL_CONDITIONS.some(([v]) => v === conditionNow) ? COL_CONDITIONS
    : [...COL_CONDITIONS, [conditionNow, conditionNow, "As recorded"]];
  const condition = colSegmented(conditions, conditionNow, null, "Condition");
  ctx.finishBox = el("div", { class: "col-finish" });
  ctx.strip = el("div", { class: "col-strip-area" }, el("p", { class: "sub", text: "Choose the card first." }));
  ctx.picture = el("div", { class: "col-sheet-picture" });
  ctx.inputs = { name, quantity, condition, language,
    notes: el("input", { id: id("notes"), type: "text", maxlength: COL_NOTES_MAX, value: value("notes"), autocomplete: "off" }) };
  ctx.printingNote = el("small", { class: "field-hint", "aria-live": "polite" });
  name.addEventListener("input", () => colSuggestNames(ctx));
  name.addEventListener("change", () => loadColPrintings(ctx, name.value));
  const field = (key, label, input, ...after) => el("label", { class: `field col-field-${key}`, for: input.id },
    el("span", { text: label }), input, ...after);
  return el("div", { class: "col-fields" }, ctx.datalist, ctx.picture,
    el("div", { class: "col-field-name col-name-row" },
      field("name", "Card name", name),
      el("button", { type: "button", class: "btn col-sheet-mutate", text: "Find its printings",
        onclick: () => loadColPrintings(ctx, name.value) })),
    el("div", { class: "field col-field-printing", role: "group", "aria-labelledby": id("printing-label") },
      el("span", { id: id("printing-label"), text: "Printing" }), ctx.strip, ctx.printingNote),
    el("div", { class: "field col-field-finish" }, el("span", { text: "Finish" }), ctx.finishBox),
    el("div", { class: "field col-field-quantity" }, el("label", { for: quantity.id, text: "Copies" }),
      el("div", { class: "stepper col-stepper" },
        el("button", { type: "button", class: "step", "aria-label": "One fewer", onclick: () => step(-1) }, "−"),
        quantity,
        el("button", { type: "button", class: "step", "aria-label": "One more", onclick: () => step(1) }, "+"))),
    el("div", { class: "field col-field-condition" }, el("span", { text: "Condition" }), condition),
    field("language", "Language", language),
    field("notes", "Notes", ctx.inputs.notes));
}

/** Card names for the name box (the editor's search), a moment after typing stops. */
function colSuggestNames(ctx) {
  clearTimeout(ctx.suggestTimer);
  const q = ctx.inputs.name.value.trim();
  if (q.length < 2) return;
  ctx.suggestTimer = setTimeout(async () => {
    const seq = ++ctx.nameSeq;
    try {
      const answer = await api(`/api/cards/search?q=${encodeURIComponent(q)}&limit=8`);
      if (seq !== ctx.nameSeq || ctx.sheet.closed || !boxCollectionEditorHere(ctx)) return;
      clear(ctx.datalist).append(...(answer.cards || []).map((c) => el("option", { value: c.name })));
    } catch (e) { /* suggestions are a help only; the printing lookup says what's wrong */ }
  }, 200);
}

/** A printings answer as [{set, set_name, collector_number, finishes, released, img_small}], whichever shape
 * it came in (GET /api/printings, or the editor's /api/cards/printings with a row per finish). */
function colPrintingList(answer) {
  const out = [];
  for (const p of (answer && answer.printings) || []) {
    const number = p.collector_number ?? p.number;
    const finishes = Array.isArray(p.finishes) ? p.finishes : p.finish ? [p.finish] : ["nonfoil"];
    const same = out.find((o) => o.set === p.set && o.collector_number === number);
    if (same) { for (const f of finishes) if (!same.finishes.includes(f)) same.finishes.push(f); continue; }
    out.push({ set: p.set, set_name: p.set_name || "", collector_number: number, finishes: [...finishes],
      released: p.released || "", img_small: p.img_small || null });
  }
  return out;
}

/** Look up a name's printings and draw the strip (keeping a row's own when editing). */
async function loadColPrintings(ctx, typed, keep = null) {
  if (!boxCollectionEditorHere(ctx)) return;
  const name = String(typed || "").trim();
  if (!name) return;
  const seq = ++ctx.printSeq;
  clear(ctx.strip).append(loadingBox("Looking up its printings…"));
  ctx.printingNote.textContent = "";
  let answer;
  try {
    try {
      answer = await api(`/api/printings?name=${encodeURIComponent(name)}`);
    } catch (e) {
      if (!boxCollectionEditorHere(ctx)) return;
      // An older server has only the editor's printing picker.
      if (!(e instanceof ApiError) || e.status !== 404 || /card/i.test(e.message)) throw e;
      answer = await api(`/api/cards/printings?name=${encodeURIComponent(name)}`);
    }
  } catch (error) {
    if (seq !== ctx.printSeq || ctx.sheet.closed || !boxCollectionEditorHere(ctx)) return;
    // A name that isn't a card's (400, 404) is an empty answer; anything else failed, and may work again.
    const unknown = error instanceof ApiError && (error.status === 400 || error.status === 404);
    clear(ctx.strip).append(unknown ? el("p", { class: "sub", text: "No printings found. Check the spelling." })
      : loadFailed("Its printings", error, () => loadColPrintings(ctx, ctx.inputs.name.value, keep)));
    ctx.printingNote.textContent = ctx.boxRepair ? "Close this review and search Collection for the exact card manually."
      : unknown ? error.message : "";
    ctx.printings = [];
    ctx.chosen = -1;
    colFillFinishes(ctx);
    return;
  }
  if (seq !== ctx.printSeq || ctx.sheet.closed || !boxCollectionEditorHere(ctx)) return;
  if (ctx.boxRepair && !boxCollectionPrintings(answer, ctx.boxRepair.difference.name)) {
    ctx.printings = []; ctx.chosen = -1; colFillFinishes(ctx);
    clear(ctx.strip).append(el("p", { class: "sub", text: "The exact card name couldn't be checked. Close this sheet and search Collection manually." }));
    return;
  }
  if (answer.name && answer.name !== ctx.inputs.name.value) ctx.inputs.name.value = answer.name;   // Scryfall's exact name
  ctx.printings = colPrintingList(answer);
  const current = keep || (ctx.row && ctx.row.name === answer.name ? ctx.row : null);
  if (!ctx.boxRepair && current && current.set && !ctx.printings.some((p) => p.set === current.set && p.collector_number === current.collector_number)) {
    ctx.printings.unshift({ set: current.set, set_name: "as recorded", collector_number: current.collector_number,
      finishes: [current.finish || "nonfoil"], released: "", img_small: null });
  }
  const at = current ? ctx.printings.findIndex((p) => p.set === current.set && p.collector_number === current.collector_number) : -1;
  ctx.chosen = at >= 0 ? at : ctx.printings.length === 1 ? 0 : -1;
  if (ctx.boxRepair && (!ctx.editing || at < 0)) ctx.chosen = -1;
  ctx.stripFilter = "";
  drawColStrip(ctx);
  colFillFinishes(ctx, current ? current.finish : null);
}

/** The printings as a strip of small pictures (the chosen one ticked), a "Find a set" box when there are
 * many, and "Bigger pictures…" (cards-ui.js pickPrinting). */
function drawColStrip(ctx) {
  const name = ctx.inputs.name.value.trim();
  const words = tokFold(ctx.stripFilter);
  const shown = ctx.printings.map((p, i) => [p, i]).filter(([p, i]) => i === ctx.chosen || !words
    || tokFold(`${p.set} ${p.set_name} ${p.collector_number}`).includes(words));
  const tiles = shown.map(([p, i]) => {
    const words = `${String(p.set).toUpperCase()} ${p.collector_number}`;
    return el("button", { type: "button", class: "col-strip-tile", "aria-pressed": String(i === ctx.chosen),
      title: p.set_name || null, "aria-label": `${words}${p.set_name ? `, ${p.set_name}` : ""}${p.released ? `, ${String(p.released).slice(0, 4)}` : ""}`,
      onclick: () => {
        if (ctx.boxRepair && (ctx.busy || ctx.sheet.closed || !boxCollectionEditorHere(ctx))) return;
        ctx.chosen = i; drawColStrip(ctx); colFillFinishes(ctx);
      } },
      el("span", { class: "col-strip-pic" }, p.img_small ? el("img", { src: p.img_small, alt: "", loading: "lazy", decoding: "async", width: 73, height: 102 })
        : el("span", { class: "col-strip-none", text: words })),
      el("span", { class: "col-strip-words", text: words }),
      p.released ? el("small", { text: String(p.released).slice(0, 4) }) : null);
  });
  const filter = ctx.printings.length > COL_STRIP_FILTER ? el("input", { type: "search", class: "col-strip-find",
    placeholder: "Find a set", "aria-label": "Find a set", value: ctx.stripFilter, autocomplete: "off",
    oninput: (e) => { ctx.stripFilter = e.target.value; const at = e.target.selectionStart; drawColStrip(ctx);
      const again = ctx.strip.querySelector(".col-strip-find"); if (again) { again.focus(); again.setSelectionRange(at, at); } } }) : null;
  add(clear(ctx.strip), [
    ctx.printings.length ? el("div", { class: "col-strip-tools" }, filter,
      el("button", { type: "button", class: "btn col-sheet-mutate", text: "Bigger pictures…",
        onclick: () => colPickBig(ctx, name) })) : null,
    ctx.printings.length ? el("div", { class: "col-strip", role: "group", "aria-label": `Printings of ${name}` }, tiles)
      : emptyBox("No printings found. Check the card's name.", el("button", { type: "button", class: "btn",
        text: "Change the name", onclick: () => { if (!ctx.sheet.closed) ctx.inputs.name.focus(); } }))]);
  const chosen = ctx.strip.querySelector('[aria-pressed="true"]');
  if (chosen && chosen.scrollIntoView) chosen.scrollIntoView({ block: "nearest", inline: "center" });
  colSheetPicture(ctx);
}

/** The bigger printing picker (cards-ui.js pickPrinting): its choice becomes the strip's. */
async function colPickBig(ctx, name) {
  if (ctx.sheet.closed || !colActive(ctx.cv) || !boxCollectionEditorHere(ctx)) return;
  const p = ctx.printings[ctx.chosen];
  const finish = ctx.finishBox.querySelector('[aria-pressed="true"]');
  let picker, picked;
  try {
    picked = await pickPrinting(name, { current: p ? { set: p.set, number: p.collector_number, finish: finish ? finish.dataset.value : "nonfoil" } : null,
      onOpen: sheet => { picker = sheet; colSheets.add(sheet); } });
  } finally { if (picker) colSheets.delete(picker); }
  if (!picked || !picked.set || ctx.sheet.closed || !colActive(ctx.cv) || !boxCollectionEditorHere(ctx)) return;
  let at = ctx.printings.findIndex((o) => o.set === picked.set && o.collector_number === picked.number);
  if (at < 0) {
    ctx.printings.unshift({ set: picked.set, set_name: picked.set_name || "", collector_number: picked.number,
      finishes: [picked.finish || "nonfoil"], released: "", img_small: picked.img_small || null });
    at = 0;
  }
  ctx.chosen = at;
  drawColStrip(ctx);
  colFillFinishes(ctx, picked.finish);
}

/** The chosen printing's picture at the top of the sheet, with Zoom (the card viewer). */
function colSheetPicture(ctx) {
  const p = ctx.printings[ctx.chosen];
  clear(ctx.picture);
  if (!p || !p.img_small) return;
  const card = ctx.row && ctx.cv.pictures[colKey(ctx.row)] && p.set === ctx.row.set && p.collector_number === ctx.row.collector_number
    ? ctx.cv.pictures[colKey(ctx.row)] : null;
  const shown = card || { name: ctx.inputs.name.value.trim(), type_line: p.set_name || "", mana_cost: "",
    img_small: p.img_small, img: p.img_small.replace(/\/small$/, "/normal") };
  ctx.picture.append(el("button", { type: "button", class: "col-sheet-pic", "aria-haspopup": "dialog",
    "aria-label": `Zoom: ${shown.name}`, onclick: (e) => openCard(shown, e.currentTarget) },
  el("img", { src: p.img_small, alt: "", width: 146, height: 204 })));
}

/** The chosen printing's finishes, as a segmented choice. */
function colFillFinishes(ctx, keep = null) {
  const chosen = ctx.printings[ctx.chosen];
  const now = ctx.finishBox.querySelector('[aria-pressed="true"]');
  const wanted = keep || (now ? now.dataset.value : null);
  clear(ctx.finishBox);
  // The Finish field shows once there's a printing to have it in.
  if (ctx.finishBox.parentNode) ctx.finishBox.parentNode.hidden = !chosen;
  if (!chosen) return;
  const value = ctx.boxRepair ? keep && chosen.finishes.includes(keep) ? keep : "" : chosen.finishes.includes(wanted) ? wanted : chosen.finishes[0];
  ctx.finishBox.append(colSegmented(chosen.finishes.map((f) => [f, COL_FINISH_WORDS[f] || f]), value, null, "Finish"));
}

function colSheetBusy(ctx, busy) {
  ctx.busy = busy;
  ctx.form.setAttribute("aria-busy", String(busy));
  for (const control of ctx.form.querySelectorAll(".col-sheet-mutate")) control.disabled = busy;
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = busy;
}

function colProblem(ctx, key, words) {
  clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", { text: words })));
  const target = key === "printing" ? ctx.strip.querySelector("button") : ctx.inputs[key];
  if (target) target.focus();
  return null;
}

/** The sheet as a save's row, or null (with the problem said) when it can't be saved. */
function colFormRow(ctx) {
  const i = ctx.inputs;
  const text = (input) => String(input.value || "").replace(/\s+/g, " ").trim();
  const name = text(i.name);
  if (!name) return colProblem(ctx, "name", "Give the card's name.");
  const chosen = ctx.printings[ctx.chosen];
  if (!chosen) {
    return colProblem(ctx, ctx.printings.length ? "printing" : "name",
      ctx.printings.length ? "Choose the printing you have." : "Find the card's printings first (Find its printings).");
  }
  const quantityText = text(i.quantity);
  const quantity = Number(quantityText);
  if (quantityText === "" || !Number.isInteger(quantity) || quantity < 1 || quantity > 9999) {
    return colProblem(ctx, "quantity", "The quantity is the number of copies: a whole number from 1 to 9999.");
  }
  const finish = ctx.finishBox.querySelector('[aria-pressed="true"]');
  if (ctx.boxRepair && (!finish || !chosen.finishes.includes(finish.dataset.value)))
    return colProblem(ctx, "printing", "Choose the finish on the physical card before saving its total.");
  const row = { name, set: String(chosen.set).toLowerCase(), collector_number: String(chosen.collector_number),
    finish: (finish && finish.dataset.value) || chosen.finishes[0] || "nonfoil", quantity, condition: i.condition.value || "",
    language: i.language.value, notes: text(i.notes) };
  if (ctx.boxRepair && name !== ctx.boxRepair.difference.name) return colProblem(ctx, "name", "Keep the exact reviewed card name. Close this sheet to search for another card.");
  if (ctx.boxRepair && !ctx.editing && (ctx.cv.rows || []).some(owned => colKey(owned) === colKey(row)))
    return colProblem(ctx, "printing", "This printing is already listed. Use Review listed copies and select its row to enter the total owned quantity.");
  return row;
}

async function saveCollectionSheet(ctx) {
  if (ctx.busy || ctx.sheet.closed || !boxCollectionEditorHere(ctx)) return;
  const row = colFormRow(ctx);
  if (!row) return;
  const body = { action: ctx.editing ? "edit" : "add", row };
  if (ctx.editing) body.original = { set: ctx.row.set, collector_number: ctx.row.collector_number, finish: ctx.row.finish };
  colSheetBusy(ctx, true);
  try {
    await colEnsureRows(ctx.cv);
    if (ctx.sheet.closed || !boxCollectionEditorHere(ctx)) return;
    await colSend(ctx, body);
  } catch (error) {
    if (!ctx.sheet.closed) clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message })));
  } finally {
    if (!ctx.sheet.closed) colSheetBusy(ctx, false);
  }
}

/** Send a save; on success close the sheet and show the new list. A list changed meanwhile offers to
 * put the change back on top of the latest one. */
async function colSend(ctx, body) {
  const cv = ctx.cv;
  if (ctx.sheet.closed || !colActive(cv) || !boxCollectionEditorHere(ctx)) return;
  body = await colReductionReason(ctx, body);
  if (!body || ctx.sheet.closed || !colActive(cv) || !boxCollectionEditorHere(ctx)) return;
  clear(ctx.message).append(loadingBox("Saving…"));
  try {
    const answer = await apiWrite("/api/collection/save", { space: cv.space, sha256: cv.sha256, ...body });
    if (!boxCollectionEditorHere(ctx)) return;
    const what = `${body.row.name} (${colPrinting(body.row)})`;
    const words = answer.merged ? `${what}: added to the row already listed.`
      : `${what} ${body.action === "add" ? "added" : "saved"}.`;
    ctx.sheet.close();
    colChanged(cv, answer, words);
  } catch (error) {
    if (ctx.sheet.closed || !colActive(cv) || !boxCollectionEditorHere(ctx)) return;
    if (error.status === 409 && error.data?.in_use && error.data.confirm_in_use) {
      const proceed = await askCollectionInUse(error.data.in_use, body.action);
      if (!proceed || ctx.sheet.closed || !colActive(cv) || !boxCollectionEditorHere(ctx)) {
        if (!ctx.sheet.closed) clear(ctx.message).append(el("p", { text: "Nothing saved." }));
        return;
      }
      return colSend(ctx, { ...body, confirm_in_use: error.data.confirm_in_use });
    }
    if (error.status === 409 && error.data && Array.isArray(error.data.rows)) { showCollectionConflict(ctx, error, body); return; }
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message })));
  }
}

function showCollectionConflict(ctx, error, body) {
  const cv = ctx.cv;
  const sheet = ctx.sheet;
  cv.sha256 = error.data.sha256;
  colTakeRows(cv, error.data);
  if (cv.kind === "rows" && colActive(cv)) drawColRowList(cv);
  sheet.heading.textContent = "The collection changed after you opened it";
  clear(sheet.body).append(ctx.message);
  clear(ctx.message);
  const discard = { text: "Discard my changes", kind: "discard", value: "discard", onclick: () => sheet.close() };
  if (ctx.boxRepair) {
    sheet.body.append(el("p", { text: "Review the current listed copies before entering a total. Re-applying an old total could count copies twice or overwrite a newer count." }));
    sheetActions(sheet, [{ text: "Review listed copies", kind: "primary", onclick: () => {
      if (!sheet.closed && boxCollectionEditorHere(ctx)) boxCollectionAfterSheet(sheet, () => boxCollectionEditorHere(ctx),
        () => openCopiesSheet(cv, body.row.name, { repair: ctx.boxRepair }));
    } }, discard]);
    return;
  }
  const resend = (next) => {
    clear(sheet.body).append(ctx.message);
    sheetActions(sheet, [{ text: "Saving…", kind: "primary", value: "saving", disabled: true }]);
    return colSend(ctx, next).then(() => {
      if (!sheet.closed && sheet.foot.querySelector('[data-action="saving"]')) {
        sheetActions(sheet, [{ text: "Close", onclick: () => sheet.close() }, discard]);
      }
    });
  };
  sheet.body.append(el("div", { class: "box box-warn" }, el("p", { text: error.message })),
    el("p", { text: "Nothing was saved. Your changes are still here." }));
  if (body.action === "add") {
    sheet.body.append(el("p", { text: "Load the latest list and your card is added to it." }));
    sheetActions(sheet, [{ text: "Load the latest and add my card", kind: "primary", onclick: () => resend(body) }, discard]);
    return;
  }
  const theirs = cv.rows.find((r) => colKey(r) === colKey(body.original));
  if (!theirs) {
    sheet.body.append(el("p", { text: "It has been removed from the list since you opened it, so there's nothing left to edit." }),
      el("p", { text: `If you still have it, add it as a new card (${body.row.name} ×${body.row.quantity}). Otherwise discard your changes.` }));
    sheetActions(sheet, [{ text: `Add ${body.row.name} ×${body.row.quantity} as a new card`, kind: "primary", onclick: () => {
      ctx.editing = false;
      resend({ action: "add", row: body.row });
    } }, discard]);
    return;
  }
  const base = ctx.base || colBase(theirs);
  const now = colBase(theirs);
  if (!colSameRow(base, now)) sheet.body.append(el("p", { text: `This card was changed meanwhile: ${colChangedWords(base, now)}.` }));
  // My changes go on top of the row as it is now, field by field; where we both changed a field, I choose.
  const { row, clashes } = rebaseFields(colBase(body.row), base, now, COL_FIELDS);
  const next = () => {
    ctx.base = now;
    return { action: "edit", row: { ...row, quantity: Number(row.quantity) },
      original: { set: theirs.set, collector_number: theirs.collector_number, finish: theirs.finish },
      ...(Object.hasOwn(body, "reason") ? { reason: body.reason } : {}) };
  };
  if (!clashes.length) {
    sheet.body.append(el("p", { text: "Load the latest and your changes are put back on top of it, field by field." }));
    sheetActions(sheet, [{ text: "Load the latest and re-apply my changes", kind: "primary", onclick: () => resend(next()) }, discard]);
    return;
  }
  sheet.body.append(el("p", { text: "You both changed these. Choose which to keep:" }));
  clashes.forEach((clash, n) => {
    const name = `col-clash-${sheet.heading.id}-${n}`;
    const option = (which, value, checked) => el("label", { class: "col-choice" },
      el("input", { type: "radio", name, value: which, checked, onchange: () => { row[clash.key] = value; } }),
      el("span", { text: `${which === "mine" ? "Yours" : "Theirs"}: ${value === "" ? "(blank)" : value}` }));
    sheet.body.append(el("fieldset", { class: "col-clash" }, el("legend", { text: COL_FIELD_WORDS[clash.key] }),
      option("mine", clash.mine, true), option("theirs", clash.theirs, false)));
  });
  sheetActions(sheet, [{ text: "Save with these choices", kind: "primary", onclick: () => resend(next()) }, discard]);
}
