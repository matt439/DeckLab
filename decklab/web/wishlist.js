/* Each person's saved card wishlist. Available on phones as well as desktops.
 * A wishlist is private: the page shows only the chosen profile's own list, and the server
 * answers 403 to anyone else (lib/api/guard.py's require_sees_wishlist), an admin included.
 * All reads and writes stay tied to the person and page that started them.
 *
 * The list is a grid of card tiles (cards-ui.js cardTile). A tap opens the card's sheet: its picture (Zoom
 * opens the card viewer over the whole list, to swipe through), its notes, printing and source to change
 * ("set"), and Remove at the bottom, which happens at once with an Undo toast that puts the card back with
 * its notes, printing and source at its old place. A source naming a deck shows as the deck's title, linked. */
"use strict";

const WISH_NOTES_MAX = 2000;        // the store's limits (lib/state/rules.py)
const WISH_SOURCE_MAX = 300;

async function showWishlist(token) {
  const profile = state.profile;
  setTitle(`${profile.name}'s wishlist`);
  const main = clear($("#main"));
  main.append(loadingBox("Loading your wishlist…"));
  const current = () => token === routeToken && state.profile && state.profile.id === profile.id;
  try {
    const data = await api(`/api/profiles/${encodeURIComponent(profile.id)}/wishlist`);
    if (!current()) return;
    clear(main);
    drawWishlist(data, profile, token);
    afterRender();
  } catch (error) {
    if (!current()) return;
    clear(main).append(errorBox("Your wishlist couldn't be loaded", error));
    afterRender();
  }
}

function wishlistActive(view) {
  return view.token === routeToken && state.profile && state.profile.id === view.profile.id
    && view.root.isConnected;
}

function drawWishlist(data, profile, token) {
  const root = el("div", { class: "wishlist-page" });
  const view = { root, profile, token, data, busy: false, searchSeq: 0, timer: 0, matches: [] };
  const input = el("input", { id: "wishlist-search", class: "search-input", type: "search",
    placeholder: "Find a card to add", autocomplete: "off", autocorrect: "off", autocapitalize: "none",
    spellcheck: "false", enterkeyhint: "search", maxlength: 100 });
  view.input = input;
  view.searchStatus = el("p", { class: "result-count", role: "status", "aria-live": "polite" });
  view.searchResults = el("ul", { class: "wishlist-search-results", "aria-label": "Matching cards" });
  view.warnings = el("div");
  view.message = el("p", { class: "wishlist-message", role: "status", "aria-live": "polite" });
  view.count = el("h2", { id: "wishlist-cards-title", class: "wishlist-count", tabindex: "-1" });
  view.cards = el("div");
  const search = el("form", { class: "panel wishlist-search", role: "search", "aria-label": "Find a card to add",
    onsubmit: (event) => { event.preventDefault(); clearTimeout(view.timer); searchWishlist(view); } },
    el("label", { class: "field", for: input.id }, el("span", { class: "sr-only", text: "Card name" }), input),
    view.searchStatus, view.searchResults);
  input.addEventListener("input", () => {
    clearTimeout(view.timer);
    view.searchSeq += 1;
    view.matches = [];
    clear(view.searchResults);
    view.searchStatus.textContent = "";
    if (input.value.trim().length >= 2) view.timer = setTimeout(() => searchWishlist(view), 180);
  });
  add(root, [
    ...pageHead({ title: `${profile.name}'s wishlist`, description: "Cards you'd like. Only you see this list; changes save at once." }),
    view.warnings, search, view.message,
    el("section", { "aria-labelledby": "wishlist-cards-title" }, view.count, view.cards),
  ]);
  $("#main").append(root);
  updateWishlist(view);
  return view;
}

/** "2 owned · 1 on the way" in the profile's own space, without zeros; null when there's neither (or the
 * counts aren't known). */
function wishlistAvailability(have) {
  if (!have || have.owned == null || have.on_the_way == null) return null;
  return [have.owned ? `${have.owned} owned` : null, have.on_the_way ? `${have.on_the_way} on the way` : null]
    .filter(Boolean).join(" · ") || null;
}

/** An entry's source: the deck it names (its title, linked), or a buylist as "Suggested in Goblins upgrades ·
 * 2026-01-11" (plain words: repository paths aren't pages). leave: run before following the link. */
