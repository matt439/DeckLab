/* The Testing page's "Popular decks" view (E3-S35): every deck the viewer may see, each its standing against its
format's standard sample of popular decks (GET /api/gauntlet/board: E3-S33's headline and E3-S34's out-of-date
states, worked out from saved games only), best first, each with Details (its deck page's Testing tab, at the
popular-decks part) and its own Play of the standard sample. Not a rating, and kept apart from Rankings.

The Testing page's views (matchups-overview.js drawMatchups and drawHome): Popular decks (the default), Matchups and
Rankings, kept in the address (?view=) and on this device (HOME_VIEW_KEY). drawHome hands its section to gbDraw for
Popular decks, the list watcher's checks to gbRefresh, and a pause to gbCancel.

The board's read is single-flight with a deadline, and dropped when the page, the profile or the view has moved on.
It reads again when a run starts or ends (the watcher's running list), every GB_POLL_MS while a row plays, and on a
view or format change. Before a Play it never plans or estimates: the deck's Testing tab says how long. A read
that starts redraws only when nothing of its format is on screen yet, and a redraw puts the keyboard focus back on
the same row's Details or Play (or its Details when its Play has gone: it's playing now).

Loaded after gauntlet.js (gtBeforeLine, gtOlderLine, gtFigureWords) and sim-ui.js (winRateFigure, rangeBar,
freshnessBadge); editor.js supplies ask().
*/
"use strict";

const GB_VIEWS = ["popular", "matchups", "rankings"];
const GB_FORMAT_KEY = "testing.popularFormat";   // local storage: the board's format
const GB_FORMATS = [["commander", "Commander"], ["constructed", "60-card"]];
const GB_SOURCES = { commander: "EDHREC averages and precons", constructed: "Forge's own precons and duels" };
const GB_POLL_MS = 30000;        // how often the board is read again while a row plays
const GB_DEADLINE_MS = 30000;    // a cold board may take a while on the PC

/** The view the Testing page opens on: the address's ?view=, else the one chosen last on this device, else
 * Popular decks. */
function gbInitialView(params) {
  const asked = params && params.get("view");
  if (GB_VIEWS.includes(asked)) return asked;
  const kept = local.get(HOME_VIEW_KEY);
  return GB_VIEWS.includes(kept) ? kept : "popular";
}

/** Keep the chosen view in the address (without the one-shot play sheet's a, av, b and bv) and on this device. */
function gbWriteView(mode) {
  local.set(HOME_VIEW_KEY, mode);
  if (typeof history !== "undefined" && history.replaceState) history.replaceState(history.state, "", `#/matchups?view=${mode}`);
}

function gbFormatWords(format) { return (GB_FORMATS.find(([f]) => f === format) || GB_FORMATS[0])[1]; }

/** True while the view's board is still the one on screen for this route and profile. */
function gbHere(view) {
  return view.mode === "popular" && view.token === routeToken && view.profile === state.profile?.id &&
    !!view.gbHost && view.gbHost.isConnected;
}

/** Draw Popular decks into drawHome's section: the format control in head, then the board. */
function gbDraw(section, view, head) {
  view.token ??= routeToken; view.profile ??= state.profile?.id;
  view.gbEntries ||= new Map();
  if (!GB_FORMATS.some(([f]) => f === view.gbFormat)) {
    const kept = local.get(GB_FORMAT_KEY);
    view.gbFormat = GB_FORMATS.some(([f]) => f === kept) ? kept : GB_FORMATS[0][0];
  }
  head.append(el("div", { class: "segmented gb-format", role: "group", "aria-label": "Format" },
    GB_FORMATS.map(([format, words]) => el("button", { type: "button", text: words,
      "aria-pressed": String(format === view.gbFormat), onclick: (e) => {
        if (view.token !== routeToken || view.profile !== state.profile?.id) return;
        view.gbFormat = format; local.set(GB_FORMAT_KEY, format);
        for (const b of e.currentTarget.parentNode.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b === e.currentTarget));
        gbRefresh(view, null, { force: true });
      } }))));
  view.gbHost = el("div", { class: "gb" });
  section.append(view.gbHost);
  gbDrawEntry(view, view.gbEntries.get(view.gbFormat) || { answer: null, error: null });
  gbRefresh(view);
}

/** The runs waiting or playing, as one string: it changes when a run starts or ends, not as games are played. */
function gbRunning(fresh) {
  return JSON.stringify((fresh && fresh.running || []).map((r) => `${r.id || r.link || r.title || ""}|${r.status || ""}`));
}

/** Read the board again when it's needed: forced, never read, a run started or ended (fresh: the list watcher's
 * answer), or a row playing and GB_POLL_MS gone. One read at a time; a later need reads again after it. */
