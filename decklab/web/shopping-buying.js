/* Read-only buying views over Shopping's pinned answer and its current local queue.
 * Queue writes still belong to shopping.js; every redraw uses their saved rows. */
"use strict";

/** Reference research belongs on the row even when there is no card image. */
function shopReference(row) {
  const price = shopPrice(row);
  if (!price) return null;
  return el("span", {class: "shop-reference"},
    el("span", {text: `Reference price ${price}`}),
    el("small", {text: row.checked ? `Checked ${row.checked}` : "Check date not recorded"}));
}

/** Resolve against current queue rows after Add, Edit, Move or Remove, never stale row numbers. */
function shopMissingQueue(item, queue) {
  const key = name => String(name || "").trim().toLocaleLowerCase();
  const names = new Set([item.name, item.card?.name, ...(item.queue || []).map(row => row.name)].map(key));
  names.delete("");
  return queue.filter(row => !row.is_token && (names.has(key(row.card?.name)) || names.has(key(row.name))));
}

function shopMissingCard(item, queue) {
  const queued = shopMissingQueue(item, queue);
  const row = cardRow(item.card || null, {name: item.name, qty: item.missing, aside: null,
    meta: `${plural(item.missing, "copy", "copies")} missing across ${plural((item.decks || []).length, "deck")}`,
    unknownMeta: "Missing from Planned lists", viewerGroup: "shopping-missing"});
  const wants = el("ul", {class: "shop-missing-decks"}, (item.decks || []).map(deck => el("li", {},
    el("a", {href: `${deckHref(deck.id)}&tab=cards&filter=missing`, text: deck.title}),
    `: ${deck.missing}`)));
  const intent = queued.length ? el("ul", {class: "shop-missing-queue"}, queued.map(entry => el("li", {},
    el("p", {text: `${entry.quantity} queued · ${SHOPPING_STATES[entry.state] || entry.state || "State not recorded"}`}),
    el("p", {class: "sub", text: [entry.deck?.title || entry.for, shopPrinting(entry)].filter(Boolean).join(" · ")}),
    shopReference(entry),
    entry.in_stock === "no" ? el("p", {class: "sub", text: "Out of stock when checked"}) : null)))
    : el("p", {class: "sub", text: "Not in the purchase queue."});
  return el("article", {class: "shop-missing-card", "data-missing-card": item.name}, row, wants,
    reprintInfo(item), intent);
}

/** A failed count remains visible alongside any successfully counted decks. */
function shopMissingCards(view) {
  const missing = view.data.missing_cards;
  if (!missing) return null;       // Older/test answers have no combined-count contract.
  const rows = missing.rows || [], errors = missing.errors || [], warnings = missing.warnings || [];
  if (missing.ready && !rows.length && !errors.length && !warnings.length) return null;
  const content = el("div", {class: "shop-missing-content"});
  if (!missing.ready) content.append(el("div", {class: "note note-warn", role: "status"},
    el("p", {text: rows.length ? "Missing-card counts are incomplete. The cards counted so far are below."
      : "Missing cards could not be counted. Card data or the collection may not be ready."}),
    el("button", {type: "button", class: "btn btn-quiet", text: "Refresh missing cards",
      onclick: event => {if (event.currentTarget.isConnected && shopQueueActive(view)) route();}})));
  if (errors.length) content.append(el("ul", {class: "shop-count-errors"}, errors.map(error => el("li", {},
    error.id ? el("a", {href: deckHref(error.id), text: error.title || error.id}) : null,
    el("span", {text: `${error.id ? ": " : ""}${error.message}`})))));
  if (warnings.length) add(content, [warningsBox(warnings, "Missing-card counts need review")]);
  if (rows.length) content.append(el("div", {class: "shop-missing-rows"},
    rows.map(item => shopMissingCard(item, view.data.to_buy || []))));
  return shopSection("shop-missing-cards", "Missing cards across decks", rows.length,
    "These totals add each Planned home deck's separate shortfall. Shared collection copies may count for more than one deck. Queue rows record purchase decisions separately.", content);
}

/** All states, including long-term plans, stay available when sharing a shop's postage. */
function shopByShop(view) {
  const rows = view.data.to_buy || [];
  if (!rows.length) return null;
  const shops = [...new Set(rows.map(row => (row.listed_at || "").trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
  const choices = [{value: "all", text: "All recorded shops"},
    ...shops.map(shop => ({value: `shop:${shop}`, text: shop})),
    {value: "unchecked", text: "Not checked at any shop"}];
  if (!choices.some(choice => choice.value === view.shopChoice)) view.shopChoice = "all";
  const select = el("select", {id: "shop-buying-store", "aria-label": "Shop"},
    choices.map(choice => el("option", {value: choice.value, text: choice.text})));
  select.value = view.shopChoice;
  const results = el("div", {class: "shop-store-results", "aria-live": "polite"});
  const draw = () => {
    clear(results);
    const wanted = view.shopChoice === "all" ? [...shops, ""]
      : [view.shopChoice === "unchecked" ? "" : view.shopChoice.slice(5)];
    let found = 0;
    wanted.forEach((shop, index) => {
      const group = rows.filter(row => (row.listed_at || "").trim() === shop);
      if (!group.length) return;
      found += group.length;
      const section = el("section", {class: "shop-store-group"},
        el("h3", {text: shop || "Not checked at any shop"}));
      for (const [stock, label] of [["yes", "In stock when checked"], ["no", "Out of stock when checked"], ["", "Stock not recorded"]]) {
        const bucket = group.filter(row => (row.in_stock === "yes" || row.in_stock === "no" ? row.in_stock : "") === stock);
        if (!bucket.length) continue;
        section.append(el("h4", {text: label}), el("div", {class: "shop-rows"}, bucket.map(row => {
          const card = shopQueueRow(row, `shopping-store-${index}-${stock || "unknown"}`, true, null, true);
          return el("div", {class: "shop-store-row"}, card,
            !shopPrice(row) ? el("p", {class: "sub", text: row.checked
              ? `Checked ${row.checked}; reference price not recorded.` : "Check date and reference price not recorded."}) : null);
        })));
      }
      results.append(section);
    });
    if (!found) results.append(el("p", {class: "empty", text: "No purchase-queue rows recorded for this shop."}));
  };
  select.addEventListener("change", () => {
    if (!select.isConnected || !shopQueueActive(view)) return;
    view.shopChoice = select.value;
    view.shopOpen = true;
    draw();
  });
  draw();
  const fold = el("details", {class: "shop-store-fold", open: Boolean(view.shopOpen)},
    el("summary", {text: "View the queue by shop"}),
    el("label", {class: "field shop-store-choice", for: select.id}, el("span", {text: "Shop"}), select), results);
  fold.addEventListener("toggle", () => {if (fold.isConnected && shopQueueActive(view)) view.shopOpen = fold.open;});
  return shopSection("shop-by-shop", "By shop", 0,
    "Every queue row last seen at each shop, including long-term plans. Prices and stock are dated references; check the shop before ordering.",
    fold);
}
