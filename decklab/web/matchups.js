/* Deck Lab's matchup screens (Milestone 5; redesigned in the UI review's WP12): Forge, a free Magic rules
engine, plays two decks against each other on the PC, many times over, and these screens start the games,
follow them and show what came out, in words a non-statistician can read.

The matchup scripts load after the editor (editor.js first), in this order:
    sim-ui.js             Forge's result pieces: win-rate figures, range bars, freshness badges, flags, tests
    matchups.js           shared constants, words, the run choice and AI limits
    matchups-overview.js  cross-device refresh, result rows, the Matchups home (matrix, phone list, play
                          sheet) and the deck page's results (deckResultParts)
    matchups-detail.js    one matchup (the pair page): starting, following and stopping a run
    matchups-results.js   the verdict, "Why we're confident", "Details" and how the games were played
    matchups-cards.js     per-card numbers from the card log
runs-pill.js (the top bar's run activity) loads after them. They share classic-script globals, as
the editor does. Nothing calls across files until the page is running. core.js supplies el, svgEl, api,
apiWrite, load, state, note, status, pct, fitWidth, progressBar, pairingId, sameDeckId, pageHead, crumb,
listName, ...; stats.js supplies tile(); deck.js supplies cardNames(), cardLink() and
pairingLinks(); version.js supplies simulationsGate() and mayStartRuns(); editor.js supplies openSheet(),
ask(), busy() and unbusy(); app.js supplies afterRender(). app.js routes to showMatchups and showMatchup;
the deck page's Matchups tab (deck-tools.js) uses deckResultParts, aiLimitsParts and the refresh loop.

Routes:
    #/matchups[?a=<deck id>&av=target|owned]   the Matchups home: a matrix of every deck against every other
                                               (on a phone, one deck's matchups as a sorted list), the runs
                                               playing now, and "Play a matchup" (a sheet). a/av open the
                                               sheet with that deck picked (the deck page's link).
    #/matchup?a=<id>&av=<v>&b=<id>&bv=<v>      one pair, from deck a's side: not played yet (the run choice
                                               and Play), waiting or running (progress, the score so far, Stop)
                                               or done (the verdict first)
    #/matchup?key=<64 hex>                     a saved result by its key (a list that has changed since, or
                                               an earlier engine's result; sides as saved)

Every number comes from the server (decklab/lib/api/forge_runs.py): GET /api/matchups (?running=1: only the
runs, for the run activity), GET /api/matchup, POST /api/matchup/run and /api/matchup/stop, and the deck view's
"matchups". Saved sides carry their deck's title today (MU-15).

One run vocabulary everywhere (MU-05): Quick look (200 games), Settle it (forge/adaptive.py's "ahead": checks
at 400, 800, 1,600 and 3,200 games until one deck is clearly ahead, or they're about even) and Precise
("assess": until the win rate is known to within ±3 points), with a set number of games under "More
options" and one time estimate (the server's "estimates", forge/estimate.py; without them, roughMinutes from
Milestone 0's speeds, which batchPlan splits as forge/lists.py's _batch_count does). The choice is the
profile's "matchup_mode" and "matchup_games" settings, saved when it changes. Field runs (field.js) and tests
of changes (variant.js) use the same words for their own budgets.

While a run is waiting or going, the pair page asks again every POLL_MS (core.js) and updates its progress
box in place; pages also check while idle so runs started on another device appear. Hidden pages pause and
route changes cancel reads and listeners; only a lost connection is shown (MU-13). Stop asks first; every
game that finished is kept.

A win rate is a mono figure in ink with its range bar on the fixed 20-80% scale (sim-ui.js, design/visual-
design.md 4.9; E11-S30 slice 6, in place of MU-06's diverging green and red bars): the figure is never coloured,
and only the matrix's cells still shade around 50%. A result that means nothing (a commander Forge's AI never
casts) gets a faded mark and no band, and says so in words.

Engines (simulation wave 2): every saved result says which engine played it ("engine": {kind, run_version,
current, words}). A result of another engine than today's gets a neutral "Earlier engine" tag, and only when no
newer result of the pair exists (MU-02); more games of its lists start a new result with today's engine.
*/
"use strict";

