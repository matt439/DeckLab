/* Deck Lab's page: the deck view's "Against popular decks" part (the gauntlet, decklab/design/gauntlet.md
section 6), from GET /api/gauntlet: the list against a balanced sample of decks from outside the house (EDHREC's
average Commander decks, Wizards precons, Forge's bundled 60-card decks), read by colour, number of colours, style
and tier, then one row per opponent, hardest first. Its choices (how many opponents, their colours, styles and
tiers) and the games a deck sit in the play box with the time estimate, then Play; while a run waits or plays it
shows its progress and Stop, asking again every GT_POLL_MS as field.js does (it stops when the page is left).
Before a catalogue is built on the PC it shows the command that builds it.
Every class this file and gauntlet.css add starts with "gt-"; it also uses the page's shared ones (deck-section,
segmented, filter-chips, box, btn, sub, empty, more). Uses core.js's helpers, sim-ui.js's winRateFigure and
rangeBar, matchups.js's runChoiceControl, runsAllowed, metaWords and gamesWords, editor.js's ask() and app.js's
jumpTo (a link with part=gauntlet scrolls here). */
"use strict";

const GT_POLL_MS = 1500;          // how often a gauntlet run's progress is asked for while it waits or plays
const GT_BUDGETS = [["fixed:50", "Quick look"], ["fixed:100", "Settle it"], ["fixed:200", "Precise"]];
const GT_BUDGET_SUB = { "fixed:50": "A first idea: 50 games against each deck.",
  "fixed:100": "100 games against each deck: each one's rate to about ±10 points.",
  "fixed:200": "200 games against each deck, so the groups are closer." };
const GT_STYLES = { aggro: "Aggro", midrange: "Midrange", control: "Control", combo: "Combo", ramp: "Ramp" };
const GT_TIERS = { core: "Core", upgraded: "Upgraded", precon: "Precons", easy: "Easy", medium: "Medium",
  hard: "Hard", "very hard": "Very hard" };
const GT_GROUPS = [["colour", "Colour"], ["identity_size", "Colours"], ["style", "Style"], ["tier", "Tier"]];

/** The deck page's "Against popular decks" part (id "sec-gauntlet"), or null for a Beginner Box half. */
function gauntletSection(data) {
  const s = data.summary;
  if (s.id.startsWith(BOX_PREFIX)) return null;
  const content = el("div", { class: "gt-content" }, loadingBox("Loading how this list does against popular decks…"));
  const section = el("section", { class: "deck-section gt-section", id: "sec-gauntlet", "aria-labelledby": "h-gauntlet" },
    el("h2", { id: "h-gauntlet", text: "Against popular decks" }), content);
  const ctx = { section, content, token: routeToken, id: s.id, version: data.version, answer: null, choice: null,
    budget: null, by: "colour", open: false, timer: 0, busy: false, asked: 0 };
  gtRefresh(ctx);
  const part = new URLSearchParams(location.hash.split("?")[1] || "").get("part");
  if (part === "gauntlet") setTimeout(() => { if (ctx.token === routeToken) jumpTo("sec-gauntlet"); }, 0);
  return section;
}

function gtHere(ctx) { return ctx.token === routeToken; }
function gtPlaying(a) { return !!a && (a.status === "queued" || a.status === "running"); }

/** The view's address: the deck and, once chosen, the sample's choices (the server's defaults until then). */
function gtUrl(ctx) {
  const q = new URLSearchParams({ id: ctx.id, version: ctx.version });
  const c = ctx.choice;
  if (c) {
    q.set("size", String(c.size));
    if (c.colours) q.set("colours", c.colours);
    if (c.styles.length) q.set("styles", c.styles.join(","));
    if (c.tiers.length) q.set("tiers", c.tiers.join(","));
  }
  if (state.profile) q.set("profile", state.profile.id);
  return `/api/gauntlet?${q}`;
}

