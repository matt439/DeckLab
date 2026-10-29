/* The Matchups home (one deck's opponents in a lab table or casual cards), the play sheet, the rows every matchup list shares, the deck page's Matchups results (deckResultParts) and the updates across
devices. Loaded after matchups.js and before the detail, result and card-stat scripts. Shares matchups.js's
constants and helpers; the refresh loop serves both matchup routes and the deck page. Functions run only after
all deferred scripts have loaded. */
"use strict";

const MATRIX_FORMATS = [["Constructed", "60-card"], ["Commander", "Commander"]];
const HOME_FORMAT_KEY = "matchups.format";      // local storage: the format the Matchups home shows
const HOME_VIEW_KEY = "matchups.view";        // ... matrix/phone matchups or saved field rankings
const HOME_DECK_KEY = "matchups.deck";          // ... and the deck its phone list shows


// ------------------------------------------------------ updates across devices

/** Called by routing before leaving a page (including switching profiles). */
function stopMatchupRefresh() {
  if (matchupRefresh) matchupRefresh.stop();
}

/** Only a lost connection is shown (MU-13: no "Last checked" line or Refresh button, as the pages ask again by
 * themselves): a banner that says so, and says when it's back. Frequent successful checks aren't announced. */
function matchupRefreshStatus() {
  const problem = el("p", { class: "mu-refresh-error", role: "status" });
  let failed = false;
  return {
    node: el("div", { class: "mu-refresh" }, problem),
    busy() {},
    fresh() {
      problem.textContent = failed ? "Connected again. Matchups are up to date." : "";
      failed = false;
    },
    lost(error) {
      failed = true;
      problem.textContent = `Matchup updates aren't available. Trying again automatically. ${error.message}`;
    },
  };
}

/** One request at a time, while visible. Idle pages still discover other devices' runs. Focus,
 * reconnecting and Safari's page restoration check immediately; leaving cancels reads and listeners.
 * Hold around writes so a read begun before Start/Stop cannot replace that write's newer answer. */
function watchMatchupUpdates({ token, host, url, active, interval = POLL_MS * LIST_POLL, view, onFresh, onLost, onPause = null }) {
  stopMatchupRefresh();
  let timer = null, request = null, failures = 0, stopped = false, held = 0, hidden = false, wakeAfterAbort = false;
  const present = () => !stopped && token === routeToken && host().isConnected;
  const visible = () => !hidden && document.visibilityState !== "hidden";
  const cancelTimer = () => { clearTimeout(timer); timer = null; };
  const cancelRequest = () => { if (request) request.abort(); };
  function schedule() {
    cancelTimer();
    if (!present()) { stop(); return; }
    if (!visible() || held || request) return;
    const base = active() ? interval : IDLE_MATCHUP_POLL_MS;
    timer = setTimeout(refresh, Math.min(30000, base * Math.min(MAX_BACKOFF, failures + 1)));
  }
  async function refresh() {
    cancelTimer();
    if (!present()) { stop(); return; }
    if (!visible() || held) return;
    if (request) { wakeAfterAbort ||= request.signal.aborted; return; }
    const controller = new AbortController();
    request = controller;
    view.busy(true);
    let timedOut = false;
    const deadline = setTimeout(() => { timedOut = true; controller.abort(); }, 12000);
    try {
      const answer = await api(url, { signal: controller.signal });
      if (!present() || controller.signal.aborted || held) return;
      await onFresh(answer, { signal: controller.signal });
      if (!present() || controller.signal.aborted || held) return;
      failures = 0;
      view.fresh();
    } catch (error) {
      if (!present() || (controller.signal.aborted && !timedOut) || held) return;
      failures += 1;
      const failure = timedOut ? new Error("The PC took too long to answer. Check the home-network connection.") : error;
      view.lost(failure);
      if (onLost) onLost(failure);
    } finally {
      clearTimeout(deadline);
      if (request === controller) request = null;
      view.busy(false);
      if (wakeAfterAbort) { wakeAfterAbort = false; refresh(); }
      else schedule();
    }
  }
  function wake() { if (visible()) refresh(); }
  function visibility() {
    if (!visible()) { cancelTimer(); cancelRequest(); if (onPause) onPause(); }
    else wake();
  }
  function hide() { hidden = true; cancelTimer(); cancelRequest(); if (onPause) onPause(); }
  function restore() { hidden = false; wake(); }
  function stop() {
    stopped = true;
    if (onPause) onPause();
    cancelTimer();
    cancelRequest();
    document.removeEventListener("visibilitychange", visibility);
    window.removeEventListener("focus", wake);
    window.removeEventListener("online", wake);
    window.removeEventListener("pagehide", hide);
    window.removeEventListener("pageshow", restore);
    if (matchupRefresh === control) matchupRefresh = null;
  }
  const control = {
    stop, refresh,
    hold() { held += 1; cancelTimer(); cancelRequest(); },
    release() { held = Math.max(0, held - 1); schedule(); },
  };
  document.addEventListener("visibilitychange", visibility);
  window.addEventListener("focus", wake);
  window.addEventListener("online", wake);
  window.addEventListener("pagehide", hide);
  window.addEventListener("pageshow", restore);
  matchupRefresh = control;
  // A deck section is constructed just before it is attached to the page.
  timer = setTimeout(schedule, 0);
  return control;
}

/** Refreshing a list must keep keyboard focus and any expanded statistics in place. */
function replaceMatchupContent(host, draw) {
  const label = (node) => `${node.tagName}|${node.getAttribute("href") || ""}|${node.textContent}`;
  const focused = document.activeElement;
  const inside = focused && host.contains(focused);
  const key = inside ? label(focused) : null;
  const opened = new Set([...host.querySelectorAll("details[open]")].map((node) => node.querySelector("summary")?.textContent));
  draw();
  for (const detail of host.querySelectorAll("details")) {
    if (opened.has(detail.querySelector("summary")?.textContent)) detail.open = true;
  }
  if (inside) {
    const next = [...host.querySelectorAll("a, button, select, summary, [tabindex]")].find((node) => label(node) === key);
    const target = next || host.querySelector("h2, h3") || host;
    if (!next) target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
    return !!next;
  }
  return false;
}


// ---------------------------------------------------------------- pairs

/** The pair a result is of, whatever its lists, versions or order: its two decks (a pairing's halves in
 * either order are one deck). */
function pairKey(idA, idB) { return [sameDeckId(idA), sameDeckId(idB)].sort().join("|"); }

/** How well a result stands for its pair (the matrix's decks are their planned lists): both planned lists
 * first, then today's lists with today's engine, then today's lists. */
function resultRank(item) {
  const current = item.sides.every((s) => s.current !== false);
  const planned = item.sides.every((s) => (s.version || "target") === "target");
  return (planned ? 4 : 0) + (current ? 2 : 0) + (current && !earlierEngine(item) ? 1 : 0);
}

/** Whether any result was played with today's engine: until one is, "Earlier engine" is the normal case, so
 * rows carry no tag for it and one line above the list says so instead (allEarlierLine). */
function anyTodaysEngine(results) { return (results || []).some((item) => !earlierEngine(item)); }

const ENGINE_NOTE_KEY = "matchups.engineNoteSeen";

/** Whether this viewer has dismissed the note about results played with an earlier engine (on this device). */
function engineNoteDismissed() { return local.get(ENGINE_NOTE_KEY) === "1"; }

/** The note above a list of results that were all played with an earlier engine, said once: it has "Got it",
 * after which it isn't shown again on this device (the matrix, the deck pages and the pair pages). null when
 * any result is today's engine's, or once dismissed. */
function allEarlierLine(results) {
  if (!(results || []).length || anyTodaysEngine(results) || engineNoteDismissed()) return null;
  const node = el("div", { class: "note mu-all-earlier", role: "note" },
    el("p", { text: "Every result here was played with an earlier version of Forge's engine. Playing a matchup " +
      "again starts a new result with today's." }),
    el("button", { type: "button", class: "btn btn-quiet btn-inline", text: "Got it", onclick: () => {
      local.set(ENGINE_NOTE_KEY, "1");
      node.remove();
    } }));
  return node;
}

