/* Deck Lab's page: the shared card pieces (decklab/UI-REVIEW.md 2.3, WP5; decklab/UI-KIT.md says how
to use them). A card tile (cardTile: the picture with its copies, a state slot, foil sheen, name, one meta
line and chips), a card row (cardRow: thumbnail, copies, name and meta, the cost), a token tile
(tokenTile), the viewer groups that let the card viewer (card-viewer.js) swipe between the cards a page
shows, and the shared printing picker (pickPrinting).

A card here is what the API sends for one (lib/api/card_lookup.py _card_json): name, mana_cost, type_line,
oracle_text, img and img_small (Deck Lab's /img/ addresses, or null), faces, power and so on. A piece made
without a card (a name Scryfall doesn't know) is drawn as words only, and opens nothing.

Loaded after core.js; it uses deck.js's cardThumb, manaCost and peekable, card-viewer.js's openCard and
editor.js's openSheet once the page is running. Nothing runs at load.
*/
"use strict";

const CARD_RATIO = 680 / 488;           // a card's height over its width
const TILE_SIZES = "(max-width: 599px) 33vw, (min-width: 2200px) 196px, 180px";   // a .card-tile's picture


// ------------------------------------------------------------ viewer groups

// An element on the page -> {card, caption, status} it shows in the card viewer. Elements marked with the same
// data-viewer group open the viewer over each other, in the order they're on the page.
const viewerCards = new WeakMap();

/** Marks node as showing card in viewer group (a name for the list, such as "deck"): a click that calls
 * openCard(card, node) opens the viewer on it, with the group's other cards a swipe or an arrow key away.
 * caption: a line or two for the viewer's text ("4 copies · FDN 227"). status: a function giving the chips the
 * viewer shows under its counter, always in sight (the tile's "Missing", "1 on the way"), or null. Returns node. */
function viewerItem(node, card, group, caption = null, status = null) {
  if (card && group) {
    viewerCards.set(node, { card, caption, status });
    node.setAttribute("data-viewer", group);
  }
  return node;
}

/** The cards of node's viewer group in page order, and node's place in it: {items, index}, or null when
 * node isn't in a group. Elements that aren't shown (display: none, a folded list) are left out. */
function viewerGroup(node) {
  const group = node && node.getAttribute ? node.getAttribute("data-viewer") : null;
  if (!group || !viewerCards.has(node)) return null;
  const nodes = Array.from(document.querySelectorAll("[data-viewer]")).filter((n) => n.getAttribute("data-viewer") === group
    && viewerCards.has(n) && (n === node || !n.getClientRects || n.getClientRects().length > 0));
  const index = nodes.indexOf(node);
  return index < 0 ? null : { items: nodes.map((n) => viewerCards.get(n)), index };
}


// -------------------------------------------------------------- pictures

/** A card's front name, for one line ("Delver of Secrets // Insectile Aberration" -> "Delver of Secrets"). */
function frontName(name) { return String(name || "").split(" // ")[0]; }

/** A card's picture for a tile: the small image, and the normal one where the tile is drawn bigger than
 * 146 px (sizes, as for <img sizes>). The words under it show while it loads and if it can't. large: an
 * address of a bigger picture (672 px wide) to offer too; if it fails, the small and normal ones are offered
 * instead, and only a failure after that leaves the words. */
function tilePicture(card, sizes, name, large = null) {
  const words = el("span", { class: "card-tile-text" },
    el("b", { text: card ? card.name : name }),
    card && card.mana_cost ? manaCost(card.mana_cost, true) : null,
    card && card.type_line ? el("small", { text: card.type_line }) : null);
  if (!card || !card.img_small) return [words];
  const usual = card.img ? `${card.img_small} 146w, ${card.img} 488w` : null;
  const big = usual && large ? `${usual}, ${large} 672w` : null;
  const img = el("img", { class: "card-tile-img", alt: "", loading: "lazy", decoding: "async", draggable: "false",
    src: card.img_small, srcset: big || usual,
    sizes: card.img ? sizes : null, width: 146, height: Math.round(146 * CARD_RATIO),
    onerror: () => {
      if (big && img.getAttribute("srcset") === big) img.setAttribute("srcset", usual);
      else img.remove();
    } });
  words.setAttribute("aria-hidden", "true");
  return [words, img];
}

