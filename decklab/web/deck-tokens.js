/* The deck page's Tokens part on its Cards tab (lib/tokens deck_tokens, for the version shown), kept short
 * (E7-S33): a summary line only when something needs a look, then one compact row per token, each a native
 * <details> whose summary is a small picture, the name with its P/T, a chip only when the token isn't
 * ready, and a short count; everything else (what it is, who makes it, the full state, the cards to grab,
 * the stand-ins, Forge's estimate) is in the row's body. The sideboard's and the opponent's tokens, the
 * counters and dice, and what Scryfall's links can't say are closed disclosures of their own.
 *     tokensSection(data)              the whole part (null for a pairing)
 *     tokenNeedList(needs, faces, o)   a list of compact rows; o: { packed, opponent }
 *     tokenCountersPart(counters)      the counters and dice the cards use (E7-S24)
 * Uses tokens.js's tokenThumb, tokenStateChip, tokNeedWords, tokCardWords, tokLabel, tokFacesUsed,
 * tokFacesKey and tokSides, token-peaks.js's tokenPeakLine, tokenPeakShort and tokenPeaksPart, dice.js's
 * diceCoverChip and product-tokens.js's productPackedTokens. */
"use strict";

/** The Tokens part: the tokens and reminders the list's cards make, each against the token cards owned.
 * Missing or different tokens are never warnings: at home a stand-in is fine. null for a pairing. */
function tokensSection(data) {
  const t = data.tokens;
  if (!t) return null;
  const section = el("section", { class: "deck-section token-part", id: "sec-tokens", "aria-labelledby": "h-tokens" },
    el("h2", { id: "h-tokens", text: "Tokens and reminders" }));
  const edit = el("p", { class: "deck-tokens-edit" }, el("a", { href: "#/tokens", text: "Edit your tokens" }));
  // Not for this viewer: a plain explanation. A failure is a notice (it came with the page: no Try again).
  if (t.unavailable || t.error) {
    section.append(t.unavailable ? el("p", { class: "sub", text: t.unavailable })
      : el("div", { class: "note note-warn", role: "alert" }, el("p", { text: t.error })));
    return section;
  }
  const needs = t.needs || [];
  if (!needs.length) {
    if (t.packed?.product) add(section, [deckPackedTokens(data)]);
    section.append(el("p", { class: "sub", text: "No tokens or reminders are linked to this list's cards on Scryfall." }));
  } else {
    const faces = tokFacesUsed(needs);
    // "Packed N" is worked out before merging: a merged line keeps only its first card's row.
    const packed = t.packed && !t.packed.product && !t.packed.error ? t.packed : null;
    const merged = needs.map((n) => ({ ...mergedTokenCards(n), packed_here: tokPackedHere(n, packed) }));
    // E7-S23: a token the cards' text gives only to the opponent has its own group; "either" stays here.
    const theirs = merged.filter((n) => n.side === "opponent"), ours = merged.filter((n) => n.side !== "opponent");
    const main = ours.filter((n) => !n.sideboard_only), side = ours.filter((n) => n.sideboard_only);
    const words = tokCountWords(t.counts, needs);
    if (words) section.append(el("p", { class: "deck-tokens-summary", text: words }));
    // A product's record covers all its decks, so it's drawn once here and its rows show card counts only.
    if (t.packed) add(section, [deckPackedTokens(data, faces)]);
    if (main.length) section.append(tokenNeedList(main, faces, { packed }));
    if (side.length) {
      section.append(el("details", { class: "deck-tokens-group" },
        el("summary", { text: `Only for sideboard cards (${num(side.length)})` }), tokenNeedList(side, faces, { packed })));
    }
    if (theirs.length) {
      section.append(el("details", { class: "deck-tokens-group deck-tokens-opponent" },
        el("summary", { text: `For your opponent (${num(theirs.length)}, approximate)` }),
        el("p", { class: "sub", text: "The cards' text gives these to the other player: hand them across the table." }),
        tokenNeedList(theirs, faces, { packed, opponent: true })));
    }
  }
  add(section, [tokenCountersPart(t.counters), tokenUnseenPart(t)]);
  section.append(edit);
  return section;
}

/** "1 to check · 1 you don't have" from a deck_tokens result's counts: only what needs a look, "" when
 * every token is ready. A token none of whose cards are free, but some packed in other decks, is counted
 * as such, as its row's chip says. */