/** Results that mean nothing (a commander never cast) go last, then best first: [{value, muted}]. */
function byBestFirst(x, y) {
  return (x.muted - y.muted) || ((y.value ?? -1) - (x.value ?? -1));
}

/** One entry per pair (MU-01): Map pairKey -> {latest, earlier: [the pair's other results, newest first],
 * newer: whether a result of today's engine exists}, from results newest first. latest is the pair's best
 * result (resultRank), the newest of those. */
function pairsOf(results) {
  const pairs = new Map();
  for (const item of results || []) {
    if (!item.sides || item.sides.length !== 2) continue;
    const key = `${item.format}|${pairKey(item.sides[0].id, item.sides[1].id)}`;
    const pair = pairs.get(key) || { latest: null, all: [] };
    pair.all.push(item);
    if (!pair.latest || resultRank(item) > resultRank(pair.latest)) pair.latest = item;
    pairs.set(key, pair);
  }
  for (const pair of pairs.values()) {
    pair.earlier = pair.all.filter((item) => item !== pair.latest);
    pair.newer = pair.all.some((item) => !earlierEngine(item));
  }
  return pairs;
}

/** A result from one deck's side: {item, me, them, rate, href}. rate is that deck's win rate (the other side's
 * is 1 - the first's, which differs only by the rare draws and timeouts); href opens the pair from its side
 * when the page can (today's lists and engine), else the result by its key. */
function fromSide(item, deckId) {
  const [a, b] = item.sides;
  const flip = sameDeckId(a.id) !== sameDeckId(deckId) && sameDeckId(b.id) === sameDeckId(deckId);
  const me = flip ? b : a, them = flip ? a : b;
  const w = item.winrate || {};
  const rate = !flip ? w : { value: w.value == null ? null : 1 - w.value, low: w.high == null ? null : 1 - w.high,
    high: w.low == null ? null : 1 - w.low };
  const href = flip && itemHref(item) === matchupHref(a, b) ? matchupHref(b, a) : itemHref(item);
  return { item, me, them, rate, href };
}

/** A win rate's edge in a word or two, from that deck's side: "Big favourite", "Underdog", "About even". */
function edgeWords(value) {
  if (value == null) return null;
  if (value >= 0.8) return "Big favourite";
  if (value >= 0.6) return "Favourite";
  if (value > 0.55) return "Slight edge";
  if (value >= 0.45) return "About even";
  if (value > 0.4) return "Slight underdog";
  if (value > 0.2) return "Underdog";
  return "Big underdog";
}


// ------------------------------------------------------------------- rows

/** A row's names: "Boros Burn vs Dimir Control", or "vs Dimir Control" on the first deck's own page
 * (against); with no b, a's title alone (a field run's or a variant test's row, jobRow). */
function rowNames(a, b, against) {
  return against
    ? el("span", { class: "mu-names" }, el("span", { class: "mu-vs-word", text: "vs " }), sideTitle(b))
    : el("span", { class: "mu-names" }, el("span", { class: "mu-first", text: sideTitle(a) }),
      b ? [el("span", { class: "mu-vs-word", text: " vs " }), sideTitle(b)] : null);
}

/** A saved result as a row: both decks (or "vs the opponent" from a deck's side: against), its compact range
 * bar and inline win-rate figure (sim-ui.js), and one line: the edge in words, games, who (a person only) and how
 * long ago (a freshness badge, plain words while it's fresh). Tags only for what's worth noticing: results that
 * mean nothing, a list that has changed since (the badge's "retest: changed since"), and "Earlier engine"
 * (neutral) when engineTag is set (the caller's: today's engine has results elsewhere and the pair has no newer
 * one). deckId: the deck whose side the row is from (default: the result's first). */
function resultRow(item, { against = false, deckId = null, engineTag = false } = {}) {
  const side = fromSide(item, deckId || item.sides[0].id);
  const muted = !!item.not_meaningful;
  const tags = [];
  if (muted) tags.push(status("crit", "Not meaningful"));
  // From a deck's side, a list changed since is the usual case: the row is faded with a dashed edge, as the
  // matrix's cells are, and one key line above the list says what that means (olderKey); its title and the
  // words a screen reader reads say which list. Elsewhere the freshness badge says "retest: changed since".
  const olderWords = [side.me.current === false ? "this list has changed since" : null,
    side.them.current === false ? "the opponent's list has changed since" : null].filter(Boolean).join("; ");
  if (engineTag && earlierEngine(item)) tags.push(status("plain", "Earlier engine"));
  const value = side.rate.value;
  const olderRow = against && !!olderWords;
  const what = `${sideTitle(side.me)}'s win rate`;
  return el("li", {}, el("a", { class: `mu-row${olderRow ? " is-older" : ""}`, href: side.href,
    title: olderRow ? capitalise(olderWords) : null },
    olderRow ? el("span", { class: "sr-only", text: `${capitalise(olderWords)}. ` }) : null,
    rowNames(side.me, side.them, against),
    el("span", { class: "mu-barline" },
      rangeBar(side.rate, { compact: true, muted, decorative: true }),
      el("span", { class: "mu-pct" }, winRateFigure(side.rate, { what, barred: true }))),
    el("span", { class: "mu-meta" },
      el("span", { text: metaWords(muted ? null : edgeWords(value), gamesWords(item.games), personName(item.by)) }),
      freshnessBadge(item.updated, { size: "row", compact: true, changed: !against && !!olderWords }), tags)));
}

/** The one key line above a deck's results when any row is faded (resultRow's against rows); null otherwise.
 * items: [{item, deckId}]. */
function olderKey(items) {
  const any = items.some(({ item, deckId }) => {
    const side = fromSide(item, deckId || item.sides[0].id);
    return side.me.current === false || side.them.current === false;
  });
  return any ? el("p", { class: "legend mu-older-key" }, el("span", { class: "mu-key-swatch is-older", "aria-hidden": "true" }),
    "Faded: one of the lists has changed since those games") : null;
}

/** A matchup waiting or being played, as a row with its progress (marked at its planned checks). A field
 * run or a variant test (wave 3's coordinators: no sides) is a row with its title, linking to its own page. */
function runningRow(run, { against = false } = {}) {
  if (!run.sides) return jobRow(run);
  const [a, b] = run.sides;
  const waiting = run.status === "queued";
  const bar = checkBar("Games played", "span");
  const p = runProgress(run);
  bar.set(p.done, p.total, p.checks);
  const wins = run.wins || [0, 0];
  const how = MODE_UNTIL[run.mode] ? MODE_UNTIL[run.mode].split(":")[0] : null;
  // One line of words (with who started it), so a wrapped line never starts with a separator.
  const words = waiting
    ? metaWords(run.ahead > 0 ? `${plural(run.ahead, "run")} ahead of it` : "Starting...", personName(run.by))
    : metaWords(run.waiting || `${thousands(p.done)} of ${p.approx ? "~" : ""}${thousands(p.total)} games`,
      run.waiting ? null : `${wins[0]}-${wins[1]} so far`, how, personName(run.by) && `started by ${run.by}`);
  return el("li", {}, el("a", { class: "mu-row", href: itemHref(run) },
    rowNames(a, b, against),
    bar.node,
    el("span", { class: "mu-meta" }, status("info", waiting ? "Waiting" : "Playing"),
      el("span", { text: words }))));
}

