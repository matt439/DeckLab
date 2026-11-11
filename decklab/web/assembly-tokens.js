/* Build decks' tokens: always optional. A token can be a spare card, a die or a scrap of paper, so nothing here
 * counts towards finishing: the ticks are class pack-tick-optional (assembly-progress.js's tick.optional), never
 * the card tasks' pack-tick. Each kind of token a deck makes is a picture tile with its name and at most one short
 * line; every longer word is the caption the viewer shows when the tile is opened. Tick ids and contexts are
 * shared progress: changing what they're made of loses the ticks already saved. */
"use strict";

const PACK_TOKEN_HINT = "Anything will do: a spare token, a die or a scrap of paper.";
const PACK_TOKEN_GROUPS = [["own", null], ["reminder", "Reminders"], ["opponent", "For your opponent"]];

/** "Zombie / Zombie Knight ×8 (Zombie side only, can be sleeved)": a token card and the face this deck
 * uses, and with faces (tokFacesUsed of the deck's needs) whether it needs the other side too:
 * "(Zombie side; both sides used)". */
function assemblyTokenCard(card, faces = null) {
  const face = card.side === "back" ? card.back : card.front;
  const sides = tokSides(card, faces);
  const side = !card.back || !face ? ""
    : sides === "both sides used" ? ` (${face} side; both sides used)` : sides ? ` (${sides})` : ` (${face} side)`;
  return `${card.back ? `${card.front} / ${card.back}` : card.front} ×${card.quantity}${side}`;
}

/** What a need's tile shows: {token (for tokenTile), example (its pictures aren't this card's printing)}. The
 * card's own pictures, else the token's own or example art; card is null for a need with no card. */
function assemblyTokenPicture(need, card) {
  if (card && (card.img || card.back_img)) {
    return { token: { front: card.front, back: card.back || null, img: card.img, back_img: card.back_img },
      example: Boolean(card.example_art) };
  }
  const img = need.image || need.example || null;
  return { token: { front: card ? card.front : need.name, back: card?.back || null, img, back_img: null }, example: Boolean(img) };
}

/** One token need as what its tile says: {group, name, qty, short, caption, picture, tick}, tick {key, context}
 * or null: what's missing or on the way is never a tick. Nothing is reserved: two decks may want the same card
 * (assemblySharedTokens). */
function assemblyTokenItem(need, faces, identity) {
  const cards = need.cards || [], standIns = need.stand_ins || [];
  const theirs = need.side === "opponent" ? "For your opponent: " : "";
  const key = `token|${need.key || need.name}`;
  const item = { group: need.side === "opponent" ? "opponent" : need.kind === "reminder" ? "reminder" : "own",
    name: need.name, qty: null, short: null, tick: null };
  const face = card => card.back ? `${card.side === "back" ? card.back : card.front} side` : null;
  let card = null;
  if ((need.state === "ready" || need.state === "check") && cards.length) {
    card = cards[0];
    Object.assign(item, { qty: card.quantity, short: face(card), tick: { key, context: need.packing_key || cards.map(identity) },
      caption: `${theirs}Grab ${cards.map(c => assemblyTokenCard(c, faces)).join(" or ")} for ${need.name}`
        + (need.state === "check" ? " (details not recorded)" : "") });
  } else if (need.state === "differs" && standIns.length) {
    card = standIns[0];
    Object.assign(item, { qty: card.quantity, short: "Stand-in", tick: { key, context: need.packing_key || identity(card) },
      caption: `${theirs}Stand-in for ${need.name}: ${card.back ? `${card.front} / ${card.back}` : card.front} ×${card.quantity}`
        + ` (${card.why && card.why.length ? `${card.why[0]}; ` : ""}${tokSides(card, faces) ? `${tokSides(card, faces)}; ` : ""}tell your opponent)` });
  } else if (need.state === "incoming") {
    Object.assign(item, { short: `${need.on_the_way || 0} on the way`, caption: `${theirs}No ${need.name} token yet: ${need.on_the_way || 0} on the way` });
  } else {
    Object.assign(item, { short: "No card", caption: `${theirs}No ${need.name} token. ${PACK_TOKEN_HINT}` });
  }
  item.picture = assemblyTokenPicture(need, card);
  if (item.picture.example) item.caption = `${item.caption.replace(/\.$/, "")}. Example art: printing not recorded.`;
  return item;
}

