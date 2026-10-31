/* The shops' daily snapshots beside a queued card's recorded reference price (E5-S08): MTGMate's
 * and Games Portal's, each with its own fetch time, and a waiting_for_stock row one finds in stock
 * marked (E5-S19). Read only: a snapshot never changes the queue, and an unknown price stays
 * unknown (never a converted US price). One shop that couldn't be read is unknown on its own. */
"use strict";

/** Each snapshot shop's own pages, the only links that may leave the page, and whether its pages
 * count stock (Games Portal's say only whether a listing is available). */
const SHOP_SNAPSHOT_SHOPS = {
  "MTGMate": {host: "www.mtgmate.com.au", pages: url => url.pathname.startsWith("/cards/") && !url.search, counts: true},
  "Games Portal": {host: "gamesportal.com.au", counts: false, pages: url =>
    url.pathname.startsWith("/products/") ? !url.search || /^\?variant=\d{1,20}$/.test(url.search)
      : url.pathname === "/search" && url.search.startsWith("?q=")},
};

/** The fetch time in local words: "28 Oct, 2:05 pm". */
function shopSnapshotWhen(value) {
  const at = typeof value === "string" ? new Date(value) : null;
  if (!at || Number.isNaN(at.getTime())) return null;
  return el("time", {class: "shop-snapshot-when", datetime: value, title: value,
    text: `fetched ${at.toLocaleString("en-AU", {day: "numeric", month: "short", hour: "numeric", minute: "2-digit"})}`});
}

