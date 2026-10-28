/* Informational destinations for one saved CSV import. Quantities and printing facts come only
 * from that response; current collection rows and mutable preview choices never supply them. */
"use strict";

const COL_FILING_MAX = 20000;
const COL_FILING_PAGE = 100;

/** Copy a bounded, conserved response into a profile/space-bound one-use notice. */
function colFilingSnapshot(answer, cv) {
  if (!answer || !Object.hasOwn(answer, "filing")) return null; // older server
  const raw = answer.filing;
  if (!raw || raw.space !== cv.space || raw.profile !== cv.profile || cv.space !== ownSpace()) return null;
  const total = Number.isSafeInteger(answer.added?.cards) && answer.added.cards > 0 ? answer.added.cards : null;
  const unknown = added => Object.freeze({ space: cv.space, profile: cv.profile, status: "unknown", total,
    added: Object.freeze(added), destinations: Object.freeze(added.map((row, index) =>
      Object.freeze({ kind: "unknown", row: index, quantity: row.quantity }))) });
  if (!total || !Array.isArray(raw.added) || !raw.added.length || raw.added.length > COL_FILING_MAX) return unknown([]);
  const added = [], keys = new Set();
  for (const row of raw.added) {
    if (!row || !["name", "set", "collector_number", "finish"].every(key => typeof row[key] === "string")
        || !row.name || row.name.length > 300 || row.set.length > 8 || row.collector_number.length > 40
        || !["nonfoil", "foil", "etched"].includes(row.finish) || !Number.isSafeInteger(row.quantity) || row.quantity < 1) return unknown([]);
    const key = JSON.stringify([row.set, row.collector_number, row.finish]);
    if (keys.has(key)) return unknown([]);
    keys.add(key);
    added.push(Object.freeze({ name: row.name, set: row.set, collector_number: row.collector_number,
      finish: row.finish, quantity: row.quantity }));
  }
  if (added.reduce((sum, row) => sum + row.quantity, 0) !== total) return unknown([]);
  if (raw.status !== "ready" || !Array.isArray(raw.destinations) || raw.destinations.length > COL_FILING_MAX) return unknown(added);
  const accounted = added.map(() => 0), destinations = [];
  for (const item of raw.destinations) {
    if (!item || !Number.isInteger(item.row) || item.row < 0 || item.row >= added.length
        || !Number.isSafeInteger(item.quantity) || item.quantity < 1 || !["deck", "storage", "unknown"].includes(item.kind)) return unknown(added);
    accounted[item.row] += item.quantity;
    if (accounted[item.row] > added[item.row].quantity) return unknown(added);
    const copy = { kind: item.kind, row: item.row, quantity: item.quantity };
    if (item.kind === "deck") {
      const deck = item.deck, pieces = typeof deck?.id === "string" ? deck.id.split("/") : [];
      const kind = cv.space === HOME_SPACE ? pieces[0] : pieces[1];
      if (!deck || !["casual", "commander"].includes(kind) || pieces.length !== (cv.space === HOME_SPACE ? 2 : 3)
          || !pieces.at(-1) || deckSpaceOf(deck.id) !== cv.space || typeof deck.title !== "string"
          || !deck.title || deck.title.length > 300 || typeof deck.status !== "string") return unknown(added);
      copy.deck = Object.freeze({ id: deck.id, title: deck.title, status: deck.status });
    }
    destinations.push(Object.freeze(copy));
  }
  if (accounted.some((quantity, index) => quantity !== added[index].quantity)) return unknown(added);
  return Object.freeze({ space: cv.space, profile: cv.profile, status: "ready", total,
    added: Object.freeze(added), destinations: Object.freeze(destinations) });
}

function colFilingHere(cv, guide, root = null) {
  return colActive(cv) && cv.profile === guide.profile && cv.space === guide.space && ownSpace() === cv.space
    && seesInventory(cv.space) && (!root || root.isConnected && cv.message.contains(root));
}

/** One set of original controls in either density; Show more never changes the advice or writes. */
function colFilingGuide(cv, guide) {
  if (!colFilingHere(cv, guide)) return null;
  const root = el("section", { class: "col-filing-guide", "aria-label": "Where these go, saved import" },
    el("h2", { text: "Where these go" }),
    el("p", { class: "sub", text: `${guide.total ? `For the ${plural(guide.total, "copy", "copies")} added by this import. ` : "The import is saved. "}`
      + "Filing suggestions based on the deck lists at that point; check them as you file the cards." }));
  const groups = new Map();
  for (const item of guide.destinations) {
    const key = item.kind === "deck" ? `deck:${item.deck.id}` : item.kind;
    if (!groups.has(key)) groups.set(key, { kind: item.kind, deck: item.deck, items: [] });
    groups.get(key).items.push(item);
  }
  if (guide.status === "unknown") root.append(el("p", { class: "box box-info col-filing-unknown", text:
    "Destination unknown. The import is saved, but its deck destinations couldn't be checked. Check where these copies belong." }));
  if (!groups.size && guide.status === "unknown") return root;
  const panels = el("div", { class: "col-filing-panels" });
  let initialLeft = COL_FILING_PAGE; // bound the whole first paint, including many waiting decks
  for (const group of groups.values()) {
    const heading = group.kind === "deck" ? el("h3", {}, el("a", { href: deckHref(group.deck.id, "target"), text: group.deck.title }))
      : el("h3", { text: group.kind === "storage" ? "To storage" : "Destination unknown" });
    const panel = el("section", { class: "panel col-filing-panel" }, heading,
      group.kind === "storage" ? el("p", { class: "sub", text: "Copies left after the waiting decks: keep them with your unsleeved cards." }) : null);
    const list = el("ul", { class: "col-filing-lines", tabindex: 0,
      "aria-label": group.kind === "deck" ? `Printing copies suggested for ${group.deck.title}` : "Imported printing copies" });
    const count = el("p", { class: "result-count", role: "status" });
    let shown = 0;
    const draw = (limit = COL_FILING_PAGE) => {
      const next = group.items.slice(shown, shown + limit);
      for (const item of next) {
        const row = guide.added[item.row];
        list.append(el("li", { text: `${item.quantity} \u00d7 ${row.name} (${colPrinting(row)})` }));
      }
      shown += next.length;
      count.textContent = `${shown} of ${plural(group.items.length, "printing line")}`;
      more.hidden = shown >= group.items.length;
    };
    const more = el("button", { type: "button", class: "btn col-filing-more", text: "Show more imported printing lines", onclick: event => {
      if (!colFilingHere(cv, guide, root) || !event.currentTarget.isConnected || event.currentTarget.hidden
          || event.currentTarget.disabled || document.querySelector("dialog[open]") || keyboardMenuOpen()) return;
      draw(); if (more.hidden) list.focus({ preventScroll: true });
    } });
    const initial = Math.min(initialLeft, group.items.length);
    draw(initial); initialLeft -= initial;
    panel.append(list, count, more); panels.append(panel);
  }
  root.append(panels);
  return root;
}
