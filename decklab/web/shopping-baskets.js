/* Shopping's Baskets (E5-S27): a proposed basket a shop from the saved daily shop checks
 * (GET /api/shopping's "baskets", lib/api/shop_baskets.py). Each shop lists the ready queue rows its
 * snapshot found in stock, with the price it showed and its fetch time, a total over the priced rows and
 * its postage from the rules a home admin sets in Settings (settings-postage.js; unknown when not set);
 * long-term and waiting rows in stock there are add-ons, those that reach the free-postage threshold
 * marked. The fewest-shops plan comes first (shopping-plan.js). A shop that couldn't be read, or a row
 * it didn't check, claims no stock. Copy this shop's list (E5-S24's copy) copies exactly the basket's
 * rows. Each read basket also has a collapsed note of the token cards the built decks make but have none of
 * (E5-S38, "token_addons"), names only, with Copy names. Read only: nothing here changes the queue, records an
 * order or stores a price. */
"use strict";

const SHOP_BASKET_WORDS = {
  in_stock: "in stock", out_of_stock: "out of stock", not_listed: "not listed",
  unknown: "couldn't be read", not_checked: "not checked", unconfirmed: "printing not confirmed",
  unread: "no saved check", not_matched: "listed, but not matched to your printing",
  not_eligible: "no listing meets the household condition/language preference",
  token: "token cards aren't checked at this shop",
};

/** One shop's reason a ready row isn't in a basket, with the shop's sets for a printing it didn't match and
 * whether its page was only the first of its results (E5-S33). */
