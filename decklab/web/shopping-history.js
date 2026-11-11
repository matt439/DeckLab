/* A queued card's price history on Shopping (E5-S29; GET /api/shopping/price-history, lib/api/shop_history.py).
 * Loaded after shopping-snapshot.js. A queued row with a shop snapshot has a "Price history" button beside its
 * snapshot line (in the lab table, in the row's extra details with the snapshot); it opens a sheet that asks for
 * the card's daily readings at each shop (kept 90 days, only while the card is queued) and shows, per shop, the
 * lowest in-stock price first, then each day newest first with its price and stock. The sheet asks for the
 * row itself (its queue_row, E5-S33), so each day is read for that row's own printing and finish, and says which;
 * a day the shop listed the card only in another printing says so, and so does a day whose page was only the
 * first of the shop's results. Read only: nothing is saved, and an answer that comes after the sheet closed, or
 * for another profile or route, is dropped. */
"use strict";

/** "2 Nov" for a reading's day. */
function shopHistoryDay(value) {
  const at = typeof value === "string" ? new Date(`${value.slice(0, 10)}T12:00:00`) : null;
  if (!at || Number.isNaN(at.getTime())) return String(value || "");
  return at.toLocaleDateString(LOCALE, {day: "numeric", month: "short"});
}

function shopHistoryPrice(day) {
  const value = Number(day.price);
  return day.price != null && day.price !== "" && Number.isFinite(value) ? listedAud(value) : "price not shown";
}

/** One day's stock in the shop's own terms (Games Portal says only in stock or not). */
function shopHistoryStock(day, counts) {
  const more = day.partial === true ? `; ${SHOP_SNAPSHOT_PARTIAL}` : "";
  if (day.preference_unknown) return "Household listing preference unavailable";
  if (day.preference_excluded) return "No listing meets household preference";
  if (!day.listed) return `${day.elsewhere === true ? "listed, but not in this printing" : "not listed"}${more}`;
  if (!day.in_stock) return `out of stock${more}`;
  return `${counts ? `${num(day.stock)} in stock` : "in stock"}${more}`;
}

/** A day's printing: "LTC 12", with its finish when it isn't nonfoil. */
function shopHistoryPrinting(day) {
  if (!day.set) return "";
  return `${String(day.set).toUpperCase()} ${day.number || ""}`.trim()
    + (day.finish && day.finish !== "nonfoil" ? ` ${day.finish}` : "");
}

/** One shop's part: its lowest in-stock price first, then the days, newest first. */
function shopHistoryShop(shop) {
  const days = Array.isArray(shop.days) ? shop.days : [];
  const head = el("h3", {text: shop.shop});
  if (!days.length) return el("section", {class: "shop-history-shop", "data-shop-history": shop.shop}, head,
    el("p", {class: "sub", text: "No earlier readings: the row shows today's."}));
  const lowest = days.filter(day => day.lowest);
  const low = lowest.length
    ? `Lowest in stock: ${shopHistoryPrice(lowest[0])} on ${lowest.map(day => shopHistoryDay(day.on)).join(", ")}`
    : "Not in stock on any day kept.";
  const rows = days.slice().reverse().map(day => el("tr", {class: day.lowest ? "shop-history-low" : null},
    el("td", {text: shopHistoryDay(day.on)}),
    el("td", {class: "num", text: day.listed ? shopHistoryPrice(day) : "—"}),
    el("td", {text: shopHistoryStock(day, shop.counts_stock !== false)}),
    el("td", {}, el("span", {text: shopHistoryPrinting(day)}),
      day.listed ? el("small", {text: shopSnapshotQuality(day)}) : null,
      day.skipped_cheaper ? el("small", {text: "Cheaper copy skipped by household preference"}) : null)));
  return el("section", {class: "shop-history-shop", "data-shop-history": shop.shop}, head,
    el("p", {class: "shop-history-lowest", text: low}),
    el("p", {class: "sub", text: `${plural(days.length, "day")} kept.`}),
    el("div", {class: "table-scroll"}, el("table", {class: "shop-history-table"},
      el("thead", {}, el("tr", {}, el("th", {scope: "col", text: "Day"}), el("th", {scope: "col", class: "num", text: "Price"}),
        el("th", {scope: "col", text: "Stock"}), el("th", {scope: "col", text: "Printing"}))),
      el("tbody", {}, rows))));
}

/** The history sheet for a queued card; asks once when opened. */
async function shopHistorySheet(card, view) {
  if (!view || !shopQueueActive(view)) return null;
  const sheet = openSheet({title: `Price history: ${card.name}`});
  const body = el("div", {class: "shop-history", "aria-busy": "true"},
    el("p", {class: "sub", text: "Reading the shops' daily snapshots…"}));
  sheet.body.append(body);
  sheetActions(sheet, [{text: "Close", kind: "primary", onclick: () => sheet.close()}]);
  const alive = () => !sheet.closed && shopQueueActive(view);
  let answer;
  try {
    const row = Number.isSafeInteger(card.queue_row) && card.queue_row > 0 ? `&row=${card.queue_row}` : "";
    answer = await api(`/api/shopping/price-history?name=${encodeURIComponent(card.name)}${row}`);
  } catch (failure) {
    if (!alive()) return sheet;
    body.removeAttribute("aria-busy");
    add(clear(body), [el("p", {class: "box box-warn", role: "alert",
      text: `The price history couldn't be loaded. ${failure.message || ""}`.trim()})]);
    return sheet;
  }
  if (!alive()) return sheet;
  body.removeAttribute("aria-busy");
  const shops = Array.isArray(answer.shops) ? answer.shops : [];
  add(clear(body), [
    el("p", {class: "sub", text: "Each day's price and stock from the nightly snapshot, kept 90 days while the card is on the queue."}),
    !answer.queued ? el("p", {class: "sub", text: "This card isn't on the purchase queue now, so no history is kept for it."}) : null,
    answer.queued && typeof answer.scope === "string" && answer.scope ? el("p", {class: "sub", "data-shop-history-scope": answer.scope,
      text: answer.scope === "any printing" ? "Read as any printing: each day's cheapest nonfoil in stock."
        : `Read for this row's own printing and finish: ${answer.scope}.`}) : null,
    shopSnapshotPreference(answer) ? el("p", {class: "sub", text: `Listing preference: ${shopSnapshotPreference(answer)}.`}) : null,
    ...shops.map(shopHistoryShop)]);
  return sheet;
}

/** The row's "Price history" button, put beside its snapshot line; null without a view or a snapshot. */
function shopHistoryButton(card, view) {
  if (!view || !shopSnapshotList(card).length) return null;
  if (shopSnapshotList(card).every(snap => snap && snap.status === "token")) return null;   // never looked up: no history
  return el("button", {type: "button", class: "btn btn-quiet shop-history-open", text: "Price history",
    "aria-label": `Price history for ${card.name}`, onclick: () => shopHistorySheet(card, view)});
}
