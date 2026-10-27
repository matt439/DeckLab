/* Deck Lab's page: the deck view's "Practice games" part (on its Practice tab, under "Deal a hand"), the
practice-game simulation.

A result saved on the PC comes with the deck (/api/deck's "practice") and is drawn at once. Otherwise the
part asks /api/goldfish when the Practice tab first opens (deck.js draws a tab's parts then, so a deck
opened only for its card list costs the PC nothing), then asks again every POLL_MS until the run is done;
while its height changes, keepPlace() (app.js) keeps what the reader is looking at where it was. The
explanations sit in closed "How…" disclosures under the numbers. A Beginner Box half gets links to its
pairings instead: it's only ever played in one.

Loaded after stats.js and before app.js. It uses core.js's helpers (api, progressBar, pct, POLL_MS,
routeToken, ...), deck.js's cardLink() and pairingLinks(), stats.js's charts (chartJobs, drawCharts,
tile, niceScale, columnPath, colourPips, explain) and, once the page is running, app.js's keepPlace().
*/
"use strict";

function ordinal(n) {
  const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th";
  return `${n}${s}`;
}

/** "2, 3 or 4" */
function orList(items) {
  return items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} or ${items[items.length - 1]}`;
}

/** The part of the deck view with the practice-game simulation. A result saved on the PC comes
 * with the deck (data.practice) and is drawn at once; otherwise the run starts now (the Practice tab has
 * just opened), and the answer replaces what's in it. A Beginner Box half links to its pairings. */
function practiceSection(data) {
  const body = el("div", { class: "practice" });
  const section = el("section", { class: "deck-section", id: "sec-practice", "aria-labelledby": "h-practice" },
    el("h2", { id: "h-practice", text: "Practice games" }), body);
  const token = routeToken;
  if (data.summary.id.startsWith(BOX_PREFIX)) {
    // A half's 20 cards are never played alone, and would give numbers no real game has.
    body.append(note("A Beginner Box half is never played on its own: it's shuffled together with another " +
      "half into a 40-card deck. So Deck Lab plays practice games with the pairings, not with these 20 cards."),
    pairingLinks(data.summary.id, "Practice games for its pairings:"));
    return section;
  }
  const answer = data.practice;
  if (answer && answer.status === "done") {
    drawPractice(body, answer.result, data);        // its charts are drawn with the rest of the page
    return section;
  }
  if (answer && answer.status === "error") {
    practiceError(body, data, token, new ApiError(0, answer.error));
    return section;
  }
  // Started once the part is on the page (its tab has just opened), so keepPlace can measure around it.
  body.append(loadingBox("Getting the practice games ready…"));
  setTimeout(() => { if (token === routeToken) runPractice(body, data, token, false); }, 0);
  return section;
}

/** Ask for the result until it's there, showing progress meanwhile. retry: start a failed run again. */
async function runPractice(body, data, token, retry) {
  const base = `/api/goldfish?id=${encodeURIComponent(data.summary.id)}&version=${data.version}`;
  const progress = practiceProgress();
  // Each change to the part keeps the reader's place below it (keepPlace).
  keepPlace(() => clear(body).append(progress.node));
  let url = base + (retry ? "&retry=1" : "");
  const current = () => token === routeToken && body.isConnected;
  for (;;) {
    let answer;
    try {
      answer = await api(url);
    } catch (e) {
      if (current()) keepPlace(() => practiceError(body, data, token, e));
      return;
    }
    if (!current()) return;
    if (answer.status === "done") {
      keepPlace(() => drawPractice(body, answer.result, data));
      return;
    }
    if (answer.status === "error") {
      keepPlace(() => practiceError(body, data, token, new ApiError(0, answer.error)));
      return;
    }
    keepPlace(() => progress.update(answer));
    url = base;             // the next asks join the run this one started
    await sleep(POLL_MS);
    if (!current()) return;
  }
}

function practiceProgress() {
  const title = el("h3", { text: "Getting the practice games ready…" });
  const bar = progressBar("Practice games played");
  const setBar = bar.set;
  // The count changes on every answer, so it isn't announced; the title is, only when it changes.
  const text = el("p", { text: "Asking the PC…" });
  const phase = el("p", { class: "sr-only", role: "status" });
  const announce = () => { if (phase.textContent !== title.textContent) phase.textContent = title.textContent; };
  const node = el("div", { class: "box box-info practice-running" },
    el("div", { class: "practice-running-head" }, el("span", { class: "spinner", "aria-hidden": "true" }), title),
    phase, bar.node, text,
    el("p", { class: "sub", text: "It takes a second or two on the PC, once for each list. After that the " +
      "results are saved and show at once." }));
  return {
    node,
    update(answer) {
      const { done, total } = answer.progress || {};
      if (answer.queued && answer.ahead > 0) {
        // (Queued with none ahead is the moment before a free thread picks it up.)
        title.textContent = "Waiting for another simulation";
        const n = answer.ahead;
        text.textContent = `${plural(n, "other run")} ${n === 1 ? "is" : "are"} ahead of this one; ` +
          `it starts as soon as ${n === 1 ? "that's" : "they're"} done.`;
        setBar(0);
      } else if (total) {
        title.textContent = "Playing practice games…";
        text.textContent = `${thousands(done)} of ${thousands(total)} games played.`;
        setBar(done / total);
      } else {
        title.textContent = "Playing practice games…";
        text.textContent = "Starting…";
      }
      announce();
    },
  };
}

function practiceError(body, data, token, error) {
  const code = error.status ? ` (error ${error.status})` : "";
  clear(body).append(el("div", { class: "box box-crit", role: "alert" },
    el("h3", { text: "The practice games couldn't be played" }),
    el("p", { text: error.message + code }),
    el("div", { class: "actions" }, el("button", { type: "button", class: "btn btn-primary", text: "Try again",
      onclick: () => runPractice(body, data, token, true) }))));
}

/** A setup's button: its name, and a few words under it (a Commander deck's two-player games are 1v1). */
function setupButton(setup, kind, onclick) {
  const oneVsOne = kind === "commander" ? "1v1, " : "";
  const sub = { multiplayer: "3 or more players", play: `${oneVsOne}you go first`, draw: `${oneVsOne}you go second` };
  return el("button", { type: "button", onclick, "aria-label": [setup.label, sub[setup.id]].filter(Boolean).join(", ") },
    el("span", { class: "setup-main", text: setup.label }),
    sub[setup.id] ? el("span", { class: "setup-sub", text: sub[setup.id] }) : null);
}

function drawPractice(body, result, data) {
  const setups = result.setups;
  const ids = setups.map((s) => s.id);
  const remembered = state.practiceSetup[result.kind];
  const panels = el("div", { class: "panels" });
  const setupText = el("p", { class: "sub setup-text" });
  const buttons = setups.map((s) => setupButton(s, result.kind, () => choose(s.id)));
  function choose(id) {
    state.practiceSetup[result.kind] = id;
    buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(ids[i] === id)));
    // The rule numbers (CR 103.8a) are in the sources at the bottom.
    setupText.textContent = setups.find((s) => s.id === id).text.replace(/\s*\(CR [^)]*\)/g, "");
    clear(panels).append(...setupPanels(result, result.results[id]));
    // Drawn with the deck page (drawDeck draws the charts once the page is in place), the charts
    // wait for that; afterwards they're drawn now.
    if (body.isConnected) drawCharts();
  }
  add(clear(body), [
    warningsBox(result.warnings, "About these practice games"),     // null when there are none
    el("div", { class: "setup-pick" },
      el("div", { class: "segmented", role: "group", "aria-label": "Which practice games to show" }, buttons)),
    panels,
    // The setup's sentence (it follows the choice), how the games work and what the numbers mean are
    // folded together; the lists of rules and cards stay their own disclosures under it.
    practiceIntro(result, data, setupText, ...practiceAbout(result)),
    practiceFinePrint(result)]);
  choose(ids.includes(remembered) ? remembered : ids[0]);
}

function practiceIntro(result, data, ...more) {
  const games = thousands(result.games);
  const d = result.deck;
  const lands = `${d.cards} cards, ${plural(d.lands, "land")}` +
    (d.spell_lands ? ` and ${plural(d.spell_lands, "spell // land card")}` : "");
  const what = result.kind === "commander"
    ? `${games} practice games of each kind below (multiplayer, and 1v1 on the play and on the draw)`
    : `${games} practice games on the play and ${games} on the draw`;
  return explain("How the practice games work",
    `Deck Lab played ${what} with this deck (${lands}), each for its first ${result.turns} turns and alone: ` +
      "there's no opponent.",
    "The simulated player follows simple rules. It mulligans a 7-card hand with fewer than 2 or more than 5 " +
      "lands. Each turn it plays a land if it has one, then casts the most expensive spells it can pay for. Mana " +
      "creatures help from the turn after they're cast, and ramp spells fetch a basic land. " +
      (result.kind === "commander" ? "The commander is cast from the command zone as soon as it fits. " : "") +
      "Card draw, Treasure and cost reductions aren't counted.",
    "So this measures the deck's mana and consistency: how often it has the lands and colours to cast its " +
      "spells on time. It says nothing about how well the deck plays against an opponent.",
    ...more);
}

function setupPanels(result, r) {
  return [mulliganPanel(r), landDropPanel(r), stuckPanel(r), practiceColourPanel(r), manaUsedPanel(r),
    firstBigPanel(r, result)];
}

/** A figure with a short unit, a name and one sentence saying what it means. */
function statRow(value, unit, name, sentence) {
  return el("li", {},
    el("div", { class: "stat-figure" }, el("span", { class: "stat-value", text: value }),
      unit ? el("span", { class: "stat-unit", text: unit }) : null),
    el("div", { class: "stat-words" }, el("b", { text: name }), el("p", { text: sentence })));
}

/** Rows of shares (0 to 1) as bars on a 0-100% scale, with the value at the end. */
function shareList(items) {
  return el("ul", { class: "bar-list share-list" }, items.map((item) => {
    const bar = el("span", { class: "bar" + (item.share ? "" : " zero"), "aria-hidden": "true" });
    bar.style.width = `${Math.max(0, Math.min(1, item.share || 0)) * 100}%`;
    return el("li", {}, el("div", { class: "row" },
      el("span", { class: "bar-label", text: item.label }), el("span", {}, bar),
      el("span", { class: "bar-count", text: pct(item.share) })));
  }));
}

/** A table of numbers in a "more" box: the chart's table view. */
function numbersTable(summary, heads, rows) {
  return el("details", { class: "more" }, el("summary", { text: summary }),
    el("table", { class: "data practice-table" },
      el("thead", {}, el("tr", {}, heads.map((h, i) => el("th", { scope: "col", class: i ? "num" : null, text: h })))),
      el("tbody", {}, rows.map((row) => el("tr", {},
        el("th", { scope: "row", text: row[0] }),
        row.slice(1).map((cell) => el("td", { class: "num", text: cell })))))));
}

// Opening hands -----------------------------------------------------------------

function mulliganPanel(r) {
  const m = r.mulligans;
  const free = m.free_rate != null;
  const kept7 = (m.kept.find((k) => k.cards === 7) || { share: 0 }).share;
  // In multiplayer about half of all 7s go back for the free mulligan, by design and at no cost, so the
  // number that costs cards comes first.
  const tiles = free
    ? [tile("Kept fewer than 7", pct(1 - kept7), "of games: mulligans that cost a card"),
      tile("Took the free mulligan", pct(m.free_rate), "of games: a new 7 at no cost")]
    : [tile("Mulligans", pct(m.rate), "of games")];
  return el("section", { class: "panel", "aria-labelledby": "h-mulligans" },
    el("h3", { id: "h-mulligans", text: "Opening hands" }),
    el("div", { class: "tiles" }, tiles),
    el("h4", { text: "Cards in the hand kept" }),
    shareList(m.kept.map((k) => ({ label: `${k.cards} cards`, share: k.share }))),
    explain("What's a mulligan?", "A mulligan is shuffling away an opening hand you don't want and drawing 7 new cards; then you put " +
      "one card on the bottom for each mulligan so far. The simulated player keeps 7 cards with 2 to 5 lands." +
      (free ? " In a multiplayer game the first mulligan is free (you keep 7), so it throws a free 7 back " +
        "unless it has 3 to 5 lands." : "")));
}

// Land drops --------------------------------------------------------------------

function landDropPanel(r) {
  const onTime = r.land_drops.on_time;
  const mana = r.land_drops.mana;
  const turns = [2, 3, 4, 5].filter((t) => onTime[t - 1] && mana[t - 1]);
  const chart = el("div", { class: "chart" });
  const detail = el("div", { class: "chart-detail", "aria-live": "polite" },
    noneSelected("Tap or point at a turn for its numbers."));
  const groups = turns.map((t) => ({
    label: `Turn ${t}`,
    values: [onTime[t - 1].chance, mana[t - 1].chance],
    aria: `Turn ${t}: ${ordinal(t)} land from hand ${pct(onTime[t - 1].chance)}, ${t} or more mana ` +
      `${pct(mana[t - 1].chance)}`,
  }));
  let active = -1;
  const show = (i) => {
    active = i;
    const t = turns[i];
    const m = mana[t - 1];
    for (const g of chart.querySelectorAll(".col")) g.classList.toggle("active", Number(g.dataset.i) === i);
    add(clear(detail), [
      el("p", {}, el("b", { text: `Turn ${t}` })),
      el("p", { text: `${pct(onTime[t - 1].chance)} of games had played a land from hand on each of turns 1 to ` +
        `${t}, so their ${ordinal(t)} land by turn ${t}.` }),
      el("p", { text: `${pct(m.chance)} had at least ${t} mana, counting mana creatures, rocks and ramp ` +
        `(${num(m.average)} mana on average).` })]);
  };
  chartJobs.push([chart, (width) => {
    drawChanceColumns(chart, groups, width, { classes: ["seg-1", "seg-2"], onPick: show,
      label: "Land drops on time, turns 2 to 5" });
    if (active >= 0) show(active);
  }]);
  return el("section", { class: "panel", "aria-labelledby": "h-drops" },
    el("h3", { id: "h-drops", text: "Land drops on time" }),
    el("ul", { class: "legend", "aria-label": "Legend" },
      el("li", {}, el("span", { class: "swatch", style: "background: var(--series-1)" }),
        "Nth land by turn N, from hand"),
      el("li", {}, el("span", { class: "swatch", style: "background: var(--series-2)" }),
        "At least N mana on turn N, with ramp")),
    chart,
    detail,
    numbersTable(`All ${onTime.length} turns as a table`,
      ["Turn N", "Nth land from hand", "At least N mana, with ramp", "Average mana"],
      onTime.map((d, i) => [String(d.turn), pct(d.chance), mana[i] ? pct(mana[i].chance) : "?",
        mana[i] ? num(mana[i].average) : "?"])),
    explain("What's a land drop?", "A land drop is playing a land from your hand; you can play one a turn. Missing one " +
      "early is the most common way to fall behind. Ramp (mana creatures, mana rocks and spells that fetch lands) " +
      "makes up for missed drops.", "A land that entered tapped counts as mana on the turn it's played."));
}

/** Columns of chances (0 to 1) in groups of one column per series, on a 0-100% scale, or with
 * fit, a scale up to a round number above the largest (for shares of games that add up to 1).
 * groups: [{label, values: [chance or null], classes?: [class per value], aria}]. */
function drawChanceColumns(host, groups, width, { classes, onPick, label, fit = false }) {
  const series = Math.max(...groups.map((g) => g.values.length));
  const height = 216;
  const m = { top: 22, right: 4, bottom: 28, left: 40 };
  const plotW = width - m.left - m.right;
  const plotH = height - m.top - m.bottom;
  let top = 1;
  let ticks = [0.25, 0.5, 0.75, 1];
  if (fit) {
    const largest = Math.max(1, ...groups.flatMap((g) => g.values.filter((v) => v != null).map((v) => v * 100)));
    const scale = niceScale(Math.min(100, largest));
    top = Math.min(100, scale.top) / 100;
    ticks = [];
    for (let v = scale.step; v <= Math.min(100, scale.top); v += scale.step) ticks.push(v / 100);
  }
  const y = (v) => m.top + plotH * (1 - Math.max(0, Math.min(top, v)) / top);
  const base = y(0);
  const band = plotW / groups.length;
  const gap = 2;
  const barW = Math.max(6, Math.min(24, (band * 0.74 - gap * (series - 1)) / series));
  const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "group", "aria-label": label });
  for (const v of ticks) {
    svg.append(svgEl("line", { class: "grid", x1: m.left, x2: width - m.right, y1: y(v), y2: y(v) }),
      svgEl("text", { class: "axis-text", x: m.left - 8, y: y(v) + 4, "text-anchor": "end", text: `${Math.round(v * 100)}%` }));
  }
  svg.append(svgEl("text", { class: "axis-text", x: m.left - 8, y: base + 4, "text-anchor": "end", text: "0%" }));
  groups.forEach((g, i) => {
    const cx = m.left + band * (i + 0.5);
    const total = g.values.length * barW + (g.values.length - 1) * gap;
    const col = svgEl("g", { class: "col", "data-i": i, tabindex: 0, role: "button", "aria-label": g.aria });
    col.append(svgEl("rect", { class: "hover-band", x: cx - band / 2 + 1, y: m.top - 18, width: band - 2,
      height: plotH + 18 + 24, rx: 6 }));
    g.values.forEach((v, k) => {
      if (v == null) return;
      const x = cx - total / 2 + k * (barW + gap);
      const top = y(v);
      if (v > 0) {
        col.append(svgEl("path", { d: columnPath(x, top, barW, Math.max(base - top, 1), 4),
          class: (g.classes && g.classes[k]) || classes[k] }));
      }
      col.append(svgEl("text", { class: "cap-text", x: x + barW / 2, y: top - 6, "text-anchor": "middle",
        text: pctShort(v).replace("%", "") }));
    });
    col.append(svgEl("text", { class: "axis-text", x: cx, y: base + 18, "text-anchor": "middle", text: g.label }));
    col.addEventListener("pointerenter", () => onPick(i));
    col.addEventListener("click", () => onPick(i));
    col.addEventListener("focus", () => onPick(i));
    col.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(i); } });
    svg.append(col);
  });
  svg.append(svgEl("line", { class: "base", x1: m.left, x2: width - m.right, y1: base, y2: base }));
  host.replaceChildren(svg);
}

// Stuck and flooded -------------------------------------------------------------

function stuckPanel(r) {
  const s = r.stuck;
  const f = r.flood;
  const rows = [];
  if (s.games != null) {
    rows.push(statRow(pct(s.games), "of games", "Stuck on lands",
      `On turn ${orList(s.turns)} you had no land to play, while holding a spell one more land would have let ` +
      "you cast."));
  }
  if (f.turns != null) {
    rows.push(statRow(pct(f.turns), `of turns ${f.from_turn} to ${f.to_turn}`, "Flooded",
      "Your hand had no spells left, only lands or nothing, so there was nothing to spend your mana on."));
  }
  return el("section", { class: "panel", "aria-labelledby": "h-stuck" },
    el("h3", { id: "h-stuck", text: "Too few lands, too many" }),
    el("ul", { class: "stat-rows" }, rows),
    el("p", { class: "sub" }, `Missed land drops: ${num(s.missed_drops)} of turns 1 to ${s.missed_turns} on average.`,
      f.games != null ? ` Games flooded on ${f.game_turns} or more turns: ${pct(f.games)}.` : ""));
}

// Colours -----------------------------------------------------------------------

function practiceColourPanel(r) {
  const c = r.colours;
  const panel = el("section", { class: "panel", "aria-labelledby": "h-practice-colours" },
    el("h3", { id: "h-practice-colours", text: "Colours" }));
  const how = explain("What's colour screw?", "A source of a colour is a land, mana creature or mana rock that makes " +
    "that colour of mana. Colour screw is having enough mana for a spell but not the right colours.");
  if (!c.by_turn.length) {
    panel.append(el("p", { class: "sub", text: "This deck's spells need no coloured mana." }), how);
    return panel;
  }
  const turns = c.by_turn[0].chances.map((_, i) => i + 1);
  const cell = (x) => {
    // The number, with a thin bar under it so the rise over the turns shows at a glance.
    const fill = el("span");
    fill.style.width = `${Math.max(0, Math.min(1, x || 0)) * 100}%`;
    return el("td", { class: "num" }, pctShort(x), el("span", { class: "meter", "aria-hidden": "true" }, fill));
  };
  const rows = c.by_turn.map((row) => el("tr", {},
    el("th", { scope: "row" },
      el("span", { class: "colour-name" }, colourPips(row.colour.split("")), capitalise(row.name))),
    row.chances.map(cell)));
  panel.append(
    el("p", { class: "sub", text: "Chance of having at least one source of each colour, by turn:" }),
    el("table", { class: "data chance-table" },
      el("caption", { class: "sr-only", text: `Chance of a source of each colour on turns 1 to ${turns.length}` }),
      el("colgroup", {}, el("col"), turns.map(() => el("col", { class: "c-turn" }))),
      el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Turn" }),
        turns.map((t) => el("th", { scope: "col", class: "num", text: String(t) })))),
      el("tbody", {}, rows)),
    el("ul", { class: "stat-rows" },
      statRow(pct(c.screw_turns), "of turns", "Colour screw",
        "You had enough mana in all for a spell in your hand, but not the colours it needs (you may still have " +
        "cast something else)."),
      statRow(pct(c.screw_wasted_turns), "of turns", "Colour screw with mana left over",
        "The same, on turns where you also couldn't spend all your mana.")),
    how);
  return panel;
}

// Mana used ---------------------------------------------------------------------

function manaUsedPanel(r) {
  const u = r.mana_used;
  return el("section", { class: "panel", "aria-labelledby": "h-used" },
    el("h3", { id: "h-used", text: "Mana used" }),
    el("ul", { class: "stat-rows" },
      statRow(pct(u.share), "of your mana", "Mana spent",
        `Of all the mana your lands and other sources could make on turns 1 to ${u.by_turn.length}, the share ` +
        "you spent on spells."),
      statRow(pct(u.all_used), "of turns", "Every mana used",
        "Turns (with any mana at all) where you spent all of it. Cheap spells help fill the gaps.")),
    numbersTable("Each turn as a table", ["Turn", "Mana spent", "All used"],
      u.by_turn.map((d) => [String(d.turn), pct(d.share), pct(d.all_used)])));
}

// First 4-drop ------------------------------------------------------------------

function firstBigPanel(r, result) {
  const b = r.first_big;
  const panel = el("section", { class: "panel", "aria-labelledby": "h-big" },
    el("h3", { id: "h-big", text: `First ${b.min_mv}-drop` }));
  const how = explain(`What's a ${b.min_mv}-drop?`, `A ${b.min_mv}-drop is a spell with mana value ${b.min_mv} or more: ` +
    "often a deck's biggest threats. This is the turn the first one was cast" +
    (result.kind === "commander" ? " (the commander counts)." : "."));
  if (!b.in_deck || !b.by_turn) {
    panel.append(el("p", { class: "sub", text: b.note || "There's nothing to show." }), how);
    return panel;
  }
  const lastTurn = b.by_turn.length;
  const turnCols = b.by_turn.map((d) => ({
    label: String(d.turn),
    values: [d.share],
    classes: [d.turn <= b.min_mv ? "seg-1" : "seg-muted"],
    aria: `Turn ${d.turn}: ${pct(d.share)} of games`,
    words: `${pct(d.share)} of games cast their first ${b.min_mv}-drop on turn ${d.turn}.`,
  }));
  turnCols.push({ label: "later", values: [b.never], classes: ["seg-muted"],
    aria: `Not by turn ${lastTurn}: ${pct(b.never)} of games`,
    words: `${pct(b.never)} of games hadn't cast one by turn ${lastTurn}.` });
  const chart = el("div", { class: "chart" });
  const detail = el("div", { class: "chart-detail", "aria-live": "polite" },
    noneSelected("Tap or point at a turn for its numbers."));
  let active = -1;
  const show = (i) => {
    active = i;
    for (const g of chart.querySelectorAll(".col")) g.classList.toggle("active", Number(g.dataset.i) === i);
    add(clear(detail), [el("p", { text: turnCols[i].words })]);
  };
  chartJobs.push([chart, (width) => {
    drawChanceColumns(chart, turnCols, width, { classes: ["seg-1"], onPick: show, fit: true,
      label: `The turn the first ${b.min_mv}-drop was cast` });
    if (active >= 0) show(active);
  }]);
  let running = 0;
  const table = b.by_turn.map((d) => {
    running += d.share || 0;
    return [String(d.turn), pct(d.share), pct(running)];
  });
  table.push([`Not by ${lastTurn}`, pct(b.never), ""]);
  panel.append(
    el("div", { class: "tiles" },
      tile(`By turn ${b.min_mv}`, pct(b.by_turn_4), "of games"),
      tile("Average turn", num(b.average_turn, 1), "when one was cast"),
      tile(`Not by turn ${lastTurn}`, pct(b.never), "of games")),
    el("ul", { class: "legend", "aria-label": "Legend" },
      el("li", {}, el("span", { class: "swatch", style: "background: var(--series-1)" }), `By turn ${b.min_mv}`),
      el("li", {}, el("span", { class: "swatch", style: "background: var(--series-muted)" }), "Later")),
    chart,
    detail,
    numbersTable("As a table", ["Turn", "That turn", "By then"], table),
    el("p", { class: "sub", text: `${plural(b.in_deck, "card")} in the deck ` +
      `${b.in_deck === 1 ? "has" : "have"} mana value ${b.min_mv} or more (an X spell counts at its smallest X).` }),
    how);
  return panel;
}