function wishlistSource(entry, leave = null) {
  const source = entry && entry.source;
  if (!source) return null;
  if (entry.source_deck) {
    return el("span", { class: "wishlist-source" }, "From ",
      el("a", { href: deckHref(entry.source_deck.id), text: entry.source_deck.title, onclick: leave }));
  }
  const filename = source.split("/").pop().replace(/\.md$/, "");
  const match = /^(\d{4}-\d{2}-\d{2})-(.+)$/.exec(filename);
  const label = match ? `${capitalise(match[2].replace(/-/g, " "))} · ${match[1]}` : filename;
  return el("span", { class: "wishlist-source", title: source, text: `Suggested in ${label}` });
}

function updateWishlist(view) {
  clear(view.warnings);
  const warning = warningsBox(view.data.warnings, "Some card details aren't available");
  if (warning) view.warnings.append(warning);
  const entries = view.data.entries || [];
  view.count.textContent = entries.length ? `${plural(entries.length, "card")}` : "Your wishlist";
  clear(view.cards);
  if (!entries.length) {
    view.cards.append(el("div", { class: "empty" }, el("p", { text: "Your wishlist is empty." }),
      el("button", { type: "button", class: "btn btn-primary", text: "Find a card to add", onclick: () => view.input.focus() })));
  } else {
    view.cards.append(el("div", { class: "card-tiles wishlist-grid" }, entries.map((entry) => wishlistTile(view, entry))));
  }
  drawWishlistSearch(view);
  setWishlistBusy(view, view.busy);
}

/** One wished-for card: its picture, how many you have (only when some), the deck or buylist it came from, and
 * its notes in the viewer. A tap opens its sheet. */
function wishlistTile(view, entry) {
  const card = entry.card;
  const have = wishlistAvailability(entry.have);
  const source = entry.source_deck ? el("a", { class: "chip chip-plain wishlist-deck-chip", href: deckHref(entry.source_deck.id),
    title: `From ${entry.source_deck.title}`, text: entry.source_deck.title }) : null;
  const tile = cardTile(card || null, { name: entry.name, meta: have,
    chips: [card ? null : status("warn", "Card details unavailable"), source].filter(Boolean),
    label: `${entry.name}${have ? `, ${have}` : ""}. Notes, printing and remove`,
    onclick: () => openWishlistSheet(view, entry) });
  tile.setAttribute("data-name", entry.name);
  const open = tile.querySelector(".card-tile-open");
  if (open) {
    open.setAttribute("class", `${open.getAttribute("class")} wishlist-mutate`);
    // The sheet's Zoom opens the viewer over the whole list, in page order.
    if (card) viewerItem(open, card, "wishlist", [entry.notes, have].filter(Boolean).join(" · ") || null);
  }
  return tile;
}

function setWishlistBusy(view, busy) {
  view.busy = busy;
  view.root.setAttribute("aria-busy", String(busy));
  for (const button of view.root.querySelectorAll(".wishlist-mutate")) {
    button.disabled = busy || button.dataset.present === "true";
  }
}

