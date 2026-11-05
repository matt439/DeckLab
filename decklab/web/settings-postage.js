/* Settings' Shops' postage (E5-S27): each price-check shop's flat postage and free-postage threshold,
 * one audited household record (GET/PUT /api/shop-postage, lib/api/shop_postage.py), a home admin's.
 * Blank means not known. Shopping's Baskets and its fewest-shops plan read it; nothing here contacts a
 * shop or stores a price paid. Loaded after settings.js, whose showSettings() calls these. */
"use strict";

function postageAdmin() { return ownSpace() === HOME_SPACE && isAdminProfile(); }

function settingsPostagePanel() {
  if (!postageAdmin()) return null;
  return el("section", {class: "panel settings-part", id: "settings-postage", "aria-labelledby": "settings-postage-title"},
    el("h2", {id: "settings-postage-title", text: "Shops' postage"}),
    // A$ whatever the configured currency (E11-S53): the shops charge postage in Australian dollars.
    el("p", {class: "sub", text: "What each shop charges to post an order, and the order total that posts free, in A$. Shopping's Baskets use them to plan the fewest shops. Leave a field blank when you don't know it."
      + (priceCurrency() !== "AUD" ? " The shops charge in Australian dollars, so these stay in A$." : "")}),
    el("div", {id: "postage-settings"}, loadingBox("Loading the shops' postage…", {small: true})));
}

/** A late load must not cross a route or profile switch, or replace a newer request. */
async function loadPostageSettings(token) {
  const host = byId("postage-settings"), profile = state.profile && state.profile.id;
  if (!host || !postageAdmin()) return;
  const sequence = host.postageRequest = (host.postageRequest || 0) + 1;
  const here = () => host.isConnected && token === routeToken && sequence === host.postageRequest
    && profile === (state.profile && state.profile.id) && postageAdmin();
  clear(host).append(loadingBox("Loading the shops' postage…", {small: true}));
  try {
    const data = await api("/api/shop-postage");
    if (here()) drawPostageSettings(host, data, token, profile);
  } catch (error) {
    if (!here()) return;
    clear(host).append(el("p", {class: "form-error", role: "alert", text: `The shops' postage couldn't be loaded: ${error.message}`}),
      el("button", {type: "button", class: "btn btn-secondary", text: "Try again", onclick: () => loadPostageSettings(token)}));
  }
}

const POSTAGE_AMOUNT = /^\d{1,4}(?:\.\d{1,2})?$/;

function drawPostageSettings(host, data, token, profile) {
  if (!data.can_edit || !Number.isInteger(data.revision) || !Array.isArray(data.shops)) {
    clear(host).append(el("p", {class: "sub", text: "The shops' postage can't be edited here."}));
    return null;
  }
  const ctx = {host, token, profile, revision: data.revision, busy: false, stale: false, inputs: []};
  ctx.here = () => ctx.form.isConnected && ctx.token === routeToken && ctx.profile === (state.profile && state.profile.id) && postageAdmin();
  ctx.form = el("form", {class: "settings-fields postage-form", onsubmit: event => { event.preventDefault(); savePostage(ctx); }});
  const amount = (id, value) => el("input", {id, type: "text", inputmode: "decimal", maxlength: 9, autocomplete: "off",
    placeholder: "Not known", value: value == null ? "" : String(value)});
  for (const shop of data.shops) {
    const postage = amount(`postage-${shop.key}`, shop.postage_aud), over = amount(`postage-free-${shop.key}`, shop.free_over_aud);
    ctx.inputs.push({key: shop.key, shop: shop.shop, postage, over});
    ctx.form.append(el("fieldset", {class: "postage-shop", "data-postage-shop": shop.key}, el("legend", {text: shop.shop}),
      el("label", {class: "field", for: postage.id}, el("span", {text: "Postage (A$)"}), postage,
        el("span", {class: "field-hint", text: "0 when it always posts free."})),
      el("label", {class: "field", for: over.id}, el("span", {text: "Free postage over (A$)"}), over,
        el("span", {class: "field-hint", text: "Blank when it has no free-postage total, or you don't know it."}))));
  }
  ctx.error = el("p", {class: "form-error", role: "alert"});
  ctx.status = el("p", {class: "sub", role: "status"});
  ctx.reload = el("button", {type: "button", class: "btn btn-secondary", text: "Load the saved postage", hidden: true,
    onclick: () => { if (ctx.here() && !ctx.busy) loadPostageSettings(token); }});
  ctx.save = el("button", {type: "submit", class: "btn btn-primary", text: "Save postage"});
  ctx.form.append(ctx.error, ctx.status, ctx.reload, el("div", {class: "actions"}, ctx.save));
  for (const item of ctx.inputs) for (const input of [item.postage, item.over]) input.addEventListener("input", () => { ctx.status.textContent = ""; });
  clear(host).append(ctx.form);
  return ctx;
}

/** {key: {postage_aud, free_over_aud}} from the form, or an Error naming the field that isn't an amount. */
function postageInput(ctx) {
  const shops = {};
  for (const item of ctx.inputs) {
    const values = {};
    for (const [field, input, words] of [["postage_aud", item.postage, "postage"], ["free_over_aud", item.over, "free-postage total"]]) {
      const text = input.value.trim().replace(/^A?\$/, "");
      if (text && !POSTAGE_AMOUNT.test(text)) throw new Error(`${item.shop}'s ${words} must be an amount such as 8.50, from 0 to 9999.99, or blank.`);
      values[field] = text || null;
    }
    shops[item.key] = values;
  }
  return shops;
}

async function savePostage(ctx) {
  if (!ctx.here() || ctx.busy || ctx.stale) return;
  let shops;
  try { shops = postageInput(ctx); } catch (error) { ctx.error.textContent = error.message; return; }
  const controls = ctx.inputs.flatMap(item => [item.postage, item.over]);
  ctx.busy = true; ctx.error.textContent = ""; ctx.status.textContent = "Saving postage…";
  controls.forEach(input => { input.disabled = true; }); ctx.save.disabled = true;
  try {
    const data = await apiWrite("/api/shop-postage", {profile: ctx.profile, expect: ctx.revision, shops}, "PUT");
    if (!ctx.here()) return;
    const next = drawPostageSettings(ctx.host, data, ctx.token, ctx.profile);
    if (next) next.status.textContent = "Postage saved. Refresh Shopping to see it in Baskets.";
  } catch (error) {
    if (!ctx.here()) return;
    ctx.stale = error.status === 409;
    ctx.error.textContent = ctx.stale ? "The saved postage changed while this form was open. Your entries are still here. Load the saved postage to discard them before saving again."
      : `The postage couldn't be saved: ${error.message}`;
    ctx.status.textContent = ""; ctx.reload.hidden = !ctx.stale;
  } finally {
    ctx.busy = false;
    if (ctx.here()) { controls.forEach(input => { input.disabled = false; }); ctx.save.disabled = ctx.stale; }
  }
}
