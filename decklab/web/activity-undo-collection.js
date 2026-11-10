/* Complete collection-row recovery. The server rechecks the immutable source; no submitted row is authority. */
"use strict";

function activityUndoCollectionEvidence(data) {
  const keys = "action,available,expect,id,kind,label,location_transfer,physical_confirmation_required,reason_required,row_count,rows,space";
  if (Object.keys(data).sort().join(",") !== keys || data.kind !== "collection" || data.action !== "collection_change_restore"
      || !Number.isSafeInteger(data.row_count) || data.row_count < 1 || data.row_count > 50
      || !Array.isArray(data.rows) || data.rows.length !== data.row_count
      || data.label !== `Complete collection change (${plural(data.row_count, "row")})`
      || typeof data.reason_required !== "boolean" || typeof data.physical_confirmation_required !== "boolean") return false;
  const seen = new Set(); let reason = false, confirmation = false;
  for (const item of data.rows) {
    if (!item || Object.keys(item).sort().join(",") !== "current,key,label,restored"
        || item.current !== null && !activityUndoRow(item.current, "collection")
        || item.restored !== null && !activityUndoRow(item.restored, "collection")) return false;
    const row = item.current || item.restored, key = activityUndoBatchKey(item.key, row);
    if (!row || !key || seen.has(key) || item.restored && !activityUndoBatchKey(item.key, item.restored)
        || item.label !== `${row.name} (${row.set.toUpperCase()} ${row.collector_number}, ${row.finish})`
        || item.current && item.restored && ACTIVITY_UNDO_FIELDS.collection.every(field => item.current[field] === item.restored[field])) return false;
    seen.add(key);
    const renamed = item.current && item.restored && item.current.name !== item.restored.name;
    reason ||= !!item.current && (!item.restored || renamed);
    confirmation ||= !!item.restored && (!item.current || renamed);
  }
  if (reason !== data.reason_required || confirmation !== data.physical_confirmation_required) return false;
  const added = data.rows.filter(row => row.current && !row.restored), deleted = data.rows.filter(row => !row.current && row.restored);
  const transfer = data.location_transfer;
  if (added.length === 1 && deleted.length === 1) {
    if (!transfer || Object.keys(transfer).sort().join(",") !== "from,location,to"
        || activityUndoBatchKey(transfer.from) !== activityUndoBatchKey(added[0].key)
        || activityUndoBatchKey(transfer.to) !== activityUndoBatchKey(deleted[0].key)
        || typeof transfer.location !== "string" || transfer.location.length > 40
        || /[\x00-\x1f\x7f-\x9f\u2028\u2029]/.test(transfer.location)
        || transfer.location.trim().replace(/\s+/g, " ") !== transfer.location) return false;
  } else if (transfer !== null) return false;
  return true;
}

function activityUndoCollectionReceipt(answer, preview) {
  return !!answer && answer.saved === true && answer.source_id === preview.id && answer.expect === preview.expect
    && Object.keys(answer).sort().join(",") === "action,expect,kind,locations_sha256,row_count,rows,saved,sha256,source_id,space,summary"
    && answer.kind === "collection" && answer.space === preview.space && answer.action === preview.action
    && answer.row_count === preview.row_count && typeof answer.summary === "string" && !!answer.summary.trim()
    && [answer.sha256, answer.locations_sha256].every(value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value))
    && Array.isArray(answer.rows) && answer.rows.length === preview.row_count && answer.rows.every((item, index) => {
      const wanted = preview.rows[index];
      return item && Object.keys(item).sort().join(",") === "key,row"
        && activityUndoBatchKey(item.key) === activityUndoBatchKey(wanted.key)
        && (wanted.restored === null ? item.row === null : activityUndoRow(item.row, "collection")
          && ACTIVITY_UNDO_FIELDS.collection.every(field => item.row[field] === wanted.restored[field]));
    });
}

