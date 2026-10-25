/* The Card list's "Set condition & language…" (E7-S29): one condition and/or language for every row the
 * search and filters show, saved as one change (POST /api/collection/bulk). By default only blanks are
 * filled in; quantities, names and notes never change, so no copies are reduced and nothing asks why.
 * Shared with collection.js (colBulkButton, colBulkSync). */
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

/** After the list is drawn: the button shows only while rows are shown, and says how many it acts on. */
function colBulkSync(cv, shown) {
  if (!cv.bulkButton) return;
  cv.bulkButton.hidden = !shown.length;
  cv.bulkButton.setAttribute("aria-label", `Set condition & language on the ${plural(shown.length, "row")} shown`);
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
function openBulkSheet(cv) {
  if (!colActive(cv) || cv.busy || !cv.editable) return null;
  const sheet = colOpenSheet("Set condition & language");
  const id = (key) => `col-bulk-${key}-${sheet.heading.id}`;
  const ctx = { cv, sheet, busy: false, rows: colShownRows(cv), narrowed: "" };
  const redraw = () => drawBulkSheet(ctx);
  ctx.condition = colSegmented([["", "As is", "Leave as is"], ...COL_CONDITIONS.filter(([v]) => v)], "", redraw, "Condition");
  ctx.language = el("select", { id: id("language"), onchange: redraw },
    el("option", { value: "", text: "Leave as is" }), COL_LANGUAGES.filter(([v]) => v).map(([v, t]) => el("option", { value: v, text: t })));
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
  sheet.body.append(el("div", { class: "col-form col-bulk" }, ctx.message, ctx.scope, ctx.fields, ctx.merged, ctx.summary));
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
  if (!rows.length) {
    // Only after a refresh that left none of them: nothing to choose for.
    ctx.scope.textContent = "No rows are shown now: close this, then change the search or filters.";
    ctx.fields.hidden = true;
    clear(ctx.merged);
    ctx.summary.textContent = "";
    sheetActions(ctx.sheet, [{ text: "Close", value: "cancel", onclick: () => ctx.sheet.close() }]);
    return;
  }
  ctx.fields.hidden = false;
  ctx.scope.textContent = ctx.narrowed ? `For the ${plural(rows.length, "row")} it was opened on that are still listed.`
    + " Copies, names and notes don't change." : `For the ${plural(rows.length, "row")} shown${rows.length < all ? ` (of ${num(all)}, after the search and filters)` : ""}.`
    + " Copies, names and notes don't change.";
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

async function saveBulk(ctx) {
  const cv = ctx.cv;
  if (ctx.busy || ctx.sheet.closed || !colActive(cv)) return;
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
    ctx.sheet.close();
    colChanged(cv, answer, answer.changed ? `${what} saved on ${plural(answer.changed, "row")}.` : "Nothing needed changing.");
    // The dialog gave focus back to the button, which is hidden when no rows are shown now: the search keeps it.
    if (colActive(cv) && cv.bulkButton && cv.bulkButton.hidden) {
      const search = cv.root && cv.root.querySelector("#col-row-search");
      if (search) search.focus();
    }
  } catch (error) {
    if (ctx.sheet.closed || !colActive(cv)) return;
    colBulkBusy(ctx, false);
    if (error.status === 409 && error.data && Array.isArray(error.data.rows)) {
      // Someone changed the collection meanwhile: show the latest rows, and what Save would do to them now.
      const filters = [cv.unrecordedOnly, cv.storageOnly];
      cv.sha256 = error.data.sha256;
      colTakeRows(cv, error.data);
      if (cv.kind === "rows") drawColRowList(cv);
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
