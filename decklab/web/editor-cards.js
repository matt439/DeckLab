/* Deck Lab's editor: getting cards into the list (Milestone 4; UI-REVIEW.md WP11).

Loaded after editor.js, editor-screen.js, editor-details.js and editor-lines.js, before editor-import.js,
editor-save.js and editor-deckpage.js. It holds the Add panel (the side panel's Add tab, or Quick edit's
search sheet): search, "My collection" and a Commander deck's "EDHREC ideas" (editor-edhrec.js), adding a
card and a line's printing sheet. Paste/replace
and a new deck's Start from workflows live in editor-import.js. It uses editor.js's constants, `editor`, lines, drafts and sheets,
editor-screen.js's changed(), editor-details.js's setField() and drawDetails(), and editor-lines.js's
section titles, steppers, moving and removing a line.

The search (GET /api/deck/find) shows a dozen cards with a line of rules text, the A$ estimate and how
many are owned: the name typed first, then the deck's space's cards, then whole-word matches. A click or
Enter on a result adds one copy and the result says "Added ✓ (now 3)"; Shift adds four, and a count typed
first ("4 bolt") adds that many. The results stay, with the text selected, so the next name can be typed
at once. "Free copies only" and the colour, type and mana value filters (folded under "Filters") narrow
it, and the filters alone browse every card; "My collection" lists the cards free for this deck in its
colours. Scryfall-style terms in the text search rules text (o:, oracle:) and type lines (t:, type:), each a
word or a quoted phrase, with the name words and filters (E2-S25); a term the server doesn't know comes
back as its own message, and no close spellings follow a search with terms. When few or no names have the typed text in them (and none is it), close spellings follow as
"Did you mean" cards. The thumbnails (or Alt+Enter) open the card viewer over the results. How to add is
a tip the first time, until "Got it", then the search box's tooltip.

Autocomplete on phones: the search box scrolls to the top of the screen when the on-screen keyboard
comes up, and the results are sized to what the keyboard leaves (window.visualViewport); the bar at the
bottom makes room only while the keyboard is up (noteKeyboard, which compares with the tallest screen
seen, so a keyboard already up for another box counts too). A tap on a result doesn't take the focus
away, so the keyboard stays up for the next card. The screen's size is first read while this file loads
(fullHeight, fullWidth and the visualViewport listeners), so viewHeight() and viewWidth() come before
that code, in this file.
*/
"use strict";

const SEARCH_DELAY = 150;       // ms after the last keystroke before names are looked up
const SEARCH_MIN = 2;           // characters before names are looked up
const SEARCH_LIMIT = 12;        // results shown at once
const GUESS_LIMIT = 3;          // "Did you mean" cards shown after few or no matches
const SHIFT_COPIES = 4;         // Shift+click or Shift+Enter adds this many
const ADDED_MS = 1800;          // how long a result says "Added ✓"
const FIND_TYPES = [["", "Any type"], ["creature", "Creature"], ["instant", "Instant"], ["sorcery", "Sorcery"],
  ["artifact", "Artifact"], ["enchantment", "Enchantment"], ["planeswalker", "Planeswalker"], ["land", "Land"],
  ["battle", "Battle"]];


// Adding cards -----------------------------------------------------------------

/** The Add tab: Add to (the section), the search with its filters and results, and Paste a list. */
function addPart(onPaste = editorSearchPaste) {
  const ed = editor;
  ed.dom.addTo = el("div", { class: "segmented", role: "group", "aria-label": "Add cards to" });
  const part = el("section", { class: "edit-add", id: "edit-add", "aria-label": "Add cards" },
    el("div", { class: "add-to" }, el("span", { class: "add-to-label", text: "Add to" }), ed.dom.addTo),
    cardSearch(),
    el("div", { class: "add-paste" },
      el("button", { type: "button", class: "btn btn-quiet", text: "Paste a list…", onclick: onPaste })));
  drawAddTo();
  return part;
}

function drawAddTo() {
  const ed = editor;
  if (!ed.dom.addTo) return;
  const focused = document.activeElement && ed.dom.addTo.contains(document.activeElement)
    ? document.activeElement.dataset.focus : null;
  clear(ed.dom.addTo).append(...ed.sections.map((s) => el("button", { type: "button",
    "aria-pressed": String(ed.addSection === s), "data-focus": `addto:${s}`,
    onclick: () => { ed.addSection = s; drawAddTo(); queueDraft(); } }, sectionTitle(s))));
  const again = focused && ed.dom.addTo.querySelector(`[data-focus="${CSS.escape(focused)}"]`);
  if (again) again.focus({ preventScroll: true });
  syncEditorSearchQuantities(ed.ac);
}

/** "4 bolt" -> {n: 4, q: "bolt"}; "bolt" -> {n: null, q: "bolt"}. */
function parseQuery(text) {
  const t = String(text || "").trim();
  const m = /^(\d{1,2})\s*x?\s+(\S.*)$/i.exec(t);
  return m && Number(m[1]) >= 1 ? { n: Number(m[1]), q: m[2].trim() } : { n: null, q: t };
}

/** The deck's colours, for My collection: its commander's colour identity, else its spells' (not the
 * colours its lands could make: a land that adds any colour isn't five colours of cards). */
function deckColours() {
  try { return listStats().identity; } catch (e) { return []; }
}

/** A search belongs to one editor/route/profile. Only initial synchronous painting may precede mount. */
function editorSearchOwned(ac) {
  const ed = ac?.owner;
  return Boolean(ed && editor === ed && ed.ac === ac && !ac.cancelled && !ed.leaving
    && ac.token === routeToken && ac.profile === state.profile?.id && ac.profile === ed.profile);
}

function editorSearchCurrent(ac, painting = false) {
  const dock = ac?.owner?.dom?.searchDock;
  return editorSearchOwned(ac) && !ac.dockSuspended && (!dock || dock.ac !== ac || editorSearchDockCurrent(dock))
    && Boolean(ac.wrap?.isConnected || (painting && ac.initializing));
}

