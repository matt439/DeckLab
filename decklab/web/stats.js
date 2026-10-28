/* Deck Lab's page: the deck view's "Stats" part (/api/deck's "stats": the mana curve, land count,
colour sources, card types and roles, tribes, Commander checks, sideboard and sources), the builder's own
categories (deck-categories.js categoriesPanel, E2-S24), its "Chance to
draw" panel (worked out here from the shown list's main deck, E3-S24), and the
hand-made chart helpers (chartJobs and drawCharts, tile, niceScale, columnPath, barPath, colourPips)
that deck.js, practice.js and matchups.js use too.

Charts are hand-made SVG. Their colours are the dataviz reference palette,
set in tokens.css (series 1 blue for creatures and sources, series 2 orange for
other spells); text never wears a series colour, and every status (short,
enough, missing) carries an icon and a word, not colour alone.

Loaded after deck.js, whose card helpers (manaCost, pip, costToSymbols, cardLink, cardNames) it uses
with core.js's, and before practice.js and app.js. Nothing here runs at load but its word tables and
the empty chartJobs queue.
*/
"use strict";

const ROLE_WORDS = {
  removal: ["Removal", "deals with the other player's creatures or other cards"],
  ramp: ["Ramp", "gives you extra mana, or extra lands, sooner"],
  draw: ["Card draw", "draws you extra cards"],
  counterspell: ["Counterspells", "stops a spell as it's cast"],
  "board wipe": ["Board wipes", "destroys many creatures at once"],
  burn: ["Burn", "deals damage directly"],
  lifegain: ["Life gain", "gains you life"],
};

const chartJobs = [];     // charts to draw once their containers are on the page

function drawCharts() {
  while (chartJobs.length) {
    const [host, draw] = chartJobs.shift();
    fitWidth(host, draw);
  }
}

function statsSection(data) {
  const st = data.stats;
  const section = el("section", { class: "deck-section", id: "sec-stats", "aria-labelledby": "h-stats" },
    el("h2", { id: "h-stats", class: "sr-only", text: "Stats" }));
  if (!st) {
    // They come with the deck, so Try again loads the deck page again.
    section.append(el("div", { class: "box box-warn" },
      el("h3", { class: "box-head", text: "The stats couldn't be worked out" }),
      el("p", { text: "The warnings at the top say why." }),
      el("div", { class: "actions" }, el("button", { type: "button", class: "btn", text: "Try again", onclick: () => route() }))));
    return section;
  }
  const notes = [];
  if (st.guidance && st.guidance.note) notes.push(st.guidance.note);
  if (st.unresolved && st.unresolved.length) {
    notes.push(`Left out of the stats (not Scryfall card names): ${st.unresolved.map((u) => `${u.qty} ${u.name}`).join(", ")}.`);
  }
  add(section, [statsVerdict(st, data.summary), warningsBox([...notes, ...(st.warnings || [])], "About these stats")]);
  section.append(el("div", { class: "panels" },
    curvePanel(st),
    landPanel(st),
    colourPanel(st),
    st.commander ? commanderPanel(st, data.summary) : null,
    drawOddsPanel(data),
    compositionPanel(st),
    categoriesPanel(data),
    tribesPanel(st),
    st.sideboard && st.sideboard.count ? sideboardPanel(st) : null,
    sourcesPanel(st)));
  return section;
}

/** The stats' answers in one strip, before any chart: the average mana value, the lands against the
 * formula, whether every colour has enough sources, and for Commander the deck rules and the lowest bracket.
 * Chips only where something's off. null when there's nothing to say. */
function statsVerdict(st, summary) {
  const items = [];
  const curve = st.curve;
  if (curve && curve.average_mv != null) items.push(verdictItem("Average mana value", num(curve.average_mv), "lands left out"));
  const lands = st.lands;
  if (lands) {
    const off = lands.verdict && lands.verdict !== "ok";
    const hint = (lands.verdict === "ok" ? "Ok; " : "") +
      (lands.recommended != null ? `the formula says ${num(lands.recommended, 1)}` : "in the deck");
    items.push(verdictItem("Lands", num(lands.effective), hint,
      off ? status(VERDICT_KIND[lands.verdict] || "warn", capitalise(lands.verdict)) : null));
  }
  const c = st.colours;
  if (c && c.colours && c.colours.length) {
    const short = c.colours.filter((x) => x.ok === false);
    const known = c.colours.every((x) => x.ok != null);
    items.push(short.length
      ? verdictItem("Colour sources", capitalise(short.map((x) => x.name).join(", ")), "too few to cast on time",
        status("warn", "Short"))
      : verdictItem("Colour sources", known ? "Enough" : "Not checked", known ? `for ${plural(c.colours.length, "colour")}` : null));
  }
  const k = st.commander;
  if (k) {
    items.push(verdictItem("Deck rules", k.ok ? "Followed" : "Broken", k.ok ? "100 cards, one of each, in colour"
      : (k.problems && k.problems[0]) || "see Commander rules", k.ok ? null : status("crit", "Breaks a rule")));
    const br = k.bracket || {};
    if (br.label) {
      const aim = summary && summary.target_bracket;
      // The value is just the numbers ("1 or 2", "4 or higher"); a label's "(theme and intent decide)" goes in
      // the small line under it, with what the deck aims for.
      const m = /^(?:Bracket\s+)?(.*?)\s*(?:\((.*)\))?$/.exec(br.label);
      const hint = [m[2], aim ? `aims for Bracket ${aim}` : "the lowest it fits"].filter(Boolean).join("; ");
      items.push(verdictItem("Bracket", m[1] || br.label, hint));
    }
  }
  if (!items.length) return null;
  return el("ul", { class: "verdict-strip", "aria-label": "The stats in brief" }, items);
}

function verdictItem(label, value, hint, chip = null) {
  return el("li", { class: "verdict" },
    el("span", { class: "verdict-label", text: label }),
    el("span", { class: "verdict-value", text: value }),
    hint ? el("span", { class: "verdict-hint", text: hint }) : null,
    chip);
}