function shopBasketReason(shop) {
  const sets = shop.status === "not_matched" ? shopSnapshotSets(shop) : "";
  return `${shop.shop}: ${SHOP_BASKET_WORDS[shop.status] || "not known"}${sets ? ` (the shop's sets: ${sets})` : ""}`
    + (shop.partial === true ? `, ${SHOP_SNAPSHOT_PARTIAL}` : "");
}

/** A basket's price as A$, or null when it isn't a price. Always A$: the shops list in AUD, never the configured
 * currency's estimate (E11-S53). */
function shopBasketAud(value) {
  if (typeof value !== "string" || !/^\d{1,9}(?:\.\d{1,2})?$/.test(value)) return null;
  return listedAud(Number(value));
}

/** True when these baskets were worked out for the queue the page now shows. */
function shopBasketsCurrent(view) {
  const baskets = view.data.baskets;
  return Boolean(baskets) && baskets.queue_revision === view.data.queue_revision;
}

/** The rows a basket copies: each row as queued, with the copies the basket counts. */
function shopBasketCopyList(view, key) {
  if (!shopBasketsCurrent(view)) return null;
  const basket = (view.data.baskets.shops || []).find(shop => shop && shop.key === key);
  if (!basket || !basket.read || !Array.isArray(basket.rows) || !basket.rows.length) return null;
  return shopCopyRows(basket.rows.map(row => ({...row, quantity: row.copies})));
}

/** Optional name-level art from this answer's current, unambiguous queue row, never a shop-printing claim. */
function shopBasketArt(view, row) {
  if (!view || !shopBasketsCurrent(view) || !view.data.queue_revision || row.is_token
      || !Number.isSafeInteger(row.queue_row) || row.queue_row < 1) return null;
  const matches = (view.data.to_buy || []).filter(item => item.queue_row === row.queue_row);
  const queued = matches.length === 1 ? matches[0] : null;
  const src = queued?.name === row.name && !queued.is_token ? queued.card?.img_small : null;
  return typeof src === "string" && src ? el("img", {class: "shop-basket-art", src, alt: "", loading: "lazy", decoding: "async",
    width: 40, height: 56, onerror: event => event.currentTarget.remove()}) : null;
}

/** Quantity/name and the already-computed line total; plans reuse only this header, not shop evidence. */
function shopBasketItemHead(row, view = null, {copies = row.copies, showTotal = true} = {}) {
  const total = shopBasketAud(row.line_aud);
  return el("div", {class: "shop-basket-item-head"}, shopBasketArt(view, row),
    el("span", {class: "shop-basket-name", text: `${copies} × ${row.name}`}),
    showTotal ? el("span", {class: "shop-basket-line-total"},
      el("small", {text: "Row total"}), el(total ? "strong" : "span", {text: total || "Not known"})) : null);
}

function shopBasketActions(...controls) {
  return controls.some(Boolean) ? el("div", {class: "shop-basket-actions"}, controls) : null;
}

/** One row's listing words: "2 × Name", the printing, the price each and the stock, then any further
 * listings an any-printing row is filled from ("also 1 × M19 314 A$0.50 each") and the line's total. */
function shopBasketLine(row, basket, view = null) {
  const listing = row.listing || {};
  const price = shopBasketAud(listing.price_aud);
  const printing = listing.set ? `${String(listing.set).toUpperCase()} ${listing.collector_number || ""}`.trim()
    + (listing.finish && listing.finish !== "nonfoil" ? ` ${listing.finish}` : "") : null;
  const each = price ? `${price} each` : "price not shown";
  const more = Array.isArray(row.more) ? row.more.filter(item => item && item.set) : [];
  const counted = Number.isInteger(row.stock) ? row.stock : listing.stock;
  const stock = basket.counts_stock ? (row.short ? `only ${counted} of ${row.quantity} in stock`
    : more.length ? `${counted} in stock across ${more.length + 1} listings` : `${listing.stock} in stock`)
    : "in stock (count not shown)";
  const also = more.map(item => {
    const name = `${String(item.set).toUpperCase()} ${item.collector_number || ""}`.trim()
      + (item.finish && item.finish !== "nonfoil" ? ` ${item.finish}` : "");
    const itemPrice = shopBasketAud(item.price_aud);
    return el("span", {class: "shop-basket-more shop-basket-listing", "data-basket-more": name},
      el("span", {class: "shop-basket-printing"}, `also ${item.copies} × `, shopSnapshotLink({shop: basket.shop, url: item.url}, name)),
      " ", el("span", {class: "shop-basket-unit-price", text: itemPrice ? `${itemPrice} each` : "price not shown"}),
      el("small", {class: "shop-snapshot-quality", text: shopSnapshotQuality(item)}));
  });
  return el("li", {class: "shop-basket-row", "data-basket-row": row.name, "data-basket-status": row.status},
    shopBasketItemHead(row, view), row.add_on ? status("outline", "Add-on") : null,
    row.lifts ? status("good", "Reaches free postage") : null,
    el("span", {class: "shop-basket-facts"},
      el("span", {class: "shop-basket-listing"},
        el("span", {class: "shop-basket-printing"}, more.length && Number.isInteger(listing.copies) ? `${listing.copies} × ` : null,
          printing ? shopSnapshotLink({shop: basket.shop, url: listing.url}, printing) : null),
        " ", el("span", {class: "shop-basket-unit-price", text: each}),
        el("small", {class: "shop-snapshot-quality", text: shopSnapshotQuality(listing)})),
      el("span", {class: `shop-basket-stock${row.short ? " status status-warn" : ""}`, text: stock}), ...also,
      row.skipped_cheaper ? el("small", {text: " · Cheaper copy skipped by household preference"}) : null,
      row.printing === "exact" ? el("small", {text: " exact printing"}) : null,
      row.carried ? el("small", {text: " from an earlier run"}) : null,
      row.partial === true ? el("small", {class: "shop-snapshot-partial", "data-basket-partial": "",
        text: ` ${SHOP_SNAPSHOT_PARTIAL}`}) : null),
    shopSnapshotWhen(row.fetched_at));
}

/** "A$12.50 for 5 cards; 1 without a price", or the words for none priced. */
function shopBasketTotal(totals, what) {
  const total = shopBasketAud(totals.total_aud);
  return el("p", {class: "shop-basket-total", "data-basket-total": totals.total_aud || ""},
    el("span", {class: "shop-basket-total-label", text: `${what} `}),
    total ? [el("strong", {class: "shop-basket-amount", text: total}),
      el("span", {class: "shop-basket-total-note", text: ` for ${plural(totals.priced, "priced row")}`
        + (totals.unpriced ? `; ${plural(totals.unpriced, "row")} without a price` : "")})]
      : el("span", {class: "shop-basket-total-note", text: "not known: no row has a price"}));
}

/** The rows a shop couldn't speak for, named so nothing is claimed. */
function shopBasketGaps(basket) {
  const gaps = [["unconfirmed", "Printing not confirmed here, so no stock is claimed"],
    ["unknown", "Couldn't be read here"], ["not_checked", "Not in this shop's last check"]];
  const lines = gaps.filter(([key]) => (basket[key] || []).length).map(([key, words]) =>
    el("li", {"data-basket-gap": key}, el("strong", {text: `${words}: `}),
      el("span", {text: basket[key].map(row => row.partial === true ? `${row.name} (${SHOP_SNAPSHOT_PARTIAL})` : row.name).join(", ")})));
  return lines.length ? el("ul", {class: "shop-basket-gaps"}, lines) : null;
}

/** A basket's postage in words: free, its flat postage and how far from free, or not known. */
function shopBasketPostageWords(postage) {
  if (!postage) return null;
  const flat = shopBasketAud(postage.postage_aud), over = shopBasketAud(postage.free_over_aud);
  const short = shopBasketAud(postage.short_by_aud), least = postage.at_least ? " (some rows have no price)" : "";
  if (postage.free) return over && postage.postage_aud !== "0.00" ? `Free postage: over ${over}${least}.` : "Posts free.";
  const charged = flat ? `Postage ${flat}` : "Postage not known";
  return short ? `${charged}; free over ${over}, ${short} more${least}.` : `${charged}.`;
}

function shopBasketPostage(postage) {
  const words = shopBasketPostageWords(postage);
  if (!words) return null;
  const unset = !postage.postage_aud && !postage.free_over_aud;
  return el("p", {class: `shop-basket-postage${postage.known ? "" : " shop-basket-postage-unknown"}`,
    "data-basket-postage": postage.charged_aud || ""}, words,
    unset && isAdminProfile() ? [" ", el("a", {href: "#/settings?part=postage", text: "Set postage in Settings"})] : null);
}

/** What the marked add-ons do for the basket's postage, or that even all of them fall short. */
function shopBasketReach(basket) {
  const reach = basket.reach, postage = basket.postage;
  if (!reach || !postage) return null;
  const total = shopBasketAud(reach.total_aud), flat = shopBasketAud(postage.postage_aud);
  if (!reach.reaches) return el("p", {class: "sub", "data-basket-reach": "short",
    text: `Even every add-on here (${total}) doesn't reach free postage.`});
  return el("p", {class: "shop-basket-reach", "data-basket-reach": reach.total_aud,
    text: `Adding the add-ons marked Reaches free postage (${total}) gets this order free postage${flat ? `, saving ${flat}` : ""}. They're on the queue already, so only bring them forward if you want them now.`});
}

/** The token add-ons (E5-S38): GET /api/shopping's "token_addons", checked, or [] (left out, or a viewer outside home's records). */
function shopTokenAddons(view) {
  const list = view?.data?.token_addons;
  if (!Array.isArray(list) || !seesHomeInventory(state.may)) return [];
  return list.filter(item => item && typeof item.name === "string" && item.name.trim()
    && !/[\u0000-\u001f\u007f]/.test(item.name) && Number.isSafeInteger(item.decks) && item.decks > 0);
}

/** The token names as copy text, one a line. */
function shopTokenAddonsText(view) {
  const names = shopTokenAddons(view).map(item => item.name.trim());
  return names.length ? names.join("\n") + "\n" : "";
}

/** Copy names: the clipboard, else a sheet to select them in. Read only: nothing is queued or added to an order. */
async function shopCopyTokenAddons(view, button) {
  const text = shopTokenAddonsText(view);
  if (!text || !button?.isConnected || button.disabled) return;
  const count = text.trim().split("\n").length;
  button.disabled = true;
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
    await navigator.clipboard.writeText(text);
    toast(`${plural(count, "token name")} copied.`);
  } catch (error) {
    if (!button.isConnected) return;
    const sheet = shopTrackQueueSheet(openSheet({title: "Copy token card names",
      onClose: () => { if (button.isConnected) button.focus({preventScroll: true}); }}), view);
    const area = el("textarea", {readonly: "", rows: Math.min(12, count + 1), class: "export-copy shop-copy-text",
      "aria-label": "Token card names", spellcheck: "false"});
    area.value = text;
    sheet.body.append(el("p", {text: "Select and copy the names below."}), area);
    sheetActions(sheet, [{text: "Close", onclick: () => sheet.close()}]);
    area.focus(); area.select();
  } finally {
    if (button.isConnected) button.disabled = false;
  }
}

