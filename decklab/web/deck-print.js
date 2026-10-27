/* Deck Lab's page: card-size printing (E4-S25), from the deck page's More menu.

Print proxies: a sheet of 63 × 88 mm pictures of the Planned list's missing copies (one per copy), for
playing the planned deck at home before every card has arrived. It reads the Planned list's owned rows, so
it's offered only to a viewer who sees the deck's space's inventory, and it notes the stand-in (the deck's
saved markers for the Planned list) each proxy covers. Nothing is written.

printCardSheet is the shared part: it shows a .print-sheet once its pictures have loaded, prints it and
takes it away again, and cardSizePages lays card-size pieces out nine to a page (a box label can use them
too).
*/
"use strict";

const PRINT_WAIT_MS = 15000;         // the longest a sheet waits for its pictures before printing anyway
const CARDS_PER_PAGE = 9;            // 3 × 3 cards of 63 × 88 mm fit A4 and US Letter inside a 6 mm margin

/** Show sheet (a .print-sheet) once its pictures have loaded (or PRINT_WAIT_MS has passed), print it, and
 * take it away after printing. An earlier sheet still there is replaced. */
async function printCardSheet(sheet) {
  document.querySelector(".print-sheet")?.remove();
  document.body.append(sheet);
  const pictures = [...sheet.querySelectorAll("img")].filter((img) => !img.complete);
  if (pictures.length) {
    await Promise.race([
      Promise.all(pictures.map((img) => new Promise((done) => {
        img.addEventListener("load", done, {once: true});
        img.addEventListener("error", done, {once: true});
      }))),
      new Promise((done) => setTimeout(done, PRINT_WAIT_MS))]);
  }
  if (!sheet.isConnected) return;           // a later sheet took its place
  window.addEventListener("afterprint", () => sheet.remove(), {once: true});
  window.print();
}

/** pieces (card-size elements) as printed pages of CARDS_PER_PAGE, each its own page. */
function cardSizePages(pieces) {
  const pages = [];
  for (let i = 0; i < pieces.length; i += CARDS_PER_PAGE) {
    pages.push(el("div", {class: "card-page"}, pieces.slice(i, i + CARDS_PER_PAGE)));
  }
  return pages;
}

/** The proxies a Planned list's answer (/api/deck, version target, with owned rows) needs: one entry per
 * missing copy, in the list's order, each {name, card, face: 0|1, covers}, where covers is the stand-in
 * that copy replaces ("Physical marker", "any card") or null. A card with a back picture of its own gets its
 * back too, right after the front. null when the answer has no owned rows (the inventory isn't the
 * viewer's). */
function proxyCopies(target) {
  if (!target || !target.owned) return null;
  const groups = Object.values(target.sections || {}).map((lines) => ({lines}));
  const marks = lineMarks(groups, cardMarks(target));
  const standins = deckStandinsOf(target);
  const covering = new Map();          // name -> the stand-ins left to cover, one entry per copy
  for (const row of (standins && standins.version === "target" ? standins.rows : []) || []) {
    const left = covering.get(row.for) || [];
    for (let i = 0; i < row.qty; i++) left.push(row.using || "any card");
    covering.set(row.for, left);
  }
  const copies = [];
  for (const {lines} of groups) {
    for (const line of lines) {
      const mark = marks.get(line);
      for (let i = 0; i < (mark ? mark.missing : 0); i++) {
        const covers = (covering.get(line.name) || []).shift() || null;
        copies.push({name: line.name, card: line.card || null, face: 0, covers});
        if (line.card && hasBackPicture(line.card)) copies.push({name: line.name, card: line.card, face: 1, covers});
      }
    }
  }
  return copies;
}

/** One proxy: the card's large picture (the normal one when there's no large), or its words when it has no
 * picture. */