/** A deck's token tiles' words. The step shows the deck's own first, then reminders, then those the cards' text
 * gives only to the opponent (E7-S23, approximate; one that may be either player's stays with the deck's own). */
function assemblyTokenItems(tokens, rows = []) {
  const identity = card => {
    const row = rows?.[card.row] || card;
    return [card.side, ...["front", "back", "set", "front_collector_number", "back_collector_number",
      "finish", "quantity", "front_details", "back_details"].map(key => row[key] ?? "")];
  };
  const faces = tokFacesUsed(tokens.needs);
  return (tokens.needs || []).map(need => assemblyTokenItem(need, faces, identity));
}

/** A token as a tile that opens in the viewer over group, with its long words as the caption. A token has no rules
 * text to miss, so the viewer doesn't say any is unavailable. type: the viewer's type line; view: a deck's plan, whose
 * big view (packOpenCard) shows its task and tick as a card's. */
function assemblyViewerTile(token, example, group, caption, opts, { type = null, view = null } = {}) {
  const card = { ...tokViewerCard(token, type, example), oracle_text: undefined, no_image: "No picture of this token." };
  const tile = tokenTile(token, { sizes: PACK_TILE_SIZES, ...opts,
    onclick: event => view ? packOpenCard(view, event.currentTarget) : openCard(card, event.currentTarget) });
  const open = tile.querySelector(".card-tile-open");
  open.setAttribute("aria-haspopup", "dialog");
  if (view) packRegisterCard(view, tile, card, caption, group);
  else viewerItem(open, card, group, caption);
  return tile;
}

function assemblyTokenTile(item, view) {
  const theirs = item.group === "opponent" ? "For your opponent: " : "";
  const tick = item.tick ? el("button", { type: "button", class: "tile-tick pack-tick-optional", "aria-pressed": "false",
    "aria-label": `${theirs}${item.name}: done`, "data-pack-tick": item.tick.key, "data-pack-count": 1,
    "data-pack-context": JSON.stringify(item.tick.context) }) : null;
  const tile = assemblyViewerTile(item.picture.token, item.picture.example, "pack-tokens", item.caption, {
    name: item.name, qty: item.qty, meta: item.short, state: tick,
    label: `${theirs}${[item.name, item.short].filter(Boolean).join(", ")}` },
  { type: item.group === "reminder" ? "Reminder" : null, view });
  if (!item.tick) tile.classList.add("is-missing");
  return tile;
}

/** The Tokens step's content: one sentence, the tiles, and what to check by hand folded away; a short line
 * when they can't be worked out. tokens: the deck's deck_tokens result, or null when there's none. */
function assemblyTokenTasks(tokens, rows = [], view = null) {
  if (!tokens) return null;
  if (tokens.unavailable || tokens.error) return [el("p", { class: "sub assembly-pending", text: tokens.unavailable || tokens.error })];
  const items = assemblyTokenItems(tokens, rows);
  const others = [...(tokens.copies || []), ...(tokens.unlisted || [])];
  const groups = PACK_TOKEN_GROUPS.map(([key, title]) => {
    const tiles = items.filter(item => item.group === key).map(item => assemblyTokenTile(item, view));
    if (!tiles.length) return null;
    const grid = el("div", { class: "card-tiles pack-token-tiles" }, tiles);
    return title ? el("div", { class: "pack-token-group" }, el("h4", { text: title }), grid) : grid;
  });
  return [items.length ? el("p", { class: "sub", text: PACK_TOKEN_HINT }) : null, ...groups,
    others.length ? el("details", { class: "pack-fold" }, el("summary", { text: `Check by hand (${plural(others.length, "card")})` }),
      el("p", { class: "sub", text: `May make copies or tokens Scryfall doesn't link: ${others.join(", ")}` })) : null];
}

