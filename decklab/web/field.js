/* Deck Lab's page: the deck view's "Against the field" part (simulation wave 3's R13,
forge-trial/sim-wave3-contract.md section 10.6; plain words in the UI review's WP12), from GET /api/field: the
deck against an average house deck, where it ranks, the decks it does better or worse against than expected,
one row per opponent (best first), and "Play the field". With no games yet it's one empty state with Play
(MU-08); the rating's maths goes in a closed "How this is worked out" (MU-09).
Every class this file and field.css add starts with "fv-" (the editor already uses .field and its
relatives); it also uses the page's shared ones (deck-section, box, btn, segmented, sub, status, empty).

fieldSection(data) is called by the deck page. It returns the part at once with a loading line, asks
/api/field for the numbers, and asks again every FV_POLL_MS while a field run waits or plays (it stops when
the page is left). Its numbers are Forge's result pieces (sim-ui.js: the average as a hero figure with its range
bar and how long ago the field was played, each opponent's compact range bar and inline figure, and the strong
and weak flags; E11-S30 slice 6). Uses core.js's helpers, matchups.js's matchupHref, runChoiceControl, shortTitle,
metaWords and gamesWords, matchups-overview.js's edgeWords, notPlayedLine and anyTodaysEngine, editor.js's ask(), and
app.js's jumpTo (a link with part=field, such as a matchup page's "playing as part of a field run" link, scrolls
here). */
"use strict";

const FV_POLL_MS = 1500;           // how often a field run's progress is asked for while it waits or plays
// The run vocabulary (MU-05) for a field run's budgets (forge/field.py's BUDGETS), meaning what it means for one
// matchup: a first idea, enough to tell which deck is ahead, then close matchups too. Each says its games a deck.
const FV_BUDGETS = [["quick", "Quick look"], ["standard", "Settle it"], ["thorough", "Precise"]];
const FV_BUDGET_SAVES = new Map();  // serialize a profile's picks, even after navigating to another deck
const FV_BUDGET_SUB = { quick: "A first idea: the fewest games against each deck that say anything.",
  standard: "Plays each deck until most matchups are clear: which deck is ahead, or that they're about even.",
  thorough: "Twice the games against each deck, so the close matchups are clear too." };
const FV_TRUST = "A rating predicts a matchup it hasn't seen only to about ±8 points of win rate: the row is " +
  "the real answer.";
const FV_VERDICTS = { ahead: "ahead", slightly_ahead: "slightly ahead", about_even: "about even",
  not_settled: "not settled" };

/** The deck page's "Against the field" part (id "sec-field"), or null when there's none: a Beginner Box
 * half only plays in a pairing. */
function fieldSection(data) {
  const s = data.summary;
  if (s.id.startsWith(BOX_PREFIX)) return null;
  const content = el("div", { class: "fv-content" }, loadingBox("Loading how this list does against the field…"));
  const section = el("section", { class: "deck-section fv-section", id: "sec-field", "aria-labelledby": "h-field" },
    el("h2", { id: "h-field", text: "Against the field" }), content, fieldMembership(data));
  const profile = state.profile ? `&profile=${encodeURIComponent(state.profile.id)}` : "";
  const ctx = { section, content, token: routeToken, id: s.id, version: data.version, title: s.title,
    url: `/api/field?id=${encodeURIComponent(s.id)}&version=${data.version}${profile}`,
    answer: null, budget: null, timer: 0, busy: false,
    // Every saved matchup of this list an earlier engine's (the Matchups part shows them): the field counts only
    // today's, so its empty state says why it's empty under them.
    earlierOnly: ((data.matchups || {}).results || []).length > 0 && !anyTodaysEngine(data.matchups.results) };
  fvRefresh(ctx);
  const part = new URLSearchParams(location.hash.split("?")[1] || "").get("part");
  if (part === "field") setTimeout(() => { if (ctx.token === routeToken) jumpTo("sec-field"); }, 0);
  return section;
}

/** Still the page this part was drawn for? */
function fvHere(ctx) { return ctx.token === routeToken; }

/** Late field content must not move a section the reader jumped to below it. */
function fvKeepPlace(change) {
  return typeof keepPlace === "function" ? keepPlace(change) : change();
}