/** An explanation, folded: "How is this worked out?" (or summary) over its paragraphs and nodes. */
function explain(summary, ...parts) {
  return el("details", { class: "more explain" }, el("summary", { text: summary || "How is this worked out?" }),
    parts.filter(Boolean).map((p) => (typeof p === "string" ? el("p", { class: "sub", text: p }) : p)));
}

/** Cite the recorded source date as text: some dates also describe publication, updates or retrieval.
 * Keep the shared sourceLink title-only for callers such as accessory shop and picture links. */
function statsSourceCitation(sources, id) {
  const link = sourceLink(sources, id);
  if (!link) return null;
  const source = sources[id];
  const date = typeof source.date === "string" ? source.date.trim() : "";
  return el("span", {}, link, ` (${date || "date unknown"})`);
}

// Mana curve ----------------------------------------------------------------

function curvePanel(st) {
  const curve = st.curve;
  const chart = el("div", { class: "chart" });
  const detail = el("div", { class: "chart-detail", "aria-live": "polite" },
    noneSelected("Tap or point at a bar to list its cards."));
  const panel = el("section", { class: "panel wide", "aria-labelledby": "h-curve" },
    el("h3", { id: "h-curve", text: "Mana curve" }),
    // The average mana value is in the verdict strip above the panels (statsVerdict), so not here again.
    el("div", { class: "tiles" },
      tile("Creatures", num(curve.creatures), "copies"),
      tile("Other spells", num(curve.noncreatures), "copies")),
    el("ul", { class: "legend", "aria-label": "Legend" },
      el("li", {}, el("span", { class: "swatch", style: "background: var(--series-1)" }), "Creatures"),
      el("li", {}, el("span", { class: "swatch", style: "background: var(--series-2)" }), "Other spells"),
      curve.average_mv != null ? el("li", {}, el("span", { class: "swatch-line" }), "Average") : null),
    chart,
    detail);
  const outside = (curve.outside || []).map((o) =>
    `${o.name} (${o.section.toLowerCase()}, mana value ${num(o.mv)})`);
  if (outside.length) {
    panel.append(el("p", { class: "sub", text: `Not in the curve: ${outside.join(", ")}. It starts outside ` +
      "the library, so you never draw it." }));
  }
  if (curve.x_spells && curve.x_spells.count) {
    panel.append(el("p", { class: "sub" }, `${plural(curve.x_spells.count, "card")} with X in the cost ` +
      "(counted as X = 0): ", cardNames(curve.x_spells.cards)));
  }
  panel.append(explain("What's the mana curve?", el("p", { class: "sub" }, renderSymbols("Mana value is a card's total " +
    "cost: {2}{R}{R} is 4, and X counts as 0. The curve shows how many cards you'll draw at each mana value (lands " +
    "aren't counted). Cheap cards let you do something every turn; expensive ones win late.", { small: true }))));
  panel.append(el("details", { class: "more" }, el("summary", { text: "The curve as a table" }),
    el("table", { class: "data curve-table" },
      el("thead", {}, el("tr", {}, ["Mana value", "Creatures", "Other spells", "Total"].map((t, i) =>
        el("th", { scope: "col", class: i ? "num" : null, text: t })))),
      el("tbody", {}, curve.buckets.map((b) => el("tr", {},
        el("th", { scope: "row", text: b.mv }),
        el("td", { class: "num", text: String(b.creatures) }),
        el("td", { class: "num", text: String(b.noncreatures) }),
        el("td", { class: "num", text: String(b.total) }))))),
    curve.average_mv_definition ? el("p", { class: "sub", text: `Average mana value: ${curve.average_mv_definition}` }) : null));
  let active = -1;
  const show = (i) => {
    active = i;
    const b = curve.buckets[i];
    for (const g of chart.querySelectorAll(".col")) g.classList.toggle("active", Number(g.dataset.i) === i);
    add(clear(detail), [
      el("p", {}, el("b", { text: `Mana value ${b.mv}: ${plural(b.total, "card")}` }),
        ` (${b.creatures} creature${b.creatures === 1 ? "" : "s"}, ${b.noncreatures} other)`),
      b.cards.length ? cardNames(b.cards) : null]);
  };
  chartJobs.push([chart, (width) => {
    drawCurve(chart, curve, width, show);
    if (active >= 0) show(active);
  }]);
  return panel;
}

function tile(label, value, hint) {
  return el("div", { class: "tile" },
    el("span", { class: "label", text: label }),
    el("span", { class: "value" }, value),
    hint ? el("span", { class: "hint", text: hint }) : null);
}

/** Round max up to a scale with at most 5 steps: {top, step}. */
function niceScale(max) {
  for (const step of [1, 2, 5, 10, 20, 25, 50, 100]) {
    if (Math.ceil(max / step) <= 5) return { top: Math.max(step, Math.ceil(max / step) * step), step };
  }
  return { top: max, step: max };
}