const FORGE_WORKERS = 16;               // Forge processes at once on the PC (config.json's forge_workers)
const SMALL_BATCH = 25;                 // the fewest games forge.plan gives a batch (forge/lists.py's SMALL_BATCH)
const NEVER_CAST_GAMES = 100;           // cast in none of this many games: flagged (forge's MIN_GAMES_NEVER_CAST)
const PROCESS_GAMES_PER_MIN = 55;       // one busy process's games a minute (16 of them: about 880)
const BIG_BOARD_GAMES_PER_MIN = 14.5;   // ... when both decks fill the board with tokens (16: about 230)
const COMMANDER_GAMES_PER_MIN = [23, 12];   // one process's Commander games a minute: few going, 16 going
const LIST_POLL = 2;                    // the list page asks every LIST_POLL × POLL_MS while a run goes
const IDLE_MATCHUP_POLL_MS = 15000;      // discover games started on another device while this page is idle
const MAX_BACKOFF = 5;                  // while the PC doesn't answer, ask at most every MAX_BACKOFF × POLL_MS
// After the matchup page is drawn afresh, the first of these on it gets the focus (focusNews).
const NEWS_IDS = ["mu-error", "mu-notice", "h-live", "h-result", "h-not-played"];
const SIDE_KIND_WORDS = { casual: "Casual", commander: "Commander", product: "Product deck", pairing: "Beginner Box pairing" };
const SEAT_BLOCK = 25;                  // the card log's engine swaps the decks' seats every this many games (forge/seeds.py)
// A deck Forge's AI plays with its auto-profile on (forge's side "auto_profile"), as cli.AUTO_PROFILE_WORDS says it.
const AUTO_PROFILE_WORDS = "Forge's AI plays this deck as a slower, non-aggro deck in every game";
const NEW_ENGINE_WORDS = "Playing more starts a new result with today's engine; this one stays as it is.";
const QUICK_GAMES = 200;                // a Quick look's games (the smallest of forge.GAME_CHOICES)
const AHEAD_LOOKS = [400, 800, 1600, 3200];     // Settle it's planned checks (forge/seqstats.py's HP_LOOKS)
// Who started a run, when it wasn't a person: the replays, the command line and Claude's checks aren't shown (MU-07).
const NOT_A_PERSON = /^(replay|command line|claude\b)/i;
let gamesChoiceIds = 0;                 // ids for the games choices' labels
let matchupRefresh = null;              // the current route's single refresh loop


// ------------------------------------------------------------------ helpers

function isLive(data) { return data.status === "queued" || data.status === "running"; }

/** "Boros Burn", or "Boros Burn (play-now list)" for the owned version (core.js listName). */
function sideTitle(side) { return side.title + (side.version === "owned" ? ` (${listName("owned", true)})` : ""); }

/** Both sides' titles, told apart in a mirror match ("Boros Burn (deck 1)"). */
function sideTitles(sides) {
  const [ta, tb] = sides.map(sideTitle);
  return ta === tb ? [`${ta} (deck 1)`, `${tb} (deck 2)`] : [ta, tb];
}

/** A deck's title, shorter, for a matrix header or a verdict: a product's "(Bloomburrow Starter Kit)" goes, and a
 * Commander deck's "Commander, Epithet: Theme" is its commander's name ("Krenko, Mob Boss: Goblin Horde
 * (upgraded)" -> "Krenko"). */
function shortTitle(title) {
  let t = String(title || "").replace(/\s*\([^)]*\)\s*$/, "");
  const colon = t.indexOf(": ");
  // A Commander deck's "Commander, Epithet: Theme": the commander's first name ("Krenko").
  if (colon > 0) t = t.slice(0, colon).split(", ")[0];
  return t || String(title || "");
}

/** A side's short title, with "(play-now)" for its owned list. */
function sideShort(side) { return shortTitle(side.title) + (side.version === "owned" ? " (play-now)" : ""); }

function matchupHref(a, b) {
  return `#/matchup?a=${encodeURIComponent(a.id)}&av=${a.version || "target"}` +
    `&b=${encodeURIComponent(b.id)}&bv=${b.version || "target"}`;
}

/** Was a saved result (a ListItem, or a matchup answer's result) played with another engine than today's
 * (forge's "engine": its "current" is false)? Older servers send no engine: then it's today's. */
function earlierEngine(item) { return !!(item && item.engine && item.engine.current === false); }

/** A saved result's or a run's page: by the decks while both lists are the ones played and the result is
 * today's engine's (so the first deck stays first), else by its key (the decks' page would show today's
 * lists with today's engine, not played yet). */
function itemHref(item) {
  const [a, b] = item.sides;
  if (a.current !== false && b.current !== false && a.id && b.id && !earlierEngine(item)) return matchupHref(a, b);
  return `#/matchup?key=${encodeURIComponent(item.key)}`;
}

/** A matchup page's address by its key. */
function keyHref(key) { return `#/matchup?key=${encodeURIComponent(key)}`; }

