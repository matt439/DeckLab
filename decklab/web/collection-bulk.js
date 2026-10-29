/* Card list bulk condition/language review (E7-S29, E7-S18): every filtered row or an explicitly
 * selected subset of printing keys, saved as one change (POST /api/collection/bulk). By default only
 * blanks are filled; quantities, names and notes stay unchanged. A selected review never widens
 * after a filter, refresh or conflict. Shared with collection-rows.js and collection.js. */
"use strict";

// rules.merge_rows' note on a row whose merged copies didn't share a condition or language.
const COL_MERGED_NOTE = "Merged copies have differing or unreported";
const COL_BULK_FIELDS = ["language", "condition"];    // the order the summary names them

/** The Card list's button (where the visitor may change this collection), or null. */
function colBulkButton(cv) {
  if (!cv.editable) return null;
  cv.bulkButton = el("button", { type: "button", class: "btn col-mutate col-bulk-open", text: "Set condition & language…",
    onclick: () => openBulkSheet(cv) });
  return cv.bulkButton;
}

/** The subset action is separate from the unchanged whole-filter action. */
function colBulkSelectionTools(cv) {
  if (!cv.editable || !seesInventory(cv.space) || !canEditSpace(cv.space)) return null;
  cv.bulkSelected = new Set();
  cv.bulkSelectedButton = el("button", { type: "button", class: "btn col-mutate col-bulk-selected", hidden: true,
    onclick: (event) => {
      if (colBulkActionCurrent(cv, event.currentTarget)) openBulkSheet(cv, true);
    } });
  cv.bulkClear = el("button", { type: "button", class: "btn btn-quiet col-mutate col-bulk-clear", text: "Clear selection", hidden: true,
    onclick: (event) => {
      if (!colBulkActionCurrent(cv, event.currentTarget)) return;
      cv.bulkSelected.clear(); cv.bulkSelectionNotice = "";
      colBulkSync(cv, colShownRows(cv));
      if (cv.bulkButton && !cv.bulkButton.hidden) cv.bulkButton.focus();
    } });
  cv.bulkSelectionCount = el("span", { class: "sub col-bulk-selection-count", role: "status" });
  return el("div", { class: "col-bulk-selection-tools" }, cv.bulkSelectedButton, cv.bulkClear, cv.bulkSelectionCount);
}

function colBulkActionCurrent(cv, control) {
  return colActive(cv) && cv.editable && seesInventory(cv.space) && canEditSpace(cv.space)
    && !cv.busy && control?.isConnected && !control.disabled && !control.hidden
    && cv.root?.contains(control) && !document.querySelector("dialog[open]") && !keyboardMenuOpen();
}

/** Native checkbox changes retain focus and mirror the one subset across both responsive row trees. */
function colBulkRowChoice(cv, row) {
  if (!cv.editable || !seesInventory(cv.space) || !canEditSpace(cv.space)) return null;
  const key = colBulkKey(row), revision = cv.sha256, rows = cv.rows;
  const input = el("input", { type: "checkbox", class: "col-mutate col-bulk-check", "data-bulk-key": key,
    "aria-label": `Select ${row.name} (${colPrinting(row)}) for batch changes`,
    onchange: () => {
      const current = colBulkActionCurrent(cv, input) && cv.list?.contains(input)
        && cv.sha256 === revision && cv.rows === rows && colShownRows(cv).some(item => colBulkKey(item) === key);
      if (!current) { input.checked = !!cv.bulkSelected?.has(key); return; }
      if (input.checked) cv.bulkSelected.add(key); else cv.bulkSelected.delete(key);
      cv.bulkSelectionNotice = "";
      colBulkSync(cv, colShownRows(cv));
    } });
  input.checked = !!cv.bulkSelected?.has(key);
  return el("label", { class: "col-bulk-row-choice" }, input,
    el("span", { class: "sr-only", text: `Select ${row.name} (${colPrinting(row)})` }));
}

