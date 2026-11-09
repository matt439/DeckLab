/* A deliberate second-engine check of saved lists. Opening Testing reads nothing here until the
   player opens this part; reads never start games. Every response belongs to its original deck,
   page, profile, request and connected controls. Independent scores are never averaged. */
"use strict";

const CC_POLL_MS = 1500;

function crosscheckSection(data) {
  const s = data.summary;
  if (s.id.startsWith(BOX_PREFIX)) return null;
  const content = el("div", { class: "cc-content", hidden: true });
  const section = el("section", { class: "deck-section", id: "sec-crosscheck", "aria-labelledby": "h-crosscheck" },
    el("h2", { id: "h-crosscheck", text: "Check with another simulator" }),
    el("p", { class: "sub", text: "Play the same saved lists in Forge and XMage. Each simulator keeps its own score." }));
  const ctx = { section, content, id: s.id, version: data.version, token: routeToken,
    profile: state.profile?.id, screen: deckScreen, asked: 0, timer: 0, busy: false, answer: null,
    opponent: null, opponentVersion: "target", games: 10, test: null, uncertain: false, reading: false };
  const open = el("button", { type: "button", class: "btn", text: "Choose a deck to test against", onclick: () => {
    if (!ccHere(ctx) || !open.isConnected || !ctx.section.contains(open)) return;
    open.hidden = true;
    content.hidden = false;
    ccRefresh(ctx);
  } });
  section.append(open, content);
  return section;
}

function ccHere(ctx) {
  return ctx.token === routeToken && ctx.profile === state.profile?.id && ctx.section.isConnected
    && ctx.screen === deckScreen && (!ctx.screen || ctx.screen.view.tab === "matchups");
}

function ccCurrent(ctx, hash, asked) {
  return ccHere(ctx) && hash === location.hash && asked === ctx.asked;
}

function ccPlaying(answer) { return answer?.status === "queued" || answer?.status === "running"; }

function ccUrl(ctx) {
  const query = new URLSearchParams({ id: ctx.id, version: ctx.version });
  if (ctx.opponent) {
    query.set("opponent", ctx.opponent);
    query.set("opponent_version", ctx.opponentVersion);
  }
  if (ctx.test) query.set("test", ctx.test);
  return `/api/crosscheck?${query}`;
}

async function ccRefresh(ctx, { timer = false } = {}) {
  clearTimeout(ctx.timer);
  if (!ccHere(ctx) || ctx.busy) return;
  const asked = ++ctx.asked, hash = location.hash;
  ctx.reading = true;
  ctx.content.setAttribute("aria-busy", "true");
  if (!ctx.answer) clear(ctx.content).append(loadingBox("Loading the simulator check…"));
  for (const button of ctx.content.querySelectorAll("button"))
    if (button.textContent === "Run both simulators") button.disabled = true;
  try {
    const answer = await api(ccUrl(ctx), timer ? { wakeHop: false } : {});
    if (!ccCurrent(ctx, hash, asked) || ctx.busy) return;
    ctx.reading = false;
    ctx.content.removeAttribute("aria-busy");
    ctx.uncertain = false;
    ccDraw(ctx, answer);
    ccSchedule(ctx);
  } catch (error) {
    if (!ccCurrent(ctx, hash, asked) || ctx.busy) return;
    ctx.reading = false;
    ctx.content.removeAttribute("aria-busy");
    clear(ctx.content).append(loadFailed("The simulator check", error, () => ccRefresh(ctx)));
  }
}

function ccSchedule(ctx) {
  clearTimeout(ctx.timer);
  if (!ccHere(ctx) || !ccPlaying(ctx.answer)) return;
  ctx.timer = setTimeout(() => { if (ccHere(ctx)) ccRefresh(ctx, { timer: true }); }, CC_POLL_MS);
}