/** A field run or a variant test playing (api.forge_runs._running_json's coordinator item), as a row. */
function jobRow(run) {
  const waiting = run.status === "queued";
  const bar = progressBar("Games played", "span");
  bar.set(run.total ? run.done / run.total : 0);
  const words = metaWords(waiting ? (run.ahead > 0 ? `${plural(run.ahead, "run")} ahead of it` : "Starting...")
    : `${thousands(run.done || 0)} of ${thousands(run.total || 0)} games`, personName(run.by) && `started by ${run.by}`);
  return el("li", {}, el(run.hidden ? "div" : "a", { class: "mu-row", href: run.hidden ? null : run.link || "#/matchups" },
    rowNames({ title: run.title || "A run of many matchups" }, null, false),
    bar.node,
    el("span", { class: "mu-meta" }, status("info", waiting ? "Waiting" : "Playing"), el("span", { text: words })),
    run.hidden ? el("div", { class: "actions" }, listedRunStop(run)) : null));
}

/** Anonymous admin rows have no deck page to open. Their opaque job key can still stop the run. */
function listedRunStop(run) {
  if (!run.key || !["queued", "running"].includes(run.status) || !mayStopRuns(run)) return null;
  const button = el("button", { type: "button", class: "btn btn-danger runs-pill-stop", text: "Stop",
    "aria-label": `Stop: ${run.title || "this run"}`, onclick: () => stopListedRun(run, button) });
  return button;
}

async function stopListedRun(run, button) {
  const profile = state.profile?.id, token = routeToken, key = run.key;
  const here = () => state.profile?.id === profile && routeToken === token && button.isConnected &&
    ["queued", "running"].includes(run.status) && mayStopRuns(run);
  if (!profile || !here()) return;
  const answer = await ask("Stop this run?", [run.title || "A run of many matchups", "Every game that finished is kept."],
    [{ value: "stop", text: "Stop it", kind: "danger" }, { value: "keep", text: "Keep playing", kind: "primary" }]);
  if (answer !== "stop" || !here()) return;
  busy(button, "Stopping...");
  try {
    await apiWrite("/api/matchup/stop", { key });
    if (!here()) return;
    if (typeof syncRunsPill === "function") syncRunsPill(true);
    matchupRefresh?.refresh();
  } catch (error) {
    if (here()) toast(`It couldn't be stopped: ${error.message}`);
  } finally {
    if (here()) unbusy(button);
  }
}

/** "Not played yet against: A, B and C", each a link that opens that pair (where it can be played) while the
 * viewer may start runs; null when there are none. deck: {id, version}; others: decks {id, title}. */
function notPlayedLine(deck, others) {
  if (!others.length) return null;
  const may = runsAllowed();
  const names = others.map((d) => may
    ? el("a", { href: matchupHref(deck, { id: d.id, version: "target" }), text: shortTitle(d.title) })
    : el("span", { text: shortTitle(d.title) }));
  return el("p", { class: "mu-not-played" }, el("span", { class: "mu-not-played-label", text: "Not played yet against: " }),
    names.map((n, i) => [i ? (i === names.length - 1 ? " and " : ", ") : null, n]), ".");
}


// ------------------------------------------------------ the Matchups home

async function showMatchups(params, token) {
  // The profile's usual games and mode, read on their own: while the database is down the settings
  // answer 503, and the page still works with the matchup answers' defaults. The loading state shows
  // at once, so a slow answer doesn't leave the last page on screen.
  const pending = api(`/api/profiles/${encodeURIComponent(state.profile.id)}/settings`).catch(() => null);
  clear($("#main")).append(loadingBox("Loading matchups…"));
  const mine = await pending;
  if (token !== routeToken) return;
  return load(["/api/decks", "/api/matchups"], token, ([library, matchups]) => {
    state.library = library;
    if (!state.matchupGames && mine && Number(mine.matchup_games)) state.matchupGames = Number(mine.matchup_games);
    if (!state.matchupMode && mine && mine.matchup_mode) state.matchupMode = mine.matchup_mode;
    drawMatchups(library, matchups, params, token);
  });
}

/** The decks that can play: every library deck and product deck, but not a Beginner Box half alone
 * (a half is only played in a pairing, chosen as two halves). */
function playableDecks(library) {
  return library.decks.filter((d) => !d.error && !d.id.startsWith(BOX_PREFIX));
}

function isCommanderDeck(d) { return d.kind === "commander"; }

/** A deck's format as results name it. */
function deckFormat(d) { return isCommanderDeck(d) ? "Commander" : "Constructed"; }

/** The decks of a format on the matrix's axes, in the library's order (home's decks, then the products, then
 * the Beginner Box pairings that have results, then each person's): [{id, version: "target", title, kind}]. */
function matrixDecks(library, results, format) {
  const decks = playableDecks(library).filter((d) => deckFormat(d) === format);
  const own = (d) => (d.space || HOME_SPACE) === HOME_SPACE;
  const byTitle = (x, y) => x.title.localeCompare(y.title);
  const pairings = new Map();
  for (const item of results || []) {
    if (item.format !== format) continue;
    for (const side of item.sides || []) {
      if (side.id && side.id.startsWith("pairing/") && !pairings.has(sameDeckId(side.id))) {
        pairings.set(sameDeckId(side.id), { id: side.id, title: side.title, kind: "pairing" });
      }
    }
  }
  return [
    ...decks.filter((d) => own(d) && !d.id.startsWith("product/")).sort(byTitle),
    ...decks.filter((d) => own(d) && d.id.startsWith("product/")).sort(byTitle),
    ...[...pairings.values()].sort(byTitle),
    ...decks.filter((d) => !own(d)).sort(byTitle),
  ].map((d) => ({ id: d.id, version: "target", title: d.title, kind: d.kind }));
}

/** Each deck's short name (shortTitle) by id, its full title where two decks' short names would be the same. */
function shortNames(decks) {
  const counts = new Map();
  for (const d of decks) counts.set(shortTitle(d.title), (counts.get(shortTitle(d.title)) || 0) + 1);
  return new Map(decks.map((d) => [d.id, counts.get(shortTitle(d.title)) > 1 ? d.title : shortTitle(d.title)]));
}

/** One best saved result per opponent, from the selected deck's side. The shared model keeps the table,
 * casual cards and touch lab links in the same order. Deleted decks stay on the deck pages, off these axes. */
function matchupEntries(deck, decks, pairs, format, engines = false) {
  const entries = [], played = new Set(), onAxis = new Set(decks.map((d) => sameDeckId(d.id)));
  for (const [key, pair] of pairs) {
    if (!key.startsWith(`${format}|`)) continue;
    if (!pair.latest.sides.some((s) => sameDeckId(s.id) === sameDeckId(deck.id))) continue;
    const item = pair.latest, side = fromSide(item, deck.id);
    if (!onAxis.has(sameDeckId(side.them.id))) continue;
    played.add(sameDeckId(side.them.id));
    const olderWords = [side.me.current === false ? "this list has changed since" : null,
      side.them.current === false ? "the opponent's list has changed since" : null,
      side.me.version === "owned" || side.them.version === "owned" ? "played with a play-now list" : null]
      .filter(Boolean).join("; ");
    entries.push({ item, side, value: side.rate.value, muted: !!item.not_meaningful, olderWords,
      engineTag: engines && !pair.newer && earlierEngine(item) });
  }
  entries.sort(byBestFirst);
  return { entries, others: decks.filter((d) => sameDeckId(d.id) !== sameDeckId(deck.id) && !played.has(sameDeckId(d.id))) };
}

/** Keep a whole-row link's spoken name to its opponent, the rate and facts that change how it reads. */
function matchupOpponentLabel(entry) {
  const { side, muted, olderWords, engineTag } = entry;
  return [sideTitle(side.them), winRateWords(side.rate, "win rate"), muted ? "results are not meaningful" : null,
    olderWords, engineTag ? "earlier engine" : null].filter(Boolean).join(", ");
}

/** Only facts the saved pair actually supplies: field strong/weak flags are never inferred from its rate. */
function matchupOpponentFlags(entry) {
  return [entry.muted ? status("crit", "Not meaningful") : null,
    entry.engineTag ? status("plain", "Earlier engine") : null];
}

