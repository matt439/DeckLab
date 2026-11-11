/* Reasoned deletion of a saved game. Positive server rights and the original page own every action. */
"use strict";

function playDeleteOwner(ctx) {
  try {
    const entries = ctx.record.mode === "pod" ? ctx.data.pods : ctx.data.games;
    return state.profile === ctx.profile && state.profile?.id === ctx.profileId
      && (state.profile?.space || HOME_SPACE) === ctx.space && routeToken === ctx.token && location.hash === ctx.hash
      && document.getElementById("main") === ctx.main && ctx.main.isConnected && ctx.main.contains(ctx.card)
      && ctx.source.parentNode === ctx.card && ctx.source.isConnected && !ctx.source.hidden
      && ctx.entry.record === ctx.record && ctx.entry.sha256 === ctx.sha && ctx.entry.can?.delete === true
      && JSON.stringify(ctx.record) === ctx.recordStamp && entries === ctx.entries && entries.includes(ctx.entry);
  } catch (_) { return false; }
}
function playDeleteHere(ctx) {
  return playDeleteOwner(ctx) && !ctx.sheet.closed && ctx.sheet.dialog.parentNode === ctx.frame.dialogParent
    && ctx.sheet.dialog.isConnected && ctx.sheet.body.parentNode === ctx.frame.bodyParent
    && ctx.sheet.foot.parentNode === ctx.frame.footParent && ctx.form.parentNode === ctx.sheet.body
    && ctx.reason.parentNode === ctx.field && ctx.field.parentNode === ctx.form
    && ctx.confirm.parentNode === ctx.sheet.foot && ctx.cancel.parentNode === ctx.sheet.foot
    && document.visibilityState !== "hidden" && keyboardDialog() === ctx.sheet.dialog;
}
function playDeleteButton(entry, data, card, describedBy = null) {
  if (entry.can?.delete !== true || !/^[a-f0-9]{64}$/.test(entry.sha256 || "")
      || !/^[a-f0-9]{32}$/.test(entry.record?.id || "")) return null;
  const source = el("button", { type: "button", class: "btn btn-quiet", text: "Delete this game",
    "aria-describedby": describedBy });
  const record = entry.record;
  const owner = { source, card, entry, record, recordStamp: JSON.stringify(record), sha: entry.sha256,
    data, entries: record.mode === "pod" ? data.pods : data.games,
    profile: state.profile, profileId: state.profile?.id, space: state.profile?.space || HOME_SPACE,
    token: routeToken, hash: location.hash, main: document.getElementById("main") };
  source.addEventListener("click", () => {
    if (!playDeleteOwner(owner) || source.disabled || keyboardDialog() || document.visibilityState === "hidden") return;
    const ctx = { ...owner, pending: false, sheet: openSheet("Delete this game") };
    ctx.reason = el("textarea", { rows: 3, maxlength: 2000, required: true });
    ctx.field = playField("Reason for deleting", ctx.reason);
    ctx.error = el("p", { class: "form-error", role: "status" });
    ctx.form = el("form", {}, el("p", { text: "Delete this saved game from the Game log? The deletion and your reason are kept on Activity." }),
      ctx.field, ctx.error);
    ctx.sheet.body.append(ctx.form);
    ctx.cancel = el("button", { type: "button", class: "btn", text: "Keep game", onclick: () => {
      if (playDeleteHere(ctx) && !ctx.pending) ctx.sheet.close();
    } });
    ctx.confirm = el("button", { type: "button", class: "btn btn-primary", text: "Delete game" });
    ctx.sheet.foot.append(ctx.cancel, ctx.confirm);
    ctx.frame = { dialogParent: ctx.sheet.dialog.parentNode, bodyParent: ctx.sheet.body.parentNode,
      footParent: ctx.sheet.foot.parentNode };
    const remove = async () => {
      if (!playDeleteHere(ctx) || ctx.pending) return;
      const reason = ctx.reason.value.trim();
      if (!reason) { ctx.error.textContent = "Give a reason for deleting this game."; ctx.reason.focus(); return; }
      ctx.pending = true; ctx.confirm.disabled = true; ctx.cancel.disabled = true;
      try {
        const answer = await apiWrite("/api/play/game/delete", { id: ctx.record.id, sha256: ctx.sha, reason, confirmed: true });
        if (!playDeleteHere(ctx)) return;
        if (answer.deleted !== true || answer.id !== ctx.record.id) throw Error("The deletion could not be confirmed. Refresh the Game log before trying again.");
        ctx.sheet.close(); toast("Game deleted."); route();
      } catch (error) {
        if (!playDeleteHere(ctx)) return;
        ctx.error.textContent = error.message;
      } finally {
        if (playDeleteHere(ctx)) { ctx.pending = false; ctx.confirm.disabled = false; ctx.cancel.disabled = false; }
      }
    };
    ctx.confirm.addEventListener("click", remove);
    ctx.form.addEventListener("submit", event => { event.preventDefault(); remove(); });
    if (playDeleteHere(ctx)) ctx.reason.focus();
  });
  return source;
}
