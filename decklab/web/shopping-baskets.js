/* Shopping's Baskets (E5-S27, first slice): a proposed basket a shop from the saved daily shop checks
 * (GET /api/shopping's "baskets", lib/api/shop_baskets.py). Each shop lists the ready queue rows its
 * snapshot found in stock, with the price it showed and its fetch time, and a total over the priced rows;
 * long-term and waiting rows in stock there are add-ons. No postage rules yet. A shop that couldn't be
 * read, or a row it didn't check, claims no stock. Copy this shop's list (E5-S24's copy) copies exactly
 * the basket's rows. Read only: nothing here changes the queue, records an order or stores a price. */
"use strict";

const SHOP_BASKET_WORDS = {
  in_stock: "in stock", out_of_stock: "out of stock", not_listed: "not listed",
  unknown: "couldn't be read", not_checked: "not checked", unconfirmed: "printing not confirmed",
  unread: "no saved check",
};

/** A basket's price as A$, or null when it isn't a price. */
function shopBasketAud(value) {
  if (typeof value !== "string" || !/^\d{1,9}(?:\.\d{1,2})?$/.test(value)) return null;
  return aud(Number(value));
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
    el("span", {class: "shop-basket-name", text: `${row.copies} × ${row.name}`}),
    el("span", {class: "shop-basket-facts"},
      more.length && Number.isInteger(listing.copies) ? `${listing.copies} × ` : null,
      printing ? shopSnapshotLink({shop: basket.shop, url: listing.url}, printing) : null,
      el("span", {text: ` ${each} · ${stock}`}), ...also,
      total && row.copies > 1 ? el("span", {text: ` · ${total}`}) : null,
      row.printing === "exact" ? el("small", {text: " exact printing"}) : null,
      row.carried ? el("small", {text: " from an earlier run"}) : null),
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
    el("li", {"data-basket-gap": key, text: `${words}: ${basket[key].map(row => row.name).join(", ")}`}));
  return lines.length ? el("ul", {class: "shop-basket-gaps"}, lines) : null;
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
    rows.length ? [shopBasketTotal(basket, "Total"), el("ul", {class: "shop-basket-rows"}, rows.map(row => shopBasketLine(row, basket)))]
      : el("p", {class: "sub", text: "No ready rows in stock here."}),
    shopBasketGaps(basket), copy,
    addOns.length ? el("div", {class: "shop-basket-addons"}, el("h4", {text: "Add-ons in stock here"}),
      el("p", {class: "sub", text: "Long-term and waiting rows this shop has, to add to the same order if you choose."}),
      shopBasketTotal(basket.add_ons_totals || {}, "Add-ons"),
      el("ul", {class: "shop-basket-rows"}, addOns.map(row => shopBasketLine(row, basket)))) : null);
}

/** The ready rows no checked shop has in stock, with each shop's reason. */
function shopBasketsUnavailable(list) {
  if (!list.length) return null;
  return el("div", {class: "shop-basket-unavailable"}, el("h3", {text: "Ready, not in stock at a checked shop"}),
    el("ul", {class: "shop-basket-rows"}, list.map(row => el("li", {class: "shop-basket-row", "data-basket-unavailable": row.name},
      el("span", {class: "shop-basket-name", text: `${row.quantity} × ${row.name}`}),
      el("span", {class: "shop-basket-facts", text: (row.shops || []).map(shop =>
        `${shop.shop}: ${SHOP_BASKET_WORDS[shop.status] || "not known"}`).join(" · ")})))));
}

/** The Baskets section, or null without a basket answer (no snapshot) or for a viewer outside home's records. */
function shopBaskets(view) {
  const baskets = view.data.baskets;
  if (!baskets || !seesHomeInventory(state.may) || !Array.isArray(baskets.shops)) return null;
  const stale = shopBasketsCurrent(view) ? null
    : el("p", {class: "note note-warn", role: "status", text: "The queue changed since these baskets were worked out. Refresh Shopping to update them."});
  return shopSection("shop-baskets", "Baskets", 0,
    "Proposed from each shop's saved daily check: the ready cards in stock there. Postage isn't counted yet. Check the shop before ordering.",
    stale, el("div", {class: "shop-baskets"}, baskets.shops.filter(Boolean).map(basket => shopBasket(view, basket))),
    shopBasketsUnavailable(baskets.unavailable || []));
}
