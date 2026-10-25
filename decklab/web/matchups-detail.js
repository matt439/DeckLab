/* One matchup, the pair page: its verdict (matchups-results.js), starting a run, live progress and stopping it,
and the pair's earlier results. Loaded after matchups.js and matchups-overview.js and before matchups-results.js
and matchups-cards.js. The classic scripts share helpers; resultPart is called only once the page is running. */
"use strict";

// ------------------------------------------------------------ one matchup

// A matchup page that can't be drawn: its error, and the way back to Matchups (asking again can't help
// with a bad address or a matchup that isn't there, so errorBox leaves "Try again" out for those).
const MATCHUP_ERROR = { title: "This matchup couldn't be opened", back: ["#/matchups", "Back to Matchups"] };

function showMatchup(params, token) {
  const q = new URLSearchParams();
  // asked: the two decks when the page was opened by them (Stop then answers from deck a's side too).
  let asked = null;
  if (params.get("key")) {
    // A key is 64 hex digits: anything else is a link copied wrong, so say so in plain words.
    if (!/^[0-9a-f]{64}$/i.test(params.get("key"))) {
      clear($("#main")).append(errorBox(MATCHUP_ERROR.title,
        new ApiError(0, "That link isn't a matchup's address: part of it may be missing."), null, MATCHUP_ERROR.back));
      afterRender();
      return;
    }
    q.set("key", params.get("key").toLowerCase());
  } else {
    asked = { a: addressDeckId(params.get("a")), av: params.get("av") === "owned" ? "owned" : "target",
      b: addressDeckId(params.get("b")), bv: params.get("bv") === "owned" ? "owned" : "target" };
    for (const [name, value] of Object.entries(asked)) q.set(name, value);
  }
  q.set("profile", state.profile.id);
  // The card names this page links to the viewer are its two decks' (loadPairExtras), never the last deck
  // page's left over.
  state.cards = new Map();
  // live: the progress box while a run is waiting or going; updates: the route's refresh control; history:
  // every saved result of the pair (from /api/matchups, read once), null until it's known; starting: a Play
  // pressed whose answer hasn't come (the page isn't drawn again under it); redrawLater: a redraw held back.
  const page = { token, url: `/api/matchup?${q}`, asked, data: null, live: null, updates: null, history: null,
    starting: false, redrawLater: false, refreshStatus: matchupRefreshStatus() };
  load(page.url, token, (data) => { drawMatchup(page, data); follow(page); loadPairExtras(page); }, MATCHUP_ERROR);
}

/** What the page reads once after its first answer, then draws itself again with: the pair's other saved
 * results (MU-m1, from /api/matchups) and its two decks' cards (from /api/deck: their lists today), so the card
 * names in its tables open the card viewer, a swipe going through each table. A deck that can't be read leaves
 * its names as plain text. */
async function loadPairExtras(page) {
  const sides = (page.data && page.data.sides) || [];
  const history = api("/api/matchups").then((answer) => answer.results || [], () => []);
  const decks = Promise.all(sides.map((side) => side.id
    ? api(`/api/deck?id=${encodeURIComponent(side.id)}&version=${side.version || "target"}`).catch(() => null)
    : null));
  const [results, answers] = await Promise.all([history, decks]);
  if (page.token !== routeToken) return;
  page.history = results;
  const cards = new Map();
  for (const answer of answers) {
    for (const lines of Object.values((answer && answer.sections) || {})) {
      for (const line of lines) {
        if (line.card && !cards.has(line.card.name)) cards.set(line.card.name, line.card);
      }
    }
  }
  state.cards = cards;
  redrawMatchup(page);
}

/** Draw the page again for its last answer, where the reader is: not while a run's live box is showing (it
 * updates in place), nor while a Play is being sent (its button and error would be replaced: the redraw waits
 * for the answer). */
function redrawMatchup(page) {
  if (!page.data || (isLive(page.data) && page.live && page.live.node.isConnected)) return;
  if (page.starting) { page.redrawLater = true; return; }
  page.redrawLater = false;
  const y = window.scrollY;
  replaceMatchupContent($("#main"), () => drawMatchup(page, page.data));
  window.scrollTo(0, y);
}