/** A filter/refresh can remove selections; it never restores them or adds newly matching rows. */
function colBulkSync(cv, shown) {
  if (!cv.bulkButton) return;
  cv.bulkButton.hidden = !shown.length;
  const words = `Set condition & language. ${plural(shown.length, "row")} shown`;
  cv.bulkButton.textContent = words;
  cv.bulkButton.setAttribute("aria-label", words);
  if (!cv.bulkSelected) return;
  const allowed = cv.editable && seesInventory(cv.space) && canEditSpace(cv.space);
  if (!allowed) cv.bulkSelected.clear();
  const keys = new Set(shown.map(colBulkKey));
  const before = cv.bulkSelected.size;
  for (const key of cv.bulkSelected) if (!keys.has(key)) cv.bulkSelected.delete(key);
  const dropped = before - cv.bulkSelected.size;
  if (dropped) cv.bulkSelectionNotice = `${plural(dropped, "selection")} cleared because those rows are no longer shown.`;
  const count = cv.bulkSelected.size;
  cv.bulkSelectedButton.hidden = !allowed || !count; cv.bulkClear.hidden = !allowed || !count;
  cv.bulkSelectionCount.hidden = !allowed;
  cv.bulkSelectedButton.textContent = `Set condition & language: ${num(count)} selected`;
  cv.bulkSelectedButton.setAttribute("aria-label", `Set condition and language on ${plural(count, "selected row")}`);
  cv.bulkSelectionCount.textContent = `${num(count)} of ${plural(shown.length, "shown row")} selected.`
    + (cv.bulkSelectionNotice ? ` ${cv.bulkSelectionNotice}` : "");
  for (const input of cv.list?.querySelectorAll(".col-bulk-check") || []) {
    input.checked = cv.bulkSelected.has(input.getAttribute("data-bulk-key"));
  }
  colLocationBatchSync(cv, shown);
}

/** A language code's name ("English"), or the code itself. */
function colLanguageWord(code) {
  const found = COL_LANGUAGES.find(([v]) => v === code);
  return found ? found[1] : code;
}

/** What Save would do to rows: wanted {condition?, language?}; onlyBlank: leave rows that have one.
 * Returns {fields: [{key, value, changing, kept}], rows (those it changes)}. */
function colBulkPlan(rows, wanted, onlyBlank) {
  const changing = new Set();
  const fields = [];
  for (const key of COL_BULK_FIELDS) {
    const value = wanted[key];
    if (!value) continue;
    let count = 0, kept = 0;
    for (const row of rows) {
      const now = String(row[key] || "");
      if (now === value || (onlyBlank && now)) { kept += 1; continue; }
      count += 1;
      changing.add(row);
    }
    fields.push({ key, value, changing: count, kept });
  }
  return { fields, rows: rows.filter((row) => changing.has(row)) };
}

/** "Sets language English on 91 rows and condition NM on 60 rows; 31 already have a condition." */
function colBulkWords(plan, onlyBlank) {
  if (!plan.fields.length) return "Choose a condition, a language or both.";
  const word = (f) => f.key === "language" ? colLanguageWord(f.value) : f.value;
  const sets = plan.fields.filter((f) => f.changing).map((f) => `${f.key} ${word(f)} on ${plural(f.changing, "row")}`);
  const kept = plan.fields.filter((f) => f.kept).map((f) => onlyBlank
    ? `${num(f.kept)} already ${f.kept === 1 ? "has" : "have"} a ${f.key}` : `${num(f.kept)} already ${word(f)}`);
  if (!sets.length) return `Nothing to change: ${kept.join("; ")}.`;
  return `Sets ${sets.join(" and ")}${kept.length ? `; ${kept.join("; ")}` : ""}.`;
}