/** timer: the poll while a run plays, which counts as use but never leaves the page for the wake gate. */
async function gtRefresh(ctx, { timer = false } = {}) {
  clearTimeout(ctx.timer);
  if (!gtHere(ctx) || ctx.busy) return;
  const asked = ++ctx.asked;
  try {
    const answer = await api(gtUrl(ctx), timer ? { wakeHop: false } : {});
    if (!gtHere(ctx) || ctx.busy || asked !== ctx.asked) return;
    gtKeepPlace(() => gtDraw(ctx, answer));
  } catch (e) {
    if (!gtHere(ctx) || ctx.busy || asked !== ctx.asked) return;
    gtKeepPlace(() => clear(ctx.content).append(loadFailed("How this list does against popular decks", e,
      () => gtRefresh(ctx))));
    return;
  }
  gtSchedule(ctx);
}

function gtKeepPlace(change) { return typeof keepPlace === "function" ? keepPlace(change) : change(); }

function gtSchedule(ctx) {
  clearTimeout(ctx.timer);
  if (!gtHere(ctx) || !gtPlaying(ctx.answer)) return;
  ctx.timer = setTimeout(() => {
    if (gtHere(ctx) && ctx.section.isConnected) gtRefresh(ctx, { timer: true });
  }, GT_POLL_MS);
}

function gtDraw(ctx, a) {
  ctx.answer = a;
  gtAnnounce(ctx, a);
  clear(ctx.content);
  if (!a.catalogue) {
    ctx.content.append(el("div", { class: "empty gt-empty" },
      el("p", { text: `There are no popular ${a.format === "commander" ? "Commander" : "60-card"} decks on the PC yet.` }),
      el("p", { class: "sub", text: "Build them once on the PC (it takes a few minutes):" }),
      el("pre", { class: "gt-command" }, el("code", { text: a.build_command || "" }))));
    return;
  }
  if (!ctx.choice) ctx.choice = gtChoiceOf(a);
  if (!ctx.budget) ctx.budget = a.default_budget || "fixed:100";
  const played = (a.games || 0) > 0;
  add(ctx.content, [
    el("p", { class: "sub", text: "How this list does against popular decks from outside the house, from Forge's AI " +
      "playing them (best of one). They never count in Rankings." }),
    played || gtPlaying(a)
      ? el("div", { class: "gt-layout" },
        el("div", { class: "gt-side" }, gtPlayBox(ctx, a)),
        el("div", { class: "gt-main" }, played ? gtGroups(ctx, a) : null, played ? gtRows(a) : null))
      : el("div", { class: "empty gt-empty" },
        el("p", { text: "No games against popular decks yet." }),
        el("p", { class: "sub", text: `Play ${plural((a.sample || {}).decks || 0, "popular deck")} to see how this ` +
          "list does by colour and by style." }),
        gtPlayBox(ctx, a, { inEmpty: true })),
    gtCredit(a)]);
}

/** The choices the server drew its sample from, as the controls hold them. */
function gtChoiceOf(a) {
  const f = (a.sample || {}).filters || {};
  return { size: (a.sample || {}).size || a.default_size || 12, colours: f.colours || "",
    styles: Array.isArray(f.styles) ? [...f.styles] : [], tiers: Array.isArray(f.tiers) ? [...f.tiers] : [] };
}

// ------------------------------------------------------------------ the results

/** One group kind at a time (Colour, Colours, Style or Tier), each group's equal-weight rate over its opponents,
 * its range, its opponents and games, and the spread between them; then the caveat. */
function gtGroups(ctx, a) {
  const groups = a.groups || {};
  const kinds = GT_GROUPS.filter(([key]) => (groups[key] || []).length);
  if (!kinds.length) return null;
  if (!kinds.some(([key]) => key === ctx.by)) ctx.by = kinds[0][0];
  const list = el("ul", { class: "gt-groups" });
  const draw = () => clear(list).append(...(groups[ctx.by] || []).map((g) => gtGroupRow(g)));
  const buttons = kinds.map(([key, title]) => el("button", { type: "button", text: title, "aria-pressed": String(key === ctx.by),
    onclick: () => { ctx.by = key; buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(kinds[i][0] === key))); draw(); } }));
  draw();
  return el("div", { class: "gt-groups-part" },
    el("h3", { id: "h-gauntlet-groups", text: "By group" }),
    el("div", { class: "segmented", role: "group", "aria-labelledby": "h-gauntlet-groups" }, buttons),
    list,
    el("p", { class: "sub gt-caveat", text: a.note || "Each range covers these sampled opponents only." }),
    ...(a.notes || []).map((text) => el("p", { class: "gt-small", text })));
}

