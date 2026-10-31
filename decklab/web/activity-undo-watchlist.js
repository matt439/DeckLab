/* Undo of 1-50 purchase-queue rows' updated values, of rows one change added or removed, or of a change
   that mixed those (E11-S08): every row together, no selection. */
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

/** Rows a change added (removed again by stable id, with one reason) or removed (restored as new rows). */
function activityUndoWatchlistRowsEvidence(data) {
  const removing = data.action === "watchlist_remove", ids = new Set(), keys = new Set();
  if (Object.keys(data).sort().join(",") !== ["action", "available", "expect", "id", "kind", "label", ...(removing ? ["reason_required"] : []),
    "row_count", "rows", "space"].join(",")) return false;
  if (data.kind !== "watchlist" || data.space !== "home" || (removing && data.reason_required !== true)
      || !Number.isSafeInteger(data.row_count) || data.row_count < 1 || data.row_count > 50
      || !Array.isArray(data.rows) || data.rows.length !== data.row_count
      || data.label !== data.row_count + (removing ? " added" : " removed") + " purchase-queue row" + (data.row_count > 1 ? "s" : "")) return false;
  for (const item of data.rows) {
    if (!item || typeof item !== "object" || typeof item.label !== "string" || !item.label.trim()) return false;
    if (removing) {
      if (Object.keys(item).sort().join(",") !== "current,label,watch_row_id" || !Number.isSafeInteger(item.watch_row_id)
          || item.watch_row_id < 1 || ids.has(item.watch_row_id) || !activityUndoWatchlistRow(item.current)) return false;
      ids.add(item.watch_row_id);
    } else {
      if (Object.keys(item).sort().join(",") !== "label,restored" || !activityUndoWatchlistRow(item.restored)) return false;
      const key = JSON.stringify(["name", "printing", "set", "collector_number", "finish", "for"].map(field => item.restored[field]));
      if (keys.has(key)) return false;
      keys.add(key);
    }
  }
  return true;
}

function activityUndoWatchlistEvidence(data) {
  if (["watchlist_remove", "watchlist_add"].includes(data.action)) return activityUndoWatchlistRowsEvidence(data);
  if (data.action === "watchlist_mixed") return activityUndoWatchlistMixedEvidence(data);
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
  if (preview.action === "watchlist_mixed") return activityUndoWatchlistMixedReceipt(answer, preview);
  if (preview.action === "watchlist_remove") return Boolean(answer && answer.saved === true && answer.source_id === preview.id
    && answer.expect === preview.expect && answer.kind === "watchlist" && answer.space === "home" && answer.action === "watchlist_remove"
    && Object.keys(answer).sort().join(",") === "action,expect,kind,removed_watch_row_ids,revision,row_count,saved,sha256,source_id,space,summary"
    && answer.row_count === preview.row_count && typeof answer.sha256 === "string" && /^[a-f0-9]{64}$/.test(answer.sha256)
    && typeof answer.revision === "string" && answer.revision.trim() && typeof answer.summary === "string" && answer.summary.trim()
    && Array.isArray(answer.removed_watch_row_ids) && answer.removed_watch_row_ids.length === preview.row_count
    && answer.removed_watch_row_ids.every((id, index) => id === preview.rows[index].watch_row_id));
  const restoring = preview.action === "watchlist_add";
  if (!answer || answer.saved !== true || answer.source_id !== preview.id || answer.expect !== preview.expect
      || Object.keys(answer).sort().join(",") !== "action,expect,kind,restored_rows,revision,row_count,saved,sha256,source_id,space,summary"
      || answer.kind !== "watchlist" || answer.space !== "home" || answer.action !== preview.action || answer.row_count !== preview.row_count
      || typeof answer.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(answer.sha256)
      || typeof answer.revision !== "string" || !answer.revision.trim() || typeof answer.summary !== "string" || !answer.summary.trim()
      || !Array.isArray(answer.restored_rows) || answer.restored_rows.length !== preview.row_count) return false;
  if (restoring) {
    // Fresh ids the review couldn't know: each distinct, each row exactly the recorded one, in the review's order.
    const ids = new Set();
    return answer.restored_rows.every((item, index) => item && typeof item === "object" && Object.keys(item).sort().join(",") === "row,watch_row_id"
      && Number.isSafeInteger(item.watch_row_id) && item.watch_row_id > 0 && !ids.has(item.watch_row_id) && ids.add(item.watch_row_id)
      && activityUndoWatchlistRow(item.row) && ACTIVITY_UNDO_FIELDS.watchlist.every(field => item.row[field] === preview.rows[index].restored[field]));
  }
  const expected = new Map(preview.rows.map(item => [item.watch_row_id, item.restored])), seen = new Set();
  for (const item of answer.restored_rows) {
    if (!item || typeof item !== "object" || Object.keys(item).sort().join(",") !== "row,watch_row_id" || !activityUndoWatchlistRow(item.row)) return false;
    const row = expected.get(item.watch_row_id);
    if (!row || seen.has(item.watch_row_id) || ACTIVITY_UNDO_FIELDS.watchlist.some(field => item.row[field] !== row[field])) return false;
    seen.add(item.watch_row_id);
  }
  return seen.size === expected.size;
}

