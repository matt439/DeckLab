/* Compare two decks (E1-S13, its first slice): #/compare?a=<deck id>&b=<deck id>[&av=target|owned&bv=...], the
 * two lists' stats side by side: their counts in brief, their mana curves on one scale, their colours and colour
 * sources, and their card types. It reads each deck as its own page does (GET /api/deck, the viewer's rights),
 * so a deck the viewer may not see answers as missing and the page shows that instead. Read-only: nothing here
 * changes either deck. The way in is a deck page's More, "Compare with…" (openCompareChooser), which lists the
 * decks the viewer sees (GET /api/decks) and, for a deck with both lists, its own other list.
 *
 * Below the stats, the cards both lists use (compareShared: GET /api/compare/shared, whose copies the pool can
 * cover for both come only to a viewer who may see the space's collection) and how the two have done against
 * each other (compareHeadToHead: the latest saved Forge result between them, from the first deck's matchups,
 * and the Game log's games between them), each fetched after the stats show, with its own Try again.
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

/** Whether the sides are one deck's two lists (a pairing's halves in either order count as one deck); one list
 * against itself isn't, so its sides keep the deck's title. */
function compareTwoLists(a, b) {
  return sameDeckId(a.summary.id) === sameDeckId(b.summary.id) && a.version !== b.version;
}

function compareDraw(sides) {
  const [a, b] = sides;
  const sameDeck = compareTwoLists(a, b);
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
      description: "Their stats, the cards both use and how they've done against each other. Nothing here changes either deck.",
      more: [{ label: "Swap sides", href: swap },
        { label: "Compare with another deck…", onclick: () => openCompareChooser(a) }] }),
    el("div", { class: "compare-heads" }, sides.map((d, i) => compareHead(d, labels[i], sameDeck))),
    warningsBox(compareNotes(sides, labels), "About these stats"),
    compareBrief(sides, labels),
    compareCurves(sides, labels),
    compareColours(sides, labels),
    compareTypes(sides, labels),
    compareShared(sides, labels, sameDeck),
    compareHeadToHead(sides, labels)]);
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
  const charts = el("div", { class: "compare-charts" },
    curves.map((curve, i) => compareCurve(curve, labels[i], top, `compare-${i}`)));
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

// Each side's bar cards are their own viewer group (compare-0, compare-1), so a swipe stays in one deck's list.
function compareCurve(curve, label, top, group) {
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
      b.cards && b.cards.length ? cardNames(b.cards, group) : null]);
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

// Cards both use, head to head ---------------------------------------------

/** Fetch path into host (a part of the page) and draw the answer there with draw(answer); a failure says so
 * with Try again. Nothing is drawn once the page has been left. */
function compareFetch(host, path, what, draw) {
  const token = routeToken;
  const fetchIt = () => {
    clear(host).append(loadingBox(`Getting ${what.toLowerCase()}…`, { small: true }));
    api(path).then((answer) => { if (token === routeToken && host.isConnected) add(clear(host), [draw(answer || {})]); })
      .catch((e) => { if (token === routeToken && host.isConnected) clear(host).append(loadFailed(what, e, fetchIt)); });
  };
  fetchIt();
  return host;
}

/** The cards both lists use (basic lands left out), each list's copies, and, for a viewer the server gives
 * counts (one who may see the space's collection), the copies free for both against what both need. */
function compareShared(sides, labels, sameDeck) {
  const [a, b] = sides;
  const q = new URLSearchParams({ a: a.summary.id, av: a.version, b: b.summary.id, bv: b.version });
  const host = el("div", { class: "compare-shared" });
  compareFetch(host, `/api/compare/shared?${q}`, "The cards both lists use",
    (answer) => compareSharedParts(answer, labels, sameDeck));
  return comparePart("h-compare-shared", "Cards both use", host);
}