function activityUndoCollectionShow(ctx) {
  const {sheet, preview, endpoint} = ctx, signature = JSON.stringify(preview);
  const current = () => ctx.here() && ctx.preview === preview && JSON.stringify(preview) === signature
    && activityUndoEvidence(preview, ctx.id, ctx.space, ctx.profile);
  let reason = "", confirmed = false, accepted = "", reasonInput = null, ownershipInput = null;
  clear(sheet.body);
  const literal = row => row === null ? el("p", {class: "sub", text: "No row"})
    : el("dl", {}, ACTIVITY_UNDO_FIELDS.collection.flatMap(field => [el("dt", {text: field.replaceAll("_", " ")}),
      el("dd", {class: field === "notes" ? "activity-undo-note" : null, text: String(row[field] || "Not recorded")})]));
  sheet.body.append(el("p", {class: "box box-warn", text: "Review this complete collection change. Every row below is restored together in one new audited change; the original stays in Activity. There is no partial selection."}),
    el("p", {class: "sub", text: "Physical cards and their use in built decks and intact products are checked again when you save. A printing being free is never assumed."}),
    el("p", {class: "sub", text: preview.location_transfer
      ? "The current storage location follows the replacement back to the restored printing: " + (preview.location_transfer.location || "Not recorded") + ". Other current rows keep their locations. No historical location is restored."
      : "Current rows keep their storage locations. Restored deleted rows start without a location; removed rows lose theirs. No historical location is restored."}),
    el("div", {class: "panels"}, preview.rows.map(item => el("section", {class: "panel activity-undo-batch-row"},
      el("h4", {text: item.label}), el("h5", {text: "Current"}), literal(item.current), el("h5", {text: "Restored by Undo"}), literal(item.restored)))));
  if (preview.reason_required) {
    reasonInput = el("input", {type: "text", maxlength: 200, value: "", "aria-label": "Reason for undoing the complete collection change"});
    sheet.body.append(el("label", {class: "field"}, el("span", {text: "Reason for removing or replacing these recorded cards (required)"}), reasonInput));
    reasonInput.addEventListener("input", () => {
      if (!current() || ctx.pending || ctx.saved || ctx.needsRefresh || !reasonInput.isConnected || !sheet.body.contains(reasonInput)) { reasonInput.value = accepted; return; }
      accepted = reasonInput.value; reason = activityUndoRemovalReason(accepted); error.textContent = ""; actions();
    });
  }
  if (preview.physical_confirmation_required) {
    ownershipInput = el("input", {type: "checkbox"}); ownershipInput.checked = false;
    sheet.body.append(el("label", {class: "choice"}, ownershipInput,
      el("span", {text: "I confirm I still physically own every historical identity and every deleted copy shown above. Fewer copies need the Collection editor."})));
    ownershipInput.addEventListener("change", () => {
      if (!current() || ctx.pending || ctx.saved || ctx.needsRefresh || !ownershipInput.isConnected || !sheet.body.contains(ownershipInput)) { ownershipInput.checked = confirmed; return; }
      confirmed = ownershipInput.checked === true; error.textContent = ""; actions();
    });
  }
  const error = el("p", {class: "form-error", role: "alert", tabindex: "-1"}); sheet.body.append(error);
  function actions() {
    for (const control of [reasonInput, ownershipInput].filter(Boolean)) control.disabled = ctx.pending || ctx.saved || ctx.needsRefresh;
    sheetActions(sheet, ctx.saved ? [{text: "Done", kind: "primary", onclick: event => { if (ctx.here() && event.currentTarget.isConnected) sheet.close(); }}]
      : ctx.needsRefresh ? [{text: "Reload Activity", kind: "primary", onclick: event => { if (ctx.here() && event.currentTarget.isConnected) sheet.close(); }},
        {text: "Close", onclick: () => sheet.close()}]
        : [{text: "Cancel", disabled: ctx.pending, onclick: () => sheet.close()},
          {text: ctx.pending ? "Saving Undo." : "Save Undo", kind: "primary", disabled: ctx.pending || preview.reason_required && !reason
            || preview.physical_confirmation_required && !confirmed, onclick: save}]);
  }
  async function save(event) {
    if (!current() || ctx.pending || ctx.saved || ctx.needsRefresh || !event?.currentTarget?.isConnected || !sheet.foot.contains(event.currentTarget)
        || ctx.endpoint !== endpoint || reasonInput && (!reasonInput.isConnected || !sheet.body.contains(reasonInput)
          || accepted !== reasonInput.value || !reason || activityUndoRemovalReason(reasonInput.value) !== reason)
        || ownershipInput && (!ownershipInput.isConnected || !sheet.body.contains(ownershipInput) || !confirmed || ownershipInput.checked !== true)) return;
    const trigger = document.activeElement, focusOwned = () => document.activeElement === trigger || document.activeElement === document.body || !document.activeElement?.isConnected;
    ctx.pending = true; error.textContent = ""; actions();
    try {
      const answer = await apiWrite(endpoint, {id: ctx.id, expect: preview.expect,
        ...(preview.reason_required ? {reason} : {}), ...(preview.physical_confirmation_required ? {confirm_owned: true} : {})});
      invalidateLibrary();
      if (!activityUndoCollectionReceipt(answer, preview)) throw Error("The Undo result could not be confirmed.");
      if (!activityUndoOwner(ctx)) return;
      ctx.saved = true;
      if (ctx.current()) {
        const message = el("p", {role: "status", tabindex: "-1", text: "Undo saved as a new change. " + answer.summary});
        sheet.body.append(message); actions(); if (ctx.here() && focusOwned()) message.focus();
      }
    } catch (failure) {
      invalidateLibrary();
      if (!activityUndoOwner(ctx)) return;
      ctx.needsRefresh = true;
      error.textContent = (failure instanceof ApiError ? failure.message : "The Undo result could not be confirmed.") + " Reload Activity before reviewing another Undo.";
      if (ctx.current() && ctx.here() && focusOwned()) error.focus();
    } finally {
      ctx.pending = false;
      if (activityUndoOwner(ctx)) { if (ctx.current()) actions(); else activityUndoAfterClose(ctx); }
    }
  }
  actions();
}
