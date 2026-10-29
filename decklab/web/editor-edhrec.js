/* Deck Lab's editor: EDHREC ideas as a scope of the Add panel (E9-S07; lib/api/edhrec.py).

Loaded directly after editor-cards.js, whose search shows them: a saved Commander deck's Add panel has an
"EDHREC ideas" tick beside My collection, and while it's on the results are the commander's commonly played
cards from EDHREC (GET /api/deck/edhrec, the deck page's answer, asked once per editor, deck revision,
profile and draft commander), in EDHREC's order, each with its share of decks. The typed name and the colour, type and mana value
filters narrow them here, on the page; cards already in the draft (any section but the sideboard) are left
out. A result adds to the draft's chosen section as a search result does (editor-cards.js pick and addCard:
one change, one Undo step), and nothing is saved until the usual Save.

The ideas are the draft's commander's: its Commander section's one or two cards are sent as commander and
commander2, so a changed or not yet saved commander needs no save first (the marks are still the saved
deck's, worked out on the server). A draft with no commander, or more than two, asks nothing and says why. Marks (free, in use, to buy
with its AUD estimate, on the way) come only when the server sent them (a viewer who may see the deck's
space's inventory) and never name a deck. An answer for another deck, revision, profile, route or list, or
one that comes after the search moved on, is ignored. EDHREC's own words for a failure are shown in the
results, and the rest of the editor keeps working. deck-edhrec.js's edhrecSourceLine says where they came
from and when they were fetched. */
"use strict";

const EDHREC_PAGE = 24;         // ideas shown at once (More shows the next)

/** Only a saved Commander deck (never a product or pairing): the server reads its saved commander. */
function editorEdhrecOffered(ed) {
  return Boolean(ed && ed.mode === "edit" && ed.id && !/^(product|pairing)\//.test(ed.id)
    && ed.kind === "commander" && ((ed.fields && ed.fields.kind) || ed.kind) === "commander");
}

/** The draft's commander(s), sorted, to compare with the answer's. */
function editorEdhrecCommanders(ed) {
  return [...new Set(((ed.lists && ed.lists.Commander) || []).map((line) => line.name))].sort();
}

/** What makes shown ideas out of date when the draft changes: the scope offered and the commander. */
function editorEdhrecDraftKey(ed) {
  return JSON.stringify([editorEdhrecOffered(ed), editorEdhrecCommanders(ed)]);
}

/** The answer belongs to one deck revision, profile, route, list and draft commander. */
function editorEdhrecKey(ac) {
  const ed = ac.owner;
  return JSON.stringify([ed.id, ed.profile, ac.token, ed.sha256 || null, editorSearchScope(ac), editorEdhrecCommanders(ed)]);
}

/** The Add panel's "EDHREC ideas" tick (null when the deck has none to offer). */
function editorEdhrecToggle(ac) {
  if (!editorEdhrecOffered(ac.owner)) return null;
  return el("label", { class: "choice ac-edhrec", title: "What other decks with this commander commonly play, from EDHREC" },
    el("input", { type: "checkbox", checked: ac.mode === "edhrec" || null, onchange: (e) => {
      ac.mode = e.target.checked ? "edhrec" : "search";
      refilter(ac);
      const again = ac.filters.querySelector(".ac-edhrec input");
      if (again) again.focus();
    } }), "EDHREC ideas");
}

/** The draft changed: when the commander (or the format) did, the ideas shown are looked at again, after the
 * change that did it has finished drawing. */
function editorEdhrecDraftChanged(ac) {
  if (!ac || ac.mode !== "edhrec" || ac.edhrecDraft == null || ac.edhrecDraft === editorEdhrecDraftKey(ac.owner)) return;
  ac.edhrecDraft = null;
  setTimeout(() => {
    if (editorSearchCurrent(ac) && ac.mode === "edhrec") refilter(ac);
  }, 0);
}

/** The server's answer for this editor, asked once (a failure is kept until Try again). */
function editorEdhrecAnswer(ac) {
  const key = editorEdhrecKey(ac);
  if (!ac.edhrec || ac.edhrec.key !== key) {
    const [first, second] = editorEdhrecCommanders(ac.owner);
    const promise = api(`/api/deck/edhrec?id=${encodeURIComponent(ac.owner.id)}&commander=${encodeURIComponent(first)}`
      + (second ? `&commander2=${encodeURIComponent(second)}` : ""));
    promise.catch(() => {});        // whoever waits for it says what went wrong
    ac.edhrec = { key, promise };
  }
  return ac.edhrec;
}

