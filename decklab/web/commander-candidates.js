/* The Collection page's "Commanders we could build…" (E9-S28, first slice; lib/api/commander_candidates.py):
 * the space's free legendary creatures (and other cards that may be a commander) ranked by how much of a
 * Commander deck the rest of the free pool covers in each one's colours, counted by the Command Zone
 * template's role targets (ramp, card advantage, targeted and mass disruption), best first. Opening one shows
 * each category's free cards against its target, then (E9-S28's second slice) asks for its free cards by
 * name (GET /api/commanders/candidate): each category's, the free non-basic lands and the other non-land
 * cards that fit. It also offers New deck from it (the new-deck editor with it as the commander, in this
 * space, for a viewer who may add decks there) and See EDHREC ideas (deck-edhrec.js's sheet, asked for
 * this commander and space only when opened). Nothing here changes anything. */
"use strict";

/** Open the ranking for the Collection page's space (any viewer the page loaded for: it sees the inventory). */
function openCommanderCandidates(cv) {
  if (!colActive(cv) || cv.busy) return null;
  const whose = colWhose(cv.space);
  const ctx = { cv, whose, seq: 0, detail: null };
  const sheet = colOpenSheet("Commanders we could build", { wide: true });
  ctx.sheet = sheet;
  ctx.intro = el("p", { class: "sub", text: `Each card that may be a commander, with a copy free in ${whose}, by how much of the Command Zone template's ramp, card advantage and disruption the rest of ${whose}'s free cards in its colours already cover. Free: owned or on the way, and not in a built deck or a product kept intact.` });
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.area = el("div", { class: "ccand-area" });
  ctx.back = { text: "← Back to the ranking", value: "back", onclick: () => backToCandidates(ctx) };
  add(sheet.body, [ctx.intro, ctx.message, ctx.area]);
  sheetActions(sheet, [{ text: "Close", value: "close", onclick: () => sheet.close() }]);
  rankCandidates(ctx);
  return ctx;
}

function candidatesAlive(ctx, seq) {
  return seq === ctx.seq && !ctx.sheet.closed && colActive(ctx.cv);
}

async function rankCandidates(ctx) {
  if (ctx.sheet.closed) return;
  const seq = ++ctx.seq;
  clear(ctx.area);
  clear(ctx.message).append(loadingBox("Ranking commanders…"));
  try {
    const params = new URLSearchParams();
    if (ctx.cv.space !== HOME_SPACE) params.set("space", ctx.cv.space);
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

function drawCandidates(ctx, answer) {
  const list = answer.candidates || [];
  add(clear(ctx.area), [
    answer.tags_available === false ? el("p", { class: "box box-warn", text: "Role tags are unavailable in the card data, so every role counts 0. Update the card data on the PC to rank them." }) : null,
    list.length ? el("ol", { class: "pcov-list" }, list.map((c) => el("li", {},
      el("button", { type: "button", class: "pcov-pick", onclick: () => openCandidate(ctx, c) },
        el("span", { class: "pcov-pick-words" }, el("strong", {}, c.name, " ", colourPips(c.colours || [])),
          el("small", { text: [plural(c.cards, "other free card"), plural(c.lands, "non-basic land"),
            c.partner && c.partner.length ? `has ${c.partner.join(", ")}` : null].filter(Boolean).join(" · ") })),
        candidateShare(c),
        el("small", { class: "pcov-missing", text: candidateShort(c) })))))
      : emptyBox(`No card that may be a commander has a copy free in ${ctx.whose}.`, null, { live: true }),
    answer.total > list.length ? el("p", { class: "result-count", text: `The best ${num(list.length)} of ${num(answer.total)}.` }) : null,
    candidateSource(answer.source)]);
}

function backToCandidates(ctx) {
  ctx.detail = null;
  ctx.intro.hidden = false;
  ctx.sheet.heading.textContent = "Commanders we could build";
  sheetActions(ctx.sheet, [{ text: "Close", value: "close", onclick: () => ctx.sheet.close() }]);
  if (ctx.ranking) drawCandidates(ctx, ctx.ranking); else rankCandidates(ctx);
}

/** "#/new?kind=commander&commander=…" in the candidate's space, or null when the viewer may not add decks there. */
function candidateNewDeckHref(ctx, c) {
  if (!createTargets().some((t) => t.space === ctx.cv.space)) return null;
  const params = new URLSearchParams({ kind: "commander", commander: c.name });
  if (ctx.cv.space !== HOME_SPACE) params.set("space", ctx.cv.space);
  return `#/new?${params}`;
}

/** New deck from it and See EDHREC ideas. */
function candidateActions(ctx, c) {
  const href = candidateNewDeckHref(ctx, c);
  return el("div", { class: "ccand-actions" },
    href ? el("a", { class: "btn btn-primary", href, text: "New deck from it" }) : null,
    el("button", { type: "button", class: "btn", text: "See EDHREC ideas…",
      onclick: () => openEdhrecSheet(null, { commander: c.name, space: ctx.cv.space }) }));
}

/** The candidate's free cards by name, asked once it's opened. */
async function loadCandidateCards(ctx, c) {
  const seq = ++ctx.seq;
  clear(ctx.cards).append(loadingBox("Finding its free cards…"));
  try {
    const params = new URLSearchParams({ name: c.name });
    if (ctx.cv.space !== HOME_SPACE) params.set("space", ctx.cv.space);
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
      meta: r.free > 1 ? `${num(r.free)} free` : "Free", viewerGroup: "commander-candidate" })))
      : el("p", { class: "sub", text: "None free in its colours." }),
    more ? el("p", { class: "result-count", text: `${plural(more, "more card")} not listed.` }) : null);
}

