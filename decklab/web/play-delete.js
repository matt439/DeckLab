/* Reasoned deletion of a saved game. Positive server rights and the original page own every action. */
"use strict";

let playDeleteSheet = null;
function closePlayDeleteSheets() {
  if (playDeleteSheet && !playDeleteSheet.closed) playDeleteSheet.close();
}

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
    && ctx.reason.parentNode === ctx.field && ctx.field.parentNode === ctx.form && ctx.review.parentNode === ctx.form
    && ctx.error.parentNode === ctx.form
    && ctx.confirm.parentNode === ctx.sheet.foot && ctx.cancel.parentNode === ctx.sheet.foot
    && document.visibilityState !== "hidden" && keyboardDialog() === ctx.sheet.dialog;
}
/** Re-read through the same viewer-filtered Game log as the original card. */
async function playDeleteCurrent(ctx) {
  const data = await api("/api/play", { cache: "no-store", wakeHop: false });
  const pod = ctx.record.mode === "pod";
  const current = (pod ? data.pods : data.games).find(entry => entry.record?.id === ctx.record.id);
  if (!current || current.can?.delete !== true) return null;
  if (!/^[a-f0-9]{64}$/.test(current.sha256 || "")) throw Error("The current game could not be checked.");
  const headId = `${ctx.sheet.heading.id}-game`;
  const card = pod ? podCard(current, data, false, headId)
    : playGameCard({ record: current.record, can: { result: false, sides: [false, false] } }, data, headId);
  return { card, sha: current.sha256 };
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
    const ctx = { ...owner, pending: false, deleteSha: owner.sha };
    ctx.sheet = openSheet("Delete this game", { onClose: () => {
      document.removeEventListener("visibilitychange", reconcile);
      ctx.sheet.dialog.removeEventListener("focusin", reconcile);
      if (playDeleteSheet === ctx.sheet) playDeleteSheet = null;
    } });
    playDeleteSheet = ctx.sheet;
    ctx.reason = el("textarea", { rows: 3, maxlength: 2000, required: true });
    ctx.field = playField("Reason for deleting", ctx.reason);
    ctx.error = el("p", { class: "form-error", role: "status" });
    ctx.review = el("div", { tabindex: "-1" });
    ctx.form = el("form", {}, el("p", { text: "Delete this saved game from the Game log? The deletion and your reason are kept on Activity." }),
      ctx.review, ctx.field, ctx.error);
    ctx.sheet.body.append(ctx.form);
    ctx.cancel = el("button", { type: "button", class: "btn", text: "Keep game", onclick: () => {
      if (playDeleteHere(ctx) && !ctx.pending) ctx.sheet.close();
    } });
    ctx.confirm = el("button", { type: "button", class: "btn btn-primary", text: "Delete game" });
    ctx.sheet.foot.append(ctx.cancel, ctx.confirm);
    ctx.frame = { dialogParent: ctx.sheet.dialog.parentNode, bodyParent: ctx.sheet.body.parentNode,
      footParent: ctx.sheet.foot.parentNode };
    let reply;
    function reconcile() {
      if (!reply || !playDeleteHere(ctx)) return;
      const result = reply;
      reply = null;
      ctx.pending = false;
      ctx.cancel.disabled = false;
      ctx.confirm.disabled = false;
      if (result.deleted) {
        ctx.sheet.close(); toast("Game deleted."); route();
        return;
      }
      clear(ctx.review);
      ctx.reviewedCard = null;
      ctx.deleteSha = null;
      ctx.confirm.textContent = "Review current game";
      if (result.error) {
        ctx.error.textContent = result.error + " Review the current game before trying to delete it again.";
      } else if (result.current) {
        ctx.review.append(el("h3", { text: "Current game" }), result.current.card);
        ctx.reviewedCard = result.current.card;
        ctx.deleteSha = result.current.sha;
        ctx.confirm.textContent = "Delete game";
        ctx.error.textContent = "Check this version of the game before confirming deletion.";
        ctx.review.focus();
      } else {
        ctx.error.textContent = "This game is no longer available to delete.";
        ctx.confirm.disabled = true;
      }
    }
    const remove = async () => {
      if (!playDeleteHere(ctx) || ctx.pending || ctx.confirm.disabled) return;
      if (ctx.reviewedCard && ctx.reviewedCard.parentNode !== ctx.review) return;
      const reason = ctx.reason.value.trim();
      if (ctx.deleteSha && !reason) { ctx.error.textContent = "Give a reason for deleting this game."; ctx.reason.focus(); return; }
      ctx.pending = true; ctx.confirm.disabled = true; ctx.cancel.disabled = true;
      ctx.error.textContent = ctx.deleteSha ? "Deleting game…" : "Checking the Game log…";
      try {
        if (ctx.deleteSha) {
          const answer = await apiWrite("/api/play/game/delete", { id: ctx.record.id, sha256: ctx.deleteSha, reason, confirmed: true });
          if (answer?.deleted !== true || answer.id !== ctx.record.id) throw Error("The deletion could not be confirmed.");
          reply = { deleted: true };
        } else {
          reply = { current: await playDeleteCurrent(ctx) };
        }
      } catch (error) {
        reply = { error: error.message || "The server could not confirm the game." };
      }
      reconcile();
    };
    document.addEventListener("visibilitychange", reconcile);
    ctx.sheet.dialog.addEventListener("focusin", reconcile);
    ctx.confirm.addEventListener("click", remove);
    ctx.form.addEventListener("submit", event => { event.preventDefault(); remove(); });
    if (playDeleteHere(ctx)) ctx.reason.focus();
  });
  return source;
}
