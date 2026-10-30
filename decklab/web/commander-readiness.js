/* The Commander pregame conversation, from the displayed list's existing stats.
 * These are detected cards and a declared aim, never a certificate of power level. */
"use strict";

function commanderDataNote(br) {
  const data = br.data || {};
  return el("div", { class: "commander-data" },
    el("p", { class: "sub", text: `Scryfall card data (Game Changers and ban list): ${data.cards_date || "date unknown"}. ` +
      `Community effect tags: ${data.tags_date || "date unknown"}. ` +
      `Commander Spellbook's two-card combos: ${data.combos_date || "date unknown"}.` }),
    (data.dates_stale !== undefined ? data.dates_stale !== false : data.stale !== false) ? el("p", { class: "sub", text: "These checks may be out of date. " +
      `A data date is unknown, in the future or more than ${data.max_age_days || 7} days old; check the current lists before playing.` }) : null,
    ...officialNotes(data));
}

/** What Wizards' latest Commander announcement says about these checks (bracket.data, E9-S24): announced
 * after the card data, after the bracket rules, or unknown. Never says the lists are current. */
function officialNotes(data) {
  const notes = [];
  const a = data.official_announcement;
  const link = (text) => a && a.url ? el("a", { href: a.url, target: "_blank", rel: "noopener", text }) : text;
  if (a && a.date && data.official_unknown === false) notes.push(el("p", { class: "sub" }, "Wizards' latest Commander announcement: ", link(a.date),
    data.official_checked ? ` (last checked ${data.official_checked}).` : "."));
  if (a && data.cards_older_than_announcement) notes.push(el("p", { class: "sub" }, "Wizards announced a Commander change on ",
    link(a.date), `, after this card data (${data.cards_date || "date unknown"}); update the card data.`));
  if (a && data.rules_older_than_announcement) notes.push(el("p", { class: "sub" }, "Deck Lab's bracket rules are older than Wizards' ",
    link(`${a.date} announcement`), ", so they may be out of date."));
  if (data.official_unknown !== false) notes.push(el("p", { class: "sub", text: "The date of Wizards' latest Commander announcement is unknown " +
    `(${data.official_checked ? `last checked ${data.official_checked}` : "never checked"}), so these checks can't say they're current.` }));
  return notes;
}

/** The combo list's answer (bracket.combos): checked, with its date, or null when it couldn't be read
 * (or the server is older than the check). Not checked is never "none found". */
function comboCheck(br) {
  const c = br && br.combos;
  if (!c || c.checked !== true || !Array.isArray(c.matches)) return null;
  return { matches: c.matches, date: (c.list_date || "").slice(0, 10) || "an unknown date" };
}

/** One two-card combo: its pieces as card links joined with " + ", what it does in short, whether it needs
 * a payoff or counts for the bracket, and a link to it on Commander Spellbook. */
function comboItem(m, group) {
  const item = el("li", {});
  (m.names || []).forEach((name, i) => {
    if (i) item.append(" + ");
    item.append(cardLink({ name }, group, { inline: true }));
  });
  item.append(`${comboWords(m)} `,
    el("a", { href: m.url, target: "_blank", rel: "noopener", text: "Commander Spellbook" }));
  return item;
}

/** What a two-card combo does in short and whether it needs a payoff or counts for the bracket, after its
 * pieces (": Infinite damage, Infinite lifegain, …. None in Brackets 1-2."). */
function comboWords(m) {
  const results = m.results || [];
  const what = results.slice(0, 2).join(", ") + (results.length > 2 ? ", …" : "");
  // Spellbook calls a lock's "Lock" a helper result, but a lock needs nothing more.
  const note = m.floor === 4 ? " Counts as mass land denial." : m.raises_floor ? " None in Brackets 1-2."
    : m.standalone === false && m.class !== "lock" && m.class !== "mass_land_denial" ? " Needs a payoff." : "";
  return `${what ? `: ${what}.` : "."}${note}`;
}

/** What the two-card combo check found, for What opponents will face, (unlabelled, under its own check
 * line) the Stats tab's Commander rules and (item drawing each combo as text) the printed play sheet. */
