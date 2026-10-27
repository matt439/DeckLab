/* The Compare page (#/compare?a=<deck id>&av=target|owned&b=<deck id>&bv=target|owned, E1-S13's first slice):
two lists' stats side by side, read only. Their mana curves (on one scale, so the bars compare), land counts,
colour sources and card types come from GET /api/deck/compare (lib/api/compare.py), which gives each list the
deck page's own stats; a deck the viewer may not see answers there as a missing one.

The two decks are picked with the matchup sheet's deckPicker (matchups-overview.js) from the viewer's library
(GET /api/decks, only the decks they may see); Compare puts them in the address. The deck page's More menu,
"Compare with…", opens it with that deck (and list) first. Cards both lists use and how they've done against
each other are later slices.

Loaded after stats.js, whose chart helpers (chartJobs, drawCharts, drawCurve, colourPips, VERDICT_KIND,
ROLE_WORDS) it uses, and before app.js, whose route() calls showCompare. */
"use strict";

/** The Compare page's address for two lists (b may be null: pick the second deck). */
function compareHref(a, av, b = null, bv = "target") {
  const part = (key, id, v) => `${key}=${encodeURIComponent(id)}&${key}v=${v === "owned" ? "owned" : "target"}`;
  return `#/compare?${part("a", a, av)}${b ? `&${part("b", b, bv)}` : ""}`;
}

function showCompare(params, token) {
  const pick = (key) => (params.get(key) ? addressDeckId(params.get(key)) : null);
  const want = { a: pick("a"), av: params.get("av") === "owned" ? "owned" : "target",
    b: pick("b"), bv: params.get("bv") === "owned" ? "owned" : "target" };
  const paths = ["/api/decks"];
  if (want.a && want.b) {
    paths.push(`/api/deck/compare?a=${encodeURIComponent(want.a)}&av=${want.av}&b=${encodeURIComponent(want.b)}&bv=${want.bv}`);
  }
  load(paths, token, ([library, answer]) => compareDraw(library, answer || null, want, token), {
    title: "The comparison couldn't be loaded",
    back: want.a ? [deckHref(want.a, want.av), "Back to the deck"] : ["#/library", "Back to Decks"] });
}

function compareDraw(library, answer, want, token) {
  const sides = answer ? answer.decks : null;
  if (sides) setTitle(`${sides[0].summary.title} and ${sides[1].summary.title}`);
  const first = want.a && (library.decks || []).find((d) => sameDeckId(d.id) === sameDeckId(want.a));
  add($("#main"), [
    pageHead({ crumb: first ? [deckHref(first.id, want.av), first.title] : ["#/library", routeFor("library").label],
      title: routeH1("compare"),
      description: "Two lists' mana curves, lands, colour sources and card types side by side." }),
    comparePicker(library, want, token),
    sides ? compareBody(sides) : null,
  ]);
  drawCharts();
}

/** The two decks to compare, each with its list, and Compare. */
function comparePicker(library, want, token) {
  const one = deckPicker(1, library, () => {});
  const two = deckPicker(2, library, () => {});
  one.set(want.a, want.av);
  if (want.b) two.set(want.b, want.bv);
  else two.other(one.value().id);
  const error = el("p", { class: "form-error", role: "alert" });
  const form = el("form", { class: "cmp-pick", "aria-label": "Decks to compare", onsubmit: (e) => {
    e.preventDefault();
    if (token !== routeToken) return;
    const [a, b] = [one.value(), two.value()];
    const problem = a.problem || b.problem;
    error.textContent = problem || "";
    if (!problem) location.hash = compareHref(a.id, a.version, b.id, b.version);
  } },
  el("div", { class: "cmp-pick-decks" }, one.node, two.node),
  error,
  el("div", { class: "actions" }, el("button", { type: "submit", class: "btn btn-primary", text: "Compare" })));
  return form;
}

/** The comparison: the two decks, the stats in brief, then the panels. */
function compareBody(sides) {
  const failed = sides.filter((s) => !s.stats);
  const warnings = sides.flatMap((s) => (s.warnings || []).map((w) => `${s.summary.title}: ${w}`));
  const both = sides.every((s) => s.stats);
  return el("div", { class: "cmp" },
    el("div", { class: "cmp-heads" }, sides.map(compareHead)),
    failed.length ? el("div", { class: "box box-warn" },
      el("h2", { class: "box-head", text: `The stats of ${failed.map((s) => s.summary.title).join(" and ")} couldn't be worked out` }),
      el("p", { text: "Try again later; the server log says why." })) : null,
    warnings.length ? warningsBox(warnings, "About these stats") : null,
    compareBrief(sides),
    both ? el("div", { class: "panels" }, compareCurvePanel(sides), compareLandPanel(sides), compareColourPanel(sides),
      compareTypesPanel(sides)) : null);
}