function tokCountWords(counts, needs = []) {
  const c = counts || {};
  const packedElsewhere = (needs || []).filter((n) => n.state === "none" && (n.in_use || []).length).length;
  return [[c.check, "to check"], [c.differs, "different"], [c.incoming, "on the way"],
    [(Number(c.none) || 0) - packedElsewhere, "you don't have"], [packedElsewhere, "packed in other decks"]]
    .filter(([n]) => n > 0).map(([n, words]) => `${n} ${words}`).join(" · ");
}

/** A deck's token needs (deck_tokens's "needs") as compact rows, in the server's order. faces: tokFacesUsed
 * of all the deck's needs; opts.packed: the deck's own packed line (its "Packed N"); opts.opponent: the
 * opponent's group, whose heading already says whose they are. */
function tokenNeedList(needs, faces = null, opts = {}) {
  return el("ul", { class: "token-needs" }, (needs || []).map((need) => tokenNeed(need, faces, opts)));
}

/** How many of a need's cards this deck's own Token cards line packs (0 when it has none). */
function tokPackedHere(need, packed) {
  if (!packed || !(packed.lines || []).length) return 0;
  const keys = new Set([...(need.cards || []), ...(need.stand_ins || [])].map(tokFacesKey));
  let n = 0;
  for (const line of packed.lines) for (const row of line.rows || []) if (keys.has(tokFacesKey(row))) n += Number(row.quantity) || 0;
  return n;
}

/** One need as a compact row: a <details> whose summary is the picture, name and P/T, a chip only when it
 * needs a look, and a short count; its body holds the rest, with why each stand-in differs. */
function tokenNeed(need, faces = null, opts = {}) {
  const cards = need.cards || [], standIns = need.stand_ins || [], incoming = need.incoming || [], inUse = need.in_use || [];
  const desc = need.key && String(need.key).startsWith("name:") ? "" : tokNeedWords(need);
  // A token without a picture of its own shows example art of a token with its name, labelled as such.
  const example = !need.image && need.example ? need.example : null;
  const chipState = need.state === "none" && inUse.length ? "in_use" : need.state;
  const here = need.packed_here ?? tokPackedHere(need, opts.packed);
  const usable = Number(need.usable) || cards.reduce((n, card) => n + (Number(card.quantity) || 0), 0);
  const count = here ? `Packed ${num(here)}` : usable ? plural(usable, "card") : "";
  const names = (need.made_by || []).map((m) => m.section === "Sideboard" ? `${m.name} (sideboard)` : m.name);
  const head = el("summary", { class: "token-row" },
    tokenThumb(example || need.image, 28, need.pt),
    el("span", { class: "token-need-name" }, el("b", { text: need.name }), need.pt ? ` ${need.pt}` : null),
    chipState && chipState !== "ready" ? tokenStateChip(chipState) : null,
    !opts.opponent && need.side === "either" ? status("info", "Maybe opponent's") : null,
    count || need.forge ? el("span", { class: "token-row-end" }, count ? el("span", { class: "token-row-count", text: count }) : null,
      typeof tokenPeakShort === "function" ? tokenPeakShort(need.forge) : null) : null);   // E7-S08, token-peaks.js
  const body = el("div", { class: "token-need-body" },
    example ? el("small", { class: "token-need-example", text: "Example art" }) : null,
    desc ? el("p", { class: "token-need-desc", text: desc }) : null,
    names.length ? el("p", { class: "token-need-made", text: `Made by ${names.join(", ")}` }) : null,
    // Whose side it lands on, read from the cards' text (E7-S23); the opponent's group says it already.
    need.side_words && !opts.opponent ? el("p", { class: `token-need-side token-need-side-${need.side}`, text: need.side_words }) : null,
    el("p", { class: "token-need-state", text: need.words || (TOK_STATES[need.state] || [])[1] || "" }),
    need.forge && typeof tokenPeakLine === "function" ? tokenPeakLine(need.forge) : null,
    cards.length ? el("ul", { class: "token-grab", "aria-label": "Grab" }, cards.map((card) => el("li", {},
      `Grab ${tokCardWords(card, faces)}`,
      card.also_for && card.also_for.length ? ` (same card as for ${card.also_for.join(" and ")})` : null,
      card.shared && card.shared.length ? el("small", { class: "tok-shared",
        text: `Also used by ${card.shared.map((h) => h.title).join(" and ")}, with too few cards for all of them` }) : null,
      card.verdict === "check" && card.why && card.why.length ? el("small", { text: card.why.join("; ") }) : null))) : null,
    inUse.length ? el("ul", { class: "token-grab", "aria-label": "In use" }, inUse.map((item) =>
      el("li", { text: `In use: ${tokLabel(item)} ×${item.quantity}, packed in ${item.decks.join(" and ")}` }))) : null,
    incoming.length ? el("ul", { class: "token-grab", "aria-label": "On the way" }, incoming.map((item) => el("li", {
      text: `On the way: ${tokLabel(item)} ×${item.quantity} (order ${item.order})` }))) : null,
    standIns.length ? el("div", { class: "token-stand-ins" }, el("p", { class: "sub", text: "Stand-ins" }),
      el("ul", { class: "token-grab" }, standIns.map((card) => el("li", {}, tokCardWords(card),
        card.why && card.why.length ? el("small", { text: card.why.join("; ") }) : null)))) : null);
  return el("li", { class: `token-need token-need-${need.state}` }, el("details", { class: "token-need-row" }, head, body));
}

