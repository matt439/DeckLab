/* Historical token DELETE eligibility is read-only. It never enters the inventory inverse/save protocol. */
"use strict";

const ATR_ACTION = "token_restore_review";
const ATR_FIELDS = ["front", "back", "set", "front_collector_number", "back_collector_number", "finish", "quantity", "front_details", "back_details", "notes"];
const ATR_LIMITS = { front: 80, back: 80, set: 16, front_collector_number: 16,
  back_collector_number: 16, finish: 7, front_details: 300, back_details: 300, notes: 500 };

function atrText(value, maximum) {
  if (typeof value !== "string" || value.length > maximum * 2 || /[\u0000-\u001f\u007f]/.test(value)) return false;
  const points = Array.from(value);
  return points.length <= maximum && !points.some(char => char.codePointAt(0) >= 0xd800 && char.codePointAt(0) <= 0xdfff);
}
function atrHint(hint) {
  return hint && typeof hint === "object" && Object.keys(hint).sort().join(",") === "action,kind,read_only,review" &&
    hint.review === true && hint.kind === "tokens" && hint.action === ATR_ACTION && hint.read_only === true;
}

/** Accept only the distinct, complete review packet; no inverse receipt or extra apply flags are admitted. */
function atrAnswer(ctx, data) {
  const keys = "action,available,current,expect,id,identity_policy,kind,label,packing_restored,physical_confirmation_required,read_only,restored,space";
  if (!data || typeof data !== "object" || Array.isArray(data) || Object.keys(data).sort().join(",") !== keys ||
      data.available !== true || data.id !== ctx.id || data.kind !== "tokens" || data.space !== ctx.space ||
      data.action !== ATR_ACTION || data.read_only !== true || data.current !== null ||
      data.identity_policy !== "fresh_id_on_future_add" || data.packing_restored !== false || data.physical_confirmation_required !== true ||
      typeof data.expect !== "string" || !/^[a-f0-9]{64}$/.test(data.expect) || !atrText(data.label, 163) || !data.label.trim()) return null;
  const row = data.restored;
  if (!row || typeof row !== "object" || Array.isArray(row) ||
      Object.keys(row).sort().join(",") !== [...ATR_FIELDS].sort().join(",") ||
      !Number.isSafeInteger(row.quantity) || row.quantity < 1 || row.quantity > 9999 ||
      Object.entries(ATR_LIMITS).some(([key, maximum]) => !atrText(row[key], maximum)) ||
      !row.front.trim() || !["", "nonfoil", "foil", "etched"].includes(row.finish) ||
      data.label !== (row.back ? `${row.front} / ${row.back}` : row.front)) return null;
  return Object.fromEntries(ATR_FIELDS.map(key => [key, row[key]]));
}

function atrOwner(ctx) {
  const view = ctx.view;
  return view.undoCtx === ctx && view.undoBusy === true && ctx.profile === state.profile && ctx.profileId === state.profile?.id &&
    ctx.space === ownSpace() && ctx.token === routeToken && view.token === ctx.token && view.profile === ctx.profileId &&
    ctx.hash === location.hash && view.hash === ctx.hash && /^#\/activity(?:\?|$)/.test(ctx.hash) &&
    JSON.stringify(view.filter) === ctx.filterSignature && view.seq === ctx.seq && view.days === ctx.root &&
    ctx.main === $("#main") && ctx.root.isConnected && ctx.main.contains(ctx.root) &&
    ctx.button.isConnected && ctx.button.parentNode === ctx.frame && ctx.frame.parentNode === ctx.frameParent &&
    ctx.root.contains(ctx.frame) && ctx.change.id === ctx.id && atrHint(ctx.change.undo);
}
function atrHere(ctx) {
  return atrOwner(ctx) && !ctx.sheet.closed && ctx.sheet.dialog === ctx.dialog && ctx.sheet.body === ctx.body &&
    ctx.sheet.foot === ctx.foot && ctx.dialog.isConnected && ctx.dialog.parentNode === ctx.dialogParent &&
    ctx.dialog.contains(ctx.body) && ctx.dialog.contains(ctx.foot) && ctx.close.parentNode === ctx.foot &&
    ctx.refresh.parentNode === ctx.foot && ctx.close.isConnected && ctx.refresh.isConnected;
}
function atrTop(ctx) {
  return Array.from(document.querySelectorAll("dialog")).filter(node => node.isConnected &&
    (node.open || node.getAttribute("open") !== null)).at(-1) === ctx.dialog;
}

