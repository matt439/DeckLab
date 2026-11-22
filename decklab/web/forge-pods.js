/* Four-player Commander simulations (E9-S11, E9-S21, E9-S22, E3-S55). A reviewed pod is separate from
 * head-to-head tests and the Game log's physical games. No request starts a run except Start.
 * Loaded with the matchup scripts; every response belongs to one route, profile and connected page. */
"use strict";

const FP_GAMES = [16, 32, 64, 128];
const FP_KEY = /^[0-9a-f]{64}$/;

function fpHref(key = null) { return "#/forge-pods" + (key ? `?key=${encodeURIComponent(key)}` : ""); }

function fpHere(ctx) {
  return ctx.token === routeToken && ctx.profile === state.profile?.id && ctx.root.isConnected &&
    ctx.address === location.hash;
}

function fpChoiceKey(deck) { return `${deck.id}|${deck.version || "target"}`; }
function fpPlaying(answer) { return ["queued", "running"].includes(answer?.status); }
function fpSignature(ctx) { return JSON.stringify({ lineup: ctx.lineup, decks: fpSelected(ctx), games: ctx.games }); }
function fpSelected(ctx) { return ctx.lineup ? ctx.selected.slice(0, 1) : ctx.selected; }

function fpChosen(ctx) {
  return fpSelected(ctx).map(value => (ctx.answer?.choices || []).find(deck => fpChoiceKey(deck) === value));
}
function fpLineup(ctx) { return (ctx.answer?.lineups || []).find(lineup => lineup.id === ctx.lineup); }

/** Only declared target brackets qualify the choices; a detected minimum cannot stand in for one. */
function fpChoiceProblem(ctx) {
  const decks = fpChosen(ctx);
  const lineup = fpLineup(ctx);
  if (ctx.lineup && !lineup) return "This published precon lineup is unavailable. Choose another lineup.";
  if (decks.some(deck => !deck)) return ctx.lineup ? "Choose a saved Commander deck." : "Choose four Commander decks.";
  if (!lineup && new Set(decks.map(deck => sameDeckId(deck.id))).size !== 4) return "Choose four different decks.";
  const brackets = [...decks.map(deck => deck.target_bracket), ...(lineup ? [lineup.target_bracket] : [])];
  if (brackets.some(value => !Number.isInteger(value) || value < 1 || value > 5)) {
    return lineup ? "Set a target bracket on your saved deck before checking this pod."
      : "Set a target bracket on each chosen deck before checking this pod.";
  }
  if (Math.max(...brackets) - Math.min(...brackets) > 1) return "Choose decks whose target brackets are at most one apart.";
  return null;
}

function fpStartProblem(ctx) {
  const a = ctx.answer;
  if (a?.simulations?.may_start === false) return a.simulations.why_not || "You cannot start simulations right now.";
  if (a?.forge?.ready === false) return a.forge.problem || "Forge is not ready on the PC.";
  if (fpPlaying(a)) return "This pod is already waiting or playing.";
  if (ctx.uncertain) return "Refresh the run before starting again; the PC did not confirm the last request.";
  if (fpChoiceProblem(ctx)) return fpChoiceProblem(ctx);
  if (!ctx.plan || ctx.plan.signature !== fpSignature(ctx)) return "Check this pod before starting.";
  if (ctx.plan.remaining === 0) return "This sample already has all its planned games. Change the run size or deck choices, then check again.";
  return null;
}

function fpControls(ctx) {
  const problem = fpChoiceProblem(ctx);
  ctx.check.disabled = !!ctx.busy || !!problem || fpPlaying(ctx.answer) || ctx.uncertain;
  ctx.start.disabled = !!ctx.busy || !!fpStartProblem(ctx);
  ctx.start.setAttribute("aria-describedby", "fp-start-reason");
  ctx.reason.textContent = fpStartProblem(ctx) || "Seats rotate between batches. Start plays only this reviewed pod.";
  ctx.selectedControls.forEach(control => { control.disabled = !!ctx.busy; });
  ctx.lineupControl.disabled = !!ctx.busy;
  ctx.gamesControl.disabled = !!ctx.busy;
  if (!ctx.plan) clear(ctx.review);
}