/** A path for a bar with rounded top corners and a square base. */
function columnPath(x, y, w, h, r) {
  if (h <= 0) return "";
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}A${r},${r} 0 0 1 ${x + r},${y}H${x + w - r}A${r},${r} 0 0 1 ${x + w},${y + r}V${y + h}Z`;
}

/** A path for a horizontal bar with a rounded right end and a square start. */
function barPath(x, y, w, h, r) {
  if (w <= 0) return "";
  r = Math.min(r, h / 2, w);
  return `M${x},${y}H${x + w - r}A${r},${r} 0 0 1 ${x + w},${y + r}V${y + h - r}A${r},${r} 0 0 1 ${x + w - r},${y + h}H${x}Z`;
}

/** The curve's chart, width wide; onPick(i) on a bar's tap, hover or focus. top: the scale's least top, so two
 * curves drawn side by side (compare.js) share one scale. */
function drawCurve(host, curve, width, onPick, top = 0) {
  const buckets = curve.buckets;
  const height = 236;
  const m = { top: 22, right: 6, bottom: 48, left: 30 };
  const plotW = width - m.left - m.right;
  const plotH = height - m.top - m.bottom;
  const scale = niceScale(Math.max(1, top, ...buckets.map((b) => b.total)));
  const y = (v) => m.top + plotH * (1 - v / scale.top);
  const base = y(0);
  const band = plotW / buckets.length;
  const barW = Math.min(24, band * 0.62);
  const gap = 2;
  const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "group",
    "aria-label": `Mana curve: ${buckets.map((b) => `${b.total} at ${b.mv}`).join(", ")}` });
  for (let v = scale.step; v <= scale.top; v += scale.step) {
    svg.append(svgEl("line", { class: "grid", x1: m.left, x2: width - m.right, y1: y(v), y2: y(v) }),
      svgEl("text", { class: "axis-text", x: m.left - 8, y: y(v) + 4, "text-anchor": "end", text: String(v) }));
  }
  svg.append(svgEl("text", { class: "axis-text", x: m.left - 8, y: base + 4, "text-anchor": "end", text: "0" }));

  if (curve.average_mv != null) {
    // Behind the bars, so it never hides one; its label sits under the axis.
    const avg = Math.min(curve.average_mv, buckets.length - 1);
    const ax = m.left + band * (avg + 0.5);
    const lx = Math.min(Math.max(ax, m.left + 44), width - m.right - 44);
    svg.append(
      svgEl("line", { class: "avg", x1: ax, x2: ax, y1: m.top - 8, y2: base + 22 }),
      svgEl("text", { class: "label-text", x: lx, y: base + 38, "text-anchor": "middle",
        text: `average ${num(curve.average_mv)}` }));
  }

  buckets.forEach((b, i) => {
    const cx = m.left + band * (i + 0.5);
    const x = cx - barW / 2;
    const col = svgEl("g", { class: "col", "data-i": i, tabindex: 0, role: "button",
      "aria-label": `Mana value ${b.mv}: ${b.creatures} creatures, ${b.noncreatures} other spells` });
    col.append(svgEl("rect", { class: "hover-band", x: cx - band / 2 + 1, y: m.top - 16, width: band - 2,
      height: plotH + 16 + 24, rx: 6 }));
    const creatureTop = y(b.creatures);
    const both = b.creatures > 0 && b.noncreatures > 0;
    if (b.creatures > 0) {
      col.append(svgEl("path", { d: both ? `M${x},${base}V${creatureTop}H${x + barW}V${base}Z`
        : columnPath(x, creatureTop, barW, base - creatureTop, 4), class: "seg-1" }));
    }
    if (b.noncreatures > 0) {
      const bottom = both ? creatureTop - gap : base;
      const topY = y(b.total);
      col.append(svgEl("path", { d: columnPath(x, topY, barW, Math.max(bottom - topY, 1), 4), class: "seg-2" }));
    }
    if (b.total > 0) {
      col.append(svgEl("text", { class: "cap-text", x: cx, y: y(b.total) - 6, "text-anchor": "middle", text: String(b.total) }));
    }
    col.append(svgEl("text", { class: "axis-text", x: cx, y: base + 17, "text-anchor": "middle", text: b.mv }));
    col.addEventListener("pointerenter", () => onPick(i));
    col.addEventListener("click", () => onPick(i));
    col.addEventListener("focus", () => onPick(i));
    col.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(i); } });
    svg.append(col);
  });
  svg.append(svgEl("line", { class: "base", x1: m.left, x2: width - m.right, y1: base, y2: base }));
  host.replaceChildren(svg);
}

// Land count ----------------------------------------------------------------

// Lands against the formula, and colour sources, are advice for tuning, never a blocker: amber, not red (red is
// kept for what stops the deck being played: cards missing, a broken deck rule).
const VERDICT_KIND = { ok: "good", "slightly low": "warn", "slightly high": "warn", low: "warn", high: "warn" };

function landPanel(st) {
  const lands = st.lands;
  const sources = st.sources;
  const f = lands.formula || {};
  const chart = el("div", { class: "chart land-chart" });
  // The count, the formula's and the verdict are the verdict strip's (statsVerdict), above the panels: the panel
  // leads with its chart, and says only what the strip doesn't (spell // land cards counted in).
  const modal = lands.mdfc && (lands.mdfc.tapped || lands.mdfc.untapped);
  const panel = el("section", { class: "panel", "aria-labelledby": "h-lands" },
    el("h3", { id: "h-lands", text: "Land count" }),
    modal ? el("p", { class: "sub", text: `${num(lands.effective)} counted: ${lands.lands} lands + spell // land cards.` }) : null,
    chart);
  if (lands.recommended != null) {
    panel.append(el("ul", { class: "legend", "aria-label": "Legend" },
      el("li", {}, el("span", { class: "swatch-dot" }), `This deck: ${num(lands.effective)}`),
      el("li", {}, el("span", { class: "swatch-line" }), `Formula: ${num(lands.recommended)}`),
      el("li", {}, el("span", { class: "swatch swatch-band" }), `Within ${num(lands.band)}`),
      el("li", {}, el("span", { class: "swatch swatch-band2" }), `Within ${num(2 * lands.band)}`)));
    chartJobs.push([chart, (width) => drawLandChart(chart, lands, width)]);
  }
  if (lands.verdict_text) panel.append(el("p", { class: "verdict-text", text: lands.verdict_text }));
  const how = explain(null, "Lands make your mana: too few and you get stuck, too many and you run out of things to do. " +
      "Frank Karsten's formula, fitted to thousands of winning decks, estimates the lands a deck needs " +
      "from its average mana value and how many cheap card-draw and mana spells it has.");
  how.append(el("div", { class: "formula" },
    el("p", {}, el("b", { text: "Formula: " }), f.text || "none for this deck size"),
    f.worked ? el("p", {}, el("b", { text: "Worked out: " }), f.worked) : null,
    f.status ? el("p", { class: "sub" }, f.published === false ? status("warn", "Our extrapolation") : null,
      f.published === false ? " " : "", f.status) : null));
  if (lands.floor) {
    panel.append(el("p", { class: "sub", text: `Karsten's advice for Commander: never fewer than ${lands.floor} lands.` }));
  }
  const cheap = lands.cheap || {};
  const cheapCards = [...(cheap.draw || []), ...(cheap.ramp || [])];
  how.append(el("p", { class: "sub" }, "Each cheap card-draw or mana spell (mana value 2 or less) lets the deck " +
    `play about a quarter of a land fewer: ${plural(cheap.count || 0, "card")} here.`,
  cheapCards.length ? cardNames(cheapCards) : null));
  if (modal) {
    how.append(el("p", { class: "sub" }, "Spell // land cards count as part of a land (0.38 if the land " +
      "always enters tapped, 0.74 if it can enter untapped): ", cardNames(lands.mdfc.cards)));
  }
  const makers = [...(lands.mana_creatures || []), ...(lands.mana_rocks || [])];
  if (makers.length) {
    panel.append(el("details", { class: "more" },
      el("summary", { text: `Mana creatures and rocks (${makers.length})` }),
      el("p", { class: "sub", text: "They make mana but aren't lands. Cheap ones (mana value 2 or less) lower the " +
        "formula's land count; the rest help with colours only." }),
      cardNames(makers.map((mk) => ({ name: `${mk.name}`, qty: mk.qty }))),
      el("ul", { class: "sources-list" }, makers.map((mk) =>
        el("li", { text: `${mk.name}: mana value ${num(mk.mv)}, makes ${mk.produces.split("").map((c) => COLOUR_WORDS[c] || c).join(" / ")}${mk.cheap ? " (cheap)" : ""}` })))));
  }
  if (lands.rule_of_thumb) {
    const cited = (lands.rule_of_thumb.sources || []).map((id) => statsSourceCitation(sources, id)).filter(Boolean);
    how.append(el("p", { class: "sub" }, el("b", { text: "Rule of thumb: " }), lands.rule_of_thumb.text,
      cited.length ? [". From: ", cited.map((a, i) => [i ? "; " : "", a]), "."] : "."));
  }
  const link = statsSourceCitation(sources, f.source);
  if (link) how.append(el("p", { class: "sub" }, "Source: ", link));
  panel.append(how);
  return panel;
}