/** A basket's collapsed note of the token cards the built decks make but have none of: names and how many decks
 * want each, never a price or stock (tokens aren't looked up at shops), with Copy names. Null when there are none. */
function shopBasketTokenAddons(view, basket) {
  const list = shopTokenAddons(view);
  if (!list.length) return null;
  return el("details", {class: "shop-basket-tokens", "data-basket-tokens": basket.key},
    el("summary", {text: `Token cards your decks make but you don't have (not checked at this shop) (${list.length})`}),
    el("p", {class: "sub", text: "Suggestions to look for here, not requirements: nothing is queued or added to this order, and no price or stock is claimed."}),
    el("ul", {class: "shop-basket-gaps"}, list.map(item => el("li", {"data-token-addon": item.name},
      el("strong", {text: item.name}),
      el("span", {text: `${item.kind && item.kind !== "token" ? `${item.kind}; ` : ""}wanted by ${plural(item.decks, "built deck")}`})))),
    el("button", {type: "button", class: "btn btn-quiet shop-basket-token-copy", text: "Copy names",
      "aria-label": `Copy the token card names for ${basket.shop}`,
      onclick: event => shopCopyTokenAddons(view, event.currentTarget)}));
}

function shopBasket(view, basket) {
  const head = el("div", {class: "shop-basket-head"}, el("h3", {text: basket.shop}), shopSnapshotWhen(basket.fetched_at));
  if (!basket.read) return el("article", {class: "shop-basket", "data-basket": basket.key, "data-basket-read": "false"}, head,
    el("p", {class: "note", text: `${basket.shop}'s saved check couldn't be read, so no stock is claimed there.`}));
  const rows = basket.rows || [], addOns = basket.add_ons || [];
  const copy = rows.length ? el("button", {type: "button", class: "btn btn-quiet shop-basket-copy", text: "Copy this shop's list",
    "aria-label": `Copy this shop's list for ${basket.shop}`, "data-copy-shop": basket.shop,
    title: "Copy this basket's ready rows, not its add-ons.",
    onclick: event => shopCopyShop(view, basket.shop, event.currentTarget, {list: () => shopBasketCopyList(view, basket.key),
      note: "in this basket's ready rows (add-ons not included)", selector: ".shop-basket-copy"})}) : null;
  if (copy && !shopBasketsCurrent(view)) copy.disabled = true;
  return el("article", {class: "shop-basket", "data-basket": basket.key, "data-basket-read": "true"}, head,
    rows.length ? shopBasketPostage(basket.postage) : null,
    rows.length ? [shopBasketTotal(basket, "Total"), el("ul", {class: "shop-basket-rows"}, rows.map(row => shopBasketLine(row, basket, view)))]
      : el("p", {class: "sub", text: "No ready rows in stock here."}),
    shopBasketGaps(basket), shopBasketActions(copy, shopReferenceBulkButton(view, basket), shopBasketOrderButton(view, basket)),
    addOns.length ? el("div", {class: "shop-basket-addons"}, el("h4", {text: "Add-ons in stock here"}),
      el("p", {class: "sub", text: "Long-term and waiting rows this shop has, to add to the same order if you choose."}),
      shopBasketTotal(basket.add_ons_totals || {}, "Add-ons"), rows.length ? shopBasketReach(basket) : null,
      el("ul", {class: "shop-basket-rows"}, addOns.map(row => shopBasketLine(row, basket, view)))) : null,
    shopBasketTokenAddons(view, basket));
}

