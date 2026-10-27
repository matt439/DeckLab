/* Deck Lab's page: Print box label (E8-S21), from a built deck's More menu.

One 63 × 88 mm label for the deck's box: its colours, its title, who plays it (a home deck only: a person's
deck is theirs by its space) and a QR code (qr.js, drawn on the page) to its deck page. The code holds only
the deck page's address: the tunnel's (GET /api/me's "address") when Deck Lab has one, so a phone can open it
from anywhere, else this page's own. Opening it asks for the deck as the page always does, so someone who may
not see the deck gets what a missing deck shows. It prints through deck-print.js's printCardSheet and
cardSizePages, the proxies' card-size layout. Nothing is written.
*/
"use strict";

/** Whether More offers Print box label: a built deck (a product's label is a later slice). */
function offersBoxLabel(data) {
  const s = data.summary;
  return s.status === "built" && !s.read_only && !/^(product|pairing)\//.test(s.id);
}

/** The address the label's QR code opens: the deck page, at the tunnel's address when there is one. */
function boxLabelAddress(id) {
  const base = (state.me && typeof state.me.address === "string" && /^https:\/\//.test(state.me.address))
    ? state.me.address : location.origin;
  return `${base.replace(/\/+$/, "")}/#/deck?id=${encodeURIComponent(id)}`;
}

/** The label: colour symbols, title, who plays it and the QR code, card-size. */
function boxLabelPiece(data) {
  const s = data.summary;
  const identity = deckColourPieces(deckPageColours(data));      // ui.js, deck.js
  const home = deckSpaceOf(s.id) === HOME_SPACE;
  const code = qrSvg(boxLabelAddress(s.id), `QR code: the deck page of ${s.title}`);
  return el("div", {class: "box-label"},
    identity ? el("p", {class: "box-label-colours", "aria-label": identity.label},
      identity.colours.map((c) => symbolImg(c, {alt: ""}))) : null,
    el("h1", {class: "box-label-title", text: s.title}),
    home ? el("p", {class: "box-label-player", text: `Played by ${playerWords(s.player)}`}) : null,
    code,
    el("p", {class: "box-label-scan", text: "Scan for the deck page"}));
}

/** More menu's Print box label: print the deck's label. */
async function printBoxLabel(data) {
  if (!qrMatrix(boxLabelAddress(data.summary.id))) { toast("This deck's address is too long for a QR code."); return; }
  const sheet = el("article", {class: "print-sheet label-sheet"}, cardSizePages([boxLabelPiece(data)]));
  await printCardSheet(sheet);
}
