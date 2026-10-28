/* Read-only buying views over Shopping's pinned answer and its current local queue.
 * Queue writes still belong to shopping.js; every redraw uses their saved rows. */
"use strict";

/** Reference research belongs on the row even when there is no card image. */
function shopReference(row) {
  const price = shopPrice(row);
  if (!price) return null;
  return el("span", {class: "shop-reference"},
    el("span", {text: `Reference price ${price}`}),
    shopChecked(row.checked));
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

/** Group copies of the current queue without changing saved state, order or row identifiers. */
function shopQueueGroups(rows, view) {
  const groups = [["ready", "Ready", rows.filter(row => row.state === "ready")],
    ["waiting", "Waiting", rows.filter(row => ["waiting_for_stock", "waiting_for_reprint"].includes(row.state))],
    ["deferred", "Deferred", rows.filter(row => row.state === "deferred")],
    ["other", "State not recorded", rows.filter(row => !SHOP_QUEUE_STATES.includes(row.state))]];
  return shopQueuePresentation(groups.filter(([, , list]) => list.length), view);
}

/** Every recorded stock/date fact stays on its canonical queue row, even without an image or price. */
function shopQueueResearch(row) {
  const price = shopReference(row), shop = shopQueueShop(row);
  return el("span", {class: "shop-reference shop-queue-research"}, price,
    !price && shop ? el("span", {text: `Recorded at ${shop}`}) : null,
    !price ? [shopChecked(row.checked), el("small", {text: "Reference price not recorded."})] : null,
    row.in_stock === "no" ? status("warn", "Out of stock when checked")
      : el("span", {text: row.in_stock === "yes" ? "In stock when checked" : "Stock not recorded"}));
}

function shopQueueShop(row) { return String(row.listed_at || "").trim(); }

/** Only the pinned answer's queue contributes shop names and counts; no library or research reads. */
function shopChoices(view) {
  const rows = view.data.to_buy || [];
  const shops = [...new Set(rows.map(shopQueueShop).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const choice = (value, text, list) => ({value, text, rows: list.length,
    cards: list.reduce((sum, row) => sum + (Number(row.quantity) || 0), 0)});
  return [choice("all", "All queue rows", rows),
    ...shops.map(shop => choice(`shop:${shop}`, shop, rows.filter(row => shopQueueShop(row) === shop))),
    choice("unchecked", "Not checked at any shop", rows.filter(row => !shopQueueShop(row)))];
}

function shopNormalizeChoice(view) {
  if (!(view.data.to_buy || []).length || !shopChoices(view).some(choice => choice.value === view.shopChoice)) view.shopChoice = "all";
}

function shopMatches(view, row) {
  const chosen = view.shopChoice || "all";
  return chosen !== "all" && shopQueueShop(row) === (chosen === "unchecked" ? "" : chosen.slice(5));
}

/** Matching marks existing rows. Reveal a matching long-term group through its existing Show all path. */
function shopApplyMatches(view) {
  if (!view.root || !shopQueueActive(view)) return;
  shopNormalizeChoice(view);
  const chosen = view.shopChoice;
  if (chosen !== "all") {
    const keys = new Set((view.data.to_buy || []).filter(row => row.state === "long_term" && shopMatches(view, row))
      .map(row => row.deck ? row.deck.id : row.for || ""));
    for (const group of view.root.querySelectorAll("[data-long-key]"))
      if (keys.has(group.getAttribute("data-long-key"))) group.querySelector(".shop-long-more")?.click();
  }
  for (const row of view.root.querySelectorAll("[data-shop-queue]")) {
    const match = chosen !== "all" && row.getAttribute("data-shop-name") === (chosen === "unchecked" ? "" : chosen.slice(5));
    if (match) row.setAttribute("data-shop-match", "true"); else row.removeAttribute("data-shop-match");
    const words = row.querySelector(".shop-match-words");
    if (words) words.textContent = match ? "Matches selected shop." : "";
  }
  for (const radio of view.root.querySelectorAll(".shop-store-radio")) radio.checked = radio.value === chosen;
  clear(view.matchSlot);
  if (chosen === "all") return;
  const words = chosen === "unchecked" ? "Marking rows not checked at any shop" : `Marking ${chosen.slice(5)} rows`;
  view.matchSlot.append(el("button", {type: "button", class: "filter-chip shop-clear-match", text: `${words} \u00d7`,
    "aria-label": `${words}. Clear shop matching`, onclick: event => {
      if (!event.currentTarget.isConnected || !shopQueueActive(view)) return;
      view.shopChoice = "all";
      shopApplyMatches(view);
      Array.from(view.root.querySelectorAll(".shop-store-radio")).find(radio => radio.value === "all")?.focus({preventScroll: true});
    }}));
}

/** One shop's current queue, coalescing only identical requested cards/printings without changing the rows. */
function shopCopyList(view, shop) {
  if (!shop) return null;
  const rows = (view.data.to_buy || []).filter(row => shopQueueShop(row) === shop);
  const entries = new Map();
  let cards = 0;
  for (const row of rows) {
    const name = String(row.card?.name || row.name || "").trim(), quantity = Number(row.quantity);
    const exact = row.printing === "exact", finish = row.finish || "";
    if (!name || /[\u0000-\u001f\u007f]/.test(name) || !Number.isSafeInteger(quantity) || quantity < 1
        || !["any", "exact"].includes(row.printing) || !["", "nonfoil", "foil", "etched"].includes(finish)
        || exact && (!row.set || !row.collector_number || !finish)) return null;
    const printing = exact ? ` (${String(row.set).toUpperCase()}) ${row.collector_number} [${finish}]`
      : finish ? ` [${finish}]` : "";
    const text = name + printing, key = JSON.stringify([Boolean(row.is_token), name, row.printing,
      exact ? String(row.set).toUpperCase() : "", exact ? String(row.collector_number) : "", finish]);
    if (!entries.has(key)) entries.set(key, {text, quantity: 0});
    entries.get(key).quantity += quantity;
    cards += quantity;
    if (!Number.isSafeInteger(cards)) return null;
  }
  return cards ? {cards, text: [...entries.values()].map(item => `${item.quantity} ${item.text}`).join("\n") + "\n"} : null;
}

/** Copying is a read action for home viewers, bound to the current page, control and displayed queue. */
async function shopCopyShop(view, shop, button) {
  const owned = () => button?.isConnected && shopQueueActive(view) && seesHomeInventory(state.may);
  if (!owned() || button.disabled || view.busy || view.stale) return;
  const list = shopCopyList(view, shop), revision = view.data.queue_revision;
  if (!list) { toast("That shop's list isn't available. Refresh Shopping and check its rows."); return; }
  const current = () => owned() && !view.busy && !view.stale && view.data.queue_revision === revision
    && shopCopyList(view, shop)?.text === list.text;
  button.disabled = true;
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
    await navigator.clipboard.writeText(list.text);
    if (current()) toast(`${plural(list.cards, "card")} copied for ${shop}.`);
  } catch (error) {
    if (!current()) return;
    const sheet = shopTrackQueueSheet(openSheet({title: `Copy ${shop}'s list`, wide: true, onClose: () => {
      if (owned() && !document.querySelector("dialog[open]")) button.focus({preventScroll: true});
    }}), view);
    sheet.shopCopy = shop;
    sheet.queueBusy = () => { if (!current()) sheet.close(); };
    const area = el("textarea", {readonly: "", rows: 12, class: "export-copy shop-copy-text",
      "aria-label": `List for ${shop}`, spellcheck: "false"});
    area.value = list.text;
    sheet.body.append(el("p", {text: "Select and copy the list below."}),
      el("p", {class: "sub", text: `${plural(list.cards, "card")} from all queue categories, including long-term plans. ` +
        "Exact printing requests include the set, collector number and finish."}), area);
    sheetActions(sheet, [{text: "Close", onclick: () => sheet.close()}]);
    area.focus(); area.select();
  } finally {
    if (owned()) button.disabled = false;
  }
}

/** A redraw closes a frozen copy fallback; only its former focus may move to the current shop control. */
function shopCloseCopySheets(view) {
  for (const sheet of [...shopQueueSheets]) {
    if (sheet.queueView !== view || !sheet.shopCopy || sheet.closed) continue;
    const focused = document.activeElement, restore = sheet.dialog.contains(focused);
    sheet.close();
    if (restore) Promise.resolve().then(() => {
      const active = document.activeElement;
      if (!shopQueueActive(view) || !seesHomeInventory(state.may)
          || active?.isConnected && active !== document.body && active !== focused) return;
      const button = Array.from(view.root.querySelectorAll(".shop-store-copy"))
        .find(candidate => candidate.dataset.copyShop === sheet.shopCopy);
      (button || view.root.querySelector(".shop-store-radio"))?.focus({preventScroll: true});
    });
  }
}

/** One read-only shop choice marks canonical rows across every saved category, including long-term. */
function shopByShop(view) {
  shopCloseCopySheets(view);
  if (!seesHomeInventory(state.may) || !(view.data.to_buy || []).length) return null;
  shopNormalizeChoice(view);
  const choices = shopChoices(view);
  return shopSection("shop-by-shop", "By shop", 0,
    "Mark queue rows last seen at a shop, including long-term plans. Prices and stock are dated references; check the shop before ordering.",
    el("fieldset", {class: "shop-store-choices"}, el("legend", {class: "sr-only", text: "Mark queue rows by shop"}),
      choices.map((choice, index) => {
        const radio = el("input", {type: "radio", class: "shop-store-radio", name: "shopping-shop", value: choice.value,
          id: `shop-choice-${index}`, "data-shop-choice": choice.value, onchange: event => {
            if (!event.currentTarget.checked || !event.currentTarget.isConnected || !shopQueueActive(view)) return;
            if (!shopChoices(view).some(item => item.value === choice.value)) return;
            view.shopChoice = choice.value;
            shopApplyMatches(view);
          }});
        radio.checked = choice.value === view.shopChoice;
        const copy = choice.value.startsWith("shop:") ? el("button", {type: "button", class: "btn btn-quiet shop-store-copy",
          text: "Copy list", "aria-label": `Copy this shop's list for ${choice.text}`, "data-copy-shop": choice.text,
          title: "Copy all queue categories last seen at this shop, including long-term plans.",
          onclick: event => shopCopyShop(view, choice.text, event.currentTarget)}) : null;
        return el("div", {class: "shop-store-row"},
          el("label", {class: "shop-store-choice", for: radio.id}, radio,
            el("span", {class: "shop-store-name", text: choice.text}),
            el("span", {class: "shop-store-counts", text: `${plural(choice.rows, "row")} \u00b7 ${plural(choice.cards, "card")}`})), copy);
      })));
}