function fpInvalidate(ctx) {
  if (!fpHere(ctx) || ctx.busy) return;
  ctx.plan = null;
  clear(ctx.message);
  fpControls(ctx);
}

function fpPaintLineup(ctx) {
  const precons = !!ctx.lineup;
  ctx.firstDeckLabel.textContent = precons ? "Saved Commander deck" : "Deck 1";
  ctx.deckFields.slice(1).forEach(field => { field.hidden = precons; });
  ctx.lineupHelp.textContent = precons
    ? "The saved deck and the precons must be within one target bracket."
    : "Choose four different Commander decks you can see. Their declared target brackets must be at most one apart. Targets are aims, not a guarantee of equal power.";
  const lineup = fpLineup(ctx);
  add(clear(ctx.lineupInfo), [lineup ? el("ul", {}, lineup.precons.map(fpLineupDeck)) : null]);
}

function fpForm(ctx) {
  const selectDeck = index => {
    const select = el("select", { class: "fp-deck", id: `fp-deck-${index}`, onchange: () => {
      if (!fpHere(ctx) || ctx.busy) return;
      ctx.selected[index] = select.value;
      fpInvalidate(ctx);
    } });
    ctx.selectedControls.push(select);
    const label = el("span", { text: `Deck ${index + 1}` });
    if (index === 0) ctx.firstDeckLabel = label;
    return el("label", { class: "fp-field", for: `fp-deck-${index}` }, label, select);
  };
  ctx.lineupControl = el("select", { id: "fp-lineup", onchange: () => {
    if (!fpHere(ctx) || ctx.busy) return;
    ctx.lineup = ctx.lineupControl.value;
    fpPaintLineup(ctx);
    fpInvalidate(ctx);
  } });
  ctx.lineupHelp = el("p", { class: "sub" });
  ctx.lineupInfo = el("div", { class: "fp-lineup-info" });
  ctx.deckFields = [0, 1, 2, 3].map(selectDeck);
  ctx.gamesControl = el("select", { class: "fp-games", id: "fp-games", onchange: () => {
    if (!fpHere(ctx) || ctx.busy) return;
    ctx.games = Number(ctx.gamesControl.value);
    fpInvalidate(ctx);
  } }, FP_GAMES.map(games => el("option", { value: String(games), text: `${games} pod games` })));
  ctx.gamesControl.value = String(ctx.games);
  ctx.check = el("button", { type: "button", class: "btn", text: "Check this pod", onclick: () => fpCheck(ctx) });
  ctx.start = el("button", { type: "button", class: "btn btn-primary", text: "Start", onclick: () => fpStart(ctx) });
  ctx.reason = el("p", { class: "sub run-blocked", id: "fp-start-reason" });
  ctx.review = el("div", { class: "fp-plan", "aria-live": "polite" });
  ctx.message = el("div", { class: "fp-message", role: "status" });
  return el("section", { class: "box fp-chooser", "aria-labelledby": "fp-choose-heading" },
    el("h2", { id: "fp-choose-heading", text: "Choose the pod" }),
    el("label", { class: "fp-field", for: "fp-lineup" }, "Lineup", ctx.lineupControl),
    ctx.lineupHelp, ctx.lineupInfo,
    el("div", { class: "fp-choices" }, ctx.deckFields),
    el("label", { class: "fp-field", for: "fp-games" }, "How many games?", ctx.gamesControl),
    el("p", { class: "sub", text: "Four-player games can take considerably longer than a head-to-head test. The PC stays awake while they play." }),
    el("div", { class: "actions" }, ctx.check), ctx.review,
    el("div", { class: "actions" }, ctx.start), ctx.reason, ctx.message);
}

function fpUrl(ctx) {
  const q = new URLSearchParams();
  if (ctx.key) q.set("key", ctx.key);
  return "/api/forge/pods" + (q.size ? `?${q}` : "");
}

