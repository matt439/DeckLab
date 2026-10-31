/* The inventory-visible Cards price table, its provenance and local column sorting.
 * Loaded after deck.js; nothing runs at load and sorting never fetches or saves data. */
"use strict";


/** The price table (the owned-vs-needed numbers): folded behind one line, "Price table: 32 missing, about
 * A$40.26", or the on-the-way copies; just "Nothing to buy" when all are here. Then the table being out of date,
 * the cards other decks hold, names that aren't Scryfall's and the collection's warnings. null when the
 * answer has no "owned" at all: the server leaves it out for a visitor who may not see the collection. */
function ownedSection(data) {
  if (!("owned" in data)) return null;
  const o = data.owned;
  const section = el("section", { class: "deck-section deck-prices", id: "sec-owned", "aria-labelledby": "h-owned" },
    el("h2", { id: "h-owned", text: "Prices" }));
  if (!o) {
    section.append(el("div", { class: "box box-warn", text: "What's owned and needed couldn't be worked out. The warnings at the top say why." }));
    return section;
  }
  const t = o.totals;
  const priceNote = el("p", { class: "price-note" }, o.price_error
    ? `No A$ estimates: ${o.price_error}`
    : `A$ prices are estimates: the cheapest non-foil printing's US price on Scryfall (prices of ${o.price_date}) ` +
      `× 1 USD = ${o.rate} AUD (ECB rate of ${o.rate_date}). Check a shop such as MTGMate before buying.`,
  t.unpriced && t.unpriced.length ? ` No price for: ${t.unpriced.join(", ")}.` : "");
  if (!t.missing) {
    section.append(el("p", { class: "deck-prices-none" },
      "Nothing to buy: every card this list counts is owned or on the way. Basic lands aren't counted."));
  }
  const coming = deckAvailability(o).coming;
  if (t.missing || coming) {
    const cost = t.missing && !o.price_error ? `, about ${aud(t.aud_missing)}` : "";
    const summary = t.missing ? `${t.missing} missing${cost}` : `${coming} on the way`;
    const details = el("details", { class: "more deck-price-table" },
      el("summary", { text: `Price table: ${summary}` }),
      el("p", { class: "sub", text: "Cards on the way (ordered or preordered) count as owned. A card can only be in " +
        "one deck at a time, so copies held by built decks or by products kept together aren't free for this one. " +
        "Basic lands aren't counted." }));
    details.append(ownedTable(o, { frame: details, owner: section, data }), priceNote);
    section.append(details);
  }
  add(section, [staleTableBox(data)]);    // editor-deckpage.js: the deck's own table is out of date (null otherwise)
  if (o.conflicts && o.conflicts.length) section.append(conflictsBox(o.conflicts));
  if (o.unresolved && o.unresolved.length) {
    section.append(el("div", { class: "box box-warn" }, el("h3", { text: "Names that aren't Scryfall cards" }),
      el("ul", {}, o.unresolved.map(([name, where]) => el("li", { text: `${name} (${where})` })))));
  }
  add(section, [warningsBox(o.warnings, "Warnings about the collection")]);
  return section;
}

/** A row's labels as the deck's table would have them (api: pool.row_labels). */
function rowLabels(r) { return r.labels || { on_the_way: [], in_use: [] }; }

function rowOrder(r) { return r.missing > 0 ? 0 : rowLabels(r).on_the_way.length ? 1 : 2; }

/** Use the API's extended estimate; older projections may supply only the unit price. */
function ownedMissingPrice(row, priceError = false) {
  const cost = row.aud_missing === undefined && Number.isFinite(row.aud_each) && Number.isFinite(row.missing)
    ? row.aud_each * row.missing : row.aud_missing;
  return !priceError && Number.isFinite(cost) && cost >= 0 ? cost : null;
}