/** A finish worth a chip: "Foil", "Etched" (nonfoil, the usual, says nothing). */
function finishChip(finish) {
  if (finish === "foil") return el("span", { class: "chip chip-plain chip-foil", text: "Foil" });
  if (finish === "etched") return el("span", { class: "chip chip-plain chip-foil", text: "Etched" });
  return null;
}


// -------------------------------------------------------------- the tile

/** A meta line's "·"-separated facts as nodes that keep each fact whole: a line that wraps breaks only before a
 * "·" ("FDC 31" / "· Nonfoil"), never inside a fact or after its dot. The words are the same. */
function metaParts(meta) {
  return String(meta).split(" · ").flatMap((part, i) =>
    [i ? " " : null, el("span", { class: "meta-part", text: i ? `· ${part}` : part })]);
}

/** A card as a picture tile (.card-tile). opts:
 *   qty         copies: a ×N badge on the picture when more than 1
 *   name        the words under the picture (default the card's front name; the full name is its title)
 *   meta        one line under the name ("MSC 143 · Nonfoil"), or null
 *   finish      "foil" or "etched": a sheen on the picture and a chip
 *   state       a node for the top-right corner (a tick button, a status badge); it sits outside the open
 *               button, so it may be a button itself
 *   ticked      true: an accent ring and the picture dimmed (a tile checked off)
 *   unrecorded  words for a dashed frame and a ribbon ("Default picture: printing not recorded")
 *   chips       nodes under the meta line (deck chips, "Condition ?"); show chips only for exceptions
 *   onclick     what a click does (default: the card viewer, over the tile's viewerGroup when given)
 *   viewerGroup the viewer group's name (viewerItem); caption: its viewer caption; viewerStatus: a function
 *               giving the chips the viewer shows under its counter (deck.js: the tile's own, such as "Missing")
 *   label       the open button's accessible name, when the name alone isn't enough
 *   sizes       <img sizes> for the picture (default TILE_SIZES)
 *   large       a bigger picture's address (the /img/ route's "large", 672 px) to offer as well, for a tile
 *               drawn big; the normal one is used when it can't load
 * Without a card (or a picture) the tile shows its name and type in card proportions instead. */
function cardTile(card, opts = {}) {
  const name = opts.name || frontName(card ? card.name : "");
  const finish = opts.finish && opts.finish !== "nonfoil" ? opts.finish : null;
  const pic = el("span", { class: "card-tile-pic" }, tilePicture(card, opts.sizes || TILE_SIZES, name, opts.large || null),
    opts.qty > 1 ? el("span", { class: "card-tile-qty", text: `×${opts.qty}` }) : null,
    opts.unrecorded ? el("span", { class: "card-tile-ribbon", text: opts.unrecorded }) : null);
  const words = [pic,
    el("span", { class: "card-tile-name", title: card && card.name !== name ? card.name : null, text: name }),
    opts.meta ? el("span", { class: "card-tile-meta" }, metaParts(opts.meta)) : null];
  const click = opts.onclick || (card ? (e) => openCard(card, e.currentTarget) : null);
  const open = click
    ? el("button", { type: "button", class: "card-tile-open", "aria-haspopup": opts.onclick ? null : "dialog",
      "aria-label": opts.label || null, onclick: click }, words)
    : el("div", { class: "card-tile-open" }, words);
  if (card && !opts.onclick && opts.viewerGroup) viewerItem(open, card, opts.viewerGroup, opts.caption || null, opts.viewerStatus || null);
  if (card && card.img) peekable(open, card);
  const chips = [finishChip(finish), ...(opts.chips || [])].filter(Boolean);
  const cls = ["card-tile", finish ? `is-${finish}` : "", opts.unrecorded ? "is-unrecorded" : "",
    opts.ticked ? "is-ticked" : "", card && card.img_small ? "" : "is-text"].filter(Boolean).join(" ");
  return el("div", { class: cls },
    open,
    opts.state ? el("span", { class: "card-tile-state" }, opts.state) : null,
    chips.length ? el("div", { class: "card-tile-chips" }, chips) : null);
}


// --------------------------------------------------------------- the row