/** The sheet: Condition and Language (each "Leave as is" to start), Only fill in blanks, and what Save does. */
function openBulkSheet(cv, selected = false) {
  if (!colActive(cv) || cv.busy || !cv.editable
      || (selected && (!seesInventory(cv.space) || !canEditSpace(cv.space)))) return null;
  const sheet = colOpenSheet("Set condition & language");
  const id = (key) => `col-bulk-${key}-${sheet.heading.id}`;
  const rows = colShownRows(cv).filter(row => !selected || cv.bulkSelected?.has(colBulkKey(row)));
  const ctx = { cv, sheet, busy: false, rows, narrowed: "", selected, reviewSha: cv.sha256,
    keys: selected ? new Set(rows.map(colBulkKey)) : null };
  ctx.selectionList = el("ul", { class: "col-bulk-selected-list", hidden: !selected, tabindex: 0,
    "aria-label": "Selected printing rows" });
  const redraw = () => drawBulkSheet(ctx);
  ctx.condition = colSegmented([["", "As is", "Leave as is"], ...COL_CONDITIONS.filter(([v]) => v)], "", redraw, "Condition");
  ctx.language = el("select", { id: id("language"), onchange: redraw },
    el("option", { value: "", text: "Leave as is" }), COL_LANGUAGES.filter(([v]) => v).map(([v, t]) => el("option", { value: v, text: `${t} (${v})` })));
  ctx.language.value = "";
  ctx.onlyBlank = el("input", { type: "checkbox", id: id("blank"), onchange: redraw });
  ctx.onlyBlank.checked = true;
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.scope = el("p", { class: "sub col-bulk-scope" });
  ctx.merged = el("div", { class: "col-bulk-merged" });
  ctx.summary = el("p", { class: "col-bulk-summary", role: "status", "aria-live": "polite" });
  ctx.fields = el("fieldset", { class: "col-bulk-fields" }, el("legend", { class: "sr-only", text: "What to set" }),
    el("div", { class: "field col-field-condition" }, el("span", { text: "Condition" }), ctx.condition),
    el("label", { class: "field col-field-language", for: ctx.language.id }, el("span", { text: "Language" }), ctx.language),
    el("label", { class: "choice col-bulk-blank", for: ctx.onlyBlank.id }, ctx.onlyBlank,
      el("span", { text: "Only fill in blanks (rows that already have one keep it)" })));
  sheet.body.append(el("div", { class: "col-form col-bulk" }, ctx.message, ctx.scope, ctx.selectionList, ctx.fields, ctx.merged, ctx.summary));
  drawBulkSheet(ctx);
  return ctx;
}

/** A row's identity key, as one string. */
function colBulkKey(row) {
  return `${row.set}|${row.collector_number}|${row.finish}`;
}

/** The name of a filter that was on before a refresh (filters: [unrecordedOnly, storageOnly]) and is off now, or "". */
function colBulkCleared(filters, cv) {
  if (filters[0] && !cv.unrecordedOnly) return "Condition or language not recorded";
  if (filters[1] && !cv.storageOnly) return "In storage only";
  return "";
}

/** While a save is on its way the choices are locked, so the sheet keeps saying what is being sent. */
function colBulkBusy(ctx, busy) {
  ctx.busy = busy;
  setCollectionBusy(ctx.cv, busy);
  ctx.fields.disabled = busy;
  for (const control of [...ctx.condition.querySelectorAll("button"), ctx.language, ctx.onlyBlank]) control.disabled = busy;
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = busy;
}

function colBulkWanted(ctx) {
  const wanted = {};
  if (ctx.condition.value) wanted.condition = ctx.condition.value;
  if (ctx.language.value) wanted.language = ctx.language.value;
  return wanted;
}