/** Whether the viewer may start a Forge run now (version.js's simulationsGate; yes when it isn't loaded, as the
 * server checks every start anyway), and the gate itself ({may, why}). */
function runsAllowed() { return typeof mayStartRuns !== "function" || mayStartRuns(); }
function runGate() { return typeof simulationsGate === "function" ? simulationsGate() : { may: true, why: null }; }

/** Who started a run, when it's a person ("Sam"); null for the replays, the command line and Claude's
 * checks (MU-07). */
function personName(by) {
  if (!by || NOT_A_PERSON.test(by)) return null;
  const names = (state.profiles || []).map((p) => p.name);
  return !names.length || names.includes(by) ? by : null;
}

/** A row's facts as one string ("1,600 games · Sam · 4 Oct"), so a wrapped line never starts with "·". */
function metaWords(...parts) { return parts.filter(Boolean).join(" · "); }

/** How the PC splits a run into batches: {workers} from the server's answer (its config.json's
 * forge_workers) when it sends it, else the usual 16. */
function batching(data) {
  return { workers: Number(data && data.workers) || FORGE_WORKERS };
}

/** forge.plan's batches for a run of games on `workers` Forge processes, {batches, size}, as
 * forge/lists.py's _batch_count splits it: the largest even number of batches, at least 2 and at most
 * min(workers, games / SMALL_BATCH) rounded down, that divides the games; 1 batch when 2 doesn't. */
function batchPlan(games, workers) {
  const cap = Math.max(2, Math.min(workers, Math.floor(games / SMALL_BATCH)));
  for (let count = cap - cap % 2; count >= 2; count -= 2) {
    if (games % count === 0) return { batches: count, size: games / count };
  }
  return { batches: 1, size: games };
}

/** The rough time a run of this many games takes, in minutes: [usually, at worst]. Each of
 * batchPlan's batches is one Forge process, up to `workers` at once, so the time follows the games
 * each process plays. At worst: big boards, or for Commander, a busy PC. */
function roughMinutes(games, commander = false, { workers = FORGE_WORKERS } = {}) {
  const { batches } = batchPlan(games, workers);
  const each = games / Math.min(workers, batches);
  const [usual, slow] = commander ? COMMANDER_GAMES_PER_MIN : [PROCESS_GAMES_PER_MIN, BIG_BOARD_GAMES_PER_MIN];
  return [each / usual, each / slow];
}

/** A set number of games' one time estimate without the server's (roughMinutes): "about 1-4 minutes". */
function roughTimeWords(games, commander = false, split) {
  return estimateWords(roughMinutes(games, commander, split));
}