/** The counters and dice a deck's cards call for (deck_tokens's "counters", lib/tokens/counters.py, E7-S24),
 * read-only and approximate: one closed disclosure whose summary lists the kinds, with a chip only when owned
 * dice and counters don't cover one. null when there are none. */
function tokenCountersPart(counters) {
  const needs = (counters && counters.needs) || [];
  if (!needs.length) return null;
  const where = { player: " (on players)", die: "" };
  const usedBy = (madeBy) => {
    const names = (madeBy || []).map((m) => m.section === "Sideboard" ? `${m.name} (sideboard)` : m.name);
    return names.length <= 2 ? `Used by ${names.join(" and ")}`
      : `Used by ${names.slice(0, 2).join(", ")} and ${plural(names.length - 2, "more card")}`;
  };
  const uncovered = (need) => need.cover && need.cover.state === "none";
  const kinds = needs.map((need) => String(need.name || "").replace(/\s+counters?$/i, ""));
  return el("details", { class: "deck-counters deck-tokens-group" },
    el("summary", {}, `Counters and dice: ${kinds.join(", ")}`,
      needs.some(uncovered) ? [" ", status("warn", "Not covered")] : null),
    el("ul", { class: "token-counters" }, needs.map((need) => el("li", { class: `token-counter token-counter-${need.group}` },
      el("b", { text: `${need.name}${where[need.group] || ""}` }),
      need.sideboard_only ? " (sideboard only)" : null,
      uncovered(need) ? [" ", diceCoverChip(need.cover)] : null,
      el("small", { class: "token-need-made", text: usedBy(need.made_by) }),
      need.cover && need.cover.words ? el("small", { class: "token-need-cover", text: need.cover.words }) : null))),
    counters.owned && counters.owned.words ? el("p", { class: "sub dice-owned", text: counters.owned.words }) : null,
    counters.note ? el("p", { class: "sub token-note", text: counters.note }) : null);
}

/** What Scryfall's links and the saved Forge games can't say, in one closed disclosure: cards that make
 * copies, cards that may make tokens no link names, how the needs are worked out, and where the suggested
 * counts come from (or why there are none). null when there's nothing to say. */
function tokenUnseenPart(t) {
  const copies = t.copies || [], unlisted = t.unlisted || [];
  const parts = [
    copies.length ? el("p", {}, el("b", { text: `Makes copies (${plural(copies.length, "card")}): ` }),
      `${copies.join(", ")}. Use a Copy token card, or any spare token, and say what it copies.`) : null,
    unlisted.length ? el("p", {}, el("b", { text: `May also make things Scryfall doesn't link (${plural(unlisted.length, "card")}): ` }),
      `${unlisted.join(", ")}. Their text mentions a token or reminder that isn't listed above.`) : null,
    t.note ? el("p", { class: "sub", text: t.note }) : null,
    typeof tokenPeaksPart === "function" ? tokenPeaksPart(t.forge) : null,      // E7-S08, token-peaks.js
  ].filter(Boolean);
  if (!parts.length) return null;
  return el("details", { class: "more token-note deck-tokens-more" }, el("summary", { text: "What Deck Lab can't see, and how it works these out" }), parts);
}

/** A built deck's packed token cards (its text's Token cards line, lib/api/deck_page.py _packed): what its
 * deck box holds, which the other decks count as in use, with "Change…" for whoever may change the deck.
 * faces (tokFacesUsed of the deck's needs) says of each double-sided card whether the deck needs both
 * sides or only one, which can be sleeved: those words are folded under the line. */