/** The colour, type and mana value filters, as /api/deck/find applies them. */
function editorEdhrecFits(ac, card) {
  if (!card) return !ac.colors.size && !ac.type && ac.mv === "";
  if (ac.colors.size && (card.color_identity || []).some((c) => !ac.colors.has(c))) return false;
  if (ac.type && !String(card.type_line || "").split(" // ")[0].toLowerCase().split(/\s+/).includes(ac.type)) return false;
  if (ac.mv !== "") {
    const mv = Number(ac.mv);
    if (mv === 7 ? !(card.cmc >= 7) : card.cmc !== mv) return false;
  }
  return true;
}

/** Card names in the draft's deck (the commander, companion and 99; not the sideboard). */
function editorEdhrecInDraft(ed) {
  const names = new Set();
  for (const [section, lines] of Object.entries(ed.lists || {})) {
    if (section !== "Sideboard") for (const line of lines || []) names.add(line.name);
  }
  return names;
}

/** One idea as a search result: its card's data, no default printing (Save gives it one), and the idea. */
function editorEdhrecItem(row, marks) {
  return { ...(row.card || { type_line: "" }), name: row.name, default: null, edhrec: { row, marks } };
}

/** A result's side: its share of EDHREC's decks, then (with marks) whether a copy is free, all in other
 * decks or to buy, and copies on the way. */
function editorEdhrecSide(c) {
  const { row, marks } = c.edhrec;
  const out = [row.inclusion != null ? el("span", { class: "ac-price", text: `${row.inclusion}% of decks`,
    title: "The share of EDHREC's decks with this commander that play it" }) : null];
  if (marks) {
    if (row.status === "free") out.push(el("span", { class: "chip chip-good", text: `${num(row.free)} free` }));
    else if (row.status === "in_use") out.push(el("span", { class: "chip chip-plain", text: "In other decks",
      title: "Owned, but every copy is in another deck" }));
    else if (row.status === "in_deck") out.push(el("span", { class: "chip chip-plain", text: "In the saved deck" }));
    else if (row.status === "to_buy") out.push(el("span", { class: "chip chip-warn",
      text: row.aud_each != null ? `To buy · ~${aud(row.aud_each)}` : "To buy · no price" }));
    if (row.on_the_way) out.push(el("span", { class: "chip chip-info", text: `${num(row.on_the_way)} on the way` }));
  }
  if (row.considering) out.push(el("span", { class: "chip chip-outline", text: "Considering" }));
  return out;
}

/** Where the ideas came from and when, above the results; hidden in the other scopes. */
function drawEditorEdhrecNote(ac, answer = null, inDeck = 0) {
  const note = ac.note;
  if (!note) return;
  if (ac.mode !== "edhrec" || !answer) { clear(note); note.hidden = true; return; }
  const marks = Boolean(answer.marks);
  const rate = marks && answer.price_error ? `No prices: ${answer.price_error}`
    : marks && answer.rate != null ? `Estimates in AUD: Scryfall's cheapest non-foil printing at 1 USD = ${num(answer.rate, 4)} AUD (ECB rate of ${answer.rate_date}), prices pulled ${answer.price_date}.` : null;
  add(clear(note), [
    edhrecSourceLine(answer),
    answer.source && answer.source.stale ? el("p", { class: "box box-warn", text: answer.source.stale }) : null,
    marks ? null : el("p", { class: "sub", text: "This deck's collection isn't yours to see, so nothing here says what's owned." }),
    rate ? el("p", { class: "sub", text: rate }) : null,
    inDeck ? el("p", { class: "sub", text: `${plural(inDeck, "idea")} already in this draft ${inDeck === 1 ? "isn't" : "aren't"} listed.` }) : null]);
  note.hidden = false;
}

/** No results: everything's in the draft already, or nothing fits the text and filters. */
function editorEdhrecEmpty(ac) {
  return ac.query ? `No EDHREC ideas with “${ac.query}” in their name fit these filters.`
    : filterCount(ac) ? "No EDHREC ideas fit these filters." : "Every EDHREC idea is in this draft already.";
}

/** editor-cards.js lookUp's EDHREC scope: the answer (asked once), narrowed here to the typed name and the
 * filters, a page at a time. */