/** The pair's saved results other than the one shown (any lists, versions or engine), newest first; null
 * until they're known. */
function pairHistory(page, data) {
  if (!page.history) return null;
  const [a, b] = data.sides;
  const key = pairKey(a.id, b.id);
  return page.history.filter((item) => item.key !== data.key && item.format === data.format && item.sides
    && pairKey(item.sides[0].id, item.sides[1].id) === key);
}

/** Draw the whole matchup page for this answer (follow() keeps up with a run that's going). */
function drawMatchup(page, data) {
  page.data = data;
  page.live = null;
  const main = clear($("#main"));
  const [a, b] = data.sides;
  setTitle(`${a.title} vs ${b.title}`);
  const commander = data.format === "Commander";
  const r = data.result;
  const history = pairHistory(page, data);
  // A newer result of the same two lists (today's engine): this one's an earlier engine's.
  const shas = [a.card_sha, b.card_sha].sort().join("|");
  const newer = r && earlierEngine(r) && history
    ? history.find((item) => !earlierEngine(item) && item.sides.map((s) => s.card_sha).sort().join("|") === shas) || null
    : null;
  // "Earlier engine" only while it's the exception: today's engine has results elsewhere, none of this pair.
  const tags = [];
  if (r && earlierEngine(r) && history && anyTodaysEngine(page.history) && !history.some((item) => !earlierEngine(item))) {
    tags.push(status("plain", "Earlier engine"));
  }
  add(main, [
    crumb("#/matchups", routeFor("matchups").label),
    el("header", { class: "mu-head" },
      el("h1", {}, sideTitle(a), el("span", { class: "mu-vs-word", text: " vs " }), sideTitle(b)),
      el("p", { class: "mu-meta-line" }, el("span", { text: metaWords(commander ? "Commander, 1v1, 40 life" : "60-card, 1v1, 20 life",
        r ? gamesWords(r.games) : null, r && r.forge_version ? `Forge ${r.forge_version}` : null) }), tags)),
    page.refreshStatus.node,
    forgeBox(data.forge),
    data.error ? markedBox("crit", "h2", "The last run didn't work", el("p", { text: data.error }),
      { id: "mu-error", role: "alert" }) : null,
    noticeBox(data)]);
  // With no result yet, the run (Play, or the live box of a run going) takes the result's place in the body,
  // so from 1,600 px the decks sit beside it; with one, a run's live box goes above the result.
  let run = null;
  if (isLive(data)) {
    page.live = liveBox(page);
    page.live.update(data);
    if (r) {
      add(main, [page.live.node,
        note("The result below is what was saved before this run. It's updated when the run ends.")]);
    } else {
      run = page.live.node;
    }
  } else if (!r) {
    run = [neverCastBox(data.sides), playBox(page, history)];
  }
  // One layout for the result: the verdict, its folded reading and the earlier results in one column; the two
  // decks beside them from 1,600 px (under the verdict before that), the page capped at a readable width.
  main.append(el("div", { class: "mu-pair-body" },
    run ? el("div", { class: "mu-pair-run" }, run) : null,
    r ? resultPart(data, page, { newer }) : null,
    el("section", { class: "mu-decks", "aria-label": "The two decks" },
      el("div", { class: "mu-sides" }, data.sides.map((s, i) => sideBox(s, i)))),
    r ? earlierResults(history, data) : null));
}

/** The pair's other results, folded (MU-m1: a pair page never hides them). null when there are none. */
function earlierResults(history, data, open = false) {
  if (!history || !history.length) return null;
  const first = data.sides[0].id;
  return el("details", { class: "more mu-earlier-results", open: open || null },
    el("summary", { text: `Earlier results of these decks (${history.length})` }),
    el("ul", { class: "mu-list" }, history.map((item) => resultRow(item, { deckId: first }))));
}