/** The scope, the merged-copies note, the summary and the Save button, for the sheet's choices now. */
function drawBulkSheet(ctx) {
  const cv = ctx.cv;
  const rows = ctx.rows;
  const all = (cv.rows || []).length;
  ctx.selectionList.hidden = !ctx.selected || !rows.length;
  if (!rows.length) {
    // Only after a refresh that left none of them: nothing to choose for.
    ctx.scope.textContent = ctx.selected ? "None of the selected rows are still shown. Close this, then select rows again."
      : "No rows are shown now: close this, then change the search or filters.";
    clear(ctx.selectionList);
    ctx.fields.hidden = true;
    clear(ctx.merged);
    ctx.summary.textContent = "";
    sheetActions(ctx.sheet, [{ text: "Close", value: "cancel", onclick: () => ctx.sheet.close() }]);
    return;
  }
  ctx.fields.hidden = false;
  ctx.scope.textContent = ctx.selected ? `For the ${plural(rows.length, "selected row")} listed below. Copies, names and notes don't change.`
    : ctx.narrowed ? `For the ${plural(rows.length, "row")} it was opened on that are still listed.`
      + " Copies, names and notes don't change." : `For the ${plural(rows.length, "row")} shown${rows.length < all ? ` (of ${num(all)}, after the search and filters)` : ""}.`
      + " Copies, names and notes don't change.";
  clear(ctx.selectionList);
  if (ctx.selected) ctx.selectionList.append(...rows.map(row => el("li", { "data-selected-key": colBulkKey(row), text:
    `${row.name} (${colPrinting(row)}), ${plural(Number(row.quantity), "copy", "copies")}; `
      + `${row.condition || "condition not recorded"}, ${row.language ? colLanguageWord(row.language) : "language not recorded"}` })));
  const merged = rows.filter((row) => String(row.notes || "").includes(COL_MERGED_NOTE)).length;
  clear(ctx.merged);
  if (merged) {
    ctx.merged.append(el("p", { class: "box box-info", text: `${plural(merged, "row")} ${merged === 1 ? "holds copies whose" : "hold copies whose"}`
      + " conditions or languages differed when they were merged (the notes say so). A value set here covers every copy"
      + " in the row; the notes stay as they are." }));
  }
  const onlyBlank = ctx.onlyBlank.checked;
  const plan = colBulkPlan(rows, colBulkWanted(ctx), onlyBlank);
  ctx.summary.textContent = colBulkWords(plan, onlyBlank);
  const count = plan.rows.length;
  sheetActions(ctx.sheet, [
    { text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() },
    { text: count ? `Save ${plural(count, "row")}` : "Save", kind: "primary", value: "save", disabled: !count || ctx.busy,
      onclick: () => saveBulk(ctx) }]);
}

/** Refresh a selected review from current rows without admitting a new printing key. */
function colBulkRebaseSelected(ctx) {
  const previous = ctx.rows.length;
  ctx.rows = colShownRows(ctx.cv).filter(row => ctx.keys.has(colBulkKey(row)) && ctx.cv.bulkSelected?.has(colBulkKey(row)));
  ctx.keys = new Set(ctx.rows.map(colBulkKey));
  ctx.reviewSha = ctx.cv.sha256;
  return previous - ctx.rows.length;
}

function colBulkSelectionReview(ctx, dropped = 0) {
  clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" },
    dropped ? el("p", { text: `${plural(dropped, "selected row")} no longer shown ${dropped === 1 ? "was" : "were"} left out.` }) : null,
    el("p", { text: "Nothing was saved. Check the current selected rows and what Save will do, then save again." })));
  drawBulkSheet(ctx);
  if (colActive(ctx.cv) && !ctx.sheet.closed && (!document.activeElement?.isConnected || document.activeElement === document.body)) {
    const button = ctx.sheet.foot.querySelector("button:not([disabled])") || ctx.sheet.foot.querySelector("button");
    if (button) button.focus();
  }
}