/** The review: each row's current and restored values, notes and sources as literal text; for rows
    added or removed, each whole row. A removal's reason input is activity-undo.js's. */
function activityUndoWatchlistBody(body, preview, text) {
  if (["watchlist_remove", "watchlist_add"].includes(preview.action)) return activityUndoWatchlistRowsBody(body, preview, text);
  if (preview.action === "watchlist_mixed") return activityUndoWatchlistMixedBody(body, preview, text);
  const where = row => [row.printing === "exact" ? "Printing exact" : "Printing any", row.for ? "for " + row.for : "", row.state].filter(Boolean).join(" · ");
  const literal = field => ["notes", "source"].includes(field) ? "activity-undo-note" : null;
  const rows = preview.rows.map(item => el("section", { class: "panel activity-undo-batch-row" }, el("h4", { text: item.label }),
    el("p", { class: "sub", text: where(item.current) }),
    item.fields.map(field => el("p", {}, el("b", { text: ACTIVITY_UNDO_WATCHLIST_WORDS[field.field] + ": " }),
      el("span", { class: literal(field.field), text: text(field.before) }), " → ", el("span", { class: literal(field.field), text: text(field.after) })))));
  body.append(el("p", { class: "sub", text: preview.row_count === 1
      ? "Review the purchase-queue row below. Its recorded values will be restored in one new audited change; the original change stays in Activity."
      : "Review all " + plural(preview.row_count, "purchase-queue row") + " below. Their recorded values will be restored together in one new audited change; the original change stays in Activity." }),
    el("p", { class: "sub", text: "Each row is checked again when you save. Nothing is ordered, bought or removed." }),
    el("div", { class: "panels" }, rows));
}

function activityUndoWatchlistRowsBody(body, preview, text) {
  const removing = preview.action === "watchlist_remove", rows = preview.rows.map(item => removing ? item.current : item.restored);
  const one = preview.row_count === 1, many = plural(preview.row_count, "purchase-queue row");
  const whole = row => el("dl", {}, ACTIVITY_UNDO_FIELDS.watchlist.flatMap(field => [el("dt", { text: ACTIVITY_UNDO_WATCHLIST_WORDS[field] }),
    el("dd", { class: ["notes", "source"].includes(field) ? "activity-undo-note" : null, text: text(row[field]) })]));
  body.append(el("p", { class: "box box-warn", text: removing
      ? (one ? "Undo removes the purchase-queue row this change added." : "Undo removes all " + many + " this change added. Every added row will be removed together.")
      : one ? "Undo adds the purchase-queue row this change removed back to the queue, as a new row, near where it was."
      : "Undo adds all " + many + " this change removed back to the queue, each as a new row, near where it was." }),
    el("p", { class: "sub", text: "Saving creates one new audited change; the original change stays in Activity. "
      + (removing ? "Each row is checked again when you save." : "Each row is checked again when you save, against the queue as it is now.")
      + " Nothing is ordered, bought or cancelled." }),
    el("p", { class: "sub", text: one ? "Review the " + (removing ? "current" : "recorded") + " row below."
      : "Review every " + (removing ? "current" : "recorded") + " row below. There is no partial selection." }),
    el("div", { class: "panels" }, preview.rows.map((item, index) => el("section", { class: "panel activity-undo-batch-row" },
      el("h4", { text: item.label }), whole(rows[index])))));
}