async function gbRefresh(view, fresh = null, { force = false } = {}) {
  if (fresh) {
    const running = gbRunning(fresh);
    if (view.gbRunningSeen !== undefined && view.gbRunningSeen !== running) force = true;
    view.gbRunningSeen = running;
  }
  if (!gbHere(view)) return;
  const format = view.gbFormat;
  const entry = view.gbEntries.get(format) || { answer: null, error: null, asked: 0 };
  view.gbEntries.set(format, entry);
  if (view.gbRequest) {
    const other = view.gbRequest.format !== format;
    view.gbAgain ||= force || other;
    if (other) gbDrawEntry(view, entry);
    return;
  }
  const playing = (entry.answer?.rows || []).some((r) => r.playing);
  if (!(force || !entry.asked || (playing && Date.now() - entry.asked >= GB_POLL_MS))) return;
  const controller = new AbortController();
  let rejectRead;
  const cancelled = new Promise((resolve, reject) => { rejectRead = reject; });
  const request = { format, token: view.token, profile: view.profile, cancelled: false, timedOut: false,
    abort(timedOut = false) {
      if (request.cancelled) return;
      request.cancelled = true; request.timedOut = timedOut; controller.abort();
      rejectRead(new Error(timedOut ? "The PC took too long to answer." : "Read cancelled."));
    } };
  const deadline = setTimeout(() => request.abort(true), GB_DEADLINE_MS);
  view.gbRequest = request; entry.asked = Date.now(); entry.loading = true;
  if (!entry.answer && !entry.error) gbDrawEntry(view, entry);
  try {
    const answer = await Promise.race([api(`/api/gauntlet/board?format=${encodeURIComponent(format)}`,
      { signal: controller.signal }), cancelled]);
    if (request.token !== routeToken || request.profile !== state.profile?.id || request.cancelled) return;
    if (!answer || answer.format !== format) throw new Error("The PC answered for a different format. Try again.");
    entry.answer = answer; entry.error = null;
  } catch (error) {
    if (request.cancelled && !request.timedOut) entry.asked = 0;
    if (request.token !== routeToken || request.profile !== state.profile?.id || (request.cancelled && !request.timedOut)) return;
    entry.error = request.timedOut ? "The PC took too long to answer." : error.message || String(error);
  } finally {
    clearTimeout(deadline);
    entry.loading = false;
    if (view.gbRequest === request) view.gbRequest = null;
    if (gbHere(view)) {
      if (view.gbAgain || view.gbFormat !== format) { view.gbAgain = false; gbRefresh(view, null, { force: true }); }
      else { gbDrawEntry(view, entry); gbSchedule(view, entry); }
    }
  }
}

/** While a row plays, read again in GB_POLL_MS. */
function gbSchedule(view, entry) {
  clearTimeout(view.gbTimer);
  view.gbTimer = null;
  if (!(entry.answer?.rows || []).some((r) => r.playing)) return;
  view.gbTimer = setTimeout(() => { view.gbTimer = null; gbRefresh(view); }, GB_POLL_MS);
}

/** Stop reading: the view, the page or the profile changed, or the list watcher paused. */
function gbCancel(view) {
  clearTimeout(view.gbTimer);
  view.gbTimer = null;
  view.gbAgain = false;
  if (view.gbRequest) { const request = view.gbRequest; view.gbRequest = null; request.abort(); }
}

/** The board for the entry's format: loading, why it failed (with Try again), or the rows. */
function gbDrawEntry(view, entry) {
  const host = view.gbHost;
  if (!host) return;
  const a = entry.answer, words = gbFormatWords(view.gbFormat);
  const failed = entry.error ? loadFailed("Popular decks", { message: entry.error },
    () => gbRefresh(view, null, { force: true })) : null;
  const focused = host.contains(document.activeElement) ? document.activeElement.dataset.focus : null;
  const draw = () => {
    clear(host);
    if (!a || a.format !== view.gbFormat) {
      host.append(failed || loadingBox(`Loading popular ${words} decks…`)); return;
    }
    add(host, [failed, gbBoard(view, a, words)]);
  };
  typeof keepPlace === "function" ? keepPlace(draw) : draw();
  if (focused) gbFocus(host, focused);
}

/** Put the focus back on the control a redraw replaced (data-focus "details:<id>" or "play:<id>"), else on the
 * same row's Details. */
function gbFocus(host, key) {
  const find = (k) => [...host.querySelectorAll("[data-focus]")].find((n) => n.dataset.focus === k);
  const again = find(key) || find(key.replace(/^play:/, "details:"));
  if (again) again.focus({ preventScroll: true });
}

