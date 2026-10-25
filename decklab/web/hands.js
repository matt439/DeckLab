/* Manual opening hands. Local, disposable practice; no inventory or deck writes. */
"use strict";

class OpeningHand {
  constructor(lines, { random = Math.random, freeFirst = false } = {}) {
    this.cards = [];
    for (const line of lines || []) {
      if (!Number.isInteger(line.qty) || line.qty < 1 || line.qty > 999) throw new Error("Invalid card quantity");
      for (let i = 0; i < line.qty; i++) this.cards.push({ ...line, copy: this.cards.length });
    }
    if (this.cards.length < 7) throw new Error("At least seven main-deck cards are needed to deal a hand.");
    this.random = random; this.freeFirst = freeFirst; this.phase = "idle";
    this.hand = []; this.library = []; this.mulligans = 0; this.draws = 0;
  }
  get bottomCount() { return Math.max(0, this.mulligans - (this.freeFirst ? 1 : 0)); }
  shuffle() {
    const deck = [...this.cards];
    for (let i = deck.length - 1; i > 0; i--) {
      const j = Math.floor(this.random() * (i + 1));
      [deck[i], deck[j]] = [deck[j], deck[i]];
    }
    this.hand = deck.splice(0, 7); this.library = deck; this.phase = "opening"; this.draws = 0;
  }
  deal() { this.mulligans = 0; this.shuffle(); }
  mulligan() {
    if (this.phase !== "opening" || this.bottomCount >= 7) return false;
    this.mulligans++; this.shuffle(); return true;
  }
  keep(indices) {
    if (this.phase !== "opening" || !Array.isArray(indices) || indices.length !== this.bottomCount
        || new Set(indices).size !== indices.length || indices.some(i => !Number.isInteger(i) || i < 0 || i >= 7)) return false;
    const bottom = indices.map(i => this.hand[i]);
    this.hand = this.hand.filter((_, i) => !indices.includes(i));
    this.library.push(...bottom); this.phase = "kept"; return true;
  }
  draw() {
    if (this.phase !== "kept" || !this.library.length) return null;
    const card = this.library.shift(); this.hand.push(card); this.draws++; return card;
  }
}

/** The Practice tab's "Deal a hand": deal seven from the main deck (commander, companion and sideboard stay
 * out), mulligan London-style, keep, then draw. The hand is sorted (spells by cost, lands last) with its land
 * and spell counts, and drawn as card pictures that open the viewer (the "hand" group). A Commander deck can
 * make the first mulligan free, as at a multiplayer table. */