function editorSearchScope(ac) { return JSON.stringify([ac.owner.id, ac.owner.version, ac.owner.space]); }

function editorSearchResultsCurrent(ac) {
  return editorSearchCurrent(ac) && (!ac.resultScope || ac.resultScope === editorSearchScope(ac));
}

function cancelEditorSearch(ac) {
  if (!ac) return;
  ac.cancelled = true;
  ++ac.seq;
  ac.pickFirst = false; ac.pickCount = null;
  resetSearchMore(ac);
  clearTimeout(ac.timer); clearTimeout(ac.addedTimer);
}

function editorSearchActionCurrent(ac, card, index, target) {
  return editorSearchCanAct(ac) && editorSearchResultsCurrent(ac) && ac.items[index] === card && target?.isConnected && ac.list.contains(target)
    && ac.query === parseQuery(ac.input.value).q;
}

function resetSearchMore(ac) {
  ac.morePending = false;
  ac.more?.removeAttribute("aria-disabled");
  if (ac.more) ac.more.textContent = "More";
  if (ac.moreError) ac.moreError.hidden = true;
}

function cardSearch() {
  const ed = editor;
  cancelEditorSearch(ed.ac);
  const sees = seesInventory(ed.space || HOME_SPACE);
  const ac = { items: [], active: -1, seq: 0, timer: 0, query: "", count: null, pickFirst: false, pickCount: null,
    guessFrom: -1, mode: "search", owned: false, colors: new Set(), type: "", mv: "", page: 1, pages: 1, sees,
    filtersOpen: local.get("editFilters") === "open", owner: ed, token: routeToken, profile: ed.profile,
    cancelled: false, initializing: true, resultScope: null };
  ac.input = el("input", { type: "search", id: "ac-input", class: "search-input",
    "aria-controls": "ac-list", "aria-describedby": "ac-help", autocomplete: "off",
    autocorrect: "off", autocapitalize: "none", spellcheck: "false", enterkeyhint: "search",
    placeholder: "Card name, e.g. 4 bolt", "aria-keyshortcuts": keyboardCharactersEnabled(ed.profile) ? "/ Alt+Enter" : "Alt+Enter",
    title: "Enter or a click adds 1 copy; Shift adds 4; “4 bolt” adds 4. Alt+Enter shows the card big. o: searches rules text and t: the type line, as on Scryfall: o:treasure t:creature, o:\"draw a card\"." });
  ac.list = el("ul", { id: "ac-list", class: "ac-list", "aria-label": "Cards found", hidden: true });
  ac.live = el("p", { class: "sr-only", role: "status", "aria-live": "polite" });
  ac.more = el("button", { type: "button", class: "btn btn-quiet ac-more", hidden: true, text: "More",
    onclick: () => { if (editorSearchResultsCurrent(ac) && !ac.morePending && ac.page < ac.pages) { ac.page += 1; lookUp(ac, parseQuery(ac.input.value).q, true); } } });
  ac.moreError = el("p", { class: "ac-more-error sub", role: "status", hidden: true });
  ed.ac = ac;
  const input = (event) => {
    if (!editorSearchCurrent(ac) || event.defaultPrevented) return;
    clearTimeout(ac.timer);
    ac.seq += 1;
    ac.items = [];
    ac.active = -1;
    ac.query = "";
    ac.pickFirst = false;
    ac.resultScope = null;
    resetSearchMore(ac);
    ac.rendered = null; clear(ac.list); ac.list.hidden = true; ac.more.hidden = true;
    ac.page = 1;
    clearAdded(ac);
    markActive(ac);
    if (!event.isComposing && !ac.input.editorComposing) schedule(ac);
  };
  ac.input.addEventListener("input", input);
  editorComposition(ac.input, input);
  ac.input.addEventListener("keydown", (e) => searchKey(ac, e));
  ac.input.addEventListener("focus", () => {
    if (!editorSearchCurrent(ac)) return;
    document.body.classList.add("is-searching");
    noteKeyboard();
    keepSearchInView(ac);
  });
  ac.input.addEventListener("blur", () => {
    setTimeout(() => {
      if (!editorSearchCurrent(ac)) return;
      if (ac.wrap.contains(document.activeElement)) return;
      document.body.classList.remove("is-searching");
      const part = ac.wrap.closest && ac.wrap.closest(".edit-add");
      if (part && part.style) part.style.minHeight = "";
      noteKeyboard();
    }, 120);
  });
  // Add/Inspect keep the search keyboard; native quantity fields/buttons need their own focus.
  ac.list.addEventListener("mousedown", (e) => {
    if (editorSearchCurrent(ac) && !e.target.closest?.(".ac-stepper")) e.preventDefault();
  });
  ac.filters = el("div", { class: "ac-filters" });
  ac.note = el("div", { class: "ac-note", hidden: true });     // where EDHREC's ideas came from (editor-edhrec.js)
  ac.wrap = el("div", { class: "ac-wrap" },
    el("div", { class: "ac" }, el("label", { for: "ac-input", class: "sr-only", text: "Card name" }), ac.input),
    ac.filters, ac.note, addTip(), el("p", { id: "ac-help", class: "sr-only", text: "Arrow keys choose a result. Enter adds it; Shift adds four. Alt+Enter opens the card. Tab reaches each result action. o: searches rules text and t: the type line." }),
    ac.live, ac.list, ac.moreError, ac.more);
  drawSearchControls(ac);
  showResults(ac);
  ac.initializing = false;
  return ac.wrap;
}