/** 55 -> "55 s", 200 -> "3 min 20 s", 1500 -> "25 min". */
function durationWords(s) {
  if (s == null || Number.isNaN(s)) return "?";
  if (s < 60) return `${Math.max(1, Math.round(s))} s`;
  const whole = Math.round(s);
  const m = Math.floor(whole / 60), rest = whole % 60;
  if (m < 10) return rest ? `${m} min ${rest} s` : `${m} min`;
  if (m < 60) return `${Math.round(s / 60)} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** "2026-10-01T13:05:12" (the PC's time) -> "1 Oct, 1:05 pm" (with the year when it isn't this one). */
function momentWords(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const opts = { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleString("en-AU", opts);
}

/** 3200 -> "3,200 games". */
function gamesWords(n) { return `${thousands(n || 0)} game${n === 1 ? "" : "s"}`; }

function rateWords(rate) { return rate && rate.value != null ? pct(rate.value) : "?"; }

function rangeWords(rate) {
  return rate && rate.low != null && rate.high != null ? `${pct(rate.low)} to ${pct(rate.high)}` : "unknown";
}

/** A box about a problem or news, with its status icon before the heading (components.css .box-head), so
 * its kind never rests on colour alone. kind: "crit", "warn" or "info"; level: "h2" or "h3"; content:
 * what goes under the heading; props: more of the box's own (id, role). */
function markedBox(kind, level, heading, content, props = {}) {
  return el("div", { ...props, class: `box box-${kind}` }, el(level, { class: "box-head", text: heading }), content);
}


// ------------------------------------------------------------ verdicts in words

/** The plain verdict of a result, for anyone (MU-04): "Boros Burn is a big favourite: wins about 9 in
 * 10". result: a matchup's result or a ListItem ({winrate, lead?, not_meaningful}); titles: the two sides'
 * names, the first being the win rate's. {text, kind}: kind "win" or "loss" (the first deck's side of it),
 * "even", "open" (not settled yet) or "none" (the results mean nothing). A ListItem has no lead: then the
 * win rate alone decides, with 45-55% "about even". */
function plainVerdict(result, titles) {
  const [ta, tb] = titles;
  const value = result && result.winrate ? result.winrate.value : null;
  if (result && result.not_meaningful) return { text: "These games don't say anything about the real decks", kind: "none" };
  if (value == null) return { text: "No games counted yet", kind: "open" };
  const lead = result.lead || null;
  let side;
  if (lead && lead.verdict === "about_even") side = null;
  else if (lead && lead.verdict === "not_settled") {
    return { text: `Too close to call so far: ${ta} has won ${pctShort(value)} of the games`, kind: "open" };
  } else if (lead && (lead.side === 0 || lead.side === 1)) side = lead.side;
  else side = Math.abs(value - 0.5) < 0.05 ? null : value > 0.5 ? 0 : 1;
  if (side == null) return { text: "These two are about even: each wins about half the games", kind: "even" };
  const leader = side === 0 ? ta : tb;
  const share = side === 0 ? value : 1 - value;
  return { text: `${leader} ${favouriteWords(share)}`, kind: side === 0 ? "win" : "loss" };
}

/** "is a big favourite: wins about 9 in 10" for the leader's share of the games (0.5 to 1). */
function favouriteWords(share) {
  const tenths = Math.round(share * 10);
  const often = share >= 0.95 ? "wins nearly every game" : `wins about ${tenths} in 10`;
  if (share >= 0.8) return `is a big favourite: ${often}`;
  if (share >= 0.6) return `is the favourite: ${often}`;
  if (share >= 0.56) return `has the edge: ${often}`;
  return "has a slight edge: wins a little over half the games";
}


// ------------------------------------------------------------ progress

/** A progress bar marked at a run's planned checks (MU-11): {node, set(done, total, checks)}, done and total in
 * games of the whole result, checks the games of each planned check (Settle it's 400, 800, 1,600 and 3,200),
 * each a tick on the bar, so the bar fills once towards the last check instead of dropping back at each. */
function checkBar(label, tag = "div") {
  const bar = progressBar(label, tag);
  bar.node.setAttribute("class", `${bar.node.getAttribute("class")} mu-checkbar`);
  const ticks = el("span", { class: "mu-checks", "aria-hidden": "true" });
  bar.node.append(ticks);
  return {
    node: bar.node,
    set(done, total, checks = []) {
      bar.set(total ? done / total : 0);
      clear(ticks).append(...checks.filter((n) => total && n > 0 && n < total).map((n) =>
        el("span", { class: "mu-check" + (done >= n ? " is-passed" : ""), style: `left: ${(100 * n) / total}%` })));
    },
  };
}

/** A run's progress over the whole result, from its job or Running item (done and total of this run, and an
 * adaptive run's plan: games_before, planned, max, next_look): {done, total, checks, approx, next}. approx: the
 * total is the plan so far (Precise plans more after its first check), shown as "~1,100". */
function runProgress(job) {
  const plan = job && job.plan;
  const done = (job && job.done) || 0;
  if (!plan) return { done, total: (job && job.total) || 0, checks: [], approx: false, next: null };
  const before = plan.games_before || 0;
  const max = plan.max || AHEAD_LOOKS[AHEAD_LOOKS.length - 1];
  if (plan.mode === "ahead") {
    return { done: before + done, total: max, checks: AHEAD_LOOKS.filter((n) => n <= max), approx: false,
      next: plan.next_look || null };
  }
  const planned = Math.max(plan.planned || 0, before + done);
  return { done: before + done, total: planned, checks: planned > 400 ? [400] : [], approx: true, next: null };
}


// ------------------------------------------------------------- run choice

/** A segmented choice of how long to play (the run vocabulary: Quick look, Settle it, Precise) with one line
 * under it: the picked option's description and its one time estimate. options: [{id, title, sub, time}] (time
 * a phrase like "about 2-6 minutes", or null); value: the id picked (null while "More options" holds the
 * choice); onPick(id). Returns {node, set(id)}. */
function runChoiceControl(options, value, onPick, { label = "How long to play" } = {}) {
  const id = `run-choice-${++gamesChoiceIds}`;
  const line = el("p", { class: "rough-time", "aria-live": "polite" });
  const buttons = options.map((o) => el("button", { type: "button", text: o.title, onclick: () => pick(o.id) }));
  let current = value;
  function show() {
    buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(options[i].id === current)));
    const o = options.find((x) => x.id === current);
    line.textContent = o ? [o.sub, o.time ? `${capitalise(o.time)}.` : null].filter(Boolean).join(" ") : "";
    line.hidden = !line.textContent;
  }
  function pick(next) {
    if (next === current) return;
    current = next;
    show();
    if (onPick) onPick(next);
  }
  show();
  const node = el("div", { class: "mu-run-choice" },
    el("span", { class: "games-label", id, text: label }),
    el("div", { class: "segmented mu-run-buttons", role: "group", "aria-labelledby": id }, buttons),
    line);
  // redraw(): the options' words (a time estimate) have changed in place.
  return { node, set(next) { current = next; show(); }, redraw: show };
}

/** The number of games to play: a row of buttons with its one time estimate under it. Choosing one saves it as
 * the profile's usual number (saveGames) and calls onChange(games). commander: the time is for Commander games
 * (setCommander changes it); split: how the PC splits a run (batching()); estimates: the server's for each count.
 * unpick() shows none chosen (another run choice holds it); a press picks again. */
function gamesChoice(choices, start, onChange, { label = "Games to play", commander = false, split, estimates } = {}) {
  const list = choices && choices.length ? choices : [200, 400, 800, 1600, 3200];
  let games = list.includes(start) ? start : list[Math.floor(list.length / 2)];
  let picked = true;
  const time = el("p", { class: "rough-time", "aria-live": "polite" });
  const buttons = list.map((n) => el("button", { type: "button", text: thousands(n), onclick: () => pick(n) }));
  function show() {
    buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(picked && list[i] === games)));
    // The server's estimate (forge/estimate.py) when it sends one; else the rough time from Milestone 0's speeds.
    const span = estimates && estimates[String(games)];
    time.textContent = picked ? `${capitalise(span ? estimateWords(span) : roughTimeWords(games, commander, split))}.` : "";
    time.hidden = !picked;
  }
  function pick(n) {
    if (n === games && picked) return;
    games = n;
    picked = true;
    show();
    saveGames(n);
    if (onChange) onChange(n);
  }
  show();
  const id = `games-label-${++gamesChoiceIds}`;
  const node = el("div", { class: "games-pick" },
    el("span", { class: "games-label", id, text: label }),
    el("div", { class: "segmented", role: "group", "aria-labelledby": id }, buttons),
    time);
  return { node, value: () => games, setCommander(on) { commander = !!on; show(); },
    setEstimates(next) { estimates = next; show(); },
    unpick() { picked = false; show(); } };
}

/** The games choice to start from: the one chosen last on this page, else the server's (the profile's). */
function startingGames(data) {
  return state.matchupGames || Number(data.default_games) || 800;
}

async function saveGames(n) {
  state.matchupGames = n;
  const profile = state.profile;
  if (!profile) return;
  try {
    await apiWrite(`/api/profiles/${encodeURIComponent(profile.id)}/settings`, { matchup_games: String(n) }, "PUT");
  } catch (e) {
    toast(`${profile.name}'s usual number of games couldn't be saved: ${e.message}`);
  }
}

// The run vocabulary (MU-05) for a matchup: each choice's server mode (forge/adaptive.py's, sim-wave3-contract.md
// section 9.4) and words. A set number of games is the fourth, under "More options".
const RUN_CHOICES = [
  { id: "quick", mode: "fixed", title: "Quick look", sub: `${QUICK_GAMES} games: a first idea.` },
  { id: "settle", mode: "ahead", title: "Settle it",
    sub: "Plays until one deck is clearly ahead, or they're about even (checks at 400, 800, 1,600 and 3,200 games)." },
  { id: "precise", mode: "assess", title: "Precise",
    sub: "Plays until the win rate is known to within 3 points either way (usually 700-1,100 games)." },
];
// The server's modes (forge/adaptive.py), as startingMode reads the profile's "matchup_mode".
const RUN_MODES = ["assess", "ahead", "fixed"];
// What a joined run plays until (run_matchup's "joined"), for "Joined the run already playing (...)".
const MODE_UNTIL = { assess: "Precise: until the win rate is known to within 3 points", ahead: "Settle it: until " +
  "one deck is clearly ahead, or they're about even", fixed: null };

/** [low, high] minutes (forge/estimate.py) in words: "under a minute", "about 2-6 minutes", "about 1-2 hours". */
function estimateWords(span) {
  if (!Array.isArray(span) || span.length !== 2) return null;
  const [low, high] = span.map(Number);
  if (!(high >= 0)) return null;
  if (high < 1) return "under a minute";
  if (low >= 90) {
    const a = Math.round(low / 60), b = Math.max(a, Math.round(high / 60));
    return a === b ? `about ${a} hour${a === 1 ? "" : "s"}` : `about ${a}-${b} hours`;
  }
  const a = Math.max(1, Math.round(low)), b = Math.max(a, Math.round(high));
  if (b >= 90) return `about ${a} minutes to ${Math.round(high / 60)} hours`;
  return a === b ? `about ${a} minute${a === 1 ? "" : "s"}` : `about ${a}-${b} minutes`;
}

/** The mode to start from: the one chosen last on this device, else the profile's (read on the Matchups
 * page, or the matchup answer's "default_mode"), else "assess". */
function startingMode(data) {
  for (const mode of [state.matchupMode, data && data.default_mode]) {
    if (RUN_MODES.includes(mode)) return mode;
  }
  return "assess";
}

async function saveMode(mode) {
  state.matchupMode = mode;
  const profile = state.profile;
  if (!profile) return;
  try {
    await apiWrite(`/api/profiles/${encodeURIComponent(profile.id)}/settings`, { matchup_mode: mode }, "PUT");
  } catch (e) {
    toast(`${profile.name}'s usual kind of run couldn't be saved: ${e.message}`);
  }
}

/** "How long to play": Quick look, Settle it or Precise (runChoiceControl), with one time estimate from the
 * answer's "estimates", and a set number of games (gamesChoice) under "More options". The profile's mode and
 * games pick the first choice (a set 200 games is a Quick look); a pick saves them. onChange() after any
 * change. value(): {mode, games} (games only for "fixed"). setCommander(on) and setEstimates(estimates,
 * commander) change every time shown (the play sheet's, as its decks change). */
function runModeChoice(data, onChange) {
  let estimates = data.estimates || null;
  let commander = data.format === "Commander";
  const split = batching(data);
  const mode = startingMode(data);
  const start = startingGames(data);
  let choice = mode === "ahead" ? "settle" : mode === "assess" ? "precise" : start === QUICK_GAMES ? "quick" : "custom";
  const games = gamesChoice(data.choices, start, () => {
    choice = "custom";
    control.set(null);
    saveMode("fixed");
    if (onChange) onChange();
  }, { commander, split, estimates: estimates && estimates.fixed, label: "A set number of games" });
  const timeOf = (id) => {
    if (id === "quick") {
      const span = estimates && estimates.fixed && estimates.fixed[String(QUICK_GAMES)];
      return span ? estimateWords(span) : roughTimeWords(QUICK_GAMES, commander, split);
    }
    if (estimates) return estimateWords(estimates[id === "settle" ? "ahead" : "assess"]);
    // Without the server's (the Matchups page's sheet): Milestone 0's speeds, from the first check to the last.
    const [few, many] = id === "settle" ? [400, 3200] : [700, 1100];
    return estimateWords([roughMinutes(few, commander, split)[0], roughMinutes(many, commander, split)[1]]);
  };
  const options = RUN_CHOICES.map((c) => ({ ...c, time: timeOf(c.id) }));
  function retime() {
    for (const o of options) o.time = timeOf(o.id);
    control.redraw();
  }
  const control = runChoiceControl(options,
    choice === "custom" ? null : choice, (id) => {
      choice = id;
      games.unpick();
      const picked = RUN_CHOICES.find((c) => c.id === id);
      saveMode(picked.mode);
      if (id === "quick") saveGames(QUICK_GAMES);
      if (onChange) onChange();
    });
  if (choice !== "custom") games.unpick();
  const more = el("details", { class: "more mu-more-options", open: choice === "custom" || null },
    el("summary", { text: "More options" }), games.node);
  return {
    node: el("div", { class: "mu-modes" }, control.node, more),
    value() {
      if (choice === "custom") return { mode: "fixed", games: games.value() };
      const picked = RUN_CHOICES.find((c) => c.id === choice);
      return { mode: picked.mode, games: picked.mode === "fixed" ? QUICK_GAMES : null };
    },
    setCommander(on) {
      if (commander === !!on) return;
      commander = !!on;
      games.setCommander(on);
      retime();
    },
    setEstimates(next, on) {
      estimates = next || null;
      commander = !!on;
      games.setCommander(on);
      games.setEstimates(estimates && estimates.fixed);
      retime();
    },
  };
}

/** An adaptive run's summary (result.adaptive_last, forge/adaptive.py) in a sentence, as
 * adaptive.words says it on the command line: why the run stopped. lead is the result's (the summary's
 * decision from the page's side), titles the page's two. null without a summary. */
function adaptiveWords(summary, lead, titles) {
  if (!summary) return null;
  const n = gamesWords(summary.games_after || 0);
  const leader = lead && (lead.side === 0 || lead.side === 1) ? titles[lead.side] : null;
  const width = summary.half_width != null ? `±${(100 * summary.half_width).toFixed(1)} points` : null;
  if (summary.outcome === "stopped") {
    const r = summary.range;
    const span = r && r.low != null ? ` A range that allows for stopping at any time: ${Math.round(100 * r.low)}-` +
      `${Math.round(100 * r.high)} %.` : "";
    const decided = summary.decision === "ahead" || summary.decision === "slightly_ahead";
    const verdict = decided && leader ? ` ${leader} is clearly ahead even so.`
      : summary.decision === "about_even" ? " The decks are about even even so (within 5 points of win rate)."
        : " Not settled.";
    return `Stopped early after ${n}, between checks.${span}${verdict}`;
  }
  if (summary.outcome === "error") return `This run stopped after ${n} because of an error.`;
  const head = `This run stopped at a planned check after ${n}`;
  switch (summary.outcome) {
    case "ahead": return leader ? `${head}: ${leader} is clearly ahead.` : `${head}.`;
    case "slightly_ahead": return leader ? `${head}: ${leader} is slightly ahead (by under 5 points).` : `${head}.`;
    case "about_even": return `${head}: the decks are about even (within 5 points of win rate).`;
    case "not_settled": return `${head}: it reached ${n} without a clear leader.`;
    case "precise": return `${head}: the win rate is known to within ${width || "±3 points"} of win rate.`;
    case "capped": case "capped_at_plan":
      return `${head}: it played as many games as planned${width ? ` (to within ${width} of win rate)` : ""}.`;
    default: return null;
  }
}

/** The small print under adaptiveWords: the last look's z and the bound it needed. */
function adaptiveDetails(summary) {
  const looks = (summary && summary.looks) || [];
  const last = looks[looks.length - 1];
  if (!last || last.z == null || last.bound == null) return null;
  return `z = ${Math.abs(last.z).toFixed(2)}; needed ${last.bound.toFixed(2)}`;
}

/** A sentence's first letter in lower case ("Field run of X" -> "field run of X"). */
function lowerFirst(text) { return text ? text[0].toLowerCase() + text.slice(1) : ""; }


// ------------------------------------------------------------ AI limits

/** What Forge's AI can't do with one list (AiLimits), for its deck: boxes and card names. brief: the
 * page already says the results mean nothing (a commander never cast), so a chip says it here.
 * deckPage: ai is the deck page's, judged by every saved game of this list (forge.list_ai), not by one
 * matchup's. Cards never cast are only judged from NEVER_CAST_GAMES games (ai.games), so until then it
 * says what was checked rather than that the AI can play every card. An all-clear is a plain sentence, never a
 * chip (chips are for exceptions). earlier: what the list's earlier engine's games showed ({commander: true}:
 * its commander was never cast there), said in place of an all-clear until today's engine has checked it.
 * otherSaid: the page already says, once, that this list's games were all an earlier engine's. */
function aiLimitsParts(ai, title, { brief = false, deckPage = false, earlier = null, otherSaid = false } = {}) {
  if (!ai) return [];
  const parts = [];
  const cannot = ai.cannot_play || [];
  const games = Number(ai.games) || 0;
  const whose = `${deckPage ? "this list's" : "this matchup's"} ${gamesWords(games)}`;
  const whyWords = {
    script: "Forge's card script tells its AI not to use it, so it never casts it",
    never_cast: `Cast 0 times in ${whose}${deckPage ? ", across all its matchups" : ""}`,
  };
  if (ai.commander_unplayable && brief) {
    parts.push(el("p", {}, status("crit", "Commander never cast"), " So this deck's results mean nothing."));
  } else if (ai.commander_unplayable) {
    parts.push(markedBox("crit", "h3", "Forge's AI never casts the commander",
      el("p", { text: `${title} plays every game without its commander, because Forge's card script tells ` +
        "its AI not to cast it. So Forge's results for this deck mean nothing about the real deck." })));
  }
  if (ai.unknown && ai.unknown.length) {
    parts.push(markedBox("crit", "h3", "Cards Forge doesn't know", [
      el("p", { text: "Forge has no card script for these names, so it can't play this list until they're fixed:" }),
      cardNames(ai.unknown)]));
  }
  for (const why of ["script", "never_cast"]) {
    const cards = cannot.filter((c) => c.why === why);
    if (!cards.length) continue;
    // With card data, a card never cast also says how often it was drawn (forge.ai's drawn_games).
    const drawn = why === "never_cast" && cards.some((c) => c.drawn_games != null);
    parts.push(el("div", { class: "ai-cards" },
      el("p", {}, status("warn", why === "script" ? "The AI can't play" : "Never cast"), " ", whyWords[why] + ":"),
      drawn ? neverCastNames(cards) : cardNames(cards.map((c) => ({ name: c.name, qty: c.qty })))));
  }
  // The team pump spells Scryfall's oracle tags name, only when Forge's card scripts can't be read (no
  // ai.pilot): otherwise pilotFlag's box gives the scripts' count, split into spells and abilities, as
  // the command line's audit does.
  const pump = ai.pilot ? null : ai.team_pump;
  if (pump && pump.copies) {
    parts.push(markedBox("warn", "h3", "Built around team pump spells", [
      el("p", { text: `${plural(pump.copies, "copy", "copies")} of spells that pump the whole team. Forge's AI ` +
        "holds these back and attacks too little, so it rates go-wide pump decks too low. In Deck Lab's " +
        "tests, Forge rated a go-wide pump deck 12 to 15 points too low for this reason." }),
      cardNames(pump.cards || [])]));
  }
  const judged = games >= NEVER_CAST_GAMES;
  // A list pilotFlag's box flags: its cards get cast, but a green "can play every card" under that box
  // read as if the flag were wrong.
  const poor = Boolean(ai.pilot && ai.pilot.poor);
  if (!parts.length && !ai.problem && earlier && earlier.commander) {
    parts.push(el("p", {}, status("warn", "Earlier games: commander never cast"), " Forge's AI never cast this " +
      "deck's commander in its games with an earlier engine. Not checked with today's engine yet."));
  } else if (!parts.length && !ai.problem && poor) {
    parts.push(el("p", {}, status("info", judged ? "Every card cast" : "Nothing held back"), judged
      ? ` None is held back by its card scripts, and every spell was cast in ${whose}, though not always well.`
      : " Forge's card scripts don't stop its AI from casting any of these cards, though it doesn't play them " +
        "all well."));
  } else if (!parts.length && !ai.problem) {
    parts.push(judged
      ? el("p", {}, el("b", { text: "Forge's AI can play every card." }),
        ` None is held back by its card scripts, and every spell was cast in ${whose}.`)
      : el("p", {}, el("b", { text: "Nothing held back." }),
        " Forge's card scripts don't stop its AI from playing any of these cards."));
  }
  if (!judged) {
    // The deck page's games of this list played with another engine (forge.list_ai's other_engine_games) don't
    // count, so a list with thousands of them says why it still waits.
    const other = deckPage && !otherSaid ? Number(ai.other_engine_games) || 0 : 0;
    const sofar = [games ? `${thousands(games)} so far` : "", other ? `${thousands(other)} more ` +
      `${other === 1 ? "was" : "were"} played with an earlier engine, or without the card log, and ` +
      `${other === 1 ? "doesn't" : "don't"} count` : ""].filter(Boolean).join("; ");
    parts.push(el("p", { class: "sub", text: "Cards it never casts show up here once " +
      `${deckPage ? "this list has played" : "this matchup has"} ${NEVER_CAST_GAMES} games` +
      (other ? " with today's engine" : "") + (sofar ? ` (${sofar}).` : ".") }));
  }
  if (ai.problem) parts.push(el("p", { class: "sub", text: `Not checked fully: ${ai.problem}` }));
  return parts;
}