function manualHandsSection(data) {
  const section = el("section", { class: "deck-section hands-section", id: "sec-hands", "aria-labelledby": "h-hands" },
    el("h2", { id: "h-hands", text: "Deal a hand" }));
  if (data.summary.id.startsWith(BOX_PREFIX)) {
    section.append(note("A Beginner Box half is only played shuffled with another half: deal a hand from one of its pairings."),
      pairingLinks(data.summary.id, "Its pairings:"));
    return section;
  }
  let shown = data, freeFirst = false, model = null, sequence = 0, loading = false;
  const commander = data.summary.kind === "commander" || data.summary.id.split("/").includes("commander");
  const body = el("div", { class: "hands-body" });
  const version = el("select", { "aria-label": "List to deal from" }, data.versions.map(v => el("option", {
    value: v, selected: v === data.version, text: listName(v) })));
  version.addEventListener("change", async () => {
    const request = ++sequence;
    loading = true; free.disabled = true;
    clear(body).append(loadingBox("Loading that list…"));
    try {
      const answer = await api(`/api/deck?id=${encodeURIComponent(data.summary.id)}&version=${version.value}&omit=matchups`);
      if (request !== sequence || !section.isConnected) return;
      shown = answer; version.value = answer.version; reset();
    } catch (error) {
      if (request === sequence && section.isConnected) {
        version.value = shown.version;
        clear(body).append(el("p", { role: "alert", text: `${error.message} The selected list is still the ${listName(shown.version, true)}.` }));
      }
    } finally {
      if (request === sequence) { loading = false; free.disabled = false; }
    }
  });
  const free = el("input", { type: "checkbox", onchange: event => {
    if (loading) { event.target.checked = freeFirst; return; }
    freeFirst = event.target.checked; reset();
  } });
  const settings = [
    data.versions.length > 1 ? el("label", { class: "field" }, el("span", { text: "Deal from" }), version) : null,
    commander ? el("label", { class: "choice hands-free" }, free, " First mulligan is free (multiplayer)") : null];
  if (settings.some(Boolean)) section.append(el("div", { class: "hands-settings" }, settings));
  section.append(body);
  function reset() {
    try { model = new OpeningHand(shown.sections.Deck, { freeFirst }); draw(); }
    catch (error) { clear(body).append(el("p", { class: "sub", text: error.message })); }
  }
  function draw() {
    const chosen = [];
    clear(body);
    if (model.phase === "idle") {
      body.append(el("div", { class: "empty hands-empty" },
        el("p", { text: `Shuffle the ${plural(model.cards.length, "card")} of the main deck and draw seven.` }),
        el("button", { class: "btn btn-primary", type: "button", text: "Deal seven",
          onclick: () => { model.deal(); draw(); } })));
      return;
    }
    const opening = model.phase === "opening";
    const statusLine = el("p", { class: "hands-status", role: "status", text: handStatus(model) });
    const selection = el("p", { class: "sub", role: "status" });
    const keep = el("button", { type: "button", class: "btn btn-primary", text: "Keep hand", disabled: model.bottomCount > 0 || null,
      onclick: () => { if (model.keep(chosen)) draw(); } });
    // Shown sorted; the model keeps the order it dealt (its indexes are what keep() takes).
    const order = model.hand.map((line, index) => ({ line, index })).sort((a, b) => handOrder(a.line, b.line));
    const hand = el("ul", { class: "hands-cards" }, order.map(({ line, index }) => {
      const tile = cardTile(line.card || null, { name: line.name, viewerGroup: "hand", caption: "In your hand" });
      const item = el("li", {}, tile);
      if (opening && model.bottomCount) {
        const pick = el("button", { class: "btn hands-bottom", type: "button", "aria-pressed": "false", text: "To bottom",
          "aria-label": `Put ${line.name} on the bottom`,
          onclick: () => {
            const at = chosen.indexOf(index);
            if (at >= 0) chosen.splice(at, 1); else if (chosen.length < model.bottomCount) chosen.push(index);
            const on = chosen.includes(index);
            pick.setAttribute("aria-pressed", String(on));
            pick.textContent = on ? "On bottom" : "To bottom";
            tile.classList.toggle("is-ticked", on);
            keep.disabled = chosen.length !== model.bottomCount;
            selection.textContent = `${chosen.length} of ${model.bottomCount} chosen. They go on the bottom in the order chosen.`;
          } });
        item.append(pick);
      }
      return item;
    }));
    body.append(statusLine, el("p", { class: "hands-counts sub", text: handCounts(model.hand) }), hand, selection,
      el("div", { class: "actions hands-actions" },
        opening ? keep : el("button", { type: "button", class: "btn btn-primary", text: "Draw next card", disabled: !model.library.length || null,
          onclick: () => { model.draw(); draw(); } }),
        opening ? el("button", { type: "button", class: "btn", text: "Mulligan", disabled: model.bottomCount >= 7 || null,
          onclick: () => { model.mulligan(); draw(); } }) : null,
        el("button", { type: "button", class: "btn btn-quiet", text: "New hand", onclick: () => { model.deal(); draw(); } })));
  }
  reset();
  return section;
}

/** The hand's state in words: "Opening seven. Keep or mulligan?", "Mulligan 2: choose 2 cards to put on the
 * bottom, then keep.", "Kept 6. Drew 2; 47 cards left in the library." */
function handStatus(model) {
  if (model.phase !== "opening") {
    const drew = model.draws ? ` Drew ${model.draws};` : "";
    return `Kept ${7 - model.bottomCount}.${drew} ${plural(model.library.length, "card")} left in the library.`;
  }
  if (!model.mulligans) return "Opening seven. Keep or mulligan?";
  if (!model.bottomCount) return "Free mulligan: a new seven. Keep or mulligan?";
  return `Mulligan ${model.mulligans}: choose ${plural(model.bottomCount, "card")} to put on the bottom, then keep.`;
}

/** "3 lands · 4 spells" for the cards in hand. */
function handCounts(hand) {
  const lands = hand.filter((line) => line.card && typeGroup(line.card) === "Lands").length;
  return `${plural(lands, "land")} · ${plural(hand.length - lands, "spell")}`;
}

/** A hand's order on screen: spells by mana value, then lands, each by name. */
function handOrder(a, b) {
  const land = (line) => (line.card && typeGroup(line.card) === "Lands" ? 1 : 0);
  return land(a) - land(b) || byCostThenName(a, b);
}
