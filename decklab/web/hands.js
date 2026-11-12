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
  // decision: what was last chosen for a hand and what the deck's keep rule says of it (E4-S09); shown only
  // after Keep or Mulligan, and forgotten when a new hand is dealt.
  let shown = data, freeFirst = false, model = null, sequence = 0, loading = false, decision = null;
  const commander = data.summary.kind === "commander" || data.summary.id.split("/").includes("commander");
  const body = el("div", { class: "hands-body" });
  const version = el("select", { "aria-label": "List to deal from" }, data.versions.map(v => el("option", {
    value: v, selected: v === data.version, text: listName(v) })));
  // A list that couldn't be loaded: said above the hand, which stays as it was, with Try again.
  const notice = el("div", { class: "hands-notice" });
  async function loadVersion(wanted) {
    const request = ++sequence;
    loading = true; free.disabled = true;
    clear(notice);
    clear(body).append(loadingBox("Loading that list…"));
    try {
      const answer = await api(`/api/deck?id=${encodeURIComponent(data.summary.id)}&version=${wanted}&omit=matchups`);
      if (request !== sequence || !section.isConnected) return;
      shown = answer; version.value = answer.version; reset();
    } catch (error) {
      if (request === sequence && section.isConnected) {
        version.value = shown.version;
        if (model) draw(); else reset();
        notice.append(el("div", { class: "note note-warn", role: "alert" },
          el("div", {}, el("p", { text: `${error.message} The selected list is still the ${listName(shown.version, true)}.` })),
          el("button", { type: "button", class: "btn btn-quiet", text: "Try again", onclick: () => {
            if (!loading) { version.value = wanted; loadVersion(wanted); }
          } })));
      }
    } finally {
      if (request === sequence) { loading = false; free.disabled = false; }
    }
  }
  version.addEventListener("change", () => loadVersion(version.value));
  const free = el("input", { type: "checkbox", onchange: event => {
    if (loading) { event.target.checked = freeFirst; return; }
    freeFirst = event.target.checked; reset();
  } });
  const settings = [
    data.versions.length > 1 ? el("label", { class: "field" }, el("span", { text: "Deal from" }), version) : null,
    commander ? el("label", { class: "choice hands-free" }, free, " First mulligan is free (multiplayer)") : null];
  if (settings.some(Boolean)) section.append(el("div", { class: "hands-settings" }, settings));
  section.append(notice, body);
  function reset() {
    decision = null;
    try { model = new OpeningHand(shown.sections.Deck, { freeFirst }); draw(); }
    catch (error) {
      // No retry: the list itself is what can't be dealt.
      model = null;
      clear(body).append(note(`This list can't be dealt from: ${error.message}`));
    }
  }
  function draw() {
    const chosen = [];
    clear(body);
    if (model.phase === "idle") {
      body.append(el("div", { class: "empty hands-empty" },
        el("p", { text: `Shuffle the ${plural(model.cards.length, "card")} of the main deck and draw seven.` }),
        el("button", { class: "btn btn-primary", type: "button", text: "Deal seven",
          onclick: () => { decision = null; model.deal(); draw(); } })));
      return;
    }
    const opening = model.phase === "opening";
    const statusLine = el("p", { class: "hands-status", role: "status", text: handStatus(model) });
    const selection = el("p", { class: "sub", role: "status" });
    const keep = el("button", { type: "button", class: "btn btn-primary", text: "Keep hand", disabled: model.bottomCount > 0 || null,
      onclick: () => {
        const free = model.freeFirst && model.mulligans === 0;
        if (!model.keep(chosen)) return;
        decision = { choice: "keep", result: keepVerdict(model.hand, shown.keep_rule, { free }) };
        draw();
      } });
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
          onclick: () => {
            const result = keepVerdict(model.hand, shown.keep_rule,
              { free: model.freeFirst && model.mulligans === 0, bottom: model.bottomCount });
            if (model.mulligan()) decision = { choice: "mulligan", result };
            draw();
          } }) : null,
        el("button", { type: "button", class: "btn btn-quiet", text: "New hand",
          onclick: () => { decision = null; model.deal(); draw(); } })));
    const advice = handAdvice(decision, shown);
    if (advice) body.append(advice);
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

/** Beside the hand: after Keep or Mulligan, whether the deck's keep rule agrees and why, with its source;
 * and the deck Notes' mulligan or opening-hand topic, whenever a hand is dealt. Null when there's neither. */
function handAdvice(decision, data) {
  const verdict = decision ? keepVerdictBox(decision, data.keep_rule) : null;
  const notes = mulliganNotes(data.guide);
  if (!verdict && !notes) return null;
  return el("aside", { class: "hands-advice", "aria-label": "Keep or mulligan advice" }, verdict, notes);
}

