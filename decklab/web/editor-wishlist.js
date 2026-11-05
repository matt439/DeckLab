/* Deck Lab's editor: the signed-in person's own wishlist as a scope of the Add panel (E5-S30;
lib/api/wishlist_ideas.py).

Loaded directly after editor-edhrec.js, whose pattern it follows: a saved casual or Commander deck's Add panel
(never a product's or pairing's), or a new deck's, has a "My wishlist" tick when a profile is chosen, and while
it's on the results are that profile's own wishlist cards that fit the deck (GET /api/deck/wishlist, asked once
per editor, deck revision, profile, kind and draft commander), in the wishlist's order: in a Commander deck,
those inside the draft commander's colour identity and legal in Commander. The typed name and the colour, type
and mana value filters narrow them here; cards already in the draft (any section but the sideboard) are left
out. Each is marked free, in use or to buy as the EDHREC ideas are, only when the server sent marks (a viewer
who may see the deck's space's inventory). A card added keeps its wished printing when one was chosen (the
line's printing; none otherwise, so Save gives it one), as one change and one Undo step; nothing is saved
until the usual Save. Nobody else's wishlist is ever asked for: the server reads only the viewer's own. */
"use strict";

const WISHLIST_PAGE = 24;       // wished cards shown at once (More shows the next)

/** A saved casual or Commander deck (never a product or pairing), or a new deck, with a profile chosen. */
function editorWishlistOffered(ed) {
  if (!ed || !ed.profile) return false;
  if (ed.mode === "new") return Boolean(ed.fields && ["casual", "commander"].includes(ed.fields.kind));
  return Boolean(ed.mode === "edit" && ed.id && !/^(product|pairing)\//.test(ed.id)
    && ["casual", "commander"].includes(ed.kind));
}

/** The deck's kind as the draft has it. */
function editorWishlistKind(ed) { return (ed.fields && ed.fields.kind) || ed.kind; }

/** The draft commander(s) a Commander deck's wished cards are filtered by; none for a casual one. */
function editorWishlistCommanders(ed) {
  return editorWishlistKind(ed) === "commander" ? editorEdhrecCommanders(ed).slice(0, 2) : [];
}

/** What makes the wished cards shown out of date when the draft changes: the kind and the commander. */
function editorWishlistDraftKey(ed) {
  return JSON.stringify([editorWishlistOffered(ed), editorWishlistKind(ed), editorWishlistCommanders(ed)]);
}

/** The answer belongs to one deck revision (or a new deck's space), profile, route, list, kind and commander. */
function editorWishlistKey(ac) {
  const ed = ac.owner;
  return JSON.stringify([ed.mode, ed.mode === "new" ? null : ed.id, ed.mode === "new" ? ed.space || null : null,
    ed.profile, ac.token, ed.sha256 || null, editorSearchScope(ac), editorWishlistKind(ed), editorWishlistCommanders(ed)]);
}

/** The wished cards' address: a saved deck by its id, a new one by its kind and the space it's being made in. */
function editorWishlistPath(ed) {
  const params = new URLSearchParams();
  if (ed.mode === "new") {
    params.set("kind", editorWishlistKind(ed));
    if (ed.space) params.set("space", ed.space);
  } else params.set("id", ed.id);
  const [first, second] = editorWishlistCommanders(ed);
  if (first) params.set("commander", first);
  if (second) params.set("commander2", second);
  return `/api/deck/wishlist?${params}`;
}

/** The Add panel's "My wishlist" tick (null when the deck has none to offer). */
function editorWishlistToggle(ac) {
  if (!editorWishlistOffered(ac.owner)) return null;
  return el("label", { class: "choice ac-wishlist", title: "The cards on your own wishlist that fit this deck" },
    el("input", { type: "checkbox", checked: ac.mode === "wishlist" || null, onchange: (e) => {
      ac.mode = e.target.checked ? "wishlist" : "search";
      refilter(ac);
      const again = ac.filters.querySelector(".ac-wishlist input");
      if (again) again.focus();
    } }), "My wishlist");
}

/** The draft changed: when the commander or the kind did, the wished cards shown are looked at again. */
function editorWishlistDraftChanged(ac) {
  if (!ac || ac.mode !== "wishlist" || ac.wishlistDraft == null || ac.wishlistDraft === editorWishlistDraftKey(ac.owner)) return;
  ac.wishlistDraft = null;
  setTimeout(() => {
    if (editorSearchCurrent(ac) && ac.mode === "wishlist") refilter(ac);
  }, 0);
}

/** The server's answer for this editor, asked once (a failure is kept until Try again). */
function editorWishlistAnswer(ac) {
  const key = editorWishlistKey(ac);
  if (!ac.wishlist || ac.wishlist.key !== key) {
    const promise = api(editorWishlistPath(ac.owner));
    promise.catch(() => {});        // whoever waits for it says what went wrong
    ac.wishlist = { key, promise };
  }
  return ac.wishlist;
}

/** One wished card as a search result: its card's data, its wished printing as the default, and the row. */
function editorWishlistItem(row, marks, answer = null) {
  const printing = row.set && row.number ? { set: row.set, number: row.number, finish: "nonfoil" } : null;
  return { ...(row.card || { type_line: "" }), name: row.name, default: printing, wish: { row, marks, answer } };
}

/** A result's side: its wished printing, then (with marks) whether a copy is free, all in other decks or to
 * buy, and copies on the way. */