// Small print -------------------------------------------------------------------

/** The run's own facts (games, turns, seed, how long it took) and how close its numbers are, as two
 * paragraphs for the folded "How the practice games work". */
function practiceAbout(result) {
  const games = thousands(result.games);
  // A 95% range: 1.96 standard errors of a 50% chance, the widest there is.
  const margin = 196 * Math.sqrt(0.25 / result.games);
  const seed = result.seed_source === "decklist"
    ? `seed ${result.seed} (made from the decklist, so the same list always gets the same numbers)`
    : `seed ${result.seed}`;
  // The page usually gets the result from the PC's saved copy, even just after the run.
  const took = `Worked out in ${num(result.seconds)} s on ${plural(result.workers, "worker process", "worker processes")}` +
    (result.saved === false ? "; not saved on the PC." : " and saved on the PC.");
  return [el("p", { class: "sub" }, `${games} games of each kind, ${result.turns} turns each, ${seed}. ${took}`),
    el("p", { class: "sub" }, "These numbers come from simulated games that follow fixed rules, not from real play. With " +
      `${games} games, each chance is almost certainly within ${num(margin, 1)} percentage points of what the ` +
      "same rules would give over endless games.")];
}

function practiceFinePrint(result) {
  const c = result.cards || {};
  const names = (list, what) => el("ul", { class: "sources-list" }, list.map((x) => el("li", {},
    cardLink({ name: x.name, qty: x.qty }), " ", what(x))));
  const sources = Object.values(result.sources || {});
  return el("div", { class: "fine-print" },
    el("details", { class: "more" }, el("summary", { text: "Every rule the simulated player follows" }),
      el("ul", { class: "sources-list" }, (result.rules || []).map((rule) => el("li", { text: rule })))),
    c.special && c.special.length ? el("details", { class: "more" },
      el("summary", { text: `Cards read in a special way (${c.special.length})` }),
      names(c.special, (x) => x.rule)) : null,
    c.not_modelled && c.not_modelled.length ? el("details", { class: "more" },
      el("summary", { text: `What isn't counted for some cards (${c.not_modelled.length})` }),
      names(c.not_modelled, (x) => x.what)) : null,
    sources.length ? el("details", { class: "more" }, el("summary", { text: "Where the rules come from" }),
      el("ul", { class: "sources-list" }, sources.map((s) => el("li", {},
        el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", text: s.title }), ` (${s.date})`)))) : null);
}