async function saveBulk(ctx) {
  const cv = ctx.cv;
  if (ctx.busy || ctx.sheet.closed || !colActive(cv) || cv.busy || !cv.editable
      || (ctx.selected && (!seesInventory(cv.space) || !canEditSpace(cv.space)))) return;
  if (ctx.selected) {
    const shown = colShownRows(cv).filter(row => ctx.keys.has(colBulkKey(row)) && cv.bulkSelected?.has(colBulkKey(row)));
    if (ctx.reviewSha !== cv.sha256 || shown.length !== ctx.rows.length) {
      colBulkSelectionReview(ctx, colBulkRebaseSelected(ctx));
      return;
    }
  }
  const wanted = colBulkWanted(ctx);
  const onlyBlank = ctx.onlyBlank.checked;
  const plan = colBulkPlan(ctx.rows, wanted, onlyBlank);
  if (!plan.rows.length) return;
  colBulkBusy(ctx, true);
  clear(ctx.message).append(loadingBox(`Saving ${plural(plan.rows.length, "row")}…`));
  try {
    const answer = await apiWrite("/api/collection/bulk", { space: cv.space, sha256: cv.sha256, ...wanted, only_blank: onlyBlank,
      keys: plan.rows.map((row) => ({ set: row.set, collector_number: row.collector_number, finish: row.finish })) });
    const what = wanted.condition && wanted.language ? "Condition and language" : wanted.condition ? "Condition" : "Language";
    colBulkBusy(ctx, false);
    if (ctx.selected) for (const key of ctx.keys) cv.bulkSelected?.delete(key);
    ctx.sheet.close();
    colChanged(cv, answer, answer.changed ? `${what} saved on ${plural(answer.changed, "row")}.` : "Nothing needed changing.");
    // The dialog gave focus back to the button, which is hidden when no rows are shown now: the search keeps it.
    if (colActive(cv) && !document.querySelector("dialog[open]")) {
      const focused = document.activeElement;
      if (ctx.selected && cv.bulkSelectedButton?.hidden
          && (focused === cv.bulkSelectedButton || focused === document.body || !focused?.isConnected)) {
        const target = cv.bulkButton && !cv.bulkButton.hidden ? cv.bulkButton : cv.rowSearch;
        if (target) target.focus();
      } else if (!ctx.selected && cv.bulkButton?.hidden) {
        const search = cv.root && cv.root.querySelector("#col-row-search");
        if (search) search.focus();
      }
    }
  } catch (error) {
    colBulkBusy(ctx, false);
    if (ctx.sheet.closed || !colActive(cv)) return;
    if (error.status === 409 && error.data && Array.isArray(error.data.rows)) {
      // Someone changed the collection meanwhile: show the latest rows, and what Save would do to them now.
      const filters = [cv.unrecordedOnly, cv.storageOnly];
      cv.sha256 = error.data.sha256;
      colTakeRows(cv, error.data);
      if (cv.kind === "rows") drawColRowList(cv);
      if (ctx.selected) {
        colBulkSelectionReview(ctx, colBulkRebaseSelected(ctx));
        return;
      }
      ctx.narrowed = colBulkCleared(filters, cv) || ctx.narrowed;
      if (ctx.narrowed) {
        // A filter the latest list can't offer was turned off: Save never widens to rows it wasn't opened on.
        const opened = new Set(ctx.rows.map(colBulkKey));
        ctx.rows = colShownRows({ ...cv, unrecordedOnly: false, storageOnly: false }).filter((row) => opened.has(colBulkKey(row)));
      } else {
        ctx.rows = colShownRows(cv);
      }
      clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", { text: error.message }),
        ctx.narrowed ? el("p", { text: `The "${ctx.narrowed}" filter no longer applies to the latest list, so Save still`
          + " covers only the rows this was opened on that are still listed." }) : null,
        el("p", { text: "Nothing was saved. The list is the latest now: check what Save will do, then save again." })));
      drawBulkSheet(ctx);
      return;
    }
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message })));
    drawBulkSheet(ctx);
  }
}