/** One deck's head: its colours, title (a link to its page) and one facts line. */
function compareHead(side, i) {
  const s = side.summary;
  const colours = Array.isArray(s.colors) ? deckColourPieces(s.colors) : null;
  const facts = [s.kind === "commander" ? "Commander" : s.id.startsWith("pairing/") ? "Beginner Box pairing"
    : s.id.startsWith("product/") ? "Product deck" : "60-card",
  (s.versions || []).length > 1 ? listName(side.version) : null,
  s.status ? capitalise(s.status) : null];
  return el("section", { class: "cmp-head", "aria-label": `Deck ${i + 1}` },
    colours ? colours.stripe() : null,
    el("div", { class: "cmp-head-in" },
      el("span", { class: "cmp-head-n", text: `Deck ${i + 1}` }),
      el("h2", { class: "cmp-head-title" }, el("a", { href: deckHref(s.id, side.version), text: s.title })),
      colours ? colours.pips(20) : null,
      factLine("cmp-head-facts", facts)));
}

/** A table with one row per figure and a column for each deck: rows are [label, cell a, cell b]. */
function compareTable(sides, rows, caption) {
  return el("table", { class: "data cmp-table" },
    el("caption", { class: "sr-only", text: caption }),
    el("colgroup", {}, el("col", { class: "cmp-col-label" }), el("col"), el("col")),
    el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "" }),
      sides.map((s) => el("th", { scope: "col", class: "num", text: s.summary.title })))),
    el("tbody", {}, rows.map(([label, ...cells]) => el("tr", {},
      el("th", { scope: "row" }, label),
      cells.map((cell) => el("td", { class: "num" }, cell == null ? "–" : cell))))));
}

/** The stats' answers in one table: what statsVerdict says on each deck page, row by row. */
function compareBrief(sides) {
  const stat = (fn) => sides.map((s) => (s.stats ? fn(s.stats, s.summary) : null));
  const lands = (st) => {
    const l = st.lands;
    if (!l) return null;
    const off = l.verdict && l.verdict !== "ok";
    return el("span", { class: "cmp-cell" }, num(l.effective),
      l.recommended != null ? el("span", { class: "cmp-hint", text: ` (formula ${num(l.recommended, 1)})` }) : null,
      off ? status(VERDICT_KIND[l.verdict] || "warn", capitalise(l.verdict)) : null);
  };
  const colours = (st) => {
    const c = st.colours && st.colours.colours;
    if (!c || !c.length) return "None needed";
    const short = c.filter((x) => x.ok === false);
    if (short.length) return el("span", { class: "cmp-cell" }, capitalise(short.map((x) => x.name).join(", ")), status("warn", "Short"));
    return c.every((x) => x.ok != null) ? "Enough" : "Not checked";
  };
  const rows = [
    ["Cards", ...sides.map((s) => {
      const n = s.summary.card_count, sb = s.summary.sideboard_count;
      return n == null ? null : `${num(n)}${sb ? ` + ${num(sb)} sideboard` : ""}`;
    })],
    ["Average mana value", ...stat((st) => (st.curve && st.curve.average_mv != null ? num(st.curve.average_mv) : null))],
    ["Creatures", ...stat((st) => (st.curve ? num(st.curve.creatures) : null))],
    ["Other spells", ...stat((st) => (st.curve ? num(st.curve.noncreatures) : null))],
    ["Lands", ...stat(lands)],
    ["Colour sources", ...stat(colours)],
  ];
  if (sides.some((s) => s.stats && s.stats.commander)) {
    rows.push(["Bracket", ...stat((st) => (st.commander && st.commander.bracket ? st.commander.bracket.label : null))]);
  }
  return el("section", { class: "panel cmp-brief", "aria-labelledby": "cmp-h-brief" },
    el("h2", { id: "cmp-h-brief", class: "cmp-panel-head", text: "In brief" }),
    compareTable(sides, rows, "The two decks' stats in brief"));
}