function sideBox(side, i) {
  const words = metaWords(SIDE_KIND_WORDS[side.kind] || "", side.version === "owned" ? listName("owned", true)
    : side.kind === "casual" || side.kind === "commander" ? listName("target", true) : "", side.card_count ? `${side.card_count} cards` : "");
  const chips = aiChips(side.ai, side.current === false);
  return el("div", { class: "mu-side" },
    el("span", { class: "mu-side-label", text: `Deck ${i + 1}` }),
    el("a", { class: "mu-side-title", href: deckHref(side.id, side.version), text: side.title }),
    words ? el("span", { class: "sub", text: capitalise(words) }) : null,
    chips.length ? el("span", { class: "chips" }, chips) : null,
    pilotNote(side),
    autoProfileNote(side));
}

/** The AI pilot a deck was played with when it isn't Forge's Default profile (side.pilot.words, wave 3: e.g.
 * "Forge's AI plays it with the Reckless profile and the team-pump fix"); null for the default pilot. */
function pilotNote(side) {
  const words = side.pilot && side.pilot.words;
  return words ? el("span", { class: "sub mu-pilot", text: `${words}.` }) : null;
}

/** A deck Forge's AI played with its auto-profile on (side.auto_profile, and it changes how the AI plays it):
 * say so; null when it's off or not known (plain Forge doesn't say, nor did runs before wave 2). Forge's rule
 * is an average mana value over 3 that counts each different nonland card once and rounds down, so 4 or more
 * (cli.AUTO_PROFILE_WHY). */
function autoProfileNote(side) {
  if (side.auto_profile !== true) return null;
  return el("span", { class: "sub mu-auto-profile", text: `${AUTO_PROFILE_WORDS}: Forge does that for a deck ` +
    "whose nonland cards average 4 mana or more (counting each different card once and rounding down)." });
}

/** Not played with today's engine yet, but played with an earlier one (data.earlier, newest first): links
 * to those results, which more games won't add to; null when there are none. The play box shows it until the
 * pair's other results are known (pairHistory). */
function earlierBox(data) {
  const keys = data.earlier || [];
  if (!keys.length) return null;
  const links = keys.length === 1 ? el("a", { href: keyHref(keys[0]), text: "see that result" })
    : ["see results ", keys.map((key, n) => [n ? ", " : null,
      el("a", { href: keyHref(key), text: String(n + 1), "aria-label": `earlier result ${n + 1}` })])];
  return el("p", { class: "sub mu-earlier" },
    `These two lists were played with ${keys.length === 1 ? "an earlier engine" : "earlier engines"} (`, links,
    "); games played now go into a new result with today's engine.");
}

/** Before any game: a deck whose commander Forge's AI never casts makes the results mean nothing, so
 * say so before Play; null otherwise. */
function neverCastBox(sides) {
  const which = sides.filter((s) => s.ai && s.ai.commander_unplayable).map((s) => s.title);
  if (!which.length) return null;
  return markedBox("crit", "h2", "These games would mean nothing",
    el("p", { text: `Forge's AI never casts the commander of ${which.join(" and ")}, so that deck would play ` +
      "every game without it. They can still be played, but the result says nothing about the real decks." }));
}

/** The last run's notice (stopped, or batches that failed); null when there's none. The server's
 * notice about a stopped run always starts "Stopped" (a run stopped while it was still waiting, or
 * before any game finished, leaves no saved run to tell by). */
function noticeBox(data) {
  if (!data.notice) return null;
  const stopped = data.notice.startsWith("Stopped");
  return markedBox(stopped ? "info" : "warn", "h2", stopped ? "The last run was stopped" : "Part of the last run failed",
    el("p", { text: data.notice }), { id: "mu-notice", role: "status" });
}

/** Not played yet (or failed): how long to play and Play. history: the pair's other results (null until
 * known): with any, the heading says these lists haven't played yet, and lists them (MU-m1). */
