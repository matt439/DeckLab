/* One queue projection at a time. Density changes move the existing viewer and write controls,
 * so their exact queue row, revision guards and focus-return target stay the same. */
"use strict";

const SHOP_QUEUE_LAB = "(min-width: 1000px)";
let shopQueueExtraId = 0;
let shopQueueDensityStop = null;

function shopQueueLab() { return Boolean(window.matchMedia?.(SHOP_QUEUE_LAB).matches); }

function shopQueueUnknown(words) {
  return el("span", {}, el("span", {class: "cell-unknown", "aria-hidden": "true", text: "\u2014"}),
    el("span", {class: "sr-only", text: words}));
}

/** Clip only the visual line: the full saved words remain text and are available on hover too. */
function shopQueueClip(words) { return el("span", {class: "shop-q-clip", title: words, text: words}); }

/** A saved calendar day, not a timestamp guessed from a price or a card-data update. */
function shopCheckDay(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const day = new Date(`${value}T12:00:00`);
  return !Number.isNaN(day.getTime()) && day.getFullYear() === Number(value.slice(0, 4))
    && day.getMonth() + 1 === Number(value.slice(5, 7)) && day.getDate() === Number(value.slice(8, 10)) ? day : null;
}

/** Keep lab's exact ISO date compact. Casual research can use the shared dated-check badge. */
function shopChecked(value, {compact = false, now = Date.now()} = {}) {
  if (!value) return compact ? shopQueueUnknown("Check date not recorded")
    : el("span", {class: "shop-checked-unknown", text: "Check date not recorded"});
  const day = shopCheckDay(value), today = new Date(now);
  today.setHours(23, 59, 59, 999);
  const words = `Recorded check date: ${value}`;
  const badge = !compact && day && day.getTime() <= today.getTime() && typeof freshnessBadge === "function"
    ? freshnessBadge(day, {verb: "checked", byDate: true, size: "casual", now,
      staleWords: `checked ${simDay(day, false, now)}`}) : null;
  return el(day ? "time" : "span", {class: "shop-checked", datetime: day ? value : null, title: words},
    badge || (compact ? value : day && day.getTime() <= today.getTime() ? `Checked ${value}` : words));
}

/** Printing intent is spoken once in full; the casual row's neutral finish pill is decorative beside it. */
function shopPrintingIntent(card) { return shopPrinting(card) + (card.finish === "nonfoil" ? ", nonfoil" : ""); }

function shopPrintingMeta(card) {
  const exact = card.printing === "exact";
  return el("span", {class: "shop-printing-meta"}, el("span", {class: "sr-only", text: shopPrintingIntent(card)}),
    el("span", {class: "shop-printing-visual", "aria-hidden": "true"},
      exact ? el("span", {class: "shop-exact-tag", text: `EXACT ${String(card.set || "").toUpperCase()}`}) : "Any printing",
      exact && card.collector_number ? el("span", {text: card.collector_number}) : null,
      finishChip(card.finish), card.finish && !["foil", "etched"].includes(card.finish) ? el("span", {text: card.finish === "nonfoil" ? "Nonfoil" : card.finish}) : null));
}

/** The full saved intent/evidence belongs in the viewer, rather than in a long button name. */
function shopQueueCaption(card) {
  return [card.deck?.title || card.for ? `For ${card.deck?.title || card.for}` : null,
    SHOPPING_STATES[card.state] || (card.state ? `State: ${card.state}` : "State not recorded"),
    `Requested printing: ${shopPrintingIntent(card)}`,
    shopPrice(card) ? `Reference price ${shopPrice(card)}` : "Reference price not recorded",
    card.checked ? `Recorded check date: ${card.checked}` : "Check date not recorded",
    card.in_stock === "yes" ? "In stock when checked" : card.in_stock === "no" ? "Out of stock when checked" : "Stock not recorded",
    card.notes || null].filter(Boolean).join(". ");
}

/** Move a node explicitly: the viewer/controls are never cloned or left hidden in a second group. */
function shopQueuePut(parent, ...nodes) {
  for (const node of nodes.filter(Boolean)) { node.remove(); parent.append(node); }
}

