/* The two-card combos a Commander deck is one card away from (E9-S25; lib/stats/commander.py
 * _near_combo_check, lib/api/near_combos.py): the Stats tab's "One card away" panel. Each combo names the
 * card to add, what the combo does, what it would do to the minimum bracket, an AUD estimate, and (only to a
 * viewer who sees the space's collection: the server sends "availability" to no one else) whether a copy is
 * free, on the way, in another deck or to buy. Whoever may change the deck adds the card to its Considering
 * list (E2-S23, saveConsidering), never straight into the lists. */
"use strict";

const NEAR_SHOWN = 8;       // combos shown before "Show all"
const NEAR_ORDER = { free: 0, on_the_way: 1, in_use: 2, to_buy: 3 };
const NEAR_STATUS = { free: ["good", "Free in the pool"], on_the_way: ["info", "On the way"],
  in_use: ["plain", "In another deck"], to_buy: ["outline", "To buy"] };

/** bracket.near_combos when the combo list could be read, else null (an older server, or no commander). */
function nearCombos(br) {
  const near = br && br.near_combos;
  return near && near.checked === true && Array.isArray(near.matches) ? near : null;
}

/** What adding the missing piece does to the bracket, or null when it changes nothing. */
function nearBracketWords(m, target) {
  if (!m.raises_minimum) return null;
  const over = target && m.minimum_with > target ? `, above the Bracket ${target} it aims for` : "";
  return `Adding it puts the deck at Bracket ${m.minimum_with} or higher${over}.`;
}

/** One combo: "Add <card>: with <piece>, <what it does>." then its marks and actions. */
function nearComboItem(m, data, editable) {
  const results = m.results || [];
  const what = results.slice(0, 2).join(", ") + (results.length > 2 ? ", …" : "");
  const others = (m.names || []).filter((name) => name !== m.missing);
  const item = el("li", { class: "near-combo" });
  const line = el("p", {}, "Add ", cardLink({ name: m.missing }, "near-combos", { inline: true }), ": with ");
  others.forEach((name, i) => {
    if (i) line.append(" and ");
    line.append(cardLink({ name }, "near-combos", { inline: true }));
  });
  const payoff = m.standalone === false && m.class !== "lock" && m.class !== "mass_land_denial" ? " Needs a payoff." : "";
  line.append(`${what ? `, ${what}` : ""}.${payoff} `,
    el("a", { href: m.url, target: "_blank", rel: "noopener", text: "Commander Spellbook" }));
  item.append(line);
  const marks = el("p", { class: "near-combo-marks" });
  if (m.availability && NEAR_STATUS[m.availability]) marks.append(status(...NEAR_STATUS[m.availability]), " ");
  marks.append(m.aud != null ? `About ${aud(m.aud)}.` : "No price.");
  const bracket = nearBracketWords(m, data.summary.target_bracket);
  if (bracket) marks.append(" ", status("warn", `Bracket ${m.minimum_with}`), ` ${bracket}`);
  item.append(marks);
  if (m.considering) item.append(el("p", { class: "sub", text: "On the Considering list." }));
  else if (editable) {
    item.append(el("button", { type: "button", class: "btn btn-quiet", text: "Add to Considering",
      onclick: async (event) => {
        // Off while it saves; a refused save (its toast says why) turns it back on to try again.
        const button = event.currentTarget;
        button.disabled = true;
        if (!await saveConsidering(data, { action: "add", line: { name: m.missing, qty: 1 } })) button.disabled = false;
      } }));
  }
  return item;
}

/** The Stats tab's "One card away" panel, or null when there's nothing to show (no near-combo answer). */
function nearCombosPanel(data) {
  const br = data.stats && data.stats.commander && data.stats.commander.bracket;
  const near = nearCombos(br);
  if (!near) return null;
  const s = data.summary;
  const editable = !s.read_only && canEditDeck(s) && data.version === "target" && !!(data.considering && data.considering.sha256);
  const panel = el("section", { class: "panel near-combos", "aria-labelledby": "h-near-combos" },
    el("h3", { id: "h-near-combos", text: `One card away: ${near.total}` }),
    el("p", { class: "sub", text: "Two-card combos with one piece in the deck. The other fits the commander's colours " +
      "and isn't banned in Commander." }));
  if (!near.matches.length) {
    panel.append(el("p", { text: "None found in Commander Spellbook's two-card combos." }));
    return panel;
  }
  // Free pieces first, then on the way, in another deck and to buy; the server's order (most serious first) within each.
  const sorted = near.matches.map((m, i) => [m, i]).sort(([a, i], [b, j]) =>
    ((NEAR_ORDER[a.availability] ?? 4) - (NEAR_ORDER[b.availability] ?? 4)) || i - j).map(([m]) => m);
  const list = el("ul", { class: "near-combo-list" });
  const show = (count) => list.replaceChildren(...sorted.slice(0, count).map((m) => nearComboItem(m, data, editable)));
  show(NEAR_SHOWN);
  panel.append(list);
  if (sorted.length > NEAR_SHOWN) {
    const more = el("button", { type: "button", class: "btn btn-quiet", text: `Show all ${sorted.length}`,
      onclick: () => { show(sorted.length); more.remove(); } });
    panel.append(more);
  }
  if (near.total > near.matches.length) {
    panel.append(el("p", { class: "sub", text: `Showing the ${near.matches.length} most serious of ${near.total}.` }));
  }
  const p = near.prices;
  panel.append(el("p", { class: "sub", text: p
    ? `Prices are estimates for the cheapest non-foil printing (Scryfall ${p.price_date}; 1 USD = ${p.rate} AUD, ECB ${p.rate_date}).`
    : "No prices: the exchange rate couldn't be read." }));
  return panel;
}
