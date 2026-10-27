/* Compare two decks (E1-S13, its first slice): #/compare?a=<deck id>&b=<deck id>[&av=target|owned&bv=...], the
 * two lists' stats side by side: their counts in brief, their mana curves on one scale, their colours and colour
 * sources, and their card types. It reads each deck as its own page does (GET /api/deck, the viewer's rights),
 * so a deck the viewer may not see answers as missing and the page shows that instead. Read-only: nothing here
 * changes either deck. The way in is a deck page's More, "Compare with…" (openCompareChooser), which lists the
 * decks the viewer sees (GET /api/decks) and, for a deck with both lists, its own other list.
 *
 * The cards both lists want and how the two have done against each other are the story's later slices.
 */
"use strict";

// The card types in the order the Stats tab lists them (lib/stats _types).
const COMPARE_TYPES = ["creature", "instant", "sorcery", "artifact", "enchantment", "planeswalker", "battle", "land"];

/** The compare page's address: deck a's list av against deck b's list bv. */
function compareHref(a, b, av = "target", bv = "target") {
  const q = new URLSearchParams({ a, b });
  if (av === "owned") q.set("av", "owned");
  if (bv === "owned") q.set("bv", "owned");
  return `#/compare?${q}`;
}

function showCompare(params, token) {
  const side = (key) => ({ id: addressDeckId(params.get(key)), version: params.get(`${key}v`) === "owned" ? "owned" : "target" });
  const a = side("a"), b = side("b");
  const url = (s) => `/api/deck?id=${encodeURIComponent(s.id)}&version=${s.version}&omit=matchups`;
  load([url(a), url(b)], token, (sides) => compareDraw(sides),
    { title: "These decks couldn't be compared", back: ["#/library", "Back to the library"] });
}

/** What a side is called: the deck's title, or, comparing a deck's two lists, the list's name. */
function compareLabel(data, sameDeck) {
  return sameDeck ? listName(data.version) : data.summary.title;
}

function compareDraw(sides) {
  const [a, b] = sides;
  const sameDeck = a.summary.id === b.summary.id;
  const labels = sides.map((d) => compareLabel(d, sameDeck));
  setTitle(sameDeck ? `${a.summary.title}: its two lists` : `${a.summary.title} and ${b.summary.title}`);
  // The card names this page shows open the card viewer with the two lists' cards.
  state.cards = new Map();
  for (const d of sides) {
    for (const lines of Object.values(d.sections || {})) {
      for (const line of lines) if (line.card && !state.cards.has(line.card.name)) state.cards.set(line.card.name, line.card);
    }
  }
  const swap = compareHref(b.summary.id, a.summary.id, b.version, a.version);
  add($("#main"), [
    pageHead({ crumb: [deckHref(a.summary.id, a.version), a.summary.title], title: routeH1("compare"),
      description: "Their stats side by side. Nothing here changes either deck.",
      more: [{ label: "Swap sides", href: swap },
        { label: "Compare with another deck…", onclick: () => openCompareChooser(a) }] }),
    el("div", { class: "compare-heads" }, sides.map((d, i) => compareHead(d, labels[i], sameDeck))),
    warningsBox(compareNotes(sides, labels), "About these stats"),
    compareBrief(sides, labels),
    compareCurves(sides, labels),
    compareColours(sides, labels),
    compareTypes(sides, labels)]);
  drawCharts();
}

/** A side's head: its colours, its title (a link to its page), its format, list and card counts. */
function compareHead(data, label, sameDeck) {
  const s = data.summary;
  const colours = deckColourPieces(Array.isArray(s.colors) ? s.colors : deckPageColours(data));
  const { main, side } = compareCounts(data);
  const facts = [s.format, data.versions && data.versions.length > 1 && !sameDeck ? listName(data.version) : null,
    plural(main, "card"), side ? `${num(side)} in the sideboard` : null].filter(Boolean);
  return el("div", { class: "compare-head" },
    colours ? colours.pips(20) : null,
    el("a", { class: "compare-title", href: deckHref(s.id, data.version), text: sameDeck ? `${s.title}: ${label}` : label }),
    el("p", { class: "compare-facts", text: facts.join(" · ") }));
}

/** The list's cards: {main: the commander and main deck, side: the sideboard}. */
function compareCounts(data) {
  const count = (names) => names.reduce((n, name) => n + (data.sections?.[name] || []).reduce((m, l) => m + (l.qty || 0), 0), 0);
  return { main: count(["Commander", "Deck"]), side: count(["Sideboard"]) };
}

/** Why a side's stats are missing or partial, named after the side. */
function compareNotes(sides, labels) {
  const notes = [];
  sides.forEach((d, i) => {
    const st = d.stats;
    if (!st) notes.push(`${labels[i]}'s stats couldn't be worked out: its deck page says why.`);
    else if (st.unresolved && st.unresolved.length) {
      notes.push(`Left out of ${labels[i]}'s stats (not Scryfall card names): ` +
        `${st.unresolved.map((u) => `${u.qty} ${u.name}`).join(", ")}.`);
    }
  });
  return notes;
}