function shopQueueTableRecord(card, casual, showFor, view) {
  const children = Array.from(casual.children), trigger = casual.querySelector(".card-row");
  trigger?.setAttribute("title", card.name);
  if (trigger?.matches("div")) trigger.setAttribute("tabindex", "-1");
  const deck = casual.querySelector(".shop-queue-deck"), actions = casual.querySelector(".shop-queue-actions");
  if (deck) deck.setAttribute("title", card.deck.title);
  const reprints = casual.querySelector(".reprint-info"), words = casual.querySelector(".shop-match-words");
  const nameCell = el("td", {class: "shop-q-name"});
  const price = shopPrice(card), value = price ? Number(card.listed_aud).toLocaleString("en-AU",
    {minimumFractionDigits: 2, maximumFractionDigits: 2}) : null;
  const printingLine = el("span", {class: "shop-q-printing-line", title: shopPrinting(card)}, card.printing === "exact"
    ? [el("span", {class: "shop-exact-tag", text: `EXACT ${String(card.set || "").toUpperCase()}`}),
      el("span", {text: [card.collector_number, card.finish && card.finish !== "nonfoil" ? card.finish : null].filter(Boolean).join(" ")})]
    : shopPrinting(card));
  const printing = el("td", {class: "shop-q-printing"}, printingLine);
  if (["waiting_for_stock", "waiting_for_reprint"].includes(card.state))
    printing.append(el("small", {class: "shop-q-reason", text: card.state === "waiting_for_stock" ? "for stock" : "for a reprint"}));
  else if (!SHOP_QUEUE_STATES.includes(card.state)) printing.append(el("small", {class: "shop-q-reason", text: `State: ${card.state || "not recorded"}`}));
  const forCell = showFor ? el("td", {class: "shop-q-for"}, deck ? null : card.for ? shopQueueClip(card.for) : shopQueueUnknown("Not for a deck")) : null;
  const shop = shopQueueShop(card);
  const tr = el("tr", {class: "shop-queue-row shop-queue-lab-row", "data-shop-queue": String(card.queue_row || ""),
    "data-shop-name": shop, "data-shop-match": shopMatches(view, card) ? "true" : null}, nameCell, printing, forCell,
    el("td", {class: "num shop-q-qty", text: card.quantity}),
    el("td", {class: "num shop-q-price"}, value == null ? shopQueueUnknown("Reference price not recorded") : value),
    el("td", {class: "shop-q-shop"}, shop ? shopQueueClip(shop) : shopQueueUnknown("Shop not recorded")),
    el("td", {class: "shop-q-stock"}, card.in_stock === "no" ? status("warn", "Out of stock")
      : card.in_stock === "yes" ? "In stock" : shopQueueUnknown("Stock not recorded")),
    el("td", {class: "shop-q-checked"}, shopChecked(card.checked, {compact: true})),
    el("td", {class: "shop-q-actions"}));
  let extra = null, extraBody = null, more = null;
  if (card.notes || reprints) {
    const id = `shop-queue-extra-${++shopQueueExtraId}`;
    extraBody = el("div", {class: "shop-q-extra-body"}, card.notes ? el("p", {text: card.notes}) : null);
    extra = el("tr", {class: "shop-q-extra", hidden: true, id}, el("td", {colspan: showFor ? 9 : 8}, extraBody));
    more = el("button", {type: "button", class: "btn btn-quiet shop-q-more", text: "\u2026",
      "aria-label": `Show notes and reprint research for ${card.name}`, "aria-expanded": "false", "aria-controls": id,
      onclick: event => {
        if (!event.currentTarget.isConnected || !shopQueueActive(view)) return;
        extra.hidden = !extra.hidden;
        event.currentTarget.setAttribute("aria-expanded", String(!extra.hidden));
      }});
    nameCell.append(more);
    // Keep a research sheet's original focus-return target visible after a density change.
    const reveal = () => { extra.hidden = false; more.setAttribute("aria-expanded", "true"); };
    reprints?.addEventListener("focusin", reveal);
    for (const target of reprints ? [...reprints.querySelectorAll("button"), ...reprints.querySelectorAll("a")] : [])
      target.addEventListener("click", reveal);
  }
  const label = trigger?.getAttribute("aria-label");
  return {casual, tr, extra, trigger, project(lab) {
    const menu = actions?.querySelector(".menu");
    if (menu) { menu.style.left = ""; menu.style.top = ""; menu.style.translate = ""; }
    if (lab) {
      shopQueuePut(nameCell, trigger, words);
      if (deck) shopQueuePut(forCell, deck);
      if (actions) shopQueuePut(tr.querySelector(".shop-q-actions"), actions);
      if (reprints) shopQueuePut(extraBody, reprints);
      if (trigger?.matches("button")) trigger.setAttribute("aria-label", `${card.name}, ${plural(card.quantity, "copy", "copies")}`);
    } else {
      for (const child of children) shopQueuePut(casual, child);
      if (label == null) trigger?.removeAttribute("aria-label"); else trigger?.setAttribute("aria-label", label);
    }
  }};
}

