/* The run activity (the UI review's WP12; P1's activity icon since E11-S30 slice 6, design/visual-design.md 4.9
and section 6 decision 3): while Forge plays a matchup, a field run or a test of a change on the PC, the shell's
#shell-status slot shows one small turning ring on every page, in a 44 px button named "Forge is playing: show
progress" (a still ring with a dot under prefers-reduced-motion), and the casual tab bar's Matchups tab an 8 px
dot. Nothing shows while nothing plays or waits. The
button opens the details: a popover under it from 1,000 px, a sheet below that (a bottom sheet on a phone). They
hold each run playing (A vs B, a progress ring, "game 37 of 200", about how long is left, Stop for a viewer the
server lets stop it, and a link to its page unless it's of a space the viewer can't see), the runs waiting, and a
link to Matchups. Stop asks first, as every Stop does (matchups-overview.js stopListedRun).

It asks GET /api/matchups?running=1 (only the runs, without reading a saved result) every RUNS_PILL_BUSY_MS
while a run plays and every RUNS_PILL_IDLE_MS while none does, and only while the page is visible: a hidden page
stops asking and asks at once when it's seen again. The Matchups pages hand it their own answers (noteRuns), so
it doesn't ask twice there. shell.js calls syncRunsPill on every route once a profile is chosen (open details
close on a new page), and stopRunsPill when the shell is hidden (the Who screen). Uses core.js (el, svgEl, add,
api, state, thousands, plural, mayStopRuns), matchups.js (runProgress, sideShort), matchups-overview.js
(stopListedRun) and editor.js (openSheet). Nothing here runs at load. */
"use strict";

const RUNS_PILL_BUSY_MS = 4000;         // how often it asks while a run plays
const RUNS_PILL_IDLE_MS = 45000;        // ... and while none does (to find runs started elsewhere)
const RUNS_PILL_FIRST_MS = 1500;        // a page's first ask waits this long, so the page's own reads go first
const RUNS_LAB_QUERY = "(min-width: 1000px)";   // the details are a popover here, a sheet below it
const runsPill = { timer: 0, request: null, running: [], listening: false, at: 0, profile: null,
  button: null, details: null, stopping: false };

/** Bring the activity up to date and keep it asking (shell.js, on every route; force: ask now, as after a Start).
 * Details left open on another page close. */
function syncRunsPill(force = false) {
  if (!state.profile) { stopRunsPill(); return; }
  if (!runsPill.listening) {
    document.addEventListener("visibilitychange", runsPillVisibility);
    runsPill.listening = true;
  }
  if (runsPill.profile !== state.profile.id) {          // another person: what they may see starts afresh
    clearTimeout(runsPill.timer);
    runsPill.timer = 0;
    if (runsPill.request && runsPill.request.abort) runsPill.request.abort();
    runsPill.request = null;
    runsPill.profile = state.profile.id;
    runsPill.running = [];
    runsPill.at = 0;
    closeRunDetails(false);
  }
  if (runsPill.details && runsPill.details.hash !== location.hash) closeRunDetails(false);
  drawRunsPill();
  if (force) askRunsPill();
  else if (!runsPill.request && Date.now() - runsPill.at > RUNS_PILL_BUSY_MS) {
    // Soon, not at once: the page's own reads go first.
    clearTimeout(runsPill.timer);
    runsPill.timer = setTimeout(askRunsPill, RUNS_PILL_FIRST_MS);
    if (runsPill.timer && runsPill.timer.unref) runsPill.timer.unref();
  } else if (!runsPill.timer && !runsPill.request) scheduleRunsPill();
}

/** Stop asking and hide the activity (the Who screen). */
function stopRunsPill() {
  clearTimeout(runsPill.timer);
  runsPill.timer = 0;
  if (runsPill.request && runsPill.request.abort) runsPill.request.abort();
  runsPill.request = null;
  runsPill.running = [];
  if (runsPill.listening) {
    document.removeEventListener("visibilitychange", runsPillVisibility);
    runsPill.listening = false;
  }
  drawRunsPill();
}

