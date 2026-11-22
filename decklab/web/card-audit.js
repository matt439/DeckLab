/* A physical count against the deck or storage section as it was when scanning started. */
"use strict";

const CARD_AUDIT_TEMPORARY = "Closing clears the counted cards and this difference report.";

function cardAuditLabel(row, mode) {
  if (row.manualLabel) return row.manualLabel;
  if (mode === "deck" || row.manual) return row.canonical_name || row.name;
  return [row.name, colPrinting(row), row.finish === "nonfoil" ? "Non-foil" : ""].filter(Boolean).join(" · ");
}

/** Equal totals can hide a swap. Compare each physical identity before adding up differences. */
function cardAuditCounts(target, expected, scanned, manualCounts) {
  const { mode } = target;
  const counts = new Map();
  const excludedNames = new Set(target.excludedNames);
  const outside = new Map();
  function entry(row) {
    const key = row.manual ? JSON.stringify(["manual", row.key || row.name]) :
      mode === "deck" ? row.canonical_name || row.name : colKey(row);
    if (!counts.has(key)) counts.set(key, { label: cardAuditLabel(row, mode), expected: 0, observed: 0, estimated: false });
    return counts.get(key);
  }
  for (const row of expected) {
    const item = entry(row);
    item.expected += row.quantity;
    if (row.estimated) item.estimated = true;
  }
  for (const row of scanned) {
    const name = row.canonical_name || row.name;
    if (excludedNames.has(name)) outside.set(name, (outside.get(name) || 0) + row.quantity);
    else entry(row).observed += row.quantity;
  }
  for (const [row, observed] of manualCounts) entry(row).observed += observed;

  const result = { expected: 0, observed: 0, missing: [], extra: [], estimated: false, outside };
  for (const item of counts.values()) {
    result.expected += item.expected;
    result.observed += item.observed;
    if (item.estimated) result.estimated = true;
    if (item.expected > item.observed) result.missing.push(item);
    if (item.observed > item.expected) result.extra.push(item);
  }
  return result;
}

function startCardAudit(target) {
  if (!target.current()) return null;
  const expected = target.rows.map(row => ({ ...row }));
  const manual = expected.filter(row => row.manual);
  const onlyUnlisted = manual.length === 0;
  if (target.mode === "section") manual.push({ key: "unlisted-tokens", name: "Unlisted token cards", manual: true, quantity: 0 });
  const fields = manual.map(row => {
    const label = cardAuditLabel(row, target.mode);
    const input = el("input", { type: "text", inputmode: "numeric", autocomplete: "off", class: "col-qty-input",
      value: row.quantity === 0 ? "0" : "", "aria-label": `Counted for ${label}` });
    return { row, input, node: el("label", { class: "field" },
      el("span", { text: label }), el("span", { class: "sub", text: `${num(row.quantity)} expected` }), input) };
  });
  const persistence = target.review ? "Save the audit after reviewing the count." : CARD_AUDIT_TEMPORARY;
  const instructions = [target.instructions, persistence].filter(Boolean).join(" ");
  const ctx = openAuditScan({ ...target, instructions, finish, manualDescription: () =>
    fields.some(({ input, row }) => input.value.trim() !== (row.quantity === 0 ? "0" : ""))
      ? "Closing clears your hand counts." : "" });
  if (ctx && fields.length) {
    const group = el(onlyUnlisted ? "details" : "section", {},
      el(onlyUnlisted ? "summary" : "h3", { text: onlyUnlisted ? "Found a token card?" : "Count by hand" }),
      !onlyUnlisted ? el("p", { class: "sub", text: "Set these aside while scanning. Enter the number you found for each, including zero." }) : null,
      fields.map(field => field.node));
    ctx.sheet.body.append(group);
  }
  return ctx;

  function finish(scanned, skipped, capture) {
    const manualCounts = [];
    for (const { row, input } of fields) {
      const value = input.value.trim();
      if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value))) {
        colScanSay(capture, "warn", `Enter a whole count for ${cardAuditLabel(row, target.mode)}, including zero.`);
        const group = input.closest("details");
        if (group) group.open = true;
        input.focus();
        return;
      }
      manualCounts.push([row, Number(value)]);
    }
    const result = cardAuditCounts(target, expected, scanned, manualCounts);
    if (!Number.isSafeInteger(result.observed)) {
      colScanSay(capture, "warn", "The total is too large. Check the counts you entered.");
      return;
    }
    const review = target.review?.({ scanned, manualCounts, result, skipped }, capture);
    showCardAuditResult(capture, result, skipped, review);
  }
}

