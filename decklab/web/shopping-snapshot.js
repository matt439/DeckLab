/* MTGMate's daily snapshot beside a queued card's recorded reference price (E5-S08), and a
 * waiting_for_stock row it finds in stock marked (E5-S19). Read only: the snapshot never
 * changes the queue, and an unknown price stays unknown (never a converted US price). */
"use strict";

/** The fetch time in local words: "28 Oct, 2:05 pm". */
function shopSnapshotWhen(value) {
  const at = typeof value === "string" ? new Date(value) : null;
  if (!at || Number.isNaN(at.getTime())) return null;
  return el("time", {class: "shop-snapshot-when", datetime: value, title: value,
    text: `fetched ${at.toLocaleString("en-AU", {day: "numeric", month: "short", hour: "numeric", minute: "2-digit"})}`});
}

/** Only the shop's own card pages may leave the page. */
function shopSnapshotLink(snap, text) {
  return typeof snap.url === "string" && /^https:\/\/www\.mtgmate\.com\.au\/cards\//.test(snap.url)
    ? el("a", {href: snap.url, target: "_blank", rel: "noopener noreferrer", text}) : el("span", {text});
}

/** The words for one row's snapshot: the shop's price and stock, or why there's none. */
function shopSnapshotWords(snap) {
  const shop = snap.shop || "MTGMate";
  const price = snap.price_aud != null && Number.isFinite(Number(snap.price_aud)) ? aud(Number(snap.price_aud)) : null;
  const printing = snap.set ? `${String(snap.set).toUpperCase()} ${snap.collector_number || ""}`.trim()
    + (snap.finish && snap.finish !== "nonfoil" ? ` ${snap.finish}` : "") : null;
  if (snap.status === "in_stock")
    return [`${shop}: ${price || "price not shown"}, ${snap.stock} in stock`, printing];
  if (snap.status === "out_of_stock")
    return [`${shop}: out of stock${price ? ` (listed at ${price})` : ""}`, printing];
  if (snap.status === "not_listed") return [`${shop}: not listed`, null];
  if (snap.status === "unknown") return [`${shop}: price unknown, the shop couldn't be read`, null];
  return [`${shop}: not in the last snapshot`, null];
}

/** The snapshot line under a queued card, or null without a snapshot. */
function shopSnapshotLine(card) {
  const snap = card && card.shop_snapshot;
  if (!snap || typeof snap !== "object") return null;
  const [words, printing] = shopSnapshotWords(snap);
  const chip = snap.back_in_stock ? status("good", "Back in stock")
    : snap.newly_in_stock ? status("info", "Newly in stock") : null;
  return el("span", {class: `shop-snapshot shop-snapshot-${snap.status}`, "data-shop-snapshot": snap.status,
    title: snap.status === "unknown" && snap.error ? snap.error : null},
    chip, el("span", {text: words}),
    printing ? el("small", {}, shopSnapshotLink(snap, printing)) : null,
    shopSnapshotWhen(snap.fetched_at));
}

/** True when the row should stand out: waiting for stock, and the snapshot finds it in stock. */
function shopSnapshotBack(card) { return Boolean(card && card.shop_snapshot && card.shop_snapshot.back_in_stock); }