function drawLandChart(host, lands, width) {
  const rec = lands.recommended, eff = lands.effective, b = lands.band || 1;
  const height = 78;
  const m = { left: 12, right: 12 };
  let lo = Math.floor(Math.min(eff, rec - 2 * b) - 1);
  let hi = Math.ceil(Math.max(eff, rec + 2 * b) + 1);
  if (hi - lo < 6) { lo -= 1; hi += 1; }
  const x = (v) => m.left + (v - lo) / (hi - lo) * (width - m.left - m.right);
  const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": `This deck has ${num(eff)} lands; the formula says ${num(rec)}.` });
  const top = 26, h = 16;
  svg.append(
    svgEl("rect", { class: "band-slight", x: x(rec - 2 * b), y: top, width: x(rec + 2 * b) - x(rec - 2 * b), height: h }),
    svgEl("rect", { class: "band-ok", x: x(rec - b), y: top, width: x(rec + b) - x(rec - b), height: h }));
  const step = hi - lo > 14 ? 2 : 1;
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    svg.append(svgEl("line", { class: "base", x1: x(v), x2: x(v), y1: top + h + 4, y2: top + h + 8 }),
      svgEl("text", { class: "axis-text", x: x(v), y: top + h + 22, "text-anchor": "middle", text: String(v) }));
  }
  const labelX = Math.min(Math.max(x(rec), 40), width - 40);
  svg.append(
    svgEl("line", { class: "rec", x1: x(rec), x2: x(rec), y1: top - 6, y2: top + h + 6 }),
    svgEl("text", { class: "label-text", x: labelX, y: top - 11, "text-anchor": "middle", text: `formula ${num(rec, 1)}` }),
    svgEl("circle", { class: "you", cx: x(eff), cy: top + h / 2, r: 7 }));
  host.replaceChildren(svg);
}

// Colour sources --------------------------------------------------------------

function colourPips(colours) {
  const wrap = el("span", { class: "cost", role: "img",
    "aria-label": colours.length ? colours.map((c) => COLOUR_WORDS[c] || c).join(", ") : "No coloured mana" });
  // Scryfall's symbols (symbols.js), the lettered circle only when a picture can't load; the words are the wrap's.
  for (const c of colours) wrap.append(symbolImg(c, { small: true, alt: "" }));
  return wrap;
}

function checkWords(check) {
  const who = check.cards && check.cards.length ? check.cards.map((c) => c.name).join(", ") : "";
  return { cost: manaCost(costToSymbols(check.cost_in_colours), true), who };
}

function colourPanel(st) {
  const c = st.colours;
  const panel = el("section", { class: "panel", "aria-labelledby": "h-colours" },
    el("h3", { id: "h-colours", text: "Colour sources" }));
  const how = explain(null, "A colour source is anything that can make mana of that colour: mostly lands, plus some mana " +
      "creatures and rocks. The more symbols of a colour a card needs, and the earlier you want to cast it, the " +
      "more sources you need. Frank Karsten's tables give the number for about a 90% chance of casting each " +
      "spell on the turn matching its mana value.");
  if (!c || !c.colours || !c.colours.length) {
    panel.append(el("p", { class: "sub", text: "This deck's spells need no coloured mana." }));
    return panel;
  }
  if (c.table_note) how.append(el("p", { class: "sub", text: c.table_note }));
  if (c.land_note) how.append(el("p", { class: "sub", text: c.land_note }));
  if (c.table != null) {
    panel.append(el("ul", { class: "legend", "aria-label": "Legend" },
      el("li", {}, el("span", { class: "swatch", style: "background: var(--series-1)" }), "Sources"),
      el("li", {}, el("span", { class: "swatch", style: "background: var(--crit)" }), "Sources (short)"),
      el("li", {}, el("span", { class: "swatch-line" }), "Needed for the hardest card")));
  }
  const rows = c.colours;
  const scaleMax = niceScale(Math.max(1, ...rows.map((r) => Math.max(r.hardest.have || 0, r.hardest.needed || 0)))).top;
  const list = el("ul", { class: "colour-list" });
  for (const summary of rows) list.append(colourRow(summary, scaleMax));
  panel.append(list);

  if (c.sources && c.sources.length) {
    // Each: what one copy is worth. An uncounted source is worth 0 (its note says why), and
    // cheap card draw has no one weight (it depends on the colour's share of the deck).
    const each = (s) => (s.counted === false ? "0" : s.weight == null ? "-" : num(s.weight));
    panel.append(el("details", { class: "more" },
      el("summary", { text: `What counts as a source (${c.sources.length})` }),
      el("table", { class: "data sources-table" },
        el("colgroup", {}, el("col"), el("col", { class: "c-makes" }), el("col", { class: "c-each" })),
        el("thead", {}, el("tr", {},
          el("th", { scope: "col", text: "Card" }), el("th", { scope: "col", text: "Makes" }),
          el("th", { scope: "col", class: "num", text: "Each" }))),
        el("tbody", {}, c.sources.map((s) => el("tr", {},
          el("th", { scope: "row" }, cardLink({ name: s.name, qty: s.qty }),
            s.note ? el("small", { class: "sub source-note", text: capitalise(s.note) }) : null),
          el("td", {}, colourPips(s.colours.split("").filter((x) => COLOUR_WORDS[x]))),
          el("td", { class: "num", text: each(s) })))))));
  }
  if (c.rules && c.rules.length) {
    panel.append(el("details", { class: "more" }, el("summary", { text: "How sources are counted" }),
      el("ul", { class: "sources-list" }, c.rules.map((r) => el("li", { text: r }))),
      c.definition ? el("p", { class: "sub", text: c.definition }) : null));
  }
  const link = statsSourceCitation(st.sources, c.source);
  if (link) how.append(el("p", { class: "sub" }, "Source: ", link));
  panel.append(how);
  return panel;
}