/** True when url is one of that shop's own listing pages. */
function shopSnapshotOwnPage(shop, value) {
  const known = SHOP_SNAPSHOT_SHOPS[shop || "MTGMate"];
  if (!known || typeof value !== "string" || value.length > 2048 || /[\u0000-\u0020\u007f\\#]/.test(value)) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.host === known.host && !url.username && !url.password && known.pages(url);
  } catch (_) { return false; }
}

/** Only the shop's own card pages may leave the page. */
function shopSnapshotLink(snap, text) {
  return shopSnapshotOwnPage(snap.shop || "MTGMate", snap.url)
    ? el("a", {href: snap.url, target: "_blank", rel: "noopener noreferrer", text}) : el("span", {text});
}

/** False for a shop whose pages say only available or not (its stock is 1 or 0). */
function shopSnapshotCounts(shop) { return SHOP_SNAPSHOT_SHOPS[shop || "MTGMate"]?.counts !== false; }

/** The words for one row's snapshot: the shop's price and stock, or why there's none. */
function shopSnapshotWords(snap) {
  const shop = snap.shop || "MTGMate";
  const price = snap.price_aud != null && Number.isFinite(Number(snap.price_aud)) ? aud(Number(snap.price_aud)) : null;
  const printing = snap.set ? `${String(snap.set).toUpperCase()} ${snap.collector_number || ""}`.trim()
    + (snap.finish && snap.finish !== "nonfoil" ? ` ${snap.finish}` : "") : null;
  if (snap.status === "in_stock")
    return [`${shop}: ${price || "price not shown"}, ${shopSnapshotCounts(shop) ? `${snap.stock} in stock` : "in stock"}`, printing];
  if (snap.status === "out_of_stock")
    return [`${shop}: out of stock${price ? ` (listed at ${price})` : ""}`, printing];
  if (snap.status === "not_listed") return [`${shop}: not listed`, null];
  if (snap.status === "unknown") return [`${shop}: price unknown, the shop couldn't be read`, null];
  return [`${shop}: not in the last snapshot`, null];
}

/** A queued card's snapshots, one a shop: "shop_snapshots", else the older single "shop_snapshot". */
function shopSnapshotList(card) {
  if (card && Array.isArray(card.shop_snapshots))
    return card.shop_snapshots.filter(snap => snap && typeof snap === "object" && !Array.isArray(snap));
  const snap = card && card.shop_snapshot;
  return snap && typeof snap === "object" ? [snap] : [];
}

/** One shop's snapshot line. */
function shopSnapshotOne(snap) {
  const [words, printing] = shopSnapshotWords(snap);
  const chip = snap.back_in_stock ? status("good", "Back in stock")
    : snap.newly_in_stock ? status("info", "Newly in stock") : null;
  return el("span", {class: `shop-snapshot shop-snapshot-${snap.status}`, "data-shop-snapshot": snap.status,
    "data-shop-snapshot-shop": snap.shop || "MTGMate", title: snap.status === "unknown" && snap.error ? snap.error : null},
    chip, el("span", {text: words}),
    printing ? el("small", {}, shopSnapshotLink(snap, printing)) : null,
    shopSnapshotWhen(snap.fetched_at));
}

/** The snapshot line under a queued card (one a shop, together when there are several), or null without one. */
function shopSnapshotLine(card) {
  const list = shopSnapshotList(card);
  if (!list.length) return null;
  if (list.length === 1) return shopSnapshotOne(list[0]);
  return el("span", {class: "shop-snapshot-list", "data-shop-snapshots": String(list.length)}, list.map(shopSnapshotOne));
}

const SHOP_SNAPSHOT_RANK = ["in_stock", "out_of_stock", "not_listed", "unknown", "not_checked"];

/** The lab table's one-line marker beside the reference price: a dot (or "Back" when a waiting row
 * is back in stock at a shop) whose spoken and hover words give every shop's gist (E5-S26). Its
 * colour is the best shop's: in stock anywhere reads as in stock. */
function shopSnapshotMarker(card) {
  const list = shopSnapshotList(card);
  if (!list.length) return null;
  const back = list.some(snap => snap.back_in_stock);
  const best = list.map(snap => snap.status).sort((a, b) =>
    (SHOP_SNAPSHOT_RANK.indexOf(a) + 9) % 9 - (SHOP_SNAPSHOT_RANK.indexOf(b) + 9) % 9)[0];
  const gist = list.map(snap => {
    const [words, printing] = shopSnapshotWords(snap);
    const lead = snap.back_in_stock ? "Back in stock. " : snap.newly_in_stock ? "Newly in stock. " : "";
    return `${lead}${words}${printing ? ` (${printing})` : ""}`;
  }).join(list.length > 1 ? "; " : "");
  return el("span", {class: `shop-q-snap shop-q-snap-${best}${back ? " shop-q-snap-back" : ""}`,
    "data-shop-snapshot-marker": best, role: "img", "aria-label": gist, title: gist,
    text: back ? "Back" : "\u2022"});
}

/** True when the row should stand out: waiting for stock, and a shop's snapshot finds it in stock. */
function shopSnapshotBack(card) { return shopSnapshotList(card).some(snap => snap.back_in_stock); }

/** Missing-card evidence requires its own dated nonfoil facts, independent of exact queue requests. */
function shopMissingSnapshotFacts(item) {
  return shopMissingSnapshotOf(item?.shop_snapshot, "MTGMate");
}

/** One shop's entry checked as that shop's (expected: the shop it must name). */
function shopMissingSnapshotOf(snap, expected) {
  const shop = expected;
  const empty = {shop, status: "not_checked", fetched_at: null};
  const unknown = {shop, status: "unknown", fetched_at: null};
  if (snap == null) return empty;
  if (typeof snap !== "object" || Array.isArray(snap) || snap.shop !== expected || snap.scope !== "nonfoil" ||
      !["in_stock", "out_of_stock", "not_listed", "unknown", "not_checked"].includes(snap.status)) return unknown;
  if (snap.status === "not_checked") return empty;
  const fetched = shopMissingSnapshotDate(snap.fetched_at);
  if (!fetched) return unknown;
  if (["not_listed", "unknown"].includes(snap.status)) return {shop, status: snap.status, fetched_at: fetched};
  // Listed only sold out without a price: out of stock, with no price to show.
  if (snap.status === "out_of_stock" && snap.price_aud === null && snap.stock === 0)
    return {shop, status: snap.status, fetched_at: fetched, price: null, stock: 0, set: null, collector_number: null, url: null};
  const price = typeof snap.price_aud === "string" && /^(?:0|[1-9]\d{0,8})\.\d{2}$/.test(snap.price_aud)
    ? Number(snap.price_aud) : NaN;
  if (!Number.isFinite(price) || price <= 0 ||
      !Number.isSafeInteger(snap.stock) || snap.stock < 0 || snap.stock > 1000000000 ||
      (snap.status === "in_stock") !== (snap.stock > 0) || snap.finish !== "nonfoil" ||
      typeof snap.set !== "string" || !/^[a-z0-9]{1,12}$/.test(snap.set) ||
      typeof snap.collector_number !== "string" || !snap.collector_number || snap.collector_number.length > 64 ||
      snap.collector_number !== snap.collector_number.trim() || !shopMissingSnapshotText(snap.collector_number) ||
      /[\u0000-\u001f\u007f/\\?#]/.test(snap.collector_number)) return unknown;
  return {shop, status: snap.status, fetched_at: fetched, price, stock: snap.stock,
    set: snap.set, collector_number: snap.collector_number, url: shopMissingSnapshotUrl(snap.url, shop)};
}

/** No normalized impossible dates or timezone-free machine times become dated price claims. */
function shopMissingSnapshotDate(value) {
  if (typeof value !== "string" || value.length > 64) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match) return null;
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (!year || month < 1 || month > 12 || day < 1 || day > days[month - 1] ||
      hour > 23 || minute > 59 || second > 59) return null;
  const offset = match[7];
  if (offset !== "Z" && (Number(offset.slice(1, 3)) > 23 || Number(offset.slice(4, 6)) > 59)) return null;
  return Number.isFinite(Date.parse(value)) ? value : null;
}

/** for-of keeps paired astral characters intact and exposes lone UTF-16 surrogates. */
function shopMissingSnapshotText(value) {
  for (const symbol of value) {
    const point = symbol.codePointAt(0);
    if (point >= 0xd800 && point <= 0xdfff) return false;
  }
  return true;
}

/** A malformed link loses its link, while validated dated price facts remain readable. */
function shopMissingSnapshotUrl(value, shop = "MTGMate") {
  if (shop !== "MTGMate") return shopMissingSnapshotOtherUrl(value, shop);
  if (typeof value !== "string" || value.length > 2048 || !shopMissingSnapshotText(value) ||
      /[\u0000-\u0020\u007f\\]/.test(value)) return null;
  try {
    const url = new URL(value);
    const path = decodeURIComponent(url.pathname);     // reject malformed UTF-8 before offering its link
    return url.protocol === "https:" && url.host === "www.mtgmate.com.au" &&
      !url.username && !url.password && !/[?#]/.test(value) &&
      path.startsWith("/cards/") && path.length > 7 && !/[\u0000-\u001f\u007f\\]/.test(path) ? url.href : null;
  } catch (_) { return null; }
}

/** Another shop's link: only its own listing pages (shopSnapshotOwnPage), with well-formed UTF-8 paths. */
function shopMissingSnapshotOtherUrl(value, shop) {
  if (typeof value !== "string" || !shopMissingSnapshotText(value) || !shopSnapshotOwnPage(shop, value)) return null;
  try {
    const url = new URL(value);
    decodeURIComponent(url.pathname);                  // reject malformed UTF-8 before offering its link
    return url.href;
  } catch (_) { return null; }
}

/** Saved unit evidence only: no queue intent, stock-printing count, freshness inference or raw errors. */
function shopMissingSnapshotLine(item, {short = false} = {}) {
  // Every snapshot shop's line when the answer lists them ("shop_snapshots"), each checked as its own
  // shop's: one shop that couldn't be read says so on its own line, the other's still shows.
  const list = Array.isArray(item?.shop_snapshots) ? item.shop_snapshots.slice(0, 8) : null;
  if (list && list.length) {
    const lines = list.map(snap => shopMissingSnapshotOne(shopMissingSnapshotOf(snap,
      snap && typeof snap === "object" && Object.hasOwn(SHOP_SNAPSHOT_SHOPS, snap.shop) ? snap.shop : "MTGMate"), short));
    return el("div", {class: "shop-missing-snapshots", "data-shop-missing-snapshots": String(lines.length)}, lines);
  }
  return shopMissingSnapshotOne(shopMissingSnapshotFacts(item), short);
}

/** One shop's saved unit evidence line. */
function shopMissingSnapshotOne(snap, short) {
  const shop = snap.shop || "MTGMate", counts = shopSnapshotCounts(shop);
  const stocked = snap.status === "in_stock", listed = stocked || (snap.status === "out_of_stock" && snap.set != null);
  // short: Shopping's missing-card rows, where the line repeats down the page; the link and date keep the detail.
  const words = short ? (stocked ? `${shop} ${aud(snap.price)} each, ${counts ? `${snap.stock} in stock` : "in stock"}`
    : snap.status === "out_of_stock" ? (snap.price == null ? `${shop}: out of stock` : `${shop} ${aud(snap.price)} each, out of stock`)
    : snap.status === "not_listed" ? `${shop}: no nonfoil listed`
    : snap.status === "unknown" ? `${shop}: price unknown`
    : `${shop}: not checked`)
    : stocked ? `${shop}: ${aud(snap.price)} each; ${counts ? plural(snap.stock, "copy", "copies") : "this printing"}${counts ? " of this printing" : ""} in stock when fetched.`
    : snap.status === "out_of_stock" ? (snap.price == null ? `${shop}: nonfoil out of stock in the saved check, with no price shown.`
      : `${shop}: nonfoil out of stock in the saved check (listed at ${aud(snap.price)} each).`)
    : snap.status === "not_listed" ? `${shop}: no nonfoil printing listed in the saved check.`
    : snap.status === "unknown" ? `${shop}: nonfoil price unknown in the saved snapshot.`
    : `${shop}: no saved nonfoil check for this card.`;
  const when = snap.fetched_at ? shopSnapshotWhen(snap.fetched_at) : null;
  // Short lines keep the year whenever it isn't this one, so an old check never reads as current.
  const fetched = snap.fetched_at ? new Date(snap.fetched_at) : null;
  if (when) when.textContent = `fetched ${fetched.toLocaleString("en-AU", !short
    ? {day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit"}
    : fetched.getFullYear() === new Date().getFullYear() ? {day: "numeric", month: "short"}
      : {day: "numeric", month: "short", year: "numeric"})}`;
  return el("div", {class: "shop-snapshot shop-missing-snapshot", "data-shop-missing-snapshot": snap.status,
    "data-shop-snapshot-shop": shop},
    stocked && !short ? el("strong", {text: "Cheapest nonfoil in saved snapshot"}) : null,
    el("span", {text: words}), listed ? el("small", {}, shopSnapshotLink(snap, `${snap.set.toUpperCase()} ${snap.collector_number} nonfoil`)) : null,
    when);
}