/** Read-only reminders from one coverage estimate across the selected decks. These never make
 * ticks: kinds and deck sources describe an estimate, not a quantity to pack for each deck. */
function assemblyCounterTasks(counters, deckId) {
  if (!counters) return null;
  const needs = (counters.needs || []).filter(need => (need.decks || []).some(deck => deck.id === deckId));
  if (!needs.length && !counters.error) return null;
  return el("section", { class: "pack-counters" }, el("h4", { text: "Counters and dice (optional)" }),
    counters.note ? el("p", { class: "sub", text: counters.note }) : null,
    counters.error ? el("p", { class: "sub assembly-pending", text: counters.error }) : null,
    needs.length ? el("ul", { class: "token-counters" }, needs.map(need => el("li", { class: "token-counter" },
      el("b", { text: need.name }), " ", diceCoverChip(need.cover),
      el("small", { class: "token-need-made", text: `Used by ${need.decks.map(deck =>
        `${deck.title}${deck.sideboard_only ? " (sideboard only)" : ""}`).join(", ")}` }),
      need.cover?.words ? el("small", { class: "token-need-cover", text: need.cover.words }) : null))) : null,
    !counters.error && counters.owned?.ready === false
      ? el("p", { class: "sub", text: counters.owned.words }) : null,
    counters.details ? el("details", { class: "pack-fold" }, el("summary", { text: "About this estimate" }),
      el("p", { class: "sub", text: counters.details })) : null);
}

/** "Shared tokens": the token cards two or more of these decks want (token_plan), hidden when there are
 * none. One card shows one face at a time; nothing is shared out or reserved. */
function assemblySharedTokens(data) {
  const plan = data.token_plan || [];
  if (!plan.length) return null;
  return el("section", { class: "panel pack-extra assembly-tokens" }, el("h2", { text: "Shared tokens" }),
    data.token_plan_note ? el("p", { class: "sub", text: data.token_plan_note }) : null,
    el("ul", { class: "pack-plain" }, plan.map(item => el("li", {},
      el("b", { text: `${tokLabel(item)} ×${item.quantity}` }),
      `: ${[...new Set((item.wanted_by || []).map(w => w.title))].join(", ")}`))));
}

/** Token rows that can't be read: folded to one line, as it never stops anything. */
function assemblyTokenProblems(problems) {
  if (!problems || !problems.length) return null;
  return el("details", { class: "box box-warn pack-token-problems" },
    el("summary", { text: `Some token rows can't be read (${problems.length})` }),
    el("ul", {}, problems.map(problem => el("li", { text: problem }))));
}

/** One owned token card as a tile; its faces' details and notes are the viewer's caption. */
function assemblyOwnedToken(item) {
  const reverse = item.back ? ` / ${item.back}${item.back_details ? ` (${item.back_details})` : ""}`
    : /single-sided verified/i.test(item.notes || "") ? " / single-sided (verified)" : " / reverse not recorded";
  const caption = `${item.quantity} physical ${item.quantity === 1 ? "card" : "cards"}: `
    + `${item.front}${item.front_details ? ` (${item.front_details})` : ""}${reverse}${item.notes ? `. ${item.notes}` : ""}`;
  return assemblyViewerTile({ front: item.front, back: item.back || null, img: item.img, back_img: item.back_img },
    Boolean(item.example_art), "pack-token-cards", caption, { name: tokLabel(item), qty: item.quantity });
}

/** "All your token cards": folded, and pictures too, with why the steps' tokens are approximate. */
function assemblyTokenPanel(data) {
  const tokens = data.tokens || [];
  return el("details", { class: "panel pack-extra assembly-token-list" },
    el("summary", { text: `All your token cards (${tokens.length})` }),
    data.token_note ? el("p", { class: "sub", text: data.token_note }) : null,
    tokens.length ? el("div", { class: "card-tiles pack-token-tiles" }, tokens.map(assemblyOwnedToken))
      : emptyBox("No token cards recorded yet.", el("a", { class: "btn", href: "#/tokens", text: "Add token cards" })));
}