/** The first time the Add panel shows (on this device): how adding works, until "Got it". */
function addTip() {
  if (local.get("editAddTip") === "seen") return null;
  const touch = window.matchMedia("(pointer: coarse)").matches;
  const tip = el("div", { class: "note ac-tip", role: "note" },
    el("p", { text: touch ? "Tap a card to add 1 copy; type “4 bolt” to add 4."
      : "Click or Enter adds 1 copy; Shift adds 4, and “4 bolt” adds 4." }),
    el("button", { type: "button", class: "btn btn-quiet", text: "Got it", onclick: () => {
      local.set("editAddTip", "seen");
      tip.remove();
      if (editor && editor.ac) editor.ac.input.focus();
    } }));
  return tip;
}

/** How many of the colour, type and mana value filters are set. */
function filterCount(ac) { return (ac.colors.size ? 1 : 0) + (ac.type ? 1 : 0) + (ac.mv !== "" ? 1 : 0); }

/** True when the results come from the filters (or My collection, EDHREC ideas or Free only), with or without a name. */
function browsing(ac) { return ac.mode === "collection" || ac.mode === "edhrec" || ac.owned || filterCount(ac) > 0; }

/** The search's filters on one row: My collection (a tick, not a second switch beside Add to's: every card
 * when it's off), Free only, then "Filters" (colours, type and mana value, folded away until opened). */
function drawSearchControls(ac) {
  const mine = ac.sees ? el("label", { class: "choice ac-mine", title: "Only the cards in your collection that are free for this deck" },
    el("input", { type: "checkbox", checked: ac.mode === "collection" || null, onchange: (e) => {
      ac.mode = e.target.checked ? "collection" : "search";
      // My collection starts in the deck's colours.
      if (ac.mode === "collection" && !ac.colors.size) deckColours().forEach((c) => ac.colors.add(c));
      refilter(ac);
      const again = ac.filters.querySelector(".ac-mine input");
      if (again) again.focus();
    } }), "My collection") : null;
  const colourButtons = "WUBRG".split("").map((c) => el("button", { type: "button", class: "ac-colour",
    "aria-pressed": String(ac.colors.has(c)), "aria-label": `Fits ${COLOUR_WORDS[c]}`, title: `Fits ${COLOUR_WORDS[c]}`,
    onclick: () => { if (ac.colors.has(c)) ac.colors.delete(c); else ac.colors.add(c); refilter(ac); } },
  symbolImg(c, { small: true, alt: "" })));
  const type = el("select", { class: "ac-select", "aria-label": "Card type",
    onchange: (e) => { ac.type = e.target.value; refilter(ac); } },
  FIND_TYPES.map(([value, label]) => el("option", { value, selected: ac.type === value || null, text: label })));
  const mv = el("select", { class: "ac-select", "aria-label": "Mana value",
    onchange: (e) => { ac.mv = e.target.value; refilter(ac); } },
  el("option", { value: "", text: "Any MV" }),
  [0, 1, 2, 3, 4, 5, 6, 7].map((n) => el("option", { value: n, selected: ac.mv === String(n) || null,
    text: n === 7 ? "MV 7+" : `MV ${n}` })));
  const n = filterCount(ac);
  const toggle = el("button", { type: "button", class: "btn btn-quiet ac-filter-toggle", "aria-expanded": String(ac.filtersOpen),
    "aria-controls": "ac-filter-more", onclick: () => {
      ac.filtersOpen = !ac.filtersOpen;
      local.set("editFilters", ac.filtersOpen ? "open" : "closed");
      drawSearchControls(ac);
      const again = ac.filters.querySelector(".ac-filter-toggle");
      if (again) again.focus();
    } }, n ? `Filters · ${n}` : "Filters", el("span", { class: "caret", "aria-hidden": "true" }));
  add(clear(ac.filters), [
    mine,
    editorEdhrecToggle(ac),
    ac.sees && ac.mode === "search" ? el("label", { class: "choice ac-owned",
      title: "Only cards with a copy free for this deck: owned or on the way, and not held by another built deck" },
    el("input", { type: "checkbox", checked: ac.owned || null,
      onchange: (e) => { ac.owned = e.target.checked; refilter(ac); } }), "Free copies only") : null,
    toggle,
    el("div", { class: "ac-filter-more", id: "ac-filter-more", hidden: !ac.filtersOpen || null },
      el("div", { class: "ac-colours", role: "group", "aria-label": "Colours the cards fit" }, colourButtons),
      type, mv)]);
  if (ac.mode !== "edhrec") drawEditorEdhrecNote(ac);
}

function refilter(ac) {
  if (!editorSearchCurrent(ac)) return;
  ac.page = 1;
  ac.seq += 1;
  ac.items = [];
  ac.active = -1;
  ac.resultScope = null;
  resetSearchMore(ac);
  ac.rendered = null; clear(ac.list); ac.list.hidden = true; ac.more.hidden = true;
  clearAdded(ac);
  drawSearchControls(ac);
  schedule(ac, 0);
}

/** Look the text up soon, or say what to type. */
function schedule(ac, delay = SEARCH_DELAY) {
  if (!editorSearchCurrent(ac, true)) return;
  clearTimeout(ac.timer);
  const { q } = parseQuery(ac.input.value);
  if (!browsing(ac) && q.length < SEARCH_MIN) {
    ac.seq += 1;
    ac.items = [];
    ac.query = "";
    showResults(ac);
    return;
  }
  ac.timer = setTimeout(() => lookUp(ac, q), delay);
}

/** /api/deck/find's address for the search as it is now. */
function findUrl(ac, q) {
  const ed = editor;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (ac.mode === "collection" || ac.owned) params.set("scope", "owned");
  if (ac.colors.size) params.set("colors", "WUBRG".split("").filter((c) => ac.colors.has(c)).join(""));
  if (ac.type) params.set("type", ac.type);
  if (ac.mv !== "") params.set("mv", ac.mv);
  params.set("limit", String(SEARCH_LIMIT));
  if (ac.page > 1) params.set("page", String(ac.page));
  if (ed && ed.mode === "edit" && ed.id) params.set("id", ed.id);
  else if (ed && ed.space) params.set("space", ed.space);
  return `/api/deck/find?${params}`;
}