function compareSharedParts(answer, labels, sameDeck) {
  const cards = answer.cards || [];
  const counts = answer.counts === true;
  const notes = [answer.why_no_counts, ...(answer.warnings || [])].filter(Boolean);
  const box = notes.length ? warningsBox(notes, "About these counts") : null;
  if (!cards.length) return [box, emptyBox("No card is in both lists (basic lands aren't counted).")];
  const short = cards.filter((c) => c.short > 0).length;
  const free = "Free copies are the collection's (on the way included) that no other built deck or intact product holds";
  const lead = !counts ? `${plural(cards.length, "card")} in both lists (basic lands aren't counted).`
    : answer.together === false
      ? `${plural(cards.length, "card")} in both lists. ${free}; one deck's two lists are never put together at once, ` +
        "so each card needs the larger count."
      : `${plural(cards.length, "card")} in both lists. ${free}, against what both lists need at once.`;
  const whom = answer.together === false ? "either list" : "both at once";
  const verdict = !counts ? null : short ? status("warn", `${plural(short, "card")} short for ${whom}`)
    : status("ok", `Enough of every card for ${whom}`);
  const cover = (c) => el("span", {}, `${num(c.free)} of ${num(c.need)}`,
    c.short > 0 ? [" ", status("warn", `${num(c.short)} short`)] : null,
    c.on_the_way ? el("small", { class: "compare-hint", text: ` ${num(c.on_the_way)} on the way` }) : null);
  const table = el("table", { class: "data compare-table compare-shared-table" },
    el("caption", { class: "sr-only", text: "Cards both lists use" }),
    el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Card" }),
      labels.map((label) => el("th", { scope: "col", class: "num", text: label })),
      counts ? el("th", { scope: "col", class: "num", text: "Free" }) : null)),
    el("tbody", {}, cards.map((c) => el("tr", {},
      el("th", { scope: "row" }, cardLink({ name: c.name }, "compare-shared")),
      el("td", { class: "num", text: num(c.a) }), el("td", { class: "num", text: num(c.b) }),
      counts ? el("td", { class: "num" }, cover(c)) : null))));
  return [box, el("p", { class: "sub", text: lead }), verdict ? el("p", { class: "compare-verdict" }, verdict) : null, table];
}

/** Whether a Forge or Game log side is the compared list: its deck (a pairing's halves in either order) and list. */
function compareIsSide(side, data) {
  return !!side && !!side.id && sameDeckId(side.id) === sameDeckId(data.summary.id)
    && (side.version || "target") === data.version;
}

/** How the two have done against each other: the latest saved Forge result between the lists (from the first
 * deck's matchups, fetched as its Matchups tab fetches them), and the Game log's games between them. */
function compareHeadToHead(sides, labels) {
  const [a, b] = sides;
  const forge = el("div", { class: "compare-forge" });
  const games = el("div", { class: "compare-games" });
  compareFetch(forge, `/api/deck?id=${encodeURIComponent(a.summary.id)}&version=${a.version}`, "Forge's results",
    (answer) => compareForgeParts(answer, a, b));
  compareFetch(games, `/api/play?id=${encodeURIComponent(a.summary.id)}`, "The Game log",
    (answer) => compareGameParts(answer, a, b, labels));
  return comparePart("h-compare-h2h", "Head to head",
    el("h3", { text: "Forge" }), forge, el("h3", { text: "Game log" }), games);
}

/** The newest saved Forge result of a's list against b's (with an earlier list of either too, faded as on the
 * deck page), or null. */
function compareLatestResult(results, b) {
  return (results || []).filter((item) => item && item.sides && compareIsSide(item.sides[1], b))
    .reduce((best, item) => (!best || String(item.updated || "") > String(best.updated || "") ? item : best), null);
}

function compareForgeParts(answer, a, b) {
  if (answer.matchups === null) return el("p", { class: "sub", text: "Forge's results couldn't be worked out for this list." });
  const latest = compareLatestResult((answer.matchups || {}).results, b);
  const play = !latest && runsAllowed() ? el("a", { class: "btn",
    href: matchupHref({ id: a.summary.id, version: a.version }, { id: b.summary.id, version: b.version }), text: "Play a matchup" }) : null;
  if (!latest) return emptyBox("Forge hasn't played these two lists against each other yet.", play);
  return [el("ul", { class: "mu-list" }, resultRow(latest, { against: true, deckId: a.summary.id })),
    el("p", { class: "sub", text: "The latest saved result: open it for its games." })];
}

