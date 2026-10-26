/* Arrival checks retain their component-wide verification; row targets are saved context only. */
"use strict";

function orderCheckRowLabel(kind, row, number) {
  const name = kind === "tokens" ? [row.front, row.back].filter(Boolean).join(" // ") : row.name;
  const printing = kind === "tokens" ? [row.front_collector_number, row.back_collector_number].filter(Boolean).join("/") : row.collector_number;
  return `Row ${number}: ${row.quantity} x ${name || "Name not recorded"} — ${row.set ? row.set.toUpperCase() : "Set not recorded"} ${printing || "number not recorded"} — ${row.finish || "finish not recorded"}`;
}

function orderCheckTargeting(component, rows) {
  return component?.status === "pending" && ["cards", "tokens"].includes(component.kind)
    && component.check_targeting?.available === true && /^[a-f0-9]{64}$/.test(component.check_targeting.payload_sha256 || "")
    && Array.isArray(rows) && rows.length > 0 && Array.from(rows).every(row => row && typeof row === "object" && !Array.isArray(row))
    && Array.isArray(component.check_targeting.row_sha256s) && component.check_targeting.row_sha256s.length === rows.length
    && Array.from(component.check_targeting.row_sha256s).every(sha => typeof sha === "string" && /^[a-f0-9]{64}$/.test(sha));
}

/** The server has already proved the original payload row. Never rebuild proof from edited rows or drafts. */
function rcptCheckTargets(comp) {
  const source = comp.c, targets = source.check_targets;
  if (!orderCheckTargeting(source, source.rows) || !Array.isArray(targets) || targets.length !== source.checks.length) return null;
  for (let i = 0; i < targets.length; i++) {
    if (!Object.hasOwn(targets, i)) return null;
    const target = targets[i];
    if (target === null) continue;
    if (!target || typeof target !== "object" || Array.isArray(target) || !Number.isSafeInteger(target.row)
        || target.row < 1 || target.row > source.rows.length || !/^[a-f0-9]{64}$/.test(target.row_sha256 || "")
        || target.row_sha256 !== source.check_targeting.row_sha256s[target.row - 1]) return null;
  }
  return targets;
}

function rcptRowChecks(comp, row) {
  const targets = rcptCheckTargets(comp);
  if (!targets || !Number.isSafeInteger(row.orig) || row.orig < 0 || row.orig >= comp.c.rows.length) return [];
  return targets.flatMap((target, i) => target?.row === row.orig + 1 ? [{number: i + 1, text: comp.c.checks[i]}] : []);
}

/** Repeated split pieces show the same original-row context, never another verification control. */
function rcptRowCheckStrip(comp, row) {
  const checks = rcptRowChecks(comp, row);
  if (!checks.length) return null;
  return el("div", {class: "rcpt-row-checks"},
    el("p", {class: "field-hint", text: "Arrival checks for the original recorded order row. Verify them in To check for this whole part; split pieces share these checks."}),
    el("p", {class: "sub", text: orderCheckRowLabel(comp.kind, comp.c.rows[row.orig], row.orig + 1)}),
    el("ul", {}, checks.map(check => el("li", {text: `Check ${check.number}: ${check.text}`}))));
}

function shopCheckTargetReceipt(answer, body, context) {
  const target = answer.targeted_check;
  if (!body.target) {
    if (target !== undefined && target !== null) throw new Error("The check's row association was unexpected. Preview the change again.");
    return;
  }
  const parts = Array.isArray(answer.checks) ? answer.checks.filter(part => part?.component === body.component) : [];
  if (!target || target.component !== body.component || target.text !== body.add?.[0]
      || !Number.isSafeInteger(target.check) || target.check !== context?.nextCheck || target.row !== body.target.row
      || target.payload_sha256 !== body.target.payload_sha256 || !context || target.row_sha256 !== context.rowShas[target.row - 1])
    throw new Error("The check's original order row could not be confirmed. Preview the change again.");
  if (parts.length !== 1 || !Array.isArray(parts[0].checks) || parts[0].checks[target.check - 1] !== target.text)
    throw new Error("The added check could not be confirmed. Preview the change again.");
}

function shopCheckTargetPreview(answer, context) {
  const target = answer.targeted_check;
  if (!target || !context || target.component !== context.component || !Number.isSafeInteger(target.row)
      || target.row < 1 || target.row > context.rows.length) return null;
  return el("section", {class: "shop-order-check-target"}, el("h4", {text: "Check associated with this original order row"}),
    el("p", {text: orderCheckRowLabel(context.kind, context.rows[target.row - 1], target.row)}),
    el("p", {text: target.text}), el("p", {class: "field-hint", text: "Verification still applies to the whole delivery part."}));
}