function comboFindings(br, group, labelled = true, item = (m) => comboItem(m, group)) {
  const check = comboCheck(br);
  const line = (text) => el("p", {}, labelled ? el("b", { text: "Two-card combos: " }) : null,
    labelled ? text : text[0].toUpperCase() + text.slice(1));
  if (!check) return line("not checked (combo list unavailable).");
  if (!check.matches.length) return line(`none found in Commander Spellbook's two-card combos (list of ${check.date}).`);
  return el("div", {},
    line(`the list holds both pieces of ${check.matches.length === 1 ? "this combo" : `these ${check.matches.length} combos`} ` +
      `(Commander Spellbook's two-card combos, list of ${check.date}).`),
    el("ul", { class: "commander-combos" }, check.matches.map(item)));
}

/** The shown list's pregame facts (E9-S05), or null when its Commander checks weren't loaded: the stats'
 * commander part (k) and bracket answer (br), the effect groups, those found, cards without data, the combo
 * check, the combos raising the floor and the lead sentence's words. The page and the printed play sheet
 * (commanderPrintPart) both read it. */
function commanderTableFacts(data) {
  const k = data.stats && data.stats.commander, br = k && k.bracket;
  if (!br) return null;
  const groups = [["Game Changers", br.game_changers], ["Mass land denial", br.mass_land_denial], ["Extra turns", br.extra_turns]];
  const found = groups.filter(([, list]) => list && list.length);
  const unknown = br.unknown_cards || [...new Set((data.stats.unresolved || [])
    .filter((u) => u.section !== "Sideboard").map((u) => u.name))];
  const combos = comboCheck(br);
  const raising = combos ? combos.matches.filter((m) => m.raises_floor) : [];
  const incomplete = groups.some(([, list]) => list == null) || unknown.length > 0 || !combos;
  const target = data.summary.target_bracket;
  let lead = target ? `Aims for Bracket ${target}` : "No target bracket set";
  // A combo's floor is never called a requirement: whether it's intended isn't checked. cards_minimum is the
  // minimum without the combos (an older server without it: the whole minimum, worded as before).
  const bar = target || 1;
  const cardsMinimum = typeof br.cards_minimum === "number" ? Math.min(br.cards_minimum, br.minimum) : br.minimum;
  if (cardsMinimum > bar) lead += `; the cards found require at least Bracket ${cardsMinimum}`;
  if (br.minimum > Math.max(cardsMinimum, bar) && raising.length) {
    lead += `${cardsMinimum > bar ? ", and" : ";"} ${raising.length === 1 ? "a two-card combo it holds puts" : "the two-card combos it holds put"} ` +
      `it at Bracket ${br.minimum} or higher, unless ${raising.length === 1 ? "the combo isn't" : "they aren't"} intended`;
  }
  if (!found.length && !raising.length) lead += incomplete ? ": the card checks are incomplete."
    : combos.matches.length ? ": no Game Changers, extra turns or mass land denial found; the two-card combos it holds don't raise the bracket."
      : ": no Game Changers, extra turns, mass land denial or two-card combos found.";
  else lead += ".";
  return { k, br, groups, found, unknown, combos, raising, target, lead };
}

/** The lead sentence with the cards found and the floor-raising combos named, each name drawn by name(). */
function commanderTableSentence(facts, name) {
  const sentence = el("p", { class: "commander-table-summary", text: facts.lead });
  for (const [label, list] of facts.found) {
    sentence.append(" ", label, ": ");
    const unique = [...new Map(list.map((entry) => [entry.name, entry])).values()];
    unique.forEach((entry, i) => {
      if (i) sentence.append(", ");
      sentence.append(name(entry.name));
    });
    sentence.append(".");
  }
  if (facts.raising.length) {
    sentence.append(" Holds both pieces of ", facts.raising.length === 1 ? "a two-card combo" : "two-card combos", ": ");
    facts.raising.forEach((m, i) => {
      if (i) sentence.append(", ");
      (m.names || []).forEach((piece, j) => {
        if (j) sentence.append(" + ");
        sentence.append(name(piece));
      });
    });
    sentence.append(".");
  }
  return sentence;
}

