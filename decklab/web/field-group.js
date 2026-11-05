/* Deck Lab's page: the deck view's "Against chosen decks" part (E3-S31, closing E3-S19's criterion 2), from
GET /api/field/group: the list against a group of house decks the viewer chooses (their own space's, and another
space's only when its decks are Public), such as a more experienced member's decks. The decks are ticked as chips
(at most the answer's max_opponents); then one figure gives the list's equal-weight average against them, with its
range and how many it's ahead of, even with and behind, then one row per chosen deck, hardest first, and Play with
the field's budgets. A group run is a field run of those decks: its games are ordinary matchups, so they count in
Rankings. While one waits or plays it shows its progress and Stop, asking again every GR_POLL_MS (it stops when the
page is left). Only lists and results show, never another space's counts.
Every class this file adds starts with "gr-"; it also uses field.js's fv- and gauntlet.js's gt- layout classes and
the page's shared ones (deck-section, filter-chips, box, btn, sub, empty, actions). Uses core.js's helpers, sim-ui.js's
winRateFigure and rangeBar, matchups.js's runChoiceControl, runsAllowed, metaWords and gamesWords, field.js's
FV_BUDGETS, FV_BUDGET_SUB and fvBudgetWords, gauntlet.js's gtTallyWords, editor.js's ask() and app.js's jumpTo (a
link with part=group, such as the Running list's, scrolls here). */
"use strict";

const GR_POLL_MS = 1500;          // how often a group run's progress is asked for while it waits or plays

/** The deck page's "Against chosen decks" part (id "sec-group"), or null for a Beginner Box half. */
function groupSection(data) {
  const s = data.summary;
  if (s.id.startsWith(BOX_PREFIX)) return null;
  const content = el("div", { class: "gr-content fv-content" }, loadingBox("Loading the decks you can choose…"));
  const section = el("section", { class: "deck-section gr-section", id: "sec-group", "aria-labelledby": "h-group" },
    el("h2", { id: "h-group", text: "Against chosen decks" }), content);
  const ctx = { section, content, token: routeToken, id: s.id, version: data.version, answer: null, chosen: [],
    budget: null, timer: 0, busy: false, asked: 0 };
  grRefresh(ctx);
  const part = new URLSearchParams(location.hash.split("?")[1] || "").get("part");
  if (part === "group") setTimeout(() => { if (ctx.token === routeToken) jumpTo("sec-group"); }, 0);
  return section;
}

function grHere(ctx) { return ctx.token === routeToken; }
function grPlaying(a) { return !!a && (a.status === "queued" || a.status === "running"); }
function grName(c) { return c.version && c.version !== "target" ? `${c.id}@${c.version}` : c.id; }

function grUrl(ctx) {
  const q = new URLSearchParams({ id: ctx.id, version: ctx.version });
  if (ctx.chosen.length) q.set("opponents", ctx.chosen.join(","));
  if (state.profile) q.set("profile", state.profile.id);
  return `/api/field/group?${q}`;
}

async function grRefresh(ctx, { timer = false } = {}) {
  clearTimeout(ctx.timer);
  if (!grHere(ctx) || ctx.busy) return;
  const asked = ++ctx.asked;
  try {
    const answer = await api(grUrl(ctx), timer ? { wakeHop: false } : {});
    if (!grHere(ctx) || ctx.busy || asked !== ctx.asked) return;
    grDraw(ctx, answer);
  } catch (e) {
    if (!grHere(ctx) || ctx.busy || asked !== ctx.asked) return;
    clear(ctx.content).append(loadFailed("How this list does against the decks you chose", e, () => grRefresh(ctx)));
    return;
  }
  grSchedule(ctx);
}

function grSchedule(ctx) {
  clearTimeout(ctx.timer);
  if (!grHere(ctx) || !grPlaying(ctx.answer)) return;
  ctx.timer = setTimeout(() => {
    if (grHere(ctx) && ctx.section.isConnected) grRefresh(ctx, { timer: true });
  }, GR_POLL_MS);
}