function playBox(page, history) {
  const data = page.data;
  const ready = !data.forge || data.forge.ready !== false;
  const choice = runModeChoice(data);
  const error = el("p", { class: "form-error", role: "alert", "data-play-error": true });
  const button = el("button", { type: "button", class: "btn btn-primary", disabled: !ready, "data-run": true,
    text: "Play", onclick: () => play(page, choice.value(), button, error) });
  const older = history ? history.length > 0 : (data.earlier || []).length > 0;
  choice.node.hidden = !runsAllowed();      // the disabled Play says why (syncRunControls)
  return el("section", { class: "panel mu-play", "aria-labelledby": "h-not-played" },
    el("h2", { id: "h-not-played", text: older ? "Not played with the current lists yet"
      : "These two decks haven't played each other yet" }),
    older && history ? earlierResults(history, data, true) : history ? null : earlierBox(data),
    el("p", { class: "sub", text: "Forge plays the games on the PC, the decks taking turns to go first. You can " +
      "leave this page meanwhile: the games go on, and the result is saved." }),
    choice.node,
    el("div", { class: "actions" }, button),
    ready ? null : el("p", { class: "sub", text: "Forge isn't ready on the PC, so games can't be played now." }),
    error);
}

/** Start a run: choice is runModeChoice's {mode, games}, or a number of games (a set number). When the
 * answer says it joined a run already waiting or playing (another mode, perhaps), a toast says so. */
async function play(page, choice, button, error) {
  const [a, b] = page.data.sides;
  const asked = typeof choice === "number" ? { mode: "fixed", games: choice } : choice;
  const body = { a: a.id, av: a.version, b: b.id, bv: b.version, mode: asked.mode };
  if (asked.mode === "fixed") body.games = asked.games;
  if (page.starting) return;           // one start at a time
  error.textContent = "";
  page.starting = true;
  busy(button, "Starting...");
  page.updates?.hold();
  try {
    const answer = await apiWrite("/api/matchup/run", body);
    page.starting = false;
    page.redrawLater = false;           // apply() draws the page afresh
    if (page.token !== routeToken) return;
    if (answer.joined) {
      const until = MODE_UNTIL[answer.joined.mode];
      toast(`Joined the run already playing${until ? ` (${until})` : ""}` +
        `${answer.joined.by ? `, started by ${answer.joined.by}` : ""}.`);
    }
    followKey(page, answer.key);
    apply(page, answer);
    if (typeof syncRunsPill === "function") syncRunsPill(true);     // runs-pill.js: the top bar's run activity shows it now
  } catch (e) {
    page.starting = false;
    if (page.token !== routeToken) return;
    const words = e.message + (e.status ? ` (error ${e.status})` : "");
    if (page.redrawLater) {
      // What came in meanwhile (earlier results, the cards) is drawn now, and the error goes in the new box.
      redrawMatchup(page);
      const fresh = $("#main [data-play-error]");
      if (fresh) fresh.textContent = words;
      return;
    }
    unbusy(button);
    error.textContent = words;
  } finally {
    page.updates?.release();
  }
}

/** After a run's answer: when it names another key than the page's (more games of a result of an earlier
 * engine start a new result, today's), the page follows that key from now on: its reads, Stop (by the key
 * alone) and its address (without a new history entry). The old watcher stops; apply() starts one for the
 * new address (play()'s release then finds that one not held, which does nothing). */
function followKey(page, key) {
  if (!key || (page.data && page.data.key === key)) return;
  page.url = `/api/matchup?${new URLSearchParams({ key, profile: state.profile.id })}`;
  page.asked = null;
  if (page.updates) {
    page.updates.stop();
    page.updates = null;
  }
  history.replaceState(history.state, "", keyHref(key));
}

/** Show a new answer (a run started or stopped), and keep following it. */
function apply(page, data) {
  if (page.token !== routeToken) return;
  show(page, data);
  follow(page);
}

/** In place while the run goes on; else the page afresh, where the reader is. When the focus was on
 * the page drawn over (Stop, Play) or nowhere, it goes to what's new (focusNews). */
function show(page, data) {
  if (isLive(data) && page.live && page.live.node.isConnected) {
    page.data = data;
    page.live.update(data);
    return;
  }
  const focused = document.activeElement;
  const lost = !focused || focused === document.body || $("#main").contains(focused);
  const y = window.scrollY;
  const keptFocus = replaceMatchupContent($("#main"), () => drawMatchup(page, data));
  window.scrollTo(0, y);
  if (lost && !keptFocus) focusNews();
}

/** Give the focus to the first of NEWS_IDS on the page (the notice of a stopped run, the result...),
 * without scrolling, so a keyboard or screen reader user goes on from there and hears it. */