async function showForgePods(params, token) {
  const root = el("div", { class: "fp-page" });
  clear($("#main")).append(root);
  const ctx = { root, token, profile: state.profile?.id, address: location.hash,
    key: params.get("key") || null, answer: null, selected: ["", "", "", ""], games: FP_GAMES[0],
    selectedControls: [], lineup: "", plan: null, busy: false, uncertain: false, initialized: false, watcher: null,
    choicesSignature: null, lineupsSignature: null };
  add(root, [crumb("#/matchups", routeFor("matchups").label), pageHead({ title: "Simulate a four-player pod",
    description: "Test four Commander decks together with Forge's AI." })]);
  if (ctx.key && !FP_KEY.test(ctx.key)) {
    root.append(errorBox("This pod couldn't be opened", new ApiError(404, "That link is not a pod run's address."), null,
      [fpHref(), "Choose a pod"]));
    afterRender();
    return;
  }
  ctx.refresh = matchupRefreshStatus();
  ctx.content = el("div", { class: "fp-content" });
  root.append(ctx.refresh.node, ctx.content);
  ctx.content.append(loadingBox("Loading four-player pods…"));
  await fpRead(ctx);
  if (fpHere(ctx)) afterRender();
}

async function fpRead(ctx) {
  if (!fpHere(ctx) || ctx.busy) return;
  ctx.watcher?.stop();
  const requestedKey = ctx.uncertain && ctx.attemptedKey ? ctx.attemptedKey : ctx.key;
  try {
    let answer;
    try {
      answer = await api(requestedKey ? `/api/forge/pods?key=${encodeURIComponent(requestedKey)}` : "/api/forge/pods");
    } catch (error) {
      // After an unconfirmed Start, read that exact run first. A definite missing run permits
      // a fresh read of the chooser, without repeating a write or assuming it started.
      if (!ctx.uncertain || error.status !== 404 || !fpHere(ctx)) throw error;
      answer = await api("/api/forge/pods");
    }
    if (!fpHere(ctx) || ctx.busy) return;
    ctx.uncertain = false;
    ctx.privacyRefused = false;
    if (requestedKey && answer.key === requestedKey) fpAddress(ctx, requestedKey);
    clear(ctx.message || el("div"));
    fpAnswer(ctx, answer);
    fpWatch(ctx);
  } catch (error) {
    if (!fpHere(ctx) || ctx.busy) return;
    ctx.plan = null;
    ctx.answer = null;
    clear(ctx.content).append(loadFailed("Four-player pods", error, () => fpRead(ctx)));
    ctx.initialized = false;
    ctx.selectedControls = [];
    ctx.choicesSignature = null;
    ctx.lineupsSignature = null;
  }
}

function fpAddress(ctx, key) {
  ctx.key = key;
  ctx.address = fpHref(key);
  history.replaceState(history.state, "", ctx.address);
}

function fpWatch(ctx) {
  ctx.watcher?.stop();
  if (ctx.privacyRefused) return;
  ctx.watcher = watchMatchupUpdates({ token: ctx.token, host: () => ctx.root, url: fpUrl(ctx),
    active: () => fpPlaying(ctx.answer), interval: 2000, view: ctx.refresh,
    onFresh: answer => { if (fpHere(ctx)) fpAnswer(ctx, answer); },
    onLost: error => {
      if (!fpHere(ctx)) return;
      if ([403, 404].includes(error.status)) {
        ctx.watcher?.stop();
        ctx.plan = null;
        ctx.answer = null;
        clear(ctx.content).append(loadFailed("This pod", error));
      }
    } });
}

