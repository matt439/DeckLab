/* Settings' Prices (E11-S53): the currency price estimates are in and the price-check shops the nightly
 * snapshot reads, a home admin's choice (GET/PUT /api/pricing-setting, lib/api/pricing_setting.py), saved as
 * one audited household record over config.json's "currency" and "shops", which apply where nothing is
 * chosen here. No restart: Deck Lab uses a change within a minute. Loaded after settings.js, whose
 * showSettings() calls these. */
"use strict";

const PRICING_SOURCE_WORDS = {saved: "Set here", config: "From config.json", default: "The default"};

function pricingAdmin() { return ownSpace() === HOME_SPACE && isAdminProfile(); }

function settingsPricingPanel() {
  if (!pricingAdmin()) return null;
  return el("section", {class: "panel settings-part", id: "settings-prices", "aria-labelledby": "settings-prices-title"},
    el("h2", {id: "settings-prices-title", text: "Prices"}),
    el("p", {class: "sub", text: "The currency Deck Lab's price estimates are in, converted from Scryfall's US prices at the ECB's rate, and the shops the nightly price check reads."}),
    el("div", {id: "pricing-settings"}, loadingBox("Loading the price settings…", {small: true})));
}

/** A late load must not cross a route or profile switch, or replace a newer request. A refusal hides the panel. */
async function loadPricingSettings(token) {
  const host = byId("pricing-settings"), profile = state.profile && state.profile.id;
  if (!host || !pricingAdmin()) return;
  const sequence = host.pricingRequest = (host.pricingRequest || 0) + 1;
  const here = () => host.isConnected && token === routeToken && sequence === host.pricingRequest
    && profile === (state.profile && state.profile.id) && pricingAdmin();
  clear(host).append(loadingBox("Loading the price settings…", {small: true}));
  try {
    const data = await api("/api/pricing-setting");
    if (here()) drawPricingSettings(host, data, token, profile);
  } catch (error) {
    if (!here()) return;
    if (error.status === 403) {
      const panel = byId("settings-prices");
      if (panel) panel.hidden = true;
      return;
    }
    clear(host).append(el("p", {class: "form-error", role: "alert", text: `The price settings couldn't be loaded: ${error.message}`}),
      el("button", {type: "button", class: "btn btn-secondary", text: "Try again", onclick: () => loadPricingSettings(token)}));
  }
}

function pricingAnswer(data) {
  return data && Number.isInteger(data.revision) && data.currency && typeof data.currency.effective === "string"
    && data.shops && Array.isArray(data.shops.choices) && Array.isArray(data.shops.effective) && Array.isArray(data.currencies);
}

function pricingSourceLine(data) {
  const words = source => PRICING_SOURCE_WORDS[source] || PRICING_SOURCE_WORDS.default;
  const names = new Map(data.shops.choices.map(shop => [shop.key, shop.name]));
  const shops = data.shops.effective.map(key => names.get(key) || key);
  return `Now: estimates in ${data.currency.effective} (${words(data.currency.source).toLowerCase()}); ` +
    `price-check shops ${shops.length ? shops.join(", ") : "none, so the nightly shop check is off"} (${words(data.shops.source).toLowerCase()}).`;
}