/** The Game log's games between the two lists: how many, each side's wins and the draws, linked to the log. */
function compareGameParts(answer, a, b, labels) {
  const mirror = compareIsSide({ id: b.summary.id, version: b.version }, a);
  let played = 0, draws = 0;
  const wins = [0, 0];
  for (const entry of answer.games || []) {
    const record = (entry && entry.record) || {};
    const [x, y] = record.sides || [];
    const straight = compareIsSide(x, a) && compareIsSide(y, b), turned = compareIsSide(x, b) && compareIsSide(y, a);
    if (!straight && !turned) continue;
    played += 1;
    if (record.result === "draw") draws += 1;
    else if (record.result === "a" || record.result === "b") wins[(record.result === "a") === straight ? 0 : 1] += 1;
  }
  const log = el("a", { href: `#/play?id=${encodeURIComponent(a.summary.id)}`, text: played ? "Open the Game log" : "Record a game" });
  if (!played) return emptyBox("No games between these two lists have been recorded.", log);
  const words = mirror ? `${plural(played, "game")}, both with this list`
    : `${plural(played, "game")}: ${labels[0]} ${plural(wins[0], "win")}, ${labels[1]} ${plural(wins[1], "win")}`;
  return [el("p", { class: "compare-games-count", text: words + (draws ? `, ${plural(draws, "draw")}` : "") + "." }),
    el("p", {}, log)];
}

// The chooser ---------------------------------------------------------------

/** "Compare with…": the decks the viewer sees (GET /api/decks, or decks: the library's, already fetched), and
 * the deck's own other list when it has two; choosing one opens the compare page. */
function openCompareChooser(data, decks = null) {
  const sheet = openSheet("Compare with…");
  const token = routeToken, profile = state.profile?.id;
  const here = () => !sheet.closed && token === routeToken && profile === state.profile?.id;
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }]);
  const fetchDecks = () => {
    clear(sheet.body).append(loadingBox("Getting the decks…", { small: true }));
    api("/api/decks").then((answer) => { if (here()) drawCompareChoices(sheet, data, answer); })
      .catch((e) => { if (here()) clear(sheet.body).append(loadFailed("The decks", e, fetchDecks)); });
  };
  if (decks) drawCompareChoices(sheet, data, { decks });
  else fetchDecks();
  return sheet;
}

/** The library's More, "Compare two decks…": choose the first of its decks (decks: the library's, the ones the
 * viewer sees), then the second in "Compare with…". */
function openCompareFirst(decks) {
  const sheet = openSheet("Compare two decks");
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }]);
  const readable = compareSorted(decks);
  if (readable.length < 2) {
    sheet.body.append(emptyBox("There aren't two decks to compare yet."));
    return sheet;
  }
  const pick = (d) => {
    sheet.close();
    openCompareChooser({ summary: { id: d.id, title: d.title, colors: d.colors }, version: "target",
      versions: d.versions || ["target"] }, decks);
  };
  sheet.body.append(el("p", { class: "sub", text: "Choose the first deck, then the one to show beside it." }),
    ...compareChoiceList(readable, (d) => ({ onclick: () => pick(d) })));
  return sheet;
}

/** The readable decks by title. */
function compareSorted(decks) {
  return (decks || []).filter((d) => !d.error).sort((x, y) => String(x.title).localeCompare(String(y.title)));
}

/** A search and one row a choice ({id, title, colors}): a link (target(d).href) or a button (target(d).onclick). */
function compareChoiceList(choices, target) {
  const list = el("ul", { class: "compare-choices" });
  const empty = el("div", {});
  const items = choices.map((d) => {
    const pieces = deckColourPieces(d.colors);
    const to = target(d);
    const inner = [pieces ? pieces.swatch() : null, el("span", { class: "compare-choice-title", text: d.title })];
    const li = el("li", {}, to.href ? el("a", { class: "compare-choice", href: to.href }, inner)
      : el("button", { type: "button", class: "compare-choice", onclick: to.onclick }, inner));
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
  return [search, list, empty];
}

function drawCompareChoices(sheet, data, answer) {
  const s = data.summary;
  const other = data.version === "owned" ? "target" : "owned";
  const own = (data.versions || []).includes(other)
    ? [{ id: s.id, title: `${s.title}: its ${listName(other, true)}`, colors: s.colors, version: other }] : [];
  const choices = [...own, ...compareSorted(answer.decks).filter((d) => d.id !== s.id)];
  if (!choices.length) {
    clear(sheet.body).append(emptyBox("There's no other deck to compare it with yet."));
    return;
  }
  clear(sheet.body).append(el("p", { class: "sub", text: `Show ${s.title}'s stats beside another list's.` }),
    ...compareChoiceList(choices, (d) => ({ href: compareHref(s.id, d.id, data.version, d.version || "target") })));
}