function gtRate(value, low, high) { return value == null ? null : { value, low, high }; }

function gtGroupRow(g) {
  const rate = gtRate(g.rate, g.low, g.high);
  const what = `Win rate against ${g.label}`;
  const spread = Array.isArray(g.spread) && g.spread[0] != null
    ? `from ${Math.round(g.spread[0] * 100)}% to ${Math.round(g.spread[1] * 100)}% by opponent` : null;
  return el("li", { class: g.opponents < 2 ? "gt-group gt-muted" : "gt-group" },
    el("span", { class: "gt-name", text: g.label }),
    el("span", { class: "gt-barline" },
      rangeBar(rate, { compact: true, muted: g.opponents < 2, decorative: true }),
      el("span", { class: "gt-pct" }, winRateFigure(rate, { what, barred: true }))),
    el("span", { class: "gt-meta", text: metaWords(plural(g.opponents, "opponent"), gamesWords(g.games), spread, g.note) }));
}

/** One row per sampled opponent, hardest first (the server's order: the lowest range first), with where it's from. */
function gtRows(a) {
  const played = (a.opponents || []).filter((o) => o.games && o.rate && o.rate.value != null);
  const waiting = (a.opponents || []).filter((o) => !played.includes(o));
  return [
    el("h3", { text: "Against each deck, hardest first" }),
    el("ul", { class: "gt-rows" }, played.map((o) => {
      const what = `Win rate against ${o.title}`;
      const chips = o.not_meaningful ? [status("crit", "Not meaningful")] : [];
      return el("li", { class: o.not_meaningful ? "gt-row gt-muted" : "gt-row" },
        el("span", { class: "gt-name", text: o.title }),
        el("span", { class: "gt-barline" },
          rangeBar(o.rate, { compact: true, muted: o.not_meaningful, decorative: true }),
          el("span", { class: "gt-pct" }, winRateFigure(o.rate, { what, barred: true }))),
        el("span", { class: "gt-meta" },
          deckColourPieces((o.identity || "").split("")).pips(16),
          el("span", { text: metaWords(GT_STYLES[o.style] || o.style, GT_TIERS[o.tier] || o.tier, gamesWords(o.games),
            o.problem) }), chips),
        gtSource(o.source));
    })),
    waiting.length ? el("p", { class: "gt-small", text: `Not played yet: ${waiting.map((o) => o.title).join(", ")}.` }) : null];
}

/** Where a sparring deck is from: EDHREC's average deck (linked, with its rank and deck count), a Wizards precon
 * from MTGJSON, or a deck bundled with Forge. */
function gtSource(src) {
  const s = src || {};
  if (s.kind === "edhrec") {
    const facts = [s.rank != null ? `rank ${thousands(s.rank)}` : null,
      s.decks != null ? `${thousands(s.decks)} decks` : null].filter(Boolean).join(", ");
    return el("span", { class: "gt-source" }, "Average deck from ",
      s.url ? el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", text: "EDHREC" }) : "EDHREC",
      facts ? ` (${facts})` : "");
  }
  if (s.kind === "mtgjson") return el("span", { class: "gt-source", text: "Wizards precon, from MTGJSON" });
  if (s.kind === "forge") return el("span", { class: "gt-source", text: "A deck bundled with Forge" });
  return null;
}

function gtCredit(a) {
  return el("p", { class: "gt-small gt-credit", text: a.credit || "" });
}

// ------------------------------------------------------------------ choices and play