function ccDraw(ctx, answer) {
  if (!answer || answer.deck?.id !== ctx.id || answer.deck?.version !== ctx.version || !Array.isArray(answer.choices))
    throw new Error("The server did not return a simulator check for this saved list.");
  ctx.answer = answer;
  ctx.test = answer.test || null;
  if (answer.opponent) {
    ctx.opponent = answer.opponent.id;
    ctx.opponentVersion = answer.opponent.version;
  }
  const playing = ccPlaying(answer), choices = answer.choices;
  const select = el("select", { id: "cc-opponent", "aria-label": "Opponent", disabled: playing,
    onchange: () => {
      if (!ccHere(ctx) || ctx.busy || playing || !select.isConnected || !ctx.content.contains(select)) return;
      const choice = choices.find((item) => item.id === select.value);
      ctx.opponent = choice?.id || null;
      ctx.opponentVersion = choice?.version || "target";
      ctx.test = null;
      ccRefresh(ctx);
    } }, el("option", { value: "", text: "Choose an opponent…" }),
    choices.map((choice) => el("option", { value: choice.id,
      text: choice.title + (choice.version === "owned" ? " (Play-now list)" : "") })));
  select.value = ctx.opponent || "";
  const games = el("select", { id: "cc-games", "aria-label": "Games per simulator", disabled: playing,
    onchange: () => { if (ccHere(ctx) && !ctx.busy && !playing && games.isConnected && ctx.content.contains(games)) ctx.games = Number(games.value); } },
    (answer.games_choices || [10, 20, 50]).map((n) => el("option", { value: String(n), text: `${n} games` })));
  games.value = String(ctx.games);
  const reasons = ["forge", "xmage"].map((name) => answer.engines?.[name]).filter((engine) => !engine?.ready)
    .map((engine) => engine?.problem || "A simulator is not ready on the server PC.");
  if (answer.why_not) reasons.push(answer.why_not);
  const start = el("button", { type: "button", class: "btn btn-primary", text: "Run both simulators",
    disabled: ctx.uncertain || playing || !answer.ready || !answer.may_start || !answer.opponent,
    onclick: () => { if (start.isConnected && ctx.content.contains(start)) ccStart(ctx); } });
  const refresh = el("button", { type: "button", class: "btn", text: "Refresh check",
    onclick: () => { if (refresh.isConnected && ctx.content.contains(refresh)) ccRefresh(ctx); } });
  const parts = [el("p", { class: "sub", text: answer.note || "These are 1v1 games. The two scores are kept separate." }),
    choices.length ? el("div", { class: "cc-controls" },
      el("label", { class: "cc-field", for: "cc-opponent" }, el("span", { text: "Opponent" }), select),
      el("label", { class: "cc-field", for: "cc-games" }, el("span", { text: "Games per simulator" }), games))
      : el("p", { class: "empty", text: "There is no other saved deck of this format you can choose." }),
    reasons.length ? el("div", { class: "box box-info", role: "status" }, reasons.map((text) => el("p", { text }))) : null,
    ccProgress(ctx, answer), answer.result ? ccResult(answer.result) : null,
    el("div", { class: "actions" }, start, refresh)];
  clear(ctx.content);
  add(ctx.content, parts);
}

function ccProgress(ctx, answer) {
  const job = answer.job;
  if (!job) return null;
  if (ccPlaying(answer)) {
    const progress = Number.isSafeInteger(job.done) && Number.isSafeInteger(job.total)
      ? `${job.done} of ${job.total} games processed.` : "Preparing the games…";
    return el("div", { class: "box box-info", role: "status" },
      el("p", { text: answer.status === "queued" ? "The simulator check is waiting." : "The simulator check is playing." }),
      el("p", { text: progress }), job.may_stop ? el("button", { type: "button", class: "btn", text: "Stop check",
        onclick: () => ccStop(ctx) }) : null);
  }
  if (job.error) return el("p", { class: "box box-warn", role: "status", text: job.error === "stopped"
    ? "The check was stopped. Completed games are kept; unfinished games do not count as losses." : job.error });
  return null;
}

function ccRate(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100 ? `${value.toFixed(1)}%` : "—";
}

function ccRange(counts) {
  const interval = counts?.win_rate_interval;
  return interval && interval.confidence === 0.95 && Number.isFinite(interval.low) && Number.isFinite(interval.high)
    && interval.low >= 0 && interval.high <= 100 && interval.low <= interval.high
    ? `${interval.low.toFixed(1)}–${interval.high.toFixed(1)}%` : "—";
}