/** Mouse lab: real table semantics. The range is its own column, so the rate figure says only the point. */
function matchupOpponentTable(entries) {
  return el("div", { class: "mu-opponent-table" }, el("table", { class: "data" },
    el("caption", { class: "sr-only", text: "Matchups by win rate, best first; results that mean nothing last" }),
    el("thead", {}, el("tr", {}, ["Opponent", "Win rate", "95% range", "Range", "Games", "Flag"]
      .map((text) => el("th", { scope: "col", text })))),
    el("tbody", {}, entries.map((entry) => {
      const { item, side, muted, olderWords } = entry;
      const range = side.rate.value == null ? null : simRange(side.rate);
      return el("tr", { class: [olderWords && "is-older", muted && "is-muted"].filter(Boolean).join(" ") },
        el("th", { scope: "row" }, el("a", { class: "mu-opponent-name", href: side.href, text: sideTitle(side.them),
          title: olderWords ? capitalise(olderWords) : null }),
          olderWords ? el("span", { class: "sr-only", text: `${capitalise(olderWords)}. ` }) : null),
        el("td", { class: "num" }, winRateFigure({ value: side.rate.value }, { what: "Win rate", barred: true })),
        el("td", { class: "num" }, range ? el("span", { class: "sim-num", text: `${range}%` })
          : el("small", { text: "Not known" })),
        el("td", {}, rangeBar(side.rate, { compact: true, muted, decorative: true })),
        el("td", { class: "num sim-num", text: thousands(item.games) }),
        el("td", {}, el("span", { class: "mu-opponent-flags" }, matchupOpponentFlags(entry)),
          freshnessBadge(item.updated, { size: "row", compact: true, changed: side.me.current === false || side.them.current === false })));
    }))));
}

/** Casual cards and touch lab rows: each is one link, never an anchor pretending to be a table row. */
function matchupOpponentLinks(entries) {
  return el("ul", { class: "mu-opponent-links" }, entries.map((entry) => {
    const { item, side, muted, olderWords } = entry;
    return el("li", {}, el("a", { class: `mu-opponent-row${olderWords ? " is-older" : ""}${muted ? " is-muted" : ""}`, href: side.href,
      "aria-label": matchupOpponentLabel(entry) },
      el("span", { class: "mu-opponent-name", text: sideTitle(side.them) }),
      el("span", { class: "mu-barline" }, rangeBar(side.rate, { compact: true, muted, decorative: true }),
        el("span", { class: "mu-pct" }, winRateFigure(side.rate, { what: "Win rate", barred: true }))),
      el("span", { class: "mu-meta" }, simNumbers(gamesWords(item.games)),
        freshnessBadge(item.updated, { size: "row", compact: true, changed: side.me.current === false || side.them.current === false }), matchupOpponentFlags(entry))));
  }));
}

/** The deck page keeps its result cards and changed-list key; it shares the home's best-first entries. */
function deckMatchupList(deck, decks, pairs, format, engines = false) {
  const { entries, others } = matchupEntries(deck, decks, pairs, format, engines);
  return [
    entries.length ? olderKey(entries.map(({ item }) => ({ item, deckId: deck.id }))) : null,
    entries.length ? el("ul", { class: "mu-list" }, entries.map(({ item, engineTag }) =>
      resultRow(item, { against: true, deckId: deck.id, engineTag })))
      : noDeckMatchups(deck),
    notPlayedLine(deck, others)];
}

/** One deck with no matchups yet: the line, and Play a matchup with it picked when play (a function taking
 * the sheet's preset) is given and the viewer may start runs. */
function noDeckMatchups(deck, play = null) {
  return emptyBox(`${deck.title} hasn't played a matchup yet.`, play && runsAllowed()
    ? el("button", { type: "button", class: "btn", text: "Play a matchup", onclick: () => play({ a: deck.id }) }) : null);
}

function drawMatchups(library, matchups, params, token) {
  const main = $("#main");
  let data = matchups;
  const gate = runGate();
  const updates = matchupRefreshStatus();
  const lists = el("div", { class: "mu-lists" });
  const view = { format: null, deck: null, mode: local.get(HOME_VIEW_KEY) === "rankings" ? "rankings" : "matchups",
    token, profile: state.profile?.id, rankings: new Map() };
  const opener = () => openPlaySheet(library, () => data, token, {}, view.format);
  // The empty states' Play a matchup (drawHome), with a deck picked or this format's first.
  view.openPlay = (preset = {}) => openPlaySheet(library, () => data, token, preset, view.format);
  const play = gate.may ? el("button", { type: "button", class: "btn btn-primary", text: "Play a matchup",
    onclick: opener }) : null;
  add(main, [
    pageHead({ title: routeH1("matchups"), description: "Forge, a free Magic rules engine, plays two decks " +
      "against each other on the PC, hundreds of times, and counts who wins.", primary: play, badge: simulationsChip() }),
    gate.may ? null : el("p", { class: "run-blocked mu-gate", text: gate.why }),
    forgeBox(data.forge),
    updates.node, lists]);
  const needsLibrary = fresh => typeof fresh.decks_revision === "string" && fresh.decks_revision !== library.decks_revision;
  const prepare = async (fresh, { signal }) => {
    if (!needsLibrary(fresh)) return false;
    const current = await api("/api/decks", { signal });
    if (signal.aborted || token !== routeToken || view.profile !== state.profile?.id || !lists.isConnected) return null;
    if (current.decks_revision !== fresh.decks_revision) throw new Error("The decks changed while their names were loading. Trying again automatically.");
    library = current; state.library = current;
    return true;
  };
  if (needsLibrary(data)) lists.append(loadingBox("Updating the decks in Matchups…"));
  else drawHome(lists, data, library, view);
  const watcher = followList(lists, token, data, updates, (fresh) => { data = fresh; }, (fresh) => drawHome(lists, fresh, library, view),
    fresh => { if (view.mode === "rankings") muRefreshRankings(view, fresh); else muRefreshSelectedSummary(view); },
    () => { muCancelRankings(view); muCancelSelectedSummary(view); }, prepare);
  if (needsLibrary(data)) watcher.refresh();
  // The deck page's "Play a matchup" link (?a=&av=) opens the sheet with that deck picked.
  if (params.get("a") && gate.may) openPlaySheet(library, () => data, token, { a: params.get("a"), av: params.get("av"),
    b: params.get("b"), bv: params.get("bv") }, null);
}

/** The runs playing now, then one deck's opponents, as cards below 1000 px, a table with a mouse and whole
 * link rows in the touch lab. view keeps the selected mode, format and deck across redraws. */