/** A table of rows, one per figure: [what, a's cell, b's cell], under the two sides' names. */
function compareTable(caption, labels, rows) {
  // A figure a side doesn't have: a dash, read out as "None".
  const cell = (value) => (value == null || value === ""
    ? [el("span", { "aria-hidden": "true", text: "–" }), el("span", { class: "sr-only", text: "None" })] : value);
  return el("table", { class: "data compare-table" },
    el("caption", { class: "sr-only", text: caption }),
    el("colgroup", {}, el("col", { class: "c-what" }), el("col"), el("col")),
    el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "" }),
      labels.map((label) => el("th", { scope: "col", class: "num", text: label })))),
    el("tbody", {}, rows.filter(Boolean).map(([what, ...cells]) => el("tr", {},
      el("th", { scope: "row", text: what }),
      cells.map((value) => el("td", { class: "num" }, cell(value)))))));
}

/** A section of the page: its heading and parts. */
function comparePart(id, title, ...parts) {
  return el("section", { class: "panel compare-part", "aria-labelledby": id },
    el("h2", { id, text: title }), parts);
}

/** In brief: the figures the Stats tab's verdict strip leads with, side by side. */
function compareBrief(sides, labels) {
  const of = (fn) => sides.map((d) => (d.stats ? fn(d.stats, d) : null));
  const lands = (st) => {
    const l = st.lands;
    if (!l) return null;
    return el("span", {}, num(l.effective), l.recommended != null
      ? el("small", { class: "compare-hint", text: ` formula ${num(l.recommended, 1)}` }) : null);
  };
  const sources = (st) => {
    const c = st.colours;
    if (!c || !c.colours || !c.colours.length) return "No coloured mana";
    const short = c.colours.filter((x) => x.ok === false);
    if (short.length) return status("warn", `Short: ${short.map((x) => x.name).join(", ")}`);
    return c.colours.every((x) => x.ok != null) ? "Enough" : "Not checked";
  };
  const commander = sides.some((d) => d.stats && d.stats.commander);
  return comparePart("h-compare-brief", "In brief", compareTable("The two lists in brief", labels, [
    ["Cards", ...sides.map((d) => num(compareCounts(d).main))],
    ["Average mana value", ...of((st) => (st.curve && st.curve.average_mv != null ? num(st.curve.average_mv) : null))],
    ["Lands", ...of(lands)],
    ["Creatures", ...of((st) => (st.curve ? num(st.curve.creatures) : null))],
    ["Other spells", ...of((st) => (st.curve ? num(st.curve.noncreatures) : null))],
    ["Colour sources", ...of(sources)],
    commander ? ["Bracket", ...of((st) => st.commander?.bracket?.label || null)] : null]));
}

/** Both mana curves on one scale (a phone stacks them), each with its bars' cards, and the two as one table. */
function compareCurves(sides, labels) {
  const curves = sides.map((d) => (d.stats && d.stats.curve) || null);
  const top = Math.max(1, ...curves.flatMap((c) => (c ? c.buckets.map((b) => b.total) : [])));
  const charts = el("div", { class: "compare-charts" }, curves.map((curve, i) => compareCurve(curve, labels[i], top)));
  const shown = curves.find(Boolean);
  const table = shown ? el("details", { class: "more" }, el("summary", { text: "The curves as a table" }),
    compareTable("Cards at each mana value", labels, shown.buckets.map((b, at) =>
      [`Mana value ${b.mv}`, ...curves.map((c) => (c ? num(c.buckets[at]?.total || 0) : null))]))) : null;
  return comparePart("h-compare-curve", "Mana curve",
    el("ul", { class: "legend", "aria-label": "Legend" },
      el("li", {}, el("span", { class: "swatch", style: "background: var(--series-1)" }), "Creatures"),
      el("li", {}, el("span", { class: "swatch", style: "background: var(--series-2)" }), "Other spells"),
      el("li", {}, el("span", { class: "swatch-line" }), "Average")),
    charts, table);
}

function compareCurve(curve, label, top) {
  const figure = el("div", { class: "compare-chart" }, el("h3", { text: label }));
  if (!curve) {
    figure.append(el("p", { class: "sub", text: "No curve: the stats couldn't be worked out." }));
    return figure;
  }
  const chart = el("div", { class: "chart" });
  const detail = el("div", { class: "chart-detail", "aria-live": "polite" },
    noneSelected("Tap or point at a bar to list its cards."));
  let active = -1;
  const show = (i) => {
    active = i;
    const b = curve.buckets[i];
    for (const g of chart.querySelectorAll(".col")) g.classList.toggle("active", Number(g.dataset.i) === i);
    add(clear(detail), [el("p", {}, el("b", { text: `Mana value ${b.mv}: ${plural(b.total, "card")}` })),
      b.cards && b.cards.length ? cardNames(b.cards) : null]);
  };
  chartJobs.push([chart, (width) => {
    drawCurve(chart, curve, width, show, top);
    if (active >= 0) show(active);
  }]);
  figure.append(chart, detail);
  return figure;
}

