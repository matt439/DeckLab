/* Deck Lab's page: the top bar's global search (E11-S31; visual-design.md 3.2 and 3.3).

One search from any page, over GET /api/search?q=: the decks the viewer may see, the viewer's own collection
(with free and in-use counts, as the Collection page counts them) and every other Scryfall card, in that order,
about 5 of each with a See all (Decks: the library filtered by title; In your collection: the Collection page's
search; Other cards: the card viewer over up to 50 matches). The server leaves out what the viewer may not
see, so nothing here filters or names anything itself.

  A search field before the avatar in the lab from 1000 px and the casual header from 600 px (300 px on the
  iPad in portrait, 16 px text so iOS doesn't zoom), its results in a panel under it; under 600 px, and on a
  phone on its side, a search icon that opens the same search as a sheet.
  `/` (outside text fields, menus and dialogs, with single-character shortcuts on) goes to it on every page
  but the Editor, where `/` stays the existing alias of F (find a card to add).
  Typing waits GS_DEBOUNCE ms; an answer to older text, another person or a closed search is dropped.
  ArrowDown from the field goes into the results, ArrowUp/ArrowDown move through them, Enter in the field
  opens the first result, Escape closes the results.

Loaded after shell.js, which calls setUpGlobalSearch() at start, drawGlobalSearch() when a profile is chosen,
syncGlobalSearch() on every route and hides #global-search on the "Who are you?" screen. Nothing runs at load.
*/
"use strict";

const GS_DEBOUNCE = 200;              // ms of typing pause before asking the server
const GS_SEE_ALL = 50;                // the card viewer's See all
// The field: the lab from 1000 px and the casual header from 600 px. Narrower, and on a phone on its side (the
// lab's top bar under 1000 px, with no room beside its nav pills), the icon and the sheet. shell.css matches it.
const GS_FIELD_QUERY = "(min-width: 1000px), (min-width: 600px) and (min-height: 501px), (min-width: 600px) and (orientation: portrait)";
const GS_ICON = "M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM20 20l-4.8-4.8";
let gsWired = false, gsSeq = 0, gsBar = null, gsSheet = null;

function gsIcon() {
  return svgEl("svg", { class: "icon icon-search", viewBox: "0 0 24 24", width: 22, height: 22, "aria-hidden": "true",
    focusable: "false" }, svgEl("path", { d: GS_ICON }));
}

/** True on the pages where `/` belongs to the page (the Editor and a new deck's). */
function gsPageOwnsSlash(path = parseHash().path) { return path === "edit" || path === "new"; }

/** One search box: the field, a status line for screen readers and the results. inSheet: the phone's sheet. */
function gsBox(inSheet) {
  const id = inSheet ? "gs-sheet" : "gs-bar";
  const input = el("input", { type: "search", class: "gs-input", id: `${id}-input`, autocomplete: "off", spellcheck: "false",
    enterkeyhint: "search", placeholder: "Search decks and cards", "aria-label": "Search decks and cards",
    "aria-controls": `${id}-results`, "aria-expanded": "false", maxlength: "100" });
  const hint = el("span", { class: "kbd gs-kbd", text: "/", "aria-hidden": "true", hidden: true });
  const status = el("p", { class: "sr-only", role: "status", "aria-live": "polite" });
  const results = el("div", { class: "gs-results", id: `${id}-results`, hidden: true });
  const form = el("form", { class: "gs-form", role: "search", onsubmit: (e) => { e.preventDefault(); gsFirst(box); } },
    gsIcon(), input, hint);
  const box = { inSheet, input, hint, status, results, form, root: el("div", { class: "gs-box" }, form, status, results),
    timer: 0, text: "", answer: null };
  input.addEventListener("input", () => gsTyped(box));
  input.addEventListener("keydown", (e) => gsFieldKey(box, e));
  input.addEventListener("focus", () => { if (box.answer && box.input.value.trim()) gsShow(box, true); });
  results.addEventListener("keydown", (e) => gsResultsKey(box, e));
  return box;
}

// ------------------------------------------------------------------ set up

/** Wire the top bar's search once, at start (shell.js setUpShell). */
function setUpGlobalSearch() {
  if (gsWired) return;
  const host = byId("global-search");
  if (!host) return;
  gsWired = true;
  gsBar = gsBox(false);
  const open = el("button", { type: "button", class: "gs-open", "aria-label": "Search decks and cards",
    "aria-haspopup": "dialog", onclick: () => openGlobalSearchSheet() }, gsIcon());
  host.append(gsBar.root, open);
  document.addEventListener("keydown", gsSlash);
  // A click outside the bar's search closes its results.
  document.addEventListener("click", (e) => {
    if (gsBar && !gsBar.root.contains(e.target)) gsShow(gsBar, false);
  });
}