function drawHome(host, data, library, view) {
  clear(host);
  const running = data.running || [], results = data.results || [];
  if (running.length) host.append(el("section", { class: "mu-group", "aria-labelledby": "h-running" },
    el("h2", { id: "h-running", text: "Playing now" }), el("ul", { class: "mu-list" }, running.map(r => runningRow(r)))));
  view.mode = view.mode === "rankings" ? "rankings" : "matchups";
  const formats = view.mode === "rankings" ? MATRIX_FORMATS
    : MATRIX_FORMATS.filter(([format]) => matrixDecks(library, results, format).length > 1);
  if (!formats.some(([f]) => f === view.format)) {
    const kept = local.get(HOME_FORMAT_KEY);
    view.format = formats.some(([f]) => f === kept) ? kept : (formats[0] || MATRIX_FORMATS[0])[0];
  }
  const section = el("section", { class: "mu-group mu-home", "aria-labelledby": "h-results" });
  const head = el("div", { class: "mu-home-head" }, el("h2", { id: "h-results", text: "Results" }),
    el("div", { class: "segmented mu-view", role: "group", "aria-label": "Results view" },
      [["matchups", "Matchups"], ["rankings", "Rankings"]].map(([mode, text]) => el("button", { type: "button", text,
        "aria-pressed": String(view.mode === mode), onclick: () => {
          if (view.token != null && (view.token !== routeToken || view.profile !== state.profile?.id)) return;
          view.mode = mode; if (mode !== "rankings") muCancelRankings(view); view.rankingsForce = true; local.set(HOME_VIEW_KEY, mode); drawHome(host, data, library, view);
        } }))));
  if (formats.length > 1) head.append(el("div", { class: "segmented mu-format", role: "group", "aria-label": "Format" },
    formats.map(([format, words]) => el("button", { type: "button", text: words, "aria-pressed": String(format === view.format),
      onclick: () => {
        if (view.token != null && (view.token !== routeToken || view.profile !== state.profile?.id)) return;
        view.format = format; view.deck = null; view.rankingsForce = true; local.set(HOME_FORMAT_KEY, format); drawHome(host, data, library, view);
      } }))));
  section.append(head); host.append(section);
  if (view.mode === "rankings") {
    muCancelSelectedSummary(view);
    view.token ??= routeToken; view.profile ??= state.profile?.id; view.rankings ||= new Map();
    view.rankingsHost = el("div", { class: "mu-rankings" }); section.append(view.rankingsHost);
    view.rankingsHost.openPlay = view.openPlay;
    muRefreshRankings(view, data); return;
  }
  if (!formats.length) {
    muCancelSelectedSummary(view);
    section.append(emptyBox("There are no two decks of one format to play yet.",
      createTargets().length ? el("a", { class: "btn", href: newDeckHref(), text: "New deck" }) : null)); return;
  }
  const decks = matrixDecks(library, results, view.format), shown = results.filter(r => r.format === view.format);
  const canonicalPick = id => library.decks.find(d => d.id === id || d.aliases?.includes(id))?.id || id;
  view.deck = canonicalPick(view.deck);
  const storedPick = local.get(HOME_DECK_KEY), keptPick = canonicalPick(storedPick);
  if (keptPick !== storedPick) local.set(HOME_DECK_KEY, keptPick);
  const pairs = pairsOf(results);
  const playButton = (preset = {}) => view.openPlay && runGate().may
    ? el("button", { type: "button", class: "btn", text: "Play a matchup", onclick: () => view.openPlay(preset) }) : null;
  if (!shown.length) section.append(emptyBox("No matchups have been played yet.", playButton()));
  add(section, [allEarlierLine(shown)]);
  const choose = (id) => {
    view.deck = id;
    local.set(HOME_DECK_KEY, id);
    replaceMatchupContent(host, () => drawHome(host, data, library, view));
  };
  // The same selected deck and best-first opponents at every density.
  const played = (d) => shown.filter((r) => r.sides.some((s) => sameDeckId(s.id) === sameDeckId(d.id))).length;
  if (!decks.some((d) => d.id === view.deck)) {
    const kept = keptPick;
    view.deck = decks.some((d) => d.id === kept) ? kept
      : [...decks].sort((x, y) => played(y) - played(x))[0].id;
  }
  const body = el("div", { class: "mu-home-body" });
  const names = shortNames(decks);
  const select = el("select", { id: "mu-deck-pick", onchange: () => choose(select.value) },
    decks.map((d) => el("option", { value: d.id, text: names.get(d.id), title: d.title, selected: d.id === view.deck })));
  const deck = decks.find((d) => d.id === view.deck);
  const { entries, others } = matchupEntries(deck, decks, pairs, view.format, anyTodaysEngine(shown));
  add(body, [el("label", { class: "field mu-deck-field", for: select.id }, el("span", { text: "Show matchups for" }), select),
    muSelectedSummary(view, library, data, deck),
    el("p", { class: "sub", text: "Saved matchup rows below may use different lists or earlier engines. Open a row for its exact lists." }),
    el("div", { class: "mu-opponents" }, entries.length
      ? [matchupOpponentTable(entries), matchupOpponentLinks(entries)]
      // With no matchups of this format at all, the empty state above already says so.
      : shown.length ? noDeckMatchups(deck, view.openPlay) : null),
    notPlayedLine(deck, others)]);
  section.append(body);
}

/** Keep discovering runs even when none was running when this page opened. onData(fresh) keeps the answer;
 * redraw(fresh) draws the lists again (only when the answer changed). */
function followList(host, token, data, view, onData, redraw, onChecked = null, onPause = null, prepare = null) {
  let running = (data.running || []).length > 0;
  let previous = JSON.stringify(data);
  return watchMatchupUpdates({ token, host: () => host, url: "/api/matchups", view, onPause,
    active: () => running, interval: POLL_MS * LIST_POLL,
    async onFresh(fresh, context) {
      const libraryChanged = prepare ? await prepare(fresh, context) : false;
      if (libraryChanged === null || token !== routeToken || context.signal.aborted || !host.isConnected) return;
      const signature = JSON.stringify(fresh);
      running = (fresh.running || []).length > 0;
      if (typeof noteRuns === "function") noteRuns(fresh.running);       // runs-pill.js: the top bar's run activity too
      if (signature !== previous || libraryChanged) {
        onData(fresh);
        replaceMatchupContent(host, () => redraw(fresh));
        previous = signature;
      }
      if (onChecked) onChecked(fresh);
    },
  });
}


// ------------------------------------------------------ saved field rankings (read only)

function muRankingsHere(view) {
  return view.mode === "rankings" && view.token === routeToken && view.profile === state.profile?.id && !view.rankingsPaused && document.visibilityState !== "hidden" && view.rankingsHost?.isConnected;
}

function muCancelRankings(view) {
  view.rankingsPaused = true;
  if (view.rankingsRequest) view.rankingsRequest.abort();
}

/** Share the existing foreground refresh loop. A changed result refreshes promptly; otherwise at most once
 * per idle interval. A format change waits for the current read, so fitting never fans out into parallel reads. */
async function muRefreshRankings(view, data) {
  view.rankingsData = data; view.rankingsPaused = false;
  if (!muRankingsHere(view)) return;
  const format = view.format, signature = JSON.stringify((data.results || []).filter(r => r.format === format));
  const entry = view.rankings.get(format) || { answer: null, error: null, asked: 0, signature: null };
  view.rankings.set(format, entry);
  if (view.rankingsRequest) {
    entry.loading = true;
    view.rankingsAgain ||= entry.signature !== signature;
    muDrawRankings(view.rankingsHost, entry, format); return;
  }
  muDrawRankings(view.rankingsHost, entry, format);
  if (!view.rankingsForce && entry.signature === signature && Date.now() - entry.asked < IDLE_MATCHUP_POLL_MS) return;
  view.rankingsForce = false;
  const controller = new AbortController();
  let rejectRead;
  const cancelled = new Promise((resolve, reject) => { rejectRead = reject; });
  const request = { format, token: view.token, profile: view.profile, cancelled: false, timedOut: false,
    abort(timedOut = false) {
      if (request.cancelled) return;
      request.cancelled = true; request.timedOut = timedOut; controller.abort();
      rejectRead(new Error(timedOut ? "The PC took too long to answer the rankings." : "Rankings read cancelled."));
    } };
  const deadline = setTimeout(() => request.abort(true), 12000);
  view.rankingsRequest = request; entry.asked = Date.now(); entry.signature = signature; entry.loading = true;
  muDrawRankings(view.rankingsHost, entry, format);
  try {
    const answer = await Promise.race([api(`/api/rankings?format=${encodeURIComponent(format)}`, { signal: controller.signal }), cancelled]);
    if (request.token !== routeToken || request.profile !== state.profile?.id || request.cancelled) return;
    if (answer.format !== format) throw new Error("The rankings answered for a different format. Try again.");
    entry.answer = answer; entry.error = null;
  } catch (error) {
    if (request.cancelled && !request.timedOut) entry.signature = null;
    if (request.token !== routeToken || request.profile !== state.profile?.id || (request.cancelled && !request.timedOut)) return;
    entry.error = request.timedOut ? "The PC took too long to answer the rankings." : error.message || String(error);
  } finally {
    clearTimeout(deadline);
    entry.loading = false;
    if (view.rankingsRequest === request) view.rankingsRequest = null;
    if (muRankingsHere(view)) {
      if (view.format !== format || view.rankingsForce || view.rankingsAgain) {
        view.rankingsAgain = false; muRefreshRankings(view, view.rankingsData);
      }
      else muDrawRankings(view.rankingsHost, entry, format);
    }
  }
}