/** Both mana curves on one scale (the taller deck's), so the same height is the same number of cards. */
function compareCurvePanel(sides) {
  const top = Math.max(1, ...sides.flatMap((s) => s.stats.curve.buckets.map((b) => b.total)));
  const chart = (side) => {
    const host = el("div", { class: "chart" });
    const detail = el("div", { class: "chart-detail", "aria-live": "polite" },
      noneSelected("Tap or point at a bar to list its cards."));
    const curve = side.stats.curve;
    const show = (i) => {
      const b = curve.buckets[i];
      for (const g of host.querySelectorAll(".col")) g.classList.toggle("active", Number(g.dataset.i) === i);
      add(clear(detail), [el("p", {}, el("b", { text: `Mana value ${b.mv}: ${plural(b.total, "card")}` })),
        b.cards.length ? cardNames(b.cards) : null]);
    };
    chartJobs.push([host, (width) => drawCurve(host, curve, width, show, top)]);
    return el("figure", { class: "cmp-figure" }, el("figcaption", { class: "cmp-figure-title", text: side.summary.title }),
      host, detail);
  };
  const mvs = sides[0].stats.curve.buckets.map((b) => b.mv);
  const total = (side, mv) => (side.stats.curve.buckets.find((b) => b.mv === mv) || { total: 0 }).total;
  return el("section", { class: "panel wide", "aria-labelledby": "cmp-h-curve" },
    el("h2", { id: "cmp-h-curve", class: "cmp-panel-head", text: "Mana curve" }),
    el("ul", { class: "legend", "aria-label": "Legend" },
      el("li", {}, el("span", { class: "swatch", style: "background: var(--series-1)" }), "Creatures"),
      el("li", {}, el("span", { class: "swatch", style: "background: var(--series-2)" }), "Other spells"),
      el("li", {}, el("span", { class: "swatch-line" }), "Average")),
    el("div", { class: "cmp-pair" }, sides.map(chart)),
    el("details", { class: "more" }, el("summary", { text: "The curves as a table" }),
      compareTable(sides, mvs.map((mv) => [`Mana value ${mv}`, ...sides.map((s) => String(total(s, mv)))]),
        "Cards at each mana value, lands left out")));
}

function compareLandPanel(sides) {
  const l = (fn) => sides.map((s) => (s.stats.lands ? fn(s.stats.lands) : null));
  const makers = (x) => (x.mana_creatures || []).concat(x.mana_rocks || []).reduce((n, mk) => n + (mk.qty || 1), 0);
  return el("section", { class: "panel", "aria-labelledby": "cmp-h-lands" },
    el("h2", { id: "cmp-h-lands", class: "cmp-panel-head", text: "Land count" }),
    compareTable(sides, [
      ["Lands", ...l((x) => num(x.lands))],
      ["Counted, with spell // land cards", ...l((x) => num(x.effective))],
      ["The formula says", ...l((x) => (x.recommended != null ? num(x.recommended, 1) : null))],
      ["Mana creatures and rocks", ...l((x) => num(makers(x)))],
    ], "The two decks' lands"),
    el("p", { class: "sub", text: "Each deck's page explains the formula under Stats." }));
}

/** Every colour either deck needs, WUBRG order: the sources each has for its hardest card, and whether
 * that's enough. */
function compareColourPanel(sides) {
  const byColour = sides.map((s) => new Map(((s.stats.colours && s.stats.colours.colours) || []).map((c) => [c.colours, c])));
  const order = "WUBRG";
  const keys = [...new Set(byColour.flatMap((m) => [...m.keys()]))]
    .sort((x, y) => order.indexOf(x[0]) - order.indexOf(y[0]) || x.localeCompare(y));
  const cell = (row) => {
    if (!row) return "Not needed";
    const h = row.hardest || {};
    const words = h.needed != null ? `${num(h.have)} of ${h.needed}` : num(h.have);
    return el("span", { class: "cmp-cell" }, words, row.ok === false ? status("warn", `Short by ${num(-h.margin)}`) : null);
  };
  const name = (key) => {
    const row = byColour.map((m) => m.get(key)).find(Boolean);
    return el("span", { class: "cmp-colour" }, colourPips(key.split("")), capitalise(row.name));
  };
  return el("section", { class: "panel", "aria-labelledby": "cmp-h-colours" },
    el("h2", { id: "cmp-h-colours", class: "cmp-panel-head", text: "Colour sources" }),
    keys.length ? [
      compareTable(sides, keys.map((key) => [name(key), ...byColour.map((m) => cell(m.get(key)))]),
        "Each colour's sources against what the hardest card needs"),
      el("p", { class: "sub", text: "Sources each deck has, of those its hardest card in that colour needs to cast on time." }),
    ] : el("p", { class: "sub", text: "Neither deck's spells need coloured mana." }));
}

/** Copies of each card type, then each role, in either deck (a card can have two types). */
function compareTypesPanel(sides) {
  const counts = (list, key) => sides.map((s) => new Map((s.stats[list] || []).map((x) => [x[key], x.count])));
  const rows = (list, key, label) => {
    const maps = counts(list, key);
    const names = [...new Set(sides.flatMap((s) => (s.stats[list] || []).filter((x) => x.count > 0).map((x) => x[key])))];
    return names.map((n) => [label(n), ...maps.map((m) => num(m.get(n) || 0))]);
  };
  const types = rows("types", "type", capitalise);
  const roles = rows("roles", "role", (r) => (ROLE_WORDS[r] || [capitalise(r)])[0]);
  return el("section", { class: "panel", "aria-labelledby": "cmp-h-types" },
    el("h2", { id: "cmp-h-types", class: "cmp-panel-head", text: "Card types and roles" }),
    types.length ? compareTable(sides, types, "Copies of each card type") : null,
    roles.length ? [el("h3", { class: "cmp-sub-head", text: "Roles" }), compareTable(sides, roles, "Copies with each role")] : null);
}
