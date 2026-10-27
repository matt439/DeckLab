/* Deck Lab's page: Print box label (E8-S21), from a built deck's or an intact product's More menu.

One 63 × 88 mm label for the deck's box: its colours, its title, who plays it (a home deck only: a person's
deck is theirs by its space) and a QR code (qr.js, drawn on the page) to its deck page. The code holds only
the deck page's address: the tunnel's (GET /api/me's "address") when Deck Lab has one, so a phone can open it
from anywhere, else this page's own. Opening it asks for the deck as the page always does, so someone who may
not see the deck gets what a missing deck shows. It prints through deck-print.js's printCardSheet and
cardSizePages, the proxies' card-size layout. Nothing is written.

An owned product kept intact is one box, so it gets one label, from any of its deck pages: the product's
name, the colours across its decks, each deck's name and one QR code, to the product's first deck page
(GET /api/deck's "box_label", product_label.py, only for viewers of home's records). One code stays big
enough to scan from the box; that page's Product storage part links the box's other decks.
*/
"use strict";

/** Whether More offers Print box label: a built deck, or a product kept intact (its box_label). */
function offersBoxLabel(data) {
  const s = data.summary;
  if (s.id.startsWith("product/")) return Boolean(productBoxLabel(data));
  return s.status === "built" && !s.read_only && !s.id.startsWith("pairing/");
}

/** An intact product's label data (GET /api/deck's box_label) when it's whole, else null. */
function productBoxLabel(data) {
  const label = data.box_label;
  return label && typeof label.link === "string" && label.link.startsWith("product/")
    && Array.isArray(label.decks) && label.decks.length ? label : null;
}

/** The address the label's QR code opens: the deck page, at the tunnel's address when there is one. */
function boxLabelAddress(id) {
  const base = (state.me && typeof state.me.address === "string" && /^https:\/\//.test(state.me.address))
    ? state.me.address : location.origin;
  return `${base.replace(/\/+$/, "")}/#/deck?id=${encodeURIComponent(id)}`;
}

/** The deck page the label's code opens: the deck's own, or an intact product's first deck. */
function boxLabelTarget(data) {
  const product = productBoxLabel(data);
  return product ? product.link : data.summary.id;
}

/** The label: colour symbols, title, who plays it (or a product's decks) and the QR code, card-size. */
function boxLabelPiece(data) {
  const s = data.summary, product = productBoxLabel(data);
  const identity = deckColourPieces(product ? product.colors : deckPageColours(data));      // ui.js, deck.js
  const home = !product && deckSpaceOf(s.id) === HOME_SPACE;
  const title = product ? product.name : s.title;
  const several = Boolean(product) && product.decks.length > 1;
  const first = several ? product.decks.find((d) => d.id === product.link) : null;
  const code = qrSvg(boxLabelAddress(boxLabelTarget(data)), several
    ? `QR code: the deck page of ${first ? first.title : "its first deck"}, in ${title}`
    : `QR code: the deck page of ${title}`);
  return el("div", {class: "box-label"},
    identity ? el("p", {class: "box-label-colours", "aria-label": identity.label},
      identity.colours.map((c) => symbolImg(c, {alt: ""}))) : null,
    el("h1", {class: "box-label-title", text: title}),
    home ? el("p", {class: "box-label-player", text: `Played by ${playerWords(s.player)}`}) : null,
    several ? el("ul", {class: "box-label-decks"}, product.decks.map((d) => el("li", {text: d.title}))) : null,
    code,
    el("p", {class: "box-label-scan", text: several ? "Scan for its decks' pages" : "Scan for the deck page"}));
}

/** More menu's Print box label: print the deck's (or its product's) label. */
async function printBoxLabel(data) {
  if (!qrMatrix(boxLabelAddress(boxLabelTarget(data)))) { toast("This deck's address is too long for a QR code."); return; }
  const sheet = el("article", {class: "print-sheet label-sheet"}, cardSizePages([boxLabelPiece(data)]));
  await printCardSheet(sheet);
}