function muRankingRow(row) {
  const versions = row.versions?.length ? row.versions : [row.version || "target"];
  const list = versions.length > 1 ? "Planned and play-now lists (same cards and pilot)" : capitalise(listName(versions[0], true));
  const r = row.rating, rated = r && Number.isFinite(r.value);
  const rate = rated ? { value: r.value, low: Number.isFinite(r.low) ? r.low : null,
    high: Number.isFinite(r.high) ? r.high : null } : null;
  const rank = rated && Number.isFinite(r.rank) && Number.isFinite(r.of) ? `Rank ${r.rank} of ${r.of}` : "No rating yet";
  const range = rated && Number.isFinite(r.rank_low) && Number.isFinite(r.rank_high)
    ? `Likely rank ${r.rank_low === r.rank_high ? r.rank_low : `${r.rank_low}-${r.rank_high}`}` : "Rank range unavailable";
  return el("li", { class: "mu-ranking-row", "data-deck": row.id, "data-version": row.version },
    el("div", { class: "mu-ranking-name" }, el("a", { href: deckHref(row.id, row.version), text: row.title }),
      el("span", { class: "sub", text: list })),
    el("div", { class: "mu-ranking-score" },
      rated ? el("span", { class: "sub", text: "Rating " }) : null,
      rated ? winRateFigure(rate, { size: "hero", what: "Rating against an average current field list" }) : null,
      el("strong", {}, simNumbers(rated ? rank : row.in_field === false ? "Outside the field" : rank)),
      rated ? el("span", {}, simNumbers(range)) : null,
      row.in_field !== false && Number.isFinite(row.games) ? el("span", { class: "sub" }, simNumbers(gamesWords(row.games))) : null),
    row.unsettled ? status("warn", "Unsettled") : null,
    row.exclusion || row.reasons?.length ? el("p", { class: "mu-ranking-reasons", text:
      [...new Set([row.exclusion, ...(row.reasons || [])].filter(Boolean))].join(" ") }) : null);
}

/** Server groups are independent rating fits: never imply an order between disconnected groups. */
function muDrawRankings(host, entry, format) {
  const signature = JSON.stringify([entry.answer, entry.error, !!entry.loading, format]);
  if (host.rankingsSignature === signature) return;
  host.rankingsSignature = signature;
  replaceMatchupContent(host, () => muRankingContent(host, entry, format));
}

/** Current selector context, separate from the saved games and each rating group's denominator. */
function manualFieldExclusionNote(count, className) {
  const known = Number.isSafeInteger(count) && count >= 0 && count <= 1000;
  return el("p", { class: className, text: known
    ? `${count} ${count === 1 ? "list" : "lists"} manually excluded from the current field.`
    : "The number of lists manually excluded from the current field is unavailable." });
}

function muRankingContent(host, entry, format) {
  clear(host);
  host.setAttribute("aria-busy", String(!!entry.loading));
  const answer = entry.answer;
  if (entry.error || answer?.error) host.append(markedBox("warn", "h3", "Rankings aren't available", [
    el("p", { text: (entry.error || answer.error) + " Trying again automatically." }),
    answer ? el("p", { text: "The saved display below may be out of date." }) : null], { role: "status" }));
  // First load: the page's waiting state; over a saved answer, a small one above it.
  if (entry.loading) host.append(loadingBox(answer ? "Updating rankings…" : "Loading rankings…", { small: !!answer }));
  if (!answer) return;
  const rows = answer.rows || [], groups = answer.groups || [];
  host.append(el("p", { text: `Current ${format === "Constructed" ? "60-card" : format} lists, using saved games with today's engine. ` +
    "The current field chooses its planned or play-now list for each deck, with its saved additions and exclusions. " +
    "Other current lists stay visible below. A rating is the model's estimated win rate against an average current field list in the same group, balanced for who starts. " +
    "Rank ranges show how uncertain the order is; Forge's AI is not a promise about a real game." }));
  host.append(manualFieldExclusionNote(answer.manual_excluded, "sub mu-manual-excluded"));
  if (groups.length > 1) host.append(markedBox("warn", "h3", "Separate rating groups",
    el("p", { text: "These groups have no games connecting them. Ranks compare lists only within the same group; there is no ranking between groups." })));
  const shown = new Set();
  const section = (title, items) => {
    if (!items.length) return;
    items.forEach(row => shown.add(row));
    host.append(el("section", { class: "mu-ranking-group" }, el("h3", { text: title }), el("ul", { class: "mu-ranking-list" }, items.map(muRankingRow))));
  };
  groups.forEach((group, index) => section(groups.length > 1 ? `Group ${index + 1} · ${plural(group.lists, "list")}` : "Ranked lists",
    rows.filter(row => row.group === group.id && row.in_field !== false && Number.isFinite(row.rating?.value))
      .sort((a, b) => b.rating.value - a.rating.value || a.title.localeCompare(b.title))));
  section("Unsettled without a rating", rows.filter(row => !shown.has(row) && row.in_field !== false));
  section("Outside the field", rows.filter(row => !shown.has(row)));
  if (!rows.length && !answer.error && !entry.error) host.append(emptyBox("There are no current lists of this format to rank.",
    host.openPlay && runsAllowed() ? el("button", { type: "button", class: "btn", text: "Play a matchup", onclick: () => host.openPlay() }) : null));
  if (answer.notes?.length) host.append(el("details", { class: "more" }, el("summary", { text: "How rankings are worked out" }),
    el("ul", {}, answer.notes.map(text => el("li", { text })))));
}


// ------------------------------------------------------ "Play a matchup"

/** One deck to play: the deck (or a Beginner Box pairing, as two halves), then which list when it has
 * two. value() is {id, version, title, commander} or {problem}. onChange() follows every change. */
