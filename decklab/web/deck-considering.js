/* The deck page's Considering list (E2-S23): cards that might go in the deck, kept in its text under
 * "## Considering" and counted nowhere (no table, pool, packing, tokens, stats, Forge or sleeves). Shown
 * read-only on the Cards tab, after the decklist; a viewer who sees the collection also sees how many
 * copies of each the pool has free for this deck (/api/deck's considering lines' "free"). */
"use strict";

/** The chip for one Considering line: "2 free in the pool", "None free", or nothing (no pool, a basic land). */
function consideringChip(line) {
  if (line.free == null) return [];
  return [line.free > 0 ? status("good", `${num(line.free)} free in the pool`) : status("plain", "None free")];
}

/** The Cards tab's Considering part, or null for a deck whose text has no Considering list. */
function deckConsideringSection(data) {
  const lines = data.considering;
  if (!lines) return null;
  const section = el("section", { class: "deck-section deck-considering", id: "sec-considering", "aria-labelledby": "h-considering" },
    el("h2", { id: "h-considering" }, "Considering", lines.length ? el("span", { class: "count", text: `(${copies(lines)})` }) : null));
  if (!lines.length) {
    section.append(el("p", { class: "sub", text: "Nothing on it yet." }));
    return section;
  }
  section.append(el("p", { class: "sub", text: "Cards you might add. They aren't in either list, so they're never needed, missing or in use." }),
    el("ul", { class: "card-list" }, lines.map((line) => el("li", {}, cardRow(line.card, {
      qty: line.qty, name: line.name, unknownMeta: "Not a Scryfall card name, so there's no card data",
      chips: consideringChip(line), viewerGroup: "deck-considering", caption: "Considering",
      viewerStatus: () => consideringChip(line) })))));
  return section;
}