/** A card's sheet: its picture (Zoom), notes, printing and source, Save, and Remove at the bottom. */
function openWishlistSheet(view, entry) {
  if (!wishlistActive(view) || view.busy) return null;
  const sheet = openSheet({ title: entry.name, wide: true });
  const id = (key) => `wish-${key}-${sheet.heading.id}`;
  const ctx = { sheet, printing: entry.set ? { set: entry.set, number: entry.number } : null };
  const notes = el("textarea", { id: id("notes"), rows: 3, maxlength: WISH_NOTES_MAX, text: entry.notes || "" });
  notes.value = entry.notes || "";
  const source = el("input", { id: id("source"), type: "text", maxlength: WISH_SOURCE_MAX, value: entry.source || "",
    autocomplete: "off", spellcheck: "false", placeholder: "A deck or buylist path, or leave blank" });
  const printingWords = el("span", { class: "wishlist-printing-words" });
  const sayPrinting = () => {
    printingWords.textContent = ctx.printing && ctx.printing.set
      ? `${ctx.printing.set.toUpperCase()} ${ctx.printing.number}${ctx.printing.set_name ? ` · ${ctx.printing.set_name}` : ""}`
      : "Any printing (the picture is a usual one)";
  };
  sayPrinting();
  const message = el("div", { class: "wishlist-sheet-message", role: "status", "aria-live": "polite" });
  const zoom = () => {
    // openCard opens the viewer over the tile's group (the whole list), at this card.
    const tile = [...view.cards.querySelectorAll(".card-tile")].find((t) => t.dataset.name === entry.name);
    sheet.close();
    if (entry.card) openCard(entry.card, tile ? tile.querySelector(".card-tile-open") : null);
  };
  const leave = () => sheet.close();
  add(sheet.body, [el("div", { class: "wishlist-sheet" }, message,
    el("div", { class: "wishlist-sheet-top" },
      entry.card && entry.card.img_small ? el("button", { type: "button", class: "wishlist-sheet-pic", "aria-label": `Zoom: ${entry.name}`, onclick: zoom },
        el("img", { src: entry.card.img_small, alt: "", width: 146, height: 204 })) : null,
      el("div", { class: "wishlist-sheet-facts" },
        entry.card ? el("p", { class: "sub", text: entry.card.type_line }) : null,
        el("p", { text: wishlistAvailability(entry.have) || "None in your collection yet" }),
        wishlistSource(entry, leave))),
    el("label", { class: "field", for: notes.id }, el("span", { text: "Notes" }), notes),
    el("div", { class: "field wishlist-printing" }, el("span", { text: "Printing" }),
      el("div", { class: "wishlist-printing-row" }, printingWords,
        el("button", { type: "button", class: "btn", text: "Choose…", onclick: async () => {
          const picked = await pickPrinting(entry.name, { current: ctx.printing ? { ...ctx.printing, finish: "nonfoil" } : null,
            title: `${entry.name}: the printing you'd like` });
          if (!picked || sheet.closed) return;
          ctx.printing = picked.set ? { set: picked.set, number: picked.number, set_name: picked.set_name } : null;
          sayPrinting();
        } }))),
    el("label", { class: "field", for: source.id }, el("span", { text: "Source" }), source))]);
  const save = async () => {
    const body = { action: "set", name: entry.name };
    if (notes.value !== (entry.notes || "")) body.notes = notes.value;
    if (source.value.trim() !== (entry.source || "")) body.source = source.value.trim();
    const set = ctx.printing ? ctx.printing.set : "", number = ctx.printing ? ctx.printing.number : "";
    if (set !== (entry.set || "") || number !== (entry.number || "")) { body.set = set; body.number = number; }
    if (Object.keys(body).length === 2) { sheet.close(); return; }
    for (const button of sheet.foot.querySelectorAll("button")) button.disabled = true;
    clear(message).append(loadingBox("Saving…"));
    const done = await changeWishlist(view, body, `${entry.name} saved.`);
    if (sheet.closed) return;
    if (done === true) { sheet.close(); return; }
    clear(message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: done.error })));
    for (const button of sheet.foot.querySelectorAll("button")) button.disabled = false;
  };
  sheetActions(sheet, [
    { text: "Save", kind: "primary", value: "save", onclick: save },
    { text: "Remove", kind: "danger btn-quiet", value: "remove", onclick: () => { sheet.close(); removeWishlist(view, entry); } }]);
  return sheet;
}

/** Remove a card at once, with an Undo toast that adds it back with its notes, printing and source, at the
 * place it had in the list. */
async function removeWishlist(view, entry) {
  const at = (view.data.entries || []).findIndex((e) => e.name === entry.name);
  const done = await changeWishlist(view, { action: "remove", name: entry.name }, `${entry.name} removed.`, { quiet: true });
  if (done !== true) return;
  showToast(`${entry.name} removed from your wishlist.`, { undo: () => undoWishlistRemove(view, entry, at) });
}

/** The Undo of a removal. The toast outlives the page, so this sends the add itself, for the profile the
 * removal was made for, and redraws the list only when that page is still showing (and nothing else is
 * being saved there); either way a toast says what happened. */
async function undoWishlistRemove(view, entry, at = -1) {
  const body = { profile: view.profile.id, action: "add", name: entry.name };
  if (at >= 0) body.at = at;              // its old place (the store puts it there; past the end appends)
  if (entry.set) { body.set = entry.set; body.number = entry.number; }
  if (entry.notes) body.notes = entry.notes;
  if (entry.source) body.source = entry.source;
  try {
    const answer = await apiWrite(`/api/profiles/${encodeURIComponent(view.profile.id)}/wishlist`, body);
    const words = `${entry.name} is back on your wishlist.`;
    if (wishlistActive(view) && !view.busy) {
      view.data = answer;
      updateWishlist(view);
      view.message.textContent = words;
    }
    toast(words);
  } catch (error) {
    toast(`${entry.name} couldn't be put back: ${error.message}`);
  }
}