function fpAnswer(ctx, answer) {
  ctx.answer = answer;
  if (!ctx.initialized) {
    ctx.initialized = true;
    const games = answer.result?.planned ?? answer.result?.games ?? answer.plan?.games ?? answer.default_games;
    if (FP_GAMES.includes(games)) ctx.games = games;
    ctx.form = fpForm(ctx);
    ctx.live = el("div", { class: "fp-live" });
    ctx.result = el("div", { class: "fp-result" });
    ctx.history = el("div", { class: "fp-history" });
    clear(ctx.content).append(ctx.live, ctx.result, ctx.form, ctx.history);
    if (answer.sides?.length === 4) {
      ctx.lineup = answer.lineup || "";
      ctx.selected = ctx.lineup ? [fpChoiceKey(answer.sides[0]), "", "", ""] : answer.sides.map(fpChoiceKey);
    }
  }
  const lineups = answer.lineups || [];
  const lineupsSignature = JSON.stringify(lineups);
  if (lineupsSignature !== ctx.lineupsSignature) {
    ctx.lineupsSignature = lineupsSignature;
    if (ctx.lineup) ctx.plan = null;
    clear(ctx.lineupControl).append(el("option", { value: "", text: "Four saved Commander decks" }),
      ...lineups.map(lineup => el("option", { value: lineup.id, text: `Published precons · ${lineup.title}` })));
    if (ctx.lineup && !fpLineup(ctx)) {
      ctx.lineupControl.append(el("option", { value: ctx.lineup, disabled: true, text: "Saved lineup unavailable" }));
    } else if (!lineups.length) {
      ctx.lineupControl.append(el("option", { disabled: true, text: "Published precon lineup unavailable" }));
    }
    ctx.lineupControl.value = ctx.lineup;
    fpPaintLineup(ctx);
  }
  const choices = answer.choices || [];
  const signature = JSON.stringify(choices);
  if (signature !== ctx.choicesSignature) {
    ctx.choicesSignature = signature;
    ctx.plan = null;
    ctx.selectedControls.forEach((select, i) => {
      clear(select).append(el("option", { value: "", text: "Choose a Commander deck…" }),
        ...choices.map(deck => el("option", { value: fpChoiceKey(deck),
          text: `${deck.title}${deck.version === "owned" ? " (play-now list)" : ""} · ${deck.target_bracket == null ? "target bracket not set" : `target bracket ${deck.target_bracket}`}${deck.public ? " · Public" : ""}` })));
      if (!choices.some(deck => fpChoiceKey(deck) === ctx.selected[i])) ctx.selected[i] = "";
      select.value = ctx.selected[i];
    });
  }
  replaceMatchupContent(ctx.live, () => {
    clear(ctx.live);
    if (fpPlaying(answer)) ctx.live.append(fpLivePart(ctx, answer));
    if (!ctx.key && answer.running?.length) ctx.live.append(fpRunningPart(answer.running));
    if (answer.notice) ctx.live.append(el("p", { class: "note", text: answer.notice }));
    if (answer.error) ctx.live.append(markedBox("crit", "h2", "The last run did not finish", el("p", { text: answer.error })));
  });
  clear(ctx.result).append(fpResultPart(answer));
  add(clear(ctx.history), [fpHistoryPart(answer)]);
  fpControls(ctx);
}

function fpBody(ctx) {
  const body = { decks: fpChosen(ctx).map(deck => ({ id: deck.id, version: deck.version || "target" })), games: ctx.games };
  if (ctx.lineup) body.lineup = ctx.lineup;
  return body;
}