/** Show the search for the profile chosen (shell.js drawShell). */
function drawGlobalSearch() {
  const host = byId("global-search");
  if (!host) return;
  host.hidden = !state.profile;
  if (gsBar && gsBar.owner !== state.profile?.id) gsReset(gsBar);
  if (gsBar) gsBar.owner = state.profile?.id;
  syncGlobalSearch();
}

/** On every route (shell.js syncShell): close the results, and say what `/` does on this page in the
 * keyboard help (nothing on the Editor's pages, where it stays the Editor's). */
function syncGlobalSearch() {
  if (gsBar) gsShow(gsBar, false);
  const host = byId("global-search");
  if (!host || !gsBar || !state.profile) return;
  const profile = state.profile.id;
  registerKeyboardHelp(host, () => gsPageOwnsSlash() ? [] : [{ keys: ["/"], label: "Search decks and cards",
    characters: true, scope: "On every page but the Editor, outside text fields, menus and dialogs." }],
  { profile, current: () => state.profile?.id === profile && !host.hidden,
    refresh: (enabled) => {
      const on = enabled && !gsPageOwnsSlash();
      gsBar.hint.hidden = !on;
      keyboardCharacterKeys(gsBar.input, ["/"], on);
    } });
}

/** Forget a box's text and answer (another person chose, or the sheet closed). */
function gsReset(box) {
  gsSeq += 1;
  clearTimeout(box.timer);
  box.input.value = "";
  box.text = "";
  box.answer = null;
  clear(box.results);
  box.status.textContent = "";
  gsShow(box, false);
}

function gsShow(box, on) {
  const shown = Boolean(on) && box.results.children.length > 0;
  box.results.hidden = !shown;
  box.input.setAttribute("aria-expanded", String(shown));
}

// ------------------------------------------------------------------ keys

/** `/` from anywhere but a text field, a menu, a dialog or the Editor: the search. */
function gsSlash(e) {
  if (e.key !== "/" || e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.repeat || e.isComposing
      || !state.profile || !keyboardCharactersEnabled() || keyboardEditing(e.target) || keyboardDialog()
      || keyboardMenuOpen() || gsPageOwnsSlash()) return;
  const host = byId("global-search");
  if (!host || host.hidden || !gsBar) return;
  e.preventDefault();
  focusGlobalSearch();
}

/** The field in the top bar, or the sheet on a phone. */
function focusGlobalSearch() {
  if (typeof window.matchMedia === "function" && !window.matchMedia(GS_FIELD_QUERY).matches) return openGlobalSearchSheet();
  gsBar.input.focus();
  if (gsBar.input.select) gsBar.input.select();
  if (gsBar.answer && gsBar.input.value.trim()) gsShow(gsBar, true);
  return gsBar;
}

function gsItems(box) { return Array.from(box.results.querySelectorAll(".gs-pick")); }

function gsFieldKey(box, e) {
  if (e.key === "ArrowDown") {
    const first = gsItems(box)[0];
    if (first) { e.preventDefault(); gsShow(box, true); first.focus(); }
  } else if (e.key === "Escape" && !box.inSheet && !box.results.hidden) {
    e.preventDefault(); gsShow(box, false);
  }
}

function gsResultsKey(box, e) {
  const items = gsItems(box), at = items.indexOf(document.activeElement);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const next = at + (e.key === "ArrowDown" ? 1 : -1);
    if (next < 0) box.input.focus();
    else if (items[Math.min(next, items.length - 1)]) items[Math.min(next, items.length - 1)].focus();
  } else if (e.key === "Escape" && !box.inSheet) {
    e.preventDefault(); gsShow(box, false); box.input.focus();
  }
}

/** Enter in the field: the first result (after the answer to this text has come). */
function gsFirst(box) {
  const first = box.answer && box.text === box.input.value.trim() ? box.results.querySelector(".gs-item") : null;
  if (first) first.click();
}

// --------------------------------------------------------------- asking

function gsTyped(box) {
  clearTimeout(box.timer);
  const text = box.input.value.trim();
  if (!text) { gsReset(box); return; }
  box.timer = setTimeout(() => gsAsk(box, text), GS_DEBOUNCE);
}

/** Ask for text; draw the answer only while it's still this box's text, person and open search. */
async function gsAsk(box, text) {
  const seq = ++gsSeq, profile = state.profile?.id;
  box.text = text;
  const current = () => seq === gsSeq && profile === state.profile?.id && box.input.value.trim() === text
    && box.root.isConnected;
  let answer;
  try {
    answer = await api(`/api/search?q=${encodeURIComponent(text)}`);
  } catch (error) {
    if (!current()) return;
    box.answer = null;
    clear(box.results).append(el("p", { class: "gs-note", text: error.message || "The search didn't work." }));
    box.status.textContent = "The search didn't work.";
    gsShow(box, true);
    return;
  }
  if (!current()) return;
  box.answer = answer;
  gsDraw(box, answer);
  gsShow(box, box.inSheet || document.activeElement === box.input || box.results.contains(document.activeElement));
}