function deckPackedTokens(data, faces = null) {
  const p = data.tokens.packed;
  if (p.product) return productPackedTokens(data);
  const lines = p.lines || [];
  const sides = (line) => [...new Set(line.rows.map((row) => tokSides(row, faces)).filter(Boolean))];
  const label = (line) => !line.rows.length ? `${line.text} (no token card matches)` : line.text;
  const words = p.error ? `The Token cards line can't be read: ${p.error}`
    : lines.length ? `Packed: ${lines.map(label).join("; ")}`
    : p.written ? "Packed: no token cards." : "Packed token cards aren't recorded yet.";
  const sleeving = p.error ? [] : lines.filter((line) => line.rows.length && sides(line).length);
  const may = canEditDeck(data.summary) && (p.choices || []).length && !p.error;
  return el("div", { class: "deck-tokens-packed" },
    sleeving.length ? el("details", { class: "deck-tokens-packed-sides" }, el("summary", { class: "sub", text: words }),
      el("ul", { class: "token-grab" }, sleeving.map((line) => el("li", { text: `${line.text}: ${sides(line).join("; ")}` }))))
      : el("p", { class: p.error ? "box box-warn" : "sub", text: words }),
    may ? el("button", { type: "button", class: "btn btn-quiet", text: "Change packed token cards…",
      onclick: () => openPackedTokens(data) }) : null);
}

/** The sheet choosing a built deck's packed token cards: a count per token card it could use (at most what
 * other decks leave of it), saved as one change (POST /api/deck/token-cards). */
function openPackedTokens(data) {
  const p = data.tokens.packed, s = data.summary;
  const sheet = openSheet({ title: "Packed token cards" });
  const inputs = [];
  sheet.body.append(el("p", { class: "sub", text: "The token cards in this deck's box. Other decks count them as in use." }),
    el("ul", { class: "pack-plain deck-packed-choices" }, (p.choices || []).map((c) => {
      const id = `packed-${sheet.heading.id}-${c.row}`;
      const input = el("input", { id, type: "number", inputmode: "numeric", min: 0, max: c.free, step: 1,
        value: String(Math.min(c.packed, c.free)) });
      inputs.push([c, input]);
      const name = `${c.back ? `${c.front} / ${c.back}` : c.front}${c.set ? ` (${c.set.toUpperCase()} ${c.number})` : ""}`;
      const rest = c.free < c.quantity ? `, ${num(c.quantity - c.free)} in other decks` : "";
      return el("li", {}, el("label", { for: id, text: `${name}: ${plural(c.quantity, "card")}${rest}` }), " ", input);
    })));
  const message = el("p", { class: "box box-crit", hidden: true });
  sheet.body.append(message);
  const save = () => {
    const cards = [];
    for (const [c, input] of inputs) {
      const n = Number(input.value);
      if (!Number.isInteger(n) || n < 0 || n > c.free) {
        message.textContent = `Choose 0 to ${c.free} for ${c.front}.`;
        message.hidden = false;
        input.focus();
        return;
      }
      if (n) cards.push({ row: c.row, quantity: n });
    }
    apiWrite("/api/deck/token-cards", { id: s.id, expect: p.expect, tokens_sha256: p.tokens_sha256, cards })
      .then(() => {
        sheet.close();
        toast("Packed token cards saved");
        const here = parseHash();
        if (here.path === "deck" && addressDeckId(here.params.get("id") || "") === s.id) route();
      })
      .catch((e) => {
        if (!(e instanceof ApiError)) throw e;
        message.textContent = e.message;
        message.hidden = false;
      });
  };
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() },
    { text: "Save", kind: "primary", value: "save", onclick: save }]);
  return sheet;
}

/** A token need with its token cards to grab that read the same ("Dog / Beast ×1, Dog side", for two rows
 * whose printings aren't recorded) as one line with their copies added up. */
function mergedTokenCards(need) {
  const cards = need.cards || [];
  if (cards.length < 2) return need;
  const byWords = new Map();
  for (const card of cards) {
    const key = JSON.stringify([card.front, card.back || "", card.side || "", card.verdict || "", card.why || [],
      card.also_for || [], (card.shared || []).map((h) => h.deck || h.title)]);
    const same = byWords.get(key);
    if (same) same.quantity = (Number(same.quantity) || 0) + (Number(card.quantity) || 0);
    else byWords.set(key, { ...card });
  }
  return byWords.size === cards.length ? need : { ...need, cards: [...byWords.values()] };
}