/** The answer: the words over it, its notes and one row a deck; no Play all. */
function gbBoard(view, a, words) {
  if (a.state === "no_catalogue") {
    return emptyBox("Popular decks aren't set up on this PC yet.",
      a.build_command ? el("pre", { class: "gb-command", text: a.build_command }) : null);
  }
  const size = a.sample?.size || 0;
  const rows = a.rows || [];
  return el("div", { class: "gb-board" },
    el("p", { class: "sub gb-intro", text: `Each deck against the same ${plural(size, `popular ${words} deck`)} ` +
      `(${GB_SOURCES[a.format] || GB_SOURCES.commander}). A figure is its average win rate against those decks only: ` +
      "not a rating. Rankings are separate." }),
    (a.notes || []).map((n) => el("p", { class: "gt-small gb-note", text: n })),
    rows.length ? el("ul", { class: "gb-rows", "aria-label": `${words} decks against popular decks` },
      rows.map((row) => gbRow(view, row)))
      : emptyBox(`No ${words} decks to test yet.`));
}

/** One deck: its name, figure and range, opponents and games, age, hardest opponent, an out-of-date state, its
 * run if one waits or plays, Details and Play. */
function gbRow(view, row) {
  const d = row.deck || {}, o = row.overall;
  const rate = o && o.rate != null ? gtRate(o.rate, o.low, o.high) : null;
  const facts = row.trial || d.trial ? [ptrNotOwnedChip()] : [];     // precon-trial.js: a precon trial (E3-S39)
  if (row.state === "unreadable") facts.push(el("p", { class: "gb-state", text: row.problem || "Forge can't read this list." }));
  else if (!rate && !row.before && !row.older) facts.push(el("p", { class: "gb-state", text: "Not tested against popular decks yet." }));
  if (rate) {
    facts.push(el("p", { class: "gb-meta" }, simNumbers(`${row.played} of ${row.of} opponents · ` +
      `${thousands(row.games || 0)} game${row.games === 1 ? "" : "s"}`)));
    const h = row.hardest;
    if (h && h.rate != null) facts.push(el("p", { class: "gb-meta gb-hardest" }, simNumbers(`Hardest: ${h.title} ${simPoints(h.rate)}%`)));
  }
  if (row.state === "partial") facts.push(status("warn", "Partly tested"));
  if (row.state === "stale_list") facts.push(gtBeforeLine(row));
  if (row.state === "stale_older") facts.push(gtOlderLine(row));
  for (const n of row.notes || []) facts.push(el("p", { class: "gt-small gb-note", text: n }));
  return el("li", { class: "gb-row", "data-deck": d.id, "data-state": row.state },
    el("div", { class: "gb-name" }, el("h3", { class: "gb-title", text: d.title }), facts),
    rate ? el("div", { class: "gb-score" },
      winRateFigure(rate, { what: "Win rate against popular decks", games: row.games || null, barred: true }),
      rangeBar(rate, { compact: true, decorative: true }), freshnessBadge(row.updated, { size: "row" })) : null,
    el("div", { class: "gb-actions" }, gbPlaying(row),
      el("a", { class: "btn", href: `${deckHref(d.id, "target")}&tab=matchups&part=gauntlet`, text: "Details",
        "aria-label": `Details: ${d.title}`, "data-focus": `details:${d.id}` }),
      gbPlayButton(view, row)));
}

/** A row's run waiting or playing, in words naming nobody. */
function gbPlaying(row) {
  const p = row.playing;
  if (!p) return null;
  if (!p.standard) return el("span", { class: "gb-playing", text: "Playing another sample" });
  return el("span", { class: "gb-playing" }, p.status === "queued" ? "Waiting to play"
    : simNumbers(`Playing: ${thousands(p.done || 0)} of ${thousands(p.total || 0)} games`));
}

/** Play the standard sample, only when the viewer may start runs and nothing of this list waits or plays. */
function gbPlayButton(view, row) {
  if (row.playing || row.state === "unreadable" || !row.deck?.card_sha || !runGate().may) return null;
  return el("button", { type: "button", class: "btn", text: "Play", "aria-label": `Play ${row.deck.title} against popular decks`,
    "data-focus": `play:${row.deck.id}`, onclick: () => gbPlay(view, row) });
}

/** Ask first, then start the standard sample through the usual run endpoint, bound to the list on screen. */
async function gbPlay(view, row) {
  const profile = state.profile?.id, token = view.token;
  const choice = await ask(`Play ${shortTitle(row.deck.title)} against popular decks?`,
    [`${plural(row.of || 0, "popular deck")}, about 100 games each. Forge plays two runs at a time; others wait ` +
      "their turn. The deck's Testing tab says how long."],
    [{ value: "play", text: "Play", kind: "primary" }, { value: "cancel", text: "Cancel" }]);
  if (choice !== "play" || token !== routeToken || state.profile?.id !== profile || !runGate().may) return;
  try {
    await apiWrite("/api/gauntlet/run", { id: row.deck.id, version: "target", expected_card_sha: row.deck.card_sha });
    if (typeof syncRunsPill === "function") syncRunsPill(true);
  } catch (e) {
    if (token === routeToken && state.profile?.id === profile) toast(e.message || String(e));
  }
  if (token === routeToken && state.profile?.id === profile) gbRefresh(view, null, { force: true });
}