async function editorEdhrecLookUp(ac, q, more = false) {
  if (!editorSearchCurrent(ac) || (more && ac.morePending)) return;
  const ed = ac.owner;
  if (!editorEdhrecOffered(ed)) { ac.mode = "search"; refilter(ac); return; }
  const seq = ++ac.seq;
  const draft = editorEdhrecCommanders(ed);
  if (draft.length < 1 || draft.length > 2) {
    // Nothing to ask EDHREC about: the draft names no commander, or more than a pair.
    ac.items = [];
    ac.edhrecDraft = editorEdhrecDraftKey(ed);
    drawEditorEdhrecNote(ac);
    listMessage(ac, draft.length ? `EDHREC ideas are for one commander or a pair, and this draft's Commander section has ${draft.length}.`
      : "Put a commander in the Commander section to see EDHREC's ideas for it.");
    return;
  }
  const scope = editorSearchScope(ac);
  const typed = () => parseQuery(ac.input.value).q;
  const asked = editorEdhrecAnswer(ac);
  ac.edhrecDraft = editorEdhrecDraftKey(ed);       // the commander changing while EDHREC is asked asks again
  const current = () => editorSearchCurrent(ac) && seq === ac.seq && typed() === q && scope === editorSearchScope(ac)
    && ac.mode === "edhrec" && ac.edhrec === asked && asked.key === editorEdhrecKey(ac);
  if (more) { ac.morePending = true; ac.more.setAttribute("aria-disabled", "true"); }
  if (!ac.items.length) listMessage(ac, "Asking EDHREC…", { kind: "loading" });
  let answer;
  try {
    answer = await asked.promise;
  } catch (e) {
    if (!current()) return;
    ac.items = [];
    ac.edhrecDraft = editorEdhrecDraftKey(ed);     // another commander asks again
    drawEditorEdhrecNote(ac);
    const again = !(e && (e.status === 400 || e.status === 404));
    listMessage(ac, `EDHREC ideas couldn't be loaded. ${(e && e.message) || ""}`.trim(), { kind: "problem",
      action: again ? el("button", { type: "button", class: "btn btn-quiet", text: "Try again", onclick: () => {
        if (!editorSearchCurrent(ac) || ac.mode !== "edhrec") return;
        ac.edhrec = null;
        schedule(ac, 0);
        ac.input.focus({ preventScroll: true });
      } }) : null });
    return;
  }
  if (!current()) return;
  ac.edhrecDraft = editorEdhrecDraftKey(ed);
  const marks = Boolean(answer.marks);
  const inDraft = editorEdhrecInDraft(ed);
  // A card EDHREC lists in two categories (its Top Cards and its type) is listed once, where it comes first.
  const all = [...new Map((answer.groups || []).flatMap((g) => g.cards).map((row) => [row.name, row])).values()];
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const fits = all.filter((row) => !inDraft.has(row.name) && words.every((w) => row.name.toLowerCase().includes(w))
    && editorEdhrecFits(ac, row.card));
  // More shows the next ideas not shown yet, not a fixed offset: adding one (or an Undo) between pages
  // changes what fits, and an offset would then skip an idea or show one twice.
  const shown = new Set(more ? ac.items.map((c) => c.name) : []);
  const rest = fits.filter((row) => !shown.has(row.name));
  const next = rest.slice(0, EDHREC_PAGE).map((row) => editorEdhrecItem(row, marks));
  if (!more) ac.page = 1;
  ac.items = more ? [...ac.items, ...next] : next;
  ac.guessFrom = -1;
  ac.resultScope = scope;
  ac.query = q;
  ac.count = parseQuery(ac.input.value).n;
  ac.pages = ac.page + (rest.length > next.length ? 1 : 0);
  resetSearchMore(ac);
  ac.active = more ? ac.active : ac.items.length ? 0 : -1;
  drawEditorEdhrecNote(ac, answer, all.filter((row) => inDraft.has(row.name)).length);
  if (ac.pickFirst && ac.items.length && ac.items[0].name.toLowerCase() === q.toLowerCase()) {
    const n = ac.pickCount;
    ac.pickFirst = false;
    ac.pickCount = null;
    drawOptions(ac);
    pick(ac, 0, n);
    return;
  }
  ac.pickFirst = false;
  drawOptions(ac);
}
