/* New deck's "Commanders we could build" (E9-S28, lib/api/commander_candidates.py):
 * the space's free legendary creatures (and other cards that may be a commander) ranked by how much of a
 * Commander deck the rest of the free pool covers in each one's colours, counted by the Command Zone
 * template's role targets (ramp, card advantage, targeted and mass disruption), best first. Opening one shows
 * each category's free cards against its target, then (E9-S28's second slice) asks for its free cards by
 * name (GET /api/commanders/candidate): each category's, the free non-basic lands and the other non-land
 * cards that fit. It also offers New deck from it (the new-deck editor with it as the commander, in this
 * space, for a viewer who may add decks there) and See EDHREC ideas (deck-edhrec.js's sheet, asked for
 * this commander and space only when opened). E9-S28's third slice: pairs of commanders (partners, a
 * commander and its Background, and the other pairings the Commander checks know) rank with the single
 * candidates by the same figure, opened as one with both commanders; and a commander every copy of which a
 * built deck or a product kept intact holds is listed apart, after the free ones, naming the deck holding it
 * (the server's words: a deck the viewer may not see is "one of the home decks"). Nothing here changes
 * anything. */
"use strict";

/** Open the ranking for the Collection page's space (any viewer the page loaded for: it sees the inventory). */
function openCommanderCandidates(cv) {
  if (!colActive(cv) || cv.busy) return null;
  const sheet = colOpenSheet("Commanders we could build", { wide: true });
  return commanderCandidatesSheet(cv.space, sheet, () => colActive(cv));
}

function commanderCandidatesSheet(space, sheet, here, onChoose = null) {
  const whose = colWhose(space);
  const ctx = { space, sheet, here, onChoose, whose, seq: 0, detail: null };
  ctx.intro = el("p", { class: "sub", text: `Role coverage uses ${whose} and expected deliveries. A draft for tonight uses only copies free now.` });
  ctx.input = el("input", { type: "search", class: "search-input", maxlength: 150, autocomplete: "off",
    "aria-label": "Find a commander by name", placeholder: "Find a commander by name" });
  ctx.search = el("form", { class: "actions", role: "search" }, ctx.input,
    el("button", { type: "submit", class: "btn", text: "Find commander" }));
  let timer;
  ctx.input.addEventListener("input", () => {
    ++ctx.seq;
    clear(ctx.area);
    clear(ctx.message);
    clearTimeout(timer);
    timer = setTimeout(() => { if (!sheet.closed && here()) rankCandidates(ctx); }, 250);
  });
  ctx.search.addEventListener("submit", event => {
    event.preventDefault();
    clearTimeout(timer);
    if (here()) rankCandidates(ctx);
  });
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.area = el("div", { class: "ccand-area" });
  ctx.back = { text: "← Back to the ranking", value: "back", onclick: () => backToCandidates(ctx) };
  add(sheet.body, [ctx.intro, ctx.search, ctx.message, ctx.area]);
  sheetActions(sheet, [{ text: "Close", value: "close", onclick: () => sheet.close() }]);
  rankCandidates(ctx);
  return ctx;
}

function candidatesAlive(ctx, seq) {
  return seq === ctx.seq && !ctx.sheet.closed && ctx.here();
}

async function rankCandidates(ctx) {
  if (ctx.sheet.closed) return;
  const seq = ++ctx.seq;
  clear(ctx.area);
  clear(ctx.message).append(loadingBox("Ranking commanders…"));
  try {
    const params = new URLSearchParams();
    if (ctx.space !== HOME_SPACE) params.set("space", ctx.space);
    ctx.query = (ctx.input.value || "").trim();
    if (ctx.query) params.set("q", ctx.query);
    const answer = await api(`/api/commanders/candidates?${params}`);
    if (!candidatesAlive(ctx, seq)) return;
    ctx.ranking = answer;
    clear(ctx.message);
    drawCandidates(ctx, answer);
  } catch (error) {
    if (!candidatesAlive(ctx, seq)) return;
    clear(ctx.message).append(loadFailed("The commander ranking", error, () => rankCandidates(ctx)));
  }
}