// ---------------------------------------------------------------- drawing

function gsDraw(box, answer) {
  const groups = (answer.groups || []).filter((g) => g.items.length || g.error);
  clear(box.results);
  if (!groups.length) {
    box.results.append(el("p", { class: "gs-note", text: `Nothing matches “${answer.q}”.` }));
    box.status.textContent = "No results.";
    return;
  }
  for (const group of groups) {
    const headId = `${box.input.id}-${group.id}`;
    const part = el("section", { class: `gs-group gs-${group.id}`, "aria-labelledby": headId },
      el("h3", { class: "gs-head", id: headId, text: group.label }));
    if (group.error) part.append(el("p", { class: "gs-note", text: group.error }));
    if (group.items.length) part.append(el("ul", { class: "gs-list" }, group.items.map((item) => el("li", {}, gsItem(box, group, item)))));
    if (group.more) part.append(gsSeeAll(box, group, answer.q));
    box.results.append(part);
  }
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  box.status.textContent = `${plural(total, "result")}: ${groups.map((g) => g.label).join(", ")}.`;
}

/** A result: a deck opens its page; a card opens the card viewer. */
function gsItem(box, group, item) {
  if (group.id === "decks") {
    const meta = [item.format || item.kind, item.status].filter(Boolean).join(" · ");
    return el("a", { class: "gs-item gs-pick", href: deckHref(item.id), onclick: () => gsDone(box) },
      el("span", { class: "gs-name", text: item.title }), meta ? el("span", { class: "gs-meta", text: meta }) : null);
  }
  const meta = group.id === "collection" ? gsCounts(item) : (item.card && item.card.type_line) || "";
  return el("button", { type: "button", class: "gs-item gs-pick", disabled: item.card ? null : true,
    onclick: (e) => { if (item.card) openCard(item.card, e.currentTarget); } },
  el("span", { class: "gs-name", text: item.name }), meta ? el("span", { class: "gs-meta", text: meta }) : null);
}

/** "3 free · 2 in decks · 1 on the way"; a tracked basic land has only its copies. */
function gsCounts(item) {
  const parts = item.basic || item.free == null ? [`${item.owned} owned`]
    : [`${item.free} free`, item.in_use ? `${item.in_use} in decks` : null];
  if (item.incoming) parts.push(`${item.incoming} on the way`);
  return parts.filter(Boolean).join(" · ");
}

/** A group's See all. The Collection page's search also matches rules text, so its link names no count. */
function gsSeeAll(box, group, q) {
  const words = group.id === "collection" ? "See all in Collection"
    : group.capped ? `See all ${group.total}+` : `See all ${group.total}`;
  if (group.id === "decks") {
    return el("a", { class: "gs-all gs-pick", href: `#/library?${new URLSearchParams({ all: "1", q })}`, onclick: () => gsDone(box),
      text: words });
  }
  if (group.id === "collection") {
    const params = new URLSearchParams({ q });
    if (group.space && group.space !== ownSpace()) params.set("space", group.space);
    return el("a", { class: "gs-all gs-pick", href: `#/collection?${params}`, onclick: () => gsDone(box), text: words });
  }
  return el("button", { type: "button", class: "gs-all gs-pick", text: words, onclick: (e) => gsAllCards(e.currentTarget, q) });
}

/** Other cards' See all: the card viewer over up to GS_SEE_ALL of them. */
async function gsAllCards(trigger, q) {
  const profile = state.profile?.id;
  try {
    const answer = await api(`/api/search?${new URLSearchParams({ q, group: "cards", limit: String(GS_SEE_ALL) })}`);
    if (profile !== state.profile?.id) return;
    const found = ((answer.groups || [])[0] || { items: [] }).items.map((item) => item.card).filter(Boolean);
    if (found.length) openCardViewer(found, 0, { trigger });
  } catch (error) {
    toast(error.message || "The cards couldn't be loaded.");
  }
}

/** A result followed: the bar's results close (a route change does too); the sheet closes itself on a link. */
function gsDone(box) { if (!box.inSheet) gsShow(box, false); }

// ------------------------------------------------------------------ sheet

/** The phone's search: the same box in a sheet, its field focused. */
function openGlobalSearchSheet() {
  if (gsSheet && !gsSheet.closed) { gsSheet.box.input.focus(); return gsSheet; }
  const box = gsBox(true);
  const sheet = openSheet("Search", { body: [box.root], onClose: () => { gsSeq += 1; clearTimeout(box.timer); gsSheet = null; } });
  sheet.dialog.classList.add("gs-sheet");
  sheet.box = box;
  gsSheet = sheet;
  box.input.focus();
  return sheet;
}