/** inEmpty: inside the empty state, whose lines already say what to do, so no heading. */
function gtPlayBox(ctx, a, { inEmpty = false } = {}) {
  const box = el("div", { class: "gt-play" });
  if (a.notice) box.append(el("p", { class: "gt-small", text: a.notice }));
  if (a.error) box.append(el("div", { class: "box box-crit" }, el("p", { text: a.error })));
  if (gtPlaying(a)) {
    add(box, gtLive(ctx, a));
    return box;
  }
  const ready = !a.forge || a.forge.ready;
  const options = GT_BUDGETS.map(([id, title]) => ({ id, title, sub: GT_BUDGET_SUB[id],
    time: gtBudgetWords((a.budgets || {})[id]) || null }));
  const choice = runChoiceControl(options, ctx.budget, (budget) => { ctx.budget = budget; }, { label: "Games a deck" });
  const allowed = runsAllowed();
  choice.node.hidden = !allowed;
  const none = !((a.sample || {}).decks);
  add(box, [inEmpty ? null : el("h3", { text: "Play popular decks" }),
    gtChoices(ctx, a), choice.node,
    none ? el("p", { class: "gt-small", text: "No popular deck matches these choices: choose fewer." }) : null,
    ready ? null : el("p", { class: "gt-small", text: (a.forge && a.forge.problem) || "Forge isn't ready on the PC." }),
    el("div", { class: "actions" }, el("button", { type: "button", class: "btn", text: "Play them",
      disabled: !ready || !state.profile || none, "data-run": true, onclick: () => gtPlay(ctx) }))]);
  return box;
}

/** The sample's choices in a closed disclosure whose summary says them: how many opponents, which colours
 * (identity within them), styles and tiers. Each change draws the sample again (nothing plays). */
function gtChoices(ctx, a) {
  const c = ctx.choice, opts = a.options || {};
  const pick = (change) => { change(); gtRefresh(ctx); };
  const toggle = (list, value) => (list.includes(value) ? list.filter((x) => x !== value) : [...list, value].sort());
  const details = el("details", { class: "more gt-choices" }, el("summary", { text: gtChoiceWords(c, a) }),
    gtSegmented("Opponents", (opts.sizes || []).map((n) => [n, String(n)]), c.size, (n) => pick(() => { c.size = n; })),
    gtChips("Only decks within these colours", [..."WUBRG"].map((x) => [x, capitalise(COLOUR_WORDS[x])]),
      [...c.colours], (x) => pick(() => { c.colours = [..."WUBRG"].filter((y) => toggle([...c.colours], x).includes(y)).join(""); })),
    gtChips("Styles", (opts.styles || []).map((x) => [x, GT_STYLES[x] || x]), c.styles,
      (x) => pick(() => { c.styles = toggle(c.styles, x); })),
    gtChips("Tiers", (opts.tiers || []).map((x) => [x, GT_TIERS[x] || x]), c.tiers,
      (x) => pick(() => { c.tiers = toggle(c.tiers, x); })));
  details.open = ctx.open;
  details.addEventListener("toggle", () => { ctx.open = details.open; });
  return details;
}

/** "12 opponents · Core · any colours · any style". */
function gtChoiceWords(c, a) {
  const colours = c.colours ? [...c.colours].map((x) => COLOUR_WORDS[x]).join(", ") : "any colours";
  const styles = c.styles.length ? c.styles.map((x) => GT_STYLES[x] || x).join(", ") : "any style";
  const tiers = c.tiers.length ? c.tiers.map((x) => GT_TIERS[x] || x).join(", ") : "every tier";
  const found = (a.sample || {}).decks;
  return metaWords(plural(found != null ? found : c.size, "opponent"), tiers, colours, styles);
}

function gtSegmented(label, options, value, onPick) {
  const id = `gt-label-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return el("div", { class: "gt-control" }, el("span", { class: "games-label", id, text: label }),
    el("div", { class: "segmented", role: "group", "aria-labelledby": id }, options.map(([v, title]) =>
      el("button", { type: "button", text: title, "aria-pressed": String(v === value), onclick: () => { if (v !== value) onPick(v); } }))));
}

function gtChips(label, options, chosen, onToggle) {
  const id = `gt-label-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return el("div", { class: "gt-control" }, el("span", { class: "games-label", id, text: label }),
    el("div", { class: "filter-chips", role: "group", "aria-labelledby": id }, options.map(([v, title]) =>
      el("button", { type: "button", class: "filter-chip", text: title, "aria-pressed": String(chosen.includes(v)),
        onclick: () => onToggle(v) }))));
}