/** "75% of the role targets · 30 of 40", with a meter. */
function candidateShare(c) {
  const pct = Math.round((c.share || 0) * 100);
  return el("span", { class: "pcov-share" },
    el("span", { class: "pcov-share-words", text: `${pct}% of the role targets · ${num(c.covered)} of ${num(c.of)}` }),
    el("span", { class: "meter", "aria-hidden": "true" }, el("span", { style: `width: ${pct}%` })));
}

function candidateShort(c) {
  return c.short && c.short.length ? `Short of ${c.short.join(", ").toLowerCase()}` : "Every counted role at its target";
}

/** The template's source line: its title, episode date and when its figures were checked. */
function candidateSource(source) {
  if (!source) return null;
  return el("p", { class: "result-count" }, "Role targets: ",
    el("a", { href: source.url, target: "_blank", rel: "noopener", text: source.title }),
    ` (${source.episode_date}; figures checked ${source.checked}). Basic lands fill the lands, so lands don't count towards the share.`);
}

/** The decks holding a held candidate, in the server's words: "Elf Stompy and one of the home decks". */
function candidateHolders(c) {
  const holders = c.held_by || [];
  const decks = holders.filter(h => h.id != null || h.title !== "lent out").map(h => h.title);
  return [decks.length ? `in ${decks.join(" and ")}` : null,
    holders.some(h => h.id == null && h.title === "lent out") ? "lent out" : null].filter(Boolean).join(" or ") || "held";
}

/** One row of the ranking (or of the held list): a button opening it. */
function candidatePick(ctx, c) {
  const pair = c.kind === "pair";
  const words = [plural(c.cards, "other covered card"), plural(c.lands, "non-basic land"),
    pair ? `together by ${c.pairing}` : c.partner && c.partner.length ? `has ${c.partner.join(", ")}` : null,
    c.kind === "held" ? candidateHolders(c) : candidateFaces(c)
      .map(f => `${pair ? f.name + ": " : ""}${candidateStock(f)}`).join(" · ")];
  return el("li", { class: pair ? "ccand-pair" : c.kind === "held" ? "ccand-held" : null },
    el("button", { type: "button", class: "pcov-pick", onclick: () => openCandidate(ctx, c) },
      el("span", { class: "pcov-pick-words" }, el("strong", {}, c.name, " ", colourPips(c.colours || [])),
        el("small", { text: words.filter(Boolean).join(" · ") })),
      candidateShare(c),
      el("small", { class: "pcov-missing", text: candidateShort(c) })));
}

/** What the pair caps left out, or null. */
function candidatePairsNote(pairs) {
  if (!pairs || (!pairs.left_out && !pairs.untried)) return null;
  return el("p", { class: "result-count", text: [
    pairs.left_out ? `${plural(pairs.left_out, "more pair")} of the ${num(pairs.found)} found aren't listed.` : null,
    pairs.untried ? `${plural(pairs.untried, "card")} that may pair weren't tried as one of a pair, to keep this quick.` : null,
  ].filter(Boolean).join(" ") });
}

function drawCandidates(ctx, answer) {
  const list = answer.candidates || [];
  const held = answer.held || [];
  add(clear(ctx.area), [
    answer.tags_available === false ? el("p", { class: "box box-warn", text: "Role tags are unavailable in the card data, so every role counts 0. Update the card data on the PC to rank them." }) : null,
    list.length ? el("ol", { class: "pcov-list" }, list.map((c) => candidatePick(ctx, c)))
      : emptyBox(ctx.query ? `No available commander matches “${ctx.query}”.`
        : `No card that may be a commander has a copy free in ${ctx.whose}.`, null, { live: true }),
    answer.total > list.length ? el("p", { class: "result-count",
      text: ctx.query ? `Showing ${num(list.length)} of ${num(answer.total)} matches.` : `The best ${num(list.length)} of ${num(answer.total)}.` }) : null,
    candidatePairsNote(answer.pairs),
    held.length ? el("section", { class: "ccand-held-list" },
      el("h3", { text: "Held or lent out" }),
      el("p", { class: "sub", text: "To use one of these commanders, review the deck holdings or wait for a loan to come back." }),
      el("ol", { class: "pcov-list" }, held.map((c) => candidatePick(ctx, c))),
      answer.held_total > held.length ? el("p", { class: "result-count", text: `${num(held.length)} of ${num(answer.held_total)} held.` }) : null) : null,
    candidateSource(answer.source)]);
}

