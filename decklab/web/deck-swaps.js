/* The deck page's side of stand-ins for missing cards (E2-S07): owned cards that could play a missing
 * card's slot, and the swaps the Play-now list already makes, with their Substitutes notes.
 *
 * deckSwapFinder: on the Cards tab under the Missing filter (either list), for a visitor who may see the
 * deck's space's collection (GET /api/deck/swaps, asked for once per list on screen). One row per missing
 * card, in the order worth buying (no stand-in first); "See them" lists the stand-ins, and a visitor who
 * may change the deck gets "Swap into the Play-now list", which opens the editor there with that card's
 * stand-ins (editor-swaps.js, #/edit?…&v=owned&swap=<name>).
 *
 * deckSwapsSection: on the Play-now list's Overview and Cards tab, each swap the list makes (/api/deck's
 * "swaps", worked out from the two lists and the Substitutes write-up, which every viewer of the deck
 * sees), with its note or "No note yet", and "Edit notes" (the editor's Notes tab) for whoever may change
 * the deck. Not the Packing plan's physical stand-ins (deck-standins.js), which never change a list.
 */
"use strict";

const SWAP_FINDER_ROWS = 5;      // missing cards the box shows before "Show all" (a phone's screen)

/** True when the deck on screen is an ordinary deck whose collection the visitor may see. */
function deckSwapsOffered(data) {
  const s = data.summary;
  return !/^(product|pairing)\//.test(s.id) && Boolean(data.owned) && seesInventory(s.space || deckSpaceOf(s.id));
}

/** The Missing filter's "Owned stand-ins" box, or null. */
function deckSwapFinder(screen) {
  const data = screen.data;
  if (screen.view.filter !== "missing" || !deckSwapsOffered(data)) return null;
  const box = el("section", { class: "box deck-swap-finder", "aria-labelledby": "h-swap-finder" },
    el("h3", { id: "h-swap-finder", text: "Owned stand-ins" }));
  const body = el("div", {}, loadingBox("Looking for stand-ins…"));
  box.append(body);
  if (!screen.swapFinder || screen.swapFinder.version !== data.version) {
    screen.swapFinder = { version: data.version,
      answer: api(`/api/deck/swaps?id=${encodeURIComponent(data.summary.id)}&version=${data.version}`) };
  }
  screen.swapFinder.answer.then((answer) => {
    if (deckScreen !== screen || !body.isConnected) return;
    drawSwapFinder(body, data, answer);
  }, (e) => {
    if (deckScreen === screen) clear(body).append(el("p", { class: "sub", text: e.message }));
  });
  return box;
}

function drawSwapFinder(body, data, answer) {
  if (!answer || !Array.isArray(answer.cards)) {        // not an answer this page can read: say nothing
    const box = body.closest(".deck-swap-finder");
    if (box) box.remove();
    return;
  }
  if (!answer.cards.length) {
    clear(body).append(el("p", { class: "sub", text: "Nothing missing can be swapped (commanders and basic lands never are)." }));
    return;
  }
  const row = (entry) => {
    const n = entry.candidates.length + entry.more;
    return el("li", { class: "swap-finder-row" },
      el("span", { class: "swap-finder-name" }, entry.name,
        el("small", { text: n ? `${entry.missing} missing · ${n} could stand in`
          : `${entry.missing} missing · no close stand-in: worth buying first` })),
      n ? el("button", { type: "button", class: "btn", text: "See them",
        "aria-label": `See the stand-ins for ${entry.name}`, onclick: () => openDeckSwapSheet(data, entry, answer) }) : null);
  };
  // The first few, with the rest behind "Show all", so a long list doesn't push the missing cards off a phone's screen.
  const list = el("ul", { class: "swap-finder-list" }, answer.cards.slice(0, SWAP_FINDER_ROWS).map(row));
  const rest = answer.cards.slice(SWAP_FINDER_ROWS);
  const more = rest.length ? el("button", { type: "button", class: "btn btn-quiet", text: `Show all ${answer.cards.length}`,
    onclick: () => { list.append(...rest.map(row)); more.remove(); } }) : null;
  add(clear(body), [
    el("p", { class: "sub", text: "Cards you have that could play these slots tonight, the most worth buying first." }),
    list, more]);
}

/** The stand-ins for one missing card, read-only, with the way into the editor for whoever may edit. */
function openDeckSwapSheet(data, entry, answer) {
  const s = data.summary;
  const editable = canEditDeck(s);
  // Only when the Play-now list is short of it too: else the editor would have nothing to swap.
  const out = !(entry.list_missing > 0);
  const sheet = openSheet({ title: `Stand-ins for ${entry.name}`, side: true });
  sheet.dialog.classList.add("swap-sheet");
  add(sheet.body, [
    el("p", { class: "sub swap-head", text: `${plural(entry.missing, "copy", "copies")} missing · ${swapLooksFor(entry)}` }),
    out ? el("p", { class: "note", text: `The ${listName("owned", true)} isn't short of it: it plays the copies you have, or something else instead.` }) : null,
    el("ul", { class: "swap-list" }, entry.candidates.map((c) => el("li", { class: "swap-row" },
      cardRow(c.card, { name: c.name, meta: swapCandidateMeta(c), viewerGroup: "deck-swaps",
        chips: !c.basic && !c.here ? [status("info", "On the way")] : [], caption: `${c.name} for ${entry.name}` }),
      el("p", { class: "sub swap-note", text: c.note.text })))),
    entry.more ? el("p", { class: "sub", text: `${plural(entry.more, "more card fits", "more cards fit")}; these are the closest.` }) : null]);
  if (editable && !out) {
    sheet.foot.append(el("a", { class: "btn", href: `${editHref(s.id, "owned")}&swap=${encodeURIComponent(entry.name)}`,
      text: `Swap into the ${listName("owned", true)}` }));
  }
}

/** "Swaps from the Planned list": the Play-now list's swaps and their notes, or null. */
function deckSwapsSection(data) {
  const found = data.swaps;
  if (data.version !== "owned" || !found || (!found.swaps.length && !found.unpaired.length)) return null;
  const s = data.summary;
  const rows = new Map(((data.owned && data.owned.rows) || []).map((r) => [r.name, r]));
  const coming = (name) => (rows.get(name) && rows.get(name).on_the_way > 0 ? [status("info", "On the way")] : []);
  const words = (swap) => (swap.using.length
    ? `${swap.using.map((u) => `${u.qty} ${u.name}`).join(" + ")} for ${swap.out_qty} ${swap.for}`
    : `${swap.out_qty} ${swap.for} out`);
  return el("section", { class: "deck-section deck-swaps", "aria-labelledby": "h-swaps" },
    el("h2", { id: "h-swaps", text: `Swaps from the ${listName("target", true)}` }),
    el("div", {}, found.swaps.map((swap) => {
      const card = (swap.using[0] && swap.using[0].card) || swap.card;
      return cardRow(card, { name: words(swap), meta: swap.note || "No note yet in Substitutes",
        chips: swap.using.flatMap((u) => coming(u.name)), viewerGroup: "deck-swaps", caption: words(swap) });
    })),
    found.unpaired.length ? el("p", { class: "sub",
      text: `Also in the ${listName("owned", true)}: ${found.unpaired.map((u) => `${u.qty} ${u.name}`).join(", ")}.` }) : null,
    canEditDeck(s) ? el("a", { class: "btn btn-quiet", href: `${editHref(s.id, "owned")}&tab=notes`, text: "Edit notes" }) : null);
}