/** A real table in lab density, the existing cards below it. Only the chosen tree is attached. */
function shopQueuePresentation(groups, view, {showFor = true, group = "to-buy", headings = true} = {}) {
  const holder = el("div", {class: "shop-queue-presentation", tabindex: "-1", role: "group", "aria-label": "Purchase queue"});
  const cards = el("div", {class: headings ? "shop-queue-groups" : "shop-rows"});
  const headers = [["name", "Card"], ["printing", "Printing"], ...(showFor ? [["for", "For"]] : []),
    ["qty", "Qty"], ["price", "Ref AUD"], ["shop", "Shop"], ["stock", "Stock"], ["checked", "Checked"], ["actions", "Actions"]];
  const table = el("table", {class: `data shop-queue-table${showFor ? "" : " shop-queue-no-for"}`},
    el("caption", {class: "sr-only", text: group === "long-term" ? "Long-term purchase queue" : "Purchase queue by category"}),
    el("thead", {}, el("tr", {}, headers.map(([key, text]) => el("th", {scope: "col", class: `shop-q-head-${key}`,
      "aria-label": key === "stock" ? "Stock when checked" : null, text})))));
  const wrap = el("div", {class: "shop-queue-table-wrap", tabindex: "0", role: "region", "aria-label": "Purchase queue table, scroll for more columns"}, table);
  let lab = null;
  const records = [], destinations = [];
  for (const [key, title, rows] of groups) {
    const list = headings ? el("div", {class: "shop-rows"}) : cards;
    if (headings) cards.append(el("section", {class: "shop-queue-group", "data-queue-group": key},
      el("h3", {}, title, el("span", {class: "shop-group-count", text: ` \u00b7 ${plural(rows.length, "row")}`})), list));
    const heading = headings ? el("tr", {class: "group-row", "data-queue-group": key},
      el("th", {scope: "rowgroup", colspan: headers.length}, title,
        el("span", {class: "group-count", text: ` \u00b7 ${plural(rows.length, "row")}`}))) : null;
    const body = el("tbody"); table.append(body);
    destinations.push({rows, list, heading, body});
  }
  const addRows = (rows, destination = destinations[0]) => {
    for (const card of rows) {
      const casual = shopQueueRow(card, group, showFor, view, false, headings);
      const record = {...shopQueueTableRecord(card, casual, showFor, view), destination};
      records.push(record);
      if (lab != null) {
        record.project(lab);
        if (lab) add(destination.body, [record.tr, record.extra]); else shopQueuePut(destination.list, record.casual);
      }
    }
  };
  for (const destination of destinations) addRows(destination.rows, destination);
  const project = () => {
    const next = shopQueueLab();
    if (next === lab) return;
    const active = document.activeElement, focus = holder.contains(active) ? active : null;
    const focusRecord = records.find(record => record.casual.contains(focus) || record.tr.contains(focus) || record.extra?.contains(focus));
    const menuButton = focus?.closest?.(".shop-queue-actions")?.querySelector(".shop-category-move");
    if (holder.isConnected) closeMenus();
    for (const child of Array.from(holder.children)) child.remove();
    for (const destination of destinations) {
      clear(destination.body);
      if (destination.heading) destination.body.append(destination.heading);
      for (const record of records.filter(item => item.destination === destination)) {
        record.project(next);
        if (next) add(destination.body, [record.tr, record.extra]); else shopQueuePut(destination.list, record.casual);
      }
    }
    holder.append(next ? wrap : cards);
    lab = next;
    const target = focus?.closest?.(".menu") ? menuButton : focus?.isConnected ? focus : focusRecord?.trigger || (focus ? holder : null);
    if (target?.isConnected) shopQueueFocus(target);
  };
  holder.appendQueueRows = addRows;
  view.queuePresentations.push(project);
  project();
  wrap.addEventListener("scroll", () => { if (wrap.isConnected) closeMenus(); });
  return holder;
}

/** Focus a newly saved row's visible control, including columns scrolled out of its table viewport. */
function shopQueueFocus(button) {
  button.focus({preventScroll: true});
  if (button.closest(".shop-queue-table")) button.scrollIntoView({block: "nearest", inline: "nearest"});
}

/** Fixed menus escape the table's horizontal scroll frame. Keep their existing keyboard/close wiring. */
function shopQueueMenuPosition(button, menu) {
  if (!button.closest(".shop-queue-table") || menu.hidden) return;
  const rect = button.getBoundingClientRect(), box = menu.getBoundingClientRect();
  menu.style.translate = "";
  menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - box.width - 8))}px`;
  menu.style.top = `${Math.max(8, Math.min(rect.bottom, window.innerHeight - box.height - 8))}px`;
}

function shopWatchQueueDensity(view) {
  if (shopQueueDensityStop) shopQueueDensityStop();
  const query = window.matchMedia?.(SHOP_QUEUE_LAB);
  if (!query?.addEventListener) return;
  let listening = true;
  const stop = () => { listening = false; query.removeEventListener("change", changed); };
  const changed = () => {
    if (!listening) return;
    if (!shopQueueActive(view)) { stop(); return; }
    const chipFocused = view.matchSlot.contains(document.activeElement);
    view.queuePresentations.forEach(project => project());
    shopApplyMatches(view);
    if (chipFocused) view.matchSlot.querySelector("button")?.focus({preventScroll: true});
  };
  shopQueueDensityStop = stop;
  query.addEventListener("change", changed);
}