function backToCandidates(ctx) {
  ctx.seq++;
  ctx.detail = null;
  ctx.intro.hidden = false;
  ctx.search.hidden = false;
  ctx.sheet.heading.textContent = "Commanders we could build";
  sheetActions(ctx.sheet, [{ text: "Close", value: "close", onclick: () => ctx.sheet.close() }]);
  if (ctx.ranking) drawCandidates(ctx, ctx.ranking); else rankCandidates(ctx);
}

/** "#/new?kind=commander&commander=…" in the candidate's space, or null when the viewer may not add decks there. */
function candidateNewDeckHref(ctx, c) {
  if (!createTargets().some((t) => t.space === ctx.space)) return null;
  const names = c.names || [c.name];
  const params = new URLSearchParams({ kind: "commander", commander: names[0] });
  if (names[1]) params.set("partner", names[1]);
  if (ctx.space !== HOME_SPACE) params.set("space", ctx.space);
  return `#/new?${params}`;
}

function candidateFaces(c) { return c.faces || [c]; }

function candidateStock(face) {
  const words = [];
  if (face.free > 0) words.push(`${num(face.free)} free now`);
  if (face.incoming > 0) words.push(face.free > 0 ? `${num(face.incoming)} on the way` : `On the way (${num(face.incoming)})`);
  return words.join(" · ") || "None free now";
}

/** New deck from it and See EDHREC ideas. */
function candidateActions(ctx, c) {
  const href = candidateNewDeckHref(ctx, c);
  const tonight = c.kind !== "held" && candidateFaces(c).every(f => f.free > 0);
  const action = (label, draft) => ctx.onChoose
    ? el("button", { type: "button", class: draft ? "btn btn-primary" : "btn", text: label,
      onclick: event => { if (ctx.here() && event.currentTarget.isConnected) ctx.onChoose(c, draft); } })
    : el("a", { class: draft ? "btn" : "btn btn-primary", href: href + (draft ? "&draft=tonight" : ""), text: label });
  return el("div", { class: "ccand-actions" },
    href ? action(ctx.onChoose ? "Use as commander" : "New deck from it", false) : null,
    href && tonight ? action("Build from cards free tonight", true) : null,
    el("button", { type: "button", class: "btn", text: "See EDHREC ideas…",
      onclick: () => openEdhrecSheet(null, { commander: (c.names || [c.name])[0], commander2: (c.names || [])[1] || null, space: ctx.space }) }));
}

/** The candidate's free cards by name, asked once it's opened. */
async function loadCandidateCards(ctx, c) {
  const seq = ++ctx.seq;
  clear(ctx.cards).append(loadingBox("Finding its free cards…"));
  try {
    const names = c.names || [c.name];
    const params = new URLSearchParams({ name: names[0] });
    if (names[1]) params.set("partner", names[1]);
    if (ctx.space !== HOME_SPACE) params.set("space", ctx.space);
    const answer = await api(`/api/commanders/candidate?${params}`);
    if (!candidatesAlive(ctx, seq) || ctx.detail !== c) return;
    drawCandidateCards(ctx, answer);
  } catch (error) {
    if (!candidatesAlive(ctx, seq) || ctx.detail !== c) return;
    clear(ctx.cards).append(loadFailed("Its free cards", error, () => loadCandidateCards(ctx, c)));
  }
}