function colourRow(summary, scaleMax) {
  const h = summary.hardest;
  const hasTable = h.needed != null;
  const verdict = summary.ok == null ? null
    : summary.ok ? el("span", { class: "numbers", text: "enough" }) : status("warn", `Short by ${num(-h.margin)}`);
  const numbers = hasTable ? `${num(h.have)} of ${h.needed} needed` : `${num(h.have)} sources`;
  const bar = el("div", { class: "chart colour-bar", "aria-hidden": "true" });
  chartJobs.push([bar, (width) => drawColourBar(bar, h, summary.ok, scaleMax, width)]);
  const { cost, who } = checkWords(h);
  const text = el("p", { class: "colour-text" },
    hasTable ? "Hardest to cast on time: " : "Most demanding: ", cost, ` by turn ${h.turn}`,
    hasTable ? `, which needs ${h.needed} ${summary.name} sources` : "",
    `; the deck has ${num(h.have)} (${num(h.have_lands)} from lands).`,
    who ? [" Cards: ", el("b", { text: who }), "."] : null);
  const more = summary.short && summary.short.length > 1
    ? ` ${summary.short.length - 1} more ${summary.name} requirement${summary.short.length > 2 ? "s are" : " is"} short.` : "";
  const li = el("li", {},
    el("div", { class: "colour-head" }, colourPips(summary.colours.split("")),
      el("b", { text: capitalise(summary.name) }), el("span", { class: "numbers", text: numbers }), verdict),
    bar, text, checkNotes(h), more ? el("p", { class: "colour-text", text: more }) : null);
  if (summary.checks && summary.checks.length > 1) {
    li.append(el("details", { class: "more" },
      el("summary", { text: `Every ${summary.name} requirement (${summary.checks.length})` }),
      checksTable(summary.checks)));
  }
  return li;
}

/** Why a requirement's number is what it is (a gold card's +1, X counted as 1, a turn
 * past 7...), from the stats' notes; null when there's nothing to say. */
function checkNotes(check) {
  if (!check.notes || !check.notes.length) return null;
  return el("ul", { class: "check-notes" }, check.notes.map((n) => el("li", { text: capitalise(n) })));
}

/** Every requirement of a colour: one <tbody> each, with its numbers on the first row and
 * its cards and notes across the whole width below, so names have room on a phone. */
function checksTable(checks) {
  return el("table", { class: "data checks-table" },
    el("colgroup", {}, el("col"), el("col", { class: "c-need" }), el("col", { class: "c-have" })),
    el("thead", {}, el("tr", {},
      el("th", { scope: "col", text: "Cost, turn" }),
      el("th", { scope: "col", class: "num", text: "Need" }),
      el("th", { scope: "col", class: "num", text: "Have" }))),
    checks.map((k) => el("tbody", { class: k.ok === false ? "is-missing" : null },
      el("tr", {},
        el("th", { scope: "row" }, manaCost(costToSymbols(k.cost_in_colours), true), ` turn ${k.turn}`,
          k.published === false ? el("small", { class: "sub", text: " (computed)" }) : null),
        el("td", { class: "num", text: k.needed == null ? "-" : String(k.needed) }),
        el("td", { class: "num missing-n", text: num(k.have) })),
      el("tr", { class: "label-row" }, el("td", { colspan: 3 },
        k.ok === false ? el("div", { class: "row-labels" }, status("warn", `Short by ${num(-k.margin)}`)) : null,
        cardNames(k.cards),
        checkNotes(k))))));
}