function drawCandidateCards(ctx, answer) {
  const groups = (answer.categories || []).map((p) => candidateCardGroup(p.label, p.cards || [], p.more,
    p.in_coverage ? `${num(p.count)} of ${num(p.target)}${p.short ? `, ${num(p.target - p.count)} short` : ""}`
      : `${plural(p.count, "free non-basic land")}; basics fill the rest`));
  const others = answer.others || { cards: [], more: 0, count: 0 };
  add(clear(ctx.cards), [
    el("h2", { class: "ccand-cards-head", text: "Free cards by role" }),
    el("p", { class: "sub", text: "Most-printed first. A card in two categories is listed in both." }),
    groups,
    candidateCardGroup("Other free cards", others.cards || [], others.more,
      `${num(others.count || 0)} that fit no counted category: creatures and the deck's plan`)]);
}

/** One candidate: its card, each template category's free cards beside its target, and what else fits. */
function openCandidate(ctx, c) {
  ctx.detail = c;
  ctx.intro.hidden = true;
  ctx.sheet.heading.textContent = c.name;
  clear(ctx.message);
  const rows = (c.categories || []).map((p) => el("tr", { class: p.short ? "ccand-short" : null },
    el("th", { scope: "row", text: p.label }),
    el("td", { class: "num", text: `${p.about ? "about " : ""}${num(p.target)}` }),
    el("td", { class: "num", text: p.count == null ? "Not counted" : num(p.count) }),
    el("td", { text: p.count == null ? "" : p.short ? "Short" : p.in_coverage ? "At target" : "Basics fill the rest" })));
  add(clear(ctx.area), [
    el("div", { class: "ccand-head" },
      el("div", { class: "card-tiles ccand-tile" }, cardTile(c.card || null, { name: c.name, viewerGroup: "commander-candidates",
        meta: [`${num(c.free)} free`] })),
      el("div", { class: "ccand-words" },
        el("p", { class: "precon-summary" }, candidateShare(c)),
        el("p", { text: candidateShort(c) + "." }),
        el("p", { class: "sub", text: `${plural(c.cards, "other free non-land card")} and ${plural(c.lands, "free non-basic land")} in its colours. A Commander deck plays one of each, so extra copies don't count.` }),
        c.partner && c.partner.length ? el("p", { class: "box box-info", text: `It has ${c.partner.join(" and ")}: a second commander would widen its colours, which isn't counted here.` }) : null,
        candidateActions(ctx, c))),
    el("table", { class: "data ccand-table" },
      el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Template category" }), el("th", { scope: "col", class: "num", text: "Target" }),
        el("th", { scope: "col", class: "num", text: "Free" }), el("th", { scope: "col", text: "" }))),
      el("tbody", {}, rows)),
    el("p", { class: "result-count", text: "Free cards count as the Stats tab counts the roles (Scryfall's oracle tags): card advantage is the draw role only, targeted disruption is removal or counterspells that aren't board wipes." }),
    ctx.cards = el("div", { class: "ccand-cards" }),
    candidateSource(ctx.ranking && ctx.ranking.source)]);
  sheetActions(ctx.sheet, [ctx.back]);
  loadCandidateCards(ctx, c);
}