async function fvRefresh(ctx) {
  clearTimeout(ctx.timer);
  if (!fvHere(ctx) || ctx.busy) return;
  try {
    const answer = await api(ctx.url);
    if (!fvHere(ctx) || ctx.busy) return;
    fvKeepPlace(() => fvDraw(ctx, answer));
  } catch (e) {
    if (!fvHere(ctx) || ctx.busy) return;
    fvKeepPlace(() => {
      clear(ctx.content).append(loadFailed("How this list does against the field", e, () => fvRefresh(ctx)));
    });
    return;
  }
  fvSchedule(ctx);
}

/** Ask again soon while the field run waits or plays. */
function fvSchedule(ctx) {
  clearTimeout(ctx.timer);
  if (!fvHere(ctx) || !ctx.answer) return;
  if (fvPlaying(ctx.answer)) {
    ctx.timer = setTimeout(() => {
      if (fvHere(ctx) && ctx.section.isConnected) fvRefresh(ctx);
    }, FV_POLL_MS);
  }
}

function fvPlaying(answer) { return answer.status === "queued" || answer.status === "running"; }

function fvDraw(ctx, a) {
  ctx.answer = a;
  fvAnnounce(ctx, a);
  if (!ctx.budget) ctx.budget = a.default_budget || "standard";
  clear(ctx.content);
  const opponents = a.opponents || [];
  const played = opponents.some((o) => o.games);
  const list = ctx.version === "owned" ? listName("owned", true) : "list";
  if (!opponents.length) {
    ctx.content.append(emptyBox(`There's no other ${a.format} deck in the field for it to play.`,
      createTargets().length ? el("a", { class: "btn", href: newDeckHref(), text: "New deck" }) : null));
    return;
  }
  if (!played && !fvPlaying(a)) {
    // One empty state, with the one action that fills it (MU-08). Only today's engine's games count here, so
    // a list whose matchups were all an earlier engine's is still empty: said, so it doesn't contradict them.
    ctx.content.append(el("div", { class: "empty fv-empty" },
      el("p", { text: ctx.earlierOnly ? "No field games with today's engine yet." : "No games against the field yet." }),
      el("p", { class: "sub", text: (ctx.earlierOnly ? "Earlier results don't count here. " : "") +
        `Play the field to see how this ${list} does against the ` +
        `${plural(opponents.length, `other ${a.format} deck`)} of the house.` }),
      fvPlayBox(ctx, a, { inEmpty: true })));
    return;
  }
  add(ctx.content, [
    el("p", { class: "sub", text: `How this ${list} does against the house's other ${a.format} decks, from Forge's ` +
      "AI playing them (best of one)." }),
    el("div", { class: "fv-layout" },
      el("div", { class: "fv-side" }, fvHeadline(a), fvChips(a), fvPlayBox(ctx, a)),
      el("div", { class: "fv-main" }, fvRows(a))),
    fvHow(a)]);
}

/** 3 -> "3rd". */
function fvOrdinal(n) {
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" })[n % 10] || "th";
  return `${n}${suffix}`;
}

/** The games the average counts: each opponent's that means something, added up. */
function fvGames(a) { return (a.opponents || []).filter((o) => !o.not_meaningful).reduce((sum, o) => sum + (o.games || 0), 0); }

/** The headline: the win rate against an average house deck as a hero figure, with how long ago the field was
 * last played (the last field run's note) and its range bar, then where the list ranks, in a sentence. */
function fvHeadline(a, { panel = true } = {}) {
  const tile = el("div", { class: panel ? "fv-tile" : "fv-summary" });
  const average = a.average;
  if (average && average.value != null) {
    const what = "Win rate against an average house deck";
    add(tile, [
      el("p", { class: "fv-big", text: "Against an average house deck:" }),
      el("div", { class: "fv-figure" },
        winRateFigure(average, { size: "hero", what, games: fvGames(a) || null, barred: true }),
        freshnessBadge(a.last_run && a.last_run.when)),
      rangeBar(average, { axis: true, decorative: true })]);
    if (average.partial || (a.coverage && a.coverage.with_floor < a.coverage.of)) {
      tile.append(el("p", { class: "fv-partial", text: `Based on ${average.counted} of ${average.of} decks; ` +
        "play the field to fill it in." }));
    }
  } else {
    tile.append(el("p", { class: "fv-big", text: "Not enough games yet for an average: play the field to fill it in." }));
  }
  const r = a.rating;
  if (r && r.value != null) {
    tile.append(el("p", { class: "fv-rating" }, "Ranks ", el("strong", { text: `${fvOrdinal(r.rank)} of ${r.of}` }),
      ` ${a.format} decks`, r.rank_low != null && r.rank_high != null && r.rank_low !== r.rank_high
        ? ` (somewhere from ${fvOrdinal(r.rank_low)} to ${fvOrdinal(r.rank_high)})` : "", "."));
    tile.append(manualFieldExclusionNote(r.manual_excluded, "sub fv-manual-excluded"));
  }
  return tile;
}