/** Send one change (body without the profile: add, remove or set); on success show the new list and say
 * words (opts.quiet: no toast, the caller shows its own). Resolves true when it was saved, else
 * {error} with the reason to show. */
async function changeWishlist(view, body, words, opts = {}) {
  if (!wishlistActive(view)) return { error: "This wishlist isn't showing any more. Open it again to make the change." };
  if (view.busy) return { error: "Another change is still being saved. Try again in a moment." };
  const trigger = document.activeElement;
  setWishlistBusy(view, true);
  view.message.textContent = body.action === "add" ? `Adding ${body.name}…` : body.action === "remove"
    ? `Removing ${body.name}…` : `Saving ${body.name}…`;
  try {
    const answer = await apiWrite(`/api/profiles/${encodeURIComponent(view.profile.id)}/wishlist`,
      { profile: view.profile.id, ...body });
    if (!wishlistActive(view)) return { error: "This wishlist isn't showing any more." };
    // Removing a card halfway down a long list keeps its neighbour in the same place.
    const before = [...view.cards.querySelectorAll(".card-tile")];
    const removed = body.action === "remove" ? before.findIndex((item) => item.dataset.name === body.name) : -1;
    const neighbour = removed >= 0 && (before[removed + 1] || before[removed - 1]);
    const anchor = neighbour && { name: neighbour.dataset.name, top: neighbour.getBoundingClientRect().top };
    view.data = answer;
    view.busy = false;
    updateWishlist(view);
    view.message.textContent = words;
    if (!opts.quiet) toast(words);
    const next = anchor && [...view.cards.querySelectorAll(".card-tile")].find((item) => item.dataset.name === anchor.name);
    if (next) window.scrollBy(0, next.getBoundingClientRect().top - anchor.top);
    // Repainting removes what had the focus: keep keyboard and screen-reader users on this task.
    if (!trigger || !trigger.isConnected || trigger === document.body) {
      const focus = body.action === "add" && view.matches.length ? view.input
        : (next && next.querySelector(".card-tile-open")) || view.count;
      focus.focus({ preventScroll: true });
    }
    return true;
  } catch (error) {
    const words = `The change couldn't be saved: ${error.message} Try again.`;
    if (!wishlistActive(view)) return { error: words };
    view.message.textContent = words;
    toast(words);
    return { error: words };
  } finally {
    if (wishlistActive(view)) setWishlistBusy(view, false);
  }
}

async function searchWishlist(view) {
  if (!wishlistActive(view)) return;
  const query = view.input.value.trim(), seq = ++view.searchSeq;
  if (query.length < 2) return;
  view.matches = [];
  clear(view.searchResults);
  view.searchStatus.textContent = "Looking up cards…";
  const current = () => wishlistActive(view) && seq === view.searchSeq && view.input.value.trim() === query;
  try {
    const answer = await api(`/api/cards/search?q=${encodeURIComponent(query)}&limit=8&detail=1`);
    if (!current()) return;
    view.matches = answer.cards || [];
    drawWishlistSearch(view);
    view.searchStatus.textContent = view.matches.length
      ? `${plural(view.matches.length, "matching card")}. Tap a picture to see it big.`
      : "No cards found. Try another name or a shorter spelling.";
  } catch (error) {
    if (current()) view.searchStatus.textContent = `The search didn't work: ${error.message} Try searching again.`;
  }
}

function drawWishlistSearch(view) {
  const saved = new Set((view.data.entries || []).map((entry) => entry.name));
  clear(view.searchResults);
  for (const card of view.matches) {
    const present = saved.has(card.name);
    view.searchResults.append(el("li", { class: "wishlist-search-card" },
      cardRow(card, { qty: null, viewerGroup: "wishlist-search", aside: null }),
      el("button", { type: "button", class: "btn wishlist-mutate",
        text: present ? "Added" : "Add",
        disabled: present || view.busy, "data-present": String(present),
        "aria-label": present ? `${card.name} is already on your wishlist` : `Add ${card.name} to your wishlist`,
        onclick: () => {
          const body = { action: "add", name: card.name };
          if (card.default) { body.set = card.default.set; body.number = card.default.number; }
          changeWishlist(view, body, `${card.name} is on your wishlist.`);
        } })));
  }
}