function deckPicker(n, library, onChange) {
  const decks = playableDecks(library);
  const halves = library.halves || [];
  const select = el("select", { id: `pick-${n}`, onchange: () => { syncParts(); onChange(); } });
  const versionButtons = ["target", "owned"].map((v) => el("button", { type: "button", text: listName(v),
    onclick: () => { version = v; syncParts(); onChange(); } }));
  const versionRow = el("div", { class: "segmented", role: "group", "aria-label": `Deck ${n}: which list` }, versionButtons);
  const half = (which, i) => el("select", { id: `pick-${n}-${which}`, onchange: () => onChange() },
    halves.map((h, k) => el("option", { value: h.id, text: h.title, selected: k === i })));
  const halfA = half("a", 0), halfB = half("b", 1);
  const pair = el("div", { class: "mu-pair" },
    el("label", { class: "field", for: halfA.id }, el("span", { text: "First half" }), halfA),
    el("label", { class: "field", for: halfB.id }, el("span", { text: "Second half" }), halfB));
  let version = "target";
  let only = null;          // true: Commander decks only; false: no Commander decks; null: any
  let preferred = new Set();

  /** A complete known pairing named by the server's visible usual-opponent ids. */
  function pairingChoice(id) {
    if (typeof id !== "string" || !/^pairing\/[a-z0-9-]+\+[a-z0-9-]+$/.test(id)) return null;
    const parts = pairingHalves(id);
    if (parts.length !== 2 || parts[0] === parts[1]) return null;
    const found = parts.map(part => halves.find(h => !h.error && h.id.split("/").pop() === part));
    return found.every(Boolean) ? { id, title: found.map(h => h.title).join(" + "), kind: "pairing" } : null;
  }

  /** The options for the decks allowed now; true when the one chosen is still there. */
  function fill() {
    const was = select.value;
    const fits = (d) => only == null || isCommanderDeck(d) === only;
    const pairings = [...preferred].filter(id => !decks.some(deck => deck.id === id)).map(pairingChoice).filter(Boolean);
    const groups = [
      ["Usual opponents", [...decks.filter(d => preferred.has(d.id)), ...pairings]],
      ["60-card decks", decks.filter((d) => !preferred.has(d.id) && d.kind !== "commander" && !d.id.startsWith("product/"))],
      ["Commander decks", decks.filter((d) => !preferred.has(d.id) && d.kind === "commander" && !d.id.startsWith("product/"))],
      ["Product decks", decks.filter((d) => !preferred.has(d.id) && d.id.startsWith("product/"))],
    ];
    clear(select);
    for (const [label, members] of groups) {
      const shown = members.filter(fits);
      if (shown.length) select.append(el("optgroup", { label }, shown.map((d) => el("option", { value: d.id, text: d.title }))));
    }
    if (only !== true && halves.length > 1) {
      const keptPair = !preferred.has(was) && !decks.some(deck => deck.id === was) && pairingChoice(was);
      select.append(el("optgroup", { label: "Beginner Box" },
        keptPair ? el("option", { value: keptPair.id, text: keptPair.title }) : null,
        el("option", { value: "pairing", text: "A pairing of two halves (40 cards)" })));
    }
    const kept = [...select.options].some((o) => o.value === was);
    if (kept) select.value = was;
    syncParts();
    return kept;
  }
  function current() { return decks.find((d) => d.id === select.value) || null; }
  function syncParts() {
    const d = current();
    const both = !!d && (d.versions || []).length > 1;
    if (!both) version = "target";
    versionRow.hidden = !both;
    versionButtons.forEach((b, i) => b.setAttribute("aria-pressed", String(["target", "owned"][i] === version)));
    pair.hidden = select.value !== "pairing";
  }
  const node = el("fieldset", { class: "mu-pick" },
    el("legend", { text: `Deck ${n}` }),
    el("label", { class: "sr-only", for: select.id, text: `Deck ${n}` }), select, versionRow, pair);
  fill();
  return {
    node,
    /** Offer only Commander decks (true), only the others (false), or any (null). When the deck chosen
     * isn't offered any more, the first one other than avoid (the other picker's deck) is chosen. */
    limit(commander, avoid, usual = []) {
      only = commander;
      preferred = new Set(usual.filter(id => id !== avoid));
      if (!fill()) this.other(avoid);
    },
    set(id, v) {
      id = decks.find(deck => deck.id === id || deck.aliases?.includes(id))?.id || id;
      const parts = pairingChoice(id) && pairingHalves(id);
      if (id && [...select.options].some(o => o.value === id)) {
        select.value = id;
      } else if (parts && [...select.options].some(o => o.value === "pairing")) {
        const [x, y] = parts;
        const find = (part) => halves.find((h) => h.id.split("/").pop() === part);
        if (find(x) && find(y)) {
          select.value = "pairing";
          halfA.value = find(x).id;
          halfB.value = find(y).id;
        }
      }
      version = v === "owned" ? "owned" : "target";
      syncParts();
    },
    /** Pick the first deck that isn't this one (deck 2's starting choice). */
    other(id) {
      const o = [...select.options].find((opt) => opt.value !== id && opt.value !== "pairing");
      if (o) select.value = o.value;
      syncParts();
    },
    value() {
      const fixedPair = pairingChoice(select.value);
      if (fixedPair) return { ...fixedPair, version: "target", commander: false };
      if (select.value === "pairing") {
        if (halfA.value === halfB.value) return { problem: `Deck ${n}: pick two different halves for the pairing.` };
        const title = (id) => (halves.find((h) => h.id === id) || { title: id.split("/").pop() }).title;
        return { id: pairingId(halfA.value, halfB.value), version: "target",
          title: `${title(halfA.value)} + ${title(halfB.value)}`, commander: false };
      }
      const d = current();
      if (!d) return { problem: `Pick deck ${n}.` };
      return { id: d.id, version, title: d.title, commander: isCommanderDeck(d) };
    },
  };
}

function sameSide(side, pick) {
  return sameDeckId(side.id) === sameDeckId(pick.id) && (side.version || "target") === pick.version &&
    side.current !== false;
}

/** The saved result (or the run) of these two lists, in either order. */
function findItem(items, a, b) {
  return (items || []).find((r) => r.sides && ((sameSide(r.sides[0], a) && sameSide(r.sides[1], b))
    || (sameSide(r.sides[0], b) && sameSide(r.sides[1], a)))) || null;
}

/** "Play a matchup" in a sheet: the two decks, how long to play (one run vocabulary) and Start. live() gives
 * the latest /api/matchups answer (the list page keeps it up to date), so the sheet knows a run of the two
 * lists already playing, or a saved result to add to. preset: {a, av, b, bv} from the address; format: the
 * matrix's ("Constructed" or "Commander"), whose first deck is picked when preset names none. The time
 * estimates are the two lists' own (GET /api/matchup's "estimates", as their pair page shows them), asked for
 * whenever the decks change; until they come, the rough ones for the format. */