function focusNews() {
  const target = NEWS_IDS.map((id) => document.getElementById(id)).find(Boolean);
  if (!target) return;
  target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}

/** Follow this matchup at full speed while playing and gently while idle, including runs started
 * from another device. Unchanged idle answers preserve the games choice and expanded result details. */
function follow(page) {
  if (page.updates || page.token !== routeToken) return;
  page.updates = watchMatchupUpdates({ token: page.token, host: () => $("#main"), url: page.url,
    active: () => isLive(page.data), interval: POLL_MS, view: page.refreshStatus,
    onFresh(answer) {
      if (JSON.stringify(answer) !== JSON.stringify(page.data)) show(page, answer);
    },
    onLost(error) { if (page.live) page.live.lost(error); },
  });
}

/** The box of a run that's waiting or going: progress (marked at the planned checks, MU-11), the score so far,
 * speed, time left and Stop. */
function liveBox(page) {
  const title = el("h2", { id: "h-live", text: "Getting ready..." });
  const bar = checkBar("Games played");
  const played = el("p", { class: "mu-played", role: "status" });
  const score = el("dl", { class: "mu-score" });
  const pace = el("p", { class: "sub" });
  const lost = el("p", { class: "sub mu-lost" });
  const stop = el("button", { type: "button", class: "btn btn-danger", text: "Stop",
    onclick: () => stopRun(page, stop) });
  // An adaptive run's plan ("Next check at 800 games") and every run's live range, dashed: the anytime-valid range,
  // which holds whenever the run is looked at, so it's wider than the result's.
  const planLine = el("p", { class: "mu-plan" });
  const rangeHost = el("div", { class: "mu-live-range" });
  // A field run or a variant test playing this matchup: a link to it in place of Stop (job.via).
  const via = el("p", { class: "mu-via" });
  const actions = el("div", { class: "actions", hidden: true }, stop);
  const node = el("section", { class: "box box-info mu-running", "aria-labelledby": "h-live" },
    el("div", { class: "mu-running-head" }, el("span", { class: "spinner", "aria-hidden": "true" }), title),
    bar.node, played, planLine, rangeHost, score, pace, lost,
    actions, via,
    el("p", { class: "sub", text: "You can leave this page: the games go on on the PC, and the result is saved." }));
  return {
    node,
    update(data) {
      lost.textContent = "";
      const job = data.job || {};
      const [ta, tb] = sideTitles(data.sides);
      const plan = job.plan || null;
      if (job.via) {
        actions.hidden = true;
        clear(via).append(`Part of a ${lowerFirst(job.via.title || "run of many matchups")}: `,
          el("a", { href: job.via.link || "#/matchups", text: "open it to stop or follow it" }), ".");
        via.hidden = false;
      } else {
        actions.hidden = !mayStopRuns(job);
        via.hidden = true;
      }
      if (plan && plan.mode === "ahead" && plan.next_look) {
        planLine.textContent = `Next check at ${thousands(plan.next_look)} games (at most ${thousands(plan.max || 3200)}).`;
      } else if (plan && plan.mode === "assess") {
        planLine.textContent = (plan.planned || 0) <= 400 && plan.stage === 1
          ? "First 400 games, then as many as needed to know the win rate to within 3 points either way."
          : `Planned: ${thousands(plan.planned || 0)} games, to know the win rate to within 3 points either way.`;
      } else {
        planLine.textContent = "";
      }
      planLine.hidden = !planLine.textContent;
      if (job.range && job.range.value != null && job.status !== "queued") {
        clear(rangeHost).append(rangeBar(job.range, { live: true,
          label: `${ta}'s live range: ${pct(job.range.low)} to ${pct(job.range.high)}` }),
        el("p", { class: "sub", text: `Live range: wider while games are still being played. ${ta}: ` +
          `${pct(job.range.low)}-${pct(job.range.high)}.` }));
        rangeHost.hidden = false;
      } else {
        clear(rangeHost);
        rangeHost.hidden = true;
      }
      const progress = runProgress(job);
      if (job.status === "queued") {
        const n = job.ahead || 0;
        title.textContent = n > 0 ? "Waiting for another matchup" : "Starting...";
        played.textContent = n > 0 ? `${plural(n, "other run")} ${n === 1 ? "is" : "are"} ahead of this one; ` +
          `it starts as soon as ${n === 1 ? "that's" : "they're"} done.`
          : job.plan || job.mode === "assess" || job.mode === "ahead" ? "The games are about to start."
            : `${thousands(job.total || 0)} games are about to start.`;
        bar.set(0, 1);
        clear(score);
        pace.textContent = job.by ? `Asked for by ${job.by}.` : "";
        return;
      }
      if (plan) {
        const before = plan.games_before || 0;
        title.textContent = plan.mode === "ahead" ? "Settle it: playing until one deck is clearly ahead..."
          : "Precise: playing until the win rate is known to within 3 points...";
        played.textContent = job.waiting || `${thousands(before + (job.done || 0))} of up to ` +
          `${thousands(plan.max || 3200)} games` + (before ? ` (${thousands(before)} from before).` : ".");
      } else {
        title.textContent = `Playing ${thousands(job.total || 0)} games...`;
        // job.waiting: none of its Forge processes can play yet, as other runs on the PC hold every slot.
        played.textContent = job.waiting || `${thousands(job.done || 0)} of ${thousands(job.total || 0)} games played.`;
      }
      bar.set(progress.done, progress.total, progress.checks);
      const wins = job.wins || [0, 0];
      const cells = [[ta, wins[0]], [tb, wins[1]]];
      if (job.other) cells.push(["Draws and timeouts", job.other]);
      clear(score).append(...cells.map(([label, n]) => el("div", {}, el("dt", { text: label }),
        el("dd", { text: thousands(n) }))));
      const bits = [];
      if (job.games_per_min != null) bits.push(`${thousands(Math.round(job.games_per_min))} games a minute`);
      // The time left comes from the pace so far, which includes Forge starting up and warming up: until a
      // tenth of the games are played it's far too long (39 minutes for a 3-minute run), so it waits. An
      // adaptive run's time left is its current stage's: the stages after it depend on what the next check finds.
      if (job.eta_s != null && job.total && job.done >= job.total / 10) {
        bits.push(`about ${durationWords(job.eta_s)} left${job.plan ? " in this stage" : ""}`);
      }
      if (job.by) bits.push(`started by ${job.by}${job.seconds != null ? ` ${durationWords(job.seconds)} ago` : ""}`);
      pace.textContent = capitalise(bits.join(", ")) + (bits.length ? "." : "");
    },
    lost(error) {
      lost.textContent = `The PC isn't answering (${error.message}). Trying again...`;
    },
  };
}