function cardAuditDifferences(title, items) {
  if (!items.length) return null;
  const quantity = items.reduce((sum, item) => sum + Math.abs(item.expected - item.observed), 0);
  return el("section", {}, el("h3", { text: `${title} (${num(quantity)})` }),
    el("ul", { class: "col-trade-list" }, items.map(item => el("li", { class: "col-trade-line" },
      el("strong", { class: "col-trade-what", text: item.label }),
      el("span", { text: `${num(item.expected)} expected${item.estimated ? " (estimate)" : ""} · ${num(item.observed)} counted` })))));
}

function showCardAuditResult(ctx, result, skipped, review) {
  const { sheet } = ctx;
  const controls = [...sheet.body.children];
  const beforeDismiss = sheet.beforeDismiss;
  ctx.auditReview = true;
  const heading = el("h3", { text: review ? "Review your count" : "Audit results", tabindex: "-1" });
  const noDiff = !result.missing.length && !result.extra.length;
  clear(sheet.body);
  add(sheet.body, [heading, ...(review ? review.content : [
    el("p", { text: `${num(result.observed)} counted · ${num(result.expected)} expected` }),
    el("p", { class: "sub", text: CARD_AUDIT_TEMPORARY }),
    skipped ? el("p", { class: "box box-warn", text: `${plural(skipped, "photo")} skipped. Only identified cards and hand counts are included.` }) : null,
    result.estimated ? el("p", { class: "sub", text: "Some expected loose counts are estimates because the copies held elsewhere are uncertain." }) : null,
    noDiff ? el("p", { class: skipped || result.estimated ? "box box-info" : "box box-good",
      text: skipped || result.estimated ? "The counted quantities match the expected quantities shown." : "All expected cards accounted for. No extras." }) : null,
    cardAuditDifferences("Missing", result.missing), cardAuditDifferences("Extra", result.extra),
    !noDiff && ctx.audit.followUpText ? el("p", { class: "sub", text: ctx.audit.followUpText }) : null]),
    result.outside.size ? el("section", {}, el("h3", { text: "Outside this audit" }),
      el("p", { class: "sub", text: "Loose quantities are unknown for these basic lands." }),
      el("ul", {}, [...result.outside].map(([name, qty]) => el("li", { text: `${num(qty)} × ${name}` })))) : null]);
  const here = event => ctx.auditReview && !ctx.busy && colScanHere(ctx) && !sheet.body.hidden &&
    event.currentTarget.isConnected && sheet.foot.contains(event.currentTarget) &&
    [...document.querySelectorAll("dialog[open]")].at(-1) === sheet.dialog;
  sheet.beforeDismiss = () => !ctx.busy;
  sheetActions(sheet, [
    { text: "Back to scanning", value: "back", onclick: event => {
      if (!here(event)) return;
      ctx.auditReview = false;
      sheet.beforeDismiss = beforeDismiss;
      sheet.body.replaceChildren(...controls);
      colScanSay(ctx, "", "");
      drawScanFoot(ctx);
      sheet.foot.querySelector('[data-action="finish"]')?.focus();
    } },
    !noDiff && ctx.audit.followUp ? { text: ctx.audit.followUp.label, value: "follow-up", onclick: event => {
      if (!here(event)) return;
      boxCollectionAfterSheet(sheet, ctx.current, ctx.audit.followUp.run);
    } } : null,
    review?.save ? { text: "Save audit", value: "save-audit", kind: "primary", onclick: event => {
      if (here(event)) review.save();
    } } : { text: "Done", value: "done", kind: "primary", onclick: event => { if (here(event)) sheet.close(); } },
  ]);
  sheet.body.scrollTop = 0;
  heading.focus();
}
