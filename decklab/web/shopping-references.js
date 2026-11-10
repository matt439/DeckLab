/* Explicit retailer-reference and AUD market-target reviews. No price paid or order is recorded here. */
"use strict";

function shopPriceWriter(view) {
  return view && (!view.root || shopQueueActive(view)) && view.token === routeToken && view.profile === state.profile?.id
    && isAdminProfile() && mayDo("orders") && seesHomeInventory(state.may)
    && !view.busy && !view.stale && typeof view.data.queue_revision === "string" && Boolean(view.data.queue_revision);
}

function shopPriceHere(ctx, control = null) {
  return shopQueueActive(ctx.view) && ctx.hash === location.hash && !ctx.sheet.closed && ctx.sheet.dialog.isConnected
    && [...document.querySelectorAll("dialog[open]")].at(-1) === ctx.sheet.dialog
    && (!control || control.isConnected && ctx.sheet.dialog.contains(control) && !control.disabled);
}

function shopReferenceButton(card, snap, view) {
  if (!shopPriceWriter(view) || !Number.isSafeInteger(card?.queue_row) || card.queue_row < 1 || !snap?.shop_key
      || !/^[0-9a-f]{64}$/.test(snap.reference_receipt || "") || snap.carried
      || !["in_stock", "out_of_stock"].includes(snap.status)) return null;
  return el("button", {type: "button", class: "btn btn-quiet shop-queue-write shop-reference-open", text: "Use this as the reference",
    onclick: event => { if (event.currentTarget.isConnected && shopPriceWriter(view)) shopPriceReview(view, "reference", [{card, snap}]); }});
}

function shopMarketTargetButton(card, view) {
  if (!shopPriceWriter(view) || !Number.isSafeInteger(card?.queue_row) || card.queue_row < 1) return null;
  return el("button", {type: "button", class: "btn btn-quiet shop-queue-write shop-target-open", text: "Buy-under target…",
    onclick: event => { if (event.currentTarget.isConnected && shopPriceWriter(view)) shopPriceReview(view, "target", [{card}]); }});
}

function shopMarketTargetLabel(card) {
  const value = card?.buy_under_aud;
  if (typeof value !== "string" || !/^\d{1,9}\.\d{2}$/.test(value)) return null;
  return el("small", {class: "shop-market-target", text: `AUD market target: ${listedAud(Number(value))} each`});
}

function shopReferenceBulkButton(view, basket) {
  if (!shopPriceWriter(view) || !shopBasketsCurrent(view) || !basket?.read) return null;
  const candidates = (basket.rows || []).flatMap(item => {
    const card = view.data.to_buy.find(row => row.queue_row === item.queue_row);
    const snap = shopSnapshotList(card).find(line => line.shop === basket.shop && line.shop_key === basket.key && line.reference_receipt);
    return card && snap ? [{card, snap}] : [];
  });
  if (!candidates.length) return null;
  return el("button", {type: "button", class: "btn btn-quiet shop-queue-write", text: "Review ready references…",
    onclick: event => { if (event.currentTarget.isConnected && shopPriceWriter(view) && shopBasketsCurrent(view))
      shopPriceReview(view, "reference", candidates, true); }});
}