/** A card as one row of a list (.card-row): thumbnail, copies, the name with one meta line (and chips),
 * then the aside (the mana cost by default). opts:
 *   qty         copies (shown as a number before the name; .qty-one marks 1); null: no column
 *   name, meta  as cardTile's (meta defaults to the type line; unknownMeta replaces it when there's no card)
 *   chips       nodes after the meta line
 *   aside       the node at the end (default manaCost of the card's cost; null for nothing)
 *   onclick, viewerGroup, caption, viewerStatus   as cardTile's
 *   thumbWide   "<media condition> <width>" where the row's thumbnail is drawn bigger (the deck's picture grid,
 *               "(min-width: 1600px) 220px"): the normal image is offered there (deck.js cardThumb)
 * Without a card it's a plain <div> that opens nothing. */
function cardRow(card, opts = {}) {
  // The name is right beside it, so the thumbnail itself is decorative; the viewer has alt text.
  const thumb = !(card && card.img_small) ? el("span", { class: "thumb-missing", "aria-hidden": "true" })
    : opts.thumbWide ? cardThumb(card, "thumb", 40, opts.thumbWide)
      : el("img", { class: "thumb", alt: "", loading: "lazy", decoding: "async", src: card.img_small, width: 40, height: 56 });
  const hasQty = opts.qty != null;
  const qty = hasQty ? el("span", { class: "qty" + (opts.qty === 1 ? " qty-one" : ""), text: String(opts.qty) }) : null;
  const meta = opts.meta !== undefined ? opts.meta : card ? card.type_line : opts.unknownMeta || "";
  const name = el("span", { class: "name" }, opts.name || (card ? card.name : ""),
    meta ? el("small", { class: card ? null : "unknown", text: meta }) : null,
    opts.chips && opts.chips.length ? el("span", { class: "card-row-chips" }, opts.chips) : null);
  const aside = opts.aside !== undefined ? opts.aside : card ? manaCost(card.mana_cost) : null;
  const cls = "card-row" + (hasQty ? "" : " card-row-noqty");
  const parts = [thumb, qty, name, aside || el("span")];
  if (!card) return el("div", { class: cls }, parts);
  const node = el("button", { type: "button", class: cls, "aria-haspopup": opts.onclick ? null : "dialog",
    onclick: opts.onclick || ((e) => openCard(card, e.currentTarget)) }, parts);
  if (!opts.onclick && opts.viewerGroup) viewerItem(node, card, opts.viewerGroup, opts.caption || null, opts.viewerStatus || null);
  return peekable(node, card);
}


// ------------------------------------------------------------- token tile

/** A token or reminder card as a tile: token is {front, back?, img?, back_img?, qty?} (img and back_img
 * Deck Lab's /img/ addresses; anything else isn't loaded), opts as cardTile's (meta: "TM11 5 · 2/2 Ooze").
 * The back, when it has a picture, overlaps the front's corner. The viewer flips between the faces. */
function tokenTile(token, opts = {}) {
  const local = (url) => (typeof url === "string" && url.startsWith("/img/") ? url : null);
  const front = local(token.img), back = local(token.back_img);
  const name = token.back ? `${token.front} // ${token.back}` : token.front;
  const card = { name, type_line: opts.meta || "Token", mana_cost: "", img: front, img_small: front,
    oracle_text: null, faces: token.back ? [{ name: token.front, type_line: "Front", img: front, img_small: front },
      { name: token.back, type_line: "Back", img: back, img_small: back }] : null };
  const tile = cardTile(card, { name: opts.name || name, sizes: "(max-width: 599px) 33vw, 146px", ...opts });
  tile.classList.add("token-tile");
  if (back) {
    tile.querySelector(".card-tile-pic").append(el("img", { class: "card-tile-back", src: back, alt: "",
      loading: "lazy", decoding: "async", width: 60, height: 84, onerror: (e) => e.currentTarget.remove() }));
  }
  return tile;
}


// --------------------------------------------------------- printing picker

/** Lets the person choose one of a card's printings in a sheet: a grid of its pictures with the set's
 * code, number and name, finishes and copies owned (GET /api/cards/printings). opts.current: the
 * {set, number, finish} chosen now (marked); opts.title: the sheet's heading. Resolves with the chosen
 * {set, number, finish, set_name, img_small, img, aud, owned, on_the_way} (a basic land's "Any printing" is
 * {set: null, number: null, finish: "nonfoil"}), or null when the sheet is closed. opts.actions adds buttons to
 * the sheet's foot (an editor line's Move and Remove): [{text, value, kind}], resolving with {action: value}. */