function proxyPiece(copy) {
  const picture = copy.card ? facePicture(copy.card, copy.face) : null;
  const local = typeof picture === "string" && picture.startsWith("/img/") ? picture : null;
  if (local) {
    return el("div", {class: "proxy-card"}, el("img", {src: viewerLargeUrl(local) || local, loading: "eager",
      alt: copy.face ? `${copy.name} (back)` : copy.name}));
  }
  const card = copy.card || {};
  const stats = card.power != null ? `${card.power}/${card.toughness}` : card.loyalty != null ? `Loyalty ${card.loyalty}` : "";
  return el("div", {class: "proxy-card proxy-text"},
    el("p", {class: "proxy-name"}, el("strong", {text: copy.name}), card.mana_cost ? ` ${card.mana_cost}` : ""),
    card.type_line ? el("p", {class: "proxy-type", text: card.type_line}) : null,
    card.oracle_text ? el("p", {class: "proxy-rules", text: card.oracle_text}) : null,
    stats ? el("p", {class: "proxy-stats", text: stats}) : null);
}

/** The sheet's first page: what it is, how to print it, and each proxy in print order with the stand-in it
 * covers. */
function proxyIntro(target, copies) {
  const fronts = copies.filter((c) => !c.face).length;
  const entries = [];
  copies.forEach((copy, i) => {
    const words = `${copy.name}${copy.face ? " (back)" : ""}`;
    const last = entries.at(-1);
    if (last && last.words === words && last.covers === copy.covers) last.to = i + 1;
    else entries.push({from: i + 1, to: i + 1, words, covers: copy.covers});
  });
  const coming = (target.owned.rows || []).reduce((n, r) => n + rowLabels(r).on_the_way.reduce((m, [, q]) => m + q, 0), 0);
  return el("section", {class: "proxy-intro"},
    el("h1", {text: `${target.summary.title}: proxies`}),
    el("p", {text: `${plural(fronts, "missing copy", "missing copies")} of the Planned list, ` +
      `${plural(copies.length, "card", "cards")} to cut out. For home games only.`}),
    el("p", {class: "print-warning", text: "Print at 100% (actual size, not fit to page): each card is 63 × 88 mm."}),
    coming ? el("p", {text: `${plural(coming, "copy is", "copies are")} on the way and not printed.`}) : null,
    el("ul", {class: "proxy-list"}, entries.map((e) => el("li", {text:
      `${e.to > e.from ? `${e.from}–${e.to}` : e.from}. ${e.words}` +
      (e.covers ? `: covers the stand-in (${e.covers})` : "")}))));
}

/** The Planned list's answer: data when it is the Planned list, else /api/deck's. */
async function plannedListOf(data) {
  if (data.version === "target") return data;
  return api(`/api/deck?id=${encodeURIComponent(data.summary.id)}&version=target&omit=matchups`);
}

/** More menu's Print proxies: print the Planned list's missing copies at card size. */
async function printProxies(data) {
  const token = typeof routeToken === "undefined" ? null : routeToken;
  let target;
  try {
    target = await plannedListOf(data);
  } catch (e) {
    toast(`The Planned list couldn't be loaded: ${e.message}`);
    return;
  }
  if (token !== null && token !== routeToken) return;          // the page was left meanwhile
  const copies = proxyCopies(target);
  if (copies === null) { toast("Missing cards show only to the people whose collection this deck uses."); return; }
  if (!copies.length) { toast("Nothing in the Planned list is missing."); return; }
  toast(`Getting ${plural(copies.length, "picture", "pictures")} ready to print…`);
  const sheet = el("article", {class: "print-sheet proxy-sheet"},
    proxyIntro(target, copies), cardSizePages(copies.map(proxyPiece)));
  await printCardSheet(sheet);
}

/** Whether More offers Print proxies: to a viewer who sees the deck's inventory, when the Planned list has
 * missing copies (the Play-now list's answer doesn't say, so it's offered there and checked on use). */
function offersProxies(data) {
  const s = data.summary;
  if (!data.owned || !(data.versions || []).includes("target") || !seesInventory(s.space || deckSpaceOf(s.id))) return false;
  return data.version !== "target" || (data.owned.totals?.missing || 0) > 0;
}
