/* Undo of 1-50 token-card rows' edited values (E11-S08): every row's recorded values back in place,
   together, by stable id; no selection, reason or confirmation. */
"use strict";

const ACTIVITY_UNDO_TOKEN_WORDS = { front: "Front", back: "Back", set: "Set", front_collector_number: "Front collector number",
  back_collector_number: "Back collector number", finish: "Finish", quantity: "Quantity (physical cards)", front_details: "Front details",
  back_details: "Back details", notes: "Notes" };

function activityUndoTokenEditEvidence(data) {
  const label = row => row.back ? row.front + " / " + row.back : row.front, ids = new Set();
  if (Object.keys(data).sort().join(",") !== "action,available,expect,id,kind,label,row_count,rows,space"
      || data.kind !== "tokens" || data.action !== "token_batch_update"
      || !Number.isSafeInteger(data.row_count) || data.row_count < 1 || data.row_count > 50
      || !Array.isArray(data.rows) || data.rows.length !== data.row_count
      || data.label !== "Updates to " + data.row_count + " token-card row" + (data.row_count > 1 ? "s" : "")) return false;
  for (const item of data.rows) {
    if (!item || typeof item !== "object" || Object.keys(item).sort().join(",") !== "current,fields,label,restored,token_row_id"
        || !Number.isSafeInteger(item.token_row_id) || item.token_row_id < 1 || ids.has(item.token_row_id)
        || !activityUndoRow(item.current, "tokens") || !activityUndoRow(item.restored, "tokens") || item.label !== label(item.current)) return false;
    ids.add(item.token_row_id);
    const changed = ACTIVITY_UNDO_FIELDS.tokens.filter(field => item.current[field] !== item.restored[field]);
    if (!changed.length || !Array.isArray(item.fields) || item.fields.length !== changed.length
        || item.fields.some((field, index) => !field || typeof field !== "object" || Object.keys(field).sort().join(",") !== "after,before,field"
          || field.field !== changed[index] || field.before !== item.current[field.field] || field.after !== item.restored[field.field])) return false;
  }
  return true;
}

function activityUndoTokenEditReceipt(answer, preview) {
  if (!answer || answer.saved !== true || answer.source_id !== preview.id || answer.expect !== preview.expect
      || Object.keys(answer).sort().join(",") !== "action,expect,kind,restored_rows,revision,row_count,saved,sha256,source_id,space,summary"
      || answer.kind !== "tokens" || answer.space !== preview.space || answer.action !== "token_batch_update" || answer.row_count !== preview.row_count
      || typeof answer.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(answer.sha256)
      || typeof answer.revision !== "string" || !answer.revision.trim() || typeof answer.summary !== "string" || !answer.summary.trim()
      || !Array.isArray(answer.restored_rows) || answer.restored_rows.length !== preview.row_count) return false;
  const expected = new Map(preview.rows.map(item => [item.token_row_id, item.restored])), seen = new Set();
  for (const item of answer.restored_rows) {
    if (!item || typeof item !== "object" || Object.keys(item).sort().join(",") !== "row,token_row_id" || !activityUndoRow(item.row, "tokens")) return false;
    const row = expected.get(item.token_row_id);
    if (!row || seen.has(item.token_row_id) || ACTIVITY_UNDO_FIELDS.tokens.some(field => item.row[field] !== row[field])) return false;
    seen.add(item.token_row_id);
  }
  return seen.size === expected.size;
}

/** The review: each row's printing and every changed value, details and notes as literal text. */
function activityUndoTokenEditBody(body, preview, text) {
  const one = preview.row_count === 1;
  const printing = row => [row.set ? row.set.toUpperCase() + " " + [row.front_collector_number, row.back_collector_number].filter(Boolean).join("/") : "Printing not recorded",
    row.finish || "finish not recorded", plural(row.quantity, "physical card")].join(" · ");
  const literal = field => ["front_details", "back_details", "notes"].includes(field) ? "activity-undo-note" : null;
  const rows = preview.rows.map(item => el("section", { class: "panel activity-undo-batch-row" }, el("h4", { text: item.label }),
    el("p", { class: "sub", text: printing(item.current) }),
    item.fields.map(field => el("p", {}, el("b", { text: ACTIVITY_UNDO_TOKEN_WORDS[field.field] + ": " }),
      el("span", { class: literal(field.field), text: text(field.before) }), " → ", el("span", { class: literal(field.field), text: text(field.after) })))));
  body.append(el("p", { class: "sub", text: one
      ? "Review the token-card row below. Its recorded values will be restored in place in one new audited change; the original change stays in Activity."
      : "Review all " + plural(preview.row_count, "token-card row") + " below. Their recorded values will be restored together, in place, in one new audited change; the original change stays in Activity. There is no partial selection." }),
    el("p", { class: "sub", text: (one ? "The row is" : "Each row is") + " checked again when you save, with the packed token cards in deck boxes and products. No token card is added or removed." }),
    el("div", { class: "panels" }, rows));
}