function drawColourBar(host, check, ok, scaleMax, width) {
  // The bar, the needed mark, and its own scale underneath, so the numbers sit by the bar.
  const height = 40, y = 7, h = 12;
  const x = (v) => Math.max(0, Math.min(v / scaleMax, 1)) * width;
  const kind = ok == null ? "fill-none" : ok ? "fill-ok" : "fill-short";
  const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}` },
    svgEl("rect", { class: "track", x: 0, y, width, height: h, rx: 2 }),
    svgEl("path", { class: kind, d: barPath(0, y, x(check.have || 0), h, 4) }));
  if (check.needed != null) {
    const nx = Math.min(Math.max(x(check.needed), 1), width - 1);
    svg.append(svgEl("line", { class: "need", x1: nx, x2: nx, y1: 1, y2: y + h + 6 }));
  }
  const step = niceScale(scaleMax).step;
  for (let v = 0; v <= scaleMax; v += step) {
    const anchor = v === 0 ? "start" : v >= scaleMax ? "end" : "middle";
    svg.append(svgEl("line", { class: "base", x1: x(v), x2: x(v), y1: y + h, y2: y + h + 3 }),
      svgEl("text", { class: "axis-text", x: x(v), y: height - 2, "text-anchor": anchor, text: String(v) }));
  }
  host.replaceChildren(svg);
}

// Types, roles, tribes and keywords ------------------------------------------

function barList(items, labelOf, hintOf) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return el("ul", { class: "bar-list" }, items.map((item) => {
    const bar = el("span", { class: "bar" + (item.count ? "" : " zero"), "aria-hidden": "true" });
    bar.style.width = `${Math.round(item.count / max * 100)}%`;
    const parts = [el("span", { class: "bar-label" }, labelOf(item),
      hintOf ? el("span", { class: "sr-only", text: `: ${hintOf(item)}` }) : null),
      el("span", {}, bar), el("span", { class: "bar-count", text: num(item.count) })];
    if (!item.count || !item.cards || !item.cards.length) return el("li", {}, el("div", { class: "row" }, parts));
    return el("li", {}, el("details", {}, el("summary", {}, parts), cardNames(item.cards)));
  }));
}

function compositionPanel(st) {
  const types = (st.types || []).filter((t) => t.count > 0);
  // Roles the deck has none of aren't listed ("Counterspells 0" says nothing).
  const roles = (st.roles || []).filter((r) => r.count > 0);
  return el("section", { class: "panel", "aria-labelledby": "h-types" },
    el("h3", { id: "h-types", text: "Card types and roles" }),
    el("p", { class: "sub", text: "Copies of each card type (a card can have two, like an artifact creature). Tap a row to list its cards." }),
    barList(types, (t) => capitalise(t.type)),
    el("h4", { text: "Roles", style: "margin-top: 16px" }),
    roles.length ? barList(roles, (r) => (ROLE_WORDS[r.role] || [capitalise(r.role)])[0],
      (r) => (ROLE_WORDS[r.role] || ["", ""])[1]) : el("p", { class: "sub", text: "No cards with a listed role." }),
    explain("Where do roles come from?", "Roles come from Scryfall's community tags, so a card can have several roles or none. " +
      "Removal deals with the other player's cards; ramp gives you extra mana sooner; card draw gets you more cards."));
}

function tribesPanel(st) {
  const tribes = (st.tribes && st.tribes.types) || [];
  const keywords = st.keywords || [];
  const panel = el("section", { class: "panel", "aria-labelledby": "h-tribes" },
    el("h3", { id: "h-tribes", text: "Creature types and keywords" }),
    el("p", { class: "sub", text: "Creature types matter for cards that care about them (\"other Elves you control get +1/+1\")." }));
  const topN = (items, n, render, what) => {
    panel.append(render(items.slice(0, n)));
    if (items.length > n) {
      panel.append(el("details", { class: "more" }, el("summary", { text: `${items.length - n} more ${what}` }),
        render(items.slice(n))));
    }
  };
  if (tribes.length) topN(tribes, 6, (list) => barList(list, (t) => t.type), "creature types");
  else panel.append(el("p", { class: "sub", text: "No creatures." }));
  const ch = st.tribes && st.tribes.changelings;
  if (ch && ch.count) panel.append(el("p", { class: "sub" }, `${plural(ch.count, "changeling")}: ${ch.note} `, cardNames(ch.cards)));
  panel.append(el("h4", { text: "Keywords", style: "margin-top: 16px" }),
    el("p", { class: "sub", text: "Abilities with a one-word name, like Flying or Trample; the card's reminder text explains each." }));
  if (keywords.length) topN(keywords, 6, (list) => barList(list, (k) => k.keyword), "keywords");
  else panel.append(el("p", { class: "sub", text: "No keywords." }));
  return panel;
}

// Chance to draw -------------------------------------------------------------

const ODDS_MAX_TURN = 20;
const ODDS_TABLE_TURNS = 7;

/** The chance that n cards drawn from a library of size cards, hits of which count, include at least one
 * hit: 1 - C(size - hits, n) / C(size, n), multiplied out term by term so no binomial grows too big. */
function chanceOfAtLeastOne(size, hits, n) {
  if (hits <= 0 || n <= 0 || size <= 0) return 0;
  if (n > size - hits) return 1;
  let none = 1;
  for (let i = 0; i < n; i++) none *= (size - hits - i) / (size - i);
  return 1 - none;
}

/** How many cards a player has seen by the start of a turn's main phase: the opening seven and one draw a
 * turn, except the first when on the play. Never more than the library holds. */
function cardsSeenBy(turn, onPlay, size) {
  return Math.min(size, 7 + turn - (onPlay ? 1 : 0));
}

/** A deck's "Chance to draw": pick a card, or several as a group (any of them counts), a turn and play or
 * draw, and the exact chance of seeing at least one by then. Worked out on the page from the shown list's
 * main deck (data.sections.Deck): a Commander's commander and a companion start outside the library, the
 * sideboard isn't drawn from. It ignores mulligans and card draw, and says so. null for a Beginner Box half,
 * which is never played on its own, and for a list too small to deal seven from. */
function drawOddsPanel(data) {
  if (!data.sections || (data.summary && data.summary.id.startsWith(BOX_PREFIX))) return null;
  const lines = mergedLines(data.sections.Deck || []).sort((a, b) => {
    const ga = typeGroup(a.card) === "Lands" ? 1 : 0, gb = typeGroup(b.card) === "Lands" ? 1 : 0;
    return ga - gb || byCostThenName(a, b);
  });
  const size = copies(lines);
  if (size < 7) return null;
  const commander = data.summary && (data.summary.kind === "commander" || data.summary.id.split("/").includes("commander"));
  const picked = new Set();
  let turn = 3, onPlay = !commander;
  const result = el("div", { class: "odds-result", "aria-live": "polite" });
  const turnInput = el("input", { type: "number", min: "1", max: String(ODDS_MAX_TURN), step: "1", value: String(turn),
    inputmode: "numeric",
    oninput: () => {
      const n = Number(turnInput.value);
      if (Number.isInteger(n) && n >= 1 && n <= ODDS_MAX_TURN) { turn = n; show(); }
    },
    onchange: () => { turnInput.value = String(turn); } });
  const seats = [[true, "On the play"], [false, "On the draw"]];
  const seat = el("div", { class: "segmented", role: "group", "aria-label": "Play or draw" });
  for (const [value, label] of seats) {
    seat.append(el("button", { type: "button", text: label, "aria-pressed": String(onPlay === value),
      onclick: () => {
        onPlay = value;
        Array.from(seat.children).forEach((b, i) => b.setAttribute("aria-pressed", String(seats[i][0] === value)));
        show();
      } }));
  }
  const boxes = [];
  const list = el("ul", { class: "odds-cards", "aria-label": "Cards to look for" }, lines.map((line) => {
    const box = el("input", { type: "checkbox", value: line.name, onchange: () => {
      if (box.checked) picked.add(line.name); else picked.delete(line.name);
      show();
    } });
    boxes.push([box, line]);
    return el("li", { "data-name": line.name.toLowerCase() },
      el("label", { class: "choice" }, box, el("span", { class: "odds-qty", text: `${line.qty}` }), el("span", { text: line.name })));
  }));
  const filter = el("input", { type: "search", placeholder: "Find a card", "aria-label": "Find a card in the list",
    oninput: () => {
      const words = filter.value.trim().toLowerCase();
      for (const item of list.children) item.hidden = Boolean(words) && !item.dataset.name.includes(words);
    } });
  const setAll = (test) => {
    for (const [box, line] of boxes) {
      box.checked = test(line);
      if (box.checked) picked.add(line.name); else picked.delete(line.name);
    }
    show();
  };
  const lands = boxes.some(([, line]) => typeGroup(line.card) === "Lands");
  const panel = el("section", { class: "panel wide", "aria-labelledby": "h-odds" },
    el("h3", { id: "h-odds", text: "Chance to draw" }),
    el("p", { class: "sub", text: "Tick a card, or several to count any of them, then choose the turn." }),
    el("div", { class: "odds-settings" },
      el("label", { class: "field odds-turn" }, el("span", { text: `By turn (1 to ${ODDS_MAX_TURN})` }), turnInput),
      seat),
    result,
    el("div", { class: "odds-picker" },
      el("div", { class: "toolbar odds-tools" }, filter,
        lands ? el("button", { type: "button", class: "btn btn-quiet", text: "All lands",
          onclick: () => setAll((line) => typeGroup(line.card) === "Lands") }) : null,
        ...oddsCategoryButtons(lines, setAll),
        el("button", { type: "button", class: "btn btn-quiet", text: "Clear", onclick: () => setAll(() => false) })),
      list),
    explain("How is this worked out?",
      `It's the exact chance that the cards seen by then include at least one of those ticked: the opening seven, ` +
      `then one draw each turn (none on turn 1 on the play), from a library of ${plural(size, "card")} shuffled at random.`,
      commander ? "In Commander the commander starts in the command zone, so the library is the rest of the deck. " +
        "At a multiplayer table nobody skips their first draw: choose On the draw." : null,
      "It ignores mulligans and any extra cards drawn, searched for or looked at, so a real game usually finds them a little sooner."));
  function show() {
    clear(result);
    const ticked = lines.filter((line) => picked.has(line.name));
    if (!ticked.length) {
      result.append(noneSelected("Tick a card below to see the chance of drawing it."));
      return;
    }
    const hits = copies(ticked);
    const seen = cardsSeenBy(turn, onPlay, size);
    const what = ticked.length === 1 ? `the ${plural(hits, "copy", "copies")} of ${ticked[0].name}`
      : `the ${ticked.length} cards ticked (${plural(hits, "copy", "copies")} in all)`;
    const draws = seen - 7;
    result.append(el("div", { class: "tiles" },
      tile(`By turn ${turn}`, pct(chanceOfAtLeastOne(size, hits, seen)), onPlay ? "on the play" : "on the draw")),
      el("p", { text: `The chance of seeing at least one of ${what} in your first ${seen} cards: the opening seven` +
        (draws > 0 ? ` and ${plural(draws, "draw")}` : "") + `, from ${plural(size, "card")}. Mulligans and extra card draw aren't counted.` }),
      el("div", { class: "odds-table-wrap" }, el("table", { class: "odds-table" },
        el("caption", { class: "sr-only", text: "The chance by each turn" }),
        el("thead", {}, el("tr", {}, el("th", { scope: "row", text: "Turn" }),
          Array.from({ length: ODDS_TABLE_TURNS }, (_, i) => el("th", { scope: "col", text: String(i + 1) })))),
        el("tbody", {}, el("tr", {}, el("th", { scope: "row", text: "Chance" }),
          Array.from({ length: ODDS_TABLE_TURNS }, (_, i) => el("td", {
            class: i + 1 === turn ? "is-current" : null,
            text: pctShort(chanceOfAtLeastOne(size, hits, cardsSeenBy(i + 1, onPlay, size))) })))))));
  }
  show();
  return panel;
}