function drawPricingSettings(host, data, token, profile) {
  if (!pricingAnswer(data)) {
    clear(host).append(el("p", {class: "form-error", role: "alert", text: "The price settings couldn't be read."}));
    return null;
  }
  const notes = [
    el("p", {class: "sub", id: "pricing-source", text: pricingSourceLine(data)}),
    el("p", {class: "sub", text: "No restart needed: Deck Lab uses a change within a minute. Deck tables keep their old currency until they're repriced: Decks, Tables out of date, Update all, or deck tables --reprice --apply on the PC. Shops' own prices and postage stay in A$, as the shops list them."})];
  if (!data.can_edit) {
    clear(host).append(...notes);
    return null;
  }
  const ctx = {host, token, profile, revision: data.revision, busy: false, stale: false};
  ctx.here = () => ctx.form.isConnected && ctx.token === routeToken && ctx.profile === (state.profile && state.profile.id) && pricingAdmin();
  const configCode = data.currency.config || "AUD, the default";
  ctx.currency = el("select", {id: "pricing-currency", style: "max-width: 320px"},
    el("option", {value: "", text: `Use config.json's (${configCode})`}),
    data.currencies.map(item => el("option", {value: item.code, text: item.symbol && item.symbol.trim() !== item.code ? `${item.code} (${item.symbol.trim()})` : item.code})));
  ctx.currency.value = data.currency.saved || "";
  const configShops = data.shops.config ? data.shops.config.map(key => (data.shops.choices.find(shop => shop.key === key) || {name: key}).name) : null;
  ctx.useConfig = el("input", {type: "checkbox", id: "pricing-shops-config"});
  ctx.useConfig.checked = data.shops.saved == null;
  const ticked = new Set(data.shops.saved == null ? data.shops.effective : data.shops.saved);
  ctx.shops = data.shops.choices.map(shop => {
    const box = el("input", {type: "checkbox", id: `pricing-shop-${shop.key}`, "data-shop": shop.key});
    box.checked = ticked.has(shop.key);
    return {key: shop.key, box, label: el("label", {class: "choice", for: box.id}, box, el("span", {text: ` ${shop.name}`}))};
  });
  ctx.off = el("p", {class: "field-hint", id: "pricing-shops-off"});
  const sync = () => {
    for (const item of ctx.shops) item.box.disabled = ctx.useConfig.checked || ctx.busy;
    const none = !ctx.useConfig.checked && ctx.shops.every(item => !item.box.checked);
    ctx.off.textContent = none ? "No shop ticked: the nightly shop check is off, and Shopping shows no shop prices." : "";
    ctx.status.textContent = "";
  };
  ctx.form = el("form", {class: "settings-fields pricing-form", onsubmit: event => { event.preventDefault(); savePricing(ctx); }});
  ctx.error = el("p", {class: "form-error", role: "alert"});
  ctx.status = el("p", {class: "sub", role: "status"});
  ctx.reload = el("button", {type: "button", class: "btn btn-secondary", text: "Load the saved price settings", hidden: true,
    onclick: () => { if (ctx.here() && !ctx.busy) loadPricingSettings(token); }});
  ctx.save = el("button", {type: "submit", class: "btn btn-primary", text: "Save price settings"});
  ctx.form.append(
    el("label", {class: "field", for: ctx.currency.id}, el("span", {text: "Currency"}), ctx.currency,
      el("span", {class: "field-hint", text: "Prices are estimates, from Scryfall's US prices at the ECB's daily rate."})),
    el("fieldset", {class: "pricing-shops"}, el("legend", {text: "Price-check shops"}),
      el("label", {class: "choice", for: ctx.useConfig.id}, ctx.useConfig,
        el("span", {text: ` Use config.json's (${configShops ? (configShops.length ? configShops.join(", ") : "none") : "every shop, the default"})`})),
      ctx.shops.map(item => item.label), ctx.off),
    ...notes, ctx.error, ctx.status, ctx.reload, el("div", {class: "actions"}, ctx.save));
  ctx.currency.addEventListener("change", sync);
  ctx.useConfig.addEventListener("change", sync);
  for (const item of ctx.shops) item.box.addEventListener("change", sync);
  clear(host).append(ctx.form);
  sync();
  return ctx;
}

/** {currency, shops} as the form says: null for "use config.json's", [] when no shop is ticked. */
function pricingInput(ctx) {
  return {currency: ctx.currency.value || null,
    shops: ctx.useConfig.checked ? null : ctx.shops.filter(item => item.box.checked).map(item => item.key)};
}

async function savePricing(ctx) {
  if (!ctx.here() || ctx.busy || ctx.stale) return;
  const chosen = pricingInput(ctx);
  const controls = [ctx.currency, ctx.useConfig, ...ctx.shops.map(item => item.box)];
  ctx.busy = true; ctx.error.textContent = ""; ctx.status.textContent = "Saving the price settings…";
  controls.forEach(input => { input.disabled = true; }); ctx.save.disabled = true;
  try {
    const data = await apiWrite("/api/pricing-setting", {profile: ctx.profile, expect: ctx.revision, ...chosen}, "PUT");
    if (!ctx.here()) return;
    const next = drawPricingSettings(ctx.host, data, ctx.token, ctx.profile);
    if (next) next.status.textContent = "Price settings saved.";
    if (typeof showFooter === "function") showFooter();      // state.status's pricing: aud() and About follow at once
  } catch (error) {
    if (!ctx.here()) return;
    ctx.stale = error.status === 409;
    ctx.error.textContent = ctx.stale ? "The saved price settings changed while this form was open. Your choices are still here. Load the saved price settings to discard them before saving again."
      : `The price settings couldn't be saved: ${error.message}`;
    ctx.status.textContent = ""; ctx.reload.hidden = !ctx.stale;
  } finally {
    ctx.busy = false;
    if (ctx.here()) {
      ctx.currency.disabled = false; ctx.useConfig.disabled = false;
      for (const item of ctx.shops) item.box.disabled = ctx.useConfig.checked;
      ctx.save.disabled = ctx.stale;
    }
  }
}