function openPlaySheet(library, live, token, preset, format = null) {
  const sheet = openSheet("Play a matchup", { wide: true });
  sheet.dialog.classList.add("mu-play-sheet");
  const one = deckPicker(1, library, () => changed(true));
  const two = deckPicker(2, library, () => changed(false));
  // How long to play (runModeChoice: the profile's choice first).
  const games = runModeChoice(live(), () => changed(false));
  const already = el("div", { class: "mu-already", "aria-live": "polite" });
  const error = el("p", { class: "form-error", role: "alert" });
  const start = el("button", { type: "submit", class: "btn btn-primary", text: "Start", "data-run": true,
    disabled: (live().forge || {}).ready === false });
  let sending = false;      // Start was pressed and its answer hasn't come (the button says "Starting...")

  const first = !preset.a && format ? playableDecks(library).find((d) => deckFormat(d) === format) : null;
  one.set(preset.a || (first && first.id), preset.av);
  function limitOpponent() {
    const picked = one.value();
    const usual = library.decks.find(deck => deck.id === picked.id)?.usual_opponents
      || Object.entries(library.usual_opponents || {}).find(([id]) => sameDeckId(id) === sameDeckId(picked.id))?.[1] || [];
    two.limit(picked.commander === true, picked.id, usual);
  }
  limitOpponent();
  if (preset.b) two.set(preset.b, preset.bv);
  else two.other(one.value().id);

  /** A change made on the form: its error (if any) is about the old choice, so it goes. */
  function changed(first) {
    error.textContent = "";
    if (first) limitOpponent();
    games.setCommander(one.value().commander === true);
    refresh();
    askEstimates();
  }

  // The two lists' own time estimates (their pair page's), asked for a moment after the last change.
  let asked = null, estimateTimer = 0;
  function askEstimates() {
    const a = one.value(), b = two.value();
    if (a.problem || b.problem || !state.profile) return;
    const want = new URLSearchParams({ a: a.id, av: a.version, b: b.id, bv: b.version, profile: state.profile.id }).toString();
    if (want === asked) return;
    asked = want;
    clearTimeout(estimateTimer);
    estimateTimer = setTimeout(async () => {
      try {
        const answer = await api(`/api/matchup?${want}`);
        if (token !== routeToken || sheet.closed || asked !== want) return;
        games.setEstimates(answer.estimates || null, answer.format === "Commander");
      } catch (e) { /* the rough times stay */ }
    }, 250);
  }

  /** What's known about the two lists picked (a run of them, a saved result), and Start's words. */
  function refresh() {
    const data = live();
    const a = one.value(), b = two.value();
    const running = a.problem || b.problem ? null : findItem(data.running, a, b);
    // Start adds to today's engine's result only: one of an earlier engine stays as it is.
    const saved = a.problem || b.problem ? null : findItem((data.results || []).filter((r) => !earlierEngine(r)), a, b);
    clear(already);
    // A run of these lists plays the games it was asked for, so the choice doesn't apply to it.
    games.node.hidden = !!running;
    if (!sending) {
      const asked = games.value();
      start.textContent = running ? "Follow the games" : !saved ? "Start"
        : asked.mode === "fixed" ? `Play ${thousands(asked.games)} more games` : "Play more";
      // Following a run is always allowed; starting one only while the simulations gate lets this viewer.
      start.disabled = (data.forge || {}).ready === false || (!running && !runsAllowed());
    }
    if (running) {
      const waiting = running.status === "queued";
      already.append(el("p", {}, status("info", waiting ? "Waiting" : "Playing"),
        waiting ? " These two lists are waiting their turn: a few matchups play at a time on the PC."
          : " These two lists are playing now."));
    } else if (saved) {
      already.append(el("p", {}, `These two lists have played ${gamesWords(saved.games)} already: ` +
        `${sideTitle(saved.sides[0])} won ${rateWords(saved.winrate)}. `,
        el("a", { href: itemHref(saved), text: "See the result" }),
        ". Start plays more games and adds them to it."));
    }
  }

  async function submit(event) {
    event.preventDefault();
    const a = one.value(), b = two.value();
    const problem = a.problem || b.problem;
    if (problem) { error.textContent = problem; return; }
    const running = findItem(live().running, a, b);
    if (running) { sheet.close(); location.hash = itemHref(running); return; }
    error.textContent = "";
    sending = true;
    busy(start, "Starting...");
    try {
      const asked = games.value();
      await apiWrite("/api/matchup/run", { a: a.id, av: a.version, b: b.id, bv: b.version, mode: asked.mode,
        ...(asked.mode === "fixed" ? { games: asked.games } : {}) });
      if (token !== routeToken) return;
      sheet.close();
      location.hash = matchupHref(a, b);
    } catch (e) {
      if (token !== routeToken) return;
      sending = false;
      unbusy(start);
      refresh();
      error.textContent = e.message + (e.status ? ` (error ${e.status})` : "");
    }
  }

  sheet.body.append(el("form", { class: "mu-play", novalidate: true, onsubmit: submit, "aria-label": "Play a matchup" },
    el("div", { class: "mu-picker" }, one.node, two.node),
    el("p", { class: "sub mu-kind-note", text: "Commander decks play Commander decks (1v1, 40 life); the others " +
      "play each other." }),
    games.node,
    already,
    el("div", { class: "actions" }, start),
    error));
  changed(false);
  syncRunControls(sheet.body);
  return sheet;
}

/** Forge isn't ready on the PC (not installed, no Java): say so. When it is, but the card log isn't (a
 * Java without the JDK's tools, or a Forge version the card log hasn't been checked with), a short note
 * says per-card stats are off and why. null when both are ready (or an older server doesn't say). */
function forgeBox(forge) {
  if (!forge) return null;
  if (forge.ready === false) {
    return markedBox("warn", "h2", "Forge isn't ready on the PC",
      el("p", { text: (forge.problem || "Forge can't be started.") + " Saved results still show, but no new games can be played until it's fixed." }));
  }
  const log = forge.card_log;
  if (!log || log.ready !== false) return null;
  return el("p", { class: "mu-cardlog-off" }, status("warn", "Per-card stats are off"), " ",
    (log.problem || "The card log can't be used on this PC.") + " Games still play as usual, without per-card numbers.");
}


// ------------------------------------------------------------ deck page

/** From GET /api/matchups: a function (deck id) -> "1 result", "2 results" (saved results with that
 * list in them, either side) or "". For a Beginner Box half's links to its pairings. */
function resultCounts(answer) {
  const counts = new Map();
  for (const item of answer.results || []) {
    for (const id of new Set(item.sides.map((side) => sameDeckId(side.id)))) counts.set(id, (counts.get(id) || 0) + 1);
  }
  return (id) => {
    const n = counts.get(sameDeckId(id)) || 0;
    return n ? plural(n, "result") : "";
  };
}

/** The deck page's results (DK-13): one row per opponent, best matchup first (results that mean nothing last),
 * each the pair's best result (this list's with today's engine first); the rest folded under "Earlier
 * results"; then "Not played yet against" (when the library is known), each linking to this list (listVersion:
 * "target" or "owned") against that deck. Never "No games yet" for an opponent with older results. */
function deckResultParts(m, s, version, library, listVersion = "target") {
  const results = m.results || [];
  const byOpponent = new Map();
  for (const item of results) {
    const key = sameDeckId(item.sides[1].id);
    const entry = byOpponent.get(key) || { latest: null, all: [] };
    entry.all.push(item);
    const rank = entry.latest ? resultRank(item) - resultRank(entry.latest) : 1;
    // The best kind of result; of equally good ones, the newest.
    if (rank > 0 || (rank === 0 && String(item.updated || "") > String(entry.latest.updated || ""))) entry.latest = item;
    byOpponent.set(key, entry);
  }
  const entries = [...byOpponent.values()].map((e) => ({ ...e, value: (e.latest.winrate || {}).value,
    muted: !!e.latest.not_meaningful })).sort(byBestFirst);
  const earlier = entries.flatMap((e) => e.all.filter((item) => item !== e.latest));
  const engines = anyTodaysEngine(results);
  const format = s.kind === "commander" ? "Commander" : "Constructed";
  const others = library ? matrixDecks(library, [], format).filter((d) => sameDeckId(d.id) !== sameDeckId(s.id)
    && !byOpponent.has(sameDeckId(d.id))) : [];
  return [
    entries.length ? [
      el("p", { class: "sub", text: `This ${version}'s win rate against each deck, best first.` }),
      allEarlierLine(results),
      olderKey(entries.map((e) => ({ item: e.latest, deckId: null }))),
      el("ul", { class: "mu-list" }, entries.map((e) =>
        resultRow(e.latest, { against: true, engineTag: engines && !e.all.some((item) => !earlierEngine(item)) }))),
      earlier.length ? el("details", { class: "more mu-earlier-results" },
        el("summary", { text: `Earlier results (${earlier.length})` }),
        el("ul", { class: "mu-list" }, earlier.map((item) => resultRow(item, { against: true })))) : null]
      // The tab's own Play a matchup follows this part, so the empty state needs no second one.
      : emptyBox(`No matchups played with this ${version} yet.`),
    notPlayedLine({ id: s.id, version: listVersion }, others)];
}

/** The deck page's one line about this list's games played with an earlier engine, when none were played with
 * today's (so the AI checks and the per-card numbers below have nothing to count yet); null otherwise. Said
 * once here, in place of a sentence in each part. */
function earlierEngineLine(m) {
  const ai = m.ai || {};
  const other = Number(ai.other_engine_games) || Number((m.cards || {}).other_engine_games) || 0;
  if (!other || Number(ai.games) > 0) return null;
  return el("p", { class: "sub mu-earlier-engine", text: `This list's ${gamesWords(other)} were all played with an ` +
    "earlier version of Forge's engine, so the checks below wait for games with today's." });
}

/** What this list's games with an earlier engine showed that today's haven't checked yet: {commander: true}
 * when its commander was never cast in them (the server's ai.other_engine_commander_unplayable, forge.list_ai);
 * null when there's nothing to say, or today's games have been counted. */
function earlierFlags(m) {
  const ai = m.ai || {};
  if (Number(ai.games) >= NEVER_CAST_GAMES || ai.commander_unplayable) return null;
  if (ai.other_engine_commander_unplayable) return { commander: true };
  return null;
}
