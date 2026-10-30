/* Undo of 1-50 purchase-queue rows' updated values (E11-S08): every row together, no selection. */
"use strict";

// The queue's quantity is text, so these rows have their own check rather than activityUndoRow's.
ACTIVITY_UNDO_FIELDS.watchlist = ["name", "set", "collector_number", "finish", "quantity", "for", "printing",
  "listed_aud", "listed_at", "in_stock", "checked", "notes", "state", "source"];
ACTIVITY_UNDO_EDITABLE.watchlist = [...ACTIVITY_UNDO_FIELDS.watchlist];
const ACTIVITY_UNDO_WATCHLIST_WORDS = { name: "Name", set: "Set", collector_number: "Collector number", finish: "Finish",
  quantity: "Quantity", for: "For deck", printing: "Printing preference", listed_aud: "Reference price (AUD)",
  listed_at: "Listed at", in_stock: "In stock", checked: "Checked", notes: "Notes", state: "Purchase state", source: "Source" };

function activityUndoWatchlistRow(row) {
  return Boolean(row && typeof row === "object" && !Array.isArray(row)
    && Object.keys(row).sort().join(",") === [...ACTIVITY_UNDO_FIELDS.watchlist].sort().join(",")
    && ACTIVITY_UNDO_FIELDS.watchlist.every(field => typeof row[field] === "string")
    && /^[1-9][0-9]*$/.test(row.quantity) && row.name.trim());
}

function activityUndoWatchlistEvidence(data) {
  if (Object.keys(data).sort().join(",") !== "action,available,expect,id,kind,label,row_count,rows,space"
      || data.kind !== "watchlist" || data.space !== "home" || data.action !== "watchlist_update"
      || !Number.isSafeInteger(data.row_count) || data.row_count < 1 || data.row_count > 50
      || !Array.isArray(data.rows) || data.rows.length !== data.row_count
      || data.label !== "Updates to " + data.row_count + " purchase-queue row" + (data.row_count > 1 ? "s" : "")) return false;
  const ids = new Set();
  for (const item of data.rows) {
    if (!item || typeof item !== "object" || Object.keys(item).sort().join(",") !== "current,fields,label,restored,watch_row_id"
        || !Number.isSafeInteger(item.watch_row_id) || item.watch_row_id < 1 || ids.has(item.watch_row_id)
        || typeof item.label !== "string" || !item.label.trim()
        || !activityUndoWatchlistRow(item.current) || !activityUndoWatchlistRow(item.restored)) return false;
    ids.add(item.watch_row_id);
    const changed = ACTIVITY_UNDO_FIELDS.watchlist.filter(field => item.current[field] !== item.restored[field]);
    if (!changed.length || !Array.isArray(item.fields) || item.fields.length !== changed.length
        || [...item.fields].some((field, index) => !field || Object.keys(field).sort().join(",") !== "after,before,field"
          || field.field !== changed[index] || field.before !== item.current[field.field] || field.after !== item.restored[field.field])) return false;
  }
  return true;
}

function activityUndoWatchlistReceipt(answer, preview) {
  if (!answer || answer.saved !== true || answer.source_id !== preview.id || answer.expect !== preview.expect
      || Object.keys(answer).sort().join(",") !== "action,expect,kind,restored_rows,revision,row_count,saved,sha256,source_id,space,summary"
      || answer.kind !== "watchlist" || answer.space !== "home" || answer.action !== "watchlist_update" || answer.row_count !== preview.row_count
      || typeof answer.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(answer.sha256)
      || typeof answer.revision !== "string" || !answer.revision.trim() || typeof answer.summary !== "string" || !answer.summary.trim()
      || !Array.isArray(answer.restored_rows) || answer.restored_rows.length !== preview.row_count) return false;
  const expected = new Map(preview.rows.map(item => [item.watch_row_id, item.restored])), seen = new Set();
  for (const item of answer.restored_rows) {
    if (!item || typeof item !== "object" || Object.keys(item).sort().join(",") !== "row,watch_row_id" || !activityUndoWatchlistRow(item.row)) return false;
    const row = expected.get(item.watch_row_id);
    if (!row || seen.has(item.watch_row_id) || ACTIVITY_UNDO_FIELDS.watchlist.some(field => item.row[field] !== row[field])) return false;
    seen.add(item.watch_row_id);
  }
  return seen.size === expected.size;
}

/** The review: each row's current and restored values, notes and sources as literal text. */
function activityUndoWatchlistBody(body, preview, text) {
  const where = row => [row.printing === "exact" ? "Printing exact" : "Printing any", row.for ? "for " + row.for : "", row.state].filter(Boolean).join(" · ");
  const literal = field => ["notes", "source"].includes(field) ? "activity-undo-note" : null;
  const rows = preview.rows.map(item => el("section", { class: "panel activity-undo-batch-row" }, el("h4", { text: item.label }),
    el("p", { class: "sub", text: where(item.current) }),
    item.fields.map(field => el("p", {}, el("b", { text: ACTIVITY_UNDO_WATCHLIST_WORDS[field.field] + ": " }),
      el("span", { class: literal(field.field), text: text(field.before) }), " → ", el("span", { class: literal(field.field), text: text(field.after) })))));
  body.append(el("p", { class: "sub", text: "Review all " + plural(preview.row_count, "purchase-queue row") + " below. Their recorded values will be restored together in one new audited change; the original change stays in Activity." }),
    el("p", { class: "sub", text: "Each row is checked again when you save. Nothing is ordered, bought or removed." }),
    el("div", { class: "panels" }, rows));
}
