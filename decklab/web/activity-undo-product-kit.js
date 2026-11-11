/* One complete intact-product kit change; no submitted assignments become write authority. */
"use strict";

function activityUndoProductKitEvidence(data, space, profile) {
  if (data.kind !== "product_kit" || data.action !== "product_kit_restore" || space !== "home" || typeof profile !== "string" || !profile
      || Object.keys(data).sort().join(",") !== "action,available,expect,id,kind,kit_confirmation_required,label,row_count,rows"
      || data.kit_confirmation_required !== true || data.label !== "Complete product-kit change"
      || !Number.isSafeInteger(data.row_count) || data.row_count < 1 || data.row_count > 50 || !Array.isArray(data.rows) || data.rows.length !== data.row_count) return false;
  const files = new Set(), fields = ["sleeves", "deck_box"];
  for (const row of data.rows) {
    if (!row || Object.keys(row).sort().join(",") !== "current,file,restored,title" || typeof row.file !== "string"
        || !/^[a-z0-9]+(?:-[a-z0-9]+)*\.csv$/.test(row.file) || files.has(row.file) || typeof row.title !== "string" || !row.title.trim()
        || [row.current, row.restored].some(side => !side || Object.keys(side).sort().join(",") !== "deck_box,sleeves"
          || fields.some(field => typeof side[field] !== "string" || side[field] && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(side[field])))
        || fields.every(field => row.current[field] === row.restored[field])) return false;
    files.add(row.file);
  }
  return true;
}

function activityUndoProductKitReceipt(answer, preview) {
  return Boolean(answer && answer.saved === true && answer.source_id === preview.id && answer.expect === preview.expect
    && answer.kind === "product_kit" && answer.action === "product_kit_restore" && answer.row_count === preview.row_count
    && Object.keys(answer).sort().join(",") === "action,expect,kind,revision,row_count,rows,saved,sha256,source_id,summary"
    && typeof answer.sha256 === "string" && /^[a-f0-9]{64}$/.test(answer.sha256) && activityUndoAuditVersion(answer.revision)
    && typeof answer.summary === "string" && answer.summary.trim() && Array.isArray(answer.rows) && answer.rows.length === preview.rows.length
    && answer.rows.every((row, index) => row && Object.keys(row).sort().join(",") === "current,file,restored,title"
      && row.file === preview.rows[index].file && row.title === preview.rows[index].title
      && ["current", "restored"].every(side => row[side] && Object.keys(row[side]).sort().join(",") === "deck_box,sleeves"
        && ["sleeves", "deck_box"].every(field => row[side][field] === preview.rows[index][side][field]))));
}

function activityUndoProductKitShow(ctx) {
  const {sheet, preview, endpoint} = ctx, signature = JSON.stringify(preview), profile = state.profile;
  const current = () => ctx.here() && state.profile === profile && ctx.preview === preview && JSON.stringify(preview) === signature
    && activityUndoEvidence(preview, ctx.id, ctx.space, ctx.profile);
  const literal = side => el("dl", {}, ["sleeves", "deck_box"].flatMap(field => [el("dt", {text: field === "sleeves" ? "Sleeves" : "Deck box"}),
    el("dd", {class: "activity-undo-note", text: side[field] || "None assigned"})]));
  clear(sheet.body).append(el("p", {class: "box box-warn", text: `Review all ${plural(preview.row_count, "owned intact product")}. Every sleeves and deck-box assignment shown restores together as one new audited change. There is no partial selection.`}),
    el("p", {class: "sub", text: "The kit must be recognised Shared accessories, and available boxes and current product records are checked again when saving. Check the physical kit with each product before confirming. Cards, packed tokens, photos and every deck stay as they are."}),
    el("p", {class: "sub", text: "Changes that also touched decks are reviewed through Deck History and a separate product-kit check. This action restores product-only kit records; the original change stays in Activity."}),
    el("div", {class: "panels"}, preview.rows.map(row => el("section", {class: "panel activity-undo-product-kit"},
      el("h3", {text: row.title}), el("p", {class: "sub", text: row.file}), el("h4", {text: "Current kit"}), literal(row.current),
      el("h4", {text: "Restored by Undo"}), literal(row.restored)))));
  const consent = el("input", {type: "checkbox"}); consent.checked = false;
  let confirmed = false;
  sheet.body.append(el("label", {class: "choice"}, consent, el("span", {text: "I confirm all restored sleeves and deck-box assignments shown match the shared kit physically with these owned intact products."})));
  const error = el("p", {class: "form-error", role: "alert", tabindex: "-1"}); sheet.body.append(error);
  consent.addEventListener("change", () => {
    if (!current() || ctx.pending || ctx.saved || ctx.needsRefresh || !consent.isConnected || !sheet.body.contains(consent)) {consent.checked = confirmed; return;}
    confirmed = consent.checked === true; error.textContent = ""; actions();
  });
  function actions() {
    consent.disabled = ctx.pending || ctx.saved || ctx.needsRefresh;
    sheetActions(sheet, ctx.saved ? [{text: "Done", kind: "primary", onclick: event => {if (current() && event.currentTarget.isConnected) sheet.close();}}]
      : ctx.needsRefresh ? [{text: "Reload Activity", kind: "primary", onclick: event => {if (current() && event.currentTarget.isConnected) sheet.close();}},
        {text: "Close", onclick: () => sheet.close()}]
        : [{text: "Cancel", disabled: ctx.pending, onclick: () => sheet.close()},
          {text: ctx.pending ? "Saving Undo." : "Save Undo", kind: "primary", disabled: ctx.pending || !confirmed, onclick: save}]);
  }
  async function save(event) {
    if (!current() || ctx.pending || ctx.saved || ctx.needsRefresh || !event?.currentTarget?.isConnected || !sheet.foot.contains(event.currentTarget)
        || ctx.endpoint !== endpoint || !consent.isConnected || !sheet.body.contains(consent) || !confirmed || consent.checked !== true) return;
    const trigger = document.activeElement, focusOwned = () => document.activeElement === trigger || document.activeElement === document.body || !document.activeElement?.isConnected;
    ctx.pending = true; error.textContent = ""; actions();
    try {
      const answer = await apiWrite(endpoint, {id: ctx.id, expect: preview.expect, confirm_kit: true});
      invalidateLibrary();
      if (!activityUndoProductKitReceipt(answer, preview)) throw Error("The Undo result could not be confirmed.");
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
}
