/* Deck Lab's page: the Decks page's "Game Changer and ban changes" panel (E9-S36).

libOfficialPanel (drawn by library.js's drawLibrary after the Tables out of date list) comes from
GET /api/official-changes (lib/api/official_changes.py), fetched after the shelf is drawn so it never holds the
shelf up, and only when the shelf has a Commander deck. It lists the cards whose Game Changer flag or
Commander ban changed when the card data last changed (both data dates), and under each the viewer's
Commander decks that hold it, with each deck's counted minimum bracket on today's card data and its aim. It's
read-only: nothing is saved, and the decks to re-check are links. No change kept, or a failure, leaves it
hidden (the shelf is what matters). Loaded after library.js; nothing here runs at load.
*/
"use strict";

/** Whether the shelf has a Commander deck to check, so the panel's request is worth making. */
function libOfficialWanted(data) {
  return (data?.decks || []).some((d) => d && !d.error && d.kind === "commander");
}

/** A note when today's card data no longer agrees with the change (it changed back since), else "". */
function libOfficialNow(card) {
  const now = card.now;
  if (!now || typeof now !== "object") return "";
  if (card.kind === "game_changer_added" && now.game_changer === false) return " Today's card data no longer lists it as one.";
  if (card.kind === "game_changer_removed" && now.game_changer === true) return " Today's card data lists it as one again.";
  if (card.kind === "banned" && now.banned === false) return " Today's card data doesn't have it banned.";
  if (card.kind === "unbanned" && now.banned === true) return " Today's card data has it banned again.";
  return "";
}

/** One deck holding a changed card: a link, its counted minimum on today's flags and its aim. */
function libOfficialDeck(deck) {
  const minimum = Number.isInteger(deck.minimum) && deck.label ? `counted ${deck.label} today` : "its minimum couldn't be counted";
  const aim = Number.isInteger(deck.target_bracket) ? `; aiming at Bracket ${deck.target_bracket}` : "";
  const over = Number.isInteger(deck.minimum) && Number.isInteger(deck.target_bracket) && deck.minimum > deck.target_bracket;
  return el("li", { class: over ? "lib-official-over" : null },
    el("a", { href: deckHref(deck.id), text: deck.title || deck.id }), ` (${minimum}${aim})`,
    over ? el("strong", { text: " Above its aim." }) : null);
}

function libOfficialCard(card) {
  const decks = Array.isArray(card.decks) ? card.decks : [];
  return el("li", { class: "lib-official-card" },
    el("p", {}, el("strong", { text: card.name }), `: ${card.words}.${libOfficialNow(card)}`),
    decks.length ? el("ul", { class: "sources-list" }, decks.map(libOfficialDeck))
      : el("p", { class: "sub", text: "None of your Commander decks hold it." }));
}

/** The panel's contents for an answer with a kept change, or null when there's nothing to show. */
function libOfficialBody(data) {
  const change = data?.change, cards = Array.isArray(data?.cards) ? data.cards : [];
  if (!change || !cards.length) return null;
  const held = new Set(cards.flatMap((c) => (Array.isArray(c.decks) ? c.decks : []).map((d) => d.id)));
  const when = change.new_date ? `the card data of ${change.new_date}` : "the latest card data";
  const since = change.old_date ? `Compared with the card data of ${change.old_date}.` : "The earlier card data's date isn't known.";
  const unread = Number.isInteger(data.unread) && data.unread > 0
    ? el("p", { class: "note", text: `${plural(data.unread, "Commander deck")} couldn't be read, so ${data.unread === 1 ? "it wasn't" : "they weren't"} checked.` }) : null;
  const details = el("details", { open: held.size > 0 },
    el("summary", {}, el("h2", { text: `Game Changer and ban changes in ${when}` })),
    el("p", { class: "sub" }, `${plural(cards.length, "card")} changed; `,
      held.size ? `${plural(held.size, "of your Commander decks", "of your Commander decks")} hold${held.size === 1 ? "s" : ""} one. Re-check ${held.size === 1 ? "it" : "them"} before the next Commander night.`
        : "none of your Commander decks hold one.",
      ` ${since} Brackets are counted minimums, not a certificate.`),
    unread,
    el("ul", { class: "lib-official-cards" }, cards.map(libOfficialCard)));
  return details;
}

/** The panel: hidden until GET /api/official-changes has a change to show; a failure leaves it hidden. */
function libOfficialPanel(data) {
  const host = el("section", { class: "box lib-official", id: "official-changes", "aria-label": "Game Changer and ban changes", hidden: true });
  if (!libOfficialWanted(data)) return host;
  (async () => {
    let answer;
    try {
      answer = await api("/api/official-changes");
    } catch (e) {
      return;
    }
    if (!host.isConnected) return;
    const body = libOfficialBody(answer);
    if (!body) return;
    clear(host).append(body);
    host.hidden = false;
    host.removeAttribute("hidden");
  })();
  return host;
}
