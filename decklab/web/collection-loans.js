/* Private loose-card loans: explicit exact printing, borrower/date and whole return. */
"use strict";

function colLoanToday() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function colLoanHere(ctx, control = null) {
  return colActive(ctx.cv) && ctx.cv.root === ctx.frame && ctx.hash === location.hash && !ctx.sheet.closed
    && ctx.sheet.dialog.isConnected && [...document.querySelectorAll("dialog[open]")].at(-1) === ctx.sheet.dialog
    && (!control || control.isConnected && ctx.sheet.dialog.contains(control) && !control.disabled);
}

async function openCollectionLoans(cv) {
  if (!colActive(cv) || cv.busy || !cv.editable || cv.unsupported) return null;
  try { await colEnsureRows(cv); }
  catch (error) { if (colActive(cv)) colSay(cv, error.message); return null; }
  if (!colActive(cv) || cv.busy) return null;
  const sheet = colOpenSheet("Loose-card loans", { wide: true });
  const ctx = { cv, sheet, frame: cv.root, hash: location.hash, busy: false, unknown: false, seq: 0, returned: false };
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.content = el("div", { class: "col-form col-loans" });
  sheet.body.append(ctx.message, ctx.content);
  await colLoanList(ctx);
  return ctx;
}

function colLoanSay(ctx, text, warning = false) {
  clear(ctx.message).append(el("p", { class: warning ? "box box-warn" : "box box-info", text }));
}

async function colLoanList(ctx, before = null) {
  if (!colLoanHere(ctx) || ctx.busy || ctx.unknown) return;
  const seq = ++ctx.seq;
  clear(ctx.content).append(loadingBox("Loading private loan records…"));
  sheetActions(ctx.sheet, [{ text: "Close", onclick: () => ctx.sheet.close() }]);
  try {
    const query = new URLSearchParams({ space: ctx.cv.space });
    if (ctx.returned) query.set("include_returned", "1");
    if (before) query.set("before", before);
    const data = await api(`/api/collection/loans?${query}`);
    if (!colLoanHere(ctx) || seq !== ctx.seq) return;
    clear(ctx.content);
    ctx.content.append(el("p", { class: "sub", text: "Borrower names and notes stay private to this collection's people. Ownership stays here; lent copies aren't free." }));
    const all = el("input", { type: "checkbox", onchange: () => { if (colLoanHere(ctx, all)) { ctx.returned = all.checked; colLoanList(ctx); } } });
    all.checked = ctx.returned;
    ctx.content.append(el("label", { class: "choice" }, all, el("span", { text: "Include returned loans" })));
    if (!data.ready) ctx.content.append(el("p", { class: "box box-info", text: "Loan records need a server update before they can be saved." }));
    if (!data.loans.length) ctx.content.append(el("p", { text: "No loans in this view." }));
    for (const loan of data.loans) {
      const item = el("section", { class: "box" },
        el("p", { text: `${plural(Number(loan.quantity), "copy", "copies")} of ${loan.name} (${colPrinting(loan)})` }),
        el("p", { text: `To ${loan.borrower} · Lent ${loan.lent_on}${loan.returned_on ? ` · Returned ${loan.returned_on}` : ""}` }));
      if (loan.notes) item.append(el("p", { class: "sub", text: loan.notes }));
      if (!loan.returned_on && data.ready) item.append(el("button", { type: "button", class: "btn", text: "Record return…",
        onclick: event => { if (colLoanHere(ctx, event.currentTarget)) colLoanReturn(ctx, loan); } }));
      ctx.content.append(item);
    }
    if (data.next) ctx.content.append(el("button", { type: "button", class: "btn", text: "Next loan records",
      onclick: event => { if (colLoanHere(ctx, event.currentTarget)) colLoanList(ctx, data.next); } }));
    sheetActions(ctx.sheet, [{ text: "Close", onclick: () => ctx.sheet.close() },
      { text: "Lend copies…", kind: "primary", disabled: !data.ready || !ctx.cv.rows.length,
        onclick: event => { if (colLoanHere(ctx, event.currentTarget)) colLoanForm(ctx); } }]);
  } catch (error) {
    if (colLoanHere(ctx) && seq === ctx.seq) {
      clear(ctx.content).append(el("button", { type: "button", class: "btn", text: "Try loan list again",
        onclick: event => { if (colLoanHere(ctx, event.currentTarget)) colLoanList(ctx); } }));
      colLoanSay(ctx, error.message, true);
    }
  }
}

function colLoanField(ctx, label, type, value, attributes = {}) {
  const id = `loan-${ctx.sheet.heading.id}-${label.toLowerCase().replace(/\W+/g, "-")}`;
  const input = el("input", { id, type, value, ...attributes });
  ctx.content.append(el("label", { class: "field", for: id }, el("span", { text: label }), input));
  return input;
}