function grDraw(ctx, a) {
  ctx.answer = a;
  // A run waiting or playing shows its own group, whatever was ticked before the page was reloaded.
  if ((a.chosen || []).length) ctx.chosen = a.chosen.map(grName);
  if (!ctx.budget) ctx.budget = a.default_budget || "standard";
  clear(ctx.content);
  const choices = a.choices || [];
  add(ctx.content, [
    el("p", { class: "sub", text: "Choose decks to play this list against, such as another player's Public decks. " +
      "The games are ordinary matchups, so they count in Rankings too." }),
    choices.length ? grChoices(ctx, a) : el("p", { class: "empty", text: "There's no other deck of this format " +
      "you can choose." }),
    ctx.chosen.length ? el("div", { class: "fv-layout" },
      (a.games || 0) > 0 ? el("div", { class: "fv-main" }, grHeadline(a), grRows(a)) : null,
      el("div", { class: "fv-side" }, grPlayBox(ctx, a))) : null]);
}

/** The decks to choose from, as chips: another space's Public decks say so. Ticking one asks for the group again. */
function grChoices(ctx, a) {
  const max = a.max_opponents || 12;
  const id = "gr-label-choices";
  const full = ctx.chosen.length >= max;
  return el("div", { class: "gt-control gr-choices" },
    el("span", { class: "games-label", id, text: `Decks to play against (up to ${max})` }),
    el("div", { class: "filter-chips", role: "group", "aria-labelledby": id }, (a.choices || []).map((c) => {
      const name = grName(c), on = ctx.chosen.includes(name);
      return el("button", { type: "button", class: "filter-chip", text: c.public ? `${c.title} (Public)` : c.title,
        "aria-pressed": String(on), disabled: grPlaying(a) || (!on && full),
        onclick: () => {
          ctx.chosen = on ? ctx.chosen.filter((n) => n !== name) : [...ctx.chosen, name];
          grRefresh(ctx);
        } });
    })));
}

/** The equal-weight average against the chosen decks, with its range, tally and how many are tested so far. */
function grHeadline(a) {
  const o = a.overall;
  if (!o || o.rate == null || !a.played) return null;
  const rate = { value: o.rate, low: o.low, high: o.high };
  const what = `Win rate against these ${plural(a.of || 0, "deck")}`;
  const tally = gtTallyWords(a.tally);
  return el("div", { class: "gt-headline" },
    el("p", { class: "gt-headline-what", text: `Against ${plural(a.of || 0, "chosen deck")}:` }),
    el("div", { class: "gt-figure" }, winRateFigure(rate, { size: "hero", what, games: a.games || null, barred: true }),
      freshnessBadge(a.updated)),
    rangeBar(rate, { axis: true, decorative: true }),
    tally ? el("p", { class: "gt-tally", text: tally }) : null,
    a.played < a.of ? el("p", { class: "gt-small", text: `${a.played} of ${a.of} decks tested so far.` }) : null,
    a.note ? el("p", { class: "gt-small", text: a.note }) : null);
}

function grRows(a) {
  const played = (a.opponents || []).filter((o) => o.games && o.rate && o.rate.value != null);
  const waiting = (a.opponents || []).filter((o) => !played.includes(o));
  return [
    el("h3", { text: "Against each deck, hardest first" }),
    el("ul", { class: "gt-rows" }, played.map((o) => el("li", { class: o.not_meaningful ? "gt-row gt-muted" : "gt-row" },
      el("span", { class: "gt-name", text: o.title }),
      el("span", { class: "gt-barline" },
        rangeBar(o.rate, { compact: true, muted: o.not_meaningful, decorative: true }),
        el("span", { class: "gt-pct" }, winRateFigure(o.rate, { what: `Win rate against ${o.title}`, barred: true }))),
      el("span", { class: "gt-meta" }, el("span", { text: metaWords(o.verdict ? capitalise(o.verdict) : null,
        gamesWords(o.games), o.not_meaningful ? "Not meaningful" : null, o.problem) }),
      freshnessBadge(o.updated, { size: "row" }))))),
    waiting.length ? el("p", { class: "gt-small", text: `Not played yet: ${waiting.map((o) => o.title).join(", ")}.` })
      : null];
}

