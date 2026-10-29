/* A deck picker: a button that shows the chosen deck (its small picture, short name and colour pips) and opens a
popover listbox of decks drawn the same way. Matchups' "Show matchups for" uses it in place of a native select,
which can't show pictures or pips. Keyboard: the arrow keys, Home and End move, Enter or Space chooses, Escape
closes, typing a name's first letters jumps to it (select-only listbox, focus on the list with
aria-activedescendant). Decks come from the caller, so it shows only what the caller already may show. Loaded after
matchups-overview.js; library.js (deckArtThumb, libColours) and ui.js (the colour pieces) are used once the page
runs, and left out when they aren't loaded (a deck then shows its name alone). */
"use strict";

const DECK_LISTBOX_TYPEAHEAD_MS = 500;

/** The pieces one deck shows: its small picture and its pips, from the library's summary of it (none for a
 * deck the library doesn't list, such as a Beginner Box pairing). */
function deckListboxArt(summary) {
  if (!summary || typeof libColours !== "function" || typeof deckArtThumb !== "function") return { thumb: null, pips: null };
  const colours = libColours(summary);
  return { thumb: deckArtThumb(summary, colours, "deck-row-art deck-pick-art"),
    pips: colours ? colours.pips(16, { cls: "deck-pips deck-pick-pips" }) : null };
}

/** The label and picker as one field. decks: [{id, title}] in their order; names: id -> the short name shown;
 * library: /api/decks' answer (for colours and pictures); selected: the chosen id; onChoose(id) runs only when
 * another deck is chosen. Returns the field node; its button has the given id. */
function deckListbox({ id, label, decks, names, library, selected, onChoose, cls = "" }) {
  const summaries = new Map((library?.decks || []).map((d) => [d.id, d]));
  const shown = (d) => names?.get(d.id) || d.title;
  const listId = `${id}-list`, labelId = `${id}-label`, valueId = `${id}-value`;
  const chosen = decks.find((d) => d.id === selected) || decks[0];
  const face = (d, extra = null) => {
    const { thumb, pips } = deckListboxArt(summaries.get(d.id));
    if (pips) pips.setAttribute("aria-hidden", "true");
    return [thumb, el("span", { class: "deck-pick-name", text: shown(d) }), pips, extra];
  };
  const button = el("button", { type: "button", id, class: "deck-pick-button", "aria-haspopup": "listbox",
    "aria-expanded": "false", "aria-controls": listId, "aria-labelledby": `${labelId} ${valueId}`, title: chosen?.title },
  chosen ? face(chosen, el("span", { class: "sr-only", id: valueId, text: chosen.title })) : null,
  el("span", { class: "deck-pick-caret", "aria-hidden": "true" }));
  const options = decks.map((d, index) => el("li", { role: "option", id: `${id}-opt-${index}`, class: "deck-pick-option",
    "data-id": d.id, "aria-label": d.title, "aria-selected": String(d.id === chosen?.id), title: d.title,
    onmousedown: (event) => event.preventDefault(),     // the list keeps the focus, so it doesn't close first
    onmousemove: () => move(index),
    onclick: () => pick(index) }, face(d)));
  const list = el("ul", { class: "deck-pick-list", role: "listbox", id: listId, tabindex: "-1", hidden: true,
    "aria-labelledby": labelId, "data-popover": "" }, options);
  list.keyboardAnchor = button;
  list.closePopover = () => close(false);
  let active = Math.max(0, decks.indexOf(chosen)), typed = "", typedTimer = null;

  function move(index) {
    if (!options.length) return;
    active = Math.max(0, Math.min(options.length - 1, index));
    options.forEach((option, n) => option.classList.toggle("is-active", n === active));
    list.setAttribute("aria-activedescendant", options[active].id);
    if (!list.hidden && options[active].scrollIntoView) options[active].scrollIntoView({ block: "nearest" });
  }
  function open(index = decks.indexOf(chosen)) {
    if (!button.isConnected || !options.length) return;
    closeMenus();
    list.hidden = false;
    button.setAttribute("aria-expanded", "true");
    if (typeof keepInWindow === "function") keepInWindow(list);
    move(index < 0 ? 0 : index);
    list.focus({ preventScroll: true });
  }
  function close(refocus) {
    if (list.hidden) return;
    list.hidden = true;
    button.setAttribute("aria-expanded", "false");
    list.removeAttribute("aria-activedescendant");
    if (refocus && button.isConnected) button.focus({ preventScroll: true });
  }
  function pick(index) {
    const deck = decks[index];
    close(true);
    if (!deck || deck.id === chosen?.id) return;
    onChoose(deck.id);
    // The caller draws the picker again: its new button has the focus, not the heading.
    const again = document.getElementById(id);
    if (again && again !== button && again.isConnected) again.focus({ preventScroll: true });
  }
  /** Type-ahead: the next deck whose shown name or full title starts with what was typed in the last half second;
   * one letter typed again goes round the decks starting with it. */
  function typeAhead(key) {
    clearTimeout(typedTimer);
    typed += key.toLowerCase();
    typedTimer = setTimeout(() => { typed = ""; }, DECK_LISTBOX_TYPEAHEAD_MS);
    const repeat = typed.length > 1 && [...typed].every((c) => c === typed[0]);
    const prefix = repeat ? typed[0] : typed;
    const start = repeat || typed.length === 1 ? active + 1 : active;
    for (let n = 0; n < decks.length; n++) {
      const index = (start + n) % decks.length, d = decks[index];
      if (shown(d).toLowerCase().startsWith(prefix) || d.title.toLowerCase().startsWith(prefix)) return index;
    }
    return -1;
  }
  const printable = (event) => typeof event.key === "string" && event.key.length === 1 && event.key !== " "
    && !event.ctrlKey && !event.metaKey && !event.altKey;

  button.addEventListener("click", () => { if (list.hidden) open(); else close(true); });
  button.addEventListener("keydown", (event) => {
    if (event.isComposing || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); open(); return; }
    if (printable(event)) {
      event.preventDefault();
      const found = typeAhead(event.key);
      open(found >= 0 ? found : active);
    }
  });
  list.addEventListener("keydown", (event) => {
    if (event.isComposing || event.altKey || event.ctrlKey || event.metaKey) return;
    const keys = { ArrowDown: active + 1, ArrowUp: active - 1, Home: 0, End: options.length - 1,
      PageDown: active + 10, PageUp: active - 10 };
    if (event.key in keys) { event.preventDefault(); move(keys[event.key]); return; }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!event.repeat) pick(active);
      return;
    }
    if (event.key === "Escape") { event.preventDefault(); close(true); return; }
    if (event.key === "Tab") { close(false); return; }
    if (printable(event)) {
      event.preventDefault();
      const found = typeAhead(event.key);
      if (found >= 0) move(found);
    }
  });
  move(active);
  list.removeAttribute("aria-activedescendant");
  return el("div", { class: ["field deck-pick", cls].filter(Boolean).join(" ") },
    el("label", { id: labelId, for: id, text: label }),
    el("div", { class: "deck-pick-wrap" }, button, list));
}