/** One list of free cards: a heading with its count (and target), the cards, and how many more aren't listed. */
function candidateCardGroup(heading, rows, more, words) {
  return el("section", { class: "ccand-group" }, el("h3", {}, heading, " ", el("small", { class: "sub", text: words })),
    rows.length ? el("div", {}, rows.map((r) => cardRow(r.card || null, { name: r.name, caption: r.name,
      meta: candidateStock(r), viewerGroup: "commander-candidate" })))
      : el("p", { class: "sub", text: "None free in its colours." }),
    more ? el("p", { class: "result-count", text: `${plural(more, "more card")} not listed.` }) : null);
}

function drawCandidateCards(ctx, answer) {
  const groups = (answer.categories || []).map((p) => candidateCardGroup(p.label, p.cards || [], p.more,
    p.in_coverage ? `${num(p.count)} of ${num(p.target)}${p.short ? `, ${num(p.target - p.count)} short` : ""}`
      : `${plural(p.count, "free non-basic land")}; basics fill the rest`));
  const others = answer.others || { cards: [], more: 0, count: 0 };
  add(clear(ctx.cards), [
    el("h2", { class: "ccand-cards-head", text: "Available cards by role" }),
    el("p", { class: "sub", text: "Counts include copies free now and on the way. A card in two categories appears in both." }),
    groups,
    candidateCardGroup("Other free cards", others.cards || [], others.more,
      `${num(others.count || 0)} for the deck's plan or for other roles`)]);
}

/** One candidate: its card, each template category's free cards beside its target, and what else fits. */
function openCandidate(ctx, c) {
  if (!ctx.here() || ctx.sheet.closed) return;
  ctx.detail = c;
  ctx.intro.hidden = true;
  ctx.search.hidden = true;
  ctx.sheet.heading.textContent = c.name;
  clear(ctx.message);
  const rows = (c.categories || []).map((p) => el("tr", { class: p.short ? "ccand-short" : null },
    el("th", { scope: "row", text: p.label }),
    el("td", { class: "num", text: `${p.about ? "about " : ""}${num(p.target)}` }),
    el("td", { class: "num", text: p.count == null ? "Not counted" : num(p.count) }),
    el("td", { text: p.count == null ? "" : p.short ? "Short" : p.in_coverage ? "At target" : "Basics fill the rest" })));
  add(clear(ctx.area), [
    el("div", { class: "ccand-head" },
      el("div", { class: "card-tiles ccand-tile" }, candidateFaces(c).map((f) =>
        cardTile(f.card || null, { name: f.name, viewerGroup: "commander-candidates",
          meta: [candidateStock(f)] }))),
      el("div", { class: "ccand-words" },
        el("p", { class: "precon-summary" }, candidateShare(c)),
        el("p", { text: candidateShort(c) + "." }),
        el("p", { class: "sub", text: `${plural(c.cards, "other covered non-land card")} and ${plural(c.lands, "non-basic land")} in its colours. Counts include incoming copies and count each card name once.` }),
        c.kind === "pair" ? el("p", { class: "box box-info", text: `Two commanders together (${c.pairing}), counted over both their colours.` })
          : c.partner && c.partner.length ? el("p", { class: "box box-info", text: `It has ${c.partner.join(" and ")}: its pairs with free cards are rows of their own in the ranking.` }) : null,
        c.kind === "held" ? el("p", { class: "box box-warn", text: `Every copy is ${candidateHolders(c)}.` }) : null,
        candidateActions(ctx, c))),
    el("table", { class: "data ccand-table" },
      el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Template category" }), el("th", { scope: "col", class: "num", text: "Target" }),
        el("th", { scope: "col", class: "num", text: "Covered" }), el("th", { scope: "col", text: "" }))),
      el("tbody", {}, rows)),
    el("p", { class: "result-count", text: "Free cards count as the Stats tab counts the roles (Scryfall's oracle tags): card advantage is the draw role only, targeted disruption is removal or counterspells that aren't board wipes." }),
    ctx.cards = el("div", { class: "ccand-cards" }),
    candidateSource(ctx.ranking && ctx.ranking.source)]);
  sheetActions(ctx.sheet, [ctx.back]);
  loadCandidateCards(ctx, c);
}