/** The decks it does better or worse against than its rating expects, each a strong or weak flag (the
 * opponent's name and the win rate, sim-ui.js forgeFlag) and a sentence, linking to that matchup: "Does better
 * than expected: 12 points more than its rank suggests". */
function fvChips(a) {
  const flagged = (a.opponents || []).filter((o) => o.residual && o.residual.flag);
  if (!flagged.length) return null;
  return el("ul", { class: "fv-chips" }, flagged.map((o) => {
    const points = Math.round(Math.abs(o.residual.r || 0) * 100);
    const strong = o.residual.flag === "strong";
    return el("li", {}, el("a", { class: `fv-chip fv-chip-${strong ? "strong" : "weak"}`,
      href: matchupHref(a.deck, o) },
    forgeFlag(strong ? "strong" : "weak", { name: shortTitle(o.title), rate: o.rate }), " ",
    el("span", {}, el("strong", { text: `${strong ? "Does better" : "Does worse"} than expected` }),
      `: ${points} points ${strong ? "more" : "less"} than its rank suggests`)));
  }));
}

/** One row per opponent with games, best matchup first (MU-09), then the ones not played yet in a line. */
function fvRows(a) {
  const opponents = a.opponents || [];
  const played = opponents.filter((o) => o.games && o.rate && o.rate.value != null)
    .sort((x, y) => (x.not_meaningful - y.not_meaningful) || (y.rate.value - x.rate.value));
  // An opponent this deck has met head to head (the Matchups tab's results above) isn't "not played yet".
  const waiting = opponents.filter((o) => !played.includes(o) && !(typeof headToHead === "function" && headToHead(o.id)));
  return [
    el("h3", { text: "Against each deck" }),
    el("ul", { class: "fv-rows" }, played.map((o) => {
      const chips = [];
      if (o.not_meaningful) chips.push(status("crit", "Not meaningful"));
      else if (o.residual && o.residual.flag) chips.push(forgeFlag(o.residual.flag === "strong" ? "strong" : "weak"));
      const what = `Win rate against ${o.title}`;
      const meta = metaWords(o.not_meaningful ? "the AI never casts a commander, so it's left out of the average"
        : o.lead && FV_VERDICTS[o.lead.verdict] ? capitalise(fvVerdict(o.lead)) : edgeWords(o.rate.value),
      gamesWords(o.games), o.problem);
      return el("li", { class: o.not_meaningful ? "fv-muted" : null },
        el("a", { class: "fv-row", href: matchupHref(a.deck, o) },
          el("span", { class: "fv-name", text: o.title }),
          el("span", { class: "fv-barline" },
            rangeBar(o.rate, { compact: true, muted: o.not_meaningful, decorative: true }),
            el("span", { class: "fv-pct" }, winRateFigure(o.rate, { what, barred: true }))),
          el("span", { class: "fv-meta" }, el("span", { text: meta }), chips)));
    })),
    notPlayedLine(a.deck, waiting.map((o) => ({ id: o.id, title: o.title })))];
}

/** The lead verdict in a word or two, from this deck's point of view (side 0 is this deck). */
function fvVerdict(lead) {
  if (lead.side === 1) return lead.verdict === "slightly_ahead" ? "slightly behind" : "behind";
  return FV_VERDICTS[lead.verdict];
}