function activityTokenReviewButton(view, change) {
  if (!state.profile || !atrHint(change.undo) || !Number.isSafeInteger(change.id) || change.id < 1) return null;
  const id = change.id, profile = state.profile, profileId = profile.id, space = ownSpace(), root = view.days, token = routeToken,
    hash = location.hash, main = $("#main");
  const button = el("button", { type: "button", class: "btn btn-quiet activity-token-review", text: "Review deleted token card" });
  button.addEventListener("click", () => {
    if (view.undoBusy || view.undoRefreshNeeded || view.undoCtx || view.older?.disabled || state.profile !== profile ||
        profileId !== state.profile?.id || space !== ownSpace() || root !== view.days || !root.isConnected ||
        main !== $("#main") || !main.contains(root) || !root.contains(button) || !button.isConnected || button.disabled ||
        token !== routeToken || view.token !== token || view.profile !== profileId || hash !== location.hash || view.hash !== hash ||
        change.id !== id || !atrHint(change.undo) || keyboardDialog() || keyboardMenuOpen()) return;
    const ctx = { view, change, id, profile, profileId, space, root, token, hash, main, button,
      frame: button.parentNode, frameParent: button.parentNode.parentNode, seq: view.seq,
      filterSignature: JSON.stringify(view.filter), generation: 0, pending: false };
    view.undoCtx = ctx; view.undoBusy = true;
    atrOpen(ctx);
  });
  return button;
}

function atrOpen(ctx) {
  const sheet = ctx.sheet = colOpenSheet("Review deleted token card", { wide: true, onClose: () => {
    if (ctx.view.undoCtx === ctx) { ctx.view.undoCtx = null; ctx.view.undoBusy = false; }
  } });
  ctx.dialog = sheet.dialog; ctx.body = sheet.body; ctx.foot = sheet.foot; ctx.dialogParent = sheet.dialog.parentNode;
  ctx.close = el("button", { type: "button", class: "btn", text: "Close", onclick: () => {
    if (atrHere(ctx) && atrTop(ctx)) sheet.close();
  } });
  ctx.refresh = el("button", { type: "button", class: "btn", text: "Refresh eligibility", onclick: () => {
    if (atrHere(ctx) && atrTop(ctx) && !ctx.pending && !ctx.refresh.disabled) atrFetch(ctx);
  } });
  sheet.foot.append(ctx.close, ctx.refresh);
  atrFetch(ctx);
  if (atrHere(ctx) && atrTop(ctx)) ctx.close.focus();
}

async function atrFetch(ctx) {
  if (!atrHere(ctx) || ctx.pending) return;
  const generation = ++ctx.generation;
  ctx.pending = true; ctx.refresh.disabled = true;
  clear(ctx.body).append(loadingBox("Checking the deleted token-card row without restoring it."));
  const current = () => generation === ctx.generation && atrHere(ctx);
  try {
    const data = await api(`/api/activity/undo?id=${ctx.id}`);
    if (!current()) return;
    const row = atrAnswer(ctx, data);
    if (!row) throw new Error("Historical review unavailable");
    atrDraw(ctx, row);
    ctx.refresh.textContent = "Refresh eligibility";
  } catch (_) {
    if (!current()) return;
    clear(ctx.body).append(el("p", { class: "box box-warn", role: "status", text:
      "This deleted token-card row is not available for review. Its history, current token cards or packing may have changed. No token cards were restored." }));
    ctx.refresh.textContent = "Try again";
  } finally {
    if (current()) { ctx.pending = false; ctx.refresh.disabled = false; }
  }
}

function atrDraw(ctx, row) {
  clear(ctx.body).append(el("p", { class: "box box-warn", text:
    "Eligibility review only. Nothing has been restored, and this review cannot save an Undo." }),
    el("p", { text: `${plural(row.quantity, "physical token card")} ${row.quantity === 1 ? "was" : "were"} recorded in this deleted row.` +
      (row.back ? " Each front/back pair is one physical card." : "") }),
    el("section", { class: "panel" }, el("h3", { text: "Historical token-card row" }),
      el("dl", {}, ATR_FIELDS.flatMap(field => [el("dt", { text: field.replaceAll("_", " ") }),
        el("dd", { class: ["front_details", "back_details", "notes"].includes(field) ? "activity-undo-note" : null,
          text: row[field] === "" ? "Not recorded" : String(row[field]) })]))),
    el("p", { class: "sub", text:
      "Any future recovery must use ordinary Add to create a new token-card record. Earlier packing will not reconnect automatically. You would need to confirm that you physically have the whole recorded quantity; fewer cards need an ordinary entry with the quantity you have." }),
    el("p", { class: "sub", text:
      "Packing is not restored. This check does not change surviving token cards, deck boxes, products or the original Activity change." }));
}