function fpPreconSource(deck) {
  if (!deck.source_name) return null;
  if (!/^https:\/\//.test(deck.source_url || "")) return deck.source_name;
  return el("a", { href: deck.source_url, target: "_blank", rel: "noopener noreferrer",
    text: `${deck.source_name} list`, "aria-label": `${deck.source_name} list for ${deck.title}` });
}

function fpLineupDeck(deck) {
  const source = fpPreconSource(deck);
  return el("li", {}, deck.title, source ? [" · ", source] : null);
}

function fpWriteFailure(ctx, error, uncertain = false) {
  ctx.plan = null;
  ctx.uncertain = uncertain;
  if ([403, 404].includes(error.status)) {
    // A selected public deck may have become private. A refusal cannot keep its old title,
    // saved result or chooser options visible while another read is being considered.
    ctx.privacyRefused = true;
    ctx.watcher?.stop();
    ctx.answer = null;
    ctx.initialized = false;
    ctx.selected = ["", "", "", ""];
    ctx.lineup = "";
    ctx.selectedControls = [];
    ctx.choicesSignature = null;
    ctx.lineupsSignature = null;
    clear(ctx.content).append(loadFailed("This pod", error, () => fpRead(ctx)));
    return;
  }
  clear(ctx.message).append(el("p", { class: "note note-crit", text: error.message || "The PC could not complete this request." }),
    el("p", { class: "sub", text: uncertain ? "The PC did not confirm whether the run started. Refresh before doing anything else. Your choices are kept."
      : "Your choices are kept. Check this pod again before starting." }),
    el("button", { type: "button", class: "btn", text: "Refresh", onclick: () => fpRead(ctx) }));
}

async function fpCheck(ctx) {
  if (!fpHere(ctx) || ctx.busy || fpChoiceProblem(ctx) || fpPlaying(ctx.answer) || ctx.uncertain) return;
  const signature = fpSignature(ctx), body = fpBody(ctx);
  ctx.busy = true;
  ctx.watcher?.hold();
  clear(ctx.message).append(loadingBox("Checking this pod…", { small: true }));
  fpControls(ctx);
  try {
    const answer = await apiWrite("/api/forge/pods/plan", body);
    if (!fpHere(ctx) || signature !== fpSignature(ctx)) return;
    if (!FP_KEY.test(answer.key || "")) throw new Error("The PC did not return a reviewed pod. Refresh and check it again.");
    fpAnswer(ctx, answer);
    if (signature !== fpSignature(ctx) || fpChoiceProblem(ctx)) {
      throw new Error("The available decks changed. Choose the pod and check it again.");
    }
    const remaining = Number.isInteger(answer.plan?.remaining) ? answer.plan.remaining : ctx.games;
    const completed = Number.isInteger(answer.plan?.completed) ? answer.plan.completed : Math.max(0, ctx.games - remaining);
    ctx.plan = { key: answer.key, signature, remaining };
    clear(ctx.message);
    clear(ctx.review).append(el("h3", { text: remaining === 0 ? "This sample is complete" : "Ready to start" }),
      el("ul", {}, (answer.sides || fpChosen(ctx)).map(fpLineupDeck)),
      el("p", { text: remaining === 0 ? `All ${ctx.games} planned pod games are already saved. No new games are needed.`
        : completed > 0 ? `${completed} of ${ctx.games} planned pod games are already saved. Start resumes the ${remaining} remaining games, keeping completed games and rotating seats between batches.`
        : `${ctx.games} pod games, with seats rotated between batches. No games have started.` }));
    const estimate = answer.plan?.estimated_seconds;
    if (remaining > 0 && fpFinite(estimate) && estimate > 0) {
      ctx.review.append(el("p", { class: "sub",
        text: `About ${durationWords(estimate)} for ${plural(remaining, "remaining game")} with one Forge worker. Timing varies.` }));
    }
  } catch (error) {
    if (fpHere(ctx)) fpWriteFailure(ctx, error);
  } finally {
    if (fpHere(ctx)) { ctx.busy = false; fpControls(ctx); ctx.watcher?.release(); }
  }
}

async function fpStart(ctx) {
  if (!fpHere(ctx) || ctx.busy || fpStartProblem(ctx)) return;
  const body = { ...fpBody(ctx), expected_key: ctx.plan.key };
  ctx.busy = true;
  ctx.attemptedKey = body.expected_key;
  ctx.watcher?.hold();
  clear(ctx.message).append(loadingBox("Starting this pod…", { small: true }));
  fpControls(ctx);
  try {
    const answer = await apiWrite("/api/forge/pods/run", body);
    if (!fpHere(ctx)) return;
    ctx.plan = null;
    if (FP_KEY.test(answer.key || "")) fpAddress(ctx, answer.key);
    clear(ctx.message);
    fpAnswer(ctx, answer);
    if (typeof syncRunsPill === "function") syncRunsPill(true);
  } catch (error) {
    if (fpHere(ctx)) fpWriteFailure(ctx, error, !error.status || error.status >= 500);
  } finally {
    if (fpHere(ctx)) { ctx.busy = false; fpControls(ctx); fpWatch(ctx); }
  }
}

function fpLivePart(ctx, answer) {
  const job = answer.job || {}, total = job.total || answer.plan?.games || 0, done = job.done || 0;
  const waiting = answer.status === "queued";
  const bar = progressBar("Pod games completed");
  bar.set(total ? done / total : 0);
  const node = el("section", { class: "box", "aria-labelledby": "fp-live-heading" },
    el("h2", { id: "fp-live-heading", text: waiting ? "Waiting to play" : "Playing this pod" }),
    el("p", { text: waiting && job.ahead > 0 ? `${plural(job.ahead, "run")} ahead of this pod.`
      : `${thousands(done)} of ${thousands(total)} pod games completed.` }), bar.node);
  if (job.may_stop && answer.key) node.append(el("button", { type: "button", class: "btn btn-danger", text: "Stop",
    onclick: () => fpStop(ctx, answer.key) }));
  return node;
}

function fpRunningPart(running) {
  const visible = running.filter(run => !run.hidden && FP_KEY.test((run.key || "").replace(/^pods:/, "")));
  if (!visible.length) return el("div");
  return el("section", { class: "box", "aria-labelledby": "fp-running-heading" },
    el("h2", { id: "fp-running-heading", text: "Pods playing now" }),
    el("ul", { class: "mu-list" }, visible.map(run => el("li", {},
      el("a", { class: "mu-row", href: run.link || fpHref(run.key.replace(/^pods:/, "")) },
        rowNames({ title: run.title || "Four-player Commander pod" }, null, false),
        el("span", { class: "sub", text: run.status === "queued" ? "Waiting to play"
          : `${thousands(run.done || 0)} of ${thousands(run.total || 0)} pod games completed` }))))));
}

async function fpStop(ctx, key) {
  if (!fpHere(ctx) || ctx.busy || ctx.questionPending || !fpPlaying(ctx.answer) || !ctx.answer.job?.may_stop || ctx.answer.key !== key) return;
  ctx.questionPending = true;
  const question = await ask("Stop this pod run?", ["Every completed pod game is kept."],
    [{ value: "stop", text: "Stop it", kind: "danger" }, { value: "keep", text: "Keep playing", kind: "primary" }]);
  ctx.questionPending = false;
  if (question !== "stop" || !fpHere(ctx) || ctx.busy || !fpPlaying(ctx.answer) || ctx.answer.key !== key || !ctx.answer.job?.may_stop) return;
  ctx.busy = true;
  ctx.watcher?.hold();
  fpControls(ctx);
  try {
    const answer = await apiWrite("/api/forge/pods/stop", { key });
    if (!fpHere(ctx)) return;
    fpAnswer(ctx, answer);
    if (typeof syncRunsPill === "function") syncRunsPill(true);
  } catch (error) {
    if (fpHere(ctx)) fpWriteFailure(ctx, error);
  } finally {
    if (fpHere(ctx)) { ctx.busy = false; fpControls(ctx); ctx.watcher?.release(); }
  }
}

function fpFinite(value) { return typeof value === "number" && Number.isFinite(value); }

function fpSeatBreakdown(deck, seats) {
  if (!deck || !seats) return null;
  return el("section", { class: "fp-seat-results", "aria-labelledby": "fp-seats-heading" },
    el("h3", { id: "fp-seats-heading", text: `${deck.title} by seat` }),
    el("ul", {}, [1, 2, 3, 4].map(seat => {
      const row = seats[seat];
      const words = row?.pods ? `${plural(row.wins, "win")} in ${plural(row.pods, "counted pod")}`
        : "no counted pod games";
      return el("li", { text: metaWords(`Seat ${seat}`, words) });
    })));
}

/** A pod uses the whole 0–100% range; the head-to-head bar's 50% centre would be misleading here. */
function fpResultPart(answer) {
  const result = answer?.result;
  if (!result) return emptyBox("No simulated pod result saved yet.");
  const summary = result.summary || result;
  const counted = summary.counted;
  const sides = result.sides || answer.sides || result.decks || [];
  const byDeck = summary.by_deck;
  const rows = Array.isArray(byDeck) ? byDeck : byDeck && typeof byDeck === "object"
    ? sides.map(side => ({ ...byDeck[side.id], ...side })) : result.decks || [];
  const section = el("section", { class: "box fp-results", "aria-labelledby": "fp-results-heading" },
    el("h2", { id: "fp-results-heading", text: "Pod win shares" }),
    el("p", { class: "sub", text: "Forge simulation · 4-player Commander · Default AI" }),
    el("p", { class: "note", text: "Use the results to compare the decks in this pod. Individual games cannot be replayed exactly." }));
  const planned = result.planned ?? result.games, completed = result.completed ?? summary.pods;
  if (Number.isInteger(planned) && planned > 0 && Number.isInteger(completed) && completed >= 0) {
    const remaining = Number.isInteger(result.remaining) ? result.remaining : Math.max(0, planned - completed);
    section.append(el("p", { class: "fp-completion", text: `${thousands(completed)} of ${thousands(planned)} planned pod games completed; ${thousands(remaining)} remain.` }));
  }
  if (["stopped", "failed", "error", "interrupted"].includes(result.state)) {
    section.append(el("p", { class: "note", text: result.state === "stopped" ? "This run was stopped. Completed games are kept."
      : "This run did not finish. Completed games are kept; its remaining games have no result." }));
  }
  if (!Number.isInteger(counted) || counted < 0 || rows.length !== 4) {
    section.append(el("p", { text: "This saved result does not have complete win-share statistics." }));
    return section;
  }
  section.append(el("p", { text: `${thousands(counted)} counted pod games. Equal shares would be 25% per deck. The 95% Wilson ranges describe sampling uncertainty.` }),
    el("ul", { class: "fp-shares" }, rows.map((row, index) => {
      const side = sides.find(deck => deck.id === row.id) || sides[index] || row;
      const rate = row.rate, range = row.range;
      const validRate = fpFinite(rate) && rate >= 0 && rate <= 1;
      const validRange = Array.isArray(range) && range.length === 2 && range.every(fpFinite) &&
        range[0] >= 0 && range[0] <= range[1] && range[1] <= 1;
      const known = validRate && validRange && counted > 0;
      const source = fpPreconSource(side);
      const list = side.version === "target" || side.version === "owned" ? listName(side.version) : "List version unavailable";
      const reference = FP_KEY.test(side.card_sha || "") ? `List ID ${side.card_sha.slice(0, 8)}` : null;
      return el("li", { class: "fp-share" },
        el("h3", { text: side.title || row.title || `Deck ${index + 1}` }),
        el("p", { class: "sub" }, source || list, reference ? ` · ${reference}` : null),
        winRateFigure(known ? { value: rate, low: range[0], high: range[1] } : null,
          { size: "hero", what: "Pod win share" }),
        el("p", { class: "sub", text: Number.isInteger(row.wins) && row.wins >= 0
          ? `${plural(row.wins, "win")} in ${thousands(counted)} counted pods` : "Wins not recorded" }));
    })), el("p", { class: "sub", text: metaWords(
      Number.isInteger(summary.draws) ? `${plural(summary.draws, "draw")} recorded` : null,
      Number.isInteger(summary.clock_stops) ? `${plural(summary.clock_stops, "clock stop")} excluded` : null,
      Number.isInteger(summary.failed_batches) ? `${plural(summary.failed_batches, "failed batch", "failed batches")}` : null) }));
  if (answer.lineup || result.lineup) add(section, [fpSeatBreakdown(sides[0], byDeck?.[sides[0]?.id]?.by_seat)]);
  if (result.note) section.append(el("p", { class: "sub", text: result.note }));
  return section;
}

function fpHistoryPart(answer) {
  const results = (answer.results || []).filter(result => FP_KEY.test(result.key || ""));
  if (!results.length) return null;
  return el("section", { class: "fp-history-list", "aria-labelledby": "fp-history-heading" },
    el("h2", { id: "fp-history-heading", text: "Saved pod runs" }),
    el("ul", { class: "mu-list" }, results.map(result => el("li", {},
      el("a", { class: "mu-row", href: fpHref(result.key) },
        rowNames({ title: (result.sides || result.decks || []).map(deck => deck.title).filter(Boolean).join(" · ") || "Four-player pod" }, null, false),
        el("span", { class: "sub", text: `${thousands(result.summary?.counted || 0)} counted pod games` }))))));
}