function runsPillVisibility() {
  if (document.visibilityState === "hidden") {
    clearTimeout(runsPill.timer);
    runsPill.timer = 0;
    if (runsPill.request && runsPill.request.abort) runsPill.request.abort();
  } else if (state.profile) {
    askRunsPill();
  }
}

function scheduleRunsPill() {
  clearTimeout(runsPill.timer);
  runsPill.timer = 0;
  if (!state.profile || document.visibilityState === "hidden") return;
  runsPill.timer = setTimeout(askRunsPill, runsPill.running.length ? RUNS_PILL_BUSY_MS : RUNS_PILL_IDLE_MS);
  if (runsPill.timer && runsPill.timer.unref) runsPill.timer.unref();     // (under Node, in the tests: never holds it open)
}

async function askRunsPill() {
  clearTimeout(runsPill.timer);
  runsPill.timer = 0;
  if (!state.profile || document.visibilityState === "hidden") return;
  const profile = state.profile.id;
  if (runsPill.request && runsPill.request.abort) runsPill.request.abort();
  const controller = typeof AbortController === "function" ? new AbortController() : {};
  runsPill.request = controller;
  try {
    const answer = await api("/api/matchups?running=1", { signal: controller.signal });
    if (runsPill.request !== controller || state.profile?.id !== profile) return;
    runsPill.request = null;
    noteRuns(answer.running);
  } catch (e) {
    if (runsPill.request !== controller || state.profile?.id !== profile) return;
    runsPill.request = null;                   // the PC isn't answering: it keeps what it showed, and asks again
    scheduleRunsPill();
  }
}

/** The runs waiting or playing (an /api/matchups answer's "running", from its own ask or a Matchups page's): draw
 * the activity and ask again in a while. */
function noteRuns(running) {
  runsPill.running = Array.isArray(running) ? running : [];
  runsPill.at = Date.now();
  drawRunsPill();
  if (!runsPill.request) scheduleRunsPill();
}

/** A run's name: "Boros Burn vs Dimir Control", or a field run's or test's title. */
function runsPillName(run) {
  return run.sides ? `${sideShort(run.sides[0])} vs ${sideShort(run.sides[1])}` : run.title || "a run of many matchups";
}

/** Show the activity icon while any run plays or waits (nothing otherwise), and bring open details up to date. */
function drawRunsPill() {
  const host = document.getElementById("shell-status");
  if (!host) return;
  const runs = state.profile ? runsPill.running : [];
  // The Matchups tab's 8 px dot (shell.css) while anything plays or waits; the icon's name says it in words.
  const tabbar = document.getElementById("tabbar");
  for (const link of tabbar ? tabbar.querySelectorAll("[data-route]") : []) {
    if (link.getAttribute("data-route") === "matchups") link.classList.toggle("has-run", runs.length > 0);
  }
  if (!runs.length) {
    closeRunDetails(false);
    host.replaceChildren();
    host.hidden = true;
    runsPill.button = null;
    return;
  }
  host.hidden = false;
  const playing = runs.some((r) => r.status === "running");
  let button = runsPill.button;
  if (!button || button.parentNode !== host) {
    button = el("button", { type: "button", class: "run-activity", "aria-expanded": "false", "aria-controls": "run-details",
      onclick: () => (runsPill.details ? closeRunDetails(true) : openRunDetails()) },
    el("span", { class: "activity-ring", "aria-hidden": "true" }));
    runsPill.button = button;
    host.replaceChildren(button);
  }
  const name = playing ? "Forge is playing: show progress" : "A Forge run is waiting: show progress";
  button.setAttribute("aria-label", name);
  button.setAttribute("title", name);
  button.setAttribute("class", `run-activity${playing ? "" : " is-waiting"}`);
  fillRunDetails();
}