/** The removal reason's words: for rows a change added, or for the added rows of a mixed change. */
function activityUndoWatchlistReason(preview) {
  const one = (preview.action === "watchlist_mixed" ? preview.counts.added : preview.row_count) === 1;
  return { label: one ? "Reason for removing this added purchase-queue row (required)" : "Reason for removing all these added purchase-queue rows (required)",
    hint: "Up to 200 characters. Enter why " + (one ? "this row" : "these rows") + " should come off the purchase queue." };
}

const ACTIVITY_UNDO_WATCHLIST_CHANGES = ["updated", "added", "removed"];

/** A change that mixed updated, added and removed rows: each kind's rows as its own slice shows them, in that order. */
function activityUndoWatchlistMixedEvidence(data) {
  const counts = data.counts, ids = new Set(), keys = new Set();
  if (Object.keys(data).sort().join(",") !== ["action", "available", "counts", "expect", "id", "kind", "label",
    ...(counts?.added ? ["reason_required"] : []), "row_count", "rows", "space"].join(",")) return false;
  if (data.kind !== "watchlist" || data.space !== "home" || !counts || typeof counts !== "object" || Array.isArray(counts)
      || Object.keys(counts).sort().join(",") !== "added,removed,updated"
      || ACTIVITY_UNDO_WATCHLIST_CHANGES.some(change => !Number.isSafeInteger(counts[change]) || counts[change] < 0)
      || ACTIVITY_UNDO_WATCHLIST_CHANGES.filter(change => counts[change] > 0).length < 2
      || (counts.added > 0 && data.reason_required !== true)
      || !Number.isSafeInteger(data.row_count) || data.row_count < 2 || data.row_count > 50
      || counts.updated + counts.added + counts.removed !== data.row_count
      || !Array.isArray(data.rows) || data.rows.length !== data.row_count
      || data.label !== "Changes to " + data.row_count + " purchase-queue rows") return false;
  const order = ACTIVITY_UNDO_WATCHLIST_CHANGES.flatMap(change => Array(counts[change]).fill(change));
  return data.rows.every((item, index) => {
    if (!item || typeof item !== "object" || item.change !== order[index] || typeof item.label !== "string" || !item.label.trim()) return false;
    if (item.change === "removed") {
      if (Object.keys(item).sort().join(",") !== "change,label,restored" || !activityUndoWatchlistRow(item.restored)) return false;
      const key = JSON.stringify(["name", "printing", "set", "collector_number", "finish", "for"].map(field => item.restored[field]));
      return !keys.has(key) && Boolean(keys.add(key));
    }
    if (!Number.isSafeInteger(item.watch_row_id) || item.watch_row_id < 1 || ids.has(item.watch_row_id) || !activityUndoWatchlistRow(item.current)) return false;
    ids.add(item.watch_row_id);
    if (item.change === "added") return Object.keys(item).sort().join(",") === "change,current,label,watch_row_id";
    if (Object.keys(item).sort().join(",") !== "change,current,fields,label,restored,watch_row_id" || !activityUndoWatchlistRow(item.restored)) return false;
    const changed = ACTIVITY_UNDO_FIELDS.watchlist.filter(field => item.current[field] !== item.restored[field]);
    return changed.length > 0 && Array.isArray(item.fields) && item.fields.length === changed.length
      && item.fields.every((field, at) => field && Object.keys(field).sort().join(",") === "after,before,field"
        && field.field === changed[at] && field.before === item.current[field.field] && field.after === item.restored[field.field]);
  });
}