/** "How this is worked out", closed: the rating's limits, what going first is worth, and the server's notes. */
function fvHow(a) {
  const r = a.rating;
  const items = [
    el("li", { text: "The average is this list's win rate against each house deck, averaged, balanced for going " +
      "first and second; the bar under it runs from 20% to 80%, with the band where it probably lies and a mark " +
      "at 50%." }),
    el("li", { text: "The rank comes from a rating of every deck worked out from all the games between them, so " +
      `it covers matchups that haven't been played yet. ${FV_TRUST}` }),
    r && r.h_points != null ? el("li", { text: `Going first is worth about ${Math.round(r.h_points)} points of win ` +
      "rate in these games." }) : null,
    ...(a.notes || []).map((text) => el("li", { text })),
  ];
  return el("details", { class: "more fv-how" }, el("summary", { text: "How this is worked out" }),
    el("ul", { class: "fv-notes" }, items));
}

/** Say when a field run starts waiting, starts playing and finishes, once each, in a line kept outside the
 * part's redrawn content (its per-game counts aren't announced). */
function fvAnnounce(ctx, a) {
  if (!ctx.announcer) {
    ctx.announcer = el("p", { class: "sr-only", role: "status" });
    ctx.section.append(ctx.announcer);
  }
  const phase = a.status === "queued" ? "Waiting to play the field." : a.status === "running" ? "Playing the field."
    : ctx.phase ? "Finished playing the field." : "";
  if (fvPlaying(a) || ctx.phase) ctx.phase = fvPlaying(a) ? a.status : null;
  if (phase && ctx.announcer.textContent !== phase) ctx.announcer.textContent = phase;
}

/** inEmpty: inside the empty state, whose line already says what to do, so no "Play the field" heading. */
function fvPlayBox(ctx, a, { inEmpty = false } = {}) {
  const box = el("div", { class: "fv-play" });
  if (a.notice) box.append(el("p", { class: "fv-small", text: a.notice }));
  if (a.error) box.append(el("div", { class: "box box-crit" }, el("p", { text: a.error })));
  if (fvPlaying(a)) {
    add(box, fvLive(ctx, a));
    return box;
  }
  const ready = !a.forge || a.forge.ready;
  // Home's saved field choices can't be read (E3-S23): the server refuses a run, so Play waits and says why.
  const refused = typeof a.run_refused === "string" && a.run_refused ? a.run_refused.slice(0, 300) : "";
  const options = FV_BUDGETS.map(([budget, title]) => ({ id: budget, title, sub: FV_BUDGET_SUB[budget],
    time: fvBudgetWords((a.budgets || {})[budget]) || null }));
  const choice = runChoiceControl(options, ctx.budget, (budget) => fvSaveBudget(ctx, budget));
  // A viewer who may not start runs sees the disabled button and why (syncRunControls), not the choice too, as
  // on a matchup's page. The button is the outlined kind: the deck page has its own primary action.
  choice.node.hidden = !runsAllowed();
  add(box, [inEmpty ? null : el("h3", { text: "Play the field" }), choice.node,
    ready ? null : el("p", { class: "fv-small", text: (a.forge && a.forge.problem) || "Forge isn't ready on the PC." }),
    refused ? el("p", { class: "fv-small", text: refused }) : null,
    el("div", { class: "actions" }, el("button", { type: "button", class: "btn", text: "Play the field",
      disabled: !ready || !state.profile || !!refused, "data-run": true, onclick: () => fvPlay(ctx) }))]);
  return box;
}

/** Remember the choice for this profile on other devices; a failed save still leaves it chosen here. */
async function fvSaveBudget(ctx, budget) {
  ctx.budget = budget;
  const profile = state.profile;
  if (!profile) return;
  const pending = (FV_BUDGET_SAVES.get(profile.id) || Promise.resolve()).then(async () => {
    // A queued choice must never be sent with a different person's viewer header.
    if (!state.profile || state.profile.id !== profile.id) return;
    try {
      await apiWrite(`/api/profiles/${encodeURIComponent(profile.id)}/settings`, { field_budget: budget }, "PUT");
    } catch (e) {
      if (state.profile && state.profile.id === profile.id) {
        toast(`${profile.name}'s usual field run couldn't be saved: ${e.message}`);
      }
    }
  });
  FV_BUDGET_SAVES.set(profile.id, pending);
  ctx.budgetSave = pending;
  try { await pending; }
  finally {
    if (FV_BUDGET_SAVES.get(profile.id) === pending) FV_BUDGET_SAVES.delete(profile.id);
  }
}

