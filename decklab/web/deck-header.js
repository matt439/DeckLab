"use strict";

/* The P1 deck header's library navigation and recorded edit date. Navigation reads a fresh visible shelf;
   it never uses another person's cached library. It keeps the library filters when they include this deck,
   otherwise uses all visible ordinary decks. The page itself and every linked deck remain server-guarded. */

/** The actual last edit, in the device's date/time zone. Unknown or invalid metadata adds no date. */
function deckChangedDate(edited) {
  if (!edited) return null;
  const when = new Date(edited);
  if (Number.isNaN(when.getTime())) return null;
  return el("time", { class: "deck-changed", datetime: when.toISOString(),
    title: `Last changed ${when.toLocaleString("en-AU", { dateStyle: "long", timeStyle: "short" })}`,
    text: `Last changed ${simDay(when)}` });
}

/** Previous/next through the last library filter, in the same grouped order as the lab's rows. */
function deckNeighbours(data) {
  if (!["casual", "commander"].includes(data.summary.kind) || data.summary.read_only) return null;
  const nav = el("nav", { class: "deck-neighbours", "aria-label": "Decks in the library", hidden: true });
  const screen = deckScreen, token = routeToken, profile = state.profile?.id;
  const here = () => nav.isConnected && screen === deckScreen && token === routeToken && profile === state.profile?.id;
  let sequence = 0;
  const refresh = async () => {
    const request = ++sequence;
    try {
      const answer = await api("/api/decks");
      if (!here() || request !== sequence) return;
      const filters = libraryFilters(new URLSearchParams((state.libraryHash || "").split("?")[1] || ""));
      const visible = (answer.decks || []).filter((deck) => !deck.error);
      let ordered = libRowOrder(libVisibleDecks({ decks: visible }, filters), filters.sort);
      if (!ordered.some((deck) => deck.id === data.summary.id)) ordered = libRowOrder(visible, filters.sort);
      const at = ordered.findIndex((deck) => deck.id === data.summary.id);
      clear(nav);
      if (at < 0) { nav.hidden = true; return; }
      screen.neighbourLinks = [];
      const neighbour = (offset, words, arrow) => {
        const deck = ordered[at + offset];
        const icon = el("span", { "aria-hidden": "true", text: arrow });
        if (!deck) return el("button", { type: "button", class: "btn btn-art", disabled: true,
          "aria-label": `No ${words.toLowerCase()} deck` }, icon);
        const link = el("a", { class: "btn btn-art", href: deckNeighbourHref(deck, screen),
          "aria-label": `${words} deck: ${deck.title}`, title: `${words}: ${deck.title}`,
          onclick: (event) => {
            if (event?.metaKey || event?.ctrlKey || event?.shiftKey || event?.altKey || !here()) return;
            const params = new URLSearchParams((state.libraryHash || "").split("?")[1] || "");
            params.set("deck", deck.id);
            state.libraryHash = `#/library?${params}`;
          } }, icon);
        screen.neighbourLinks.push([deck, link]);
        return link;
      };
      add(nav, [neighbour(-1, "Previous", "‹"), neighbour(1, "Next", "›"),
        el("span", { class: "deck-neighbour-count", role: "status", "aria-label": `Deck ${at + 1} of ${ordered.length}`,
          text: `${at + 1} of ${ordered.length}` })]);
      nav.hidden = false;
    } catch (error) {
      if (!here() || request !== sequence) return;
      clear(nav).append(el("span", { class: "sub", text: "Deck navigation unavailable" }),
        el("button", { type: "button", class: "btn", text: "Try again", onclick: () => { if (here()) refresh(); } }));
      nav.hidden = false;
    }
  };
  refresh();
  return nav;
}

/** Each neighbour keeps the current tab/filter and uses Play-now only when that deck has that list. */
function deckNeighbourHref(deck, screen) {
  const version = screen.data.version === "owned" && deck.versions?.includes("owned") ? "owned" : "target";
  let href = deckHref(deck.id, version);
  if (screen.view.tab !== "overview") href += `&tab=${screen.view.tab}`;
  if (screen.view.tab === "cards" && screen.view.filter !== "all") href += `&filter=${screen.view.filter}`;
  return href;
}

function syncDeckNeighbours(screen) {
  for (const [deck, link] of screen.neighbourLinks || []) link.setAttribute("href", deckNeighbourHref(deck, screen));
}