function pickPrinting(name, opts = {}) {
  return new Promise((resolve) => {
    let chosen = null;
    const sheet = openSheet({ title: opts.title || `${name}: printing`, wide: true, onClose: () => resolve(chosen) });
    if (opts.onOpen) opts.onOpen(sheet);
    const body = el("div", { class: "pp" }, loadingBox("Looking up its printings…"));
    sheet.body.append(body);
    // opts.actions: more buttons for the foot ([{text, value, kind}]; destructive last), each resolving with {action: value}.
    sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() },
      ...(opts.actions || []).map((a) => ({ text: a.text, kind: a.kind || "", value: a.value,
        onclick: () => { chosen = { action: a.value }; sheet.close(); } }))]);
    const pick = (p, finish) => { chosen = { ...p, finish }; delete chosen.finishes; sheet.close(); };
    api(`/api/cards/printings?name=${encodeURIComponent(name)}`).then((a) => {
      if (sheet.closed) return;
      const current = opts.current || null;
      // One tile per printing; its finishes (one row each in the answer) are buttons under it.
      const printings = [];
      for (const p of a.printings || []) {
        const same = printings.find((o) => o.set === p.set && o.number === p.number);
        if (same) { same.finishes.push(p); continue; }
        printings.push({ ...p, finishes: [p] });
      }
      const isCurrent = (p, f) => current && current.set === p.set && current.number === p.number
        && (!f || (current.finish || "nonfoil") === f.finish);
      const tiles = printings.map((p) => {
        const have = p.finishes.reduce((n, f) => n + (f.owned || 0), 0);
        const coming = p.finishes.reduce((n, f) => n + (f.on_the_way || 0), 0);
        const first = p.finishes.find((f) => isCurrent(p, f)) || p.finishes.find((f) => f.finish === "nonfoil") || p.finishes[0];
        const words = [`${p.set.toUpperCase()} ${p.number}`, p.released ? p.released.slice(0, 4) : null].filter(Boolean).join(" · ");
        const counts = [have ? `${have} owned` : "", coming ? `${coming} on the way` : ""].filter(Boolean).join(" · ");
        const finishes = p.finishes.length > 1
          ? el("div", { class: "pp-finishes", role: "group", "aria-label": `Finish of ${words}` }, p.finishes.map((f) =>
            el("button", { type: "button", class: "btn btn-quiet", "aria-pressed": String(Boolean(isCurrent(p, f))),
              onclick: () => pick(p, f.finish) }, capitalise(f.finish), f.owned ? el("small", { text: ` ${f.owned}` }) : null)))
          : null;
        return cardTile({ name, type_line: p.set_name, img: p.img, img_small: p.img_small }, {
          name: words, meta: p.set_name || null, finish: p.finishes.length === 1 ? p.finishes[0].finish : null,
          ticked: Boolean(isCurrent(p)), label: `${words}, ${p.set_name || ""}${isCurrent(p) ? ", chosen now" : ""}`,
          sizes: "(max-width: 599px) 33vw, 146px",
          chips: [counts ? el("span", { class: "chip chip-info", text: counts }) : null, finishes].filter(Boolean),
          state: isCurrent(p) ? el("span", { class: "card-tile-tick", "aria-hidden": "true" }) : null,
          onclick: () => pick(p, first.finish) });
      });
      add(clear(body), [
        a.basic ? el("div", { class: "actions" }, el("button", { type: "button", class: "btn",
          "aria-pressed": String(Boolean(current && !current.set)),
          onclick: () => pick({ set: null, number: null }, "nonfoil") }, "Any printing")) : null,
        tiles.length ? el("div", { class: "pp-grid" }, tiles) : el("p", { class: "empty", text: "No paper printings found." }),
        a.total > (a.printings || []).length ? el("p", { class: "sub",
          text: `Showing the ${(a.printings || []).length} likeliest of ${a.total}: the ones you have first, then the cheapest.` }) : null]);
      const mark = body.querySelector(".is-ticked .card-tile-open") || body.querySelector(".card-tile-open");
      if (mark) mark.focus();
    }).catch((e) => {
      if (!(e instanceof ApiError)) throw e;
      if (!sheet.closed) add(clear(body), [el("div", { class: "box box-crit" }, el("p", { text: e.message }))]);
    });
  });
}