async function lookUp(ac, q, more = false) {
  if (ac.mode === "edhrec") return editorEdhrecLookUp(ac, q, more);
  if (!editorSearchCurrent(ac) || (more && ac.morePending)) return;
  const seq = ++ac.seq;
  const scope = editorSearchScope(ac);
  const page = ac.page;
  if (more) { ac.morePending = true; ac.more.setAttribute("aria-disabled", "true"); }
  const typed = () => parseQuery(ac.input.value).q;
  if (!ac.items.length) listMessage(ac, "Looking up cards…", { kind: "loading" });
  try {
    const answer = await api(findUrl(ac, q));
    if (!editorSearchCurrent(ac) || seq !== ac.seq || typed() !== q || scope !== editorSearchScope(ac)) return;
    const found = answer.cards || [];
    // Few or no names have the text in them: the server's close spellings ("did_you_mean") come after
    // them, as cards to pick. Without any, what "Paste a list" makes of the text, which also covers a
    // server that doesn't send them.
    let guesses = [];
    if (q && !more && ac.mode === "search" && !ac.owned && !hasFindTerms(q)) {
      const shown = new Set(found.map((c) => c.name));
      const close = (answer.did_you_mean || []).filter((name) => !shown.has(name)).slice(0, GUESS_LIMIT);
      guesses = close.length ? await cardsNamed(close) : [];
      if (!found.length && !guesses.length) guesses = await closeCards(q);
      if (!editorSearchCurrent(ac) || seq !== ac.seq || typed() !== q || scope !== editorSearchScope(ac)) return;
    }
    const items = more ? [...ac.items, ...found] : [...found, ...guesses];
    if (!more) ac.guessFrom = guesses.length ? found.length : -1;      // where the "Did you mean" cards start
    ac.items = items;
    ac.resultScope = scope;
    ac.query = q;
    ac.count = parseQuery(ac.input.value).n;
    ac.pages = answer.pages || 1;
    resetSearchMore(ac);
    ac.active = more ? ac.active : ac.items.length ? 0 : -1;
    if (ac.pickFirst && ac.items.length && ac.items[0].name.toLowerCase() === q.toLowerCase()) {
      // Enter came before the answer: as many copies as Enter asked for then (Shift's 4, or a count typed).
      const n = ac.pickCount;
      ac.pickFirst = false;
      ac.pickCount = null;
      drawOptions(ac);
      pick(ac, 0, n);
      return;
    }
    ac.pickFirst = false;
    drawOptions(ac);
  } catch (e) {
    if (!editorSearchCurrent(ac) || seq !== ac.seq || typed() !== q || scope !== editorSearchScope(ac)) return;
    const words = e.status === 400 && e.data?.reason === "term" ? e.message
      : e.status === 503 && e.data?.reason === "off" ? e.message
      : e.status === 503 && e.data?.reason !== "database" ? "The card data isn't ready yet: try again in a minute."
      : `The search didn't work: ${e.message}`;
    if (more && ac.items.length) {
      resetSearchMore(ac); ac.page = Math.max(1, page - 1);
      ac.more.textContent = "Retry more"; ac.more.hidden = !(ac.page < ac.pages);
      ac.moreError.textContent = words; ac.moreError.hidden = false;
    } else {
      ac.items = [];
      listMessage(ac, words, { kind: "problem", action: el("button", { type: "button", class: "btn btn-quiet", text: "Try again",
        onclick: () => { if (editorSearchCurrent(ac)) { schedule(ac, 0); ac.input.focus({ preventScroll: true }); } } }) });
    }
  }
}

/** Whether the search text holds a rules-text or type-line term (o:, t:, E2-S25): its results are cards
 * that match them, so no close spellings of the text follow. */
function hasFindTerms(q) {
  return /(?:^|\s)(?:o|oracle|t|type):/i.test(q);
}

/** Cards the name search can't find but a close spelling can (a typo such as "lightnig bolt", "fire/ice",
 * "Æther Vial"): what "Paste a list" makes of the text as one decklist line (its name, or the names it
 * suggests), each with the search's details. [] if none. */
async function closeCards(q) {
  let parsed;
  try {
    parsed = await apiWrite("/api/decklist/parse", { text: /^\d+\s*x?\s+\S/i.test(q) ? q : `1 ${q}` });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return [];
  }
  const names = [];
  for (const lines of Object.values(parsed.sections || {})) for (const line of lines) names.push(line.name);
  for (const u of parsed.unknown || []) names.push(...(u.suggestions || []));
  return cardsNamed([...new Set(names)].slice(0, SEARCH_LIMIT));
}

/** The search's details (picture, cost, default printing, copies in the pool) of exact card names, in
 * their order; a name the search doesn't find is left out. */
async function cardsNamed(names) {
  const found = await Promise.all(names.map((name) =>
    api(`/api/cards/search?q=${encodeURIComponent(name)}&limit=8&detail=1`)
      .then((a) => (a.cards || []).find((c) => c.name === name) || null)
      .catch(() => null)));
  return found.filter(Boolean);
}

/** One line in place of the results: kind "loading" (a small spinner first) or "problem" (crit words), and at
 * most the one action that helps. The words also go to ac.live, the search's one live region (a line put
 * into the list isn't read out), and are taken back from it when results come (drawOptions). */
function listMessage(ac, text, { kind = "", action = null } = {}) {
  if (!editorSearchCurrent(ac, true)) return;
  ac.list.hidden = false;
  ac.rendered = null;
  resetSearchMore(ac);
  clear(ac.list).append(el("li", { class: "ac-message" + (kind ? ` ac-message-${kind}` : ""), role: "presentation" },
    kind === "loading" ? el("span", { class: "spinner spinner-small", "aria-hidden": "true" }) : null,
    el("span", { text }), action));
  ac.more.hidden = true;
  ac.live.textContent = ac.liveMessage = text;
}