function editorWishlistSide(c) {
  const { row, marks, answer } = c.wish;
  const out = [row.set ? el("span", { class: "ac-price", text: `${row.set.toUpperCase()} ${row.number}`,
    title: "The printing on your wishlist, which the line keeps" }) : null];
  if (marks) {
    if (row.status === "free") out.push(el("span", { class: "chip chip-good", text: `${num(row.free)} free` }));
    else if (row.status === "in_use") out.push(el("span", { class: "chip chip-plain", text: "In other decks",
      title: "Owned, but every copy is in another deck" }));
    else if (row.status === "in_deck") out.push(el("span", { class: "chip chip-plain", text: "In the saved deck" }));
    else if (row.status === "to_buy") out.push(el("span", { class: "chip chip-warn",
      text: row.aud_each != null ? `To buy · ~${ansMoney(row.aud_each, answer)}` : "To buy · no price" }));
    if (row.on_the_way) out.push(el("span", { class: "chip chip-info", text: `${num(row.on_the_way)} on the way` }));
  }
  return out;
}

/** What the wished cards are, above the results; hidden in the other scopes. */
function drawEditorWishlistNote(ac, answer = null, inDeck = 0) {
  const note = ac.note;
  if (!note || ac.mode !== "wishlist") return;
  if (!answer) { clear(note); note.hidden = true; return; }
  const marks = Boolean(answer.marks);
  const fit = answer.kind === "commander"
    ? answer.identity == null ? "No commander yet, so every colour is listed."
      : `Only cards in the commander's colour identity and legal in Commander are listed.`
    : null;
  const rate = marks && answer.price_error ? `No prices: ${answer.price_error}`
    : marks && answer.rate != null ? estimateRateWords(answer) : null;
  add(clear(note), [
    el("p", { class: "sub", text: "From your own wishlist, in its order." + (fit ? ` ${fit}` : "") }),
    answer.left_out ? el("p", { class: "sub", text: `${plural(answer.left_out, "wished card")} ${answer.left_out === 1 ? "doesn't" : "don't"} fit this deck.` }) : null,
    marks ? null : el("p", { class: "sub", text: "This deck's collection isn't yours to see, so nothing here says what's owned." }),
    rate ? el("p", { class: "sub", text: rate }) : null,
    inDeck ? el("p", { class: "sub", text: `${plural(inDeck, "wished card")} already in this draft ${inDeck === 1 ? "isn't" : "aren't"} listed.` }) : null]);
  note.hidden = false;
}

/** No results: an empty wishlist, everything's in the draft already, or nothing fits the text and filters. */
function editorWishlistEmpty(ac) {
  return ac.query ? `No wished cards with “${ac.query}” in their name fit these filters.`
    : filterCount(ac) ? "No wished cards fit these filters."
      : ac.wishlistTotal ? "Every wished card that fits this deck is in this draft already."
        : "No card on your wishlist fits this deck.";
}

/** editor-cards.js lookUp's wishlist scope: the answer (asked once), narrowed here to the typed name and the
 * filters, a page at a time. */
async function editorWishlistLookUp(ac, q, more = false) {
  if (!editorSearchCurrent(ac) || (more && ac.morePending)) return;
  const ed = ac.owner;
  if (!editorWishlistOffered(ed)) { ac.mode = "search"; refilter(ac); return; }
  const seq = ++ac.seq;
  const scope = editorSearchScope(ac);
  const typed = () => parseQuery(ac.input.value).q;
  const asked = editorWishlistAnswer(ac);
  ac.wishlistDraft = editorWishlistDraftKey(ed);
  const current = () => editorSearchCurrent(ac) && seq === ac.seq && typed() === q && scope === editorSearchScope(ac)
    && ac.mode === "wishlist" && ac.wishlist === asked && asked.key === editorWishlistKey(ac);
  if (more) { ac.morePending = true; ac.more.setAttribute("aria-disabled", "true"); }
  if (!ac.items.length) listMessage(ac, "Reading your wishlist…", { kind: "loading" });
  let answer;
  try {
    answer = await asked.promise;
  } catch (e) {
    if (!current()) return;
    ac.items = [];
    drawEditorWishlistNote(ac);
    const again = !(e && (e.status === 400 || e.status === 403 || e.status === 404));
    listMessage(ac, `Your wishlist couldn't be loaded. ${(e && e.message) || ""}`.trim(), { kind: "problem",
      action: again ? el("button", { type: "button", class: "btn btn-quiet", text: "Try again", onclick: () => {
        if (!editorSearchCurrent(ac) || ac.mode !== "wishlist") return;
        ac.wishlist = null;
        schedule(ac, 0);
        ac.input.focus({ preventScroll: true });
      } }) : null });
    return;
  }
  if (!current()) return;
  const marks = Boolean(answer.marks);
  const inDraft = editorEdhrecInDraft(ed);
  const all = answer.cards || [];
  ac.wishlistTotal = all.length;
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const fits = all.filter((row) => !inDraft.has(row.name) && words.every((w) => row.name.toLowerCase().includes(w))
    && editorEdhrecFits(ac, row.card));
  // More shows the next wished cards not shown yet (an add between pages changes what fits).
  const shown = new Set(more ? ac.items.map((c) => c.name) : []);
  const rest = fits.filter((row) => !shown.has(row.name));
  const next = rest.slice(0, WISHLIST_PAGE).map((row) => editorWishlistItem(row, marks, answer));
  if (!more) ac.page = 1;
  ac.items = more ? [...ac.items, ...next] : next;
  ac.guessFrom = -1;
  ac.resultScope = scope;
  ac.query = q;
  ac.count = parseQuery(ac.input.value).n;
  ac.pages = ac.page + (rest.length > next.length ? 1 : 0);
  resetSearchMore(ac);
  ac.active = more ? ac.active : ac.items.length ? 0 : -1;
  drawEditorWishlistNote(ac, answer, all.filter((row) => inDraft.has(row.name)).length);
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
