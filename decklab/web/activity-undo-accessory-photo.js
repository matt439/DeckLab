/* Combined recorded accessory facts/crop, always on verified current photo bytes. */
"use strict";

const ACTIVITY_UNDO_PHOTO_RECORD_ACTION = "accessory_photo_record_update";
const ACTIVITY_UNDO_PHOTO_RECORD_FIELDS = ["owner", "kind", "quantity", ...ACTIVITY_UNDO_EDITABLE.accessory, "crop"];

function activityUndoAccessoryPhotoRecordEvidence(data, space, profile) {
  const owners = space === "home" ? [profile, "shared"] : space === profile ? [profile] : [];
  if (data.action !== ACTIVITY_UNDO_PHOTO_RECORD_ACTION || typeof profile !== "string" || !profile || !owners.length
      || Object.keys(data).sort().join(",") !== "action,available,current,expect,fields,id,kind,label,photo,photo_confirmation_required,record_confirmation_required,restored"
      || data.photo_confirmation_required !== true || data.record_confirmation_required !== true
      || !activityUndoAccessoryPhotoRow(data.current) || !activityUndoAccessoryPhotoRow(data.restored)
      || !owners.includes(data.current.owner) || !owners.includes(data.restored.owner)
      || data.current.id !== data.restored.id || data.current.image !== data.restored.image
      || data.current.crop === data.restored.crop || data.label !== data.current.name
      || !activityUndoAccessoryPhoto(data.photo, data.current)) return false;
  const changed = ACTIVITY_UNDO_PHOTO_RECORD_FIELDS.filter(field => data.current[field] !== data.restored[field]);
  return changed.length >= 2 && changed.includes("crop") && Array.isArray(data.fields) && data.fields.length === changed.length
    && data.fields.every((field, index) => field && Object.keys(field).sort().join(",") === "after,before,field"
      && field.field === changed[index] && field.before === data.current[field.field] && field.after === data.restored[field.field]);
}

function activityUndoAccessoryPhotoRecordReceipt(answer, preview) {
  return Boolean(answer && answer.saved === true && answer.source_id === preview.id && answer.expect === preview.expect
    && answer.kind === "accessory" && answer.action === ACTIVITY_UNDO_PHOTO_RECORD_ACTION
    && Object.keys(answer).sort().join(",") === "action,expect,kind,photo,restored,revision,saved,sha256,source_id,summary"
    && typeof answer.sha256 === "string" && /^[a-f0-9]{64}$/.test(answer.sha256) && activityUndoAuditVersion(answer.revision)
    && typeof answer.summary === "string" && answer.summary.trim()
    && activityUndoAccessoryPhotoRow(answer.restored) && activityUndoAccessoryPhoto(answer.photo, answer.restored)
    && ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS.every(field => answer.restored[field] === preview.restored[field])
    && ["name", "size", "sha256", "version"].every(field => answer.photo[field] === preview.photo[field]));
}