/** Each side's colour identity, then every colour (or group) either side's spells need: the sources it has
 * against the number its hardest card needs, Short where it falls short. */
function compareColours(sides, labels) {
  const keys = [];
  for (const d of sides) {
    for (const c of d.stats?.colours?.colours || []) if (!keys.some((k) => k.colours === c.colours)) keys.push(c);
  }
  const identity = (d) => {
    const pieces = deckColourPieces(Array.isArray(d.summary.colors) ? d.summary.colors : deckPageColours(d));
    return pieces ? pieces.pips(16) : null;
  };
  const sourceCell = (d, key) => {
    const row = (d.stats?.colours?.colours || []).find((c) => c.colours === key.colours);
    if (!row) return null;
    const h = row.hardest || {};
    const words = h.needed != null ? `${num(h.have)} of ${h.needed}` : `${num(h.have)}`;
    return el("span", {}, words, row.ok === false ? [" ", status("warn", "Short")] : null);
  };
  return comparePart("h-compare-colours", "Colours", compareTable("Colours and colour sources", labels, [
    ["Colour identity", ...sides.map(identity)],
    ...keys.map((key) => [`${capitalise(key.name)} sources`, ...sides.map((d) => sourceCell(d, key))])]),
  keys.length ? el("p", { class: "sub", text: "Sources against the number the hardest card of that colour needs to be " +
    "cast on time (Frank Karsten's tables; the Stats tab explains them)." }) : null);
}

/** Copies of each card type (a card can have two), with a bar on one scale for both sides. */
function compareTypes(sides, labels) {
  const counts = sides.map((d) => new Map((d.stats?.types || []).map((t) => [t.type, t.count])));
  const types = COMPARE_TYPES.filter((t) => counts.some((m) => m.get(t)));
  const max = Math.max(1, ...counts.flatMap((m) => [...m.values()]));
  const cell = (m, type) => {
    if (!m.size) return null;
    const n = m.get(type) || 0;
    const bar = el("span", { class: "compare-bar", "aria-hidden": "true" });
    bar.style.width = `${Math.round(n / max * 100)}%`;
    return el("span", { class: "compare-count" }, el("span", { class: "compare-track" }, bar), num(n));
  };
  return comparePart("h-compare-types", "Card types", types.length
    ? compareTable("Copies of each card type", labels, types.map((t) => [capitalise(t), ...counts.map((m) => cell(m, t))]))
    : el("p", { class: "sub", text: "No card types to compare." }));
}

// The chooser ---------------------------------------------------------------

/** "Compare with…": the decks the viewer sees (GET /api/decks), and the deck's own other list when it has two;
 * choosing one opens the compare page. */
function openCompareChooser(data) {
  const sheet = openSheet("Compare with…");
  const token = routeToken, profile = state.profile?.id;
  const here = () => !sheet.closed && token === routeToken && profile === state.profile?.id;
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }]);
  const fetchDecks = () => {
    clear(sheet.body).append(loadingBox("Getting the decks…", { small: true }));
    api("/api/decks").then((answer) => { if (here()) drawCompareChoices(sheet, data, answer); })
      .catch((e) => { if (here()) clear(sheet.body).append(loadFailed("The decks", e, fetchDecks)); });
  };
  fetchDecks();
  return sheet;
}

function drawCompareChoices(sheet, data, answer) {
  const s = data.summary;
  const other = data.version === "owned" ? "target" : "owned";
  const own = (data.versions || []).includes(other)
    ? [{ id: s.id, title: `${s.title}: its ${listName(other, true)}`, colors: s.colors, version: other }] : [];
  const decks = (answer.decks || []).filter((d) => !d.error && d.id !== s.id)
    .sort((x, y) => String(x.title).localeCompare(String(y.title)));
  const choices = [...own, ...decks];
  const list = el("ul", { class: "compare-choices" });
  const empty = el("div", {});
  const items = choices.map((d) => {
    const pieces = deckColourPieces(d.colors);
    const li = el("li", {}, el("a", { class: "compare-choice", href: compareHref(s.id, d.id, data.version, d.version || "target") },
      pieces ? pieces.swatch() : null, el("span", { class: "compare-choice-title", text: d.title })));
    li.dataset.title = String(d.title).toLowerCase();
    list.append(li);
    return li;
  });
  const search = el("input", { type: "search", class: "compare-search", placeholder: "Find a deck", "aria-label": "Find a deck",
    autocomplete: "off" });
  search.addEventListener("input", () => {
    const words = search.value.trim().toLowerCase();
    let shown = 0;
    for (const li of items) {
      li.hidden = Boolean(words) && !li.dataset.title.includes(words);
      if (!li.hidden) shown += 1;
    }
    clear(empty);
    if (!shown) empty.append(emptyBox("No deck matches that.", null, { live: true }));
  });
  if (!choices.length) {
    clear(sheet.body).append(emptyBox("There's no other deck to compare it with yet."));
    return;
  }
  clear(sheet.body).append(el("p", { class: "sub", text: `Show ${s.title}'s stats beside another list's.` }),
    search, list, empty);
}