function shopPriceReview(view, kind, candidates, bulk = false) {
  if (!view?.root || !shopQueueActive(view) || !shopPriceWriter(view)) return null;
  const sheet = shopTrackQueueSheet(openSheet({title: kind === "target" ? "AUD market target" : "Review shop references", wide: true}), view);
  const ctx = {view, sheet, kind, candidates, bulk, hash: location.hash, expect: view.data.queue_revision,
    busy: false, unknown: false, saved: false, preview: null};
  ctx.message = el("div", {class: "form-error", role: "alert", hidden: true});
  ctx.content = el("div", {class: "shop-price-review"});
  sheet.body.append(ctx.message, ctx.content);
  if (kind === "target") {
    const id = `market-target-${sheet.heading.id}`;
    ctx.target = el("input", {id, type: "text", inputmode: "decimal", maxlength: 12, value: candidates[0].card.buy_under_aud || "",
      autocomplete: "off"});
    ctx.content.append(el("p", {text: candidates[0].card.name}),
      el("p", {class: "sub", text: "Optional AUD market price per copy. Saved in-stock readings at or below it are marked."}),
      el("label", {class: "field", for: id}, el("span", {text: "Buy at or below (A$ each)"}), ctx.target),
      el("p", {class: "field-hint", text: "Use at most two decimal places. Leave blank to clear the target."}));
  } else {
    ctx.content.append(el("p", {class: "sub", text: "Reference observations come from saved shop readings, with their reading date. Review the old and new values before saving."}));
    ctx.selections = candidates.map(candidate => {
      const box = el("input", {type: "checkbox"}); box.checked = !bulk;
      ctx.content.append(el("label", {class: "choice"}, box, el("span", {text:
        `${candidate.card.name} · ${candidate.snap.shop} · ${candidate.snap.price_aud == null ? "price unknown" : listedAud(Number(candidate.snap.price_aud))} · ${shopSnapshotQuality(candidate.snap)}`})));
      return {...candidate, box};
    });
    if (bulk) ctx.content.append(el("p", {class: "field-hint", text: "Select up to 100 ready rows. Add-ons and unselected rows are left as they are."}));
  }
  ctx.edit = ctx.content;
  ctx.review = el("div", {hidden: true}); sheet.body.append(ctx.review);
  shopPriceEditActions(ctx);
  return ctx;
}

function shopPriceSay(ctx, words) { ctx.message.hidden = false; ctx.message.textContent = words; }

function shopPriceEditActions(ctx) {
  sheetActions(ctx.sheet, [{text: "Cancel", onclick: () => ctx.sheet.close()},
    {text: "Preview", kind: "primary", onclick: event => shopPreviewPrice(ctx, event.currentTarget)}]);
}

function shopPriceBusy(ctx, value) {
  ctx.busy = value; shopQueueBusy(ctx.view, value);
  if (!value && ctx.pressed) { unbusy(ctx.pressed); ctx.pressed = null; }
  for (const control of ctx.sheet.dialog.querySelectorAll("input, select, button")) {
    if (value) { control.priceWasDisabled = control.disabled; control.disabled = true; }
    else if (typeof control.priceWasDisabled === "boolean") { control.disabled = control.priceWasDisabled; delete control.priceWasDisabled; }
  }
  if (value) ctx.pressed = [...ctx.sheet.foot.querySelectorAll(".btn-primary")].pop() || null;
  shopSheetBusy(ctx.sheet, value, ctx.preview ? "Saving…" : "Reviewing…");
}

async function shopPreviewPrice(ctx, control) {
  if (!shopPriceHere(ctx, control) || !shopPriceWriter(ctx.view) || ctx.busy || ctx.unknown || ctx.saved) return;
  if (ctx.expect !== ctx.view.data.queue_revision) { shopPriceSay(ctx, "Shopping changed. Close this and review the current row again."); return; }
  const requests = ctx.kind === "target" ? [{row: ctx.candidates[0].card.queue_row, value: ctx.target.value.trim() || null}]
    : ctx.selections.filter(item => item.box.checked).map(item => ({row: item.card.queue_row, shop: item.snap.shop_key, receipt: item.snap.reference_receipt}));
  if (!requests.length || requests.length > 100) { shopPriceSay(ctx, "Select 1 to 100 rows to review."); return; }
  shopPriceBusy(ctx, true); ctx.message.hidden = true;
  try {
    const data = await apiWrite("/api/shopping/queue", {action: `${ctx.kind}_preview`, expect: ctx.expect, requests});
    if (!shopPriceHere(ctx) || ctx.expect !== ctx.view.data.queue_revision) return;
    ctx.preview = data.preview;
    clear(ctx.review); ctx.edit.hidden = true; ctx.review.hidden = false;
    for (const change of data.changes || []) {
      const labels = {listed_aud: "Reference (A$ each)", listed_at: "Shop", in_stock: "In stock when checked", checked: "Reading date", buy_under_aud: "Market target (A$ each)"};
      const table = el("table", {class: "data"}, el("thead", {}, el("tr", {}, ["Field", "Old", "New"].map(text => el("th", {scope: "col", text})))),
        el("tbody", {}, Object.keys(change.new || {}).map(key => el("tr", {}, el("th", {scope: "row", text: labels[key] || key}),
          el("td", {text: change.old?.[key] || "Not recorded"}), el("td", {text: change.new[key] || "Not recorded"})))));
      const part = el("section", {}, el("h3", {text: change.name}), el("div", {class: "table-wrap"}, table));
      if (change.source) add(part, [el("p", {class: "sub", text: `${change.printing.set.toUpperCase()} ${change.printing.collector_number} ${change.printing.finish} · ${shopSnapshotQuality(change.source)}`}),
        shopSnapshotLink(change.source, "Saved listing"), shopSnapshotWhen(change.source.fetched_at)]);
      ctx.review.append(part);
    }
    if (!data.changed) ctx.review.append(el("p", {text: "Those values already match. Nothing needs saving."}));
    sheetActions(ctx.sheet, [{text: "Back", onclick: event => {
      if (!shopPriceHere(ctx, event.currentTarget) || ctx.busy) return;
      ctx.preview = null; ctx.review.hidden = true; ctx.edit.hidden = false; shopPriceEditActions(ctx);
    }}, {text: ctx.kind === "target" ? "Save target" : "Save references", kind: "primary", disabled: !data.preview,
      onclick: event => shopApplyPrice(ctx, event.currentTarget)}]);
  } catch (error) {
    if (shopPriceHere(ctx)) shopPriceSay(ctx, `Nothing saved. ${error.message}`);
  } finally {
    if (shopQueueActive(ctx.view)) shopPriceBusy(ctx, false);
    else ctx.busy = false;
  }
}