function ownedTable(o, ownership = {}) {
  // Only the cards worth a look: missing, on the way or held by another deck. The rest are simply owned.
  const rows = [...o.rows].filter((r) => r.missing > 0 || rowLabels(r).on_the_way.length || rowLabels(r).in_use.length)
    .sort((a, b) => rowOrder(a) - rowOrder(b) || b.missing - a.missing || a.name.localeCompare(b.name));
  // "Can use" is capped at Need, as in the decks' tables (PLAN.md part 2).
  const usable = (r) => Math.min(r.available, r.need);
  const available = o.rows.reduce((n, r) => n + usable(r), 0);
  const table = el("table", { class: "data owned-table" }), headings = new Map();
  const profile = state.profile, viewer = profile?.id, space = profile?.space || HOME_SPACE, token = routeToken;
  const main = $("#main"), hash = location.hash, originalRows = o.rows;
  const screen = ownership.data && deckScreen?.data === ownership.data ? deckScreen : null;
  const screenView = screen?.view;
  const wrap = el("div", {class: "table-wrap"});
  let frame = ownership.frame || null, frameParent = ownership.owner || null;
  let sort = null;
  const sortable = (key, text, cls = "") => {
    const button = el("button", {type: "button", class: "th-sort", text, "data-owned-sort": key,
      onclick: () => {
        if (!profile || profile !== state.profile || viewer !== state.profile?.id || space !== (state.profile?.space || HOME_SPACE) ||
            token !== routeToken || (screen ? screen !== deckScreen || screen.data !== ownership.data ||
              screen.view !== screenView || !priceTableRoute(screen) : hash !== location.hash) || main !== $("#main") || !main.isConnected ||
            !table.isConnected || table.parentNode !== wrap || !main.contains(wrap) || o.rows !== originalRows ||
            ownership.data && ownership.data.owned !== o ||
            !button.isConnected || button.parentNode !== heading || !head.contains(heading) || head.parentNode !== table ||
            headings.get(key) !== heading || frame && (wrap.parentNode !== frame || frame.parentNode !== frameParent)) return;
        if (!frame) { frame = wrap.parentNode; frameParent = frame.parentNode; }
        sort = {key, dir: sort?.key === key ? -sort.dir : key === "name" ? 1 : -1};
        draw(); button.focus({preventScroll: true});
      }});
    const heading = el("th", {scope: "col", class: cls}, button);
    headings.set(key, heading); return heading;
  };
  const caption = el("caption", {class: "sr-only", text: "Cards missing, on the way or held by another deck: copies needed, usable and missing, estimated AUD missing cost, and a unit estimate below each card name. Sort by Card, Missing or estimated missing cost."});
  const columns = el("colgroup", {}, el("col"), el("col", {class: "c-need"}), el("col", {class: "c-have"}),
    el("col", {class: "c-miss"}), el("col", {class: "c-price"}));
  const head = el("thead", {}, el("tr", {}, sortable("name", "Card"),
    el("th", {scope: "col", class: "num", text: "Need"}), el("th", {scope: "col", class: "num", text: "Can use"}),
    sortable("missing", "Missing", "num"), sortable("cost", "~AUD missing", "num")));
  const bodies = new Map(rows.map(row => [row, ownedRow(row, usable(row), o.price_error)]));
  const foot = el("tfoot", {}, el("tr", {},
      el("th", { scope: "row", text: `All ${plural(o.totals.cards, "card")}` }),
      el("td", { class: "num", text: num(o.totals.need) }),
      el("td", { class: "num", text: num(available) }),
      el("td", { class: "num", text: num(o.totals.missing) }),
      el("td", { class: "num", text: "" })),
      o.price_error ? null : el("tr", {}, el("td", { colspan: 5, class: "total-cost" },
        o.totals.missing ? `The ${plural(o.totals.missing, "missing copy", "missing copies")} would cost about ` +
          `${aud(o.totals.aud_missing)} (estimate).` : "Nothing is missing.")));
  function draw() {
    const ordered = sort ? [...rows].sort((a, b) => {
      if (sort.key === "name") return sort.dir * a.name.localeCompare(b.name);
      const av = sort.key === "cost" ? ownedMissingPrice(a, o.price_error) : a.missing;
      const bv = sort.key === "cost" ? ownedMissingPrice(b, o.price_error) : b.missing;
      const ak = Number.isFinite(av), bk = Number.isFinite(bv);
      return ak !== bk ? ak ? -1 : 1 : (ak ? sort.dir * (av - bv) : 0) || a.name.localeCompare(b.name);
    }) : rows;
    for (const [key, heading] of headings) {
      if (sort?.key === key) heading.setAttribute("aria-sort", sort.dir > 0 ? "ascending" : "descending");
      else heading.removeAttribute("aria-sort");
    }
    clear(table).append(caption, columns, head, ...ordered.map(row => bodies.get(row)), foot);
  }
  draw();
  wrap.append(table);
  return wrap;
}