/** The results; nothing (no empty box) until a name is typed or a filter is set. */
function showResults(ac) {
  if (!editorSearchCurrent(ac, true)) return;
  if (ac.items.length) { drawOptions(ac); return; }
  if (browsing(ac)) {
    listMessage(ac, ac.mode === "collection" ? "Looking through your collection…"
      : ac.mode === "edhrec" ? "Asking EDHREC…" : "Looking up cards…", { kind: "loading" });
    schedule(ac, 0);
    return;
  }
  clear(ac.list);
  ac.rendered = null;
  resetSearchMore(ac);
  ac.list.hidden = true;
  ac.more.hidden = true;
}

/** The "Added ✓" a result showed belongs to that search: a new one (typing, a filter, Escape) drops it. */
function clearAdded(ac) {
  ac.addedAt = null;
  clearTimeout(ac.addedTimer);
}

/** "Llanowar Elves" with the typed part marked: the text as typed, else each typed word where a word of
 * the name starts with it, in order ("llan elv"), else nothing. */
function highlight(name, q) {
  if (!q) return name;
  const i = name.toLowerCase().indexOf(q.toLowerCase());
  if (i >= 0) return [name.slice(0, i), el("mark", { text: name.slice(i, i + q.length) }), name.slice(i + q.length)];
  const lower = name.toLowerCase();
  const parts = [];
  let from = 0;
  for (const word of q.toLowerCase().split(/\s+/).filter(Boolean)) {
    let at = lower.indexOf(word, from);
    while (at > 0 && /[\p{L}\p{N}]/u.test(lower[at - 1])) at = lower.indexOf(word, at + 1);
    if (at < 0) return name;
    parts.push(name.slice(from, at), el("mark", { text: name.slice(at, at + word.length) }));
    from = at + word.length;
  }
  parts.push(name.slice(from));
  return parts;
}

/** A result's first line of rules text, symbols drawn, reminder text left out. */
function oracleLine(card) {
  const text = (card.oracle_text || (card.faces && card.faces[0] && card.faces[0].oracle_text) || "")
    .split("\n")[0].replace(/\s*\([^)]*\)/g, "");
  return text ? renderSymbols(text, { small: true }) : null;
}

/** The owned badge of a result: "2 free" (My collection), "3 owned" or "1 on the way". */
function ownedBadge(c) {
  if (c.free != null) return el("span", { class: "chip chip-good", text: `${c.free} free` });
  const have = c.have || {};
  if (have.owned) return el("span", { class: "chip chip-good", text: `${have.owned} owned` });
  if (have.on_the_way) return el("span", { class: "chip chip-info", text: `${have.on_the_way} on the way` });
  return null;
}

function searchResultSide(c, words = null) {
  if (words) return [el("span", { class: "ac-added", text: words })];
  if (c.edhrec) return editorEdhrecSide(c);
  return [c.aud != null ? el("span", { class: "ac-price", text: `A$${c.aud.toFixed(2)}` }) : null, ownedBadge(c)];
}

function drawOptions(ac) {
  if (!editorSearchCurrent(ac, true) || (ac.resultScope && ac.resultScope !== editorSearchScope(ac))) return;
  if (!ac.items.length) {
    listMessage(ac, ac.mode === "edhrec" ? editorEdhrecEmpty(ac) : ac.mode === "collection" || ac.owned
      ? (ac.query ? `None of your free cards have “${ac.query}” in their name with these filters.` : "No free cards with these filters.")
      : !ac.query ? "No cards fit these filters."
        : filterCount(ac) ? `No card names with “${ac.query}” in them fit these filters.`
          : `No card names have “${ac.query}” in them, and none are spelt close to it.`,
    { action: filterCount(ac) ? el("button", { type: "button", class: "btn btn-quiet", text: "Clear filters", onclick: () => {
      if (!editorSearchCurrent(ac)) return;
      ac.colors.clear(); ac.type = ""; ac.mv = "";
      refilter(ac);
      ac.input.focus({ preventScroll: true });
    } }) : null });
    return;
  }
  // Results came: a waiting or nothing-found line said through ac.live is over (an "added" one stays).
  if (ac.liveMessage && ac.live.textContent === ac.liveMessage) ac.live.textContent = "";
  ac.liveMessage = null;
  ac.list.hidden = false;
  ac.resultScope = editorSearchScope(ac);
  const prior = ac.rendered;
  const retained = prior && prior.query === ac.query && prior.scope === ac.resultScope && prior.cards.length <= ac.items.length
    && prior.cards.every((card, i) => card === ac.items[i]) && prior.nodes.every(node => ac.list.contains(node));
  if (!retained) { clear(ac.list); ac.rendered = { query: ac.query, scope: ac.resultScope, cards: [], nodes: [] }; }
  // "Added ✓" only on the card that was added, in the search it was added from.
  const added = ac.addedAt && ac.addedAt.query === ac.query ? ac.addedAt : null;
  ac.items.forEach((c, i) => {
    const isAdded = !!(added && added.i === i && added.name === c.name);
    const old = ac.rendered.nodes[i];
    if (old) {
      old.classList.toggle("is-added", isAdded);
      add(clear(old.querySelector(".ac-side")), searchResultSide(c, isAdded ? added.words : null));
      syncSearchQuantity(old.querySelector(".ac-actions").searchQuantity);
      return;
    }
    if (i === ac.guessFrom) {
      add(ac.list, [el("li", { class: "ac-message ac-guess", role: "presentation",
        text: i ? "Or did you mean:" : `No card names have “${ac.query}” in them. Did you mean:` })]);
    }
    const card = cardData(c);
    const thumb = c.img_small
      ? viewerItem(el("button", { type: "button", class: "ac-thumb-btn", title: "See it big", "aria-label": `See ${c.name} big`, "aria-haspopup": "dialog",
        onclick: (e) => { e.stopPropagation(); if (editorSearchActionCurrent(ac, c, i, e.currentTarget)) openCard(card, e.currentTarget); } },
      el("img", { class: "ac-thumb", src: c.img_small, alt: "", width: 40, height: 56, loading: "lazy", decoding: "async" })),
      card, "editor-results", c.type_line)
      : el("span", { class: "ac-thumb thumb-missing", "aria-hidden": "true" });
    const addButton = el("button", { type: "button", class: "ac-add", "aria-label": `Add ${c.name}`, "aria-describedby": `ac-type-${i} ac-side-${i}`,
      onclick: e => {
        if (e.currentTarget.hidden || !editorSearchActionCurrent(ac, c, i, e.currentTarget)) return;
        ac.active = i; markActive(ac); pick(ac, i, e.shiftKey ? SHIFT_COPIES : null);
      }, onfocus: () => { if (editorSearchResultsCurrent(ac)) { ac.active = i; markActive(ac); } } }, "Add");
    const facts = el("div", { class: "ac-result-facts" },
    el("span", { class: "ac-words" },
      el("span", { class: "ac-name" }, el("span", { class: "ac-name-text" }, highlight(c.name, ac.query)), manaCost(c.mana_cost, true)),
      // One line under the name: the type, then the start of the rules text (two-line results: more fit).
      el("small", { class: "ac-oracle", id: `ac-type-${i}` }, el("span", { class: "ac-type", text: c.type_line }),
        oracleLine(c) ? [" · ", oracleLine(c)] : null)),
    el("span", { class: "ac-side", id: `ac-side-${i}` }, searchResultSide(c, isAdded ? added.words : null)));
    const option = peekable(el("li", { id: `ac-opt-${i}`, class: "ac-option" + (isAdded ? " is-added" : ""), "data-i": i }, thumb, facts, searchQuantitySlot(ac, c, i, addButton)), card);
    ac.list.append(option);
    syncSearchQuantity(option.querySelector(".ac-actions").searchQuantity);
    ac.rendered.nodes.push(option);
  });
  ac.rendered.cards = ac.items.slice();
  const hideMore = !ac.morePending && !(ac.page < ac.pages);
  if (hideMore && document.activeElement === ac.more && editorSearchResultsCurrent(ac)
      && ![...document.querySelectorAll("dialog[open]")].some(dialog => !dialog.contains(ac.input))) ac.input.focus({ preventScroll: true });
  ac.more.hidden = hideMore;
  markActive(ac);
}