// Commander checks -----------------------------------------------------------

/** One Commander rule: a quiet tick when it's kept (no chip for "all fine"), a chip when it's broken or
 * couldn't be checked. */
function checkItem(ok, what, ...detail) {
  const mark = ok == null ? status("plain", "Not checked") : ok
    ? el("span", { class: "check-ok", role: "img", "aria-label": "Kept", text: "✓" }) : status("crit", "Problem");
  return el("li", {}, mark, el("span", { class: "what", text: what }),
    detail.length ? el("div", { class: "detail" }, detail) : null);
}

function commanderPanel(st, summary) {
  const k = st.commander;
  const br = k.bracket || {};
  const names = (list) => (list && list.length ? cardNames(list.map((x) => (typeof x === "string" ? { name: x } : x))) : null);
  const checks = el("ul", { class: "checks" },
    checkItem(k.size.ok, `${k.size.cards} of ${k.size.expected} cards`, k.size.note),
    checkItem(k.eligibility.ok, `Commander: ${k.commanders.join(" and ") || "none"}`,
      ...(k.eligibility.problems || []).map((p) => el("div", { text: p }))),
    checkItem(k.singleton.ok, "One copy of each card",
      k.singleton.duplicates.length ? `Too many copies: ${k.singleton.duplicates.map((d) => `${d.name} (${d.copies}, limit ${d.limit})`).join(", ")}.` : "Basic lands excepted.",
      k.singleton.allowed.length ? ` Allowed by their own text: ${k.singleton.allowed.map((a) => `${a.name} (${a.copies})`).join(", ")}.` : null),
    checkItem(k.identity.checked === false ? null : k.identity.ok, "Colour identity",
      k.colour_identity ? ["Every card fits the commander's colours: ", colourPips(k.colour_identity.split(""))]
        : "The commander is colourless, so every card must be too.",
      k.identity.outside.length ? el("div", { text: `Outside: ${k.identity.outside.map((o) => `${o.name} (${o.outside})`).join(", ")}` }) : null),
    checkItem(k.legality.ok, "Ban list",
      k.legality.banned.length ? ["Banned: ", names(k.legality.banned)] : "No banned cards.",
      k.legality.banned_as_companion.length ? ["Banned as a companion: ", names(k.legality.banned_as_companion)] : null,
      k.legality.not_legal.length ? ["Not legal in Commander: ", names(k.legality.not_legal)] : null),
    checkItem(true, `Game Changers: ${(br.game_changers || []).length}`,
      "Cards Wizards lists as swinging games hardest. Brackets 1-2 allow none, Bracket 3 up to three.",
      names(br.game_changers), commanderDataNote(br)),
    checkItem(br.mass_land_denial == null ? null : true, `Mass land denial: ${br.mass_land_denial == null ? "not checked" : br.mass_land_denial.length}`,
      names(br.mass_land_denial)),
    checkItem(br.extra_turns == null ? null : true, `Extra turns: ${br.extra_turns == null ? "not checked" : br.extra_turns.length}`,
      names(br.extra_turns)),
    checkItem(comboCheck(br) ? true : null, `Two-card combos: ${comboCheck(br) ? comboCheck(br).matches.length : "not checked"}`,
      comboFindings(br, "names", false)));
  const target = summary.target_bracket;
  const panel = el("section", { class: "panel", "aria-labelledby": "h-commander" },
    el("h3", { id: "h-commander", text: "Commander rules" }),
    el("p", {}, k.ok ? "Follows the deck rules." : status("crit", "Breaks a deck rule")),
    k.problems && k.problems.length ? el("ul", { class: "sources-list" }, k.problems.map((p) => el("li", { text: p }))) : null,
    checks,
    el("div", { class: "formula", style: "margin-top: 12px" },
      el("p", {}, el("b", { text: "Minimum bracket: " }), br.label || "?"),
      (br.reasons || []).map((r) => el("p", { class: "sub", text: r })),
      target ? el("p", { class: "sub", text: `The deck aims for Bracket ${target}.` }) : null));
  panel.append(explain("What are the rules and brackets?", "A Commander deck has exactly 100 cards including the " +
    "commander, one copy of each card (basic lands excepted), and only cards within the commander's colours. Brackets " +
    "(1 to 5) describe how strong a deck is, so a table can match decks of similar power."));
  if (br.not_automatic && br.not_automatic.length) {
    panel.append(el("details", { class: "more" }, el("summary", { text: "What Deck Lab can't judge" }),
      el("ul", { class: "sources-list" }, br.not_automatic.map((t) => el("li", { text: t })))));
  }
  if (br.brackets && br.brackets.length) {
    // A list rather than a four-column table, which is too narrow to read on a phone.
    panel.append(el("details", { class: "more" }, el("summary", { text: "The five brackets" }),
      el("ul", { class: "bracket-list" }, br.brackets.map((b) => el("li", {},
        el("p", {}, el("b", { text: `${b.number} ${b.name}` }),
          b.min_turns ? el("span", { class: "sub", text: ` (games last ${b.min_turns}+ turns)` }) : null),
        el("dl", {},
          el("div", {}, el("dt", { text: "Game Changers" }), el("dd", { text: b.game_changers == null ? "any" : String(b.game_changers) })),
          el("div", {}, el("dt", { text: "Mass land denial" }), el("dd", { text: b.mass_land_denial })),
          el("div", {}, el("dt", { text: "Extra turns" }), el("dd", { text: b.extra_turns })),
          el("div", {}, el("dt", { text: "Two-card combos" }), el("dd", { text: b.two_card_combos }))),
        b.note ? el("p", { class: "sub", text: b.note }) : null))),
      (br.sources || []).map((id) => statsSourceCitation(st.sources, id)).filter(Boolean).map((a) => el("p", { class: "sub" }, a))));
  }
  return panel;
}