function ownedRow(r, usable, priceError = false) {
  // Only the copies this deck counts on that haven't arrived, and the decks holding a
  // card only when they leave this deck short: the same labels as the deck's table.
  // "Cards other decks are holding" below lists every deck holding copies.
  const labels = [];
  const own = rowLabels(r);
  if (r.missing > 0) labels.push(status("crit", `${r.missing} missing`));
  labels.push(...rowIncomingSources(r).map(incomingSourceChip));
  for (const [deck, n] of own.in_use) labels.push(status("warn", `${n} in use in ${deck}`));
  const priced = !priceError && Number.isFinite(r.aud_each) && r.aud_each >= 0;
  if (r.priced_finish && r.priced_finish !== "nonfoil" && priced) labels.push(status("plain", `${r.priced_finish} price`));
  const reprints = r.missing > 0 ? reprintInfo(r) : null;
  const savedShop = Number.isSafeInteger(r.missing) && r.missing > 0 && Object.hasOwn(r, "shop_snapshot") && typeof shopMissingSnapshotLine === "function"
    ? shopMissingSnapshotLine(r) : null;
  // One <tbody> per card: its numbers, then its labels across the whole width.
  return el("tbody", { class: r.missing > 0 ? "is-missing" : null },
    el("tr", {},
      el("th", { scope: "row", class: "name-cell" }, cardLink({ name: r.name }, "owned-table"),
        el("span", {class: "price-each", text: priced ? `${aud(r.aud_each)} each (estimate)` : "No estimate"})),
      el("td", { class: "num", text: num(r.need) }),
      el("td", { class: "num", text: num(usable) }),
      el("td", { class: "num missing-n", text: num(r.missing) }),
      el("td", { class: "num", text: ownedMissingPrice(r, priceError) === null ? "-" : ownedMissingPrice(r, priceError).toFixed(2) })),
    labels.length ? el("tr", { class: "label-row" },
      el("td", { colspan: 5 }, el("div", { class: "row-labels" }, labels))) : null,
    reprints ? el("tr", {class: "label-row reprint-row"}, el("td", {colspan: 5}, reprints)) : null,
    savedShop ? el("tr", {class: "label-row deck-shop-row"}, el("td", {colspan: 5},
      el("p", {class: "sub", text: "Saved shop checks: any nonfoil printing, each shop with its own fetch time. It may differ from the printing or finish in your list. Price is per card; stock may cover fewer copies than you need." }),
      savedShop)) : null);
}

/** Cards-tab filters may change in this screen; a different deck or saved-list route may not own its table. */
function priceTableRoute(screen) {
  const address = parseHash();
  return address.path === "deck" && address.params.get("id") === screen.data.summary.id &&
    (address.params.get("v") === "owned" ? "owned" : "target") === screen.data.version && screen.view.tab === "cards";
}

function conflictsBox(conflicts) {
  return el("div", { class: "box" },
    el("h3", { text: "Cards other decks are holding" }),
    el("p", { class: "sub", text: "These cards are owned, but some copies sit in other decks. Swap them over, or buy more." }),
    el("ul", {}, conflicts.map((c) => el("li", {},
      el("b", { text: c.name }),
      `: needs ${c.need}, you own ${c.owned}; ${c.decks.map(([deck, n]) => `${n} in ${deck}`).join(", ")}. `,
      c.short > 0 ? status("crit", `${c.short} short`) : "Enough left."))));
}