/** Alt+Enter: the active result's card, big, in the viewer over the results. */
function viewResult(ac) {
  if (!editorSearchResultsCurrent(ac) || ac.query !== parseQuery(ac.input.value).q) return;
  const option = ac.list.querySelector(`#ac-opt-${ac.active}`);
  const thumb = option && option.querySelector(".ac-thumb-btn");
  const c = ac.items[ac.active];
  if (!c) return;
  const addButton = option?.querySelector(".ac-add");
  const fallback = addButton?.hidden ? option.querySelector(".ac-actions").searchQuantity.qty : addButton;
  openCard(cardData(c), thumb || fallback);
}

/** Bring the active result into view inside the box that scrolls the results (the list, the side panel or the
 * sheet), never the page: a result coming up mustn't move the list being edited. */
function showInResults(option) {
  let box = option.parentElement;
  while (box && box !== document.body) {
    const style = getComputedStyle(box);
    if (/(auto|scroll)/.test(style.overflowY) && box.scrollHeight > box.clientHeight) break;
    box = box.parentElement;
  }
  if (!box || box === document.body) return;
  const b = box.getBoundingClientRect();
  const o = option.getBoundingClientRect();
  if (o.top < b.top) box.scrollTop -= b.top - o.top;
  else if (o.bottom > b.bottom) box.scrollTop += Math.min(o.bottom - b.bottom, o.top - b.top);
}

function markActive(ac, announce = false) {
  if (!editorSearchCurrent(ac, true)) return;
  ac.list.querySelectorAll(".ac-option").forEach((option, i) => {
    if (i === ac.active) option.setAttribute("aria-current", "true");
    else option.removeAttribute("aria-current");
    if (i === ac.active) {
      if (typeof getComputedStyle === "function" && option.getBoundingClientRect) showInResults(option);
      peekAt(option);
    }
  });
  if (announce && ac.items[ac.active]) ac.live.textContent = `Result ${ac.active + 1} of ${ac.items.length}: ${ac.items[ac.active].name}.`;
}

function searchKey(ac, e) {
  if (!editorSearchCurrent(ac) || editorKeyIgnored(e) || keyboardMenuOpen() || e.ctrlKey || e.metaKey) return;
  const open = ac.items.length > 0 && editorSearchResultsCurrent(ac);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (e.altKey || e.shiftKey || !open || !editorSearchCanAct(ac)) return;
    e.preventDefault();
    const n = ac.items.length;
    ac.active = (ac.active + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
    markActive(ac, true);
  } else if (e.key === "Enter" && e.altKey) {
    if (e.shiftKey) return;
    e.preventDefault();
    if (!e.repeat && editorSearchCanAct(ac) && open && ac.active >= 0) viewResult(ac);
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (e.repeat) return;
    if (!editorSearchCanAct(ac)) { ac.pickFirst = false; ac.pickCount = null; return; }
    const { n, q } = parseQuery(ac.input.value);
    const copiesWanted = e.shiftKey ? SHIFT_COPIES : n;
    if (open && ac.active >= 0 && ac.query === q) {
      pick(ac, ac.active, copiesWanted);
    } else if (q.length >= SEARCH_MIN) {
      // Typed faster than the lookup: add the card when it comes, if the name is exactly right.
      clearTimeout(ac.timer);
      ac.pickFirst = true;
      ac.pickCount = copiesWanted;
      lookUp(ac, q);
    }
  } else if (e.key === "Escape") {
    if (e.altKey || e.shiftKey || !editorSearchCanAct(ac)) return;
    if (e.repeat) { e.preventDefault(); return; }
    if (ac.input.value) {
      e.preventDefault();
      ac.input.value = "";
      clearTimeout(ac.timer);
      ac.seq += 1;
      clearAdded(ac);
      Object.assign(ac, { items: [], active: -1, query: "", page: 1 });
      markActive(ac);
      showResults(ac);
    }
  }
}