/** The details' parts: each run playing, the runs waiting, and the way to Matchups. */
function runDetailsParts(runs) {
  const playing = runs.filter((r) => r.status === "running");
  const waiting = runs.filter((r) => r.status !== "running");
  const named = runs.length > 1;
  return [
    playing.map((run) => runEntry(run, named)),
    waiting.length ? el("section", { class: "run-waiting", "aria-label": "Waiting to play" },
      el("h3", { class: "run-waiting-head", text: playing.length ? "Waiting" : "Waiting to play" }),
      el("ul", { class: "run-waiting-list" }, waiting.map((run) => el("li", {},
        el("span", { class: "run-waiting-name", text: runsPillName(run) }),
        el("span", { class: "run-waiting-ahead", text: run.ahead > 0 ? `${plural(run.ahead, "run")} ahead` : "next" }),
        runStop(run, named))))) : null,
    el("p", { class: "run-details-foot" }, el("a", { class: "btn btn-quiet btn-inline", href: "#/matchups",
      "data-focus": "matchups", text: "Every run on Matchups", onclick: () => closeRunDetails(false) }))];
}

/** One run playing: "Forge playing: A vs B" (its status line), its progress ring and "game 37 of 200", about how
 * long is left (once a tenth of it has played, as the pair page says it), a link to its page and Stop. */
function runEntry(run, named) {
  const p = run.sides ? runProgress(run) : { done: run.done || 0, total: run.total || 0, approx: false };
  const share = p.total ? p.done / p.total : 0;
  const left = run.eta_s != null && p.total && p.done >= p.total / 10 ? runLeftWords(run.eta_s) : null;
  const total = `${p.approx ? "~" : ""}${thousands(p.total || 0)}`;
  return el("div", { class: "run-entry" },
    progressRing(share, `Games played: ${thousands(p.done)} of ${total}`),
    el("div", { class: "run-entry-words" },
      el("p", { class: "run-summary", role: "status" }, el("b", { text: "Forge playing: " }), runsPillName(run)),
      el("p", { class: "run-count" }, "game ", el("span", { class: "sim-num", text: thousands(p.done) }), " of ",
        el("span", { class: "sim-num", text: total }), left ? ` · about ${left} left` : null)),
    el("div", { class: "run-entry-actions" },
      !run.hidden && run.link ? el("a", { class: "btn btn-quiet btn-inline", href: run.link, text: "Open it",
        "data-focus": `${run.key}:open`, onclick: () => closeRunDetails(false) }) : null,
      runStop(run, named)));
}

/** A run's Stop, for a viewer the server lets stop it (mayStopRuns: its may_stop), or null. Named "Stop the Forge
 * run" (with the run's name when the details list more than one). While its question is open the details don't
 * redraw, so the answer still finds its button. */
function runStop(run, named) {
  if (!run.key || !["queued", "running"].includes(run.status) || !mayStopRuns(run)) return null;
  const button = el("button", { type: "button", class: "btn run-stop", "data-focus": `${run.key}:stop`,
    "aria-label": named ? `Stop the Forge run: ${runsPillName(run)}` : "Stop the Forge run",
    onclick: async () => {
      runsPill.stopping = true;
      try { await stopListedRun(run, button); } finally { runsPill.stopping = false; fillRunDetails(); }
    } },
  el("span", { class: "run-stop-glyph", "aria-hidden": "true" }), "Stop");
  return button;
}