/** Cards never cast, each with how often it was drawn in the games with card data: "drawn in 54 games,
 * never cast" (a card drawn and never cast is one the AI held; one never drawn just never came up). */
function neverCastNames(cards) {
  return el("ul", { class: "card-names drawn-names" }, cards.map((c) => el("li", {},
    cardLink({ name: c.name, qty: c.qty }),
    c.drawn_games == null ? null : el("span", { class: "drawn-n",
      text: c.drawn_games ? `drawn in ${gamesWords(c.drawn_games)}, never cast` : "never drawn" }))));
}

/** A side's AI limits as status chips, for the matchup page's deck boxes. */
function aiChips(ai, notCurrent) {
  const chips = [];
  if (notCurrent) chips.push(status("warn", "Older list"));
  if (!ai) return chips;
  if (ai.commander_unplayable) chips.push(status("crit", "Commander never cast"));
  const n = (ai.cannot_play || []).reduce((sum, c) => sum + (c.qty || 1), 0);
  if (n) chips.push(status("warn", `${plural(n, "card")} the AI can't play`));
  // A team pump deck as pilotFlag's box judges it; the oracle tags only when the scripts can't be read.
  const pumps = ai.pilot ? ai.pilot.poor && ai.pilot.why === "team_pumps" : ai.team_pump && ai.team_pump.copies;
  if (pumps) chips.push(status("warn", "Team pump deck"));
  if (ai.unknown && ai.unknown.length) chips.push(status("crit", "Unknown cards"));
  return chips;
}