/** Add result i: n copies (a count typed first, or Shift's 4), else 1. The result says "Added ✓ (now 3)"
 * and the text is selected, so the next name replaces it. */
function pick(ac, i, n = null) {
  if (!editorSearchCanAct(ac) || !editorSearchResultsCurrent(ac)) return;
  const c = ac.items[i];
  const { q } = parseQuery(ac.input.value);
  if (!c || ac.query !== q) return;
  const line = addCard(c, editor.addSection, n || 1);
  if (!editorSearchCurrent(ac)) return;
  const words = `Added ✓ (now ${line.qty})`;
  const added = { i, words, name: c.name, query: ac.query };
  ac.addedAt = added;
  ac.live.textContent = `${c.name}: added, ${plural(line.qty, "copy", "copies")} in the ${sectionWords(findLine(line.uid).section)}.`;
  drawOptions(ac);
  clearTimeout(ac.addedTimer);
  ac.addedTimer = setTimeout(() => {
    if (!editorSearchCurrent(ac)) return;
    if (ac.addedAt !== added) return;
    ac.addedAt = null;
    if (ac.items.length && ac.query === added.query) drawOptions(ac);
  }, ADDED_MS);
  ac.input.focus({ preventScroll: true });
  if (ac.input.select) ac.input.select();
}

/** On a phone the on-screen keyboard covers the bottom of the screen: put the search box near the top
 * and keep the results within what's left (visualViewport says how much that is). Beside the list (the
 * sticky side panel, from 1,000 px), whatever the pointer, the panel goes up under the top bar; on a touch
 * screen or a short one its own body also scrolls the box to its top: scrolling the page to the box does
 * nothing for a sticky panel, and an iPad's keyboard would otherwise cover the results. */
function keepSearchInView(ac) {
  if (ac?.dockSuspended) return;
  if (editorSearchDocked(ac)) {
    queueEditorSearchDockFit(ac.owner.dom.searchDock);
    revealEditorSearchDockFocus(ac.owner.dom.searchDock, ac.input); return;
  }
  const side = stickySide(ac);
  const small = window.matchMedia("(pointer: coarse)").matches || (window.visualViewport && window.visualViewport.height < 560);
  if (side) {
    raiseSidePanel(ac);
    const body = small && ac.input.closest(".edit-side-body");
    if (body) {
      // The Add part fills the panel's body exactly (editor.css), so it grows by what's above the box (Add to)
      // for the body to have that much to scroll; the results get the room. It shrinks back on blur.
      const by = ac.input.getBoundingClientRect().top - body.getBoundingClientRect().top - 8;
      const part = ac.wrap.closest(".edit-add");
      if (by > 1 && part && part.style) part.style.minHeight = `calc(100% + ${Math.ceil(by + body.scrollTop)}px)`;
      if (Math.abs(by) > 1) body.scrollTop += by;
    }
  } else if (small) {
    ac.input.scrollIntoView({ block: "start" });
  }
  fitList(ac);
}

/** The side panel the search is in, when it's sticky beside the list (from 1,000 px), else null. */
function stickySide(ac) {
  const side = ac && ac.wrap && ac.wrap.closest && ac.wrap.closest(".edit-side");
  if (!side || typeof getComputedStyle !== "function" || getComputedStyle(side).position !== "sticky") return null;
  return side;
}

/** Beside the list (from 1,000 px), the side panel is sticky under the top bar: when the search gets the focus
 * with the panel still lower down the page, the page goes up to there, so the panel has the screen's height
 * for the results (the list scrolls with it, so nothing is lost). */
function raiseSidePanel(ac) {
  const side = stickySide(ac);
  if (!side) return;
  const stick = parseFloat(getComputedStyle(side).top) || 0;
  const by = side.getBoundingClientRect().top - stick;
  if (by > 1) window.scrollBy(0, by);
}

/** The results' height on a touch screen with its keyboard up: what's left under the box. */
function fitList(ac) {
  if (editorSearchDocked(ac)) { ac.list.style.maxHeight = ""; return; }
  if (!ac || !ac.list || !document.body.classList.contains("keyboard-up")) {
    if (ac && ac.list && ac.list.style) ac.list.style.maxHeight = "";
    return;
  }
  const vv = window.visualViewport;
  const bottom = vv ? vv.offsetTop + vv.height : window.innerHeight;
  const top = ac.list.getBoundingClientRect().top;
  ac.list.style.maxHeight = `${Math.max(168, Math.floor(bottom - top - 16))}px`;
}

/** The height of what's on screen now: less than the page's while an on-screen keyboard is up. */
function viewHeight() {
  const vv = window.visualViewport;
  return vv ? vv.height * vv.scale : window.innerHeight;
}

function viewWidth() {
  const vv = window.visualViewport;
  return vv ? vv.width * vv.scale : window.innerWidth;
}

// The height with no keyboard up: the tallest seen at this width since the page loaded (a phone turned
// round starts again). Not just the height when the search box got the focus: the keyboard may be up
// already then, for the title or a quantity box.
let fullHeight = viewHeight();
let fullWidth = viewWidth();

/** body.keyboard-up while the search box has the focus and an on-screen keyboard takes part of a touch
 * screen: the bar at the bottom makes room for the results then (editor.css), and only then. A
 * keyboard put away with Back, or a hardware keyboard, leaves the focus in the box and the whole
 * screen, and the bar shows. */
