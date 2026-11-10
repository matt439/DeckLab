/* Shopping's Baskets (E5-S27): a proposed basket a shop from the saved daily shop checks
 * (GET /api/shopping's "baskets", lib/api/shop_baskets.py). Each shop lists the ready queue rows its
 * snapshot found in stock, with the price it showed and its fetch time, a total over the priced rows and
 * its postage from the rules a home admin sets in Settings (settings-postage.js; unknown when not set);
 * long-term and waiting rows in stock there are add-ons, those that reach the free-postage threshold
 * marked. The fewest-shops plan comes first (shopping-plan.js). A shop that couldn't be read, or a row
 * it didn't check, claims no stock. Copy this shop's list (E5-S24's copy) copies exactly the basket's
 * rows. Read only: nothing here changes the queue, records an order or stores a price. */
"use strict";

const SHOP_BASKET_WORDS = {
  in_stock: "in stock", out_of_stock: "out of stock", not_listed: "not listed",
  unknown: "couldn't be read", not_checked: "not checked", unconfirmed: "printing not confirmed",
  unread: "no saved check", not_matched: "listed, but not matched to your printing",
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

/** One row's listing words: "2 × Name", the printing, the price each and the stock, then any further
 * listings an any-printing row is filled from ("also 1 × M19 314 A$0.50 each") and the line's total. */
function shopBasketLine(row, basket) {
  const listing = row.listing || {};
  const price = shopBasketAud(listing.price_aud);
  const printing = listing.set ? `${String(listing.set).toUpperCase()} ${listing.collector_number || ""}`.trim()
    + (listing.finish && listing.finish !== "nonfoil" ? ` ${listing.finish}` : "") : null;
  const each = price ? `${price} each` : "price not shown";
  const more = Array.isArray(row.more) ? row.more.filter(item => item && item.set) : [];
  const counted = Number.isInteger(row.stock) ? row.stock : listing.stock;
  const stock = basket.counts_stock ? (row.short ? `only ${counted} of ${row.quantity} in stock`
    : more.length ? `${counted} in stock across ${more.length + 1} printings` : `${listing.stock} in stock`)
    : "in stock (count not shown)";
  const total = shopBasketAud(row.line_aud);
  const also = more.map(item => {
    const name = `${String(item.set).toUpperCase()} ${item.collector_number || ""}`.trim()
      + (item.finish && item.finish !== "nonfoil" ? ` ${item.finish}` : "");
    const itemPrice = shopBasketAud(item.price_aud);
    return el("span", {class: "shop-basket-more", "data-basket-more": name},
      ` · also ${item.copies} × `, shopSnapshotLink({shop: basket.shop, url: item.url}, name),
      ` ${itemPrice ? `${itemPrice} each` : "price not shown"}`);
  });
  return el("li", {class: "shop-basket-row", "data-basket-row": row.name, "data-basket-status": row.status},
    row.add_on ? status("outline", "Add-on") : null,
    row.lifts ? status("good", "Reaches free postage") : null,
    el("span", {class: "shop-basket-name", text: `${row.copies} × ${row.name}`}),
    el("span", {class: "shop-basket-facts"},
      more.length && Number.isInteger(listing.copies) ? `${listing.copies} × ` : null,
      printing ? shopSnapshotLink({shop: basket.shop, url: listing.url}, printing) : null,
      el("span", {text: ` ${each} · ${stock}`}), ...also,
      total && row.copies > 1 ? el("span", {text: ` · ${total}`}) : null,
      row.printing === "exact" ? el("small", {text: " exact printing"}) : null,
      row.carried ? el("small", {text: " from an earlier run"}) : null,
      row.partial === true ? el("small", {class: "shop-snapshot-partial", "data-basket-partial": "",
        text: ` ${SHOP_SNAPSHOT_PARTIAL}`}) : null),
    shopSnapshotWhen(row.fetched_at));
}

/** "A$12.50 for 5 cards; 1 without a price", or the words for none priced. */
function shopBasketTotal(totals, what) {
  const total = shopBasketAud(totals.total_aud);
  const parts = [total ? `${what} ${total} for ${plural(totals.priced, "priced row")}` : `${what} not known: no row has a price`];
  if (total && totals.unpriced) parts.push(`${plural(totals.unpriced, "row")} without a price`);
  return el("p", {class: "shop-basket-total", "data-basket-total": totals.total_aud || "", text: parts.join("; ")});
}

/** The rows a shop couldn't speak for, named so nothing is claimed. */
function shopBasketGaps(basket) {
  const gaps = [["unconfirmed", "Printing not confirmed here, so no stock is claimed"],
    ["unknown", "Couldn't be read here"], ["not_checked", "Not in this shop's last check"]];
  const lines = gaps.filter(([key]) => (basket[key] || []).length).map(([key, words]) =>
    el("li", {"data-basket-gap": key, text: `${words}: ${basket[key].map(row =>
      row.partial === true ? `${row.name} (${SHOP_SNAPSHOT_PARTIAL})` : row.name).join(", ")}`}));
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
    rows.length ? [shopBasketTotal(basket, "Total"), el("ul", {class: "shop-basket-rows"}, rows.map(row => shopBasketLine(row, basket)))]
      : el("p", {class: "sub", text: "No ready rows in stock here."}),
    shopBasketGaps(basket), copy,
    addOns.length ? el("div", {class: "shop-basket-addons"}, el("h4", {text: "Add-ons in stock here"}),
      el("p", {class: "sub", text: "Long-term and waiting rows this shop has, to add to the same order if you choose."}),
      shopBasketTotal(basket.add_ons_totals || {}, "Add-ons"), rows.length ? shopBasketReach(basket) : null,
      el("ul", {class: "shop-basket-rows"}, addOns.map(row => shopBasketLine(row, basket)))) : null);
}

/** The ready rows no checked shop has in stock, with each shop's reason. */
function shopBasketsUnavailable(list) {
  if (!list.length) return null;
  return el("div", {class: "shop-basket-unavailable"}, el("h3", {text: "Ready, not in stock at a checked shop"}),
    el("ul", {class: "shop-basket-rows"}, list.map(row => el("li", {class: "shop-basket-row", "data-basket-unavailable": row.name},
      el("span", {class: "shop-basket-name", text: `${row.quantity} × ${row.name}`}),
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
    shopBasketsUnavailable(baskets.unavailable || []));
}
