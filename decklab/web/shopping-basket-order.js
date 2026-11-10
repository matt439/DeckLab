/* Price-free hand-off of a saved basket/plan to the ordinary reviewed order sheet. */
"use strict";

function shopBasketOrderWriter(view) {
  return Boolean(view && (!view.root || shopQueueActive(view)) && view.token === routeToken && view.profile === state.profile?.id
    && isAdminProfile() && mayDo("orders") && seesHomeInventory(state.may) && !view.busy && !view.stale
    && view.data.queue_revision && shopBasketsCurrent(view));
}

function shopBasketOrderCopies(value) {
  const count = typeof value === "number" ? value : typeof value === "string" && /^\d+$/.test(value) ? Number(value) : NaN;
  return Number.isSafeInteger(count) && count > 0 && count <= 9999 ? count : null;
}

function shopBasketOrderPrinting(listing) {
  if (!listing || typeof listing !== "object" || typeof listing.set !== "string" || !/^[a-z0-9]{1,12}$/i.test(listing.set)
      || typeof listing.collector_number !== "string" || !listing.collector_number.trim() || listing.collector_number.length > 100
      || /[\u0000-\u0020\u007f]/.test(listing.collector_number) || !["nonfoil", "foil", "etched"].includes(listing.finish)) return null;
  return {set: listing.set.toLowerCase(), collector_number: listing.collector_number, finish: listing.finish};
}

/** The plan buys the same cheapest-first prefix that shop_plan._cost totals. A stock-unknown
 * shop has a single listing for every counted copy. Never spread copies by average price. */
function shopBasketOrderPrefix(item, copies) {
  const total = shopBasketOrderCopies(item?.copies);
  if (!total || copies > total || !Array.isArray(item.more)) return null;
  const ladder = item.more.length ? [item.listing, ...item.more] : [{...item.listing, copies: total}];
  const result = []; let left = copies, available = 0;
  for (const listing of ladder) {
    const count = shopBasketOrderCopies(listing?.copies), printing = shopBasketOrderPrinting(listing);
    if (!count || !printing) return null;
    available += count;
    const take = Math.min(left, count);
    if (take > 0) result.push({...printing, quantity: take});
    left -= take;
  }
  return left === 0 && available === total ? result : null;
}

/** Only current ready queue rows can seed an order; add-ons never enter this projection.
 * Return just the order's eight card columns and queue reductions, without retailer prices,
 * stock, grades, language, URLs, targets or private queue notes. */
function shopBasketOrderSeed(view, selected, basket) {
  if (!shopBasketOrderWriter(view) || !basket?.read || !Array.isArray(basket.rows) || !Array.isArray(selected?.rows)
      || !(view.data.baskets.shops || []).includes(basket) || selected.key !== basket.key || selected.shop !== basket.shop
      || selected !== basket && !(view.data.baskets.plan?.recommended?.shops || []).includes(selected)
      || typeof selected.shop !== "string" || !selected.shop.trim() || selected.shop.length > 200
      || /[\u0000-\u001f\u007f]/.test(selected.shop) || !selected.rows.length || selected.rows.length > 500) return null;
  const cards = new Map(), fulfils = [], seen = new Set();
  for (const chosen of selected.rows) {
    const number = chosen.queue_row, count = shopBasketOrderCopies(chosen.copies);
    if (!Number.isSafeInteger(number) || number < 1 || seen.has(number) || !count) return null;
    seen.add(number);
    const matches = view.data.to_buy.filter(row => row.queue_row === number);
    const sources = basket.rows.filter(row => row.queue_row === number);
    if (matches.length !== 1 || sources.length !== 1) return null;
    const queued = matches[0], source = sources[0], queuedCopies = shopBasketOrderCopies(queued.quantity);
    if (queued.state !== "ready" || source.state !== "ready" || chosen.state !== "ready" || source.status !== "in_stock"
        || source.carried || source.is_token || source.add_on || !queuedCopies || count > queuedCopies
        || source.name !== queued.name || chosen.name !== queued.name || typeof queued.name !== "string"
        || !queued.name.trim() || queued.name.length > 150 || /[\u0000-\u001f\u007f]/.test(queued.name)) return null;
    const printings = shopBasketOrderPrefix(source, count);
    if (!printings) return null;
    for (const printing of printings) {
      const key = JSON.stringify([queued.name, printing.set, printing.collector_number, printing.finish]);
      const existing = cards.get(key);
      if (existing) {
        existing.quantity += printing.quantity;
        if (existing.quantity > 9999) return null;
      } else cards.set(key, {name: queued.name, ...printing, condition: "", language: "", notes: ""});
    }
    fulfils.push({row: number, quantity: count});
  }
  if (cards.size > 500) return null;
  return {expect: view.data.queue_revision, seller: selected.shop, ordered_on: shopOrderToday(), cards: [...cards.values()], fulfils};
}

function shopBasketOrderButton(view, selected, basket = selected) {
  if (!shopBasketOrderSeed(view, selected, basket)) return null;
  return el("button", {type: "button", class: "btn btn-quiet shop-queue-write shop-basket-order", text: "Record this order…",
    "aria-label": `Record this order from ${selected.shop}`, onclick: event => {
      if (!event.currentTarget.isConnected || !view.root || !shopQueueActive(view)
          || document.querySelectorAll("dialog[open]").length) return;
      const seed = shopBasketOrderSeed(view, selected, basket);
      if (seed) shopOrderSheet(view, seed);
    }});
}