function sideboardPanel(st) {
  const sb = st.sideboard;
  const short = (sb.checks || []).filter((k) => k.ok === false);
  return el("section", { class: "panel", "aria-labelledby": "h-side" },
    el("h3", { id: "h-side", text: `Sideboard (${sb.count})` }),
    el("p", { class: "sub", text: "Cards kept aside to swap in between games. They aren't in the stats above, but their colours are checked against the main deck's sources." }),
    cardNames(sb.cards),
    short.length ? [el("h4", { text: "Short on sources", style: "margin-top: 12px" }), checksTable(short)]
      : el("p", { class: "sub", text: "The main deck has enough sources for them." }));
}

/** The ids of the sources the stats cite ("source" and "sources" values anywhere in them). */
function citedSources(value, found = new Set()) {
  if (Array.isArray(value)) value.forEach((v) => citedSources(v, found));
  else if (value && typeof value === "object") {
    for (const [key, v] of Object.entries(value)) {
      if (key === "sources" && Array.isArray(v)) v.forEach((id) => typeof id === "string" && found.add(id));
      else if (key === "source" && typeof v === "string") found.add(v);
      else if (key !== "sources") citedSources(v, found);
    }
  }
  return found;
}

function sourcesPanel(st) {
  const cited = citedSources(st);
  const entries = Object.entries(st.sources || {}).filter(([id]) => cited.has(id));
  if (!entries.length) return null;
  return el("section", { class: "panel wide", "aria-labelledby": "h-sources" },
    el("h3", { id: "h-sources", text: "Where the numbers come from" }),
    el("ul", { class: "sources-list" }, entries.map(([id]) => el("li", {}, statsSourceCitation(st.sources, id)))));
}