function ccResult(result) {
  const changed = !!result.has_variant;
  const headings = ["Simulator", "Completed", "Win rate", "95% range", ...(changed ? ["Changed list", "Difference"] : []), "Unfinished"];
  const rows = ["forge", "xmage"].map((name) => {
    const engine = result.engines?.[name] || {}, counts = engine.baseline || {};
    // Cancelled games are a labelled subset of unplayed, not another set of games.
    const unfinished = [counts.failed, counts.timeouts, counts.unplayed].filter(Number.isSafeInteger).reduce((a, b) => a + b, 0);
    const completed = Number.isSafeInteger(counts.completed) ? counts.completed : 0;
    const delta = engine.delta_percentage_points;
    const difference = typeof delta === "number" && Number.isFinite(delta) ? `${delta > 0 ? "+" : ""}${delta.toFixed(1)} points` : "—";
    return el("tr", {}, el("th", { scope: "row", text: name === "forge" ? "Forge" : "XMage" }),
      el("td", { text: String(completed) }), el("td", { text: ccRate(counts.win_rate) }), el("td", { text: ccRange(counts) }),
      ...(changed ? [el("td", { text: ccRate(engine.variant?.win_rate) }), el("td", { text: difference })] : []),
      el("td", { text: String(unfinished) }));
  });
  const opponent = result.decks?.opponent?.title || "the chosen opponent";
  return el("div", { class: "box cc-result" }, el("h3", { text: `Saved check against ${opponent}` }),
    result.current === false ? el("p", { class: "box box-warn", text: "A saved list has changed since this check. These results describe the earlier lists." }) : null,
    el("div", { class: "table-wrap cc-table", tabindex: "0", role: "region",
      "aria-label": "Simulator results, scroll horizontally for all columns" }, el("table", { class: "data" },
      el("caption", { text: "Each simulator's score for the checked list; no combined win rate." }),
      el("thead", {}, el("tr", {}, headings.map((text) => el("th", { scope: "col", text })))),
      el("tbody", {}, rows))),
    ...["forge", "xmage"].map((name) => {
      const engine = result.engines?.[name], title = name === "forge" ? "Forge" : "XMage";
      return engine?.missing_cards?.length ? el("p", { class: "box box-warn", text: `${title} does not support: ${engine.missing_cards.join(", ")}.` })
        : engine?.problem ? el("p", { class: "box box-warn", text: `${title}: ${engine.problem}` }) : null;
    }),
    el("p", { class: "sub", text: result.agreement?.text || "Compare the two scores; agreement does not establish human playing strength." }),
    el("p", { class: "sub", text: "Unfinished games are shown separately. Small samples are a first look; these games do not affect Forge's Rankings." }));
}

function ccControls(ctx, disabled) {
  for (const tag of ["button", "select"])
    for (const node of ctx.content.querySelectorAll(tag)) node.disabled = disabled;
}

async function ccWrite(ctx, path, body) {
  if (!ccHere(ctx) || ctx.busy) return;
  const asked = ++ctx.asked, hash = location.hash;
  ctx.busy = true;
  clearTimeout(ctx.timer);
  ccControls(ctx, true);
  try {
    const answer = await apiWrite(path, body);
    ctx.busy = false;
    if (!ccCurrent(ctx, hash, asked)) return;
    ctx.uncertain = false;
    ccDraw(ctx, answer);
    ccSchedule(ctx);
  } catch (error) {
    ctx.busy = false;
    if (!ccCurrent(ctx, hash, asked)) return;
    // A lost response may follow a successful start. A deliberate refresh can recover it;
    // never automatically resubmit or discard the user's selection.
    ctx.uncertain = true;
    ccDraw(ctx, ctx.answer);
    ctx.content.insertBefore(el("p", { class: "box box-warn", role: "status",
      text: `${error.message || "The server did not answer."} Refresh this check before trying again.` }),
    ctx.content.children[0] || null);
  }
}

function ccStart(ctx) {
  const answer = ctx.answer;
  if (!ccHere(ctx) || ctx.busy || ctx.reading || ctx.uncertain || ccPlaying(answer) || !answer?.ready || !answer?.may_start || !answer.opponent
      || !/^[a-f0-9]{64}$/.test(answer.deck.card_sha) || !/^[a-f0-9]{64}$/.test(answer.opponent.card_sha)) return;
  return ccWrite(ctx, "/api/crosscheck/run", { id: ctx.id, version: ctx.version,
    opponent: answer.opponent.id, opponent_version: answer.opponent.version, games: ctx.games,
    expected_card_sha: answer.deck.card_sha, expected_opponent_card_sha: answer.opponent.card_sha });
}

async function ccStop(ctx) {
  if (!ccHere(ctx) || ctx.busy || !ccPlaying(ctx.answer) || !ctx.answer.job?.may_stop) return;
  const test = ctx.answer.job.test, hash = location.hash, asked = ctx.asked;
  const choice = await ask("Stop this simulator check?", ["Completed games are kept. Unfinished games do not count as losses."],
    [{ value: "stop", text: "Stop check", kind: "danger" }, { value: "keep", text: "Keep playing", kind: "primary" }]);
  if (choice !== "stop" || !ccCurrent(ctx, hash, asked) || !ccPlaying(ctx.answer)
      || !ctx.answer.job?.may_stop || ctx.answer.job.test !== test) return;
  return ccWrite(ctx, "/api/crosscheck/stop", { test });
}