function keepVerdictBox({ choice, result }, rule) {
  const lead = choice === "keep" ? "Your kept hand" : "Your last hand";
  if (!result) return el("div", { class: "hands-verdict", role: "status" },
    el("p", { text: `${lead}: the deck's keep rule couldn't be loaded, so there's nothing to compare it with.` }));
  const source = result.free ? rule.free_source : rule.source;
  return el("div", { class: `hands-verdict hands-verdict-${result.verdict}`, role: "status" },
    el("p", { class: "hands-verdict-agree", text: `${lead}: ${keepAgreement(choice, result)}` }),
    el("p", { class: "hands-verdict-why", text: result.text }),
    source && source.url ? el("p", { class: "sub" }, "Rule: ",
      el("a", { href: source.url, target: "_blank", rel: "noopener noreferrer", text: source.title }),
      ", as the Practice tab's simulated games use it. It counts lands only.") : null);
}

/** The deck Notes' topics about mulligans or a good opening hand (guide.py's topics), folded, or null. */
function mulliganNotes(guide) {
  const parts = (guide && guide.sections || []).filter(part => /^(?:mulligans?|(?:a good )?opening hand)\b/i.test(part.title));
  if (!parts.length) return null;
  return el("div", { class: "hands-notes" },
    el("h3", { text: "From this deck's notes" }),
    guide.changed_on ? el("p", { class: "note note-warn", text: `The list changed on ${guide.changed_on}, so these notes may be out of date.` }) : null,
    parts.map((part, i) => el("details", { class: "guide-topic", open: i === 0 || null }, el("summary", {}, el("h4", { text: part.title })),
      typeof guideMarkdown === "function" ? guideMarkdown(part.markdown) : el("p", { text: part.markdown }))));
}

/** Whether the rule counts a card in hand as a land: the server's keep_land (a land or a spell // land card,
 * as the simulation counts), else the card's type. */
function keepLand(line) {
  if (typeof line.keep_land === "boolean") return line.keep_land;
  return !!(line.card && typeGroup(line.card) === "Lands");
}

/** What the deck's keep rule (data.keep_rule: the practice games' Karsten rule) says of a hand, or null with no
 * rule. hand: the cards held; bottom: the cards the rule would still put on the bottom first (a hand judged when
 * Mulligan is chosen: lands while there are more than rule.bottom_lands_above, then spells); free: the free first
 * seven of a multiplayer game, which has its own range. Four cards or fewer always keep; a land count at either
 * end of the range is "borderline", never a firm answer. The words name lands only.
 * {verdict: "keep"|"borderline"|"mulligan", lands, size, low, high, free, text}. */
function keepVerdict(hand, rule, { free = false, bottom = 0 } = {}) {
  if (!rule || !rule.sizes || !Array.isArray(hand)) return null;
  let lands = hand.filter(keepLand).length, spells = hand.length - lands;
  const above = Number.isInteger(rule.bottom_lands_above) ? rule.bottom_lands_above : 3;
  for (let i = 0; i < bottom; i++) {
    if (lands && (lands > above || !spells)) lands--; else if (spells) spells--;
  }
  const size = lands + spells;
  const counted = `${plural(lands, "land")} in ${plural(size, "card")}`;
  const said = bottom ? `after putting ${plural(bottom, "card")} on the bottom as the rule does, ${counted}` : counted;
  if (size <= rule.always_keep) {
    return { verdict: "keep", lands, size, low: null, high: null, free: false,
      text: `Keep: ${said}. The rule always keeps ${rule.always_keep} cards or fewer.` };
  }
  const range = free ? rule.free : rule.sizes[String(size)];
  if (!Array.isArray(range)) return null;
  const [low, high] = range;
  const keeps = free ? `A free first seven is kept only with ${low} to ${high} lands.`
    : `The rule keeps ${size} cards with ${low} to ${high} lands.`;
  let verdict, text;
  if (lands < low || lands > high) {
    verdict = "mulligan";
    text = `Mulligan: ${said} is too ${lands < low ? "few" : "many"}. ${keeps}`;
  } else if (lands === low || lands === high) {
    verdict = "borderline";
    text = `Borderline: ${said} is the ${lands === low ? "fewest" : "most"} the rule keeps, so it's a close call. ${keeps}`;
  } else {
    verdict = "keep";
    text = `Keep: ${said}. ${keeps}`;
  }
  return { verdict, lands, size, low, high, free, text };
}

/** "you kept, and the rule agrees." for a choice ("keep" or "mulligan") against keepVerdict's answer. */
function keepAgreement(choice, result) {
  if (result.verdict === "borderline") return "the rule calls this hand borderline, so either choice is fair.";
  const kept = choice === "keep";
  if ((result.verdict === "keep") === kept) return kept ? "you kept, and the rule agrees." : "you took a mulligan, and the rule agrees.";
  return kept ? "you kept; the rule would have taken a mulligan." : "you took a mulligan; the rule would have kept.";
}

/** "3 lands · 4 spells" for the cards in hand, counted as the keep rule counts them (a spell // land card is a
 * land), so the counts never contradict the verdict beside them (E4-S09). */
function handCounts(hand) {
  const lands = hand.filter(keepLand).length;
  return `${plural(lands, "land")} · ${plural(hand.length - lands, "spell")}`;
}

/** A hand's order on screen: spells by mana value, then lands, each by name. */
function handOrder(a, b) {
  const land = (line) => (line.card && typeGroup(line.card) === "Lands" ? 1 : 0);
  return land(a) - land(b) || byCostThenName(a, b);
}