function noteKeyboard() {
  const h = viewHeight();
  const w = viewWidth();
  if (Math.abs(w - fullWidth) > 1) {
    fullWidth = w;
    fullHeight = h;
  } else if (h > fullHeight) {
    fullHeight = h;
  }
  const typing = !!(editor && editor.ac && !editor.ac.dockSuspended && document.activeElement === editor.ac.input);
  const touch = window.matchMedia("(pointer: coarse)").matches;
  document.body.classList.toggle("keyboard-up", typing && touch && h < fullHeight - 120);
}

/** --vvh sizes the side panel to the screen above the keyboard (iOS keeps 100dvh the whole screen's).
 * The editor's sticky bar also needs the part of the layout viewport below the visual viewport: Safari
 * can pan back after typing, leaving Save behind its input accessory row. Track that pan as well as
 * height changes. The scaled height distinguishes a keyboard from pinch zoom alone. */
function noteViewHeight() {
  const root = document.documentElement;
  if (!root || !root.style || !root.style.setProperty) return;
  const h = viewHeight();
  root.style.setProperty("--vvh", `${Math.round(h)}px`);
  const vv = window.visualViewport;
  const keyboard = window.matchMedia("(pointer: coarse)").matches && h < fullHeight - 120;
  const bottom = vv && keyboard ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0;
  root.style.setProperty("--editor-keyboard-bottom", `${bottom}px`);
}

if (window.visualViewport) {
  let last = viewHeight();
  noteViewHeight();
  window.visualViewport.addEventListener("resize", () => {
    const h = viewHeight();
    const grew = h > last + 1;
    last = h;
    noteViewHeight();
    noteKeyboard();
    const ac = editor && editor.ac;
    if (!ac || ac.dockSuspended || document.activeElement !== ac.input) return;
    // The keyboard coming up puts the box at the top; it going away leaves the page where it is.
    if (grew) fitList(ac);
    else keepSearchInView(ac);
  });
  window.visualViewport.addEventListener("scroll", () => {
    noteViewHeight();
    if (editor && editor.ac) fitList(editor.ac);
  });
}

/** The card data of a search answer, as a decklist line has it. */
function cardData(c) {
  const { default: _, have: __, aud: ___, free: ____, edhrec: _____, ...card } = c;
  return card;
}

/** Add n copies of a found card to section (on the line of its default printing when there is one).
 * Returns the line. */
function addCard(c, section, n = 1) {
  const ed = editor;
  const lines = ed.lists[section] || (ed.lists[section] = []);
  const d = c.default;
  // More copies of a card already there go on its line (the default printing's, if it has one).
  let line = editorAddLine(ed, c, section);
  if (line) {
    line.qty = Math.min(MAX_COPIES, line.qty + n);
  } else {
    line = newLine({ qty: Math.min(MAX_COPIES, n), name: c.name, set: d && d.set, number: d && d.number,
      finish: d ? d.finish : "nonfoil", card: cardData(c) });
    placeLine(lines, line);
  }
  ed.lastAdded = line.uid;
  ed.flash = line.uid;
  if (section === "Commander" && ed.addSection === "Commander") {
    // That was the commander (partners: pick "Commander" again for the second): the cards picked
    // after it go into the 99, not the Commander section.
    ed.addSection = "Deck";
    if (ed.dom.addTo) drawAddTo();
    toast(`${c.name} is the commander. New cards go to ${sectionTitle("Deck")} now.`);
  }
  syncSections();
  changed();
  const row = ed.dom.lines && ed.dom.lines.querySelector(`.edit-row[data-uid="${line.uid}"]`);
  // Only where Add is a column beside the list (from 1,000 px, editor.css): above the list (a tablet in portrait),
  // scrolling to the row would take the search box, and the keyboard's field, off the screen.
  if (row && !ed.quick && addBesideList()) row.scrollIntoView({ block: "nearest" });
  return line;
}

/** True when the editor's Add panel is a column beside the list (editor.css: from 1,000 px wide). */
function addBesideList() {
  return typeof window === "undefined" || typeof window.matchMedia !== "function"
    || window.matchMedia("(min-width: 1000px)").matches;
}

/** Quick Add uses the same retained nonmodal search dock. */
function openAddSheet() { openEditorSearchDock(); }


// ------------------------------------------------------------ printing picker

/** A line's printing sheet (cards-ui.js pickPrinting: the printings as pictures), with Move and Remove at
 * the bottom. */
async function openPrintings(uid) {
  const found = findLine(uid);
  if (!found) return;
  const { line, section } = found;
  const actions = [...moveTargets(section).map((s) => ({ text: `Move to ${moveWords(s)}`, value: `move:${s}` })),
    { text: "Remove", kind: "danger", value: "remove" }];
  const chosen = await pickPrinting(line.name, { title: line.name, actions,
    current: { set: line.set, number: line.number, finish: line.finish || "nonfoil" } });
  if (!chosen || !findLine(uid) || editor === null) return;
  if (chosen.action === "remove") removeLine(uid);
  else if (chosen.action && chosen.action.startsWith("move:")) moveLine(uid, chosen.action.slice(5));
  else if (!chosen.action) choosePrinting(uid, chosen);
}

function choosePrinting(uid, p) {
  const found = findLine(uid);
  if (!found) return;
  const { line, section } = found;
  if ((line.set || null) === (p.set || null) && (line.number || null) === (p.number || null)
      && (line.finish || "nonfoil") === (p.finish || "nonfoil")) return;
  line.set = p.set || null;
  line.number = p.number || null;
  line.finish = p.finish || "nonfoil";
  if (line.card && p.img_small) line.card = { ...line.card, img_small: p.img_small, img: p.img || p.img_small.replace(/\/small$/, "/normal") };
  // Two lines for one printing become one.
  const lines = editor.lists[section];
  const twin = lines.find((l) => l !== line && lineKey(l) === lineKey(line));
  if (twin) {
    twin.qty = Math.min(MAX_COPIES, twin.qty + line.qty);
    lines.splice(lines.indexOf(line), 1);
  }
  changed();
  toast(`${line.name}: ${printingText(line)} now.`);
}