function activityUndoAccessoryPhotoRecordShow(ctx) {
  const {sheet, preview, endpoint} = ctx, signature = JSON.stringify(preview), profile = state.profile;
  const current = () => ctx.here() && state.profile === profile && ctx.preview === preview && JSON.stringify(preview) === signature
    && activityUndoEvidence(preview, ctx.id, ctx.space, ctx.profile);
  const kind = row => ({sleeves: "Sleeves", deck_box: "Deck box", playmat: "Playmat"})[row.kind];
  const owner = value => value === "shared" ? "Shared" : profile?.name || value;
  const count = row => `${row.quantity} ${row.kind === "sleeves" ? row.quantity === "1" ? "individual sleeve" : "individual sleeves" : row.quantity === "1" ? "item" : "items"}`;
  const words = {id: "Record ID", owner: "Owner", kind: "Kind", quantity: "Recorded count", image_source: "Image-source URL", link: "Product link", image: "Current image file", capacity: "Box capacity", crop: "Crop coordinates"};
  const literal = row => el("dl", {}, ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS.flatMap(field => [
    el("dt", {text: words[field] || capitalise(field)}), el("dd", {class: "activity-undo-note", text: field === "kind" ? kind(row)
      : field === "owner" ? owner(row.owner) : field === "quantity" ? count(row) : row[field] || "Not recorded"})]));
  const frames = [["Current record and crop", preview.current], ["Restored record and crop", preview.restored]].map(([title, row]) => {
    const box = el("span", {class: "acc-thumb acc-thumb-fill"});
    return {box, crop: row.crop, label: title + " on the current photo", panel: el("figure", {class: "panel"},
      el("h3", {text: title}), box, literal(row))};
  });
  let photo, confirmedPhoto = false, confirmedRecord = false;
  const status = el("p", {class: "sub", role: "status", "aria-live": "polite", text: "Checking the current photo before reviewing both crops."});
  clear(sheet.body).append(el("p", {class: "box box-warn", text: "Undo restores this whole recorded correction and crop together on the photo saved now. It cannot recover an earlier photo. Both views use the same verified current bytes; the photo and all kit assignments are kept."}),
    el("p", {class: "sub", text: "Review both complete records. The restored count replaces this record's current total; sleeves count individual sleeves, boxes and playmats count items. If the facts differ from what you own, cancel and use Sleeves & boxes. Sharing or kind changes require an unused record and are checked again when saving."}),
    el("p", {class: "sub", text: "Saved links restore as literal text. An image-source URL is not verified against the current photo. Read access follows the restored owner's existing Public/Private setting; Undo does not change that setting. Saving creates one new audited change and keeps the original in Activity."}),
    status, el("div", {class: "panels activity-undo-photos"}, frames.map(frame => frame.panel)));
  const photoInput = el("input", {type: "checkbox", disabled: true}), recordInput = el("input", {type: "checkbox"});
  photoInput.checked = recordInput.checked = false;
  const row = preview.restored;
  sheet.body.append(el("label", {class: "choice"}, photoInput, el("span", {text: "I have checked both views and want this recorded crop on the current photo."})),
    el("label", {class: "choice"}, recordInput, el("span", {text: row.quantity === "0"
      ? `I confirm this zero-quantity reference record should have all the restored details, be ${kind(row)}, and be ${owner(row.owner)}.`
      : `I confirm all restored details, the full count of ${count(row)} still physically owned as ${kind(row)}, and that this record should be ${owner(row.owner)}.`})));
  const error = el("p", {class: "form-error", role: "alert", tabindex: "-1"}); sheet.body.append(error);
  const attached = input => input.isConnected && sheet.body.contains(input);
  for (const input of [photoInput, recordInput]) input.addEventListener("change", () => {
    if (!current() || ctx.pending || ctx.saved || ctx.needsRefresh || !attached(input) || input === photoInput && !photo?.valid()) {
      input.checked = input === photoInput ? confirmedPhoto : confirmedRecord; return;
    }
    if (input === photoInput) confirmedPhoto = input.checked === true; else confirmedRecord = input.checked === true;
    error.textContent = ""; actions();
  });
  function actions() {
    photoInput.disabled = ctx.pending || ctx.saved || ctx.needsRefresh || !photo?.valid();
    recordInput.disabled = ctx.pending || ctx.saved || ctx.needsRefresh;
    sheetActions(sheet, ctx.saved ? [{text: "Done", kind: "primary", onclick: event => {if (current() && event.currentTarget.isConnected) sheet.close();}}]
      : ctx.needsRefresh ? [{text: "Reload Activity", kind: "primary", onclick: event => {if (current() && event.currentTarget.isConnected) sheet.close();}},
        {text: "Close", onclick: () => sheet.close()}]
        : [{text: "Cancel", disabled: ctx.pending, onclick: () => sheet.close()},
          {text: ctx.pending ? "Saving Undo." : "Save Undo", kind: "primary", disabled: ctx.pending || !confirmedPhoto || !confirmedRecord || !photo?.valid(), onclick: save}]);
  }
  async function save(event) {
    if (!current() || ctx.pending || ctx.saved || ctx.needsRefresh || ctx.endpoint !== endpoint
        || !event?.currentTarget?.isConnected || !sheet.foot.contains(event.currentTarget)
        || !attached(photoInput) || !attached(recordInput) || photoInput.checked !== true || recordInput.checked !== true
        || !confirmedPhoto || !confirmedRecord || !photo?.valid()) return;
    const trigger = document.activeElement, focusOwned = () => document.activeElement === trigger || document.activeElement === document.body || !document.activeElement?.isConnected;
    ctx.pending = true; error.textContent = ""; actions();
    try {
      const answer = await apiWrite(endpoint, {id: ctx.id, expect: preview.expect, confirm_photo: true, confirm_record: true});
      invalidateLibrary();
      if (!activityUndoAccessoryPhotoRecordReceipt(answer, preview)) throw Error("The Undo result could not be confirmed.");
      if (!activityUndoOwner(ctx) || state.profile !== profile) return;
      ctx.saved = true;
      if (ctx.current()) {
        const message = el("p", {role: "status", tabindex: "-1", text: "Undo saved as a new change. " + answer.summary});
        sheet.body.append(message); actions(); if (current() && focusOwned()) message.focus();
      }
    } catch (failure) {
      invalidateLibrary();
      if (!activityUndoOwner(ctx) || state.profile !== profile) return;
      ctx.needsRefresh = true;
      error.textContent = (failure instanceof ApiError ? failure.message : "The Undo result could not be confirmed.") + " Reload Activity before reviewing another Undo.";
      if (current() && focusOwned()) error.focus();
    } finally {
      ctx.pending = false;
      if (activityUndoOwner(ctx) && state.profile === profile) {if (ctx.current()) actions(); else activityUndoAfterClose(ctx);}
    }
  }
  actions();
  const photoCtx = {...ctx, current: () => ctx.current() && state.profile === profile && ctx.preview === preview && JSON.stringify(preview) === signature};
  photo = activityUndoPhotoPreview(photoCtx, frames, () => {
    if (!photoCtx.current()) return;
    if (photo.failed) {
      confirmedPhoto = false; ctx.needsRefresh = true;
      status.textContent = "The current photo could not be verified. Reload Activity before reviewing this correction again.";
    } else status.textContent = "Both crops use the verified current photo. Review every restored detail and both crop views.";
    photoInput.checked = confirmedPhoto; actions();
  });
  ctx.photoRelease = photoCtx.photoRelease;
}