async function stopRun(page, button) {
  if (!mayStopRuns(page.data?.job)) return;
  const profile = state.profile?.id;
  const data = page.data;
  const job = data.job || {};
  const queued = job.status === "queued";
  const choice = await ask("Stop this matchup?", [
    queued ? "It hasn't started yet, so nothing is lost: it just leaves the queue."
      : "Every game finished so far is kept and saved with the result. The games still being played are " +
        "dropped, and the rest aren't played.",
    !queued && job.plan ? "Stopped early, the result shows the games played so far, judged as a run stopped " +
      "between its checks." : "",
    job.by && state.profile && job.by !== state.profile.name ? `${job.by} started it.` : ""].filter(Boolean),
  [{ value: "stop", text: "Stop it", kind: "danger" }, { value: "keep", text: "Keep playing", kind: "primary" }]);
  if (page.token !== routeToken || state.profile?.id !== profile) return;
  // The run may have ended while the question was up, and the page been drawn afresh without Stop.
  if (!button.isConnected) focusNews();
  if (choice !== "stop" || !isLive(page.data) || !mayStopRuns(page.data.job)) return;
  busy(button, "Stopping...");
  page.updates?.hold();
  try {
    const answer = await apiWrite("/api/matchup/stop", { key: page.data.key, ...(page.asked || {}) });
    if (page.token !== routeToken || state.profile?.id !== profile) return;
    apply(page, answer);
  } catch (e) {
    if (page.token !== routeToken || state.profile?.id !== profile) return;
    unbusy(button);
    toast(`It couldn't be stopped: ${e.message}`);
  } finally {
    page.updates?.release();
  }
}