/** "about 100 games a deck, about 25–40 minutes" for a budget (the answer's budgets). */
function gtBudgetWords(b) {
  if (!b) return "";
  const parts = [`about ${thousands(b.games)} games a deck`];
  if (b.new_games === 0) parts.push("nothing new to play");
  else if (b.minutes) parts.push(`about ${Math.round(b.minutes[0])}–${Math.round(b.minutes[1])} minutes`);
  else if (b.new_games) parts.push(`${thousands(b.new_games)} new games, time not yet measured`);
  return parts.join(", ");
}

/** A run waiting or playing: its progress, who's playing now and Stop. */
function gtLive(ctx, a) {
  const job = a.job || {};
  const pairs = Object.values(job.pairs || {});
  const bar = progressBar("Games against popular decks played");
  bar.set(job.total ? job.done / job.total : 0);
  const playing = pairs.filter((p) => p.playing).map((p) => (p.opponent || {}).title).filter(Boolean);
  const words = a.status === "queued"
    ? (job.ahead > 0 ? `Waiting: ${plural(job.ahead, "run")} ahead of it` : "Starting…")
    : playing.length ? `Playing: ${playing.join(", ")}` : "Choosing the next decks to play…";
  return [
    el("h3", {}, el("span", { class: "spinner spinner-small", "aria-hidden": "true" }), " Playing popular decks"),
    bar.node,
    el("p", { class: "gt-small" }, status("info", a.status === "queued" ? "Waiting" : "Playing"), " ",
      `${thousands(job.done || 0)} of ${thousands(job.total || 0)} games · ${words}`),
    job.by ? el("p", { class: "gt-small", text: `Started by ${job.by}` }) : null,
    mayStopRuns(job) ? el("div", { class: "actions" }, el("button", { type: "button", class: "btn btn-danger", text: "Stop",
      onclick: () => gtStop(ctx) })) : null];
}

function gtAnnounce(ctx, a) {
  if (!ctx.announcer) {
    ctx.announcer = el("p", { class: "sr-only", role: "status" });
    ctx.section.append(ctx.announcer);
  }
  const phase = a.status === "queued" ? "Waiting to play popular decks." : a.status === "running" ? "Playing popular decks."
    : ctx.phase ? "Finished playing popular decks." : "";
  if (gtPlaying(a) || ctx.phase) ctx.phase = gtPlaying(a) ? a.status : null;
  if (phase && ctx.announcer.textContent !== phase) ctx.announcer.textContent = phase;
}

async function gtWrite(ctx, path, body) {
  const profile = state.profile?.id;
  ctx.busy = true;
  ctx.asked++;
  clearTimeout(ctx.timer);
  try {
    const answer = await apiWrite(path, { id: ctx.id, version: ctx.version, ...body });
    ctx.busy = false;
    if (gtHere(ctx) && state.profile?.id === profile) { gtDraw(ctx, answer); gtSchedule(ctx); }
    if (state.profile?.id === profile && typeof syncRunsPill === "function") syncRunsPill(true);
  } catch (e) {
    ctx.busy = false;
    if (gtHere(ctx) && state.profile?.id === profile) { toast(e.message || String(e)); gtRefresh(ctx); }
  }
}

function gtPlay(ctx) {
  const a = ctx.answer || {}, c = ctx.choice || gtChoiceOf(a);
  const body = { budget: ctx.budget, size: c.size, colours: c.colours, styles: c.styles.join(","), tiers: c.tiers.join(",") };
  if (a.deck && a.deck.card_sha) body.expected_card_sha = a.deck.card_sha;
  return gtWrite(ctx, "/api/gauntlet/run", body);
}

/** Stop asks first, as every Stop does; every game that finished is kept. */
async function gtStop(ctx) {
  if (!gtHere(ctx) || !gtPlaying(ctx.answer) || !mayStopRuns(ctx.answer?.job)) return null;
  const profile = state.profile?.id;
  const choice = await ask("Stop playing popular decks?", ["Every game that finished is kept."],
    [{ value: "stop", text: "Stop it", kind: "danger" }, { value: "keep", text: "Keep playing", kind: "primary" }]);
  if (choice !== "stop" || !gtHere(ctx) || state.profile?.id !== profile || !gtPlaying(ctx.answer) ||
      !mayStopRuns(ctx.answer?.job)) return null;
  return gtWrite(ctx, "/api/gauntlet/stop", {});
}