/** The ready rows no checked shop has in stock, with each shop's reason. */
function shopBasketsUnavailable(list, view = null) {
  if (!list.length) return null;
  return el("div", {class: "shop-basket-unavailable"}, el("h3", {text: "Ready, not in stock at a checked shop"}),
    el("ul", {class: "shop-basket-rows"}, list.map(row => el("li", {class: "shop-basket-row", "data-basket-unavailable": row.name},
      shopBasketItemHead(row, view, {copies: row.quantity, showTotal: false}),
      el("span", {class: "shop-basket-facts", text: (row.shops || []).map(shopBasketReason).join(" · ")})))));
}

/** The Baskets section, or null without a basket answer (no snapshot) or for a viewer outside home's records. */
function shopBaskets(view) {
  const baskets = view.data.baskets;
  if (!baskets || !seesHomeInventory(state.may) || !Array.isArray(baskets.shops)) return null;
  const stale = shopBasketsCurrent(view) ? null
    : el("p", {class: "note note-warn", role: "status", text: "The queue changed since these baskets were worked out. Refresh Shopping to update them."});
  return shopSection("shop-baskets", "Baskets", 0,
    "Proposed from each shop's saved daily check: the ready cards in stock there, and each shop's postage as set in Settings. Check the shop before ordering.",
    stale, typeof shopBasketPlan === "function" ? shopBasketPlan(view) : null, el("div", {class: "shop-baskets"}, baskets.shops.filter(Boolean).map(basket => shopBasket(view, basket))),
    shopBasketsUnavailable(baskets.unavailable || [], view));
}