function colLoanForm(ctx, draft = null) {
  if (!colLoanHere(ctx) || ctx.busy || ctx.unknown) return;
  clear(ctx.message); clear(ctx.content);
  ctx.mode = "lend";
  ctx.reviewSha = ctx.cv.sha256;
  ctx.content.append(el("p", { class: "box box-info", text: "Only confirmed free loose copies can be lent. Built decks, intact products and other loans are checked again on Save. Basic-land allocations aren't tracked." }));
  const id = `loan-printing-${ctx.sheet.heading.id}`;
  ctx.printing = el("select", { id }, el("option", { value: "", text: "Choose a tracked printing" }), ctx.cv.rows.map(row => el("option", { value: colKey(row),
    text: `${row.name} (${colPrinting(row)}) · ${plural(Number(row.quantity), "owned copy", "owned copies")}` })));
  ctx.printing.value = draft && ctx.cv.rows.some(row => colKey(row) === colKey(draft)) ? colKey(draft) : "";
  ctx.content.append(el("label", { class: "field", for: id }, el("span", { text: "Tracked printing" }), ctx.printing));
  ctx.quantity = colLoanField(ctx, "Copies to lend", "number", String(draft?.quantity || 1), { min: 1, max: 9999, step: 1, inputmode: "numeric" });
  ctx.borrower = colLoanField(ctx, "Borrower", "text", draft?.borrower || "", { maxlength: 80, autocomplete: "off", required: true });
  ctx.date = colLoanField(ctx, "Lent date", "date", draft?.lent_on || colLoanToday(), { required: true });
  ctx.notes = colLoanField(ctx, "Notes (optional)", "text", draft?.notes || "", { maxlength: 500, autocomplete: "off" });
  colLoanFoot(ctx, "Lend copies");
  ctx.borrower.focus();
}

function colLoanReturn(ctx, loan) {
  if (!colLoanHere(ctx) || ctx.busy || ctx.unknown) return;
  clear(ctx.message); clear(ctx.content);
  ctx.mode = "return"; ctx.loan = loan;
  ctx.content.append(el("p", { text: `Record all ${plural(Number(loan.quantity), "copy", "copies")} of ${loan.name} (${colPrinting(loan)}) returned from ${loan.borrower}.` }));
  ctx.date = colLoanField(ctx, "Return date", "date", colLoanToday(), { min: loan.lent_on, required: true });
  colLoanFoot(ctx, "Record return");
}

function colLoanFoot(ctx, text) {
  sheetActions(ctx.sheet, [{ text: "Back", onclick: event => { if (colLoanHere(ctx, event.currentTarget)) colLoanList(ctx); } },
    { text, kind: "primary", onclick: event => saveCollectionLoan(ctx, event.currentTarget) }]);
}

async function saveCollectionLoan(ctx, control) {
  if (!colLoanHere(ctx, control) || ctx.busy || ctx.unknown || ctx.cv.busy) return;
  const body = { space: ctx.cv.space };
  if (ctx.mode === "lend") {
    const row = ctx.cv.rows.find(item => colKey(item) === ctx.printing.value);
    if (!row || !ctx.borrower.value.trim() || !ctx.date.value || !/^[1-9]\d{0,3}$/.test(ctx.quantity.value)) {
      colLoanSay(ctx, "Choose a printing, a positive quantity, a borrower and the lent date.", true); return;
    }
    body.sha256 = ctx.reviewSha;
    body.row = Object.fromEntries(["name", "set", "collector_number", "finish"].map(key => [key, row[key]]));
    Object.assign(body.row, { quantity: Number(ctx.quantity.value), borrower: ctx.borrower.value.trim(),
      lent_on: ctx.date.value, notes: ctx.notes.value.trim() });
  } else { Object.assign(body, { loan_id: ctx.loan.id, returned_on: ctx.date.value }); }
  ctx.busy = true; setCollectionBusy(ctx.cv, true);
  for (const node of ctx.sheet.dialog.querySelectorAll("input, select, button")) node.disabled = true;
  try {
    const answer = await apiWrite(`/api/collection/${ctx.mode === "lend" ? "lend" : "return"}`, body);
    if (!colLoanHere(ctx)) return;
    ctx.sheet.close();
    colChanged(ctx.cv, answer, ctx.mode === "lend" ? "Loan recorded. Those copies are lent out." : "Return recorded. Those copies are free again.");
  } catch (error) {
    if (!colLoanHere(ctx)) return;
    const refused = [400, 403, 404, 409, 413, 429].includes(error.status);
    ctx.unknown = !refused;
    colLoanSay(ctx, refused ? `Nothing saved. ${error.message}`
      : "The save result couldn't be confirmed. Close this and check the loan list before recording it again.", true);
    if (ctx.unknown) sheetActions(ctx.sheet, [{ text: "Close", onclick: () => ctx.sheet.close() }]);
    else if (error.status === 409) sheetActions(ctx.sheet, [{ text: "Close", onclick: () => ctx.sheet.close() },
      { text: "Refresh collection and review", onclick: async event => {
        const control = event.currentTarget;
        if (!colLoanHere(ctx, control) || ctx.busy) return;
        const seq = ++ctx.seq;
        control.disabled = true;
        try {
          const data = await api(`/api/collection/rows?space=${encodeURIComponent(ctx.cv.space)}`);
          if (!colLoanHere(ctx) || seq !== ctx.seq) return;
          ctx.cv.sha256 = data.sha256; colTakeRows(ctx.cv, data);
          if (ctx.mode === "lend") {
            colLoanForm(ctx, body.row);
            colLoanSay(ctx, "Collection refreshed. Check the printing and copies, then lend only after reviewing them again.");
          } else colLoanList(ctx);
        } catch (refreshError) {
          if (colLoanHere(ctx) && seq === ctx.seq) colLoanSay(ctx, refreshError.message, true);
        } finally {
          if (colLoanHere(ctx) && seq === ctx.seq) control.disabled = false;
        }
      } }]);
  } finally {
    ctx.busy = false;
    if (colActive(ctx.cv)) setCollectionBusy(ctx.cv, false);
    if (colLoanHere(ctx)) for (const node of ctx.sheet.dialog.querySelectorAll("input, select, button")) node.disabled = false;
  }
}