const COMMANDER_CHECK_LIMITS = "Only two-card combos from Commander Spellbook's list are checked, and the list can miss some. " +
  "Combos of three or more cards, combos needing a card that isn't named, chained or repeated extra turns, " +
  "how quickly the deck wins and your intent aren't checked. " +
  "Agree on the game with the table; these card checks alone don't establish a bracket.";

function commanderReadiness(data) {
  if (data.summary.kind !== "commander") return null;
  const heading = el("h2", { id: "h-commander-table", text: "At the Commander table" });
  const section = el("section", { class: "deck-section commander-readiness", "aria-labelledby": "h-commander-table" }, heading);
  add(section, [commanderNightPart(data)]);
  const facts = commanderTableFacts(data);
  if (!facts) {
    section.append(note("Commander checks are unavailable, so check this list before naming a bracket."));
    return section;
  }
  const { k, br, groups, found, unknown, combos, target } = facts;
  section.append(commanderTableSentence(facts, (name) => cardLink({ name }, "commander-readiness", { inline: true })));
  if (!k.ok) section.append(el("p", { class: "sub", text: "Deck rules need attention before this list can be played; see Stats." }));
  if (unknown.length) section.append(el("p", { class: "sub", text: `Cards without data: ${unknown.join(", ")}. The checks are incomplete.` }));
  const effects = el("details", { class: "more" }, el("summary", { text: "What opponents will face" }));
  if (found.length || (combos && combos.matches.length)) effects.open = true;
  for (const [label, list] of groups) {
    effects.append(el("div", {}, el("p", {}, el("b", { text: `${label}: ` }),
      list == null ? "not checked (effect data unavailable)." : list.length ? null : "none found in the checked cards."),
      list && list.length ? cardNames(list) : null));
  }
  effects.append(comboFindings(br, "commander-readiness"));
  effects.append(el("p", { class: "sub", text: "Mass land denial means removing or locking down many lands. " +
    "Community tags can miss cards or flag effects you don't intend to use." }));
  section.append(effects,
    el("p", { class: "sub", text: COMMANDER_CHECK_LIMITS }),
    commanderDataNote(br));
  if (target === 2) section.append(el("p", { class: "sub", text: "Bracket 2 aims for a straightforward, social game with time to develop; " +
    "expect at least eight turns before a win or loss. A few extra-turn cards can fit, but chaining them cannot." }));
  const source = data.stats.sources && data.stats.sources["wizards-commander"];
  if (source) section.append(el("a", { href: source.url, target: "_blank", rel: "noopener", text: "Commander brackets and Game Changers" }));
  return section;
}

/** The printed play sheet's At the table (E9-S27), for a Commander deck only: the pregame sentence, what
 * opponents will face and the two-card combos the shown list holds, as plain text from the facts the page
 * already loaded, with the card data's dates. Never fetches; facts that weren't loaded are said to be so.
 * Nothing here reads the inventory (the one-card-away combos are left out). */
function commanderPrintPart(data) {
  if (data.summary.kind !== "commander") return [];
  const heading = el("h2", { text: "At the table" });
  const facts = commanderTableFacts(data);
  if (!facts) return [heading, el("p", { class: "print-warning", text: "The Commander checks weren't loaded, so this sheet " +
    "can't say what opponents will face. Check the list before naming a bracket." })];
  const { k, groups, unknown } = facts;
  const parts = [heading, commanderTableSentence(facts, (name) => name)];
  if (!k.ok) parts.push(el("p", { class: "print-warning", text: "Deck rules need attention before this list can be played." }));
  if (unknown.length) parts.push(el("p", { text: `Cards without data: ${unknown.join(", ")}. The checks are incomplete.` }));
  for (const [label, list] of groups) parts.push(el("p", {}, el("b", { text: `${label}: ` }),
    list == null ? "not checked (effect data unavailable)."
      : list.length ? `${[...new Set(list.map((entry) => entry.name))].join(", ")}.` : "none found in the checked cards."));
  // Each combo as text: on paper there's no viewer or link to follow.
  parts.push(comboFindings(facts.br, null, true, (m) => el("li", { text: `${(m.names || []).join(" + ")}${comboWords(m)}` })));
  parts.push(el("p", { text: COMMANDER_CHECK_LIMITS }), commanderDataNote(facts.br));
  return parts;
}