function activityUndoWatchlistMixedReceipt(answer, preview) {
  const rows = change => preview.rows.filter(item => item.change === change), same = (row, wanted) => activityUndoWatchlistRow(row)
    && ACTIVITY_UNDO_FIELDS.watchlist.every(field => row[field] === wanted[field]);
  const updated = rows("updated"), added = rows("added"), removed = rows("removed");
  const known = new Set([...updated, ...added].map(item => item.watch_row_id)), fresh = new Set();
  return Boolean(answer && answer.saved === true && answer.source_id === preview.id && answer.expect === preview.expect
    && Object.keys(answer).sort().join(",") === "action,expect,kind,new_rows,removed_watch_row_ids,restored_rows,revision,row_count,saved,sha256,source_id,space,summary"
    && answer.kind === "watchlist" && answer.space === "home" && answer.action === "watchlist_mixed" && answer.row_count === preview.row_count
    && typeof answer.sha256 === "string" && /^[a-f0-9]{64}$/.test(answer.sha256)
    && typeof answer.revision === "string" && answer.revision.trim() && typeof answer.summary === "string" && answer.summary.trim()
    && Array.isArray(answer.restored_rows) && answer.restored_rows.length === updated.length
    && answer.restored_rows.every((item, index) => item && typeof item === "object" && Object.keys(item).sort().join(",") === "row,watch_row_id"
      && item.watch_row_id === updated[index].watch_row_id && same(item.row, updated[index].restored))
    && Array.isArray(answer.removed_watch_row_ids) && answer.removed_watch_row_ids.length === added.length
    && answer.removed_watch_row_ids.every((id, index) => id === added[index].watch_row_id)
    && Array.isArray(answer.new_rows) && answer.new_rows.length === removed.length
    && answer.new_rows.every((item, index) => item && typeof item === "object" && Object.keys(item).sort().join(",") === "row,watch_row_id"
      && Number.isSafeInteger(item.watch_row_id) && item.watch_row_id > 0 && !known.has(item.watch_row_id) && !fresh.has(item.watch_row_id)
      && Boolean(fresh.add(item.watch_row_id)) && same(item.row, removed[index].restored)));
}

function activityUndoWatchlistMixedBody(body, preview, text) {
  const { updated, added, removed } = preview.counts;
  const parts = [updated ? "restores the recorded values of " + (updated === 1 ? "the row it updated" : "all " + plural(updated, "row") + " it updated") : "",
    added ? "removes " + (added === 1 ? "the row it added" : "all " + plural(added, "row") + " it added") : "",
    removed ? "adds " + (removed === 1 ? "the row it removed back to the queue as a new row, near where it was"
      : "all " + plural(removed, "row") + " it removed back to the queue, each as a new row near where it was") : ""].filter(Boolean);
  const where = row => [row.printing === "exact" ? "Printing exact" : "Printing any", row.for ? "for " + row.for : "", row.state].filter(Boolean).join(" · ");
  const note = field => ["notes", "source"].includes(field) ? "activity-undo-note" : null;
  const whole = row => el("dl", {}, ACTIVITY_UNDO_FIELDS.watchlist.flatMap(field => [el("dt", { text: ACTIVITY_UNDO_WATCHLIST_WORDS[field] }),
    el("dd", { class: note(field), text: text(row[field]) })]));
  const group = (change, one, many) => {
    const items = preview.rows.filter(item => item.change === change);
    return items.length ? [el("h4", { text: items.length === 1 ? one : many }), el("div", { class: "panels" }, items.map(item => el("section", { class: "panel activity-undo-batch-row" },
      el("h4", { text: item.label }),
      change === "updated" ? [el("p", { class: "sub", text: where(item.current) }), ...item.fields.map(field => el("p", {}, el("b", { text: ACTIVITY_UNDO_WATCHLIST_WORDS[field.field] + ": " }),
        el("span", { class: note(field.field), text: text(field.before) }), " → ", el("span", { class: note(field.field), text: text(field.after) })))]
        : whole(change === "added" ? item.current : item.restored))))] : [];
  };
  body.append(el("p", { class: "box box-warn", text: "Undo reverses this whole change together: it " + parts.join("; it ") + "." }),
    el("p", { class: "sub", text: "Saving creates one new audited change; the original change stays in Activity. Each row is checked again when you save, against the queue as it is now. Nothing is ordered, bought or cancelled." }),
    el("p", { class: "sub", text: "Review all " + plural(preview.row_count, "purchase-queue row") + " below. There is no partial selection." }),
    ...group("updated", "Updated row: recorded values to restore", "Updated rows: recorded values to restore"),
    ...group("added", "Added row to remove", "Added rows to remove"),
    ...group("removed", "Removed row to add back", "Removed rows to add back"));
}