async function shopApplyPrice(ctx, control) {
  if (!shopPriceHere(ctx, control) || !shopPriceWriter(ctx.view) || ctx.busy || ctx.unknown || ctx.saved || !ctx.preview) return;
  shopPriceBusy(ctx, true); ctx.message.hidden = true;
  try {
    const data = await apiWrite("/api/shopping/queue", {action: `${ctx.kind}_apply`, preview: ctx.preview});
    if (!shopPriceHere(ctx)) return;
    ctx.saved = true;
    for (const change of data.changes || []) {
      const row = ctx.view.data.to_buy.find(item => item.queue_row === change.row);
      if (row) Object.assign(row, change.new);
    }
    ctx.view.data.queue_revision = data.revision;
    try {
      const fresh = await api("/api/shopping");
      if (!shopPriceHere(ctx)) return;
      if (fresh.queue_revision !== data.revision) throw new Error("Shopping changed again. Refresh it before another edit.");
      const queue = ctx.view.data.to_buy;
      queue.splice(0, queue.length, ...(fresh.to_buy || []));
      Object.assign(ctx.view.data, fresh, {to_buy: queue});
      ctx.view.redraw(); ctx.sheet.close();
      toast(ctx.kind === "target" ? "AUD market target saved." : "Reference observations saved.");
    } catch (refreshError) {
      if (!shopPriceHere(ctx)) return;
      ctx.view.stale = true;
      shopPriceSay(ctx, `Saved. ${refreshError.message || "Shopping couldn't be refreshed."}`);
      sheetActions(ctx.sheet, [{text: "Close", onclick: () => ctx.sheet.close()}, {text: "Refresh Shopping", onclick: event => {
        if (shopPriceHere(ctx, event.currentTarget)) { shopCloseQueueSheets(ctx.view); route(); }
      }}]);
    }
  } catch (error) {
    if (!shopPriceHere(ctx)) return;
    ctx.unknown = ![400, 403, 404, 409, 413, 429].includes(error.status);
    if (error.status === 409) ctx.view.stale = true;
    shopPriceSay(ctx, ctx.unknown ? "The save result couldn't be confirmed. Close this and refresh Shopping before recording it again."
      : `Nothing saved. ${error.message}`);
    ctx.preview = null;
    sheetActions(ctx.sheet, [{text: "Close", onclick: () => ctx.sheet.close()}, error.status === 409 ? {text: "Refresh Shopping", onclick: event => {
      if (shopPriceHere(ctx, event.currentTarget)) { shopCloseQueueSheets(ctx.view); route(); }
    }} : null]);
  } finally {
    if (shopQueueActive(ctx.view)) shopPriceBusy(ctx, false);
    else ctx.busy = false;
  }
}