/** "about 400 games a deck, about 25-40 minutes" for a budget (the answer's budgets): its one time estimate. */
function fvBudgetWords(b) {
  if (!b) return "";
  const parts = [`about ${thousands(b.games)} games a deck`];
  if (b.new_games === 0) parts.push("nothing new to play");
  else if (b.minutes) parts.push(`about ${Math.round(b.minutes[0])}–${Math.round(b.minutes[1])} minutes`);
  else if (b.new_games) parts.push(`${thousands(b.new_games)} new games`);
  return parts.join(", ");
}

/** A field run waiting or playing: its progress, who's playing now, a mini bar per opponent and Stop. */
function fvLive(ctx, a) {
  const job = a.job || {};
  const pairs = Object.values(job.pairs || {});
  const bar = progressBar("Field games played");
  bar.set(job.total ? job.done / job.total : 0);
  const playing = pairs.filter((p) => p.playing).map((p) => p.opponent.title);
  const waiting = pairs.filter((p) => !p.playing && !p.dropped && p.done < p.total).length;
  const words = a.status === "queued"
    ? (job.ahead > 0 ? `Waiting: ${plural(job.ahead, "run")} ahead of it` : "Starting…")
    : playing.length ? `Playing: ${playing.join(", ")}` + (waiting ? ` (${waiting} waiting)` : "")
      : "Choosing the next decks to play…";
  return [
    el("h3", {}, el("span", { class: "spinner spinner-small", "aria-hidden": "true" }), " Playing the field"),
    bar.node,
    el("p", { class: "fv-small" }, status("info", a.status === "queued" ? "Waiting" : "Playing"), " ",
      `${thousands(job.done || 0)} of ${thousands(job.total || 0)} games · ${words}`),
    pairs.length ? el("ul", { class: "fv-minis" }, pairs.map((p) => {
      const mini = progressBar(`Games against ${p.opponent.title}`, "span");
      mini.set(p.total ? p.done / p.total : 0);
      return el("li", { class: p.dropped ? "fv-muted" : null }, el("span", { class: "fv-mini-name", text: p.opponent.title }),
        mini.node, el("span", { class: "fv-mini-count", text: p.dropped ? "left out" : `${p.done}/${p.total}` }));
    })) : null,
    job.by ? el("p", { class: "fv-small", text: `Started by ${job.by}` }) : null,
    mayStopRuns(job) ? el("div", { class: "actions" }, el("button", { type: "button", class: "btn btn-danger", text: "Stop",
      onclick: () => fvStop(ctx) })) : null];
}

async function fvWrite(ctx, path, body) {
  const profile = state.profile?.id;
  ctx.busy = true;
  clearTimeout(ctx.timer);
  try {
    const answer = await apiWrite(path, { id: ctx.id, version: ctx.version, ...body });
    ctx.busy = false;
    if (fvHere(ctx) && state.profile?.id === profile) { fvDraw(ctx, answer); fvSchedule(ctx); }
    if (state.profile?.id === profile && typeof syncRunsPill === "function") syncRunsPill(true);
  } catch (e) {
    ctx.busy = false;
    if (fvHere(ctx) && state.profile?.id === profile) { toast(e.message || String(e)); fvRefresh(ctx); }
  }
}

function fvPlay(ctx) { return fvWrite(ctx, "/api/field/run", { budget: ctx.budget }); }

/** Stop asks first (a sheet, as every Stop does); every game that finished is kept. */
async function fvStop(ctx) {
  if (!fvHere(ctx) || !fvPlaying(ctx.answer || {}) || !mayStopRuns(ctx.answer?.job)) return null;
  const profile = state.profile?.id;
  const choice = await ask("Stop the field run?", ["Every game that finished is kept."],
    [{ value: "stop", text: "Stop it", kind: "danger" }, { value: "keep", text: "Keep playing", kind: "primary" }]);
  if (choice !== "stop" || !fvHere(ctx) || state.profile?.id !== profile || !fvPlaying(ctx.answer || {}) ||
      !mayStopRuns(ctx.answer?.job)) return null;
  return fvWrite(ctx, "/api/field/stop", {});
}