/** About how long is left, from forge's estimate in seconds: "under a minute", "6 min", "1 h 20 min". */
function runLeftWords(seconds) {
  const m = Math.round(seconds / 60);
  if (m < 1) return "under a minute";
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`;
}

/** A progress ring (role="progressbar"): its track in --ring-track and the share played as a teal arc. */
function progressRing(share, label) {
  const n = Math.round(Math.max(0, Math.min(1, share || 0)) * 100);
  return el("span", { class: "run-ring", role: "progressbar", "aria-label": label, "aria-valuemin": 0,
    "aria-valuemax": 100, "aria-valuenow": n },
  svgEl("svg", { viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false" },
    svgEl("circle", { class: "run-ring-track", cx: 12, cy: 12, r: 9.5 }),
    svgEl("circle", { class: "run-ring-arc", cx: 12, cy: 12, r: 9.5, pathLength: 100, "stroke-dasharray": `${n} 100` })));
}

/** Open the details: a popover under the icon from 1,000 px, which closes on Escape, a click elsewhere or a new
 * page (not on a click in Stop's question over it, nor on the Escape that closes that question); below that a
 * sheet. */
function openRunDetails() {
  const button = runsPill.button;
  if (!button || runsPill.details) return;
  const lab = typeof window.matchMedia === "function" && window.matchMedia(RUNS_LAB_QUERY).matches;
  button.setAttribute("aria-expanded", "true");
  if (lab) {
    const body = el("div", { class: "run-details-body" });
    const node = el("section", { class: "run-details run-popover", id: "run-details", "aria-label": "Forge runs" }, body);
    button.parentNode.append(node);
    const keys = (e) => {
      if (e.key !== "Escape" || e.defaultPrevented || runsPill.stopping) return;
      if (e.target && e.target.closest && e.target.closest("dialog")) return;
      e.preventDefault();
      closeRunDetails(true);
    };
    const outside = (e) => {
      const target = e.target;
      if (node.contains(target) || button.contains(target)) return;
      if (target && target.closest && target.closest("dialog")) return;
      closeRunDetails(false);
    };
    document.addEventListener("keydown", keys);
    document.addEventListener("pointerdown", outside, true);
    runsPill.details = { body, hash: location.hash, close() {
      node.remove();
      document.removeEventListener("keydown", keys);
      document.removeEventListener("pointerdown", outside, true);
    } };
  } else {
    const sheet = openSheet("Forge runs", { onClose: () => {
      if (runsPill.details && runsPill.details.sheet === sheet) { runsPill.details = null; detailsClosed(false); }
    } });
    sheet.dialog.setAttribute("id", "run-details");
    sheet.dialog.setAttribute("class", `${sheet.dialog.getAttribute("class")} run-details run-sheet`);
    runsPill.details = { body: sheet.body, sheet, hash: location.hash, close() { sheet.close(); } };
  }
  fillRunDetails();
}

/** Put the runs into open details (not while a Stop's question is open); they close once nothing runs. A link or
 * button that had the focus gets it back in the new parts (each has a data-focus), or the first one does when
 * it's gone, so a keyboard user isn't thrown out on every ask. */
function fillRunDetails() {
  const details = runsPill.details;
  if (!details || runsPill.stopping) return;
  const runs = state.profile ? runsPill.running : [];
  // The Matchups tab's 8 px dot (shell.css) while anything plays or waits; the icon's name says it in words.
  const tabbar = document.getElementById("tabbar");
  for (const link of tabbar ? tabbar.querySelectorAll("[data-route]") : []) {
    if (link.getAttribute("data-route") === "matchups") link.classList.toggle("has-run", runs.length > 0);
  }
  if (!runs.length) { closeRunDetails(false); return; }
  const focused = document.activeElement;
  const held = focused && focused !== details.body && details.body.contains(focused)
    ? focused.getAttribute("data-focus") || "" : null;
  details.body.replaceChildren();
  add(details.body, runDetailsParts(runs));
  if (held == null) return;
  const parts = [...details.body.querySelectorAll("[data-focus]")];
  const again = parts.find((n) => n.getAttribute("data-focus") === held) || parts[0];
  if (again) again.focus({ preventScroll: true });
}

/** Close the details (refocus: give the icon the focus back, as after Escape). */
function closeRunDetails(refocus) {
  const details = runsPill.details;
  if (!details) return;
  runsPill.details = null;
  details.close();
  detailsClosed(refocus);
}

function detailsClosed(refocus) {
  const button = runsPill.button;
  if (!button) return;
  button.setAttribute("aria-expanded", "false");
  if (refocus && button.isConnected) button.focus({ preventScroll: true });
}