function grPlayBox(ctx, a) {
  const box = el("div", { class: "fv-play gr-play" });
  if (a.notice) box.append(el("p", { class: "fv-small", text: a.notice }));
  if (a.error) box.append(el("div", { class: "box box-crit" }, el("p", { text: a.error })));
  if (grPlaying(a)) {
    add(box, grLive(ctx, a));
    return box;
  }
  const ready = !a.forge || a.forge.ready;
  const options = FV_BUDGETS.map(([budget, title]) => ({ id: budget, title, sub: FV_BUDGET_SUB[budget],
    time: fvBudgetWords((a.budgets || {})[budget]) || null }));
  const choice = runChoiceControl(options, ctx.budget, (budget) => { ctx.budget = budget; });
  choice.node.hidden = !runsAllowed();
  add(box, [el("h3", { text: `Play ${plural(ctx.chosen.length, "chosen deck")}` }), choice.node,
    ready ? null : el("p", { class: "fv-small", text: (a.forge && a.forge.problem) || "Forge isn't ready on the PC." }),
    el("div", { class: "actions" }, el("button", { type: "button", class: "btn", text: "Play these decks",
      disabled: !ready || !state.profile, "data-run": true, onclick: () => grPlay(ctx) }))]);
  return box;
}

function grLive(ctx, a) {
  const job = a.job || {};
  const bar = progressBar("Group games played");
  bar.set(job.total ? job.done / job.total : 0);
  const playing = Object.values(job.pairs || {}).filter((p) => p.playing).map((p) => p.opponent.title);
  const words = a.status === "queued"
    ? (job.ahead > 0 ? `Waiting: ${plural(job.ahead, "run")} ahead of it` : "Starting…")
    : playing.length ? `Playing: ${playing.join(", ")}` : "Choosing the next decks to play…";
  return [
    el("h3", {}, el("span", { class: "spinner spinner-small", "aria-hidden": "true" }), " Playing the chosen decks"),
    bar.node,
    el("p", { class: "fv-small" }, status("info", a.status === "queued" ? "Waiting" : "Playing"), " ",
      `${thousands(job.done || 0)} of ${thousands(job.total || 0)} games · ${words}`),
    job.by ? el("p", { class: "fv-small", text: `Started by ${job.by}` }) : null,
    mayStopRuns(job) ? el("div", { class: "actions" }, el("button", { type: "button", class: "btn btn-danger",
      text: "Stop", onclick: () => grStop(ctx) })) : null];
}

async function grWrite(ctx, path, body) {
  const profile = state.profile?.id;
  ctx.busy = true;
  ctx.asked++;
  clearTimeout(ctx.timer);
  try {
    const answer = await apiWrite(path, { id: ctx.id, version: ctx.version, ...body });
    ctx.busy = false;
    if (grHere(ctx) && state.profile?.id === profile) { grDraw(ctx, answer); grSchedule(ctx); }
    if (state.profile?.id === profile && typeof syncRunsPill === "function") syncRunsPill(true);
  } catch (e) {
    ctx.busy = false;
    if (grHere(ctx) && state.profile?.id === profile) { toast(e.message || String(e)); grRefresh(ctx); }
  }
}

function grPlay(ctx) {
  const a = ctx.answer || {};
  const body = { budget: ctx.budget, opponents: [...ctx.chosen] };
  if (a.deck && a.deck.card_sha) body.expected_card_sha = a.deck.card_sha;
  return grWrite(ctx, "/api/field/group/run", body);
}

/** Stop asks first, as every Stop does; every game that finished is kept. */
async function grStop(ctx) {
  if (!grHere(ctx) || !grPlaying(ctx.answer) || !mayStopRuns(ctx.answer?.job)) return null;
  const profile = state.profile?.id;
  const choice = await ask("Stop playing the chosen decks?", ["Every game that finished is kept."],
    [{ value: "stop", text: "Stop it", kind: "danger" }, { value: "keep", text: "Keep playing", kind: "primary" }]);
  if (choice !== "stop" || !grHere(ctx) || state.profile?.id !== profile || !grPlaying(ctx.answer) ||
      !mayStopRuns(ctx.answer?.job)) return null;
  return grWrite(ctx, "/api/field/group/stop", {});
}
