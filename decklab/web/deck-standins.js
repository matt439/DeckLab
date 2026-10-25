/* The physical markers for the displayed logical list, already resolved by the server.
 * Stand-ins reveal inventory, so stale page data is also checked against the current viewer. */
"use strict";

function deckStandinsOf(data) {
  const standins = data.standins;
  const space = data.summary.space || deckSpaceOf(data.summary.id);
  return standins && standins.version === data.version && seesInventory(space) ? standins : null;
}

function deckStandinWords(row) {
  return `${row.using || "Any card"} stands for ${row.for}`;
}

function deckStandinsSection(data) {
  const standins = deckStandinsOf(data);
  if (!standins || (!(standins.rows || []).length && !(standins.warnings || []).length)) return null;
  return el("section", { class: "deck-section deck-standins", id: "sec-standins", "aria-labelledby": "h-standins" },
    el("h2", { id: "h-standins", text: "Stand-ins" }),
    (standins.rows || []).length ? [
      el("p", { class: "sub", text: "Tell your opponent what each stand-in represents. Tap a card for its picture and rules." }),
      el("div", {}, standins.rows.map(row => cardRow(row.card, {
        qty: row.qty, name: deckStandinWords(row),
        meta: row.card ? `Picture and rules for ${row.for}` : "Picture and rules unavailable",
        viewerGroup: "deck-standins", caption: `${row.qty} x ${deckStandinWords(row)}`,
      }))),
    ] : null,
    (standins.warnings || []).length ? el("div", { class: "box box-warn" },
      el("ul", {}, standins.warnings.map(text => el("li", { text })))) : null);
}
