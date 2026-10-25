/* Advisory collection guards. All prompts leave the original form intact; the save API rechecks
 * held copies and binds an explicit override to the exact change and inventory revision. */
"use strict";

const colSheets = new Set();

function colOpenSheet(title, opts = {}) {
  const sheet = openSheet(title, { ...opts, onClose: result => {
    colSheets.delete(sheet);
    if (opts.onClose) opts.onClose(result);
  } });
  colSheets.add(sheet);
  return sheet;
}

/** Raw filenames, reasons and held decks belong to the viewer who opened the sheet. */
function colCloseSheets() {
  for (const sheet of [...colSheets].reverse()) if (!sheet.closed) sheet.close();
  colSheets.clear();
}

function askCollectionChoice(title, paragraphs, choices) {
  return new Promise(resolve => {
    const sheet = colOpenSheet(title, { onClose: result => resolve(result == null ? null : result) });
    sheet.body.append(...paragraphs.map(text => el("p", { text })));
    sheetActions(sheet, choices.map(choice => ({ ...choice, onclick: () => sheet.close(choice.value) })));
  });
}

function colReasonControl(sheet) {
  const input = el("input", { id: `col-reason-${sheet.heading.id}`, type: "text", maxlength: 200, autocomplete: "off",
    placeholder: "e.g. sold, traded, entered twice" });
  const node = el("div", { class: "col-reason" },
    el("label", { class: "field", for: input.id }, el("span", { text: "Why (optional)" }), input),
    el("div", { class: "actions" }, ["Sold", "Traded"].map(text => el("button", { type: "button", class: "btn btn-quiet", text,
      onclick: () => { input.value = text.toLowerCase(); } }))));
  return { node, input };
}

function askCollectionReduction(row, next = null, title = null) {
  return new Promise(resolve => {
    const removed = next && next.name === row.name ? Number(row.quantity) - Number(next.quantity) : Number(row.quantity);
    const sheet = colOpenSheet(title || (next ? `Reduce ${row.name}?` : `Remove ${row.name} ×${row.quantity}?`),
      { onClose: result => resolve(result == null ? null : result) });
    const reason = colReasonControl(sheet);
    sheet.body.append(el("p", { text: next
      ? `${removed} ${removed === 1 ? "copy" : "copies"} of ${row.name} (${colPrinting(row)}) ${removed === 1 ? "comes" : "come"} out of the collection.`
      : `${row.name} (${colPrinting(row)}) ×${row.quantity} comes out of the collection. To remove only some copies, lower the quantity instead.` }), reason.node);
    sheetActions(sheet, [
      { text: "Keep it", onclick: () => sheet.close(null) },
      { text: next ? "Save reduction" : "Remove", kind: "danger btn-primary", onclick: () => sheet.close({ reason: reason.input.value.trim() }) }]);
  });
}

/** Only an edit that reduces physical copies asks why. A printing correction at the same quantity
 * keeps every copy; changing a name removes the old card's copies even if the new quantity is larger. */
async function colReductionReason(ctx, body) {
  if (body.action !== "edit" || Object.hasOwn(body, "reason")) return body;
  const old = ctx.cv.rows?.find(row => colKey(row) === colKey(body.original));
  if (!old || (old.name === body.row.name && Number(body.row.quantity) >= Number(old.quantity))) return body;
  const choice = await askCollectionReduction(old, body.row);
  return choice ? { ...body, reason: choice.reason } : null;
}

function askCollectionInUse(warnings, action) {
  return new Promise(resolve => {
    const sheet = colOpenSheet("Copies in use", { onClose: result => resolve(result === true) });
    for (const warning of warnings) {
      if (warning.message) { sheet.body.append(el("p", { class: "box box-warn", text: warning.message })); continue; }
      sheet.body.append(el("div", { class: "box box-warn" },
        el("p", { text: `${warning.name}: ${warning.after} owned after this change; ${warning.in_use} in use (${warning.shortage} short).` }),
        el("ul", {}, warning.holders.map(holder => el("li", {}, `${holder.qty} × in `,
          el("a", { href: deckHref(holder.id), text: holder.title }))))));
    }
    sheet.body.append(el("p", { text: "Take these cards out of the deck or break up the intact product first. You can continue if the collection records need correcting. Update the out-of-date deck tables afterwards to show the shortage." }));
    sheetActions(sheet, [{ text: "Keep the collection", onclick: () => sheet.close(false) },
      { text: action === "remove" ? "Remove anyway" : "Save anyway", kind: "danger btn-primary", onclick: () => sheet.close(true) }]);
  });
}

function colRepeatImportWarning(repeats) {
  if (!repeats?.length) return null;
  return el("div", { class: "box box-warn col-import-repeat" },
    el("h3", { text: "This file was already imported" }),
    el("ul", {}, repeats.map(item => el("li", { text: `${item.name}: ${item.imported_at ? "imported on " + item.imported_at : "import date not recorded"}; ${item.imported_by ? "by " + item.imported_by : "importer not recorded"}.` }))),
    el("p", { text: "Importing it again adds these copies again. Continue only if these are additional physical copies; the repeat will be recorded in the change history." }));
}
